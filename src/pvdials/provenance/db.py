"""Connection and schema for the provenance store (KT §11: PostgreSQL/Neon).

Local development runs against a local Postgres (installed via Homebrew, no
Docker in this environment) with the exact same JSONB/GIN behaviour a real
Neon connection would have — switching to Neon later is a DATABASE_URL
change only, no query rewrites.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from sqlalchemy import Column, DateTime, MetaData, String, Table, create_engine, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine

load_dotenv()

# Local dev default: Homebrew Postgres uses peer/trust auth for the OS user,
# no password. Overridden by DATABASE_URL (.env) for anything else, Neon included.
DEFAULT_DATABASE_URL = "postgresql+psycopg2://localhost:5432/pvdials_dev"

metadata = MetaData()

# Keyed by content hash, not by (config, stage): values shared upstream of the
# first differing model (most of the eventual derived configurations, per N19)
# are stored once regardless of how many configs produced them.
stage_output_values = Table(
    "stage_output_values",
    metadata,
    Column("content_hash", String, primary_key=True),
    Column("payload", JSONB, nullable=False),
    Column("first_seen_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# One row per run_pipeline() call (B5: written after, not during). Keyed by the
# document's own content hash for the same de-duplication reason as above.
provenance_records = Table(
    "provenance_records",
    metadata,
    Column("id", String, primary_key=True),
    Column("execution_set", String, nullable=False),
    Column("config_label", String, nullable=False),
    Column("document", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


def get_engine(database_url: str | None = None) -> Engine:
    """A SQLAlchemy engine for the provenance store."""
    url = database_url or os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    return create_engine(url)


def create_schema(engine: Engine) -> None:
    """Create both tables if they don't already exist."""
    metadata.create_all(engine)


def is_reachable(engine: Engine) -> bool:
    """True if the database can actually be connected to right now.

    Used by tests to skip gracefully rather than fail when no local Postgres
    is running — the rest of the suite stays green in any environment.
    """
    try:
        with engine.connect():
            return True
    except Exception:  # noqa: BLE001 - reachability probe, any failure means "not reachable"
        return False
