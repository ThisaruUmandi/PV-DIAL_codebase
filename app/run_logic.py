"""Page 3 logic without Streamlit: run the saved analysis, read its stage outputs back,
and turn them into the chart, the summary table and the CSV the page shows.

The run uses the step functions of pvdials.analysis (never run_analysis) on the inputs that
pages 1 and 2 saved. Every number on the page comes from the series read back out of
stage_output_values, the same place a reopened analysis will read them from.
"""

from __future__ import annotations

import io
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd

from app import config_logic, wording
from pvdials import report
from pvdials.analysis import (
    AnalysisConfig,
    AnalysisError,
    HardwareResult,
    LoadResult,
    PipelineRunResult,
    SiteStepResult,
    build_run_info,
    step_hardware,
    step_load_and_validate,
    step_run_pipelines,
    step_site_and_offset,
)
from pvdials.config import ROOT, load_defaults
from pvdials.data.column_mapper import TimeOffset, detect_site_metadata
from pvdials.dla.metrics import Tau
from pvdials.provenance.analyses import load_analysis, load_stage_series, save_analysis
from pvdials.provenance.db import get_connection
from pvdials.provenance.model import unwrap_value

LABELS = config_logic.LABELS
STAGES = config_logic.STAGES
CHECK_ORDER = ("decomposition", "transposition", "temperature", "dc", "ac_not_exceeding_dc", "all_finite")

# the order a row's status moves through; a later status is never replaced by an earlier one
_STATUS_ORDER = (
    "started", "load_done", "site_done", "pipelines_configured", "pipelines_done",
    "phase1_done", "phase2_done", "phase3_done", "done",
)
_LATER_SECTIONS = ("phase1", "phase2", "phase3", "reexec")


# --- Rebuilding what the steps need from the saved inputs ----------------------------------------


def weather_path(inputs: dict) -> str:
    path = Path(inputs["weather_file"])
    return str(path if path.is_absolute() else ROOT / path)


def config_from_inputs(inputs: dict) -> AnalysisConfig:
    offset, site, hardware = inputs["time_offset"], inputs["site"], inputs["hardware"]
    return AnalysisConfig(
        name=inputs["name"],
        weather_file=weather_path(inputs),
        offset_value_h=float(offset["value_h"]),
        offset_reason=offset.get("reason") or "",
        tilt_deg=float(site["tilt_deg"]),
        azimuth_deg=float(site["azimuth_deg"]),
        albedo=site.get("albedo"),
        mounting_geometry=site.get("mounting_geometry"),
        mounting_construction=site.get("mounting_construction"),
        module_height_m=site.get("module_height_m"),
        module_name=hardware["module_name"],
        inverter_name=hardware["inverter_name"],
        modules_per_string=int(hardware["modules_per_string"]),
        strings_per_inverter=int(hardware["strings_per_inverter"]),
        pipelines={label: dict(inputs["pipelines"][label]) for label in LABELS},
        reexecution=None,
    )


def offset_from_inputs(inputs: dict) -> TimeOffset:
    stored = inputs["time_offset"]
    return TimeOffset(
        float(stored["value_h"]), stored.get("source") or "user_entered", None, stored.get("reason") or None
    )


def tau_from_inputs(inputs: dict) -> Tau:
    return Tau(float(inputs["tau"]["value"]), inputs["tau"]["source"])


def site_from_inputs(inputs: dict, load_result: LoadResult):
    """Coordinates as page 1 settled them: read from the file, with any value the user entered
    put back as theirs."""
    site = detect_site_metadata(load_result.uploaded.preamble, load_result.uploaded.table)
    saved = inputs.get("location") or {}
    sources = saved.get("sources") or {}
    for name in ("latitude", "longitude", "elevation"):
        value = saved.get(name)
        if value is None:
            continue
        if sources.get(name) == "From CSV" and site.values.get(name) == value:
            continue
        site.set_user_value(name, value)
    return site


# --- Running ---------------------------------------------------------------------------------------


@dataclass
class Live:
    """The objects step 4 needs to carry on from, kept in session state."""

    config: AnalysisConfig
    defaults: dict
    tau: Tau
    load_result: LoadResult
    site_result: SiteStepResult
    hardware: HardwareResult
    pipelines: PipelineRunResult


