import datetime as dt

import pytest
from psycopg.types.json import Jsonb

from pvdials.provenance.db import get_connection, is_reachable, run_schema

pytestmark = pytest.mark.skipif(
    not is_reachable(),
    reason="No local Postgres reachable (DATABASE_URL not set or the service isn't running).",
)


@pytest.fixture(autouse=True)
def _clean_schema():
    with get_connection() as conn:
        run_schema(conn)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM stage_output_values")
            cur.execute("DELETE FROM provenance_records")
        conn.commit()
    yield


def test_stage_output_values_round_trips_jsonb():
    payload = {"dni": [1.0, 2.0, 3.0], "dhi": [0.1, 0.2, 0.3]}
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO stage_output_values (content_hash, payload) VALUES (%s, %s)",
            ("abc123", Jsonb(payload)),
        )
        conn.commit()
        cur.execute(
            "SELECT content_hash, payload, first_seen_at FROM stage_output_values "
            "WHERE content_hash = %s",
            ("abc123",),
        )
        row = cur.fetchone()

    assert row[0] == "abc123"
    assert row[1] == payload
    assert isinstance(row[2], dt.datetime)


def test_provenance_records_round_trips_jsonb():
    document = {"prefix": {"default": "https://pvdial.local/ns#"}, "bundle": {"original": {}}}
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO provenance_records (id, execution_set, config_label, document) "
            "VALUES (%s, %s, %s, %s)",
            ("doc-hash-1", "original", "A", Jsonb(document)),
        )
        conn.commit()
        cur.execute(
            "SELECT execution_set, config_label, document FROM provenance_records WHERE id = %s",
            ("doc-hash-1",),
        )
        row = cur.fetchone()

    assert row[0] == "original"
    assert row[1] == "A"
    assert row[2] == document


def test_content_hash_is_the_primary_key():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO stage_output_values (content_hash, payload) VALUES (%s, %s)",
            ("dupe", Jsonb({"a": 1})),
        )
        conn.commit()

    with pytest.raises(Exception), get_connection() as conn, conn.cursor() as cur:  # noqa: B017 - IntegrityError, driver-specific
        cur.execute(
            "INSERT INTO stage_output_values (content_hash, payload) VALUES (%s, %s)",
            ("dupe", Jsonb({"a": 2})),
        )
        conn.commit()


def test_index_exists_on_provenance_records():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'provenance_records'")
        indexes = {row[0] for row in cur.fetchall()}

    assert "provenance_records_execution_set_config_label_idx" in indexes
