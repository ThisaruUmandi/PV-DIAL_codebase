"""Step 6 · Report and the three downloads, on a stored thesis analysis (phases 1 to 3 and a confirmed change).
pvdials_test only. The report is built from stored data alone: no pipeline is run and nothing is written."""

import copy
import csv
import hashlib
import html
import io
import json
import re
import shutil
import subprocess
from datetime import UTC
from pathlib import Path

import pytest
from prov.model import ProvDocument
from streamlit.testing.v1 import AppTest

from app import analysis_logic as al
from app import reexec_logic as rx
from app import report_export as ex
from app import report_html as rh
from app import report_logic as rl
from app import run_logic, wording
from pvdials.provenance.analyses import linked_records, load_analysis, save_analysis
from pvdials.provenance.db import get_connection, is_reachable
from tests.interface.test_app_page3 import THESIS_FILE, _clean, _inputs
from tests.interface.test_app_page4 import _session

pytestmark = [
    pytest.mark.skipif(not THESIS_FILE.exists(), reason="thesis weather file not present"),
    pytest.mark.skipif(not is_reachable(), reason="no Postgres reachable"),
]

ANALYSIS = "p6-thesis"
HEX = re.compile(r"\b[0-9a-f]{32,}\b")
THESIS_AC = {"A": 9837.3, "B": 9723.5, "C": 9667.2}
THESIS_DC = {"A": 10254.0, "B": 10134.6, "C": 10075.4}
THESIS_NRMSD = {
    "A-B": (0.1235, 0.0036, 0.1534, 0.0173, 0.0172),
    "A-C": (0.1396, 0.0065, 0.1946, 0.0225, 0.0223),
}
THESIS_PHI = {"A-B": ([17.52, 6.10, 50.23, 0.02, 0.0], 73.88), "A-C": ([21.51, 7.80, 66.12, 0.0, 0.0], 95.44)}
STAGES = al.STAGES


@pytest.fixture(scope="module")
def stored():
    """A thesis analysis, run and saved: Phases 1 to 3 and one confirmed change (A with 'disc' at Decomposition)."""
    _clean()
    inputs = _inputs()
    run = run_logic.run_pipelines(inputs, ANALYSIS)
    ss = _session(run, inputs, ANALYSIS)
    al.run_phase1(ss)
    al.run_phase2(ss)
    al.run_phase3(ss)
    attempt = rx.run_attempt(ss, ("A", "B"), "A", "disc")
    rx.confirm_attempt(ss, attempt, True)
    return run, inputs, ss


def _counts() -> dict:
    with get_connection() as conn, conn.cursor() as cur:
        out = {}
        for table in ("analyses", "analysis_records", "provenance_records", "stage_output_values"):
            cur.execute(f"SELECT count(*) FROM {table}")
            out[table] = cur.fetchone()[0]
        cur.execute("SELECT id, updated_at, status FROM analyses ORDER BY id")
        out["rows"] = cur.fetchall()
    return out


def _page6():
    import streamlit as st

    from app import components
    from app import state as app_state
    from app.screens import report_page

    app_state.init_state(st.session_state)
    for key in ("1", "past"):
        components.PAGES[key] = f"step-{key}"
    st.page_link = lambda target, label=None, **kw: st.markdown(f"[{label}]({target})")
    st.switch_page = lambda target: st.session_state.__setitem__("switched_to", target)
    report_page.render()


def _open(**extra) -> AppTest:
    at = AppTest.from_function(_page6, default_timeout=180)
    at.session_state["analysis_id"] = ANALYSIS
    at.session_state["phase1_done"] = True
    for key, value in extra.items():
        at.session_state[key] = value
    return at.run()


def _walk(block, skip=None):
    """Everything an element block holds, in order, descending into expanders (skip one by label)."""
    from streamlit.testing.v1.element_tree import Block

    out = []
    for child in block.children.values():
        if isinstance(child, Block):
            if skip and getattr(child, "label", None) == skip:
                continue
            out += _walk(child, skip)
        else:
            out.append(child)
    return out


def _page_html(at, skip=None) -> str:
    return " ".join(el.value for el in _walk(at.main, skip) if el.type == "html")


def _plain(markup: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup)))


