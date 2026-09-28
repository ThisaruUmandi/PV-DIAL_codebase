import copy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pvlib import pvsystem

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
from pvdials.data.validate import validate_post_dc
from pvdials.physics.adapters import AdapterError
from pvdials.physics.adapters.dc import dc_power
from pvdials.physics.adapters.decomposition import decompose
from pvdials.physics.adapters.temperature import cell_temperature
from pvdials.physics.adapters.transposition import transpose
from pvdials.physics.geometry import ArrayGeometry, resolve_albedo
from pvdials.physics.hardware import CEC, SANDIA, ModuleRecord
from pvdials.physics.mounting import resolve_mounting
from pvdials.physics.registry import stage_pool
from pvdials.physics.site import build_site_context
from pvdials.types import Stage

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
STAGE4_SELECTABLE = [c.name for c in stage_pool(Stage.DC) if c.selectable]
COLOMBO = SiteMetadata(
    values={"latitude": 6.944, "longitude": 79.856, "elevation": 16.0},
    sources={"latitude": "From CSV", "longitude": "From CSV", "elevation": "From CSV"},
)
GEOMETRY = ArrayGeometry(surface_tilt_deg=6.944, surface_azimuth_deg=180.0)
DEFAULT_ALBEDO = resolve_albedo(None, load_defaults())
DEFAULT_MOUNTING = resolve_mounting(None, None, load_defaults())

CEC_MODULES = pvsystem.retrieve_sam(CEC)
CEC_NAME = "Canadian_Solar_Inc__CS6K_300MS"
CEC_MODULE = ModuleRecord(CEC, CEC_NAME, CEC_MODULES[CEC_NAME])

SANDIA_MODULES = pvsystem.retrieve_sam(SANDIA)
SANDIA_NAME = SANDIA_MODULES.columns[0]
SANDIA_MODULE = ModuleRecord(SANDIA, SANDIA_NAME, SANDIA_MODULES[SANDIA_NAME])

# pvlib's lambertw MPP search (pvsystem.singlediode(method="lambertw"), the
# method configured here) degenerates to a single-point bracket at IL=0 and
# warns on a harmless divide-by-zero inside scipy's _chandrupatla_minimize
# (used internally for that MPP search, not the bishop88/chandrupatla IV-curve
# method); not relevant to what these tests check.
pytestmark = pytest.mark.filterwarnings("ignore::RuntimeWarning")


def _day(ghi_scale=900.0):
    idx = pd.date_range("2023-03-21", periods=24, freq="h", tz="UTC")
    weather = pd.DataFrame(
        {"ghi": 0.0, "temp_air": 28.0, "wind_speed": 1.0, "pressure": 101000.0}, index=idx
    )
    ctx = build_site_context(weather, COLOMBO, TimeOffset(0.5, TAG_FILE))
    cos_z = np.cos(np.radians(ctx.solpos["zenith"]))
    weather["ghi"] = (ghi_scale * cos_z).clip(lower=0)
    return weather, ctx


def _fixture():
    uploaded = load_uploaded_csv(FIXTURES / "sample_pvgis_tmy.csv")
    weather = preprocess(uploaded.table, detect_columns(uploaded.table), canonical_year=2023).df
    site = detect_site_metadata(uploaded.preamble, uploaded.table)
    ctx = build_site_context(weather, site, detect_time_offset(uploaded.preamble))
    return weather, ctx


def _stages(weather, ctx, module=CEC_MODULE):
    decomposition = decompose("erbs", weather, ctx)
    transposition = transpose("isotropic", weather, decomposition, ctx, GEOMETRY, DEFAULT_ALBEDO)
    temperature = cell_temperature(
        "faiman", transposition, weather, DEFAULT_MOUNTING, GEOMETRY, module=module
    )
    return transposition, temperature


def _dc(model, weather, ctx, module=CEC_MODULE, mps=10, spi=2, **kwargs):
    transposition, temperature = _stages(weather, ctx, module=module)
    return dc_power(
        model,
        transposition,
        temperature,
        ctx,
        module,
        modules_per_string=mps,
        strings_per_inverter=spi,
        **kwargs,
    )


