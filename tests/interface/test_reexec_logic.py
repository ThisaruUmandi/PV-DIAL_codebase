"""Page 5 logic that needs no database: pairs, candidates and reasons, the attempt view, the shared writer, and the
guards for stage names and UK spelling."""

import re

import pytest
import yaml

from app import analysis_logic as al
from app import config_logic, wording
from app import reexec_logic as rx
from pvdials.analysis import ReexecDetails, phase1_to_dict, reexec_to_dict
from pvdials.config import ROOT
from pvdials.guided_reexecution import DISCLAIMER, FinalRunResult
from pvdials.provenance.analyses import NOT_RECORDED
from pvdials.types import PipelineConfig, Stage

STAGES = al.STAGES
THESIS = yaml.safe_load((ROOT / "analysis.yaml").read_text(encoding="utf-8"))


def _entry(nrmsd, outcome=3, k="DECOMPOSITION", tau=0.093, source="default"):
    return {
        "status": "ran", "pair": ["A", "B"], "outcome": outcome, "k": k,
        "differing_stages": ["DECOMPOSITION", "TEMPERATURE"], "tau": {"value": tau, "source": source},
        "metrics": [
            {"stage": s.upper(), "rmsd": 1.0, "nrmsd": v, "mad": 1.0, "mbd": 0.0, "systematic_share": 0.1,
             "n_pooled": 100, "not_computable_reason": None}
            for s, v in zip(STAGES, nrmsd, strict=True)
        ],
    }


BEFORE = _entry((0.1235, 0.0036, 0.1534, 0.0173, 0.0172))
AFTER = _entry((0.0500, 0.0036, 0.1534, 0.0173, 0.0172), outcome=3, k="TEMPERATURE")


# --- Which pairs are offered ----------------------------------------------------------------------------------------------


def test_only_pairs_with_a_k_are_offered_in_the_fixed_order():
    none = {"status": "ran", "outcome": 1, "k": None}
    failed = {"status": "not computable", "reason": "not computable — x at stage DC"}
    assert rx.pairs_with_k({"A-B": BEFORE, "A-C": BEFORE, "B-C": none}) == [("A", "B"), ("A", "C")]
    assert rx.pairs_with_k({"A-B": none, "A-C": BEFORE, "B-C": BEFORE}) == [("A", "C"), ("B", "C")]
    assert rx.pairs_with_k({"A-B": none, "A-C": failed, "B-C": none}) == []
    assert rx.pair_stage({"A-B": BEFORE}, ("A", "B")) == "decomposition"


# --- Candidates ----------------------------------------------------------------------------------------------------------------


def _inputs():
    inputs = {k: v for k, v in THESIS.items() if k != "pipelines"}
    inputs["pipelines"] = {label: dict(THESIS["pipelines"][label]) for label in "ABC"}
    return inputs


def test_candidates_are_the_registry_pool_in_pool_order_and_each_blocked_one_has_its_reason():
    inputs = _inputs()
    pools = config_logic.pools_for(MODULE := inputs["hardware"]["module_name"], None, None, inputs["hardware"]["inverter_name"])
    assert MODULE
    for stage in ("decomposition", "transposition", "temperature", "dc"):
        pool = rx.candidate_pool(inputs, stage, inputs["pipelines"]["A"], "A")
        assert [c.name for c in pool] == [c.name for c in pools.views[stage]]  # pool order, never sorted
        for candidate in pool:
            assert candidate.selectable or candidate.reason  # a blocked model always says why


def test_the_anchors_own_model_is_listed_as_not_selectable_with_a_reason():
    inputs = _inputs()
    pool = {c.name: c for c in rx.candidate_pool(inputs, "temperature", inputs["pipelines"]["A"], "A")}
    assert pool["faiman"].selectable is False and pool["faiman"].reason == "already the model in A"
    assert pool["pvsyst_cell"].selectable is True and pool["ross"].selectable is True


