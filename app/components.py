"""Shared Streamlit pieces: the sidebar, summary strip, pending-change prompt and
the one place a failure is shown to the user."""

from __future__ import annotations

import streamlit as st

from app import gating, state, wording

# page key -> st.Page, set by main.py on every run
PAGES: dict[str, st.Page] = {}


def register_pages(pages: dict[str, st.Page]) -> None:
    PAGES.clear()
    PAGES.update(pages)


def show_problem(message: str) -> None:
    """The only place a problem is shown with Streamlit's red box. Say what
    happened and what to do next, in plain words, with no stack trace."""
    st.error(message)


def sidebar(current: str) -> None:
    """Brand, then one link per page with its status written out."""
    flags = state.flags(st.session_state)
    with st.sidebar:
        st.markdown(f"### {wording.APP_TITLE}")
        st.caption(wording.APP_TAGLINE)
        for key in gating.PAGE_KEYS:
            status = gating.page_status(key, flags, current)
            st.page_link(
                PAGES[key],
                label=gating.page_label(key, status),
                disabled=(status == "locked"),
            )
            if key == "home":
                st.caption("Current analysis")


def step_header(step: int) -> None:
    st.caption(wording.STEP_OF.format(n=step))
    st.title(wording.STEP_TITLES[step])


def summary_strip() -> None:
    """One line: analysis, weather file, the three pipelines, τ and its source (F2.2)."""
    parts = state.summary_parts(st.session_state)
    with st.container(border=True):
        st.caption(" | ".join(f"**{label}:** {text}" for label, text in parts))


def locked_panel(step: int) -> None:
    reason = gating.lock_reason(step, state.flags(st.session_state))
    st.subheader(wording.LOCKED_HEADING)
    st.info(reason)
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
        st.info(wording.CANCELLED_NOTE)
    if not pending:
        return
    with st.container(border=True):
        st.warning(pending["message"])
        left, right = st.columns(2)
        left.button(wording.CONFIRM, on_click=_confirm, key="pending_confirm")
        right.button(wording.CANCEL, on_click=_cancel, key="pending_cancel")
