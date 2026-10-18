"""Does dla.tau = 0.093 (calibrated on Colombo only) still look sensible at
other Sri Lankan sites? n=100 chains (4,950 pairs) per site, seed 0, same
tau grid / widths / amended-plateau rule as the Colombo exhaustive run.

Standalone, analysis only: no change to src/ or the config, no downloads,
nothing written into data/weather/. n=100 shows whether 0.093 is still
sensible, not a precise per-site tau (sampling noise is about +-0.01).

Usage:
    python experiments/tau_calibration/tau_other_locations.py [--n 1000] <csv> [<csv> ...]
Run the Colombo file first as the baseline.
"""

from __future__ import annotations

import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np
from n34_calibration import CANDIDATE_WIDTHS, TAU_GRID, sample_chains
from tau_calibration import STAGE_ORDER, change_cumsum, k_matrix_for_grid, stable_fraction
from tau_ensemble_timing import (
    MODULE_NAME,
    ExperimentContext,
    build_configs,
    build_shared_inputs,
    run_all_pipelines,
)
from trivial_plateau_amendment import amended_plateau_table, select_default_tau, trivial_region_masks

from pvdials.config import load_defaults
from pvdials.data.column_mapper import TAG_FILE, TAG_USER_ENTERED, TimeOffset, detect_columns, detect_site_metadata
from pvdials.data.preprocess import preprocess
from pvdials.data.upload import load_uploaded_csv
from pvdials.dla.phase1 import _differing_stages, run_phase1
from pvdials.physics.geometry import ArrayGeometry, resolve_albedo
from pvdials.physics.hardware import CEC, load_module, resolve_array_size
from pvdials.physics.mounting import resolve_mounting
from pvdials.physics.site import build_site_context, offset_consistency_report

OUTPUT_DIR = Path(__file__).parent / "outputs" / "other_locations"
N = 100  # default; override with --n
SEED = 0
CURRENT_TAU = 0.093
PLATEAU_LO, PLATEAU_HI = 0.088, 0.098
EXPECTED_CHAINS = 2058
TAU_SHIFT_FLAG = 0.02  # "well over" the +-0.01 sampling noise
PLATEAU_FLAG_BELOW = 0.99
TRIVIAL_FLAG = 0.99


def grid_idx(tau: float) -> int:
    return round((tau - TAU_GRID[0]) / (TAU_GRID[1] - TAU_GRID[0]))


def header_offset_h(preamble: list[str]) -> float:
    for line in preamble:
        if "time offset" in line.lower():
            return float(line.split(":")[-1])
    return 0.5


def build_context(path: Path, defaults: dict):
    """Same calls as tau_ensemble_timing.build_experiment_context(), with the
    file and tilt as parameters. The time offset is chosen from this file's own
    day/night consistency (header value vs 0 h), not copied from Colombo."""
    uploaded = load_uploaded_csv(path)
    weather = preprocess(uploaded.table, detect_columns(uploaded.table)).df
    site = detect_site_metadata(uploaded.preamble, uploaded.table)
    header_h = header_offset_h(uploaded.preamble)

    report = offset_consistency_report(weather, site, {"hour-start": 0.0, "header": header_h}, defaults)
    for c in report:
        print(
            f"  offset {c.value_h:.2f} h ({c.label}): ghi>0 & sun down = {c.ghi_positive_sun_down}, "
            f"ghi==0 & sun up = {c.ghi_zero_sun_up}"
        )
    best = min(report, key=lambda c: (c.ghi_positive_sun_down + c.ghi_zero_sun_up, c.value_h != header_h))
    override = None if best.value_h == header_h else f"header states {header_h} h; file aligns with {best.value_h} h"
    offset = TimeOffset(best.value_h, TAG_USER_ENTERED if override else TAG_FILE, override_reason=override)
    print(f"  -> using offset {best.value_h:.2f} h" + (f" (override: {override})" if override else " (header value)"))
    ctx = build_site_context(weather, site, offset, defaults)

    module = load_module(CEC, MODULE_NAME)
    mounting = resolve_mounting(None, None, defaults)
    geometry = ArrayGeometry(site.values["latitude"], 180.0)  # tilt = site latitude, as for Colombo
    albedo = resolve_albedo(None, defaults)
    array_size = resolve_array_size(10, 2)
    shared_cec, shared_adr = build_shared_inputs(weather, ctx, module, mounting, geometry, albedo, array_size)
    configs = build_configs(module, mounting)
    assert len(configs) == EXPECTED_CHAINS, f"Expected {EXPECTED_CHAINS} chains, got {len(configs)}"
    experiment = ExperimentContext(
        defaults=defaults, ctx=ctx, configs=configs, shared_cec=shared_cec, shared_adr=shared_adr
    )
    return experiment, site, best.value_h


