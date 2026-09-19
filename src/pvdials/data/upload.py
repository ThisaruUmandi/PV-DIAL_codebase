"""Accepts a user-uploaded weather CSV and loads it as a raw DataFrame.

Deliberately does no interpretation here — column detection and mapping
to canonical fields happens in column_mapper.py. This module's only job
is: take a file, return a DataFrame, fail clearly if it can't be read.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


class UploadError(Exception):
    """Raised when an uploaded file can't be read as a CSV at all."""


def load_uploaded_csv(file_path: str | Path) -> pd.DataFrame:
    """Read an uploaded CSV file into a raw, unmodified DataFrame.

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
        df = pd.read_csv(path)
    except Exception as exc:
        raise UploadError(f"Could not read '{path.name}' as a CSV: {exc}") from exc

    if df.empty:
        raise UploadError(f"'{path.name}' was read successfully but contains no rows.")

    return df