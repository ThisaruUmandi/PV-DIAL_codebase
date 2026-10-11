from pathlib import Path

import pytest
from psycopg.types.json import Jsonb
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
from pvdials.provenance.recorder import record
from pvdials.provenance.replay import replay
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


def _record_a_real_run() -> str:
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

    shared = SharedInputs(
        weather=weather,
        ctx=ctx,
        geometry=ArrayGeometry(surface_tilt_deg=6.944, surface_azimuth_deg=180.0),
        albedo=resolve_albedo(None, load_defaults()),
        mounting=resolve_mounting(None, None, load_defaults()),
        module=module,
        array_size=ArraySize(10, 2),
        inverter=inverter,
    )
    config = PipelineConfig("A", "erbs", "isotropic", "faiman", "singlediode_cec", "sandia")
    result = run_pipeline(config, shared)
    return record(config, shared, result), result


def test_replay_reproduces_the_recorded_run():
    record_id, _ = _record_a_real_run()

    result = replay(record_id)

    assert result.passed
    assert {s.stage for s in result.stages} == {
        "decomposition",
        "transposition",
        "temperature",
        "dc",
        "ac",
    }
    for stage in result.stages:
        assert stage.hash_matches, f"{stage.stage}: hash mismatch"
        assert stage.values_match, f"{stage.stage}: values mismatch"


def test_replay_catches_a_corrupted_stored_value():
    record_id, result = _record_a_real_run()

    # Corrupt the stored ac payload directly, leaving the document's own
    # recorded content_hash untouched.
    ac_hash, ac_payload = hash_dataframe(result.outputs.ac.outputs)
    ac_payload["p_ac"][0] = 999_999.0
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE stage_output_values SET payload = %s WHERE content_hash = %s",
            (Jsonb(ac_payload), ac_hash),
        )
        conn.commit()

    replayed = replay(record_id)

    by_stage = {s.stage: s for s in replayed.stages}
    assert not replayed.passed
    # Rerunning still reproduces the same result the document originally
    # recorded (the corruption never touched the document) ...
    assert by_stage["ac"].hash_matches
    # ... but the stored payload at that hash no longer matches it.
    assert not by_stage["ac"].values_match
    # Every other stage is untouched and still passes both checks.
    for stage_name in ("decomposition", "transposition", "temperature", "dc"):
        assert by_stage[stage_name].hash_matches
        assert by_stage[stage_name].values_match


def test_replay_raises_for_an_unknown_record_id():
    with pytest.raises(Exception, match="No provenance record"):
        replay("not-a-real-id")
