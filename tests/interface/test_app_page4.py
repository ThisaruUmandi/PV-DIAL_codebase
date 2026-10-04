"""Step 4 · Analysis, Phase 1: the logic on the thesis run and the page (AppTest). pvdials_test only.

The thesis inputs use the thesis time offset (0 h), so the numbers are the section D numbers.
"""

import copy
import html
import re

import pytest
from streamlit.testing.v1 import AppTest

from app import analysis_logic as al
from app import gating, state, wording
from app import run_logic as rl
from pvdials.analysis import (
    NOT_RUN_OUTCOME_1,
    phase1_to_dict,
    phase2_to_dict,
    phase3_pair_to_dict,
    step_disagreement_check,
    step_phase2,
    step_phase3,
)
from pvdials.provenance.analyses import load_analysis
from pvdials.provenance.db import get_connection, is_reachable
from tests.interface.test_app_page3 import THESIS_FILE, _clean, _inputs

pytestmark = [
    pytest.mark.skipif(not THESIS_FILE.exists(), reason="thesis weather file not present"),
    pytest.mark.skipif(not is_reachable(), reason="no Postgres reachable"),
]

STAGES = al.STAGES
# section D, nRMSD by stage (decomposition / transposition / temperature / DC / AC)
THESIS_NRMSD = {
    "A-B": (0.1235, 0.0036, 0.1534, 0.0173, 0.0172),
    "A-C": (0.1396, 0.0065, 0.1946, 0.0225, 0.0223),
}
HEX = re.compile(r"\b[0-9a-f]{32,}\b")


def _inputs_with_tau(value: float | None) -> dict:
    inputs = _inputs()
    if value is not None:
        inputs["tau"] = {"value": value, "source": "user_entered"}
    return inputs


def _session(run, inputs, analysis_id) -> dict:
    """The parts of session state that Phase 1 reads and writes, as a plain dict."""
    ss = {"run": run, "inputs": inputs, "analysis_id": analysis_id, "name": inputs["name"]}
    for key in ("phase1", "phase2", "phase3"):
        ss[key] = None
    return ss


def _counts() -> dict:
    with get_connection() as conn, conn.cursor() as cur:
        out = {}
        for table in ("analyses", "analysis_records", "provenance_records", "stage_output_values"):
            cur.execute(f"SELECT count(*) FROM {table}")
            out[table] = cur.fetchone()[0]
    return out


@pytest.fixture(scope="module")
def thesis():
    """The thesis pipelines run once; each test that presses Phase 1 uses its own copy of the session."""
    _clean()
    inputs = _inputs_with_tau(None)
    return rl.run_pipelines(inputs, "p4-thesis"), inputs


def _fresh_run(tau: float | None = None, analysis_id: str = "p4-page"):
    _clean()
    inputs = _inputs_with_tau(tau)
    return rl.run_pipelines(inputs, analysis_id), inputs


# --- Phase 1 on the thesis run: section D ---------------------------------------------------------------------------


def test_thesis_phase1_gives_the_section_d_values_outcomes_and_k(thesis):
    run, inputs = thesis
    ss = _session(run, inputs, "p4-thesis")
    phase1 = al.run_phase1(ss)
    assert list(phase1) == ["A-B", "A-C", "B-C"]
    for key, expected in THESIS_NRMSD.items():
        found = [m["nrmsd"] for m in phase1[key]["metrics"]]
        assert found == pytest.approx(expected, abs=5e-5), key
        assert phase1[key]["outcome"] == 3 and phase1[key]["k"] == "DECOMPOSITION"
    bc = phase1["B-C"]
    assert bc["outcome"] == 1 and bc["k"] is None
    assert max(m["nrmsd"] for m in bc["metrics"]) == pytest.approx(0.0706, abs=5e-5)
    assert all(e["tau"] == {"value": 0.093, "source": "default"} for e in phase1.values())


