"""τ-plateau convergence check across ensemble size (N33 support, diagnostic
only — this is NOT N34). Checks whether the width/stable-fraction trade-off
computed by tau_calibration.plateau_table() holds steady as the ensemble
size n grows (100, 300, 1000, 2058 chains, the full valid-combination
population for the fixed hardware setup), so N33's eventual ensemble-size
choice is informed by real evidence instead of a guess.

Grid (TAU_GRID) and candidate widths (CANDIDATE_WIDTHS) below are PROVISIONAL
— an exploratory choice for this diagnostic, not N33's official parameters.
N33 is written and confirmed separately, choosing its own values on their
own merits; nothing here is silently reused as N33's calibration.

n=100/300/1000 are exhaustive (every pair, real run_phase1()). n=2058 is a
large random sample (not exhaustive — a full run there was already measured
at ~205 minutes in tau_ensemble_timing.py and isn't worth repeating for a
diagnostic check), and is reported as such.

Run standalone: python3 experiments/tau_calibration/tau_calibration_convergence.py
"""

from __future__ import annotations

import itertools
import random
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from tau_calibration import (
    change_cumsum,
    k_matrix_for_grid,
    pair_nrmsd_matrix,
    plateau_table,
    stable_fraction_curve,
)
from tau_ensemble_timing import build_experiment_context, run_all_pipelines

from pvdials.dla.phase1 import run_phase1

OUTPUT_DIR = Path(__file__).parent / "outputs"
NRMSD_CACHE_DIR = OUTPUT_DIR / "nrmsd_cache"
TAU_GRID = np.linspace(0.0, 1.0, 501)  # PROVISIONAL
CANDIDATE_WIDTHS = [0.01, 0.02, 0.05, 0.1, 0.2]  # PROVISIONAL, tau-units
ENSEMBLE_SIZES = [100, 300, 1000, 2058]
EXHAUSTIVE_LIMIT = 1000  # n <= this: every pair; above: sampled
SAMPLE_PAIR_COUNT_LARGE = 300_000
SEED = 0


def compute_pair_nrmsd(pairs, configs_by_label, results, daylight):
    """Real run_phase1() per pair (tau_value=0.0 placeholder — only the
    per-stage nRMSD values are kept; outcome/k from this call are ignored
    and recomputed properly, per grid point, by k_matrix_for_grid()).
    """
    pair_nrmsd = {}
    for label_a, label_b in pairs:
        result = run_phase1(
            configs_by_label[label_a],
            results[label_a],
            configs_by_label[label_b],
            results[label_b],
            daylight,
            tau_value=0.0,
        )
        pair_nrmsd[(label_a, label_b)] = {stage: m.nrmsd for stage, m in result.metrics.items()}
    return pair_nrmsd


def get_nrmsd_matrix(n, pairs, configs_by_label, results, daylight):
    """Real per-pair nRMSD is the expensive part (up to ~46 min at n=1000) —
    cache it to disk so a later change to the plateau/stability analysis
    (which is cheap) doesn't require re-running run_phase1() over every pair
    again. Cache holds only nRMSD values, never a fitted parameter or a
    calibration result — nothing here becomes N33/N34 output by being cached.
    """
    cache_path = NRMSD_CACHE_DIR / f"nrmsd_matrix_n{n}.npy"
    if cache_path.exists():
        print(f"  (loaded cached nRMSD matrix: {cache_path})")
        return np.load(cache_path)
    pair_nrmsd = compute_pair_nrmsd(pairs, configs_by_label, results, daylight)
    nrmsd_matrix, _ = pair_nrmsd_matrix(pair_nrmsd)
    NRMSD_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    np.save(cache_path, nrmsd_matrix)
    return nrmsd_matrix


def pairs_for_n(n, labels, rng):
    if n <= EXHAUSTIVE_LIMIT:
        return list(itertools.combinations(labels[:n], 2)), "exhaustive"
    pool = labels[:n]
    sampled = set()
    while len(sampled) < SAMPLE_PAIR_COUNT_LARGE:
        a, b = rng.sample(pool, 2)
        sampled.add((a, b) if a < b else (b, a))
    total = n * (n - 1) // 2
    return list(sampled), f"sampled ({SAMPLE_PAIR_COUNT_LARGE:,} of {total:,})"


