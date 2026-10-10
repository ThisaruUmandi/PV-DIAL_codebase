"""The recorder (KT §11, Step 7.3). Writes after a completed run_pipeline() call.

B5, write-timing axis: called immediately after run_pipeline() returns, not
from inside it — run_pipeline() and every adapter stay untouched. See
model.py's module docstring and the plan for the full reasoning.
"""

from __future__ import annotations

import hashlib
import json

from psycopg.types.json import Jsonb

from pvdials.physics.pipeline import PipelineResult, SharedInputs
from pvdials.provenance.db import run
from pvdials.provenance.model import build_document, hash_dataframe
from pvdials.types import ExecutionSet, PipelineConfig

_STAGES = ("decomposition", "transposition", "temperature", "dc", "ac")


def record(
    config: PipelineConfig,
    shared: SharedInputs,
    result: PipelineResult,
    execution_set: str = ExecutionSet.ORIGINAL.value,
) -> str:
    """Record one completed run_pipeline() call. Returns the document's id.

    execution_set: one of ExecutionSet's values -- ORIGINAL (default, a
    user-configured pipeline), DERIVED (Phase 3's coalition runs) or REEXEC
    (O4's guided re-execution attempts, including discarded retries). Every
    caller now passes this explicitly where it isn't the default, so the
    three execution sets are distinguishable in the record (KT §4, N10;
    closes the O2 gap where Phase 3's derived runs weren't recorded at all).

    Each stage output is content-hash-deduplicated into stage_output_values
    (Postgres's own ON CONFLICT DO NOTHING, not a manual check-then-insert) —
    this is where the saving described for the eventual derived configurations
    (N19) actually happens. The PROV document itself is deduplicated the same
    way, keyed by its own content hash.
    """
    # The weather input, hashed and stored the same way as a stage output —
    # replay (7.4) needs to reconstruct SharedInputs from the record alone,
    # in a fresh process, so the input itself must be recoverable too, not
    # just described by rows/start/end.
    values: dict[str, dict] = {}
    weather_hash, weather_payload = hash_dataframe(shared.weather)
    values[weather_hash] = weather_payload
    for stage_name in _STAGES:
        stage_result = getattr(result.outputs, stage_name)
        content_hash, payload = hash_dataframe(stage_result.outputs)
        values.setdefault(content_hash, payload)

    document = build_document(config, shared, result, execution_set)
    document_json = document.serialize(format="json")
    document_id = hashlib.sha256(document_json.encode("utf-8")).hexdigest()

    def write(conn) -> None:
        # Each payload is large (about 0.5 MB) and the database is a network round trip away, so a
        # value it already holds is not sent again: ask which of these hashes exist (one query),
        # send only the rest (one batch). ON CONFLICT DO NOTHING stays as the guard against two
        # writers racing; the stored rows are the same either way.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT content_hash FROM stage_output_values WHERE content_hash = ANY(%s)",
                (list(values),),
            )
            held = {row[0] for row in cur.fetchall()}
            missing = [(h, Jsonb(payload)) for h, payload in values.items() if h not in held]
            if missing:
                cur.executemany(
                    "INSERT INTO stage_output_values (content_hash, payload) VALUES (%s, %s) "
                    "ON CONFLICT (content_hash) DO NOTHING",
                    missing,
                )
            cur.execute(
                "INSERT INTO provenance_records (id, execution_set, config_label, document) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                (document_id, execution_set, config.label, Jsonb(json.loads(document_json))),
            )

    run(write)

    return document_id






