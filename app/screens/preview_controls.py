"""Skeleton preview only — removed in S3.

Lets the gating and the clear warning be tried before any page has content:
a slider sets how far the analysis has got, and a text box goes through the
same request_change path every real input will use.
"""

from __future__ import annotations

import streamlit as st

from app import state

NAME_WIDGET = "preview_name_widget"


def _on_name_change() -> None:
    new = st.session_state[NAME_WIDGET]
    if new != st.session_state.get("name"):
        state.request_change(st.session_state, "name", new, widget_key=NAME_WIDGET)


def _on_progress_change() -> None:
    state.set_progress(st.session_state, st.session_state["preview_progress"])


def render() -> None:
    with st.sidebar.expander("Skeleton preview only — removed in S3"):
        st.caption(
            "Pretend the analysis has got this far, then change the analysis name "
            "to see the warning before later steps are cleared."
        )
        st.slider(
            "Progress (0 nothing … 5 re-execution confirmed)",
            0, state.PROGRESS_MAX, 0, key="preview_progress", on_change=_on_progress_change,
        )
        st.session_state.setdefault(NAME_WIDGET, st.session_state.get("name", ""))
        st.text_input("Analysis name", key=NAME_WIDGET, on_change=_on_name_change)