def _module_for(model):
    return SANDIA_MODULE if model == "sapm" else CEC_MODULE


@pytest.mark.parametrize("model", STAGE4_SELECTABLE)
def test_every_selectable_model_runs_and_passes_sanity_check(model):
    module = _module_for(model)
    for weather, ctx in (_fixture(), _day()):
        result = _dc(model, weather, ctx, module=module)

        assert result.outputs.index.equals(weather.index)
        assert validate_post_dc(result.outputs).passed


def test_pvwatts_dc_runs_on_both_module_libraries():
    weather, ctx = _day()
    for module in (CEC_MODULE, SANDIA_MODULE):
        result = _dc("pvwatts_dc", weather, ctx, module=module)
        assert validate_post_dc(result.outputs).passed


@pytest.mark.parametrize("model", ["sapm", "singlediode_desoto", "singlediode_cec"])
def test_wrong_library_raises(model):
    weather, ctx = _day()
    wrong_module = CEC_MODULE if model == "sapm" else SANDIA_MODULE

    with pytest.raises(AdapterError):
        _dc(model, weather, ctx, module=wrong_module)


def test_singlediode_pvsyst_is_structurally_excluded():
    weather, ctx = _day()

    with pytest.raises(AdapterError, match="gamma_ref"):
        _dc("singlediode_pvsyst", weather, ctx)


@pytest.mark.parametrize("model", STAGE4_SELECTABLE)
def test_array_size_is_required(model):
    weather, ctx = _day()
    module = _module_for(model)
    transposition, temperature = _stages(weather, ctx, module=module)

    with pytest.raises(AdapterError, match="[Nn]o default"):
        dc_power(model, transposition, temperature, ctx, module)


def test_pvwatts_dc_power_scales_by_array_size():
    weather, ctx = _day()
    unit = _dc("pvwatts_dc", weather, ctx, mps=1, spi=1)
    array = _dc("pvwatts_dc", weather, ctx, mps=10, spi=2)

    ratio = (array.outputs["p_dc"] / unit.outputs["p_dc"]).dropna()
    np.testing.assert_allclose(ratio, 20.0)


def test_sapm_voltage_and_current_scale_independently():
    weather, ctx = _day()
    unit = _dc("sapm", weather, ctx, module=SANDIA_MODULE, mps=1, spi=1)
    array = _dc("sapm", weather, ctx, module=SANDIA_MODULE, mps=10, spi=2)

    v_ratio = (array.outputs["v_dc"] / unit.outputs["v_dc"]).dropna()
    i_ratio = (array.outputs["i_dc"] / unit.outputs["i_dc"]).dropna()
    np.testing.assert_allclose(v_ratio, 10.0)
    np.testing.assert_allclose(i_ratio, 2.0)


@pytest.mark.parametrize("model", ["singlediode_desoto", "singlediode_cec"])
def test_singlediode_voltage_and_current_scale_independently(model):
    weather, ctx = _day()
    unit = _dc(model, weather, ctx, mps=1, spi=1)
    array = _dc(model, weather, ctx, mps=10, spi=2)

    v_ratio = (array.outputs["v_dc"] / unit.outputs["v_dc"]).dropna()
    i_ratio = (array.outputs["i_dc"] / unit.outputs["i_dc"]).dropna()
    np.testing.assert_allclose(v_ratio, 10.0)
    np.testing.assert_allclose(i_ratio, 2.0)


def test_pvwatts_dc_has_no_voltage_or_current():
    weather, ctx = _day()
    result = _dc("pvwatts_dc", weather, ctx)

    assert "v_dc" not in result.outputs.columns
    assert result.records["v_dc"] == "not produced by this model"
    assert result.records["i_dc"] == "not produced by this model"


@pytest.mark.parametrize("model", ["sapm", "singlediode_desoto", "singlediode_cec"])
def test_models_that_produce_voltage_and_current_have_them(model):
    weather, ctx = _day()
    module = _module_for(model)
    result = _dc(model, weather, ctx, module=module)

    assert {"p_dc", "v_dc", "i_dc"} == set(result.outputs.columns)


