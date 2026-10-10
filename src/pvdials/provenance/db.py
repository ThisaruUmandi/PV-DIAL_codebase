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

import os
import time
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import Connection

load_dotenv()

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

# Local dev default: Homebrew Postgres uses peer/trust auth for the OS user,
# no password. Overridden by DATABASE_URL (.env) for anything else, Neon included.
DEFAULT_DATABASE_URL = "postgresql://localhost:5432/pvdials_dev"

CONNECT_TIMEOUT_SECONDS = 10
RETRY_DELAY_SECONDS = 1.0


def get_connection(database_url: str | None = None) -> Connection:
    """A psycopg connection to the provenance store."""
    url = database_url or os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    # SQLAlchemy-style URLs ("postgresql+psycopg2://...") may still be in an
    # old .env; psycopg takes a plain "postgresql://" URL.
    url = url.replace("postgresql+psycopg2://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )
    # Neon scales idle computes to zero, so the first connection after a quiet
    # spell can time out or be refused while it wakes. One short retry covers it.
    kwargs = {} if "connect_timeout" in url else {"connect_timeout": CONNECT_TIMEOUT_SECONDS}
    try:
        return psycopg.connect(url, **kwargs)
    except psycopg.OperationalError:
        time.sleep(RETRY_DELAY_SECONDS)
        return psycopg.connect(url, **kwargs)


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
        with get_connection(database_url):
            return True
    except Exception:  # noqa: BLE001 - reachability probe, any failure means "not reachable"
        return False
