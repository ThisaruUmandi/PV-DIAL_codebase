"""Streamlit AppTest smoke tests (no browser). The database is pvdials_test."""

import html
import re
from pathlib import Path

from streamlit.testing.v1 import AppTest

from app import wording
from tests.interface.test_app_page3 import _clean


def _page_text(at) -> str:
    """All visible text from st.html blocks, markup removed."""
    joined = " ".join(el.value for el in at.get("html"))
    return html.unescape(re.sub(r"<[^>]+>", "", joined))


MAIN = str(Path(__file__).resolve().parents[2] / "app" / "main.py")


def test_main_runs_and_shows_home_without_an_exception():
    _clean()  # an empty store: Home says how to start
    at = AppTest.from_file(MAIN, default_timeout=30).run()
    assert not at.exception
    assert [t.value for t in at.title] == [wording.HOME_HEADLINE]
    text = _page_text(at)
    assert wording.HOME_NOT_SHOWN in text
    assert wording.EMPTY_PAST in text
    for pill in wording.STAGE_PILLS:
        assert pill in text
    assert wording.SIX_STEPS in text


def _locked_screen():
    import streamlit as st

    from app import state
    from app.screens import step_skeleton

    state.init_state(st.session_state)
    step_skeleton.render(3)


def test_a_locked_step_shows_its_reason_and_no_content():
    at = AppTest.from_function(_locked_screen, default_timeout=30).run()
    assert not at.exception
    assert [t.value for t in at.title] == ["Run & provenance"]
    text = _page_text(at)
    assert wording.LOCKED_HEADING in text and wording.LOCK_REASON[3] in text
    assert wording.PLACEHOLDER not in [m.value for m in at.markdown]


def _prompt_screen():
    import streamlit as st

    from app import components, state

    state.init_state(st.session_state)
    if "started" not in st.session_state:
        st.session_state["started"] = True
        state.set_progress(st.session_state, 4)
        st.session_state["w"] = "typed"
        state.request_change(st.session_state, "name", "renamed", widget_key="w", old_widget="kept")
    components.render_pending_change()
    st.write(f"RUN={st.session_state['run_done']}|W={st.session_state['w']}|NAME={st.session_state['name']}")


def _state_line(at) -> str:
    return next(m.value for m in at.markdown if m.value.startswith("RUN="))


def test_the_clear_prompt_cancel_restores_the_field_and_keeps_everything():
    at = AppTest.from_function(_prompt_screen, default_timeout=30).run()
    assert "This clears steps 2 to 6 of this analysis." in _page_text(at)
    at.button(key="pending_cancel").click().run()
    assert "This clears" not in _page_text(at) and wording.CANCELLED_NOTE in _page_text(at)
    assert _state_line(at) == "RUN=True|W=kept|NAME="


def test_the_clear_prompt_confirm_applies_the_change_and_clears_later_steps():
    at = AppTest.from_function(_prompt_screen, default_timeout=30).run()
    at.button(key="pending_confirm").click().run()
    assert "This clears" not in _page_text(at)
    assert _state_line(at) == "RUN=False|W=typed|NAME=renamed"
