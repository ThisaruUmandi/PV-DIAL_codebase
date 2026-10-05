"""Home and Past analyses: open (read-only), continue, duplicate, refresh, search, filter and order.
pvdials_test only (tests/conftest.py forces it). The thesis pipelines run once, in a module fixture."""

import copy
import csv
import html
import io
import json
import re
import uuid

import pytest
import yaml
from streamlit.testing.v1 import AppTest

from app import analysis_logic as al
from app import config_logic, past_logic, run_logic, services, session_load, wording
from app import report_logic as rl
from pvdials.analysis import run_analysis
from pvdials.config import ROOT, load_defaults
from pvdials.dla.metrics import resolve_tau
from pvdials.provenance.analyses import linked_records, load_analysis, save_analysis
from pvdials.provenance.db import get_connection, is_reachable
from tests.interface.test_app_page1 import _complete_form
from tests.interface.test_app_page3 import THESIS_FILE, _clean, _inputs
from tests.interface.test_app_page4 import _session

pytestmark = [
    pytest.mark.skipif(not THESIS_FILE.exists(), reason="thesis weather file not present"),
    pytest.mark.skipif(not is_reachable(), reason="no Postgres reachable"),
]

MAIN = str(ROOT / "app" / "main.py")
HEX = re.compile(r"\b[0-9a-f]{20,}\b")
COLOMBO = json.loads((ROOT / "tests" / "fixtures" / "colombo_thesis_run_row.json").read_text())
THESIS_AC = {"A": 9837.3, "B": 9723.5, "C": 9667.2}
THESIS_DC = {"A": 10254.0, "B": 10134.6, "C": 10075.4}
THESIS_NRMSD = {
    "A-B": (0.1235, 0.0036, 0.1534, 0.0173, 0.0172),
    "A-C": (0.1396, 0.0065, 0.1946, 0.0225, 0.0223),
}
THESIS_PHI = {"A-B": ([17.52, 6.10, 50.23, 0.02, 0.0], 73.88), "A-C": ([21.51, 7.80, 66.12, 0.0, 0.0], 95.44)}
IDS: dict[str, str] = {}


@pytest.fixture(autouse=True)
def _restore_streamlit_links():
    """The page harness replaces page_link and switch_page; put the real ones back after each test."""
    import streamlit as st
    from streamlit.delta_generator import DeltaGenerator

    saved = (st.page_link, st.switch_page, DeltaGenerator.page_link)
    yield
    st.page_link, st.switch_page, DeltaGenerator.page_link = saved


def _hex() -> str:
    return uuid.uuid4().hex


# --- the saved analyses these tests open ----------------------------------------------------------------------------------


def _stopped_at(step: int, name: str) -> str:
    """An analysis saved by the interface's own save functions, stopped at this step; τ is user-entered (0.01)."""
    ingest = services.ingest_upload(THESIS_FILE.read_bytes(), THESIS_FILE.name)
    form = _complete_form(ingest, name=name, offset_choice="hour_start", offset_reason="file content aligns with 0 h")
    done = services.commit_page1(form, ingest, _hex(), tau=resolve_tau(0.01, load_defaults()))
    analysis_id, inputs = done.analysis_id, done.inputs
    if step == 1:  # what page 1 had saved before it read the site
        save_analysis(analysis_id, name, "load_done", {k: v for k, v in inputs.items() if k != "location"})
        return analysis_id
    if step == 2:
        return analysis_id
    pools = config_logic.pools_for(
        inputs["hardware"]["module_name"], inputs["site"]["mounting_geometry"],
        inputs["site"]["mounting_construction"], inputs["hardware"]["inverter_name"],
    )
    saved = config_logic.commit_page2(
        analysis_id, inputs, pools, _inputs()["pipelines"], {"value": 0.01, "source": "user_entered"}
    )
    if step == 4:
        run_logic.run_pipelines(saved, analysis_id)
    return analysis_id


@pytest.fixture(scope="module")
def world():
    """pvdials_test with: the thesis analysis saved by the command line, an old-shape row, and analyses saved by
    the interface that stopped at step 1, 2, 3 and 4 (the last with and without Phase 1)."""
    _clean()
    yaml_path = ROOT / "tests" / "_s9_thesis.yaml"
    config = yaml.safe_load((ROOT / "analysis.yaml").read_text(encoding="utf-8"))
    config["name"] = "Zulu thesis by the command line"
    yaml_path.write_text(yaml.dump(config), encoding="utf-8")
    try:
        IDS["cli"] = run_analysis(str(yaml_path), analysis_id=_hex()).analysis_id
    finally:
        yaml_path.unlink(missing_ok=True)

    IDS["old"] = _hex()
    save_analysis(
        IDS["old"], "Old shape colombo", COLOMBO["status"], COLOMBO["inputs"], COLOMBO["phase1"], COLOMBO["phase2"],
        COLOMBO["phase3"], COLOMBO["reexec"], COLOMBO["pipelines"],
    )
    IDS["s1"] = _stopped_at(1, "Mike stopped at one")
    IDS["s2"] = _stopped_at(2, "Lima stopped at two")
    IDS["s3"] = _stopped_at(3, "Kilo stopped at three")
    IDS["s4"] = _stopped_at(4, "Juliet stopped at four")
    IDS["s4p1"] = _stopped_at(4, "India stopped at four after phase one")
    row = load_analysis(IDS["s4p1"])
    ss = _session(run_logic.reopen(IDS["s4p1"], row["inputs"]), row["inputs"], IDS["s4p1"])
    ss["run"].live = None
    al.run_phase1(ss)
    return IDS


