"""Tests for pvdials.report: descriptive stage summaries and the reshaped
Phase 2 / Phase 3 report views. Pure-function tests where possible (no real
pipeline runs needed for the Phase 2/3 reshaping, since those only reformat
already-computed dataclasses); one real-file test for the one thing that
genuinely needs real physics (DC vs AC annual energy), one DB round-trip test
for the new `pipelines` column.
"""

from pathlib import Path

import pytest

from pvdials.config import load_defaults
from pvdials.data.column_mapper import (
    TAG_USER_ENTERED,
    TimeOffset,
    detect_columns,
    detect_site_metadata,
    detect_time_offset,
)
from pvdials.data.preprocess import preprocess
from pvdials.data.upload import load_uploaded_csv
from pvdials.dla.metrics import TAG_DEFAULT, Tau
from pvdials.dla.phase1 import OUTCOME_DISAGREEMENT_FOUND, PairPhase1Result
from pvdials.dla.phase2 import Phase2Result
from pvdials.dla.phase3 import Phase3Result
from pvdials.physics.geometry import ArrayGeometry, resolve_albedo
from pvdials.physics.hardware import CEC, CEC_INVERTER, ArraySize, InverterRecord, ModuleRecord
from pvdials.physics.mounting import resolve_mounting
from pvdials.physics.pipeline import PipelineResult, SharedInputs, run_pipeline
from pvdials.physics.site import build_site_context
from pvdials.provenance.analyses import load_analysis, save_analysis
from pvdials.provenance.db import get_connection, is_reachable, run_schema
from pvdials.report import (
    build_phase2_rows,
    build_phase3_rows,
    build_stage_summaries,
    resolve_analysis_tau,
    stage_summaries_to_dict,
)
from pvdials.types import PipelineConfig, Stage

