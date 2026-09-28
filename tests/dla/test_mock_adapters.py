"""Demonstrates the mock-adapter fixture end to end, through a real
run_pipeline() call — not a claim that this IS one of KT §14's named C1-C5
cases (those, and their D3 write-up, are separate, deferred evaluation
work). This just proves the mechanism itself works before that work needs it.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pvlib import pvsystem

from pvdials.config import load_defaults
from pvdials.data.column_mapper import (
    TAG_ASSUMED_ABSENT,
    SiteMetadata,
    TimeOffset,
    detect_columns,
    detect_site_metadata,
    detect_time_offset,
)
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


def _shared_full_day():
    """A synthetic 24-hour day (real Colombo lat/long, so real solar position
    gives a genuine ~12-hour daylight mask), not the tiny 4-row/1-daylight-row
    repo fixture -- needed wherever a test checks Phase 1's outcome/k, since
    that fixture's n_pooled (28/09's sample-size guard, dla/metrics.py) is too
    small for stages 2-5 to give a real nRMSD at all.
    """
    index = pd.date_range("2023-06-21 00:00", periods=24, freq="h", tz="UTC")
    site = SiteMetadata(
        values={"latitude": 6.944, "longitude": 79.856, "elevation": 16.0},
        sources={"latitude": "test", "longitude": "test", "elevation": "test"},
    )
    offset = TimeOffset(0.0, TAG_ASSUMED_ABSENT, None)

    # Real solar position (Colombo's actual local solar noon, not a hand-picked
    # UTC hour) drives the GHI shape, so daylight rows always carry positive
    # irradiance and night rows are always exactly 0 -- a hand-picked UTC peak
    # hour would misalign against local solar noon (UTC+~5.3h at this
    # longitude) and put GHI=0 inside some "daylight" rows.
    probe_weather = pd.DataFrame(
        {"ghi": 0.0, "temp_air": 28.0, "wind_speed": 1.0, "pressure": 101000.0}, index=index
    )
    probe_ctx = build_site_context(probe_weather, site, offset)
    cos_zenith = np.cos(np.radians(probe_ctx.solpos["zenith"].to_numpy()))
    ghi = pd.Series(np.clip(cos_zenith, 0.0, None) * 900.0, index=index)

    weather = pd.DataFrame(
        {"ghi": ghi, "temp_air": 28.0, "wind_speed": 1.0, "pressure": 101000.0}, index=index
    )
    ctx = build_site_context(weather, site, offset)
    assert int(ctx.daylight.sum()) >= 11, "need enough daylight rows to clear N_MIN"
    assert (weather["ghi"][ctx.daylight] > 0).all(), "daylight rows must carry real irradiance"

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
    # A real, full daylight span (not the 1-daylight-row repo fixture -- 28/09's
    # sample-size guard makes that give "not computable") means pvwatts_dc/
    # pvwatts damp a small temperature delta enough by Stage 5 that it reads as
    # compensating rather than a genuine disagreement. delta=2.0 (temp_cell
    # tripled) is unrealistic but keeps this a pure mechanism test: it isn't
    # damped away, so it stays detected at the stage it was injected at.
    shared = _shared_full_day()
    install_mock_model(
        monkeypatch, Stage.TEMPERATURE, "mock_faiman_triple", "faiman", delta=2.0
    )

    config_a = PipelineConfig("A", "erbs", "isotropic", "faiman", "pvwatts_dc", "pvwatts")
    config_b = PipelineConfig(
        "B", "erbs", "isotropic", "mock_faiman_triple", "pvwatts_dc", "pvwatts"
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
