"""Step 5 · Guided re-execution: the page (AppTest) on top of pvdials' O4Session. pvdials_test only.

The thesis inputs use the thesis time offset (0 h). A and B both first differ from each other at Decomposition, so
the pair A–B (and A–C) offer a decomposition substitution; 'disc' is B's own model, 'dirint' is C's.
"""

import copy
import html
import json
import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app import analysis_logic as al
from app import gating, wording
from app import reexec_logic as rx
from app import run_logic as rl
from pvdials.analysis import phase1_to_dict
from pvdials.guided_reexecution import DISCLAIMER, annual_yield_kwh
from pvdials.provenance.analyses import NOT_RECORDED, load_analysis, save_analysis
from pvdials.provenance.db import get_connection, is_reachable
from pvdials.types import Stage
from tests.interface.test_app_page3 import THESIS_FILE
from tests.interface.test_app_page4 import _chart_frames, _counts, _fresh_run, _session

pytestmark = [
    pytest.mark.skipif(not THESIS_FILE.exists(), reason="thesis weather file not present"),
    pytest.mark.skipif(not is_reachable(), reason="no Postgres reachable"),
]

HEX = re.compile(r"\b[0-9a-f]{32,}\b")
ANALYSIS = "p4-page"  # the id _fresh_run uses


def _ready(tau: float | None = None):
    """A fresh run with Phase 1 done: (run, inputs, session dict holding phase1)."""
    run, inputs = _fresh_run(tau=tau, analysis_id=ANALYSIS)
    ss = _session(run, inputs, ANALYSIS)
    al.run_phase1(ss)
    return run, inputs, ss


def _page5():
    import streamlit as st

    from app import components
    from app import state as app_state
    from app.screens import reexec_page

    app_state.init_state(st.session_state)
    for key in ("3", "4", "6"):
        components.PAGES[key] = f"step-{key}"
    st.page_link = lambda target, label=None, **kw: st.markdown(f"[{label}]({target})")
    if st.session_state.pop("_t_change", None):  # an edit on page 1 or 2, as those pages make it
        app_state.request_change(st.session_state, "tau", {"value": 0.2, "source": "user_entered"})
    components.render_pending_change()
    reexec_page.render()


def _text(at) -> str:
    joined = " ".join(el.value for el in at.get("html"))
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", joined)))


def _attempts_table(at) -> str:
    """The text of the attempts list, nothing else on the page."""
    found = re.search(r"Attempts in this session</h2>(<table.*?</table>)", _markup(at), re.DOTALL)
    assert found, "no attempts list on the page"
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", found.group(1))))


def _markup(at) -> str:
    return " ".join(el.value for el in at.get("html"))


def _open(run, inputs, ss, **extra) -> AppTest:
    at = AppTest.from_function(_page5, default_timeout=180)
    at.session_state["inputs"] = inputs
    at.session_state["analysis_id"] = ANALYSIS
    at.session_state["name"] = inputs["name"]
    at.session_state["config"] = inputs["pipelines"]
    at.session_state["tau"] = inputs["tau"]
    for flag in ("data_valid", "config_valid", "run_done"):
        at.session_state[flag] = True
    at.session_state["run"] = run
    at.session_state["phase1"] = ss["phase1"]
    at.session_state["phase1_done"] = True
    at.session_state["has_k"] = ss["has_k"]
    for key, value in extra.items():
        at.session_state[key] = value
    return at.run()


def _choose(at, pair="A-B", anchor="A", candidate="disc") -> AppTest:
    at.selectbox(key="w5_pair").set_value(pair).run()
    at.radio(key="w5_anchor").set_value(anchor).run()
    at.radio(key="w5_candidate").set_value(candidate).run()
    return at


def _attempt(at, pair="A-B", anchor="A", candidate="disc") -> AppTest:
    _choose(at, pair, anchor, candidate)
    at.button(key="w5_run_button").click().run()
    assert not at.exception
    return at


def _reexec_documents(set_name: str = "reexec") -> list[tuple[str, dict]]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT pr.config_label, pr.document FROM provenance_records pr JOIN analysis_records ar ON ar.record_id = pr.id "
            "WHERE ar.analysis_id = %s AND pr.execution_set = %s ORDER BY pr.created_at, pr.id",
            (ANALYSIS, set_name),
        )
        return list(cur.fetchall())


def _entities(document: dict) -> dict:
    return next(iter(document["bundle"].values()))["entity"]


def _models(document: dict) -> dict:
    config = _entities(document)["configuration"]
    return {key: config[f"{key}_model"] for key in wording.STAGE_KEYS}


# --- Which pairs, candidates and reasons --------------------------------------------------------------------------------


