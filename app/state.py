"""Session state for the interface, as pure functions on a MutableMapping.

st.session_state and a plain dict both work, so the rules (what an input
change clears, the confirm/cancel flow) are tested without a browser.

Steps 1-6 follow the page order. Each input belongs to a step; changing it
clears every later step's results. Anything that would be cleared is shown to
the user first (F2.5), and Cancel keeps everything.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from app import wording

# Which step an input belongs to. Changing it clears steps after that step.
INPUT_STEP = {
    "name": 1,
    "weather": 1,
    "offset": 1,
    "site": 1,
    "hardware": 1,
    "config": 2,
    "tau": 2,
}

# What each later step holds. Cleared by an earlier input change. "tau" is a
# step-2 input and is deliberately not listed: a page-1 change keeps it.
STEP_KEYS: dict[int, tuple[str, ...]] = {
    2: ("config", "config_valid"),
    3: ("run", "pipelines_summary", "run_info", "run_done"),
    4: ("phase1", "phase2", "phase3", "phase1_done", "has_k"),
    5: ("reexec_session", "reexec_confirmed"),
}
LAST_STEP = 6

# A step that is done has opened the next one, so changing one of its inputs needs the
# warning even if nothing later holds a result yet, and its flag is reset: the step has to
# be confirmed again (Continue) before the next one opens.
OPENS_NEXT = {1: "data_valid", 2: "config_valid"}

_DEFAULTS: dict[str, Any] = {
    "analysis_id": None,
    "name": "",
    "weather": None,
    "offset": None,
    "site": None,
    "hardware": None,
    "config": None,
    "tau": None,
    "data_valid": False,
    "config_valid": False,
    "run_done": False,
    "phase1_done": False,
    "has_k": False,
    "reexec_confirmed": False,
    "readonly": False,
    "run": None,
    "pipelines_summary": None,
    "run_info": None,
    "phase1": None,
    "phase2": None,
    "phase3": None,
    "reexec_session": None,
    "pending": None,
    "ingest": None,
    "location": None,
    "inputs": None,
    "flash": None,
}

PROGRESS_MAX = 5  # 0 nothing ... 5 re-execution confirmed


def init_state(ss: MutableMapping) -> None:
    """Fill in any missing key; never overwrites what is already there."""
    for key, value in _DEFAULTS.items():
        ss.setdefault(key, value)


# Widget state is kept per page under these prefixes; a new analysis must not inherit it.
_PAGE_WIDGET_PREFIXES = ("w1_", "w2_", "w3_")
_PAGE_TRANSIENT = ("upload_n", "upload_problem", "_ingest_new", "cancel_note")


def new_analysis(ss: MutableMapping) -> None:
    """Start from nothing (Home > Start new analysis): no value typed or chosen for an earlier
    analysis may show up in this one, so every page's widget state goes too."""
    for key in list(ss.keys()):
        if key.startswith(_PAGE_WIDGET_PREFIXES) or key in _PAGE_TRANSIENT:
            del ss[key]
    for key, value in _DEFAULTS.items():
        ss[key] = value


def flags(ss: MutableMapping) -> dict[str, bool]:
    """The gating flags (see gating.py)."""
    return {
        "data_valid": bool(ss.get("data_valid")),
        "config_valid": bool(ss.get("config_valid")),
        "run_done": bool(ss.get("run_done")),
        "phase1_done": bool(ss.get("phase1_done")),
        "has_k": bool(ss.get("has_k")),
        "reexec_confirmed": bool(ss.get("reexec_confirmed")),
        "readonly": bool(ss.get("readonly")),
    }


def _is_set(value: Any) -> bool:
    return value is not None and value is not False and value != ""


def steps_with_results(ss: MutableMapping) -> list[int]:
    """Steps 2-6 that currently hold something. Step 6 (the report) has no state
    of its own: it exists once Phase 1 has run."""
    held = []
    for step in range(2, LAST_STEP + 1):
        if step == LAST_STEP:
            present = _is_set(ss.get("phase1_done"))
        else:
            present = any(_is_set(ss.get(key)) for key in STEP_KEYS[step])
        if present:
            held.append(step)
    return held


def first_cleared_step(ss: MutableMapping, from_step: int) -> int | None:
    """The first step after from_step that holds something, or None."""
    later = [s for s in steps_with_results(ss) if s > from_step]
    opener = OPENS_NEXT.get(from_step)
    if opener and _is_set(ss.get(opener)):
        later.append(from_step + 1)
    return min(later) if later else None