def _counts() -> dict:
    with get_connection() as conn, conn.cursor() as cur:
        out = {}
        for table in ("analyses", "analysis_records", "provenance_records", "stage_output_values"):
            cur.execute(f"SELECT count(*) FROM {table}")
            out[table] = cur.fetchone()[0]
        cur.execute("SELECT id, status, updated_at FROM analyses ORDER BY id")
        out["rows"] = cur.fetchall()
    return out


def _record_ids(analysis_id: str) -> list[str]:
    return sorted(r["record_id"] for r in linked_records(analysis_id))


# --- the pages, in one session -----------------------------------------------------------------------------------------------


def _app():
    import streamlit as st

    from app import components, state
    from app.page_map import step_page
    from app.screens import home, past

    ss = st.session_state
    state.init_state(ss)
    for key in ("home", "past", "1", "2", "3", "4", "5", "6"):
        components.PAGES[key] = key
    from streamlit.delta_generator import DeltaGenerator

    link = lambda target, label=None, **kw: st.markdown(f"[{label}]({target})")
    st.page_link = link
    DeltaGenerator.page_link = lambda self, target, label=None, **kw: self.markdown(f"[{label}]({target})")
    st.switch_page = lambda target: ss.__setitem__("_page", target)
    components.flash()
    components.render_pending_change()
    pages = {"home": home.render, "past": past.render, **{str(n): step_page(n) for n in range(1, 7)}}
    pages[ss.get("_page", "past")]()


def _at(page: str = "past", **state) -> AppTest:
    at = AppTest.from_function(_app, default_timeout=240)
    at.session_state["_page"] = page
    for key, value in state.items():
        at.session_state[key] = value
    return at.run()


def _walk(block):
    from streamlit.testing.v1.element_tree import Block

    out = []
    for child in block.children.values():
        out += _walk(child) if isinstance(child, Block) else [child]
    return out


def _html(at) -> str:
    return " ".join(el.value for el in _walk(at.main) if el.type == "html")


def _plain(markup: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup)))


def _text(at) -> str:
    return _plain(_html(at))


def _names(at) -> list[str]:
    return re.findall(r'<div class="pv-row-name">(.*?)</div>', _html(at))


def _row_names(rows) -> list[str]:
    return [html.escape(r.name) for r in rows]


def _position(rows, analysis_id: str) -> int:
    return next(i for i, row in enumerate(rows) if row.id == analysis_id)


def _open_from_past(world, key: str, action: str) -> AppTest:
    at = _at()
    rows = past_logic.past_rows()
    at.button(key=f"past_{action}_{_position(rows, world[key])}").click().run()
    return at


# --- Open: the Report, read-only -----------------------------------------------------------------------------------------------


def test_an_analysis_saved_by_the_command_line_opens_on_the_report_with_the_thesis_values(world):
    at = _open_from_past(world, "cli", "open")
    assert not at.exception
    assert at.session_state["_page"] == "6" and at.session_state["analysis_id"] == world["cli"]
    assert at.session_state["readonly"] is True
    at.run()
    assert not at.exception
    markup = _html(at)
    text = _plain(markup)
    assert wording.RP_READONLY in text
    for label, value in THESIS_AC.items():
        assert f"{value:,.1f} kWh" in text, label  # annual AC, as the thesis gives it
    lines = re.findall(r'<span class="pv-mono">(A – B · Outcome \d|A – C · Outcome \d|B – C · Outcome \d)</span>', markup)
    assert lines == ["A – B · Outcome 3", "A – C · Outcome 3", "B – C · Outcome 1"]
    assert text.count("k = Decomposition") == 2 and "k = none" in text
    report = rl.build_report(world["cli"])
    for key, expected in THESIS_NRMSD.items():
        assert [m["nrmsd"] for m in report.row["phase1"][key]["metrics"]] == pytest.approx(expected, abs=5e-5)
        for value in expected:
            assert f"{value:.4f}" in text
    for key, (phi, total) in THESIS_PHI.items():
        entry = report.row["phase3"][key]
        assert [round(i["value"], 2) for i in entry["phi_final"]] == phi
        assert round(sum(i["value"] for i in entry["phi_final"]), 2) == total
    assert "add up to 73.88 W; RMSD(A,B) is 73.88 W." in text
    from app import report_export as ex

    table = list(csv.DictReader(io.StringIO(ex.downloads_for(world["cli"], ex.saved_iso(world["cli"])).csv.decode())))
    ac = {r["pipeline"]: float(r["value"]) for r in table if r["section"] == "annual" and r["stage"] == "ac" and r["quantity"] == "annual_energy"}
    dc = {r["pipeline"]: float(r["value"]) for r in table if r["section"] == "annual" and r["stage"] == "dc" and r["quantity"] == "annual_energy"}
    for label in "ABC":
        assert round(ac[label], 1) == THESIS_AC[label] and round(dc[label], 1) == THESIS_DC[label]


