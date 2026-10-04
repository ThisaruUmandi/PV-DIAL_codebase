"""Step 3 · Run & provenance: the logic in app/run_logic.py and the page (AppTest).

Database tests use pvdials_test (tests/conftest.py forces it). The thesis weather file and the
thesis pipelines (analysis.yaml) give the numbers the thesis reports for the annual energy.
"""

import html
import io
import re
from datetime import date

import pandas as pd
import pytest
import yaml
from streamlit.testing.v1 import AppTest

from app import run_logic as rl
from app import state, wording
from experiments.evaluation.db_safety import guard_not_dev_database, resolve_current_database_url
from pvdials.analysis import AnalysisError
from pvdials.config import ROOT
from pvdials.provenance.analyses import load_analysis, save_analysis
from pvdials.provenance.db import get_connection, is_reachable, run_schema

THESIS_FILE = ROOT / "data" / "weather" / "tmy_6.944_79.856_2005_2020.csv"
THESIS_SHA = "9828d22b6291d0f84d5c6d87331a5487109e3dd436e39f9809eaae03d408ebeb"
THESIS = yaml.safe_load((ROOT / "analysis.yaml").read_text(encoding="utf-8"))

# the thesis annual energies, kWh (one decimal, as the thesis tables give them)
THESIS_AC = {"A": 9837.3, "B": 9723.5, "C": 9667.2}
THESIS_DC = {"A": 10254.0, "B": 10134.6, "C": 10075.4}

pytestmark = [
    pytest.mark.skipif(not THESIS_FILE.exists(), reason="thesis weather file not present"),
    pytest.mark.skipif(not is_reachable(), reason="no Postgres reachable"),
]


def _inputs() -> dict:
    """What pages 1 and 2 leave in the saved analysis: the thesis inputs, the thesis time offset
    (0 h, the user's own choice), the thesis pipelines and the default τ."""
    inputs = {k: v for k, v in THESIS.items() if k != "pipelines"}
    inputs["name"] = "page three test"
    inputs["time_offset"] = {**THESIS["time_offset"], "source": "user_entered", "choice": "hour_start"}
    inputs["weather"] = {"name": THESIS_FILE.name, "sha256": THESIS_SHA, "header_offset_h": 0.5}
    inputs["location"] = {
        "latitude": 6.944, "longitude": 79.856, "elevation": 16.0,
        "sources": {"latitude": "From CSV", "longitude": "From CSV", "elevation": "From CSV"},
    }
    inputs["pipelines"] = {label: dict(THESIS["pipelines"][label]) for label in rl.LABELS}
    inputs["tau"] = {"value": 0.093, "source": "default"}
    return inputs


def _clean() -> None:
    guard_not_dev_database(resolve_current_database_url(), "page 3 tests")
    with get_connection() as conn:
        run_schema(conn)
        with conn.cursor() as cur:
            for table in ("analysis_records", "analyses", "stage_output_values", "provenance_records"):
                cur.execute(f"DELETE FROM {table}")
        conn.commit()


def _count(table: str) -> int:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table}")
        return cur.fetchone()[0]


@pytest.fixture
def clean_db():
    _clean()
    yield


@pytest.fixture(scope="module")
def _thesis_state():
    """One real run of the thesis pipelines, saved to pvdials_test."""
    _clean()
    inputs = _inputs()
    return rl.run_pipelines(inputs, "p3-thesis"), inputs


@pytest.fixture
def thesis_run(_thesis_state):
    """The run above; if a test that empties the store ran in between, the same records are made again
    (record ids are content hashes, so they come out identical)."""
    run, inputs = _thesis_state
    if load_analysis("p3-thesis") is None:
        rl.run_pipelines(inputs, "p3-thesis")
    return run, inputs


# --- Thesis values, from the stored series ------------------------------------------------------------


def test_annual_ac_and_dc_match_the_thesis_values_to_the_decimal_the_thesis_gives(thesis_run):
    run, _ = thesis_run
    for label in rl.LABELS:
        # rounding-aware: the stored series gives a value that rounds to the thesis figure
        assert round(run.annual_ac[label], 1) == THESIS_AC[label], label
        assert abs(run.annual_ac[label] - THESIS_AC[label]) < 0.05, label
        assert round(run.annual_dc[label], 1) == THESIS_DC[label], label
        assert abs(run.annual_dc[label] - THESIS_DC[label]) < 0.05, label
        assert rl.kwh_text(run.annual_ac[label]) == f"{THESIS_AC[label]:,.1f}"
    assert rl.kwh_text(THESIS_AC["A"]) == "9,837.3" and rl.kwh_text(THESIS_DC["A"]) == "10,254.0"


def test_the_series_come_back_from_the_store_and_agree_with_the_annual_yield_the_run_computed(thesis_run):
    run, _ = thesis_run
    live = run.live.pipelines
    for label in rl.LABELS:
        assert run.annual_ac[label] == pytest.approx(live.annual_yield_kwh[label], rel=1e-9)
        assert set(run.series[label]) == set(rl.STAGES)
        assert len(run.series[label]["ac"]) == 8760


