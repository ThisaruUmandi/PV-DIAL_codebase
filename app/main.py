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

from app import components, session_load, state, store, wording
from app.page_map import build_pages

# the URL carries the analysis (a) and, for one opened from Past analyses, its mode (ro), so a browser
# refresh keeps both; nothing else is kept there
_QUERY_KEYS = ("a", "ro")


def _wanted_query(ss) -> dict[str, str]:
    if not session_load.valid_id(ss.get("analysis_id")):
        return {}
    return {"a": ss["analysis_id"], **({"ro": "1"} if ss.get("readonly") else {})}


def _sync_query(ss) -> None:
    wanted = _wanted_query(ss)
    if {key: st.query_params.get(key) for key in _QUERY_KEYS if key in st.query_params} != wanted:
        st.query_params.from_dict(wanted)


def _restore_from_url(ss) -> str | None:
    """The first run of a session: a refreshed page arrives with ?a=<id>. Take that analysis (and its
    mode) back from the store. An id that is malformed or unknown gives Home with one plain message.
    Returns the page key to go to, or None."""
    ss["url_checked"] = True
    raw = st.query_params.get("a")
    if raw is None:
        return None
    try:
        if not session_load.valid_id(raw):
            raise session_load.LoadError(wording.PAST_NOT_FOUND)
        if st.query_params.get("ro") == "1":
            session_load.open_readonly(ss, raw)
            return None
        return "1" if session_load.restore(ss, raw).message else None
    except session_load.LoadError as exc:
        ss["flash"] = str(exc)
        st.query_params.clear()
        return "home"


def main() -> None:
    st.set_page_config(page_title=wording.APP_TITLE, layout="wide")
    state.init_state(st.session_state)

    pages = build_pages()
    components.register_pages(pages)
    selected = st.navigation(list(pages.values()), position="hidden")
    current = next(key for key, page in pages.items() if page.title == selected.title)

    connected = store.db_reachable()
    if connected and not st.session_state.get("url_checked"):
        go = _restore_from_url(st.session_state)
        if go is not None:
            st.switch_page(components.PAGES[go])
    _sync_query(st.session_state)
    components.sidebar(current, connected)

    if not connected:
        components.show_problem(wording.DB_UNREACHABLE)
        st.stop()

    components.flash()
    components.render_pending_change()
    selected.run()


main()
