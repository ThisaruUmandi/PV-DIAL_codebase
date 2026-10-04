"""Step 5 · Guided re-execution (optional), laid out as in the Reexecute mock-up.

Choose a pair that has a k, the anchor and one candidate; an attempt runs only on its button and always starts
from the frozen anchor. No candidate or attempt is ordered, scored or marked by how the disagreement changed; the
change is a signed number. A confirmed change is asked for first, then saved.
"""

from __future__ import annotations

from html import escape

import streamlit as st

from app import (
    analysis_charts,
    analysis_logic,
    components,
    gating,
    reexec_logic,
    run_logic,
    state,
    wording,
)

PAIR_KEY, ANCHOR_KEY, CAND_KEY, VIEW_KEY = "w5_pair", "w5_anchor", "w5_candidate", "w5_view"
NO_K = "—"


# --- State plumbing ---------------------------------------------------------------------------------------


def _phase1(ss) -> dict | None:
    value = ss.get("phase1")
    return value if isinstance(value, dict) and all(k in value for k in ("A-B", "A-C", "B-C")) else None


def _request(flag: str):
    def callback() -> None:
        st.session_state[flag] = True

    return callback


def _ask(seq: int):
    def callback() -> None:
        st.session_state["w5_confirming"] = seq

    return callback


def _cancel() -> None:
    st.session_state["w5_confirming"] = None


def init_widgets(ss, pair_keys: list[str]) -> None:
    """Streamlit forgets a widget's state while another page shows, so a missing choice takes the value it had
    at the end of the last render (w5_prev). Nothing is preselected: the first time every choice is empty."""
    prev = ss.setdefault("w5_prev", {})
    for key in (PAIR_KEY, ANCHOR_KEY, CAND_KEY):
        if key not in ss:
            ss[key] = prev.get(key)
    if ss[PAIR_KEY] not in pair_keys:
        ss[PAIR_KEY] = None


def _pair(ss) -> tuple[str, str] | None:
    return tuple(ss[PAIR_KEY].split("-")) if ss.get(PAIR_KEY) else None


# --- Running -----------------------------------------------------------------------------------------------


def _status(title: str, work, ss, problem_key: str) -> bool:
    """Run work(say) under a progress box; True when it finished, False with a plain message otherwise."""
    with st.status(title, expanded=True) as box:

        def say(text: str) -> None:
            box.update(label=text)
            st.write(text)

        try:
            work(say)
        except reexec_logic.ATTEMPT_FAILURES as exc:
            box.update(label=title, state="complete")
            ss[problem_key] = wording.RX_FAILED.format(detail=str(exc).split("failed:")[-1].strip().rstrip("."))
            return False
        box.update(label=wording.R_PROGRESS_DONE, state="complete", expanded=False)
    ss.pop(problem_key, None)
    return True


def _run_attempt(ss) -> None:
    pair, anchor, candidate = _pair(ss), ss.get(ANCHOR_KEY), ss.get(CAND_KEY)
    if pair is None or anchor is None or candidate is None:
        return

    def work(say) -> None:
        attempt = reexec_logic.run_attempt(ss, pair, anchor, candidate, say)
        ss[VIEW_KEY] = attempt["seq"]

    _status(wording.RX_PROGRESS_TITLE, work, ss, "p5_problem")


def _confirm(ss) -> None:
    seq = ss.get("w5_confirming")
    attempt = next((a for a in (ss.get("reexec_session") or {}).get("attempts", []) if a["seq"] == seq), None)
    if attempt is None:
        return
    if _status(
        wording.RX_PROGRESS_CONFIRM,
        lambda say: reexec_logic.confirm_attempt(ss, attempt, bool(ss.get("w5_yield")), say),
        ss, "p5_problem",
    ):
        ss["w5_confirming"] = None
        ss["flash"] = wording.RX_CONFIRMED_SAVED.format(change=reexec_logic.change_text(ss["reexec_session"]["confirmed"]))
        st.rerun()  # the sidebar was drawn before the step finished


# --- Pieces of the page --------------------------------------------------------------------------------------


def _not_selectable(pool, stage: str) -> None:
    blocked = [c for c in pool if not c.selectable]
    if not blocked:
        return
    items = "".join(
        f'<div><span class="pv-mono pv-model">{escape(c.name)}</span> — {escape(c.reason or "")}</div>' for c in blocked
    )
    with st.container(key="card_notsel5"):
        st.html(
            f'<h2 class="pv-card-title">{escape(wording.RX_NOT_SELECTABLE_TITLE)}</h2>'
            f'<p class="pv-card-sub">{escape(wording.RX_NOT_SELECTABLE_SUB)}</p><div class="pv-notsel-grid">{items}</div>'
        )


