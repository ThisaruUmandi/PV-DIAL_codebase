"""Placeholder for steps 1-6: heading, summary strip, lock panel."""

from __future__ import annotations

import streamlit as st

from app import components, gating, state, wording


def render(step: int) -> None:
    components.step_header(step)
    if step >= 3:
        components.summary_strip()
    if not gating.is_unlocked(step, state.flags(st.session_state)):
        components.locked_panel(step)
        return
    st.write(wording.PLACEHOLDER)
