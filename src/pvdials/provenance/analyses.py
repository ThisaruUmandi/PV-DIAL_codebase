"""Persistence for the orchestrator's analyses (analysis.py, `python -m pvdials`).

analyses: one row per end-to-end run, upserted after every step so a crash
mid-run leaves a queryable partial record (status = last step reached).
analysis_records: links an analysis to every provenance_records row it
touched. A separate link table, not a run-id column on provenance_records,
because that table's id is content-derived (sha256 of the document JSON):
two analyses with identical inputs produce the identical id, so a plain
owning-run column could only ever point to whichever analysis got there
first. The link table records every analysis that touched a given record,
dedup or not.
"""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from pvdials.provenance.db import get_connection


def save_analysis(
    analysis_id: str,
    name: str,
    status: str,
    inputs: dict[str, Any],
    phase1: Any | None = None,
    phase2: Any | None = None,
    phase3: Any | None = None,
    reexec: Any | None = None,
    pipelines: Any | None = None,
) -> None:
    """Upsert one analysis row. A plain upsert, not a partial update: pass
    along everything computed so far at each call (including from earlier
    steps), not just what's new since the last save.

    pipelines: per-pipeline descriptive stage-output summaries (report.py's
    stage_summaries_to_dict output) -- saved here (not just to results.json)
    so a saved analysis can be reopened read-only via load_analysis() without
    recomputing anything.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO analyses (id, name, status, inputs, phase1, phase2, phase3, reexec, pipelines)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                status = EXCLUDED.status,
                inputs = EXCLUDED.inputs,
                phase1 = EXCLUDED.phase1,
                phase2 = EXCLUDED.phase2,
                phase3 = EXCLUDED.phase3,
                reexec = EXCLUDED.reexec,
                pipelines = EXCLUDED.pipelines,
                updated_at = now()
            """,
            (
                analysis_id,
                name,
                status,
                Jsonb(inputs),
                Jsonb(phase1) if phase1 is not None else None,
                Jsonb(phase2) if phase2 is not None else None,
                Jsonb(phase3) if phase3 is not None else None,
                Jsonb(reexec) if reexec is not None else None,
                Jsonb(pipelines) if pipelines is not None else None,
            ),
        )
        conn.commit()


def link_record(analysis_id: str, record_id: str) -> None:
    """Record that this analysis touched this provenance_records row.
    Called once per real recorder.record() call the orchestrator makes,
    regardless of whether that call inserted a new row or matched an
    existing one via content-hash dedup.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO analysis_records (analysis_id, record_id) VALUES (%s, %s) "
            "ON CONFLICT DO NOTHING",
            (analysis_id, record_id),
        )
        conn.commit()


_ANALYSIS_FIELDS = (
    "id", "name", "created_at", "updated_at", "status", "inputs", "phase1", "phase2", "phase3", "reexec",
    "pipelines",
)


def load_analysis(analysis_id: str) -> dict[str, Any] | None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(_ANALYSIS_FIELDS)} FROM analyses WHERE id = %s",
            (analysis_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return dict(zip(_ANALYSIS_FIELDS, row, strict=True))


def list_analyses() -> list[dict[str, Any]]:
    fields = ("id", "name", "created_at", "updated_at", "status")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT {', '.join(fields)} FROM analyses ORDER BY created_at DESC")
        rows = cur.fetchall()
    return [dict(zip(fields, row, strict=True)) for row in rows]


def records_for_analysis(analysis_id: str) -> list[dict]:
    """Every provenance document this analysis touched (for provenance.json)."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT pr.document FROM provenance_records pr "
            "JOIN analysis_records ar ON ar.record_id = pr.id "
            "WHERE ar.analysis_id = %s",
            (analysis_id,),
        )
        rows = cur.fetchall()
    return [row[0] for row in rows]
