"""The downloadable report: one HTML file that opens with no internet. It walks the same blocks as the Report
page (app/report_logic), draws the charts with the vendored Vega, Vega-Lite and Vega-Embed inlined in the file,
and loads nothing from outside: no CDN, no web fonts, no external URL."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from app import report_logic as rl
from app import wording

APP = Path(__file__).resolve().parent
VENDOR = APP / "vendor" / "vega"
SANS_STACK = 'system-ui, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif'
MONO_STACK = 'ui-monospace, Menlo, Consolas, "Courier New", monospace'
_FONTS = {"IBM Plex Sans": SANS_STACK, "IBM Plex Mono": MONO_STACK, "Fraunces": "Georgia, serif"}


def _swap_fonts(node: Any) -> Any:
    """The page keeps the design fonts; the file gets system stacks, so nothing has to be fetched."""
    if isinstance(node, dict):
        return {key: _swap_fonts(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_swap_fonts(value) for value in node]
    return _FONTS.get(node, node) if isinstance(node, str) else node


def spec_for_file(chart) -> dict:
    """An Altair chart as a Vega-Lite spec for the file: system fonts, and the width follows the page."""
    spec = _swap_fonts(chart.to_dict())
    spec["width"] = "container"
    spec["autosize"] = {"type": "fit", "contains": "padding"}
    return spec


def _script_json(spec: dict) -> str:
    """JSON that is safe inside a <script> element (no '<', so no closing tag can appear in it)."""
    return json.dumps(spec, separators=(",", ":")).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def _items(blocks: list[Any], counter: list[int]) -> list[dict]:
    out: list[dict] = []
    for block in blocks:
        if isinstance(block, rl.Facts):
            out.append({"kind": "facts", "rows": block.rows})
        elif isinstance(block, rl.Lines):
            out.append({"kind": "lines", "entries": block.items})
        elif isinstance(block, rl.Table):
            out.append({"kind": "table", "html": block.html})
        elif isinstance(block, rl.Chart):
            counter[0] += 1
            out.append(
                {"kind": "chart", "id": counter[0], "alt": block.alt_text, "spec": _script_json(spec_for_file(block.chart))}
            )
        elif isinstance(block, rl.Heading):
            out.append({"kind": "heading", "text": block.text})
        elif isinstance(block, rl.Strip):
            out.append({"kind": "strip", "label": block.label, "value": block.value})
        elif isinstance(block, rl.Text):
            out.append({"kind": "text", "text": block.text, "style": block.kind})
        elif isinstance(block, rl.Columns):
            out.append({"kind": "columns", "left": _items(block.left, counter), "right": _items(block.right, counter)})
        elif isinstance(block, rl.Details):
            out.append({"kind": "details", "title": block.title, "blocks": _items(block.blocks, counter)})
    return out


def render_html(report: rl.Report) -> str:
    environment = Environment(loader=FileSystemLoader(APP / "templates"), autoescape=True)
    template = environment.get_template("report.html.j2")
    counter = [0]
    sections = [
        {"key": s.key, "title": s.title, "sub": s.sub, "blocks": _items(s.blocks, counter)} for s in report.sections
    ]
    technical = {"kind": "details", "title": report.technical.title, "blocks": _items(report.technical.blocks, counter)}
    return template.render(
        title=wording.RP_HTML_TITLE.format(name=report.name),
        eyebrow=wording.STEP_OF.format(n=6),
        heading=wording.STEP_TITLES[6],
        name=report.name,
        saved=wording.RP_SAVED.format(time=report.saved_text),
        noscript=wording.RP_HTML_NOSCRIPT,
        foot=wording.RP_HTML_FOOT,
        sections=sections,
        technical=technical,
        css=(APP / "static" / "report.css").read_text(encoding="utf-8"),
        vega_js=(VENDOR / "vega.min.js").read_text(encoding="utf-8"),
        vega_lite_js=(VENDOR / "vega-lite.min.js").read_text(encoding="utf-8"),
        vega_embed_js=(VENDOR / "vega-embed.min.js").read_text(encoding="utf-8"),
    )
