"""Storage layer for the interface (S1): run_info, new inputs, summary list,
duplicate, stage series from provenance, old-row compatibility, and
re-execution idempotency. Database tests run on pvdials_test only
(tests/conftest.py forces it; _clean_schema refuses pvdials_dev)."""

import copy
import hashlib
import json
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd
import pytest
import yaml

from experiments.evaluation.db_safety import guard_not_dev_database, resolve_current_database_url
from pvdials.analysis import run_analysis
from pvdials.data.upload import file_sha256, store_upload
from pvdials.provenance.analyses import (
    NOT_RECORDED,
    duplicate_analysis,
    linked_records,
    list_analyses_summary,
    load_analysis,
    load_stage_series,
    recorded,
    save_analysis,
)
from pvdials.provenance.db import get_connection, is_reachable, run_schema
from tests.storage_helpers import rerun_analysis

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SAMPLE_FILE = FIXTURES / "sample_pvgis_tmy.csv"
COLOMBO_ROW = FIXTURES / "colombo_thesis_run_row.json"

pytestmark = [
    pytest.mark.filterwarnings("ignore::RuntimeWarning"),
    pytest.mark.skipif(not is_reachable(), reason="No local Postgres reachable."),
]

YAML = {
    "name": "storage test",
    "weather_file": str(SAMPLE_FILE),
    "time_offset": {"value_h": 0.0, "reason": "file content aligns with 0 h"},
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


def _yaml_path(tmp_path) -> str:
    path = tmp_path / "analysis.yaml"
    path.write_text(yaml.dump(copy.deepcopy(YAML)), encoding="utf-8")
    return str(path)


def _counts() -> dict[str, int]:
    out = {}
    with get_connection() as conn, conn.cursor() as cur:
        for table in ("analyses", "analysis_records", "provenance_records", "stage_output_values"):
            cur.execute(f"SELECT count(*) FROM {table}")
            out[table] = cur.fetchone()[0]
    return out


def _linked_record_ids(analysis_id: str) -> set[str]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT record_id FROM analysis_records WHERE analysis_id = %s", (analysis_id,))
        return {row[0] for row in cur.fetchall()}


# --- schema ----------------------------------------------------------------------


def test_run_schema_adds_run_info_and_is_idempotent():
    with get_connection() as conn:
        run_schema(conn)
        run_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = 'analyses' AND column_name = 'run_info'"
            )
            assert cur.fetchone()[0] == 1


def test_run_info_round_trips():
    save_analysis("a1", "n", "done", {"x": 1}, run_info={"started_at": "t", "checks": {"A": {}}})
    row = load_analysis("a1")
    assert row["run_info"] == {"started_at": "t", "checks": {"A": {}}}


# --- new inputs and run_info written by the shared save path ----------------------


def test_run_analysis_records_tau_weather_hash_and_run_info(tmp_path):
    run = run_analysis(_yaml_path(tmp_path))
    row = load_analysis(run.analysis_id)

    assert row["inputs"]["tau"] == {"value": 0.093, "source": "default"}
    assert row["inputs"]["weather"] == {
        "name": "sample_pvgis_tmy.csv",
        "sha256": hashlib.sha256(SAMPLE_FILE.read_bytes()).hexdigest(),
        "header_offset_h": 0.5,
    }
    info = row["run_info"]
    assert row["status"] == "done"
    assert info["pvlib_version"]
    assert info["started_at"] and info["finished_at"] and info["duration_s"] >= 0
    assert set(info["checks"]) == {"A", "B", "C"}
    assert all("passed" in c for per in info["checks"].values() for c in per.values())
    assert [c["label"] for c in info["offset_report"]] == ["header", "hour_start", "hour_centre"]
    assert info["offset_report"][0]["value_h"] == 0.5  # the file's own header, not the YAML's 0 h


def test_file_sha256_and_store_upload_are_content_addressed(tmp_path):
    assert file_sha256(SAMPLE_FILE) == hashlib.sha256(SAMPLE_FILE.read_bytes()).hexdigest()
    content = SAMPLE_FILE.read_bytes()
    path1, sha1 = store_upload(content, root=tmp_path)
    path2, sha2 = store_upload(content, root=tmp_path)
    assert path1 == path2 == tmp_path / f"{sha1}.csv" and sha1 == sha2
    assert path1.read_bytes() == content
    assert len(list(tmp_path.iterdir())) == 1


# --- old rows must still load -------------------------------------------------------


def _save_colombo_row() -> dict:
    row = json.loads(COLOMBO_ROW.read_text(encoding="utf-8"))
    save_analysis(
        row["id"], row["name"], row["status"], row["inputs"], row["phase1"], row["phase2"],
        row["phase3"], row["reexec"], row["pipelines"],
    )
    return row


def test_colombo_thesis_run_shape_loads_and_reports_missing_parts():
    row = _save_colombo_row()
    assert "tau" not in row["inputs"] and "weather" not in row["inputs"]

    loaded = load_analysis(row["id"])
    assert loaded["run_info"] is None
    assert recorded(loaded, "inputs", "tau", "value") == NOT_RECORDED
    assert recorded(loaded, "inputs", "weather", "sha256") == NOT_RECORDED
    assert recorded(loaded, "run_info", "checks") == NOT_RECORDED
    assert recorded(loaded, "run_info", "started_at") == NOT_RECORDED
    assert NOT_RECORDED == "not recorded for this analysis"
    # what IS there still reads normally
    assert recorded(loaded, "inputs", "site", "tilt_deg") == 6.944
    assert recorded(loaded, "phase1", "A-B", "outcome") == 3


