"""The Report as one view, built ONLY from stored data: the analysis row, stage_output_values and the linked
provenance records. No pipeline is run and rebuild_live is not called, so a stored analysis opens read-only.

The view is a list of sections made of a few block types. The Report page and the HTML download both walk the
same blocks, so a number cannot differ between them. Every chart has its numbers in a table next to it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from html import escape
from typing import Any

import altair as alt
import pandas as pd

from app import (
    analysis_charts,
    analysis_logic,
    components,
    config_logic,
    reexec_logic,
    run_logic,
    tables,
    wording,
)
from pvdials.analysis import AnalysisError
from pvdials.provenance.analyses import linked_records, load_analysis, load_stage_series

NOT_RECORDED = wording.RX_NOT_RECORDED
LABELS = config_logic.LABELS
STAGES = config_logic.STAGES
EXECUTION_SETS = (
    ("original", "ORIGINAL", wording.RP_PROV_ORIGINAL),
    ("derived", "DERIVED", wording.RP_PROV_DERIVED),
    ("reexec", "REEXEC", wording.RP_PROV_REEXEC),
)


# --- Blocks ----------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Facts:
    rows: list[tuple[str, str]]


@dataclass(frozen=True)
class Lines:
    """One line per item: a head, a label and a tail (Phase 1: pair and outcome, outcome label, k)."""

    items: list[tuple[str, str, str]]


@dataclass(frozen=True)
class Table:
    html: str  # escaped by the shared table builders


@dataclass(frozen=True)
class Chart:
    chart: alt.Chart
    alt_text: str


@dataclass(frozen=True)
class Text:
    text: str
    kind: str = "note"  # "note", "state" or "sub"


@dataclass(frozen=True)
class Heading:
    text: str


@dataclass(frozen=True)
class Strip:
    label: str
    value: str


@dataclass(frozen=True)
class Columns:
    """Two blocks side by side, as the mock-up places them (stacked on a narrow screen)."""

    left: list[Any]
    right: list[Any]


@dataclass(frozen=True)
class Details:
    title: str
    blocks: list[Any] = field(default_factory=list)


@dataclass(frozen=True)
class Section:
    key: str
    title: str
    sub: str | None
    blocks: list[Any]


def format_saved(saved: datetime) -> str:
    """A saved time as the Report and the lists show it: UTC, day month year, hours and minutes."""
    return saved.astimezone(UTC).strftime("%d %b %Y %H:%M UTC")


@dataclass(frozen=True)
class Report:
    analysis_id: str
    name: str
    saved: datetime
    sections: list[Section]
    technical: Details
    row: dict[str, Any]
    records: list[dict[str, Any]]
    tau: dict[str, Any]
    weather_name: str
    pvlib: str

    @property
    def saved_text(self) -> str:
        return format_saved(self.saved)


# --- Small shared facts -------------------------------------------------------------------------------------------------


def _first_original(records: list[dict]) -> dict | None:
    return next((r for r in records if r["execution_set"] == "original"), None)


def _entities(record: dict | None) -> dict:
    return run_logic._bundle(record["document"])["entity"] if record else {}


def _stored(inputs: dict, *keys: str) -> Any:
    value: Any = inputs
    for key in keys:
        if not isinstance(value, dict) or value.get(key) is None:
            return None
        value = value[key]
    return value


def _or_not_recorded(value: Any) -> str:
    return NOT_RECORDED if value is None else str(value)


def hour_label(series: dict | None) -> tuple[str, str]:
    """(axis label, clock name) for the hour axis: UTC when the stored time stamps say so, else 'file time'."""
    index = next((s["ac"].index for s in (series or {}).values() if s), None)
    zone = None if index is None else index.tz
    if zone is not None and str(zone) in ("UTC", "UTC+00:00", "+00:00"):
        return wording.RP_YEAR_HOUR_UTC, wording.RP_YEAR_CLOCK_UTC
    return wording.RP_YEAR_HOUR_FILE, wording.RP_YEAR_CLOCK_FILE


# --- The year section: hour × month and monthly energy, from the stored AC series ------------------------------------


def hour_month_matrix(ac_a: pd.Series, ac_b: pd.Series) -> pd.DataFrame:
    """Mean, over the days of each month, of |AC(a) − AC(b)| at each hour of the day: 24 rows × 12 columns (W)."""
    difference = (ac_a.astype(float) - ac_b.astype(float)).abs()
    grouped = difference.groupby([difference.index.hour, difference.index.month]).mean()
    matrix = grouped.unstack(level=1)
    return matrix.reindex(index=range(24), columns=range(1, 13))


def monthly_energy(series: dict[str, dict[str, pd.DataFrame]]) -> pd.DataFrame:
    """Monthly AC energy (kWh) of A, B and C: rows are months 1-12, columns are the pipelines. The sum of the
    months is each pipeline's annual figure (the same row-energy rule as page 3)."""
    columns = {}
    for label in LABELS:
        per_row = run_logic.row_energy(series[label]["ac"]["p_ac"])
        columns[label] = per_row.groupby(per_row.index.month).sum()
    return pd.DataFrame(columns).reindex(range(1, 13))


