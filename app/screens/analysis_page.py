"""Step 4 · Analysis, laid out as in the Analysis mock-up.

Three buttons: Phase 1, Phase 2, Phase 3. A phase computes only on its button; a rerun of the page draws what is
in session state (which holds what was saved). Pairs are always A–B, A–C, B–C, and nothing is sorted, ranked or
highlighted by how much the pipelines disagree.
"""

from __future__ import annotations

from html import escape

import streamlit as st

from app import (
    analysis_charts,
    analysis_logic,
    components,
    gating,
    run_logic,
    state,
    tables,
    wording,
)
from pvdials.analysis import AnalysisError

PAIR_KEY = "w4_pair"
P3_PAIR_KEY = "w4_p3pair"
LABELS = run_logic.LABELS


# --- State plumbing ----------------------------------------------------------------------------------


def _phase1(ss) -> dict | None:
    value = ss.get("phase1")
    return value if isinstance(value, dict) and all(k in value for k in ("A-B", "A-C", "B-C")) else None


def init_widgets(ss, views) -> None:
    """Streamlit forgets a widget's state while another page shows, so a missing choice takes the value
    it had at the end of the last render (w4_prev). First time: the first pair that has numbers."""
    ss.setdefault("w4_prev", {})
    keys = [view.key for view in views]
    if ss.get(PAIR_KEY) not in keys:
        first = next((view.key for view in views if view.computable), keys[0])
        ss[PAIR_KEY] = ss["w4_prev"].get(PAIR_KEY) if ss["w4_prev"].get(PAIR_KEY) in keys else first


def _request(phase: int):
    def callback() -> None:
        st.session_state[f"w4_run_p{phase}"] = True

    return callback


def _failure_text(exc: Exception) -> str:
    return wording.P4_FAILED.format(detail=str(exc).split("failed:")[-1].strip().rstrip("."))


def _run_phase1(ss) -> None:
    with st.status(wording.P4_PROGRESS_TITLE, expanded=True) as box:

        def say(text: str) -> None:
            box.update(label=text)
            st.write(text)

        try:
            analysis_logic.run_phase1(ss, say)
        except (AnalysisError, KeyError, ValueError) as exc:
            box.update(label=wording.P4_PROGRESS_TITLE, state="complete")
            ss["p1_problem"] = _failure_text(exc)
            return
        box.update(label=wording.R_PROGRESS_DONE, state="complete", expanded=False)
    ss.pop("p1_problem", None)
    st.rerun()  # the sidebar was drawn before this phase finished; draw the page again so it shows the new state


def _run_phase2(ss) -> None:
    with st.status(wording.P4_P2_PROGRESS_TITLE, expanded=True) as box:

        def say(text: str) -> None:
            box.update(label=text)
            st.write(text)

        try:
            analysis_logic.run_phase2(ss, say)
        except (AnalysisError, KeyError, ValueError) as exc:
            box.update(label=wording.P4_P2_PROGRESS_TITLE, state="complete")
            ss["p2_problem"] = wording.P4_P2_FAILED.format(detail=str(exc).split("failed:")[-1].strip().rstrip("."))
            return
        box.update(label=wording.R_PROGRESS_DONE, state="complete", expanded=False)
    ss.pop("p2_problem", None)


def _run_phase3(ss) -> None:
    with st.status(wording.P4_P3_PROGRESS_TITLE, expanded=True) as box:

        def say(text: str) -> None:
            box.update(label=text)
            st.write(text)

        try:
            analysis_logic.run_phase3(ss, say)
        except (AnalysisError, KeyError, ValueError) as exc:
            box.update(label=wording.P4_P3_PROGRESS_TITLE, state="complete")
            ss["p3_problem"] = wording.P4_P3_FAILED.format(detail=str(exc).split("failed:")[-1].strip().rstrip("."))
            return
        box.update(label=wording.R_PROGRESS_DONE, state="complete", expanded=False)
    ss.pop("p3_problem", None)


# --- Pieces of the page -----------------------------------------------------------------------------------


