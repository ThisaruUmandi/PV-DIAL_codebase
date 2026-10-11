"""Step 1 · Data & site: the logic in app/services.py and the page itself (AppTest).

Database tests use pvdials_test (tests/conftest.py forces it). The thesis weather file
is used for acceptance only: the app never asserts its hash.
"""

import html
import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app import services, state, wording
from experiments.evaluation.db_safety import guard_not_dev_database, resolve_current_database_url
from pvdials.provenance.analyses import load_analysis, recorded
from pvdials.provenance.db import get_connection, is_reachable, run_schema

ROOT = Path(__file__).resolve().parents[2]
THESIS = ROOT / "data" / "weather" / "tmy_6.944_79.856_2005_2020.csv"
THESIS_SHA = "9828d22b6291d0f84d5c6d87331a5487109e3dd436e39f9809eaae03d408ebeb"
SAMPLE = ROOT / "tests" / "fixtures" / "sample_pvgis_tmy.csv"

needs_thesis = pytest.mark.skipif(not THESIS.exists(), reason="thesis weather file not present")
needs_db = pytest.mark.skipif(not is_reachable(), reason="no Postgres reachable")


@pytest.fixture(autouse=True)
def _no_writes_to_the_real_upload_store(tmp_path, monkeypatch):
    from pvdials.data import upload

    monkeypatch.setattr(upload, "UPLOADS_DIR", tmp_path / "uploads")


@pytest.fixture
def clean_db():
    guard_not_dev_database(resolve_current_database_url(), "page 1 tests")
    with get_connection() as conn:
        run_schema(conn)
        with conn.cursor() as cur:
            for table in ("analysis_records", "analyses", "stage_output_values", "provenance_records"):
                cur.execute(f"DELETE FROM {table}")
        conn.commit()
    yield


def _complete_form(ingest: services.Ingest, **overrides) -> services.Form:
    values = {
        "name": "page one test",
        "latitude": ingest.site_found.get("latitude"),
        "longitude": ingest.site_found.get("longitude"),
        "elevation": ingest.site_found.get("elevation"),
        "tilt": 6.944, "azimuth": 180.0,
        "module": "Canadian_Solar_Inc__CS6K_300MS",
        "inverter": "ABB__PVI_6000_OUTD_S_US_A__208V_",
        "modules_per_string": 10, "strings_per_inverter": 2, "module_height_m": 3.0,
    }
    values.update(overrides)
    return services.Form(**values)


# --- Reading the file: acceptance with the thesis file -----------------------------------------


@needs_thesis
def test_thesis_file_acceptance():
    ingest = services.ingest_upload(THESIS.read_bytes(), THESIS.name)
    assert ingest.usable and ingest.sha256 == THESIS_SHA
    assert ingest.rows == 8760 and ingest.hourly and ingest.source_label == "PVGIS TMY"
    assert ingest.missing_required == [] and ingest.columns["pressure"] == "SP"
    assert all(r.passed and not r.warnings for r in ingest.tiers.values())
    assert ingest.header_offset.value_h == 0.5 and ingest.header_offset.source == "file"
    assert ingest.site_found == {"latitude": 6.944, "longitude": 79.856, "elevation": 16.0}

    form = _complete_form(ingest)
    counts = {c.label: (c.value_h, c.ghi_positive_sun_down, c.ghi_zero_sun_up)
              for c in services.offset_counts(ingest, form)}
    assert counts == {"header": (0.5, 91, 38), "hour_start": (0.0, 0, 0), "hour_centre": (0.5, 91, 38)}
    tier4 = services.tier4_result(ingest, form)
    assert tier4.passed
    assert services.blockers(form, ingest) == []


def test_offset_labels_use_the_files_own_header_value():
    ingest = services.ingest_upload(SAMPLE.read_bytes(), "sample.csv")
    assert ingest.header_offset.value_h == 0.5
    assert services.offset_labels(ingest)["header"] == "Header (0.5 h)"
    no_header = SAMPLE.read_text().replace("Irradiance Time Offset (h): 0.5\n", "")
    ingest = services.ingest_upload(no_header.encode(), "no_offset.csv")
    assert services.offset_labels(ingest)["header"] == wording.D_OFFSET_HEADER_ABSENT
    assert ingest.header_offset.source == "assumed_absent_from_header"