def _choose(ss, phase1: dict, pairs: list[tuple[str, str]]) -> None:
    keys = [reexec_logic.pair_key(p) for p in pairs]
    with st.container(key="card_choose"):
        st.selectbox(
            wording.RX_PAIR, keys, index=None, key=PAIR_KEY, placeholder=wording.RX_PAIR_PLACEHOLDER,
            format_func=lambda k: wording.RX_PAIR_OPTION.format(pair=wording.P4_PAIR.format(a=k[0], b=k[2]), n=phase1[k]["outcome"]),
        )
        pair = _pair(ss)
        if pair is None:
            st.html(f'<p class="pv-note-line">{escape(wording.RX_RUN_NEEDS)}</p>')
            return
        stage = reexec_logic.pair_stage(phase1, pair)
        st.html(
            f'<div class="pv-fixed-stage"><span>{escape(wording.RX_STAGE_FIXED)}</span>'
            f"<b>{escape(wording.STAGE_NUMBERED[stage])}</b></div>"
        )
        st.radio(
            wording.RX_ANCHOR, list(pair), index=None, key=ANCHOR_KEY,
            format_func=lambda a: wording.RX_ANCHOR_OPTION.format(a=a, b=reexec_logic.other_label(pair, a)),
        )
        anchor = ss.get(ANCHOR_KEY)
        if anchor is None:
            st.html(f'<p class="pv-note-line">{escape(wording.RX_RUN_NEEDS)}</p>')
            return
        models = ss["inputs"]["pipelines"][anchor]
        pool = reexec_logic.candidate_pool(ss["inputs"], stage, models, anchor)
        names = reexec_logic.selectable_names(pool)
        if ss.get(CAND_KEY) not in names:
            ss[CAND_KEY] = None  # a candidate that is no longer offered is emptied, never swapped
        st.radio(wording.RX_CANDIDATE.format(stage=wording.STAGE_NAME[stage]), names, index=None, key=CAND_KEY)
        st.html(f'<p class="pv-note-line">{escape(wording.RX_SENTENCE.format(anchor=anchor, stage=wording.STAGE_NAME[stage]))}</p>')
        st.button(
            wording.RX_RUN, key="w5_run_button", type="primary", on_click=_request("w5_run"),
            disabled=ss.get(CAND_KEY) is None or bool(ss.get("pending")),
        )
    _not_selectable(pool, stage)


def _attempts_card(attempts: list[dict], phase1: dict, pair: tuple[str, str]) -> None:
    rows = []
    for position, attempt in enumerate(attempts, start=1):
        after = attempt["phase1"]
        if after.get("status") == "ran":
            outcome, k = wording.P4_OUTCOME.format(n=after["outcome"]), (
                wording.STAGE_NAME[after["k"].lower()] if after["k"] else wording.K_NONE
            )
        else:
            outcome, k = wording.P4_NA, NO_K
        rows.append(
            f"<tr><td>{escape(wording.RX_ATTEMPT_LABEL.format(n=position))}</td><td>{escape(attempt['anchor'])}</td>"
            f"<td class='pv-mono'>{escape(attempt['candidate'])}</td><td>{escape(outcome)}</td><td>{escape(k)}</td></tr>"
        )
    head = "".join(f"<th>{escape(name)}</th>" for name in wording.RX_ATTEMPT_COLUMNS)
    st.html(
        f'<h2 class="pv-card-title">{escape(wording.RX_ATTEMPTS_TITLE)}</h2>'
        f'<table class="pv-stage-table"><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table>'
    )


def _cell(value: float | None, over: bool) -> str:
    mark = components.over_tau_mark() if over else ""
    return f'<td class="pv-num pv-nowrap">{mark}<span class="pv-mono">{analysis_logic.fmt_nrmsd(value)}</span></td>'


