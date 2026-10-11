"""Exhaustive full-population run of the amended trivial-plateau rule
(28/09b). Same amended rule, tau grid, widths, and >=0.99 criterion as
trivial_plateau_amendment.py's n=1000 sample run -- this uses every one of
C(2,058, 2) = 2,116,653 pairs exhaustively, no sampling, no seed. Analysis
only -- no changes to run_defaults.yaml or any production code; does not
decide or apply a new tau.

This is the ~205 min run that trivial_plateau_amendment.py's own docstring
flagged as needing separate approval -- approved 28/09 after the n=1000
result and the adr night-NaN fix (committed) confirmed 0/2,058 chains fail
any check. Run under caffeinate so the machine doesn't sleep partway through
a multi-hour job, and unbuffered so progress is visible immediately (a
previous n=1000 run looked stalled for 127+ minutes purely from stdout
buffering through `tee`, not a real hang -- see trivial_plateau_amendment.py):

    caffeinate -i python3 -u experiments/tau_calibration/trivial_plateau_amendment_exhaustive.py
"""

from __future__ import annotations

import itertools
import time
from pathlib import Path

import numpy as np
from n34_calibration import CANDIDATE_WIDTHS, DEFAULT_TAU_STABLE_THRESHOLD, TAU_GRID
from tau_calibration import STAGE_ORDER, k_matrix_for_grid
from tau_ensemble_timing import build_experiment_context, run_all_pipelines
from trivial_plateau_amendment import (
    amended_plateau_table,
    plot_amended_stability_curve,
    select_default_tau,
    trivial_region_masks,
)

from pvdials.dla.phase1 import _differing_stages, run_phase1

OUTPUT_DIR = Path(__file__).parent / "outputs" / "trivial_plateau_amendment"
CACHE_DIR = OUTPUT_DIR / "exhaustive_cache"
LOG_EVERY = 50_000


def change_cumsum_compact(k_matrix: np.ndarray) -> np.ndarray:
    """Same computation as tau_calibration.change_cumsum, but int16 instead
    of int32 -- halves memory (~2.1 GB vs ~4.2 GB at 2,116,653 pairs x 501
    grid points, on a machine already running with little headroom). The
    max possible cumulative change count is 500 (one fewer than the grid's
    501 columns), safely inside int16's range.
    """
    changes = k_matrix[:, 1:] != k_matrix[:, :-1]
    cumsum = np.zeros(k_matrix.shape, dtype=np.int16)
    cumsum[:, 1:] = np.cumsum(changes, axis=1)
    return cumsum


def confirm_all_chains_pass(configs, results) -> None:
    """Your explicit condition: confirm before computing anything. The
    pool_scan.py rerun already found 0/2,058 failures after the adr fix, but
    this re-checks inside the actual run being reported, not from memory of
    a separate earlier script.
    """
    failures = []
    for config in configs:
        result = results[config.label]
        for name, vr in result.validations.items():
            if not vr.passed:
                failures.append((config.label, name, vr.problems))
    if failures:
        print(f"STOP: {len(failures)} (chain, check) failure(s) found -- not proceeding.", flush=True)
        for label, name, problems in failures:
            print(f"  {label}: {name} -- {problems}", flush=True)
        raise SystemExit(1)
    print(f"Confirmed: all {len(configs)} chains pass every check. Proceeding.", flush=True)