def _tables(markup: str) -> list[str]:
    return [re.sub(r"\s+", " ", t) for t in re.findall(r"<table.*?</table>", markup, re.DOTALL)]


def _file(stored_ids=ANALYSIS) -> str:
    return ex.downloads_for(stored_ids, ex.saved_iso(stored_ids)).html.decode("utf-8")


# --- Gating, structure, states -----------------------------------------------------------------------------------------------


def test_the_report_is_locked_until_phase_1_has_run(stored):
    at = AppTest.from_function(_page6, default_timeout=60)
    at.session_state["analysis_id"] = ANALYSIS
    at.run()
    assert wording.LOCK_REASON[6] in _plain(_page_html(at)) and not at.get("download_button")
    assert not at.exception


def test_the_page_has_the_mock_ups_sections_in_order_with_three_downloads_and_the_footer(stored):
    at = _open()
    assert not at.exception
    text = _plain(_page_html(at))
    titles = ["Inputs", "Pipelines", "Phase 1 · Where", "Phase 2 · How it carries", "Phase 3 · How much",
              "Disagreement over the year", "Guided re-execution · confirmed change", "Provenance"]
    positions = [text.index(t) for t in titles]
    assert positions == sorted(positions)
    assert "Step 6 of 6" in _plain(_page_html(at)) or at.title[0].value == "Report"
    assert [b.label for b in at.get("download_button")] == [wording.RP_DL_HTML, wording.RP_DL_CSV, wording.RP_DL_PROV]
    assert "thesis" in text or "page three test" in text
    markdown = " ".join(m.value for m in at.markdown)
    assert wording.RP_BACK_PAST in markdown and wording.RP_NEW in [b.label for b in at.button]
    assert wording.RP_SAVED.format(time=rl.report_for(ANALYSIS, ex.saved_iso(ANALYSIS)).saved_text) in text


def test_the_download_buttons_carry_their_help_text(stored):
    at = _open()
    helps = {b.label: b.proto.help for b in at.get("download_button")}
    assert helps[wording.RP_DL_PROV] == "One JSON file holding one PROV-JSON document per record, each unchanged."
    assert "no internet" in helps[wording.RP_DL_HTML] and "signed" in helps[wording.RP_DL_CSV]


# --- The thesis values on the page --------------------------------------------------------------------------------------------


def test_the_report_shows_the_section_d_values(stored):
    at = _open()
    markup = _page_html(at)
    text = _plain(markup)
    for label, value in THESIS_AC.items():
        assert f"{value:,.1f} kWh" in text, label  # annual AC in the Pipelines table
    lines = re.findall(r'<span class="pv-mono">(A – B · Outcome \d|A – C · Outcome \d|B – C · Outcome \d)</span>', markup)
    assert lines == ["A – B · Outcome 3", "A – C · Outcome 3", "B – C · Outcome 1"]
    assert text.count("k = Decomposition") == 2 and "k = none" in text
    report = rl.report_for(ANALYSIS, ex.saved_iso(ANALYSIS))
    phase1 = report.row["phase1"]
    for key, expected in THESIS_NRMSD.items():
        assert [m["nrmsd"] for m in phase1[key]["metrics"]] == pytest.approx(expected, abs=5e-5)
        for value in expected:
            assert f"{value:.4f}" in text
    assert max(m["nrmsd"] for m in phase1["B-C"]["metrics"]) == pytest.approx(0.0706, abs=5e-5)
    for key, (phi, total) in THESIS_PHI.items():
        entry = report.row["phase3"][key]
        assert [round(i["value"], 2) for i in entry["phi_final"]] == phi
        assert round(sum(i["value"] for i in entry["phi_final"]), 2) == total == round(entry["rmsd_ab"], 2)
    assert "add up to 73.88 W; RMSD(A,B) is 73.88 W." in text and "add up to 95.44 W; RMSD(A,C) is 95.44 W." in text
    assert "Outcome 1 — nothing to attribute." in text  # B–C in Phase 3
    for stage_phi in ("17.52", "6.10", "50.23", "0.02"):
        assert stage_phi in text


