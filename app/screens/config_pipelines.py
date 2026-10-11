"""Step 2 · Pipeline configuration, laid out as in the Configure mock-up.

Fifteen cells (A, B, C by five stages) plus the τ field. Each cell lists only models the module
allows, in pool order; the lists react to the other cells so no chain that Phase 3 could not
attribute can be built. Every change goes through state.request_change, so an edit after
Continue shows the clear warning first (F2.5).
"""

from __future__ import annotations

from html import escape

import streamlit as st

from app import components, config_logic, gating, state, wording
from pvdials.analysis import AnalysisError

TAU_KEY = "w2_tau"


def _key(label: str, stage: str) -> str:
    return f"w2_{label}_{stage}"


CELL_KEYS = [_key(label, stage) for label in config_logic.LABELS for stage in config_logic.STAGES]


# --- State plumbing --------------------------------------------------------------------------------


def init_widgets(ss) -> None:
    """Streamlit forgets a widget's state while another page shows, so a missing cell takes the
    value it had at the end of the last render (w2_prev, not a widget). A new analysis starts empty."""
    ss.setdefault("w2_prev", {})
    for key in CELL_KEYS:
        if key not in ss:
            ss[key] = ss["w2_prev"].get(key)
    if TAU_KEY not in ss:
        ss[TAU_KEY] = ss["w2_prev"].get(TAU_KEY, config_logic.default_tau())


def collect(ss) -> dict[str, dict[str, str | None]]:
    return {label: {stage: ss[_key(label, stage)] for stage in config_logic.STAGES} for label in config_logic.LABELS}


def _drop_values_no_longer_offered(ss, pools) -> None:
    """A cell whose model is no longer offered (another cell changed, or the pool did) is emptied
    before it is drawn; it is never swapped for something else."""
    for _ in range(2):  # a DC change can empty an AC cell, which can free a DC option
        config = collect(ss)
        for label in config_logic.LABELS:
            offered = config_logic.options(pools, config[label], [config[o] for o in config_logic.LABELS if o != label])
            for stage in config_logic.STAGES:
                if ss[_key(label, stage)] not in (None, *offered.models[stage]):
                    ss[_key(label, stage)] = None


def _edited(label: str, stage: str) -> None:
    ss = st.session_state
    key = _key(label, stage)
    state.request_change(ss, "config", collect(ss), widget_key=key, old_widget=ss["w2_prev"].get(key))


def _tau_edited() -> None:
    ss = st.session_state
    value = ss.get(TAU_KEY)
    if config_logic.tau_problem(value) is not None:
        return  # nothing usable to commit; the page says so and Continue stays blocked
    state.request_change(
        ss, "tau", config_logic.tau_from_value(value), widget_key=TAU_KEY, old_widget=ss["w2_prev"].get(TAU_KEY)
    )


def _reset_tau() -> None:
    ss = st.session_state
    old = ss.get(TAU_KEY)
    ss[TAU_KEY] = config_logic.default_tau()
    state.request_change(
        ss, "tau", config_logic.tau_from_value(ss[TAU_KEY]), widget_key=TAU_KEY, old_widget=old
    )


def _load_example(pools) -> None:
    ss = st.session_state
    example = config_logic.example_pipelines()
    if example is None:
        return
    config, left_out = config_logic.usable_example(pools, example)
    old = {key: ss.get(key) for key in CELL_KEYS}
    for label in config_logic.LABELS:
        for stage in config_logic.STAGES:
            ss[_key(label, stage)] = config[label][stage]
    ss["w2_example_left_out"] = left_out
    state.request_change(ss, "config", config, restore_many=old)


# --- Pieces of the page ------------------------------------------------------------------------------


def _not_selectable_card(pools) -> None:
    items = "".join(
        f'<div><span class="pv-mono pv-model">{escape(name)}</span>{escape(wording.C_STAGE_MARK.get(stage, ""))} — {escape(reason)}</div>'
        for stage, name, reason in config_logic.not_selectable(pools)
    )
    st.html(
        f'<h2 class="pv-card-title">{escape(wording.C_NOT_SELECTABLE_TITLE)}</h2>'
        f'<p class="pv-card-sub">{escape(wording.C_NOT_SELECTABLE_SUB)}</p>'
        f'<div class="pv-notsel-grid">{items}</div>'
        f'<p class="pv-note-line">{escape(wording.C_AC_FOLLOWS)}</p>'
    )


