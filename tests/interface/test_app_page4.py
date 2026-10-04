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
def _thesis_state():
    """The thesis pipelines run once; each test that presses Phase 1 uses its own copy of the session."""
    _clean()
    inputs = _inputs_with_tau(None)
    return rl.run_pipelines(inputs, "p4-thesis"), inputs


@pytest.fixture
def thesis(_thesis_state):
    """The run above. Tests that start from a clean database remove its rows; when that has happened the
    same run is made again (provenance ids are content hashes, so the records come out identical)."""
    run, inputs = _thesis_state
    if load_analysis("p4-thesis") is None:
        run = rl.run_pipelines(inputs, "p4-thesis")
    return run, inputs


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


# --- Phase 2: propagation profile (6b) -------------------------------------------------------------------------------------


def _press_phase_1_then_2(tau: float | None = None):
    run, inputs = _fresh_run(tau=tau)
    at = _open(run, inputs)
    at.button(key="w4_p1").click().run()
    return at


def test_phase_2_values_are_the_mean_max_and_change_of_the_three_pairs_nrmsd(thesis):
    run, inputs = thesis
    ss = _session(run, inputs, "p4-thesis")
    phase1 = al.run_phase1(ss)
    phase2 = al.run_phase2(ss)
    view = al.phase2_view(phase2)
    assert view.ran and view.pair_labels == ["A-B", "A-C", "B-C"]
    # independent arithmetic on the stored Phase 1 values (not the backend's own)
    stored = {key: {m["stage"].lower(): m["nrmsd"] for m in phase1[key]["metrics"]} for key in phase1}
    previous = 0.0
    for stage in STAGES:
        values = [stored[key][stage] for key in ("A-B", "A-C", "B-C")]
        mean = sum(values) / 3
        assert view.pairs["A-B"][stage] == stored["A-B"][stage] and view.pairs["B-C"][stage] == stored["B-C"][stage]
        assert view.mean[stage] == pytest.approx(mean, rel=1e-12) and view.max[stage] == max(values)
        assert view.delta[stage] == pytest.approx(mean - previous, abs=1e-12)  # the first stage is compared with 0
        previous = mean
    assert view.max["temperature"] == pytest.approx(0.1946, abs=5e-5)  # the A–C temperature value of section D


def test_phase_2_is_saved_with_the_shape_the_command_line_stores_and_keeps_the_other_sections(thesis):
    run, inputs = thesis
    ss = _session(run, inputs, "p4-thesis")
    al.run_phase1(ss)
    before = load_analysis("p4-thesis")
    al.run_phase2(ss)
    row = load_analysis("p4-thesis")
    live = run.live
    results = step_disagreement_check(live.pipelines, live.site_result.ctx, live.defaults, tau=live.tau)
    assert row["phase2"] == ss["phase2"] == phase2_to_dict(step_phase2(results), results)
    assert row["status"] == "phase2_done"
    for section in ("phase1", "phase3", "run_info", "pipelines", "inputs"):
        assert row[section] == before[section], section


def test_phase_2_needs_no_live_pipelines_and_running_it_again_changes_nothing(thesis, monkeypatch):
    run, inputs = thesis
    first_ss = _session(run, inputs, "p4-thesis")
    al.run_phase1(first_ss)
    first = copy.deepcopy(al.run_phase2(first_ss))
    reopened = rl.reopen("p4-thesis")
    monkeypatch.setattr(rl, "rebuild_live", lambda *a, **k: pytest.fail("Phase 2 must not rebuild the pipelines"))
    counts = _counts()
    ss = _session(reopened, inputs, "p4-thesis")
    ss["phase1"] = first_ss["phase1"]
    assert al.run_phase2(ss) == first and _counts() == counts


