"""Step 2 · Pipeline configuration: the logic in app/config_logic.py and the page (AppTest).

Database tests use pvdials_test (tests/conftest.py forces it). The thesis pipelines come from
analysis.yaml, the file the command line reads.
"""

import dataclasses
import html
import itertools
import re

import pytest
import yaml
from streamlit.testing.v1 import AppTest

from app import config_logic as cl
from app import wording
from experiments.evaluation.db_safety import guard_not_dev_database, resolve_current_database_url
from pvdials.analysis import AnalysisError
from pvdials.config import ROOT
from pvdials.dla.phase3 import pair_is_shapley_computable
from pvdials.provenance.analyses import load_analysis
from pvdials.provenance.db import get_connection, is_reachable, run_schema

needs_db = pytest.mark.skipif(not is_reachable(), reason="no Postgres reachable")

THESIS = yaml.safe_load((ROOT / "analysis.yaml").read_text(encoding="utf-8"))
EXAMPLE = {label: dict(THESIS["pipelines"][label]) for label in cl.LABELS}
MODULE = THESIS["hardware"]["module_name"]
INVERTER = THESIS["hardware"]["inverter_name"]


def _inputs() -> dict:
    """What page 1 leaves in session state, built from the same file the command line reads."""
    inputs = {k: v for k, v in THESIS.items() if k != "pipelines"}
    inputs["name"] = "page two test"
    return inputs


def _pools() -> cl.Pools:
    return cl.pools_for(MODULE, None, None, INVERTER)


def _empty() -> dict:
    return {label: dict.fromkeys(cl.STAGES) for label in cl.LABELS}


@pytest.fixture
def clean_db():
    guard_not_dev_database(resolve_current_database_url(), "page 2 tests")
    with get_connection() as conn:
        run_schema(conn)
        with conn.cursor() as cur:
            for table in ("analysis_records", "analyses", "stage_output_values", "provenance_records"):
                cur.execute(f"DELETE FROM {table}")
        conn.commit()
    yield


# --- Which models a cell offers ---------------------------------------------------------------------


def test_first_three_stages_follow_pool_order_and_only_selectable_models():
    pools = _pools()
    offered = cl.options(pools, _empty()["A"], [_empty()["B"], _empty()["C"]])
    for stage in cl.STAGES[:4]:
        view = [c.name for c in pools.views[stage] if c.selectable]
        if stage != "dc":
            assert offered.models[stage] == view  # same order as the registry, never re-ordered
    assert set(offered.models["dc"]) <= {c.name for c in pools.views["dc"] if c.selectable}
    order = [c.name for c in pools.views["dc"]]
    assert offered.models["dc"] == [m for m in order if m in offered.models["dc"]]


def test_models_the_module_cannot_use_are_listed_with_the_registrys_reason_and_never_offered():
    pools = _pools()
    listed = cl.not_selectable(pools)
    names = {name for _stage, name, _reason in listed}
    assert {"sapm", "singlediode_pvsyst", "dirindex", "prilliman"} <= names
    assert all(reason for _s, _n, reason in listed)
    for stage, name, reason in listed:
        pool = {c.name: c for c in pools.views[stage]}
        assert pool[name].reason == reason  # the registry's own words, not a copy
    offered = cl.options(pools, _empty()["A"], [_empty()["B"], _empty()["C"]])
    for stage, name, _ in listed:
        assert name not in offered.models[stage]


def test_the_single_diode_and_sapm_families_cannot_be_mixed():
    pools = _pools()
    column = _empty()
    for label in cl.LABELS:
        offered = cl.options(pools, column[label], [column[o] for o in cl.LABELS if o != label])
        assert "sapm" not in offered.models["dc"]
        assert "singlediode_pvsyst" not in offered.models["dc"]
    with pytest.raises(AnalysisError):
        cl.commit_page2("x", _inputs(), pools, {**_full(), "A": {**EXAMPLE["A"], "dc": "sapm"}}, cl.tau_from_value(0.093))


