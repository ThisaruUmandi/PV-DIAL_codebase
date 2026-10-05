"""The Report and its downloads that need no database: file names, escaping, the vendored libraries, the hour
label, the confirmed-change states, and the CSV columns."""

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import altair as alt
import pandas as pd
import pytest

from app import analysis_logic as al
from app import report_export as ex
from app import report_html as rh
from app import report_logic as rl
from app import wording
from tests.interface.test_reexec_logic import AFTER, BEFORE, _entry

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / "app" / "vendor" / "vega"
MANIFEST = json.loads((VENDOR / "VERSIONS.json").read_text(encoding="utf-8"))
SAVED = datetime(2026, 10, 5, 4, 53, tzinfo=UTC)


# --- File names -----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ('a<b>&"c/d e', "a_b_c_d_e_2026-10-05"),
        ("Colombo TMY · thesis", "Colombo_TMY_thesis_2026-10-05"),
        ("../../etc/passwd", "etc_passwd_2026-10-05"),
        ("   ", "analysis_2026-10-05"),
        ("...hidden", "hidden_2026-10-05"),
        ("é ü ñ", "e_u_n_2026-10-05"),
        ("CON:\\NUL*?|", "CON_NUL_2026-10-05"),
    ],
)
def test_the_download_file_stem_is_safe_for_a_file_system(name, expected):
    stem = ex.safe_stem(name, SAVED)
    assert stem == expected
    assert re.fullmatch(r"[A-Za-z0-9._-]+", stem) and not stem.startswith(".") and len(stem) <= 80


def test_a_very_long_name_is_cut():
    assert len(ex.safe_stem("x" * 500, SAVED)) <= 60 + len("_2026-10-05")


# --- The vendored libraries --------------------------------------------------------------------------------------------------


def test_the_vendored_versions_equal_what_the_installed_altair_declares():
    packages = MANIFEST["packages"]
    assert packages["vega-lite"]["version"] == alt.VEGALITE_VERSION  # exact
    assert packages["vega"]["version"].split(".")[0] == alt.VEGA_VERSION  # the declared major
    assert packages["vega-embed"]["version"].split(".")[0] == alt.VEGAEMBED_VERSION


