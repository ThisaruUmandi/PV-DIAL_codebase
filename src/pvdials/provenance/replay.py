"""The replay test (KT §11, O2's headline evidence). Step 7.4.

Loads a provenance_records row by id, rebuilds the PipelineConfig and
SharedInputs from the stored document alone (the weather input, hardware
identity, geometry, mounting and site settings — nothing from the calling
process's memory), re-runs run_pipeline() in a fresh process, and compares
every stage output against what was originally stored: a hash pre-check
first (does rerunning still give the document's own recorded content_hash?),
then a full elementwise comparison against the stored payload (does the
stored value still match what the pipeline actually produces?) — not a
replacement for the hash check, a second, independent one.

"Fresh process" is a spawned Python interpreter (multiprocessing, spawn
context), not Neon's branching feature — that isn't available locally. A
real Neon connection could add branch-based isolation later; this already
satisfies "fresh process" literally: no shared state, a full re-import.
"""

from __future__ import annotations

import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

import pandas as pd

from pvdials.data.column_mapper import SiteMetadata, TimeOffset
from pvdials.physics.geometry import Albedo, ArrayGeometry
from pvdials.physics.hardware import (
    ArraySize,
    InverterRecord,
    ModuleRecord,
    load_inverter,
    load_module,
)
from pvdials.physics.mounting import Mounting
from pvdials.physics.pipeline import SharedInputs, run_pipeline
from pvdials.physics.site import build_site_context
from pvdials.provenance.db import get_connection
from pvdials.provenance.model import hash_dataframe, unwrap_value
from pvdials.types import PipelineConfig

_STAGES = ("decomposition", "transposition", "temperature", "dc", "ac")


@dataclass(frozen=True)
class StageComparison:
    stage: str
    hash_matches: bool  # rerunning still gives the document's own recorded content_hash
    values_match: bool  # the stored payload still matches what the pipeline actually produces


@dataclass(frozen=True)
class ReplayResult:
    record_id: str
    stages: tuple[StageComparison, ...]

    @property
    def passed(self) -> bool:
        return all(s.hash_matches and s.values_match for s in self.stages)


def _dataframe_from_payload(payload: dict) -> pd.DataFrame:
    """Inverse of hash_dataframe: rebuild a DataFrame from a stored payload."""
    index = pd.DatetimeIndex([pd.Timestamp(ts) for ts in payload["index"]])
    index.name = "timestamp"
    data = {}
    for col, values in payload.items():
        if col == "index":
            continue
        if col == "timestamp_original":
            data[col] = pd.to_datetime(list(values))
        else:
            data[col] = [float("nan") if v is None else float(v) for v in values]
    return pd.DataFrame(data, index=index)


def _module_record(attrs: dict) -> ModuleRecord:
    return load_module(unwrap_value(attrs["module_library"]), unwrap_value(attrs["module_name"]))


def _inverter_record(attrs: dict) -> InverterRecord | None:
    if "inverter_name" not in attrs:
        return None
    return load_inverter(
        unwrap_value(attrs["inverter_library"]), unwrap_value(attrs["inverter_name"])
    )


def _site_metadata(site_attrs: dict) -> SiteMetadata:
    values, sources = {}, {}
    for field in ("latitude", "longitude", "elevation"):
        if field in site_attrs:
            values[field] = float(unwrap_value(site_attrs[field]))
            sources[field] = unwrap_value(site_attrs.get(f"site_sources.{field}", "unknown"))
    return SiteMetadata(values=values, sources=sources)


def _time_offset(site_attrs: dict) -> TimeOffset:
    return TimeOffset(
        value_h=float(unwrap_value(site_attrs["time_offset_h"])),
        source=unwrap_value(site_attrs["time_offset_source"]),
    )


