"""Neutral-wording check for evaluation report text (KT section 5): the same
banned-word patterns tests/guards/test_vocabulary.py already enforces on
src/pvdials/, applied here directly to strings instead of files, since
experiments/ and its own generated report text aren't covered by that guard.

Kept in sync with test_vocabulary.py's patterns by inspection (that guard
scans files; this checks strings) -- if the guard's patterns ever change,
update these to match.
"""

from __future__ import annotations

import re

_ERROR_ALLOW = re.compile(r'\b[A-Z]\w*Error\b|\berrors="coerce"')
_PATTERNS = [
    re.compile(r"\b(rmse|mae|mbe|accuracy)\b", re.IGNORECASE),
    re.compile(r"\b(recommend\w*|suggest\w*|optimal\w*|improv\w*|best|correct)\b", re.IGNORECASE),
]
_ERROR_PATTERN = re.compile(r"error", re.IGNORECASE)


def check_banned_words(text: str) -> list[str]:
    """Every banned-word hit found in text, as 'pattern: matched text' lines.
    Empty list means clean.
    """
    hits = []
    for pattern in _PATTERNS:
        for m in pattern.finditer(text):
            hits.append(f"{pattern.pattern}: {m.group(0)!r}")
    checked = _ERROR_ALLOW.sub("", text)
    for m in _ERROR_PATTERN.finditer(checked):
        hits.append(f"error: {m.group(0)!r}")
    return hits