def _full() -> dict:
    return {label: dict(EXAMPLE[label]) for label in cl.LABELS}


def test_pvwatts_dc_removes_sandia_and_adr_at_ac_with_a_plain_reason():
    pools = _pools()
    column = _empty()
    column["A"]["dc"] = "pvwatts_dc"
    offered = cl.options(pools, column["A"], [column["B"], column["C"]])
    assert not set(offered.models["ac"]) & {"sandia", "adr"}
    assert offered.notes["ac"] and "pvwatts_dc" in offered.notes["ac"][0] and "DC voltage" in offered.notes["ac"][0]


def test_choosing_sandia_removes_pvwatts_dc_from_every_pipeline():
    pools = _pools()
    column = _empty()
    column["B"]["ac"] = "sandia"
    own = cl.options(pools, column["B"], [column["A"], column["C"]])
    other = cl.options(pools, column["A"], [column["B"], column["C"]])
    assert "pvwatts_dc" not in own.models["dc"] and "pvwatts_dc" not in other.models["dc"]
    assert own.notes["dc"] and other.notes["dc"]


def test_the_page_cannot_build_a_chain_phase_3_could_not_attribute():
    """For every combination of DC and AC choices in the three pipelines: if each choice is
    offered given the other two, every pair is computable; if any pair is not computable,
    some choice is not offered. The offering rules and Phase 3's own check agree exactly."""
    pools = _pools()
    dc_all = [c.name for c in pools.views["dc"] if c.selectable]
    cec_ac = cl.options(pools, _empty()["A"], [_empty()["B"], _empty()["C"]]).models["ac"]
    base = dict(EXAMPLE["A"])
    cells = list(itertools.product(dc_all, cec_ac))
    checked = 0
    for combo in itertools.product(cells, repeat=3):
        config = {
            label: {**base, "dc": dc, "ac": ac} for label, (dc, ac) in zip(cl.LABELS, combo, strict=True)
        }
        all_offered = True
        for label in cl.LABELS:
            offered = cl.options(pools, config[label], [config[o] for o in cl.LABELS if o != label])
            all_offered &= config[label]["dc"] in offered.models["dc"] and config[label]["ac"] in offered.models["ac"]
        configs = {label: cl.to_pipeline_config(label, config[label]) for label in cl.LABELS}
        computable = all(
            pair_is_shapley_computable(configs[a], configs[b])[0] for a, b in (("A", "B"), ("A", "C"), ("B", "C"))
        )
        assert all_offered == computable, combo
        assert (cl.problems(pools, config) == []) == computable
        checked += 1
    assert checked == len(cells) ** 3


def test_missing_stages_and_the_same_model_everywhere_are_handled():
    config = _full()
    assert cl.problems(_pools(), config) == []
    assert cl.missing_stages({**config["A"], "ac": None}) == ["ac"]
    assert any("Pipeline A" in p for p in cl.problems(_pools(), {**config, "A": {**config["A"], "ac": None}}))
    same = {label: dict(EXAMPLE["A"]) for label in cl.LABELS}
    assert cl.problems(_pools(), same) == []  # three identical pipelines are allowed; Phase 1 reports "same model"
    assert [cl.differs(config, s) for s in cl.STAGES] == [True, True, True, True, False]


# --- The thesis example ------------------------------------------------------------------------------


def test_example_fills_all_fifteen_cells_from_analysis_yaml():
    config, left_out = cl.usable_example(_pools(), cl.example_pipelines())
    assert left_out == [] and config == _full()


def test_example_leaves_an_unavailable_model_empty_and_names_it_never_swapping():
    pools = _pools()
    views = dict(pools.views)
    views["temperature"] = tuple(
        dataclasses.replace(c, selectable=False, reason="removed for this test") if c.name == "ross" else c
        for c in views["temperature"]
    )
    config, left_out = cl.usable_example(dataclasses.replace(pools, views=views), cl.example_pipelines())
    assert config["C"]["temperature"] is None and any("ross" in name for name in left_out)
    assert {k: v for k, v in config["C"].items() if k != "temperature"} == {
        k: v for k, v in EXAMPLE["C"].items() if k != "temperature"
    }