def matrix_table_html(matrix: pd.DataFrame) -> str:
    head = "".join(f"<th class='pv-num'>{escape(month)}</th>" for month in analysis_charts.MONTHS)
    body = "".join(
        f"<tr><td class='pv-mono'>{hour:02d}</td>"
        + "".join(f"<td class='pv-num pv-mono'>{matrix.loc[hour, m]:.1f}</td>" for m in matrix.columns)
        + "</tr>"
        for hour in matrix.index
    )
    return (
        '<table class="pv-stage-table pv-full"><thead><tr>'
        f"<th>{escape(wording.RP_YEAR_HOUR_COL)}</th>{head}</tr></thead><tbody>{body}</tbody></table>"
    )


def monthly_table_html(frame: pd.DataFrame) -> str:
    head = "".join(f"<th class='pv-num'>{escape(wording.R_PIPELINE.format(label=label))}</th>" for label in frame.columns)
    body = "".join(
        f"<tr><td>{escape(analysis_charts.MONTHS[month - 1])}</td>"
        + "".join(f"<td class='pv-num pv-mono'>{run_logic.kwh_text(frame.loc[month, label])}</td>" for label in frame.columns)
        + "</tr>"
        for month in frame.index
    )
    totals = "".join(
        f"<td class='pv-num pv-mono'><b>{run_logic.kwh_text(float(frame[label].sum()))}</b></td>" for label in frame.columns
    )
    return (
        '<table class="pv-stage-table"><thead><tr>'
        f"<th>{escape(wording.RP_MONTH_COL)}</th>{head}</tr></thead>"
        f"<tbody>{body}<tr><td><b>{escape(wording.RP_YEAR_ROW)}</b></td>{totals}</tr></tbody></table>"
    )


# --- Sections ------------------------------------------------------------------------------------------------------------