def test_only_pairs_with_a_k_are_offered_and_nothing_is_preselected():
    run, inputs, ss = _ready()
    ss["phase1"]
    at = _open(run, inputs, ss)
    assert not at.exception
    box = at.selectbox(key="w5_pair")
    assert list(box.options) == ["A – B · Outcome 3", "A – C · Outcome 3"] and box.value is None  # B–C has no k
    assert wording.RX_STAGE_FIXED not in _text(at)  # the stage shows once a pair is chosen
    assert at.get("radio") == [] or all(r.value is None for r in at.radio)
    assert not [b for b in at.button if b.key == "w5_run_button"]  # no run button until a candidate can be chosen


def test_when_no_pair_has_a_k_the_page_says_so_and_points_to_the_report():
    run, inputs, ss = _ready(tau=0.5)
    ss["phase1"]
    at = _open(run, inputs, ss)
    assert not at.exception
    text = _text(at)
    assert wording.RX_EMPTY in text
    assert wording.RX_GO_REPORT in " ".join(m.value for m in at.markdown)  # the link to the Report
    assert not at.selectbox and not at.radio and not at.button


def test_the_page_is_optional_and_shows_the_step_number_and_the_summary_strip():
    run, inputs, ss = _ready()
    ss["phase1"]
    at = _open(run, inputs, ss)
    text = _text(at)
    assert "Step 5 of 6" in text and wording.TAG_OPTIONAL in text and wording.RX_INTRO in text and "Pipeline A" in text


def test_candidates_are_in_pool_order_and_blocked_models_show_the_registrys_reason():
    run, inputs, ss = _ready()
    ss["phase1"]
    at = _open(run, inputs, ss)
    at.selectbox(key="w5_pair").set_value("A-B").run()
    assert wording.STAGE_NUMBERED["decomposition"] in _text(at) and wording.RX_STAGE_FIXED in _text(at)
    at.radio(key="w5_anchor").set_value("A").run()
    pool = rx.candidate_pool(inputs, "decomposition", inputs["pipelines"]["A"], "A")
    assert list(at.radio(key="w5_candidate").options) == [c.name for c in pool if c.selectable]
    assert [c.name for c in pool] == ["erbs", "erbs_driesse", "disc", "dirint", "dirindex", "boland", "louche", "orgill_hollands", "campbell_norman", "gti_dirint"]
    text = _text(at)
    assert wording.RX_NOT_SELECTABLE_TITLE in text and "already the model in A" in text
    for blocked in (c for c in pool if not c.selectable):
        assert blocked.name in text and (blocked.reason or "") in text
    assert at.radio(key="w5_candidate").value is None  # no candidate preselected


def test_the_pool_equals_the_sessions_own_alternatives_apart_from_the_anchors_own_model():
    run, inputs, ss = _ready()
    ss["phase1"]
    for stage in ("decomposition", "transposition", "temperature", "dc", "ac"):
        session = rx._session(run.live, ("A", "B"), "A", stage, lambda _id: None)
        theirs = [(c.name, c.selectable, c.reason) for c in session.alternatives()]
        ours = [(c.name, c.selectable, c.reason) for c in rx.candidate_pool(inputs, stage, inputs["pipelines"]["A"], "A")]
        assert [n for n, *_ in ours] == [n for n, *_ in theirs]  # same models, same order
        differing = {n for (n, ok, why), (_n, ok2, why2) in zip(ours, theirs, strict=True) if (ok, why) != (ok2, why2)}
        assert differing <= {inputs["pipelines"]["A"][stage]} | ({"pvwatts_dc"} if stage == "dc" else set())


# --- An attempt -----------------------------------------------------------------------------------------------------------


def test_every_number_on_the_page_equals_the_sessions_own_result_for_the_same_attempt():
    run, inputs, ss = _ready()
    phase1 = ss["phase1"]
    own = rx._session(run.live, ("A", "B"), "A", "decomposition", lambda _id: None).propose("disc")
    at = _attempt(_open(run, inputs, ss))
    attempt = at.session_state["reexec_session"]["attempts"][0]
    assert attempt["phase1"] == phase1_to_dict(own.phase1)  # exactly what the session returned
    text = _text(at)
    before = {m["stage"].lower(): m["nrmsd"] for m in phase1["A-B"]["metrics"]}
    for stage in al.STAGES:
        after = own.phase1.metrics[Stage[stage.upper()]].nrmsd
        row = next(r for r in rx.attempt_view(phase1["A-B"], attempt["phase1"]).rows if r.stage == stage)
        assert row.after == after and row.before == before[stage] and row.change == pytest.approx(after - before[stage])
        assert al.fmt_nrmsd(after) in text and rx.fmt_change(after - before[stage]) in text
    assert f"Outcome {own.phase1.outcome}, " in text
    assert attempt["yield_kwh"] == annual_yield_kwh(own.result)