def test_pressing_phase_2_draws_the_profile_with_a_table_of_the_same_numbers():
    at = _press_phase_1_then_2()
    assert not at.button(key="w4_p2").disabled
    at.button(key="w4_p2").click().run()
    assert not at.exception
    view = al.phase2_view(at.session_state["phase2"])
    text = _text(at)
    assert wording.P4_P2_TITLE in text and wording.P4_P2_NOTE in text
    rows = al.phase2_rows(view)
    for row in rows:
        for cell in (*row["pairs"], row["mean"], row["max"], row["delta"]):
            assert cell in text
    line = next(frames for frames in _chart_frames(at) if "pair" in frames[0] and frames[0]["pair"].nunique() == 3 and len(frames[0]) == 15 and "over" not in frames[0])[0]
    for key in view.pair_labels:
        label = wording.P4_PAIR.format(a=key[0], b=key[2])
        for index, stage in enumerate(STAGES):
            cell = line[(line["pair"] == label) & (line["stage"] == wording.P4_HEAT_AXIS[index])].iloc[0]
            assert cell["nrmsd"] == pytest.approx(view.pairs[key][stage], abs=1e-12) and cell["text"] == rows[index]["pairs"][view.pair_labels.index(key)]
    assert at.session_state["phase2"] == load_analysis("p4-page")["phase2"]


def test_the_pairs_are_told_apart_by_dash_and_marker_as_well_as_colour_and_tau_is_drawn_from_the_run():
    import altair as alt  # noqa: F401  (the chart is an Altair chart)

    from app import analysis_charts as charts

    run, inputs = _fresh_run(tau=0.01)
    ss = _session(run, inputs, "p4-page")
    al.run_phase1(ss)
    view = al.phase2_view(al.run_phase2(ss))
    tau = al.tau_of(ss["phase1"])
    spec = charts.propagation_chart(view, tau["value"], al.tau_text(tau)).to_dict()
    text = str(spec)
    layer = {key: next(layer for layer in spec["layer"] if key in layer["encoding"]) for key in ("strokeDash", "shape")}
    dashes = layer["strokeDash"]["encoding"]["strokeDash"]["scale"]
    shapes = layer["shape"]["encoding"]["shape"]["scale"]
    colours = next(layer for layer in spec["layer"] if layer["mark"]["type"] == "line")["encoding"]["color"]["scale"]
    assert len({str(d) for d in dashes["range"]}) == 3 and len(set(shapes["range"])) == 3 and len(set(colours["range"])) == 3
    assert dashes["domain"] == ["A – B", "A – C", "B – C"]  # fixed order
    datasets = spec["datasets"]
    assert any(row.get("tau") == 0.01 for rows in datasets.values() for row in rows)  # τ comes from the run, not the code
    assert "τ = 0.01 (user_entered)" in text
    pipelines_look = {"circle", "square", "triangle-up"}
    assert not pipelines_look & set(shapes["range"])  # not confused with the A, B, C look of page 3


def test_when_no_pair_exceeds_tau_the_not_run_state_shows_at_once_without_a_chart():
    at = _press_phase_1_then_2(tau=0.5)
    text = _text(at)
    assert wording.PHASE2_NOT_RUN in text
    assert at.button(key="w4_p2").disabled
    assert wording.P4_P2_TITLE not in text and len(at.get("vega_lite_chart")) == 2  # heatmap and stage bars only
    assert at.session_state["phase2"] == {"status": "not run", "reason": "no pair exceeds tau"}


def test_a_failed_check_reason_and_a_negative_change_are_shown_as_stored():
    run, inputs = _fresh_run()
    ss = _session(run, inputs, "p4-page")
    phase1 = al.run_phase1(ss)
    failed = _open(run, inputs, phase1=phase1, phase1_done=True, has_k=True,
                   phase2={"status": "not run", "reason": "a pipeline failed its checks"})
    assert wording.P4_PHASE2_NOT_RUN_FAILED in _text(failed) and failed.button(key="w4_p2").disabled
    stored = al.run_phase2(ss)
    stored["delta"][2]["value"] = -0.0123  # a stage whose mean falls
    shown = _open(run, inputs, phase1=phase1, phase1_done=True, has_k=True, phase2=stored)
    assert "−0.0123" in _text(shown) and "-0.0123" not in _text(shown)


def test_a_rerun_of_the_page_draws_the_stored_results_and_computes_nothing(monkeypatch):
    at = _press_phase_1_then_2()
    at.button(key="w4_p2").click().run()
    before = _text(at)

    def refuse(*args, **kwargs):
        pytest.fail("a phase was recomputed on a rerun")

    monkeypatch.setattr(al, "step_disagreement_check", refuse)
    monkeypatch.setattr(al, "step_phase2", refuse)
    monkeypatch.setattr(al, "step_phase3", refuse)
    at.run()
    assert not at.exception and _text(at) == before
    at.get("button_group")[0].set_value("A-C")
    at.run()
    assert not at.exception and wording.P4_P2_TITLE in _text(at)


