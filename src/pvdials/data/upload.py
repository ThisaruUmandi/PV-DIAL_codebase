"""Accepts a user-uploaded weather CSV and loads it as a raw DataFrame.

Many weather exports (e.g. PVGIS) wrap the data table in metadata: a
preamble above the header row and notes below the table. This module
finds the table, reads it unmodified, and keeps the preamble lines as
plain text. Column mapping to canonical fields happens in column_mapper.py.
"""

from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from pvdials.config import ROOT
from pvdials.data.column_mapper import KNOWN_ALIASES

UPLOADS_DIR = ROOT / "data" / "uploads"

log = logging.getLogger(__name__)


class UploadError(Exception):
    """Raised when an uploaded file can't be read as a CSV at all."""


@dataclass
class UploadedFile:
    """The data table from an uploaded CSV, plus any text above it.

    table: the raw, unmodified data table
    preamble: lines above the header row (e.g. PVGIS latitude/longitude lines)
    """

    name: str
    table: pd.DataFrame
    preamble: list[str] = field(default_factory=list)


def _find_header_row(lines: list[str]) -> int:
    """Index of the first line with a known timestamp column name, else 0.

    If no line matches, the first line is used as the header and the
    column mapper reports the timestamp as missing.
    """
    timestamp_aliases = set(KNOWN_ALIASES["timestamp"])
    for i, line in enumerate(lines):
        fields = {f.strip().lower() for f in line.split(",")}
        if fields & timestamp_aliases:
            return i
    return 0


def _find_table_end(lines: list[str], header_row: int) -> int:
    """Index of the first blank line after the header, else end of file."""
    for i in range(header_row + 1, len(lines)):
        if not lines[i].strip():
            return i
    return len(lines)


def load_uploaded_csv(file_path: str | Path) -> UploadedFile:
    """Read an uploaded CSV file into a raw, unmodified data table.

    Raises UploadError with a clear message on failure (bad encoding,
    not actually a CSV, empty file, etc.) rather than letting pandas'
    raw exception surface to the user.
    """
    path = Path(file_path)
    if not path.exists():
        raise UploadError(f"File not found: {path}")
    if path.suffix.lower() != ".csv":
        raise UploadError(f"Expected a .csv file, got: {path.suffix}")

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise UploadError(f"'{path.name}' is not UTF-8 text: {exc}") from exc

    header_row = _find_header_row(lines)
    table_end = _find_table_end(lines, header_row)

    try:
        df = pd.read_csv(io.StringIO("\n".join(lines[header_row:table_end])))
    except Exception as exc:
        raise UploadError(f"Could not read '{path.name}' as a CSV: {exc}") from exc

    if df.empty:
        raise UploadError(f"'{path.name}' was read successfully but contains no rows.")

    return UploadedFile(name=path.name, table=df, preamble=lines[:header_row])


def file_sha256(file_path: str | Path) -> str:
    """SHA-256 of the file's bytes (the uploaded file itself, not the
    preprocessed data -- provenance keeps its own hash of the latter)."""
    digest = hashlib.sha256()
    with Path(file_path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _put_in_database(sha: str, content: bytes) -> None:
    """Copy the bytes into the uploaded_files table (a no-op if that hash is already there).

    Never raises: with no database reachable the upload is still kept on disk, as before.
    """
    from pvdials.provenance import db

    def work(conn) -> None:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO uploaded_files (sha256, content) VALUES (%s, %s) "
                "ON CONFLICT (sha256) DO NOTHING",
                (sha, content),
            )

    try:
        db.run(work)
    except Exception as exc:  # noqa: BLE001 - the disk copy is still good, so this is only logged
        log.warning("Could not store upload %s in the database: %s", sha[:12], exc)


def _get_from_database(sha: str) -> bytes | None:
    from pvdials.provenance import db

    def work(conn) -> bytes | None:
        with conn.cursor() as cur:
            cur.execute("SELECT content FROM uploaded_files WHERE sha256 = %s", (sha,))
            row = cur.fetchone()
        return bytes(row[0]) if row else None

    try:
        return db.run(work)
    except Exception as exc:  # noqa: BLE001 - no database means no stored copy to give back
        log.warning("Could not read upload %s from the database: %s", sha[:12], exc)
        return None


def store_upload(content: bytes, root: str | Path | None = None) -> tuple[Path, str]:
    """Keep an uploaded file so a saved analysis can be continued, duplicated or re-run later.

    The bytes go into the database (uploaded_files, keyed by SHA-256) and into
    data/uploads/<sha256>.csv, which analysis reads from as a cache. Content-addressed:
    storing the same bytes twice keeps one copy of each. Returns (path, sha256).
    """
    sha = hashlib.sha256(content).hexdigest()
    folder = Path(root) if root is not None else UPLOADS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{sha}.csv"
    if not path.exists():
        path.write_bytes(content)
    _put_in_database(sha, content)
    return path, sha


def ensure_local(sha256: str, root: str | Path | None = None) -> Path | None:
    """The cached file for this hash, rebuilt from the database if the disk copy is gone.

    Returns None when neither the disk nor the database has it (or the stored bytes do not
    match the hash), so the caller can ask for the file to be uploaded again.
    """
    folder = Path(root) if root is not None else UPLOADS_DIR
    path = folder / f"{sha256}.csv"
    if path.exists():
        return path
    content = _get_from_database(sha256)
    if content is None or hashlib.sha256(content).hexdigest() != sha256:
        return None
    folder.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def backfill_uploads(root: str | Path | None = None) -> tuple[int, int]:
    """Copy every <sha256>.csv in the uploads folder into the database.

    Returns (copied, skipped); a file is skipped when its name is not the SHA-256 of its bytes.
    """
    from pvdials.provenance import db

    folder = Path(root) if root is not None else UPLOADS_DIR
    copied = skipped = 0
    for path in sorted(folder.glob("*.csv")):
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != path.stem:
            skipped += 1
            continue

        def work(conn, sha=path.stem, content=content) -> None:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO uploaded_files (sha256, content) VALUES (%s, %s) "
                    "ON CONFLICT (sha256) DO NOTHING",
                    (sha, content),
                )

        db.run(work)
        copied += 1
    return copied, skipped
