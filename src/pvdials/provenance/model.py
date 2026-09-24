"""The PROV document model (KT §11, Step 7.2). Uses the PROV data model.

Do not claim "conforms to W3C PROV" — that hasn't been validated (N29).

Builds one document (one bundle, named for the execution set) per
run_pipeline() call, recording the configuration, the site context, and the
five stages as a chained lineage: each stage's activity `used` the entity the
previous stage produced, not just five disconnected records.
"""

from __future__ import annotations

import hashlib
import json
import math

import numpy as np
import pandas as pd
from prov.model import ProvDocument

from pvdials.physics.pipeline import PipelineResult, SharedInputs
from pvdials.types import PipelineConfig

# A project-internal namespace. Doesn't need to be dereferenceable, only
# stable — prov requires every identifier to sit under one (checked 24/09).
NAMESPACE = "https://pvdial.local/ns#"


def _to_native(value):
    """Coerce a numpy scalar to a native Python type; pass everything else through.

    Defensive, not fixing a live bug: every adapter already casts explicitly
    before storing into .records (checked against a real run across all five
    stages and every model branch, 24/09). But np.float64 silently serializes
    to the wrong value, and np.int64/np.bool_ crash prov's own JSON encoder
    with RecursionError (checked 24/09) — a future model that forgets the
    cast should fail a test here, not corrupt a provenance record.
    """
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _flatten_records(records: dict) -> dict:
    """Flatten one level of nesting (records['coefficients']['u0'] ->
    'coefficients.u0'), coercing every leaf to a native type.

    prov's add_attributes() rejects a nested dict outright (unhashable,
    checked 24/09). One level is enough: no current adapter nests deeper.
    """
    flat = {}
    for key, value in records.items():
        if isinstance(value, dict):
            for subkey, subvalue in value.items():
                flat[f"{key}.{subkey}"] = _to_native(subvalue)
        else:
            flat[key] = _to_native(value)
    return flat


def hash_dataframe(df: pd.DataFrame) -> tuple[str, dict]:
    """Content hash and JSON-serializable payload for a stage output DataFrame.

    payload: {"index": [...ISO-8601...], <column>: [...values...], ...}.
    NaN -> None before serializing: plain json.dumps accepts NaN (not valid
    JSON), but Postgres's JSONB column rejects it.
    """
    payload: dict = {"index": [ts.isoformat() for ts in df.index]}
    for col in df.columns:
        values = []
        for v in df[col].tolist():
            v = _to_native(v)
            if isinstance(v, float) and math.isnan(v):
                v = None
            values.append(v)
        payload[col] = values

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return content_hash, payload


def build_document(
    config: PipelineConfig, shared: SharedInputs, result: PipelineResult
) -> ProvDocument:
    """Build one PROV document for a completed run_pipeline() call."""
    document = ProvDocument()
    document.set_default_namespace(NAMESPACE)
    bundle = document.bundle("original")  # TODO: name from ExecutionSet once derived/reexec exist
    bundle.set_default_namespace(NAMESPACE)

    user = bundle.agent("user", {"prov:type": "Person"})
    pvdial = bundle.agent("pvdial", {"prov:type": "SoftwareAgent"})
    pvlib_agent = bundle.agent(
        "pvlib",
        {"prov:type": "SoftwareAgent", "version": shared.ctx.settings["pvlib_version"]},
    )

    configuration_attrs = {
        "label": config.label,
        "decomposition_model": config.decomposition_model,
        "transposition_model": config.transposition_model,
        "temperature_model": config.temperature_model,
        "dc_model": config.dc_model,
        "ac_model": config.ac_model,
        "module_library": shared.module.library,
        "module_name": shared.module.name,
        "surface_tilt_deg": shared.geometry.surface_tilt_deg,
        "surface_azimuth_deg": shared.geometry.surface_azimuth_deg,
        "modules_per_string": shared.array_size.modules_per_string,
        "strings_per_inverter": shared.array_size.strings_per_inverter,
        "mounting_geometry": shared.mounting.geometry,
        "mounting_geometry_source": shared.mounting.geometry_source,
        "mounting_construction": shared.mounting.construction,
        "mounting_construction_source": shared.mounting.construction_source,
        "albedo": shared.albedo.value,
        "albedo_source": shared.albedo.source,
    }
    if shared.inverter is not None:
        configuration_attrs["inverter_name"] = shared.inverter.name
        configuration_attrs["inverter_library"] = shared.inverter.library
    if shared.module_height_m is not None:
        configuration_attrs["module_height_m"] = shared.module_height_m
    if shared.array_height is not None:
        configuration_attrs["array_height"] = shared.array_height
    configuration = bundle.entity(
        "configuration", {k: _to_native(v) for k, v in configuration_attrs.items()}
    )
    bundle.wasAttributedTo(configuration, user)

    site_attrs = {
        k: _to_native(v) for k, v in shared.ctx.settings.items() if not isinstance(v, dict)
    }
    site_context = bundle.entity("site_context", site_attrs)
    # site_sources is its own dict (per-field lat/lon/elevation tags) -> flatten
    for field, source in shared.ctx.settings.get("site_sources", {}).items():
        site_context.add_attributes({f"site_sources.{field}": source})
    bundle.wasAttributedTo(site_context, pvdial)

    weather = bundle.entity(
        "weather",
        {
            "rows": len(shared.weather),
            "start": shared.weather.index[0].isoformat(),
            "end": shared.weather.index[-1].isoformat(),
        },
    )
    bundle.wasAttributedTo(weather, user)

    def add_stage(name: str, stage_result, upstream) -> object:
        activity = bundle.activity(f"stage_{name}")
        bundle.wasAssociatedWith(activity, pvdial)
        bundle.wasAssociatedWith(activity, pvlib_agent)
        bundle.used(activity, configuration)
        for entity in upstream:
            bundle.used(activity, entity)

        content_hash, _ = hash_dataframe(stage_result.outputs)
        attrs = {"content_hash": content_hash}
        attrs.update(_flatten_records(stage_result.records))
        output_entity = bundle.entity(name, attrs)
        bundle.wasGeneratedBy(output_entity, activity)
        return output_entity

    decomposition_entity = add_stage("decomposition", result.outputs.decomposition, [weather])
    transposition_entity = add_stage(
        "transposition", result.outputs.transposition, [decomposition_entity]
    )
    temperature_entity = add_stage(
        "temperature", result.outputs.temperature, [transposition_entity]
    )
    dc_entity = add_stage("dc", result.outputs.dc, [temperature_entity, transposition_entity])
    add_stage("ac", result.outputs.ac, [dc_entity])

    return document
