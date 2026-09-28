import copy
from pathlib import Path

import numpy as np
import pandas as pd
import pvlib
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
from pvdials.data.validate import validate_post_transposition
from pvdials.physics.adapters import AdapterError
from pvdials.physics.adapters.decomposition import decompose
from pvdials.physics.adapters.transposition import transpose
from pvdials.physics.geometry import TAG_DEFAULT, ArrayGeometry, resolve_albedo
from pvdials.physics.registry import stage_pool
from pvdials.physics.site import build_site_context
from pvdials.types import Stage

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
STAGE2_MODELS = [c.name for c in stage_pool(Stage.TRANSPOSITION)]
COLOMBO = SiteMetadata(
    values={"latitude": 6.944, "longitude": 79.856, "elevation": 16.0},
    sources={"latitude": "From CSV", "longitude": "From CSV", "elevation": "From CSV"},
)
GEOMETRY = ArrayGeometry(surface_tilt_deg=6.944, surface_azimuth_deg=180.0)
DEFAULT_ALBEDO = resolve_albedo(None, load_defaults())


def _fixture():
    uploaded = load_uploaded_csv(FIXTURES / "sample_pvgis_tmy.csv")
    weather = preprocess(uploaded.table, detect_columns(uploaded.table), canonical_year=2023).df
    site = detect_site_metadata(uploaded.preamble, uploaded.table)
    ctx = build_site_context(weather, site, detect_time_offset(uploaded.preamble))
    return weather, ctx


def _day(ghi_scale=900.0):
    idx = pd.date_range("2023-03-21", periods=24, freq="h", tz="UTC")
    weather = pd.DataFrame(
        {"ghi": 0.0, "temp_air": 28.0, "wind_speed": 1.0, "pressure": 101000.0}, index=idx
    )
    ctx = build_site_context(weather, COLOMBO, TimeOffset(0.5, TAG_FILE))
    cos_z = np.cos(np.radians(ctx.solpos["zenith"]))
    weather["ghi"] = (ghi_scale * cos_z).clip(lower=0)
    return weather, ctx


def _transpose(model, weather, ctx, albedo=DEFAULT_ALBEDO, geometry=GEOMETRY, defaults=None):
    decomposition = decompose("erbs", weather, ctx)
    return transpose(model, weather, decomposition, ctx, geometry, albedo, defaults=defaults)


@pytest.mark.parametrize("model", STAGE2_MODELS)
def test_every_model_runs_on_canonical_index_and_passes_sanity_check(model):
    for weather, ctx in (_fixture(), _day()):
        result = _transpose(model, weather, ctx)

        assert result.outputs.index.equals(weather.index)
        assert validate_post_transposition(result.outputs).passed


def test_all_seven_are_selectable_no_misfits():
    assert all(c.selectable for c in stage_pool(Stage.TRANSPOSITION))
    assert {c.name for c in stage_pool(Stage.TRANSPOSITION)} == {
        "isotropic",
        "klucher",
        "haydavies",
        "reindl",
        "king",
        "perez",
        "perez-driesse",
    }


def test_uses_apparent_zenith_not_true_zenith():
    weather, ctx = _day()
    other_weather, other_ctx = _day()
    other_weather["pressure"] = 97000.0  # changes apparent zenith only (Step 3 precedent)
    other_ctx = build_site_context(other_weather, COLOMBO, TimeOffset(0.5, TAG_FILE))

    pd.testing.assert_series_equal(ctx.solpos["zenith"], other_ctx.solpos["zenith"])
    assert not ctx.solpos["apparent_zenith"].equals(other_ctx.solpos["apparent_zenith"])

    base = _transpose("isotropic", weather, ctx)
    other = _transpose("isotropic", other_weather, other_ctx)
    assert not base.outputs["poa_global"].equals(other.outputs["poa_global"])


@pytest.mark.parametrize("model", ["haydavies", "reindl", "perez", "perez-driesse"])
def test_dni_extra_source_reaches_these_models(model):
    weather, ctx = _day()
    scaled_ctx = build_site_context(weather, COLOMBO, TimeOffset(0.5, TAG_FILE))
    object.__setattr__(scaled_ctx, "dni_extra", scaled_ctx.dni_extra * 1.1)

    base = _transpose(model, weather, ctx)
    other = _transpose(model, weather, scaled_ctx)

    assert not base.outputs["poa_global"].equals(other.outputs["poa_global"])
    assert base.records["dni_extra_source"] == "SiteContext"


@pytest.mark.parametrize("model", ["isotropic", "klucher", "king"])
def test_dni_extra_not_used_by_these_models(model):
    weather, ctx = _day()
    result = _transpose(model, weather, ctx)

    assert result.records["dni_extra_source"] == "not used by this model"