# --- Bad files: plain-words messages ------------------------------------------------------------


def test_file_missing_a_required_column_gets_a_plain_message():
    text = SAMPLE.read_text().replace("G(h)", "Gx")
    ingest = services.ingest_upload(text.encode(), "no_ghi.csv")
    assert not ingest.usable and ingest.missing_required == ["ghi"]
    assert ingest.problem == (
        "The file is missing the column(s) GHI, so it cannot be used. "
        "Upload a file that has GHI, T2m and WS10m."
    )
    blockers = services.blockers(services.Form(name="x"), ingest)
    assert blockers == [ingest.problem]


def test_file_that_is_not_a_weather_csv_gets_a_plain_message():
    ingest = services.ingest_upload(b"", "empty.csv")
    assert not ingest.usable
    assert ingest.problem.startswith("That file could not be read as a weather CSV (")
    assert ingest.problem.endswith("Upload an hourly PVGIS TMY file saved as .csv.")


def test_a_failed_tier_blocks_continue_and_names_the_tier():
    text = SAMPLE.read_text().replace("20190228:2300,24.3,", "20190228:2300,,")  # a missing temperature
    ingest = services.ingest_upload(text.encode(), "gap.csv")
    assert ingest.usable and not ingest.tiers[1].passed
    assert ingest.tiers[1].problems == ["Column 'temp_air' has 1 missing value(s)."]
    reasons = services.blockers(_complete_form(ingest), ingest)
    assert any("Tier 1 · structure" in r and "fix the file and upload it again" in r for r in reasons)


def test_duplicate_time_stamps_are_reported_in_plain_words():
    text = SAMPLE.read_text().replace("20190228:2300,24.3", "20190228:2200,24.3")
    ingest = services.ingest_upload(text.encode(), "dup.csv")
    assert not ingest.usable
    assert "share the same month, day and hour" in ingest.problem
    assert ingest.problem.endswith("Upload an hourly PVGIS TMY file saved as .csv.")


def test_blockers_name_every_missing_input_in_plain_words():
    ingest = services.ingest_upload(SAMPLE.read_bytes(), "sample.csv")
    reasons = services.blockers(services.Form(), ingest)
    for expected in (
        wording.D_NEED_NAME, wording.D_NEED_LAT, wording.D_NEED_LON, wording.D_NEED_TILT,
        wording.D_NEED_AZIMUTH, wording.D_NEED_MODULE, wording.D_NEED_INVERTER,
        wording.D_NEED_MODULES, wording.D_NEED_STRINGS, wording.D_NEED_HEIGHT,
    ):
        assert expected in reasons
    assert services.blockers(services.Form(), None) == [wording.D_NEED_NAME, wording.D_NEED_FILE]


def test_an_offset_that_differs_from_the_header_needs_a_reason():
    ingest = services.ingest_upload(SAMPLE.read_bytes(), "sample.csv")
    form = _complete_form(ingest, offset_choice="hour_start", offset_reason="")
    assert wording.D_NEED_REASON in services.blockers(form, ingest)
    form = _complete_form(ingest, offset_choice="hour_start", offset_reason="file aligns with 0 h")
    assert services.blockers(form, ingest) == []


# --- Saving through the shared path --------------------------------------------------------------


