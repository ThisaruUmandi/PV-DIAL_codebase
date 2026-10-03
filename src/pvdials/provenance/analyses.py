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

import uuid
from typing import Any

import pandas as pd
from psycopg.types.json import Jsonb

from pvdials.provenance.db import get_connection

# Shown wherever a part of a saved analysis was written before that part existed
# (e.g. rows saved before tau and run_info were stored): a missing part is
# reported, never an exception and never a silent blank.
NOT_RECORDED = "not recorded for this analysis"


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
    run_info: Any | None = None,
) -> None:
    """Upsert one analysis row. A plain upsert, not a partial update: pass
    along everything computed so far at each call (including from earlier
    steps), not just what's new since the last save.

    pipelines: per-pipeline descriptive stage-output summaries (report.py's
    stage_summaries_to_dict output) -- saved here (not just to results.json)
    so a saved analysis can be reopened read-only via load_analysis() without
    recomputing anything.

    run_info: per-run facts that are not results (checks per pipeline,
    validation tiers, offset report, start/finish times, pvlib version), so a
    reopened analysis can show them without a live run.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO analyses (
                id, name, status, inputs, phase1, phase2, phase3, reexec, pipelines, run_info
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                status = EXCLUDED.status,
                inputs = EXCLUDED.inputs,
                phase1 = EXCLUDED.phase1,
                phase2 = EXCLUDED.phase2,
                phase3 = EXCLUDED.phase3,
                reexec = EXCLUDED.reexec,
                pipelines = EXCLUDED.pipelines,
                run_info = EXCLUDED.run_info,
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
                Jsonb(run_info) if run_info is not None else None,
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
    "pipelines", "run_info",
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


def recorded(analysis: dict[str, Any], section: str, *keys: str) -> Any:
    """analysis[section][keys...], or NOT_RECORDED if any step of the path is
    absent or null -- how a row saved before tau / run_info / weather details
    were stored is read without failing.
    """
    value: Any = analysis.get(section)
    for key in keys:
        if not isinstance(value, dict) or value.get(key) is None:
            return NOT_RECORDED
        value = value[key]
    return NOT_RECORDED if value is None else value


_STATUS_FILTERS = {"complete": "a.status = 'done'", "in_progress": "a.status <> 'done'"}
_ORDERS = {
    "newest": "a.created_at DESC, a.id",
    "oldest": "a.created_at ASC, a.id",
    "name": "lower(a.name) ASC, a.created_at DESC",
}
_PAIR_ORDER = ("A-B", "A-C", "B-C")


def list_analyses_summary(
    search: str | None = None, status: str | None = None, order: str = "newest"
) -> list[dict[str, Any]]:
    """Rows for Past analyses / Home: name, weather file, status, date and the
    Phase 1 outcome per pair (fixed A-B, A-C, B-C order). Orderable by date
    or name only -- never by disagreement; any other `order` is refused.

    status: None (all), "complete" or "in_progress". search matches the
    analysis name or the weather file name (case-insensitive).
    """
    if order not in _ORDERS:
        raise ValueError(f"order must be one of {sorted(_ORDERS)}")
    if status is not None and status not in _STATUS_FILTERS:
        raise ValueError(f"status must be one of {sorted(_STATUS_FILTERS)} or None")

    where, params = [], []
    if status is not None:
        where.append(_STATUS_FILTERS[status])
    if search:
        where.append("(a.name ILIKE %s OR a.inputs->>'weather_file' ILIKE %s)")
        params += [f"%{search}%", f"%{search}%"]
    sql = (
        "SELECT a.id, a.name, a.created_at, a.updated_at, a.status, "
        "a.inputs->>'weather_file', a.phase1 FROM analyses a"
        + (" WHERE " + " AND ".join(where) if where else "")
        + " ORDER BY " + _ORDERS[order]
    )
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    summaries = []
    for analysis_id, name, created_at, updated_at, row_status, weather_file, phase1 in rows:
        outcomes: dict[str, Any] = {}
        for pair in _PAIR_ORDER:
            entry = (phase1 or {}).get(pair)
            if entry is None:
                outcomes[pair] = None
            elif entry.get("status") == "ran":
                outcomes[pair] = entry["outcome"]
            else:
                outcomes[pair] = "not computable"
        summaries.append(
            {
                "id": analysis_id,
                "name": name,
                "created_at": created_at,
                "updated_at": updated_at,
                "status": row_status,
                "weather_file": weather_file.rsplit("/", 1)[-1] if weather_file else NOT_RECORDED,
                "phase1_outcomes": outcomes,
            }
        )
    return summaries


def duplicate_analysis(analysis_id: str, new_id: str | None = None) -> str:
    """A new analysis with the same inputs and nothing else: new id, status
    'started', no results, no provenance links. The saved original is never
    touched. Returns the new id.
    """
    source = load_analysis(analysis_id)
    if source is None:
        raise ValueError(f"No saved analysis with id {analysis_id!r}.")
    new_id = new_id or uuid.uuid4().hex
    save_analysis(new_id, f"{source['name']} (copy)", "started", source["inputs"])
    return new_id


_STAGE_NAMES = ("decomposition", "transposition", "temperature", "dc", "ac")


def load_stage_series(
    analysis_id: str, label: str, execution_set: str = "original"
) -> dict[str, pd.DataFrame] | None:
    """The hourly stage outputs of one pipeline of a saved analysis, rebuilt
    from provenance: analysis_records -> provenance_records (config_label) ->
    each stage entity's content_hash -> stage_output_values. Nothing is
    copied into `analyses`. None if the analysis has no such record. Columns
    come back in name order (JSONB does not keep key order): use them by name.
    """
    from pvdials.provenance.model import unwrap_value
    from pvdials.provenance.replay import dataframe_from_payload

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT pr.document FROM provenance_records pr "
            "JOIN analysis_records ar ON ar.record_id = pr.id "
            "WHERE ar.analysis_id = %s AND pr.execution_set = %s AND pr.config_label = %s",
            (analysis_id, execution_set, label),
        )
        row = cur.fetchone()
        if row is None:
            return None
        bundle = next(iter(row[0]["bundle"].values()))
        series: dict[str, pd.DataFrame] = {}
        for stage in _STAGE_NAMES:
            content_hash = unwrap_value(bundle["entity"][stage]["content_hash"])
            cur.execute(
                "SELECT payload FROM stage_output_values WHERE content_hash = %s", (content_hash,)
            )
            payload = cur.fetchone()
            if payload is None:
                return None
            series[stage] = dataframe_from_payload(payload[0])
    return series