def test_pvwatts_dc_is_not_selectable_against_an_anchor_whose_ac_needs_a_dc_voltage():
    from pvdials.physics.registry import NO_V_DC_REASON

    inputs = _inputs()
    pool = {c.name: c for c in rx.candidate_pool(inputs, "dc", inputs["pipelines"]["A"], "A")}  # A's AC is sandia
    assert pool["pvwatts_dc"].selectable is False and pool["pvwatts_dc"].reason == NO_V_DC_REASON
    assert pool["singlediode_desoto"].selectable is True
    anchor = {**inputs["pipelines"]["A"], "ac": "pvwatts"}  # an AC model that needs no voltage
    assert {c.name: c for c in rx.candidate_pool(inputs, "dc", anchor, "A")}["pvwatts_dc"].selectable is True


def test_at_the_ac_stage_the_pool_follows_the_anchors_dc_model():
    inputs = _inputs()
    anchor = {**inputs["pipelines"]["A"], "dc": "pvwatts_dc"}
    pool = {c.name: c for c in rx.candidate_pool(inputs, "ac", anchor, "A")}
    assert pool["sandia"].selectable is False and pool["adr"].selectable is False and pool["sandia"].reason


# --- The attempt view ------------------------------------------------------------------------------------------------------------


def test_the_change_is_after_minus_before_as_a_signed_number_with_no_words():
    view = rx.attempt_view(BEFORE, AFTER)
    assert view.computable and [r.stage for r in view.rows] == list(STAGES)
    assert view.rows[0].change == pytest.approx(0.05 - 0.1235)
    assert rx.fmt_change(view.rows[0].change) == "−0.0735" and rx.fmt_change(view.rows[1].change) == "0.0000"
    assert rx.fmt_change(0.0123) == "0.0123" and rx.fmt_change(-1e-17) == "0.0000"  # a value that rounds to zero has no sign
    assert view.before_outcome == "Outcome 3, k = Decomposition" and view.after_outcome == "Outcome 3, k = Cell temperature"
    assert [(r.before_over, r.after_over) for r in view.rows] == [(True, False), (False, False), (True, True), (False, False), (False, False)]


def test_an_attempt_that_is_not_computable_has_the_reason_and_no_k_and_no_change():
    after = phase1_to_dict("not computable — too few daylight samples at stage DC")
    view = rx.attempt_view(BEFORE, after)
    assert view.computable is False and view.rows == [] and view.after_outcome is None
    assert view.message == "Not computable — too few daylight samples at stage DC power"


def test_one_axis_range_serves_every_attempt_and_pair():
    phase1 = {"A-B": BEFORE, "A-C": _entry((0.2, 0.01, 0.3, 0.02, 0.02)), "B-C": _entry((0.0674, 0.005, 0.0706, 0.008, 0.008), 1, None)}
    attempts = [{"phase1": AFTER}, {"phase1": _entry((0.5, 0, 0, 0, 0))}, {"phase1": phase1_to_dict("not computable — x at stage DC")}]
    top = rx.axis_max(phase1, attempts)
    assert top == pytest.approx(0.5 * 1.15)
    assert rx.axis_max(phase1, attempts[:1]) == pytest.approx(0.3 * 1.15)  # grows only when a larger attempt exists
    assert rx.axis_max(phase1, []) >= 0.093


# --- The shared writer ---------------------------------------------------------------------------------------------------------------------


def _final(label="A_B_confirmed"):
    config = PipelineConfig(label, "erbs", "isotropic", "pvsyst_cell", "singlediode_cec", "sandia")
    return FinalRunResult(pair=("A", "B"), config=config, result=None, annual_yield_kwh=9800.5)