def test_the_result_has_a_chart_beside_the_table_and_the_change_is_a_signed_number():
    run, inputs, ss = _ready()
    ss["phase1"]
    at = _attempt(_open(run, inputs, ss))
    text = _text(at)
    assert wording.RX_COL_BEFORE in text and wording.RX_COL_AFTER in text and wording.RX_COL_CHANGE in text
    assert "−" in text  # the decomposition nRMSD falls to zero: a true minus sign
    frame = next(f for chart in _chart_frames(at) for f in chart if "series" in f.columns)
    assert set(frame["series"]) == {wording.RX_COL_BEFORE, wording.RX_COL_AFTER} and len(frame) == 10
    assert list(frame["stage"][:2]) == [wording.STAGE_NAME["decomposition"]] * 2
    lowered = text.lower()
    for judging in ("better", "worse", "improv", "success", "fail", "reduc", "increas", "preferable than", "good", "bad"):
        assert judging not in lowered.replace("it does not identify which configuration is preferable", "")


def test_a_second_attempt_starts_from_the_frozen_anchor_not_from_the_first():
    run, inputs, ss = _ready()
    ss["phase1"]
    at = _attempt(_open(run, inputs, ss), candidate="disc")
    _attempt_two = _attempt(at, candidate="dirint")
    docs = _reexec_documents()
    anchor = inputs["pipelines"]["A"]
    attempt_models = [_models(d) for label, d in docs if label == "A_B_reexec"]
    assert len(attempt_models) == 2
    for models, expected in zip(attempt_models, ("disc", "dirint"), strict=True):
        differing = [s for s in wording.STAGE_KEYS if models[s] != anchor[s]]
        assert differing == ["decomposition"] and models["decomposition"] == expected  # one stage only, never chained
    direct = rx._session(run.live, ("A", "B"), "A", "decomposition", lambda _id: None)
    first, second = direct.propose("disc"), direct.retry("dirint")
    assert second.config.decomposition_model == "dirint" and first.config.decomposition_model == "disc"
    assert second.config.temperature_model == anchor["temperature"]


def test_an_attempt_under_one_pair_never_appears_under_another_and_they_are_listed_in_the_order_made():
    run, inputs, ss = _ready()
    ss["phase1"]
    at = _attempt(_open(run, inputs, ss), "A-B", "A", "disc")
    _attempt(at, "A-B", "A", "dirint")  # 'dirint' sorts before 'disc': the list must still show disc first
    _attempt(at, "A-C", "A", "disc")
    attempts = at.session_state["reexec_session"]["attempts"]
    assert [(a["pair"], a["candidate"]) for a in attempts] == [("A-B", "disc"), ("A-B", "dirint"), ("A-C", "disc")]
    assert [a["pair"] for a in rx.attempts_of(at.session_state, ("A", "B"))] == ["A-B", "A-B"]
    assert [a["candidate"] for a in rx.attempts_of(at.session_state, ("A", "C"))] == ["disc"]
    listing = _attempts_table(at)  # the page is on A–C now
    assert "dirint" not in listing and listing.count("Attempt 1") == 1 and "Attempt 2" not in listing
    at.selectbox(key="w5_pair").set_value("A-B").run()
    listing = _attempts_table(at)
    assert listing.index("disc") < listing.index("dirint") and "Attempt 2" in listing


def _attempt_domain(at):
    for el in at.get("vega_lite_chart"):
        spec = json.loads(el.proto.spec)
        layers = spec.get("layer", [])
        if any("series" in json.dumps(layer) for layer in layers):
            for layer in layers:
                scale = layer.get("encoding", {}).get("y", {}).get("scale", {})
                if "domain" in scale:
                    return scale["domain"]
    return None


def test_the_chart_axis_range_is_the_same_for_every_attempt_and_pair():
    run, inputs, ss = _ready()
    at = _attempt(_open(run, inputs, ss), "A-B", "A", "disc")
    first_alone = _attempt_domain(at)
    _attempt(at, "A-B", "A", "dirint")
    _attempt(at, "A-C", "A", "disc")
    seqs = {(a["pair"], a["candidate"]): a["seq"] for a in at.session_state["reexec_session"]["attempts"]}
    domains = []
    for pair, candidate in (("A-C", "disc"), ("A-B", "dirint"), ("A-B", "disc")):
        at.selectbox(key="w5_pair").set_value(pair).run()
        at.get("button_group")[0].set_value(seqs[(pair, candidate)]).run()
        domains.append(_attempt_domain(at))
    assert domains[0] and domains[0][0] == 0
    assert domains[0] == domains[1] == domains[2]  # every attempt, either pair: one range
    assert domains[0][1] >= first_alone[1]  # the range only grows when a larger value exists in the session


