"""The stylesheet carries the mock-up design tokens, and the sidebar rules follow the status."""

import re

from app import gating, state, theme

CSS = theme.stylesheet()

# Read from the eight mock-ups (Main, Past, Analysis, ...).
TOKENS = {
    "page background": "#F6F4EF",
    "card border": "#DAD5CB",
    "soft border": "#E6E1D7",
    "table header / soft fill": "#F1EEE7",
    "strong soft fill": "#EEEAE2",
    "primary teal": "#1F5F6B",
    "teal hover / dark": "#15454E",
    "light teal fill": "#E4EFF0",
    "body text": "#1F2328",
    "secondary text": "#5B6168",
    "muted": "#8C979A",
    "sidebar background": "#1E2A2E",
    "sidebar text": "#F2EFE8",
    "sidebar muted label": "#B9C2C4",
    "over-tau orange": "#C2702D",
}


def test_every_design_token_is_in_the_stylesheet():
    for name, value in TOKENS.items():
        assert value.lower() in CSS.lower(), f"{name} {value} missing"


def test_fonts_use_the_mockup_google_fonts_url_with_offline_fallbacks():
    assert (
        "https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600"
        "&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap"
    ) in CSS
    assert "--pv-serif: 'Fraunces', Georgia, serif" in CSS
    assert "--pv-sans: 'IBM Plex Sans', system-ui, sans-serif" in CSS
    assert "--pv-mono: 'IBM Plex Mono', monospace" in CSS


def test_sidebar_width_and_radii_match_the_mockups():
    assert "width: 248px" in CSS
    assert re.search(r"border-radius: 12px", CSS)  # cards
    assert re.search(r"min-height: 44px", CSS)  # sidebar items and buttons


def _flags(level):
    ss: dict = {}
    state.init_state(ss)
    state.set_progress(ss, level)
    return state.flags(ss)


def test_sidebar_rules_show_done_current_and_locked_differently():
    css = theme.sidebar_status_css(_flags(1), current="2")
    rules = {line.split(" {")[0]: line for line in css.splitlines() if " {" in line}

    def block(key, suffix=""):
        sel = theme._selector(key) + suffix
        return next((r for name, r in rules.items() if name == sel), "")

    assert 'content: "Done"' in block("1", "::after")  # done step: word after the title
    assert "data:image/svg+xml" in block("1", "::before")  # tick badge
    assert "#2F6E78" in block("2")  # current: filled
    assert 'content: "2"' in block("2", "::before")
    assert "#8C979A" in block("3")  # locked: muted
    assert "data:image/svg+xml" in block("3", "::before")  # lock icon
    assert block("3", "::after") == ""  # locked: icon and muted colour, no extra word


def test_sidebar_status_words_come_from_one_place():
    for level in range(6):
        flags = _flags(level)
        css = theme.sidebar_status_css(flags, current="home")
        for key in gating.STEPS:
            if gating.page_status(str(key), flags, "home") == "done":
                assert 'content: "Done"' in css