def _inputs_section(row: dict, records: list[dict], series: dict | None) -> Section:
    inputs = row["inputs"] or {}
    entities = _entities(_first_original(records))
    configuration = run_logic._attrs(entities["configuration"]) if "configuration" in entities else {}
    weather = run_logic._attrs(entities["weather"]) if "weather" in entities else {}
    name = _stored(inputs, "weather", "name")
    if weather.get("rows") and series and series.get("A"):
        spacing = run_logic.spacing_text({label: s for label, s in series.items() if s})
        weather_text = wording.RP_V_WEATHER.format(name=_or_not_recorded(name), rows=int(weather["rows"]), spacing=spacing)
    else:
        weather_text = wording.RP_V_WEATHER_NO_ROWS.format(name=_or_not_recorded(name))
    offset = _stored(inputs, "time_offset")
    location = _stored(inputs, "location")
    albedo = configuration.get("albedo", _stored(inputs, "site", "albedo"))
    site = inputs.get("site") or {}
    hardware = inputs.get("hardware") or {}
    tau = analysis_logic.tau_of(row.get("phase1") or {}, inputs.get("tau")) if inputs.get("tau") or row.get("phase1") else None
    pvlib = (row.get("run_info") or {}).get("pvlib_version")
    rows = [
        (wording.RP_IN_WEATHER, weather_text),
        (
            wording.RP_IN_OFFSET,
            wording.RP_V_OFFSET.format(value=float(offset["value_h"]), source=offset.get("source", NOT_RECORDED))
            if offset and offset.get("value_h") is not None else NOT_RECORDED,
        ),
        (
            wording.RP_IN_LOCATION,
            wording.RP_V_LOCATION.format(lat=location["latitude"], lon=location["longitude"], elev=location["elevation"])
            if location and None not in (location.get("latitude"), location.get("longitude"), location.get("elevation"))
            else NOT_RECORDED,
        ),
        (
            wording.RP_IN_ORIENT,
            wording.RP_V_ORIENT.format(
                tilt=float(site["tilt_deg"]), azimuth=float(site["azimuth_deg"]),
                albedo=f"{float(albedo):g}" if albedo is not None else NOT_RECORDED,
            )
            if site.get("tilt_deg") is not None and site.get("azimuth_deg") is not None
            else NOT_RECORDED,
        ),
        (wording.RP_IN_MODULE, _or_not_recorded(hardware.get("module_name"))),
        (wording.RP_IN_INVERTER, _or_not_recorded(hardware.get("inverter_name"))),
        (
            wording.RP_IN_ARRAY,
            wording.RP_V_ARRAY.format(modules=hardware["modules_per_string"], strings=hardware["strings_per_inverter"])
            if hardware.get("modules_per_string") and hardware.get("strings_per_inverter")
            else NOT_RECORDED,
        ),
        (
            wording.RP_IN_TAU_PVLIB,
            wording.RP_V_TAU_PVLIB.format(
                tau=analysis_logic.tau_text(tau) if tau and tau.get("source") != NOT_RECORDED else NOT_RECORDED,
                version=pvlib or NOT_RECORDED,
            ),
        ),
    ]
    return Section("inputs", wording.RP_S_INPUTS, None, [Facts(rows)])


def _pipelines_section(row: dict) -> Section:
    inputs = row["inputs"] or {}
    models = inputs.get("pipelines") or {}
    summary = row.get("pipelines") or {}
    head = f"<th>{escape(wording.RP_PIPE_STAGE)}</th>" + "".join(f"<th>{escape(label)}</th>" for label in LABELS)
    body = []
    for stage in STAGES:
        cells = "".join(
            f"<td class='pv-mono'>{escape(models[label][stage]) if models.get(label) else escape(NOT_RECORDED)}</td>"
            for label in LABELS
        )
        body.append(f"<tr><td>{escape(wording.STAGE_NUMBERED[stage])}</td>{cells}</tr>")
    energy = []
    for label in LABELS:
        entry = next((e for e in summary.get(label, []) if e["stage"] == "AC"), None)
        value = entry.get("annual_energy_kwh") if entry else None
        energy.append(f"{run_logic.kwh_text(value)} kWh" if value is not None else NOT_RECORDED)
    body.append(
        f"<tr><td>{escape(wording.RP_PIPE_ANNUAL)}</td>"
        + "".join(f"<td class='pv-num pv-mono'>{escape(text)}</td>" for text in energy)
        + "</tr>"
    )
    html = f'<table class="pv-stage-table"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'
    return Section("pipelines", wording.RP_S_PIPELINES, None, [Table(html)])


def _phase1_section(row: dict, tau: dict | None) -> Section:
    phase1 = row.get("phase1")
    if not phase1 or not all(k in phase1 for k in ("A-B", "A-C", "B-C")):
        return Section("phase1", wording.RP_S_P1, wording.RP_S_P1_SUB, [Text(NOT_RECORDED, "state")])
    views = analysis_logic.phase1_view(phase1)
    lines = []
    for view in views:
        if view.computable:
            lines.append((f"{view.label} · {wording.P4_OUTCOME.format(n=view.outcome)}", view.outcome_text, view.k_text))
        else:
            lines.append((view.label, view.not_computable or "", ""))
    blocks: list[Any] = [Lines(lines)]
    if any(v.computable for v in views):
        blocks += [
            Heading(wording.P4_HEAT_TITLE),
            Text(wording.P4_HEAT_SUB.format(tau=analysis_logic.tau_text(tau or analysis_logic.tau_of(phase1))), "sub"),
            Chart(analysis_charts.heatmap(views), wording.RP_HEAT_ALT),
            Table(tables.heat_table_html(views)),
        ]
    return Section("phase1", wording.RP_S_P1, wording.RP_S_P1_SUB, blocks)


