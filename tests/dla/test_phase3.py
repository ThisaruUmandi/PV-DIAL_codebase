"""Phase 3 (KT Step 9): Shapley-value contribution quantification tests."""

import math
from pathlib import Path

import pytest
from pvlib import pvsystem

import pvdials.dla.phase3 as phase3_module
from pvdials.config import load_defaults
from pvdials.data.column_mapper import detect_columns, detect_site_metadata, detect_time_offset
from pvdials.data.preprocess import preprocess
from pvdials.data.upload import load_uploaded_csv
from pvdials.dla.phase3 import (
    ALL_STAGES,
    NOT_COMPUTABLE_REASON,
    Phase3NotComputable,
    all_coalitions,
    build_derived_config,
    coalition_is_pool_valid,
    pair_is_shapley_computable,
    run_phase3,
    shapley_values,
    stage_field,
)
from pvdials.physics.geometry import ArrayGeometry, resolve_albedo
from pvdials.physics.hardware import CEC, ArraySize, ModuleRecord
from pvdials.physics.mounting import resolve_mounting
from pvdials.physics.pipeline import SharedInputs, run_pipeline
from pvdials.physics.site import build_site_context
from pvdials.types import PipelineConfig, Stage
from tests.unit.test_pool_validity import HYBRID_VALIDITY_CASES

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

pytestmark = pytest.mark.filterwarnings("ignore::RuntimeWarning")

CONFIG_A = PipelineConfig("A", "erbs", "isotropic", "faiman", "pvwatts_dc", "pvwatts")
CONFIG_B = PipelineConfig("B", "disc", "haydavies", "pvsyst_cell", "pvwatts_dc", "pvwatts")


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


# --- build_derived_config / all_coalitions --------------------------------------


def test_build_derived_config_at_empty_coalition_reproduces_config_a():
    derived = build_derived_config(CONFIG_A, CONFIG_B, frozenset(), label="x")
    for stage in ALL_STAGES:
        field = stage_field(stage)
        assert getattr(derived, field) == getattr(CONFIG_A, field)


def test_build_derived_config_at_full_coalition_reproduces_config_b():
    derived = build_derived_config(CONFIG_A, CONFIG_B, frozenset(ALL_STAGES), label="x")
    for stage in ALL_STAGES:
        field = stage_field(stage)
        assert getattr(derived, field) == getattr(CONFIG_B, field)


def test_build_derived_config_mixes_fields_by_coalition():
    coalition = frozenset({Stage.TRANSPOSITION, Stage.DC})
    derived = build_derived_config(CONFIG_A, CONFIG_B, coalition, label="x")

    assert derived.decomposition_model == CONFIG_A.decomposition_model
    assert derived.transposition_model == CONFIG_B.transposition_model
    assert derived.temperature_model == CONFIG_A.temperature_model
    assert derived.dc_model == CONFIG_B.dc_model
    assert derived.ac_model == CONFIG_A.ac_model


def test_all_coalitions_is_the_full_32_member_powerset():
    coalitions = all_coalitions()

    assert len(coalitions) == 32
    assert len(set(coalitions)) == 32
    assert frozenset() in coalitions
    assert frozenset(ALL_STAGES) in coalitions


# --- coalition_is_pool_valid / pair_is_shapley_computable -----------------------


@pytest.mark.parametrize("dc_model,ac_model,expected_ok", HYBRID_VALIDITY_CASES)
def test_coalition_is_pool_valid_matches_the_shared_hybrid_validity_table(dc_model, ac_model, expected_ok):
    # build_derived_config: coalition stages take config_b's model, others take
    # config_a's. coalition={DC} -> derived.dc_model=config_b's, derived.ac_model=
    # config_a's -- so the parametrized values go there, not on the matching config.
    config_a = PipelineConfig("A", "erbs", "isotropic", "faiman", "singlediode_cec", ac_model)
    config_b = PipelineConfig("B", "erbs", "isotropic", "faiman", dc_model, "sandia")
    coalition = frozenset({Stage.DC})  # DC comes from config_b, AC comes from config_a

    assert coalition_is_pool_valid(config_a, config_b, coalition) == expected_ok


def test_pair_is_shapley_computable_true_when_every_coalition_is_valid():
    config_a = PipelineConfig("A", "erbs", "isotropic", "faiman", "singlediode_cec", "sandia")
    config_b = PipelineConfig("B", "disc", "haydavies", "pvsyst_cell", "singlediode_desoto", "adr")

    computable, invalid = pair_is_shapley_computable(config_a, config_b)

    assert computable is True
    assert invalid == []