def test_colombo_thesis_run_shape_in_the_summary_list():
    row = _save_colombo_row()
    (summary,) = list_analyses_summary()
    assert summary["id"] == row["id"]
    assert summary["weather_file"] == "tmy_6.944_79.856_2005_2020.csv"
    assert summary["phase1_outcomes"] == {"A-B": 3, "A-C": 3, "B-C": 1}


# --- summary list: filters and ordering -------------------------------------------


def test_summary_list_filters_and_orders_by_date_or_name_only():
    save_analysis("1", "beta", "done", {"weather_file": "x/one.csv"})
    save_analysis("2", "Alpha", "load_done", {"weather_file": "x/two.csv"})
    save_analysis("3", "gamma", "done", {"weather_file": "x/three.csv"})

    assert [s["id"] for s in list_analyses_summary(order="newest")] == ["3", "2", "1"]
    assert [s["id"] for s in list_analyses_summary(order="oldest")] == ["1", "2", "3"]
    assert [s["name"] for s in list_analyses_summary(order="name")] == ["Alpha", "beta", "gamma"]
    assert {s["id"] for s in list_analyses_summary(status="complete")} == {"1", "3"}
    assert {s["id"] for s in list_analyses_summary(status="in_progress")} == {"2"}
    assert {s["id"] for s in list_analyses_summary(search="TWO")} == {"2"}
    assert {s["id"] for s in list_analyses_summary(search="gam")} == {"3"}
    with pytest.raises(ValueError):
        list_analyses_summary(order="disagreement")


# --- duplicate ---------------------------------------------------------------------


def test_duplicate_copies_inputs_only_and_leaves_the_original_untouched():
    row = _save_colombo_row()
    before = load_analysis(row["id"])

    new_id = duplicate_analysis(row["id"])
    copy_row = load_analysis(new_id)

    assert new_id != row["id"]
    assert copy_row["inputs"] == row["inputs"]
    assert copy_row["status"] == "started"
    for part in ("phase1", "phase2", "phase3", "reexec", "pipelines", "run_info"):
        assert copy_row[part] is None
    assert _linked_record_ids(new_id) == set()
    after = load_analysis(row["id"])
    assert {k: after[k] for k in after if k != "updated_at"} == {k: before[k] for k in before if k != "updated_at"}
    with pytest.raises(ValueError):
        duplicate_analysis("does-not-exist")


# --- stage series from provenance ----------------------------------------------------


def test_stage_series_from_provenance_equal_the_live_series(tmp_path):
    run = run_analysis(_yaml_path(tmp_path))
    for label in ("A", "B", "C"):
        stored = load_stage_series(run.analysis_id, label)
        assert stored is not None and list(stored) == ["decomposition", "transposition", "temperature", "dc", "ac"]
        for stage, frame in stored.items():
            live = getattr(run.pipelines.results[label].outputs, stage).outputs
            # JSONB does not keep key order, so columns come back sorted by name; compare by name.
            assert set(frame.columns) == set(live.columns)
            assert (frame.index == live.index).all()
            pd.testing.assert_frame_equal(
                frame[list(live.columns)], live, check_exact=True, check_freq=False, check_names=False
            )
    assert load_stage_series(run.analysis_id, "Z") is None
    assert load_stage_series("no-such-analysis", "A") is None


# --- idempotency of re-execution -------------------------------------------------


def test_reexecuting_an_existing_analysis_in_a_fresh_process_adds_nothing(tmp_path):
    yaml_path = _yaml_path(tmp_path)
    first = run_analysis(yaml_path)
    ids_before = _linked_record_ids(first.analysis_id)
    counts_before = _counts()
    created_before = load_analysis(first.analysis_id)["created_at"]
    assert len(ids_before) >= 3  # at least the three ORIGINAL records

    with ProcessPoolExecutor(max_workers=1, mp_context=mp.get_context("spawn")) as executor:
        again_id = executor.submit(rerun_analysis, yaml_path, first.analysis_id).result()

    assert again_id == first.analysis_id
    assert _linked_record_ids(first.analysis_id) == ids_before
    assert _counts() == counts_before
    row = load_analysis(first.analysis_id)
    assert row["created_at"] == created_before and row["status"] == "done"


# --- linked provenance records, read-only ------------------------------------------


def test_linked_records_returns_every_linked_document_unchanged_in_a_fixed_order_and_writes_nothing(tmp_path):
    run = run_analysis(_yaml_path(tmp_path))
    linked = _linked_record_ids(run.analysis_id)
    counts_before = _counts()
    records = linked_records(run.analysis_id)
    assert {r["record_id"] for r in records} == linked and len(records) == len(linked) >= 3  # no more, no fewer
    assert [r["execution_set"] for r in records] == sorted(
        (r["execution_set"] for r in records), key=("original", "derived", "reexec").index
    )  # ORIGINAL, then DERIVED, then REEXEC
    originals = [r for r in records if r["execution_set"] == "original"]
    assert [r["config_label"] for r in originals] == ["A", "B", "C"]
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, document FROM provenance_records")
        stored = dict(cur.fetchall())
    for record in records:
        assert record["document"] == stored[record["record_id"]]  # the document as stored, unchanged
        assert set(record) == {"record_id", "execution_set", "config_label", "document"}
    assert _counts() == counts_before and linked_records("no-such-analysis") == []