def test_the_vendored_files_match_the_manifest_and_carry_their_licence():
    for name, entry in MANIFEST["packages"].items():
        data = (VENDOR / entry["file"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], name
        licence = (VENDOR / entry["licence_file"]).read_text(encoding="utf-8")
        assert "Redistribution and use in source and binary forms" in licence and entry["licence"] == "BSD-3-Clause"
        assert b"</script" not in data.lower() and b"<!--" not in data  # safe to inline in a script element


# --- Escaping, chart specs ---------------------------------------------------------------------------------------------------


def test_chart_specs_for_the_file_use_system_fonts_and_follow_the_page_width():
    from app import analysis_charts as charts

    entries = {k: BEFORE for k in ("A-B", "A-C", "B-C")}
    chart = charts.heatmap(al.phase1_view(entries))
    assert "IBM Plex" in json.dumps(chart.to_dict())  # the page keeps the design fonts
    spec = rh.spec_for_file(chart)
    assert "IBM Plex" not in json.dumps(spec) and "ui-monospace" in json.dumps(spec)
    assert spec["width"] == "container"


def test_script_json_cannot_close_the_script_element():
    text = rh._script_json({"a": "</script><!--", "b": "x y"})
    assert "<" not in text and " " not in text and json.loads(text)["a"] == "</script><!--"


# --- The hour label ---------------------------------------------------------------------------------------------------------------


def _series(tz):
    index = pd.date_range("2023-01-01", periods=48, freq="h", tz=tz)
    frame = pd.DataFrame({"p_ac": range(48)}, index=index)
    return {label: {"ac": frame} for label in "ABC"}


def test_the_hour_axis_says_utc_when_the_stored_time_stamps_are_utc_and_file_time_otherwise():
    assert rl.hour_label(_series("UTC")) == ("Hour of day (UTC, as in the file)", "UTC")
    assert rl.hour_label(_series("Asia/Colombo")) == ("Hour of day (file time)", "file time")
    assert rl.hour_label(_series(None)) == ("Hour of day (file time)", "file time")
    assert rl.hour_label(None) == ("Hour of day (file time)", "file time")


def test_the_hour_by_month_matrix_is_24_by_12_and_is_the_mean_of_the_absolute_difference():
    index = pd.date_range("2023-01-01", "2023-12-31 23:00", freq="h", tz="UTC")
    a = pd.Series(100.0, index=index)
    b = pd.Series(100.0, index=index)
    b[(index.month == 3) & (index.hour == 12)] = 160.0  # a 60 W gap at 12:00 in March, every day
    b[(index.month == 3) & (index.hour == 12) & (index.day == 1)] = 100.0  # except on the first
    matrix = rl.hour_month_matrix(a, b)
    assert matrix.shape == (24, 12) and list(matrix.index) == list(range(24)) and list(matrix.columns) == list(range(1, 13))
    assert matrix.loc[12, 3] == pytest.approx(60.0 * 30 / 31)  # mean over the 31 days of March
    assert matrix.drop(index=12).max().max() == 0.0 and matrix.loc[12, 4] == 0.0


def test_monthly_energy_adds_up_to_the_annual_energy_by_the_same_rule_as_page_3():
    from app import run_logic

    index = pd.date_range("2023-01-01", "2023-12-31 23:00", freq="h", tz="UTC")
    series = {label: {"ac": pd.DataFrame({"p_ac": [float(i % 7) * (k + 1) for i in range(len(index))]}, index=index)}
              for k, label in enumerate("ABC")}
    energy = rl.monthly_energy(series)
    assert energy.shape == (12, 3)
    for label in "ABC":
        annual = float(run_logic.row_energy(series[label]["ac"]["p_ac"]).sum())
        assert float(energy[label].sum()) == pytest.approx(annual, rel=1e-12)


# --- The confirmed-change states ------------------------------------------------------------------------------------------------


def _row(reexec, k="TEMPERATURE"):
    phase1 = {key: _entry((0.1235, 0.0036, 0.1534, 0.0173, 0.0172), k=k) for key in ("A-B", "A-C", "B-C")}
    return {
        "inputs": {"pipelines": {"A": {"decomposition": "erbs", "transposition": "isotropic", "temperature": "faiman",
                                       "dc": "singlediode_cec", "ac": "sandia"}}},
        "phase1": phase1, "reexec": reexec,
    }


def _texts(section):
    return [getattr(b, "text", None) or getattr(b, "rows", None) or getattr(b, "html", "") for b in section.blocks]


def test_without_a_confirmed_change_the_section_says_so():
    section = rl._reexec_section(_row(None), None)
    assert [b.text for b in section.blocks] == ["No change was confirmed."]


def test_a_confirmed_change_shows_track_change_yield_table_chart_note_and_the_exact_disclaimer():
    reexec = {
        "pair": ["A", "B"], "config_label": "A_B_confirmed", "annual_yield_kwh": 9864.3351, "disclaimer": "x",
        "substituted_stage_model": {}, "anchor": "A", "stage": "TEMPERATURE", "candidate": "noct_sam", "phase1": AFTER,
    }
    section = rl._reexec_section(_row(reexec), None)
    assert section.sub == "A – B track · anchor A · stage 3, Cell temperature"
    columns = section.blocks[0]
    assert isinstance(columns, rl.Columns)  # change and yield on the left, the table on the right, as in the mock-up
    assert columns.left[0].rows == [("Change", "faiman → noct_sam")]
    assert columns.left[1].label == "Annual yield, A with noct_sam" and columns.left[1].value == "9,864.3 kWh"
    table = columns.right[0].html
    assert "Confirmed noct_sam" in table and "3 · Cell temperature" in table and "5 · AC conversion" in table
    assert "1 · Decomposition" not in table  # from the localised stage on, as in the mock-up
    assert any(isinstance(b, rl.Chart) for b in section.blocks)
    texts = [b.text for b in section.blocks if isinstance(b, rl.Text)]
    assert texts == [wording.RP_RX_NOTE, wording.DISCLAIMER]
    assert wording.RP_RX_NOTE == "Every attempt is kept in the provenance record; only the confirmed change is shown here."


def test_a_row_saved_before_the_new_shape_says_not_recorded_for_the_missing_parts():
    old = {"pair": ["A", "B"], "config_label": "A_B_confirmed", "annual_yield_kwh": 9800.0, "disclaimer": "x",
           "substituted_stage_model": {}}
    section = rl._reexec_section(_row(old), None)
    assert "not recorded for this analysis" in section.sub
    columns = section.blocks[0]
    assert columns.left[0].rows == [("Change", wording.RX_NOT_RECORDED)]
    assert columns.left[1].value == "9,800.0 kWh"
    table = columns.right[0].html
    assert table.count(wording.RX_NOT_RECORDED) == 3  # the Confirmed column, three stages (3 · to 5 ·)
    assert not any(isinstance(b, rl.Chart) for b in section.blocks)  # nothing saved to draw


def test_a_pair_that_is_not_computable_after_the_change_shows_its_reason_and_no_chart():
    from pvdials.analysis import phase1_to_dict

    reexec = {"pair": ["A", "B"], "config_label": "x", "annual_yield_kwh": None, "disclaimer": "x", "substituted_stage_model": {},
              "anchor": "A", "stage": "TEMPERATURE", "candidate": "noct_sam",
              "phase1": phase1_to_dict("not computable — zero spread at stage DC")}
    section = rl._reexec_section(_row(reexec), None)
    assert section.blocks[0].left[1].value == wording.RX_YIELD_NONE
    assert any(isinstance(b, rl.Text) and b.text == "Not computable — zero spread at stage DC power" for b in section.blocks)
    assert not any(isinstance(b, rl.Chart) for b in section.blocks)


def test_the_sections_come_in_the_order_of_the_mock_up():
    assert [wording.RP_S_INPUTS, wording.RP_S_PIPELINES, wording.RP_S_P1, wording.RP_S_P2, wording.RP_S_P3,
            wording.RP_S_YEAR, wording.RP_S_REEXEC, wording.RP_S_PROV] == [
        "Inputs", "Pipelines", "Phase 1 · Where", "Phase 2 · How it carries", "Phase 3 · How much",
        "Disagreement over the year", "Guided re-execution · confirmed change", "Provenance",
    ]
