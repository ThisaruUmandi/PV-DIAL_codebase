"""Read-only summary of an R1 cache (never rewrites it):

  * how many 0.01-wide tau windows pass the amended plateau rule (centre
    outside both trivial regions, inside the tail limit, stable share >= the
    default threshold), and the lowest and highest stable share among them;
  * the Phase 1 shares at chosen tau values (share of all pairs that differs
    from Baseline A, outcome 1, k later, outcome 3).

Same functions as trivial_plateau_amendment_exhaustive.py, so the windows are
the ones the amended rule searched.

Usage (repo root): PVDIAL_OFFSET_H=0.5 python3 experiments/tau_calibration/r1_windows_and_tau_shares.py [tau ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from n34_calibration import DEFAULT_TAU_STABLE_THRESHOLD, TAU_GRID
from run_settings import output_dir, run_record
from tau_calibration import k_matrix_for_grid, stable_fraction_curve
from trivial_plateau_amendment import trivial_region_masks
from trivial_plateau_amendment_exhaustive import CACHE_DIR, change_cumsum_compact

WIDTH = 0.01
DEFAULT_TAUS = (0.05, 0.15, 0.2)
OUT = output_dir(Path(__file__).parent / "outputs" / "trivial_plateau_amendment", tau_specific=False) / "windows_and_tau_shares.json"


def shares_at(nrmsd: np.ndarray, min_s: np.ndarray, tau: float) -> dict:
    over = nrmsd > tau
    has = over.any(axis=1)
    k = np.where(has, over.argmax(axis=1), -1)
    n = len(nrmsd)
    outcome1, later = int((~has).sum()), int((has & (k > min_s)).sum())
    return {
        "differs_from_baseline_a_pct": (outcome1 + later) / n * 100,
        "outcome1_pct": outcome1 / n * 100,
        "k_later_pct": later / n * 100,
        "outcome3_pct": float((has & (nrmsd[:, 4] <= tau)).sum()) / n * 100,
        "outcome2_pct": float((has & (nrmsd[:, 4] > tau)).sum()) / n * 100,
    }


def main() -> None:
    taus = [float(t) for t in sys.argv[1:]] or list(DEFAULT_TAUS)
    nrmsd = np.load(CACHE_DIR / "nrmsd_matrix_n2058_exhaustive.npy")
    min_s = np.load(CACHE_DIR / "min_s_idx_n2058_exhaustive.npy")
    valid = ~np.isnan(nrmsd).any(axis=1)

    k_matrix = k_matrix_for_grid(nrmsd, TAU_GRID)
    _, _, high, low = trivial_region_masks(k_matrix, min_s, valid)
    cumsum = change_cumsum_compact(k_matrix[valid])
    del k_matrix

    step = TAU_GRID[1] - TAU_GRID[0]
    centres, fractions = stable_fraction_curve(cumsum, TAU_GRID, max(1, round(WIDTH / step)))
    below_one = np.where(fractions < 1.0)[0]
    tail_limit = len(fractions) - 1 if len(below_one) == 0 else int(below_one[-1])
    allowed = ~(np.interp(centres, TAU_GRID, (high | low).astype(float)) >= 0.5)
    allowed[tail_limit + 1:] = False
    passed = allowed & (fractions >= DEFAULT_TAU_STABLE_THRESHOLD)

    out = {
        "n_pairs": int(len(nrmsd)),
        "window_width": WIDTH,
        "windows_searched": int(len(centres)),
        "windows_allowed_by_trivial_and_tail_rules": int(allowed.sum()),
        "windows_passing": int(passed.sum()),
        "stable_share_lowest": float(fractions[passed].min()) if passed.any() else None,
        "stable_share_highest": float(fractions[passed].max()) if passed.any() else None,
        "passing_centres_range": [float(centres[passed].min()), float(centres[passed].max())] if passed.any() else None,
        "threshold": DEFAULT_TAU_STABLE_THRESHOLD,
        "shares": {f"{t:g}": shares_at(nrmsd, min_s, t) for t in taus},
    }
    OUT.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
