"""Connection and schema for the provenance store (KT §11: PostgreSQL/Neon).

Plain psycopg (v3), no ORM: two flat, fixed tables don't need a query-builder
layer, and every statement stays literal enough to quote directly in the
dissertation appendix. schema.sql holds the actual DDL, version-controlled.

Local development runs against a local Postgres (installed via Homebrew, no
Docker in this environment) with the exact same JSONB/GIN behaviour a real
Neon connection would have — switching to Neon later is a DATABASE_URL
change only, no query rewrites.
"""

from __future__ import annotations

import atexit
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import psycopg
from dotenv import load_dotenv
from psycopg import Connection
from psycopg_pool import ConnectionPool

T = TypeVar("T")

load_dotenv()

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

# Local dev default: Homebrew Postgres uses peer/trust auth for the OS user,
# no password. Overridden by DATABASE_URL (.env) for anything else, Neon included.
DEFAULT_DATABASE_URL = "postgresql://localhost:5432/pvdials_dev"

CONNECT_TIMEOUT_SECONDS = 10
RETRY_DELAY_SECONDS = 1.0

# The pool: small, because one analysis is one user. A connection used within the last
# CHECK_AFTER_IDLE_SECONDS is trusted as it is; one that has sat longer is tested (one round
# trip) when it is taken, because Neon closes idle connections and suspends an idle compute.
POOL_MIN_SIZE = 1
POOL_MAX_SIZE = 4
POOL_MAX_IDLE_SECONDS = 120  # connections above POOL_MIN_SIZE are closed after this long unused
POOL_MAX_LIFETIME_SECONDS = 1800  # every connection is replaced after this long
POOL_WAIT_SECONDS = 30  # how long a caller waits for a free connection (or a waking compute)
CHECK_AFTER_IDLE_SECONDS = 15.0

# prepare_threshold=None: never auto-prepare statements. psycopg prepares a statement after five
# identical executions, which a reused connection now reaches; a pooler in transaction mode (Neon's
# -pooler host) does not keep prepared statements, so it would fail with "prepared statement does
# not exist". It costs nothing here: every statement is run only once or a few times per call.
_CONNECT_KWARGS = {"prepare_threshold": None, "connect_timeout": CONNECT_TIMEOUT_SECONDS}


def _resolve_url(database_url: str | None = None) -> str:
    url = database_url or os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    # SQLAlchemy-style URLs ("postgresql+psycopg2://...") may still be in an
    # old .env; psycopg takes a plain "postgresql://" URL.
    return url.replace("postgresql+psycopg2://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )


def get_connection(database_url: str | None = None) -> Connection:
    """A new, unpooled psycopg connection to the provenance store. The caller closes it (`with`
    does). The package itself uses run() below; this stays for scripts, tests and the replay worker."""
    url = _resolve_url(database_url)
    # Neon scales idle computes to zero, so the first connection after a quiet
    # spell can time out or be refused while it wakes. One short retry covers it.
    kwargs = {k: v for k, v in _CONNECT_KWARGS.items() if k != "connect_timeout" or "connect_timeout" not in url}
    try:
        return psycopg.connect(url, **kwargs)
    except psycopg.OperationalError:
        time.sleep(RETRY_DELAY_SECONDS)
        return psycopg.connect(url, **kwargs)


# --- The pool --------------------------------------------------------------------------------------

_pool: ConnectionPool | None = None
_pool_url: str | None = None
_pool_lock = threading.Lock()


def _stamp(conn: Connection) -> None:
    conn._pv_last_used = time.monotonic()  # type: ignore[attr-defined]


def _check(conn: Connection) -> None:
    """Checked when a connection is taken from the pool: raises if it has dropped, and the pool then
    discards it and hands out another. A connection used moments ago is not tested again."""
    if time.monotonic() - getattr(conn, "_pv_last_used", 0.0) >= CHECK_AFTER_IDLE_SECONDS:
        ConnectionPool.check_connection(conn)


def _pool_for(url: str) -> ConnectionPool:
    """The shared pool for this URL (made on first use; a different URL, as the tests set, gets a new one)."""
    global _pool, _pool_url
    with _pool_lock:
        if _pool is None or _pool_url != url:
            if _pool is not None:
                _pool.close()
                _pool, _pool_url = None, None
            pool = ConnectionPool(
                url,
                min_size=POOL_MIN_SIZE,
                max_size=POOL_MAX_SIZE,
                max_idle=POOL_MAX_IDLE_SECONDS,
                max_lifetime=POOL_MAX_LIFETIME_SECONDS,
                timeout=POOL_WAIT_SECONDS,
                kwargs=dict(_CONNECT_KWARGS),
                configure=_stamp,
                check=_check,
                open=False,
            )
            # Wait for the first connection before any request: a request that arrives while it is
            # still being made queues, and the pool answers a queued request by opening a second one.
            # A pool that cannot connect is not kept (the caller sees the failure, the next call tries again).
            try:
                pool.open(wait=True, timeout=2 * CONNECT_TIMEOUT_SECONDS)
            except Exception:
                pool.close()
                raise
            _pool = pool
            _pool_url = url
        return _pool


def close_pool() -> None:
    """Close the shared pool (it is made again on next use)."""
    global _pool, _pool_url
    with _pool_lock:
        if _pool is not None:
            _pool.close()
        _pool, _pool_url = None, None


atexit.register(close_pool)


def run(work: Callable[[Connection], T], database_url: str | None = None) -> T:
    """Run work(conn) in one transaction on a pooled connection and commit; return its result.

    work does its statements and never commits itself. If the connection turns out to have dropped
    while work runs (before the commit), nothing has been saved: work is run again, once, on a fresh
    connection. A failure at the commit itself is never retried -- whether it was saved is then
    unknown -- and neither is a failure on a connection that is still up.
    """
    pool = _pool_for(_resolve_url(database_url))
    for attempt in (1, 2):
        conn: Connection | None = None
        committing = False
        try:
            with pool.connection() as conn:
                result = work(conn)
                committing = True
                conn.commit()
                _stamp(conn)
                return result
        except (psycopg.OperationalError, psycopg.InterfaceError):
            # the pool has already discarded a dropped connection (and rolled it back, ignoring the failure)
            dropped = conn is not None and (conn.closed or conn.broken)
            if attempt == 1 and dropped and not committing:
                continue
            raise
    raise AssertionError("unreachable")  # pragma: no cover


def run_schema(conn: Connection) -> None:
    """Create both tables (and the index) if they don't already exist."""
    with conn.cursor() as cur:
        cur.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def is_reachable(database_url: str | None = None) -> bool:
    """True if the database can actually be connected to right now.

    Used by tests to skip gracefully rather than fail when no local Postgres
    is running — the rest of the suite stays green in any environment.
    """
    try:
        if database_url is None:
            run(lambda conn: conn.execute("SELECT 1"))  # a real round trip, through the pool
        else:
            with get_connection(database_url):
                pass
        return True
    except Exception:  # noqa: BLE001 - reachability probe, any failure means "not reachable"
        return False
