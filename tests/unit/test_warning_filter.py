import warnings

from pvdials.warning_filter import ChandrupatlaWarningFilter


def test_suppresses_and_counts_the_target_warning():
    with ChandrupatlaWarningFilter() as f:
        warnings.warn_explicit(
            "invalid value encountered in divide",
            RuntimeWarning,
            filename="/some/path/scipy/optimize/_chandrupatla.py",
            lineno=437,
        )
        warnings.warn_explicit(
            "invalid value encountered in divide",
            RuntimeWarning,
            filename="/some/path/scipy/optimize/_chandrupatla.py",
            lineno=437,
        )
    assert f.count == 2


def test_leaves_unrelated_warnings_alone(monkeypatch):
    seen = []
    monkeypatch.setattr(warnings, "showwarning", lambda *a, **kw: seen.append(a))

    with ChandrupatlaWarningFilter() as f:
        warnings.warn_explicit(
            "some other problem",
            RuntimeWarning,
            filename="/some/path/elsewhere.py",
            lineno=1,
        )
    assert f.count == 0
    assert len(seen) == 1
    assert str(seen[0][0]) == "some other problem"