def test_the_annual_dc_energies_are_in_the_results_csv(stored):
    rows = list(csv.DictReader(io.StringIO(ex.downloads_for(ANALYSIS, ex.saved_iso(ANALYSIS)).csv.decode())))
    dc = {r["pipeline"]: float(r["value"]) for r in rows if r["section"] == "annual" and r["stage"] == "dc" and r["quantity"] == "annual_energy"}
    ac = {r["pipeline"]: float(r["value"]) for r in rows if r["section"] == "annual" and r["stage"] == "ac" and r["quantity"] == "annual_energy"}
    for label in "ABC":
        assert round(dc[label], 1) == THESIS_DC[label] and round(ac[label], 1) == THESIS_AC[label]


def test_phase_3_shows_every_pair_in_order_with_same_model_and_no_signed_column(stored):
    at = _open()
    markup = _page_html(at)
    text = _plain(markup)
    section = text.split("Phase 3 · How much")[1].split("Disagreement over the year")[0]
    assert section.index("A – B") < section.index("A – C") < section.index("B – C")
    assert wording.SAME_MODEL in section and "signed" not in section.lower()
    assert 'class="pv-status' not in markup and "pv-icon-warn" not in markup  # page 4's neutral look
    assert 'class="pv-over"' in markup


def test_a_negative_phi_has_a_true_minus_and_a_downward_bar_in_the_report(stored):
    row = copy.deepcopy(load_analysis(ANALYSIS))
    entry = row["phase3"]["A-B"]
    values = [40.0, -3.2, 20.0, 0.5, 0.0]
    for key in ("phi_ab", "phi_ba", "phi_final"):
        for item, value in zip(entry[key], values, strict=True):
            item["value"] = value
    entry["rmsd_ab"] = sum(values)
    section = rl._phase3_section(row)
    table = next(b for b in section.blocks if isinstance(b, rl.Table)).html
    assert "−3.20" in table and "-3.20" not in table
    from app import analysis_charts as charts

    view = al.phase3_views(row["phase1"], row["phase3"])[0]
    frame = charts.waterfall_frame(view)
    assert frame.iloc[1]["end"] < frame.iloc[1]["start"] and frame.iloc[1]["text"] == "−3.20"


# --- The HTML file equals the page ------------------------------------------------------------------------------------------------


def test_every_table_in_the_file_is_the_same_as_the_page_table_in_the_same_order(stored):
    at = _open()
    page_tables = _tables(_page_html(at))
    file_tables = _tables(_without_libraries(_file()))
    assert page_tables == file_tables and len(page_tables) == 10
    for number in ("9,837.3", "0.1235", "17.52", "50.23", "73.88"):
        assert number in " ".join(file_tables) or number in _plain(_file())


def test_every_chart_of_the_page_is_in_the_file_with_the_same_data(stored):
    at = _open()
    report = rl.report_for(ANALYSIS, ex.saved_iso(ANALYSIS))
    charts = [b for s in report.sections for b in _flatten(s.blocks) if isinstance(b, rl.Chart)]
    file = _file()
    assert len(at.get("vega_lite_chart")) == len(charts) == file.count("data-chart=") == 11
    specs = re.findall(r'<script type="application/json" id="spec-\d+">(.*?)</script>', file, re.DOTALL)
    assert len(specs) == len(charts)
    for chart_block, raw in zip(charts, specs, strict=True):
        spec = json.loads(raw)
        expected = rh.spec_for_file(chart_block.chart)
        assert spec == expected  # the same chart, the same data
        assert spec["datasets"] == expected["datasets"]


def _flatten(blocks):
    for block in blocks:
        if isinstance(block, rl.Details):
            yield from _flatten(block.blocks)
        elif isinstance(block, rl.Columns):
            yield from _flatten(block.left)
            yield from _flatten(block.right)
        yield block


def test_the_disclaimer_is_exact_on_the_page_and_in_the_file(stored):
    at = _open()
    assert wording.DISCLAIMER in html.unescape(_page_html(at))
    assert wording.DISCLAIMER in html.unescape(_file())
    assert wording.RP_RX_NOTE in html.unescape(_file())


# --- Monthly energy, hour × month -----------------------------------------------------------------------------------------------


