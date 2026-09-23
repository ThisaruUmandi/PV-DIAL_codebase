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
from pvdials.data.validate import validate_ac_not_exceeding_dc, validate_post_dc
from pvdials.physics.adapters import AdapterError
from pvdials.physics.adapters.ac import ac_power
from pvdials.physics.adapters.dc import dc_power
from pvdials.physics.adapters.decomposition import decompose
from pvdials.physics.adapters.temperature import cell_temperature
from pvdials.physics.adapters.transposition import transpose
from pvdials.physics.geometry import ArrayGeometry, resolve_albedo
from pvdials.physics.hardware import (
    ADR_INVERTER,
    CEC,
    CEC_INVERTER,
    SANDIA,
    ArraySize,
    InverterRecord,
    ModuleRecord,
    pdc0,
)
from pvdials.physics.mounting import resolve_mounting
from pvdials.physics.site import build_site_context

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
COLOMBO = SiteMetadata(
    values={"latitude": 6.944, "longitude": 79.856, "elevation": 16.0},
    sources={"latitude": "From CSV", "longitude": "From CSV", "elevation": "From CSV"},
)
GEOMETRY = ArrayGeometry(surface_tilt_deg=6.944, surface_azimuth_deg=180.0)
DEFAULT_ALBEDO = resolve_albedo(None, load_defaults())
DEFAULT_MOUNTING = resolve_mounting(None, None, load_defaults())
ARRAY = ArraySize(10, 2)

CEC_MODULES = pvsystem.retrieve_sam(CEC)
CEC_NAME = "Canadian_Solar_Inc__CS6K_300MS"
CEC_MODULE = ModuleRecord(CEC, CEC_NAME, CEC_MODULES[CEC_NAME])

SANDIA_MODULES = pvsystem.retrieve_sam(SANDIA)
SANDIA_NAME = SANDIA_MODULES.columns[0]
SANDIA_MODULE = ModuleRecord(SANDIA, SANDIA_NAME, SANDIA_MODULES[SANDIA_NAME])

# A shared CEC/ADR inverter, ~6 kW, roughly matched to the 10x2 array so AC/DC
# ratios stay physically sensible rather than heavily clipped.
CEC_INVERTERS = pvsystem.retrieve_sam(CEC_INVERTER)
ADR_INVERTERS = pvsystem.retrieve_sam(ADR_INVERTER)
INV_NAME = "ABB__PVI_6000_OUTD_S_US_A__208V_"
SANDIA_INVERTER = InverterRecord(CEC_INVERTER, INV_NAME, CEC_INVERTERS[INV_NAME])
ADR_INVERTER_RECORD = InverterRecord(ADR_INVERTER, INV_NAME, ADR_INVERTERS[INV_NAME])

ADR_ONLY_NAME = next(n for n in ADR_INVERTERS.columns if n not in CEC_INVERTERS.columns)
ADR_ONLY_INVERTER = InverterRecord(ADR_INVERTER, ADR_ONLY_NAME, ADR_INVERTERS[ADR_ONLY_NAME])

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


def _dc_result(dc_model, weather, ctx, module):
    decomposition = decompose("erbs", weather, ctx)
    transposition = transpose("isotropic", weather, decomposition, ctx, GEOMETRY, DEFAULT_ALBEDO)
    temperature = cell_temperature(
        "faiman", transposition, weather, DEFAULT_MOUNTING, GEOMETRY, module=module
    )
    return dc_power(
        dc_model,
        transposition,
        temperature,
        ctx,
        module,
        modules_per_string=ARRAY.modules_per_string,
        strings_per_inverter=ARRAY.strings_per_inverter,
    )


# (dc_model, ac_model, module, inverter) for the 7 selectable combinations
COMBINATIONS = [
    ("pvwatts_dc", "pvwatts", CEC_MODULE, None),
    ("sapm", "sandia", SANDIA_MODULE, SANDIA_INVERTER),
    ("sapm", "adr", SANDIA_MODULE, ADR_INVERTER_RECORD),
    ("singlediode_desoto", "sandia", CEC_MODULE, SANDIA_INVERTER),
    ("singlediode_desoto", "adr", CEC_MODULE, ADR_INVERTER_RECORD),
    ("singlediode_cec", "sandia", CEC_MODULE, SANDIA_INVERTER),
    ("singlediode_cec", "adr", CEC_MODULE, ADR_INVERTER_RECORD),
]


def _ac_result(dc_model, ac_model, module, inverter, weather, ctx):
    dc = _dc_result(dc_model, weather, ctx, module)
    return dc, ac_power(ac_model, dc, inverter=inverter, module=module, array_size=ARRAY)


