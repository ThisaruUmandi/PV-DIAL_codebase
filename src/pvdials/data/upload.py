"""Accepts a user-uploaded weather CSV and loads it as a raw DataFrame.

Many weather exports (e.g. PVGIS) wrap the data table in metadata: a
preamble above the header row and notes below the table. This module
finds the table, reads it unmodified, and keeps the preamble lines as
plain text. Column mapping to canonical fields happens in column_mapper.py.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from pvdials.data.column_mapper import KNOWN_ALIASES


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
