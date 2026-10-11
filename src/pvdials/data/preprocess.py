"""Cleans a raw uploaded DataFrame into canonical, analysis-ready form.

Works ONLY from canonical field names (as resolved by column_mapper.py) —
never from source-specific column names like PVGIS's "Gb(n)" or "time(UTC)".
This is what keeps the physics/diagnostic layers source-agnostic.

Every change made to the data is kept as a RecordedStep, so it can be
written into provenance later (Step 7).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from pvdials.config import load_defaults
from pvdials.data.column_mapper import ColumnMapping


class PreprocessError(Exception):
    """Raised when the data can't be cleaned into a usable form."""


@dataclass(frozen=True)
class RecordedStep:
    """One change made to the uploaded data during preprocessing.

    provisional: open-item ID (e.g. "B3") if the rule is not yet settled.
    """

    name: str
    detail: str
    provisional: str | None = None


@dataclass
class PreprocessResult:
    df: pd.DataFrame
    steps: list[RecordedStep] = field(default_factory=list)


SUPPLIED_COMPONENT_FIELDS = ["dni", "dhi"]


def build_canonical_dataframe(
    raw_df: pd.DataFrame, mapping: ColumnMapping
) -> pd.DataFrame:
    """Extract and rename only the columns the mapper found, into canonical names.

    Rejects the file if any required field is missing.
    """
    if not mapping.found:
        raise PreprocessError("No recognized columns found in the uploaded file.")
    if mapping.missing:
        raise PreprocessError(
            "Required field(s) missing from the uploaded file: " + ", ".join(mapping.missing)
        )

    canonical_df = pd.DataFrame(
        {canonical: raw_df[source_col] for canonical, source_col in mapping.found.items()}
    )
    return canonical_df


def drop_supplied_components(
    df: pd.DataFrame, mapping: ColumnMapping, steps: list[RecordedStep]
) -> pd.DataFrame:
    """Drop supplied DNI/DHI. Stage 1 re-derives them from GHI; they are
    never used as a reference.
    """
    present = [f for f in SUPPLIED_COMPONENT_FIELDS if f in df.columns]
    if not present:
        return df

    sources = ", ".join(f"{mapping.found[f]} ({f})" for f in present)
    steps.append(
        RecordedStep(
            "drop_supplied_dni_dhi",
            f"Dropped supplied column(s) {sources}. Stage 1 re-derives DNI/DHI from GHI.",
        )
    )
    return df.drop(columns=present)


# Timestamp formats seen across common weather-data sources so far.
# Add to this list as new uploaded files reveal new conventions.
KNOWN_TIMESTAMP_FORMATS = [
    "%Y%m%d:%H%M",       # PVGIS style: 20200101:0000
    "%Y-%m-%d %H:%M",    # ISO-ish style: 2020-01-01 00:00
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y %H:%M",
]


