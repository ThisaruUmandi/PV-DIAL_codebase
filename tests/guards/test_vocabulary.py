"""Path A vocabulary guards (KT §2, rules 1 and 2)."""

from ._scan import find

# Allowed: Python exception class names (UploadError, ValueError, ...) and
# pandas' errors="coerce" keyword. Both are Python/pandas API, not metric names.
ERROR_ALLOW = r'\b[A-Z]\w*Error\b|\berrors="coerce"'


def test_no_error_metric_names():
    hits = find(r"\b(rmse|mae|mbe|accuracy)\b")
    assert not hits, "Use RMSD/nRMSD/MAD/MBD, not error names:\n" + "\n".join(hits)


def test_no_error_word():
    hits = find(r"error", allow=ERROR_ALLOW)
    assert not hits, "'error' is not allowed (disagreement is not error):\n" + "\n".join(hits)


def test_no_banned_words():
    hits = find(r"\b(recommend\w*|suggest\w*|optimal\w*|improv\w*|best|correct)\b")
    assert not hits, "Banned word found:\n" + "\n".join(hits)