def _buttons(ss, phase1: dict | None) -> None:
    done = phase1 is not None
    columns = st.columns(3)
    with columns[0]:
        st.button(
            wording.P4_P1_BUTTON, key="w4_p1", type="secondary" if done else "primary",
            on_click=_request(1), disabled=bool(ss.get("pending")),
        )
        st.html(f'<p class="pv-btn-note">{escape(wording.P4_RAN if done else wording.P4_P1_CAPTION)}</p>')
    phase2 = ss.get("phase2") if isinstance(ss.get("phase2"), dict) else None
    blocked2 = analysis_logic.phase2_blocked_reason(phase2) if done else None
    blocked3 = analysis_logic.phase3_blocked_reason(phase1) if done else None
    with columns[1]:
        st.button(
            wording.P4_P2_BUTTON, key="w4_p2", type="secondary", on_click=_request(2),
            disabled=not done or blocked2 is not None or bool(ss.get("pending")),
        )
        ran2 = phase2 is not None and phase2.get("status") == "ran"
        note2 = blocked2 or (wording.P4_RAN if ran2 else wording.P4_P2_CAPTION)
        st.html(f'<p class="pv-btn-note">{escape(note2)}</p>')
    with columns[2]:
        st.button(
            wording.P4_P3_BUTTON, key="w4_p3", type="secondary", on_click=_request(3),
            disabled=not done or blocked3 is not None or bool(ss.get("pending")),
        )
        finished3 = done and analysis_logic.phase3_done(phase1, ss.get("phase3") if isinstance(ss.get("phase3"), dict) else None)
        note3 = blocked3 or (wording.P4_RAN if finished3 else wording.P4_P3_CAPTION)
        st.html(f'<p class="pv-btn-note">{escape(note3)}</p>')
    if not done:
        st.html(f'<p class="pv-note-line">{escape(wording.P4_LOCKED)}</p>')


def _empty() -> None:
    first, _dot, rest = wording.EMPTY_ANALYSIS.partition(". ")
    with st.container(key="card_empty"):
        st.html(f'<p class="pv-empty"><b>{escape(first)}.</b> {escape(rest)}</p>')


def _pair_card(view) -> None:
    with st.container(key=f"card_pair_{view.key.replace('-', '')}"):
        if not view.computable:
            st.html(
                f'<div class="pv-pair-head">{escape(view.label)}</div>'
                f'<p class="pv-pair-sentence">{escape(view.not_computable or "")}</p>'
            )
            return
        st.html(
            f'<div class="pv-pair-head">{escape(view.label)}</div>'
            f'<div class="pv-outcome">{escape(wording.P4_OUTCOME.format(n=view.outcome))}</div>'
            f'<div class="pv-outcome-text">{escape(view.outcome_text)}</div>'
            f'<div class="pv-k pv-mono" title="{escape(wording.HELP_K)}">{escape(view.k_text)}</div>'
            f'<p class="pv-pair-sentence">{escape(view.sentence)}</p>'
            f'<p class="pv-band">{escape(view.band or "")}</p>'
        )


def _heat_card(views, tau: dict) -> None:
    with st.container(key="card_heat"):
        components.card_title(wording.P4_HEAT_TITLE, wording.P4_HEAT_SUB.format(tau=analysis_logic.tau_text(tau)))
        chart, table = st.columns([4, 5])
        with chart:
            st.altair_chart(analysis_charts.heatmap(views), width="stretch")
        with table:
            st.html(tables.heat_table_html(views))


def _stage_table(rows, tau: dict) -> str:
    body = []
    for row in rows:
        against = components.over_tau_mark() if row["over"] else f'<span class="pv-within">{escape(wording.P4_WITHIN_TAU)}</span>'
        first = f'<span class="pv-first">{escape(wording.P4_FIRST_OVER)}</span>' if row["first"] else ""
        value = wording.P4_NA if row["nrmsd"] is None else row["text"]
        body.append(
            f"<tr><td>{escape(row['label'])}{first}</td>"
            f'<td class="pv-num pv-mono">{escape(value)}</td>'
            f"<td>{against}</td>"
            f'<td class="pv-models">{row["models"]}</td></tr>'
        )
    against_header = wording.P4_COL_AGAINST.format(tau=analysis_logic.tau_text(tau))
    return (
        '<table class="pv-stage-table"><thead><tr>'
        f"<th>{escape(wording.P4_COL_STAGE)}</th>"
        f'<th class="pv-num">{tables.tip(wording.P4_COL_NRMSD, wording.HELP_NRMSD)}</th>'
        f'<th>{tables.tip(against_header, wording.HELP_TAU)}</th>'
        f"<th>{escape(wording.P4_COL_MODELS)}</th></tr></thead><tbody>{''.join(body)}</tbody></table>"
    )