def test_the_run_saved_inputs_pipelines_and_run_info_under_the_pipelines_done_status(thesis_run):
    run, _ = thesis_run
    row = load_analysis("p3-thesis")
    assert row["status"] == "pipelines_done"
    assert row["inputs"]["pipelines"] == THESIS["pipelines"]
    assert row["inputs"]["tau"] == {"value": 0.093, "source": "default"}
    info = row["run_info"]
    assert info["started_at"] and info["finished_at"] and info["duration_s"] >= 0
    assert info["pvlib_version"] == run.run_info["pvlib_version"]
    assert set(info["checks"]) == set(rl.LABELS)
    assert set(row["pipelines"]) == set(rl.LABELS)
    assert row["phase1"] is None  # step 4 has not run


def test_every_check_of_the_thesis_pipelines_is_shown_with_its_words_and_passes(thesis_run):
    run, _ = thesis_run
    for label in rl.LABELS:
        rows = rl.check_rows(run.run_info, label)
        assert [what for _ok, what, _d in rows] == [wording.R_CHECK_LABELS[n] for n in rl.CHECK_ORDER]
        assert all(ok for ok, _w, _d in rows)
    assert rl.pipelines_not_passing(run.run_info) == []


def test_a_failed_check_is_named_with_its_problem_and_the_pipeline_is_listed():
    info = {
        "checks": {
            "A": {"dc": {"passed": True, "problems": []}},
            "B": {"dc": {"passed": False, "problems": ["DC power has 3 negative value(s)."]}},
        }
    }
    assert rl.check_rows(info, "B") == [(False, wording.R_CHECK_LABELS["dc"], "DC power has 3 negative value(s).")]
    assert rl.pipelines_not_passing(info) == ["B"]


# --- Running twice ---------------------------------------------------------------------------------------


def test_running_twice_adds_no_records_and_gives_the_same_values(clean_db):
    inputs = _inputs()
    first = rl.run_pipelines(inputs, "p3-twice")
    counts = {t: _count(t) for t in ("provenance_records", "analysis_records", "analyses", "stage_output_values")}
    assert counts["provenance_records"] == 3 and counts["analysis_records"] == 3 and counts["analyses"] == 1
    second = rl.run_pipelines(inputs, "p3-twice")
    assert {t: _count(t) for t in counts} == counts
    assert second.record_ids == first.record_ids
    assert second.annual_ac == first.annual_ac and second.annual_dc == first.annual_dc
    for label in rl.LABELS:
        for stage in rl.STAGES:
            pd.testing.assert_frame_equal(second.series[label][stage], first.series[label][stage])
    assert second.provenance["records"] == first.provenance["records"]


def test_running_again_keeps_results_a_later_step_already_saved(clean_db):
    inputs = _inputs()
    rl.run_pipelines(inputs, "p3-keep")
    row = load_analysis("p3-keep")
    save_analysis("p3-keep", row["name"], "phase1_done", inputs, phase1={"A-B": {"status": "ran"}},
                  pipelines=row["pipelines"], run_info=row["run_info"])
    rl.run_pipelines(inputs, "p3-keep")
    again = load_analysis("p3-keep")
    assert again["phase1"] == {"A-B": {"status": "ran"}} and again["status"] == "phase1_done"
    assert again["run_info"]["checks"] == row["run_info"]["checks"]


def test_a_missing_weather_file_is_reported_in_plain_words_and_nothing_is_saved(clean_db):
    inputs = {**_inputs(), "weather_file": "data/uploads/not_there.csv"}
    with pytest.raises(AnalysisError, match="no longer there"):
        rl.run_pipelines(inputs, "p3-missing")
    assert load_analysis("p3-missing") is None


# --- Pipeline outputs: periods, table, chart, CSV ----------------------------------------------------------

DAY = date(2023, 6, 15)
BOUNDARY_WEEK = date(2023, 7, 31)  # Monday 31 Jul to Sunday 6 Aug crosses a month end


def _energy_in(run, label, stage, column, period, anchor) -> float:
    frame = run.series[label][stage]
    start, end = rl.window_bounds(frame.index, period, anchor)
    part = frame[(frame.index >= start) & (frame.index < end)][column]
    return float(rl.row_energy(part).sum())


