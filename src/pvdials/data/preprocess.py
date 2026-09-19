"""Cleans a raw uploaded DataFrame into canonical, analysis-ready form.

Works ONLY from canonical field names (as resolved by column_mapper.py) —
never from source-specific column names like PVGIS's "Gb(n)" or "time(UTC)".
This is what keeps the physics/diagnostic layers source-agnostic.
"""

from __future__ import annotations

import pandas as pd

from pvdials.data.column_mapper import ColumnMapping


class PreprocessError(Exception):
    """Raised when the data can't be cleaned into a usable form."""


def build_canonical_dataframe(
    raw_df: pd.DataFrame, mapping: ColumnMapping
) -> pd.DataFrame:
    """Extract and rename only the columns the mapper found, into canonical names.

    Only includes fields present in mapping.found — missing required fields
    must be supplied separately by the user before this can be considered
    complete (see validate.py).
    """
    if not mapping.found:
        raise PreprocessError("No recognized columns found in the uploaded file.")

    canonical_df = pd.DataFrame(
        {canonical: raw_df[source_col] for canonical, source_col in mapping.found.items()}
    )
    return canonical_df


# Timestamp formats seen across common weather-data sources so far.
# Add to this list as new uploaded files reveal new conventions.
KNOWN_TIMESTAMP_FORMATS = [
    "%Y%m%d:%H%M",       # PVGIS style: 20200101:0000
    "%Y-%m-%d %H:%M",    # ISO-ish style: 2020-01-01 00:00
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y %H:%M",
]


def parse_timestamp(canonical_df: pd.DataFrame) -> pd.DataFrame:
    """Parse the timestamp column and set it as a tz-naive datetime index.

    Tries each known format explicitly before falling back to pandas'
    general inference — some real-world formats (PVGIS's "20200101:0000")
    are ambiguous enough that automatic guessing silently fails.

    Timezone handling is deliberately left open here — B3 (decisions.md)
    is still unresolved on which timezone convention to apply. This just
    gets the index into a usable datetime form; tz-awareness comes later.
    """
    if "timestamp" not in canonical_df.columns:
        raise PreprocessError("No timestamp column available — cannot proceed.")

    df = canonical_df.copy()
    raw = df["timestamp"]

    parsed = None
    for fmt in KNOWN_TIMESTAMP_FORMATS:
        attempt = pd.to_datetime(raw, format=fmt, errors="coerce")
        if attempt.notna().all():
            parsed = attempt
            break

    if parsed is None:
        # No known format matched every row — fall back to general inference
        parsed = pd.to_datetime(raw, errors="coerce")

    if parsed.isna().any():
        bad_count = parsed.isna().sum()
        raise PreprocessError(
            f"{bad_count} row(s) have a timestamp that could not be parsed."
        )

    df["timestamp"] = parsed
    df = df.set_index("timestamp").sort_index()
    return df