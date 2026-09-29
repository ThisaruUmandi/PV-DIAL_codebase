import math

import pandas as pd
import pytest

from pvdials.config import load_defaults
from pvdials.dla.metrics import (
    TAG_DEFAULT,
    TAG_USER_ENTERED,
    pair_metrics,
    pooled_p5_p95,
    resolve_tau,
    stage_series,
)
from pvdials.types import Stage
from tests.dla.builders import all_daylight, make_pipeline_result


def test_pair_metrics_matches_a_hand_computed_example():
    # 11 elements: n_pooled = 22 >= N_MIN (21), so nrmsd is a real number, not
    # "not computable" (28/09's sample-size guard) -- fewer would go vacuous.
    a = pd.Series([10.0, 20.0, 30.0, 40.0, 10.0, 20.0, 30.0, 40.0, 10.0, 20.0, 30.0])
    b = pd.Series([12.0, 18.0, 33.0, 36.0, 12.0, 18.0, 33.0, 36.0, 12.0, 18.0, 33.0])
    # diff = [-2, 2, -3, 4, -2, 2, -3, 4, -2, 2, -3]
    diffs = [-2, 2, -3, 4, -2, 2, -3, 4, -2, 2, -3]
    p5, p95 = pooled_p5_p95(a, b)

    metrics = pair_metrics(a, b, p5, p95)

    expected_rmsd = math.sqrt(sum(d**2 for d in diffs) / len(diffs))
    expected_mad = sum(abs(d) for d in diffs) / len(diffs)
    expected_mbd = sum(diffs) / len(diffs)
    assert metrics.rmsd == pytest.approx(expected_rmsd)
    assert metrics.mad == pytest.approx(expected_mad)
    assert metrics.mbd == pytest.approx(expected_mbd)
    assert metrics.not_computable_reason is None
    assert metrics.nrmsd == pytest.approx(expected_rmsd / (p95 - p5))
    assert metrics.systematic_share == pytest.approx(expected_mbd**2 / expected_rmsd**2)


def test_nrmsd_is_symmetric():
    a = pd.Series([10.0, 20.0, 30.0] * 4)
    b = pd.Series([12.0, 18.0, 33.0] * 4)
    p5, p95 = pooled_p5_p95(a, b)

    ab = pair_metrics(a, b, p5, p95)
    ba = pair_metrics(b, a, p5, p95)

    assert ab.not_computable_reason is None
    assert ab.rmsd == pytest.approx(ba.rmsd)
    assert ab.nrmsd == pytest.approx(ba.nrmsd)
    assert ab.mbd == pytest.approx(-ba.mbd)


def test_identical_series_give_zero_and_undefined_share():
    a = pd.Series([10.0, 20.0, 30.0])

    p5, p95 = pooled_p5_p95(a, a)
    metrics = pair_metrics(a, a, p5, p95)

    assert metrics.rmsd == 0.0
    assert metrics.mad == 0.0
    assert metrics.mbd == 0.0
    assert metrics.nrmsd == 0.0
    assert metrics.systematic_share is None  # 0/0, not a defensible zero


def test_stage3_celsius_and_kelvin_give_identical_nrmsd():
    celsius_a = pd.Series([20.0, 25.0, 30.0] * 4)
    celsius_b = pd.Series([22.0, 24.0, 33.0] * 4)
    kelvin_a = celsius_a + 273.15
    kelvin_b = celsius_b + 273.15

    p5_c, p95_c = pooled_p5_p95(celsius_a, celsius_b)
    p5_k, p95_k = pooled_p5_p95(kelvin_a, kelvin_b)

    metrics_c = pair_metrics(celsius_a, celsius_b, p5_c, p95_c)
    metrics_k = pair_metrics(kelvin_a, kelvin_b, p5_k, p95_k)

    assert metrics_c.not_computable_reason is None
    assert metrics_c.nrmsd == pytest.approx(metrics_k.nrmsd)


