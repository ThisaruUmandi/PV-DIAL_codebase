"""Which steps are open, done, current or locked. Pure functions; no Streamlit."""

from __future__ import annotations

from collections.abc import Mapping

from app import wording

PAGE_KEYS = ("home", "1", "2", "3", "4", "5", "6", "past")
STEPS = (1, 2, 3, 4, 5, 6)


def is_unlocked(step: int, flags: Mapping[str, bool]) -> bool:
    """Steps open in order; Phase 2 and 3 are gated inside step 4 itself."""
    if step == 1:
        return True
    if step == 2:
        return bool(flags.get("data_valid"))
    if step == 3:
        return bool(flags.get("data_valid") and flags.get("config_valid"))
    if step == 4:
        return bool(flags.get("run_done"))
    if step == 5:
        return bool(flags.get("phase1_done") and flags.get("has_k"))
    if step == 6:
        return bool(flags.get("phase1_done"))
    raise ValueError(f"No such step: {step}")


def is_done(step: int, flags: Mapping[str, bool]) -> bool:
    """Step 6 is never 'done': it is a view of the finished analysis."""
    done = {
        1: "data_valid",
        2: "config_valid",
        3: "run_done",
        4: "phase1_done",
        5: "reexec_confirmed",
    }
    return bool(flags.get(done[step])) if step in done else False


def lock_reason(step: int, flags: Mapping[str, bool]) -> str | None:
    """Why a step is locked, or None if it is open."""
    return None if is_unlocked(step, flags) else wording.LOCK_REASON[step]


def page_status(page_key: str, flags: Mapping[str, bool], current: str) -> str:
    """One of 'current', 'locked', 'done', 'open' for a page key."""
    if page_key == current:
        return "current"
    if page_key in ("home", "past"):
        return "open"
    step = int(page_key)
    if not is_unlocked(step, flags):
        return "locked"
    return "done" if is_done(step, flags) else "open"


_STATUS_WORD = {
    "current": wording.STATUS_CURRENT,
    "locked": wording.STATUS_LOCKED,
    "done": wording.STATUS_DONE,
}


def status_word(page_key: str, status: str) -> str:
    """The word shown after a sidebar title: Done, Current or Locked. Open steps
    show none (as in the mock-ups); Home and Past never show one."""
    if page_key in ("home", "past") and status != "current":
        return ""
    return _STATUS_WORD.get(status, "")


def page_title(page_key: str) -> str:
    """Sidebar title, without number or status (the badge and the word are drawn
    beside it by the stylesheet)."""
    if page_key == "home":
        return wording.HOME_TITLE
    if page_key == "past":
        return wording.PAST_TITLE
    return wording.STEP_TITLES[int(page_key)]