@dataclass
class RunState:
    """Everything page 3 shows. Built by a run (live objects kept for step 4) or by reopen(), which
    rebuilds it from what was stored; both give the same page."""

    analysis_id: str
    models: dict[str, dict[str, str]]
    run_info: dict[str, Any]
    pipelines_summary: dict[str, Any]
    record_ids: list[str]
    series: dict[str, dict[str, pd.DataFrame]]
    daylight: pd.Series
    annual_ac: dict[str, float]
    annual_dc: dict[str, float]
    provenance: dict[str, Any] = field(default_factory=dict)
    live: Live | None = None


def _save(analysis_id: str, name: str, status: str, inputs: dict, **sections) -> None:
    """save_analysis, but a row that has already moved on (Phase 1 onward) keeps its later
    results and its later status: running the pipelines again must not wipe them."""
    existing = load_analysis(analysis_id)
    if existing is not None:
        for key in _LATER_SECTIONS:
            if existing.get(key) is not None:
                sections.setdefault(key, existing[key])
        if existing["status"] in _STATUS_ORDER and _STATUS_ORDER.index(existing["status"]) > _STATUS_ORDER.index(status):
            status = existing["status"]
    save_analysis(analysis_id, name, status, inputs, **sections)


def run_pipelines(
    inputs: dict, analysis_id: str, progress: Callable[[str], None] | None = None
) -> RunState:
    """Steps 1 to 2 of the pipeline (read, site, hardware, run the three pipelines), saving as
    each finishes. Raises AnalysisError with a message for the page."""
    say = progress or (lambda _text: None)
    started_at = datetime.now(UTC).isoformat()
    started_clock = time.monotonic()
    defaults = load_defaults()
    tau = tau_from_inputs(inputs)
    config = config_from_inputs(inputs)
    if not Path(config.weather_file).exists():
        raise AnalysisError(wording.R_FILE_MISSING)

    say(wording.R_PROGRESS_LOAD)
    load_result = step_load_and_validate(config.weather_file)
    _save(analysis_id, config.name, "load_done", inputs)

    say(wording.R_PROGRESS_SITE)
    site_result = step_site_and_offset(
        load_result, config, defaults, tau,
        offset=offset_from_inputs(inputs), site=site_from_inputs(inputs, load_result),
    )
    _save(analysis_id, config.name, "site_done", inputs)

    say(wording.R_PROGRESS_HARDWARE)
    hardware = step_hardware(load_result, site_result, config, defaults)
    pipelines = step_run_pipelines(
        config, hardware, defaults, analysis_id,
        progress=lambda label: say(wording.R_PROGRESS_PIPELINE.format(label=label)),
    )

    say(wording.R_PROGRESS_SAVE)
    summaries = report.build_stage_summaries(pipelines, site_result.ctx.daylight)
    pipelines_dict = report.stage_summaries_to_dict(summaries)
    run_info = build_run_info(
        started_at, load_result, site_result, pipelines,
        finished_at=datetime.now(UTC).isoformat(),
        duration_s=round(time.monotonic() - started_clock, 3),
    )
    _save(analysis_id, config.name, "pipelines_done", inputs, pipelines=pipelines_dict, run_info=run_info)

    say(wording.R_PROGRESS_READ_BACK)
    series = read_back(analysis_id)
    live = Live(config, defaults, tau, load_result, site_result, hardware, pipelines)
    return _build_state(
        analysis_id, inputs, run_info, pipelines_dict, series, site_result.ctx.daylight, live, list(pipelines.record_ids)
    )


def _build_state(
    analysis_id: str, inputs: dict, run_info: dict, pipelines_dict: dict, series: dict,
    daylight: pd.Series, live: Live | None, record_ids: list[str],
) -> RunState:
    state = RunState(
        analysis_id=analysis_id,
        models={label: dict(inputs["pipelines"][label]) for label in LABELS},
        run_info=run_info,
        pipelines_summary=pipelines_dict,
        record_ids=record_ids,
        series=series,
        daylight=daylight,
        annual_ac={},
        annual_dc={},
        live=live,
    )
    state.annual_ac = {
        label: period_figure(series, daylight, label, "ac", QUANTITIES["ac"][0]) for label in LABELS
    }
    state.annual_dc = {
        label: period_figure(series, daylight, label, "dc", QUANTITIES["dc"][0]) for label in LABELS
    }
    state.provenance = provenance_summary(analysis_id)
    if not state.record_ids:
        state.record_ids = [record["id"] for record in state.provenance["records"]]
    docs = read_documents(analysis_id)
    state.provenance["lineage"] = {label: lineage(state, label, docs) for label in LABELS}
    return state


