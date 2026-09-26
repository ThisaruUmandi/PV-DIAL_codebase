"""General-purpose τ-plateau / k-stability code (N33/N34 support).

Not itself N34's pre-registered calibration run — a reusable building block
any script (this folder's diagnostic convergence check, or eventually N34
itself) can call with its own grid/width/stability parameters. Nothing here
hard-codes a specific tau-selection rule; callers decide how to read the
width/stability trade-off table plateau_table() returns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from pvdials.types import Stage

# Canonical Phase-1 stage order (KT §8.2) — mirrors dla/phase1.py's own
# _STAGES_IN_ORDER exactly. Kept as a separate constant (not imported) since
# k_for_tau() below operates on a plain nrmsd dict, not a PairPhase1Result;
# tau_calibration_convergence.py's smoke check cross-verifies the two
# implementations agree on real data, so this can't silently drift unnoticed.
STAGE_ORDER = (Stage.DECOMPOSITION, Stage.TRANSPOSITION, Stage.TEMPERATURE, Stage.DC, Stage.AC)


def k_for_tau(nrmsd_by_stage: dict[Stage, float], tau: float) -> Stage | None:
    """The first stage (canonical order) whose nRMSD exceeds tau, else None
    (KT's outcome 1, nothing to diagnose, in dla/phase1.py's own terms).
    """
    for stage in STAGE_ORDER:
        if nrmsd_by_stage[stage] > tau:
            return stage
    return None


def pair_nrmsd_matrix(pair_nrmsd: dict[Any, dict[Stage, float]]) -> tuple[np.ndarray, list]:
    """Packs {pair: {stage: nrmsd}} into a (n_pairs, 5) array, canonical stage order."""
    pairs = list(pair_nrmsd.keys())
    matrix = np.array([[pair_nrmsd[p][stage] for stage in STAGE_ORDER] for p in pairs], dtype=float)
    return matrix, pairs


def k_matrix_for_grid(nrmsd_matrix: np.ndarray, tau_grid: np.ndarray) -> np.ndarray:
    """(n_pairs, n_grid) int8 array: index (0-4) of the first stage exceeding
    tau at that grid point, or -1 if none.

    One vectorized comparison per grid point, so cost scales with grid size,
    not grid size x pair count in a Python loop — this is what keeps it fast
    even at millions of pairs.
    """
    n_pairs = nrmsd_matrix.shape[0]
    k = np.full((n_pairs, len(tau_grid)), -1, dtype=np.int8)
    for j, tau in enumerate(tau_grid):
        exceeds = nrmsd_matrix > tau
        any_exceed = exceeds.any(axis=1)
        first_idx = exceeds.argmax(axis=1)  # first True; meaningless where any_exceed is False
        k[:, j] = np.where(any_exceed, first_idx, -1)
    return k


def change_cumsum(k_matrix: np.ndarray) -> np.ndarray:
    """cumsum[:, j] = number of k-changes among grid columns 1..j (0 at column 0).

    Lets stable_fraction() answer any window query in O(n_pairs) rather than
    O(n_pairs x window width) — needed since window widths span up to ~100
    grid steps and get queried thousands of times across a sweep.
    """
    changes = k_matrix[:, 1:] != k_matrix[:, :-1]
    cumsum = np.zeros(k_matrix.shape, dtype=np.int32)
    cumsum[:, 1:] = np.cumsum(changes, axis=1)
    return cumsum


def stable_fraction(cumsum: np.ndarray, lo_idx: int, hi_idx: int) -> float:
    """Fraction of pairs whose k never changed between grid columns lo_idx and hi_idx."""
    return float((cumsum[:, hi_idx] == cumsum[:, lo_idx]).mean())


def stable_fraction_curve(
    cumsum: np.ndarray, tau_grid: np.ndarray, width_steps: int
) -> tuple[np.ndarray, np.ndarray]:
    """Sliding-window stable_fraction across the whole grid at a fixed width, for plotting."""
    n_positions = len(tau_grid) - width_steps
    centres = np.empty(n_positions, dtype=float)
    fractions = np.empty(n_positions, dtype=float)
    for lo in range(n_positions):
        hi = lo + width_steps
        centres[lo] = (tau_grid[lo] + tau_grid[hi]) / 2
        fractions[lo] = stable_fraction(cumsum, lo, hi)
    return centres, fractions


@dataclass(frozen=True)
class PlateauCandidate:
    """One candidate window width's best placement (see plateau_table)."""

    width: float
    lo: float
    hi: float
    centre: float
    stable_fraction: float


def plateau_table(
    k_matrix: np.ndarray, tau_grid: np.ndarray, candidate_widths: list[float]
) -> list[PlateauCandidate]:
    """Best placement per candidate width — the width/stability trade-off,
    not one auto-picked tau. As the window widens, the achievable
    stable_fraction can only fall, so there is no single "widest AND most
    stable" answer; this returns one point per width and leaves the
    trade-off reading to the caller (KT's own tie-break rule isn't written
    down anywhere available here, so none is hard-coded).

    Excludes the trivial high-tau tail: k(tau) is monotonic per pair (raising
    tau can only push k later or to None), so once tau exceeds every pair's
    largest per-stage nRMSD, k is None for everyone, permanently — and
    stable_fraction locks at 1.0 forever from that point on. That lock-in
    point is provable, not a chosen constant, and it's width-specific (a wider
    window needs its own left edge past the lock-in point too, so it locks in
    later than a narrow one — confirmed empirically: width=0.01 locks in
    around tau=0.22-0.25, width=0.2 not until tau=0.32-0.33, on real data).
    The search for "best" is restricted to at-or-before the last index where
    the curve is still below 1.0, per width, so a plateau deep in that empty
    tail can never win by default.
    """
    cumsum = change_cumsum(k_matrix)
    step = tau_grid[1] - tau_grid[0]
    results = []
    for width in candidate_widths:
        width_steps = max(1, round(width / step))
        if width_steps >= len(tau_grid):
            continue
        centres, fractions = stable_fraction_curve(cumsum, tau_grid, width_steps)
        below_one = np.where(fractions < 1.0)[0]
        if len(below_one) == 0:
            # Never dips below 1.0 anywhere in the grid — every pair's k is
            # already constant across the whole range tested. Nothing to
            # exclude; search the full curve and flag it via stable_fraction=1.0.
            search_limit = len(fractions) - 1
        else:
            search_limit = int(below_one[-1])
        best_idx = int(np.argmax(fractions[: search_limit + 1]))
        results.append(
            PlateauCandidate(
                width=width,
                lo=float(centres[best_idx] - width / 2),
                hi=float(centres[best_idx] + width / 2),
                centre=float(centres[best_idx]),
                stable_fraction=float(fractions[best_idx]),
            )
        )
    return results
