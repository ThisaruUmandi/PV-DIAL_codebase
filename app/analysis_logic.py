"""Page 4 logic without Streamlit: Phase 1 now, Phases 2 and 3 in the next parts.

The page reads only the stored dict shapes (what phase1_to_dict and its siblings write, which is also what
the command line saves), from session state or the database. A phase computes only when its button is
pressed; the pvdials step functions do the computing. Pairs are always A-B, A-C, B-C.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app import config_logic, run_logic, wording
from pvdials.analysis import (
    NOT_RUN_OUTCOME_1,
    PAIR_LABELS,
    AnalysisError,
    PairPhase1Result,
    phase1_to_dict,
    phase2_to_dict,
    phase3_pair_to_dict,
    step_disagreement_check,
    step_phase2,
    step_phase3,
)
from pvdials.dla.metrics import PairMetrics, Tau
from pvdials.provenance.analyses import load_analysis, save_analysis
from pvdials.types import Stage

PAIRS = PAIR_LABELS
STAGES = config_logic.STAGES
_SECTIONS = ("pipelines", "run_info", "phase1", "phase2", "phase3", "reexec")
STAGE_UNIT = {stage: run_logic.QUANTITIES[stage][0].unit for stage in STAGES}  # the headline column's unit


def pair_key(pair: tuple[str, str]) -> str:
    return f"{pair[0]}-{pair[1]}"


def pair_label(pair: tuple[str, str]) -> str:
    return wording.P4_PAIR.format(a=pair[0], b=pair[1])


def stage_name(stage: str) -> str:
    return wording.R_STAGE_SHORT[stage]


# --- Stored dict <-> pvdials objects -----------------------------------------------------------------


def phase1_from_dict(entry: dict[str, Any]) -> PairPhase1Result | str:
    """The object a step function expects, rebuilt from a stored Phase 1 dict. A pair that was not
    computable comes back as its reason string, as the step function gave it."""
    if entry.get("status") != "ran":
        return entry["reason"]
    metrics = {
        Stage[m["stage"]]: PairMetrics(
            rmsd=m["rmsd"], nrmsd=m["nrmsd"], mad=m["mad"], mbd=m["mbd"],
            systematic_share=m["systematic_share"], n_pooled=m["n_pooled"],
            not_computable_reason=m["not_computable_reason"],
        )
        for m in entry["metrics"]
    }
    return PairPhase1Result(
        pair=tuple(entry["pair"]),
        metrics=metrics,
        outcome=entry["outcome"],
        k=Stage[entry["k"]] if entry["k"] else None,
        differing_stages=frozenset(Stage[name] for name in entry["differing_stages"]),
        tau=Tau(entry["tau"]["value"], entry["tau"]["source"]),
    )


def phase1_results_from(phase1: dict[str, dict]) -> dict[tuple[str, str], PairPhase1Result | str]:
    return {pair: phase1_from_dict(phase1[pair_key(pair)]) for pair in PAIRS}


# --- k band (KT E.2) -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class KBand:
    """Where k stays the same as τ changes. k is the first stage whose nRMSD is above τ, so k stays at
    stage j while τ is below nRMSD[j] and at or above the largest nRMSD of the stages before j. lower is
    inclusive, upper exclusive. With no stage over τ, k stays 'none' for τ at or above the largest nRMSD."""

    stage: str | None
    lower: float | None
    upper: float


def k_band(nrmsd: dict[str, float], tau: float) -> KBand:
    """A pure function of the stored nRMSD values and τ; nothing is run."""
    values = [nrmsd[stage] for stage in STAGES]
    k = next((i for i, value in enumerate(values) if value > tau), None)
    if k is None:
        return KBand(None, None, max(values))
    return KBand(STAGES[k], max(values[:k]) if k > 0 else None, values[k])


def fmt_nrmsd(value: float | None) -> str:
    return wording.P4_NA if value is None else f"{value:.4f}"


def k_band_text(band: KBand) -> str:
    if band.stage is None:
        return wording.P4_BAND_NONE.format(upper=fmt_nrmsd(band.upper))
    if band.lower is None:
        return wording.P4_BAND_FIRST.format(stage=stage_name(band.stage), upper=fmt_nrmsd(band.upper))
    return wording.P4_BAND_LATER.format(
        stage=stage_name(band.stage), lower=fmt_nrmsd(band.lower), upper=fmt_nrmsd(band.upper)
    )


# --- What the page shows: one view per pair, read by the cards, the heatmap and the tables --------------


_NOT_COMPUTABLE = re.compile(r"^not computable — (?P<reason>.+) at stage (?P<stage>[A-Z_]+)$")


def not_computable_text(reason: str) -> str:
    """'Not computable — <reason> at stage <s>'; a reason in another form is shown as stored."""
    found = _NOT_COMPUTABLE.match(reason)
    if found and found["stage"].lower() in STAGES:
        return wording.NOT_COMPUTABLE.format(reason=found["reason"], stage=stage_name(found["stage"].lower()))
    return reason[:1].upper() + reason[1:]


@dataclass(frozen=True)
class PairView:
    pair: tuple[str, str]
    key: str
    label: str
    computable: bool
    outcome: int | None
    outcome_text: str
    k: str | None
    k_text: str
    sentence: str
    band: str | None
    nrmsd: dict[str, float | None]
    over: frozenset[str]
    differing: frozenset[str]
    metrics: list[dict[str, Any]]
    not_computable: str | None


def phase1_view(phase1: dict[str, dict]) -> list[PairView]:
    """One view per pair, in the fixed order A-B, A-C, B-C. Every number the page prints comes from here."""
    views = []
    for pair in PAIRS:
        entry = phase1[pair_key(pair)]
        if entry.get("status") != "ran":
            views.append(
                PairView(
                    pair, pair_key(pair), pair_label(pair), False, None, "", None, wording.P4_K_NONE, "", None,
                    dict.fromkeys(STAGES), frozenset(), frozenset(), [], not_computable_text(entry["reason"]),
                )
            )
            continue
        nrmsd = {m["stage"].lower(): m["nrmsd"] for m in entry["metrics"]}
        tau = entry["tau"]["value"]
        over = frozenset(stage for stage, value in nrmsd.items() if value is not None and value > tau)
        k = entry["k"].lower() if entry["k"] else None
        outcome = entry["outcome"]
        a, b = pair
        sentence = wording.PAIR_SENTENCE[outcome].format(a=a, b=b, stage=stage_name(k) if k else "")
        views.append(
            PairView(
                pair, pair_key(pair), pair_label(pair), True, outcome, wording.OUTCOME_TEXT[outcome], k,
                wording.P4_K.format(stage=stage_name(k)) if k else wording.P4_K_NONE, sentence,
                k_band_text(k_band(nrmsd, tau)), nrmsd, over, frozenset(n.lower() for n in entry["differing_stages"]),
                entry["metrics"], None,
            )
        )
    return views


def tau_of(phase1: dict[str, dict], fallback: dict | None = None) -> dict:
    """τ and its source as the run used them (read from a pair's stored result; never fixed in code)."""
    for entry in phase1.values():
        if entry.get("tau"):
            return entry["tau"]
    return fallback or {"value": float("nan"), "source": wording.R_PROV_NOT_RECORDED}


def tau_text(tau: dict) -> str:
    return wording.P4_TAU_TEXT.format(value=tau["value"], source=tau["source"])


def stage_rows(view: PairView, models: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    """The stage table for one pair: nRMSD, whether it is over τ, whether it is the first stage over τ,
    and both pipelines' models (or 'Same model')."""
    a, b = view.pair
    rows = []
    for stage in STAGES:
        same = models[a][stage] == models[b][stage]
        rows.append(
            {
                "stage": stage,
                "label": wording.C_STAGE_LABELS[stage],
                "nrmsd": view.nrmsd[stage],
                "text": fmt_nrmsd(view.nrmsd[stage]),
                "over": stage in view.over,
                "first": stage == view.k,
                "models": wording.P4_MODELS_SAME
                if same
                else wording.P4_MODELS_DIFFER.format(a=a, b=b, model_a=models[a][stage], model_b=models[b][stage]),
            }
        )
    return rows


def full_rows(views: list[PairView]) -> list[list[str]]:
    """Every stored metric, one row per pair and stage, for the closed 'full table'."""
    rows = []
    for view in views:
        for metric in view.metrics:
            stage = metric["stage"].lower()
            unit = STAGE_UNIT[stage]
            rows.append(
                [
                    view.label, stage_name(stage), unit, _num(metric["rmsd"]), fmt_nrmsd(metric["nrmsd"]),
                    _num(metric["mad"]), _num(metric["mbd"]), _num(metric["systematic_share"]), f"{metric['n_pooled']:,}",
                ]
            )
    return rows


def _num(value: float | None) -> str:
    return wording.P4_NA if value is None else f"{value:.4f}"


# --- Gating and the states that follow from Phase 1 alone --------------------------------------------------


def has_k(phase1: dict[str, dict]) -> bool:
    return any(entry.get("status") == "ran" and entry.get("k") for entry in phase1.values())


def phase2_blocked_reason(phase2: dict | None) -> str | None:
    """The reason Phase 2 cannot run, when Phase 1 alone settles it; None when it can run."""
    if phase2 is None or phase2.get("status") != "not run":
        return None
    return wording.PHASE2_NOT_RUN if "no pair" in phase2["reason"] else wording.P4_PHASE2_NOT_RUN_FAILED


def phase3_eligible(phase1: dict[str, dict]) -> list[tuple[str, str]]:
    """The pairs Phase 3 computes: those that reached outcome 2 or 3."""
    return [
        pair for pair in PAIRS
        if phase1[pair_key(pair)].get("status") == "ran" and phase1[pair_key(pair)]["outcome"] in (2, 3)
    ]


def phase3_blocked_reason(phase1: dict[str, dict]) -> str | None:
    """Why Phase 3 has nothing to compute, when Phase 1 alone settles it."""
    if phase3_eligible(phase1):
        return None
    if all(phase1[pair_key(p)].get("status") == "ran" for p in PAIRS):
        return wording.PHASE3_OUTCOME_1
    return wording.P4_PHASE2_NOT_RUN_FAILED


def outcome_one_text(entry: dict) -> str | None:
    """'Outcome 1 — nothing to attribute.' for a pair whose stored Phase 3 entry is the outcome-1 state."""
    if entry.get("status") == "not run" and entry.get("reason") == NOT_RUN_OUTCOME_1:
        return wording.PHASE3_OUTCOME_1
    return None


# --- Saving: the same shapes the command line stores ----------------------------------------------------------


def save_sections(analysis_id: str, name: str, status: str, inputs: dict, **updates: Any) -> None:
    """save_analysis keeping everything already stored: a section that is not named here stays as it is,
    and the status never moves backwards. (save_analysis writes None over anything it is not given.)"""
    existing = load_analysis(analysis_id)
    sections = {key: existing[key] for key in _SECTIONS if existing and existing.get(key) is not None}
    sections.update({key: value for key, value in updates.items() if value is not None})
    if existing and existing["status"] in run_logic._STATUS_ORDER and run_logic._STATUS_ORDER.index(
        existing["status"]
    ) > run_logic._STATUS_ORDER.index(status):
        status = existing["status"]
    save_analysis(analysis_id, name, status, inputs, **sections)


def derived_states(live: run_logic.Live, results: dict) -> tuple[dict | None, dict]:
    """What Phase 1 settles by itself, built by the same step functions and dict writers the command
    line uses, so what is saved has the same shape. Phase 2: 'not run' when no pair exceeds τ (or a
    pipeline failed). Phase 3: the 'not run' entry of each pair that is outcome 1 or failed."""
    phase2 = phase2_to_dict(None, results) if step_phase2(results) is None else None
    settled = {pair: result for pair, result in results.items() if isinstance(result, str) or result.outcome == 1}
    phase3 = {}
    if settled:
        outputs = step_phase3(live.pipelines, settled, live.hardware, live.site_result.ctx, live.defaults, "")
        phase3 = {pair_key(pair): phase3_pair_to_dict(value) for pair, value in outputs.items()}
    return phase2, phase3


def run_phase1(ss: Any, progress: Callable[[str], None] | None = None) -> dict[str, dict]:
    """Phase 1 on its button: compare the pipelines, save, and settle what follows from it alone.
    The live pipelines come from the run just made, or are rebuilt from the stored inputs."""
    say = progress or (lambda _text: None)
    run = ss["run"]
    if run.live is None:
        say(wording.P4_PROGRESS_REBUILD)
        run.live = run_logic.rebuild_live(ss["inputs"], ss["analysis_id"], say)
    live = run.live
    say(wording.P4_PROGRESS_COMPARE)
    results = step_disagreement_check(live.pipelines, live.site_result.ctx, live.defaults, tau=live.tau)
    phase1 = {pair_key(pair): phase1_to_dict(result) for pair, result in results.items()}
    phase2, phase3 = derived_states(live, results)

    say(wording.P4_PROGRESS_SAVE)
    existing = load_analysis(ss["analysis_id"]) or {}
    keep2 = existing.get("phase2")  # a Phase 2 or Phase 3 already stored is not replaced
    keep3 = existing.get("phase3") or {}
    merged3 = {**phase3, **keep3} or None
    save_sections(
        ss["analysis_id"], ss["name"] or ss["inputs"]["name"], "phase1_done", ss["inputs"],
        phase1=phase1, phase2=keep2 or phase2, phase3=merged3,
    )
    ss["phase1"] = phase1
    ss["phase2"] = keep2 or phase2
    ss["phase3"] = merged3
    ss["phase1_done"] = True
    ss["has_k"] = has_k(phase1)
    return phase1


__all__ = [
    "PAIRS",
    "AnalysisError",
    "KBand",
    "PairView",
    "derived_states",
    "has_k",
    "k_band",
    "k_band_text",
    "phase1_from_dict",
    "phase1_results_from",
    "phase1_view",
    "run_phase1",
    "save_sections",
    "stage_rows",
    "tau_of",
]
