"""Hazard TI: the test suite must never touch pvdials_dev. Runs before
collection and before any fixture (pytest_configure fires right after
argument parsing) -- a misconfigured TEST_DATABASE_URL fails the whole
session immediately, with nothing collected or run, rather than letting
_clean_schema or any other DB-touching fixture reach a connection.

DATABASE_URL is always set by .env (to pvdials_dev) by the time any test
file imports provenance/db.py, and python-dotenv's load_dotenv() defaults
to override=False -- so setting os.environ["DATABASE_URL"] here, before
any test file is imported, is what actually takes effect, and .env's own
load_dotenv() call later will not clobber it back.
"""

from __future__ import annotations

import os

from experiments.evaluation.db_safety import guard_not_dev_database, resolve_test_database_url


def pytest_configure(config) -> None:
    url = resolve_test_database_url()
    guard_not_dev_database(url, "the test suite")
    os.environ["DATABASE_URL"] = url
