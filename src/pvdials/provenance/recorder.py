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
from pvdials.provenance.db import get_connection
from pvdials.provenance.model import build_document, hash_dataframe
from pvdials.types import PipelineConfig

# Hardcoded for now, consistent with build_document's bundle name — nothing
# else exists yet (derived/reexec sets are Steps 9/10). One open TODO, not two.
EXECUTION_SET = "original"

_STAGES = ("decomposition", "transposition", "temperature", "dc", "ac")


def record(config: PipelineConfig, shared: SharedInputs, result: PipelineResult) -> str:
    """Record one completed run_pipeline() call. Returns the document's id.

    Each stage output is content-hash-deduplicated into stage_output_values
    (Postgres's own ON CONFLICT DO NOTHING, not a manual check-then-insert) —
    this is where the saving described for the eventual derived configurations
    (N19) actually happens. The PROV document itself is deduplicated the same
    way, keyed by its own content hash.
    """
    with get_connection() as conn, conn.cursor() as cur:
        # The weather input, hashed and stored the same way as a stage output —
        # replay (7.4) needs to reconstruct SharedInputs from the record alone,
        # in a fresh process, so the input itself must be recoverable too, not
        # just described by rows/start/end.
        weather_hash, weather_payload = hash_dataframe(shared.weather)
        cur.execute(
            "INSERT INTO stage_output_values (content_hash, payload) VALUES (%s, %s) "
            "ON CONFLICT (content_hash) DO NOTHING",
            (weather_hash, Jsonb(weather_payload)),
        )

        for stage_name in _STAGES:
            stage_result = getattr(result.outputs, stage_name)
            content_hash, payload = hash_dataframe(stage_result.outputs)
            cur.execute(
                "INSERT INTO stage_output_values (content_hash, payload) VALUES (%s, %s) "
                "ON CONFLICT (content_hash) DO NOTHING",
                (content_hash, Jsonb(payload)),
            )

        document = build_document(config, shared, result)
        document_json = document.serialize(format="json")
        document_id = hashlib.sha256(document_json.encode("utf-8")).hexdigest()
        cur.execute(
            "INSERT INTO provenance_records (id, execution_set, config_label, document) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
            (document_id, EXECUTION_SET, config.label, Jsonb(json.loads(document_json))),
        )
        conn.commit()

    return document_id