def test_pair_is_shapley_computable_false_when_a_coalition_combines_pvwatts_dc_with_sandia():
    config_a = PipelineConfig("A", "erbs", "isotropic", "faiman", "pvwatts_dc", "pvwatts")
    config_b = PipelineConfig("B", "disc", "haydavies", "pvsyst_cell", "singlediode_cec", "sandia")

    computable, invalid = pair_is_shapley_computable(config_a, config_b)

    assert computable is False
    # The coalition with DC from A (pvwatts_dc) and AC from B (sandia) is invalid.
    assert frozenset({Stage.AC}) in invalid


# --- shapley_values: formula check, independent of PV ---------------------------


def test_shapley_values_matches_the_textbook_additive_game():
    """v(T) = sum of each player's own weight for players in T. The known
    Shapley value of an additive game is each player's own weight exactly --
    validates the formula against theory before trusting it on physics data.
    """
    weights = {Stage.DECOMPOSITION: 3.0, Stage.TRANSPOSITION: 1.0, Stage.TEMPERATURE: 4.0, Stage.DC: 1.0, Stage.AC: 5.0}
    v = {coalition: sum(weights[s] for s in coalition) for coalition in all_coalitions()}

    phi = shapley_values(v)

    for stage in ALL_STAGES:
        assert phi[stage] == pytest.approx(weights[stage])


# --- run_phase3: not-computable path ---------------------------------------------


def test_run_phase3_returns_not_computable_without_running_any_pipeline(monkeypatch):
    config_a = PipelineConfig("A", "erbs", "isotropic", "faiman", "pvwatts_dc", "pvwatts")
    config_b = PipelineConfig("B", "disc", "haydavies", "pvsyst_cell", "singlediode_cec", "sandia")

    def _boom(*args, **kwargs):
        raise AssertionError("run_pipeline must not be called for a non-computable pair")

    monkeypatch.setattr(phase3_module, "run_pipeline", _boom)

    result = run_phase3(
        config_a, result_a=None, config_b=config_b, result_b=None,
        shared_cec=None, shared_adr=None, daylight=None,
    )

    assert isinstance(result, Phase3NotComputable)
    assert result.pair == ("A", "B")
    assert result.reason == NOT_COMPUTABLE_REASON
    assert frozenset({Stage.AC}) in result.invalid_coalitions


# --- run_phase3: real end-to-end, N32 efficiency, signed sensitivity check -------


def test_run_phase3_real_end_to_end_satisfies_efficiency_and_reports_signed_sensitivity():
    shared = _shared()
    defaults = load_defaults()
    result_a = run_pipeline(CONFIG_A, shared, defaults)
    result_b = run_pipeline(CONFIG_B, shared, defaults)

    result = run_phase3(
        CONFIG_A, result_a, CONFIG_B, result_b,
        shared_cec=shared, shared_adr=shared,
        daylight=shared.ctx.daylight, defaults=defaults,
    )

    assert not isinstance(result, Phase3NotComputable)

    # N32 -- Shapley's efficiency axiom, aggregate and per-stage.
    tol = 1e-9
    assert sum(result.phi_ab.values()) == pytest.approx(result.v_ab[frozenset(ALL_STAGES)], abs=tol)
    assert sum(result.phi_ba.values()) == pytest.approx(result.v_ba[frozenset(ALL_STAGES)], abs=tol)
    assert sum(result.phi_final.values()) == pytest.approx(result.rmsd_ab, abs=tol)
    for stage in ALL_STAGES:
        assert result.phi_final[stage] == pytest.approx(
            (result.phi_ab[stage] + result.phi_ba[stage]) / 2, abs=tol
        )

    # v(empty)=0 in both directions by construction.
    assert result.v_ab[frozenset()] == 0.0
    assert result.v_ba[frozenset()] == 0.0

    # Signed sensitivity check (N2): structurally present, direction A->B only.
    assert result.signed_v[frozenset()] == 0.0
    assert set(result.signed_phi) == set(ALL_STAGES)

    # share is defined (pipelines are not identical here) and finite.
    for stage in ALL_STAGES:
        assert result.share[stage] is not None
        assert math.isfinite(result.share[stage])
