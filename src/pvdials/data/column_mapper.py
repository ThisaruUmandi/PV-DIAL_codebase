"""Maps whatever columns an uploaded CSV happens to have onto PV-DIAL's
canonical field names, so every later layer (preprocess, physics, etc.)
only ever deals with canonical names — never raw, source-specific headers.

Each canonical field lists known aliases seen across common weather-data
sources (PVGIS, NASA POWER, generic exports). This list grows over time
as new uploaded files reveal new naming conventions — it is not exhaustive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

# canonical field -> known column-name variants (case-insensitive match)
KNOWN_ALIASES: dict[str, list[str]] = {
    "timestamp": ["time", "datetime", "time(utc)", "date", "timestamp"],
    "ghi": ["ghi", "g(h)", "global horizontal irradiance"],
    "temp_air": ["t2m", "temp_air", "temperature", "air temperature"],
    "wind_speed": ["ws10m", "wind_speed", "wind speed"],
    # Optional fields. RH is range-checked if present. Supplied DNI/DHI are
    # detected only so preprocessing can drop them as a recorded step.
    "rh": ["rh", "rh2m", "relative_humidity", "relative humidity"],
    "dni": ["gb(n)", "dni"],
    "dhi": ["gd(h)", "dhi"],
    # Surface pressure in Pa, for solar-position refraction (Step 3)
    "pressure": ["sp", "surface_pressure", "surface pressure", "pressure"],
}

REQUIRED_FIELDS = ["timestamp", "ghi", "temp_air", "wind_speed"]

# Site fields: read from the file if present, otherwise entered by the user.
SITE_ALIASES: dict[str, list[str]] = {
    "latitude": ["latitude", "lat"],
    "longitude": ["longitude", "lon", "lng"],
    "elevation": ["elevation", "elev", "altitude"],
}

FROM_CSV = "From CSV"
USER_ENTERED = "User entered"

# Provenance tags for values that feed solar position (Step 3 decisions, 23/09)
TAG_FILE = "file"
TAG_USER_ENTERED = "user_entered"
TAG_ASSUMED_ABSENT = "assumed_absent_from_header"

TIME_OFFSET_ALIASES = ["irradiance time offset", "time offset"]

NO_OFFSET_NOTICE = (
    "No irradiance time offset was found in the file header. Solar position is "
    "computed at the file's own timestamps (offset 0 h). If the dataset's "
    "documentation states an offset, enter it here."
)


@dataclass
class ColumnMapping:
    """Result of inspecting an uploaded CSV's columns.

    found: canonical field -> the actual column name matched in the CSV
    missing: canonical fields with no confident match — user must supply
    """

    found: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)

    def is_complete(self) -> bool:
        return not self.missing


def detect_columns(df: pd.DataFrame) -> ColumnMapping:
    """Inspect df's columns and match them to canonical fields."""
    lower_columns = {col.lower().strip(): col for col in df.columns}

    mapping = ColumnMapping()
    for canonical, aliases in KNOWN_ALIASES.items():
        matched_column = None
        for alias in aliases:
            if alias in lower_columns:
                matched_column = lower_columns[alias]
                break
        if matched_column is not None:
            mapping.found[canonical] = matched_column
        elif canonical in REQUIRED_FIELDS:
            mapping.missing.append(canonical)

    return mapping

@dataclass
class SiteMetadata:
    """Latitude, longitude and elevation, each tagged with where it came from.

    values: site field -> value
    sources: site field -> FROM_CSV or USER_ENTERED
    missing: site fields the user must enter
    """

    values: dict[str, float] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)

    def set_user_value(self, site_field: str, value: float) -> None:
        if site_field not in SITE_ALIASES:
            raise ValueError(f"Unknown site field: {site_field}")
        self.values[site_field] = float(value)
        self.sources[site_field] = USER_ENTERED
        if site_field in self.missing:
            self.missing.remove(site_field)

    def is_complete(self) -> bool:
        return not self.missing


def _normalise_key(text: str) -> str:
    """'Latitude (decimal degrees)' -> 'latitude'."""
    return re.sub(r"\(.*?\)", "", text).strip().lower()


def _from_preamble(preamble: list[str], aliases: list[str]) -> float | None:
    """Value from a 'key: value' line whose key matches an alias."""
    for line in preamble:
        key, sep, value = line.partition(":")
        if sep and _normalise_key(key) in aliases:
            try:
                return float(value.strip())
            except ValueError:
                return None
    return None


def _from_columns(df: pd.DataFrame, aliases: list[str]) -> float | None:
    """Value from a matching column, only if it holds one constant value."""
    for col in df.columns:
        if _normalise_key(str(col)) in aliases:
            unique = df[col].dropna().unique()
            if len(unique) == 1:
                try:
                    return float(unique[0])
                except (TypeError, ValueError):
                    return None
    return None


def detect_site_metadata(preamble: list[str], df: pd.DataFrame) -> SiteMetadata:
    """Find latitude, longitude and elevation in the uploaded file.

    Looks in the preamble lines first, then in data columns. Anything not
    found is listed in `missing` for the user to enter. No site is hard-coded.
    """
    site = SiteMetadata()
    for site_field, aliases in SITE_ALIASES.items():
        value = _from_preamble(preamble, aliases)
        if value is None:
            value = _from_columns(df, aliases)
        if value is None:
            site.missing.append(site_field)
        else:
            site.values[site_field] = value
            site.sources[site_field] = FROM_CSV
    return site


@dataclass
class TimeOffset:
    """Offset (hours) from each timestamp to the time its irradiance value represents.

    PVGIS states it in the header ("Irradiance Time Offset (h): 0.5").
    source: TAG_FILE, TAG_ASSUMED_ABSENT or TAG_USER_ENTERED
    notice: text shown to the user when the offset was assumed, else None
    """

    value_h: float
    source: str
    notice: str | None = None

    def set_user_value(self, value_h: float) -> None:
        self.value_h = float(value_h)
        self.source = TAG_USER_ENTERED
        self.notice = None


def detect_time_offset(preamble: list[str]) -> TimeOffset:
    """Read the irradiance time offset from the preamble.

    If the header doesn't state one, 0 h is assumed — recorded as an
    assumption, with a notice for the user, who may override it.
    """
    value = _from_preamble(preamble, TIME_OFFSET_ALIASES)
    if value is None:
        return TimeOffset(0.0, TAG_ASSUMED_ABSENT, NO_OFFSET_NOTICE)
    return TimeOffset(value, TAG_FILE)