def test_the_one_plain_sentence_about_frozen_anchors_and_the_disclaimer_are_on_the_page():
    run, inputs, ss = _ready()
    ss["phase1"]
    at = _open(run, inputs, ss)
    assert DISCLAIMER in _text(at)  # exactly, before anything is chosen
    _choose(at)
    text = _text(at)
    assert "Every attempt starts from the original A and changes only Decomposition. Earlier attempts stay in the provenance record but never carry over." in text
    assert wording.DISCLAIMER == DISCLAIMER


def test_an_attempt_that_is_not_computable_shows_its_reason_with_no_k_and_no_change_column():
    run, inputs, ss = _ready()
    ss["phase1"]
    attempt = {
        "seq": 1, "pair": "A-B", "anchor": "A", "stage": "decomposition", "candidate": "disc",
        "phase1": phase1_to_dict("not computable — too few daylight samples at stage DC"),
        "yield_kwh": 1.0, "anchor_yield_kwh": 1.0,
    }
    at = _open(run, inputs, ss, reexec_session={"attempts": [attempt], "confirmed": None}, w5_pair="A-B")
    assert not at.exception
    text = _text(at)
    assert "Not computable — too few daylight samples at stage DC power" in text
    result = text.split("Disagreement with")[1]
    assert wording.RX_COL_CHANGE not in result and "k = " not in result  # no change column, no k
    assert not any("series" in f.columns for chart in _chart_frames(at) for f in chart)  # no attempt chart
    listing = _attempts_table(at)
    assert wording.P4_NA in listing and rx_dash() in listing and "k =" not in listing


def rx_dash() -> str:
    from app.screens.reexec_page import NO_K

    return NO_K


def test_an_unsuitable_substitution_gives_one_plain_message_and_no_attempt():
    run, inputs, ss = _ready()
    ss["phase1"]
    at = _open(run, inputs, ss)
    with pytest.raises(rx.ATTEMPT_FAILURES):
        rx.run_attempt(at.session_state, ("A", "B"), "A", "dirindex")  # not a pool-valid candidate for this file
    assert not rx.attempts_of(at.session_state, ("A", "B"))


# --- Yield, confirm ----------------------------------------------------------------------------------------------------------


def test_the_annual_yield_is_shown_on_request_side_by_side_and_matches_page_3():
    run, inputs, ss = _ready()
    ss["phase1"]
    at = _attempt(_open(run, inputs, ss))
    expander = next(e for e in at.expander if e.label == wording.RX_YIELD_OPEN)
    assert not expander.proto.expanded  # on request
    attempt = at.session_state["reexec_session"]["attempts"][0]
    assert attempt["anchor_yield_kwh"] == pytest.approx(run.annual_ac["A"], rel=1e-12)  # page 3's figure
    body = " ".join(str(getattr(c, "value", "")) for c in expander.children.values())
    assert run_kwh(attempt["anchor_yield_kwh"]) in body and run_kwh(attempt["yield_kwh"]) in body


def run_kwh(value: float) -> str:
    return rl.kwh_text(value)


def test_confirm_asks_first_and_saves_once_and_the_same_attempt_again_adds_no_rows():
    run, inputs, ss = _ready()
    ss["phase1"]
    at = _attempt(_open(run, inputs, ss))
    assert load_analysis(ANALYSIS)["reexec"] is None
    at.button(key="w5_confirm_button").click().run()
    assert "Save disc at Decomposition for A in A – B as the confirmed change?" in _text(at)
    assert load_analysis(ANALYSIS)["reexec"] is None  # asked, nothing saved yet
    at.button(key="w5_cancel_button").click().run()
    assert load_analysis(ANALYSIS)["reexec"] is None and "Save disc" not in _text(at)
    at.button(key="w5_confirm_button").click().run()
    at.button(key="w5_save_button").click().run()
    assert not at.exception
    row = load_analysis(ANALYSIS)
    assert row["status"] == "done" and row["reexec"]["candidate"] == "disc" and at.session_state["reexec_confirmed"] is True
    counts = _counts()
    at.button(key="w5_confirm_button").click().run()
    at.button(key="w5_save_button").click().run()  # confirming the same attempt again
    assert _counts() == counts and load_analysis(ANALYSIS)["reexec"] == row["reexec"]
    _attempt(at, "A-B", "A", "disc")  # running the same attempt again
    assert _counts() == counts


def test_a_confirmed_change_saves_the_anchor_the_stage_the_candidate_and_the_attempts_phase1():
    run, inputs, ss = _ready()
    phase1 = ss["phase1"]
    at = _attempt(_open(run, inputs, ss))
    attempt = at.session_state["reexec_session"]["attempts"][0]
    at.button(key="w5_confirm_button").click().run()
    at.button(key="w5_save_button").click().run()
    saved = load_analysis(ANALYSIS)["reexec"]
    assert (saved["anchor"], saved["stage"], saved["candidate"]) == ("A", "DECOMPOSITION", "disc")
    assert saved["phase1"] == attempt["phase1"]  # what is saved is that attempt's Phase 1
    assert saved["pair"] == ["A", "B"] and saved["config_label"] == "A_B_confirmed" and saved["disclaimer"] == DISCLAIMER
    assert saved["substituted_stage_model"]["decomposition_model"] == "disc"
    assert saved["annual_yield_kwh"] is None  # not asked for
    assert set(saved["phase1"]) == set(phase1["A-B"])  # the same shape as a phase1 pair


