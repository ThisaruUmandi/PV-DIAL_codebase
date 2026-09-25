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
    a = pd.Series([10.0, 20.0, 30.0, 40.0])
    b = pd.Series([12.0, 18.0, 33.0, 36.0])
    # diff = [-2, 2, -3, 4]
    p5, p95 = pooled_p5_p95(a, b)

    metrics = pair_metrics(a, b, p5, p95)

    expected_rmsd = math.sqrt((4 + 4 + 9 + 16) / 4)
    expected_mad = (2 + 2 + 3 + 4) / 4
    expected_mbd = (-2 + 2 - 3 + 4) / 4
    assert metrics.rmsd == pytest.approx(expected_rmsd)
    assert metrics.mad == pytest.approx(expected_mad)
    assert metrics.mbd == pytest.approx(expected_mbd)
    assert metrics.nrmsd == pytest.approx(expected_rmsd / (p95 - p5))
    assert metrics.systematic_share == pytest.approx(expected_mbd**2 / expected_rmsd**2)


def test_nrmsd_is_symmetric():
    a = pd.Series([10.0, 20.0, 30.0])
    b = pd.Series([12.0, 18.0, 33.0])
    p5, p95 = pooled_p5_p95(a, b)

    ab = pair_metrics(a, b, p5, p95)
    ba = pair_metrics(b, a, p5, p95)

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
    celsius_a = pd.Series([20.0, 25.0, 30.0])
    celsius_b = pd.Series([22.0, 24.0, 33.0])
    kelvin_a = celsius_a + 273.15
    kelvin_b = celsius_b + 273.15

    p5_c, p95_c = pooled_p5_p95(celsius_a, celsius_b)
    p5_k, p95_k = pooled_p5_p95(kelvin_a, kelvin_b)

    metrics_c = pair_metrics(celsius_a, celsius_b, p5_c, p95_c)
    metrics_k = pair_metrics(kelvin_a, kelvin_b, p5_k, p95_k)

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
