"""Baseline A and Baseline B (evaluation KT, section 2) -- the two simpler
comparator methods Phase 1 is measured against. Pure functions, no pvlib.

Never imported by src/pvdials/.
"""

from __future__ import annotations

from pvdials.types import Stage

_STAGES_IN_ORDER = (Stage.DECOMPOSITION, Stage.TRANSPOSITION, Stage.TEMPERATURE, Stage.DC, Stage.AC)


def baseline_a_stage(differing_stages: frozenset[Stage]) -> Stage:
    """min(S): the first stage (in pipeline order) where the pair's models
    differ. Read off the configuration, no computation.
    """
    for stage in _STAGES_IN_ORDER:
        if stage in differing_stages:
            return stage
    raise ValueError("differing_stages is empty -- no S, min(S) undefined")


def informative_rate_parts(outcome: int, k: Stage | None, min_s: Stage) -> tuple[bool, bool]:
    """Whether Phase 1 differs from Baseline A, split into its two named
    parts: (a) outcome 1 (Phase 1 found nothing to diagnose at all), (b)
    k > min_s (Phase 1 found something, but later than Baseline A would).
    k < min_s never happens (property #4) -- not asserted here, callers that
    want that guard should check it themselves against their own data.
    """
    part_a = outcome == 1
    part_b = (not part_a) and k is not None and k > min_s
    return part_a, part_b


def baseline_b_stage(nrmsd_by_stage: dict[Stage, float]) -> Stage:
    """The stage with the largest single-step rise in nRMSD, nrmsd(0) = 0,
    rise(s) = nrmsd(s) - nrmsd(s-1) in pipeline order. Ties -> earliest
    stage (first occurrence of the max rise, not the last).
    """
    previous = 0.0
    best_stage = _STAGES_IN_ORDER[0]
    best_rise = None
    for stage in _STAGES_IN_ORDER:
        rise = nrmsd_by_stage[stage] - previous
        if best_rise is None or rise > best_rise:
            best_rise = rise
            best_stage = stage
        previous = nrmsd_by_stage[stage]
    return best_stage
