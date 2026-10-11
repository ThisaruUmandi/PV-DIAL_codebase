import copy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pvlib import pvsystem, temperature

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
from pvdials.data.validate import validate_post_temperature
from pvdials.physics.adapters import AdapterError
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
STAGE3_SELECTABLE = [c.name for c in stage_pool(Stage.TEMPERATURE) if c.selectable]
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


def _transposition(weather, ctx):
    decomposition = decompose("erbs", weather, ctx)
    return transpose("isotropic", weather, decomposition, ctx, GEOMETRY, DEFAULT_ALBEDO)


def _cell_temperature(model, weather, ctx, module=CEC_MODULE, mounting=DEFAULT_MOUNTING, **kwargs):
    transposition = _transposition(weather, ctx)
    kwargs.setdefault("module_height_m", 3.0)
    return cell_temperature(model, transposition, weather, mounting, GEOMETRY, module=module, **kwargs)


@pytest.mark.parametrize("model", STAGE3_SELECTABLE)
def test_every_selectable_model_runs_and_passes_sanity_check(model):
    for weather, ctx in (_fixture(), _day()):
        result = _cell_temperature(model, weather, ctx)

        assert result.outputs.index.equals(weather.index)
        assert validate_post_temperature(result.outputs, weather).passed


@pytest.mark.parametrize("model", ["sapm_cell", "pvsyst_cell"])
def test_coefficients_change_with_mounting_geometry(model):
    weather, ctx = _day()
    open_rack = resolve_mounting("open_rack", "glass_glass", load_defaults())
    close_mount = resolve_mounting("close_mount", "glass_glass", load_defaults())

    a = _cell_temperature(model, weather, ctx, mounting=open_rack)
    b = _cell_temperature(model, weather, ctx, mounting=close_mount)

    assert not a.outputs["temp_cell"].equals(b.outputs["temp_cell"])


def test_sapm_cell_raises_on_unsupported_mounting_combination():
    weather, ctx = _day()
    unsupported = resolve_mounting("close_mount", "glass_polymer", load_defaults())

    with pytest.raises(AdapterError, match="SAPM coefficient set"):
        _cell_temperature("sapm_cell", weather, ctx, mounting=unsupported)


@pytest.mark.parametrize("model", ["fuentes", "noct_sam", "ross"])
def test_noct_gated_models_raise_on_sandia_module(model):
    weather, ctx = _day()

    with pytest.raises(AdapterError, match="NOCT"):
        _cell_temperature(model, weather, ctx, module=SANDIA_MODULE)


def test_fuentes_requires_module_height():
    weather, ctx = _day()
    transposition = _transposition(weather, ctx)

    with pytest.raises(AdapterError, match="module_height_m"):
        cell_temperature(
            "fuentes", transposition, weather, DEFAULT_MOUNTING, GEOMETRY, module=CEC_MODULE
        )


def test_module_efficiency_reaches_the_adapter():
    weather, ctx = _day()
    result = _cell_temperature("fuentes", weather, ctx)

    p = CEC_MODULE.params
    expected = float(p["I_mp_ref"]) * float(p["V_mp_ref"]) / (float(p["A_c"]) * 1000.0)
    assert result.records["module_efficiency"] == pytest.approx(expected)


def test_wind_height_is_the_pvgis_convention_not_pvlib_default():
    weather, ctx = _day()
    changed = copy.deepcopy(load_defaults())
    changed["stage3"]["fuentes"]["wind_height_m"] = 30.0

    base = _cell_temperature("fuentes", weather, ctx, defaults=load_defaults())
    other = _cell_temperature("fuentes", weather, ctx, defaults=changed)

    assert not base.outputs["temp_cell"].equals(other.outputs["temp_cell"])
    assert base.records["coefficients"]["wind_height_m"] == 10.0


def test_noct_sam_array_height_default_and_override():
    weather, ctx = _day()
    default_result = _cell_temperature("noct_sam", weather, ctx)
    override_result = _cell_temperature("noct_sam", weather, ctx, array_height=2)

    assert default_result.records["array_height"] == 1
    assert override_result.records["array_height"] == 2
    assert not default_result.outputs["temp_cell"].equals(override_result.outputs["temp_cell"])


def test_ross_uses_noct_from_module():
    weather, ctx = _day()
    result = _cell_temperature("ross", weather, ctx)

    expected = temperature.ross(
        _transposition(weather, ctx).outputs["poa_global"],
        weather["temp_air"],
        noct=CEC_MODULE.params["T_NOCT"],
    )
    pd.testing.assert_series_equal(result.outputs["temp_cell"], expected, check_names=False)


def test_pvsyst_module_efficiency_and_alpha_absorption_are_held_fixed():
    weather, ctx = _day()
    result = _cell_temperature("pvsyst_cell", weather, ctx, module=None)

    assert result.records["coefficients"]["module_efficiency"] == 0.1
    assert result.records["coefficients"]["alpha_absorption"] == 0.9


def test_unconditional_models_work_without_a_module():
    weather, ctx = _day()

    for model in ("faiman", "pvsyst_cell", "sapm_cell"):
        result = _cell_temperature(model, weather, ctx, module=None)
        assert validate_post_temperature(result.outputs, weather).passed


def test_same_input_twice_gives_identical_output():
    weather, ctx = _fixture()
    for model in STAGE3_SELECTABLE:
        first = _cell_temperature(model, weather, ctx)
        second = _cell_temperature(model, weather, ctx)
        pd.testing.assert_frame_equal(first.outputs, second.outputs)
        assert first.records == second.records


def test_unknown_model_raises():
    weather, ctx = _day()

    with pytest.raises(AdapterError, match="not a Stage 3 candidate"):
        _cell_temperature("no_such_model", weather, ctx)


@pytest.mark.parametrize("model", ["faiman_rad", "generic_linear", "prilliman"])
def test_structurally_excluded_models_raise_with_their_reason(model):
    weather, ctx = _day()

    with pytest.raises(AdapterError):
        _cell_temperature(model, weather, ctx)


def test_mismatched_transposition_index_is_rejected():
    weather, ctx = _day()
    transposition = _transposition(weather, ctx)
    short_weather = weather.iloc[:-1]

    with pytest.raises(AdapterError, match="[Tt]ransposition"):
        cell_temperature(
            "faiman", transposition, short_weather, DEFAULT_MOUNTING, GEOMETRY, module=CEC_MODULE
        )
