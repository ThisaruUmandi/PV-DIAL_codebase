"""DLA metrics (KT §8.1): RMSD, nRMSD, MAD, MBD, systematic_share.

Deviation names throughout (Path A rule 1): disagreement between two
pipelines is not treated as a defect, so every identifier here names a
deviation, never the more familiar three-letter metric names that imply one
pipeline is the reference.

nRMSD and raw RMSD decide (KT §8.1); MAD, MBD and systematic_share only
describe. Never gate on them — only Phase 1 (nRMSD vs tau) gates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from pvdials.physics.pipeline import StageOutputs
from pvdials.types import Stage

TAG_DEFAULT = "default"
TAG_USER_ENTERED = "user_entered"

# Percentile positions nRMSD's denominator is built from (KT §8.1). Named so
# N_MIN below is derived from them, not a separately chosen number.
P5_QUANTILE = 0.05
P95_QUANTILE = 0.95

# Smallest pooled sample size at which P5 no longer reduces to pandas' linear
# interpolation between just the two smallest pooled values (28/09, found via
# a real degenerate case: at n=2, P5 = min + 0.05*(max-min) and P95 = min +
# 0.95*(max-min), giving P95-P5 = 0.9*|a-b| identically regardless of a/b's
# actual magnitude -- nRMSD collapses to a fixed 1/0.9 constant, meaningless).
# P5's interpolation position is P5_QUANTILE*(n-1); it draws on a third value
# (index >= 1) once that position is >= 1, i.e. n >= ceil(1/P5_QUANTILE) + 1.
# By symmetry the same n also clears P95's equivalent condition at the top.
N_MIN = math.ceil(1 / P5_QUANTILE) + 1


@dataclass(frozen=True)
class Tau:
    """The materiality threshold. source: TAG_DEFAULT or TAG_USER_ENTERED.

    tau is user-adjustable between runs, fixed within a run (KT §8.5). Every
    run records tau and whether it is the default or user-set.
    """

    value: float
    source: str


def resolve_tau(user_value: float | None, defaults: dict) -> Tau:
    """tau from the user, or the (PROVISIONAL) pre-filled default."""
    if user_value is None:
        return Tau(float(defaults["dla"]["tau"]), TAG_DEFAULT)
    return Tau(float(user_value), TAG_USER_ENTERED)


def resolve_user_tau(user_value: float | None, defaults: dict) -> Tau:
    """resolve_tau(), for a tau typed by a person: it must be a finite number above 0
    (KT E.1 -- the only check on the value; no advice on it). None means 'not entered'
    and gives the default. resolve_tau() itself is unchanged for existing callers."""
    if user_value is not None and (
        isinstance(user_value, bool) or not math.isfinite(float(user_value)) or float(user_value) <= 0
    ):
        raise ValueError(f"tau must be a number greater than 0, got {user_value!r}")
    return resolve_tau(user_value, defaults)


@dataclass(frozen=True)
class PairMetrics:
    """One pair's metrics at one stage. All computed over daylight rows only.

    systematic_share is None when rmsd == 0 (the pipelines are identical at
    this stage: mbd is then 0 too, so the ratio is 0/0, not a defensible 0).

    n_pooled: how many values (both pipelines together) nRMSD's denominator
    would be drawn from -- 2x the daylight-row count for stages 2-5, 4x at
    Stage 1 (DNI concatenated with DHI, per pipeline, before pooling).
    not_computable_reason: None when nrmsd is a real, meaningful number;
    otherwise the reason it isn't (n_pooled < N_MIN, or a zero pooled
    spread) -- nrmsd is None whenever this is set, replacing what used to
    be a returned math.inf (28/09: that number was never meaningful either).
    """

    rmsd: float
    nrmsd: float | None
    mad: float
    mbd: float
    systematic_share: float | None
    n_pooled: int
    not_computable_reason: str | None


def stage_series(stage_outputs: StageOutputs, stage: Stage, daylight: pd.Series) -> pd.Series:
    """The daylight-masked comparison series for one stage.

    Stage 1: the DNI and DHI series concatenated (positionally paired -- see
    pooled_p5_p95, which pools the same way for the nRMSD denominator),
    decided 25/09 (B2/N36) -- they share units (W/m^2), and neither alone
    represents Stage 1's actual output. Stages 2-5 have one unambiguous
    column each.
    """
    if stage == Stage.DECOMPOSITION:
        outputs = stage_outputs.decomposition.outputs
        dni = outputs["dni"][daylight].reset_index(drop=True)
        dhi = outputs["dhi"][daylight].reset_index(drop=True)
        return pd.concat([dni, dhi], ignore_index=True)
    if stage == Stage.TRANSPOSITION:
        return stage_outputs.transposition.outputs["poa_global"][daylight].reset_index(drop=True)
    if stage == Stage.TEMPERATURE:
        return stage_outputs.temperature.outputs["temp_cell"][daylight].reset_index(drop=True)
    if stage == Stage.DC:
        return stage_outputs.dc.outputs["p_dc"][daylight].reset_index(drop=True)
    if stage == Stage.AC:
        return stage_outputs.ac.outputs["p_ac"][daylight].reset_index(drop=True)
    raise ValueError(f"Unknown stage: {stage!r}")


def pooled_p5_p95(series_a: pd.Series, series_b: pd.Series) -> tuple[float, float]:
    """P5/P95 of both pipelines' values pooled together (KT §8.1).

    For Stage 1, series_a/series_b are already the DNI+DHI concatenation, so
    pooling them here pools both components from both pipelines together, per
    the 25/09 decision extending the pooling convention to the two components.
    """
    pooled = pd.concat([series_a, series_b], ignore_index=True)
    return float(pooled.quantile(P5_QUANTILE)), float(pooled.quantile(P95_QUANTILE))


def pair_metrics(series_a: pd.Series, series_b: pd.Series, p5: float, p95: float) -> PairMetrics:
    """RMSD/nRMSD/MAD/MBD/systematic_share for one pair at one stage (KT §8.1).

    MBD(A,B) = -MBD(B,A): diff is signed a-minus-b: the caller's ordering
    decides which pipeline is "a".

    nrmsd is None (not_computable_reason set) whenever it wouldn't be a real
    number: too few pooled samples for P5/P95 to mean anything (n_pooled <
    N_MIN), or a zero pooled spread (P95 == P5) -- this replaces what used to
    be a returned math.inf in the zero-spread case (28/09: that number was
    never meaningful either, just differently wrong). rmsd == 0 is checked
    first and always gives nrmsd = 0.0 regardless of sample size: two
    identical series have zero disagreement unconditionally (D(A,A) = 0).
    """
    diff = series_a.to_numpy() - series_b.to_numpy()
    rmsd = math.sqrt((diff**2).mean())
    denominator = p95 - p5
    n_pooled = len(series_a) + len(series_b)

    not_computable_reason: str | None = None
    if rmsd == 0:
        nrmsd = 0.0
    elif n_pooled < N_MIN:
        nrmsd = None
        not_computable_reason = f"too few daylight samples (n pooled < {N_MIN})"
    elif denominator == 0:
        nrmsd = None
        not_computable_reason = "zero spread (P95 - P5 = 0)"
    else:
        nrmsd = rmsd / denominator

    mad = float(abs(diff).mean())
    mbd = float(diff.mean())
    systematic_share = (mbd**2) / (rmsd**2) if rmsd != 0 else None
    return PairMetrics(
        rmsd=rmsd, nrmsd=nrmsd, mad=mad, mbd=mbd, systematic_share=systematic_share,
        n_pooled=n_pooled, not_computable_reason=not_computable_reason,
    )