def test_monthly_ac_energy_sums_to_the_annual_ac_figure_per_pipeline(stored):
    report = rl.report_for(ANALYSIS, ex.saved_iso(ANALYSIS))
    series = {label: run_logic.load_stage_series(ANALYSIS, label) for label in "ABC"}
    energy = rl.monthly_energy(series)
    stored_ac = {
        label: next(e["annual_energy_kwh"] for e in report.row["pipelines"][label] if e["stage"] == "AC") for label in "ABC"
    }
    for label in "ABC":
        assert float(energy[label].sum()) == pytest.approx(stored_ac[label], rel=1e-9)
        assert round(float(energy[label].sum()), 1) == THESIS_AC[label]
    table = rl.monthly_table_html(energy)
    year_row = re.search(r"<b>Year</b></td>(.*?)</tr>", table).group(1)
    assert [float(v.replace(",", "")) for v in re.findall(r"<b>([\d,.]+)</b>", year_row)] == pytest.approx(
        [round(stored_ac[label], 1) for label in "ABC"], abs=0.051
    )


def test_each_pairs_hour_by_month_table_has_24_by_12_cells_computed_from_the_stored_series(stored):
    series = {label: run_logic.load_stage_series(ANALYSIS, label) for label in "ABC"}
    file = _file()
    details = re.findall(r"<details><summary>(Table: hour × month, [^<]+)</summary>(.*?)</details>", file, re.DOTALL)
    assert [d[0] for d in details] == [f"Table: hour × month, {p} (W)" for p in ("A – B", "A – C", "B – C")]
    for (title, body), pair in zip(details, (("A", "B"), ("A", "C"), ("B", "C")), strict=True):
        rows = re.findall(r"<tr><td class='pv-mono'>(\d\d)</td>(.*?)</tr>", body)
        assert len(rows) == 24 and all(len(re.findall(r"<td class='pv-num pv-mono'>", cells)) == 12 for _h, cells in rows)
        a, b = series[pair[0]]["ac"]["p_ac"], series[pair[1]]["ac"]["p_ac"]
        diff = (a - b).abs()
        expected = diff.groupby([diff.index.hour, diff.index.month]).mean()
        cells = {(int(h), m + 1): float(v) for h, c in rows for m, v in enumerate(re.findall(r"pv-mono'>([\d.]+)</td>", c))}
        for (hour, month), value in expected.items():
            assert cells[(hour, month)] == pytest.approx(value, abs=0.051)  # printed to one decimal
        assert title.endswith("(W)")


def test_the_year_maps_share_one_colour_scale_and_the_hour_axis_is_labelled_with_its_clock(stored):
    report = rl.report_for(ANALYSIS, ex.saved_iso(ANALYSIS))
    year = next(s for s in report.sections if s.key == "year")
    charts = [b.chart.to_dict() for b in year.blocks if isinstance(b, rl.Chart)]
    heat = [c for c in charts if c.get("encoding", {}).get("color", {}).get("field") == "difference"]
    assert len(heat) == 3
    domains = {tuple(c["encoding"]["color"]["scale"]["domain"]) for c in heat}
    assert len(domains) == 1 and next(iter(domains))[0] == 0
    assert all(c["encoding"]["y"]["title"] == "Hour of day (UTC, as in the file)" for c in heat)
    text = _plain(_page_html(_open()))
    assert "Hours are on the file's own clock (UTC)." in text


# --- The CSV --------------------------------------------------------------------------------------------------------------------------