requires_postgres = pytest.mark.skipif(
    not is_reachable(),
    reason="No local Postgres reachable (DATABASE_URL not set or the service isn't running).",
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REAL_COLOMBO_FILE = Path("data/weather/tmy_6.944_79.856_2005_2020.csv")
requires_real_colombo_file = pytest.mark.skipif(
    not REAL_COLOMBO_FILE.exists(), reason=f"Real Colombo file not present at {REAL_COLOMBO_FILE}"
)

GEOMETRY = ArrayGeometry(surface_tilt_deg=6.944, surface_azimuth_deg=180.0)


class _FakePipelineRunResult:
    """Just enough of PipelineRunResult's shape for build_stage_summaries --
    avoids needing a real Postgres-backed step_run_pipelines() call.
    """

    def __init__(self, configs, results, annual_yield_kwh):
        self.configs = configs
        self.results = results
        self.annual_yield_kwh = annual_yield_kwh


def _real_pipelines_and_daylight(weather_file: Path, configs: dict[str, PipelineConfig], offset=None):
    defaults = load_defaults()
    uploaded = load_uploaded_csv(weather_file)
    weather = preprocess(uploaded.table, detect_columns(uploaded.table), canonical_year=2023).df
    site = detect_site_metadata(uploaded.preamble, uploaded.table)
    if offset is None:
        offset = detect_time_offset(uploaded.preamble)
    ctx = build_site_context(weather, site, offset, defaults)

    from pvlib import pvsystem

    cec_modules = pvsystem.retrieve_sam(CEC)
    module = ModuleRecord(CEC, "Canadian_Solar_Inc__CS6K_300MS", cec_modules["Canadian_Solar_Inc__CS6K_300MS"])
    cec_inverters = pvsystem.retrieve_sam(CEC_INVERTER)
    inv_name = "ABB__PVI_6000_OUTD_S_US_A__208V_"
    shared = SharedInputs(
        weather=weather, ctx=ctx, geometry=GEOMETRY, albedo=resolve_albedo(None, defaults),
        mounting=resolve_mounting(None, None, defaults), module=module, array_size=ArraySize(10, 2),
        module_height_m=3.0, inverter=InverterRecord(CEC_INVERTER, inv_name, cec_inverters[inv_name]),
    )
    results: dict[str, PipelineResult] = {}
    yields: dict[str, float] = {}
    for label, config in configs.items():
        result = run_pipeline(config, shared, defaults)
        results[label] = result
        from pvdials.guided_reexecution import annual_yield_kwh

        yields[label] = annual_yield_kwh(result)
    return _FakePipelineRunResult(configs, results, yields), ctx.daylight


@pytest.mark.slow
@requires_real_colombo_file
def test_real_file_dc_annual_energy_exceeds_ac_for_every_pipeline():
    """DC is integrated from p_dc, AC from p_ac -- physically distinct
    quantities (inverter conversion isn't lossless), so DC's annual total
    must sit above AC's for every real pipeline, never equal to it.
    """
    configs = {
        "A": PipelineConfig("A", "erbs", "isotropic", "faiman", "singlediode_cec", "sandia"),
        "B": PipelineConfig("B", "disc", "haydavies", "pvsyst_cell", "singlediode_desoto", "sandia"),
        "C": PipelineConfig("C", "dirint", "perez", "ross", "singlediode_cec", "sandia"),
    }
    offset = TimeOffset(
        0.0, TAG_USER_ENTERED,
        override_reason="header states 0.5 h; file day/night content aligns with 0 h",
    )
    pipelines, daylight = _real_pipelines_and_daylight(REAL_COLOMBO_FILE, configs, offset=offset)
    summaries = build_stage_summaries(pipelines, daylight)

    for label in configs:
        dc_kwh = summaries[label][Stage.DC].annual_energy_kwh
        ac_kwh = summaries[label][Stage.AC].annual_energy_kwh
        assert dc_kwh > ac_kwh, f"{label}: DC={dc_kwh} did not exceed AC={ac_kwh}"


def test_build_stage_summaries_model_names_and_units():
    configs = {
        "A": PipelineConfig("A", "erbs", "isotropic", "faiman", "singlediode_cec", "sandia"),
    }
    pipelines, daylight = _real_pipelines_and_daylight(FIXTURES / "sample_pvgis_tmy.csv", configs)
    summaries = build_stage_summaries(pipelines, daylight)

    per_stage = summaries["A"]
    assert per_stage[Stage.DECOMPOSITION].model == "erbs"
    assert per_stage[Stage.TRANSPOSITION].model == "isotropic"
    assert per_stage[Stage.TEMPERATURE].model == "faiman"
    assert per_stage[Stage.DC].model == "singlediode_cec"
    assert per_stage[Stage.AC].model == "sandia"

    assert per_stage[Stage.DECOMPOSITION].dni_kwh_m2 is not None
    assert per_stage[Stage.DECOMPOSITION].dhi_kwh_m2 is not None
    assert per_stage[Stage.TRANSPOSITION].poa_global_kwh_m2 is not None
    assert per_stage[Stage.TEMPERATURE].temp_cell_mean_c <= per_stage[Stage.TEMPERATURE].temp_cell_max_c
    assert per_stage[Stage.AC].annual_energy_kwh == pytest.approx(pipelines.annual_yield_kwh["A"])


def test_stage_summaries_to_dict_is_ordered_and_json_safe():
    configs = {
        "A": PipelineConfig("A", "erbs", "isotropic", "faiman", "singlediode_cec", "sandia"),
    }
    pipelines, daylight = _real_pipelines_and_daylight(FIXTURES / "sample_pvgis_tmy.csv", configs)
    summaries = build_stage_summaries(pipelines, daylight)

    as_dict = stage_summaries_to_dict(summaries)
    rows = as_dict["A"]
    assert [row["stage"] for row in rows] == [
        "DECOMPOSITION", "TRANSPOSITION", "TEMPERATURE", "DC", "AC",
    ]
    for row in rows:
        for value in row.values():
            assert value is None or isinstance(value, (str, float))


def test_resolve_analysis_tau_skips_not_computable_strings():
    real = PairPhase1Result(
        pair=("A", "B"), metrics={}, outcome=OUTCOME_DISAGREEMENT_FOUND, k=Stage.DECOMPOSITION,
        differing_stages=frozenset({Stage.DECOMPOSITION}), tau=Tau(0.15, TAG_DEFAULT),
    )
    mixed = {("A", "B"): "not computable — pipeline A failed all_finite", ("A", "C"): real}
    assert resolve_analysis_tau(mixed) == 0.15

    all_strings = {("A", "B"): "not computable — x", ("A", "C"): "not computable — y"}
    assert resolve_analysis_tau(all_strings) is None


def test_build_phase2_rows_delta_and_marker():
    pair_nrmsd = {("A", "B"): {
        Stage.DECOMPOSITION: 0.05, Stage.TRANSPOSITION: 0.20,
        Stage.TEMPERATURE: 0.02, Stage.DC: 0.30, Stage.AC: 0.01,
    }}
    result = Phase2Result(pair_nrmsd=pair_nrmsd, mean_nrmsd={}, max_nrmsd={}, delta={})

    rows = build_phase2_rows(result, tau=0.1)
    assert len(rows) == 1
    row = rows[0]
    assert row.pair == ("A", "B")

    by_stage = {r.stage: r for r in row.stages}
    assert by_stage[Stage.DECOMPOSITION].delta == pytest.approx(0.05)  # first stage: delta == its own nrmsd
    assert by_stage[Stage.DECOMPOSITION].exceeds_tau is False
    assert by_stage[Stage.TRANSPOSITION].delta == pytest.approx(0.20 - 0.05)
    assert by_stage[Stage.TRANSPOSITION].exceeds_tau is True  # 0.20 > 0.1
    assert by_stage[Stage.TEMPERATURE].delta == pytest.approx(0.02 - 0.20)
    assert by_stage[Stage.DC].exceeds_tau is True  # 0.30 > 0.1
    assert by_stage[Stage.AC].exceeds_tau is False


def _phase3_result(pair, differing_stage, signed_value):
    """One stage differs (nonzero phi/share/signed_phi); the other four are
    identical-model stages (all exactly 0, matching real Shapley output when
    nrmsd is exactly 0 for a stage)."""
    zero = dict.fromkeys(Stage, 0.0)
    phi = dict(zero)
    phi[differing_stage] = 10.0
    signed = dict(zero)
    signed[differing_stage] = signed_value
    share = dict(zero)
    share[differing_stage] = 1.0
    return Phase3Result(
        pair=pair, phi_ab=phi, phi_ba=phi, phi_final=phi, share=share,
        v_ab={}, v_ba={}, rmsd_ab=10.0, signed_phi=signed, signed_v={},
    )


def test_build_phase3_rows_same_model_and_direction_words():
    config_a = PipelineConfig("A", "erbs", "isotropic", "faiman", "singlediode_cec", "sandia")
    config_b = PipelineConfig("B", "disc", "isotropic", "faiman", "singlediode_cec", "sandia")
    configs = {"A": config_a, "B": config_b}

    positive = _phase3_result(("A", "B"), Stage.DECOMPOSITION, signed_value=5.0)
    rows = build_phase3_rows({("A", "B"): positive}, configs)
    by_stage = {r.stage: r for r in rows}

    assert by_stage[Stage.DECOMPOSITION].same_model is False
    assert by_stage[Stage.DECOMPOSITION].direction_words == "B's model gives higher AC output than A's"
    for stage in (Stage.TRANSPOSITION, Stage.TEMPERATURE, Stage.DC, Stage.AC):
        assert by_stage[stage].same_model is True
        assert by_stage[stage].direction_words == "same model — no difference"

    negative = _phase3_result(("A", "B"), Stage.DECOMPOSITION, signed_value=-5.0)
    rows = build_phase3_rows({("A", "B"): negative}, configs)
    by_stage = {r.stage: r for r in rows}
    assert by_stage[Stage.DECOMPOSITION].direction_words == "B's model gives lower AC output than A's"


def test_build_phase3_rows_skips_not_run_and_not_computable():
    from pvdials.dla.phase3 import Phase3NotComputable

    configs = {
        "A": PipelineConfig("A", "erbs", "isotropic", "faiman", "singlediode_cec", "sandia"),
        "B": PipelineConfig("B", "disc", "isotropic", "faiman", "singlediode_cec", "sandia"),
        "C": PipelineConfig("C", "dirint", "isotropic", "faiman", "singlediode_cec", "sandia"),
    }
    results = {
        ("A", "B"): "not run — outcome 1 (no stage exceeds tau)",
        ("A", "C"): Phase3NotComputable(pair=("A", "C"), invalid_coalitions=[]),
    }
    assert build_phase3_rows(results, configs) == []


@requires_postgres
def test_save_and_load_analysis_round_trips_pipelines_column():
    with get_connection() as conn:
        run_schema(conn)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM analyses WHERE id = %s", ("test_report_roundtrip",))
        conn.commit()

    pipelines_dict = {
        "A": [{"stage": "DECOMPOSITION", "model": "erbs", "dni_kwh_m2": 123.4, "dhi_kwh_m2": 56.7,
               "poa_global_kwh_m2": None, "temp_cell_mean_c": None, "temp_cell_max_c": None,
               "annual_energy_kwh": None}],
    }
    save_analysis(
        "test_report_roundtrip", "roundtrip test", "pipelines_done", inputs={"x": 1},
        pipelines=pipelines_dict,
    )
    loaded = load_analysis("test_report_roundtrip")
    assert loaded["pipelines"] == pipelines_dict

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM analyses WHERE id = %s", ("test_report_roundtrip",))
        conn.commit()