def test_the_confirmed_runs_stage_outputs_are_the_same_stored_payloads_as_the_attempts():
    run, inputs, ss = _ready()
    ss["phase1"]
    at = _attempt(_open(run, inputs, ss))
    before = _counts()
    at.button(key="w5_confirm_button").click().run()
    at.button(key="w5_save_button").click().run()
    after = _counts()
    assert after["stage_output_values"] == before["stage_output_values"]  # no new payload rows
    assert after["provenance_records"] == before["provenance_records"] + 1  # only the confirmed run's own record
    docs = dict(_reexec_documents())
    hashes = lambda doc: {s: _entities(doc)[s]["content_hash"] for s in wording.STAGE_KEYS}
    assert hashes(docs["A_B_confirmed"]) == hashes(docs["A_B_reexec"])
    assert _models(docs["A_B_confirmed"]) == _models(docs["A_B_reexec"])


def test_confirm_is_only_offered_for_an_attempt_run_in_this_session():
    run, inputs, ss = _ready()
    ss["phase1"]
    at = _open(run, inputs, ss)
    _choose(at)
    assert not [b for b in at.button if b.key == "w5_confirm_button"]  # nothing run yet, nothing to confirm
    fabricated = {"seq": 9, "pair": "A-B", "anchor": "A", "stage": "decomposition", "candidate": "disc", "phase1": {}}
    with pytest.raises(ValueError, match="Confirm is offered"):
        rx.confirm_attempt(at.session_state, fabricated, False)
    assert load_analysis(ANALYSIS)["reexec"] is None


def test_a_second_confirmation_asks_with_the_change_it_replaces_and_then_replaces_it():
    run, inputs, ss = _ready()
    ss["phase1"]
    at = _attempt(_open(run, inputs, ss), candidate="disc")
    at.button(key="w5_confirm_button").click().run()
    assert "This replaces" not in _text(at)  # nothing confirmed yet
    at.button(key="w5_save_button").click().run()
    _attempt(at, candidate="dirint")
    at.button(key="w5_confirm_button").click().run()
    assert "This replaces the confirmed change: A – B · Decomposition: disc." in _text(at)
    at.button(key="w5_save_button").click().run()
    assert load_analysis(ANALYSIS)["reexec"]["candidate"] == "dirint"
    assert "A – B · Decomposition: dirint" in _text(at)


def test_the_yield_is_stored_only_when_asked_for():
    run, inputs, ss = _ready()
    ss["phase1"]
    at = _attempt(_open(run, inputs, ss))
    at.button(key="w5_confirm_button").click().run()
    at.checkbox(key="w5_yield").set_value(True).run()
    at.button(key="w5_save_button").click().run()
    saved = load_analysis(ANALYSIS)["reexec"]
    assert saved["annual_yield_kwh"] == pytest.approx(at.session_state["reexec_session"]["attempts"][0]["yield_kwh"], rel=1e-9)


def test_a_row_saved_before_these_fields_existed_shows_not_recorded_for_the_missing_parts():
    run, inputs, ss = _ready()
    ss["phase1"]
    row = load_analysis(ANALYSIS)
    old = {
        "pair": ["A", "B"], "config_label": "A_B_confirmed", "annual_yield_kwh": 9800.0, "disclaimer": DISCLAIMER,
        "substituted_stage_model": {f"{k}_model": v for k, v in {**inputs["pipelines"]["A"], "decomposition": "disc"}.items()},
    }
    save_analysis(ANALYSIS, row["name"], "done", row["inputs"], phase1=row["phase1"], phase2=row["phase2"],
                  phase3=row["phase3"], reexec=old, pipelines=row["pipelines"], run_info=row["run_info"])
    at = _open(run, inputs, ss)
    assert not at.exception
    text = _text(at)
    assert text.count(NOT_RECORDED) >= 4  # anchor, stage, candidate and the after-substitution comparison
    assert "disc · isotropic · faiman · singlediode_cec · sandia" in text and "9,800.0 kWh" in text
    assert wording.RX_CONFIRMED_TITLE in text