def _stage_card(ss, views, tau: dict) -> None:
    models = ss["inputs"]["pipelines"]
    with st.container(key="card_stage"):
        head, picker = st.columns([2, 3])
        with head:
            components.card_title(wording.P4_STAGE_TITLE)
        with picker:
            st.segmented_control(
                wording.P4_STAGE_PAIR, [view.key for view in views], key=PAIR_KEY,
                format_func=lambda key: next(v.label for v in views if v.key == key), selection_mode="single",
            )
        view = next(v for v in views if v.key == ss[PAIR_KEY])
        if not view.computable:
            components.message("warn", view.not_computable or "")
            return
        rows = analysis_logic.stage_rows(view, models)
        axis_max = analysis_logic.nrmsd_axis_max(views, tau["value"])  # the same range whichever pair is shown
        table, chart = st.columns([3, 2])
        with table:
            st.html(_stage_table(rows, tau))
        with chart:
            st.altair_chart(analysis_charts.stage_bars(rows, tau["value"], analysis_logic.tau_text(tau), axis_max), width="stretch")
        st.html(f'<p class="pv-note-line">{escape(wording.P4_UNITLESS.format(tau=analysis_logic.tau_text(tau)))}</p>')


def _phase2_section(ss, phase1: dict) -> None:
    phase2 = ss.get("phase2") if isinstance(ss.get("phase2"), dict) else None
    if phase2 is None:
        return
    view = analysis_logic.phase2_view(phase2)
    tau = analysis_logic.tau_of(phase1, ss["inputs"].get("tau"))
    with st.container(key="card_p2"):
        if not view.ran:
            components.card_title(wording.P4_P2_NOT_RUN_TITLE)
            components.message("todo", view.reason or "", False)
            return
        components.card_title(wording.P4_P2_TITLE, wording.P4_P2_SUB.format(tau=analysis_logic.tau_text(tau)))
        st.altair_chart(
            analysis_charts.propagation_chart(view, tau["value"], analysis_logic.tau_text(tau)), width="stretch"
        )
        st.html(f'<p class="pv-sr-only">{escape(wording.P4_P2_CHART_ALT)}</p>')
        st.html(tables.phase2_table_html(view, analysis_logic.phase2_rows(view)))


def _efficiency_line(view) -> None:
    text, agrees = tables.efficiency_text(view)
    components.message("ok" if agrees else "warn", text, False)


def _phase3_section(ss, phase1: dict) -> None:
    phase3 = ss.get("phase3") if isinstance(ss.get("phase3"), dict) else None
    views = analysis_logic.phase3_views(phase1, phase3)
    if all(view.state in ("pending",) for view in views) and not phase3:
        return  # nothing to show yet: Phase 3 has not been run and Phase 1 settled none of the pairs
    keys = [analysis_logic.pair_key(view.pair) for view in views]
    if ss.get(P3_PAIR_KEY) not in keys:
        shown = next((v for v in views if v.state == "ran"), views[0])
        ss[P3_PAIR_KEY] = ss["w4_prev"].get(P3_PAIR_KEY) if ss["w4_prev"].get(P3_PAIR_KEY) in keys else analysis_logic.pair_key(shown.pair)
    with st.container(key="card_p3"):
        head, picker = st.columns([2, 3])
        with head:
            components.card_title(wording.P4_P3_TITLE.format(pair=analysis_logic.pair_label(next(v.pair for v in views if analysis_logic.pair_key(v.pair) == ss[P3_PAIR_KEY]))), wording.P4_P3_SUB)
        with picker:
            st.segmented_control(
                wording.P4_P3_PICK, keys, key=P3_PAIR_KEY, selection_mode="single",
                format_func=lambda key: wording.P4_PAIR.format(a=key[0], b=key[2]),
            )
        view = next(v for v in views if analysis_logic.pair_key(v.pair) == ss[P3_PAIR_KEY])
        if view.state != "ran":
            components.message("todo", view.message or "", False)
            return
        st.html(tables.phase3_table_html(view, wording.HELP_PHI))
        if view.one_stage:
            components.message("todo", wording.ONE_STAGE_NOTE, False)
        _efficiency_line(view)
    if view.state == "ran":
        a, b = view.pair
        with st.container(key="card_p3_chart"):
            components.card_title(
                wording.P4_P3_WATERFALL_TITLE.format(pair=analysis_logic.pair_label(view.pair)),
                wording.P4_P3_WATERFALL_SUB.format(a=a, b=b),
            )
            st.altair_chart(analysis_charts.waterfall(view), width="stretch")
            st.html(f'<p class="pv-sr-only">{escape(wording.P4_P3_ALT.format(a=a, b=b))}</p>')