def test_sapm_zero_irradiance_nan_is_fixed_and_recorded():
    # sapm()'s own v_mp formula uses log(effective_irradiance): at 0 that's -inf,
    # times an i_mp of exactly 0, giving NaN rather than the correct 0 (found on
    # the real Colombo file, 23/09).
    idx = pd.date_range("2023-01-01 00:00", periods=3, freq="h", tz="UTC")
    weather = pd.DataFrame(
        {"ghi": 0.0, "temp_air": 25.0, "wind_speed": 1.0, "pressure": 101000.0}, index=idx
    )
    ctx = build_site_context(weather, COLOMBO, TimeOffset(0.5, TAG_FILE))
    result = _dc("sapm", weather, ctx, module=SANDIA_MODULE)

    assert (result.outputs["p_dc"] == 0).all()
    assert (result.outputs["v_dc"] == 0).all()
    assert result.records["nan_at_zero_irradiance_set_zero"] > 0


@pytest.mark.parametrize("model", ["singlediode_desoto", "singlediode_cec"])
def test_singlediode_zero_irradiance_residual_is_forced_to_exact_zero_and_recorded(model):
    # At IL=0, pvlib's lambertw MPP search degenerates to a single-point
    # bracket and returns a tiny nonzero v_mp/p_mp/i_mp residual instead of
    # exact 0 -- not NaN, but wrong (no irradiance, no photocurrent, exactly
    # zero output). inverter.adr() only recognises night at bit-exact
    # v_dc=0.0 (28/09), so an unpatched residual reads as NaN downstream.
    weather, ctx = _day()
    result = _dc(model, weather, ctx)

    zero_irradiance = weather["ghi"].to_numpy(dtype=float) == 0.0
    assert zero_irradiance.any(), "fixture must contain real zero-GHI (night) rows"
    for col in ("p_dc", "v_dc", "i_dc"):
        assert (result.outputs.loc[zero_irradiance, col] == 0.0).all()
    assert result.records["effective_irradiance_zero_forced_exact_zero"] == int(zero_irradiance.sum())


def test_pdc0_and_gamma_pdc_reach_the_adapter():
    weather, ctx = _day()
    changed = copy.deepcopy(load_defaults())

    base = _dc("pvwatts_dc", weather, ctx, defaults=load_defaults())
    other = _dc("pvwatts_dc", weather, ctx, defaults=changed)  # same values, sanity baseline

    assert base.records["pdc0"] == pytest.approx(float(CEC_MODULE.params["STC"]))
    assert base.records["gamma_pdc"] == pytest.approx(float(CEC_MODULE.params["gamma_r"]) / 100.0)
    pd.testing.assert_frame_equal(base.outputs, other.outputs)


def test_gamma_r_unit_conversion_matters():
    # If gamma_r (%/degC) were used unconverted as gamma_pdc (1/degC), the
    # temperature response would be ~100x too strong.
    weather, ctx = _day()
    result = _dc("pvwatts_dc", weather, ctx)

    assert -0.01 < result.records["gamma_pdc"] < -0.001


def test_iam_physical_setting_reaches_the_adapter():
    weather, ctx = _day()
    changed = copy.deepcopy(load_defaults())
    changed["stage4"]["iam_physical"]["L"] = 0.02  # far from the default 0.002

    base = _dc("singlediode_cec", weather, ctx, defaults=load_defaults())
    other = _dc("singlediode_cec", weather, ctx, defaults=changed)

    assert not base.outputs["p_dc"].equals(other.outputs["p_dc"])


REAL_COLOMBO_FILE = Path("data/weather/tmy_6.939_79.854_2005_2023.csv")
requires_real_colombo_file = pytest.mark.skipif(
    not REAL_COLOMBO_FILE.exists(), reason=f"Real Colombo file not present at {REAL_COLOMBO_FILE}"
)