def _result_table(view: reexec_logic.AttemptView) -> str:
    body = "".join(
        f"<tr><td>{escape(row.label)}</td>{_cell(row.before, row.before_over)}{_cell(row.after, row.after_over)}"
        f"<td class='pv-num pv-mono'>{escape(reexec_logic.fmt_change(row.change))}</td></tr>"
        for row in view.rows
    )
    outcome = (
        f"<tr><td>{escape(wording.RX_ROW_OUTCOME)}</td><td class='pv-num' colspan='1'>{escape(view.before_outcome)}</td>"
        f"<td class='pv-num' colspan='2'>{escape(view.after_outcome or '')}</td></tr>"
    )
    return (
        '<table class="pv-stage-table"><thead><tr>'
        f"<th>{escape(wording.P4_COL_STAGE)}</th><th class='pv-num'>{escape(wording.RX_COL_BEFORE)}</th>"
        f"<th class='pv-num'>{escape(wording.RX_COL_AFTER)}</th><th class='pv-num'>{escape(wording.RX_COL_CHANGE)}</th>"
        f"</tr></thead><tbody>{body}{outcome}</tbody></table>"
    )


def _result_card(ss, phase1: dict, attempt: dict, position: int, tau: dict, top: float) -> None:
    pair = tuple(attempt["pair"].split("-"))
    view = reexec_logic.attempt_view(phase1[attempt["pair"]], attempt["phase1"])
    other = reexec_logic.other_label(pair, attempt["anchor"])
    with st.container(key="card_result"):
        components.card_title(
            wording.RX_RESULT_TITLE.format(other=other),
            wording.RX_RESULT_SUB.format(
                n=position, candidate=attempt["candidate"], stage=wording.STAGE_NAME[attempt["stage"]],
                anchor=attempt["anchor"], pair=analysis_logic.pair_label(pair),
            ),
        )
        if not view.computable:
            components.message("todo", view.message or "", False)
            return
        table, chart = st.columns([3, 2])
        with table:
            st.html(_result_table(view))
        with chart:
            st.altair_chart(analysis_charts.attempt_chart(view, analysis_logic.tau_text(tau), top), width="stretch")
            st.html(f'<p class="pv-sr-only">{escape(wording.RX_CHART_ALT)}</p>')
        with st.expander(wording.RX_YIELD_OPEN, expanded=False):
            st.html(
                f'<p class="pv-note-line">{escape(wording.RX_YIELD_NOTE)}</p>'
                '<table class="pv-stage-table"><thead><tr>'
                f"<th class='pv-num'>{escape(wording.RX_YIELD_ORIGINAL.format(anchor=attempt['anchor']))}</th>"
                f"<th class='pv-num'>{escape(wording.RX_YIELD_SUBSTITUTED.format(anchor=attempt['anchor'], candidate=attempt['candidate']))}</th>"
                f"</tr></thead><tbody><tr><td class='pv-num pv-mono'>{run_logic.kwh_text(attempt['anchor_yield_kwh'])} kWh</td>"
                f"<td class='pv-num pv-mono'>{run_logic.kwh_text(attempt['yield_kwh'])} kWh</td></tr></tbody></table>"
            )


def _confirm_area(ss, attempt: dict) -> None:
    stage = wording.STAGE_NAME[attempt["stage"]]
    pair = analysis_logic.pair_label(tuple(attempt["pair"].split("-")))
    with st.container(key="card_confirm"):
        st.button(
            wording.RX_CONFIRM.format(candidate=attempt["candidate"]), key="w5_confirm_button",
            on_click=_ask(attempt["seq"]), disabled=bool(ss.get("pending")),
        )
        if ss.get("w5_confirming") != attempt["seq"]:
            return
        text = wording.RX_CONFIRM_ASK.format(candidate=attempt["candidate"], stage=stage, anchor=attempt["anchor"], pair=pair)
        existing = reexec_logic.confirmed_of(ss)
        if existing:
            text += " " + wording.RX_CONFIRM_REPLACES.format(change=reexec_logic.change_text(existing))
        st.html(f'<p class="pv-ask">{escape(text)}</p>')
        st.checkbox(wording.RX_YIELD_CHECK, key="w5_yield")
        yes, no = st.columns(2)
        with yes:
            st.button(wording.RX_CONFIRM_YES, key="w5_save_button", type="primary", on_click=_request("w5_do_confirm"))
        with no:
            st.button(wording.RX_CONFIRM_NO, key="w5_cancel_button", on_click=_cancel)


