"""Step 6 · Report, laid out as in the Report mock-up: the same sections in the same order.

Built only from the stored analysis (no pipeline is run, rebuild_live is not called, nothing is written), from the
same view as the downloadable HTML report. Over τ has page 4's look; nothing is sorted or ranked.
"""

from __future__ import annotations

from html import escape

import streamlit as st

from app import components, gating, report_export, report_logic, state, wording
from pvdials.analysis import AnalysisError

# --- Blocks -----------------------------------------------------------------------------------------------------------


def _facts(rows) -> str:
    cells = "".join(
        f'<div class="pv-kv pv-prov-row"><span>{escape(label)}</span><span class="pv-mono pv-prov-value">{escape(value)}</span></div>'
        for label, value in rows
    )
    return f'<div class="pv-prov">{cells}</div>'


def _lines(items) -> str:
    rows = "".join(
        f'<div class="pv-rp-line"><span class="pv-mono">{escape(head)}</span><span>{escape(label)}</span>'
        f'<span class="pv-mono">{escape(tail)}</span></div>'
        for head, label, tail in items
    )
    return f'<div class="pv-rp-lines">{rows}</div>'


def _blocks(blocks) -> None:
    for block in blocks:
        if isinstance(block, report_logic.Facts):
            st.html(_facts(block.rows))
        elif isinstance(block, report_logic.Lines):
            st.html(_lines(block.items))
        elif isinstance(block, report_logic.Table):
            st.html(block.html)
        elif isinstance(block, report_logic.Chart):
            st.altair_chart(block.chart, width="stretch")
            st.html(f'<p class="pv-sr-only">{escape(block.alt_text)}</p>')
        elif isinstance(block, report_logic.Heading):
            st.html(f'<h3 class="pv-rp-h3">{escape(block.text)}</h3>')
        elif isinstance(block, report_logic.Strip):
            st.html(f'<div class="pv-strip-grey"><span>{escape(block.label)}</span><b class="pv-mono">{escape(block.value)}</b></div>')
        elif isinstance(block, report_logic.Text):
            css = "pv-disclaimer" if block.kind == "disclaimer" else ("pv-empty" if block.kind == "state" else "pv-note-line")
            st.html(f'<p class="{css}">{escape(block.text)}</p>')
        elif isinstance(block, report_logic.Columns):
            left, right = st.columns(2)
            with left:
                _blocks(block.left)
            with right:
                _blocks(block.right)
        elif isinstance(block, report_logic.Details):
            with st.expander(block.title, expanded=False):
                _blocks(block.blocks)


def _section(section: report_logic.Section) -> None:
    with st.container(key=f"card_rp_{section.key}"):
        components.card_title(section.title, section.sub)
        _blocks(section.blocks)


# --- Header, footer -------------------------------------------------------------------------------------------------------


def _downloads(ss, report: report_logic.Report, saved: str, columns) -> None:
    stem = report_export.safe_stem(report.name, report.saved)
    spec = (
        (wording.RP_DL_HTML, wording.RP_HELP_HTML, "text/html", f"{stem}_report.html", lambda: report_export.downloads_for(report.analysis_id, saved).html, "w6_dl_html"),
        (wording.RP_DL_CSV, wording.RP_HELP_CSV, "text/csv", f"{stem}_results.csv", lambda: report_export.downloads_for(report.analysis_id, saved).csv, "w6_dl_csv"),
        (wording.RP_DL_PROV, wording.RP_HELP_PROV, "application/json", f"{stem}_provenance.json", lambda: report_export.downloads_for(report.analysis_id, saved).prov, "w6_dl_prov"),
    )
    for column, (label, help_text, mime, name, data, key) in zip(columns, spec, strict=True):
        with column:
            st.download_button(label, data=data, file_name=name, mime=mime, help=help_text, key=key, width="stretch")


def _footer(ss) -> None:
    with st.container(key="rp_foot"):
        left, right = st.columns([1, 1])
        with left:
            st.page_link(components.PAGES["past"], label=wording.RP_BACK_PAST)
        with right:
            st.button(wording.RP_NEW, key="w6_new", type="primary", on_click=lambda: st.session_state.__setitem__("w6_asking", True))
        if ss.get("w6_asking"):
            st.html(f'<p class="pv-ask">{escape(wording.RP_NEW_ASK)}</p>')
            yes, no = st.columns(2)
            with yes:
                if st.button(wording.RP_NEW_YES, key="w6_new_yes_button", type="primary"):
                    state.new_analysis(ss)
                    st.switch_page(components.PAGES["1"])
            with no:
                st.button(wording.RP_NEW_NO, key="w6_new_no", on_click=lambda: st.session_state.__setitem__("w6_asking", False))


# --- The page ----------------------------------------------------------------------------------------------------------------


def render() -> None:
    ss = st.session_state
    flags = state.flags(ss)
    head_left, head_right = st.columns([1, 2])
    with head_left:
        components.step_header(6)
    if not gating.is_unlocked(6, flags):
        components.locked_panel(6)
        return
    analysis_id = ss.get("analysis_id")
    saved = report_export.saved_iso(analysis_id) if analysis_id else ""
    if not saved:
        components.show_problem(wording.RP_NO_ANALYSIS)
        return
    try:
        report = report_logic.report_for(analysis_id, saved)
    except AnalysisError as exc:
        components.show_problem(str(exc))
        return
    with head_right:
        _downloads(ss, report, saved, st.columns(3))
    readonly = (
        f'<span class="pv-rp-readonly">{escape(wording.RP_READONLY)}</span>' if ss.get("readonly") else ""
    )
    with st.container(key="card_rp_id"):
        st.html(
            f'<div class="pv-rp-id"><div><b>{escape(report.name)}</b>'
            f'<span class="pv-muted"> · {escape(wording.RP_SAVED.format(time=report.saved_text))}</span></div>{readonly}</div>'
        )
    for section in report.sections:
        _section(section)
    with st.container(key="card_rp_technical"):
        _blocks([report.technical])
    _footer(ss)
