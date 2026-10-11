"""Worker for the cross-process idempotency test (importable by a spawned process)."""

from __future__ import annotations


def rerun_analysis(yaml_path: str, analysis_id: str) -> str:
    """Runs the full orchestrator in a fresh process against an existing analysis id."""
    import warnings

    from pvdials.analysis import run_analysis

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return run_analysis(yaml_path, analysis_id=analysis_id).analysis_id