def _table(ss, pools) -> None:
    config = collect(ss)
    with st.container(key="cfg_table"):
        with st.container(key="cfg_head"):
            columns = st.columns([1.15, 1, 1, 1])
            columns[0].html(f'<div class="pv-th-plain">{escape(wording.C_STAGE_HEADER)}</div>')
            for column, label in zip(columns[1:], config_logic.LABELS, strict=True):
                column.html(f'<div class="pv-th-plain">{escape(wording.C_COLUMN.format(label=label))}</div>')
        for stage in config_logic.STAGES:
            with st.container(key=f"cfg_row_{stage}"):
                columns = st.columns([1.15, 1, 1, 1])
                tag = components.tag_html("differs") if config_logic.differs(config, stage) else ""
                columns[0].html(
                    f'<div class="pv-stage-cell"><span class="pv-stage-name">{escape(wording.C_STAGE_LABELS[stage])}</span>{tag}</div>'
                )
                notes: list[str] = []
                for column, label in zip(columns[1:], config_logic.LABELS, strict=True):
                    others = [config[o] for o in config_logic.LABELS if o != label]
                    offered = config_logic.options(pools, config[label], others)
                    notes += [n for n in offered.notes[stage] if n not in notes]
                    with column:
                        st.selectbox(
                            wording.C_ARIA_CELL.format(label=label, stage=wording.C_STAGE_LABELS[stage]),
                            offered.models[stage], index=None, key=_key(label, stage),
                            placeholder=wording.C_CHOOSE, label_visibility="collapsed",
                            on_change=_edited, args=(label, stage),
                        )
                for note in notes:
                    components.message("todo", note, False)


def _settings_card(ss) -> tuple[bool, dict | None]:
    components.card_title(wording.C_SETTINGS_TITLE, wording.C_SETTINGS_SUB)
    value = ss.get(TAU_KEY)
    problem = config_logic.tau_problem(value)
    tau = None if problem else config_logic.tau_from_value(value)
    tag = None if tau is None else ("default" if tau["source"] == "default" else "user")
    components.field_label(wording.C_TAU_LABEL, tag, hint=wording.HELP_TAU)
    field, button = st.columns([2, 1])
    with field:
        st.number_input(
            wording.C_TAU_LABEL, key=TAU_KEY, value=None, min_value=0.0, step=0.001, format="%g",
            label_visibility="collapsed", on_change=_tau_edited,
        )
    with button:
        st.button(
            wording.C_TAU_RESET, key="w2_tau_reset", on_click=_reset_tau,
            disabled=tau is None or tau["source"] == "default",
        )
    st.html(f'<p class="pv-note-line">{escape(wording.HELP_TAU)}</p>')
    if problem:
        components.message("bad", problem)
    return problem is None, tau


def _continue(ss, pools, config, tau) -> None:
    try:
        saved = config_logic.commit_page2(ss["analysis_id"], ss["inputs"], pools, config, tau)
    except (AnalysisError, KeyError, ValueError) as exc:
        components.show_problem(wording.C_SETUP_FAILED.format(detail=str(exc).rstrip(".")))
        return
    ss["inputs"] = saved
    ss["config"] = config
    ss["tau"] = tau
    ss["config_valid"] = True
    ss["flash"] = wording.C_SAVED_FLASH
    st.switch_page(components.PAGES["3"])


def render() -> None:
    ss = st.session_state
    components.step_header(2)
    flags = state.flags(ss)
    if not gating.is_unlocked(2, flags) or not ss.get("inputs"):
        components.locked_panel(2)
        return

    init_widgets(ss)
    inputs = ss["inputs"]
    pools = config_logic.pools_for(
        inputs["hardware"]["module_name"],
        inputs["site"]["mounting_geometry"],
        inputs["site"]["mounting_construction"],
        inputs["hardware"]["inverter_name"],
    )
    _drop_values_no_longer_offered(ss, pools)

    st.html(f'<p class="pv-muted" style="margin:0">{escape(wording.C_INTRO)}</p>')
    if config_logic.example_pipelines() is not None:
        with st.container(key="cfg_example"):
            st.button(wording.C_EXAMPLE_BUTTON, key="w2_example", on_click=_load_example, args=(pools,))
            st.html(f'<span class="pv-note-line">{escape(wording.C_EXAMPLE_NOTE)}</span>')
        left_out = ss.pop("w2_example_left_out", None)
        if left_out:
            components.message("warn", wording.C_EXAMPLE_SKIPPED.format(names=", ".join(left_out)))

    _table(ss, pools)
    with st.container(key="card_notsel"):
        _not_selectable_card(pools)
    with st.container(key="card_settings"):
        tau_ok, tau = _settings_card(ss)

    config = collect(ss)
    items = []
    for label in config_logic.LABELS:
        gaps = config_logic.missing_stages(config[label])
        detail = wording.C_STILL_NEEDS.format(stages=", ".join(wording.C_STAGE_LABELS[g].split(" · ")[1].lower() for g in gaps)) if gaps else ""
        items.append((not gaps, wording.C_CHECKLIST_PIPELINE.format(label=label), detail))
    items.append((tau_ok, wording.C_CHECKLIST_TAU, ""))
    ready = all(done for done, _l, _d in items) and not config_logic.problems(pools, config)

    with st.container(key="continue_row"):
        left, middle, right = st.columns([1, 2, 1.3])
        with left:
            st.page_link(components.PAGES["1"], label=wording.C_BACK)
        with middle:
            components.checklist(items, wording.D_CHECKLIST_TITLE, wording.D_CHECKLIST_READY)
        with right:
            if st.button(wording.C_CONTINUE, type="primary", key="w2_continue", disabled=not ready or bool(ss.get("pending"))):
                _continue(ss, pools, config, tau)

    ss["w2_prev"] = {key: ss.get(key) for key in (*CELL_KEYS, TAU_KEY)}