@pytest.mark.parametrize("dc_model,ac_model,module,inverter", COMBINATIONS)
def test_every_combination_runs_on_canonical_index(dc_model, ac_model, module, inverter):
    weather, ctx = _day()
    dc, ac = _ac_result(dc_model, ac_model, module, inverter, weather, ctx)

    assert ac.outputs.index.equals(weather.index)
    assert validate_post_dc(dc.outputs).passed


@pytest.mark.parametrize("dc_model,ac_model,module,inverter", COMBINATIONS)
def test_ac_never_exceeds_dc_on_the_real_file(dc_model, ac_model, module, inverter):
    # The N21 regression guard, run over every selectable Stage 4/5 combination.
    weather, ctx = _fixture()
    dc, ac = _ac_result(dc_model, ac_model, module, inverter, weather, ctx)

    result = validate_ac_not_exceeding_dc(ac.outputs, dc.outputs)
    assert result.passed, result.problems


def test_sandia_raises_without_v_dc():
    weather, ctx = _day()
    dc = _dc_result("pvwatts_dc", weather, ctx, CEC_MODULE)

    with pytest.raises(AdapterError, match="v_dc"):
        ac_power("sandia", dc, inverter=SANDIA_INVERTER)


def test_adr_raises_without_v_dc():
    weather, ctx = _day()
    dc = _dc_result("pvwatts_dc", weather, ctx, CEC_MODULE)

    with pytest.raises(AdapterError, match="v_dc"):
        ac_power("adr", dc, inverter=ADR_INVERTER_RECORD)


def test_sandia_raises_on_adr_only_inverter():
    weather, ctx = _day()
    dc = _dc_result("sapm", weather, ctx, SANDIA_MODULE)

    with pytest.raises(AdapterError, match="CECInverter"):
        ac_power("sandia", dc, inverter=ADR_ONLY_INVERTER)


def test_adr_accepts_adr_only_inverter():
    weather, ctx = _day()
    dc = _dc_result("sapm", weather, ctx, SANDIA_MODULE)

    result = ac_power("adr", dc, inverter=ADR_ONLY_INVERTER)
    assert result.records["inverter_name"] == ADR_ONLY_NAME


def test_pvwatts_needs_no_inverter_database_entry():
    weather, ctx = _day()
    dc = _dc_result("pvwatts_dc", weather, ctx, CEC_MODULE)

    result = ac_power("pvwatts", dc, module=CEC_MODULE, array_size=ARRAY)
    assert "inverter_name" not in result.records


def test_pvwatts_needs_module_and_array_size():
    weather, ctx = _day()
    dc = _dc_result("pvwatts_dc", weather, ctx, CEC_MODULE)

    with pytest.raises(AdapterError, match="module and array size"):
        ac_power("pvwatts", dc)


def test_pvwatts_pdc0_matches_stage4_derivation_scaled_by_array():
    weather, ctx = _day()
    dc = _dc_result("pvwatts_dc", weather, ctx, CEC_MODULE)

    result = ac_power("pvwatts", dc, module=CEC_MODULE, array_size=ARRAY)

    per_module, _ = pdc0(CEC_MODULE)
    expected = per_module * ARRAY.modules_per_string * ARRAY.strings_per_inverter
    assert result.records["pdc0"] == pytest.approx(expected)


@pytest.mark.parametrize("dc_model,ac_model,module,inverter", COMBINATIONS)
def test_same_input_twice_gives_identical_output(dc_model, ac_model, module, inverter):
    weather, ctx = _day()
    _, ac1 = _ac_result(dc_model, ac_model, module, inverter, weather, ctx)
    _, ac2 = _ac_result(dc_model, ac_model, module, inverter, weather, ctx)

    pd.testing.assert_frame_equal(ac1.outputs, ac2.outputs)
    assert ac1.records == ac2.records


def test_unknown_model_raises():
    weather, ctx = _day()
    dc = _dc_result("pvwatts_dc", weather, ctx, CEC_MODULE)

    with pytest.raises(AdapterError, match="not a Stage 5 candidate"):
        ac_power("no_such_model", dc)


def test_ac_dc_index_mismatch_is_rejected():
    weather, ctx = _day()
    dc = _dc_result("sapm", weather, ctx, SANDIA_MODULE)
    short_dc_outputs = dc.outputs.iloc[:-1]

    with pytest.raises(ValueError, match="index"):
        validate_ac_not_exceeding_dc(dc.outputs, short_dc_outputs)
