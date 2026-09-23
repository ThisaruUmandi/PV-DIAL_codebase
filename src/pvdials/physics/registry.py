"""Researcher-authored mapping of candidate models to stages.

pvlib has no stage metadata: which function belongs to which stage, and
whether it fits that stage's slot, is decided here by the researcher.
Pools are tuples in a fixed POOL ORDER. Nothing here sorts or ranks.
"""

from __future__ import annotations

from dataclasses import dataclass

from pvdials.types import Stage


@dataclass(frozen=True)
class CandidateModel:
    """One candidate model for a stage.

    reason: plain statement of why a model can't be selected; None if selectable.
    """

    name: str
    stage: Stage
    selectable: bool = True
    reason: str | None = None


def _selectable(name: str, stage: Stage) -> CandidateModel:
    return CandidateModel(name, stage)


def _shown(name: str, stage: Stage, reason: str) -> CandidateModel:
    return CandidateModel(name, stage, selectable=False, reason=reason)


_S1 = Stage.DECOMPOSITION

# Stage 1 fit check, 23/09: Stage 1 takes GHI (plus the shared site context) only.
STAGE_POOLS: dict[Stage, tuple[CandidateModel, ...]] = {
    Stage.DECOMPOSITION: (
        _selectable("erbs", _S1),
        _selectable("erbs_driesse", _S1),
        _selectable("disc", _S1),
        _selectable("dirint", _S1),
        _shown("dirindex", _S1, "needs clear-sky GHI and DNI; not derivable from GHI alone"),
        _selectable("boland", _S1),
        _selectable("louche", _S1),
        _selectable("orgill_hollands", _S1),
        _shown("campbell_norman", _S1, "needs atmospheric transmittance, not GHI"),
        _shown("gti_dirint", _S1, "needs plane-of-array irradiance, not GHI"),
    ),
}


def stage_pool(stage: Stage) -> tuple[CandidateModel, ...]:
    """All candidates for a stage, selectable or not, in pool order."""
    return STAGE_POOLS[stage]


def get_candidate(stage: Stage, name: str) -> CandidateModel | None:
    for candidate in STAGE_POOLS[stage]:
        if candidate.name == name:
            return candidate
    return None