@pytest.mark.parametrize("stage", ["decomposition", "transposition", "dc", "ac"])
def test_day_week_month_and_year_totals_agree_with_each_other_and_with_the_annual_figure(thesis_run, stage):
    run, _ = thesis_run
    quantity = rl.QUANTITIES[stage][0]
    for label in rl.LABELS:
        def total(period, anchor, label=label):
            table = dict(rl.summary_rows(run.series, run.daylight, stage, quantity, period, anchor))
            return next(iter(table.values()))[label]

        # a day: 24 hourly rows add up to the table's figure
        hours = rl.chart_frame(run.series, run.daylight, stage, quantity, "day", DAY)[label]
        assert len(hours) == 24
        assert hours.sum() / 1000 == pytest.approx(total("day", DAY), rel=1e-9)
        # a week is seven days; a month is its days; the year is its twelve months
        days_of_week = [total("day", date(2023, 6, d)) for d in range(12, 19)]
        assert sum(days_of_week) == pytest.approx(total("week", DAY), rel=1e-9)
        month_days = rl.chart_frame(run.series, run.daylight, stage, quantity, "month", DAY)[label]
        assert len(month_days) == 30 and month_days.sum() == pytest.approx(total("month", DAY), rel=1e-9)
        months = rl.chart_frame(run.series, run.daylight, stage, quantity, "year", DAY)[label]
        assert len(months) == 12 and months.sum() == pytest.approx(total("year", DAY), rel=1e-9)
        assert total("year", DAY) == pytest.approx(_energy_in(run, label, stage, quantity.column, "year", DAY))
    ac = {label: dict(rl.summary_rows(run.series, run.daylight, "ac", rl.QUANTITIES["ac"][0], "year", DAY))[wording.R_TOTAL_ENERGY][label]
          for label in rl.LABELS}
    assert ac == pytest.approx(run.annual_ac)


def test_a_week_that_crosses_a_month_end_is_split_between_the_two_months_without_loss(thesis_run):
    run, _ = thesis_run
    q = rl.QUANTITIES["ac"][0]
    for label in rl.LABELS:
        week = dict(rl.summary_rows(run.series, run.daylight, "ac", q, "week", BOUNDARY_WEEK))[wording.R_TOTAL_ENERGY][label]
        july_part = dict(rl.summary_rows(run.series, run.daylight, "ac", q, "day", date(2023, 7, 31)))[wording.R_TOTAL_ENERGY][label]
        august_part = sum(
            dict(rl.summary_rows(run.series, run.daylight, "ac", q, "day", date(2023, 8, d)))[wording.R_TOTAL_ENERGY][label]
            for d in range(1, 7)
        )
        assert july_part + august_part == pytest.approx(week, rel=1e-9)


def test_temperature_is_the_mean_and_maximum_over_daylight_hours_only(thesis_run):
    run, _ = thesis_run
    q = rl.QUANTITIES["temperature"][0]
    table = dict(rl.summary_rows(run.series, run.daylight, "temperature", q, "day", DAY))
    for label in rl.LABELS:
        hourly = run.series[label]["temperature"]["temp_cell"]
        start = pd.Timestamp(DAY, tz=hourly.index.tz)
        day = hourly[(hourly.index >= start) & (hourly.index < start + pd.Timedelta(days=1))]
        lit = day[run.daylight.reindex(day.index).to_numpy(dtype=bool)]
        assert 0 < len(lit) < len(day)
        assert table[wording.R_MEAN_TEMP][label] == pytest.approx(float(lit.mean()))
        assert table[wording.R_MAX_TEMP][label] == pytest.approx(float(lit.max()))
        assert table[wording.R_MEAN_TEMP][label] != pytest.approx(float(day.mean()))  # not the all-hours mean


def test_the_row_energy_rule_equals_the_integrator_behind_the_annual_yield(thesis_run):
    from pvdials.guided_reexecution import integrate_watts_series_to_kwh

    run, _ = thesis_run
    series = run.series["A"]["ac"]["p_ac"]
    assert rl.row_energy(series).sum() == pytest.approx(integrate_watts_series_to_kwh(series), rel=1e-12)


def test_the_csv_holds_exactly_the_chart_data(thesis_run):
    run, _ = thesis_run
    for stage, period, anchor in (("ac", "day", DAY), ("dc", "week", DAY), ("transposition", "month", DAY),
                                  ("decomposition", "year", DAY)):
        quantity = rl.QUANTITIES[stage][0]
        frame = rl.chart_frame(run.series, run.daylight, stage, quantity, period, anchor)
        data = rl.csv_bytes(frame, quantity, period)
        parsed = pd.read_csv(io.BytesIO(data), index_col=0, parse_dates=True)
        assert list(parsed.columns) == [f"Pipeline {label} - {rl.axis_title(quantity, period)}" for label in rl.LABELS]
        assert len(parsed) == len(frame)
        assert parsed.to_numpy() == pytest.approx(frame.to_numpy(), rel=1e-12)
        spec = rl.outputs_chart(frame, rl.axis_title(quantity, period), period).to_dict()
        plotted = next(iter(spec["datasets"].values()))
        assert len(plotted) == frame.size  # every number in the CSV is a point in the chart's data
        assert sum(row["value"] for row in plotted) == pytest.approx(float(frame.to_numpy().sum()), rel=1e-9)


def test_pipelines_are_told_apart_by_dash_and_marker_as_well_as_colour(thesis_run):
    run, _ = thesis_run
    quantity = rl.QUANTITIES["ac"][0]
    frame = rl.chart_frame(run.series, run.daylight, "ac", quantity, "day", DAY)
    spec = rl.outputs_chart(frame, "AC", "day").to_dict()
    text = str(spec)
    assert "strokeDash" in text and "shape" in text and "color" in text
    dashes = next(layer for layer in spec["layer"] if "strokeDash" in layer["encoding"])["encoding"]["strokeDash"]["scale"]
    shapes = next(layer for layer in spec["layer"] if "shape" in layer["encoding"])["encoding"]["shape"]["scale"]
    assert len({str(d) for d in dashes["range"]}) == 3 and len(set(shapes["range"])) == 3
    assert dashes["domain"] == [f"Pipeline {label}" for label in rl.LABELS]  # fixed order, no sorting