def test_open_writes_nothing_and_offers_no_run_or_edit_control(world):
    before = _counts()
    at = _open_from_past(world, "cli", "open")
    at.run()  # the Report
    assert [b.key for b in at.button] == ["w6_new"]
    assert [b.label for b in at.get("download_button")] == [wording.RP_DL_HTML, wording.RP_DL_CSV, wording.RP_DL_PROV]
    for step in range(1, 6):  # every step page shows one plain panel and nothing to press, type or choose
        at.session_state["_page"] = str(step)
        at.run()
        assert not at.exception
        text = _text(at)
        assert wording.RO_PANEL_TITLE in text and "Nothing on this step can be run or changed" in text
        assert not at.button and not at.text_input and not at.number_input and not at.selectbox
        assert not at.get("file_uploader") and not at.checkbox and not at.radio
    assert wording.RO_PANEL_REEXEC.split(". ")[-1] in _text(_page_five(at))  # step 5 names Duplicate
    assert "choose Duplicate on Past analyses" in _text(_page_five(at))
    assert _counts() == before


def _page_five(at) -> AppTest:
    at.session_state["_page"] = "5"
    return at.run()


def test_a_step_page_of_an_opened_analysis_does_not_say_duplicate_except_step_5(world):
    at = _open_from_past(world, "cli", "open")
    for step in (1, 2, 3, 4):
        at.session_state["_page"] = str(step)
        at.run()
        assert "Duplicate" not in _text(at)


def test_the_downloads_of_an_opened_analysis_still_work(world):
    at = _open_from_past(world, "cli", "open")
    at.run()
    from app import report_export as ex

    files = ex.downloads_for(world["cli"], ex.saved_iso(world["cli"]))
    assert files.html.startswith(b"<!doctype html") or files.html.lstrip().lower().startswith(b"<!doctype html")
    assert files.csv and json.loads(files.prov)


def test_an_old_shape_row_opens_and_says_not_recorded_for_the_parts_it_lacks(world):
    at = _open_from_past(world, "old", "open")
    at.run()
    assert not at.exception
    text = _text(at)
    assert at.session_state["readonly"] is True
    assert wording.RP_READONLY in text and "not recorded for this analysis" in text
    assert "A – B · Outcome 3" in text  # what the row does hold still reads normally
    assert at.session_state["analysis_id"] == world["old"]


# --- Continue: the same analysis, at the step it reached ---------------------------------------------------------------


@pytest.mark.parametrize(("key", "step"), [("s1", 1), ("s2", 2), ("s3", 3), ("s4", 4), ("s4p1", 4)])
def test_continue_lands_on_the_step_reached_and_keeps_the_analysis_and_its_records(world, key, step):
    before, records_before = _counts(), _record_ids(world[key])
    row_before = load_analysis(world[key])
    at = _open_from_past(world, key, "continue")
    assert not at.exception
    ss = at.session_state
    assert ss["_page"] == str(step) and ss["analysis_id"] == world[key] and ss["readonly"] is False
    assert (ss["data_valid"], ss["config_valid"], ss["run_done"]) == (step >= 2, step >= 3, step >= 4)
    assert ss["phase1_done"] is (key == "s4p1")
    assert ss["name"] == row_before["name"] and ss["inputs"] == row_before["inputs"]
    if step >= 4:
        assert ss["run"].live is None  # the live pipelines are rebuilt only when a button needs them
        assert ss["run"].analysis_id == world[key]
    assert _counts() == before  # loading writes nothing
    assert _record_ids(world[key]) == records_before
    assert load_analysis(world[key]) == row_before


