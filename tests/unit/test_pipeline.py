import dataclasses
from pathlib import Path

import pandas as pd
import pytest
from pvlib import pvsystem

from pvdials.config import load_defaults
from pvdials.data.column_mapper import (
    detect_columns,
    detect_site_metadata,
    detect_time_offset,
)
from pvdials.data.preprocess import preprocess
from pvdials.data.upload import load_uploaded_csv
from pvdials.physics.adapters import AdapterError
from pvdials.physics.geometry import ArrayGeometry, resolve_albedo
from pvdials.physics.hardware import (
    CEC,
    CEC_INVERTER,
    SANDIA,
    ArraySize,
    InverterRecord,
    ModuleRecord,
)
from pvdials.physics.mounting import resolve_mounting
from pvdials.physics.pipeline import SharedInputs, StageOutputs, run_pipeline
from pvdials.physics.site import build_site_context
from pvdials.types import PipelineConfig

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
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

CEC_INVERTERS = pvsystem.retrieve_sam(CEC_INVERTER)
INV_NAME = "ABB__PVI_6000_OUTD_S_US_A__208V_"
SANDIA_INVERTER = InverterRecord(CEC_INVERTER, INV_NAME, CEC_INVERTERS[INV_NAME])

pytestmark = pytest.mark.filterwarnings("ignore::RuntimeWarning")


def _shared(module=CEC_MODULE, mounting=DEFAULT_MOUNTING, inverter=SANDIA_INVERTER):
    uploaded = load_uploaded_csv(FIXTURES / "sample_pvgis_tmy.csv")
    weather = preprocess(uploaded.table, detect_columns(uploaded.table), canonical_year=2023).df
    site = detect_site_metadata(uploaded.preamble, uploaded.table)
    ctx = build_site_context(weather, site, detect_time_offset(uploaded.preamble))
    return SharedInputs(
        weather=weather,
        ctx=ctx,
        geometry=GEOMETRY,
        albedo=DEFAULT_ALBEDO,
        mounting=mounting,
        module=module,
        array_size=ARRAY,
        inverter=inverter,
    )


def test_full_run_singlediode_cec_sandia():
    shared = _shared()
    config = PipelineConfig("A", "erbs", "isotropic", "faiman", "singlediode_cec", "sandia")

    result = run_pipeline(config, shared)

    assert isinstance(result.outputs, StageOutputs)
    assert all(v.passed for v in result.validations.values()), result.validations
    # Regression pin against the fixture, established 24/09
    assert result.outputs.dc.outputs["p_dc"].sum() == pytest.approx(110.99074, abs=1e-3)
    assert result.outputs.ac.outputs["p_ac"].sum() == pytest.approx(74.79084, abs=1e-3)


def test_full_run_pvwatts_dc_pvwatts_no_inverter_needed():
    shared = dataclasses.replace(_shared(), inverter=None)
    config = PipelineConfig("B", "erbs", "isotropic", "faiman", "pvwatts_dc", "pvwatts")

    result = run_pipeline(config, shared)

    assert all(v.passed for v in result.validations.values()), result.validations
    assert "v_dc" not in result.outputs.dc.outputs.columns
    assert result.outputs.ac.outputs["p_ac"].sum() == pytest.approx(87.36302, abs=1e-3)


def test_full_run_sapm_sandia_on_sandiamod():
    shared = _shared(module=SANDIA_MODULE)
    config = PipelineConfig("C", "erbs", "isotropic", "faiman", "sapm", "sandia")

    result = run_pipeline(config, shared)

    assert all(v.passed for v in result.validations.values()), result.validations
    assert result.outputs.ac.outputs["p_ac"].sum() == pytest.approx(19.76478, abs=1e-3)


def test_three_configs_share_the_same_ctx_and_weather_objects():
    # D6: solar position computed once, shared by every pipeline in a comparison.
    # run_pipeline must never rebuild it — the same SharedInputs feeds all three.
    shared = _shared()
    configs = [
        PipelineConfig("A", "erbs", "isotropic", "faiman", "singlediode_cec", "sandia"),
        PipelineConfig("B", "disc", "isotropic", "faiman", "singlediode_cec", "sandia"),
        PipelineConfig("C", "boland", "isotropic", "faiman", "singlediode_cec", "sandia"),
    ]

    results = [run_pipeline(c, shared) for c in configs]

    for result in results:
        assert result.outputs.transposition.records["surface_tilt_deg"] == GEOMETRY.surface_tilt_deg
    # The three decomposition models genuinely differ downstream...
    assert not results[0].outputs.decomposition.outputs.equals(results[1].outputs.decomposition.outputs)
    # ...but every pipeline ran against the same shared weather/ctx index (no rebuild per config)
    assert all(r.outputs.ac.outputs.index.equals(shared.weather.index) for r in results)


def test_unselectable_model_raises_the_adapters_own_reason():
    bad_mounting = resolve_mounting("close_mount", "glass_polymer", load_defaults())
    shared = _shared(mounting=bad_mounting)
    config = PipelineConfig("D", "erbs", "isotropic", "sapm_cell", "singlediode_cec", "sandia")

    with pytest.raises(AdapterError, match="no SAPM coefficient set"):
        run_pipeline(config, shared)


def test_pipeline_config_is_frozen():
    config = PipelineConfig("A", "erbs", "isotropic", "faiman", "singlediode_cec", "sandia")

    with pytest.raises(dataclasses.FrozenInstanceError):
        config.label = "Z"


def test_same_config_twice_gives_identical_output():
    shared = _shared()
    config = PipelineConfig("A", "erbs", "isotropic", "faiman", "singlediode_cec", "sandia")

    first = run_pipeline(config, shared)
    second = run_pipeline(config, shared)

    pd.testing.assert_frame_equal(first.outputs.ac.outputs, second.outputs.ac.outputs)
    pd.testing.assert_frame_equal(first.outputs.dc.outputs, second.outputs.dc.outputs)
