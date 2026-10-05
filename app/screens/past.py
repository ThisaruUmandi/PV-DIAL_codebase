"""Past analyses, laid out as in the Past mock-up: search, status, order, the list, and what each action does.

Rows come from the store and are listed by date or name only; nothing here sorts or marks an analysis by how
much its pipelines disagree.
"""

from __future__ import annotations

from html import escape

import streamlit as st

from app import components, past_logic, wording
from app.screens import past_rows

SEARCH_KEY, STATUS_KEY, ORDER_KEY = "w7_search", "w7_status", "w7_order"
WIDTHS = [2.5, 1.15, 1.95, 1.45, 2.5]
_STATUS_LABELS = dict(wording.PAST_FILTERS)
_ORDER_LABELS = dict(wording.PAST_ORDERS)


def init_widgets(ss) -> None:
    """Streamlit forgets a widget's state while another page shows, so a missing choice takes the value it
    had at the end of the last render (w7_prev). First time: no search, all statuses, newest first."""
    prev = ss.setdefault("w7_prev", {})
    for key, default in ((SEARCH_KEY, ""), (STATUS_KEY, "all"), (ORDER_KEY, "newest")):
        if key not in ss:
            ss[key] = prev.get(key, default)
    if ss[STATUS_KEY] is None:  # pressing the chosen button again clears it; that is the same as All
        ss[STATUS_KEY] = "all"


def _controls(ss) -> None:
    with st.container(key="past_controls"):
        search, status, order = st.columns([4, 2.4, 1.4], gap="small", vertical_alignment="bottom")
        with search:
            components.field_label(wording.PAST_SEARCH)
            st.text_input(
                wording.PAST_SEARCH, key=SEARCH_KEY, placeholder=wording.PAST_SEARCH_PLACEHOLDER,
                label_visibility="collapsed",
            )
        with status:
            components.field_label(wording.PAST_STATUS)
            st.segmented_control(
                wording.PAST_STATUS, list(_STATUS_LABELS), format_func=_STATUS_LABELS.get, key=STATUS_KEY,
                selection_mode="single", label_visibility="collapsed",
            )
        with order:
            components.field_label(wording.PAST_ORDER)
            st.selectbox(
                wording.PAST_ORDER, list(_ORDER_LABELS), format_func=_ORDER_LABELS.get, key=ORDER_KEY,
                label_visibility="collapsed",
            )


def _footer() -> None:
    boxes = "".join(
        f'<div class="pv-foot-box"><b>{escape(lead)}</b> {escape(rest)}</div>' for lead, rest in wording.PAST_FOOTER
    )
    st.html(f'<div class="pv-foot-grid">{boxes}</div><p class="pv-muted pv-foot-note">{escape(wording.PAST_ORDER_NOTE)}</p>')


def render() -> None:
    ss = st.session_state
    init_widgets(ss)
    past_rows.run_pending(ss)

    with st.container(key="past_head"):
        left, right = st.columns([3, 1.4], gap="small", vertical_alignment="bottom")
        with left:
            components.eyebrow(wording.SAVED_WORK)
            st.title(wording.PAST_TITLE)
            st.html(f'<p class="pv-muted" style="margin:0">{escape(wording.PAST_INTRO)}</p>')
        with right, st.container(key="past_new"):
            components.start_new_analysis("past_start")
    if ss.get("past_problem"):
        components.show_problem(ss["past_problem"])

    _controls(ss)
    search, status, order = ss[SEARCH_KEY].strip(), ss[STATUS_KEY], ss[ORDER_KEY]
    rows = past_logic.past_rows(search or None, status, order)

    if not rows:
        filtered = bool(search) or status != "all"
        everything = past_logic.past_rows() if filtered else []
        components.note(wording.PAST_NO_MATCH if everything else wording.EMPTY_PAST)
    else:
        with st.container(key="past_list"):
            past_rows.header(WIDTHS, wording.PAST_HEADERS, "past_header")
            past_rows.render_rows(rows, WIDTHS, "past", with_duplicate=True)
    _footer()
    ss["w7_prev"] = {key: ss[key] for key in (SEARCH_KEY, STATUS_KEY, ORDER_KEY)}