def test_thesis_k_bands(thesis):
    run, inputs = thesis
    views = {v.key: v for v in al.phase1_view(al.run_phase1(_session(run, inputs, "p4-thesis")))}
    assert views["A-B"].band == "k stays at Decomposition for any τ below 0.1235"
    assert views["A-C"].band == "k stays at Decomposition for any τ below 0.1396"
    assert views["B-C"].band == "No stage is over τ for any τ at or above 0.0706"
    assert (views["A-B"].outcome_text, views["B-C"].outcome_text) == (wording.OUTCOME_TEXT[3], wording.OUTCOME_TEXT[1])
    assert views["A-B"].k_text == "k = Decomposition" and views["B-C"].k_text == "k = none"


def test_phase1_saves_the_dicts_the_command_line_would_and_leaves_the_run_alone(thesis):
    run, inputs = thesis
    before = load_analysis("p4-thesis")
    ss = _session(run, inputs, "p4-thesis")
    al.run_phase1(ss)
    row = load_analysis("p4-thesis")
    assert row["status"] == "phase1_done" and row["phase1"] == ss["phase1"]
    live = run.live
    results = step_disagreement_check(live.pipelines, live.site_result.ctx, live.defaults, tau=live.tau)
    assert row["phase1"] == {f"{a}-{b}": phase1_to_dict(r) for (a, b), r in results.items()}
    assert row["run_info"] == before["run_info"] and row["pipelines"] == before["pipelines"]  # nothing wiped
    assert row["inputs"] == before["inputs"]
    assert row["phase2"] is None  # Phase 2 can run, so Phase 1 does not settle it
    assert row["phase3"] == {"B-C": phase3_pair_to_dict(NOT_RUN_OUTCOME_1)}  # the outcome-1 pair is settled
    assert ss["phase1_done"] is True and ss["has_k"] is True


def test_stored_phase1_dicts_survive_the_round_trip_and_phase2_agrees_from_rebuilt_objects(thesis):
    run, inputs = thesis
    ss = _session(run, inputs, "p4-thesis")
    phase1 = al.run_phase1(ss)
    for entry in phase1.values():
        assert phase1_to_dict(al.phase1_from_dict(entry)) == entry
    live = run.live
    live_results = step_disagreement_check(live.pipelines, live.site_result.ctx, live.defaults, tau=live.tau)
    rebuilt = al.phase1_results_from(phase1)
    assert list(rebuilt) == list(live_results)
    from_live = step_phase2(live_results)
    from_rebuilt = step_phase2(rebuilt)
    assert from_live is not None and from_rebuilt is not None
    assert from_rebuilt == from_live  # the objects, value for value
    dict_live, dict_rebuilt = phase2_to_dict(from_live, live_results), phase2_to_dict(from_rebuilt, rebuilt)
    assert dict_rebuilt == dict_live
    for stage in from_live.mean_nrmsd:
        assert from_rebuilt.mean_nrmsd[stage] == from_live.mean_nrmsd[stage]
        assert from_rebuilt.max_nrmsd[stage] == from_live.max_nrmsd[stage]
        assert from_rebuilt.delta[stage] == from_live.delta[stage]
    for pair in from_live.pair_nrmsd:
        assert from_rebuilt.pair_nrmsd[pair] == from_live.pair_nrmsd[pair]


def test_running_phase1_again_gives_the_same_values_and_adds_no_rows(thesis):
    run, inputs = thesis
    ss = _session(run, inputs, "p4-thesis")
    first = copy.deepcopy(al.run_phase1(ss))
    counts = _counts()
    second = al.run_phase1(_session(run, inputs, "p4-thesis"))
    assert second == first and _counts() == counts


# --- Rebuilding the live objects ---------------------------------------------------------------------------------------


def test_rebuild_live_writes_nothing_and_gives_the_same_record_ids(thesis):
    run, inputs = thesis
    before_row, counts = load_analysis("p4-thesis"), _counts()
    live = rl.rebuild_live(inputs, "p4-thesis")
    assert live.pipelines.record_ids == run.record_ids  # same provenance records
    assert _counts() == counts
    after = load_analysis("p4-thesis")
    assert after["updated_at"] == before_row["updated_at"] and after["run_info"] == before_row["run_info"]
    assert live.pipelines.annual_yield_kwh == run.live.pipelines.annual_yield_kwh