@pytest.mark.parametrize("model", ["perez", "perez-driesse"])
def test_airmass_source_reaches_these_models(model):
    weather, ctx = _day()
    scaled_ctx = build_site_context(weather, COLOMBO, TimeOffset(0.5, TAG_FILE))
    object.__setattr__(scaled_ctx, "airmass_relative", scaled_ctx.airmass_relative * 1.5)

    base = _transpose(model, weather, ctx)
    other = _transpose(model, weather, scaled_ctx)

    assert not base.outputs["poa_global"].equals(other.outputs["poa_global"])
    assert base.records["airmass_source"] == "SiteContext"


def test_perez_zero_ghi_divide_by_zero_is_fixed_and_recorded():
    # perez's own formula divides by DHI: GHI = DNI = DHI = 0 gives 0/0 = NaN
    # in pvlib, not the physically correct 0 (found on the real Colombo file, 23/09)
    idx = pd.date_range("2023-01-14 00:00", periods=3, freq="h", tz="UTC")
    weather = pd.DataFrame(
        {"ghi": 0.0, "temp_air": 25.0, "wind_speed": 1.0, "pressure": 101000.0}, index=idx
    )
    ctx = build_site_context(weather, COLOMBO, TimeOffset(0.5, TAG_FILE))
    decomposition = decompose("erbs", weather, ctx)
    assert (decomposition.outputs["dni"] == 0).all()
    assert (decomposition.outputs["dhi"] == 0).all()

    result = transpose("perez", weather, decomposition, ctx, GEOMETRY, DEFAULT_ALBEDO)

    assert (result.outputs["poa_global"] == 0).all()
    assert (result.outputs["poa_sky_diffuse"] == 0).all()
    assert (result.outputs["poa_diffuse"] == 0).all()
    assert (result.outputs["poa_direct"] == 0).all()
    assert (result.outputs["poa_ground_diffuse"] == 0).all()
    assert result.records["nan_at_zero_ghi_set_zero"] > 0


def test_no_nan_fix_recorded_for_models_without_the_divide_by_zero():
    weather, ctx = _day()
    result = _transpose("isotropic", weather, ctx)

    assert result.records["nan_at_zero_ghi_set_zero"] == 0


def test_airmass_not_used_by_haydavies():
    weather, ctx = _day()
    result = _transpose("haydavies", weather, ctx)

    assert result.records["airmass_source"] == "not used by this model"


def test_aoi_matches_independent_calculation():
    weather, ctx = _day()
    result = _transpose("isotropic", weather, ctx)

    expected = pvlib.irradiance.aoi(
        GEOMETRY.surface_tilt_deg,
        GEOMETRY.surface_azimuth_deg,
        ctx.solpos["apparent_zenith"],
        ctx.solpos["azimuth"],
    )
    np.testing.assert_allclose(result.outputs["aoi"], expected)


def test_albedo_defaults_to_prefill_when_not_given():
    albedo = resolve_albedo(None, load_defaults())

    assert albedo.value == 0.2
    assert albedo.source == TAG_DEFAULT


def test_albedo_user_value_is_tagged_and_changes_ground_diffuse():
    weather, ctx = _day()
    default_result = _transpose("isotropic", weather, ctx, albedo=DEFAULT_ALBEDO)
    user_albedo = resolve_albedo(0.6, load_defaults())
    other_result = _transpose("isotropic", weather, ctx, albedo=user_albedo)

    assert user_albedo.source == "user_entered"
    assert not default_result.outputs["poa_ground_diffuse"].equals(
        other_result.outputs["poa_ground_diffuse"]
    )
    assert other_result.records["albedo"] == 0.6
    assert other_result.records["albedo_source"] == "user_entered"


def test_model_perez_setting_changes_perez_but_not_isotropic():
    weather, ctx = _day()
    changed = copy.deepcopy(load_defaults())
    changed["stage2"]["model_perez"] = "sandiacomposite1988"

    base_perez = _transpose("perez", weather, ctx)
    other_perez = _transpose("perez", weather, ctx, defaults=changed)
    base_iso = _transpose("isotropic", weather, ctx)
    other_iso = _transpose("isotropic", weather, ctx, defaults=changed)

    assert not base_perez.outputs["poa_global"].equals(other_perez.outputs["poa_global"])
    pd.testing.assert_series_equal(base_iso.outputs["poa_global"], other_iso.outputs["poa_global"])


