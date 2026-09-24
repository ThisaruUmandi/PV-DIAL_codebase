import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
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
from pvdials.provenance.model import NAMESPACE, _to_native, build_document, hash_dataframe
from pvdials.types import PipelineConfig

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

pytestmark = pytest.mark.filterwarnings("ignore::RuntimeWarning")


def _value(attr):
    """Unwrap PROV-JSON's typed-literal form ({"$": ..., "type": "xsd:..."})
    for anything non-string — the spec's own convention, not a model.py quirk.
    """
    return attr["$"] if isinstance(attr, dict) and "$" in attr else attr


def _real_run():
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
    return config, shared, result


def test_document_has_the_three_agents():
    config, shared, result = _real_run()
    document = build_document(config, shared, result)

    parsed = json.loads(document.serialize(format="json"))
    agents = parsed["bundle"]["original"]["agent"]

    assert set(agents) == {"user", "pvdial", "pvlib"}
    assert agents["pvlib"]["version"] == "0.15.2"


def test_lineage_chain_resolves_end_to_end():
    config, shared, result = _real_run()
    document = build_document(config, shared, result)

    parsed = json.loads(document.serialize(format="json"))["bundle"]["original"]
    used_by = {}
    for rel in parsed["used"].values():
        used_by.setdefault(rel["prov:activity"], []).append(rel["prov:entity"])

    assert "configuration" in used_by["stage_decomposition"]
    assert "weather" in used_by["stage_decomposition"]
    assert "decomposition" in used_by["stage_transposition"]
    assert "transposition" in used_by["stage_temperature"]
    assert "temperature" in used_by["stage_dc"]
    assert "transposition" in used_by["stage_dc"]  # dc also uses transposition directly
    assert "dc" in used_by["stage_ac"]


def test_configuration_entity_carries_source_tags_not_just_values():
    config, shared, result = _real_run()
    document = build_document(config, shared, result)

    parsed = json.loads(document.serialize(format="json"))["bundle"]["original"]
    configuration = parsed["entity"]["configuration"]

    assert configuration["mounting_geometry_source"] == "default"
    assert configuration["mounting_construction_source"] == "default"
    assert configuration["albedo_source"] == "default"


def test_site_context_entity_carries_flattened_site_sources():
    config, shared, result = _real_run()
    document = build_document(config, shared, result)

    parsed = json.loads(document.serialize(format="json"))["bundle"]["original"]
    site_context = parsed["entity"]["site_context"]

    assert site_context["site_sources.latitude"] == "From CSV"
    assert site_context["pressure_source"] == "file"


def test_stage_entities_carry_their_records_flattened_and_hashed():
    config, shared, result = _real_run()
    document = build_document(config, shared, result)

    parsed = json.loads(document.serialize(format="json"))["bundle"]["original"]
    entities = parsed["entity"]

    assert "content_hash" in entities["decomposition"]
    assert int(_value(entities["decomposition"]["dhi_clipped_count"])) == 0
    assert "content_hash" in entities["temperature"]
    assert float(_value(entities["temperature"]["coefficients.u0"])) == pytest.approx(25.0)
    # a nested .records dict, flattened one level
    assert "diode_params.alpha_sc" in entities["dc"]


def test_document_serializes_to_valid_json_and_provn():
    config, shared, result = _real_run()
    document = build_document(config, shared, result)

    as_json = document.serialize(format="json")
    parsed = json.loads(as_json)  # raises if not valid JSON
    assert parsed["prefix"]["default"] == NAMESPACE

    as_provn = document.serialize(format="provn")
    assert as_provn.startswith("document")
    assert as_provn.strip().endswith("endDocument")


def test_hash_dataframe_is_deterministic_and_sensitive_to_changes():
    df = pd.DataFrame(
        {"dni": [1.0, 2.0], "dhi": [0.1, 0.2]},
        index=pd.date_range("2023-01-01", periods=2, freq="h", tz="UTC"),
    )
    hash_a, _ = hash_dataframe(df)
    hash_b, _ = hash_dataframe(df.copy())

    changed = df.copy()
    changed.loc[changed.index[0], "dni"] = 999.0
    hash_c, _ = hash_dataframe(changed)

    assert hash_a == hash_b
    assert hash_a != hash_c


def test_hash_dataframe_converts_nan_to_none_and_stays_valid_json():
    df = pd.DataFrame(
        {"dni": [1.0, float("nan")]},
        index=pd.date_range("2023-01-01", periods=2, freq="h", tz="UTC"),
    )

    _, payload = hash_dataframe(df)

    assert payload["dni"][1] is None
    round_tripped = json.loads(json.dumps(payload))  # raises if payload wasn't valid JSON
    assert round_tripped["dni"][1] is None


def test_to_native_coerces_numpy_scalars():
    assert isinstance(_to_native(np.float64(1.5)), float)
    assert isinstance(_to_native(np.int64(3)), int)
    assert isinstance(_to_native(np.bool_(True)), bool)
    assert _to_native("already native") == "already native"


def test_document_still_serializes_with_a_coerced_numpy_value_in_records():
    # Today's adapters never leave a numpy value in .records (confirmed 24/09),
    # but this pins the defensive path so a future one can't silently break it.
    config, shared, result = _real_run()
    result.outputs.decomposition.records["probe"] = np.float64(2.5)

    document = build_document(config, shared, result)

    parsed = json.loads(document.serialize(format="json"))["bundle"]["original"]
    probe = float(_value(parsed["entity"]["decomposition"]["probe"]))
    assert probe == pytest.approx(2.5)
    assert not math.isnan(probe)
