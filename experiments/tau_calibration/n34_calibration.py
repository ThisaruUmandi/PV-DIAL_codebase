"""N34 — the pre-registered τ-calibration run (N33's protocol, implemented
exactly as written). This is N34 itself, not the earlier diagnostic
convergence check (tau_calibration_convergence.py) — it uses a fresh random
sample and fresh real computation; none of the diagnostic run's cached
nRMSD matrices (outputs/nrmsd_cache/) are read here.

N33's protocol, verbatim parameters:
- Sample: a fresh random sample of 100 chains from the full 2,058-chain
  valid population, seed=0 (random.Random(0)). Also n=1000, same
  population, fresh random sample, same seed=0, to confirm any
  fine-grained claim (N33's ensemble-size justification: n=100 for the
  coarse default, n=1000 to confirm fine-grained values).
- tau grid: numpy.linspace(0.0, 1.0, 501).
- Candidate window widths: [0.01, 0.02, 0.05, 0.1, 0.2] tau-units.
- Stability measure: the fraction of pairs whose first-emergence stage
  k(tau) is identical across every tau in the candidate window.
- Trivial-tail exclusion (per width): the smallest tau at which
  stable_fraction first reaches 1.0 and never drops below it again for the
  rest of the grid; plateau selection is restricted to tau below that
  point. (This is exactly tau_calibration.plateau_table()'s existing rule,
  already verified against real run_phase1() output in the diagnostic run.)
- Default tau: the centre of the plateau reported at the smallest
  candidate width whose restricted-range stable_fraction reaches >= 0.99.

Run standalone: python3 experiments/tau_calibration/n34_calibration.py
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
    STAGE_ORDER,
    change_cumsum,
    k_matrix_for_grid,
    pair_nrmsd_matrix,
    plateau_table,
    stable_fraction_curve,
)
from tau_ensemble_timing import build_experiment_context, run_all_pipelines

from pvdials.dla.phase1 import run_phase1

OUTPUT_DIR = Path(__file__).parent / "outputs" / "n34"
TAU_GRID = np.linspace(0.0, 1.0, 501)  # N33
CANDIDATE_WIDTHS = [0.01, 0.02, 0.05, 0.1, 0.2]  # N33, ascending — order matters for select_default_tau
SEED = 0  # N33
ENSEMBLE_SIZES = [100, 1000]  # N33
DEFAULT_TAU_STABLE_THRESHOLD = 0.99  # N33


def sample_chains(all_labels: list[str], n: int, seed: int) -> list[str]:
    """A fresh random sample of n chains, per N33 (not the deterministic
    prefix used by the earlier diagnostic convergence check).
    """
    rng = random.Random(seed)
    return rng.sample(all_labels, n)


def compute_pair_nrmsd(pairs, configs_by_label, results, daylight):
    """Real run_phase1() per pair (tau_value=0.0 placeholder — only the
    per-stage nRMSD values are kept; k is computed properly per grid point
    by k_matrix_for_grid(), not read from this placeholder call).
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


def select_default_tau(table):
    """N33's rule: the centre of the plateau at the smallest candidate width
    whose restricted-range stable_fraction reaches >= 0.99. `table` must be
    in ascending-width order (plateau_table preserves candidate_widths' order).
    """
    for candidate in table:
        if candidate.stable_fraction >= DEFAULT_TAU_STABLE_THRESHOLD:
            return candidate
    return None


def plot_stability_curve(n: int, cumsum: np.ndarray, out_path: Path) -> None:
    fig, ax = plt.subplots()
    step = TAU_GRID[1] - TAU_GRID[0]
    for width in CANDIDATE_WIDTHS:
        width_steps = max(1, round(width / step))
        centres, fractions = stable_fraction_curve(cumsum, TAU_GRID, width_steps)
        ax.plot(centres, fractions, label=f"width={width}")
    ax.set_xlabel("Candidate threshold value (τ)")
    ax.set_ylabel("Share of pairs giving the same answer (stable fraction)")
    ax.set_title(f"N34: stability vs τ, n={n} chains")
    ax.legend()
    ax.set_ylim(0, 1.02)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_nrmsd_distributions(n: int, nrmsd_matrix: np.ndarray, out_path: Path) -> None:
    fig, axes = plt.subplots(1, 5, figsize=(20, 4))
    for i, stage in enumerate(STAGE_ORDER):
        axes[i].hist(nrmsd_matrix[:, i], bins=50)
        axes[i].set_title(stage.name)
        axes[i].set_xlabel("nRMSD")
    axes[0].set_ylabel("pair count")
    fig.suptitle(f"N34: per-stage nRMSD distribution, n={n} chains ({nrmsd_matrix.shape[0]:,} pairs)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


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

    default_taus = {}
    for n in ENSEMBLE_SIZES:
        print(f"\n=== N34 run: n={n} (fresh random sample, seed={SEED}) ===")
        sampled_labels = sample_chains(all_labels, n, SEED)
        pairs = list(itertools.combinations(sampled_labels, 2))
        print(f"Sampled {n} chains -> {len(pairs):,} exhaustive pairs")

        t0 = time.perf_counter()
        pair_nrmsd = compute_pair_nrmsd(pairs, configs_by_label, results, experiment.daylight)
        nrmsd_matrix, _ = pair_nrmsd_matrix(pair_nrmsd)
        print(f"Fresh nRMSD computed in {time.perf_counter() - t0:.1f} s")

        k_matrix = k_matrix_for_grid(nrmsd_matrix, TAU_GRID)
        cumsum = change_cumsum(k_matrix)
        table = plateau_table(k_matrix, TAU_GRID, CANDIDATE_WIDTHS)

        print(f"Plateau table (n={n}):")
        for c in table:
            print(
                f"  width={c.width:.3f}  best=[{c.lo:.3f},{c.hi:.3f}]  "
                f"centre={c.centre:.3f}  stable_fraction={c.stable_fraction:.3f}"
            )

        default = select_default_tau(table)
        default_taus[n] = default
        if default is not None:
            print(
                f"N33 default tau (n={n}): {default.centre:.4f}  "
                f"(width={default.width}, stable_fraction={default.stable_fraction:.3f})"
            )
        else:
            print(
                f"N33 default tau (n={n}): NONE of the candidate widths reached "
                f"stable_fraction >= {DEFAULT_TAU_STABLE_THRESHOLD}"
            )

        plot_stability_curve(n, cumsum, OUTPUT_DIR / f"n34_stability_curve_n{n}.png")
        plot_nrmsd_distributions(n, nrmsd_matrix, OUTPUT_DIR / f"n34_nrmsd_distribution_n{n}.png")

    print("\n=== Summary ===")
    for n, default in default_taus.items():
        if default is not None:
            print(f"n={n}: default tau = {default.centre:.4f} (width={default.width}, stable_fraction={default.stable_fraction:.3f})")
        else:
            print(f"n={n}: no width reached the {DEFAULT_TAU_STABLE_THRESHOLD} threshold")
    print(f"\nFigures written to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
