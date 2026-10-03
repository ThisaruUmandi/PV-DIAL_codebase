"""End-to-end orchestrator tests (pvdials/analysis.py)."""

import copy
import re
from pathlib import Path

import pytest
import yaml

import pvdials.analysis as analysis_module
from pvdials.analysis import (
    NOT_RUN_OUTCOME_1,
    AnalysisError,
    PipelineRunResult,
    build_results_dict,
    parse_analysis_yaml,
    run_analysis,
    step_disagreement_check,
    step_hardware,
    step_load_and_validate,
    step_site_and_offset,
)
from pvdials.config import load_defaults
from pvdials.provenance.analyses import load_analysis
from pvdials.provenance.db import get_connection, is_reachable, run_schema
from pvdials.types import Stage
from tests.dla.mock_adapters import install_mock_model, install_mock_temperature_model

from experiments.evaluation.db_safety import guard_not_dev_database, resolve_current_database_url

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REAL_FILE = Path("data/weather/tmy_6.944_79.856_2005_2020.csv")

pytestmark = pytest.mark.filterwarnings("ignore::RuntimeWarning")

requires_postgres = pytest.mark.skipif(
    not is_reachable(),
    reason="No local Postgres reachable (DATABASE_URL not set or the service isn't running).",
)
requires_real_file = pytest.mark.skipif(
    not REAL_FILE.exists(), reason=f"Real Colombo file not present at {REAL_FILE}"
)
if REAL_FILE.exists():
    from experiments.evaluation.weather_source import verify_thesis_weather_file

    verify_thesis_weather_file()


@pytest.fixture(autouse=True)
def _clean_schema():
    guard_not_dev_database(resolve_current_database_url(), "_clean_schema")
    with get_connection() as conn:
        run_schema(conn)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM analysis_records")
            cur.execute("DELETE FROM analyses")
            cur.execute("DELETE FROM stage_output_values")
            cur.execute("DELETE FROM provenance_records")
        conn.commit()
    yield


BASE_YAML: dict = {
    "name": "test",
    "weather_file": str(FIXTURES / "sample_pvgis_tmy.csv"),
    "time_offset": {"value_h": 0.5, "reason": "header value, unmodified"},
    "site": {
        "tilt_deg": 6.944, "azimuth_deg": 180.0, "albedo": None,
        "mounting_geometry": None, "mounting_construction": None, "module_height_m": 3.0,
    },
    "hardware": {
        "module_name": "Canadian_Solar_Inc__CS6K_300MS",
        "inverter_name": "ABB__PVI_6000_OUTD_S_US_A__208V_",
        "modules_per_string": 10, "strings_per_inverter": 2,
    },
    "pipelines": {
        "A": {"decomposition": "erbs", "transposition": "isotropic", "temperature": "faiman",
              "dc": "singlediode_cec", "ac": "sandia"},
        "B": {"decomposition": "disc", "transposition": "haydavies", "temperature": "pvsyst_cell",
              "dc": "singlediode_desoto", "ac": "sandia"},
        "C": {"decomposition": "dirint", "transposition": "perez", "temperature": "ross",
              "dc": "singlediode_cec", "ac": "sandia"},
    },
}


def _write_yaml(tmp_path, overrides: dict | None = None) -> str:
    data = copy.deepcopy(BASE_YAML)
    if overrides:
        data.update(overrides)
    path = tmp_path / "analysis.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")
    return str(path)


def _use_fixed_tau(monkeypatch, tau: float) -> None:
    """Makes run_analysis() use an explicit, test-local tau instead of
    whatever configs/run_defaults.yaml currently has -- a test whose outcome
    assertions hinge on a specific tau value must not depend on the live
    production default (28/09: changing that default from 0.234 to 0.093
    silently broke test_only_one_qualifying_pair_runs_phase2_and_gates_phase3_per_pair,
    which had no such override).
    """
    fixed_defaults = copy.deepcopy(load_defaults())
    fixed_defaults["dla"]["tau"] = tau
    monkeypatch.setattr(analysis_module, "load_defaults", lambda: fixed_defaults)


