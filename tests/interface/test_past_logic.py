"""Past analyses and Home rows: how far an analysis got, what a row offers, copy names and the loader's
pure parts. No browser and no database."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app import analysis_logic as al
from app import past_logic as pl
from app import session_load as sl
from app import wording

FIXTURE = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "colombo_thesis_run_row.json").read_text())
PHASE1, PHASE2, PHASE3 = FIXTURE["phase1"], FIXTURE["phase2"], FIXTURE["phase3"]
INPUT_KEYS = sorted(["name", "weather_file", "time_offset", "site", "hardware", "pipelines", "tau", "location", "weather"])
ALL_SECTIONS = ["inputs", "phase1", "phase2", "phase3", "pipelines", "run_info"]


def _entry(**kw) -> dict:
    base = {
        "id": "a" * 32, "name": "x", "weather_file": "data/weather/f.csv", "updated_at": datetime(2026, 10, 5, 19, 10, tzinfo=UTC),
        "status": "started", "sections": ["inputs"], "input_keys": INPUT_KEYS, "phase1": None, "phase2": None, "phase3": None,
    }
    base.update(kw)
    return base


# --- how far an analysis got (the approved table) ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "sections", "expected"),
    [
        ("started", ["inputs"], ("stopped", 1)),
        ("load_done", ["inputs"], ("stopped", 1)),
        ("site_done", ["inputs"], ("stopped", 2)),
        ("pipelines_configured", ["inputs"], ("stopped", 3)),
        ("pipelines_done", ["inputs", "pipelines", "run_info"], ("stopped", 4)),
        ("pipelines_done", ["inputs"], ("stopped", 3)),  # says it ran, but the run was never stored
        ("done", ["inputs"], ("complete", None)),
    ],
)
def test_the_stopped_step_comes_from_the_status_for_steps_1_to_3_and_the_stored_run_for_step_4(status, sections, expected):
    got = pl.progress(status, sections)
    assert (got.kind, got.step) == expected


def test_phase_1_saved_with_phase_2_or_an_eligible_phase_3_still_to_run_is_stopped_at_step_4():
    held = [*ALL_SECTIONS[:2], "pipelines", "run_info"]
    only1 = pl.progress("phase1_done", held, PHASE1, None, None)
    assert (only1.kind, only1.step) == ("stopped", 4)
    no3 = pl.progress("phase2_done", [*held, "phase2"], PHASE1, PHASE2, {"B-C": PHASE3["B-C"]})  # A-B and A-C are eligible
    assert (no3.kind, no3.step) == ("stopped", 4)
    all3 = pl.progress("phase3_done", [*held, "phase2", "phase3"], PHASE1, PHASE2, PHASE3)
    assert all3.kind == "complete" and all3.text == wording.PAST_COMPLETE


def test_phase_1_alone_settles_the_analysis_when_no_pair_is_over_tau():
    settled = {pair: {"status": "ran", "outcome": 1, "k": None} for pair in pl.PAIRS}
    phase2_not_run = {"status": "not run", "reason": "no pair exceeds tau"}
    done = pl.progress("phase1_done", ["inputs", "phase1", "phase2", "pipelines", "run_info"], settled, phase2_not_run, {})
    assert done.kind == "complete"


def test_the_step_4_rule_agrees_with_the_analysis_page_logic():
    for phase3 in (None, {}, {"A-B": 1}, {"A-B": 1, "A-C": 1}, PHASE3):
        assert pl.step4_finished(PHASE1, PHASE2, phase3) == (
            al.phase3_done(PHASE1, phase3) or not al.phase3_eligible(PHASE1)
        )
    assert al.phase3_eligible(PHASE1) == [tuple(pair.split("-")) for pair in pl._eligible_for_phase3(PHASE1)]


def test_the_status_line_is_one_plain_line():
    assert pl.Progress("complete").text == "Complete"
    assert pl.Progress("stopped", 3).text == "Stopped at step 3"


# --- the outcome cell -------------------------------------------------------------------------------------------------


def test_the_outcome_cell_reads_a_b_3_a_c_1_b_c_1_and_says_not_run_yet_without_phase_1():
    assert pl.outcome_text(PHASE1) == "A–B 3 · A–C 3 · B–C 1"
    assert pl.outcome_text(None) == "Not run yet" == pl.outcome_text({})
    partial = {"A-B": {"status": "ran", "outcome": 2}, "A-C": {"status": "not run", "reason": "x"}}
    assert pl.outcome_text(partial) == "A–B 2 · A–C not computable · B–C not computable"


# --- what a row offers -------------------------------------------------------------------------------------------------


def test_a_complete_row_offers_open_and_duplicate_a_stopped_row_continue_and_duplicate():
    complete = pl.row_from_overview(_entry(status="done", sections=ALL_SECTIONS, phase1=PHASE1, phase2=PHASE2, phase3=PHASE3))
    assert complete.actions == ("open", "duplicate") and complete.main_action == "open" and complete.status == "Complete"
    stopped = pl.row_from_overview(_entry(status="site_done"))
    assert stopped.actions == ("continue", "duplicate") and stopped.main_action == "continue"
    assert stopped.status == "Stopped at step 2" and stopped.outcome == "Not run yet" and stopped.note is None


def test_a_row_without_the_inputs_a_step_needs_gets_no_continue_and_one_plain_line_why():
    row = pl.row_from_overview(_entry(status="pipelines_configured", input_keys=["name", "weather_file"]))
    assert row.actions == ("duplicate",) and row.note == wording.PAST_CANNOT_CONTINUE
    with_phase1 = pl.row_from_overview(
        _entry(status="phase1_done", sections=["inputs", "phase1", "pipelines", "run_info"], phase1=PHASE1, input_keys=["name"])
    )
    assert with_phase1.actions == ("open", "duplicate") and with_phase1.note == wording.PAST_CANNOT_CONTINUE


def test_the_file_name_is_the_stored_one_without_its_folder_and_a_missing_one_says_so():
    assert pl.row_from_overview(_entry(weather_file="data/uploads/ab12.csv")).file == "ab12.csv"
    assert pl.row_from_overview(_entry(weather_file=None)).file == "not recorded for this analysis"


def test_the_saved_time_is_utc_in_the_form_the_report_uses():
    assert pl.row_from_overview(_entry()).saved == "05 Oct 2026 19:10 UTC"


def test_no_order_by_disagreement_can_be_asked_for():
    for order in ("outcome", "disagreement", "nrmsd", "k"):
        with pytest.raises(ValueError):
            pl.past_rows(order=order)
    with pytest.raises(ValueError):
        pl.past_rows(status="in progress")
    assert [value for value, _label in wording.PAST_ORDERS] == ["newest", "oldest", "name"]
    assert [label for _value, label in wording.PAST_ORDERS] == ["Newest first", "Oldest first", "Name A–Z"]


# --- Duplicate: the copy's name ------------------------------------------------------------------------------------------


def test_a_copy_is_named_copy_then_copy_2_and_a_name_is_never_reused():
    assert pl.copy_name("Colombo", set()) == "Colombo (copy)"
    assert pl.copy_name("Colombo", {"Colombo (copy)"}) == "Colombo (copy 2)"
    assert pl.copy_name("Colombo (copy)", {"Colombo (copy)"}) == "Colombo (copy 2)"  # a copy of a copy does not stack
    assert pl.copy_name("Colombo (copy 2)", {"Colombo (copy)", "Colombo (copy 2)"}) == "Colombo (copy 3)"


# --- what may reach the address bar ----------------------------------------------------------------------------------------


def test_only_what_the_app_itself_makes_is_a_valid_id():
    assert sl.valid_id("0123456789abcdef0123456789abcdef")
    for bad in (None, "", "short", "0123456789ABCDEF0123456789abcdef", "0123456789abcdef0123456789abcde!", "a" * 33,
                "0123456789abcdef0123456789abcdef\n", "../etc/passwd", ["x"], 5):
        assert not sl.valid_id(bad), bad


def test_the_offset_choice_is_read_back_from_a_row_the_command_line_saved():
    assert sl.offset_choice({"choice": "hour_centre", "value_h": 0.0}) == "hour_centre"
    assert sl.offset_choice({"value_h": 0.0, "source": "user_entered"}) == "hour_start"
    assert sl.offset_choice({"value_h": 0.5, "source": "user_entered"}) == "hour_centre"
    assert sl.offset_choice({"value_h": 0.5, "source": "from_header"}) == "header"


def test_all_the_new_text_is_in_wording_and_keeps_the_agreed_wording_exact():
    assert [lead + " " + rest for lead, rest in wording.PAST_FOOTER] == [
        "Open shows a finished analysis on the Report page, read-only.",
        "Continue reopens an unfinished analysis at the step where it stopped.",
        "Duplicate starts a new analysis with the same inputs. Saved analyses are never edited.",
    ]
    assert wording.PAST_ORDER_NOTE == "Listed by date or name only — never by amount of disagreement."
    assert wording.PAST_NO_MATCH == "No analysis matches your search."
    assert wording.HOME_NOT_SHOWN == (
        "What it does not show: which pipeline is closer to the real system. There is no measured reference, so "
        "PV-DIALS reports how far the pipelines differ and never which one is right. Choosing between configurations "
        "stays with you."
    )
    assert wording.STEP_SUMMARIES[5] == "Swap one model at the localised stage."
    assert re.search(r"flagged", " ".join(wording.STEP_SUMMARIES.values())) is None
    assert wording.PAST_FILTERS == (("all", "All"), ("complete", "Complete"), ("stopped", "Stopped"))
