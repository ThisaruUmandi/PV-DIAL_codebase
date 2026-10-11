"""O4 (KT Step 10): guided re-execution tests."""

import numpy as np
import pandas as pd
import pytest
from pvlib import pvsystem

from pvdials.config import load_defaults
from pvdials.data.column_mapper import TAG_ASSUMED_ABSENT, SiteMetadata, TimeOffset
from pvdials.dla.phase1 import run_phase1
from pvdials.guided_reexecution import (
    DISCLAIMER,
    FinalRunResult,
    O4Error,
    O4Session,
    ProposalResult,
    alternatives_at_stage,
    annual_yield_kwh,
    stage_field,
    substitute_stage,
)
from pvdials.physics.geometry import ArrayGeometry, resolve_albedo
from pvdials.physics.hardware import (
    ADR_INVERTER,
    CEC,
    CEC_INVERTER,
    ArraySize,
    InverterRecord,
    ModuleRecord,
)
from pvdials.physics.mounting import resolve_mounting
from pvdials.physics.pipeline import SharedInputs, run_pipeline
from pvdials.physics.registry import stage3_pool_view, stage4_pool_view
from pvdials.physics.site import build_site_context
from pvdials.provenance.db import get_connection, is_reachable, run_schema
from pvdials.types import ExecutionSet, PipelineConfig, Stage
from tests.dla.mock_adapters import install_mock_model

pytestmark = pytest.mark.filterwarnings("ignore::RuntimeWarning")

requires_postgres = pytest.mark.skipif(
    not is_reachable(),
    reason="No local Postgres reachable (DATABASE_URL not set or the service isn't running).",
)

CONFIG_A = PipelineConfig("A", "erbs", "isotropic", "faiman", "singlediode_cec", "sandia")
CONFIG_B = PipelineConfig("B", "disc", "haydavies", "pvsyst_cell", "singlediode_desoto", "adr")


def _inverter_dbs():
    return pvsystem.retrieve_sam(CEC_INVERTER), pvsystem.retrieve_sam(ADR_INVERTER)


def _shared_pair():
    """Two SharedInputs, one per inverter library -- CONFIG_B uses ac_model=
    'adr', which needs the ADRInverter-tagged record; CONFIG_A's 'sandia'
    needs the CECInverter-tagged one. Same routing Phase 3 established.

    Uses a synthetic full day (real Colombo lat/long, real solar position
    driving GHI), not the tiny 1-daylight-row repo fixture -- 28/09's
    sample-size guard (dla/metrics.py, N_MIN=21) makes that fixture give
    "not computable" rather than a real Phase 1 outcome/k.
    """
    index = pd.date_range("2023-06-21 00:00", periods=24, freq="h", tz="UTC")
    site = SiteMetadata(
        values={"latitude": 6.944, "longitude": 79.856, "elevation": 16.0},
        sources={"latitude": "test", "longitude": "test", "elevation": "test"},
    )
    offset = TimeOffset(0.0, TAG_ASSUMED_ABSENT, None)
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
    cec_modules = pvsystem.retrieve_sam(CEC)
    module = ModuleRecord(
        CEC, "Canadian_Solar_Inc__CS6K_300MS", cec_modules["Canadian_Solar_Inc__CS6K_300MS"]
    )
    cec_inverters, adr_inverters = _inverter_dbs()
    inv_name = "ABB__PVI_6000_OUTD_S_US_A__208V_"

    base = {
        "weather": weather,
        "ctx": ctx,
        "geometry": ArrayGeometry(surface_tilt_deg=6.944, surface_azimuth_deg=180.0),
        "albedo": resolve_albedo(None, load_defaults()),
        "mounting": resolve_mounting(None, None, load_defaults()),
        "module": module,
        "array_size": ArraySize(10, 2),
        "module_height_m": 3.0,
    }
    shared_cec = SharedInputs(
        **base, inverter=InverterRecord(CEC_INVERTER, inv_name, cec_inverters[inv_name])
    )
    shared_adr = SharedInputs(
        **base, inverter=InverterRecord(ADR_INVERTER, inv_name, adr_inverters[inv_name])
    )
    return shared_cec, shared_adr


