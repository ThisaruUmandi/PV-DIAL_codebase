"""Demonstrates the mock-adapter fixture end to end, through a real
run_pipeline() call — not a claim that this IS one of KT §14's named C1-C5
cases (those, and their D3 write-up, are separate, deferred evaluation
work). This just proves the mechanism itself works before that work needs it.
"""

from pathlib import Path

import pytest
from pvlib import pvsystem

from pvdials.config import load_defaults
from pvdials.data.column_mapper import detect_columns, detect_site_metadata, detect_time_offset
from pvdials.data.preprocess import preprocess
from pvdials.data.upload import load_uploaded_csv
from pvdials.dla.phase1 import OUTCOME_DISAGREEMENT_FOUND, run_phase1
from pvdials.physics.geometry import ArrayGeometry, resolve_albedo
from pvdials.physics.hardware import CEC, ArraySize, ModuleRecord
from pvdials.physics.mounting import resolve_mounting
from pvdials.physics.pipeline import SharedInputs, run_pipeline
from pvdials.physics.site import build_site_context
from pvdials.types import PipelineConfig, Stage
from tests.dla.mock_adapters import install_mock_model

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

pytestmark = pytest.mark.filterwarnings("ignore::RuntimeWarning")


def _shared():
    uploaded = load_uploaded_csv(FIXTURES / "sample_pvgis_tmy.csv")
    weather = preprocess(uploaded.table, detect_columns(uploaded.table), canonical_year=2023).df
    site = detect_site_metadata(uploaded.preamble, uploaded.table)
    ctx = build_site_context(weather, site, detect_time_offset(uploaded.preamble))
    cec_modules = pvsystem.retrieve_sam(CEC)
    module = ModuleRecord(
        CEC, "Canadian_Solar_Inc__CS6K_300MS", cec_modules["Canadian_Solar_Inc__CS6K_300MS"]
    )
    return SharedInputs(
        weather=weather,
        ctx=ctx,
        geometry=ArrayGeometry(surface_tilt_deg=6.944, surface_azimuth_deg=180.0),
        albedo=resolve_albedo(None, load_defaults()),
        mounting=resolve_mounting(None, None, load_defaults()),
        module=module,
        array_size=ArraySize(10, 2),
    )


def test_mock_model_output_is_the_real_baseline_perturbed(monkeypatch):
    shared = _shared()
    install_mock_model(
        monkeypatch, Stage.TEMPERATURE, "mock_faiman_plus10pct", "faiman", delta=0.10
    )

    real_config = PipelineConfig("A", "erbs", "isotropic", "faiman", "pvwatts_dc", "pvwatts")
    mock_config = PipelineConfig(
        "B", "erbs", "isotropic", "mock_faiman_plus10pct", "pvwatts_dc", "pvwatts"
    )

    real_result = run_pipeline(real_config, shared)
    mock_result = run_pipeline(mock_config, shared)

    expected = real_result.outputs.temperature.outputs["temp_cell"] * 1.10
    actual = mock_result.outputs.temperature.outputs["temp_cell"]
    assert (actual == expected).all()
    assert mock_result.outputs.temperature.records["mock"] is True
    assert mock_result.outputs.temperature.records["base_model"] == "faiman"


def test_a_delta_confined_to_one_stage_is_detected_at_that_stage_via_run_pipeline(monkeypatch):
    shared = _shared()
    install_mock_model(
        monkeypatch, Stage.TEMPERATURE, "mock_faiman_plus10pct", "faiman", delta=0.10
    )

    config_a = PipelineConfig("A", "erbs", "isotropic", "faiman", "pvwatts_dc", "pvwatts")
    config_b = PipelineConfig(
        "B", "erbs", "isotropic", "mock_faiman_plus10pct", "pvwatts_dc", "pvwatts"
    )
    result_a = run_pipeline(config_a, shared)
    result_b = run_pipeline(config_b, shared)

    phase1 = run_phase1(config_a, result_a, config_b, result_b, shared.ctx.daylight)

    assert phase1.outcome == OUTCOME_DISAGREEMENT_FOUND
    assert phase1.k == Stage.TEMPERATURE
    # Everything upstream of the mock is untouched and identical
    assert phase1.metrics[Stage.DECOMPOSITION].nrmsd == 0.0
    assert phase1.metrics[Stage.TRANSPOSITION].nrmsd == 0.0


def test_installing_a_mock_does_not_affect_other_model_names_at_the_same_stage(monkeypatch):
    shared = _shared()
    install_mock_model(monkeypatch, Stage.TEMPERATURE, "mock_delta", "faiman", delta=0.10)

    # A different real model at the same stage must be completely unaffected
    config = PipelineConfig("A", "erbs", "isotropic", "pvsyst_cell", "pvwatts_dc", "pvwatts")
    result = run_pipeline(config, shared)

    assert result.outputs.temperature.records.get("mock") is None
    assert "mock_delta" not in result.outputs.temperature.records.get("model", "")


def test_additive_mode_adds_delta_rather_than_scaling(monkeypatch):
    shared = _shared()
    install_mock_model(
        monkeypatch, Stage.TEMPERATURE, "mock_faiman_plus5c", "faiman", delta=5.0, mode="additive"
    )

    real_config = PipelineConfig("A", "erbs", "isotropic", "faiman", "pvwatts_dc", "pvwatts")
    mock_config = PipelineConfig(
        "B", "erbs", "isotropic", "mock_faiman_plus5c", "pvwatts_dc", "pvwatts"
    )
    real_result = run_pipeline(real_config, shared)
    mock_result = run_pipeline(mock_config, shared)

    expected = real_result.outputs.temperature.outputs["temp_cell"] + 5.0
    actual = mock_result.outputs.temperature.outputs["temp_cell"]
    assert (actual == expected).all()
    assert mock_result.outputs.temperature.records["mode"] == "additive"
