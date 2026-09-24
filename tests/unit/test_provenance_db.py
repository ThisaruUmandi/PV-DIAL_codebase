import datetime as dt

import pytest

from pvdials.provenance.db import (
    create_schema,
    get_engine,
    is_reachable,
    provenance_records,
    stage_output_values,
)

engine = get_engine()

pytestmark = pytest.mark.skipif(
    not is_reachable(engine),
    reason="No local Postgres reachable (DATABASE_URL not set or the service isn't running).",
)


@pytest.fixture(autouse=True)
def _clean_schema():
    create_schema(engine)
    with engine.begin() as conn:
        conn.execute(stage_output_values.delete())
        conn.execute(provenance_records.delete())
    yield


def test_stage_output_values_round_trips_jsonb():
    payload = {"dni": [1.0, 2.0, 3.0], "dhi": [0.1, 0.2, 0.3]}
    with engine.begin() as conn:
        conn.execute(
            stage_output_values.insert().values(content_hash="abc123", payload=payload)
        )
        row = conn.execute(
            stage_output_values.select().where(stage_output_values.c.content_hash == "abc123")
        ).one()

    assert row.content_hash == "abc123"
    assert row.payload == payload
    assert isinstance(row.first_seen_at, dt.datetime)


def test_provenance_records_round_trips_jsonb():
    document = {"prefix": {"default": "https://pvdial.example.org/ns#"}, "bundle": {"original": {}}}
    with engine.begin() as conn:
        conn.execute(
            provenance_records.insert().values(
                id="doc-hash-1", execution_set="original", config_label="A", document=document
            )
        )
        row = conn.execute(
            provenance_records.select().where(provenance_records.c.id == "doc-hash-1")
        ).one()

    assert row.execution_set == "original"
    assert row.config_label == "A"
    assert row.document == document


def test_content_hash_is_the_primary_key():
    with engine.begin() as conn:
        conn.execute(stage_output_values.insert().values(content_hash="dupe", payload={"a": 1}))

    with pytest.raises(Exception), engine.begin() as conn:  # noqa: B017 - IntegrityError, driver-specific
        conn.execute(stage_output_values.insert().values(content_hash="dupe", payload={"a": 2}))
