"""End-to-end orchestrator. Pure functions only -- no printing, no UI -- so
`python -m pvdials` and (later) Streamlit call exactly the same functions.

The six-step user-facing flow:
  1. Input data and configuration
  2. Pipeline execution
  3. Disagreement check (Phase 1)
  4. DLA (Phase 2, Phase 3)
  5. Guided re-execution (O4, optional)
  6. Report -- printing/formatting is the CLI's job (pvdials/__main__.py),
     not this module's.

Each step function takes exactly the prior results it actually needs (not
always literally "the previous one" -- e.g. building SharedInputs needs both
the loaded weather AND the site context, a real DAG, not a straight line).
None of them print or raise on a merely-interesting finding (e.g. Tier 1-3
problems, an outcome-1 pair); run_analysis() is the driver that decides
whether/when to stop, since an interactive caller (Streamlit) may want to
show a finding and let a person decide, rather than auto-halting.

N12 gating (decisions.md 13/09, "ordering correction"): outcome 1 -> Phase 2
and Phase 3 do not run for that pair; Phase 3's derived configs are only
built for outcome 2/3 pairs. dla/phase2.py and dla/phase3.py are unchanged;
the gating lives here, in what this orchestrator chooses to call.
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from pvdials import report
from pvdials.config import load_defaults
from pvdials.data.column_mapper import (
    TAG_USER_ENTERED,
    TimeOffset,
    detect_columns,
    detect_site_metadata,
    detect_time_offset,
)
from pvdials.data.preprocess import preprocess
from pvdials.data.upload import UploadedFile, load_uploaded_csv
from pvdials.data.validate import (
    ValidationResult,
    run_all_validations,
    validate_physical_consistency,
)
from pvdials.dla.metrics import Tau, resolve_tau
from pvdials.dla.phase1 import PairPhase1Result, run_phase1
from pvdials.dla.phase2 import Phase2Result, run_phase2
from pvdials.dla.phase3 import (
    ALL_STAGES,
    Phase3NotComputable,
    Phase3Result,
    run_phase3,
)
from pvdials.dla.phase3 import (
    stage_field as phase3_stage_field,
)
from pvdials.guided_reexecution import (
    FinalRunResult,
    O4Error,
    O4Session,
    annual_yield_kwh,
)
from pvdials.physics.geometry import ArrayGeometry, resolve_albedo
from pvdials.physics.hardware import (
    ADR_INVERTER,
    CEC,
    CEC_INVERTER,
    load_inverter,
    load_inverter_database,
    load_module,
    resolve_array_size,
)
from pvdials.physics.mounting import resolve_mounting
from pvdials.physics.pipeline import PipelineResult, SharedInputs, run_pipeline
from pvdials.physics.shared_inputs import shared_inputs_for
from pvdials.physics.site import SiteContext, build_site_context, offset_consistency_report
from pvdials.provenance.analyses import link_record, save_analysis
from pvdials.provenance.db import is_reachable
from pvdials.provenance.recorder import record as record_provenance
from pvdials.types import ExecutionSet, PipelineConfig, Stage

OUTCOME_NOTHING_TO_DIAGNOSE = 1
NOT_RUN_OUTCOME_1 = "not run — outcome 1 (no stage exceeds tau)"
PIPELINE_LABELS = ("A", "B", "C")
PAIR_LABELS = (("A", "B"), ("A", "C"), ("B", "C"))


class AnalysisError(Exception):
    """Raised with a clear 'Step N (name) failed: ...' message."""


# --- Step 1: input data and configuration -----------------------------------------


@dataclass(frozen=True)
class AnalysisConfig:
    """Parsed analysis.yaml."""

    name: str
    weather_file: str
    offset_value_h: float
    offset_reason: str
    tilt_deg: float
    azimuth_deg: float
    albedo: float | None
    mounting_geometry: str | None
    mounting_construction: str | None
    module_height_m: float | None
    module_name: str
    inverter_name: str
    modules_per_string: int
    strings_per_inverter: int
    pipelines: dict[str, dict[str, str]]  # label -> {decomposition, transposition, temperature, dc, ac}
    reexecution: dict[str, str] | None  # {pair: "A-B", anchor: "A", candidate: "..."}


_REQUIRED_TOP_KEYS = ("name", "weather_file", "time_offset", "site", "hardware", "pipelines")
_REQUIRED_STAGE_KEYS = ("decomposition", "transposition", "temperature", "dc", "ac")


def parse_analysis_yaml(path: str) -> AnalysisConfig:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AnalysisError(f"Step 1 (input data and configuration) failed: {path} not found") from exc
    except yaml.YAMLError as exc:
        raise AnalysisError(f"Step 1 (input data and configuration) failed: invalid YAML: {exc}") from exc

    missing = [k for k in _REQUIRED_TOP_KEYS if k not in raw]
    if missing:
        raise AnalysisError(
            f"Step 1 (input data and configuration) failed: analysis.yaml is missing {missing}"
        )

    pipelines = raw["pipelines"]
    if set(pipelines) != set(PIPELINE_LABELS):
        raise AnalysisError(
            f"Step 1 (input data and configuration) failed: pipelines must be exactly "
            f"{PIPELINE_LABELS}, got {sorted(pipelines)}"
        )
    for label, stages in pipelines.items():
        missing_stages = [k for k in _REQUIRED_STAGE_KEYS if k not in stages]
        if missing_stages:
            raise AnalysisError(
                f"Step 1 (input data and configuration) failed: pipeline {label} is missing "
                f"stage(s) {missing_stages}"
            )

    site = raw.get("site", {})
    hardware = raw.get("hardware", {})
    offset = raw["time_offset"]

    return AnalysisConfig(
        name=raw["name"],
        weather_file=raw["weather_file"],
        offset_value_h=float(offset["value_h"]),
        offset_reason=str(offset.get("reason", "")),
        tilt_deg=float(site["tilt_deg"]),
        azimuth_deg=float(site["azimuth_deg"]),
        albedo=site.get("albedo"),
        mounting_geometry=site.get("mounting_geometry"),
        mounting_construction=site.get("mounting_construction"),
        module_height_m=site.get("module_height_m"),
        module_name=hardware["module_name"],
        inverter_name=hardware["inverter_name"],
        modules_per_string=int(hardware["modules_per_string"]),
        strings_per_inverter=int(hardware["strings_per_inverter"]),
        pipelines=pipelines,
        reexecution=raw.get("reexecution"),
    )


@dataclass(frozen=True)
class LoadResult:
    uploaded: UploadedFile
    weather: pd.DataFrame
    validation: ValidationResult  # Tier 1-3 only -- Tier 4 needs the SiteContext, see step_site_and_offset


def step_load_and_validate(weather_file: str) -> LoadResult:
    try:
        uploaded = load_uploaded_csv(weather_file)
    except Exception as exc:
        raise AnalysisError(f"Step 1 (input data and configuration) failed: {exc}") from exc

    mapping = detect_columns(uploaded.table)
    if not mapping.is_complete():
        raise AnalysisError(
            f"Step 1 (input data and configuration) failed: missing required column(s) "
            f"{mapping.missing}"
        )
    weather = preprocess(uploaded.table, mapping).df
    validation = run_all_validations(weather)
    return LoadResult(uploaded=uploaded, weather=weather, validation=validation)


@dataclass(frozen=True)
class SiteStepResult:
    ctx: SiteContext
    tier4: ValidationResult
    offset_report: tuple  # tuple[OffsetCandidate, ...] from offset_consistency_report


def step_site_and_offset(
    load_result: LoadResult, config: AnalysisConfig, defaults: dict, tau: Tau
) -> SiteStepResult:
    """Builds the SiteContext from the YAML-given offset (not re-detected --
    the value+reason are a direct input), then runs Tier 4 (which needs the
    zenith series this just produced) and the offset-preset comparison
    report together -- Gap A: Tier 4 structurally can't run before this.

    tau: the run's already-resolved Tau (run_analysis(), via resolve_tau()),
    threaded into build_site_context() so every provenance record's
    site_context entity carries it (verification property #25). Phase 1's
    own per-pair resolve_tau() call is unaffected -- see the comment at
    run_analysis()'s early call.
    """
    site = detect_site_metadata(load_result.uploaded.preamble, load_result.uploaded.table)
    if not site.is_complete():
        raise AnalysisError(
            f"Step 1 (input data and configuration) failed: weather file has no "
            f"{site.missing} -- this version has no manual-entry fallback for missing "
            f"site coordinates."
        )

    offset = TimeOffset(config.offset_value_h, TAG_USER_ENTERED, override_reason=config.offset_reason)
    try:
        ctx = build_site_context(
            load_result.weather, site, offset, defaults, tau=tau.value, tau_source=tau.source
        )
    except Exception as exc:
        raise AnalysisError(f"Step 1 (input data and configuration) failed: {exc}") from exc

    tier4 = validate_physical_consistency(
        load_result.weather, ctx.solpos["zenith"], ctx.zenith_start, ctx.zenith_end
    )

    # "header" must be the file's own stated offset, not whatever the user
    # chose to run with -- config.offset_value_h is the latter, and using it
    # here would silently relabel the user's own choice as "the header value".
    file_header_offset_h = detect_time_offset(load_result.uploaded.preamble).value_h
    offset_report = offset_consistency_report(
        load_result.weather,
        site,
        {"header": file_header_offset_h, "hour_start": 0.0, "hour_centre": 0.5},
        defaults,
    )

    return SiteStepResult(ctx=ctx, tier4=tier4, offset_report=offset_report)


@dataclass(frozen=True)
class HardwareResult:
    shared_cec: SharedInputs
    shared_adr: SharedInputs
    cec_inverters: pd.DataFrame
    adr_inverters: pd.DataFrame


def step_hardware(load_result: LoadResult, site_result: SiteStepResult, config: AnalysisConfig, defaults: dict) -> HardwareResult:
    try:
        module = load_module(CEC, config.module_name)
        cec_inverters = load_inverter_database(CEC_INVERTER)
        adr_inverters = load_inverter_database(ADR_INVERTER)
        inverter_cec = load_inverter(CEC_INVERTER, config.inverter_name)
        inverter_adr = load_inverter(ADR_INVERTER, config.inverter_name)
    except Exception as exc:
        raise AnalysisError(f"Step 1 (input data and configuration) failed: {exc}") from exc

    mounting = resolve_mounting(config.mounting_geometry, config.mounting_construction, defaults)
    base = {
        "weather": load_result.weather,
        "ctx": site_result.ctx,
        "geometry": ArrayGeometry(surface_tilt_deg=config.tilt_deg, surface_azimuth_deg=config.azimuth_deg),
        "albedo": resolve_albedo(config.albedo, defaults),
        "mounting": mounting,
        "module": module,
        "array_size": resolve_array_size(config.modules_per_string, config.strings_per_inverter),
        "module_height_m": config.module_height_m,
    }
    shared_cec = SharedInputs(**base, inverter=inverter_cec)
    shared_adr = SharedInputs(**base, inverter=inverter_adr)
    return HardwareResult(shared_cec=shared_cec, shared_adr=shared_adr, cec_inverters=cec_inverters, adr_inverters=adr_inverters)


# --- Step 2: pipeline execution ----------------------------------------------------


def _build_pipeline_configs(config: AnalysisConfig) -> dict[str, PipelineConfig]:
    return {
        label: PipelineConfig(
            label=label,
            decomposition_model=stages["decomposition"],
            transposition_model=stages["transposition"],
            temperature_model=stages["temperature"],
            dc_model=stages["dc"],
            ac_model=stages["ac"],
        )
        for label, stages in config.pipelines.items()
    }


@dataclass(frozen=True)
class PipelineRunResult:
    configs: dict[str, PipelineConfig]
    results: dict[str, PipelineResult]
    checks: dict[str, dict[str, ValidationResult]]  # label -> {"decomposition": ..., "ac_not_exceeding_dc": ...}
    annual_yield_kwh: dict[str, float]
    record_ids: list[str] = field(default_factory=list)


def step_run_pipelines(
    config: AnalysisConfig, hardware: HardwareResult, defaults: dict, analysis_id: str
) -> PipelineRunResult:
    configs = _build_pipeline_configs(config)
    results: dict[str, PipelineResult] = {}
    checks: dict[str, dict[str, ValidationResult]] = {}
    yields: dict[str, float] = {}
    record_ids: list[str] = []

    for label, cfg in configs.items():
        shared = shared_inputs_for(cfg, hardware.shared_cec, hardware.shared_adr)
        try:
            result = run_pipeline(cfg, shared, defaults)
        except Exception as exc:
            raise AnalysisError(f"Step 2 (pipeline execution) failed for pipeline {label}: {exc}") from exc
        record_id = record_provenance(cfg, shared, result, ExecutionSet.ORIGINAL.value)
        link_record(analysis_id, record_id)
        record_ids.append(record_id)
        results[label] = result
        checks[label] = result.validations  # already computed by run_pipeline() itself
        yields[label] = annual_yield_kwh(result)

    return PipelineRunResult(
        configs=configs, results=results, checks=checks, annual_yield_kwh=yields, record_ids=record_ids
    )


# --- Step 3: disagreement check (Phase 1) ------------------------------------------


def failed_check_names(checks: dict[str, ValidationResult]) -> list[str]:
    """Names of the checks that failed for one pipeline, e.g. ['dc',
    'ac_not_exceeding_dc'] -- empty if every check passed. Shared by the
    failed-check policy (below) and the CLI's printing, so both name the
    same checks the same way.
    """
    return [name for name, result in checks.items() if not result.passed]


def step_disagreement_check(
    pipelines: PipelineRunResult, ctx: SiteContext, defaults: dict
) -> dict[tuple[str, str], PairPhase1Result | str]:
    """A pair involving a pipeline that failed its own checks is reported as
    'not computable' before Phase 1 even runs -- running a disagreement
    comparison against known-bad output would just measure the bug, not any
    real disagreement.
    """
    results: dict[tuple[str, str], PairPhase1Result | str] = {}
    for label_a, label_b in PAIR_LABELS:
        failed_a = failed_check_names(pipelines.checks[label_a])
        failed_b = failed_check_names(pipelines.checks[label_b])
        if failed_a or failed_b:
            failed_label, failed_names = (label_a, failed_a) if failed_a else (label_b, failed_b)
            results[(label_a, label_b)] = (
                f"not computable — pipeline {failed_label} failed {', '.join(failed_names)}"
            )
            continue
        try:
            results[(label_a, label_b)] = run_phase1(
                pipelines.configs[label_a], pipelines.results[label_a],
                pipelines.configs[label_b], pipelines.results[label_b],
                ctx.daylight, defaults=defaults,
            )
        except Exception as exc:
            raise AnalysisError(
                f"Step 3 (disagreement check) failed for pair {label_a}-{label_b}: {exc}"
            ) from exc
    return results


# --- Step 4: DLA (Phase 2, Phase 3, N12-gated) --------------------------------------


def step_phase2(phase1_results: dict[tuple[str, str], PairPhase1Result | str]) -> Phase2Result | None:
    """N12: Phase 2 re-reads Phase 1's own nRMSD values and computes nothing
    new -- unlike Phase 3, it never triggers a derived-space run, so the
    13/09 gating (which exists specifically to avoid those runs) applies
    more loosely here than to Phase 3. Rule: Phase 2 runs whenever at least
    one pair reached outcome 2/3, computed over all three pairs exactly as
    defined (dla/phase2.py is unchanged -- it already takes all three
    unconditionally, so it can only run when all three are real results).
    Skipped if all three are outcome 1, or if any pair is a string status
    (failed-check policy) -- run_phase2() has no way to accept a string in
    place of a real PairPhase1Result.
    """
    if any(isinstance(r, str) for r in phase1_results.values()):
        return None
    if all(r.outcome == OUTCOME_NOTHING_TO_DIAGNOSE for r in phase1_results.values()):
        return None
    ab, ac, bc = (phase1_results[pair] for pair in PAIR_LABELS)
    return run_phase2(ab, ac, bc)


def step_phase3(
    pipelines: PipelineRunResult,
    phase1_results: dict[tuple[str, str], PairPhase1Result | str],
    hardware: HardwareResult,
    ctx: SiteContext,
    defaults: dict,
    analysis_id: str,
) -> dict[tuple[str, str], Phase3Result | Phase3NotComputable | str]:
    """N12: Phase 3 (and its derived-config runs) only run for outcome 2/3
    pairs. An outcome-1 pair gets the string NOT_RUN_OUTCOME_1 instead --
    distinct from Phase3NotComputable (hybrid invalidity), which is a
    different reason and is left exactly as dla/phase3.py already computes
    it (that precheck is untouched). A pair whose Phase 1 entry is itself a
    string (failed-check policy) propagates that same string unchanged --
    there's no real outcome to gate on, so Phase 3 doesn't attempt anything.
    """
    results: dict[tuple[str, str], Phase3Result | Phase3NotComputable | str] = {}
    for pair, phase1 in phase1_results.items():
        if isinstance(phase1, str):
            results[pair] = phase1
            continue
        if phase1.outcome == OUTCOME_NOTHING_TO_DIAGNOSE:
            results[pair] = NOT_RUN_OUTCOME_1
            continue
        label_a, label_b = pair
        record_ids: list[str] = []
        try:
            result = run_phase3(
                pipelines.configs[label_a], pipelines.results[label_a],
                pipelines.configs[label_b], pipelines.results[label_b],
                hardware.shared_cec, hardware.shared_adr, ctx.daylight, defaults,
                on_record=record_ids.append,
            )
        except Exception as exc:
            raise AnalysisError(f"Step 4 (Phase 3) failed for pair {label_a}-{label_b}: {exc}") from exc
        for record_id in record_ids:
            link_record(analysis_id, record_id)
        results[pair] = result
    return results


# --- Step 5: guided re-execution (O4, optional) -------------------------------------


def step_reexecution(
    config: AnalysisConfig,
    pipelines: PipelineRunResult,
    phase1_results: dict[tuple[str, str], PairPhase1Result],
    hardware: HardwareResult,
    ctx: SiteContext,
    defaults: dict,
    analysis_id: str,
) -> FinalRunResult | None:
    """Non-interactive: goes straight to confirm() with the one YAML-given
    candidate. propose()/retry() exist for a *live* user comparing options
    before deciding -- a YAML-driven run has already decided. The candidate
    still goes through O4Session's own pool-valid check (unchanged); it is
    NOT pre-validated here, so that check stays the single source of truth.
    """
    if config.reexecution is None:
        return None

    pair_str = config.reexecution["pair"]
    anchor_label = config.reexecution["anchor"]
    candidate = config.reexecution["candidate"]
    label_a, label_b = pair_str.split("-")
    pair_key = (label_a, label_b) if (label_a, label_b) in phase1_results else (label_b, label_a)
    phase1 = phase1_results.get(pair_key)
    if phase1 is None:
        raise AnalysisError(f"Step 5 (guided re-execution) failed: unknown pair {pair_str!r}")
    if isinstance(phase1, str):
        raise AnalysisError(f"Step 5 (guided re-execution) failed: pair {pair_str} is {phase1!r}")
    if phase1.k is None:
        raise AnalysisError(
            f"Step 5 (guided re-execution) failed: pair {pair_str} is {NOT_RUN_OUTCOME_1} -- "
            f"there is no stage to substitute at."
        )

    other_label = label_b if anchor_label == label_a else label_a
    record_ids: list[str] = []
    session = O4Session(
        pair=(label_a, label_b),
        anchor_config=pipelines.configs[anchor_label],
        anchor_result=pipelines.results[anchor_label],
        other_config=pipelines.configs[other_label],
        other_result=pipelines.results[other_label],
        stage=phase1.k,
        shared_cec=hardware.shared_cec,
        shared_adr=hardware.shared_adr,
        cec_inverters=hardware.cec_inverters,
        adr_inverters=hardware.adr_inverters,
        daylight=ctx.daylight,
        defaults=defaults,
        on_record=record_ids.append,
    )
    try:
        final = session.confirm(candidate, compute_yield=True)
    except O4Error as exc:
        raise AnalysisError(f"Step 5 (guided re-execution) failed: {exc}") from exc
    for record_id in record_ids:
        link_record(analysis_id, record_id)
    return final


# --- Serialization (Gap C): Stage/frozenset keys, NaN/inf -> null, pipeline order ---


def _safe_float(x: Any) -> float | None:
    if x is None:
        return None
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    return x


def _coalition_key(coalition: frozenset[Stage]) -> str:
    ordered = [s.name for s in ALL_STAGES if s in coalition]
    return "+".join(ordered) if ordered else "EMPTY"


def _stage_list(d: dict[Stage, float]) -> list[dict[str, Any]]:
    """Ordered list of {stage, value}, Decomposition->AC -- not a bare dict,
    since JSONB does not guarantee object key order survives storage; an
    array's element order is preserved, so pipeline order is guaranteed this
    way regardless of how Postgres stores it.
    """
    return [{"stage": s.name, "value": _safe_float(d[s])} for s in ALL_STAGES if s in d]


def phase1_to_dict(result: PairPhase1Result | str) -> dict[str, Any]:
    if isinstance(result, str):
        return {"status": "not computable", "reason": result}
    return {
        "status": "ran",
        "pair": list(result.pair),
        "outcome": result.outcome,
        "k": result.k.name if result.k is not None else None,
        "differing_stages": [s.name for s in ALL_STAGES if s in result.differing_stages],
        "tau": {"value": _safe_float(result.tau.value), "source": result.tau.source},
        "metrics": [
            {
                "stage": stage.name,
                "rmsd": _safe_float(m.rmsd),
                "nrmsd": _safe_float(m.nrmsd),
                "mad": _safe_float(m.mad),
                "mbd": _safe_float(m.mbd),
                "systematic_share": _safe_float(m.systematic_share),
                "n_pooled": m.n_pooled,
                "not_computable_reason": m.not_computable_reason,
            }
            for stage, m in result.metrics.items()
        ],
    }


def phase2_to_dict(
    result: Phase2Result | None, phase1_results: dict[tuple[str, str], PairPhase1Result | str]
) -> dict[str, Any]:
    if result is None:
        if any(isinstance(r, str) for r in phase1_results.values()):
            reason = "a pipeline failed its checks"
        else:
            reason = "no pair exceeds tau"
        return {"status": "not run", "reason": reason}
    return {
        "status": "ran",
        "pair_nrmsd": [
            {"pair": list(pair), "nrmsd": _stage_list(values)} for pair, values in result.pair_nrmsd.items()
        ],
        "mean_nrmsd": _stage_list(result.mean_nrmsd),
        "max_nrmsd": _stage_list(result.max_nrmsd),
        "delta": _stage_list(result.delta),
    }


def phase3_pair_to_dict(result: Phase3Result | Phase3NotComputable | str) -> dict[str, Any]:
    if isinstance(result, str):
        return {"status": "not run", "reason": result}
    if isinstance(result, Phase3NotComputable):
        return {
            "status": "not computable",
            "reason": result.reason,
            "invalid_coalitions": [_coalition_key(c) for c in result.invalid_coalitions],
        }
    return {
        "status": "ran",
        "pair": list(result.pair),
        "rmsd_ab": _safe_float(result.rmsd_ab),
        "phi_ab": _stage_list(result.phi_ab),
        "phi_ba": _stage_list(result.phi_ba),
        "phi_final": _stage_list(result.phi_final),
        "share": _stage_list({s: v for s, v in result.share.items() if v is not None}) if any(
            v is not None for v in result.share.values()
        ) else [],
        "signed_phi": _stage_list(result.signed_phi),
        "v_ab": [{"coalition": _coalition_key(c), "value": _safe_float(v)} for c, v in result.v_ab.items()],
        "v_ba": [{"coalition": _coalition_key(c), "value": _safe_float(v)} for c, v in result.v_ba.items()],
        "signed_v": [{"coalition": _coalition_key(c), "value": _safe_float(v)} for c, v in result.signed_v.items()],
    }


def phase3_to_dict(results: dict[tuple[str, str], Any]) -> dict[str, Any]:
    return {f"{a}-{b}": phase3_pair_to_dict(r) for (a, b), r in results.items()}


def reexec_to_dict(result: FinalRunResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "pair": list(result.pair),
        "config_label": result.config.label,
        "substituted_stage_model": {
            phase3_stage_field(s): getattr(result.config, phase3_stage_field(s)) for s in ALL_STAGES
        },
        "annual_yield_kwh": _safe_float(result.annual_yield_kwh),
        "disclaimer": result.disclaimer,
    }


# --- Top-level driver: run every step in order, saving after each ------------------


@dataclass(frozen=True)
class AnalysisRunResult:
    analysis_id: str
    name: str
    load_result: LoadResult
    site_result: SiteStepResult
    pipelines: PipelineRunResult
    stage_summaries: dict[str, dict[Stage, report.StageSummary]]
    phase1_results: dict[tuple[str, str], PairPhase1Result]
    phase2_result: Phase2Result | None
    phase3_results: dict[tuple[str, str], Phase3Result | Phase3NotComputable | str]
    reexec_result: FinalRunResult | None


def run_analysis(yaml_path: str, analysis_id: str | None = None) -> AnalysisRunResult:
    """Runs every step in order, saving progress to the analyses table after
    each one (status = last step reached), so a crash mid-run still leaves a
    queryable partial record. Checks Postgres reachability first, before
    touching the YAML at all -- provenance is load-bearing here (Phase 3 and
    O4 both record as they run), so there is no point parsing input for a
    run that cannot possibly finish.
    """
    if not is_reachable():
        raise AnalysisError(
            "Postgres is unreachable (DATABASE_URL not set or the service isn't running) -- "
            "stopping before Step 1, since Phase 3/O4 both require it to record as they run."
        )

    analysis_id = analysis_id or uuid.uuid4().hex
    config = parse_analysis_yaml(yaml_path)
    defaults = load_defaults()
    # tau is now resolved in two places: here (early, so the SiteContext and
    # every provenance record can carry it) and again, unchanged, once per
    # pair inside run_phase1() (dla/phase1.py, via step_disagreement_check).
    # Both calls use the same resolve_tau(None, defaults) with the same
    # defaults object, so they are guaranteed to agree -- not restructuring
    # Phase 1 to remove the second call. If analysis.yaml ever gains a real
    # tau-override field, that value must reach BOTH call sites, ideally by
    # resolving once here and threading the result into
    # step_disagreement_check too, rather than letting the two resolutions
    # drift apart.
    tau = resolve_tau(None, defaults)
    inputs_dict = {
        "name": config.name,
        "weather_file": config.weather_file,
        "time_offset": {"value_h": config.offset_value_h, "reason": config.offset_reason},
        "site": {
            "tilt_deg": config.tilt_deg,
            "azimuth_deg": config.azimuth_deg,
            "albedo": config.albedo,
            "mounting_geometry": config.mounting_geometry,
            "mounting_construction": config.mounting_construction,
            "module_height_m": config.module_height_m,
        },
        "hardware": {
            "module_name": config.module_name,
            "inverter_name": config.inverter_name,
            "modules_per_string": config.modules_per_string,
            "strings_per_inverter": config.strings_per_inverter,
        },
        "pipelines": config.pipelines,
        "reexecution": config.reexecution,
    }
    save_analysis(analysis_id, config.name, "started", inputs_dict)

    load_result = step_load_and_validate(config.weather_file)
    save_analysis(analysis_id, config.name, "load_done", inputs_dict)

    site_result = step_site_and_offset(load_result, config, defaults, tau)
    save_analysis(analysis_id, config.name, "site_done", inputs_dict)

    hardware = step_hardware(load_result, site_result, config, defaults)
    pipelines = step_run_pipelines(config, hardware, defaults, analysis_id)
    stage_summaries = report.build_stage_summaries(pipelines, site_result.ctx.daylight)
    pipelines_dict = report.stage_summaries_to_dict(stage_summaries)
    save_analysis(analysis_id, config.name, "pipelines_done", inputs_dict, pipelines=pipelines_dict)

    phase1_results = step_disagreement_check(pipelines, site_result.ctx, defaults)
    phase1_dict = {f"{a}-{b}": phase1_to_dict(r) for (a, b), r in phase1_results.items()}
    save_analysis(
        analysis_id, config.name, "phase1_done", inputs_dict, phase1=phase1_dict, pipelines=pipelines_dict
    )

    phase2_result = step_phase2(phase1_results)
    phase2_dict = phase2_to_dict(phase2_result, phase1_results)
    save_analysis(
        analysis_id, config.name, "phase2_done", inputs_dict,
        phase1=phase1_dict, phase2=phase2_dict, pipelines=pipelines_dict,
    )

    phase3_results = step_phase3(pipelines, phase1_results, hardware, site_result.ctx, defaults, analysis_id)
    phase3_dict = phase3_to_dict(phase3_results)
    save_analysis(
        analysis_id, config.name, "phase3_done", inputs_dict,
        phase1=phase1_dict, phase2=phase2_dict, phase3=phase3_dict, pipelines=pipelines_dict,
    )

    reexec_result = step_reexecution(
        config, pipelines, phase1_results, hardware, site_result.ctx, defaults, analysis_id
    )
    reexec_dict = reexec_to_dict(reexec_result)
    save_analysis(
        analysis_id, config.name, "done", inputs_dict,
        phase1=phase1_dict, phase2=phase2_dict, phase3=phase3_dict, reexec=reexec_dict,
        pipelines=pipelines_dict,
    )

    return AnalysisRunResult(
        analysis_id=analysis_id,
        name=config.name,
        load_result=load_result,
        site_result=site_result,
        pipelines=pipelines,
        stage_summaries=stage_summaries,
        phase1_results=phase1_results,
        phase2_result=phase2_result,
        phase3_results=phase3_results,
        reexec_result=reexec_result,
    )


# --- Output folder exports (results.json, stage_outputs.csv, provenance.json) -------


def build_results_dict(run: AnalysisRunResult) -> dict[str, Any]:
    return {
        "analysis_id": run.analysis_id,
        "name": run.name,
        "load_validation": {
            "passed": run.load_result.validation.passed,
            "problems": run.load_result.validation.problems,
            "warnings": run.load_result.validation.warnings,
            "notes": run.load_result.validation.notes,
            "counts": run.load_result.validation.counts,
        },
        "tier4": {
            "passed": run.site_result.tier4.passed,
            "warnings": run.site_result.tier4.warnings,
            "notes": run.site_result.tier4.notes,
            "counts": run.site_result.tier4.counts,
        },
        "offset_report": [
            {
                "label": c.label,
                "value_h": c.value_h,
                "ghi_positive_sun_down": c.ghi_positive_sun_down,
                "ghi_zero_sun_up": c.ghi_zero_sun_up,
            }
            for c in run.site_result.offset_report
        ],
        "pipelines": {
            label: {
                "config": {phase3_stage_field(s): getattr(cfg, phase3_stage_field(s)) for s in ALL_STAGES},
                "annual_yield_kwh": _safe_float(run.pipelines.annual_yield_kwh[label]),
                "checks_passed": all(v.passed for v in run.pipelines.checks[label].values()),
                "failed_checks": failed_check_names(run.pipelines.checks[label]),
            }
            for label, cfg in run.pipelines.configs.items()
        },
        "stage_summaries": report.stage_summaries_to_dict(run.stage_summaries),
        "phase1": {f"{a}-{b}": phase1_to_dict(r) for (a, b), r in run.phase1_results.items()},
        "phase2": phase2_to_dict(run.phase2_result, run.phase1_results),
        "phase3": phase3_to_dict(run.phase3_results),
        "reexec": reexec_to_dict(run.reexec_result),
    }


def write_results_json(run: AnalysisRunResult, out_dir: str) -> Path:
    path = Path(out_dir) / "results.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_results_dict(run), indent=2), encoding="utf-8")
    return path


def write_stage_outputs_csv(run: AnalysisRunResult, out_dir: str) -> Path:
    """Wide format, one row per timestamp, {label}_{output} columns, for
    A/B/C only -- Phase 3's derived/re-execution runs stay in Postgres,
    reachable via provenance.json / the analysis_records link, not
    duplicated here.
    """
    columns = {}
    for label, result in run.pipelines.results.items():
        columns[f"{label}_dni"] = result.outputs.decomposition.outputs["dni"]
        columns[f"{label}_dhi"] = result.outputs.decomposition.outputs["dhi"]
        columns[f"{label}_poa_global"] = result.outputs.transposition.outputs["poa_global"]
        columns[f"{label}_temp_cell"] = result.outputs.temperature.outputs["temp_cell"]
        columns[f"{label}_p_dc"] = result.outputs.dc.outputs["p_dc"]
        columns[f"{label}_p_ac"] = result.outputs.ac.outputs["p_ac"]
    df = pd.DataFrame(columns)
    path = Path(out_dir) / "stage_outputs.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index_label="timestamp")
    return path


def write_provenance_json(run: AnalysisRunResult, out_dir: str) -> Path:
    from pvdials.provenance.analyses import records_for_analysis

    documents = records_for_analysis(run.analysis_id)
    path = Path(out_dir) / "provenance.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(documents, indent=2), encoding="utf-8")
    return path


def write_outputs(run: AnalysisRunResult, out_dir: str) -> None:
    write_results_json(run, out_dir)
    write_stage_outputs_csv(run, out_dir)
    write_provenance_json(run, out_dir)
