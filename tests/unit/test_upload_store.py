"""Uploaded weather files are kept in the database (uploaded_files) as well as on disk."""

import hashlib

import pytest

from pvdials.data import upload
from pvdials.provenance.db import get_connection, is_reachable, run_schema

pytestmark = pytest.mark.skipif(
    not is_reachable(),
    reason="No local Postgres reachable (DATABASE_URL not set or the service isn't running).",
)

CONTENT = b"time,ghi\n2020-01-01 00:00,0\n"
SHA = hashlib.sha256(CONTENT).hexdigest()


@pytest.fixture(autouse=True)
def _clean_table():
    with get_connection() as conn:
        run_schema(conn)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM uploaded_files")
        conn.commit()
    yield


def _rows() -> list[tuple[str, bytes]]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT sha256, content FROM uploaded_files")
        return [(sha, bytes(content)) for sha, content in cur.fetchall()]


def test_store_upload_writes_disk_and_database_once(tmp_path):
    path, sha = upload.store_upload(CONTENT, root=tmp_path)
    upload.store_upload(CONTENT, root=tmp_path)

    assert sha == SHA
    assert path.read_bytes() == CONTENT
    assert _rows() == [(SHA, CONTENT)]


def test_ensure_local_rebuilds_a_deleted_file_from_the_database(tmp_path):
    path, sha = upload.store_upload(CONTENT, root=tmp_path)
    path.unlink()

    restored = upload.ensure_local(sha, root=tmp_path)

    assert restored == path
    assert upload.file_sha256(restored) == sha


def test_ensure_local_returns_none_for_an_unknown_hash(tmp_path):
    assert upload.ensure_local("0" * 64, root=tmp_path) is None


def test_ensure_local_refuses_stored_bytes_that_do_not_match_the_hash(tmp_path):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO uploaded_files (sha256, content) VALUES (%s, %s)", ("1" * 64, CONTENT))
        conn.commit()

    assert upload.ensure_local("1" * 64, root=tmp_path) is None


def test_store_upload_still_writes_to_disk_when_the_database_fails(tmp_path, monkeypatch):
    def broken(_work, *_a, **_k):
        raise RuntimeError("database down")

    monkeypatch.setattr("pvdials.provenance.db.run", broken)

    path, _ = upload.store_upload(CONTENT, root=tmp_path)

    assert path.read_bytes() == CONTENT


def test_backfill_copies_hash_named_files_and_skips_the_rest(tmp_path):
    (tmp_path / f"{SHA}.csv").write_bytes(CONTENT)
    (tmp_path / "not_a_hash.csv").write_bytes(b"x")

    assert upload.backfill_uploads(root=tmp_path) == (1, 1)
    assert _rows() == [(SHA, CONTENT)]