# --- YAML parsing -------------------------------------------------------------------


def test_parse_analysis_yaml_missing_file_raises_clearly():
    with pytest.raises(AnalysisError, match="not found"):
        parse_analysis_yaml("/no/such/file.yaml")


def test_parse_analysis_yaml_missing_pipeline_stage_raises_clearly(tmp_path):
    data = {**BASE_YAML, "pipelines": {**BASE_YAML["pipelines"], "A": {"decomposition": "erbs"}}}
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")
    with pytest.raises(AnalysisError, match="missing stage"):
        parse_analysis_yaml(str(path))


def test_parse_analysis_yaml_happy_path(tmp_path):
    config = parse_analysis_yaml(_write_yaml(tmp_path))
    assert config.name == "test"
    assert config.pipelines["A"]["temperature"] == "faiman"
    assert config.reexecution is None


# --- End-to-end on the real small fixture (real models, no mock) -------------------


@requires_postgres
def test_run_analysis_end_to_end_on_real_fixture(tmp_path):
    """Runs every step through analysis.py's real functions -- the small
    repo fixture is a real file, so this proves the whole wiring executes
    without error, even though (being 4 rows / 1 daylight row) its own
    numbers are not meaningful evidence of anything -- see demo_full_project.py's
    prior finding on this same fixture.
    """
    run = run_analysis(_write_yaml(tmp_path))

    assert run.load_result.validation.passed
    assert set(run.pipelines.configs) == {"A", "B", "C"}
    assert set(run.phase1_results) == {("A", "B"), ("A", "C"), ("B", "C")}

    saved = load_analysis(run.analysis_id)
    assert saved["status"] == "done"
    assert saved["name"] == "test"


# --- Constructed outcome-3 pair: Phase 2, Phase 3, re-execution, save->load --------


