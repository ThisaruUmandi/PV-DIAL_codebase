"""Helpers for guard tests: scan source files for forbidden text."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCAN_DIRS = [ROOT / "src", ROOT / "app"]


APP_DIR = ROOT / "app"
TEMPLATE_DIR = APP_DIR / "templates"
TEMPLATE_SUFFIXES = (".j2", ".html")
STATIC_DIR = APP_DIR / "static"


def app_python_files(app_dir: Path = APP_DIR):
    """Every .py file under app/."""
    if app_dir.exists():
        yield from sorted(app_dir.rglob("*.py"))


def template_files(template_dir: Path = TEMPLATE_DIR):
    """The report template(s): text the user reads, so the vocabulary guard covers it."""
    if template_dir.exists():
        for path in sorted(template_dir.rglob("*")):
            if path.is_file() and path.suffix in TEMPLATE_SUFFIXES:
                yield path


def stylesheet_files(static_dir: Path = STATIC_DIR):
    """The interface stylesheet(s): comments and content strings are text the user may read."""
    if static_dir.exists():
        yield from sorted(static_dir.rglob("*.css"))


def source_files():
    for d in SCAN_DIRS:
        if d.exists():
            yield from d.rglob("*.py")
    yield from template_files()
    yield from stylesheet_files()


def find(pattern: str, allow: str | None = None):
    """Return 'path:line: text' for every line matching pattern (case-insensitive).

    allow: optional case-sensitive pattern removed from each line before matching,
    for uses that are permitted (e.g. Python exception class names).
    """
    rx = re.compile(pattern, re.IGNORECASE)
    allow_rx = re.compile(allow) if allow else None
    hits = []
    for path in source_files():
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            checked = allow_rx.sub("", line) if allow_rx else line
            if rx.search(checked):
                hits.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()}")
    return hits
