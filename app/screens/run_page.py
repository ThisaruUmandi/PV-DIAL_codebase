"""Step 3 · Run & provenance, laid out as in the Run mock-up.

Run the three pipelines you configured, see their checks and annual energy side by side, look
at what each stage produced, and see which records the run left in the provenance store.
Nothing here ranks, sorts or marks one pipeline; A, B and C always appear in that order.
"""

from __future__ import annotations

from html import escape

import streamlit as st

from app import components, config_logic, gating, run_logic, state, wording
from pvdials.analysis import AnalysisError

STAGE_KEY, QUANTITY_KEY, PERIOD_KEY, DATE_KEY = "w3_stage", "w3_quantity", "w3_period", "w3_date"
LABELS = run_logic.LABELS


# --- State plumbing ----------------------------------------------------------------------------------


def init_widgets(ss, run: run_logic.RunState | None) -> None:
    """Streamlit forgets a widget's state while another page shows, so a missing choice takes the
    value it had at the end of the last render (w3_prev). First time: decomposition, one day,
    the first date in the file."""
    ss.setdefault("w3_prev", {})
    defaults = {STAGE_KEY: "decomposition", PERIOD_KEY: "day"}
    for key, value in defaults.items():
        if ss.get(key) is None:
            ss[key] = ss["w3_prev"].get(key) or value
    first = run_logic.data_dates(run.series)[0] if run else None
    if run and ss.get(DATE_KEY) is None:
        ss[DATE_KEY] = ss["w3_prev"].get(DATE_KEY) or first
    stage = ss[STAGE_KEY]
    options = [q.column for q in run_logic.QUANTITIES[stage]]
    if ss.get(QUANTITY_KEY) not in options:
        ss[QUANTITY_KEY] = options[0]


def _failure_text(exc: Exception) -> str:
    text = str(exc)
    if text == wording.R_FILE_MISSING:
        return text
    if "failed:" in text:
        text = text.split("failed:", 1)[1].strip()
    return wording.R_RUN_FAILED.format(detail=text.rstrip("."))


def _run(ss) -> None:
    """Run the pipelines with progress in plain words; keep what step 4 needs in session state."""
    with st.status(wording.R_PROGRESS_TITLE, expanded=True) as box:

        def say(text: str) -> None:
            box.update(label=text)
            st.write(text)

        try:
            result = run_logic.run_pipelines(ss["inputs"], ss["analysis_id"], say)
        except (AnalysisError, KeyError, ValueError) as exc:
            box.update(label=wording.R_PROGRESS_TITLE, state="complete")
            ss["run_problem"] = _failure_text(exc)
            return
        box.update(label=wording.R_PROGRESS_DONE, state="complete", expanded=False)
    ss.pop("run_problem", None)
    ss["run"] = result
    ss["pipelines_summary"] = result.pipelines_summary
    ss["run_info"] = result.run_info
    ss["run_done"] = True


# --- Pieces of the page --------------------------------------------------------------------------------


def _request_run() -> None:
    st.session_state["w3_run_requested"] = True


def _empty(ss) -> None:
    with st.container(key="card_run_empty"):
        components.card_title(wording.R_EMPTY_TITLE)
        st.html(f'<p class="pv-muted" style="margin:0">{escape(wording.R_EMPTY_TEXT)}</p>')
        if ss.get("run_problem"):
            components.show_problem(ss["run_problem"])
        st.button(wording.R_RUN, type="primary", key="w3_run", disabled=bool(ss.get("pending")), on_click=_request_run)


def _banner(ss, run: run_logic.RunState) -> None:
    failed = run_logic.pipelines_not_passing(run.run_info)
    n = len(LABELS)
    ok = not failed
    title = wording.R_BANNER_PASSED.format(n=n) if ok else wording.R_BANNER_NOT_PASSED.format(n=n, failed=len(failed))
    seconds = run.run_info.get("duration_s")
    with st.container(key="card_banner"):
        left, right = st.columns([4, 1])
        with left:
            took = (
                f' <span class="pv-runtime-inline">{escape(wording.R_RUN_TIME)} <span class="pv-mono">{seconds:.1f} s</span></span>'
                if seconds is not None
                else ""
            )
            st.html(
                f'<div class="pv-banner-title">{components.icon("ok" if ok else "warn", 18)}'
                f"<span>{escape(title)}</span></div>"
                f'<p class="pv-muted" style="margin:4px 0 0 26px">{escape(wording.R_BANNER_SUB)}{took}</p>'
            )
        with right:
            st.button(
                wording.R_RUN_AGAIN, key="w3_run_again", disabled=bool(ss.get("pending")), on_click=_request_run,
                help=wording.R_RUN_AGAIN_NOTE,
            )
    if ss.get("run_problem"):
        components.show_problem(ss["run_problem"])