@needs_db
def test_commit_saves_load_done_then_site_done_with_the_shared_inputs_shape(clean_db):
    ingest = services.ingest_upload(SAMPLE.read_bytes(), "sample.csv")
    done = services.commit_page1(_complete_form(ingest), ingest)
    row = load_analysis(done.analysis_id)
    assert row["status"] == "site_done" and row["name"] == "page one test"
    inputs = row["inputs"]
    assert inputs["weather"]["sha256"] == ingest.sha256 and inputs["weather"]["name"] == "sample.csv"
    assert inputs["weather"]["header_offset_h"] == 0.5
    assert inputs["time_offset"] == {
        "value_h": 0.5, "reason": "", "source": "file", "choice": "header",
    }
    assert inputs["location"] == {
        "latitude": 6.944, "longitude": 79.856, "elevation": 16.0,
        "sources": {"latitude": "From CSV", "longitude": "From CSV", "elevation": "From CSV"},
    }
    assert inputs["tau"] == {"value": 0.093, "source": "default"}
    assert inputs["hardware"]["module_name"] == "Canadian_Solar_Inc__CS6K_300MS"
    assert inputs["site"]["tilt_deg"] == 6.944 and inputs["site"]["albedo"] is None
    assert row["phase1"] is None and recorded(row, "run_info", "checks") == "not recorded for this analysis"


@needs_db
def test_a_chosen_offset_is_saved_as_the_users_with_its_reason(clean_db):
    ingest = services.ingest_upload(SAMPLE.read_bytes(), "sample.csv")
    form = _complete_form(ingest, offset_choice="hour_start", offset_reason="file aligns with 0 h")
    done = services.commit_page1(form, ingest)
    assert done.inputs["time_offset"] == {
        "value_h": 0.0, "reason": "file aligns with 0 h", "source": "user_entered", "choice": "hour_start",
    }
    assert done.site_result.ctx.settings["time_offset_source"] == "user_entered"


@needs_db
def test_saving_again_with_the_same_id_replaces_the_row_not_adds_one(clean_db):
    ingest = services.ingest_upload(SAMPLE.read_bytes(), "sample.csv")
    first = services.commit_page1(_complete_form(ingest), ingest)
    services.commit_page1(_complete_form(ingest, name="renamed"), ingest, analysis_id=first.analysis_id)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM analyses")
        assert cur.fetchone()[0] == 1
    assert load_analysis(first.analysis_id)["name"] == "renamed"


# --- State: a finished step 1 needs the warning -----------------------------------------------------


def test_changing_a_page_1_input_after_continue_warns_and_confirm_reopens_the_step():
    ss: dict = {}
    state.init_state(ss)
    ss["data_valid"] = True  # Continue was pressed; nothing later holds a result yet
    applied = state.request_change(ss, "site", {"tilt": 10}, widget_key="w", old_widget=6.9)
    assert applied is False
    assert ss["pending"]["message"] == "This clears steps 2 to 6 of this analysis."
    state.confirm_pending(ss)
    assert ss["site"] == {"tilt": 10} and ss["data_valid"] is False


def test_cancel_puts_the_widget_back_to_its_own_old_value():
    ss: dict = {"w": 10}
    state.init_state(ss)
    ss["data_valid"] = True
    state.request_change(ss, "site", {"tilt": 10}, widget_key="w", old_widget=6.9)
    state.cancel_pending(ss)
    assert ss["w"] == 6.9 and ss["data_valid"] is True and ss["pending"] is None


# --- The page (AppTest) ----------------------------------------------------------------------------------


def _page1():
    import streamlit as st

    from app import components, state
    from app.screens import data_site

    state.init_state(st.session_state)
    components.PAGES["2"] = "step-2"
    st.switch_page = lambda target: st.session_state.__setitem__("switched_to", target)
    components.render_pending_change()
    data_site.render()


def _text(at) -> str:
    joined = " ".join(el.value for el in at.get("html"))
    return html.unescape(re.sub(r"<[^>]+>", " ", joined))


def _fresh() -> AppTest:
    return AppTest.from_function(_page1, default_timeout=60).run()


def _upload(at: AppTest, path: Path = SAMPLE) -> AppTest:
    key = f"w1_upload_{at.session_state['upload_n']}"
    at.get_by_key(key).upload(path.name, path.read_bytes(), "text/csv")
    return at.run()