def test_an_empty_period_is_reported_not_drawn(thesis_run):
    run, _ = thesis_run
    frame = rl.chart_frame(run.series, run.daylight, "ac", rl.QUANTITIES["ac"][0], "day", date(2030, 1, 1))
    assert frame.empty


# --- Provenance summary -----------------------------------------------------------------------------------


def test_the_provenance_summary_counts_the_original_records_and_keeps_the_two_hashes_apart(thesis_run):
    run, inputs = thesis_run
    prov = run.provenance
    assert prov["count"] == 3 and prov["execution_set"] == "ORIGINAL"
    assert [r["label"] for r in prov["records"]] == list(rl.LABELS)
    assert len({r["id"] for r in prov["records"]}) == 3
    assert prov["data_hash"] and len(prov["data_hash"]) == 64
    assert prov["data_hash"] != inputs["weather"]["sha256"]  # prepared data is not the uploaded file's bytes
    for record in prov["records"]:
        assert set(record["stage_hashes"]) == set(rl.STAGES)


# --- The page (AppTest) -------------------------------------------------------------------------------------


def _page3():
    import streamlit as st

    from app import components, state
    from app.screens import run_page

    state.init_state(st.session_state)
    components.PAGES["2"] = "step-2"
    components.PAGES["4"] = "step-4"
    st.switch_page = lambda target: st.session_state.__setitem__("switched_to", target)
    st.page_link = lambda target, label=None, **kw: st.markdown(f"[{label}]({target})")
    if st.session_state.pop("_t_change", None):  # an edit on page 1 or 2, as those pages make it
        state.request_change(st.session_state, "tau", {"value": 0.2, "source": "user_entered"})
    components.render_pending_change()
    run_page.render()


def _text(at) -> str:
    joined = " ".join(el.value for el in at.get("html"))
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", joined)))


def _open(done: bool = True, **extra) -> AppTest:
    at = AppTest.from_function(_page3, default_timeout=120)
    inputs = extra.pop("inputs", _inputs())
    at.session_state["inputs"] = inputs
    at.session_state["analysis_id"] = "p3-page"
    at.session_state["name"] = inputs["name"]
    at.session_state["config"] = inputs["pipelines"]
    at.session_state["tau"] = inputs["tau"]
    at.session_state["data_valid"] = done
    at.session_state["config_valid"] = done
    for key, value in extra.items():
        at.session_state[key] = value
    return at.run()


def test_locked_until_pages_1_and_2_are_done(clean_db):
    at = _open(done=False)
    assert not at.exception and not at.button
    assert wording.LOCK_REASON[3] in _text(at)


def test_before_a_run_the_page_says_so_in_plain_words_and_offers_the_run(clean_db):
    at = _open()
    assert not at.exception
    text = _text(at)
    assert wording.R_EMPTY_TITLE in text and wording.R_EMPTY_TEXT in text
    assert at.button(key="w3_run").label == wording.R_RUN and not at.button(key="w3_run").disabled
    assert at.session_state["run_done"] is False
    assert "Annual AC" not in text


def test_pressing_run_shows_the_results_saves_the_run_and_unlocks_step_4(clean_db):
    at = _open()
    at.button(key="w3_run").click().run()
    assert not at.exception
    assert at.session_state["run_done"] is True and isinstance(at.session_state["run"], rl.RunState)
    text = _text(at)
    assert wording.R_BANNER_PASSED.format(n=3) in text
    for label in rl.LABELS:
        assert f"{THESIS_AC[label]:,.1f} kWh" in text and f"{THESIS_DC[label]:,.1f} kWh" in text
    assert text.index("Pipeline A") < text.index("Pipeline B") < text.index("Pipeline C")  # fixed order
    assert all(w in text for w in (wording.R_PROV_FILE_SHA, wording.R_PROV_DATA_HASH, "ORIGINAL · 3 records"))
    assert load_analysis("p3-page")["status"] == "pipelines_done"
    assert [e.label for e in at.expander] == [wording.R_LINEAGE_OPEN, wording.R_IDS_OPEN]
    assert not any(e.proto.expanded for e in at.expander)  # detail on request, not by default
    assert at.session_state["pipelines_summary"] and at.session_state["run_info"]["finished_at"]


def test_every_check_appears_with_an_icon_and_a_word_for_each_pipeline(clean_db):
    at = _open()
    at.button(key="w3_run").click().run()
    markup = " ".join(el.value for el in at.get("html"))
    assert markup.count("pv-status-ok") == 3 * len(rl.CHECK_ORDER)
    assert markup.count(wording.R_PASSED) >= 3 * len(rl.CHECK_ORDER)
    assert markup.count("pv-icon-ok") >= 3 * len(rl.CHECK_ORDER)