def test_the_csv_has_the_planned_columns_and_the_stored_values(stored):
    data = ex.downloads_for(ANALYSIS, ex.saved_iso(ANALYSIS)).csv.decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(data)))
    assert list(rows[0]) == ["section", "pair", "pipeline", "stage", "quantity", "value", "unit", "text"]
    row = load_analysis(ANALYSIS)
    run = {r["quantity"]: r for r in rows if r["section"] == "run"}
    assert run["analysis_name"]["text"] == row["name"]
    assert run["saved_time"]["text"] == row["updated_at"].astimezone(UTC).isoformat()
    assert run["weather_file"]["text"] == THESIS_FILE.name
    assert (float(run["time_offset"]["value"]), run["time_offset"]["text"]) == (0.0, "user_entered")
    assert run["pvlib_version"]["text"] == row["run_info"]["pvlib_version"]
    assert (float(run["tau"]["value"]), run["tau"]["text"]) == (0.093, "default")
    found = {(r["pair"], r["stage"], r["quantity"]): r for r in rows if r["section"] == "phase1"}
    for key, entry in row["phase1"].items():
        for metric in entry["metrics"]:
            for quantity in ("rmsd", "nrmsd", "mad", "mbd", "systematic_share", "n_pooled"):
                cell = found[(key, metric["stage"].lower(), quantity)]
                assert float(cell["value"]) == metric[quantity] if metric[quantity] is not None else cell["value"] == ""
    assert found[("A-B", "decomposition", "rmsd")]["unit"] == "W/m²" and found[("A-B", "ac", "nrmsd")]["unit"] == "unitless"
    phase3 = {(r["pair"], r["stage"], r["quantity"]): float(r["value"]) for r in rows if r["section"] == "phase3" and r["stage"]}
    for key in ("A-B", "A-C"):
        for field in ("phi_ab", "phi_ba", "phi_final", "share", "signed_phi"):
            for item in row["phase3"][key][field]:
                assert phase3[(key, item["stage"].lower(), field)] == item["value"]
    assert any(r["section"] == "phase3" and r["pair"] == "B-C" and "outcome 1" in r["text"].lower() for r in rows)
    assert {r["quantity"] for r in rows if r["section"] == "phase2"} >= {"nrmsd", "mean_nrmsd", "max_nrmsd", "delta_mean_nrmsd"}
    reexec = {r["quantity"]: r for r in rows if r["section"] == "reexec"}
    assert reexec["candidate"]["text"] == "disc" and reexec["anchor"]["text"] == "A" and float(reexec["annual_yield"]["value"]) > 9000


# --- The PROV-JSON file ---------------------------------------------------------------------------------------------------------------


def test_the_provenance_file_holds_every_linked_record_unchanged_and_each_loads_with_prov(stored):
    payload = json.loads(ex.downloads_for(ANALYSIS, ex.saved_iso(ANALYSIS)).prov)
    assert payload["format"] == wording.RP_PROV_FORMAT and "unchanged" in payload["format"]
    linked = linked_records(ANALYSIS)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT record_id FROM analysis_records WHERE analysis_id = %s", (ANALYSIS,))
        in_db = {r[0] for r in cur.fetchall()}
    assert {r["record_id"] for r in payload["records"]} == in_db and len(payload["records"]) == len(in_db) == len(linked)
    assert [r["execution_set"] for r in payload["records"][:3]] == ["original"] * 3  # ORIGINAL first
    sets = {r["execution_set"] for r in payload["records"]}
    assert sets == {"original", "derived", "reexec"}
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, document FROM provenance_records")
        stored_docs = dict(cur.fetchall())
    for record in payload["records"]:
        assert record["document"] == stored_docs[record["record_id"]]  # as stored, unchanged
        assert re.fullmatch(r"[0-9a-f]{64}", record["record_id"])
        document = ProvDocument.deserialize(content=json.dumps(record["document"]))
        assert document.bundles and list(document.bundles)  # a real PROV document with its bundle
    assert payload["analysis"]["name"]


# --- No external URL; the file in a browser with no network ------------------------------------------------------------------------


def _without_libraries(file: str) -> str:
    out = file
    for name in ("vega.min.js", "vega-lite.min.js", "vega-embed.min.js"):
        out = out.replace((rh.VENDOR / name).read_text(encoding="utf-8"), "")
    return out


def test_the_file_loads_nothing_from_outside(stored):
    file = _without_libraries(_file())
    assert not re.search(r"<script[^>]*\ssrc\s*=", file, re.IGNORECASE) and "<link" not in file.lower()
    assert not re.search(r"<(img|iframe|video|audio|source|embed|object)\b", file, re.IGNORECASE)
    assert "@import" not in file and not re.search(r"url\(\s*['\"]?(https?:)?//", file, re.IGNORECASE)
    assert not re.search(r"\b(fetch|XMLHttpRequest|WebSocket|importScripts)\b", file)
    assert "fonts.googleapis" not in file and "cdn." not in file.lower()
    urls = set(re.findall(r"https?://[^\s\"'<>)]+", file))
    assert all(u.startswith("https://vega.github.io/schema/") for u in urls), urls  # only the spec's schema label
    assert 'rel="stylesheet"' not in file and "IBM Plex" not in file  # system font stacks only
    for name in ("vega.min.js", "vega-lite.min.js", "vega-embed.min.js"):
        assert (rh.VENDOR / name).read_text(encoding="utf-8") in _file()  # the libraries are inlined