def _fill_required(at: AppTest) -> AppTest:
    at.number_input(key="w1_tilt").set_value(6.944)
    at.number_input(key="w1_azimuth").set_value(180.0)
    at.number_input(key="w1_modules_per_string").set_value(10)
    at.number_input(key="w1_strings_per_inverter").set_value(2)
    at.number_input(key="w1_module_height_m").set_value(3.0)
    return at.run()


def test_empty_page_blocks_continue_and_lists_what_is_missing():
    at = _fresh()
    assert not at.exception
    assert [t.value for t in at.title] == ["Data & site"]
    assert at.button(key="w1_continue").disabled
    text = _text(at)
    assert wording.D_CHECKLIST_TITLE in text
    assert "Analysis name — needs a value" in re.sub(r"\s+", " ", text)
    assert "Weather file uploaded" in text and wording.D_DROP_NOTE in text
    # a field's tag is a word beside its label
    assert "required" in text and "optional" in text and "default" in text


def test_the_drop_zone_prompt_is_handed_to_the_stylesheet_from_wording():
    from app import theme

    assert f'--pv-drop-text: "{wording.D_DROP_TEXT}"' in theme.text_variables()
    assert wording.D_DROP_TEXT == "Drag a CSV here or click to browse"
    assert 'content: var(--pv-drop-text)' in theme.stylesheet()


def test_uploading_a_file_replaces_the_drop_zone_by_a_summary_strip():
    at = _upload(_fresh())
    assert not at.exception
    text = re.sub(r"\s+", " ", _text(at))
    ingest = at.session_state["ingest"]
    assert "sample_pvgis_tmy.csv" in text and "rows" in text and "hourly" in text
    assert "Required columns found (GHI, T2m, WS10m, SP)" in text
    assert wording.LABEL_FILE_SHA in text and ingest.sha256 in text
    assert wording.D_DROP_NOTE not in text  # the drop zone is gone
    assert ingest.sha256 == services.ingest_upload(SAMPLE.read_bytes(), "x").sha256
    # site prefilled from the file, locked, and tagged as such
    assert at.number_input(key="w1_latitude").value == 6.944 and at.number_input(key="w1_latitude").disabled
    assert text.count("from file") >= 3


def test_a_file_missing_a_column_shows_the_plain_message_and_keeps_continue_blocked():
    bad = SAMPLE.read_text().replace("G(h)", "Gx").encode()
    at = _fresh()
    at.get_by_key("w1_upload_0").upload("no_ghi.csv", bad, "text/csv")
    at.run()
    expected = (
        "The file is missing the column(s) GHI, so it cannot be used. "
        "Upload a file that has GHI, T2m and WS10m."
    )
    text = re.sub(r"\s+", " ", _text(at))
    assert expected in text
    assert "pv-msg-bad" in " ".join(el.value for el in at.get("html"))  # a cross icon + the words
    assert at.button(key="w1_continue").disabled
    assert wording.D_DROP_NOTE in text  # nothing was accepted, so the drop zone stays


@needs_db
def test_filling_the_form_enables_continue_saves_and_opens_step_2(clean_db):
    at = _upload(_fresh())
    assert at.button(key="w1_continue").disabled
    at = _fill_required(at)
    assert not at.button(key="w1_continue").disabled
    at.button(key="w1_continue").click().run()
    assert not at.exception
    assert at.session_state["data_valid"] is True and at.session_state["switched_to"] == "step-2"
    row = load_analysis(at.session_state["analysis_id"])
    assert row["status"] == "site_done" and row["inputs"]["site"]["tilt_deg"] == 6.944
    assert at.session_state["flash"] == wording.D_SAVED_FLASH


@needs_db
def test_editing_after_continue_shows_the_warning_and_cancel_keeps_the_value(clean_db):
    at = _fill_required(_upload(_fresh()))
    at.button(key="w1_continue").click().run()
    at.number_input(key="w1_tilt").set_value(20.0).run()
    assert "This clears steps 2 to 6 of this analysis." in _text(at)
    assert at.session_state["data_valid"] is True
    assert at.button(key="w1_continue").disabled  # nothing else can be changed or saved meanwhile
    at.button(key="pending_cancel").click().run()
    assert at.number_input(key="w1_tilt").value == 6.944
    assert "This clears steps" not in _text(at) and at.session_state["data_valid"] is True