def reopen(analysis_id: str, inputs: dict | None = None) -> RunState:
    """Page 3 for an analysis that was run and stored. Reads only: the stored series, run_info,
    summary and records; the daylight mask is rebuilt from the stored site, offset and
    timestamps with the same step functions the run used. Nothing is written."""
    row = load_analysis(analysis_id)
    if row is None or row.get("run_info") is None or row.get("pipelines") is None:
        raise AnalysisError(wording.R_NOT_RUN_STORED)
    inputs = inputs or row["inputs"]
    config = config_from_inputs(inputs)
    if not Path(config.weather_file).exists():
        raise AnalysisError(wording.R_FILE_MISSING)
    load_result = step_load_and_validate(config.weather_file)
    site_result = step_site_and_offset(
        load_result, config, load_defaults(), tau_from_inputs(inputs),
        offset=offset_from_inputs(inputs), site=site_from_inputs(inputs, load_result),
    )
    series = read_back(analysis_id)
    return _build_state(
        analysis_id, inputs, row["run_info"], row["pipelines"], series, site_result.ctx.daylight, None, []
    )


def read_back(analysis_id: str) -> dict[str, dict[str, pd.DataFrame]]:
    """The stored stage outputs of A, B and C, through load_stage_series."""
    out = {}
    for label in LABELS:
        series = load_stage_series(analysis_id, label)
        if series is None:
            raise AnalysisError(wording.R_NOT_SAVED.format(label=label))
        out[label] = series
    return out


# --- What the cards say -----------------------------------------------------------------------------


def row_hours(index: pd.DatetimeIndex) -> pd.Series:
    """Hours each row stands for: the gap to the next time stamp; the last row repeats the one
    before it; a single row is one hour. The same rule as the integrator behind the annual yield."""
    if len(index) < 2:
        return pd.Series([1.0], index=index)
    gaps = pd.Series(index[1:] - index[:-1], dtype="timedelta64[ns]").dt.total_seconds().to_numpy() / 3600.0
    hours = list(gaps) + [gaps[-1]]
    return pd.Series(hours, index=index)


def row_energy(values: pd.Series) -> pd.Series:
    """kWh (or kWh/m²) in each row of a W (or W/m²) series."""
    return values.astype(float) * row_hours(values.index) / 1000.0


def kwh_text(value: float) -> str:
    """9837.3 -> '9,837.3' (one decimal, as the thesis tables give them)."""
    return f"{value:,.1f}"


def column_info(column: str) -> tuple[str, str | None]:
    """Plain name and unit of a stored output column; a column that is not in the table in
    wording.py is shown by its stored key with no unit."""
    return wording.COLUMN_INFO.get(column, (column, None))


def check_rows(run_info: dict, label: str) -> list[tuple[bool, str, str]]:
    """(passed, what is checked, detail) per check of one pipeline, in a fixed order."""
    found = (run_info.get("checks") or {}).get(label) or {}
    rows = []
    for name in CHECK_ORDER:
        if name not in found:
            continue
        passed = bool(found[name]["passed"])
        detail = "" if passed else "; ".join(found[name].get("problems") or [])
        rows.append((passed, wording.R_CHECK_LABELS[name], detail))
    return rows


def pipelines_not_passing(run_info: dict) -> list[str]:
    return [label for label in LABELS if any(not ok for ok, _w, _d in check_rows(run_info, label))]


# --- Pipeline outputs: period, figures, chart frame, CSV -----------------------------------------------


@dataclass(frozen=True)
class Quantity:
    column: str
    label: str
    unit: str
    kind: str  # "irradiance", "power" or "temperature"


def _quantity(column: str) -> Quantity:
    name, unit = column_info(column)
    kind = {"W/m²": "irradiance", "W": "power", "°C": "temperature"}[unit or ""]
    return Quantity(column, name, unit or "", kind)


QUANTITIES: dict[str, tuple[Quantity, ...]] = {
    "decomposition": (_quantity("dni"), _quantity("dhi")),
    "transposition": (_quantity("poa_global"),),
    "temperature": (_quantity("temp_cell"),),
    "dc": (_quantity("p_dc"),),
    "ac": (_quantity("p_ac"),),
}
PERIODS = tuple(wording.R_PERIODS)