def _zenith(run: run_logic.RunState) -> float | None:
    return next(
        (r["site"].get("daylight_mask_zenith_max_deg") for r in run.provenance.get("records", []) if r.get("site")),
        None,
    )


def _details(run: run_logic.RunState, views) -> None:
    with st.expander(wording.P4_DEFS_OPEN, expanded=False):
        items = [
            (wording.P4_COL_NRMSD, wording.HELP_NRMSD),
            (wording.TAU, wording.HELP_TAU),
            ("k", wording.HELP_K),
            *(("", line) for line in wording.P4_DEF_OUTCOMES),
            *wording.P4_P2_DEFS,
            ("φ", wording.HELP_PHI),
            ("", wording.P4_PHI_NEGATIVE),
            ("Share", wording.HELP_SHARE),
        ]
        st.html(
            '<dl class="pv-defs">'
            + "".join(f"<div><dt>{escape(term)}</dt><dd>{escape(text)}</dd></div>" for term, text in items)
            + "</dl>"
        )
    with st.expander(wording.P4_METHOD_OPEN, expanded=False):
        zenith = _zenith(run)
        lines = (
            [wording.P4_METHOD_LINES[0].format(margin=90 - float(zenith)), *wording.P4_METHOD_LINES[1:]]
            if zenith is not None
            else list(wording.P4_METHOD_LINES_PLAIN)
        )
        st.html("<ul class='pv-method'>" + "".join(f"<li>{escape(line)}</li>" for line in lines) + "</ul>")
    with st.expander(wording.P4_FULL_OPEN, expanded=False):
        head = "".join(f"<th>{escape(name)}</th>" for name in wording.P4_FULL_COLUMNS)
        body = "".join(
            "<tr>" + "".join(f"<td class='pv-mono'>{escape(cell)}</td>" if i > 1 else f"<td>{escape(cell)}</td>" for i, cell in enumerate(row)) + "</tr>"
            for row in analysis_logic.full_rows([v for v in views if v.computable])
        )
        st.html(f'<table class="pv-stage-table pv-full"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>')


def _phase1_section(ss, run: run_logic.RunState, phase1: dict) -> None:
    views = analysis_logic.phase1_view(phase1)
    tau = analysis_logic.tau_of(phase1, ss["inputs"].get("tau"))
    init_widgets(ss, views)
    columns = st.columns(3)
    for column, view in zip(columns, views, strict=True):
        with column:
            _pair_card(view)
    if any(view.computable for view in views):
        _heat_card(views, tau)
        _stage_card(ss, views, tau)
    _phase2_section(ss, phase1)
    _phase3_section(ss, phase1)
    _details(run, views)


def render() -> None:
    ss = st.session_state
    components.step_header(4)
    components.summary_strip()
    if not gating.is_unlocked(4, state.flags(ss)) or not isinstance(ss.get("run"), run_logic.RunState):
        components.locked_panel(4)
        return
    run = ss["run"]

    if ss.pop("w4_run_p1", False) and not ss.get("pending"):
        _run_phase1(ss)
    phase1 = _phase1(ss)
    if ss.pop("w4_run_p2", False) and phase1 is not None and not ss.get("pending"):
        _run_phase2(ss)
    if ss.pop("w4_run_p3", False) and phase1 is not None and not ss.get("pending"):
        _run_phase3(ss)

    st.page_link(components.PAGES["3"], label=wording.P4_VIEW_RUN)
    _buttons(ss, phase1)
    for problem in ("p1_problem", "p2_problem", "p3_problem"):
        if ss.get(problem):
            components.show_problem(ss[problem])
    if phase1 is None:
        _empty()
    else:
        _phase1_section(ss, run, phase1)
    ss["w4_prev"] = {PAIR_KEY: ss.get(PAIR_KEY), P3_PAIR_KEY: ss.get(P3_PAIR_KEY)}