def _output_cell(outputs, tip: str) -> str:
    parts = []
    for name, value, unit in outputs:
        tipped = f' class="pv-tip" title="{escape(tip)}"' if name == wording.R_MEAN_DAYLIGHT else ""
        parts.append(
            f'<span class="pv-out"><span{tipped}>{escape(name)}</span> '
            f'<b class="pv-mono">{escape(value)}</b> <span class="pv-unit">{escape(unit)}</span></span>'
        )
    return "".join(parts)


def _pipeline_card(run: run_logic.RunState, label: str) -> None:
    tip = run_logic.daylight_tip(run)
    rows = []
    for row in run_logic.stage_rows(run, label):
        passed, what, detail = row.check
        word = wording.R_PASSED if passed else wording.R_NOT_PASSED
        problem = f'<div class="pv-kv-detail">{escape(detail)}</div>' if detail and not passed else ""
        rows.append(
            f"<tr><td>{escape(wording.R_STAGE_SHORT[row.stage])}</td>"
            f'<td class="pv-mono">{escape(row.model)}</td>'
            f'<td class="pv-num">{_output_cell(row.outputs, tip)}</td>'
            f'<td><span class="pv-status pv-status-{"ok" if passed else "bad"}">'
            f'{components.icon("ok" if passed else "bad")}{escape(word)}</span>'
            f'<span class="pv-check-what">{escape(what)}</span>{problem}</td></tr>'
        )
    foot = run_logic.card_footer(run, label)
    finite_ok = foot["finite"][0]
    finite = (
        f'<span class="pv-status pv-status-{"ok" if finite_ok else "bad"}">'
        f'{components.icon("ok" if finite_ok else "bad")}{escape(wording.R_FOOTER_FINITE)}: '
        f'{escape(wording.R_PASSED if finite_ok else wording.R_NOT_PASSED)}</span>'
    )
    with st.container(key=f"card_pipe_{label}"):
        st.html(
            f'<h2 class="pv-card-title">{escape(wording.R_PIPELINE.format(label=label))}</h2>'
            f'<table class="pv-stage-table"><thead><tr><th>{escape(wording.R_CARD_STAGE)}</th>'
            f'<th>{escape(wording.R_CARD_MODEL)}</th><th class="pv-num">{escape(wording.R_CARD_OUTPUT)}</th>'
            f'<th>{escape(wording.R_CARD_CHECK)}</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'
            f'<div class="pv-card-foot"><span>{escape(wording.R_SAVED)} '
            f'<b class="pv-mono">{foot["saved"]} / {foot["of"]}</b></span>{finite}</div>'
        )


def _selection(ss) -> tuple[str, run_logic.Quantity, str]:
    stage = ss[STAGE_KEY]
    quantity = next(q for q in run_logic.QUANTITIES[stage] if q.column == ss[QUANTITY_KEY])
    return stage, quantity, ss[PERIOD_KEY]


def _table_html(rows, quantity) -> str:
    head = "".join(f"<span>{label}</span>" for label in LABELS)
    body = ""
    for name, values in rows:
        cells = "".join(
            f'<span class="pv-mono">{"–" if values[label] != values[label] else run_logic.kwh_text(values[label])}</span>'
            for label in LABELS
        )
        body += f'<span class="pv-sum-label">{escape(name)}</span>{cells}'
    return (
        f'<div class="pv-sum"><b>{escape(wording.R_TABLE_WINDOW)}</b>'
        f'<div class="pv-sum-grid"><span></span>{head}{body}</div></div>'
    )


