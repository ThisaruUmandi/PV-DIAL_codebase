from pathlib import Path

import pytest
from pvlib import pvsystem

from pvdials.config import load_defaults
from pvdials.data.column_mapper import detect_columns, detect_site_metadata, detect_time_offset
from pvdials.data.preprocess import preprocess
from pvdials.data.upload import load_uploaded_csv
from pvdials.physics.geometry import ArrayGeometry, resolve_albedo
from pvdials.physics.hardware import CEC, CEC_INVERTER, ArraySize, InverterRecord, ModuleRecord
from pvdials.physics.mounting import resolve_mounting
from pvdials.physics.pipeline import SharedInputs, run_pipeline
from pvdials.physics.site import build_site_context
from pvdials.provenance.db import get_connection, is_reachable, run_schema
from pvdials.provenance.model import hash_dataframe
from pvdials.provenance.recorder import EXECUTION_SET, record
from pvdials.types import PipelineConfig

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

pytestmark = [
    pytest.mark.filterwarnings("ignore::RuntimeWarning"),
    pytest.mark.skipif(
        not is_reachable(),
        reason="No local Postgres reachable (DATABASE_URL not set or the service isn't running).",
    ),
]


@pytest.fixture(autouse=True)
def _clean_schema():
    with get_connection() as conn:
        run_schema(conn)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM stage_output_values")
            cur.execute("DELETE FROM provenance_records")
        conn.commit()
    yield


def _shared():
    uploaded = load_uploaded_csv(FIXTURES / "sample_pvgis_tmy.csv")
    weather = preprocess(uploaded.table, detect_columns(uploaded.table), canonical_year=2023).df
    site = detect_site_metadata(uploaded.preamble, uploaded.table)
    ctx = build_site_context(weather, site, detect_time_offset(uploaded.preamble))

    cec_modules = pvsystem.retrieve_sam(CEC)
    module = ModuleRecord(
        CEC, "Canadian_Solar_Inc__CS6K_300MS", cec_modules["Canadian_Solar_Inc__CS6K_300MS"]
    )
    cec_inverters = pvsystem.retrieve_sam(CEC_INVERTER)
    inv_name = "ABB__PVI_6000_OUTD_S_US_A__208V_"
    inverter = InverterRecord(CEC_INVERTER, inv_name, cec_inverters[inv_name])

    return SharedInputs(
        weather=weather,
        ctx=ctx,
        geometry=ArrayGeometry(surface_tilt_deg=6.944, surface_azimuth_deg=180.0),
        albedo=resolve_albedo(None, load_defaults()),
        mounting=resolve_mounting(None, None, load_defaults()),
        module=module,
        array_size=ArraySize(10, 2),
        inverter=inverter,
    )


def _count(query, params=()):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchone()[0]


def test_two_configs_sharing_an_upstream_stage_dedup_that_value():
    shared = _shared()
    config_a = PipelineConfig("A", "erbs", "isotropic", "faiman", "singlediode_cec", "sandia")
    config_b = PipelineConfig("B", "erbs", "isotropic", "faiman", "singlediode_desoto", "sandia")
    result_a = run_pipeline(config_a, shared)
    result_b = run_pipeline(config_b, shared)

    record(config_a, shared, result_a)
    record(config_b, shared, result_b)

    # Same decomposition model -> the same decomposition output -> the same hash
    hash_a, _ = hash_dataframe(result_a.outputs.decomposition.outputs)
    hash_b, _ = hash_dataframe(result_b.outputs.decomposition.outputs)
    assert hash_a == hash_b

    assert _count(
        "SELECT count(*) FROM stage_output_values WHERE content_hash = %s", (hash_a,)
    ) == 1
    # 2 configs x 5 stages = 10 slots, but decomposition/transposition/temperature
    # are shared (3 dedup'd) and dc/ac differ (2 unique each) -> 3 + 2 + 2 = 7,
    # plus the weather input itself (also shared, also dedup'd) -> 8
    assert _count("SELECT count(*) FROM stage_output_values") == 8
    assert _count("SELECT count(*) FROM provenance_records") == 2


def test_recording_the_same_config_twice_is_idempotent():
    shared = _shared()
    config = PipelineConfig("A", "erbs", "isotropic", "faiman", "singlediode_cec", "sandia")
    result = run_pipeline(config, shared)

    first_id = record(config, shared, result)
    second_id = record(config, shared, result)

    assert first_id == second_id
    assert _count("SELECT count(*) FROM provenance_records WHERE id = %s", (first_id,)) == 1


def test_recorded_document_round_trips_from_postgres():
    shared = _shared()
    config = PipelineConfig("A", "erbs", "isotropic", "faiman", "singlediode_cec", "sandia")
    result = run_pipeline(config, shared)

    record_id = record(config, shared, result)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT execution_set, config_label, document FROM provenance_records WHERE id = %s",
            (record_id,),
        )
        row = cur.fetchone()

    assert row[0] == EXECUTION_SET
    assert row[1] == "A"
    assert row[2]["bundle"][EXECUTION_SET]["entity"]["configuration"]["label"] == "A"


def test_stage_output_payload_round_trips_from_postgres():
    shared = _shared()
    config = PipelineConfig("A", "erbs", "isotropic", "faiman", "singlediode_cec", "sandia")
    result = run_pipeline(config, shared)
    record(config, shared, result)

    content_hash, expected_payload = hash_dataframe(result.outputs.ac.outputs)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT payload FROM stage_output_values WHERE content_hash = %s", (content_hash,)
        )
        row = cur.fetchone()

    assert row[0] == expected_payload


def test_weather_input_is_stored_and_recoverable_by_its_own_hash():
    # 7.4 (replay) needs to rebuild SharedInputs from the record alone, in a
    # fresh process, so the weather input must be recoverable too, not just
    # described by rows/start/end.
    shared = _shared()
    config = PipelineConfig("A", "erbs", "isotropic", "faiman", "singlediode_cec", "sandia")
    result = run_pipeline(config, shared)
    record(config, shared, result)

    weather_hash, expected_payload = hash_dataframe(shared.weather)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT payload FROM stage_output_values WHERE content_hash = %s", (weather_hash,)
        )
        row = cur.fetchone()

    assert row is not None
    assert row[0] == expected_payload
