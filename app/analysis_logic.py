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


def nrmsd_axis_max(views: list[PairView], tau: float) -> float:
    """One upper end for every nRMSD axis on the page: the largest value of any pair (or τ), with a little room."""
    values = [v for view in views for v in view.nrmsd.values() if v is not None]
    return max([*values, tau]) * 1.15


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



# --- Phase 2: propagation profile --------------------------------------------------------------------------------


def fmt_signed(value: float | None) -> str:
    """A number that can be negative, with a true minus sign (not a hyphen)."""
    if value is None:
        return wording.P4_NA
    text = f"{abs(value):.4f}"
    return f"{wording.P4_MINUS}{text}" if value < 0 and round(abs(value), 4) != 0 else text


@dataclass(frozen=True)
class Phase2View:
    """The Phase 2 numbers, read from the stored dict in stage order. Both the chart and the table read these."""

    ran: bool
    reason: str | None
    pair_labels: list[str]
    pairs: dict[str, dict[str, float]]  # pair key -> stage -> nRMSD
    mean: dict[str, float]
    max: dict[str, float]
    delta: dict[str, float]


def _by_stage(items: list[dict]) -> dict[str, float]:
    return {item["stage"].lower(): item["value"] for item in items}


def phase2_view(phase2: dict) -> Phase2View:
    """The stored Phase 2 dict as numbers by stage; a 'not run' dict gives its reason."""
    if phase2.get("status") != "ran":
        reason = phase2_blocked_reason(phase2) or phase2.get("reason", "")
        return Phase2View(False, reason, [], {}, {}, {}, {})
    pairs = {pair_key(tuple(item["pair"])): _by_stage(item["nrmsd"]) for item in phase2["pair_nrmsd"]}
    keys = [pair_key(pair) for pair in PAIRS if pair_key(pair) in pairs]  # fixed order, whatever order was stored
    return Phase2View(
        True, None, keys, {key: pairs[key] for key in keys},
        _by_stage(phase2["mean_nrmsd"]), _by_stage(phase2["max_nrmsd"]), _by_stage(phase2["delta"]),
    )


def phase2_rows(view: Phase2View) -> list[dict[str, Any]]:
    """The table under the chart: one row per stage, the three pairs' values then mean, max and Δ."""
    return [
        {
            "stage": stage,
            "label": wording.P4_HEAT_AXIS[index],
            "pairs": [fmt_nrmsd(view.pairs[key][stage]) for key in view.pair_labels],
            "mean": fmt_nrmsd(view.mean[stage]),
            "max": fmt_nrmsd(view.max[stage]),
            "delta": fmt_signed(view.delta[stage]),
        }
        for index, stage in enumerate(STAGES)
    ]


def run_phase2(ss: Any, progress: Callable[[str], None] | None = None) -> dict:
    """Phase 2 on its button. It computes nothing new: step_phase2 re-reads the Phase 1 values, which are
    rebuilt from the stored dicts, so no live pipelines are needed. Saved with the shape the command line stores."""
    say = progress or (lambda _text: None)
    say(wording.P4_P2_PROGRESS_READ)
    results = phase1_results_from(ss["phase1"])
    phase2 = phase2_to_dict(step_phase2(results), results)
    say(wording.P4_P2_PROGRESS_SAVE)
    save_sections(
        ss["analysis_id"], ss["name"] or ss["inputs"]["name"], "phase2_done", ss["inputs"], phase2=phase2
    )
    ss["phase2"] = phase2
    return phase2


# --- Phase 3: contribution of each stage to the final AC gap --------------------------------------------------------


PHI_UNIT = run_logic.column_info("p_ac")[1]  # φ is in the unit of AC power, from the one column table


def fmt_watts(value: float | None) -> str:
    """Two decimals with a true minus sign for a negative value; nothing else is said about the sign."""
    if value is None:
        return wording.P4_NA
    text = f"{abs(value):.2f}"
    return f"{wording.P4_MINUS}{text}" if value < 0 and round(abs(value), 2) != 0 else text


def fmt_share(value: float | None) -> str:
    if value is None:
        return wording.P4_NA
    text = f"{abs(value):.3f}"
    return f"{wording.P4_MINUS}{text}" if value < 0 and round(abs(value), 3) != 0 else text


@dataclass(frozen=True)
class Phase3Row:
    stage: str
    label: str
    same_model: bool
    phi_ab: float
    phi_ba: float
    phi_final: float
    share: float | None


@dataclass(frozen=True)
class Phase3View:
    """One pair's stored Phase 3 entry, in stage order. The table, the efficiency line and the waterfall all
    read these values, so the same number is never worked out twice."""

    pair: tuple[str, str]
    state: str  # "ran", "outcome 1", "not computable", "not run", "pending"
    message: str | None
    rows: list[Phase3Row]
    rmsd_ab: float | None
    total: float | None  # the stages' φ final added up
    one_stage: bool
    share_defined: bool


