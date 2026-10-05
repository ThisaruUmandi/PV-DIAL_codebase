"""Past analyses and Home's recent rows, without Streamlit.

How far an analysis got is worked out from what is stored (its sections), not from the status text,
once the pipelines have run. The rows are listed by date or name only; nothing here reads or sorts
by how much the pipelines disagree.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app import wording
from app.report_logic import format_saved
from pvdials.provenance.analyses import (
    NOT_RECORDED,
    duplicate_analysis,
    list_analyses,
    list_analyses_overview,
)

PAIRS = ("A-B", "A-C", "B-C")
COMPLETE, STOPPED = "complete", "stopped"
OPEN, CONTINUE, DUPLICATE = "open", "continue", "duplicate"

# the status the early steps leave behind; from step 3 on the stored sections say how far it got
_EARLY_STEP = {"started": 1, "load_done": 1, "site_done": 2, "pipelines_configured": 3}
# statuses past the pipeline run; a row that says so but holds no run is stopped at the run (step 3)
_PAST_THE_RUN = ("pipelines_done", "phase1_done", "phase2_done", "phase3_done")
# inputs a step's page needs to be restored (top-level keys of the stored inputs)
_NEEDED = {
    1: (),
    2: ("name", "weather_file", "time_offset", "site", "hardware"),
    3: ("name", "weather_file", "time_offset", "site", "hardware", "pipelines", "tau"),
}
_NEEDED[4] = _NEEDED[3]


@dataclass(frozen=True)
class Progress:
    """Complete, or stopped at a step (1 to 4)."""

    kind: str
    step: int | None = None

    @property
    def text(self) -> str:
        return wording.PAST_COMPLETE if self.kind == COMPLETE else wording.PAST_STOPPED.format(n=self.step)


def _eligible_for_phase3(phase1: dict) -> list[str]:
    """The pairs Phase 3 computes: those that reached outcome 2 or 3."""
    return [
        pair for pair in PAIRS
        if isinstance(phase1.get(pair), dict) and phase1[pair].get("status") == "ran" and phase1[pair].get("outcome") in (2, 3)
    ]


def step4_finished(phase1: dict | None, phase2: dict | None, phase3: dict | None) -> bool:
    """Phase 1 is stored, Phase 2 is stored (run, or settled by Phase 1 alone) and every pair Phase 3
    computes has its entry."""
    if not isinstance(phase1, dict) or not phase1 or phase2 is None:
        return False
    return all(pair in (phase3 or {}) for pair in _eligible_for_phase3(phase1))


def progress(status: str, sections: list[str] | set[str], phase1=None, phase2=None, phase3=None) -> Progress:
    """How far an analysis got."""
    held = set(sections)
    if status == "done":
        return Progress(COMPLETE)
    if "phase1" in held and phase1:
        return Progress(COMPLETE) if step4_finished(phase1, phase2, phase3) else Progress(STOPPED, 4)
    if {"pipelines", "run_info"} <= held:
        return Progress(STOPPED, 4)
    return Progress(STOPPED, _EARLY_STEP.get(status, 3 if status in _PAST_THE_RUN else 1))


def inputs_present(step: int, input_keys: list[str]) -> bool:
    """True when the stored inputs hold what the page for this step needs."""
    return all(key in input_keys for key in _NEEDED[step])


def outcome_text(phase1: dict | None) -> str:
    """'A–B 3 · A–C 1 · B–C 1', 'Not run yet' with no Phase 1, 'not computable' for a pair without a result."""
    if not isinstance(phase1, dict) or not phase1:
        return wording.PAST_NOT_RUN_YET
    parts = []
    for pair in PAIRS:
        entry = phase1.get(pair)
        value = entry["outcome"] if isinstance(entry, dict) and entry.get("status") == "ran" else wording.PAST_NOT_COMPUTABLE
        parts.append(wording.PAST_OUTCOME_PAIR.format(pair=pair.replace("-", "–"), outcome=value))
    return wording.PAST_OUTCOME_JOIN.join(parts)


@dataclass(frozen=True)
class PastRow:
    id: str
    name: str
    file: str
    saved: str
    outcome: str
    progress: Progress
    actions: tuple[str, ...]  # in the order shown; the first is the main one
    note: str | None = None

    @property
    def status(self) -> str:
        return self.progress.text

    @property
    def main_action(self) -> str | None:
        """Open or Continue: the one action this analysis's state allows (Home shows only this)."""
        return next((a for a in self.actions if a != DUPLICATE), None)


def _file_text(weather_name: str | None, weather_file: str | None) -> str:
    """The name the file had when it was uploaded; for a row without one, the stored file's own name."""
    if weather_name:
        return weather_name
    return weather_file.replace("\\", "/").rsplit("/", 1)[-1] if weather_file else NOT_RECORDED


def row_from_overview(entry: dict[str, Any]) -> PastRow:
    held = entry["sections"]
    state = progress(entry["status"], held, entry["phase1"], entry["phase2"], entry["phase3"])
    has_phase1 = "phase1" in held and bool(entry["phase1"])
    note = None
    if state.kind == COMPLETE:
        actions = (OPEN, DUPLICATE) if has_phase1 else (DUPLICATE,)
    elif inputs_present(state.step, entry["input_keys"]):
        actions = (CONTINUE, DUPLICATE)
    else:
        actions = (OPEN, DUPLICATE) if has_phase1 else (DUPLICATE,)
        note = wording.PAST_CANNOT_CONTINUE
    return PastRow(
        id=entry["id"],
        name=entry["name"],
        file=_file_text(entry.get("weather_name"), entry["weather_file"]),
        saved=format_saved(entry["updated_at"]),
        outcome=outcome_text(entry["phase1"] if has_phase1 else None),
        progress=state,
        actions=actions,
        note=note,
    )


def past_rows(search: str | None = None, status: str = "all", order: str = "newest") -> list[PastRow]:
    """The rows of Past analyses. status is all, complete or stopped (worked out from what is stored);
    order is newest, oldest or name. Any other order is refused, so no ordering by disagreement exists."""
    if status not in ("all", COMPLETE, STOPPED):
        raise ValueError(f"status must be one of all, {COMPLETE}, {STOPPED}")
    rows = [row_from_overview(entry) for entry in list_analyses_overview(search or None, order)]
    return rows if status == "all" else [r for r in rows if r.progress.kind == status]


def recent_rows(limit: int = 3) -> list[PastRow]:
    """The most recent analyses, newest first, for Home."""
    return past_rows(order="newest")[:limit]


# --- Duplicate ---------------------------------------------------------------------------------------------------


def copy_name(name: str, existing: set[str]) -> str:
    """'<name> (copy)', then '(copy 2)', '(copy 3)' … The name of a copy is never reused."""
    base = re.sub(r" \(copy(?: \d+)?\)$", "", name)
    candidate, n = f"{base} (copy)", 1
    while candidate in existing:
        n += 1
        candidate = f"{base} (copy {n})"
    return candidate


def duplicate(analysis_id: str, name: str) -> tuple[str, str]:
    """A new analysis with the same inputs and no results, named as a copy. Returns (id, name). The saved
    original is not touched."""
    new_name = copy_name(name, {row["name"] for row in list_analyses()})
    return duplicate_analysis(analysis_id, name=new_name), new_name