@pytest.mark.slow
@requires_real_colombo_file
def test_real_file_adr_night_nan_is_cured_and_matches_sandia():
    """The 28/09-diagnosed pool-scan finding: 588/2,058 chains failed, 100%
    ac_model='adr', 100% at night, 0% daylight -- root-caused to the
    singlediode lambertw solver's tiny nonzero v_dc residual at zero
    irradiance, which fails adr()'s bit-exact v_dc==0 night check (sandia's
    p_dc<Pso threshold tolerates the same residual fine). With this stage's
    forced-exact-zero patch, adr must have zero NaN p_ac and agree with
    sandia's own night-tare value on the same real zero-GHI rows.
    """
    from pvlib import pvsystem as _pvsystem

    from pvdials.data.column_mapper import TAG_USER_ENTERED
    from pvdials.physics.hardware import ADR_INVERTER, CEC_INVERTER, ArraySize, InverterRecord
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

    cec_inverters = _pvsystem.retrieve_sam(CEC_INVERTER)
    adr_inverters = _pvsystem.retrieve_sam(ADR_INVERTER)
    inv_name = "ABB__PVI_6000_OUTD_S_US_A__208V_"
    base = {
        "weather": weather, "ctx": ctx, "geometry": GEOMETRY, "albedo": DEFAULT_ALBEDO,
        "mounting": DEFAULT_MOUNTING, "module": CEC_MODULE, "array_size": ArraySize(10, 2),
        "module_height_m": 3.0,
    }
    shared_cec = SharedInputs(**base, inverter=InverterRecord(CEC_INVERTER, inv_name, cec_inverters[inv_name]))
    shared_adr = SharedInputs(**base, inverter=InverterRecord(ADR_INVERTER, inv_name, adr_inverters[inv_name]))

    config_sandia = PipelineConfig("S", "dirint", "perez", "ross", "singlediode_cec", "sandia")
    config_adr = PipelineConfig("R", "dirint", "perez", "ross", "singlediode_cec", "adr")
    result_sandia = run_pipeline(config_sandia, shared_cec, defaults)
    result_adr = run_pipeline(config_adr, shared_adr, defaults)

    assert result_adr.outputs.ac.outputs["p_ac"].isna().sum() == 0
    assert result_adr.validations["all_finite"].passed

    zero_ghi = weather["ghi"].to_numpy(dtype=float) == 0.0
    assert zero_ghi.any()
    p_ac_adr_night = result_adr.outputs.ac.outputs["p_ac"][zero_ghi]
    p_ac_sandia_night = result_sandia.outputs.ac.outputs["p_ac"][zero_ghi]
    pd.testing.assert_series_equal(p_ac_adr_night, p_ac_sandia_night, check_names=False)


def test_effective_irradiance_path_recorded():
    weather, ctx = _day()

    no_spectral = _dc("pvwatts_dc", weather, ctx)
    sapm_path = _dc("sapm", weather, ctx, module=SANDIA_MODULE)

    assert "no_spectral" in no_spectral.records["effective_irradiance_path"]
    assert "sapm" in sapm_path.records["effective_irradiance_path"]


def test_same_input_twice_gives_identical_output():
    weather, ctx = _fixture()
    for model in STAGE4_SELECTABLE:
        module = _module_for(model)
        first = _dc(model, weather, ctx, module=module)
        second = _dc(model, weather, ctx, module=module)
        pd.testing.assert_frame_equal(first.outputs, second.outputs)
        assert first.records == second.records


def test_unknown_model_raises():
    weather, ctx = _day()

    with pytest.raises(AdapterError, match="not a Stage 4 candidate"):
        _dc("no_such_model", weather, ctx)


def test_mismatched_transposition_temperature_index_is_rejected():
    weather, ctx = _day()
    transposition, temperature = _stages(weather, ctx)
    short_transposition = transposition.__class__(
        outputs=transposition.outputs.iloc[:-1], records=transposition.records
    )

    with pytest.raises(AdapterError, match="index"):
        dc_power(
            "pvwatts_dc",
            short_transposition,
            temperature,
            ctx,
            CEC_MODULE,
            modules_per_string=1,
            strings_per_inverter=1,
        )
