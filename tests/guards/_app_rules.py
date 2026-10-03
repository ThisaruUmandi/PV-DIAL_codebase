"""Rules for the interface code under app/ (verification properties #22, #23 and
the layer rules). Each rule takes a list of files and returns the violations, so
the same function checks the real app/ and a seeded violation in a test."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ST_ERROR_FILE = "app/components.py"

_COMPENSAT = re.compile(r"compensat\w*", re.IGNORECASE)
_SORT = re.compile(
    r"\bsorted\(|\.sort\(|sort_values|argsort|nlargest|nsmallest|heapq|\.rank\(|"
    r"\bsort\s*=\s*(?!None\b)"
)
_FORBIDDEN_IMPORT_ROOTS = {"experiments", "tests"}


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _lines(path: Path):
    yield from enumerate(path.read_text(encoding="utf-8").splitlines(), 1)


def check_st_error_only_in_wrapper(files, root: Path) -> list[str]:
    """st.error( may appear once, in app/components.py."""
    hits, count = [], 0
    for path in files:
        for n, line in _lines(path):
            if "st.error(" in line:
                count += 1
                if _rel(path, root) != ST_ERROR_FILE:
                    hits.append(f"{_rel(path, root)}:{n}: st.error outside {ST_ERROR_FILE}")
    if count > 1:
        hits.append(f"st.error( appears {count} times in app/; the wrapper is the only use")
    return hits


def check_no_compensation_words(files, root: Path) -> list[str]:
    """The words 'compensating' / 'compensation' never reach the interface or report."""
    return [
        f"{_rel(path, root)}:{n}: {line.strip()}"
        for path in files
        for n, line in _lines(path)
        if _COMPENSAT.search(line)
    ]


def check_no_forbidden_imports(files, root: Path) -> list[str]:
    """app/ must not import experiments/ or tests/."""
    hits = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules = [node.module]
            for module in modules:
                if module.split(".")[0] in _FORBIDDEN_IMPORT_ROOTS:
                    hits.append(f"{_rel(path, root)}:{node.lineno}: imports {module}")
    return hits


def check_no_sort_keys(files, root: Path) -> list[str]:
    """No sorting or ranking in app/ (property #22: candidates in pool order, pairs
    in fixed order, saved analyses by date or name). A line may opt out with
    '# sort-ok: <reason>', which is then visible in review."""
    return [
        f"{_rel(path, root)}:{n}: {line.strip()}"
        for path in files
        for n, line in _lines(path)
        if _SORT.search(line) and "# sort-ok:" not in line
    ]


def check_run_analysis_not_given_an_existing_id(files, root: Path) -> list[str]:
    """The app creates analyses through run_analysis only with a fresh id: a call
    that passes an id (second argument or analysis_id=) is a rerun over a saved
    analysis, which overwrites its stored results. Rebuilds use the step
    functions."""
    hits = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name != "run_analysis":
                continue
            if len(node.args) >= 2 or any(kw.arg == "analysis_id" for kw in node.keywords):
                hits.append(f"{_rel(path, root)}:{node.lineno}: run_analysis called with an id")
    return hits