def test_the_page_after_continue_shows_the_stored_inputs_and_the_stored_choices(world):
    at = _open_from_past(world, "s3", "continue")
    ss = at.session_state
    assert ss["w1_prev"]["w1_name"] == "Kilo stopped at three" and ss["w1_prev"]["w1_tilt"] == 6.944
    assert ss["w1_prev"]["w1_offset_choice"] == "hour_start" and ss["w1_prev"]["w1_latitude"] == 6.944
    assert ss["w1_prev"]["w1_module"] == "Canadian_Solar_Inc__CS6K_300MS"
    assert ss["w2_prev"]["w2_tau"] == 0.01 and ss["tau"] == {"value": 0.01, "source": "user_entered"}
    assert ss["w2_prev"]["w2_A_decomposition"] == "erbs" and ss["w2_prev"]["w2_C_transposition"] == "perez"
    at.session_state["_page"] = "3"
    at.run()
    assert not at.exception and wording.R_EMPTY_TITLE in _text(at)  # page 3: ready to run, the saved pipelines held
    at.session_state["_page"] = "2"
    at.run()
    assert not at.exception
    assert at.session_state["w2_tau"] == 0.01 and at.session_state["w2_B_decomposition"] == "disc"
    at.session_state["_page"] = "1"
    at.run()
    assert not at.exception
    assert at.session_state["w1_name"] == "Kilo stopped at three" and at.session_state["w1_azimuth"] == 180.0
    assert at.session_state["w1_albedo"] == 0.2 and at.session_state["w1_module_height_m"] == 3.0


def test_continuing_at_step_4_and_pressing_phase_1_rebuilds_without_adding_a_row_or_a_record(world):
    key = "s4"
    at = _open_from_past(world, key, "continue")
    records_before, counts_before = _record_ids(world[key]), _counts()
    at.session_state["_page"] = "4"
    at.run()
    assert at.button(key="w4_p1")
    at.button(key="w4_p1").click().run()
    assert not at.exception
    assert at.session_state["phase1_done"] is True and at.session_state["analysis_id"] == world[key]
    after = _counts()
    assert after["analyses"] == counts_before["analyses"]
    assert after["provenance_records"] == counts_before["provenance_records"]  # the same record ids, no new rows
    assert _record_ids(world[key]) == records_before
    row = load_analysis(world[key])
    assert row["phase1"] is not None and row["status"] == "phase1_done" and row["inputs"]["name"] == "Juliet stopped at four"
    assert row["pipelines"] is not None and row["run_info"] is not None  # what was stored before stays


def test_continuing_at_step_3_and_running_saves_into_the_same_analysis(world):
    at = _open_from_past(world, "s3", "continue")
    counts_before = _counts()
    at.session_state["_page"] = "3"
    at.run()
    at.button(key="w3_run").click().run()
    assert not at.exception
    assert at.session_state["analysis_id"] == world["s3"] and at.session_state["run_done"] is True
    row = load_analysis(world["s3"])
    assert row["status"] == "pipelines_done" and row["name"] == "Kilo stopped at three" and row["run_info"] is not None
    assert row["inputs"]["tau"] == {"value": 0.01, "source": "user_entered"}
    assert _counts()["analyses"] == counts_before["analyses"]  # the row was filled in, not added to
    assert sorted(r["record_id"] for r in linked_records(world["s3"])) == sorted(at.session_state["run"].record_ids)
    assert len(set(at.session_state["run"].record_ids)) == len(at.session_state["run"].record_ids)
    # the row is now one that stopped at step 4
    assert past_logic.progress(row["status"], [k for k in ("pipelines", "run_info") if row[k]], None, None, None).step == 4


def test_run_analysis_is_never_called_by_continue_or_open(world, monkeypatch):
    from pvdials import analysis

    def refuse(*args, **kwargs):
        raise AssertionError("run_analysis must not be called")

    monkeypatch.setattr(analysis, "run_analysis", refuse)
    for key, action in (("s4", "continue"), ("s2", "continue"), ("cli", "open")):
        at = _open_from_past(world, key, action)
        assert not at.exception


def test_continue_at_step_1_shows_the_stored_file_and_does_not_replace_the_form_with_the_files_own_values(world):
    at = _open_from_past(world, "s1", "continue")
    at.session_state["_page"] = "1"
    at.run()
    assert not at.exception
    text = _text(at)
    assert THESIS_FILE.name in text and at.session_state["w1_name"] == "Mike stopped at one"
    assert at.session_state["w1_offset_choice"] == "hour_start"  # the stored choice, not the file's own


# --- a weather file that is no longer stored ----------------------------------------------------------------------------------