@pytest.mark.slow
@requires_postgres
@requires_real_file
def test_constructed_outcome_3_pair_covers_phase2_phase3_reexec_and_roundtrip(tmp_path, monkeypatch):
    """The small repo fixture (4 rows, 1 daylight row) turns out to be
    unusable for this: its pooled-quantile nRMSD calculation is degenerate
    (probed directly -- every delta from 5% to 25% gave the identical
    saturated nRMSD=1.1111 at every stage, so outcome never reached 3
    regardless of perturbation size). This uses the real Colombo file
    instead (same one used throughout this project's real-data
    verifications), where +100%/-50% rise-above-ambient temperature
    perturbations are confirmed (probed directly) to give outcome 3 for all
    three pairs: pipeline A keeps the real 'faiman' model; B and C use mock
    perturbations of it. Exercises Phase 2, Phase 3, and one confirmed
    re-execution together, then a save -> load round trip. Slower than the
    rest of this file (real 8,760-row data, real Phase 3 derived runs) --
    expect this one test to take on the order of a minute.

    The mocks perturb the RISE above ambient (temp_cell - temp_air), not the
    absolute Celsius value (28/09's failed-check policy, item 5, surfaced why
    this matters): faiman's cell temp equals ambient exactly at night and
    near sunrise/sunset, and a plain multiplicative perturbation of the
    absolute value scales ambient itself there -- confirmed directly, a
    +/-30% version of this pushed >1,000 real rows more than 5 C below air
    temp, tripping the unrelated physical-plausibility check regardless of
    how reasonable the intended daytime disagreement was.
    install_mock_temperature_model keeps every model's real
    ambient-convergence property intact, so no such rows occur here.
    """
    overrides = {
        "weather_file": str(REAL_FILE),
        "time_offset": {"value_h": 0.0, "reason": "header states 0.5 h; file day/night content aligns with 0 h"},
        "pipelines": {
            "A": {**BASE_YAML["pipelines"]["A"], "temperature": "faiman"},
            "B": {**BASE_YAML["pipelines"]["A"], "temperature": "mock_temp_plus100"},
            "C": {**BASE_YAML["pipelines"]["A"], "temperature": "mock_temp_minus50"},
        },
        "reexecution": {"pair": "A-B", "anchor": "A", "candidate": "pvsyst_cell"},
    }
    yaml_path = _write_yaml(tmp_path, overrides)

    install_mock_temperature_model(monkeypatch, "mock_temp_plus100", "faiman", delta=1.0)
    install_mock_temperature_model(monkeypatch, "mock_temp_minus50", "faiman", delta=-0.5)

    run = run_analysis(yaml_path)

    for pair, p1 in run.phase1_results.items():
        assert p1.outcome == 3, f"{pair} did not reach outcome 3: {p1.outcome}"

    assert run.phase2_result is not None
    assert run.phase3_results
    for result in run.phase3_results.values():
        assert not isinstance(result, str), "Phase 3 unexpectedly not run for a qualifying pair"

    assert run.reexec_result is not None
    assert run.reexec_result.config.temperature_model == "pvsyst_cell"
    assert "preferable" in run.reexec_result.disclaimer

    # The re-execution attempt is recorded as REEXEC and linked to this
    # analysis -- checked here, inside the test, rather than by querying the
    # DB afterward (a later, unrelated test's cleanup fixture legitimately
    # wipes provenance_records, cascading the link away, so post-suite state
    # doesn't reflect what this test itself verified).
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT pr.execution_set, pr.config_label FROM provenance_records pr "
            "JOIN analysis_records ar ON ar.record_id = pr.id "
            "WHERE ar.analysis_id = %s AND pr.execution_set = %s",
            (run.analysis_id, "reexec"),
        )
        reexec_rows = cur.fetchall()
    assert len(reexec_rows) == 1
    assert reexec_rows[0][1] == run.reexec_result.config.label

    # save -> load round trip
    saved = load_analysis(run.analysis_id)
    assert saved["status"] == "done"
    assert saved["phase2"]["status"] == "ran"
    assert all(v["status"] == "ran" for v in saved["phase3"].values())
    assert saved["reexec"]["substituted_stage_model"]["temperature_model"] == "pvsyst_cell"


@pytest.mark.slow
@requires_postgres
@requires_real_file
def test_only_one_qualifying_pair_runs_phase2_and_gates_phase3_per_pair(tmp_path, monkeypatch):
    """New Phase 2 gate: it runs whenever AT LEAST ONE pair reached outcome
    2/3, not only when all three do -- confirmed empirically (probed
    directly on the real file). Uses an explicit, test-local tau (0.10),
    independent of whatever configs/run_defaults.yaml currently has (28/09:
    changing that default from 0.234 to 0.093 silently broke this test, since
    it previously read the live default implicitly) -- A=real faiman, B=mock
    +10% (A-B crosses tau: temp_nrmsd=0.1391, +39% over), C=mock+5% (A-C=
    0.0734, B-C=0.0699, both ~27-30% under tau). Comfortable margins on both
    sides (previously ~0.007, thin) so this doesn't need retuning again if
    TEST_TAU or the real-file data ever shift slightly. Phase 2 must run
    (computed over all three pairs regardless); Phase 3 must run for A-B
    only, reporting NOT_RUN_OUTCOME_1 for A-C/B-C.
    """
    TEST_TAU = 0.10
    _use_fixed_tau(monkeypatch, TEST_TAU)
    install_mock_model(monkeypatch, Stage.TEMPERATURE, "mock_b", "faiman", delta=0.10)
    install_mock_model(monkeypatch, Stage.TEMPERATURE, "mock_c", "faiman", delta=0.05)

    overrides = {
        "weather_file": str(REAL_FILE),
        "time_offset": {"value_h": 0.0, "reason": "header states 0.5 h; file day/night content aligns with 0 h"},
        "pipelines": {
            "A": {**BASE_YAML["pipelines"]["A"], "temperature": "faiman"},
            "B": {**BASE_YAML["pipelines"]["A"], "temperature": "mock_b"},
            "C": {**BASE_YAML["pipelines"]["A"], "temperature": "mock_c"},
        },
    }
    run = run_analysis(_write_yaml(tmp_path, overrides))

    assert run.phase1_results[("A", "B")].outcome == 3
    assert run.phase1_results[("A", "C")].outcome == 1
    assert run.phase1_results[("B", "C")].outcome == 1

    assert run.phase2_result is not None, "Phase 2 must run when at least one pair qualifies"

    assert not isinstance(run.phase3_results[("A", "B")], str)
    assert run.phase3_results[("A", "C")] == NOT_RUN_OUTCOME_1
    assert run.phase3_results[("B", "C")] == NOT_RUN_OUTCOME_1


