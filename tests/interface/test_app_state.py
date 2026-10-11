"""Clear-on-change rules and the confirm / cancel flow, on a plain dict."""

from app import state, wording


def _fresh() -> dict:
    ss: dict = {}
    state.init_state(ss)
    return ss


def test_change_with_nothing_downstream_applies_silently():
    ss = _fresh()
    assert state.request_change(ss, "name", "first") is True
    assert ss["name"] == "first" and ss["pending"] is None


def test_change_with_results_downstream_is_held_with_the_warning():
    ss = _fresh()
    state.set_progress(ss, 4)
    applied = state.request_change(ss, "name", "new name")
    assert applied is False
    assert ss["name"] == ""  # not applied yet
    assert ss["pending"]["message"] == "This clears steps 2 to 6 of this analysis."


def test_confirm_applies_and_clears_every_later_step():
    ss = _fresh()
    state.set_progress(ss, 5)
    state.request_change(ss, "name", "new")
    state.confirm_pending(ss)
    assert ss["name"] == "new" and ss["pending"] is None
    assert not (ss["config_valid"] or ss["run_done"] or ss["phase1_done"] or ss["reexec_confirmed"])
    assert ss["run"] is None and ss["phase1"] is None
    assert state.steps_with_results(ss) == []


def test_cancel_keeps_everything_and_restores_the_widget_value():
    ss = _fresh()
    state.set_progress(ss, 4)
    ss["name"] = "kept"
    ss["w"] = "typed over"
    before = {k: v for k, v in ss.items() if k not in ("pending", "w")}
    state.request_change(ss, "name", "typed over", widget_key="w")
    state.cancel_pending(ss)
    assert ss["w"] == "kept" and ss["pending"] is None
    assert {k: v for k, v in ss.items() if k not in ("pending", "w")} == before


def test_tau_change_clears_steps_3_to_6_only_and_page_1_change_keeps_tau():
    ss = _fresh()
    ss["tau"] = {"value": 0.093, "source": "default"}
    state.set_progress(ss, 4)
    state.request_change(ss, "tau", {"value": 0.2, "source": "user_entered"})
    assert ss["pending"]["message"] == wording.clears_message(3)
    state.confirm_pending(ss)
    assert ss["tau"]["source"] == "user_entered"
    assert ss["config_valid"] is False  # step 2 is reopened: it has to be confirmed (Continue) again
    assert ss["run"] is None and ss["phase1"] is None

    state.set_progress(ss, 4)
    state.request_change(ss, "name", "x")
    state.confirm_pending(ss)
    assert ss["tau"] == {"value": 0.2, "source": "user_entered"}  # page-1 change keeps τ


def test_message_names_the_first_step_that_holds_something():
    ss = _fresh()
    ss["reexec_confirmed"] = True  # only re-execution (and so the report) exists downstream
    state.request_change(ss, "config", {"A": {}})
    assert ss["pending"]["message"] == "This clears steps 5 to 6 of this analysis."


def test_init_state_never_overwrites_and_new_analysis_resets():
    ss = _fresh()
    ss["name"] = "keep me"
    state.init_state(ss)
    assert ss["name"] == "keep me"
    state.new_analysis(ss)
    assert ss["name"] == "" and ss["analysis_id"] is None


def test_summary_parts_say_not_set_yet_and_never_invent():
    ss = _fresh()
    parts = dict(state.summary_parts(ss))
    assert all(v == wording.NOT_SET_YET for k, v in parts.items() if k != "Analysis" or not ss["name"])
    ss["name"] = "colombo"
    ss["weather"] = {"name": "tmy.csv"}
    ss["config"] = {"A": {"decomposition": "erbs", "transposition": "isotropic",
                          "temperature": "faiman", "dc": "singlediode_cec", "ac": "sandia"}}
    ss["tau"] = {"value": 0.093, "source": "default"}
    parts = dict(state.summary_parts(ss))
    assert parts["Analysis"] == "colombo" and parts["Weather file"] == "tmy.csv"
    assert parts["Pipeline A"] == "erbs · isotropic · faiman · singlediode_cec · sandia"
    assert parts["Pipeline B"] == wording.NOT_SET_YET
    assert parts["τ"] == "0.093 (default)"