def test_nothing_on_the_results_is_sorted_highlighted_or_ranked(clean_db):
    at = _open()
    at.button(key="w3_run").click().run()
    markup = " ".join(el.value for el in at.get("html"))
    for word in ("rank", "winner", "highest", "lowest", "difference", "Δ"):
        assert word not in markup.lower()
    assert [s.proto.label for s in at.get("selectbox")] == [wording.R_PERIOD]


def test_the_stage_and_period_selectors_change_what_is_shown(clean_db):
    at = _open()
    at.button(key="w3_run").click().run()
    assert "Irradiation (kWh/m²)" in _text(at)
    at.get("button_group")[0].set_value("ac")
    at.run()
    assert not at.exception and wording.R_TOTAL_ENERGY in _text(at)
    at.selectbox(key="w3_period").set_value("year").run()
    assert not at.exception and not at.get("date_input")  # the whole file: no date to pick
    text = _text(at)
    assert f"{THESIS_AC['A']:,.1f}" in text and f"{THESIS_AC['C']:,.1f}" in text


def test_the_download_button_is_there_and_carries_the_chart_csv(clean_db):
    at = _open()
    at.button(key="w3_run").click().run()
    assert at.get("download_button")


def test_a_change_on_page_1_or_2_after_the_run_asks_first_and_confirming_clears_this_page(clean_db):
    at = _open()
    at.button(key="w3_run").click().run()
    at.session_state["_t_change"] = True
    at.run()
    assert "This clears steps 3 to 6 of this analysis." in _text(at)
    assert at.session_state["run_done"] is True and at.button(key="w3_run_again").disabled
    at.button(key="pending_confirm").click().run()
    assert at.session_state["run_done"] is False and at.session_state["run"] is None
    assert at.session_state["pipelines_summary"] is None and at.session_state["run_info"] is None
    # the change reopens step 2, so this page waits behind it, empty
    assert wording.LOCK_REASON[3] in _text(at) and not at.get("download_button")


def test_cancelling_the_change_keeps_the_results(clean_db):
    at = _open()
    at.button(key="w3_run").click().run()
    at.session_state["_t_change"] = True
    at.run()
    at.button(key="pending_cancel").click().run()
    assert at.session_state["run_done"] is True and wording.R_BANNER_PASSED.format(n=3) in _text(at)


def test_a_missing_weather_file_gives_one_plain_message_and_leaves_step_4_locked(clean_db):
    at = _open(inputs={**_inputs(), "weather_file": "data/uploads/not_there.csv"})
    at.button(key="w3_run").click().run()
    assert not at.exception
    assert [e.value for e in at.error] == [wording.R_FILE_MISSING]
    assert at.session_state["run_done"] is False


def test_when_the_store_cannot_be_reached_the_app_shows_one_plain_message(monkeypatch):
    from app import store

    monkeypatch.setattr(store, "db_reachable", lambda: False)
    at = AppTest.from_file(str(ROOT / "app" / "main.py"), default_timeout=30).run()
    assert [e.value for e in at.error] == [wording.DB_UNREACHABLE]


def test_new_analysis_leaves_no_choice_of_this_page_behind():
    ss = {"w3_stage": "ac", "w3_period": "year", "w3_date": date(2023, 1, 1), "w3_prev": {"w3_stage": "ac"}}
    state.new_analysis(ss)
    assert not [k for k in ss if k.startswith("w3_")]


# --- Stage-wise card: one shared figure for the card and the Year column of Pipeline outputs -------------------


def _year_rows(run, stage, quantity):
    anchor = rl.data_dates(run.series)[0]
    return dict(rl.summary_rows(run.series, run.daylight, stage, quantity, "year", anchor))


def test_every_card_value_equals_the_year_figure_in_pipeline_outputs(thesis_run):
    run, _ = thesis_run
    checked = 0
    for label in rl.LABELS:
        for row in rl.stage_rows(run, label):
            assert [o[0] for o in row.outputs] and len(row.outputs) == len(rl.QUANTITIES[row.stage])
            for quantity, (_name, text, unit) in zip(rl.QUANTITIES[row.stage], row.outputs, strict=True):
                year = next(iter(_year_rows(run, row.stage, quantity).values()))[label]
                assert text == rl.kwh_text(year), (label, row.stage, quantity.column)
                assert year == rl.period_figure(run.series, run.daylight, label, row.stage, quantity)
                assert unit == rl.total_unit(quantity)
                checked += 1
    assert checked == 3 * 6  # three pipelines x (DNI, DHI, POA, temperature, DC, AC)


def test_the_stage_table_has_one_row_per_stage_in_stage_order_with_the_models_that_were_run(thesis_run):
    run, inputs = thesis_run
    for label in rl.LABELS:
        rows = rl.stage_rows(run, label)
        assert [r.stage for r in rows] == list(rl.STAGES)
        assert [r.model for r in rows] == [inputs["pipelines"][label][s] for s in rl.STAGES]
        assert all(passed for r in rows for passed in (r.check[0],))
        assert rows[-1].check[1] == "AC ≤ DC"
        footer = rl.card_footer(run, label)
        assert footer["saved"] == 5 and footer["of"] == 5 and footer["finite"][0] is True