def test_reexecution_on_an_outcome_1_pair_is_refused(tmp_path, monkeypatch):
    """Verification property #10, second half: an outcome-1 pair (k is None,
    nothing to substitute) must refuse an O4 track rather than silently
    running one. Reuses the same A/B/C setup as the Phase 2/3 gating test
    above, where A-C is outcome 1, and points reexecution at that pair.
    """
    TEST_TAU = 0.10
    _use_fixed_tau(monkeypatch, TEST_TAU)
    install_mock_model(monkeypatch, Stage.TEMPERATURE, "mock_b", "faiman", delta=0.10)
    install_mock_model(monkeypatch, Stage.TEMPERATURE, "mock_c", "faiman", delta=0.05)

    overrides = {
        "weather_file": str(REAL_FILE),
        "time_offset": {"value_h": 0.0, "reason": "header states 0.5 h; file day/night content aligns with 0 h"},
        "pipelines": {
            "A": {**BASE_YAML["pipelines"]["A"], "temperature": "faiman"},
            "B": {**BASE_YAML["pipelines"]["A"], "temperature": "mock_b"},
            "C": {**BASE_YAML["pipelines"]["A"], "temperature": "mock_c"},
        },
        "reexecution": {"pair": "A-C", "anchor": "A", "candidate": "disc"},
    }

    with pytest.raises(AnalysisError, match=re.escape(NOT_RUN_OUTCOME_1)):
        run_analysis(_write_yaml(tmp_path, overrides))


def test_step_disagreement_check_passes_the_identical_daylight_object_to_every_pair():
    """Verification property #15: the daylight mask must be identical for
    every configuration -- checked here at the point where step_disagreement_check
    hands it to run_phase1 for each of the three pairs, since that's the one
    place a per-pair recompute or a copy could slip in. Identity (`is`), not
    just equality, since analysis.py's own comment claims this is the same
    ctx.daylight object every time, never rebuilt.
    """
    from types import SimpleNamespace

    from tests.dla.builders import DEFAULT_INDEX, all_daylight, make_pipeline_result

    daylight = all_daylight(DEFAULT_INDEX)
    ctx = SimpleNamespace(daylight=daylight)

    ramp = [400.0, 500.0, 600.0, 600.0, 500.0, 400.0]
    results = {
        label: make_pipeline_result(
            label, decomposition_model=model,
            dni=ramp, dhi=[v / 4 for v in ramp], poa_global=[v * 1.1 for v in ramp],
            temp_cell=[v / 10 for v in ramp], p_dc=[v * 3 for v in ramp], p_ac=[v * 2.8 for v in ramp],
        )
        for label, model in (("A", "erbs"), ("B", "disc"), ("C", "dirint"))
    }
    pipelines = PipelineRunResult(
        configs={label: r.config for label, r in results.items()},
        results=results,
        checks={label: {} for label in results},
        annual_yield_kwh={label: 0.0 for label in results},
    )

    seen_daylight_objects = []
    real_run_phase1 = analysis_module.run_phase1

    def spy_run_phase1(config_a, result_a, config_b, result_b, passed_daylight, **kwargs):
        seen_daylight_objects.append(passed_daylight)
        return real_run_phase1(config_a, result_a, config_b, result_b, passed_daylight, **kwargs)

    analysis_module.run_phase1 = spy_run_phase1
    try:
        step_disagreement_check(pipelines, ctx, load_defaults())
    finally:
        analysis_module.run_phase1 = real_run_phase1

    assert len(seen_daylight_objects) == 3
    assert all(obj is daylight for obj in seen_daylight_objects)


