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
    """A locked step is still a link: it opens the lock panel, which says why it is
    locked. No hover box, so nothing covers the other steps."""
    st.page_link(PAGES[key], label=gating.page_title(key))


# --- Field furniture, shared by every page ------------------------------------------------------

def icon(name: str, size: int = 16) -> str:
    """A small outline icon, drawn by the stylesheet (inline SVG is removed by Streamlit's
    HTML clean-up). It always sits beside words, so meaning never rests on colour."""
    return (
        f'<span class="pv-icon pv-icon-{name}" style="width:{size}px;height:{size}px" aria-hidden="true"></span>'
    )


_TAGS = {
    "file": (wording.TAG_FROM_FILE, "lock"),
    "required": (wording.TAG_REQUIRED, None),
    "optional": (wording.TAG_OPTIONAL, None),
    "default": (wording.TAG_DEFAULT, None),
    "user": (wording.TAG_USER_ENTERED, None),
    "differs": (wording.C_DIFFERS, None),
}


def tag_html(kind: str) -> str:
    """A small tag beside a label: 'from file', 'required', 'optional' or 'default'. The
    tag is a word, so it reads without colour."""
    text, glyph = _TAGS[kind]
    return (
        f'<span class="pv-tag pv-tag-{kind}" title="{escape(wording.TAG_TITLES[kind])}">'
        f"{icon(glyph, 12) if glyph else ''}{escape(text)}</span>"
    )


def field_label(text: str, tag: str | None = None, hint: str | None = None, stacked: bool = False) -> None:
    """The label above a field (14 px, weight 500) with its tag. The widget itself is
    drawn with a hidden label so screen readers still get the text. stacked puts the tag
    on its own line (for narrow, three-across rows, so the fields below stay level)."""
    title = f' title="{escape(hint)}"' if hint else ""
    css = "pv-label pv-label-stacked" if stacked else "pv-label"
    st.html(
        f'<div class="{css}"><span class="pv-label-text"{title}>{escape(text)}</span>'
        f"{tag_html(tag) if tag else ''}</div>"
    )


def over_tau_mark() -> str:
    """The one look for 'over τ': an outlined tag in plain ink, on one line. 'Within τ' has no mark at all."""
    return f'<span class="pv-over">{escape(wording.P4_OVER_TAU)}</span>'


def message_html(kind: str, text: str, boxed: bool = True) -> str:
    """Icon + words: tick (ok), warning (warn), cross (bad). Colour only adds to it."""
    glyph = {"ok": "ok", "warn": "warn", "bad": "bad", "todo": "todo"}[kind]
    box = " pv-msg-box" if boxed else ""
    return f'<div class="pv-msg pv-msg-{kind}{box}">{icon(glyph)}<span>{escape(text)}</span></div>'


def message(kind: str, text: str, boxed: bool = True) -> None:
    st.html(message_html(kind, text, boxed))


def card_title(title: str, sub: str | None = None) -> None:
    """Section title with a one-line explanation under it."""
    sub_html = f'<p class="pv-card-sub">{escape(sub)}</p>' if sub else ""
    st.html(f'<h2 class="pv-card-title">{escape(title)}</h2>{sub_html}')


def checklist(items: list[tuple[bool, str, str]], heading: str, ready_text: str) -> None:
    """What is still missing, with ticks. items: (done, label, missing detail)."""
    rows = []
    for done, label, detail in items:
        kind = "ok" if done else "todo"
        text = label if done or not detail else f"{label} — {detail}"
        rows.append(f'<li class="pv-check pv-check-{kind}">{icon(kind)}<span>{escape(text)}</span></li>')
    tail = f'<div class="pv-check-ready">{escape(ready_text)}</div>' if all(i[0] for i in items) else ""
    st.html(f'<div class="pv-checklist"><b>{escape(heading)}</b><ul>{"".join(rows)}</ul>{tail}</div>')


# --- Page furniture -----------------------------------------------------------------


def step_header(step: int) -> None:
    with st.container(key="step_head"):
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
    cancelled = state.cancel_pending(st.session_state)
    st.session_state["cancel_note"] = True
    if cancelled and cancelled.get("reset_uploader"):
        # a file picker cannot be set back; a new one takes its place, empty
        st.session_state["upload_n"] = st.session_state.get("upload_n", 0) + 1


def flash() -> None:
    """A short confirmation after a step is saved (shown once)."""
    message = st.session_state.pop("flash", None)
    if message:
        note(message)


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