def test_with_a_user_entered_tau_the_attempt_and_every_reexec_record_carry_it():
    run, inputs, ss = _ready(tau=0.01)
    ss["phase1"]
    at = _attempt(_open(run, inputs, ss))
    attempt = at.session_state["reexec_session"]["attempts"][0]
    assert attempt["phase1"]["tau"] == {"value": 0.01, "source": "user_entered"}
    at.button(key="w5_confirm_button").click().run()
    at.button(key="w5_save_button").click().run()
    saved = load_analysis(ANALYSIS)["reexec"]
    assert saved["phase1"]["tau"] == {"value": 0.01, "source": "user_entered"}
    documents = _reexec_documents()
    assert len(documents) == 2
    for _label, document in documents:
        site = _entities(document)["site_context"]
        assert float(site["tau_value"]["$"]) == 0.01 and site["tau_source"] == "user_entered"
    assert "0.01 (user_entered)" in _text(at)  # the summary strip
    labels = [v for chart in _chart_frames(at) for f in chart if "label" in f.columns for v in f["label"]]
    taus = [v for chart in _chart_frames(at) for f in chart if "tau" in f.columns for v in f["tau"]]
    assert "τ = 0.01 (user_entered)" in labels and 0.01 in taus  # the chart's τ line, from the run


# --- Gating, clearing, reopening ------------------------------------------------------------------------------------------------


def test_step_5_is_locked_until_phase_1_and_needs_a_k():
    run, inputs = _fresh_run(analysis_id=ANALYSIS)
    at = AppTest.from_function(_page5, default_timeout=120)
    at.session_state["inputs"], at.session_state["run"], at.session_state["analysis_id"] = inputs, run, ANALYSIS
    for flag in ("data_valid", "config_valid", "run_done"):
        at.session_state[flag] = True
    at.run()
    assert wording.LOCK_REASON[5] in _text(at) and not at.selectbox
    flags = {"phase1_done": True, "has_k": True}
    assert gating.is_unlocked(5, flags) and not gating.is_unlocked(5, {"phase1_done": True, "has_k": False})


def test_changing_an_earlier_input_after_an_attempt_warns_and_confirming_clears_the_page():
    run, inputs, ss = _ready()
    ss["phase1"]
    at = _attempt(_open(run, inputs, ss))
    at.session_state["_t_change"] = True
    at.run()
    assert "This clears steps 3 to 6 of this analysis." in _text(at)
    assert at.session_state["reexec_session"]["attempts"]  # nothing is cleared until the user confirms
    at.button(key="pending_confirm").click().run()
    assert at.session_state["reexec_session"] is None and at.session_state["reexec_confirmed"] is False
    assert at.session_state["phase1"] is None


def test_after_a_reopen_the_pipelines_are_rebuilt_without_new_rows_and_an_attempt_works():
    run, inputs, ss = _ready()
    phase1 = ss["phase1"]
    counts, records = _counts(), list(run.record_ids)
    reopened = rl.reopen(ANALYSIS)
    assert reopened.live is None
    at = _open(reopened, inputs, ss)
    messages: list[str] = []
    session = {"run": reopened, "inputs": inputs, "analysis_id": ANALYSIS, "name": inputs["name"], "phase1": phase1}
    attempt = rx.run_attempt(session, ("A", "B"), "A", "disc", messages.append)
    assert wording.P4_PROGRESS_REBUILD in messages and reopened.live.pipelines.record_ids == records
    after = _counts()
    assert after["analyses"] == counts["analyses"] and after["stage_output_values"] >= counts["stage_output_values"]
    assert attempt["phase1"]["outcome"] in (1, 2, 3)
    assert not at.exception


# --- Neutral marks, one set of stage names, plain page -------------------------------------------------------------------------


def test_over_tau_has_one_neutral_look_and_no_status_colours_or_icons():
    run, inputs, ss = _ready()
    ss["phase1"]
    at = _attempt(_open(run, inputs, ss))
    markup = _markup(at)
    assert 'class="pv-over"' in markup and wording.P4_OVER_TAU in _text(at)
    for banned in ("pv-status", "pv-icon-warn", "pv-icon-bad", "pv-icon-ok", "pv-msg-bad", "pv-msg-ok"):
        assert banned not in markup, banned
    assert not re.search(r"(red|green|#[8-9A-F]\w*1C1C|#14532D)", markup.replace("tired", ""))  # no status colours inline


def test_the_page_names_stages_only_from_the_one_set_and_has_no_hash_or_banned_word():
    run, inputs, ss = _ready()
    ss["phase1"]
    at = _attempt(_open(run, inputs, ss))
    text = _text(at)
    allowed = set(wording.STAGE_NAME_LIST) | set(wording.STAGE_NUMBERED.values())
    for cell in re.findall(r"<td>([^<]+)</td>", _markup(at)):
        if re.match(r"^\d · ", cell) or cell in {"Decomposition", "Transposition", "Cell temperature", "DC", "AC"}:
            assert cell in allowed, cell
    assert not HEX.findall(text.lower())
    low = text.lower()
    for word in ("recommend", "suggest", "optimal", "improv", "best", "error", "compensat", "winner", "rank", "sort"):
        assert word not in low, word
    assert not re.search(r"\bcorrect", low)


