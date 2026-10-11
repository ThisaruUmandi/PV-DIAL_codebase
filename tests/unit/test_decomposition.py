import copy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pvdials.config import load_defaults
from pvdials.data.column_mapper import (
    TAG_FILE,
    SiteMetadata,
    TimeOffset,
    detect_columns,
    detect_site_metadata,
    detect_time_offset,
)
from pvdials.data.preprocess import preprocess
from pvdials.data.upload import load_uploaded_csv
from pvdials.data.validate import validate_post_decomposition
from pvdials.physics.adapters.decomposition import CLOSURE_RULE, AdapterError, decompose
from pvdials.physics.registry import stage_pool
from pvdials.physics.site import build_site_context
from pvdials.types import Stage

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SELECTABLE = [c.name for c in stage_pool(Stage.DECOMPOSITION) if c.selectable]
COLOMBO = SiteMetadata(
    values={"latitude": 6.944, "longitude": 79.856, "elevation": 16.0},
    sources={"latitude": "From CSV", "longitude": "From CSV", "elevation": "From CSV"},
)


def _fixture():
    uploaded = load_uploaded_csv(FIXTURES / "sample_pvgis_tmy.csv")
    weather = preprocess(uploaded.table, detect_columns(uploaded.table), canonical_year=2023).df
    site = detect_site_metadata(uploaded.preamble, uploaded.table)
    return weather, build_site_context(weather, site, detect_time_offset(uploaded.preamble))


def _day(ghi_scale=900.0):
    """One hourly day at HH:30 effective times; GHI follows the sun (0 when it's down)."""
    idx = pd.date_range("2023-03-21", periods=24, freq="h", tz="UTC")
    weather = pd.DataFrame(
        {"ghi": 0.0, "temp_air": 28.0, "wind_speed": 1.0, "pressure": 101000.0}, index=idx
    )
    ctx = build_site_context(weather, COLOMBO, TimeOffset(0.5, TAG_FILE))
    cos_z = np.cos(np.radians(ctx.solpos["zenith"]))
    weather["ghi"] = (ghi_scale * cos_z).clip(lower=0)
    return weather, ctx


@pytest.mark.parametrize("model", SELECTABLE)
def test_every_selectable_model_runs_on_canonical_index(model):
    for weather, ctx in (_fixture(), _day()):
        result = decompose(model, weather, ctx)

        assert result.outputs.index.equals(weather.index)  # no HH:00 / HH:30 doubling
        assert list(result.outputs.columns) == ["dni", "dhi"]


@pytest.mark.parametrize("model", SELECTABLE)
def test_every_selectable_model_passes_tier6_on_a_full_day(model):
    weather, ctx = _day()

    assert validate_post_decomposition(decompose(model, weather, ctx).outputs).passed


def test_dirint_series_edge_daylight_row_is_reported_by_tier6():
    # OPEN (23/09): with use_delta_kt_prime, dirint compares each hour with its
    # neighbours. The fixture ends on a sunrise hour whose only neighbour is a
    # night row, so dirint returns NaN there. Rule not decided; Tier 6 reports it.
    weather, ctx = _fixture()
    result = decompose("dirint", weather, ctx)

    assert ctx.daylight.iloc[-1]
    assert np.isnan(result.outputs["dni"].iloc[-1])
    assert not validate_post_decomposition(result.outputs).passed


@pytest.mark.parametrize("model", ["disc", "dirint"])
def test_closure_models_derive_dhi_from_true_zenith(model):
    weather, ctx = _day()
    result = decompose(model, weather, ctx)

    zenith = ctx.solpos["zenith"]
    closure = weather["ghi"] - result.outputs["dni"] * np.cos(np.radians(zenith))
    expected = closure.clip(lower=0.0)
    np.testing.assert_allclose(result.outputs["dhi"], expected)
    assert result.records["dhi_source"] == CLOSURE_RULE


def test_dirint_nan_beyond_guard_set_to_zero_and_counted():
    weather, ctx = _day()
    result = decompose("dirint", weather, ctx)

    beyond = ctx.solpos["zenith"] >= 87
    assert beyond.any()
    assert (result.outputs.loc[beyond, "dni"] == 0).all()
    assert result.records["nan_beyond_guard_set_zero"] > 0


def test_louche_negative_dhi_clipped_and_recorded():
    weather, ctx = _day(ghi_scale=0.0)  # GHI = 0 all day; louche still gives DNI ~ 0.002*ETR

    result = decompose("louche", weather, ctx)

    assert (result.outputs["dhi"] >= 0).all()
    assert result.records["dhi_clipped_count"] > 0
    assert result.records["dhi_clipped_min_w_m2"] < 0


def test_no_clip_recorded_when_nothing_negative():
    weather, ctx = _day()
    result = decompose("erbs", weather, ctx)

    assert result.records["dhi_clipped_count"] == 0
    assert result.records["dhi_clipped_min_w_m2"] is None


def test_coefficients_come_from_defaults():
    weather, ctx = _day()
    changed = copy.deepcopy(load_defaults())
    changed["stage1"]["boland"]["a_coeff"] = 5.0

    base = decompose("boland", weather, ctx)
    other = decompose("boland", weather, ctx, defaults=changed)

    assert not base.outputs.equals(other.outputs)
    assert other.records["coefficients"]["a_coeff"] == 5.0


def test_same_input_twice_gives_identical_output():
    weather, ctx = _fixture()
    for model in SELECTABLE:
        first, second = decompose(model, weather, ctx), decompose(model, weather, ctx)
        pd.testing.assert_frame_equal(first.outputs, second.outputs)
        assert first.records == second.records


def test_non_selectable_model_raises_with_its_reason():
    weather, ctx = _day()

    with pytest.raises(AdapterError, match="clear-sky"):
        decompose("dirindex", weather, ctx)


def test_unknown_model_raises():
    weather, ctx = _day()

    with pytest.raises(AdapterError, match="not a Stage 1 candidate"):
        decompose("no_such_model", weather, ctx)


def test_tier6_catches_negative_and_nonfinite_values():
    bad = pd.DataFrame({"dni": [1.0, np.nan], "dhi": [-0.5, 2.0]})

    result = validate_post_decomposition(bad)

    assert not result.passed
    assert any("non-finite" in p for p in result.problems)
    assert any("negative" in p for p in result.problems)