def test_stage1_concatenation_is_sensitive_to_dhi_even_when_dni_matches():
    result_a = make_pipeline_result(
        "A", dni=[100, 100, 100], dhi=[50, 50, 50],
        poa_global=[0] * 3, temp_cell=[0] * 3, p_dc=[0] * 3, p_ac=[0] * 3,
        index=pd.date_range("2023-06-21 08:00", periods=3, freq="h", tz="UTC"),
    )
    result_b = make_pipeline_result(
        "B", dni=[100, 100, 100], dhi=[80, 80, 80],  # DNI identical, DHI differs
        poa_global=[0] * 3, temp_cell=[0] * 3, p_dc=[0] * 3, p_ac=[0] * 3,
        index=pd.date_range("2023-06-21 08:00", periods=3, freq="h", tz="UTC"),
    )
    daylight = all_daylight(pd.date_range("2023-06-21 08:00", periods=3, freq="h", tz="UTC"))

    series_a = stage_series(result_a.outputs, Stage.DECOMPOSITION, daylight)
    series_b = stage_series(result_b.outputs, Stage.DECOMPOSITION, daylight)
    p5, p95 = pooled_p5_p95(series_a, series_b)
    metrics = pair_metrics(series_a, series_b, p5, p95)

    assert metrics.rmsd > 0  # a DNI-only metric would have reported 0 here
    assert len(series_a) == 6  # 3 DNI rows + 3 DHI rows concatenated


def test_stage1_pooling_spans_both_components_and_both_pipelines():
    result_a = make_pipeline_result(
        "A", dni=[100, 200], dhi=[10, 20],
        poa_global=[0] * 2, temp_cell=[0] * 2, p_dc=[0] * 2, p_ac=[0] * 2,
        index=pd.date_range("2023-06-21 08:00", periods=2, freq="h", tz="UTC"),
    )
    result_b = make_pipeline_result(
        "B", dni=[110, 210], dhi=[15, 25],
        poa_global=[0] * 2, temp_cell=[0] * 2, p_dc=[0] * 2, p_ac=[0] * 2,
        index=pd.date_range("2023-06-21 08:00", periods=2, freq="h", tz="UTC"),
    )
    daylight = all_daylight(pd.date_range("2023-06-21 08:00", periods=2, freq="h", tz="UTC"))

    series_a = stage_series(result_a.outputs, Stage.DECOMPOSITION, daylight)
    series_b = stage_series(result_b.outputs, Stage.DECOMPOSITION, daylight)
    p5, p95 = pooled_p5_p95(series_a, series_b)

    # Pooled set = DNI_a, DNI_b, DHI_a, DHI_b = [100,200,110,210,10,20,15,25]
    all_values = pd.Series([100, 200, 110, 210, 10, 20, 15, 25])
    assert p5 == pytest.approx(all_values.quantile(0.05))
    assert p95 == pytest.approx(all_values.quantile(0.95))


def test_resolve_tau_default_and_user_entered():
    defaults = load_defaults()

    default_tau = resolve_tau(None, defaults)
    user_tau = resolve_tau(0.1, defaults)

    assert default_tau.value == defaults["dla"]["tau"]
    assert default_tau.source == TAG_DEFAULT
    assert user_tau.value == 0.1
    assert user_tau.source == TAG_USER_ENTERED


def test_production_default_tau_is_0_093():
    """A literal, load-bearing check of configs/run_defaults.yaml's actual
    value -- not tautological like test_resolve_tau_default_and_user_entered
    above (which only confirms resolve_tau reads back whatever's there).
    28/09: 0.093, experiments/tau_calibration/trivial_plateau_amendment_exhaustive.py
    (amended plateau rule, exhaustive over all 2,116,653 valid-pair
    combinations; supersedes N34's 0.234, which the amended rule found
    100% near-trivial-high across the whole population). If this ever fails,
    it means run_defaults.yaml's tau changed -- update this test deliberately,
    don't just silence it, since other tests assume specific outcomes at
    specific tau values and may need re-tuning too (28/09 found one such
    case the hard way: test_only_one_qualifying_pair_runs_phase2_and_gates_phase3_per_pair
    in tests/unit/test_analysis.py, now fixed with its own explicit tau).
    """
    assert load_defaults()["dla"]["tau"] == 0.093