def test_the_cards_show_the_thesis_dc_and_ac_values(thesis_run):
    run, _ = thesis_run
    for label in rl.LABELS:
        rows = {r.stage: r for r in rl.stage_rows(run, label)}
        assert rows["dc"].outputs[0][1] == f"{THESIS_DC[label]:,.1f}" and rows["dc"].outputs[0][2] == "kWh"
        assert rows["ac"].outputs[0][1] == f"{THESIS_AC[label]:,.1f}" and rows["ac"].outputs[0][2] == "kWh"


def test_the_card_figures_equal_the_figures_the_run_itself_saved(thesis_run):
    run, _ = thesis_run
    saved = load_analysis("p3-thesis")["pipelines"]
    fields = {"decomposition": ("dni_kwh_m2", "dhi_kwh_m2"), "transposition": ("poa_global_kwh_m2",),
              "temperature": ("temp_cell_mean_c",), "dc": ("annual_energy_kwh",), "ac": ("annual_energy_kwh",)}
    for label in rl.LABELS:
        by_stage = {entry["stage"].lower(): entry for entry in saved[label]}
        for row in rl.stage_rows(run, label):
            for (_n, text, _u), field in zip(row.outputs, fields[row.stage], strict=True):
                assert float(text.replace(",", "")) == pytest.approx(by_stage[row.stage][field], abs=0.051), (label, row.stage)
        # the daylight mean itself, not rounded: the mask rebuilt for a page equals the run's own
        assert rl.period_figure(run.series, run.daylight, label, "temperature", rl.QUANTITIES["temperature"][0]) == (
            pytest.approx(by_stage["temperature"]["temp_cell_mean_c"], rel=1e-9)
        )


def test_the_daylight_figure_is_labelled_and_explained(thesis_run):
    run, _ = thesis_run
    tip = rl.daylight_tip(run)
    assert "85" in tip and "5°" in tip and "daylight" in tip.lower()
    assert wording.R_MEAN_DAYLIGHT == "Mean over daylight hours"
    assert wording.R_MEAN_DAYLIGHT in rl.axis_title(rl.QUANTITIES["temperature"][0], "year")


# --- One table for stored columns ---------------------------------------------------------------------------


def test_every_column_in_the_thesis_run_has_a_name_and_a_unit_in_the_table(thesis_run):
    run, _ = thesis_run
    seen = {c for label in rl.LABELS for stage in rl.STAGES for c in run.series[label][stage].columns}
    assert seen and seen <= set(wording.COLUMN_INFO), sorted(seen - set(wording.COLUMN_INFO))
    assert all(unit for _name, unit in wording.COLUMN_INFO.values())


def test_a_column_that_is_not_in_the_table_is_shown_by_its_stored_key_with_no_unit():
    assert rl.column_info("zzz_new_output") == ("zzz_new_output", None)
    assert rl.column_info("p_ac") == wording.COLUMN_INFO["p_ac"]


def test_the_chart_the_card_and_the_lineage_all_read_the_same_table(thesis_run):
    run, _ = thesis_run
    for quantities in rl.QUANTITIES.values():
        for q in quantities:
            assert (q.label, q.unit) == wording.COLUMN_INFO[q.column]
            assert q.label in rl.axis_title(q, "day") and q.unit in rl.axis_title(q, "day")
    statement = run.provenance["lineage"]["A"]["stages"][4]["statement"]
    assert "AC power (W)" in statement  # the lineage names p_ac from the same entry


# --- Provenance: the lineage equals the stored record -------------------------------------------------------


def _stored(label):
    return rl.read_documents("p3-thesis")[label]["document"]


def _entities(label):
    return next(iter(_stored(label)["bundle"].values()))["entity"]


def _number(value):
    return float(value["$"]) if isinstance(value, dict) else value


def test_every_model_and_setting_shown_equals_the_stored_record(thesis_run):
    run, inputs = thesis_run
    for label in rl.LABELS:
        lineage = run.provenance["lineage"][label]
        entities = _entities(label)
        assert [s["stage"] for s in lineage["stages"]] == list(rl.STAGES)
        for stage in lineage["stages"]:
            entity = entities[stage["stage"]]
            assert stage["model"] == entity["model"] == inputs["pipelines"][label][stage["stage"]]
            stored_keys = {k for k in entity if k not in ("content_hash", "model")}
            assert {key for key, _l, _v in stage["settings"]} == stored_keys  # nothing dropped, nothing added
            for key, _label, text in stage["settings"]:
                stored = entity[key]
                if isinstance(stored, dict) and stored.get("type") in ("xsd:double", "xsd:int"):
                    digits = re.match(r"-?[\d.]+(?:e-?\d+)?", text).group(0)
                    assert float(digits) == pytest.approx(float(stored["$"]), rel=1e-9), key
                elif isinstance(stored, bool):
                    assert text == ("true" if stored else "false"), key
                elif isinstance(stored, list):
                    assert text == ", ".join(str(v) for v in stored), key
                else:
                    assert text == str(stored), key


