"""Past analyses. The list itself arrives in a later step."""

from __future__ import annotations

import streamlit as st

from app import components, wording


def render() -> None:
    components.eyebrow(wording.SAVED_WORK)
    st.title(wording.PAST_TITLE)
    components.note(wording.EMPTY_PAST)
