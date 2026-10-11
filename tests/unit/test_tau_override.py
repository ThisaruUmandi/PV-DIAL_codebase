"""A tau typed by the user reaches every place tau is used (KT E.1, the 29/09 known limit).

One run resolves tau once and passes the same Tau to: the SiteContext (so every provenance
record -- ORIGINAL, DERIVED and REEXEC -- carries it), every pair's Phase 1, and the
re-execution session's own Phase 1. Untouched, everything carries 0.093 and "default".

The end-to-end test uses the thesis weather file with mock models (as test_analysis.py does)
and is marked slow; the validation tests are fast.
"""

import copy
import math
from pathlib import Path

import pytest
import yaml

from experiments.evaluation.db_safety import guard_not_dev_database, resolve_current_database_url
from pvdials.analysis import (
    AnalysisError,
    parse_analysis_yaml,
    run_analysis,
    step_hardware,
)
from pvdials.config import load_defaults
from pvdials.dla.metrics import resolve_tau, resolve_user_tau
from pvdials.guided_reexecution import O4Session
from pvdials.provenance.analyses import load_analysis
from pvdials.provenance.db import get_connection, is_reachable, run_schema
from pvdials.types import Stage
from tests.dla.mock_adapters import install_mock_model, install_mock_temperature_model

REAL_FILE = Path("data/weather/tmy_6.944_79.856_2005_2020.csv")
DEFAULT_TAU = 0.093

requires_postgres = pytest.mark.skipif(not is_reachable(), reason="no Postgres reachable")
requires_real_file = pytest.mark.skipif(not REAL_FILE.exists(), reason="thesis weather file not present")


@pytest.fixture(autouse=True)
def _clean_schema():
    guard_not_dev_database(resolve_current_database_url(), "tau override tests")
    with get_connection() as conn:
        run_schema(conn)
        with conn.cursor() as cur:
            for table in ("analysis_records", "analyses", "stage_output_values", "provenance_records"):
                cur.execute(f"DELETE FROM {table}")
        conn.commit()
    yield


# --- validation: tau > 0, and only that ---------------------------------------------------------


@pytest.mark.parametrize("bad", [0, 0.0, -0.1, -5, math.nan, math.inf, -math.inf, True])
def test_a_user_tau_must_be_a_finite_number_above_zero(bad):
    with pytest.raises(ValueError, match="greater than 0"):
        resolve_user_tau(bad, load_defaults())


@pytest.mark.parametrize("good", [1e-9, 0.01, 0.15, 0.234, 1, 25.0])
def test_any_positive_tau_is_accepted_without_comment(good):
    tau = resolve_user_tau(good, load_defaults())
    assert tau.value == good and tau.source == "user_entered"


def test_no_tau_gives_the_default_and_the_default_tag():
    tau = resolve_user_tau(None, load_defaults())
    assert (tau.value, tau.source) == (DEFAULT_TAU, "default")
    assert tau == resolve_tau(None, load_defaults())  # the unchanged function agrees


def test_resolve_tau_itself_is_unchanged_for_existing_callers():
    assert resolve_tau(0.0, load_defaults()).value == 0.0  # the evaluation sweeps rely on this


@requires_postgres
def test_run_analysis_refuses_a_non_positive_tau_before_doing_any_work(tmp_path):
    from tests.unit.test_analysis import _write_yaml

    with pytest.raises(AnalysisError, match="greater than 0"):
        run_analysis(_write_yaml(tmp_path), tau_value=0)


# --- end to end: every record, every pair result, the re-execution Phase 1 -------------------------


def _documents(analysis_id: str):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT pr.execution_set, pr.document FROM provenance_records pr "
            "JOIN analysis_records ar ON ar.record_id = pr.id WHERE ar.analysis_id = %s",
            (analysis_id,),
        )
        return cur.fetchall()


def _site_tau(document) -> tuple[float, str]:
    entity = document["bundle"][next(iter(document["bundle"]))]["entity"]["site_context"]
    return float(entity["tau_value"]["$"]), str(entity["tau_source"])


