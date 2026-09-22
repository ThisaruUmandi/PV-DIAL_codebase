"""Maps whatever columns an uploaded CSV happens to have onto PV-DIAL's
canonical field names, so every later layer (preprocess, physics, etc.)
only ever deals with canonical names — never raw, source-specific headers.

Each canonical field lists known aliases seen across common weather-data
sources (PVGIS, NASA POWER, generic exports). This list grows over time
as new uploaded files reveal new naming conventions — it is not exhaustive.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

# canonical field -> known column-name variants (case-insensitive match)
KNOWN_ALIASES: dict[str, list[str]] = {
    "timestamp": ["time", "datetime", "time(utc)", "date", "timestamp"],
    "ghi": ["ghi", "g(h)", "global horizontal irradiance"],
    "temp_air": ["t2m", "temp_air", "temperature", "air temperature"],
    "wind_speed": ["ws10m", "wind_speed", "wind speed"],
}

REQUIRED_FIELDS = ["timestamp", "ghi", "temp_air", "wind_speed"]


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