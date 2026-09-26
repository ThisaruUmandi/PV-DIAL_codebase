"""τ-calibration timing (N33 support). Measures real cost of the DLA's Phase 1
over the exhaustive valid-combination population for one fixed representative
hardware setup, so the N33 pre-registration entry can state a realistic
ensemble size and runtime instead of guessing.

This is a timing/feasibility exercise only — it is not the calibration run
itself (N34), which must not start until N33 is written. Lives in
experiments/ per KT's own placement; dla/ never imports from here.

build_experiment_context()/run_all_pipelines() are reused by
tau_calibration_convergence.py, so the two scripts can't drift apart on the
fixed hardware/site setup.

Run standalone: python3 experiments/tau_calibration/tau_ensemble_timing.py
"""

from __future__ import annotations

import itertools
import random
import statistics
import time
from dataclasses import dataclass, replace
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
from pvdials.dla.phase1 import run_phase1
from pvdials.physics.geometry import ArrayGeometry, resolve_albedo
from pvdials.physics.hardware import (
    ADR_INVERTER,
    CEC,
    CEC_INVERTER,
    load_inverter,
    load_module,
    resolve_array_size,
)
from pvdials.physics.mounting import resolve_mounting
from pvdials.physics.pipeline import PipelineResult, SharedInputs, run_pipeline
from pvdials.physics.registry import (
    stage1_pool_view,
    stage2_pool_view,
    stage3_pool_view,
    stage4_pool_view,
    stage5_pool_view,
)
from pvdials.physics.site import SiteContext, build_site_context
from pvdials.types import PipelineConfig

REAL_FILE = Path("/Users/umandi/workfolder/Research/Sandbox/pvlib_test1/tmy_6.944_79.856_2005_2020.csv")
MODULE_NAME = "Canadian_Solar_Inc__CS6K_300MS"
INVERTER_NAME = "ABB__PVI_6000_OUTD_S_US_A__208V_"
SAMPLE_PAIR_COUNT = 20_000
KT_ENSEMBLE_SIZE = 100
SEED = 0


def build_configs(module, mounting) -> list[PipelineConfig]:
    """Enumerate every valid PipelineConfig for the fixed hardware, exactly the
    same registry calls already used to hand-verify the 2,058-chain population.
    """
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


def build_shared_inputs(weather, ctx, module, mounting, geometry, albedo, array_size):
    """Two SharedInputs, one per inverter library. ac_power() takes a single
    InverterRecord (one .library each), so 'sandia'/'pvwatts' configs use the
    CEC-loaded record and 'adr' configs use the ADR-loaded one — the same
    library-mismatch fix already made once for the 3-pipeline verification
    script (config C's ac_model had to match the shared inverter's library).
    """
    base = SharedInputs(
        weather=weather,
        ctx=ctx,
        geometry=geometry,
        albedo=albedo,
        mounting=mounting,
        module=module,
        array_size=array_size,
        module_height_m=3.0,  # required by 'fuentes' (Stage 3), no default (N40)
    )
    shared_cec = replace(base, inverter=load_inverter(CEC_INVERTER, INVERTER_NAME))
    shared_adr = replace(base, inverter=load_inverter(ADR_INVERTER, INVERTER_NAME))
    return shared_cec, shared_adr


@dataclass(frozen=True)
class ExperimentContext:
    """Everything both scripts in this folder need: the fixed site/hardware
    setup and the exact 2,058-chain population, built once from real code.
    """

    defaults: dict
    ctx: SiteContext
    configs: list[PipelineConfig]
    shared_cec: SharedInputs
    shared_adr: SharedInputs

    @property
    def daylight(self):
        return self.ctx.daylight


def build_experiment_context() -> ExperimentContext:
    """Real weather/site/hardware build, plus the exact valid-combination
    population, for the fixed representative setup used across this folder.
    """
    defaults = load_defaults()

    uploaded = load_uploaded_csv(REAL_FILE)
    weather = preprocess(uploaded.table, detect_columns(uploaded.table)).df
    site = detect_site_metadata(uploaded.preamble, uploaded.table)
    offset = TimeOffset(
        0.0,
        TAG_USER_ENTERED,
        override_reason="header states 0.5 h; file day/night content aligns with 0 h",
    )
    ctx = build_site_context(weather, site, offset, defaults)

    module = load_module(CEC, MODULE_NAME)
    mounting = resolve_mounting(None, None, defaults)
    geometry = ArrayGeometry(6.944, 180.0)
    albedo = resolve_albedo(None, defaults)
    array_size = resolve_array_size(10, 2)

    shared_cec, shared_adr = build_shared_inputs(
        weather, ctx, module, mounting, geometry, albedo, array_size
    )

    configs = build_configs(module, mounting)
    assert len(configs) == 2058, (
        f"Expected exactly 2,058 chains (the earlier hand-verified count); got {len(configs)}. "
        "Stopping — a silent count drift would invalidate anything built on this population."
    )

    return ExperimentContext(
        defaults=defaults, ctx=ctx, configs=configs, shared_cec=shared_cec, shared_adr=shared_adr
    )