def _yaml_with_two_differing_stages(tmp_path) -> str:
    """A differs from B at transposition (large) and temperature (small): |S| = 2, so Phase 3
    makes DERIVED records. C = A. Re-execution asks for A-B with a transposition candidate."""
    from tests.unit.test_analysis import BASE_YAML

    data = copy.deepcopy(BASE_YAML)
    base = BASE_YAML["pipelines"]["A"]
    data.update(
        {
            "weather_file": str(REAL_FILE),
            "time_offset": {"value_h": 0.0, "reason": "file day/night content aligns with 0 h"},
            "pipelines": {
                "A": {**base},
                "B": {**base, "transposition": "mock_transposition", "temperature": "mock_temperature"},
                "C": {**base},
            },
            "reexecution": {"pair": "A-B", "anchor": "A", "candidate": "haydavies"},
        }
    )
    path = tmp_path / "analysis.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")
    return str(path)


@pytest.mark.slow
@requires_postgres
@requires_real_file
@pytest.mark.parametrize(
    "tau_value, expected",
    [(None, (DEFAULT_TAU, "default")), (0.15, (0.15, "user_entered")), (0.01, (0.01, "user_entered"))],
    ids=["untouched", "user_0.15", "user_0.01"],
)
def test_tau_reaches_every_record_every_pair_and_the_reexecution_phase1(tmp_path, monkeypatch, tau_value, expected):
    install_mock_model(monkeypatch, Stage.TRANSPOSITION, "mock_transposition", "isotropic", delta=0.60)
    install_mock_temperature_model(monkeypatch, "mock_temperature", "faiman", delta=0.5)

    yaml_path = _yaml_with_two_differing_stages(tmp_path)
    run = run_analysis(yaml_path, tau_value=tau_value)
    value, source = expected

    # 1. every pair result
    for pair, result in run.phase1_results.items():
        assert not isinstance(result, str), pair
        assert (result.tau.value, result.tau.source) == (value, source), pair

    # 2. every provenance record of the analysis: ORIGINAL, DERIVED and REEXEC
    documents = _documents(run.analysis_id)
    by_set: dict[str, list] = {}
    for execution_set, document in documents:
        by_set.setdefault(execution_set, []).append(_site_tau(document))
    assert set(by_set) == {"original", "derived", "reexec"}, set(by_set)
    for execution_set, taus in by_set.items():
        assert taus and all(t == (value, source) for t in taus), (execution_set, taus)

    # 3. what was saved
    saved = load_analysis(run.analysis_id)
    assert (saved["inputs"]["tau"]["value"], saved["inputs"]["tau"]["source"]) == (value, source)
    for pair_json in saved["phase1"].values():
        assert (pair_json["tau"]["value"], pair_json["tau"]["source"]) == (value, source)

    # 4. the re-execution session's own Phase 1 (propose/retry), built the way the
    #    orchestrator builds it: handed the run's Tau, and also with the bare value.
    config = run.pipelines.configs
    defaults = load_defaults()
    hardware = step_hardware(run.load_result, run.site_result, parse_analysis_yaml(yaml_path), defaults)
    phase1_ab = run.phase1_results[("A", "B")]
    kwargs = {
        "pair": ("A", "B"), "anchor_config": config["A"], "anchor_result": run.pipelines.results["A"],
        "other_config": config["B"], "other_result": run.pipelines.results["B"], "stage": phase1_ab.k,
        "shared_cec": hardware.shared_cec, "shared_adr": hardware.shared_adr,
        "cec_inverters": hardware.cec_inverters, "adr_inverters": hardware.adr_inverters,
        "daylight": run.site_result.ctx.daylight, "defaults": defaults,
    }
    with_tau_object = O4Session(**kwargs, tau=phase1_ab.tau).propose("haydavies")
    assert (with_tau_object.phase1.tau.value, with_tau_object.phase1.tau.source) == (value, source)
    with_value = O4Session(**kwargs, tau_value=tau_value).propose("haydavies")
    assert (with_value.phase1.tau.value, with_value.phase1.tau.source) == (value, source)
    # the attempt's own provenance record carries the same tau as the run's
    new_taus = {
        _site_tau(document)
        for execution_set, document in _documents_all()
        if execution_set == "reexec"
    }
    assert new_taus == {(value, source)}


def _documents_all():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT execution_set, document FROM provenance_records")
        return cur.fetchall()

