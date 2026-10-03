"""Look and feel: loads the stylesheet and builds the per-run sidebar rules.

app/static/style.css holds the fixed rules (tokens read from the mock-ups). The
sidebar's per-page badge, status word and colours depend on the analysis state, so
those few rules are generated here for each run, keyed on each link's address.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from urllib.parse import quote

import streamlit as st

from app import gating, wording

STYLE_PATH = Path(__file__).resolve().parent / "static" / "style.css"

_LINK = 'section[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"]'
_HREF = {"home": "", **{str(n): f"step{n}" for n in range(1, 7)}, "past": "past"}

_CHECK = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='#FFFFFF' "
    "stroke-width='3' stroke-linecap='round' stroke-linejoin='round'><path d='M5 12.5l4.5 4.5L19 7.5'/></svg>"
)
_LOCK = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='#8C979A' "
    "stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'><rect x='5.5' y='10.5' width='13' "
    "height='9' rx='1.5'/><path d='M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5'/></svg>"
)
_HOME = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='#F2EFE8' "
    "stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'><path d='M3 11l9-7 9 7'/>"
    "<path d='M5 10v10h14V10'/><path d='M10 20v-6h4v6'/></svg>"
)
_CLOCK = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='#F2EFE8' "
    "stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'><circle cx='12' cy='12' r='8.5'/>"
    "<path d='M12 7.5V12l3 2'/></svg>"
)


def _svg(markup: str, size: int, background: str = "transparent") -> str:
    return f'{background} url("data:image/svg+xml,{quote(markup)}") center / {size}px no-repeat'


def _selector(page_key: str) -> str:
    href = _HREF[page_key]
    return f'{_LINK}[href=""]' if page_key == "home" else f'{_LINK}[href$="{href}"]'


def sidebar_status_css(flags: Mapping[str, bool], current: str) -> str:
    """Rules for each sidebar link: badge (number, tick or lock), colours and the
    status word shown after the title, so colour is never the only signal."""
    rules = []
    for key in gating.PAGE_KEYS:
        status = gating.page_status(key, flags, current)
        sel = _selector(key)
        word = gating.status_word(key, status)
        before, link = [], []
        if key in ("home", "past"):
            before.append(f"background: {_svg(_HOME if key == 'home' else _CLOCK, 18)}")
        elif status == "done":
            before.append(f"background: {_svg(_CHECK, 14, '#3F7F88')}")
        elif status == "locked":
            before.append(f"background: {_svg(_LOCK, 18)}")
        else:
            border = "#FFFFFF" if status == "current" else "#8FA3A7"
            before.append(f'content: "{key}"; border: 1px solid {border}')
        if status == "current":
            link.append("background: #2F6E78; color: #FFFFFF; font-weight: 600")
        if status == "locked":
            link.append("color: #8C979A")
            rules.append(f"{sel}:hover {{ background: transparent }}")  # a locked link does not react
        if link:
            rules.append(f"{sel} {{ {'; '.join(link)} }}")
            rules.append(f"{sel} p {{ font-weight: inherit }}")
        rules.append(f"{sel}::before {{ {'; '.join(before)} }}")
        if word and status == "done":
            rules.append(f'{sel}::after {{ content: "{word}" }}')
    return "\n".join(rules)


def stylesheet() -> str:
    return STYLE_PATH.read_text(encoding="utf-8")


def text_variables() -> str:
    """Words that the stylesheet draws (the drop-zone prompt, the replace-file button) are
    kept in wording.py like all other text and handed to the stylesheet as CSS variables."""
    values = {
        "--pv-drop-text": wording.D_DROP_TEXT,
        "--pv-replace-text": wording.D_REPLACE_TEXT,
    }
    body = "; ".join(f'{name}: "{value}"' for name, value in values.items())
    return f":root {{ {body} }}"


def apply(flags: Mapping[str, bool], current: str) -> None:
    """Inject the stylesheet and this run's sidebar rules (call once per run)."""
    st.html(f"<style>\n{stylesheet()}\n{text_variables()}\n{sidebar_status_css(flags, current)}\n</style>")


__all__ = ["apply", "sidebar_status_css", "stylesheet", "wording"]