def _phase2_section(row: dict, tau: dict | None) -> Section:
    phase1, phase2 = row.get("phase1"), row.get("phase2")
    if not phase2:
        return Section("phase2", wording.RP_S_P2, wording.RP_S_P2_SUB, [Text(wording.RP_NOT_RUN, "state")])
    view = analysis_logic.phase2_view(phase2)
    if not view.ran:
        return Section("phase2", wording.RP_S_P2, wording.RP_S_P2_SUB, [Text(view.reason or wording.RP_NOT_RUN, "state")])
    tau = tau or analysis_logic.tau_of(phase1 or {})
    return Section(
        "phase2", wording.RP_S_P2, wording.RP_S_P2_SUB,
        [
            Chart(
                analysis_charts.propagation_chart(view, tau["value"], analysis_logic.tau_text(tau)),
                wording.P4_P2_CHART_ALT,
            ),
            Table(tables.phase2_table_html(view, analysis_logic.phase2_rows(view))),
        ],
    )


def _phase3_section(row: dict) -> Section:
    phase1, phase3 = row.get("phase1"), row.get("phase3")
    if not phase1 or not all(k in phase1 for k in ("A-B", "A-C", "B-C")):
        return Section("phase3", wording.RP_S_P3, wording.RP_S_P3_SUB, [Text(NOT_RECORDED, "state")])
    blocks: list[Any] = []
    for view in analysis_logic.phase3_views(phase1, phase3):
        label = analysis_logic.pair_label(view.pair)
        if view.state != "ran":
            message = wording.RP_NOT_RUN if view.state == "pending" else (view.message or wording.RP_NOT_RUN)
            blocks.append(Text(wording.RP_P3_PAIR_STATE.format(pair=label, state=message), "state"))
            continue
        a, b = view.pair
        efficiency, _agrees = tables.efficiency_text(view)
        blocks += [
            Heading(label),
            Columns(
                [Heading(wording.P4_P3_COL_SHARE), Chart(analysis_charts.share_chart(view), wording.RP_P3_ALT_SHARE)],
                [
                    Heading(wording.P4_P3_WATERFALL_TITLE.format(pair=label)),
                    Chart(analysis_charts.waterfall(view), wording.P4_P3_ALT.format(a=a, b=b)),
                ],
            ),
            Table(tables.phase3_report_table_html(view)),
            Text(efficiency, "note"),
        ]
        if view.one_stage:
            blocks.append(Text(wording.ONE_STAGE_NOTE, "note"))
    return Section("phase3", wording.RP_S_P3, wording.RP_S_P3_SUB, blocks)


def _year_section(row: dict, series: dict | None) -> Section:
    sub = wording.RP_S_YEAR_SUB
    phase1 = row.get("phase1")
    if not phase1 or not all(k in phase1 for k in ("A-B", "A-C", "B-C")):
        return Section("year", wording.RP_S_YEAR, sub, [Text(NOT_RECORDED, "state")])
    if not series or not all(series.get(label) for label in LABELS):
        return Section("year", wording.RP_S_YEAR, sub, [Text(NOT_RECORDED, "state")])
    label_text, clock = hour_label(series)
    pairs = [p for p in analysis_logic.PAIRS if phase1[analysis_logic.pair_key(p)].get("status") == "ran"]
    matrices = {p: hour_month_matrix(series[p[0]]["ac"]["p_ac"], series[p[1]]["ac"]["p_ac"]) for p in pairs}
    top = max((float(m.max().max()) for m in matrices.values()), default=1.0) or 1.0  # one colour scale for every map
    blocks: list[Any] = []
    for pair in pairs:
        title = analysis_logic.pair_label(pair)
        blocks += [
            Heading(wording.RP_YEAR_HEAT_TITLE.format(pair=title)),
            Chart(analysis_charts.hour_month_chart(matrices[pair], top, label_text), wording.RP_YEAR_ALT.format(pair=title)),
            Text(wording.RP_YEAR_NOTE.format(clock=clock), "note"),
            Details(wording.RP_YEAR_TABLE_OPEN.format(pair=title), [Table(matrix_table_html(matrices[pair]))]),
        ]
    energy = monthly_energy(series)
    blocks += [
        Heading(wording.RP_MONTHLY_TITLE),
        Chart(analysis_charts.monthly_energy_chart(energy), wording.RP_MONTHLY_ALT),
        Table(monthly_table_html(energy)),
        Text(wording.RP_MONTHLY_NOTE, "note"),
    ]
    return Section("year", wording.RP_S_YEAR, sub, blocks)


