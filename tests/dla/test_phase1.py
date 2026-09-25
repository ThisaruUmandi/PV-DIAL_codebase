import pandas as pd
import pytest

from pvdials.config import load_defaults
from pvdials.dla.phase1 import (
    OUTCOME_COMPENSATING_DIFFERENCES,
    OUTCOME_DISAGREEMENT_FOUND,
    OUTCOME_NOTHING_TO_DIAGNOSE,
    run_phase1,
)
from pvdials.types import Stage
from tests.dla.builders import all_daylight, make_pipeline_result

INDEX = pd.date_range("2023-06-21 08:00", periods=6, freq="h", tz="UTC")
DAYLIGHT = all_daylight(INDEX)


# Varying (not constant-repeated) values: a realistic pooled P95-P5 needs
# actual spread across the daylight hours. A constant series collapses the
# denominator to the (tiny) gap between two near-identical constants, making
# nRMSD ~= 1.0 regardless of how small the intended delta is.
_RAMP = [0.7, 0.85, 1.0, 1.0, 0.85, 0.7]


def _baseline(label, **overrides):
    values = {
        "dni": [v * 400.0 for v in _RAMP],
        "dhi": [v * 100.0 for v in _RAMP],
        "poa_global": [v * 500.0 for v in _RAMP],
        "temp_cell": [v * 45.0 for v in _RAMP],
        "p_dc": [v * 1500.0 for v in _RAMP],
        "p_ac": [v * 1400.0 for v in _RAMP],
        "index": INDEX,
    }
    values.update(overrides)
    return make_pipeline_result(label, **values)


def test_identical_pipelines_give_outcome_1():
    result_a = _baseline("A")
    result_b = _baseline("B")

    phase1 = run_phase1(result_a.config, result_a, result_b.config, result_b, DAYLIGHT)

    assert phase1.outcome == OUTCOME_NOTHING_TO_DIAGNOSE
    assert phase1.k is None
    assert all(m.nrmsd == 0.0 for m in phase1.metrics.values())


def test_delta_at_one_stage_gives_outcome_2_with_k_at_that_stage():
    result_a = _baseline("A")
    # A large difference at Stage 4 that propagates through to Stage 5 too
    # (as it would in a real pipeline) -- everything upstream identical.
    result_b = _baseline(
        "B",
        p_dc=[v * 3000.0 for v in _RAMP],
        p_ac=[v * 2800.0 for v in _RAMP],
        dc_model="singlediode_desoto",
    )

    phase1 = run_phase1(result_a.config, result_a, result_b.config, result_b, DAYLIGHT)

    assert phase1.outcome == OUTCOME_DISAGREEMENT_FOUND
    assert phase1.k == Stage.DC
    assert phase1.differing_stages == frozenset({Stage.DC})


def test_sub_tau_upstream_delta_plus_supra_tau_later_delta_gives_k_at_the_later_stage():
    # The most important constructed case (KT C3): proves tau actually gates,
    # not just "first stage that differs at all".
    defaults = load_defaults()
    tau = defaults["dla"]["tau"]

    result_a = _baseline("A")
    # Stage 2 (poa_global): a tiny relative difference, well under tau.
    small_delta_poa = [v * 500.0 * (1 + tau / 10) for v in _RAMP]
    # Stage 4 (p_dc), propagated to Stage 5 (p_ac) as it would in a real
    # pipeline: a large relative difference, well over tau.
    big_delta_dc = [v * 1500.0 * (1 + tau * 10) for v in _RAMP]
    big_delta_ac = [v * 1400.0 * (1 + tau * 10) for v in _RAMP]
    result_b = _baseline(
        "B",
        poa_global=small_delta_poa,
        p_dc=big_delta_dc,
        p_ac=big_delta_ac,
        transposition_model="klucher",
        dc_model="singlediode_desoto",
    )

    phase1 = run_phase1(result_a.config, result_a, result_b.config, result_b, DAYLIGHT)

    assert phase1.metrics[Stage.TRANSPOSITION].nrmsd <= tau
    assert phase1.metrics[Stage.DC].nrmsd > tau
    assert phase1.k == Stage.DC
    assert phase1.outcome == OUTCOME_DISAGREEMENT_FOUND


def test_upstream_disagreement_with_final_agreement_gives_outcome_3():
    result_a = _baseline("A")
    # A large difference at Stage 1, but AC ends up matching again.
    result_b = _baseline(
        "B", dni=[800.0] * 6, dhi=[300.0] * 6, decomposition_model="disc"
    )

    phase1 = run_phase1(result_a.config, result_a, result_b.config, result_b, DAYLIGHT)

    assert phase1.k == Stage.DECOMPOSITION
    assert phase1.metrics[Stage.AC].nrmsd == 0.0
    assert phase1.outcome == OUTCOME_COMPENSATING_DIFFERENCES


def test_differing_stages_matches_the_actual_config_fields():
    result_a = _baseline("A")
    result_b = _baseline(
        "B", decomposition_model="disc", ac_model="adr"
    )

    phase1 = run_phase1(result_a.config, result_a, result_b.config, result_b, DAYLIGHT)

    assert phase1.differing_stages == frozenset({Stage.DECOMPOSITION, Stage.AC})


def test_relabelling_pipelines_does_not_change_the_outcome():
    result_a = _baseline("A", p_dc=[3000.0] * 6, dc_model="singlediode_desoto")
    result_b = _baseline("B")

    ab = run_phase1(result_a.config, result_a, result_b.config, result_b, DAYLIGHT)
    ba = run_phase1(result_b.config, result_b, result_a.config, result_a, DAYLIGHT)

    assert ab.outcome == ba.outcome
    assert ab.k == ba.k
    assert ab.differing_stages == ba.differing_stages
    for stage in ab.metrics:
        assert ab.metrics[stage].nrmsd == pytest.approx(ba.metrics[stage].nrmsd)
        assert ab.metrics[stage].mbd == pytest.approx(-ba.metrics[stage].mbd)


def test_tau_is_recorded_on_the_result():
    result_a = _baseline("A")
    result_b = _baseline("B")

    phase1 = run_phase1(result_a.config, result_a, result_b.config, result_b, DAYLIGHT, tau_value=0.2)

    assert phase1.tau.value == 0.2
    assert phase1.tau.source == "user_entered"