def confirm_all_chains_pass(labels, results) -> None:
    failures = [
        (label, name, vr.problems)
        for label in labels
        for name, vr in results[label].validations.items()
        if not vr.passed
    ]
    if failures:
        print(f"STOP: {len(failures)} (chain, check) failure(s) -- not proceeding for this site.", flush=True)
        for label, name, problems in failures[:20]:
            print(f"  {label}: {name} -- {problems}", flush=True)
        raise RuntimeError(f"{len(failures)} chain validation failures")
    print(f"  Confirmed: all {len(labels)} sampled chains pass every check.", flush=True)


def run_site(path: Path, defaults: dict, n: int) -> dict:
    print(f"\n=== {path.name} (n={n}) ===", flush=True)
    experiment, site, offset_h = build_context(path, defaults)
    configs_by_label = {c.label: c for c in experiment.configs}
    sampled = sample_chains([c.label for c in experiment.configs], n, SEED)
    sampled_configs = [configs_by_label[label] for label in sampled]

    t0 = time.perf_counter()
    results = run_all_pipelines(sampled_configs, experiment.shared_cec, experiment.shared_adr, experiment.defaults)
    print(f"  {len(sampled)} pipelines in {time.perf_counter() - t0:.1f} s", flush=True)
    confirm_all_chains_pass(sampled, results)

    pairs = list(itertools.combinations(sampled, 2))
    nrmsd = np.empty((len(pairs), len(STAGE_ORDER)))
    min_s = np.empty(len(pairs), dtype=np.int8)
    t0 = time.perf_counter()
    for i, (a, b) in enumerate(pairs):
        r = run_phase1(
            configs_by_label[a], results[a], configs_by_label[b], results[b], experiment.daylight, tau_value=0.0
        )
        nrmsd[i] = [r.metrics[s].nrmsd for s in STAGE_ORDER]
        s = _differing_stages(configs_by_label[a], configs_by_label[b])
        min_s[i] = min(s).value - 1
        if (i + 1) % 50_000 == 0:
            elapsed = time.perf_counter() - t0
            eta = (len(pairs) - i - 1) / ((i + 1) / elapsed) / 60
            print(f"  progress: {i + 1:,}/{len(pairs):,} pairs  elapsed={elapsed / 60:.1f} min  eta={eta:.1f} min", flush=True)
    print(f"  {len(pairs):,} pairs of run_phase1 in {time.perf_counter() - t0:.1f} s", flush=True)

    valid = ~np.isnan(nrmsd).any(axis=1)
    k = k_matrix_for_grid(nrmsd, TAU_GRID)
    share1, share_min_s, hi_mask, lo_mask = trivial_region_masks(k, min_s, valid)
    cumsum = change_cumsum(k[valid])
    table = amended_plateau_table(cumsum, TAU_GRID, CANDIDATE_WIDTHS, hi_mask, lo_mask)
    default = select_default_tau(table)

    plateau_stable = stable_fraction(cumsum, grid_idx(PLATEAU_LO), grid_idx(PLATEAU_HI))
    share1_at = float(np.interp(CURRENT_TAU, TAU_GRID, share1))
    share_min_s_at = float(np.interp(CURRENT_TAU, TAU_GRID, share_min_s))
    max_stage = nrmsd[valid].max(axis=1)

    flags = []
    if plateau_stable < PLATEAU_FLAG_BELOW:
        flags.append(f"plateau [{PLATEAU_LO},{PLATEAU_HI}] unstable ({plateau_stable:.3f})")
    if share1_at >= TRIVIAL_FLAG or share_min_s_at >= TRIVIAL_FLAG:
        flags.append("trivial regime at 0.093")
    if default is None:
        flags.append("no width reaches 0.99")
    elif abs(default.centre - CURRENT_TAU) > TAU_SHIFT_FLAG:
        flags.append(f"tau moved by {default.centre - CURRENT_TAU:+.3f}")

    return {
        "file": path.name,
        "latitude": site.values["latitude"],
        "longitude": site.values["longitude"],
        "elevation": site.values.get("elevation"),
        "offset_h": offset_h,
        "n_chains": n,
        "n_pairs": len(pairs),
        "nan_pairs": int((~valid).sum()),
        "amended_default_tau": None if default is None else default.centre,
        "amended_default_width": None if default is None else default.width,
        "amended_default_stable_fraction": None if default is None else default.stable_fraction,
        "plateau_stable_fraction": plateau_stable,
        "share_outcome1_at_0.093": share1_at,
        "share_k_eq_minS_at_0.093": share_min_s_at,
        "max_stage_nrmsd": {
            "median": float(np.median(max_stage)),
            "p90": float(np.percentile(max_stage, 90)),
            "p99": float(np.percentile(max_stage, 99)),
            "max": float(max_stage.max()),
        },
        "plateau_table": [
            {"width": c.width, "lo": c.lo, "hi": c.hi, "centre": c.centre, "stable_fraction": c.stable_fraction}
            for c in table
        ],
        "flags": flags,
    }


