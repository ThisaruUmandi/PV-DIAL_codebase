"""Home, laid out as in the Main mock-up."""

from __future__ import annotations

from html import escape

import streamlit as st

from app import components, past_logic, wording
from app.screens import past_rows

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


RECENT_WIDTHS = [2.5, 1.15, 1.95, 1.45, 1.5]


def _recent(ss) -> None:
    """The three most recent analyses from the store, each with the one action its state allows."""
    with st.container(key="recent_head"):
        title, link = st.columns([3, 1], gap="small")
        title.html(f'<h2 class="pv-card-title">{escape(wording.RECENT_ANALYSES)}</h2>')
        with link:
            st.page_link(components.PAGES["past"], label=wording.VIEW_ALL_PAST)
    rows = past_logic.recent_rows()
    if not rows:
        st.html(f'<div class="pv-empty-row">{escape(wording.EMPTY_PAST)}</div>')
        return
    past_rows.header(RECENT_WIDTHS, wording.RECENT_HEADERS, "recent_header")
    past_rows.render_rows(rows, RECENT_WIDTHS, "recent", with_duplicate=False)


def render() -> None:
    ss = st.session_state
    past_rows.run_pending(ss)
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
            components.start_new_analysis("home_start")
        if ss.get("past_problem"):
            components.show_problem(ss["past_problem"])

        with st.container(key="recent"):
            _recent(ss)

        st.html(f'<h2 class="pv-card-title">{escape(wording.SIX_STEPS)}</h2>')
        with st.container(key="steps"):
            columns = st.columns(6)
            for step, column in zip(wording.STEP_TITLES, columns, strict=True):
                number = f"{step} · {wording.OPTIONAL}" if step == 5 else str(step)
                column.page_link(
                    components.PAGES[str(step)],
                    label=f"{number}\n\n{wording.STEP_TITLES[step]}\n\n{wording.STEP_SUMMARIES[step]}",
                )