def _pipeline_config(config_attrs: dict) -> PipelineConfig:
    return PipelineConfig(
        label=unwrap_value(config_attrs["label"]),
        decomposition_model=unwrap_value(config_attrs["decomposition_model"]),
        transposition_model=unwrap_value(config_attrs["transposition_model"]),
        temperature_model=unwrap_value(config_attrs["temperature_model"]),
        dc_model=unwrap_value(config_attrs["dc_model"]),
        ac_model=unwrap_value(config_attrs["ac_model"]),
    )


def _shared_inputs(bundle: dict, cur) -> SharedInputs:
    config_attrs = bundle["entity"]["configuration"]
    site_attrs = bundle["entity"]["site_context"]
    weather_attrs = bundle["entity"]["weather"]

    weather_hash = unwrap_value(weather_attrs["content_hash"])
    cur.execute("SELECT payload FROM stage_output_values WHERE content_hash = %s", (weather_hash,))
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"Weather payload for hash {weather_hash!r} not found; can't replay.")
    weather = _dataframe_from_payload(row[0])

    ctx = build_site_context(weather, _site_metadata(site_attrs), _time_offset(site_attrs))

    return SharedInputs(
        weather=weather,
        ctx=ctx,
        geometry=ArrayGeometry(
            surface_tilt_deg=float(unwrap_value(config_attrs["surface_tilt_deg"])),
            surface_azimuth_deg=float(unwrap_value(config_attrs["surface_azimuth_deg"])),
        ),
        albedo=Albedo(
            value=float(unwrap_value(config_attrs["albedo"])),
            source=unwrap_value(config_attrs["albedo_source"]),
        ),
        mounting=Mounting(
            geometry=unwrap_value(config_attrs["mounting_geometry"]),
            geometry_source=unwrap_value(config_attrs["mounting_geometry_source"]),
            construction=unwrap_value(config_attrs["mounting_construction"]),
            construction_source=unwrap_value(config_attrs["mounting_construction_source"]),
        ),
        module=_module_record(config_attrs),
        array_size=ArraySize(
            modules_per_string=int(unwrap_value(config_attrs["modules_per_string"])),
            strings_per_inverter=int(unwrap_value(config_attrs["strings_per_inverter"])),
        ),
        inverter=_inverter_record(config_attrs),
        module_height_m=(
            float(unwrap_value(config_attrs["module_height_m"]))
            if "module_height_m" in config_attrs
            else None
        ),
        array_height=(
            int(unwrap_value(config_attrs["array_height"]))
            if "array_height" in config_attrs
            else None
        ),
    )


def _replay_worker(record_id: str, database_url: str | None) -> ReplayResult:
    """Runs in a fresh (spawned) process: no state shared with the caller."""
    with get_connection(database_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT document FROM provenance_records WHERE id = %s", (record_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"No provenance record with id {record_id!r}.")
        document = row[0]
        bundle_name = next(iter(document["bundle"]))
        bundle = document["bundle"][bundle_name]

        config = _pipeline_config(bundle["entity"]["configuration"])
        shared = _shared_inputs(bundle, cur)

    result = run_pipeline(config, shared)

    stages = []
    with get_connection(database_url) as conn, conn.cursor() as cur:
        for stage_name in _STAGES:
            recorded_hash = unwrap_value(bundle["entity"][stage_name]["content_hash"])
            fresh_hash, fresh_payload = hash_dataframe(getattr(result.outputs, stage_name).outputs)
            hash_matches = fresh_hash == recorded_hash

            cur.execute(
                "SELECT payload FROM stage_output_values WHERE content_hash = %s", (recorded_hash,)
            )
            stored = cur.fetchone()
            values_match = stored is not None and stored[0] == fresh_payload

            stages.append(StageComparison(stage_name, hash_matches, values_match))

    return ReplayResult(record_id=record_id, stages=tuple(stages))


def replay(record_id: str, database_url: str | None = None) -> ReplayResult:
    """Reload record_id in a fresh process, rebuild the configuration, rerun,
    and compare every stage output against what was originally stored.
    """
    context = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=1, mp_context=context) as executor:
        future = executor.submit(_replay_worker, record_id, database_url)
        return future.result()
