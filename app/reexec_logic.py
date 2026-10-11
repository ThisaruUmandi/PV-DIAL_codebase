"""Page 5 logic without Streamlit: guided re-execution on top of pvdials' O4Session, which is not changed.

An attempt is anchor + exactly one substitution at the pair's k; the session builds it from the frozen anchor
every time, so attempts never carry over. The page keeps the attempts of this session (as plain dicts, in the
order made), links each attempt's provenance record to the analysis, and saves only a confirmed change, through
the same writer the command line uses (reexec_to_dict with ReexecDetails).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app import analysis_logic, config_logic, run_logic, wording
from pvdials.analysis import AnalysisError, ReexecDetails, phase1_to_dict, reexec_to_dict
from pvdials.guided_reexecution import FinalRunResult, O4Error, O4Session, annual_yield_kwh
from pvdials.physics.adapters import AdapterError
from pvdials.physics.hardware import ADR_INVERTER, CEC_INVERTER
from pvdials.physics.registry import (
    CandidateModel,
    dc_model_produces_v_dc,
    stage5_pool_view,
    stage5_selectable,
)
from pvdials.provenance.analyses import link_record
from pvdials.types import Stage

STAGES = config_logic.STAGES
PAIRS = analysis_logic.PAIRS
pair_key = analysis_logic.pair_key
pair_label = analysis_logic.pair_label

# what can stop an attempt: the session's own, a model that cannot run in this chain, a bad input
ATTEMPT_FAILURES = (O4Error, AdapterError, AnalysisError, ValueError, KeyError)


def stage_enum(stage: str) -> Stage:
    return Stage[stage.upper()]


# --- Which pairs, which stage, which candidates ----------------------------------------------------------------


def pairs_with_k(phase1: dict[str, dict]) -> list[tuple[str, str]]:
    """The pairs that have a k, in the fixed order A-B, A-C, B-C."""
    return [
        pair for pair in PAIRS
        if phase1[pair_key(pair)].get("status") == "ran" and phase1[pair_key(pair)].get("k")
    ]


def pair_stage(phase1: dict[str, dict], pair: tuple[str, str]) -> str:
    """The pair's k as a lower-case stage key: the one stage a substitution may change."""
    return phase1[pair_key(pair)]["k"].lower()


@dataclass(frozen=True)
class Candidate:
    name: str
    selectable: bool
    reason: str | None


def candidate_pool(inputs: dict, stage: str, anchor_models: dict[str, str], anchor: str) -> list[Candidate]:
    """Every model of the pool at this stage, in pool order, each selectable or with its reason. This is the
    session's own alternatives() (the registry's pool views, the same as page 2), read without needing the
    live pipelines, plus two facts the page adds: the anchor's own model changes nothing, and a DC model
    that gives no voltage cannot feed an AC model that needs one."""
    pools = config_logic.pools_for(
        inputs["hardware"]["module_name"], inputs["site"]["mounting_geometry"],
        inputs["site"]["mounting_construction"], inputs["hardware"]["inverter_name"],
    )
    if stage == "ac":
        cec, adr = config_logic._inverter_tables()
        view: tuple[CandidateModel, ...] = stage5_pool_view(
            inputs["hardware"]["inverter_name"], cec, adr, anchor_models["dc"]
        )
    else:
        view = pools.views[stage]
    out = []
    for candidate in view:
        selectable, reason = candidate.selectable, candidate.reason
        if selectable and candidate.name == anchor_models[stage]:
            selectable, reason = False, wording.RX_REASON_CURRENT.format(anchor=anchor)
        if selectable and stage == "dc":
            fits, why = stage5_selectable(
                anchor_models["ac"], {CEC_INVERTER, ADR_INVERTER}, dc_model_produces_v_dc(candidate.name)
            )
            if not fits:
                selectable, reason = False, why
        out.append(Candidate(candidate.name, selectable, reason))
    return out


def selectable_names(pool: list[Candidate]) -> list[str]:
    return [c.name for c in pool if c.selectable]


# --- Attempts ----------------------------------------------------------------------------------------------------------