def test_analysis_rejects_a_weather_file_missing_a_required_column(tmp_path):
    """Verification property #16, end to end: a file missing a required
    field must be rejected, with the missing field named -- not just the
    detection primitive (test_column_mapper.py::test_detects_missing_field),
    but the actual step_load_and_validate/run_analysis rejection path.
    sample_weather_incomplete.csv is missing wind_speed (confirmed via
    detect_columns in test_column_mapper.py).
    """
    incomplete_file = FIXTURES / "sample_weather_incomplete.csv"
    overrides = {"weather_file": str(incomplete_file)}

    with pytest.raises(AnalysisError, match="wind_speed"):
        run_analysis(_write_yaml(tmp_path, overrides))


def test_no_comparison_can_contain_both_sapm_and_single_diode(tmp_path):
    """Verification property #18: step_hardware always loads a CEC-library
    module (load_module(CEC, ...), analysis.py) -- there is no code path in
    this app that loads a SANDIA-library module for a real comparison. Since
    stage4_selectable() gates sapm on module.library == SANDIA and
    singlediode_desoto/singlediode_cec on module.library == CEC, this single
    shared module structurally makes sapm unselectable in every comparison
    this app can actually build, which is a stronger guarantee than "not
    both" -- confirmed directly against the real hardware-loading path, not
    just the registry function in isolation (test_registry.py already
    covers that).
    """
    from pvdials.dla.metrics import resolve_tau
    from pvdials.physics.hardware import CEC
    from pvdials.physics.registry import stage4_selectable

    defaults = load_defaults()
    config = parse_analysis_yaml(_write_yaml(tmp_path))
    load_result = step_load_and_validate(config.weather_file)
    tau = resolve_tau(None, defaults)
    site_result = step_site_and_offset(load_result, config, defaults, tau)
    hardware = step_hardware(load_result, site_result, config, defaults)

    module = hardware.shared_cec.module
    assert module.library == CEC
    sapm_ok, _ = stage4_selectable("sapm", module)
    cec_ok, _ = stage4_selectable("singlediode_cec", module)
    desoto_ok, _ = stage4_selectable("singlediode_desoto", module)

    assert sapm_ok is False
    assert cec_ok is True
    assert desoto_ok is True


