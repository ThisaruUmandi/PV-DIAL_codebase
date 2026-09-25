import pandas as pd
import pytest

from pvdials.dla.phase1 import run_phase1
from pvdials.dla.phase2 import run_phase2
from pvdials.types import Stage
from tests.dla.builders import all_daylight, make_pipeline_result

INDEX = pd.date_range("2023-06-21 08:00", periods=6, freq="h", tz="UTC")
DAYLIGHT = all_daylight(INDEX)
_RAMP = [0.7, 0.85, 1.0, 1.0, 0.85, 0.7]


def _pipeline(label, dc_scale=1.0, ac_scale=1.0, dc_model="singlediode_cec", ac_model="sandia"):
    return make_pipeline_result(
        label,
        dc_model=dc_model,
        ac_model=ac_model,
        dni=[v * 400.0 for v in _RAMP],
        dhi=[v * 100.0 for v in _RAMP],
        poa_global=[v * 500.0 for v in _RAMP],
        temp_cell=[v * 45.0 for v in _RAMP],
        p_dc=[v * 1500.0 * dc_scale for v in _RAMP],
        p_ac=[v * 1400.0 * ac_scale for v in _RAMP],
        index=INDEX,
    )


def test_delta_1_is_mean_nrmsd_1_minus_zero():
    a = _pipeline("A")
    b = _pipeline("B", dc_scale=1.5, ac_scale=1.5, dc_model="singlediode_desoto")
    c = _pipeline("C")

    ab = run_phase1(a.config, a, b.config, b, DAYLIGHT)
    ac = run_phase1(a.config, a, c.config, c, DAYLIGHT)
    bc = run_phase1(b.config, b, c.config, c, DAYLIGHT)

    phase2 = run_phase2(ab, ac, bc)

    assert phase2.delta[Stage.DECOMPOSITION] == pytest.approx(phase2.mean_nrmsd[Stage.DECOMPOSITION])


def test_mean_and_max_match_hand_computed_values_across_three_pairs():
    a = _pipeline("A")
    b = _pipeline("B", dc_scale=1.5, ac_scale=1.5, dc_model="singlediode_desoto")
    c = _pipeline("C")  # identical to A

    ab = run_phase1(a.config, a, b.config, b, DAYLIGHT)
    ac = run_phase1(a.config, a, c.config, c, DAYLIGHT)
    bc = run_phase1(b.config, b, c.config, c, DAYLIGHT)

    phase2 = run_phase2(ab, ac, bc)

    # A-C is identical (0 everywhere); A-B and B-C both see the same DC-scale
    # disagreement (B differs from both A and C the same way).
    expected_mean_dc = (ab.metrics[Stage.DC].nrmsd + 0.0 + bc.metrics[Stage.DC].nrmsd) / 3
    expected_max_dc = max(ab.metrics[Stage.DC].nrmsd, 0.0, bc.metrics[Stage.DC].nrmsd)

    assert phase2.mean_nrmsd[Stage.DC] == pytest.approx(expected_mean_dc)
    assert phase2.max_nrmsd[Stage.DC] == pytest.approx(expected_max_dc)
    assert ac.metrics[Stage.DC].nrmsd == 0.0
    assert phase2.pair_nrmsd[("A", "C")][Stage.DC] == 0.0


def test_only_pair_curves_appear_never_per_pipeline():
    a = _pipeline("A")
    b = _pipeline("B", dc_scale=1.5, ac_scale=1.5, dc_model="singlediode_desoto")
    c = _pipeline("C")

    ab = run_phase1(a.config, a, b.config, b, DAYLIGHT)
    ac = run_phase1(a.config, a, c.config, c, DAYLIGHT)
    bc = run_phase1(b.config, b, c.config, c, DAYLIGHT)

    phase2 = run_phase2(ab, ac, bc)

    assert set(phase2.pair_nrmsd.keys()) == {("A", "B"), ("A", "C"), ("B", "C")}
    for label in ("A", "B", "C"):
        assert (label,) not in phase2.pair_nrmsd  # no single-pipeline entries