# --- τ -------------------------------------------------------------------------------------------------


def test_tau_tag_follows_the_value_and_only_numbers_above_zero_are_usable():
    assert cl.tau_from_value(cl.default_tau()) == {"value": 0.093, "source": "default"}
    assert cl.tau_from_value(0.15) == {"value": 0.15, "source": "user_entered"}
    assert cl.tau_from_value(0.01)["source"] == "user_entered"
    assert cl.tau_problem(0.15) is None and cl.tau_problem(0.093) is None
    for bad in (0, 0.0, -0.1, None, float("nan"), float("inf"), "abc"):
        assert cl.tau_problem(bad) == wording.C_TAU_PROBLEM, bad


# --- Saving --------------------------------------------------------------------------------------------


@needs_db
def test_selecting_the_thesis_pipelines_saves_a_record_equal_to_analysis_yaml(clean_db):
    saved = cl.commit_page2("p2-acceptance", _inputs(), _pools(), _full(), cl.tau_from_value(0.093))
    row = load_analysis("p2-acceptance")
    assert row["status"] == "pipelines_configured"
    assert row["inputs"]["pipelines"] == THESIS["pipelines"] == saved["pipelines"]
    assert row["inputs"]["tau"] == {"value": 0.093, "source": "default"}
    assert row["inputs"]["hardware"] == THESIS["hardware"] and row["inputs"]["site"] == THESIS["site"]


@needs_db
def test_a_user_tau_is_saved_with_its_source_and_saving_again_replaces_the_row(clean_db):
    cl.commit_page2("p2-tau", _inputs(), _pools(), _full(), cl.tau_from_value(0.15))
    assert load_analysis("p2-tau")["inputs"]["tau"] == {"value": 0.15, "source": "user_entered"}
    cl.commit_page2("p2-tau", _inputs(), _pools(), _full(), cl.tau_from_value(0.01))
    assert load_analysis("p2-tau")["inputs"]["tau"] == {"value": 0.01, "source": "user_entered"}
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM analyses")
        assert cur.fetchone()[0] == 1


@needs_db
def test_an_incomplete_or_invalid_configuration_is_refused_and_nothing_is_written(clean_db):
    config = _full()
    config["B"]["ac"] = None
    with pytest.raises(AnalysisError):
        cl.commit_page2("p2-bad", _inputs(), _pools(), config, cl.tau_from_value(0.093))
    with pytest.raises(AnalysisError):
        cl.commit_page2("p2-bad", _inputs(), _pools(), _full(), {"value": 0.0, "source": "user_entered"})
    assert load_analysis("p2-bad") is None


# --- The page (AppTest) -----------------------------------------------------------------------------


def _page2():
    import streamlit as st

    from app import components, state
    from app.screens import config_pipelines

    state.init_state(st.session_state)
    if st.session_state.pop("_t_start_new", None):  # Home > Start new analysis, then page 1 is done again
        carried = st.session_state.pop("_t_inputs")
        state.new_analysis(st.session_state)
        st.session_state.update(inputs=carried, analysis_id="p2-fresh", data_valid=True)
    components.PAGES["1"] = "step-1"
    components.PAGES["3"] = "step-3"
    st.switch_page = lambda target: st.session_state.__setitem__("switched_to", target)
    st.page_link = lambda target, label=None, **kw: st.markdown(f"[{label}]({target})")  # no navigation in AppTest
    components.render_pending_change()
    config_pipelines.render()


def _text(at) -> str:
    joined = " ".join(el.value for el in at.get("html"))
    return html.unescape(re.sub(r"<[^>]+>", " ", joined))