def test_a_missing_upload_file_says_which_file_to_upload_again_and_the_right_file_resumes(world, tmp_path):
    stored = tmp_path / "gone.csv"
    stored.write_bytes(THESIS_FILE.read_bytes())
    row = load_analysis(world["s2"])
    inputs = copy.deepcopy(row["inputs"])
    inputs["weather_file"] = str(stored)
    inputs["weather"]["stored_path"] = str(stored)
    new_id = _hex()
    save_analysis(new_id, "Hotel missing file", "site_done", inputs)
    stored.unlink()

    at = _at()
    rows = past_logic.past_rows()
    at.button(key=f"past_continue_{_position(rows, new_id)}").click().run()
    assert not at.exception
    ss = at.session_state
    message = wording.PAST_FILE_MISSING.format(name=THESIS_FILE.name)
    assert ss["_page"] == "1" and ss["upload_problem"] == message and ss["analysis_id"] == new_id
    assert ss["awaiting_file"]["sha256"] == inputs["weather"]["sha256"]
    assert not ss["data_valid"] and ss["weather"] is None
    at.run()
    assert message in _text(at)

    wrong = services.ingest_upload(b"time,GHI\n1,2\n", "other.csv")
    assert session_load.resume_after_upload(ss, wrong) == wording.PAST_FILE_WRONG.format(name=THESIS_FILE.name)
    right = services.ingest_upload(THESIS_FILE.read_bytes(), THESIS_FILE.name)
    assert session_load.resume_after_upload(ss, right) is None
    stored.write_bytes(THESIS_FILE.read_bytes())  # the same file is back where the analysis expects it
    resumed: dict = {}
    landing = session_load.restore(resumed, new_id)
    assert landing.page == "2" and resumed["data_valid"] is True and resumed["analysis_id"] == new_id
    assert resumed["weather"]["name"] == THESIS_FILE.name and "awaiting_file" not in resumed


def test_the_file_uploaded_again_lets_the_analysis_carry_on_from_where_it_stopped_even_from_a_new_path(world, tmp_path):
    row = load_analysis(world["s2"])
    inputs = copy.deepcopy(row["inputs"])
    inputs["weather_file"] = str(tmp_path / "moved_away.csv")  # where it was saved is gone for good
    new_id = _hex()
    save_analysis(new_id, "Golf file moved", "site_done", inputs)
    at = _at()
    rows = past_logic.past_rows()
    at.button(key=f"past_continue_{_position(rows, new_id)}").click().run()
    assert at.session_state["_page"] == "1" and at.session_state["awaiting_file"]["analysis_id"] == new_id
    again = services.ingest_upload(THESIS_FILE.read_bytes(), THESIS_FILE.name, root=tmp_path / "uploads")
    assert session_load.resume_after_upload(at.session_state, again) is None
    at.session_state["_resume"] = {"id": new_id, "file": again.stored_path}
    at.session_state["_page"] = "1"
    at.run()  # page 1 loads the analysis again with the file that is there now
    assert not at.exception
    ss = at.session_state
    assert ss["_page"] == "2" and ss["analysis_id"] == new_id and ss["data_valid"] is True
    assert ss["inputs"]["weather_file"] == again.stored_path and "awaiting_file" not in ss
    assert load_analysis(new_id)["inputs"]["weather_file"] == str(tmp_path / "moved_away.csv")  # nothing was written
    at.run()
    assert wording.PAST_RESUMED in _text(at)


# --- Duplicate -----------------------------------------------------------------------------------------------------------------


def test_duplicate_makes_a_new_analysis_with_the_same_inputs_and_no_results_and_opens_it_on_step_1(world):
    source = load_analysis(world["s4p1"])
    counts_before = _counts()
    at = _open_from_past(world, "s4p1", "duplicate")
    assert not at.exception
    ss = at.session_state
    new_id = ss["analysis_id"]
    assert new_id != world["s4p1"] and ss["_page"] == "1" and ss["readonly"] is False
    copy_row = load_analysis(new_id)
    assert copy_row["name"] == copy_row["inputs"]["name"] == "India stopped at four after phase one (copy)"
    assert {k: v for k, v in copy_row["inputs"].items() if k != "name"} == {k: v for k, v in source["inputs"].items() if k != "name"}
    assert copy_row["inputs"]["tau"] == {"value": 0.01, "source": "user_entered"}  # the τ and its source are kept
    assert copy_row["status"] == "started"
    for part in ("phase1", "phase2", "phase3", "reexec", "pipelines", "run_info"):
        assert copy_row[part] is None
    assert _record_ids(new_id) == []
    after = _counts()
    assert after["analyses"] == counts_before["analyses"] + 1
    assert after["provenance_records"] == counts_before["provenance_records"]
    unchanged = load_analysis(world["s4p1"])
    assert unchanged == source  # the saved original is never edited
    assert ss["w1_prev"]["w1_name"] == copy_row["name"] and ss["w1_prev"]["w1_tilt"] == 6.944
    assert not ss["data_valid"] and ss["phase1"] is None and ss["run"] is None
    at.run()  # step 1 opens with the saved inputs in its form and says what was made
    assert not at.exception and wording.PAST_DUPLICATED.format(name=copy_row["name"]) in _text(at)
    assert at.session_state["w1_name"] == copy_row["name"] and THESIS_FILE.name in _text(at)


def test_a_second_copy_of_the_same_analysis_is_named_copy_2(world):
    first = _open_from_past(world, "s4", "duplicate").session_state["analysis_id"]
    second = _open_from_past(world, "s4", "duplicate").session_state["analysis_id"]
    assert first != second
    assert load_analysis(second)["name"] == "Juliet stopped at four (copy 2)"
    third = _open_from_past(world, "s4", "duplicate").session_state["analysis_id"]
    assert load_analysis(third)["name"] == "Juliet stopped at four (copy 3)"


