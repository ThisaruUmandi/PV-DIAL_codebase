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


def find(pattern: str):
    rx = re.compile(pattern, re.IGNORECASE)
    hits = []
    for path in source_files():
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if rx.search(line):
                hits.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()}")
    return hits