def _outputs(ss, run: run_logic.RunState) -> None:
    stage, quantity, period = _selection(ss)
    anchor = ss[DATE_KEY]
    frame = run_logic.chart_frame(run.series, run.daylight, stage, quantity, period, anchor)
    with st.container(key="card_outputs"):
        head, button = st.columns([4, 1])
        with head:
            components.card_title(wording.R_OUT_TITLE, wording.R_OUT_SUB)
        with button:
            st.download_button(
                wording.R_DOWNLOAD, data=run_logic.csv_bytes(frame, quantity, period),
                file_name=f"{stage}_{quantity.column}_{period}.csv", mime="text/csv", key="w3_download",
                disabled=frame.empty,
            )
        controls = st.columns([5.6, 1.3, 1.3])
        with controls[0]:
            st.segmented_control(
                wording.R_STAGE, config_logic.STAGES, key=STAGE_KEY, format_func=wording.R_STAGE_SHORT.get,
                selection_mode="single",
            )
            if len(run_logic.QUANTITIES[stage]) > 1:
                st.segmented_control(
                    wording.R_QUANTITY, [q.column for q in run_logic.QUANTITIES[stage]], key=QUANTITY_KEY,
                    format_func=lambda column: next(q.label for q in run_logic.QUANTITIES[stage] if q.column == column),
                    selection_mode="single",
                )
        with controls[1]:
            st.selectbox(wording.R_PERIOD, list(run_logic.PERIODS), key=PERIOD_KEY, format_func=wording.R_PERIODS.get)
        with controls[2]:
            if period != "year":
                first, last = run_logic.data_dates(run.series)
                st.date_input(
                    wording.R_DATE, key=DATE_KEY, min_value=first, max_value=last, help=wording.R_DATE_HELP,
                    format="YYYY-MM-DD",
                )
        if frame.empty:
            components.message("warn", wording.R_NO_DATA_IN_PERIOD)
            return
        chart_col, table_col = st.columns([2, 1.25])
        with chart_col:
            st.altair_chart(
                run_logic.outputs_chart(frame, run_logic.axis_title(quantity, period), period),
                width="stretch",
            )
            st.html(f'<p class="pv-sr-only">{escape(wording.R_CHART_ALT)}</p>')
        with table_col:
            st.html(_table_html(run_logic.summary_rows(run.series, run.daylight, stage, quantity, period, anchor), quantity))


def _facts_html(rows: list[tuple[str, str]]) -> str:
    cells: list[list[str]] = []
    for label, value in rows:
        if label == "" and cells:
            cells[-1][1] += f"<br>{escape(value)}"
        else:
            cells.append([label, escape(value)])
    return "".join(
        f'<div class="pv-kv pv-prov-row"><span>{escape(label)}</span><span class="pv-prov-value">{value}</span></div>'
        for label, value in cells
    )


def _lineage_html(lin: dict) -> str:
    chain = [f'<span class="pv-chip">{escape(wording.R_LINEAGE_WEATHER)}</span>']
    for stage in lin["stages"]:
        chain.append(
            '<span class="pv-arrow" aria-hidden="true">→</span>'
            f'<span class="pv-chip">{escape(wording.R_LINEAGE_STAGE_NAMES[stage["stage"]])}'
            f' <span class="pv-mono">{escape(stage["model"])}</span></span>'
        )
    config = "".join(
        f"<div><span>{escape(label)}</span><b>{escape(value)}</b></div>" for _key, label, value in lin["configuration"]
    )
    blocks = [
        (
            f'<div class="pv-lin-block"><h4>{escape(wording.R_LINEAGE_CONFIG)}</h4>'
            f'<div class="pv-lin-settings">{config}</div><p>{escape(lin["configuration_used"])}</p></div>'
        )
    ]
    for stage in lin["stages"]:
        settings = "".join(
            f"<div><span>{escape(label)}</span><b>{escape(value)}</b></div>" for _key, label, value in stage["settings"]
        ) or f'<p>{escape(wording.R_LINEAGE_NO_SETTINGS)}</p>'
        note = f'<p class="pv-lin-note">{escape(stage["note"])}</p>' if stage["note"] else ""
        blocks.append(
            f'<div class="pv-lin-block"><h4>{escape(wording.R_LINEAGE_STAGE_NAMES[stage["stage"]])}</h4>'
            f'<p>{escape(stage["statement"])}</p>{note}'
            f'<div class="pv-lin-settings">{settings}</div></div>'
        )
    return (
        f'<div class="pv-lineage"><h3>{escape(wording.R_PIPELINE.format(label=lin["label"]))}</h3>'
        f'<div class="pv-chain">{"".join(chain)}</div>{"".join(blocks)}</div>'
    )