def test_the_writer_always_has_the_four_new_keys_and_fills_them_when_given_details():
    plain = reexec_to_dict(_final())
    assert {"anchor", "stage", "candidate", "phase1"} <= set(plain) and plain["anchor"] is None and plain["phase1"] is None
    details = ReexecDetails("A", Stage.TEMPERATURE, "pvsyst_cell", AFTER)
    full = reexec_to_dict(_final(), details)
    assert (full["anchor"], full["stage"], full["candidate"]) == ("A", "TEMPERATURE", "pvsyst_cell")
    assert full["phase1"] == AFTER  # a phase1 dict passes through as written
    assert set(plain) == set(full)  # the same shape with or without details
    from app.analysis_logic import phase1_from_dict

    again = reexec_to_dict(_final(), ReexecDetails("A", Stage.TEMPERATURE, "pvsyst_cell", phase1_from_dict(AFTER)))
    assert again["phase1"] == AFTER  # an object is written in the same shape


def test_parts_missing_from_a_row_saved_earlier_read_as_not_recorded():
    old = {"pair": ["A", "B"], "config_label": "A_B_confirmed", "annual_yield_kwh": None,
           "substituted_stage_model": {"decomposition_model": "erbs"}, "disclaimer": DISCLAIMER}
    assert wording.RX_NOT_RECORDED == NOT_RECORDED == "not recorded for this analysis"
    for key in ("anchor", "stage", "candidate", "phase1"):
        assert rx.recorded(old, key) == NOT_RECORDED
    assert rx.change_text(old) == "A – B · not recorded for this analysis: not recorded for this analysis"
    new = reexec_to_dict(_final(), ReexecDetails("B", Stage.DC, "singlediode_desoto", AFTER))
    assert rx.change_text(new) == "A – B · DC power: singlediode_desoto"


def test_the_disclaimer_is_the_sessions_own_sentence():
    assert wording.DISCLAIMER == DISCLAIMER == (
        "This shows how disagreement changes with one substitution. It does not identify which "
        "configuration is preferable — that choice remains the user's."
    )


# --- One set of stage names, and UK spelling ------------------------------------------------------------------------------------------------


def test_every_list_of_stage_names_derives_from_the_one_set():
    names = [wording.STAGE_NAME[k] for k in wording.STAGE_KEYS]
    assert names == ["Decomposition", "Transposition", "Cell temperature", "DC power", "AC conversion"]
    assert list(wording.STAGE_NAME_LIST) == names == list(wording.STAGE_PILLS) == list(wording.P4_HEAT_AXIS)
    assert wording.R_STAGE_SHORT == wording.R_LINEAGE_STAGE_NAMES == wording.STAGE_NAME
    assert [wording.C_STAGE_LABELS[k] for k in wording.STAGE_KEYS] == [f"{i} · {n}" for i, n in enumerate(names, start=1)]
    assert {k: v for k, v in wording.STAGE_NAMES.items()} == {k.upper(): v for k, v in wording.STAGE_NAME.items()}


_US = re.compile(
    r"\b\w*(?:localiz|normaliz|summariz|visualiz|organiz|recogniz|analyz|initializ|characteriz|customiz|categoriz|"
    r"optimiz|utiliz|standardiz|finaliz)\w*\b|\b(?:behavior|favor|honor|neighbor|catalog|defense|gray|meter)\w*\b",
    re.IGNORECASE,
)


def test_wording_and_page_text_use_uk_spelling():
    texts = {}
    for path in [ROOT / "app" / "wording.py", *sorted((ROOT / "app" / "screens").glob("*.py")),
                 ROOT / "app" / "components.py", ROOT / "app" / "analysis_logic.py", ROOT / "app" / "reexec_logic.py"]:
        for match in re.finditer(r'"([^"\n]{3,})"', path.read_text(encoding="utf-8")):
            if _US.search(match.group(1)):
                texts.setdefault(path.name, []).append(match.group(1)[:60])
    assert not texts, texts
    assert "Localisation" in wording.P4_P1_BUTTON and "Localised" in wording.RX_STAGE_FIXED
