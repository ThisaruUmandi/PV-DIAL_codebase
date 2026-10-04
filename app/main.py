"""PV-DIALS interface entry point.

Run from the repository root:  streamlit run app/main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from app import components, state, store, wording
from app.screens import config_pipelines, data_site, home, past, step_skeleton


def _step_page(step: int):
    def page() -> None:
        if step == 1:
            data_site.render()
        elif step == 2:
            config_pipelines.render()
        else:
            step_skeleton.render(step)

    page.__name__ = f"step_{step}"
    return page


def build_pages() -> dict[str, st.Page]:
    pages = {"home": st.Page(home.render, title=wording.HOME_TITLE, url_path="home", default=True)}
    for step, title in wording.STEP_TITLES.items():
        pages[str(step)] = st.Page(_step_page(step), title=title, url_path=f"step{step}")
    pages["past"] = st.Page(past.render, title=wording.PAST_TITLE, url_path="past")
    return pages


def main() -> None:
    st.set_page_config(page_title=wording.APP_TITLE, layout="wide")
    state.init_state(st.session_state)

    pages = build_pages()
    components.register_pages(pages)
    selected = st.navigation(list(pages.values()), position="hidden")
    current = next(key for key, page in pages.items() if page.title == selected.title)

    connected = store.db_reachable()
    components.sidebar(current, connected)

    if not connected:
        components.show_problem(wording.DB_UNREACHABLE)
        st.stop()

    components.flash()
    components.render_pending_change()
    selected.run()


main()
