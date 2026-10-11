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
from pvdials.provenance.db import is_reachable
from pvdials.types import PipelineConfig, Stage
from tests.unit.test_pool_validity import HYBRID_VALIDITY_CASES

requires_postgres = pytest.mark.skipif(
    not is_reachable(),
    reason="No local Postgres reachable (DATABASE_URL not set or the service isn't running).",
)

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


@requires_postgres
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


def test_stage_not_in_s_gets_phi_final_zero():
    """Verification property #8, first half: a stage where both pipelines
    use the same model is never in S, so it can never be the coalition that
    changes AC output -- phi_final there must be exactly 0. CONFIG_A/CONFIG_B
    share dc_model and ac_model (both pvwatts_dc/pvwatts); this checks that
    explicitly, rather than only checking share[stage] is finite as the
    efficiency test above does.

    Representation note (per project decision): the output object stores
    this as 0.0, not a null/None -- confirmed here, not changed.
    """
    shared = _shared()
    defaults = load_defaults()
    result_a = run_pipeline(CONFIG_A, shared, defaults)
    result_b = run_pipeline(CONFIG_B, shared, defaults)

    result = run_phase3(
        CONFIG_A, result_a, CONFIG_B, result_b,
        shared_cec=shared, shared_adr=shared, daylight=shared.ctx.daylight,
        defaults=defaults, record=False,
    )

    assert CONFIG_A.dc_model == CONFIG_B.dc_model
    assert CONFIG_A.ac_model == CONFIG_B.ac_model
    assert result.phi_final[Stage.DC] == 0.0
    assert result.phi_final[Stage.AC] == 0.0
    assert result.signed_phi[Stage.DC] == 0.0
    assert result.signed_phi[Stage.AC] == 0.0


def test_pair_differing_at_exactly_one_stage_gives_it_100_percent_share():
    """Verification property #8, second half: |S|=1 means the full 32-member
    coalition space still degenerates to 2 physically distinct configs (the
    two endpoints), so the one stage in S must take the entire RMSD -- share
    == 1.0, every other stage's phi_final == 0.
    """
    shared = _shared()
    defaults = load_defaults()
    config_a = PipelineConfig("A", "erbs", "isotropic", "faiman", "pvwatts_dc", "pvwatts")
    config_b = PipelineConfig("B", "erbs", "haydavies", "faiman", "pvwatts_dc", "pvwatts")
    result_a = run_pipeline(config_a, shared, defaults)
    result_b = run_pipeline(config_b, shared, defaults)

    result = run_phase3(
        config_a, result_a, config_b, result_b,
        shared_cec=shared, shared_adr=shared, daylight=shared.ctx.daylight,
        defaults=defaults, record=False,
    )

    assert result.share[Stage.TRANSPOSITION] == pytest.approx(1.0, abs=1e-9)
    for stage in ALL_STAGES:
        if stage != Stage.TRANSPOSITION:
            assert result.phi_final[stage] == 0.0


def test_relabelling_the_pair_does_not_change_phi_final_or_share():
    """Verification property #2, extended past Phase 1: phi_final is already
    the average of both anchor directions, so swapping which config is X and
    which is Y must leave phi_final/rmsd_ab/share unchanged -- only
    signed_phi is expected to flip sign (it reports a direction, not a
    magnitude). record=False: this only needs the physics, not provenance.
    """
    shared = _shared()
    defaults = load_defaults()
    result_a = run_pipeline(CONFIG_A, shared, defaults)
    result_b = run_pipeline(CONFIG_B, shared, defaults)

    ab = run_phase3(
        CONFIG_A, result_a, CONFIG_B, result_b,
        shared_cec=shared, shared_adr=shared, daylight=shared.ctx.daylight,
        defaults=defaults, record=False,
    )
    ba = run_phase3(
        CONFIG_B, result_b, CONFIG_A, result_a,
        shared_cec=shared, shared_adr=shared, daylight=shared.ctx.daylight,
        defaults=defaults, record=False,
    )

    assert ab.rmsd_ab == pytest.approx(ba.rmsd_ab)
    for stage in ALL_STAGES:
        assert ab.phi_final[stage] == pytest.approx(ba.phi_final[stage], abs=1e-9)
        assert ab.share[stage] == pytest.approx(ba.share[stage], abs=1e-9)
        assert ab.signed_phi[stage] == pytest.approx(-ba.signed_phi[stage], abs=1e-9)


