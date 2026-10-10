"""Hazard TI: a guard against ever running test/experiment code that wipes
provenance tables against the real development database, pvdials_dev.
Shared by tests/conftest.py (the whole test session) and
experiments/evaluation/step0_measure_phase3.py's main() (the other place
that deletes from provenance_records/stage_output_values) -- one guard,
not two copies that could drift apart.

No dependency on pytest or anything test-specific -- importable from either
side cheaply.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

from pvdials.provenance.db import DEFAULT_DATABASE_URL

FORBIDDEN_DATABASE_NAME = "pvdials_dev"
TEST_DATABASE_URL_DEFAULT = "postgresql://localhost:5432/pvdials_test"
# hostname is None for a URL with no host (Unix-socket / peer-auth local Postgres)
LOCAL_HOSTS = {None, "", "localhost", "127.0.0.1", "::1"}


def guard_not_dev_database(url: str, context: str) -> None:
    """Raises if url points at pvdials_dev, or at a remote host (e.g. Neon)
    that TEST_DATABASE_URL doesn't explicitly name. Fails loudly; does nothing
    else (no wipe, no connection attempt)."""
    host = urlparse(url).hostname
    if host not in LOCAL_HOSTS and url != os.environ.get("TEST_DATABASE_URL"):
        raise RuntimeError(
            f"Refusing to run {context} against remote host {host!r}! "
            f"This code wipes provenance tables, so a remote database (Neon) is "
            f"only allowed when TEST_DATABASE_URL is set to exactly that URL."
        )
    if FORBIDDEN_DATABASE_NAME in url:
        raise RuntimeError(
            f"Refusing to run {context} against {FORBIDDEN_DATABASE_NAME}! "
            f"Resolved database URL = {url!r}. This must not touch the "
            f"development database. Point TEST_DATABASE_URL (for the test "
            f"suite) or DATABASE_URL (for this script) at a different "
            f"database, e.g. {TEST_DATABASE_URL_DEFAULT}."
        )


def resolve_current_database_url() -> str:
    """Whatever get_connection() would actually resolve to right now -- the
    exact same os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL) db.py
    itself uses, so the guard reflects reality, not a re-derived assumption.
    """
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def resolve_test_database_url(env_var: str = "TEST_DATABASE_URL") -> str:
    """Test-session only: defaults to pvdials_test regardless of whatever
    .env's own DATABASE_URL currently holds (it's always set, to
    pvdials_dev, so "default when unset" would never trigger in practice --
    this reads a separate, test-specific knob instead).
    """
    return os.environ.get(env_var, TEST_DATABASE_URL_DEFAULT)