def data_dates(series: dict[str, dict[str, pd.DataFrame]]) -> tuple[date, date]:
    index = series[LABELS[0]]["ac"].index
    return index[0].date(), index[-1].date()


def window_bounds(index: pd.DatetimeIndex, period: str, anchor: date) -> tuple[pd.Timestamp, pd.Timestamp]:
    """[start, end) of the period that contains the date; the year is the whole file."""
    tz = index.tz
    if period == "year":
        return index[0], index[-1] + pd.Timedelta(seconds=1)
    day = pd.Timestamp(anchor)
    if period == "day":
        start, end = day, day + pd.Timedelta(days=1)
    elif period == "week":
        start = day - pd.Timedelta(days=day.weekday())
        end = start + pd.Timedelta(days=7)
    elif period == "month":
        start = day.replace(day=1)
        end = pd.Timestamp((start + pd.offsets.MonthBegin(1)).to_pydatetime())
    else:
        raise ValueError(f"No such period: {period!r}")
    if tz is not None:
        start, end = start.tz_localize(tz), end.tz_localize(tz)
    return start, end


def _cut(frame: pd.DataFrame, bounds: tuple[pd.Timestamp, pd.Timestamp]) -> pd.DataFrame:
    return frame[(frame.index >= bounds[0]) & (frame.index < bounds[1])]


def _daylight_rows(part: pd.Series, daylight: pd.Series) -> pd.Series:
    """The rows of a series that fall in daylight (the run's own mask; the same rule Phase 1 uses)."""
    return part[daylight.reindex(part.index).fillna(False).to_numpy(dtype=bool)]


def period_values(
    series: dict[str, dict[str, pd.DataFrame]], daylight: pd.Series, stage: str, quantity: Quantity,
    period: str, anchor: date,
) -> dict[str, tuple[float, float]]:
    """For each pipeline, the two figures shown for a period: (energy or irradiation, hourly peak),
    or for temperature (mean, maximum) over daylight hours. The one place these are computed:
    the pipeline cards (period 'year') and the Pipeline outputs table both read it."""
    out = {}
    for label in LABELS:
        frame = series[label][stage]
        part = _cut(frame, window_bounds(frame.index, period, anchor))[quantity.column]
        if quantity.kind == "temperature":
            part = _daylight_rows(part, daylight)
            first, second = (float(part.mean()), float(part.max())) if len(part) else (float("nan"),) * 2
        elif part.empty:
            first = second = float("nan")
        else:
            first, second = float(row_energy(part).sum()), float(part.max())
        out[label] = (first, second)
    return out


def period_figure(
    series: dict[str, dict[str, pd.DataFrame]], daylight: pd.Series, label: str, stage: str, quantity: Quantity,
    period: str = "year", anchor: date | None = None,
) -> float:
    anchor = anchor or data_dates(series)[0]
    return period_values(series, daylight, stage, quantity, period, anchor)[label][0]


def total_unit(quantity: Quantity) -> str:
    return wording.TOTAL_UNIT.get(quantity.unit, quantity.unit)


def axis_title(quantity: Quantity, period: str) -> str:
    """What the vertical axis measures for this period."""
    if period in ("day", "week"):
        return f"{quantity.label} ({quantity.unit}), {wording.R_HOURLY}"
    every = wording.R_PER_DAY if period == "month" else wording.R_PER_MONTH
    prefix = f"{wording.R_MEAN_DAYLIGHT}: " if quantity.kind == "temperature" else ""
    return f"{prefix}{quantity.label} ({total_unit(quantity)}) {every}"


def chart_frame(
    series: dict[str, dict[str, pd.DataFrame]], daylight: pd.Series, stage: str, quantity: Quantity,
    period: str, anchor: date,
) -> pd.DataFrame:
    """Exactly what the chart draws and the CSV holds: a time column and one column per
    pipeline. Hourly values for a day or a week; daily totals (or daylight means, for temperature)
    for a month; monthly ones for the whole year."""
    columns = {}
    for label in LABELS:
        frame = series[label][stage]
        part = _cut(frame, window_bounds(frame.index, period, anchor))[quantity.column]
        if period in ("day", "week"):
            columns[label] = part
            continue
        if quantity.kind == "temperature":
            per_row = _daylight_rows(part, daylight)
        else:
            per_row = row_energy(part)
        clock = per_row.index.tz_localize(None) if per_row.index.tz is not None else per_row.index  # local clock time
        grouper = clock.floor("D") if period == "month" else clock.to_period("M").to_timestamp()
        grouped = per_row.groupby(grouper)
        columns[label] = grouped.mean() if quantity.kind == "temperature" else grouped.sum()
    out = pd.DataFrame(columns)
    out.index.name = "time"
    return out