def _open() -> AppTest:
    """Page 2 as it is when step 1 is done: inputs in state, step 2 unlocked."""
    at = AppTest.from_function(_page2, default_timeout=60)
    at.session_state["inputs"] = _inputs()
    at.session_state["analysis_id"] = "p2-page"
    at.session_state["name"] = "page two test"
    at.session_state["data_valid"] = True
    return at.run()


def _fill(at: AppTest, config: dict) -> AppTest:
    """Choose each cell the way a person would, one at a time, in stage order."""
    for stage in cl.STAGES:
        for label in cl.LABELS:
            at.selectbox(key=f"w2_{label}_{stage}").set_value(config[label][stage])
            at = at.run()
    return at


def _cells(at: AppTest) -> dict:
    return {label: {s: at.selectbox(key=f"w2_{label}_{s}").value for s in cl.STAGES} for label in cl.LABELS}


def test_locked_until_step_1_is_done():
    at = AppTest.from_function(_page2, default_timeout=60).run()
    assert not at.exception and not at.selectbox
    assert not at.button(key="w2_continue") if at.button else True


def test_empty_page_shows_fifteen_empty_cells_the_default_tau_and_a_blocked_button():
    at = _open()
    assert not at.exception
    assert len(at.selectbox) == 15 and all(box.value is None for box in at.selectbox)
    assert at.number_input(key="w2_tau").value == 0.093
    assert at.button(key="w2_continue").disabled
    text = _text(at)
    assert "needs decomposition, transposition, cell temperature, dc power, ac conversion" in text
    assert wording.C_NOT_SELECTABLE_TITLE in text and "sapm" in text and "Analysis settings" in text
    assert "Differs across pipelines" not in text  # nothing chosen yet, nothing differs


def test_every_cell_lists_its_models_in_pool_order():
    at = _open()
    pools = _pools()
    for label in cl.LABELS:
        for stage in cl.STAGES[:3]:
            expected = [c.name for c in pools.views[stage] if c.selectable]
            assert list(at.selectbox(key=f"w2_{label}_{stage}").options) == expected


def test_the_example_button_fills_the_thesis_pipelines_and_labels_itself_as_an_example():
    at = _open()
    assert wording.C_EXAMPLE_BUTTON in [b.label for b in at.button]
    at.button(key="w2_example").click().run()
    assert not at.exception and _cells(at) == _full()
    assert not at.button(key="w2_continue").disabled
    text = _text(at)
    assert wording.C_EXAMPLE_NOTE in text
    assert text.count("Differs across pipelines") == 4  # stages 1-4 differ, stage 5 does not
    assert "Pipeline A: all five stages chosen" in text


def test_choosing_cells_by_hand_reaches_the_same_configuration_and_notes_the_ac_rule():
    at = _fill(_open(), _full())
    assert _cells(at) == _full() and not at.button(key="w2_continue").disabled
    assert "pvwatts_dc is not offered because this pipeline's AC model (sandia)" in _text(at)
    assert "pvwatts_dc" not in at.selectbox(key="w2_A_dc").options


def test_picking_pvwatts_dc_empties_a_sandia_cell_in_the_same_pipeline_rather_than_swapping_it():
    at = _open()
    at.selectbox(key="w2_A_dc").set_value("pvwatts_dc").run()
    assert not {"sandia", "adr"} & set(at.selectbox(key="w2_A_ac").options)
    assert at.selectbox(key="w2_A_dc").value == "pvwatts_dc"
    assert "needs a DC voltage" in _text(at) or "DC voltage" in _text(at)


def test_continue_stays_disabled_with_fourteen_cells_and_says_what_is_missing():
    config = _full()
    at = _open().button(key="w2_example").click().run()
    assert not at.button(key="w2_continue").disabled
    at.selectbox(key="w2_C_ac").set_value(None).run()
    assert at.button(key="w2_continue").disabled
    assert "Pipeline C: all five stages chosen" in _text(at) and "needs ac conversion" in _text(at)
    assert _cells(at)["C"]["ac"] is None and _cells(at)["A"] == config["A"]


