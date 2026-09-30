"""Independent Shapley/OAT comparator functions (evaluation KT Step 2).

Deliberately does NOT import dla.phase3.shapley_values: the whole point of
"run these functions on the Colombo v tables and check phi matches
production's phi_final within ε" is a real cross-check against an
independent implementation, not the same function checked against itself.

Pure functions, no pvlib, no I/O. Never imported by src/pvdials/.
"""

from __future__ import annotations

import itertools
import math

from pvdials.types import Stage


def coalition_key(coalition: frozenset[Stage]) -> str:
    """Same format as analysis.py's private _coalition_key(): "EMPTY" for
    the empty set, else stage names joined by "+" in pipeline order.
    """
    ordered = [s.name for s in Stage if s in coalition]
    return "+".join(ordered) if ordered else "EMPTY"


def parse_coalition_key(key: str) -> frozenset[Stage]:
    """Inverse of coalition_key() / analysis.py's private _coalition_key():
    "EMPTY" -> empty set, else "DECOMPOSITION+TEMPERATURE" (pipeline stage
    order) -> the matching frozenset of Stage members.
    """
    if key == "EMPTY":
        return frozenset()
    return frozenset(Stage[name] for name in key.split("+"))


def shapley_values(v: dict[frozenset, float], players: tuple) -> dict:
    """The standard Shapley value: average marginal contribution over every
    coalition not containing i, weighted by |S|!(n-|S|-1)!/n! -- the
    closed-form equivalent of averaging over every ordering.
    """
    n = len(players)
    phi = {}
    for i in players:
        rest = [p for p in players if p != i]
        total = 0.0
        for size in range(len(rest) + 1):
            weight = math.factorial(size) * math.factorial(n - size - 1) / math.factorial(n)
            for combo in itertools.combinations(rest, size):
                s = frozenset(combo)
                total += weight * (v[s | {i}] - v[s])
        phi[i] = total
    return phi


def averaged_game(v_xy: dict[frozenset, float], v_yx: dict[frozenset, float]) -> dict:
    """w(T) = (v_xy(T) + v_yx(T)) / 2 for every coalition T present in both."""
    return {t: (v_xy[t] + v_yx[t]) / 2 for t in v_xy}


def singleton_reading(v: dict[frozenset, float], i) -> float:
    """v({i})."""
    return v[frozenset({i})]


def loo_reading(v: dict[frozenset, float], full_set: frozenset, i) -> float:
    """v(S) - v(S \\ {i}) -- what i adds last."""
    return v[full_set] - v[full_set - {i}]


def attribution_gap(readings: dict, v_s: float) -> float:
    """|sum(readings) - v(S)| / v(S) -- readings is either the singleton or
    the LOO reading per player, caller's choice. 0/0 (v(S)==0, readings also
    sum to ~0) is reported as 0, not a defensible ratio otherwise.
    """
    total = sum(readings.values())
    if v_s == 0:
        return 0.0 if abs(total) < 1e-12 else math.inf
    return abs(total - v_s) / abs(v_s)


def argmax_with_ties(values: dict, tie_tol: float = 1e-9) -> tuple[list, float]:
    """Every key within tie_tol (relative) of the true max -- len > 1 means
    a tie, per the KT's own instruction ("ties within 1e-9 relative
    reported as ties").
    """
    max_val = max(values.values())
    scale = max(abs(max_val), 1e-12)
    tied = [k for k, val in values.items() if abs(val - max_val) <= tie_tol * scale]
    return tied, max_val


def rank_agreement(phi: dict, readings: dict, tie_tol: float = 1e-9) -> str:
    """"agree" if phi's largest share and readings' largest name the same
    player, "disagree" if they name different ones, "tie" if either side is
    itself tied for the max.
    """
    phi_top, _ = argmax_with_ties(phi, tie_tol)
    reading_top, _ = argmax_with_ties(readings, tie_tol)
    if len(phi_top) > 1 or len(reading_top) > 1:
        return "tie"
    return "agree" if phi_top[0] == reading_top[0] else "disagree"


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Standard closed-form Wilson 95% interval (z=1.96) for a proportion."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z**2 / n
    center = p + z**2 / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
    lower = (center - margin) / denom
    upper = (center + margin) / denom
    return (max(0.0, lower), min(1.0, upper))
