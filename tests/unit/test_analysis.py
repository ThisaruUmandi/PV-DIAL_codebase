"""End-to-end orchestrator tests (pvdials/analysis.py)."""

from pathlib import Path

import pytest
import yaml

from pvdials.analysis import (
    NOT_RUN_OUTCOME_1,
    AnalysisError,
    parse_analysis_yaml,
    run_analysis,
)
from pvdials.provenance.analyses import load_analysis
from pvdials.provenance.db import get_connection, is_reachable, run_schema
from pvdials.types import Stage
from tests.dla.mock_adapters import install_mock_model, install_mock_temperature_model

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REAL_FILE = Path("/Users/umandi/workfolder/Research/Sandbox/pvlib_test1/tmy_6.944_79.856_2005_2020.csv")

pytestmark = pytest.mark.filterwarnings("ignore::RuntimeWarning")

requires_postgres = pytest.mark.skipif(
    not is_reachable(),
    reason="No local Postgres reachable (DATABASE_URL not set or the service isn't running).",
)
requires_real_file = pytest.mark.skipif(
    not REAL_FILE.exists(), reason=f"Real Colombo file not present at {REAL_FILE}"
)


@pytest.fixture(autouse=True)
def _clean_schema():
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
    import copy

    data = copy.deepcopy(BASE_YAML)
    if overrides:
        data.update(overrides)
    path = tmp_path / "analysis.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")
    return str(path)


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
    directly on the real file): A=real faiman, B=mock+30% (A-B crosses tau,
    temp_nrmsd=0.32), C=mock+15% (A-C=0.20, B-C=0.18, both stay under
    tau=0.234). Phase 2 must run (computed over all three pairs regardless);
    Phase 3 must run for A-B only, reporting NOT_RUN_OUTCOME_1 for A-C/B-C.
    """
    install_mock_model(monkeypatch, Stage.TEMPERATURE, "mock_b", "faiman", delta=0.30)
    install_mock_model(monkeypatch, Stage.TEMPERATURE, "mock_c", "faiman", delta=0.15)

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
