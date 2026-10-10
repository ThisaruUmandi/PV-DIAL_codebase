"""The pooled connection (db.run) and the recorder's no-resend rule. pvdials_test only (tests/conftest.py
points DATABASE_URL there and refuses pvdials_dev)."""

import psycopg
import pytest

from pvdials.provenance import db
from pvdials.provenance.db import get_connection, is_reachable, run, run_schema

pytestmark = pytest.mark.skipif(
    not is_reachable(),
    reason="No local Postgres reachable (DATABASE_URL not set or the service isn't running).",
)


@pytest.fixture(autouse=True)
def _scratch_table():
    with get_connection() as conn:
        run_schema(conn)
        conn.execute("CREATE TABLE IF NOT EXISTS pool_probe (n INT)")
        conn.execute("DELETE FROM pool_probe")
        conn.commit()
    yield
    with get_connection() as conn:
        conn.execute("DROP TABLE IF EXISTS pool_probe")
        conn.commit()


def _rows():
    with get_connection() as conn:
        return [r[0] for r in conn.execute("SELECT n FROM pool_probe ORDER BY n").fetchall()]


def test_run_commits_and_returns_the_result():
    assert run(lambda conn: conn.execute("INSERT INTO pool_probe VALUES (1) RETURNING n").fetchone()[0]) == 1
    assert _rows() == [1]


def test_run_rolls_back_when_the_work_fails():
    def work(conn):
        conn.execute("INSERT INTO pool_probe VALUES (2)")
        raise ValueError("boom")

    with pytest.raises(ValueError):
        run(work)
    assert _rows() == []


def test_one_connection_is_reused_across_calls():
    run(lambda conn: conn.execute("SELECT 1"))
    pids = {run(lambda conn: conn.info.backend_pid) for _ in range(5)}
    assert len(pids) == 1


def _kill_pooled_backend():
    pid = run(lambda conn: conn.info.backend_pid)
    with get_connection() as other:
        other.execute("SELECT pg_terminate_backend(%s)", (pid,))
        other.commit()


def test_a_dropped_connection_is_retried_once_before_the_commit():
    _kill_pooled_backend()
    calls = []

    def work(conn):
        calls.append(1)
        conn.execute("INSERT INTO pool_probe VALUES (3)")

    run(work)
    assert len(calls) == 2  # first on the dead connection, then on a fresh one
    assert _rows() == [3]  # saved once


def test_an_error_on_a_connection_that_is_still_up_is_not_retried():
    calls = []

    def work(conn):
        calls.append(1)
        raise psycopg.OperationalError("not a dropped connection")

    with pytest.raises(psycopg.OperationalError):
        run(work)
    assert len(calls) == 1


def test_a_failure_at_the_commit_is_never_retried(monkeypatch):
    calls = []

    def work(conn):
        calls.append(1)
        conn.execute("INSERT INTO pool_probe VALUES (4)")

    def failing_commit(self):
        raise psycopg.OperationalError("connection lost during commit")

    monkeypatch.setattr(psycopg.Connection, "commit", failing_commit)
    with pytest.raises(psycopg.OperationalError):
        run(work)
    monkeypatch.undo()
    assert len(calls) == 1
    assert _rows() == []  # nothing was committed, and nothing was run a second time


def test_a_connection_idle_for_long_is_tested_when_taken(monkeypatch):
    run(lambda conn: conn.execute("SELECT 1"))
    tested = []
    original = db.ConnectionPool.check_connection
    monkeypatch.setattr(db.ConnectionPool, "check_connection", staticmethod(lambda c: (tested.append(1), original(c))[1]))
    run(lambda conn: conn.execute("SELECT 1"))
    assert tested == []  # just used: trusted
    monkeypatch.setattr(db, "CHECK_AFTER_IDLE_SECONDS", 0.0)
    run(lambda conn: conn.execute("SELECT 1"))
    assert tested == [1]  # idle past the limit: tested


def test_statements_are_never_prepared():
    assert run(lambda conn: conn.prepare_threshold) is None
    assert get_connection().prepare_threshold is None