def test_phase1_after_a_reopen_rebuilds_the_pipelines_with_a_progress_message_and_changes_only_the_phase_sections(thesis):
    run, inputs = thesis
    expected = al.run_phase1(_session(run, inputs, "p4-thesis"))
    counts, before = _counts(), load_analysis("p4-thesis")
    reopened = rl.reopen("p4-thesis")  # no live objects, as for a stored analysis
    assert reopened.live is None
    messages: list[str] = []
    ss = _session(reopened, inputs, "p4-thesis")
    again = al.run_phase1(ss, messages.append)
    assert wording.P4_PROGRESS_REBUILD in messages and messages[-1] == wording.P4_PROGRESS_SAVE
    assert again == expected and reopened.live is not None
    assert _counts() == counts  # no duplicate rows
    after = load_analysis("p4-thesis")
    assert after["run_info"] == before["run_info"] and after["pipelines"] == before["pipelines"]
    assert after["id"] == "p4-thesis" and after["phase1"] == expected


# --- States that follow from Phase 1 alone -------------------------------------------------------------------------------


def test_when_no_pair_exceeds_tau_phase_2_and_3_are_settled_with_the_shapes_the_command_line_stores():
    run, inputs = _fresh_run(tau=0.5)
    ss = _session(run, inputs, "p4-page")
    phase1 = al.run_phase1(ss)
    assert all(e["outcome"] == 1 and e["k"] is None for e in phase1.values())
    live = run.live
    results = step_disagreement_check(live.pipelines, live.site_result.ctx, live.defaults, tau=live.tau)
    cli2 = phase2_to_dict(step_phase2(results), results)
    cli3 = {
        f"{a}-{b}": phase3_pair_to_dict(v)
        for (a, b), v in step_phase3(live.pipelines, results, live.hardware, live.site_result.ctx, live.defaults, "p4-page").items()
    }
    assert ss["phase2"] == cli2 == {"status": "not run", "reason": "no pair exceeds tau"}
    assert ss["phase3"] == cli3 and set(cli3) == {"A-B", "A-C", "B-C"}
    row = load_analysis("p4-page")
    assert row["phase2"] == cli2 and row["phase3"] == cli3
    assert ss["has_k"] is False and ss["phase1_done"] is True
    assert al.phase2_blocked_reason(ss["phase2"]) == wording.PHASE2_NOT_RUN
    assert al.phase3_blocked_reason(phase1) == wording.PHASE3_OUTCOME_1
    assert all(al.outcome_one_text(e) == wording.PHASE3_OUTCOME_1 for e in ss["phase3"].values())


def test_with_a_pair_over_tau_phase_2_and_3_are_not_settled_early(thesis):
    run, inputs = thesis
    ss = _session(run, inputs, "p4-thesis")
    phase1 = al.run_phase1(ss)
    assert al.phase2_blocked_reason(ss["phase2"]) is None and al.phase3_blocked_reason(phase1) is None
    assert al.phase3_eligible(phase1) == [("A", "B"), ("A", "C")]  # outcome 3 pairs, in fixed order


def test_outcome_2_with_a_user_entered_tau():
    run, inputs = _fresh_run(tau=0.01)
    phase1 = al.run_phase1(_session(run, inputs, "p4-page"))
    views = {v.key: v for v in al.phase1_view(phase1)}
    assert views["A-B"].outcome == 2 and views["A-C"].outcome == 2 and views["B-C"].outcome == 3
    assert views["A-B"].outcome_text == "Exceeds τ; final AC above τ"
    assert views["A-B"].sentence.endswith("At the final AC output the difference is still above τ.")
    assert all(e["tau"] == {"value": 0.01, "source": "user_entered"} for e in phase1.values())
    assert al.tau_text(al.tau_of(phase1)) == "0.01 (user_entered)"


# --- The page (AppTest) ----------------------------------------------------------------------------------------------------