def plot_stage_curve(n, cumsum):
    fig, ax = plt.subplots()
    step = TAU_GRID[1] - TAU_GRID[0]
    for width in CANDIDATE_WIDTHS:
        width_steps = max(1, round(width / step))
        if width_steps >= len(TAU_GRID):
            continue
        centres, fractions = stable_fraction_curve(cumsum, TAU_GRID, width_steps)
        ax.plot(centres, fractions, label=f"width={width}")
    ax.set_xlabel("Candidate threshold value (τ)")
    ax.set_ylabel("Share of pairs giving the same answer (stable fraction)")
    ax.set_title(f"n={n} chains")
    ax.legend()
    ax.set_ylim(0, 1.02)
    fig.savefig(OUTPUT_DIR / f"stability_curve_n{n}.png", dpi=150)
    plt.close(fig)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    experiment = build_experiment_context()
    configs = experiment.configs
    labels = [c.label for c in configs]
    configs_by_label = {c.label: c for c in configs}

    print("=== Running all 2,058 pipelines (real) ===")
    t0 = time.perf_counter()
    results = run_all_pipelines(configs, experiment.shared_cec, experiment.shared_adr, experiment.defaults)
    print(f"Done in {time.perf_counter() - t0:.1f} s")

    rng = random.Random(SEED)
    tables = {}
    cumsums = {}
    for n in ENSEMBLE_SIZES:
        pairs, method = pairs_for_n(n, labels, rng)
        print(f"\n=== n={n} ({method}, {len(pairs):,} pairs) ===")
        t0 = time.perf_counter()
        nrmsd_matrix = get_nrmsd_matrix(n, pairs, configs_by_label, results, experiment.daylight)
        k_matrix = k_matrix_for_grid(nrmsd_matrix, TAU_GRID)
        cumsum = change_cumsum(k_matrix)
        table = plateau_table(k_matrix, TAU_GRID, CANDIDATE_WIDTHS)
        print(f"Computed in {time.perf_counter() - t0:.1f} s")
        for c in table:
            print(
                f"  width={c.width:.3f}  best=[{c.lo:.3f},{c.hi:.3f}]  "
                f"centre={c.centre:.3f}  stable_fraction={c.stable_fraction:.3f}"
            )
        tables[n] = table
        cumsums[n] = cumsum
        plot_stage_curve(n, cumsum)

    print("\n=== Best width per n ===")
    best_per_n = {n: max(tables[n], key=lambda c: c.stable_fraction) for n in ENSEMBLE_SIZES}
    for n, best in best_per_n.items():
        print(f"  n={n}: best width={best.width}, centre={best.centre:.3f}, stable_fraction={best.stable_fraction:.3f}")

    widths = {best.width for best in best_per_n.values()}
    representative_width = best_per_n[2058].width
    print(f"\nOverlay uses n=2058's best width ({representative_width}) for all four curves.")
    if len(widths) > 1:
        print(
            "NOTE: best width is NOT the same across n — the overlay plot below shows every n "
            f"at n=2058's width ({representative_width}), so it does not show each smaller n at "
            "its own best width. Read the per-n tables above for each n's own best width/centre/"
            "stable_fraction; do not read the overlay as comparing like-for-like best cases."
        )

    fig, ax = plt.subplots()
    step = TAU_GRID[1] - TAU_GRID[0]
    width_steps = max(1, round(representative_width / step))
    for n in ENSEMBLE_SIZES:
        centres, fractions = stable_fraction_curve(cumsums[n], TAU_GRID, width_steps)
        ax.plot(centres, fractions, label=f"n={n}")
    ax.set_xlabel("Candidate threshold value (τ)")
    ax.set_ylabel("Share of pairs giving the same answer (stable fraction)")
    ax.set_title(f"Overlay at width={representative_width} (n=2058's best width)")
    ax.legend()
    ax.set_ylim(0, 1.02)
    fig.savefig(OUTPUT_DIR / "stability_curve_overlay.png", dpi=150)
    plt.close(fig)
    print(f"\nPlots written to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