def run_all_pipelines(
    configs: list[PipelineConfig], shared_cec: SharedInputs, shared_adr: SharedInputs, defaults: dict
) -> dict[str, PipelineResult]:
    """Real run_pipeline() for every config, routed to the inverter-library-
    matching SharedInputs (see build_shared_inputs's docstring).
    """
    results = {}
    for config in configs:
        shared = shared_adr if config.ac_model == "adr" else shared_cec
        results[config.label] = run_pipeline(config, shared, defaults)
    return results


def main() -> None:
    print("=== Population enumeration ===")
    experiment = build_experiment_context()
    configs = experiment.configs
    print(f"Enumerated {len(configs)} valid chains.")
    total_pairs = len(configs) * (len(configs) - 1) // 2
    print(f"Exhaustive unordered pairs: {total_pairs:,}")

    print("\n=== Phase A: run and time all 2,058 pipelines ===")
    per_config_times = []
    results: dict[str, PipelineResult] = {}
    phase_a_start = time.perf_counter()
    for config in configs:
        shared = experiment.shared_adr if config.ac_model == "adr" else experiment.shared_cec
        t0 = time.perf_counter()
        results[config.label] = run_pipeline(config, shared, experiment.defaults)
        per_config_times.append(time.perf_counter() - t0)
    phase_a_total = time.perf_counter() - phase_a_start
    print(f"Total: {phase_a_total:.1f} s for {len(configs)} configs")
    print(
        f"Per-config: mean={statistics.mean(per_config_times) * 1000:.2f} ms  "
        f"median={statistics.median(per_config_times) * 1000:.2f} ms  "
        f"min={min(per_config_times) * 1000:.2f} ms  max={max(per_config_times) * 1000:.2f} ms"
    )

    print(f"\n=== Phase B: real run_phase1() over a random sample of {SAMPLE_PAIR_COUNT:,} pairs ===")
    rng = random.Random(SEED)
    labels = [c.label for c in configs]
    by_label = {c.label: c for c in configs}
    sampled_pairs = set()
    while len(sampled_pairs) < SAMPLE_PAIR_COUNT:
        a, b = rng.sample(labels, 2)
        sampled_pairs.add((a, b) if a < b else (b, a))

    per_pair_times = []
    phase_b_start = time.perf_counter()
    for label_a, label_b in sampled_pairs:
        t0 = time.perf_counter()
        run_phase1(
            by_label[label_a], results[label_a], by_label[label_b], results[label_b], experiment.daylight
        )
        per_pair_times.append(time.perf_counter() - t0)
    phase_b_total = time.perf_counter() - phase_b_start
    mean_pair_time = statistics.mean(per_pair_times)
    print(f"Total: {phase_b_total:.1f} s for {len(sampled_pairs):,} pairs")
    print(
        f"Per-pair: mean={mean_pair_time * 1000:.3f} ms  "
        f"median={statistics.median(per_pair_times) * 1000:.3f} ms"
    )

    print(f"\n=== Phase C: real, complete {KT_ENSEMBLE_SIZE}-chain ensemble (KT's pre-registered size) ===")
    kt_labels = labels[:KT_ENSEMBLE_SIZE]
    kt_pairs = list(itertools.combinations(kt_labels, 2))
    phase_c_start = time.perf_counter()
    for label_a, label_b in kt_pairs:
        run_phase1(
            by_label[label_a], results[label_a], by_label[label_b], results[label_b], experiment.daylight
        )
    phase_c_total = time.perf_counter() - phase_c_start
    print(f"Total: {phase_c_total:.2f} s for {len(kt_pairs):,} pairs ({KT_ENSEMBLE_SIZE} chains)")

    print("\n=== Extrapolation to the full exhaustive population (estimate, not a completed run) ===")
    estimated_full = mean_pair_time * total_pairs
    print(f"Measured mean per-pair time: {mean_pair_time * 1000:.3f} ms (n={len(sampled_pairs):,} sample)")
    print(f"Extrapolated full-population Phase-1 time: {estimated_full:.1f} s ({estimated_full / 60:.1f} min)")
    print(f"Plus the one-off Phase-A pipeline-computation cost: {phase_a_total:.1f} s")
    print(
        f"Estimated full run total: {phase_a_total + estimated_full:.1f} s "
        f"({(phase_a_total + estimated_full) / 60:.1f} min)"
    )

    print("\n=== Summary ===")
    print(f"Population: {len(configs)} chains, {total_pairs:,} exhaustive pairs")
    print(f"Phase A (real, complete): {phase_a_total:.1f} s")
    print(f"Phase B (real, sampled {len(sampled_pairs):,} pairs): {phase_b_total:.1f} s")
    print(f"Phase C (real, complete, {KT_ENSEMBLE_SIZE}-chain KT ensemble): {phase_c_total:.2f} s")
    print(f"Extrapolated exhaustive-population total: {phase_a_total + estimated_full:.1f} s")


if __name__ == "__main__":
    main()
