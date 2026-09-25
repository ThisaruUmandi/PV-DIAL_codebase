"""Phase 1: first-appearance detection (KT §8.2).

This function also *is* the separate disagreement check the user-facing flow
runs before the DLA proper (decided 25/09): the check and Phase 1 are the
same computation, just shown at two points in the flow. There is no second
code path — an orchestrator (not yet built) calling this once under each
label satisfies both.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from pvdials.config import load_defaults
from pvdials.dla.metrics import (
    PairMetrics,
    Tau,
    pair_metrics,
    pooled_p5_p95,
    resolve_tau,
    stage_series,
)
from pvdials.physics.pipeline import PipelineResult
from pvdials.types import PipelineConfig, Stage

_STAGES_IN_ORDER = (Stage.DECOMPOSITION, Stage.TRANSPOSITION, Stage.TEMPERATURE, Stage.DC, Stage.AC)

# Two branches and one flag (KT §8.2), not three branches: outcome 3 is a
# labelled subcase of outcome 2 (upstream disagreement that happens to agree
# again by the final stage), not a separately detected condition.
OUTCOME_NOTHING_TO_DIAGNOSE = 1
OUTCOME_DISAGREEMENT_FOUND = 2
OUTCOME_COMPENSATING_DIFFERENCES = 3


def _differing_stages(config_a: PipelineConfig, config_b: PipelineConfig) -> frozenset[Stage]:
    """S: the stages where the two pipelines use different models."""
    model_field_by_stage = {
        Stage.DECOMPOSITION: "decomposition_model",
        Stage.TRANSPOSITION: "transposition_model",
        Stage.TEMPERATURE: "temperature_model",
        Stage.DC: "dc_model",
        Stage.AC: "ac_model",
    }
    return frozenset(
        stage
        for stage, field_name in model_field_by_stage.items()
        if getattr(config_a, field_name) != getattr(config_b, field_name)
    )


@dataclass(frozen=True)
class PairPhase1Result:
    """One pair's Phase 1 outcome.

    pair: (label_a, label_b), matching the ordering used for every signed
    metric (mbd(a,b) = -mbd(b,a)). k: the earliest stage over tau, None if
    outcome is 1. differing_stages: S, the stages where the two pipelines'
    model choices differ (not where they disagree numerically).
    """

    pair: tuple[str, str]
    metrics: dict[Stage, PairMetrics]
    outcome: int
    k: Stage | None
    differing_stages: frozenset[Stage]
    tau: Tau


def run_phase1(
    config_a: PipelineConfig,
    result_a: PipelineResult,
    config_b: PipelineConfig,
    result_b: PipelineResult,
    daylight: pd.Series,
    tau_value: float | None = None,
    defaults: dict | None = None,
) -> PairPhase1Result:
    """Run Phase 1 (and, equivalently, the disagreement check) for one pair.

    daylight: the shared daylight mask from the comparison's SiteContext
    (identical for both pipelines, since it's derived from solar position
    only, never from pipeline output).
    """
    defaults = defaults or load_defaults()
    tau = resolve_tau(tau_value, defaults)

    metrics: dict[Stage, PairMetrics] = {}
    for stage in _STAGES_IN_ORDER:
        series_a = stage_series(result_a.outputs, stage, daylight)
        series_b = stage_series(result_b.outputs, stage, daylight)
        p5, p95 = pooled_p5_p95(series_a, series_b)
        metrics[stage] = pair_metrics(series_a, series_b, p5, p95)

    over_tau = [stage for stage in _STAGES_IN_ORDER if metrics[stage].nrmsd > tau.value]

    if not over_tau:
        outcome = OUTCOME_NOTHING_TO_DIAGNOSE
        k = None
    else:
        k = over_tau[0]
        outcome = (
            OUTCOME_COMPENSATING_DIFFERENCES
            if metrics[Stage.AC].nrmsd <= tau.value
            else OUTCOME_DISAGREEMENT_FOUND
        )

    return PairPhase1Result(
        pair=(config_a.label, config_b.label),
        metrics=metrics,
        outcome=outcome,
        k=k,
        differing_stages=_differing_stages(config_a, config_b),
        tau=tau,
    )