def test_tau_field_tag_and_reset():
    at = _open()
    assert "default" in _text(at) and at.button(key="w2_tau_reset").disabled
    at.number_input(key="w2_tau").set_value(0.15).run()
    assert not at.exception and at.button(key="w2_tau_reset").disabled is False
    assert wording.TAG_USER_ENTERED in _text(at) or "user entered" in _text(at)
    at.button(key="w2_tau_reset").click().run()
    assert at.number_input(key="w2_tau").value == 0.093 and at.button(key="w2_tau_reset").disabled


def test_tau_help_text_is_verbatim_and_gives_no_advice():
    text = _text(_open())
    assert wording.HELP_TAU in text
    for word in ("recommend", "suggest", "should", "best", "optimal"):
        assert word not in text.lower().replace("should not", "")


def test_a_tau_of_zero_blocks_continue_and_says_why():
    at = _open().button(key="w2_example").click().run()
    at.number_input(key="w2_tau").set_value(0.0).run()
    assert at.button(key="w2_continue").disabled
    assert wording.C_TAU_PROBLEM in _text(at)


@needs_db
def test_continue_saves_configuration_and_tau_flags_step_2_done_and_opens_step_3(clean_db):
    at = _open().button(key="w2_example").click().run()
    at.number_input(key="w2_tau").set_value(0.15).run()
    at.button(key="w2_continue").click().run()
    assert not at.exception
    assert at.session_state["config_valid"] is True and at.session_state["switched_to"] == "step-3"
    assert at.session_state["flash"] == wording.C_SAVED_FLASH
    row = load_analysis("p2-page")
    assert row["status"] == "pipelines_configured"
    assert row["inputs"]["pipelines"] == THESIS["pipelines"]
    assert row["inputs"]["tau"] == {"value": 0.15, "source": "user_entered"}


@needs_db
def test_changing_a_cell_after_continue_shows_the_clear_warning_and_cancel_keeps_it(clean_db):
    at = _open().button(key="w2_example").click().run()
    at.button(key="w2_continue").click().run()
    at.selectbox(key="w2_A_decomposition").set_value("disc").run()
    assert "This clears steps 3 to 6 of this analysis." in _text(at)
    assert at.session_state["config_valid"] is True and at.button(key="w2_continue").disabled
    at.button(key="pending_cancel").click().run()
    assert at.selectbox(key="w2_A_decomposition").value == "erbs" and "This clears steps" not in _text(at)
    assert at.session_state["config_valid"] is True


@needs_db
def test_changing_tau_after_continue_warns_and_confirming_reopens_the_step(clean_db):
    at = _open().button(key="w2_example").click().run()
    at.button(key="w2_continue").click().run()
    at.number_input(key="w2_tau").set_value(0.01).run()
    assert "This clears steps 3 to 6 of this analysis." in _text(at)
    assert at.session_state["tau"] == {"value": 0.093, "source": "default"}  # not changed until confirmed
    at.button(key="pending_confirm").click().run()
    assert at.session_state["tau"] == {"value": 0.01, "source": "user_entered"}
    assert at.session_state["config_valid"] is False and not at.button(key="w2_continue").disabled


def test_a_fresh_analysis_shows_an_empty_configuration_with_nothing_left_over():
    at = _open().button(key="w2_example").click().run()
    at.number_input(key="w2_tau").set_value(0.15).run()
    assert all(box.value for box in at.selectbox)
    at.session_state["_t_start_new"] = True
    at.session_state["_t_inputs"] = _inputs()
    at.run()
    assert not at.exception
    assert all(box.value is None for box in at.selectbox)
    assert at.number_input(key="w2_tau").value == 0.093
    assert at.session_state["config"] is None and at.session_state["tau"] is None
    assert at.button(key="w2_continue").disabled
    assert "Differs across pipelines" not in _text(at)