def test_no_sort_key_by_disagreement_exists_in_the_page_5_code():
    from pathlib import Path

    for name in ("app/reexec_logic.py", "app/screens/reexec_page.py"):
        source = Path(name).read_text(encoding="utf-8")
        assert not re.search(r"\b(sorted|\.sort|sort_values|nlargest|nsmallest|argsort|\.rank)\b\(?", source), name


def test_the_confirm_prompt_and_result_do_not_change_what_the_session_returned():
    run, inputs, ss = _ready()
    ss["phase1"]
    at = _attempt(_open(run, inputs, ss))
    snapshot = copy.deepcopy(at.session_state["reexec_session"]["attempts"])
    at.button(key="w5_confirm_button").click().run()
    assert at.session_state["reexec_session"]["attempts"] == snapshot  # asking changes nothing


# --- The command line and the interface save the same change ------------------------------------------------------------


def test_the_command_line_path_and_the_interface_make_the_same_records_and_the_same_saved_shape():
    """Both go through reexec_to_dict. Confirming A with 'disc' in the interface and asking the command line's
    step for the same substitution under another analysis id gives the same provenance record id and the
    same keys; recording is untouched, so no record id changes."""
    import dataclasses

    from pvdials.analysis import reexec_details_for, reexec_to_dict, step_reexecution

    run, inputs, ss = _ready()
    at = _attempt(_open(run, inputs, ss))
    at.button(key="w5_confirm_button").click().run()
    at.button(key="w5_save_button").click().run()
    app_saved = load_analysis(ANALYSIS)["reexec"]
    app_ids = {label: document for label, document in _reexec_documents("reexec")}
    live = run.live
    config = dataclasses.replace(
        rl.config_from_inputs(inputs), reexecution={"pair": "A-B", "anchor": "A", "candidate": "disc"}
    )
    results = al.phase1_results_from(ss["phase1"])
    save_analysis("p5-cli", "cli path", "site_done", inputs)
    final = step_reexecution(
        config, live.pipelines, results, live.hardware, live.site_result.ctx, live.defaults, "p5-cli", tau=live.tau
    )
    details = reexec_details_for(config, live.pipelines, results, final, live.site_result.ctx, live.defaults, live.tau)
    cli_saved = reexec_to_dict(final, details)
    assert set(cli_saved) == set(app_saved)
    for key in ("pair", "config_label", "substituted_stage_model", "anchor", "stage", "candidate", "disclaimer"):
        assert cli_saved[key] == app_saved[key], key
    same = lambda entry: {**entry, "pair": [entry["pair"][1]]}
    assert same(cli_saved["phase1"]) == same(app_saved["phase1"])  # the same comparison, whichever path made it
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT pr.id FROM provenance_records pr JOIN analysis_records ar ON ar.record_id = pr.id "
            "WHERE ar.analysis_id = %s AND pr.execution_set = 'reexec'",
            ("p5-cli",),
        )
        cli_record = {row[0] for row in cur.fetchall()}
        cur.execute(
            "SELECT pr.id FROM provenance_records pr JOIN analysis_records ar ON ar.record_id = pr.id "
            "WHERE ar.analysis_id = %s AND pr.execution_set = 'reexec' AND pr.config_label = 'A_B_confirmed'",
            (ANALYSIS,),
        )
        app_record = {row[0] for row in cur.fetchall()}
    assert cli_record == app_record and len(cli_record) == 1  # one and the same record
    assert app_ids  # the attempt's own record exists too


# --- Page 4: the fixes made in this pass ------------------------------------------------------------------------------


def _open4(run, inputs, ss, **extra):
    from tests.interface.test_app_page4 import _open as open4

    return open4(run, inputs, phase1=ss["phase1"], phase1_done=True, has_k=True, **extra)


def test_page_4_uses_one_neutral_look_for_over_tau_with_no_status_colour_or_icon():
    run, inputs, ss = _ready()
    at = _open4(run, inputs, ss)
    markup = _markup(at)
    stage_table = markup.split("Stage table against")[1].split("<table")[1].split("</table>")[0]
    assert 'class="pv-over"' in stage_table and 'class="pv-within"' in stage_table
    for banned in ("pv-status", "pv-icon-warn", "pv-icon-ok", "pv-icon-bad"):
        assert banned not in markup, banned
    assert markup.count('class="pv-over"') >= 2 + 2  # heat table (A–B has two stages over τ) and the stage table