def _confirmed_table_html(before: analysis_logic.PairView | None, view: reexec_logic.AttemptView | None, title: str, k: str) -> str:
    """Before and Confirmed for the stages from the localised stage to AC, as in the mock-up. A part that was not
    saved reads 'not recorded for this analysis'."""
    rows = []
    stages = list(wording.STAGE_KEYS)
    missing = f"<td class='pv-num'>{escape(NOT_RECORDED)}</td>"
    for index, stage in enumerate(stages):
        if index < stages.index(k):
            continue
        if view is not None and view.computable:
            row = view.rows[index]
            cells = _confirmed_cell(row.before, row.before_over) + _confirmed_cell(row.after, row.after_over)
        elif before is not None and before.computable:
            cells = _confirmed_cell(before.nrmsd[stage], stage in before.over) + missing
        else:
            cells = missing + missing
        rows.append(f"<tr><td>{escape(wording.STAGE_NUMBERED[stage])}</td>{cells}</tr>")
    return (
        '<table class="pv-stage-table pv-attempts"><thead><tr>'
        f"<th>{escape(wording.RP_RX_TABLE_STAGE)}</th><th class='pv-num'>{escape(wording.RX_COL_BEFORE)}</th>"
        f"<th class='pv-num'>{escape(title)}</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def _confirmed_cell(value: float | None, over: bool) -> str:
    mark = components.over_tau_mark() if over else ""
    return f'<td class="pv-num pv-nowrap">{mark}<span class="pv-mono">{analysis_logic.fmt_nrmsd(value)}</span></td>'


def _reexec_section(row: dict, tau: dict | None) -> Section:
    reexec = row.get("reexec")
    title, sub = wording.RP_S_REEXEC, None
    if not reexec:
        return Section("reexec", title, sub, [Text(wording.RP_NO_CHANGE, "state")])
    inputs = row["inputs"] or {}
    phase1 = row.get("phase1") or {}
    pair = tuple(reexec["pair"])
    pair_entry = phase1.get(analysis_logic.pair_key(pair))
    anchor, stage, candidate = reexec.get("anchor"), reexec.get("stage"), reexec.get("candidate")
    stage_key = stage.lower() if stage else None
    k = (pair_entry or {}).get("k", None)
    k_key = k.lower() if k else stage_key
    stage_text = (
        wording.RP_RX_STAGE.format(number=list(wording.STAGE_KEYS).index(stage_key) + 1, name=wording.STAGE_NAME[stage_key])
        if stage_key else NOT_RECORDED
    )
    sub = wording.RP_RX_TRACK.format(pair=analysis_logic.pair_label(pair), anchor=anchor or NOT_RECORDED, stage=stage_text)
    old = ((inputs.get("pipelines") or {}).get(anchor) or {}).get(stage_key) if anchor and stage_key else None
    change = wording.RP_RX_CHANGE_VALUE.format(old=old, new=candidate) if old and candidate else NOT_RECORDED
    yield_value = reexec.get("annual_yield_kwh")
    yield_text = f"{run_logic.kwh_text(yield_value)} kWh" if yield_value is not None else wording.RX_YIELD_NONE
    left: list[Any] = [
        Facts([(wording.RP_RX_CHANGE, change)]),
        Strip(wording.RP_RX_YIELD.format(anchor=anchor or NOT_RECORDED, candidate=candidate or NOT_RECORDED), yield_text),
    ]
    blocks: list[Any] = []
    saved_phase1 = reexec.get("phase1")
    before = analysis_logic.phase1_view(phase1)[analysis_logic.PAIRS.index(pair)] if pair_entry else None
    view = (
        reexec_logic.attempt_view(pair_entry, saved_phase1)
        if saved_phase1 and pair_entry and pair_entry.get("status") == "ran"
        else None
    )
    column = wording.RX_COL_CONFIRMED.format(model=candidate) if candidate else wording.RX_COL_CONFIRMED_PLAIN
    if k_key:
        blocks.append(Columns(left, [Table(_confirmed_table_html(before, view, column, k_key))]))
    else:
        blocks.extend(left)
    if view is not None and view.computable and k_key:
        tau = tau or analysis_logic.tau_of(phase1)
        top = reexec_logic.axis_max(phase1, [{"phase1": saved_phase1}])
        blocks += [
            Heading(wording.RP_RX_CHART_TITLE),
            Chart(
                analysis_charts.confirmed_bars(view, analysis_logic.tau_text(tau), top, column, k_key),
                wording.RP_RX_CHART_ALT,
            ),
        ]
    elif view is not None and not view.computable:
        blocks.append(Text(view.message or "", "state"))
    blocks += [Text(wording.RP_RX_NOTE, "note"), Text(wording.DISCLAIMER, "disclaimer")]
    return Section("reexec", title, sub, blocks)


def _provenance_section(records: list[dict]) -> Section:
    counts = {es: sum(1 for r in records if r["execution_set"] == es) for es, _u, _l in EXECUTION_SETS}
    rows = [(label, wording.RP_PROV_COUNT.format(set=upper, n=counts[es])) for es, upper, label in EXECUTION_SETS]
    return Section("provenance", wording.RP_S_PROV, None, [Facts(rows)])


def _technical(row: dict, records: list[dict], analysis_id: str) -> Details:
    inputs = row["inputs"] or {}
    entities = _entities(_first_original(records))
    data_hash = run_logic.unwrap_value(entities["weather"]["content_hash"]) if "weather" in entities else None
    rows = [
        (wording.R_PROV_RUN_ID, analysis_id),
        (wording.R_PROV_FILE_SHA, _or_not_recorded(_stored(inputs, "weather", "sha256"))),
        (wording.R_PROV_DATA_HASH, _or_not_recorded(data_hash)),
    ]
    return Details(wording.R_IDS_OPEN, [Text(wording.R_IDS_NOTE, "note"), Facts(rows)])


# --- The report ------------------------------------------------------------------------------------------------------------


def build_report(analysis_id: str) -> Report:
    """The whole report for one stored analysis. Reads the row, the stored AC series and the linked records,
    and nothing else."""
    row = load_analysis(analysis_id)
    if row is None:
        raise AnalysisError(wording.RP_NO_ANALYSIS)
    records = linked_records(analysis_id)
    series: dict[str, dict | None] | None = {label: load_stage_series(analysis_id, label) for label in LABELS}
    if not any(series.values()):
        series = None
    inputs = row["inputs"] or {}
    tau = analysis_logic.tau_of(row.get("phase1") or {}, inputs.get("tau")) if (row.get("phase1") or inputs.get("tau")) else None
    sections = [
        _inputs_section(row, records, series),
        _pipelines_section(row),
        _phase1_section(row, tau),
        _phase2_section(row, tau),
        _phase3_section(row),
        _year_section(row, series),
        _reexec_section(row, tau),
        _provenance_section(records),
    ]
    saved = row["updated_at"]
    return Report(
        analysis_id=analysis_id, name=row["name"], saved=saved, sections=sections,
        technical=_technical(row, records, analysis_id), row=row, records=records,
        tau=tau or {"value": None, "source": NOT_RECORDED},
        weather_name=_or_not_recorded(_stored(inputs, "weather", "name")),
        pvlib=(row.get("run_info") or {}).get("pvlib_version") or NOT_RECORDED,
    )


@lru_cache(maxsize=4)
def report_for(analysis_id: str, saved_iso: str) -> Report:
    """The report of one analysis at one saved time, kept so a rerun of the page does not read it all again."""
    return build_report(analysis_id)


__all__ = ["Report", "Section", "build_report", "hour_month_matrix", "monthly_energy", "report_for"]