def _session(monkeypatch, defaults=None):
    """Over a real full day (28/09's sample-size guard needs >=11 daylight
    rows), CONFIG_A and CONFIG_B's real models (erbs/disc, isotropic/
    haydavies, singlediode_cec/desoto, sandia/adr) all land under tau --
    genuinely consistent, not a test bug (matches what the real Colombo run
    showed: reasonable pvlib models usually agree). To exercise the session
    mechanics we still need a real, tau-exceeding disagreement, so CONFIG_B's
    temperature model is swapped for a mock that exaggerates pvsyst_cell's
    own output (same technique as tests/dla/test_mock_adapters.py) -- this
    guarantees phase1.k == Stage.TEMPERATURE without touching CONFIG_A/B's
    real-model identity anywhere else in this file.
    """
    shared_cec, shared_adr = _shared_pair()
    cec_inverters, adr_inverters = _inverter_dbs()
    install_mock_model(monkeypatch, Stage.TEMPERATURE, "mock_pvsyst_cell_triple", "pvsyst_cell", delta=2.0)
    config_b = substitute_stage(CONFIG_B, Stage.TEMPERATURE, "mock_pvsyst_cell_triple", label="B")

    result_a = run_pipeline(CONFIG_A, shared_cec, defaults)
    result_b = run_pipeline(config_b, shared_adr, defaults)
    phase1 = run_phase1(
        CONFIG_A, result_a, config_b, result_b, shared_cec.ctx.daylight, defaults=defaults
    )
    assert phase1.k is not None  # this pair must actually disagree for a session to make sense
    return O4Session(
        pair=(CONFIG_A.label, config_b.label),
        anchor_config=CONFIG_A,
        anchor_result=result_a,
        other_config=config_b,
        other_result=result_b,
        stage=phase1.k,
        shared_cec=shared_cec,
        shared_adr=shared_adr,
        cec_inverters=cec_inverters,
        adr_inverters=adr_inverters,
        daylight=shared_cec.ctx.daylight,
        defaults=defaults,
    )


# --- substitute_stage -------------------------------------------------------------


def test_substitute_stage_replaces_only_the_named_stage():
    substituted = substitute_stage(CONFIG_A, Stage.TEMPERATURE, "pvsyst_cell", label="x")

    assert substituted.temperature_model == "pvsyst_cell"
    assert substituted.decomposition_model == CONFIG_A.decomposition_model
    assert substituted.transposition_model == CONFIG_A.transposition_model
    assert substituted.dc_model == CONFIG_A.dc_model
    assert substituted.ac_model == CONFIG_A.ac_model
    assert substituted.label == "x"


def test_substitute_stage_covers_every_stage_field():
    for stage in Stage:
        field = stage_field(stage)
        substituted = substitute_stage(CONFIG_A, stage, "placeholder_model", label="x")
        assert getattr(substituted, field) == "placeholder_model"


# --- alternatives_at_stage ---------------------------------------------------------


def test_alternatives_at_stage_dispatches_to_the_matching_pool_view():
    shared_cec, _ = _shared_pair()
    cec_inverters, adr_inverters = _inverter_dbs()

    temperature_alts = alternatives_at_stage(
        Stage.TEMPERATURE, CONFIG_A, shared_cec, cec_inverters, adr_inverters
    )
    assert temperature_alts == stage3_pool_view(shared_cec.module, shared_cec.mounting)

    dc_alts = alternatives_at_stage(Stage.DC, CONFIG_A, shared_cec, cec_inverters, adr_inverters)
    assert dc_alts == stage4_pool_view(shared_cec.module)


# --- annual_yield_kwh ---------------------------------------------------------------


def test_annual_yield_kwh_uses_each_rows_actual_duration():
    """Irregular gaps: 1h, then 2h, then (no next row) assumed = the last gap (2h)."""
    index = pd.DatetimeIndex(["2023-01-01 00:00", "2023-01-01 01:00", "2023-01-01 03:00"], tz="UTC")
    p_ac = pd.Series([100.0, 200.0, 300.0], index=index)  # W

    class _FakeAC:
        outputs = pd.DataFrame({"p_ac": p_ac})

    class _FakeOutputs:
        ac = _FakeAC()

    class _FakeResult:
        outputs = _FakeOutputs()

    # row 0: 1h @ 100W = 100 Wh; row 1: 2h @ 200W = 400 Wh; row 2 (last, no next
    # row): assumed 2h (the preceding gap) @ 300W = 600 Wh. Total = 1100 Wh = 1.1 kWh.
    assert annual_yield_kwh(_FakeResult()) == pytest.approx(1.1)