def _page4():
    import streamlit as st

    from app import components, state
    from app.screens import analysis_page

    state.init_state(st.session_state)
    components.PAGES["3"] = "step-3"
    components.PAGES["4"] = "step-4"
    st.page_link = lambda target, label=None, **kw: st.markdown(f"[{label}]({target})")
    components.render_pending_change()
    analysis_page.render()


def _text(at) -> str:
    joined = " ".join(el.value for el in at.get("html"))
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", joined)))


def _open(run, inputs, done: bool = True, **extra) -> AppTest:
    at = AppTest.from_function(_page4, default_timeout=120)
    at.session_state["inputs"] = inputs
    at.session_state["analysis_id"] = "p4-page"
    at.session_state["name"] = inputs["name"]
    at.session_state["config"] = inputs["pipelines"]
    at.session_state["tau"] = inputs["tau"]
    at.session_state["data_valid"] = done
    at.session_state["config_valid"] = done
    at.session_state["run"] = run
    at.session_state["run_done"] = done
    for key, value in extra.items():
        at.session_state[key] = value
    return at.run()


def test_before_phase_1_the_page_says_so_and_phase_2_and_3_are_locked():
    run, inputs = _fresh_run()
    at = _open(run, inputs)
    assert not at.exception
    text = _text(at)
    assert "No analysis yet. Run Phase 1 to see where the pipelines first differ by more than τ." in text
    assert wording.P4_LOCKED in text
    assert not at.button(key="w4_p1").disabled and at.button(key="w4_p2").disabled and at.button(key="w4_p3").disabled
    assert "Outcome" not in text


def test_step_4_is_locked_until_the_pipelines_have_run():
    run, inputs = _fresh_run()
    at = _open(run, inputs, done=False)
    assert not at.exception and not at.button
    assert wording.LOCK_REASON[4] in _text(at)


def test_pressing_phase_1_shows_the_pair_cards_the_heatmap_and_the_tables_with_the_same_numbers():
    run, inputs = _fresh_run()
    at = _open(run, inputs)
    at.button(key="w4_p1").click().run()
    assert not at.exception
    ss = at.session_state
    views = al.phase1_view(ss["phase1"])
    text = _text(at)
    assert text.index("A – B") < text.index("A – C") < text.index("B – C")  # fixed order, never by disagreement
    for view in views:
        assert wording.P4_OUTCOME.format(n=view.outcome) in text and view.outcome_text in text
        assert view.k_text in text and view.sentence in text and view.band in text
        for stage in STAGES:
            assert al.fmt_nrmsd(view.nrmsd[stage]) in text  # heat table and stage table text
    heat, outline = _chart_frames(at)[0]
    assert len(heat) == 15 and list(heat["pair"].unique()) == [v.label for v in views]  # fixed pair order
    for view in views:  # the heatmap's own data holds every number the tables print
        for index, stage in enumerate(STAGES):
            row = heat[(heat["pair"] == view.label) & (heat["stage"] == wording.P4_HEAT_AXIS[index])].iloc[0]
            assert row["text"] == al.fmt_nrmsd(view.nrmsd[stage])
            assert bool(row["over"]) == (stage in view.over)
            assert row["nrmsd"] == pytest.approx(view.nrmsd[stage], abs=1e-12)
    assert len(outline) == sum(len(v.over) for v in views)  # one outline per cell over τ, no more
    bars = _chart_frames(at)[1][0]
    first = next(v for v in views if v.computable)
    assert list(bars["text"]) == [al.fmt_nrmsd(first.nrmsd[s_]) for s_ in STAGES]  # the stage chart: the selected pair
    assert text.count(wording.P4_OVER_TAU) >= sum(len(v.over) for v in views)  # the words, not only an outline
    assert ss["phase1_done"] is True and ss["has_k"] is True


def test_the_page_reads_tau_and_its_source_from_the_run():
    run, inputs = _fresh_run(tau=0.01)
    at = _open(run, inputs)
    at.button(key="w4_p1").click().run()
    text = _text(at)
    assert "τ = 0.01 (user_entered)" in text and "0.093" not in text.split("Stage table against")[0].split("Disagreement map")[1]
    assert "Exceeds τ; final AC above τ" in text and "is still above τ" in text


