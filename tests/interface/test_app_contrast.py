"""Every text/background pair the stylesheet uses must read clearly (WCAG AA, 4.5:1).

The pairs are listed by hand from app/static/style.css and app/theme.py; a browser
audit of the running app (every visible text, in each state) backs this up. If a
colour in the stylesheet changes, change it here too and the ratio is re-checked.
"""

import re

import pytest

from app import theme

CSS = theme.stylesheet()


def _luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    channels = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(fg: str, bg: str) -> float:
    a, b = _luminance(fg), _luminance(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


PAIRS = [
    ("body text on page", "#1F2328", "#F6F4EF"),
    ("body text on card", "#1F2328", "#FFFFFF"),
    ("intro text", "#3E444B", "#F6F4EF"),
    ("secondary text on page", "#5B6168", "#F6F4EF"),
    ("secondary text on card", "#5B6168", "#FFFFFF"),
    ("secondary text on table header", "#5B6168", "#F1EEE7"),
    ("primary button", "#FFFFFF", "#1F5F6B"),
    ("primary button hover", "#FFFFFF", "#15454E"),
    ("secondary button", "#1F5F6B", "#FFFFFF"),
    ("link on page", "#1F5F6B", "#F6F4EF"),
    ("link on card", "#1F5F6B", "#FFFFFF"),
    ("info note", "#15454E", "#E4EFF0"),
    ("soft box", "#1F2328", "#F1EEE7"),
    ("problem box", "#7A1F1A", "#FBEAE6"),
    ("tooltip", "#F6F4EF", "#1F2328"),
    ("sidebar text", "#F2EFE8", "#1E2A2E"),
    ("sidebar active link", "#FFFFFF", "#2F6E78"),
    ("sidebar muted label", "#B9C2C4", "#1E2A2E"),
    ("sidebar locked link", "#8C979A", "#1E2A2E"),
    ("sidebar locked link, pointer over it (no fill)", "#8C979A", "#1E2A2E"),
    ("sidebar 'Done' word", "#B9C2C4", "#1E2A2E"),
    ("arrow between stage pills", "#5B6168", "#F6F4EF"),
    ("disabled button", "#5F656B", "#EFECE5"),
]


@pytest.mark.parametrize("name, fg, bg", PAIRS)
def test_text_pair_meets_aa(name, fg, bg):
    assert contrast(fg, bg) >= 4.5, f"{name}: {fg} on {bg} = {contrast(fg, bg):.2f}"


def test_every_listed_colour_is_really_in_the_stylesheet():
    for name, fg, bg in PAIRS:
        for colour in (fg, bg):
            assert colour.lower() in (CSS + theme.sidebar_status_css({}, "home")).lower(), (name, colour)


def test_tooltip_is_a_dark_box_with_light_text_and_lets_the_mouse_through():
    block = re.search(r'\[data-testid="stTooltipContent"\] \{[^}]*\}', CSS).group(0)
    assert "background: var(--pv-text)" in block
    assert re.search(r"stTooltipContent.*color: #F6F4EF", CSS, re.DOTALL)
    assert "pointer-events: none" in CSS


def test_the_toolbar_is_not_hidden_because_it_holds_the_button_that_reopens_the_sidebar():
    assert not re.search(r'\[data-testid="stToolbar"\]\s*\{\s*display:\s*none', CSS)
    assert 'data-testid="stMainMenu"' in CSS and 'data-testid="stAppDeployButton"' in CSS


def test_sidebar_is_always_visible_on_a_desktop_window_and_reopenable_on_a_narrow_one():
    desktop = CSS[CSS.index("@media (min-width: 769px)"):]
    desktop = desktop[: desktop.index("}\n/*")]
    assert "transform: none !important" in desktop
    assert "stSidebarCollapseButton" in desktop and "display: none" in desktop
    narrow = CSS[CSS.index("@media (max-width: 768px)"):]
    assert "stExpandSidebarButton" in narrow and "opacity: 1" in narrow


def test_a_locked_sidebar_link_has_no_hover_fill():
    flags = {"data_valid": False}
    css = theme.sidebar_status_css(flags, "home")
    assert 'href$="step2"]:hover { background: transparent }' in css


def test_sidebar_links_carry_no_hover_box_and_headings_no_link_icon():
    import inspect

    from app import components

    assert "help=" not in inspect.getsource(components._nav_link)
    assert "disabled=" not in inspect.getsource(components._nav_link)
    assert '[data-testid="stHeaderActionElements"] { display: none; }' in CSS
