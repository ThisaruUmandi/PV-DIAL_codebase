"""Home: what the tool shows and does not show, and how to start."""

from __future__ import annotations

import streamlit as st

from app import components, state, wording


def render() -> None:
    st.caption(wording.HOME_TITLE)
    st.title(wording.HOME_HEADLINE)
    st.write(wording.HOME_INTRO)

    st.subheader("What the analysis shows")
    for phase, text in wording.HOME_SHOWS:
        st.markdown(f"**{phase}.** {text}")
    st.info(wording.HOME_NOT_SHOWN)

    st.subheader("Before you start")
    for item in wording.HOME_BEFORE_YOU_START:
        st.markdown(f"- {item}")
    st.caption(wording.HOME_SAVED_NOTE)

    if st.button(wording.START_NEW_ANALYSIS, type="primary"):
        state.new_analysis(st.session_state)
        st.switch_page(components.PAGES["1"])

    st.subheader("The six steps")
    for step, title in wording.STEP_TITLES.items():
        optional = " (optional)" if step == 5 else ""
        st.markdown(f"**{step} · {title}{optional}.** {wording.STEP_SUMMARIES[step]}")