# --- N_MIN sample-size guard (28/09) ------------------------------------------------


def test_n_min_is_21_derived_from_the_quantile_constants():
    from pvdials.dla.metrics import N_MIN, P5_QUANTILE

    # n_min: smallest n such that P5_QUANTILE*(n-1) >= 1 (P5 draws on a third
    # value, not just the two smallest pooled ones).
    assert P5_QUANTILE * (N_MIN - 1) >= 1
    assert P5_QUANTILE * (N_MIN - 2) < 1
    assert N_MIN == 21


def test_boundary_n_pooled_20_is_not_computable():
    a = pd.Series(list(range(10)), dtype=float)
    b = pd.Series([v + 1.0 for v in range(10)])
    p5, p95 = pooled_p5_p95(a, b)

    metrics = pair_metrics(a, b, p5, p95)

    assert metrics.n_pooled == 20
    assert metrics.nrmsd is None
    assert metrics.not_computable_reason == "too few daylight samples (n pooled < 21)"


def test_boundary_n_pooled_22_is_computable():
    # n_pooled is always even in practice (both series are daylight-masked to
    # the same length), so 21 itself can never occur -- 20 (not computable)
    # vs 22 (computable) is the real boundary this guard draws.
    a = pd.Series(list(range(11)), dtype=float)
    b = pd.Series([v + 1.0 for v in range(11)])
    p5, p95 = pooled_p5_p95(a, b)

    metrics = pair_metrics(a, b, p5, p95)

    assert metrics.n_pooled == 22
    assert metrics.not_computable_reason is None
    assert metrics.nrmsd is not None


def test_zero_pooled_spread_is_not_computable():
    # 41 pooled values are 5.0, one is 6.0 -> P5 and P95 both land on 5.0
    # (interpolated between repeated 5.0s), so P95-P5=0 even though rmsd!=0.
    a = pd.Series([5.0] * 21)
    b = pd.Series([5.0] * 20 + [6.0])
    p5, p95 = pooled_p5_p95(a, b)
    assert p95 - p5 == 0.0

    metrics = pair_metrics(a, b, p5, p95)

    assert metrics.rmsd > 0
    assert metrics.n_pooled == 42
    assert metrics.nrmsd is None
    assert metrics.not_computable_reason == "zero spread (P95 - P5 = 0)"


def test_rmsd_zero_is_always_computable_regardless_of_sample_size():
    # rmsd==0 is checked before the sample-size guard: two identical series
    # have zero disagreement unconditionally, even with very few points.
    a = pd.Series([10.0, 20.0, 30.0])

    p5, p95 = pooled_p5_p95(a, a)
    metrics = pair_metrics(a, a, p5, p95)

    assert metrics.n_pooled == 6
    assert metrics.rmsd == 0.0
    assert metrics.nrmsd == 0.0
    assert metrics.not_computable_reason is None
    assert metrics.systematic_share is None  # 0/0, not a defensible zero


def test_one_daylight_row_fixture_is_not_computable_not_10_over_9():
    """The originally-diagnosed degenerate case (25/09): with exactly 1
    daylight row per pipeline, P95-P5 collapsed to 0.9*|a-b|, giving nRMSD a
    fixed 10/9 regardless of the actual disagreement. The sample-size guard
    now catches this directly: n_pooled=2 < N_MIN, so nrmsd is None with a
    clear reason, not a silently-meaningless 1.1111.
    """
    a = pd.Series([100.0])
    b = pd.Series([150.0])
    p5, p95 = pooled_p5_p95(a, b)

    metrics = pair_metrics(a, b, p5, p95)

    assert metrics.n_pooled == 2
    assert metrics.nrmsd is None
    assert metrics.not_computable_reason == "too few daylight samples (n pooled < 21)"