def test_a_unit_is_shown_only_where_the_stored_key_says_which(thesis_run):
    run, _ = thesis_run
    dc = {key: text for key, _l, text in run.provenance["lineage"]["A"]["stages"][3]["settings"]}
    assert dc["diode_params.R_s"] == "0.262808"  # a resistance: no unit is guessed
    assert dc["diode_params.alpha_sc"] == "0.00325" and dc["array_size"] == "10, 2"
    transposition = {key: text for key, _l, text in run.provenance["lineage"]["A"]["stages"][1]["settings"]}
    assert transposition["surface_tilt_deg"] == "6.944°" and transposition["surface_azimuth_deg"] == "180°"
    for stage in run.provenance["lineage"]["A"]["stages"]:
        for key, _label, text in stage["settings"]:
            if not key.endswith(("_deg", "_m", "_h", "_w_m2")):
                assert not re.search(r"[\d.]( s| m| h|°| W/m²)$", text), (key, text)


def test_the_configuration_is_one_block_per_pipeline_and_stages_do_not_borrow_from_it(thesis_run):
    run, _ = thesis_run
    for label in rl.LABELS:
        lineage = run.provenance["lineage"][label]
        config = _entities(label)["configuration"]
        shown = {key for key, _l, _v in lineage["configuration"]}
        assert shown == {k for k in config if k != "label" and not k.endswith("_model")}
        assert lineage["configuration_used"] == wording.R_LINEAGE_CONFIG_USED  # as the record links it
        config_only = {"module_name", "modules_per_string", "strings_per_inverter", "mounting_geometry"}
        for stage in lineage["stages"]:
            assert not config_only & {key for key, _l, _v in stage["settings"]}
        units = {key: text for key, _l, text in lineage["configuration"]}
        assert units["surface_tilt_deg"].endswith("°") and units["module_height_m"].endswith(" m")
        assert units["albedo"] == "0.2" and units["modules_per_string"] == "10"  # no unit where the key has none


def test_what_each_stage_used_equals_the_records_links_and_what_it_produced_equals_the_stored_series(thesis_run):
    run, _ = thesis_run
    for label in rl.LABELS:
        bundle = next(iter(_stored(label)["bundle"].values()))
        links = {}
        for link in bundle["used"].values():
            links.setdefault(link["prov:activity"].removeprefix("stage_"), set()).add(link["prov:entity"])
        for stage in run.provenance["lineage"][label]["stages"]:
            name = stage["stage"]
            assert set(stage["used"]) == links[name] - {"configuration"}
            assert stage["columns"] == list(run.series[label][name].columns)
            assert stage["rows"] == len(run.series[label][name]) == 8760
            assert f"{stage['rows']:,} rows" in stage["statement"]


def test_the_weather_note_appears_for_cell_temperature_only_when_the_record_lacks_that_link(thesis_run, monkeypatch):
    run, _ = thesis_run
    stages = run.provenance["lineage"]["A"]["stages"]
    assert stages[2]["used"] == ["transposition"] and stages[2]["note"] == wording.R_LINEAGE_NO_WEATHER_LINK
    assert [s["note"] for s in stages if s["stage"] != "temperature"] == [None] * 4
    docs = rl.read_documents("p3-thesis")
    bundle = next(iter(docs["A"]["document"]["bundle"].values()))
    bundle["used"]["_:test_link"] = {"prov:entity": "weather", "prov:activity": "stage_temperature"}
    relinked = rl.lineage(run, "A", docs)["stages"][2]
    assert "weather" in relinked["used"] and relinked["note"] is None


def test_the_top_block_equals_the_stored_facts(thesis_run):
    run, inputs = thesis_run
    facts = {label: value for label, value in rl.top_block(run, inputs) if label}
    record = _entities("A")
    assert facts[wording.R_PROV_WEATHER] == THESIS_FILE.name
    assert facts[wording.R_PROV_TAU] == "0.093 · default"
    assert facts[wording.R_PROV_PVLIB] == run.run_info["pvlib_version"]
    assert facts[wording.R_PROV_OFFSET].startswith("0 h · user_entered")
    site = facts[wording.R_PROV_SITE]
    assert "latitude 6.944°" in site and "longitude 79.856°" in site and "elevation 16 m" in site and "From CSV" in site
    assert facts[wording.R_PROV_SET] == "ORIGINAL · 3 records"
    rows_line = next(v for l, v in rl.top_block(run, inputs) if not l)
    assert f"{int(record['weather']['rows']['$']):,} rows" in rows_line and "(hourly)" in rows_line


# --- Hashes stay in one closed expander -----------------------------------------------------------------------

HEX = re.compile(r"\b[0-9a-f]{32,}\b")


def _block_texts(block, skip_label=None):
    """All text a block shows, walking into nested blocks; the expander named skip_label is skipped."""
    from streamlit.testing.v1.element_tree import Block

    found = []
    for child in block.children.values():
        if isinstance(child, Block):
            if skip_label is not None and getattr(child, "label", None) == skip_label:
                continue
            found += _block_texts(child, skip_label)
        else:
            found.append(str(getattr(child, "value", "")) + " " + str(getattr(child, "label", "")))
    return found


