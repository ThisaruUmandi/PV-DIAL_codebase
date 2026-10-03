"""Guards for the interface code under app/ and the report template.

Each rule is checked twice: the real app/ must pass, and a seeded violation in a
temporary file must be flagged (so a guard that silently matches nothing fails here).
"""

import pytest

from ._app_rules import (
    check_no_compensation_words,
    check_no_forbidden_imports,
    check_no_sort_keys,
    check_run_analysis_not_given_an_existing_id,
    check_st_error_only_in_wrapper,
)
from ._scan import ROOT, app_python_files, stylesheet_files, template_files


def _real_py():
    return list(app_python_files())


def _real_text():
    return list(app_python_files()) + list(template_files()) + list(stylesheet_files())


def _seed(tmp_path, relative: str, text: str):
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- the real app passes --------------------------------------------------------------


def test_real_app_st_error_only_in_the_wrapper():
    assert not check_st_error_only_in_wrapper(_real_py(), ROOT)


def test_real_app_and_template_have_no_compensation_words():
    assert not check_no_compensation_words(_real_text(), ROOT)


def test_real_app_imports_nothing_from_experiments_or_tests():
    assert not check_no_forbidden_imports(_real_py(), ROOT)


def test_real_app_has_no_sorting_or_ranking():
    assert not check_no_sort_keys(_real_py(), ROOT)


def test_real_app_never_calls_run_analysis_with_an_existing_id():
    assert not check_run_analysis_not_given_an_existing_id(_real_py(), ROOT)


# --- each rule fails on a seeded violation ----------------------------------------------


def test_seeded_st_error_in_another_file_is_flagged(tmp_path):
    bad = _seed(tmp_path, "app/screens/p.py", "import streamlit as st\nst.error('x')\n")
    assert check_st_error_only_in_wrapper([bad], tmp_path)


def test_seeded_second_st_error_in_the_wrapper_file_is_flagged(tmp_path):
    bad = _seed(tmp_path, "app/components.py", "st.error('a')\nst.error('b')\n")
    assert check_st_error_only_in_wrapper([bad], tmp_path)


def test_single_st_error_in_the_wrapper_file_passes(tmp_path):
    good = _seed(tmp_path, "app/components.py", "def f(m):\n    st.error(m)\n")
    assert not check_st_error_only_in_wrapper([good], tmp_path)


@pytest.mark.parametrize("word", ["compensating", "Compensation", "compensates"])
def test_seeded_compensation_word_is_flagged_in_code_and_template(tmp_path, word):
    py = _seed(tmp_path, "app/w.py", f'TEXT = "outcome 3 shows {word} differences"\n')
    tpl = _seed(tmp_path, "app/templates/report.html.j2", f"<p>{word}</p>\n")
    css = _seed(tmp_path, "app/static/style.css", f'.x::after {{ content: "{word}" }}\n')
    assert check_no_compensation_words([py], tmp_path)
    assert check_no_compensation_words([tpl], tmp_path)
    assert check_no_compensation_words([css], tmp_path)


@pytest.mark.parametrize(
    "line", ["import experiments.evaluation.wording", "from tests.dla import builders",
             "from experiments import x"],
)
def test_seeded_import_from_experiments_or_tests_is_flagged(tmp_path, line):
    bad = _seed(tmp_path, "app/x.py", line + "\n")
    assert check_no_forbidden_imports([bad], tmp_path)


def test_ordinary_imports_pass_the_import_rule(tmp_path):
    good = _seed(tmp_path, "app/x.py", "import streamlit as st\nfrom pvdials import analysis\n")
    assert not check_no_forbidden_imports([good], tmp_path)


@pytest.mark.parametrize(
    "line",
    [
        "rows = sorted(rows, key=lambda r: r.nrmsd)",
        "rows.sort()",
        "df = df.sort_values('nrmsd')",
        "idx = np.argsort(values)",
        "top = df.nlargest(3, 'nrmsd')",
        "r = df.x.rank()",
        "alt.X('pair', sort='-y')",
        "import heapq",
    ],
)
def test_seeded_sorting_is_flagged(tmp_path, line):
    bad = _seed(tmp_path, "app/x.py", line + "\n")
    assert check_no_sort_keys([bad], tmp_path)


def test_sort_none_and_marked_lines_pass(tmp_path):
    good = _seed(
        tmp_path, "app/x.py",
        "alt.X('pair', sort=None)\nnames = sorted(names)  # sort-ok: name order, not disagreement\n",
    )
    assert not check_no_sort_keys([good], tmp_path)


@pytest.mark.parametrize(
    "call",
    [
        "run_analysis(path, existing_id)",
        "run_analysis(path, analysis_id=existing_id)",
        "analysis.run_analysis(path, analysis_id='abc')",
    ],
)
def test_seeded_run_analysis_with_an_id_is_flagged(tmp_path, call):
    bad = _seed(tmp_path, "app/x.py", f"def go():\n    return {call}\n")
    assert check_run_analysis_not_given_an_existing_id([bad], tmp_path)


def test_run_analysis_without_an_id_passes(tmp_path):
    good = _seed(tmp_path, "app/x.py", "def go():\n    return run_analysis(path)\n")
    assert not check_run_analysis_not_given_an_existing_id([good], tmp_path)