@requires_postgres
def test_run_phase3_records_every_derived_run_as_execution_set_derived():
    """Closes the O2 gap: Phase 3's derived-pipeline runs must be
    reconstructible from the record, same as an original run_pipeline() call.

    28/09 (evaluation KT Step 0): count updated from 60 to 2^|S|-2. Before the
    dedup fix, every one of the 32-coalition space's 30 non-trivial T's per
    direction got its own label (built from the FULL 5-stage coalition, not
    just S), so stages outside S produced byte-identical models under
    DIFFERENT labels -- and since config.label is itself one of the hashed
    provenance attributes (provenance/model.py::build_document), those
    differently-labelled-but-physically-identical configs never deduplicated,
    giving 60 distinct rows. The fix uses one canonical, S-scoped label per
    physically distinct config, shared by both directions -- CONFIG_A/
    CONFIG_B differ at 3 stages (decomposition, transposition, temperature;
    dc and ac share a model), so 2^3-2 = 6.
    """
    from pvdials.provenance.db import get_connection, run_schema
    from pvdials.types import ExecutionSet

    with get_connection() as conn:
        run_schema(conn)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM stage_output_values")
            cur.execute("DELETE FROM provenance_records")
        conn.commit()

    shared = _shared()
    defaults = load_defaults()
    result_a = run_pipeline(CONFIG_A, shared, defaults)
    result_b = run_pipeline(CONFIG_B, shared, defaults)

    run_phase3(
        CONFIG_A, result_a, CONFIG_B, result_b,
        shared_cec=shared, shared_adr=shared,
        daylight=shared.ctx.daylight, defaults=defaults,
    )

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT config_label FROM provenance_records WHERE execution_set = %s",
            (ExecutionSet.DERIVED.value,),
        )
        labels = [row[0] for row in cur.fetchall()]

    derived_labels = [label for label in labels if label.startswith("_derived_")]

    # 2^|S|-2 distinct derived configs, shared across both directions -- see
    # the docstring above for why this isn't 60 anymore.
    assert len(derived_labels) == 6


@pytest.mark.parametrize(
    "config_b, expected_s",
    [
        (CONFIG_B, 3),  # decomposition, transposition, temperature differ
        (PipelineConfig("D", "disc", "isotropic", "pvsyst_cell", "pvwatts_dc", "pvwatts"), 2),  # decomposition, temperature
    ],
)
def test_run_phase3_calls_run_pipeline_exactly_2_pow_s_minus_2_times(monkeypatch, config_b, expected_s):
    """28/09 (evaluation KT Step 0): checks the dedup mechanism directly --
    the actual number of run_pipeline() calls _shared_ac_series_cache() makes
    -- rather than only its downstream effect on provenance record counts
    (test_run_phase3_records_every_derived_run_as_execution_set_derived,
    above). record=False, so this doesn't need Postgres at all.
    """
    shared = _shared()
    defaults = load_defaults()
    result_a = run_pipeline(CONFIG_A, shared, defaults)
    result_b = run_pipeline(config_b, shared, defaults)

    real_run_pipeline = phase3_module.run_pipeline
    calls = []

    def counting_run_pipeline(*args, **kwargs):
        calls.append(1)
        return real_run_pipeline(*args, **kwargs)

    monkeypatch.setattr(phase3_module, "run_pipeline", counting_run_pipeline)

    run_phase3(
        CONFIG_A, result_a, config_b, result_b,
        shared_cec=shared, shared_adr=shared,
        daylight=shared.ctx.daylight, defaults=defaults, record=False,
    )

    assert len(calls) == 2**expected_s - 2