def _identifiers_html(ids: dict) -> str:
    def row(label: str, value: str, help_text: str | None = None) -> str:
        helper = f"<small>{escape(help_text)}</small>" if help_text else ""
        return (
            f'<div class="pv-kv pv-prov-row"><span>{escape(label)}{helper}</span>'
            f'<span class="pv-mono pv-prov-value">{escape(value)}</span></div>'
        )

    rows = [
        row(wording.R_PROV_RUN_ID, ids["run_id"]),
        row(wording.R_PROV_FILE_SHA, ids["file_sha"], wording.R_PROV_FILE_SHA_HELP),
        row(wording.R_PROV_DATA_HASH, ids["data_hash"], wording.R_PROV_DATA_HASH_HELP),
    ]
    records = []
    for record in ids["records"]:
        hashes = "".join(
            f"<div><span>{escape(wording.R_IDS_STAGE_HASH.format(stage=wording.R_LINEAGE_STAGE_NAMES[s]))}</span> {escape(h)}</div>"
            for s, h in record["stage_hashes"].items()
        )
        records.append(
            f'<div class="pv-record"><b>{escape(wording.R_PIPELINE.format(label=record["label"]))}</b>'
            f'<div><span>{escape(wording.R_IDS_RECORD)}</span> {escape(record["id"])}</div>{hashes}</div>'
        )
    return f'<div class="pv-prov">{"".join(rows)}</div><div class="pv-records pv-mono">{"".join(records)}</div>'


def _provenance(ss, run: run_logic.RunState) -> None:
    inputs = ss["inputs"]
    with st.container(key="card_prov"):
        st.html(
            f'<h2 class="pv-card-title">{escape(wording.R_PROV_TITLE)}</h2>'
            f'<div class="pv-prov">{_facts_html(run_logic.top_block(run, inputs))}</div>'
        )
        with st.expander(wording.R_LINEAGE_OPEN, expanded=False):
            st.html(f'<p class="pv-note-line">{escape(wording.R_LINEAGE_NOTE)}</p>')
            for label in LABELS:
                st.html(_lineage_html(run.provenance["lineage"][label]))
        with st.expander(wording.R_IDS_OPEN, expanded=False):
            st.html(f'<p class="pv-note-line">{escape(wording.R_IDS_NOTE)}</p>')
            st.html(_identifiers_html(run_logic.identifiers(run, inputs)))


def render() -> None:
    ss = st.session_state
    components.step_header(3)
    components.summary_strip()
    if not gating.is_unlocked(3, state.flags(ss)) or not ss.get("inputs"):
        components.locked_panel(3)
        return

    if ss.pop("w3_run_requested", False) and not ss.get("pending"):
        _run(ss)  # progress shows here, then the results below are drawn from the new run
    run = ss.get("run") if isinstance(ss.get("run"), run_logic.RunState) else None
    init_widgets(ss, run)
    if run is None:
        _empty(ss)
    else:
        _banner(ss, run)
        for label in LABELS:
            _pipeline_card(run, label)
        _outputs(ss, run)
        _provenance(ss, run)

    with st.container(key="run_foot"):
        left, right = st.columns([1, 1])
        with left:
            st.page_link(components.PAGES["2"], label=wording.R_BACK)
        with right:
            done = bool(ss.get("run_done")) and run is not None
            st.page_link(components.PAGES["4"], label=wording.R_GO_ANALYSIS, disabled=not done)
            if not done:
                st.html(f'<p class="pv-note-line">{escape(wording.R_GO_LOCKED)}</p>')

    ss["w3_prev"] = {key: ss.get(key) for key in (STAGE_KEY, PERIOD_KEY, DATE_KEY)}
