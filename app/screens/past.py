"""Past analyses. The list itself arrives in a later step."""

from __future__ import annotations

import streamlit as st

from app import wording


def render() -> None:
    st.caption("Saved work")
    st.title(wording.PAST_TITLE)
    st.info(wording.EMPTY_PAST)
