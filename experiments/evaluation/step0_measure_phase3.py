"""Step 0 (evaluation KT, docs/evaluation-kt.md): measures Phase 3's current
cost on the real Colombo pairs (A-B, A-C) before any code change -- hybrid
run count, distinct-config count, time in physics vs provenance writes vs
nRMSD/Shapley computation, and the number of DISTINCT provenance_records
rows the pair's derived runs actually create.

Not evaluation code (doesn't compare PV-DIAL to a simpler method) -- a
timing/counting instrument for the Step 0 production change. Monkeypatches
dla.phase3's own references to run_pipeline/record_provenance to time-stamp
each call without changing behavior (same technique tests/dla/
mock_adapters.py uses for stage adapters).

Run standalone: python3 experiments/evaluation/step0_measure_phase3.py
"""

from __future__ import annotations

import time
from pathlib import Path

import pvdials.dla.phase3 as phase3_module
from pvdials.config import load_defaults
from pvdials.data.column_mapper import (
    TAG_USER_ENTERED,
    TimeOffset,
    detect_columns,
    detect_site_metadata,
)
from pvdials.data.preprocess import preprocess
from pvdials.data.upload import load_uploaded_csv
from pvdials.dla.phase1 import _differing_stages
from pvdials.physics.geometry import ArrayGeometry, resolve_albedo
from pvdials.physics.hardware import (
    ADR_INVERTER,
    CEC,
    CEC_INVERTER,
    ArraySize,
    InverterRecord,
    ModuleRecord,
)
from pvdials.physics.mounting import resolve_mounting
from pvdials.physics.pipeline import SharedInputs, run_pipeline
from pvdials.physics.site import build_site_context
from pvdials.provenance.db import get_connection
from pvdials.types import ExecutionSet, PipelineConfig

REAL_FILE = Path("data/weather/tmy_6.939_79.854_2005_2023.csv")
MODULE_NAME = "Canadian_Solar_Inc__CS6K_300MS"
INVERTER_NAME = "ABB__PVI_6000_OUTD_S_US_A__208V_"

CONFIGS = {
    "A": PipelineConfig("A", "erbs", "isotropic", "faiman", "singlediode_cec", "sandia"),
    "B": PipelineConfig("B", "disc", "haydavies", "pvsyst_cell", "singlediode_desoto", "sandia"),
    "C": PipelineConfig("C", "dirint", "perez", "ross", "singlediode_cec", "sandia"),
}
PAIRS = [("A", "B"), ("A", "C")]


def _shared():
    from pvlib import pvsystem

    uploaded = load_uploaded_csv(REAL_FILE)
    weather = preprocess(uploaded.table, detect_columns(uploaded.table), canonical_year=2023).df
    site = detect_site_metadata(uploaded.preamble, uploaded.table)
    offset = TimeOffset(
        0.0, TAG_USER_ENTERED,
        override_reason="header states 0.5 h; file day/night content aligns with 0 h",
    )
    ctx = build_site_context(weather, site, offset, load_defaults())
    cec_modules = pvsystem.retrieve_sam(CEC)
    module = ModuleRecord(CEC, MODULE_NAME, cec_modules[MODULE_NAME])
    cec_inverters = pvsystem.retrieve_sam(CEC_INVERTER)
    adr_inverters = pvsystem.retrieve_sam(ADR_INVERTER)
    base = {
        "weather": weather, "ctx": ctx,
        "geometry": ArrayGeometry(surface_tilt_deg=6.944, surface_azimuth_deg=180.0),
        "albedo": resolve_albedo(None, load_defaults()),
        "mounting": resolve_mounting(None, None, load_defaults()),
        "module": module, "array_size": ArraySize(10, 2), "module_height_m": 3.0,
    }
    shared_cec = SharedInputs(**base, inverter=InverterRecord(CEC_INVERTER, INVERTER_NAME, cec_inverters[INVERTER_NAME]))
    shared_adr = SharedInputs(**base, inverter=InverterRecord(ADR_INVERTER, INVERTER_NAME, adr_inverters[INVERTER_NAME]))
    return shared_cec, shared_adr, ctx.daylight


class _Timers:
    def __init__(self):
        self.physics_s = 0.0
        self.provenance_s = 0.0
        self.run_pipeline_calls = 0
        self.record_provenance_calls = 0


def _install_timing_wrappers(timers: _Timers):
    real_run_pipeline = phase3_module.run_pipeline
    real_record_provenance = phase3_module.record_provenance

    def timed_run_pipeline(*args, **kwargs):
        t0 = time.perf_counter()
        result = real_run_pipeline(*args, **kwargs)
        timers.physics_s += time.perf_counter() - t0
        timers.run_pipeline_calls += 1
        return result

    def timed_record_provenance(*args, **kwargs):
        t0 = time.perf_counter()
        result = real_record_provenance(*args, **kwargs)
        timers.provenance_s += time.perf_counter() - t0
        timers.record_provenance_calls += 1
        return result

    phase3_module.run_pipeline = timed_run_pipeline
    phase3_module.record_provenance = timed_record_provenance
    return real_run_pipeline, real_record_provenance


def _restore(real_run_pipeline, real_record_provenance):
    phase3_module.run_pipeline = real_run_pipeline
    phase3_module.record_provenance = real_record_provenance


def _derived_record_count() -> int:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM provenance_records WHERE execution_set = %s", (ExecutionSet.DERIVED.value,))
        return cur.fetchone()[0]


def main() -> None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM stage_output_values")
        cur.execute("DELETE FROM provenance_records")
        conn.commit()

    defaults = load_defaults()
    shared_cec, shared_adr, daylight = _shared()
    print("Running pipelines A, B, C...", flush=True)
    results = {label: run_pipeline(config, shared_cec, defaults) for label, config in CONFIGS.items()}

    for label_a, label_b in PAIRS:
        config_a, config_b = CONFIGS[label_a], CONFIGS[label_b]
        s = _differing_stages(config_a, config_b)
        print(f"\n=== Pair {label_a}-{label_b}: |S|={len(s)}, S={sorted(st.name for st in s)} ===", flush=True)

        before = _derived_record_count()
        timers = _Timers()
        real_run_pipeline, real_record_provenance = _install_timing_wrappers(timers)
        t0 = time.perf_counter()
        try:
            result = phase3_module.run_phase3(
                config_a, results[label_a], config_b, results[label_b],
                shared_cec, shared_adr, daylight, defaults,
            )
        finally:
            _restore(real_run_pipeline, real_record_provenance)
        total_s = time.perf_counter() - t0
        after = _derived_record_count()

        other_s = total_s - timers.physics_s - timers.provenance_s
        print(f"  total time: {total_s:.3f} s")
        print(f"  run_pipeline() calls: {timers.run_pipeline_calls}  (physics time: {timers.physics_s:.3f} s)")
        print(f"  record_provenance() calls: {timers.record_provenance_calls}  (provenance time: {timers.provenance_s:.3f} s)")
        print(f"  other (nRMSD/Shapley/etc.) time: {other_s:.3f} s")
        print(f"  distinct configs 2^|S| (incl. endpoints): {2 ** len(s)}, non-trivial: {2 ** len(s) - 2}")
        print(f"  derived provenance_records rows created for this pair: {after - before}")
        print(f"  efficiency check: sum(phi_final)={sum(result.phi_final.values()):.6f}  rmsd_ab={result.rmsd_ab:.6f}")


if __name__ == "__main__":
    main()