def summary_rows(
    series: dict[str, dict[str, pd.DataFrame]], daylight: pd.Series, stage: str, quantity: Quantity,
    period: str, anchor: date,
) -> list[tuple[str, dict[str, float]]]:
    """Two rows for the table beside the chart, over the whole period shown (not per bucket)."""
    names = {
        "irradiance": (wording.R_TOTAL_IRRADIATION, wording.R_PEAK.format(unit=quantity.unit)),
        "power": (wording.R_TOTAL_ENERGY, wording.R_PEAK.format(unit=quantity.unit)),
        "temperature": (wording.R_MEAN_TEMP, wording.R_MAX_TEMP),
    }[quantity.kind]
    values = period_values(series, daylight, stage, quantity, period, anchor)
    return [(names[i], {label: values[label][i] for label in LABELS}) for i in (0, 1)]


def csv_bytes(frame: pd.DataFrame, quantity: Quantity, period: str) -> bytes:
    """The chart frame as CSV: time first, then Pipeline A, B, C with the quantity in the header."""
    unit = axis_title(quantity, period)
    shown = frame.copy()
    shown.columns = [f"{wording.R_PIPELINE.format(label=label)} - {unit}" for label in shown.columns]
    buffer = io.StringIO()
    shown.to_csv(buffer, index_label="time")
    return buffer.getvalue().encode("utf-8")


_MARKS = {"A": ("circle", [1, 0]), "B": ("square", [7, 4]), "C": ("triangle-up", [2, 3])}
_COLOURS = {"A": "#1F5F6B", "B": "#C2702D", "C": "#3E444A"}


def chart_long(frame: pd.DataFrame) -> pd.DataFrame:
    """The chart frame in long form (what Altair is given), tz dropped so the axis shows local clock time."""
    long = frame.copy()
    long.index = long.index.tz_localize(None) if long.index.tz is not None else long.index
    long = long.reset_index().melt(id_vars="time", var_name="pipeline", value_name="value")
    long["pipeline"] = long["pipeline"].map(lambda label: wording.R_PIPELINE.format(label=label))
    return long