def _chrome() -> str | None:
    for candidate in (
        shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chrome"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ):
        if candidate and Path(candidate).exists():
            return candidate
    return None


@pytest.mark.skipif(_chrome() is None, reason="no Chrome or Chromium to render the file")
def test_the_file_draws_every_chart_in_a_browser_with_the_network_blocked(stored, tmp_path):
    path = tmp_path / "report.html"
    path.write_bytes(ex.downloads_for(ANALYSIS, ex.saved_iso(ANALYSIS)).html)
    netlog = tmp_path / "net.json"
    result = subprocess.run(
        [_chrome(), "--headless=new", "--disable-gpu", "--no-sandbox", '--host-resolver-rules=MAP * ~NOTFOUND',
         "--virtual-time-budget=20000", f"--log-net-log={netlog}", "--dump-dom", f"file://{path}"],
        capture_output=True, text=True, timeout=120, check=False,
    )
    dom = result.stdout
    assert 'data-charts-ready="yes"' in dom
    assert dom.count('data-drawn="yes"') == dom.count("data-chart=") == 11 and 'data-drawn="no"' not in dom
    manifest = json.loads((rh.VENDOR / "VERSIONS.json").read_text(encoding="utf-8"))["packages"]
    assert f'data-vega="{manifest["vega"]["version"]}"' in dom
    assert f'data-vega-lite="{manifest["vega-lite"]["version"]}"' in dom
    assert f'data-vega-embed="{manifest["vega-embed"]["version"]}"' in dom
    net = json.loads(netlog.read_text(encoding="utf-8"))
    names = {v: k for k, v in net["constants"]["logEventTypes"].items()}
    from_page = [
        e["params"]["url"] for e in net["events"]
        if names.get(e["type"]) == "URL_REQUEST_START_JOB" and str(e.get("params", {}).get("url", "")).startswith("http")
        and e["params"].get("initiator") not in (None, "not an origin")
    ]
    assert from_page == []  # no request came from the page (Chrome's own background traffic has no origin)


# --- Escaping, the cache, read-only --------------------------------------------------------------------------------------------------


def test_an_analysis_name_with_markup_and_slashes_is_escaped_in_the_file_and_safe_in_file_names(stored):
    name = '<b>&"x"/y z'
    inputs = {"name": name, "weather": {"name": "w.csv"}, "tau": {"value": 0.093, "source": "default"}}
    save_analysis("p6-escape", name, "site_done", inputs)
    file = ex.downloads_for("p6-escape", ex.saved_iso("p6-escape")).html.decode()
    assert "<b>&" not in _without_libraries(file) and "&lt;b&gt;&amp;&#34;x&#34;/y z" in file
    stem = ex.downloads_for("p6-escape", ex.saved_iso("p6-escape")).stem
    assert re.fullmatch(r"[A-Za-z0-9._-]+", stem) and stem.startswith("b_x_y_z_")
    assert "<title>PV-DIALS report · &lt;b&gt;&amp;&#34;x&#34;/y z</title>" in file
    assert "not recorded for this analysis" in html.unescape(file)  # sections that were never saved say so


def test_the_downloads_are_built_once_per_analysis_and_saved_time(stored, monkeypatch):
    ex.downloads_for.cache_clear()
    calls = []
    original = rh.render_html
    monkeypatch.setattr(rh, "render_html", lambda report: calls.append(1) or original(report))
    saved = ex.saved_iso(ANALYSIS)
    first = ex.downloads_for(ANALYSIS, saved)
    at = _open()
    at.run()
    second = ex.downloads_for(ANALYSIS, saved)
    assert first is second and len(calls) == 1
    assert ex.downloads_for.cache_info().hits >= 1


def test_the_report_renders_in_a_fresh_session_without_running_anything_and_writes_nothing(stored, monkeypatch):
    import pvdials.analysis as analysis_module

    def refuse(*args, **kwargs):
        pytest.fail("the report ran or rebuilt something")

    monkeypatch.setattr(run_logic, "rebuild_live", refuse)
    monkeypatch.setattr(run_logic, "run_pipelines", refuse)
    monkeypatch.setattr(analysis_module, "step_run_pipelines", refuse)
    monkeypatch.setattr(analysis_module, "step_disagreement_check", refuse)
    monkeypatch.setattr(analysis_module, "step_phase3", refuse)
    ex.downloads_for.cache_clear()
    rl.report_for.cache_clear()
    before = _counts()
    at = _open()  # only the analysis id and the flag: no run state, nothing live
    assert not at.exception and at.session_state["run"] is None
    ex.downloads_for(ANALYSIS, ex.saved_iso(ANALYSIS))
    assert _counts() == before  # all four tables and every analysis row's updated_at untouched


# --- No hash outside the technical identifiers ---------------------------------------------------------------------------------------------


def test_no_hash_like_text_is_shown_outside_technical_identifiers_on_the_page_and_in_the_file(stored):
    at = _open()
    outside = _plain(_page_html(at, skip=wording.R_IDS_OPEN))
    assert not HEX.findall(outside) and ANALYSIS not in outside.replace("p6-thesis track", "")
    inside = _plain(" ".join(el.value for el in _walk(next(e for e in at.expander if e.label == wording.R_IDS_OPEN)) if el.type == "html"))
    row = load_analysis(ANALYSIS)
    for secret in (row["inputs"]["weather"]["sha256"], ANALYSIS):
        assert secret in inside
    assert len(set(HEX.findall(inside))) >= 2 and wording.R_PROV_FILE_SHA in inside and wording.R_PROV_DATA_HASH in inside
    assert not any(e.proto.expanded for e in at.expander)  # closed by default
    visible = _plain(re.sub(r"<(script|style)\b.*?</script>|<style\b.*?</style>", " ", _without_libraries(_file()), flags=re.DOTALL))
    technical = visible.split(wording.R_IDS_OPEN)[-1]
    before = visible[: visible.rindex(wording.R_IDS_OPEN)]
    assert not HEX.findall(before) and len(set(HEX.findall(technical))) >= 2


def test_the_visible_text_of_the_file_has_no_banned_word(stored):
    visible = _plain(re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", _file(), flags=re.DOTALL)).lower()
    for word in ("recommend", "suggest", "optimal", "improv", "error", "compensat", "winner", "rank"):
        assert word not in visible, word
    assert not re.search(r"\bbest\b|\bcorrect", visible)


# --- The footer -------------------------------------------------------------------------------------------------------------------------------


def test_start_new_analysis_asks_first_and_then_closes_the_current_one_leaving_it_saved(stored):
    at = _open(name="thesis")
    at.button(key="w6_new").click().run()
    assert wording.RP_NEW_ASK in _plain(_page_html(at))
    assert at.session_state["analysis_id"] == ANALYSIS and "switched_to" not in at.session_state  # asked, nothing done
    at.button(key="w6_new_no").click().run()
    assert wording.RP_NEW_ASK not in _plain(_page_html(at)) and at.session_state["analysis_id"] == ANALYSIS
    at.button(key="w6_new").click().run()
    at.button(key="w6_new_yes_button").click().run()
    assert at.session_state["analysis_id"] is None and at.session_state["switched_to"] == "step-1"
    assert load_analysis(ANALYSIS) is not None  # it stays saved


def test_the_read_only_note_shows_only_when_the_report_is_opened_read_only(stored):
    assert wording.RP_READONLY not in _plain(_page_html(_open()))
    assert wording.RP_READONLY in _plain(_page_html(_open(readonly=True)))


def test_the_report_of_an_analysis_that_was_not_run_further_shows_plain_states(stored):
    inputs = _inputs()
    save_analysis("p6-early", "early", "site_done", inputs)
    report = rl.build_report("p6-early")
    states = {s.key: [getattr(b, "text", None) for b in s.blocks] for s in report.sections}
    assert states["phase1"] == ["not recorded for this analysis"] and states["phase2"] == ["Not run in this analysis."]
    assert states["phase3"] == ["not recorded for this analysis"] and states["year"] == ["not recorded for this analysis"]
    assert states["reexec"] == ["No change was confirmed."]
    file = ex.downloads_for("p6-early", ex.saved_iso("p6-early")).html.decode()
    assert hashlib.sha256(file.encode()).hexdigest()  # it renders