def test_dla_output_object_has_every_specified_field(tmp_path, monkeypatch):
    """Verification property #24, against the field list Umee gave directly
    (not a spec document in this repo):

    Phase 1, per pair and stage: RMSD, nRMSD, MAD, MBD, systematic share,
    outcome, k. Phase 2, per pair: nRMSD by stage, mean, max, delta.
    Phase 3: phi in both directions, phi_final, share, signed phi, the v
    tables. Pool view: kept separate from the pair results (checked
    structurally in tests/guards/test_layers.py, not here).

    Reuses the A-B-reaches-outcome-3 setup from
    test_only_one_qualifying_pair_runs_phase2_and_gates_phase3_per_pair, since
    field presence for the Phase 2/3 "ran" branches can only be checked on a
    pair that actually ran them -- an all-outcome-1 run would report Phase 2
    as "not run" and every Phase 3 pair as a bare string, with none of the
    fields below present at all (by design, not a defect).

    Not renaming anything: this only asserts presence, using the exact
    field names phase1_to_dict/phase2_to_dict/phase3_pair_to_dict already
    use (systematic_share, mean_nrmsd, max_nrmsd, phi_ab, phi_ba, phi_final,
    signed_phi, v_ab, v_ba, signed_v).
    """
    TEST_TAU = 0.10
    _use_fixed_tau(monkeypatch, TEST_TAU)
    install_mock_model(monkeypatch, Stage.TEMPERATURE, "mock_b", "faiman", delta=0.10)
    install_mock_model(monkeypatch, Stage.TEMPERATURE, "mock_c", "faiman", delta=0.05)

    overrides = {
        "weather_file": str(REAL_FILE),
        "time_offset": {"value_h": 0.0, "reason": "header states 0.5 h; file day/night content aligns with 0 h"},
        "pipelines": {
            "A": {**BASE_YAML["pipelines"]["A"], "temperature": "faiman"},
            "B": {**BASE_YAML["pipelines"]["A"], "temperature": "mock_b"},
            "C": {**BASE_YAML["pipelines"]["A"], "temperature": "mock_c"},
        },
    }
    run = run_analysis(_write_yaml(tmp_path, overrides))
    output = build_results_dict(run)

    # Phase 1, per pair and stage.
    p1_ab = output["phase1"]["A-B"]
    assert p1_ab["status"] == "ran"
    assert "outcome" in p1_ab
    assert "k" in p1_ab
    for stage_metrics in p1_ab["metrics"]:
        for field in ("rmsd", "nrmsd", "mad", "mbd", "systematic_share"):
            assert field in stage_metrics, f"Phase 1 metrics missing {field!r}: {stage_metrics}"

    # Phase 2, per pair (nRMSD by stage) plus the aggregate fields.
    p2 = output["phase2"]
    assert p2["status"] == "ran"
    for field in ("pair_nrmsd", "mean_nrmsd", "max_nrmsd", "delta"):
        assert field in p2, f"Phase 2 missing {field!r}: {sorted(p2)}"

    # Phase 3.
    p3_ab = output["phase3"]["A-B"]
    assert p3_ab["status"] == "ran"
    for field in ("phi_ab", "phi_ba", "phi_final", "share", "signed_phi", "v_ab", "v_ba", "signed_v"):
        assert field in p3_ab, f"Phase 3 missing {field!r}: {sorted(p3_ab)}"


def _run_ab_outcome3_analysis(tmp_path, monkeypatch, fixed_tau: float | None):
    """Shared setup: A-B reaches outcome 3, A-C/B-C reach outcome 1 -- same
    construction as test_only_one_qualifying_pair_runs_phase2_and_gates_
    phase3_per_pair, reused here for the tau-provenance tests. Works at both
    the live default (0.093) and TEST_TAU=0.10: the mock deltas were sized
    with enough margin (A-B's temp_nrmsd ~0.139, A-C/B-C's ~0.070-0.073) to
    clear or stay under either threshold the same way.
    """
    if fixed_tau is not None:
        _use_fixed_tau(monkeypatch, fixed_tau)
    install_mock_model(monkeypatch, Stage.TEMPERATURE, "mock_b", "faiman", delta=0.10)
    install_mock_model(monkeypatch, Stage.TEMPERATURE, "mock_c", "faiman", delta=0.05)

    overrides = {
        "weather_file": str(REAL_FILE),
        "time_offset": {"value_h": 0.0, "reason": "header states 0.5 h; file day/night content aligns with 0 h"},
        "pipelines": {
            "A": {**BASE_YAML["pipelines"]["A"], "temperature": "faiman"},
            "B": {**BASE_YAML["pipelines"]["A"], "temperature": "mock_b"},
            "C": {**BASE_YAML["pipelines"]["A"], "temperature": "mock_c"},
        },
    }
    return run_analysis(_write_yaml(tmp_path, overrides))


