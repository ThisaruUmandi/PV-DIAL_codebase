"""Which screen each page shows. A step opened from Past analyses (read-only) shows one plain panel instead of its controls."""

from __future__ import annotations

import streamlit as st

from app import components, wording
from app.screens import (
    analysis_page,
    config_pipelines,
    data_site,
    home,
    past,
    reexec_page,
    report_page,
    run_page,
    step_skeleton,
)


def step_page(step: int):
    def page() -> None:
        if st.session_state.get("readonly") and step < 6:
            components.step_header(step)
            components.readonly_panel(step)
        elif step == 1:
            data_site.render()
        elif step == 2:
            config_pipelines.render()
        elif step == 3:
            run_page.render()
        elif step == 4:
            analysis_page.render()
        elif step == 5:
            reexec_page.render()
        elif step == 6:
            report_page.render()
        else:
            step_skeleton.render(step)

    page.__name__ = f"step_{step}"
    return page


def build_pages() -> dict[str, st.Page]:
    pages = {"home": st.Page(home.render, title=wording.HOME_TITLE, url_path="home", default=True)}
    for step, title in wording.STEP_TITLES.items():
        pages[str(step)] = st.Page(step_page(step), title=title, url_path=f"step{step}")
    pages["past"] = st.Page(past.render, title=wording.PAST_TITLE, url_path="past")
    return pages
