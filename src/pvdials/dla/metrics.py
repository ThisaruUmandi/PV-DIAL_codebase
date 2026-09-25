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


@dataclass(frozen=True)
class PairMetrics:
    """One pair's metrics at one stage. All computed over daylight rows only.

    systematic_share is None when rmsd == 0 (the pipelines are identical at
    this stage: mbd is then 0 too, so the ratio is 0/0, not a defensible 0).
    """

    rmsd: float
    nrmsd: float
    mad: float
    mbd: float
    systematic_share: float | None


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
    return float(pooled.quantile(0.05)), float(pooled.quantile(0.95))


def pair_metrics(series_a: pd.Series, series_b: pd.Series, p5: float, p95: float) -> PairMetrics:
    """RMSD/nRMSD/MAD/MBD/systematic_share for one pair at one stage (KT §8.1).

    MBD(A,B) = -MBD(B,A): diff is signed a-minus-b: the caller's ordering
    decides which pipeline is "a".
    """
    diff = series_a.to_numpy() - series_b.to_numpy()
    rmsd = math.sqrt((diff**2).mean())
    denominator = p95 - p5
    # rmsd == 0 first: two identical series have zero disagreement regardless
    # of the pool's spread (D(A,A) = 0 unconditionally). inf only applies when
    # there IS a disagreement but the pooled reference range is degenerate
    # (zero spread) -- rare on real, continuous physical data.
    if rmsd == 0:
        nrmsd = 0.0
    elif denominator == 0:
        nrmsd = math.inf
    else:
        nrmsd = rmsd / denominator
    mad = float(abs(diff).mean())
    mbd = float(diff.mean())
    systematic_share = (mbd**2) / (rmsd**2) if rmsd != 0 else None
    return PairMetrics(rmsd=rmsd, nrmsd=nrmsd, mad=mad, mbd=mbd, systematic_share=systematic_share)