def _tau_values_recorded_for_analysis(analysis_id: str) -> list[float]:
    """Every provenance record linked to this analysis (any execution set),
    reading tau_value straight out of its own document's site_context
    entity -- the actual recorded value, not what the caller expects it to
    be.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT pr.document FROM provenance_records pr "
            "JOIN analysis_records ar ON ar.record_id = pr.id "
            "WHERE ar.analysis_id = %s",
            (analysis_id,),
        )
        rows = cur.fetchall()

    values = []
    for (document,) in rows:
        bundle_name = next(iter(document["bundle"]))
        site_context = document["bundle"][bundle_name]["entity"]["site_context"]
        values.append(float(site_context["tau_value"]["$"]))
    return values


@pytest.mark.parametrize("fixed_tau", [None, 0.10], ids=["live_default", "overridden"])
def test_recorded_tau_equals_phase1_tau(tmp_path, monkeypatch, fixed_tau):
    """Verification property #25, the wiring end to end: every provenance
    record's tau_value must equal the tau the pair's own Phase 1 result
    used -- not just build_site_context()'s own fallback (test_site.py) --
    checked at both the live default and an explicitly overridden tau, since
    the override must reach the early resolve_tau() call in run_analysis()
    the same way it already reaches every per-pair run_phase1() call.
    """
    run = _run_ab_outcome3_analysis(tmp_path, monkeypatch, fixed_tau)
    expected_tau = run.phase1_results[("A", "B")].tau.value

    recorded = _tau_values_recorded_for_analysis(run.analysis_id)
    assert recorded, "expected at least one provenance record for this analysis"
    for value in recorded:
        assert value == pytest.approx(expected_tau)


def test_every_record_in_one_analysis_shares_the_same_tau_value(tmp_path, monkeypatch):
    """Verification property #25, "constant within a run": the ORIGINAL
    pipeline records (A, B, C) and the DERIVED records (Phase 3's
    coalitions) must all carry the identical tau_value -- not merely each
    individually matching some tau, but all matching EACH OTHER.

    Needs a pair with |S| >= 2 to actually produce DERIVED records (a
    |S| = 1 pair, like the temperature-only setup above, needs zero derived
    runs -- both endpoints are already-known results, per Step 0's dedup
    fix). A-B differs at TRANSPOSITION (large delta, crosses tau, so Phase 3
    runs) and TEMPERATURE (small delta, stays under tau, but still counts
    toward S since S is about which MODEL is used, not its nRMSD).
    """
    TEST_TAU = 0.10
    _use_fixed_tau(monkeypatch, TEST_TAU)
    install_mock_model(monkeypatch, Stage.TRANSPOSITION, "mock_transposition", "isotropic", delta=0.30)
    install_mock_temperature_model(monkeypatch, "mock_temperature", "faiman", delta=0.02)

    overrides = {
        "weather_file": str(REAL_FILE),
        "time_offset": {"value_h": 0.0, "reason": "header states 0.5 h; file day/night content aligns with 0 h"},
        "pipelines": {
            "A": {**BASE_YAML["pipelines"]["A"]},
            "B": {
                **BASE_YAML["pipelines"]["A"],
                "transposition": "mock_transposition",
                "temperature": "mock_temperature",
            },
            "C": {**BASE_YAML["pipelines"]["A"]},
        },
    }
    run = run_analysis(_write_yaml(tmp_path, overrides))
    assert run.phase1_results[("A", "B")].outcome != 1
    assert not isinstance(run.phase3_results[("A", "B")], str)

    recorded = _tau_values_recorded_for_analysis(run.analysis_id)
    assert len(recorded) >= 4, "expected ORIGINAL (3) plus at least one DERIVED record"
    assert len(set(recorded)) == 1, f"tau_value differs across records: {sorted(set(recorded))}"
