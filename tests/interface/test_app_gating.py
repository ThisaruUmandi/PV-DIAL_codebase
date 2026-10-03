"""Which steps are open, done, current or locked."""

import pytest

from app import gating, state, wording


def _flags(level: int, readonly: bool = False) -> dict:
    ss: dict = {}
    state.init_state(ss)
    state.set_progress(ss, level)
    ss["readonly"] = readonly
    return state.flags(ss)


@pytest.mark.parametrize(
    "level, open_steps",
    [(0, {1}), (1, {1, 2}), (2, {1, 2, 3}), (3, {1, 2, 3, 4}), (4, {1, 2, 3, 4, 5, 6}),
     (5, {1, 2, 3, 4, 5, 6})],
)
def test_steps_open_in_order(level, open_steps):
    flags = _flags(level)
    assert {s for s in gating.STEPS if gating.is_unlocked(s, flags)} == open_steps


def test_step_5_needs_a_pair_with_a_k():
    flags = _flags(4)
    flags["has_k"] = False  # Phase 1 ran, every pair outcome 1
    assert gating.is_unlocked(6, flags) and not gating.is_unlocked(5, flags)


def test_lock_reason_is_given_for_locked_steps_only():
    flags = _flags(0)
    assert gating.lock_reason(1, flags) is None
    for step in range(2, 7):
        assert gating.lock_reason(step, flags) == wording.LOCK_REASON[step]


def test_status_done_current_open_locked():
    flags = _flags(3)
    assert gating.page_status("3", flags, current="3") == "current"
    assert gating.page_status("1", flags, current="3") == "done"
    assert gating.page_status("4", flags, current="3") == "open"
    assert gating.page_status("5", flags, current="3") == "locked"
    assert gating.page_status("6", flags, current="3") == "locked"
    assert gating.page_status("home", flags, current="3") == "open"
    assert gating.page_status("past", flags, current="3") == "open"


def test_report_is_open_but_never_done():
    flags = _flags(5)
    assert gating.page_status("6", flags, current="1") == "open"


def test_sidebar_labels_carry_a_status_word_not_just_colour():
    assert gating.page_label("2", "locked") == "2 · Pipeline configuration — Locked"
    assert gating.page_label("1", "done") == "1 · Data & site — Done"
    assert gating.page_label("4", "current") == "4 · Analysis — Current"
    assert gating.page_label("home", "open") == "Home"
    assert gating.page_label("past", "current") == "Past analyses — Current"


def test_read_only_flag_does_not_change_which_steps_are_open():
    assert _flags(4, readonly=True)["readonly"] is True
    assert {s for s in gating.STEPS if gating.is_unlocked(s, _flags(4, True))} == set(gating.STEPS)
