"""Home, laid out as in the Main mock-up."""

from __future__ import annotations

from html import escape

import streamlit as st

from app import components, state, wording

_NOT_SHOWN_LEAD = "What it does not show:"


def _stages_strip() -> str:
    pills = '<span class="pv-arrow" aria-hidden="true">→</span>'.join(
        f'<span class="pv-pill">{escape(name)}</span>' for name in wording.STAGE_PILLS
    )
    return (
        f'<div class="pv-stages"><span class="pv-stages-label">{escape(wording.STAGES_COMPARED)}</span>'
        f"{pills}</div>"
    )


def _phases_card() -> str:
    rows = "".join(
        f'<div class="pv-phase">{escape(phase)}</div><div><b>{escape(lead)}</b> {escape(text)}</div>'
        for phase, lead, text in wording.HOME_SHOWS
    )
    rest = wording.HOME_NOT_SHOWN.removeprefix(_NOT_SHOWN_LEAD)
    return (
        f'<h2 class="pv-card-title">{escape(wording.HOME_CARD_SHOWS)}</h2>'
        f'<div class="pv-phase-grid">{rows}</div>'
        f'<div class="pv-soft"><b>{escape(_NOT_SHOWN_LEAD)}</b>{escape(rest)}</div>'
    )


def _before_card() -> str:
    items = "".join(f"<li>{escape(item)}</li>" for item in wording.HOME_BEFORE_YOU_START)
    return (
        f'<h2 class="pv-card-title">{escape(wording.HOME_CARD_BEFORE)}</h2>'
        f'<ul class="pv-list">{items}</ul>'
        f'<p class="pv-muted">{escape(wording.HOME_SAVED_NOTE)}</p>'
    )


def _recent_card() -> str:
    headers = wording.RECENT_HEADERS
    last = wording.RECENT_HEADERS[-1]
    cells = "".join(
        f'<div class="pv-th"><span class="{"pv-sr" if h == last else ""}">{escape(h)}</span></div>'
        for h in headers
    )
    return (
        '<div class="pv-recent-head">'
        f'<h2 class="pv-card-title">{escape(wording.RECENT_ANALYSES)}</h2>'
        f'<span style="font-size:14px;font-weight:600;color:var(--pv-teal)">{escape(wording.VIEW_ALL_PAST)}</span>'
        "</div>"
        '<div class="pv-table" style="grid-template-columns: 2.2fr 1fr 1.6fr 1.2fr 1fr">'
        f'{cells}<div class="pv-empty-row">{escape(wording.EMPTY_PAST)}</div></div>'
    )


def render() -> None:
    with st.container(key="home"):
        with st.container(key="home_head"):
            components.eyebrow(wording.HOME_TITLE)
            st.title(wording.HOME_HEADLINE)
            st.html(f'<p class="pv-intro">{escape(wording.HOME_INTRO)}</p>')
        st.html(_stages_strip())

        left, right = st.columns([3, 2])
        with left, st.container(key="card_phases"):
            st.html(_phases_card())
        with right, st.container(key="card_before"):
            st.html(_before_card())
            if st.button(wording.START_NEW_ANALYSIS, type="primary"):
                state.new_analysis(st.session_state)
                st.switch_page(components.PAGES["1"])

        with st.container(key="recent"):
            st.html(_recent_card())

        st.html(f'<h2 class="pv-card-title">{escape(wording.SIX_STEPS)}</h2>')
        with st.container(key="steps"):
            columns = st.columns(6)
            for step, column in zip(wording.STEP_TITLES, columns, strict=True):
                number = f"{step} · {wording.OPTIONAL}" if step == 5 else str(step)
                column.page_link(
                    components.PAGES[str(step)],
                    label=f"{number}\n\n{wording.STEP_TITLES[step]}\n\n{wording.STEP_SUMMARIES[step]}",
                )
