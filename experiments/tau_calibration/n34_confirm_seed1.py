"""N34 confirmation run: n=1000, seed=1, everything else identical to N33's
protocol (see n34_calibration.py's module docstring for the full protocol).

Purpose: n=100's default-tau claim (0.161, seed=0) and n=1000's (0.101,
seed=0) disagreed at width=0.01. This checks whether n=1000 itself is
reproducible under a second, independent seed — if seed=1 also lands near
0.101, that's confirmation the n=1000 value is real (not a one-off draw),
and n=100's disagreement is evidence n=100 under-resolves this width, per
N33's own reason for including the n=1000 check.

Not a new protocol — same grid, widths, trivial-tail rule, selection rule
as n34_calibration.py; only the seed changes. Fresh computation, no reuse of
any cached nRMSD (neither the diagnostic's outputs/nrmsd_cache/ nor the
seed=0 N34 run's in-memory arrays, which were never persisted).

Run standalone: python3 experiments/tau_calibration/n34_confirm_seed1.py
"""

from __future__ import annotations

import itertools
import time
from pathlib import Path

from n34_calibration import (
    CANDIDATE_WIDTHS,
    TAU_GRID,
    compute_pair_nrmsd,
    plot_nrmsd_distributions,
    plot_stability_curve,
    sample_chains,
    select_default_tau,
)
from tau_calibration import change_cumsum, k_matrix_for_grid, pair_nrmsd_matrix, plateau_table
from tau_ensemble_timing import build_experiment_context, run_all_pipelines

OUTPUT_DIR = Path(__file__).parent / "outputs" / "n34"
N = 1000
SEED = 1


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print("=== Building experiment context and running all 2,058 pipelines (fresh, real) ===")
    experiment = build_experiment_context()
    configs = experiment.configs
    all_labels = [c.label for c in configs]
    configs_by_label = {c.label: c for c in configs}

    t0 = time.perf_counter()
    results = run_all_pipelines(configs, experiment.shared_cec, experiment.shared_adr, experiment.defaults)
    print(f"Pipelines done in {time.perf_counter() - t0:.1f} s")

    print(f"\n=== N34 confirmation run: n={N} (fresh random sample, seed={SEED}) ===")
    sampled_labels = sample_chains(all_labels, N, SEED)
    pairs = list(itertools.combinations(sampled_labels, 2))
    print(f"Sampled {N} chains -> {len(pairs):,} exhaustive pairs")

    t0 = time.perf_counter()
    pair_nrmsd = compute_pair_nrmsd(pairs, configs_by_label, results, experiment.daylight)
    nrmsd_matrix, _ = pair_nrmsd_matrix(pair_nrmsd)
    print(f"Fresh nRMSD computed in {time.perf_counter() - t0:.1f} s")

    k_matrix = k_matrix_for_grid(nrmsd_matrix, TAU_GRID)
    cumsum = change_cumsum(k_matrix)
    table = plateau_table(k_matrix, TAU_GRID, CANDIDATE_WIDTHS)

    print(f"Plateau table (n={N}, seed={SEED}):")
    for c in table:
        print(
            f"  width={c.width:.3f}  best=[{c.lo:.3f},{c.hi:.3f}]  "
            f"centre={c.centre:.3f}  stable_fraction={c.stable_fraction:.3f}"
        )

    default = select_default_tau(table)
    if default is not None:
        print(
            f"N33 default tau (n={N}, seed={SEED}): {default.centre:.4f}  "
            f"(width={default.width}, stable_fraction={default.stable_fraction:.3f})"
        )
    else:
        print(f"N33 default tau (n={N}, seed={SEED}): NONE of the candidate widths reached 0.99")

    plot_stability_curve(N, cumsum, OUTPUT_DIR / f"n34_stability_curve_n{N}_seed{SEED}.png")
    plot_nrmsd_distributions(N, nrmsd_matrix, OUTPUT_DIR / f"n34_nrmsd_distribution_n{N}_seed{SEED}.png")
    print(f"\nFigures written to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