def _session(live: run_logic.Live, pair: tuple[str, str], anchor: str, stage: str, on_record: Callable[[str], None]) -> O4Session:
    other = pair[1] if anchor == pair[0] else pair[0]
    hardware = live.hardware
    return O4Session(
        pair=pair,
        anchor_config=live.pipelines.configs[anchor],
        anchor_result=live.pipelines.results[anchor],
        other_config=live.pipelines.configs[other],
        other_result=live.pipelines.results[other],
        stage=stage_enum(stage),
        shared_cec=hardware.shared_cec,
        shared_adr=hardware.shared_adr,
        cec_inverters=hardware.cec_inverters,
        adr_inverters=hardware.adr_inverters,
        daylight=live.site_result.ctx.daylight,
        defaults=live.defaults,
        on_record=on_record,
        tau=live.tau,  # the run's own τ and source, so the attempt's Phase 1 and its records carry them
    )


def _live(ss: Any, say: Callable[[str], None]) -> run_logic.Live:
    run = ss["run"]
    if run.live is None:
        say(wording.P4_PROGRESS_REBUILD)
        run.live = run_logic.rebuild_live(ss["inputs"], ss["analysis_id"], say)
    return run.live


def other_label(pair: tuple[str, str], anchor: str) -> str:
    return pair[1] if anchor == pair[0] else pair[0]


def attempts_of(ss: Any, pair: tuple[str, str]) -> list[dict]:
    """The attempts made in this session under this pair, in the order made. Nothing here depends on the numbers."""
    stored = ss.get("reexec_session") or {}
    return [a for a in stored.get("attempts", []) if a["pair"] == pair_key(pair)]


def run_attempt(
    ss: Any, pair: tuple[str, str], anchor: str, candidate: str, progress: Callable[[str], None] | None = None
) -> dict:
    """One attempt, on its button: anchor + one substitution at the pair's k, with a Phase 1 against the other
    pipeline. Its provenance record is linked to the analysis. Kept in the session in the order made."""
    say = progress or (lambda _text: None)
    stage = pair_stage(ss["phase1"], pair)
    live = _live(ss, say)
    record_ids: list[str] = []
    session = _session(live, pair, anchor, stage, record_ids.append)
    say(wording.RX_PROGRESS_RUN.format(anchor=anchor, candidate=candidate, stage=wording.STAGE_NAME[stage]))
    proposal = session.propose(candidate)
    say(wording.RX_PROGRESS_COMPARE.format(other=other_label(pair, anchor)))
    say(wording.RX_PROGRESS_SAVE)
    for record_id in record_ids:
        link_record(ss["analysis_id"], record_id)
    stored = ss.get("reexec_session") or {"attempts": [], "confirmed": None}
    attempt = {
        "seq": len(stored["attempts"]) + 1,
        "pair": pair_key(pair),
        "anchor": anchor,
        "stage": stage,
        "candidate": candidate,
        "phase1": phase1_to_dict(proposal.phase1),
        "yield_kwh": annual_yield_kwh(proposal.result),
        "anchor_yield_kwh": annual_yield_kwh(live.pipelines.results[anchor]),
    }
    stored["attempts"] = [*stored["attempts"], attempt]
    ss["reexec_session"] = stored
    return attempt


# --- Confirm ---------------------------------------------------------------------------------------------------------------


def confirm_attempt(
    ss: Any, attempt: dict, compute_yield: bool, progress: Callable[[str], None] | None = None
) -> dict:
    """Confirm an attempt that has been run in this session: one fresh run against the frozen anchor (the
    session's confirm()), its record linked, and the change saved through the shared writer with the anchor,
    the stage, the candidate and the attempt's own Phase 1."""
    say = progress or (lambda _text: None)
    stored = ss.get("reexec_session") or {}
    if attempt not in stored.get("attempts", []):
        raise ValueError(wording.RX_CONFIRM_ONLY_RUN)
    pair = tuple(attempt["pair"].split("-"))
    live = _live(ss, say)
    record_ids: list[str] = []
    session = _session(live, pair, attempt["anchor"], attempt["stage"], record_ids.append)
    say(wording.RX_PROGRESS_CONFIRM)
    final: FinalRunResult = session.confirm(attempt["candidate"], compute_yield=compute_yield)
    for record_id in record_ids:
        link_record(ss["analysis_id"], record_id)
    saved = reexec_to_dict(
        final,
        ReexecDetails(attempt["anchor"], stage_enum(attempt["stage"]), attempt["candidate"], attempt["phase1"]),
    )
    say(wording.RX_PROGRESS_SAVE)
    analysis_logic.save_sections(
        ss["analysis_id"], ss["name"] or ss["inputs"]["name"], "done", ss["inputs"], reexec=saved
    )
    stored["confirmed"] = saved
    ss["reexec_session"] = stored
    ss["reexec_confirmed"] = True
    return saved