def test_phase_2_page_has_no_hash_and_no_banned_word():
    at = _press_phase_1_then_2()
    at.button(key="w4_p2").click().run()
    text = _text(at).lower()
    assert not HEX.findall(text)
    for word in ("recommend", "suggest", "optimal", "improv", "best", "error", "compensat", "winner", "rank"):
        assert word not in text, word
    assert not re.search(r"\bcorrect", text)


# --- Phase 3: contribution of each stage (6c) -------------------------------------------------------------------------------

# section D, φ final (W) by stage, and the totals they add up to
THESIS_PHI = {
    "A-B": ([17.52, 6.10, 50.23, 0.02, 0.0], 73.88),
    "A-C": ([21.51, 7.80, 66.12, 0.0, 0.0], 95.44),
}


def _stored_phase1(run, inputs) -> dict:
    return al.run_phase1(_session(run, inputs, "p4-thesis"))


def _phase3_entry(phi_final, rmsd=None, pair=("A", "B")) -> dict:
    """A stored Phase 3 entry, as phase3_pair_to_dict writes it, for the pages that show constructed numbers."""
    from pvdials.analysis import ALL_STAGES  # noqa: F401  (stage names as the backend writes them)

    names = ["DECOMPOSITION", "TRANSPOSITION", "TEMPERATURE", "DC", "AC"]
    total = sum(phi_final) if rmsd is None else rmsd
    stage_list = lambda values: [{"stage": n, "value": v} for n, v in zip(names, values, strict=True)]
    return {
        "status": "ran", "pair": list(pair), "rmsd_ab": total,
        "phi_ab": stage_list(phi_final), "phi_ba": stage_list(phi_final), "phi_final": stage_list(phi_final),
        "share": stage_list([v / total for v in phi_final]), "signed_phi": stage_list(phi_final),
        "v_ab": [], "v_ba": [], "signed_v": [],
    }


def test_thesis_phase_3_gives_the_section_d_contributions_and_they_add_up_to_rmsd(thesis):
    run, inputs = thesis
    ss = _session(run, inputs, "p4-thesis")
    al.run_phase1(ss)
    messages: list[str] = []
    phase3 = al.run_phase3(ss, messages.append)
    for key, (expected, total) in THESIS_PHI.items():
        entry = phase3[key]
        assert entry["status"] == "ran"
        found = [item["value"] for item in entry["phi_final"]]
        assert [round(v, 2) for v in found] == expected, key
        assert sum(found) == pytest.approx(entry["rmsd_ab"], abs=1e-6)
        assert round(entry["rmsd_ab"], 2) == total
        assert sum(item["value"] for item in entry["share"]) == pytest.approx(1.0, abs=1e-9)
    # RMSD(A,B) at the final stage is Phase 1's own RMSD for AC
    ab_ac = next(m for m in ss["phase1"]["A-B"]["metrics"] if m["stage"] == "AC")
    assert phase3["A-B"]["rmsd_ab"] == pytest.approx(ab_ac["rmsd"], abs=1e-6)
    assert phase3["B-C"] == phase3_pair_to_dict(NOT_RUN_OUTCOME_1)  # the outcome-1 pair stays as Phase 1 settled it


def test_one_press_computes_every_eligible_pair_with_a_message_for_each(thesis):
    run, inputs = thesis
    ss = _session(run, inputs, "p4-thesis")
    al.run_phase1(ss)
    messages: list[str] = []
    al.run_phase3(ss, messages.append)
    pair_messages = [m for m in messages if m.startswith("Attributing")]
    assert pair_messages == [
        "Attributing the final AC difference for A – B (1 of 2). This takes a few seconds.",
        "Attributing the final AC difference for A – C (2 of 2). This takes a few seconds.",
    ]
    assert messages[-1] == wording.P4_P3_PROGRESS_SAVE
    assert al.phase3_done(ss["phase1"], ss["phase3"])