def test_a_pair_that_is_not_computable_shows_its_reason_and_no_k():
    run, inputs = _fresh_run()
    stored = al.run_phase1(_session(run, inputs, "p4-page"))
    stored["A-C"] = {"status": "not computable", "reason": "not computable — too few daylight samples at stage DC"}
    at = _open(run, inputs, phase1=stored, phase1_done=True, has_k=True)
    assert not at.exception
    markup = " ".join(el.value for el in at.get("html"))
    text = _text(at)
    assert "Not computable — too few daylight samples at stage DC power" in text
    card = re.search(r'pv-pair-head">A – C</div>(.*?)</div>', markup + "</div>", re.DOTALL)  # nothing of a k in this card
    assert card and "k =" not in card.group(1)
    assert text.count("k = ") == 2  # the other two pairs only
    assert wording.P4_NA in text


def test_buttons_after_phase_1_when_no_pair_exceeds_tau_say_why_beside_them():
    run, inputs = _fresh_run(tau=0.5)
    at = _open(run, inputs)
    at.button(key="w4_p1").click().run()
    text = _text(at)
    assert wording.PHASE2_NOT_RUN in text and wording.PHASE3_OUTCOME_1 in text
    assert at.button(key="w4_p2").disabled and at.button(key="w4_p3").disabled
    assert wording.P4_COMING not in text


def test_gating_step_5_needs_a_k_and_the_report_needs_phase_1():
    run, inputs = _fresh_run()
    at = _open(run, inputs)
    flags = state.flags(at.session_state)
    assert not gating.is_unlocked(5, flags) and not gating.is_unlocked(6, flags)
    at.button(key="w4_p1").click().run()
    flags = state.flags(at.session_state)
    assert gating.is_unlocked(5, flags) and gating.is_unlocked(6, flags)
    run2, inputs2 = _fresh_run(tau=0.5)  # no pair has a k
    at2 = _open(run2, inputs2)
    at2.button(key="w4_p1").click().run()
    flags2 = state.flags(at2.session_state)
    assert gating.is_unlocked(6, flags2) and not gating.is_unlocked(5, flags2)


def test_definitions_method_and_full_table_are_closed_expanders_with_the_agreed_texts():
    run, inputs = _fresh_run()
    at = _open(run, inputs)
    at.button(key="w4_p1").click().run()
    labels = [e.label for e in at.expander]
    assert labels == [wording.P4_DEFS_OPEN, wording.P4_METHOD_OPEN, wording.P4_FULL_OPEN]
    assert not any(e.proto.expanded for e in at.expander)
    defs = _text_of(at.expander[0])
    for line in (wording.HELP_NRMSD, wording.HELP_TAU, wording.HELP_K, wording.HELP_PHI, wording.HELP_SHARE,
                 "φ can be negative. The stages still add up to RMSD(A,B)."):
        assert line in defs
    assert "Systematic share" in _text_of(at.expander[2])


def _chart_frames(at) -> list[list]:
    """The data each chart was given, decoded from the page itself (one list of frames per chart)."""
    import pyarrow as pa

    return [
        [pa.ipc.open_stream(d.data.data).read_all().to_pandas() for d in el.proto.datasets]
        for el in at.get("vega_lite_chart")
    ]


def _text_of(block) -> str:
    out = []
    for child in block.children.values():
        out.append(str(getattr(child, "value", "")))
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", " ".join(out))))


def test_tooltips_come_from_wording_and_the_page_has_no_hash_ranking_or_banned_words():
    run, inputs = _fresh_run()
    at = _open(run, inputs)
    at.button(key="w4_p1").click().run()
    markup = " ".join(el.value for el in at.get("html"))
    for hint in (wording.HELP_K, wording.HELP_NRMSD, wording.HELP_TAU):
        assert html.escape(hint) in markup
    text = _text(at).lower()
    assert not HEX.findall(text)
    for word in ("rank", "winner", "highest", "lowest", "best", "recommend", "suggest", "optimal", "improv", "error", "compensat"):
        assert word not in text, word
    assert not re.search(r"\bcorrect", text)