def print_table(rows: list[dict]) -> None:
    head = (
        f"{'site (lat,lon)':<18}{'tau*':>7}{'plateau':>9}{'out1':>7}{'k=minS':>8}"
        f"{'med':>8}{'P90':>8}{'P99':>8}{'max':>8}  flags"
    )
    print("\n" + head)
    print("-" * len(head))
    for r in rows:
        m = r["max_stage_nrmsd"]
        tau = r["amended_default_tau"]
        print(
            f"{r['latitude']:>7.3f},{r['longitude']:<9.3f}"
            f"{'none' if tau is None else format(tau, '.3f'):>7}{r['plateau_stable_fraction']:>9.3f}"
            f"{r['share_outcome1_at_0.093']:>7.3f}{r['share_k_eq_minS_at_0.093']:>8.3f}"
            f"{m['median']:>8.4f}{m['p90']:>8.4f}{m['p99']:>8.4f}{m['max']:>8.4f}  "
            f"{'; '.join(r['flags']) or 'ok'}"
        )


def main() -> None:
    args = sys.argv[1:]
    n = N
    if args[:1] == ["--n"]:
        n, args = int(args[1]), args[2:]
    paths = [Path(p) for p in args]
    if not paths:
        raise SystemExit(__doc__)
    defaults = load_defaults()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = OUTPUT_DIR / "summary.json"
    stored = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    # Keys are "<file>@n<N>"; entries from the first (n=100) run have no suffix.
    existing = {(k if "@n" in k else f"{k}@n100"): v for k, v in stored.items()}

    for path in paths:
        existing[f"{path.name}@n{n}"] = run_site(path, defaults, n)
        summary_path.write_text(json.dumps(existing, indent=2))
    print_table([v for v in existing.values() if v["n_chains"] == n])
    print(f"\nWrote {summary_path}")


if __name__ == "__main__":
    main()
