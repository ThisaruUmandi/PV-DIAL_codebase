"""Shared Streamlit pieces: the sidebar, headings, summary strip, lock panel, the
pending-change prompt and the one place a failure is shown to the user.

HTML here is structure only; all text comes from wording.py or state, and every
inserted value is escaped.
"""

from __future__ import annotations

from html import escape
from importlib.metadata import version

import streamlit as st

from app import gating, state, theme, wording
from pvdials.config import load_defaults

# page key -> st.Page, set by main.py on every run
PAGES: dict[str, st.Page] = {}


def register_pages(pages: dict[str, st.Page]) -> None:
    PAGES.clear()
    PAGES.update(pages)


def show_problem(message: str) -> None:
    """The only place a problem is shown with Streamlit's red box. Say what
    happened and what to do next, in plain words, with no stack trace."""
    st.error(message)


def note(text: str) -> None:
    """A soft teal note (the mock-ups' information box)."""
    st.html(f'<div class="pv-note pv-note-info">{escape(text)}</div>')


def eyebrow(text: str) -> None:
    st.html(f'<div class="pv-eyebrow">{escape(text)}</div>')


# --- Sidebar ----------------------------------------------------------------------


def _footer_html(connected: bool) -> str:
    tau = st.session_state.get("tau")
    if isinstance(tau, dict):
        tau_text = wording.TAU_FOOTER.format(value=tau["value"], source=tau["source"])
    else:
        tau_text = wording.TAU_FOOTER.format(value=load_defaults()["dla"]["tau"], source="default")
    store_text = wording.STORE_CONNECTED if connected else wording.STORE_NOT_CONNECTED
    return (
        '<div class="pv-side-footer">'
        f"<div>{escape(store_text)}</div>"
        f'<div class="pv-mono">{escape(wording.PVLIB_FOOTER.format(version=version("pvlib")))}</div>'
        f'<div class="pv-mono">{escape(tau_text)}</div></div>'
    )


def sidebar(current: str, connected: bool = True) -> None:
    """Brand, then one link per page. The badge, status word and colours are drawn by
    the stylesheet from the same status the links carry as a tooltip."""
    flags = state.flags(st.session_state)
    theme.apply(flags, current)
    with st.sidebar:
        st.html(
            '<div class="pv-brand">'
            f'<div class="pv-brand-name">{escape(wording.APP_TITLE)}</div>'
            f'<div class="pv-brand-tag">{escape(wording.APP_TAGLINE)}</div></div>'
        )
        for key in gating.PAGE_KEYS:
            status = gating.page_status(key, flags, current)
            if key == "past":
                with st.container(key="nav_past"):
                    _nav_link(key, status, flags)
                continue
            _nav_link(key, status, flags)
            if key == "home":
                st.html(f'<div class="pv-side-label">{escape(wording.CURRENT_ANALYSIS)}</div>')
        st.html(_footer_html(connected))


def _nav_link(key: str, status: str, flags) -> None:
    st.page_link(
        PAGES[key],
        label=gating.page_title(key),
        help=gating.page_tooltip(key, status, flags),
        disabled=(status == "locked"),
    )


# --- Page furniture -----------------------------------------------------------------


def step_header(step: int) -> None:
    eyebrow(wording.STEP_OF.format(n=step))
    st.title(wording.STEP_TITLES[step])


def summary_strip() -> None:
    """One line: analysis, weather file, the three pipelines, τ and its source (F2.2)."""
    parts = state.summary_parts(st.session_state)
    items = []
    for label, text in parts:
        mono = " pv-mono" if label.startswith("Pipeline") or label == wording.TAU else ""
        items.append(f'<span><b>{escape(label)}</b><span class="{mono.strip()}">{escape(text)}</span></span>')
    with st.container(key="summary"):
        st.html(f'<div class="pv-strip">{"".join(items)}</div>')


def locked_panel(step: int) -> None:
    reason = gating.lock_reason(step, state.flags(st.session_state))
    with st.container(key="lock"):
        st.html(
            f'<div class="pv-lock-title">{escape(wording.LOCKED_HEADING)}</div>'
            f'<p class="pv-lock-text">{escape(reason or "")}</p>'
        )
        previous = PAGES.get(str(step - 1))
        if previous is not None:
            st.page_link(previous, label=f"Go to step {step - 1}")


def _confirm() -> None:
    state.confirm_pending(st.session_state)


def _cancel() -> None:
    state.cancel_pending(st.session_state)
    st.session_state["cancel_note"] = True


def render_pending_change() -> None:
    """If an input change would clear later steps, say so and ask (F2.5)."""
    pending = st.session_state.get("pending")
    if st.session_state.pop("cancel_note", False):
        note(wording.CANCELLED_NOTE)
    if not pending:
        return
    with st.container(key="pending"):
        st.html(f'<div style="font-weight:600">{escape(pending["message"])}</div>')
        left, right, _ = st.columns([1, 1, 3])
        left.button(wording.CONFIRM, on_click=_confirm, key="pending_confirm", type="primary")
        right.button(wording.CANCEL, on_click=_cancel, key="pending_cancel")
