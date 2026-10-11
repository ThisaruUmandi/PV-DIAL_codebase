"""Descriptive, presentation-layer views of an analysis run: per-stage
per-pipeline summaries, and reshaped Phase 2 / Phase 3 tables.

Pure functions, no printing/IO -- __main__.py's CLI and (eventually) a
Streamlit report both build their views from these same structures, so the
two never drift apart on what a "stage summary" or a "Phase 3 row" contains.
__main__.py keeps owning the actual print/format work (this module's own
job is only turning already-computed results into row/table data), matching
this project's existing split between computation and CLI printing.

Descriptive only: nothing here feeds Phase 1/2/3 -- the DLA is computed
entirely in dla/ before any of this runs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pandas as pd

from pvdials.dla.phase3 import ALL_STAGES, Phase3NotComputable, stage_field
from pvdials.guided_reexecution import integrate_watts_series_to_kwh
from pvdials.types import PipelineConfig, Stage


def _json_safe_float(x: float | None) -> float | None:
    """NaN/inf aren't valid JSON/JSONB -- same convention as analysis.py's
    own _safe_float (kept as a separate copy here, not imported, since
    analysis.py imports this module and a runtime import the other way
    would be circular)."""
    if x is None:
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    return x

if TYPE_CHECKING:
    from pvdials.analysis import PipelineRunResult
    from pvdials.dla.phase1 import PairPhase1Result
    from pvdials.dla.phase2 import Phase2Result
    from pvdials.dla.phase3 import Phase3Result


@dataclass(frozen=True)
class StageSummary:
    """One stage's descriptive summary for one pipeline; only the fields
    that stage actually produces are set, the rest stay None. Descriptive
    only -- never fed into Phase 1/2/3.
    """

    model: str
    dni_kwh_m2: float | None = None
    dhi_kwh_m2: float | None = None
    poa_global_kwh_m2: float | None = None
    temp_cell_mean_c: float | None = None
    temp_cell_max_c: float | None = None
    annual_energy_kwh: float | None = None


def build_stage_summaries(
    pipelines: PipelineRunResult, daylight: pd.Series
) -> dict[str, dict[Stage, StageSummary]]:
    """{label: {stage: StageSummary}} for every pipeline x stage.

    AC reuses pipelines.annual_yield_kwh (already computed) rather than
    recomputing it a second way. DC is genuinely integrated from
    outputs.dc.outputs["p_dc"] -- it is expected to sit a few percent above
    AC's total (inverter conversion isn't lossless), never equal to it.
    """
    summaries: dict[str, dict[Stage, StageSummary]] = {}
    for label, config in pipelines.configs.items():
        outputs = pipelines.results[label].outputs
        temp_cell = outputs.temperature.outputs["temp_cell"]
        daylight_temp = temp_cell[daylight]
        summaries[label] = {
            Stage.DECOMPOSITION: StageSummary(
                model=config.decomposition_model,
                dni_kwh_m2=integrate_watts_series_to_kwh(outputs.decomposition.outputs["dni"]),
                dhi_kwh_m2=integrate_watts_series_to_kwh(outputs.decomposition.outputs["dhi"]),
            ),
            Stage.TRANSPOSITION: StageSummary(
                model=config.transposition_model,
                poa_global_kwh_m2=integrate_watts_series_to_kwh(
                    outputs.transposition.outputs["poa_global"]
                ),
            ),
            Stage.TEMPERATURE: StageSummary(
                model=config.temperature_model,
                temp_cell_mean_c=float(daylight_temp.mean()),
                temp_cell_max_c=float(daylight_temp.max()),
            ),
            Stage.DC: StageSummary(
                model=config.dc_model,
                annual_energy_kwh=integrate_watts_series_to_kwh(outputs.dc.outputs["p_dc"]),
            ),
            Stage.AC: StageSummary(
                model=config.ac_model,
                annual_energy_kwh=pipelines.annual_yield_kwh[label],
            ),
        }
    return summaries


def stage_summaries_to_dict(summaries: dict[str, dict[Stage, StageSummary]]) -> dict[str, list[dict]]:
    """Ordered {stage, ...fields} list per label -- an array, not a bare
    dict, since JSONB does not preserve object key order (same convention as
    analysis.py's own _stage_list()).
    """
    result: dict[str, list[dict]] = {}
    for label, per_stage in summaries.items():
        rows = []
        for stage in ALL_STAGES:
            summary = per_stage[stage]
            row: dict[str, Any] = {"stage": stage.name, "model": summary.model}
            for field_name in (
                "dni_kwh_m2", "dhi_kwh_m2", "poa_global_kwh_m2",
                "temp_cell_mean_c", "temp_cell_max_c", "annual_energy_kwh",
            ):
                value = getattr(summary, field_name)
                row[field_name] = _json_safe_float(value)
            rows.append(row)
        result[label] = rows
    return result


@dataclass(frozen=True)
class Phase2StageRow:
    stage: Stage
    nrmsd: float
    delta: float
    exceeds_tau: bool


@dataclass(frozen=True)
class Phase2Row:
    pair: tuple[str, str]
    stages: list[Phase2StageRow]


def resolve_analysis_tau(
    phase1_results: dict[tuple[str, str], PairPhase1Result | str],
) -> float | None:
    """The one tau every pair was checked against (any real
    PairPhase1Result's .tau.value -- every pair shares it by construction,
    since step_disagreement_check resolves it once from the same defaults).
    None if every pair is "not computable" (no real result to read it from).
    """
    for result in phase1_results.values():
        if not isinstance(result, str):
            return result.tau.value
    return None


def build_phase2_rows(phase2_result: Phase2Result, tau: float) -> list[Phase2Row]:
    """One row per pair: nRMSD, the change from the previous stage (the same
    consecutive-difference formula Phase2Result.delta already uses, applied
    per-pair here instead of to the mean), and whether that stage's nRMSD
    exceeds tau. Computed directly from phase2_result.pair_nrmsd -- no
    change to run_phase2() itself.
    """
    rows = []
    for pair, per_stage_nrmsd in phase2_result.pair_nrmsd.items():
        stage_rows = []
        previous = 0.0
        for stage in ALL_STAGES:
            nrmsd = per_stage_nrmsd[stage]
            stage_rows.append(
                Phase2StageRow(stage=stage, nrmsd=nrmsd, delta=nrmsd - previous, exceeds_tau=nrmsd > tau)
            )
            previous = nrmsd
        rows.append(Phase2Row(pair=pair, stages=stage_rows))
    return rows


@dataclass(frozen=True)
class Phase3Row:
    pair: tuple[str, str]
    stage: Stage
    model_a: str
    model_b: str
    same_model: bool
    phi_ab: float
    phi_ba: float
    phi_final: float
    share: float | None
    signed_phi: float
    direction_words: str


def build_phase3_rows(
    phase3_results: dict[tuple[str, str], Phase3Result | Phase3NotComputable | str],
    configs: dict[str, PipelineConfig],
) -> list[Phase3Row]:
    """One row per (pair, stage), for pairs that actually ran (a real
    Phase3Result) -- __main__.py keeps printing "not run"/"not computable"
    for the others exactly as it does today; this function just skips them.

    direction_words is derived from signed_phi's own sign convention
    (dla/phase3.py::run_phase3): the anchor is result.pair[0], the full
    coalition equals result.pair[1]'s own series, so positive signed_phi
    means pair[1]'s model at that stage pushes final AC output higher than
    pair[0]'s model would; negative means lower. Where the two pipelines use
    the same model at a stage, phi/share/signed_phi are all exactly 0 (nrmsd
    is exactly 0 for identical models) -- reported as same_model=True so a
    caller can print one phrase instead of a row of zeros.
    """
    rows = []
    for result in phase3_results.values():
        if isinstance(result, str | Phase3NotComputable):
            continue
        label_a, label_b = result.pair
        config_a, config_b = configs[label_a], configs[label_b]
        for stage in ALL_STAGES:
            field = stage_field(stage)
            model_a = getattr(config_a, field)
            model_b = getattr(config_b, field)
            same_model = model_a == model_b
            signed = result.signed_phi[stage]
            if same_model:
                direction = "same model — no difference"
            elif signed > 0:
                direction = f"{label_b}'s model gives higher AC output than {label_a}'s"
            elif signed < 0:
                direction = f"{label_b}'s model gives lower AC output than {label_a}'s"
            else:
                direction = "no net direction (signed φ = 0)"
            rows.append(
                Phase3Row(
                    pair=result.pair,
                    stage=stage,
                    model_a=model_a,
                    model_b=model_b,
                    same_model=same_model,
                    phi_ab=result.phi_ab[stage],
                    phi_ba=result.phi_ba[stage],
                    phi_final=result.phi_final[stage],
                    share=result.share[stage],
                    signed_phi=signed,
                    direction_words=direction,
                )
            )
    return rows
