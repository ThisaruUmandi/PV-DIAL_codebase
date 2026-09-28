"""Pool scan (28/09): run every pool-valid chain (2,058, same fixed hardware
as tau_calibration/) on the real Colombo file and check every stage's every
output column for non-finite values.

Prompted by the 24-row p_dc NaN found in pipeline C (dirint/perez/ross/
singlediode_cec): that one only broke DC because of what perez fed it, and
the failure could in principle depend on any model combination, not just
that one -- this checks the whole real pool, not a single-stage sweep.

Not shipped code -- a diagnostic script, same spirit as experiments/tau_calibration/.

Run: python3 experiments/pool_scan.py
"""

from __future__ import annotations

import itertools
import time
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

from pvlib import pvsystem

from pvdials.config import load_defaults
from pvdials.data.column_mapper import (
    TAG_USER_ENTERED,
    TimeOffset,
    detect_columns,
    detect_site_metadata,
)
from pvdials.data.preprocess import preprocess
from pvdials.data.upload import load_uploaded_csv
from pvdials.data.validate import validate_all_finite
from pvdials.physics.geometry import ArrayGeometry, resolve_albedo
from pvdials.physics.hardware import (
    ADR_INVERTER,
    CEC,
    CEC_INVERTER,
    InverterRecord,
    load_module,
    resolve_array_size,
)
from pvdials.physics.mounting import resolve_mounting
from pvdials.physics.pipeline import SharedInputs, run_pipeline
from pvdials.physics.registry import (
    stage1_pool_view,
    stage2_pool_view,
    stage3_pool_view,
    stage4_pool_view,
    stage5_pool_view,
)
from pvdials.physics.shared_inputs import shared_inputs_for
from pvdials.physics.site import build_site_context
from pvdials.types import PipelineConfig

REAL_FILE = Path("data/weather/tmy_6.939_79.854_2005_2023.csv")
MODULE_NAME = "Canadian_Solar_Inc__CS6K_300MS"
INVERTER_NAME = "ABB__PVI_6000_OUTD_S_US_A__208V_"


def build_configs(module, mounting) -> list[PipelineConfig]:
    cec_inverters = pvsystem.retrieve_sam(CEC_INVERTER)
    adr_inverters = pvsystem.retrieve_sam(ADR_INVERTER)

    stage1 = [c.name for c in stage1_pool_view() if c.selectable]
    stage2 = [c.name for c in stage2_pool_view() if c.selectable]
    stage3 = [c.name for c in stage3_pool_view(module, mounting) if c.selectable]
    stage4 = [c.name for c in stage4_pool_view(module) if c.selectable]

    configs = []
    index = 0
    for s1, s2, s3, s4 in itertools.product(stage1, stage2, stage3, stage4):
        stage5 = [
            c.name
            for c in stage5_pool_view(INVERTER_NAME, cec_inverters, adr_inverters, s4)
            if c.selectable
        ]
        for s5 in stage5:
            index += 1
            configs.append(
                PipelineConfig(
                    label=f"chain-{index:04d}",
                    decomposition_model=s1,
                    transposition_model=s2,
                    temperature_model=s3,
                    dc_model=s4,
                    ac_model=s5,
                )
            )
    return configs


def main() -> None:
    defaults = load_defaults()
    uploaded = load_uploaded_csv(REAL_FILE)
    weather = preprocess(uploaded.table, detect_columns(uploaded.table)).df
    site = detect_site_metadata(uploaded.preamble, uploaded.table)
    offset = TimeOffset(
        0.0, TAG_USER_ENTERED,
        override_reason="header states 0.5 h; file day/night content aligns with 0 h",
    )
    ctx = build_site_context(weather, site, offset, defaults)

    module = load_module(CEC, MODULE_NAME)
    mounting = resolve_mounting(None, None, defaults)
    geometry = ArrayGeometry(6.944, 180.0)
    albedo = resolve_albedo(None, defaults)
    array_size = resolve_array_size(10, 2)

    cec_inverters = pvsystem.retrieve_sam(CEC_INVERTER)
    adr_inverters = pvsystem.retrieve_sam(ADR_INVERTER)
    base = SharedInputs(
        weather=weather, ctx=ctx, geometry=geometry, albedo=albedo, mounting=mounting,
        module=module, array_size=array_size, module_height_m=3.0,
    )
    shared_cec = replace(base, inverter=InverterRecord(CEC_INVERTER, INVERTER_NAME, cec_inverters[INVERTER_NAME]))
    shared_adr = replace(base, inverter=InverterRecord(ADR_INVERTER, INVERTER_NAME, adr_inverters[INVERTER_NAME]))

    configs = build_configs(module, mounting)
    print(f"Enumerated {len(configs)} valid chains.")
    assert len(configs) == 2058

    stage_map = [
        ("Decomposition", "decomposition"),
        ("Transposition", "transposition"),
        ("Temperature", "temperature"),
        ("DC", "dc"),
        ("AC", "ac"),
    ]

    failures = []  # (chain_label, model_tuple, stage_name, column, n_bad, n_day, n_night)
    t0 = time.perf_counter()
    for i, config in enumerate(configs, 1):
        shared = shared_inputs_for(config, shared_cec, shared_adr)
        result = run_pipeline(config, shared, defaults)
        model_tuple = (
            config.decomposition_model, config.transposition_model, config.temperature_model,
            config.dc_model, config.ac_model,
        )
        for stage_label, attr in stage_map:
            stage_result = getattr(result.outputs, attr)
            vr = validate_all_finite(stage_result.outputs, stage_label, ctx.daylight)
            if not vr.passed:
                for problem in vr.problems:
                    failures.append((config.label, model_tuple, stage_label, problem))
        if i % 500 == 0:
            print(f"  ...{i}/{len(configs)} chains checked ({time.perf_counter()-t0:.0f}s elapsed)")

    elapsed = time.perf_counter() - t0
    print(f"\nDone: {len(configs)} chains checked in {elapsed:.1f}s")
    print(f"Total failing (chain, stage, problem) entries: {len(failures)}")

    if not failures:
        print("No non-finite values found anywhere in the pool. Stage 2 fix confirmed clean.")
        return

    by_model_combo = defaultdict(list)
    for label, model_tuple, stage_label, problem in failures:
        by_model_combo[model_tuple].append((label, stage_label, problem))

    print(f"\nDistinct model combinations with at least one failure: {len(by_model_combo)}")
    for model_tuple, entries in by_model_combo.items():
        print(f"\n  {model_tuple}:")
        for label, stage_label, problem in entries:
            print(f"    [{label}] {stage_label}: {problem}")


if __name__ == "__main__":
    main()