def test_duplicating_an_old_shape_row_keeps_what_it_has_and_leaves_the_rest_empty(world):
    at = _open_from_past(world, "old", "duplicate")
    assert not at.exception
    ss = at.session_state
    copy_row = load_analysis(ss["analysis_id"])
    assert "tau" not in copy_row["inputs"] and copy_row["inputs"]["site"]["tilt_deg"] == 6.944
    assert ss["_page"] == "1" and ss["w1_prev"]["w1_tilt"] == 6.944
    assert ss["w1_prev"]["w1_offset_choice"] == "hour_start"  # read back from the saved 0 h


# --- Refresh: the URL keeps the analysis and the mode -------------------------------------------------------------------------


def _app_at(**params) -> AppTest:
    at = AppTest.from_file(MAIN, default_timeout=240)
    for key, value in params.items():
        at.query_params[key] = value
    return at.run()


def test_a_refresh_with_the_analysis_in_the_address_keeps_the_analysis_and_its_step(world):
    for key, step in (("s1", 1), ("s2", 2), ("s4p1", 4)):
        counts = _counts()
        at = _app_at(a=world[key])
        assert not at.exception
        ss = at.session_state
        assert ss["analysis_id"] == world[key] and ss["readonly"] is False
        assert (ss["data_valid"], ss["config_valid"], ss["run_done"]) == (step >= 2, step >= 3, step >= 4)
        assert ss["phase1_done"] is (key == "s4p1")
        assert dict(at.query_params) == {"a": [world[key]]}  # still in the address
        assert _counts() == counts


def test_the_address_carries_the_analysis_when_one_is_opened_and_none_when_there_is_none(world):
    at = AppTest.from_file(MAIN, default_timeout=240).run()
    assert dict(at.query_params) == {}
    first = next(b for b in at.button if b.key.startswith("recent_"))
    first.click().run()
    assert not at.exception
    assert dict(at.query_params)["a"] == [at.session_state["analysis_id"]]


def test_a_refresh_of_an_opened_analysis_stays_read_only(world):
    at = _app_at(a=world["cli"], ro="1")
    assert not at.exception
    ss = at.session_state
    assert ss["analysis_id"] == world["cli"] and ss["readonly"] is True
    assert dict(at.query_params) == {"a": [world["cli"]], "ro": ["1"]}


def test_an_unknown_or_malformed_id_gives_home_with_one_plain_message_and_no_crash(world):
    for bad in ("0123456789abcdef0123456789abcdef", "nonsense", "../../etc/passwd", "0123456789ABCDEF0123456789abcdef", ""):
        at = _app_at(a=bad)
        assert not at.exception, bad
        assert at.session_state["analysis_id"] is None
        assert [t.value for t in at.title] == [wording.HOME_HEADLINE]
        assert wording.PAST_NOT_FOUND in _page_text_of(at)
        assert dict(at.query_params) == {}  # the bad id is not kept in the address
        assert not at.error


def test_a_refresh_of_a_read_only_row_that_has_no_phase_1_gives_home_and_a_plain_message(world):
    at = _app_at(a=world["s2"], ro="1")
    assert not at.exception and [t.value for t in at.title] == [wording.HOME_HEADLINE]
    assert "saved without a Phase 1" in _page_text_of(at)


def test_a_plain_address_starts_empty(world):
    at = _app_at()
    assert at.session_state["analysis_id"] is None and not at.session_state["data_valid"]


def _page_text_of(at) -> str:
    joined = " ".join(el.value for el in at.get("html"))
    return _plain(joined)


# --- the list: search, status, order ------------------------------------------------------------------------------------------


def _set(at, key, value):
    widget = at.text_input(key=key) if key == "w7_search" else at.selectbox(key=key)
    widget.set_value(value)
    return at.run()


def _expected(search=None, status="all", order="newest"):
    return past_logic.past_rows(search, status, order)


def test_the_list_shows_every_saved_analysis_newest_first_by_default(world):
    at = _at()
    assert not at.exception
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT name FROM analyses ORDER BY created_at DESC, id")
        expected = [html.escape(r[0]) for r in cur.fetchall()]
    assert _names(at) == expected
    text = _text(at)
    for header in wording.PAST_HEADERS:
        assert header in text


def test_search_matches_the_name_or_the_weather_file_without_regard_to_case(world):
    at = _at()
    at = _set(at, "w7_search", "STOPPED AT")
    shown = _names(at)
    assert shown == _row_names(_expected("STOPPED AT")) and len(shown) >= 6
    assert all("stopped at" in name.lower() for name in shown)
    at = _set(at, "w7_search", "tmy_6.944")  # the file name
    assert len(_names(at)) == len(_expected("tmy_6.944")) >= 7  # the name the file had when it was uploaded
    at = _set(at, "w7_search", "colombo")
    assert _names(at) == _row_names(_expected("colombo"))
    assert "Old shape colombo" in _names(at) and all("colombo" in n.lower() for n in _names(at))