def test_phase_3_is_saved_as_the_command_line_stores_it_and_a_second_press_adds_nothing(thesis):
    run, inputs = thesis
    ss = _session(run, inputs, "p4-thesis")
    phase1 = al.run_phase1(ss)
    before = load_analysis("p4-thesis")
    al.run_phase3(ss)
    row = load_analysis("p4-thesis")
    live = run.live
    results = step_disagreement_check(live.pipelines, live.site_result.ctx, live.defaults, tau=live.tau)
    cli = {
        f"{a}-{b}": phase3_pair_to_dict(v)
        for (a, b), v in step_phase3(live.pipelines, results, live.hardware, live.site_result.ctx, live.defaults, "p4-thesis").items()
    }
    assert row["phase3"] == ss["phase3"] == cli and row["status"] == "phase3_done"
    for section in ("phase1", "phase2", "run_info", "pipelines", "inputs"):
        assert row[section] == before[section], section
    assert row["phase1"] == phase1
    counts, first = _counts(), copy.deepcopy(ss["phase3"])
    al.run_phase3(_session(run, inputs, "p4-thesis") | {"phase1": phase1, "phase3": None})
    assert _counts() == counts and load_analysis("p4-thesis")["phase3"] == first


def test_reopening_and_running_phase_3_again_gives_the_same_records_rows_and_analysis_id(thesis):
    run, inputs = thesis
    ss = _session(run, inputs, "p4-thesis")
    phase1 = al.run_phase1(ss)
    first = copy.deepcopy(al.run_phase3(ss))

    def linked() -> set[str]:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT record_id FROM analysis_records WHERE analysis_id = %s", ("p4-thesis",))
            return {r[0] for r in cur.fetchall()}

    records, counts, before = linked(), _counts(), load_analysis("p4-thesis")
    assert len(records) >= 3 + 20  # three original records and the derived runs of the two pairs
    reopened = rl.reopen("p4-thesis")
    messages: list[str] = []
    again = _session(reopened, inputs, "p4-thesis") | {"phase1": phase1}
    result = al.run_phase3(again, messages.append)
    assert wording.P4_PROGRESS_REBUILD in messages  # the live pipelines were rebuilt from the stored inputs
    assert result == first and linked() == records and _counts() == counts
    after = load_analysis("p4-thesis")
    assert after["id"] == before["id"] == "p4-thesis" and after["run_info"] == before["run_info"]


def test_a_stage_with_the_same_model_keeps_its_stored_zero_and_is_shown_as_same_model(thesis):
    run, inputs = thesis
    ss = _session(run, inputs, "p4-thesis")
    phase1 = al.run_phase1(ss)
    phase3 = al.run_phase3(ss)
    view = al.phase3_views(phase1, phase3)[0]  # A–B: both pipelines use sandia at AC
    ac = view.rows[-1]
    assert ac.same_model is True and ac.phi_final == 0.0 and ac.phi_ab == 0.0  # the stored value is untouched
    assert phase3["A-B"]["phi_final"][-1]["value"] == 0.0
    assert not any(row.same_model for row in view.rows[:4])
    ac_c = al.phase3_views(phase1, phase3)[1].rows
    assert [row.same_model for row in ac_c] == [False, False, False, True, True]  # A–C also share the DC model


def _open_with(run, inputs, phase1, phase3, **extra):
    return _open(run, inputs, phase1=phase1, phase1_done=True, has_k=True, phase3=phase3, **extra)


def _p3_frame(at):
    return next(f for chart in _chart_frames(at) for f in chart if "kind" in f.columns)


def test_pressing_phase_3_shows_the_table_the_efficiency_line_and_a_waterfall_that_ends_at_rmsd():
    run, inputs = _fresh_run()
    at = _open(run, inputs)
    at.button(key="w4_p1").click().run()
    assert not at.button(key="w4_p3").disabled
    at.button(key="w4_p3").click().run()
    assert not at.exception
    ss = at.session_state
    view = al.phase3_views(ss["phase1"], ss["phase3"])[0]
    text = _text(at)
    for row in view.rows:
        if not row.same_model:
            for value in (row.phi_ab, row.phi_ba, row.phi_final):
                assert al.fmt_watts(value) in text
    assert wording.SAME_MODEL in text  # the AC row
    total, rmsd, agrees = al.efficiency(view)
    assert agrees and f"add up to {al.fmt_watts(total)} W; RMSD(A,B) is {al.fmt_watts(rmsd)} W." in text
    frame = _p3_frame(at)
    assert list(frame["kind"]) == ["stage"] * 5 + ["total"]
    assert frame.iloc[-1]["end"] == view.rmsd_ab and frame.iloc[-1]["start"] == 0.0  # the last bar is RMSD(A,B)
    assert frame.iloc[4]["end"] == pytest.approx(view.rmsd_ab, abs=1e-6)  # the stages end where it ends
    assert list(frame["text"][:5]) == [wording.P4_P3_BAR_SAME if r.same_model else al.fmt_watts(r.phi_final) for r in view.rows]
    assert not re.search(r"\bsigned\b", text.lower())
    assert at.session_state["phase3"] == load_analysis("p4-page")["phase3"]


