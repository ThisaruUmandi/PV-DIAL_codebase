"""Amends N33/N34's plateau-selection rule with two new exclusion regions
(28/09 pre-registered amendment). Analysis only -- no changes to dla/,
run_defaults.yaml, or any other production code.

New rule (on top of N33's existing high-tau tail exclusion, already in
tau_calibration.plateau_table()):

- Near-trivial HIGH region: tau where >= 99% of pairs are outcome 1
  (k = None, i.e. k_matrix's -1 sentinel).
- Near-trivial LOW region: tau where >= 99% of pairs have
  k = min(S), S being the set of stages where the two chains use different
  models (dla.phase1._differing_stages). At very small tau, almost every
  pair's first differing stage already "exceeds" tau trivially, so k just
  reports where the two chains first diverge structurally -- not a
  meaningful diagnosis.

Both regions are excluded from plateau-window placement (a window only
competes for best-placement if its centre clears BOTH new regions AND
N33's existing tail cutoff). Grid, widths, and the final default-tau
selection rule (smallest width clearing stable_fraction >= 0.99) are
otherwise exactly N33's.

Data source note (28/09 discovery, see chat): the pre-existing
outputs/nrmsd_cache/nrmsd_matrix_n1000.npy is NOT N34 data -- it comes from
tau_calibration_convergence.py's deterministic-prefix sampling
(labels[:1000]), a different script with a different sampling procedure
than N34's own random.Random(seed).sample(...). N34 itself never persists
its matrix. So both seed=0 and seed=1 here are computed fresh via N34's own
real sample_chains() procedure (n34_calibration.py / n34_confirm_seed1.py),
never from that mismatched cache -- otherwise "do both seeds agree" would
really be testing "does a random sample agree with a deterministic prefix",
not a real seed check. This still only pays N34's own already-established
n=1000 cost (run the 2,058 pipelines once, then two pairwise nRMSD passes
of 499,500 pairs each) -- not the separately-gated ~205 min exhaustive-pair
run.

Run standalone: python3 experiments/tau_calibration/trivial_plateau_amendment.py
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch
from n34_calibration import (
    CANDIDATE_WIDTHS,
    DEFAULT_TAU_STABLE_THRESHOLD,
    TAU_GRID,
    sample_chains,
)
from n34_calibration import (
    SEED as N34_SEED,
)
from tau_calibration import (
    change_cumsum,
    k_matrix_for_grid,
    pair_nrmsd_matrix,
    stable_fraction_curve,
)
from tau_ensemble_timing import build_experiment_context, run_all_pipelines

from pvdials.dla.phase1 import _differing_stages, run_phase1

assert N34_SEED == 0, "n34_calibration.SEED changed underneath this script's seed-0 assumption"

OUTPUT_DIR = Path(__file__).parent / "outputs" / "trivial_plateau_amendment"
N = 1000
SEEDS = [0, 1]
TRIVIAL_THRESHOLD = 0.99  # new rule's own threshold, same value as N33's DEFAULT_TAU_STABLE_THRESHOLD


@dataclass(frozen=True)
class AmendedPlateauCandidate:
    width: float
    lo: float | None
    hi: float | None
    centre: float | None
    stable_fraction: float | None  # None: every window at this width was excluded


def min_differing_stage_index(pairs, configs_by_label) -> np.ndarray:
    """Per pair, 0-4 index (Stage.value - 1) of the first (lowest-numbered)
    stage where the two chains' models differ -- min(S).
    """
    idx = np.empty(len(pairs), dtype=np.int8)
    for i, (label_a, label_b) in enumerate(pairs):
        s = _differing_stages(configs_by_label[label_a], configs_by_label[label_b])
        assert s, f"pair {(label_a, label_b)} has no differing stage -- two chains are identical"
        idx[i] = min(s).value - 1
    return idx


def compute_pair_nrmsd_with_progress(pairs, configs_by_label, results, daylight, log_every=25_000):
    """Same computation as n34_calibration.compute_pair_nrmsd (real run_phase1()
    per pair, tau_value=0.0 placeholder -- only the per-stage nRMSD values are
    kept), with periodic flushed progress output.

    run_phase1() measured directly at ~6 ms/pair on this machine, so 499,500
    pairs is a genuine ~50 min of unavoidable compute (N34's own established
    per-pair cost, not a bug) -- without progress output this looks
    indistinguishable from a hang. flush=True matters here specifically
    because this script is normally run piped through `tee` for logging;
    piped stdout is block-buffered by default, so plain print() can sit
    invisible in the buffer for the entire run (confirmed 28/09: an earlier
    run looked stalled for 127+ minutes purely from this, not real hang).
    """
    pair_nrmsd = {}
    t0 = time.perf_counter()
    total = len(pairs)
    for i, (label_a, label_b) in enumerate(pairs):
        result = run_phase1(
            configs_by_label[label_a],
            results[label_a],
            configs_by_label[label_b],
            results[label_b],
            daylight,
            tau_value=0.0,
        )
        pair_nrmsd[(label_a, label_b)] = {stage: m.nrmsd for stage, m in result.metrics.items()}
        if (i + 1) % log_every == 0 or (i + 1) == total:
            elapsed = time.perf_counter() - t0
            rate = (i + 1) / elapsed
            remaining = (total - (i + 1)) / rate if rate > 0 else float("nan")
            print(
                f"  run_phase1 progress: {i + 1:,}/{total:,} pairs  "
                f"elapsed={elapsed:.1f}s  eta={remaining:.1f}s",
                flush=True,
            )
    return pair_nrmsd


def trivial_region_masks(k_matrix: np.ndarray, min_s_idx: np.ndarray, valid_mask: np.ndarray):
    """Per-tau share of outcome-1 pairs and share with k=min(S), over
    NaN-free pairs only, plus the two >=99% boolean exclusion masks.
    """
    k_valid = k_matrix[valid_mask]
    share_outcome1 = (k_valid == -1).mean(axis=0)
    share_k_eq_minS = (k_valid == min_s_idx[valid_mask, None]).mean(axis=0)
    near_trivial_high = share_outcome1 >= TRIVIAL_THRESHOLD
    near_trivial_low = share_k_eq_minS >= TRIVIAL_THRESHOLD
    return share_outcome1, share_k_eq_minS, near_trivial_high, near_trivial_low


def amended_plateau_table(
    cumsum: np.ndarray,
    tau_grid: np.ndarray,
    candidate_widths: list[float],
    near_trivial_high: np.ndarray,
    near_trivial_low: np.ndarray,
) -> list[AmendedPlateauCandidate]:
    """Same placement search as tau_calibration.plateau_table(), plus: a
    window's centre must also fall outside both new near-trivial regions.
    Both region masks are interpolated (nearest via >=0.5 threshold on the
    linearly-interpolated boolean-as-float) since a window centre need not
    land exactly on a tau_grid point when width_steps is odd.

    Takes a precomputed change_cumsum(k_matrix) rather than k_matrix itself
    (unlike tau_calibration.plateau_table) so a caller that also needs cumsum
    for its own stability-curve plot computes it exactly once -- at the
    exhaustive C(2058,2)-pair scale this array alone is multiple GB, so
    computing it twice is a real cost, not just a style nit.
    """
    step = tau_grid[1] - tau_grid[0]
    excluded_at_grid = (near_trivial_high | near_trivial_low).astype(float)
    results = []
    for width in candidate_widths:
        width_steps = max(1, round(width / step))
        if width_steps >= len(tau_grid):
            continue
        centres, fractions = stable_fraction_curve(cumsum, tau_grid, width_steps)
        below_one = np.where(fractions < 1.0)[0]
        tail_limit = len(fractions) - 1 if len(below_one) == 0 else int(below_one[-1])

        excluded_at_centre = np.interp(centres, tau_grid, excluded_at_grid) >= 0.5
        allowed = ~excluded_at_centre
        allowed[tail_limit + 1 :] = False

        candidate_idx = np.where(allowed)[0]
        if len(candidate_idx) == 0:
            results.append(AmendedPlateauCandidate(width=width, lo=None, hi=None, centre=None, stable_fraction=None))
            continue
        best_idx = int(candidate_idx[np.argmax(fractions[candidate_idx])])
        results.append(
            AmendedPlateauCandidate(
                width=width,
                lo=float(centres[best_idx] - width / 2),
                hi=float(centres[best_idx] + width / 2),
                centre=float(centres[best_idx]),
                stable_fraction=float(fractions[best_idx]),
            )
        )
    return results


def select_default_tau(table: list[AmendedPlateauCandidate]) -> AmendedPlateauCandidate | None:
    for candidate in table:
        if candidate.stable_fraction is not None and candidate.stable_fraction >= DEFAULT_TAU_STABLE_THRESHOLD:
            return candidate
    return None


def contiguous_spans(mask: np.ndarray, grid: np.ndarray) -> list[tuple[float, float]]:
    """(start, end) tau-value spans of contiguous True runs in mask, for axvspan."""
    spans = []
    in_span = False
    start = None
    for i, flag in enumerate(mask):
        if flag and not in_span:
            in_span = True
            start = grid[i]
        elif not flag and in_span:
            in_span = False
            spans.append((start, grid[i - 1]))
    if in_span:
        spans.append((start, grid[-1]))
    return spans


def plot_amended_stability_curve(
    n: int, seed: int, cumsum: np.ndarray, near_trivial_high: np.ndarray, near_trivial_low: np.ndarray, out_path: Path
) -> None:
    fig, ax = plt.subplots()
    step = TAU_GRID[1] - TAU_GRID[0]
    for width in CANDIDATE_WIDTHS:
        width_steps = max(1, round(width / step))
        centres, fractions = stable_fraction_curve(cumsum, TAU_GRID, width_steps)
        ax.plot(centres, fractions, label=f"width={width}")

    for lo, hi in contiguous_spans(near_trivial_low, TAU_GRID):
        ax.axvspan(lo, hi, color="tab:orange", alpha=0.15)
    for lo, hi in contiguous_spans(near_trivial_high, TAU_GRID):
        ax.axvspan(lo, hi, color="tab:red", alpha=0.15)
    ax.axvline(0.234, color="black", linestyle="--", linewidth=1, label="tau=0.234 (N34)")

    handles, labels = ax.get_legend_handles_labels()
    if near_trivial_low.any():
        handles.append(Patch(color="tab:orange", alpha=0.15))
        labels.append("near-trivial LOW (>=99% k=min(S))")
    if near_trivial_high.any():
        handles.append(Patch(color="tab:red", alpha=0.15))
        labels.append("near-trivial HIGH (>=99% outcome 1)")

    ax.set_xlabel("Candidate threshold value (τ)")
    ax.set_ylabel("Share of pairs giving the same answer (stable fraction)")
    ax.set_title(f"Amended plateau selection: stability vs τ, n={n} chains, seed={seed}")
    ax.legend(handles, labels, fontsize="small")
    ax.set_ylim(0, 1.02)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def run_for_seed(seed: int, all_labels, configs_by_label, results, daylight) -> dict:
    print(f"\n=== seed={seed} (n={N}, N34's own random sample_chains procedure) ===", flush=True)
    sampled_labels = sample_chains(all_labels, N, seed)
    pairs = list(itertools.combinations(sampled_labels, 2))
    print(f"Sampled {N} chains -> {len(pairs):,} exhaustive pairs", flush=True)

    t0 = time.perf_counter()
    pair_nrmsd = compute_pair_nrmsd_with_progress(pairs, configs_by_label, results, daylight)
    nrmsd_matrix, ordered_pairs = pair_nrmsd_matrix(pair_nrmsd)
    print(f"nRMSD computed in {time.perf_counter() - t0:.1f} s", flush=True)

    nan_mask = np.isnan(nrmsd_matrix).any(axis=1)
    nan_count = int(nan_mask.sum())
    valid_mask = ~nan_mask
    print(f"NaN-affected pairs: {nan_count} / {len(ordered_pairs):,}")

    min_s_idx = min_differing_stage_index(ordered_pairs, configs_by_label)

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
        f"in_near_trivial_high={in_high_at_0234}"
    )

    # Only over NaN-free rows: a NaN row's k_matrix entries are trivially -1
    # everywhere (k_matrix_for_grid treats NaN>tau as False), which would
    # falsely read as "perfectly stable outcome-1" and contaminate both the
    # trivial-region shares above and the plateau search below if included.
    k_valid = k_matrix[valid_mask]
    cumsum = change_cumsum(k_valid)
    table = amended_plateau_table(cumsum, TAU_GRID, CANDIDATE_WIDTHS, near_trivial_high, near_trivial_low)

    print("Amended plateau table:")
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
            f"Amended default tau: {default.centre:.4f}  "
            f"(width={default.width}, stable_fraction={default.stable_fraction:.3f})"
        )
    else:
        print(f"Amended default tau: no width reaches stable_fraction >= {DEFAULT_TAU_STABLE_THRESHOLD}")

    max_nrmsd = np.nanmax(nrmsd_matrix[valid_mask], axis=1)
    print(
        f"Per-pair max-stage nRMSD: median={np.median(max_nrmsd):.4f}  "
        f"P90={np.percentile(max_nrmsd, 90):.4f}  P99={np.percentile(max_nrmsd, 99):.4f}  "
        f"max={max_nrmsd.max():.4f}"
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plot_amended_stability_curve(
        N, seed, cumsum, near_trivial_high, near_trivial_low,
        OUTPUT_DIR / f"amended_stability_curve_n{N}_seed{seed}.png",
    )

    return {
        "seed": seed,
        "nan_count": nan_count,
        "n_pairs": len(ordered_pairs),
        "share_outcome1_at_0234": float(share_outcome1[idx_0234]),
        "share_k_eq_minS_at_0234": float(share_k_eq_minS[idx_0234]),
        "in_near_trivial_high_at_0234": in_high_at_0234,
        "table": table,
        "default": default,
        "max_nrmsd_stats": {
            "median": float(np.median(max_nrmsd)),
            "P90": float(np.percentile(max_nrmsd, 90)),
            "P99": float(np.percentile(max_nrmsd, 99)),
            "max": float(max_nrmsd.max()),
        },
    }


def main() -> None:
    print("=== Building experiment context and running all 2,058 pipelines (fresh, real) ===", flush=True)
    experiment = build_experiment_context()
    configs = experiment.configs
    all_labels = [c.label for c in configs]
    configs_by_label = {c.label: c for c in configs}

    t0 = time.perf_counter()
    results = run_all_pipelines(configs, experiment.shared_cec, experiment.shared_adr, experiment.defaults)
    print(f"Pipelines done in {time.perf_counter() - t0:.1f} s (measured directly: ~196s baseline)", flush=True)

    seed_results = {}
    for seed in SEEDS:
        seed_results[seed] = run_for_seed(seed, all_labels, configs_by_label, results, experiment.daylight)

    print("\n=== Summary ===")
    for seed, r in seed_results.items():
        print(f"seed={seed}: NaN pairs={r['nan_count']}, in_near_trivial_high(0.234)={r['in_near_trivial_high_at_0234']}")
        if r["default"] is not None:
            print(f"  amended default tau = {r['default'].centre:.4f} (width={r['default'].width})")
        else:
            print("  amended default tau: no width reaches 0.99")
    both = list(seed_results.values())
    agree_on_0234 = both[0]["in_near_trivial_high_at_0234"] == both[1]["in_near_trivial_high_at_0234"]
    print(f"\nBoth seeds agree on whether tau=0.234 is near-trivial-high: {agree_on_0234}")
    print(f"\nFigures written to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
