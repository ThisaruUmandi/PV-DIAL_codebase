"""Helpers for guard tests: scan source files for forbidden text."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCAN_DIRS = [ROOT / "src", ROOT / "app"]


def source_files():
    for d in SCAN_DIRS:
        if d.exists():
            yield from d.rglob("*.py")


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