def parse_timestamp(canonical_df: pd.DataFrame) -> pd.DataFrame:
    """Parse the timestamp column and set it as the datetime index.

    Tries each known format explicitly before falling back to pandas'
    general inference — some real-world formats (PVGIS's "20200101:0000")
    are ambiguous enough that automatic guessing silently fails.

    Does not sort: a TMY mixes years, so sorting by real date scrambles the
    months. Ordering is done by reindex_to_canonical_year().
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
    return df.set_index("timestamp")


def reindex_to_canonical_year(
    df: pd.DataFrame, canonical_year: int, steps: list[RecordedStep]
) -> pd.DataFrame:
    """Move every row onto one non-leap year by (month, day, hour, minute).

    TMY files mix months from different years, some leap. Raw day-of-year
    then collides or skips, which gives wrong solar declination. The
    original timestamp is kept in 'timestamp_original'.
    """
    if calendar.isleap(canonical_year):
        raise PreprocessError(f"Canonical year {canonical_year} is a leap year.")

    original = df.index
    if original.tz is not None:
        # Same instants, expressed in UTC, then made naive for the re-index
        original = original.tz_convert("UTC").tz_localize(None)
        steps.append(
            RecordedStep("convert_to_utc", "Timestamps carried a timezone; converted to UTC.")
        )

    feb29 = (original.month == 2) & (original.day == 29)
    if feb29.any():
        # Rule for 29 February is an open item — stop rather than guess
        raise PreprocessError(
            f"{feb29.sum()} row(s) fall on 29 February, which the canonical non-leap "
            f"year does not have. No rule is set for these rows yet."
        )

    canonical = pd.DatetimeIndex(
        [
            pd.Timestamp(canonical_year, t.month, t.day, t.hour, t.minute)
            for t in original
        ]
    )
    if canonical.duplicated().any():
        dupes = canonical[canonical.duplicated()]
        raise PreprocessError(
            f"{len(dupes)} row(s) share the same month, day and hour (first: "
            f"{dupes[0]:%d %b %H:%M}). The file may span more than one year."
        )

    out = df.copy()
    out.insert(0, "timestamp_original", original)
    out.index = canonical
    out.index.name = "timestamp"
    out = out.sort_index()

    years = sorted(set(original.year))
    steps.append(
        RecordedStep(
            "reindex_canonical_year",
            f"Re-indexed {len(out)} row(s) from source year(s) {years} onto non-leap "
            f"year {canonical_year} by (month, day, hour). Original timestamps kept "
            f"in 'timestamp_original'.",
        )
    )
    return out


def localise_to_utc(df: pd.DataFrame, steps: list[RecordedStep]) -> pd.DataFrame:
    """Tag the index as UTC. Timezone convention is still open (B3)."""
    out = df.copy()
    out.index = out.index.tz_localize("UTC")
    steps.append(
        RecordedStep("localise_utc", "Timestamps treated as UTC.", provisional="B3")
    )
    return out


def normalise_negative_zero(df: pd.DataFrame, steps: list[RecordedStep]) -> pd.DataFrame:
    """Replace -0.0 with +0.0 in every numeric column."""
    out = df.copy()
    counts = {}
    for col in out.select_dtypes(include="number").columns:
        negative_zero = (out[col] == 0) & np.signbit(out[col])
        if negative_zero.any():
            counts[col] = int(negative_zero.sum())
            out.loc[negative_zero, col] = 0.0

    if counts:
        detail = ", ".join(f"{col}: {n}" for col, n in counts.items())
        steps.append(RecordedStep("normalise_negative_zero", f"-0.0 set to +0.0 ({detail})."))
    return out


def clamp_negative_wind(df: pd.DataFrame, steps: list[RecordedStep]) -> pd.DataFrame:
    """Set negative wind speed to 0. Rule is still open (B3)."""
    if "wind_speed" not in df.columns:
        return df

    negative = df["wind_speed"] < 0
    if not negative.any():
        return df

    out = df.copy()
    where = out["timestamp_original"] if "timestamp_original" in out.columns else out.index
    old_values = out.loc[negative, "wind_speed"]
    changes = ", ".join(
        f"{t:%Y%m%d:%H%M} ({v})" for t, v in zip(where[negative.to_numpy()], old_values)
    )
    out.loc[negative, "wind_speed"] = 0.0
    steps.append(
        RecordedStep(
            "clamp_negative_wind",
            f"Negative wind speed set to 0 at {negative.sum()} row(s): {changes}.",
            provisional="B3",
        )
    )
    return out


def preprocess(
    raw_df: pd.DataFrame, mapping: ColumnMapping, canonical_year: int | None = None
) -> PreprocessResult:
    """Run every preprocessing step in order and return the recorded steps."""
    if canonical_year is None:
        canonical_year = load_defaults()["data"]["canonical_year"]

    steps: list[RecordedStep] = []
    df = build_canonical_dataframe(raw_df, mapping)
    df = drop_supplied_components(df, mapping, steps)
    df = parse_timestamp(df)
    df = reindex_to_canonical_year(df, canonical_year, steps)
    df = localise_to_utc(df, steps)
    df = normalise_negative_zero(df, steps)
    df = clamp_negative_wind(df, steps)
    return PreprocessResult(df=df, steps=steps)