def test_same_input_twice_gives_identical_output():
    weather, ctx = _fixture()
    for model in STAGE2_MODELS:
        first, second = _transpose(model, weather, ctx), _transpose(model, weather, ctx)
        pd.testing.assert_frame_equal(first.outputs, second.outputs)
        assert first.records == second.records


def test_unknown_model_raises():
    weather, ctx = _day()

    with pytest.raises(AdapterError, match="not a Stage 2 candidate"):
        _transpose("no_such_model", weather, ctx)


def test_mismatched_decomposition_index_is_rejected():
    weather, ctx = _day()
    other_weather, other_ctx = _day()
    other_weather.index = other_weather.index + pd.Timedelta(days=1)
    other_ctx = build_site_context(other_weather, COLOMBO, TimeOffset(0.5, TAG_FILE))
    mismatched_decomposition = decompose("erbs", other_weather, other_ctx)

    with pytest.raises(AdapterError, match="[Dd]ecomposition"):
        transpose("isotropic", weather, mismatched_decomposition, ctx, GEOMETRY, DEFAULT_ALBEDO)


def test_mismatched_weather_and_context_index_is_rejected():
    weather, ctx = _day()
    other_weather, other_ctx = _day()
    other_weather.index = other_weather.index + pd.Timedelta(days=1)
    other_ctx = build_site_context(other_weather, COLOMBO, TimeOffset(0.5, TAG_FILE))
    decomposition = decompose("erbs", weather, ctx)

    with pytest.raises(AdapterError, match="site context"):
        transpose("isotropic", weather, decomposition, other_ctx, GEOMETRY, DEFAULT_ALBEDO)


# --- Real-file regression: the 24-row Stage 2 NaN fix (28/09) ----------------------

REAL_COLOMBO_FILE = Path("data/weather/tmy_6.939_79.854_2005_2023.csv")
requires_real_colombo_file = pytest.mark.skipif(
    not REAL_COLOMBO_FILE.exists(), reason=f"Real Colombo file not present at {REAL_COLOMBO_FILE}"
)


@pytest.mark.slow
@requires_real_colombo_file
def test_real_file_perez_fix_clears_downstream_dc_nans():
    """The originally-diagnosed case: pipeline C (dirint/perez/ross/
    singlediode_cec/sandia) had 24 NaN p_dc rows on the real Colombo file --
    poa_diffuse (not poa_global) was NaN at those rows, feeding straight into
    Stage 4's effective_irradiance. With the Stage 2 fix covering every
    output column, p_dc must have zero NaNs and the pipeline's annual AC
    energy must be finite.
    """
    from pvlib import pvsystem

    from pvdials.data.column_mapper import TAG_USER_ENTERED
    from pvdials.guided_reexecution import annual_yield_kwh
    from pvdials.physics.hardware import CEC, CEC_INVERTER, ArraySize, InverterRecord, ModuleRecord
    from pvdials.physics.mounting import resolve_mounting
    from pvdials.physics.pipeline import SharedInputs, run_pipeline
    from pvdials.types import PipelineConfig

    defaults = load_defaults()
    uploaded = load_uploaded_csv(REAL_COLOMBO_FILE)
    weather = preprocess(uploaded.table, detect_columns(uploaded.table)).df
    site = detect_site_metadata(uploaded.preamble, uploaded.table)
    offset = TimeOffset(
        0.0, TAG_USER_ENTERED,
        override_reason="header states 0.5 h; file day/night content aligns with 0 h",
    )
    ctx = build_site_context(weather, site, offset, defaults)

    cec_modules = pvsystem.retrieve_sam(CEC)
    module = ModuleRecord(CEC, "Canadian_Solar_Inc__CS6K_300MS", cec_modules["Canadian_Solar_Inc__CS6K_300MS"])
    cec_inverters = pvsystem.retrieve_sam(CEC_INVERTER)
    inv_name = "ABB__PVI_6000_OUTD_S_US_A__208V_"
    shared = SharedInputs(
        weather=weather, ctx=ctx, geometry=GEOMETRY,
        albedo=resolve_albedo(None, defaults), mounting=resolve_mounting(None, None, defaults),
        module=module, array_size=ArraySize(10, 2), module_height_m=3.0,
        inverter=InverterRecord(CEC_INVERTER, inv_name, cec_inverters[inv_name]),
    )
    config_c = PipelineConfig("C", "dirint", "perez", "ross", "singlediode_cec", "sandia")
    result_c = run_pipeline(config_c, shared, defaults)

    assert result_c.outputs.dc.outputs["p_dc"].isna().sum() == 0
    assert np.isfinite(annual_yield_kwh(result_c))
    assert result_c.validations["all_finite"].passed