def test_in_the_heatmaps_side_table_the_tag_stays_on_one_line_and_every_number_is_right_aligned():
    run, inputs, ss = _ready()
    markup = _markup(open4_at := _open4(run, inputs, ss))
    assert open4_at
    side = markup.split("<table")[1].split("</table>")[0]
    cells = re.findall(r'<td class="([^"]+)">(.*?)</td>', side)
    numeric = [(cls, body) for cls, body in cells if "pv-mono" in body]
    assert numeric and all("pv-num" in cls and "pv-nowrap" in cls for cls, _ in numeric)  # right-aligned, never wrapping
    tagged = [body for _cls, body in numeric if "pv-over" in body]
    assert tagged and all(re.match(r'<span class="pv-over">over τ</span><span class="pv-mono">', body) for body in tagged)
    css = (Path(__file__).resolve().parents[2] / "app" / "static" / "style.css").read_text(encoding="utf-8")
    assert ".pv-nowrap { white-space: nowrap; }" in css and ".pv-stage-table td.pv-num { text-align: right; }" in css
    assert "white-space: nowrap" in css.split(".pv-over {")[-1].split("}")[0]  # the tag itself does not wrap


def test_the_stage_bars_use_the_same_nrmsd_axis_range_for_all_three_pairs():
    run, inputs, ss = _ready()
    at = _open4(run, inputs, ss)

    def bar_domain():
        for el in at.get("vega_lite_chart"):
            spec = json.loads(el.proto.spec)
            for layer in spec.get("layer", []):
                encoding = layer.get("encoding", {})
                if layer.get("mark", {}).get("type") == "bar":
                    return encoding["x"]["scale"]["domain"]
        return None

    seen = []
    for pair in ("A-B", "A-C", "B-C"):
        at.get("button_group")[0].set_value(pair).run()
        seen.append(bar_domain())
    assert seen[0] and seen[0][0] == 0 and seen[0] == seen[1] == seen[2]


def test_there_is_room_above_every_chart_for_the_hover_toolbar():
    css = (Path(__file__).resolve().parents[2] / "app" / "static" / "style.css").read_text(encoding="utf-8")
    assert re.search(r'\[data-testid="stVegaLiteChart"\]\s*\{\s*padding-top:\s*30px', css)


def test_the_phase_buttons_use_uk_spelling():
    run, inputs, ss = _ready()
    at = _open4(run, inputs, ss)
    labels = [b.label for b in at.button]
    assert "Run Phase 1 — Localisation" in labels and not any("Localization" in label for label in labels)


# --- One set of stage names on the rendered pages ------------------------------------------------------------------------------


def test_stage_names_on_every_page_come_from_the_one_set():
    from tests.interface import test_app_page3 as page3

    allowed = set(wording.STAGE_NAME_LIST)
    numbered = set(wording.STAGE_NUMBERED.values())
    run, inputs, ss = _ready()

    # page 3: the stage buttons and the stage column of each pipeline card
    at3 = page3._open(inputs=inputs, run=run, run_done=True, analysis_id=ANALYSIS)
    assert list(at3.get("button_group")[0].options) == list(wording.STAGE_NAME_LIST)
    first_column = re.findall(r"<tr><td>([^<]+)</td><td class=\"pv-mono\">", _markup(at3))
    assert len(first_column) == 15 and set(first_column) == allowed
    chips = re.findall(r'<span class="pv-chip">([^<]+?)(?: <span|</span>)', _markup(at3))
    assert {c.strip() for c in chips} <= allowed | {wording.R_LINEAGE_WEATHER}

    # page 4: heatmap axis, the table beside it, the stage table, the Phase 3 table
    at4 = _open4(run, inputs, ss)
    heat = next(f for chart in _chart_frames(at4) for f in chart if "over_text" in f.columns)
    assert set(heat["stage"]) == allowed
    markup4 = _markup(at4)
    assert set(re.findall(r"<tr><td>([^<]+)</td><td class=\"pv-num", markup4)) <= allowed | numbered
    assert set(re.findall(r"<tr><td>(\d · [^<]+?)(?:<span|</td>)", markup4)) <= numbered

    # page 5: the stage column of the result table and the fixed stage
    at5 = _attempt(_open(run, inputs, ss))
    markup5 = _markup(at5)
    assert set(re.findall(r"<tr><td>(\d · [^<]+)</td>", markup5)) == numbered
    assert wording.STAGE_NUMBERED["decomposition"] in _text(at5)

    # Home: the pills
    home = AppTest.from_file(str(Path(__file__).resolve().parents[2] / "app" / "main.py"), default_timeout=60).run()
    pills = re.findall(r'<span class="pv-pill">([^<]+)</span>', _markup(home))
    assert pills == list(wording.STAGE_NAME_LIST)
    # quantity names stay in the units table, so "AC power" is a quantity here, never a stage
    assert wording.COLUMN_INFO["p_ac"][0] == "AC power" and "AC power" not in allowed