def efficiency(view: Phase3View) -> tuple[float, float, bool]:
    """(sum of φ final, RMSD(A,B), whether they agree): the efficiency property, read from the stored values."""
    total, rmsd = view.total or 0.0, view.rmsd_ab or 0.0
    return total, rmsd, abs(total - rmsd) <= 1e-6 * max(1.0, abs(rmsd))


def phase3_view(pair: tuple[str, str], entry: dict | None, differing: frozenset[str]) -> Phase3View:
    """What the page shows for one pair. A pair with no stored entry is 'pending' (eligible, not yet run)
    or, if Phase 1 settled it, shows that reason."""
    if entry is None:
        return Phase3View(pair, "pending", wording.P4_P3_PENDING, [], None, None, False, True)
    status = entry.get("status")
    if status == "not run":
        text = outcome_one_text(entry)
        return Phase3View(
            pair, "outcome 1" if text else "not run", text or not_computable_text(entry["reason"]),
            [], None, None, False, True,
        )
    if status == "not computable":
        n = len(entry.get("invalid_coalitions") or [])
        message = wording.NOT_COMPUTABLE_HYBRID + (f". {wording.P4_P3_INVALID_COUNT.format(n=n)}" if n else "")
        return Phase3View(pair, "not computable", message, [], None, None, False, True)
    by = {key: _by_stage(entry[key]) for key in ("phi_ab", "phi_ba", "phi_final")}
    shares = _by_stage(entry["share"]) if entry.get("share") else {}
    rows = [
        Phase3Row(
            stage, wording.C_STAGE_LABELS[stage], stage not in differing, by["phi_ab"][stage], by["phi_ba"][stage],
            by["phi_final"][stage], shares.get(stage),
        )
        for stage in STAGES
    ]
    return Phase3View(
        pair, "ran", None, rows, entry["rmsd_ab"], sum(row.phi_final for row in rows),
        len(differing) == 1, bool(shares),
    )


def phase3_views(phase1: dict[str, dict], phase3: dict | None) -> list[Phase3View]:
    """One view per pair in the fixed order A-B, A-C, B-C."""
    phase3 = phase3 or {}
    out = []
    for pair in PAIRS:
        entry1 = phase1[pair_key(pair)]
        differing = frozenset(n.lower() for n in entry1.get("differing_stages", []))
        if entry1.get("status") != "ran" and pair_key(pair) not in phase3:
            out.append(Phase3View(pair, "not run", not_computable_text(entry1["reason"]), [], None, None, False, True))
            continue
        out.append(phase3_view(pair, phase3.get(pair_key(pair)), differing))
    return out


def phase3_done(phase1: dict[str, dict], phase3: dict | None) -> bool:
    """True when every pair Phase 3 computes has its entry."""
    eligible = phase3_eligible(phase1)
    return bool(eligible) and all(pair_key(pair) in (phase3 or {}) for pair in eligible)


def run_phase3(ss: Any, progress: Callable[[str], None] | None = None) -> dict:
    """Phase 3 on its button: every eligible pair (outcome 2 or 3), one pair at a time with a message each,
    saving after each. The live pipelines come from the run just made, or are rebuilt from the stored inputs.
    Derived runs are recorded by the step function, so a second press adds no rows."""
    say = progress or (lambda _text: None)
    run = ss["run"]
    pairs = phase3_eligible(ss["phase1"])
    if not pairs:
        return ss.get("phase3") or {}
    if run.live is None:
        say(wording.P4_PROGRESS_REBUILD)
        run.live = run_logic.rebuild_live(ss["inputs"], ss["analysis_id"], say)
    live = run.live
    results = phase1_results_from(ss["phase1"])
    stored = (load_analysis(ss["analysis_id"]) or {}).get("phase3") or {}
    # what Phase 1 settles, what is already stored, and what the session holds; nothing is dropped
    phase3 = {**derived_states(live, results)[1], **stored, **(ss.get("phase3") or {})}
    name = ss["name"] or ss["inputs"]["name"]
    for index, pair in enumerate(pairs, start=1):
        say(wording.P4_P3_PROGRESS_PAIR.format(pair=pair_label(pair), i=index, n=len(pairs)))
        out = step_phase3(live.pipelines, {pair: results[pair]}, live.hardware, live.site_result.ctx, live.defaults, ss["analysis_id"])
        phase3[pair_key(pair)] = phase3_pair_to_dict(out[pair])
        save_sections(ss["analysis_id"], name, "phase3_done", ss["inputs"], phase3=phase3)
        ss["phase3"] = phase3
    say(wording.P4_P3_PROGRESS_SAVE)
    return phase3


__all__ = [
    "PAIRS",
    "AnalysisError",
    "KBand",
    "PairView",
    "Phase2View",
    "derived_states",
    "has_k",
    "k_band",
    "k_band_text",
    "nrmsd_axis_max",
    "phase1_from_dict",
    "phase1_results_from",
    "phase1_view",
    "phase2_rows",
    "phase2_view",
    "phase3_done",
    "phase3_view",
    "phase3_views",
    "run_phase1",
    "run_phase2",
    "run_phase3",
    "save_sections",
    "stage_rows",
    "tau_of",
]
