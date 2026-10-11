"""The three downloads of the Report, all made from the stored analysis only: the HTML report, a tidy results CSV
and the PROV-JSON export. Each is built once per analysis and saved time (downloads_for) and kept, so a rerun of
the page does not rebuild the files."""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC
from functools import lru_cache
from typing import Any

from app import analysis_logic, report_html, report_logic, run_logic, wording
from pvdials.provenance.analyses import load_analysis

CSV_COLUMNS = ("section", "pair", "pipeline", "stage", "quantity", "value", "unit", "text")
NOT_RECORDED = wording.RX_NOT_RECORDED


# --- File names ----------------------------------------------------------------------------------------------------------


def safe_stem(name: str, saved) -> str:
    """The analysis name made safe for a file system, then the saved date: only letters, digits, '.', '_' and '-'
    survive (anything else, spaces and < > & " / included, becomes '_'), never empty, never hidden, bounded."""
    ascii_name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode("ascii")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_name).strip("._-")
    stem = re.sub(r"_{2,}", "_", stem)[:60].strip("._-") or "analysis"
    return f"{stem}_{saved.astimezone(UTC):%Y-%m-%d}"


# --- Results CSV ------------------------------------------------------------------------------------------------------------


def _row(section, quantity, value=None, unit="", text="", pair="", pipeline="", stage="") -> dict[str, Any]:
    return {
        "section": section, "pair": pair, "pipeline": pipeline, "stage": stage, "quantity": quantity,
        "value": "" if value is None else value, "unit": unit, "text": text,
    }


_STAGE_UNIT = analysis_logic.STAGE_UNIT


def results_rows(report: report_logic.Report) -> list[dict[str, Any]]:
    """Every stored number of the analysis as one tidy row each. Units come from the one table; a part that was
    not run or not saved is a row whose text says so."""
    row = report.row
    inputs = row["inputs"] or {}
    rows: list[dict[str, Any]] = []
    offset = inputs.get("time_offset") or {}
    rows += [
        _row("run", "analysis_name", text=report.name),
        _row("run", "saved_time", text=report.saved.astimezone(UTC).isoformat()),
        _row("run", "weather_file", text=report.weather_name),
        _row("run", "time_offset", offset.get("value_h"), "h", offset.get("source", NOT_RECORDED)),
        _row("run", "pvlib_version", text=report.pvlib),
        _row("run", "tau", report.tau["value"], "unitless", str(report.tau["source"])),
    ]
    summary_fields = {
        "dni_kwh_m2": ("annual_dni", "kWh/m²"), "dhi_kwh_m2": ("annual_dhi", "kWh/m²"),
        "poa_global_kwh_m2": ("annual_poa_global", "kWh/m²"), "temp_cell_mean_c": ("daylight_mean_cell_temperature", "°C"),
        "temp_cell_max_c": ("daylight_max_cell_temperature", "°C"), "annual_energy_kwh": ("annual_energy", "kWh"),
    }
    summary = row.get("pipelines")
    if not summary:
        rows.append(_row("annual", "status", text=NOT_RECORDED))
    for label in report_logic.LABELS:
        for entry in (summary or {}).get(label, []):
            stage = entry["stage"].lower()
            for field, (quantity, unit) in summary_fields.items():
                if entry.get(field) is not None:
                    rows.append(_row("annual", quantity, entry[field], unit, entry["model"], pipeline=label, stage=stage))
    phase1 = row.get("phase1")
    if not phase1:
        rows.append(_row("phase1", "status", text=NOT_RECORDED))
    for key, entry in (phase1 or {}).items():
        if entry.get("status") != "ran":
            rows.append(_row("phase1", "status", text=entry.get("reason", ""), pair=key))
            continue
        rows.append(_row("phase1", "outcome", entry["outcome"], "", wording.OUTCOME_TEXT[entry["outcome"]], pair=key))
        rows.append(_row("phase1", "k", text=wording.STAGE_NAME[entry["k"].lower()] if entry["k"] else wording.K_NONE, pair=key))
        for metric in entry["metrics"]:
            stage = metric["stage"].lower()
            for quantity, unit in (("rmsd", _STAGE_UNIT[stage]), ("nrmsd", "unitless"), ("mad", _STAGE_UNIT[stage]),
                                   ("mbd", _STAGE_UNIT[stage]), ("systematic_share", "unitless"), ("n_pooled", "count")):
                rows.append(_row("phase1", quantity, metric[quantity], unit, pair=key, stage=stage))
    phase2 = row.get("phase2")
    if not phase2:
        rows.append(_row("phase2", "status", text=wording.RP_NOT_RUN))
    elif phase2.get("status") != "ran":
        rows.append(_row("phase2", "status", text=analysis_logic.phase2_blocked_reason(phase2) or phase2.get("reason", "")))
    else:
        for item in phase2["pair_nrmsd"]:
            for stage_value in item["nrmsd"]:
                rows.append(_row("phase2", "nrmsd", stage_value["value"], "unitless",
                                 pair=analysis_logic.pair_key(tuple(item["pair"])), stage=stage_value["stage"].lower()))
        for field, quantity in (("mean_nrmsd", "mean_nrmsd"), ("max_nrmsd", "max_nrmsd"), ("delta", "delta_mean_nrmsd")):
            for stage_value in phase2[field]:
                rows.append(_row("phase2", quantity, stage_value["value"], "unitless", stage=stage_value["stage"].lower()))
    phase3 = row.get("phase3") or {}
    for key in ("A-B", "A-C", "B-C"):
        entry = phase3.get(key)
        if entry is None:
            rows.append(_row("phase3", "status", text=wording.RP_NOT_RUN, pair=key))
        elif entry.get("status") != "ran":
            rows.append(_row("phase3", "status", text=entry.get("reason", ""), pair=key))
        else:
            rows.append(_row("phase3", "rmsd_ab", entry["rmsd_ab"], analysis_logic.PHI_UNIT, pair=key))
            for field, quantity, unit in (
                ("phi_ab", "phi_ab", analysis_logic.PHI_UNIT), ("phi_ba", "phi_ba", analysis_logic.PHI_UNIT),
                ("phi_final", "phi_final", analysis_logic.PHI_UNIT), ("share", "share", "unitless"),
                ("signed_phi", "signed_phi", analysis_logic.PHI_UNIT),
            ):
                for stage_value in entry.get(field) or []:
                    rows.append(_row("phase3", quantity, stage_value["value"], unit, pair=key, stage=stage_value["stage"].lower()))
    reexec = row.get("reexec")
    if not reexec:
        rows.append(_row("reexec", "status", text=wording.RP_NO_CHANGE))
    else:
        key = analysis_logic.pair_key(tuple(reexec["pair"]))
        for quantity in ("anchor", "candidate"):
            rows.append(_row("reexec", quantity, text=str(reexec.get(quantity) or NOT_RECORDED), pair=key))
        stage = reexec.get("stage")
        rows.append(_row("reexec", "stage", text=wording.STAGE_NAME[stage.lower()] if stage else NOT_RECORDED, pair=key))
        rows.append(_row("reexec", "config_label", text=reexec["config_label"], pair=key))
        value = reexec.get("annual_yield_kwh")
        rows.append(_row("reexec", "annual_yield", value, "kWh", "" if value is not None else wording.RX_YIELD_NONE, pair=key))
        saved = reexec.get("phase1")
        if saved and saved.get("status") == "ran":
            rows.append(_row("reexec", "outcome", saved["outcome"], "", wording.OUTCOME_TEXT[saved["outcome"]], pair=key))
            for metric in saved["metrics"]:
                rows.append(_row("reexec", "nrmsd_confirmed", metric["nrmsd"], "unitless", pair=key, stage=metric["stage"].lower()))
        else:
            rows.append(_row("reexec", "phase1", text=(saved or {}).get("reason", NOT_RECORDED), pair=key))
    return rows