def _confirmed_card(ss, phase1: dict) -> None:
    reexec = reexec_logic.confirmed_of(ss)
    if not reexec:
        return
    pair = tuple(reexec["pair"])
    models = reexec["substituted_stage_model"]
    stage_key = reexec.get("stage")
    items = [
        (wording.RX_CONFIRMED_ANCHOR, str(reexec_logic.recorded(reexec, "anchor"))),
        (
            wording.RX_CONFIRMED_STAGE,
            wording.STAGE_NAME[stage_key.lower()] if stage_key else wording.RX_NOT_RECORDED,
        ),
        (wording.RX_CONFIRMED_CANDIDATE, str(reexec_logic.recorded(reexec, "candidate"))),
        (wording.RX_CONFIRMED_MODELS, " · ".join(models[f"{key}_model"] for key in wording.STAGE_KEYS)),
        (
            wording.RX_CONFIRMED_YIELD,
            f"{run_logic.kwh_text(reexec['annual_yield_kwh'])} kWh" if reexec.get("annual_yield_kwh") is not None else wording.RX_YIELD_NONE,
        ),
    ]
    rows = "".join(
        f'<div class="pv-kv pv-prov-row"><span>{escape(label)}</span><span class="pv-mono pv-prov-value">{escape(value)}</span></div>'
        for label, value in items
    )
    with st.container(key="card_confirmed"):
        components.card_title(wording.RX_CONFIRMED_TITLE, reexec_logic.change_text(reexec))
        st.html(f'<div class="pv-prov">{rows}</div>')
        after = reexec.get("phase1")
        if after and phase1.get(reexec_logic.pair_key(pair), {}).get("status") == "ran":
            view = reexec_logic.attempt_view(phase1[reexec_logic.pair_key(pair)], after)
            if view.computable:
                st.html(_result_table(view))
            else:
                components.message("todo", view.message or "", False)
        else:
            components.message("todo", f"{wording.RX_COL_AFTER}: {wording.RX_NOT_RECORDED}", False)


def _tag_optional() -> None:
    st.html(
        f'<span class="pv-tag pv-tag-optional" title="{escape(wording.RX_OPTIONAL_TITLE)}">{escape(wording.TAG_OPTIONAL)}</span>'
        f'<p class="pv-muted" style="margin:6px 0 0">{escape(wording.RX_INTRO)}</p>'
    )


# --- The page ----------------------------------------------------------------------------------------------------------


def render() -> None:
    ss = st.session_state
    components.step_header(5)
    _tag_optional()
    components.summary_strip()
    flags = state.flags(ss)
    phase1 = _phase1(ss)
    if not gating.is_unlocked(5, flags) or phase1 is None or not isinstance(ss.get("run"), run_logic.RunState):
        if flags.get("phase1_done") and not flags.get("has_k"):
            with st.container(key="card_empty5"):
                st.html(f'<p class="pv-empty">{escape(wording.RX_EMPTY)}</p>')
                st.page_link(components.PAGES["6"], label=wording.RX_GO_REPORT)
        else:
            components.locked_panel(5)
        return

    st.page_link(components.PAGES["3"], label=wording.P4_VIEW_RUN)
    if ss.pop("w5_run", False) and not ss.get("pending"):
        _run_attempt(ss)
    if ss.pop("w5_do_confirm", False) and not ss.get("pending"):
        _confirm(ss)

    pairs = reexec_logic.pairs_with_k(phase1)
    init_widgets(ss, [reexec_logic.pair_key(p) for p in pairs])
    _choose(ss, phase1, pairs)
    if ss.get("p5_problem"):
        components.show_problem(ss["p5_problem"])

    with st.container(key="card_disclaimer"):
        st.html(f'<p class="pv-disclaimer">{escape(wording.DISCLAIMER)}</p>')

    pair = _pair(ss)
    session_attempts = (ss.get("reexec_session") or {}).get("attempts", [])
    if pair is not None:
        attempts = reexec_logic.attempts_of(ss, pair)
        if attempts:
            seqs = [a["seq"] for a in attempts]
            if ss.get(VIEW_KEY) not in seqs:
                ss[VIEW_KEY] = seqs[-1]
            tau = analysis_logic.tau_of(phase1, ss["inputs"].get("tau"))
            with st.container(key="card_attempts"):
                _attempts_card(attempts, phase1, pair)
                st.segmented_control(
                    wording.RX_VIEW, seqs, key=VIEW_KEY, selection_mode="single",
                    format_func=lambda seq: wording.RX_ATTEMPT_LABEL.format(n=seqs.index(seq) + 1),
                )
            shown = next(a for a in attempts if a["seq"] == ss[VIEW_KEY])
            _result_card(ss, phase1, shown, seqs.index(shown["seq"]) + 1, tau, reexec_logic.axis_max(phase1, session_attempts))
            _confirm_area(ss, shown)
    _confirmed_card(ss, phase1)
    ss["w5_prev"] = {key: ss.get(key) for key in (PAIR_KEY, ANCHOR_KEY, CAND_KEY)}