def test_no_match_says_so_in_one_plain_line_and_an_empty_store_says_how_to_start(world):
    at = _set(_at(), "w7_search", "zzz nothing like this")
    assert wording.PAST_NO_MATCH in _text(at) and not _names(at)
    assert wording.EMPTY_PAST not in _text(at)


def test_the_status_filter_is_all_complete_or_stopped_by_what_is_stored(world):
    at = _at()
    group = at.get("button_group")[0]
    assert [o.content for o in group.proto.options] == ["All", "Complete", "Stopped"]
    complete = {r.id for r in _expected(status="complete")}
    stopped = {r.id for r in _expected(status="stopped")}
    assert world["cli"] in complete and world["old"] in complete
    assert {world["s1"], world["s2"], world["s3"], world["s4"], world["s4p1"]} <= stopped
    assert not complete & stopped
    all_ids = {r.id for r in _expected()}
    assert complete | stopped == all_ids
    at.session_state["w7_status"] = "complete"
    at.run()
    assert _names(at) == _row_names(_expected(status="complete"))
    at.session_state["w7_status"] = "stopped"
    at.run()
    assert _names(at) == _row_names(_expected(status="stopped"))
    assert all("Stopped at step" in _text(at) for _ in [0]) and "Complete" not in " ".join(_names(at))


def test_each_order_gives_the_expected_rows_and_none_is_by_disagreement(world):
    at = _at()
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT name FROM analyses ORDER BY created_at ASC, id")
        oldest = [html.escape(r[0]) for r in cur.fetchall()]
        cur.execute("SELECT name FROM analyses ORDER BY lower(name) ASC, created_at DESC")
        by_name = [html.escape(r[0]) for r in cur.fetchall()]
    assert at.selectbox(key="w7_order").options == ["Newest first", "Oldest first", "Name A–Z"]
    at = _set(at, "w7_order", "oldest")
    assert _names(at) == oldest
    at = _set(at, "w7_order", "name")
    assert _names(at) == by_name
    assert [n.lower() for n in by_name] == sorted(n.lower() for n in by_name)
    at = _set(at, "w7_order", "newest")
    assert _names(at) == list(reversed(oldest))
    assert wording.PAST_ORDER_NOTE in _text(at)


def test_a_search_and_an_order_are_still_there_after_visiting_another_page(world):
    at = _set(_at(), "w7_search", "kilo")
    at.session_state["_page"] = "home"
    at.run()
    at.session_state["_page"] = "past"
    at.run()
    assert at.text_input(key="w7_search").value == "kilo" and _names(at) == ["Kilo stopped at three"]


# --- every row's button acts on the analysis that row showed -----------------------------------------------------------------


def test_each_button_acts_on_the_row_it_was_drawn_in_under_a_search_filter(world):
    rows = _expected("stopped at")
    assert len(rows) >= 6
    for position in (0, 2, len(rows) - 1):
        action = "continue" if "continue" in rows[position].actions else "duplicate"
        fresh = _set(_at(), "w7_search", "stopped at")
        fresh.button(key=f"past_{action}_{position}").click().run()
        assert not fresh.exception
        acted = fresh.session_state["analysis_id"]
        if action == "continue":
            assert acted == rows[position].id
        else:
            assert load_analysis(acted)["name"].startswith(rows[position].name)


def test_each_button_acts_on_the_row_it_was_drawn_in_even_after_a_new_analysis_is_saved(world):
    at = _at()
    drawn = past_logic.past_rows()
    target = _position(drawn, world["s3"])
    # another session saves a newer analysis, so every position in a fresh list moves down one
    newcomer = _hex()
    save_analysis(newcomer, "Newcomer saved meanwhile", "load_done", {"name": "Newcomer saved meanwhile"})
    assert past_logic.past_rows()[0].id == newcomer
    assert past_logic.past_rows()[target].id != world["s3"]
    at.button(key=f"past_continue_{target}").click().run()
    assert at.session_state["analysis_id"] == world["s3"]  # the drawn row, not the one now at that position
    # and the same for Duplicate
    at = _at()
    drawn = past_logic.past_rows()
    target = _position(drawn, world["s2"])
    save_analysis(_hex(), "Another newcomer", "load_done", {"name": "Another newcomer"})
    at.button(key=f"past_duplicate_{target}").click().run()
    assert load_analysis(at.session_state["analysis_id"])["name"].startswith("Lima stopped at two (copy")


def test_no_button_is_keyed_by_an_analysis_id(world):
    at = _at()
    keys = [b.key for b in at.button]
    assert keys and all(re.fullmatch(r"(past_(open|continue|duplicate)_\d+|past_start|past_new)", k) for k in keys), keys
    assert not any(HEX.search(k) for k in keys)