def test_annual_yield_kwh_single_row_assumes_one_hour():
    index = pd.DatetimeIndex(["2023-01-01 00:00"], tz="UTC")
    p_ac = pd.Series([500.0], index=index)

    class _FakeAC:
        outputs = pd.DataFrame({"p_ac": p_ac})

    class _FakeOutputs:
        ac = _FakeAC()

    class _FakeResult:
        outputs = _FakeOutputs()

    assert annual_yield_kwh(_FakeResult()) == pytest.approx(0.5)


# --- O4Session: pool-valid enforcement, anti-chaining, provenance -----------------


@requires_postgres
def test_propose_rejects_a_candidate_that_is_not_pool_valid_at_the_session_stage(monkeypatch):
    session = _session(monkeypatch, load_defaults())
    valid_names = {c.name for c in session.alternatives() if c.selectable}
    assert "definitely_not_a_real_model" not in valid_names

    with pytest.raises(O4Error):
        session.propose("definitely_not_a_real_model")


@requires_postgres
def test_retry_never_chains_onto_a_previous_attempt(monkeypatch):
    """Two different substitutions in a row must each independently equal
    anchor + exactly one substitution -- never anchor + both.
    """
    session = _session(monkeypatch, load_defaults())
    candidates = [c.name for c in session.alternatives() if c.selectable]
    assert len(candidates) >= 2, "need at least 2 real alternatives to prove non-chaining"

    first = session.propose(candidates[0])
    second = session.retry(candidates[1])

    field = stage_field(session.stage)
    # Every OTHER field must still match the anchor exactly in both attempts --
    # if retry had chained onto `first`, second's other fields could differ.
    for stage in Stage:
        if stage == session.stage:
            continue
        other_field = stage_field(stage)
        assert getattr(first.config, other_field) == getattr(session.anchor_config, other_field)
        assert getattr(second.config, other_field) == getattr(session.anchor_config, other_field)

    assert getattr(first.config, field) == candidates[0]
    assert getattr(second.config, field) == candidates[1]
    assert first.pair == session.pair
    assert second.pair == session.pair


def test_a_substituted_config_is_sealed_to_its_own_pair(monkeypatch):
    """Verification property #20: a config produced by one pair's session
    must never be indistinguishable from one produced by another pair's
    session. _run_substitution's label is built from self.pair
    (guided_reexecution.py), so two sessions differing only in `pair` --
    same anchor_config, same stage, same candidate -- must still produce
    configs with different labels, tagged to their own track.
    """
    import dataclasses

    session_ab = _session(monkeypatch, load_defaults())
    session_ad = dataclasses.replace(session_ab, pair=("A", "D"))

    candidate = next(c.name for c in session_ab.alternatives() if c.selectable)

    result_ab = session_ab.propose(candidate)
    result_ad = session_ad.propose(candidate)

    assert result_ab.pair == ("A", session_ab.other_config.label)
    assert result_ad.pair == ("A", "D")
    assert result_ab.config.label != result_ad.config.label
    assert result_ab.config != result_ad.config


@requires_postgres
def test_propose_and_confirm_are_recorded_as_reexec(monkeypatch):
    with get_connection() as conn:
        run_schema(conn)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM stage_output_values")
            cur.execute("DELETE FROM provenance_records")
        conn.commit()

    session = _session(monkeypatch, load_defaults())
    candidate = next(c.name for c in session.alternatives() if c.selectable)

    proposal = session.propose(candidate)
    final = session.confirm(candidate, compute_yield=True)

    assert isinstance(proposal, ProposalResult)
    assert isinstance(final, FinalRunResult)
    assert final.disclaimer == DISCLAIMER
    assert final.annual_yield_kwh is not None
    assert final.annual_yield_kwh > 0

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM provenance_records WHERE execution_set = %s",
            (ExecutionSet.REEXEC.value,),
        )
        reexec_count = cur.fetchone()[0]

    # propose() + confirm() = 2 distinct recorded runs (different labels).
    assert reexec_count == 2