def main() -> None:
    print("=== Building experiment context and running all 2,058 pipelines (fresh, real) ===", flush=True)
    experiment = build_experiment_context()
    configs = experiment.configs
    all_labels = [c.label for c in configs]
    configs_by_label = {c.label: c for c in configs}

    t0 = time.perf_counter()
    results = run_all_pipelines(configs, experiment.shared_cec, experiment.shared_adr, experiment.defaults)
    print(f"Pipelines done in {time.perf_counter() - t0:.1f} s", flush=True)

    confirm_all_chains_pass(configs, results)

    n = len(all_labels)
    total_pairs = n * (n - 1) // 2
    print(f"Exhaustive population: {n} chains -> {total_pairs:,} pairs", flush=True)

    nrmsd_matrix = np.empty((total_pairs, len(STAGE_ORDER)), dtype=np.float64)
    min_s_idx = np.empty(total_pairs, dtype=np.int8)

    # Written directly into preallocated arrays (not a growing dict-of-dicts,
    # unlike n34_calibration.compute_pair_nrmsd) -- at 2.1M pairs a Python
    # dict-of-dicts would itself cost roughly a GB in pure object overhead,
    # on top of the final numpy matrix; this avoids that entirely.
    t0 = time.perf_counter()
    for i, (label_a, label_b) in enumerate(itertools.combinations(all_labels, 2)):
        result = run_phase1(
            configs_by_label[label_a],
            results[label_a],
            configs_by_label[label_b],
            results[label_b],
            experiment.daylight,
            tau_value=0.0,
        )
        nrmsd_matrix[i] = [result.metrics[stage].nrmsd for stage in STAGE_ORDER]

        s = _differing_stages(configs_by_label[label_a], configs_by_label[label_b])
        assert s, f"pair {(label_a, label_b)} has no differing stage -- two chains are identical"
        min_s_idx[i] = min(s).value - 1

        if (i + 1) % LOG_EVERY == 0 or (i + 1) == total_pairs:
            elapsed = time.perf_counter() - t0
            rate = (i + 1) / elapsed
            remaining_min = (total_pairs - (i + 1)) / rate / 60 if rate > 0 else float("nan")
            print(
                f"  progress: {i + 1:,}/{total_pairs:,} pairs  "
                f"elapsed={elapsed / 60:.1f} min  eta={remaining_min:.1f} min",
                flush=True,
            )
    print(f"nRMSD computed in {(time.perf_counter() - t0) / 60:.1f} min", flush=True)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    np.save(CACHE_DIR / "nrmsd_matrix_n2058_exhaustive.npy", nrmsd_matrix)
    np.save(CACHE_DIR / "min_s_idx_n2058_exhaustive.npy", min_s_idx)
    (CACHE_DIR / "labels_n2058_exhaustive.txt").write_text("\n".join(all_labels), encoding="utf-8")
    print(f"Saved raw nRMSD matrix, min(S) index, and label order to {CACHE_DIR}", flush=True)

    nan_mask = np.isnan(nrmsd_matrix).any(axis=1)
    nan_count = int(nan_mask.sum())
    valid_mask = ~nan_mask
    print(f"NaN-affected pairs: {nan_count} / {total_pairs:,}", flush=True)

    k_matrix = k_matrix_for_grid(nrmsd_matrix, TAU_GRID)
    share_outcome1, share_k_eq_minS, near_trivial_high, near_trivial_low = trivial_region_masks(
        k_matrix, min_s_idx, valid_mask
    )

    idx_0234 = round((0.234 - TAU_GRID[0]) / (TAU_GRID[1] - TAU_GRID[0]))
    assert TAU_GRID[idx_0234] == 0.234, "0.234 is not exactly on the 501-point grid -- grid changed?"
    in_high_at_0234 = bool(near_trivial_high[idx_0234])
    print(
        f"At tau=0.234: share_outcome1={share_outcome1[idx_0234]:.4f}  "
        f"share_k_eq_minS={share_k_eq_minS[idx_0234]:.4f}  "
        f"in_near_trivial_high={in_high_at_0234}",
        flush=True,
    )

    k_valid = k_matrix[valid_mask]
    del k_matrix  # free ~1 GB before the still-substantial cumsum allocation
    cumsum = change_cumsum_compact(k_valid)
    table = amended_plateau_table(cumsum, TAU_GRID, CANDIDATE_WIDTHS, near_trivial_high, near_trivial_low)

    print("Amended plateau table (exhaustive, all 2,116,653 pairs):", flush=True)
    for c in table:
        if c.stable_fraction is None:
            print(f"  width={c.width:.3f}  no window clears both trivial-region exclusions")
        else:
            print(
                f"  width={c.width:.3f}  best=[{c.lo:.3f},{c.hi:.3f}]  "
                f"centre={c.centre:.3f}  stable_fraction={c.stable_fraction:.3f}"
            )

    default = select_default_tau(table)
    if default is not None:
        print(
            f"Amended default tau (exhaustive): {default.centre:.4f}  "
            f"(width={default.width}, stable_fraction={default.stable_fraction:.3f})",
            flush=True,
        )
    else:
        print(
            f"Amended default tau (exhaustive): no width reaches stable_fraction >= "
            f"{DEFAULT_TAU_STABLE_THRESHOLD}",
            flush=True,
        )

    max_nrmsd = np.nanmax(nrmsd_matrix[valid_mask], axis=1)
    print(
        f"Per-pair max-stage nRMSD: median={np.median(max_nrmsd):.4f}  "
        f"P90={np.percentile(max_nrmsd, 90):.4f}  P99={np.percentile(max_nrmsd, 99):.4f}  "
        f"max={max_nrmsd.max():.4f}",
        flush=True,
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plot_amended_stability_curve(
        n, "exhaustive (all C(2058,2) pairs)", cumsum, near_trivial_high, near_trivial_low,
        OUTPUT_DIR / "amended_stability_curve_n2058_exhaustive.png",
    )

    print("\n=== Summary ===")
    print(f"NaN pairs: {nan_count} / {total_pairs:,}")
    print(f"in_near_trivial_high(0.234): {in_high_at_0234}")
    if default is not None:
        print(f"amended default tau = {default.centre:.4f} (width={default.width})")
    else:
        print("amended default tau: no width reaches 0.99")
    print(f"\nFigure written to {OUTPUT_DIR}")
    print(f"Raw nRMSD matrix (never needs recomputing) saved to {CACHE_DIR}")


if __name__ == "__main__":
    main()