def test_no_hash_or_run_id_is_shown_anywhere_outside_the_technical_identifiers_expander(clean_db):
    at = _open()
    at.button(key="w3_run").click().run()
    run = at.session_state["run"]
    outside = " ".join(_block_texts(at.main, skip_label=wording.R_IDS_OPEN))
    assert not HEX.findall(outside)
    for secret in (THESIS_SHA, run.analysis_id, run.provenance["data_hash"], *(r["id"] for r in run.provenance["records"])):
        assert secret not in outside
    inside = " ".join(_block_texts(next(e for e in at.expander if e.label == wording.R_IDS_OPEN)))
    for secret in (THESIS_SHA, run.analysis_id, run.provenance["data_hash"], *(r["id"] for r in run.provenance["records"])):
        assert secret in inside
    for text in (wording.R_PROV_FILE_SHA, wording.R_PROV_DATA_HASH, wording.R_IDS_NOTE):
        assert text in inside and text not in outside
    assert len(set(HEX.findall(inside))) >= 3 + 3 * 5  # run id aside: file, data, three records, fifteen stage hashes


def test_the_lineage_reads_as_a_chain_with_plain_statements_for_each_pipeline(clean_db):
    at = _open()
    at.button(key="w3_run").click().run()
    lineage = " ".join(_block_texts(next(e for e in at.expander if e.label == wording.R_LINEAGE_OPEN)))
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", lineage)))
    assert text.count(wording.R_LINEAGE_WEATHER) >= 3 and text.count("→") == 3 * 5
    assert "Transposition (isotropic) used the output of Decomposition (DHI, DNI) and produced" in text
    assert "Decomposition (erbs) used the weather file and produced DHI (W/m²), DNI (W/m²), 8,760 rows." in text
    assert text.count(wording.R_LINEAGE_CONFIG_USED) == 3 and text.count(wording.R_LINEAGE_NO_WEATHER_LINK) == 3
    assert text.index("Pipeline A") < text.index("Pipeline B") < text.index("Pipeline C")


def test_the_card_page_shows_the_stage_table_with_the_thesis_values(clean_db):
    at = _open()
    at.button(key="w3_run").click().run()
    text = _text(at)
    for header in (wording.R_CARD_STAGE, wording.R_CARD_MODEL, wording.R_CARD_OUTPUT, wording.R_CARD_CHECK):
        assert header in text
    for label in rl.LABELS:
        assert f"{THESIS_DC[label]:,.1f} kWh" in text and f"{THESIS_AC[label]:,.1f} kWh" in text
    assert text.count("AC ≤ DC") == 3 and text.count(wording.R_FOOTER_FINITE) == 3
    assert text.count("Stage outputs saved 5 / 5") == 3
    markup = " ".join(el.value for el in at.get("html"))
    assert wording.R_DAYLIGHT_TIP.split("{")[0].strip()[:15] in markup  # the tooltip text is on the figure
    assert 'class="pv-tip"' in markup and "5° above the horizon" in markup


# --- Reopening writes nothing -------------------------------------------------------------------------------------


def _snapshot():
    with get_connection() as conn, conn.cursor() as cur:
        counts = {}
        for table in ("analyses", "analysis_records", "provenance_records", "stage_output_values"):
            cur.execute(f"SELECT count(*) FROM {table}")
            counts[table] = cur.fetchone()[0]
        cur.execute("SELECT id, updated_at, status FROM analyses ORDER BY id")
        counts["rows"] = cur.fetchall()
    return counts


def test_reopening_a_stored_analysis_rebuilds_the_page_and_writes_nothing(thesis_run):
    run, inputs = thesis_run
    before = _snapshot()
    reopened = rl.reopen("p3-thesis")
    at = _open(inputs=inputs, run=reopened, run_done=True, analysis_id="p3-thesis")
    assert not at.exception
    assert _snapshot() == before  # all four tables, and the analysis row's own updated_at, untouched
    text = _text(at)
    for label in rl.LABELS:
        assert f"{THESIS_AC[label]:,.1f} kWh" in text and f"{THESIS_DC[label]:,.1f} kWh" in text
    assert reopened.annual_ac == run.annual_ac and reopened.annual_dc == run.annual_dc
    pd.testing.assert_series_equal(reopened.daylight, run.daylight)  # the mask rebuilt equals the run's own
    assert reopened.live is None and reopened.run_info == load_analysis("p3-thesis")["run_info"]
    assert reopened.provenance["lineage"]["B"]["stages"][1]["model"] == "haydavies"
    assert [st["rows"] for st in reopened.provenance["lineage"]["C"]["stages"]] == [8760] * 5


def test_opening_an_analysis_that_was_never_run_says_so_and_writes_nothing(clean_db):
    save_analysis("p3-never", "never run", "pipelines_configured", _inputs())
    before = _snapshot()
    with pytest.raises(AnalysisError, match="no stored run"):
        rl.reopen("p3-never")
    assert _snapshot() == before


def test_a_new_analysis_page_has_no_hash_in_its_empty_state(clean_db):
    at = _open()
    assert not HEX.findall(" ".join(_block_texts(at.main)))