def test_the_thesis_waterfall_ends_at_rmsd_ab_from_the_charts_own_data(thesis):
    run, inputs = thesis
    ss = _session(run, inputs, "p4-thesis")
    phase1 = al.run_phase1(ss)
    phase3 = al.run_phase3(ss)
    at = _open_with(run, inputs, phase1, phase3)
    frame = _p3_frame(at)
    assert round(frame.iloc[-1]["end"], 2) == 73.88 and frame.iloc[-1]["end"] == phase3["A-B"]["rmsd_ab"]
    assert [round(v, 2) for v in frame["value"][:5]] == THESIS_PHI["A-B"][0]
    at.get("button_group")[1].set_value("A-C")
    at.run()
    frame = _p3_frame(at)
    assert round(frame.iloc[-1]["end"], 2) == 95.44 and [round(v, 2) for v in frame["value"][:5]] == THESIS_PHI["A-C"][0]


def test_a_negative_phi_has_a_true_minus_in_the_table_and_draws_downward_with_its_signed_value(thesis):
    run, inputs = thesis
    phase1 = _stored_phase1(run, inputs)
    entry = _phase3_entry([40.0, -3.2, 20.0, 0.5, 0.0])
    at = _open_with(run, inputs, phase1, {"A-B": entry})
    text = _text(at)
    assert "−3.20" in text and "-3.20" not in text
    for banned in ("steps down", "reduces", "lowers", "negative value"):
        assert banned not in text.lower().replace("φ can be negative", "")
    frame = _p3_frame(at)
    transposition = frame.iloc[1]
    assert transposition["end"] < transposition["start"] and transposition["value"] == -3.2 and transposition["text"] == "−3.20"
    assert frame.iloc[-1]["end"] == pytest.approx(57.3) and frame.iloc[4]["end"] == pytest.approx(57.3)  # still adds up to RMSD
    assert "agrees" not in text and f"add up to {al.fmt_watts(57.3)} W; RMSD(A,B) is {al.fmt_watts(57.3)} W." in text


def test_a_pair_that_differs_at_one_stage_shows_the_normal_table_and_the_note(thesis):
    run, inputs = thesis
    phase1 = copy.deepcopy(_stored_phase1(run, inputs))
    phase1["A-B"]["differing_stages"] = ["TEMPERATURE"]
    entry = _phase3_entry([0.0, 0.0, 73.88, 0.0, 0.0])
    at = _open_with(run, inputs, phase1, {"A-B": entry})
    text = _text(at)
    assert wording.ONE_STAGE_NOTE in text
    assert "73.88" in text and text.count(wording.SAME_MODEL) == 4  # the one stage that differs carries it all
    assert al.phase3_views(phase1, {"A-B": entry})[0].one_stage is True


def test_the_note_is_not_shown_when_more_than_one_stage_differs(thesis):
    run, inputs = thesis
    phase1 = _stored_phase1(run, inputs)
    at = _open_with(run, inputs, phase1, {"A-B": _phase3_entry([17.52, 6.10, 50.23, 0.02, 0.0])})
    assert wording.ONE_STAGE_NOTE not in _text(at)


def test_a_real_pair_that_differs_at_exactly_one_stage_is_a_result_with_the_note():
    _clean()
    inputs = _inputs_with_tau(0.01)
    inputs["pipelines"]["B"] = {**inputs["pipelines"]["A"], "temperature": "pvsyst_cell"}  # B differs from A only here
    run = rl.run_pipelines(inputs, "p4-page")
    ss = _session(run, inputs, "p4-page")
    phase1 = al.run_phase1(ss)
    assert phase1["A-B"]["differing_stages"] == ["TEMPERATURE"] and phase1["A-B"]["outcome"] in (2, 3)
    phase3 = al.run_phase3(ss)
    entry = phase3["A-B"]
    assert entry["status"] == "ran"  # nothing is hidden because only one stage differs
    phi = {item["stage"]: item["value"] for item in entry["phi_final"]}
    assert phi["TEMPERATURE"] == pytest.approx(entry["rmsd_ab"], abs=1e-6)  # the whole difference sits in that stage
    assert all(phi[s] == 0.0 for s in ("DECOMPOSITION", "TRANSPOSITION", "DC", "AC"))
    at = _open(run, inputs, phase1=phase1, phase1_done=True, has_k=True, phase3=phase3)
    assert wording.ONE_STAGE_NOTE in _text(at)