def outputs_chart(frame: pd.DataFrame, title: str, period: str) -> alt.Chart:
    """A, B and C told apart by line dash and marker shape as well as colour."""
    long = chart_long(frame)
    domain = [wording.R_PIPELINE.format(label=label) for label in LABELS]
    scale_colour = alt.Scale(domain=domain, range=[_COLOURS[label] for label in LABELS])
    scale_dash = alt.Scale(domain=domain, range=[_MARKS[label][1] for label in LABELS])
    scale_shape = alt.Scale(domain=domain, range=[_MARKS[label][0] for label in LABELS])
    axis_format = {"day": "%H:%M", "week": "%a %d %b", "month": "%d %b", "year": "%b"}[period]
    x = alt.X("time:T", title=None, axis=alt.Axis(format=axis_format, labelFont="IBM Plex Mono", labelColor="#5B6168"))
    y = alt.Y("value:Q", title=title, axis=alt.Axis(labelFont="IBM Plex Mono", labelColor="#5B6168", titleColor="#3E444A"))
    legend = alt.Legend(title=None, symbolType="stroke", symbolStrokeWidth=3, labelColor="#3E444A")
    base = alt.Chart(long).encode(x=x, y=y)
    line = base.mark_line(strokeWidth=2.5).encode(
        color=alt.Color("pipeline:N", scale=scale_colour, legend=legend),
        strokeDash=alt.StrokeDash("pipeline:N", scale=scale_dash, legend=None),
    )
    every = max(1, len(frame) // 12)
    marked = long.assign(_n=long.groupby("pipeline").cumcount())
    points = (
        alt.Chart(marked[marked["_n"] % every == 0])
        .mark_point(filled=True, size=55, opacity=1)
        .encode(
            x=x, y=y,
            color=alt.Color("pipeline:N", scale=scale_colour, legend=None),
            shape=alt.Shape("pipeline:N", scale=scale_shape, legend=None),
        )
    )
    return (
        (line + points)
        .properties(height=240)
        .configure(background="#FFFFFF")
        .configure_view(stroke="#E6E1D7")
        .configure_axis(gridColor="#EEEAE2", domainColor="#C9C3B7", tickColor="#C9C3B7")
    )


# --- The stage table in each pipeline card ----------------------------------------------------------------


@dataclass(frozen=True)
class StageRow:
    stage: str
    model: str
    outputs: list[tuple[str, str, str]]  # (name, value text, unit)
    check: tuple[bool, str, str]  # (passed, what is checked, problem text)


def stage_rows(run: RunState, label: str) -> list[StageRow]:
    """One row per stage in stage order. Values come from the stored series through
    period_figure, the same function the Pipeline outputs table uses for 'Full year'."""
    checks = (run.run_info.get("checks") or {}).get(label) or {}
    rows = []
    for stage in STAGES:
        outputs = []
        for quantity in QUANTITIES[stage]:
            value = period_figure(run.series, run.daylight, label, stage, quantity)
            name = wording.R_MEAN_DAYLIGHT if quantity.kind == "temperature" else quantity.label
            outputs.append((name, kwh_text(value), total_unit(quantity)))
        key = "ac_not_exceeding_dc" if stage == "ac" else stage
        found = checks.get(key) or {"passed": False, "problems": [wording.R_PROV_NOT_RECORDED]}
        what = wording.R_CHECK_LABELS[key]
        rows.append(
            StageRow(stage, run.models[label][stage], outputs, (bool(found["passed"]), what, "; ".join(found.get("problems") or [])))
        )
    return rows


def card_footer(run: RunState, label: str) -> dict[str, Any]:
    """The two lines under the table: every column finite, and how many stage outputs were read back."""
    found = ((run.run_info.get("checks") or {}).get(label) or {}).get("all_finite")
    saved = sum(1 for stage in STAGES if not run.series[label][stage].empty)
    return {
        "finite": (bool(found["passed"]) if found else False, "; ".join((found or {}).get("problems") or [])),
        "saved": saved,
        "of": len(STAGES),
    }


def daylight_tip(run: RunState) -> str:
    """The tooltip on the daylight mean, with the stored threshold when the record carries it."""
    zenith = next(
        (r["site"].get("daylight_mask_zenith_max_deg") for r in run.provenance.get("records", []) if r.get("site")),
        None,
    )
    if zenith is None:
        return wording.R_DAYLIGHT_TIP_PLAIN
    return wording.R_DAYLIGHT_TIP.format(margin=90 - float(zenith), zenith=float(zenith))


# --- Provenance: what the stored record holds -----------------------------------------------------------------


def _bundle(document: dict) -> dict:
    return next(iter(document["bundle"].values()))


def _typed(value: Any) -> Any:
    """A stored attribute as the number or text it is. PROV-JSON keeps numbers as typed literals
    ({"$": "6.944", "type": "xsd:double"}); give them back as numbers, leave everything else as stored."""
    if isinstance(value, dict) and "$" in value:
        kind = value.get("type", "")
        if kind in ("xsd:double", "xsd:float", "xsd:decimal"):
            return float(value["$"])
        if kind in ("xsd:int", "xsd:integer", "xsd:long"):
            return int(value["$"])
        return value["$"]
    return value


def _attrs(entity: dict) -> dict[str, Any]:
    return {key: _typed(value) for key, value in entity.items()}


def read_documents(analysis_id: str) -> dict[str, dict[str, Any]]:
    """{label: {'id', 'execution_set', 'document'}} for the ORIGINAL records of one analysis."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT pr.id, pr.execution_set, pr.config_label, pr.document FROM provenance_records pr "
            "JOIN analysis_records ar ON ar.record_id = pr.id WHERE ar.analysis_id = %s "
            "AND pr.execution_set = 'original'",
            (analysis_id,),
        )
        rows = cur.fetchall()
    found = {label: {"id": rid, "execution_set": es, "document": doc} for rid, es, label, doc in rows}
    return {label: found[label] for label in LABELS if label in found}  # fixed A, B, C order


def provenance_summary(analysis_id: str) -> dict[str, Any]:
    """The records this analysis touched, with the few facts the page names. 'data_hash' is the
    hash of the prepared weather data inside the records (all three agree)."""
    docs = read_documents(analysis_id)
    records = []
    for label, found in docs.items():
        entities = _bundle(found["document"])["entity"]
        records.append(
            {
                "id": found["id"],
                "label": label,
                "execution_set": found["execution_set"],
                "data_hash": unwrap_value(entities["weather"]["content_hash"]),
                "stage_hashes": {s: unwrap_value(entities[s]["content_hash"]) for s in STAGES},
                "site": _attrs(entities["site_context"]),
                "weather": _attrs(entities["weather"]),
            }
        )
    hashes = {r["data_hash"] for r in records}
    return {
        "records": records,
        "count": len(records),
        "execution_set": records[0]["execution_set"].upper() if records else None,
        "data_hash": hashes.pop() if len(hashes) == 1 else None,
    }


def _setting_text(key: str, value: Any) -> str:
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, float):
        text = format(value, ".10g")  # every stored digit, no padding
    elif isinstance(value, list):
        text = ", ".join(_setting_text(key, v) for v in value)
    else:
        text = str(value)
    if isinstance(value, int | float) and not isinstance(value, bool):
        for suffix, unit in wording.SETTING_UNIT_SUFFIX:
            if key.endswith(suffix):
                return text + unit  # a unit only where the stored key carries one
    return text


def settings_of(entity: dict, skip: tuple[str, ...] = ()) -> list[tuple[str, str, str]]:
    """(stored key, plain label, value text) for every stored attribute except hashes and `skip`."""
    return [
        (key, wording.SETTING_LABELS.get(key, key), _setting_text(key, value))
        for key, value in _attrs(entity).items()
        if key != "content_hash" and key not in skip
    ]


_CONFIG_FIRST = (
    "module_name", "module_library", "inverter_name", "inverter_library", "modules_per_string",
    "strings_per_inverter", "mounting_geometry", "mounting_geometry_source", "mounting_construction",
    "mounting_construction_source", "albedo", "albedo_source", "surface_tilt_deg", "surface_azimuth_deg",
    "module_height_m",
)


def lineage(run: RunState, label: str, docs: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """One pipeline's chain, from its stored record and stored series: the configuration block, then
    per stage what it used, what it produced and its own stored settings. Nothing is added."""
    document = (docs or read_documents(run.analysis_id))[label]["document"]
    bundle = _bundle(document)
    entities = bundle["entity"]
    links: dict[str, list[str]] = {}
    for link in bundle.get("used", {}).values():
        links.setdefault(link["prov:activity"].removeprefix("stage_"), []).append(link["prov:entity"])
    config = entities["configuration"]
    config_keys = [k for k in _CONFIG_FIRST if k in config] + [
        k for k in config if k not in _CONFIG_FIRST and k != "label" and not k.endswith("_model") and k != "content_hash"
    ]
    stages = []
    for stage in STAGES:
        frame = run.series[label][stage]
        used = [e for e in links.get(stage, []) if e != "configuration"]
        used_text = []
        for source in used:
            if source == "weather":
                used_text.append(wording.R_LINEAGE_USED_WEATHER)
            else:
                columns = ", ".join(column_info(c)[0] for c in run.series[label][source].columns)
                used_text.append(wording.R_LINEAGE_USED_STAGE.format(stage=wording.R_LINEAGE_STAGE_NAMES[source], columns=columns))
        produced = ", ".join(
            f"{name} ({unit})" if unit else name for name, unit in (column_info(c) for c in frame.columns)
        )
        statement = wording.R_LINEAGE_STATEMENT.format(
            stage=wording.R_LINEAGE_STAGE_NAMES[stage], model=_attrs(entities[stage])["model"],
            used=" and ".join(used_text) or wording.R_LINEAGE_USED_NOTHING, produced=produced, rows=len(frame),
        )
        stages.append(
            {
                "stage": stage,
                "model": _attrs(entities[stage])["model"],
                "used": used,
                "columns": list(frame.columns),
                "rows": len(frame),
                "statement": statement,
                "settings": settings_of(entities[stage], skip=("model",)),
                "note": wording.R_LINEAGE_NO_WEATHER_LINK if stage == "temperature" and "weather" not in used else None,
            }
        )
    used_config = [s for s in STAGES if "configuration" in links.get(s, [])]
    return {
        "label": label,
        "configuration": [(k, wording.SETTING_LABELS.get(k, k), _setting_text(k, _attrs(config)[k])) for k in config_keys],
        "configuration_used": (
            wording.R_LINEAGE_CONFIG_USED
            if used_config == list(STAGES)
            else wording.R_LINEAGE_CONFIG_USED_SOME.format(
                stages=", ".join(wording.R_LINEAGE_STAGE_NAMES[s] for s in used_config) or wording.R_PROV_NOT_RECORDED
            )
        ),
        "stages": stages,
    }


def spacing_text(series: dict[str, dict[str, pd.DataFrame]]) -> str:
    """The spacing of the stored time stamps."""
    index = series[LABELS[0]]["ac"].index
    step = pd.Series(index[1:] - index[:-1]).mode().iloc[0]
    minutes = step.total_seconds() / 60
    return wording.R_PROV_SPACING_HOURLY if minutes == 60 else wording.R_PROV_SPACING_OTHER.format(minutes=minutes)


def _day(stamp: str) -> str:
    return datetime.fromisoformat(stamp).strftime("%d %b %Y %H:%M")


def top_block(run: RunState, inputs: dict) -> list[tuple[str, str]]:
    """The readable facts at the head of the provenance section, each read from what is stored."""
    record = run.provenance["records"][0]
    site, weather = record["site"], record["weather"]
    offset = (
        f"{float(site['time_offset_h']):g} h · {site.get('time_offset_source', wording.R_PROV_NOT_RECORDED)}"
    )
    reason = (inputs.get("time_offset") or {}).get("reason")
    if reason:
        offset += f" · {wording.R_PROV_REASON.format(reason=reason)}"
    info = run.run_info
    return [
        (wording.R_PROV_WEATHER, (inputs.get("weather") or {}).get("name") or wording.R_PROV_NOT_RECORDED),
        (
            "",
            wording.R_PROV_ROWS.format(
                rows=int(weather["rows"]), start=_day(weather["start"]), end=_day(weather["end"]),
                spacing=spacing_text(run.series),
            ),
        ),
        (
            wording.R_PROV_SITE,
            wording.R_PROV_SITE_VALUE.format(
                latitude=float(site["latitude"]), lat_src=site.get("site_sources.latitude", "?"),
                longitude=float(site["longitude"]), lon_src=site.get("site_sources.longitude", "?"),
                elevation=float(site["elevation"]), elev_src=site.get("site_sources.elevation", "?"),
            ),
        ),
        (wording.R_PROV_OFFSET, offset),
        (wording.R_PROV_TAU, f"{float(site['tau_value']):g} · {site['tau_source']}"),
        (wording.R_PROV_PVLIB, info.get("pvlib_version") or wording.R_PROV_NOT_RECORDED),
        (wording.R_PROV_STARTED, clock_text(info.get("started_at"))),
        (wording.R_PROV_FINISHED, clock_text(info.get("finished_at"))),
        (
            wording.R_PROV_SET,
            wording.R_PROV_RECORDS.format(set=run.provenance.get("execution_set") or "?", n=run.provenance.get("count", 0)),
        ),
    ]


def identifiers(run: RunState, inputs: dict) -> dict[str, Any]:
    """Everything hash-like, for the one closed expander and nowhere else."""
    return {
        "run_id": run.analysis_id,
        "file_sha": (inputs.get("weather") or {}).get("sha256") or wording.R_PROV_NOT_RECORDED,
        "data_hash": run.provenance.get("data_hash") or wording.R_PROV_NOT_RECORDED,
        "records": run.provenance["records"],
    }


def clock_text(stamp: str | None) -> str:
    if not stamp:
        return wording.R_PROV_NOT_RECORDED
    return datetime.fromisoformat(stamp).astimezone(UTC).strftime("%d %b %Y %H:%M:%S UTC")


__all__ = [
    "PERIODS",
    "QUANTITIES",
    "Live",
    "Quantity",
    "RunState",
    "chart_frame",
    "check_rows",
    "csv_bytes",
    "identifiers",
    "kwh_text",
    "lineage",
    "outputs_chart",
    "period_figure",
    "provenance_summary",
    "reopen",
    "run_pipelines",
    "stage_rows",
    "summary_rows",
    "top_block",
    "window_bounds",
]