def confirmed_of(ss: Any) -> dict | None:
    """The confirmed change: this session's, or the one stored with the analysis."""
    stored = (ss.get("reexec_session") or {}).get("confirmed")
    if stored:
        return stored
    from pvdials.provenance.analyses import load_analysis

    row = load_analysis(ss["analysis_id"]) if ss.get("analysis_id") else None
    return (row or {}).get("reexec") or None


def recorded(reexec: dict, key: str) -> Any:
    """A part of a stored change, or 'not recorded for this analysis' for a row saved before it existed."""
    value = reexec.get(key)
    return wording.RX_NOT_RECORDED if value is None else value


def change_text(reexec: dict) -> str:
    """The confirmed change in words, from what is stored only."""
    pair = "-".join(reexec["pair"])
    stage, candidate = recorded(reexec, "stage"), recorded(reexec, "candidate")
    stage_text = wording.STAGE_NAME.get(stage.lower(), stage) if stage != wording.RX_NOT_RECORDED else stage
    return wording.RX_CONFIRMED_CHANGE.format(pair=pair_label(tuple(pair.split("-"))), stage=stage_text, candidate=candidate)


# --- What the page shows for an attempt ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AttemptRow:
    stage: str
    label: str
    before: float | None
    after: float | None
    change: float | None
    before_over: bool
    after_over: bool


@dataclass(frozen=True)
class AttemptView:
    """One attempt, before and after, read from the stored Phase 1 of the pair and the attempt's own Phase 1.
    The table, the chart, the list and the outcome line all read this, so no number is worked out twice."""

    computable: bool
    message: str | None
    rows: list[AttemptRow]
    before_outcome: str
    after_outcome: str | None
    tau: float


def _outcome_k(entry: dict) -> str:
    k = entry.get("k")
    return wording.RX_OUTCOME_K.format(
        n=entry["outcome"], k=wording.P4_K.format(stage=wording.STAGE_NAME[k.lower()]) if k else wording.P4_K_NONE
    )


def attempt_view(before: dict, after: dict) -> AttemptView:
    """Before = the pair's stored Phase 1; after = the attempt's Phase 1 (as phase1_to_dict writes it)."""
    tau = before["tau"]["value"]
    pre = {m["stage"].lower(): m["nrmsd"] for m in before["metrics"]}
    if after.get("status") != "ran":
        return AttemptView(False, analysis_logic.not_computable_text(after["reason"]), [], _outcome_k(before), None, tau)
    post = {m["stage"].lower(): m["nrmsd"] for m in after["metrics"]}
    rows = [
        AttemptRow(
            stage, wording.STAGE_NUMBERED[stage], pre[stage], post[stage], post[stage] - pre[stage],
            pre[stage] > tau, post[stage] > tau,
        )
        for stage in STAGES
    ]
    return AttemptView(True, None, rows, _outcome_k(before), _outcome_k(after), tau)


def fmt_change(value: float | None) -> str:
    return analysis_logic.fmt_signed(value)


def axis_max(phase1: dict[str, dict], attempts: list[dict]) -> float:
    """One upper end for every attempt chart in the session: the largest nRMSD of any pair before, or of any
    attempt after, or τ, with a little room. The range does not change from one attempt to the next view."""
    values: list[float] = []
    tau = 0.0
    for entry in phase1.values():
        if entry.get("status") == "ran":
            tau = entry["tau"]["value"]
            values += [m["nrmsd"] for m in entry["metrics"] if m["nrmsd"] is not None]
    for attempt in attempts:
        if attempt["phase1"].get("status") == "ran":
            values += [m["nrmsd"] for m in attempt["phase1"]["metrics"] if m["nrmsd"] is not None]
    return max([*values, tau]) * 1.15


__all__ = [
    "ATTEMPT_FAILURES",
    "AnalysisError",
    "AttemptView",
    "Candidate",
    "attempt_view",
    "attempts_of",
    "axis_max",
    "candidate_pool",
    "change_text",
    "confirm_attempt",
    "confirmed_of",
    "pairs_with_k",
    "run_attempt",
    "selectable_names",
]