def test_a_pair_that_cannot_be_decomposed_shows_its_reason_and_no_numbers(thesis):
    run, inputs = thesis
    phase1 = _stored_phase1(run, inputs)
    entry = {"status": "not computable", "reason": "not computable — DC/AC hybrid invalidity",
             "invalid_coalitions": ["DC+AC", "TEMPERATURE+DC+AC"]}
    at = _open_with(run, inputs, phase1, {"A-B": entry})
    text = _text(at)
    assert wording.NOT_COMPUTABLE_HYBRID in text and "2 of the stage combinations cannot be run" in text
    assert "φ final (W)" not in text and len(_chart_frames(at)) == 2  # no table, no waterfall


def test_outcome_1_pairs_are_settled_by_phase_1_and_shown_without_pressing_phase_3():
    run, inputs = _fresh_run(tau=0.5)
    at = _open(run, inputs)
    at.button(key="w4_p1").click().run()
    assert wording.PHASE3_OUTCOME_1 in _text(at) and at.button(key="w4_p3").disabled
    for key in ("A-C", "B-C"):
        at.get("button_group")[1].set_value(key)
        at.run()
        assert wording.PHASE3_OUTCOME_1 in _text(at)


def test_with_a_mix_the_outcome_1_pair_is_settled_and_the_others_wait_for_the_press(thesis):
    run, inputs = thesis
    phase1 = _stored_phase1(run, inputs)
    settled = {"B-C": phase3_pair_to_dict(NOT_RUN_OUTCOME_1)}
    at = _open_with(run, inputs, phase1, settled)
    assert not at.button(key="w4_p3").disabled
    assert wording.P4_P3_PENDING in _text(at)  # A–B waits for the button
    at.get("button_group")[1].set_value("B-C")
    at.run()
    assert wording.PHASE3_OUTCOME_1 in _text(at)


def test_a_pair_that_failed_its_checks_shows_the_reason_as_stored(thesis):
    run, inputs = thesis
    phase1 = copy.deepcopy(_stored_phase1(run, inputs))
    phase1["A-C"] = {"status": "not computable", "reason": "not computable — pipeline A failed dc"}
    phase3 = {"A-C": {"status": "not run", "reason": "not computable — pipeline A failed dc"}}
    at = _open_with(run, inputs, phase1, phase3)
    at.get("button_group")[1].set_value("A-C")
    at.run()
    assert "Not computable — pipeline A failed dc" in _text(at)


def test_choosing_a_pair_to_view_computes_nothing(thesis, monkeypatch):
    run, inputs = thesis
    ss = _session(run, inputs, "p4-thesis")
    phase1 = al.run_phase1(ss)
    phase3 = al.run_phase3(ss)
    at = _open_with(run, inputs, phase1, phase3)

    def refuse(*args, **kwargs):
        pytest.fail("a selector change computed something")

    monkeypatch.setattr(al, "step_phase3", refuse)
    monkeypatch.setattr(al, "step_disagreement_check", refuse)
    for key in ("A-C", "B-C", "A-B"):
        at.get("button_group")[1].set_value(key)
        at.run()
        assert not at.exception


def test_the_phase_3_page_has_tooltips_and_no_signed_column_hash_or_banned_word(thesis):
    run, inputs = thesis
    ss = _session(run, inputs, "p4-thesis")
    phase1 = al.run_phase1(ss)
    at = _open_with(run, inputs, phase1, al.run_phase3(ss))
    markup = " ".join(el.value for el in at.get("html"))
    for hint in (wording.HELP_PHI, wording.HELP_SHARE):
        assert html.escape(hint) in markup
    text = _text(at).lower()
    assert not HEX.findall(text) and not re.search(r"\bsigned\b", text)
    for word in ("recommend", "suggest", "optimal", "improv", "best", "error", "compensat", "winner", "rank"):
        assert word not in text, word
    assert not re.search(r"\bcorrect", text)
    assert text.index("φ a→b") < text.index("φ b→a") < text.index("φ final")