def results_csv(report: report_logic.Report) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in results_rows(report):
        writer.writerow({**row, "value": repr(row["value"]) if isinstance(row["value"], float) else row["value"]})
    return buffer.getvalue().encode("utf-8")


# --- PROV-JSON ---------------------------------------------------------------------------------------------------------------


def provenance_json(report: report_logic.Report) -> bytes:
    """One JSON file holding one PROV-JSON document per linked record, each exactly as stored. (A record's id is
    the SHA-256 of prov's JSON text at the time it was written; the stored copy keeps the same content but not that
    text's key order, so the id is given beside the document, not recomputed from it.)"""
    payload = {
        "format": wording.RP_PROV_FORMAT,
        "analysis": {"name": report.name, "saved": report.saved.astimezone(UTC).isoformat()},
        "records": report.records,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


# --- All three, once ------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Downloads:
    stem: str
    html: bytes
    csv: bytes
    prov: bytes


@lru_cache(maxsize=8)
def downloads_for(analysis_id: str, saved_iso: str) -> Downloads:
    """Built once per analysis and saved time; a rerun of the page asks again and gets the same files."""
    report = report_logic.build_report(analysis_id)
    return Downloads(
        stem=safe_stem(report.name, report.saved),
        html=report_html.render_html(report).encode("utf-8"),
        csv=results_csv(report),
        prov=provenance_json(report),
    )


def saved_iso(analysis_id: str) -> str:
    """The analysis's saved time as text: the key under which its downloads are kept."""
    row = load_analysis(analysis_id)
    return row["updated_at"].isoformat() if row else ""


__all__ = ["CSV_COLUMNS", "Downloads", "downloads_for", "provenance_json", "results_csv", "results_rows", "run_logic", "safe_stem", "saved_iso"]