def clear_from(ss: MutableMapping, from_step: int) -> None:
    """Clear everything held by steps after from_step."""
    for step, keys in STEP_KEYS.items():
        if step > from_step:
            for key in keys:
                ss[key] = _DEFAULTS[key]
    opener = OPENS_NEXT.get(from_step)
    if opener:
        ss[opener] = False


def set_progress(ss: MutableMapping, level: int) -> None:
    """Preview only: set the gating flags for a given point in the flow.

    0 nothing, 1 data complete, 2 + configuration, 3 + run, 4 + Phase 1 (a pair
    with a first stage over τ), 5 + re-execution confirmed. Stores a marker
    instead of real results.
    """
    level = max(0, min(PROGRESS_MAX, int(level)))
    ss["data_valid"] = level >= 1
    ss["config_valid"] = level >= 2
    ss["run_done"] = level >= 3
    ss["run"] = "preview" if level >= 3 else None
    ss["phase1_done"] = level >= 4
    ss["has_k"] = level >= 4
    ss["phase1"] = "preview" if level >= 4 else None
    ss["reexec_confirmed"] = level >= 5


_UNSET = object()


def request_change(
    ss: MutableMapping,
    key: str,
    new: Any,
    widget_key: str | None = None,
    old_widget: Any = _UNSET,
    reset_uploader: bool = False,
    restore_many: dict[str, Any] | None = None,
) -> bool:
    """Change an input. Returns True if applied now.

    If later steps hold results, nothing is applied: a pending change is stored
    for the user to confirm or cancel, and False is returned.
    """
    from_step = INPUT_STEP[key]
    first = first_cleared_step(ss, from_step)
    if first is None:
        ss[key] = new
        clear_from(ss, from_step)
        ss["pending"] = None
        return True
    existing = ss.get("pending") or {}
    # Several fields can change before the user answers: remember the earliest old value of
    # each, so Cancel puts all of them back.
    restore = dict(existing.get("restore", {}))
    if widget_key is not None:
        restore.setdefault(widget_key, ss.get(key) if old_widget is _UNSET else old_widget)
    for many_key, many_old in (restore_many or {}).items():
        restore.setdefault(many_key, many_old)
    ss["pending"] = {
        "key": key,
        "old": existing.get("old", ss.get(key)),
        "new": new,
        "widget_key": widget_key,
        "restore": restore,
        "reset_uploader": reset_uploader or bool(existing.get("reset_uploader")),
        "first_cleared": first,
        "message": wording.clears_message(first),
    }
    return False


def confirm_pending(ss: MutableMapping) -> None:
    pending = ss.get("pending")
    if not pending:
        return
    ss[pending["key"]] = pending["new"]
    clear_from(ss, INPUT_STEP[pending["key"]])
    ss["pending"] = None


def cancel_pending(ss: MutableMapping) -> dict | None:
    """Keep everything; put every field changed meanwhile back to its old value.
    Returns the cancelled change (so a caller can also reset a file uploader), or None."""
    pending = ss.get("pending")
    if not pending:
        return None
    for widget_key, old in pending.get("restore", {}).items():
        ss[widget_key] = old
    ss["pending"] = None
    return pending


def summary_parts(ss: MutableMapping) -> list[tuple[str, str]]:
    """(label, text) pairs for the one-line summary strip (F2.2). Missing parts
    read 'not set yet'; nothing is invented."""
    not_set = wording.NOT_SET_YET
    weather = ss.get("weather")
    weather_name = weather.get("name") if isinstance(weather, dict) else None
    config = ss.get("config")
    tau = ss.get("tau")

    parts = [
        ("Analysis", ss.get("name") or not_set),
        ("Weather file", weather_name or not_set),
    ]
    for label in ("A", "B", "C"):
        models = config.get(label) if isinstance(config, dict) else None
        if isinstance(models, dict):
            order = ("decomposition", "transposition", "temperature", "dc", "ac")
            text = " · ".join(str(models.get(stage, "?")) for stage in order)
        else:
            text = not_set
        parts.append((f"Pipeline {label}", text))
    if isinstance(tau, dict):
        parts.append((wording.TAU, f"{tau['value']:g} ({tau['source']})"))
    else:
        parts.append((wording.TAU, not_set))
    return parts