# --- Home -----------------------------------------------------------------------------------------------------------------------


def test_home_lists_the_three_most_recent_with_the_one_action_each_allows(world):
    at = _at("home")
    assert not at.exception
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, name FROM analyses ORDER BY created_at DESC, id LIMIT 3")
        newest = cur.fetchall()
    assert _names(at) == [html.escape(name) for _id, name in newest]
    rows = past_logic.recent_rows()
    assert [r.id for r in rows] == [i for i, _n in newest]
    keys = [b.key for b in at.button if b.key.startswith("recent_")]
    assert len(keys) == 3 and not any("duplicate" in k for k in keys)
    labels = {b.key: b.label for b in at.button if b.key.startswith("recent_")}
    for index, row in enumerate(rows):
        assert labels[f"recent_{row.main_action}_{index}"] == row.main_action.capitalize()


def test_home_has_the_agreed_texts_exactly(world):
    at = _at("home")
    text = _text(at)
    assert wording.HOME_NOT_SHOWN in text
    assert text.count("What it does not show:") == 1
    for bullet in wording.HOME_BEFORE_YOU_START:
        assert bullet in text
    assert wording.HOME_BEFORE_YOU_START == (
        "An hourly PVGIS TMY file (CSV) with GHI, T2m and WS10m. SP is optional",
        "Tilt, azimuth and albedo for the array",
        "A module and inverter from the CEC database, and the array layout (modules per string, strings per inverter)",
        "The module mounting height",
    )
    for needle in (wording.RECENT_ANALYSES, wording.SIX_STEPS, wording.STAGES_COMPARED, wording.HOME_CARD_SHOWS,
                   wording.HOME_CARD_BEFORE):
        assert needle in text
    assert at.button(key="home_start").label == wording.START_NEW_ANALYSIS
    markdown = " ".join(m.value for m in at.markdown)
    assert wording.VIEW_ALL_PAST in markdown
    for name in wording.STAGE_NAME_LIST:
        assert name in text
    assert "localised stage" in markdown and "flagged" not in markdown and "flagged" not in text


def test_home_and_past_show_no_hash_like_text_and_no_run_id(world):
    for page in ("home", "past"):
        at = _at(page)
        shown = _text(at) + " " + " ".join(m.value for m in at.markdown)
        assert not HEX.search(shown), page
        for key in world.values():
            assert key not in shown
        assert "run id" not in shown.lower() and "[" not in _text(at)


def test_the_pages_show_none_of_the_words_the_interface_never_uses(world):
    banned = re.compile(r"recommend|suggest|optimal|best|improv|correct|error|accura|compensat", re.IGNORECASE)
    for page in ("home", "past"):
        at = _at(page)
        assert not banned.search(_text(at)), (page, banned.search(_text(at)))


# --- Start new analysis asks first when one is open --------------------------------------------------------------------------


@pytest.mark.parametrize(("page", "key"), [("home", "home_start"), ("past", "past_start")])
def test_start_new_analysis_asks_first_when_an_analysis_is_open_and_starts_at_once_when_none_is(world, page, key):
    at = _at(page)  # nothing open: no question
    at.button(key=key).click().run()
    assert at.session_state["_page"] == "1" and wording.HOME_NEW_ASK not in _text(at)

    at = _at(page, analysis_id=world["s2"], name="Lima stopped at two")
    at.button(key=key).click().run()
    assert wording.HOME_NEW_ASK in _text(at) and "_page" in at.session_state and at.session_state["_page"] == page
    assert at.session_state["analysis_id"] == world["s2"]
    at.button(key=f"{key}_no").click().run()
    assert wording.HOME_NEW_ASK not in _text(at) and at.session_state["analysis_id"] == world["s2"]
    at.button(key=key).click().run()
    at.button(key=f"{key}_yes").click().run()
    assert at.session_state["analysis_id"] is None and at.session_state["_page"] == "1"
    assert load_analysis(world["s2"]) is not None  # the closed analysis stays saved


def test_starting_a_new_analysis_after_one_was_opened_read_only_leaves_the_mode_behind(world):
    at = _open_from_past(world, "cli", "open")
    at.session_state["_page"] = "past"
    at.run()
    at.button(key="past_start").click().run()
    at.button(key="past_start_yes").click().run()
    assert at.session_state["readonly"] is False and at.session_state["analysis_id"] is None
    assert at.session_state["phase1"] is None and at.session_state["config"] is None


# --- an empty store (keep this last: it empties the store the tests above read) -----------------------------------------


def test_home_with_no_saved_analysis_says_how_to_start_one():
    _clean()  # last in this file: it empties the store the other tests read
    at = _at("home")
    assert wording.EMPTY_PAST in _text(at) and not _names(at)
    at = _at("past")
    assert wording.EMPTY_PAST in _text(at) and wording.PAST_NO_MATCH not in _text(at)
