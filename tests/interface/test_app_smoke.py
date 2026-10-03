"""Streamlit AppTest smoke tests (no browser). The database is pvdials_test."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from app import wording

MAIN = str(Path(__file__).resolve().parents[2] / "app" / "main.py")


def test_main_runs_and_shows_home_without_an_exception():
    at = AppTest.from_file(MAIN, default_timeout=30).run()
    assert not at.exception
    assert [t.value for t in at.title] == [wording.HOME_HEADLINE]
    assert wording.HOME_NOT_SHOWN in [i.value for i in at.info]


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
    assert [i.value for i in at.info] == [wording.LOCK_REASON[3]]
    assert wording.PLACEHOLDER not in [m.value for m in at.markdown]


def _preview_screen():
    import streamlit as st

    from app import components, state
    from app.screens import preview_controls

    state.init_state(st.session_state)
    preview_controls.render()
    components.render_pending_change()
    st.write(f"NAME={st.session_state['name']}|RUN={st.session_state['run_done']}")


def _name_and_run(at) -> str:
    return next(m.value for m in at.markdown if m.value.startswith("NAME="))


def test_changing_an_input_after_a_run_warns_and_cancel_keeps_everything():
    at = AppTest.from_function(_preview_screen, default_timeout=30).run()
    at.sidebar.slider[0].set_value(4).run()
    assert _name_and_run(at) == "NAME=|RUN=True"

    at.sidebar.text_input[0].set_value("renamed").run()
    assert [w.value for w in at.warning] == ["This clears steps 2 to 6 of this analysis."]
    assert _name_and_run(at) == "NAME=|RUN=True"  # not applied yet

    at.button(key="pending_cancel").click().run()
    assert not at.warning
    assert _name_and_run(at) == "NAME=|RUN=True"
    assert at.sidebar.text_input[0].value == ""  # the box is put back
    assert wording.CANCELLED_NOTE in [i.value for i in at.info]


def test_confirming_applies_the_change_and_clears_later_steps():
    at = AppTest.from_function(_preview_screen, default_timeout=30).run()
    at.sidebar.slider[0].set_value(4).run()
    at.sidebar.text_input[0].set_value("renamed").run()
    at.button(key="pending_confirm").click().run()
    assert not at.warning
    assert _name_and_run(at) == "NAME=renamed|RUN=False"
