"""Phase 2: propagation profile (KT §8.3).

Reads Phase 1's nRMSD values only. No new measurement, no new pipeline runs.
"""

from __future__ import annotations

from dataclasses import dataclass

from pvdials.dla.phase1 import PairPhase1Result
from pvdials.types import Stage

_STAGES_IN_ORDER = (Stage.DECOMPOSITION, Stage.TRANSPOSITION, Stage.TEMPERATURE, Stage.DC, Stage.AC)


@dataclass(frozen=True)
class Phase2Result:
    """The data behind "one chart, three pair curves" (KT §8.3) — the chart
    itself is Step 11/12's job. Never per-pipeline curves: a single pipeline
    has no disagreement value.
    """

    pair_nrmsd: dict[tuple[str, str], dict[Stage, float]]
    mean_nrmsd: dict[Stage, float]
    max_nrmsd: dict[Stage, float]
    delta: dict[Stage, float]


def run_phase2(
    ab: PairPhase1Result, ac: PairPhase1Result, bc: PairPhase1Result
) -> Phase2Result:
    """Aggregate the three pairs' Phase 1 nRMSD values into the propagation profile."""
    pairs = (ab, ac, bc)
    pair_nrmsd = {
        pair.pair: {stage: pair.metrics[stage].nrmsd for stage in _STAGES_IN_ORDER}
        for pair in pairs
    }

    mean_nrmsd: dict[Stage, float] = {}
    max_nrmsd: dict[Stage, float] = {}
    for stage in _STAGES_IN_ORDER:
        values = [pair.metrics[stage].nrmsd for pair in pairs]
        mean_nrmsd[stage] = sum(values) / len(values)
        max_nrmsd[stage] = max(values)

    delta: dict[Stage, float] = {}
    previous_mean = 0.0  # mean_nRMSD[0] = 0 (KT §8.3)
    for stage in _STAGES_IN_ORDER:
        delta[stage] = mean_nrmsd[stage] - previous_mean
        previous_mean = mean_nrmsd[stage]

    return Phase2Result(
        pair_nrmsd=pair_nrmsd, mean_nrmsd=mean_nrmsd, max_nrmsd=max_nrmsd, delta=delta
    )