@needs_db
def test_confirming_the_change_applies_it_and_reopens_the_step(clean_db):
    at = _fill_required(_upload(_fresh()))
    at.button(key="w1_continue").click().run()
    at.number_input(key="w1_tilt").set_value(20.0).run()
    at.button(key="pending_confirm").click().run()
    assert at.number_input(key="w1_tilt").value == 20.0
    assert at.session_state["data_valid"] is False
    assert not at.button(key="w1_continue").disabled  # the step can be confirmed again


def test_choosing_a_different_offset_needs_a_reason_before_continue():
    at = _fill_required(_upload(_fresh()))
    assert not at.button(key="w1_continue").disabled
    at.radio(key="w1_offset_choice").set_value("hour_start").run()
    assert at.button(key="w1_continue").disabled
    assert "Time offset — needs a reason" in re.sub(r"\s+", " ", _text(at))
    at.text_input(key="w1_offset_reason").set_value("file aligns with 0 h").run()
    assert not at.button(key="w1_continue").disabled


@needs_thesis
def test_page_with_the_thesis_file_shows_the_acceptance_numbers():
    at = _upload(_fresh(), THESIS)
    assert not at.exception
    text = _text(at)
    assert at.session_state["ingest"].sha256 == THESIS_SHA
    table = re.sub(r"\s+", " ", text)
    assert "Header (0.5 h) 91 38" in table
    assert "Hour-start (0 h) 0 0" in table
    assert "Hour-centre (0.5 h) 91 38" in table
    assert "Tiers 1–4 passed · 0 warnings" in table and "8,760 rows · hourly · PVGIS TMY" in table


# --- the polish: tags, messages, checklist -------------------------------------------------------------


def test_every_field_carries_a_word_tag():
    at = _upload(_fresh())
    html_all = " ".join(el.value for el in at.get("html"))
    for kind in ("pv-tag-file", "pv-tag-required", "pv-tag-optional", "pv-tag-default"):
        assert kind in html_all
    # tags are words, so they read without colour
    for word in (wording.TAG_FROM_FILE, wording.TAG_REQUIRED, wording.TAG_OPTIONAL, wording.TAG_DEFAULT):
        assert f">{word}</span>" in html_all.replace('<span class="pv-icon pv-icon-lock" style="width:12px;height:12px" aria-hidden="true"></span>', "")


def test_messages_carry_an_icon_and_words():
    from app import components

    for kind, glyph in (("ok", "ok"), ("warn", "warn"), ("bad", "bad")):
        html_text = components.message_html(kind, "words")
        assert f"pv-icon-{glyph}" in html_text and "<span>words</span>" in html_text


def test_checklist_ticks_what_is_done_and_names_what_is_still_needed():
    ingest = services.ingest_upload(SAMPLE.read_bytes(), "sample.csv")
    partial = services.checklist(_complete_form(ingest, tilt=None, module_height_m=None), ingest)
    by_key = {c.key: c for c in partial}
    assert by_key["name"].done and by_key["file"].done and by_key["tiers"].done and by_key["site"].done
    assert not by_key["orient"].done and by_key["orient"].needs == ("tilt",)
    assert not by_key["hardware"].done and by_key["hardware"].needs == ("module height",)
    complete = services.checklist(_complete_form(ingest), ingest)
    assert all(c.done for c in complete)
    # the checklist and the old list of reasons always agree
    for form in (_complete_form(ingest), _complete_form(ingest, tilt=None), services.Form()):
        assert (services.blockers(form, ingest) == []) == all(c.done for c in services.checklist(form, ingest))
    assert [c.key for c in services.checklist(services.Form(), None)] == [
        "name", "file", "tiers", "site", "offset", "orient", "hardware"
    ]
