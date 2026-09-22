"""Sanity checks on cleaned, canonical weather data.

Source-agnostic: works for any uploaded file, not just a fixed 8,760-row
PVGIS TMY. Checks that make sense only for a full year of hourly data are
applied conditionally, based on what was actually uploaded.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class ValidationResult:
    passed: bool = True
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_problem(self, message: str) -> None:
        self.passed = False
        self.problems.append(message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)


def validate_structure(df: pd.DataFrame) -> ValidationResult:
    """Tier 1: basic structural sanity — no missing values, no duplicate timestamps."""
    result = ValidationResult()

    if df.empty:
        result.add_problem("Dataset has no rows.")
        return result

    if df.index.duplicated().any():
        dupes = df.index.duplicated().sum()
        result.add_problem(f"{dupes} duplicate timestamp(s) found.")

    for col in df.columns:
        n_missing = df[col].isna().sum()
        if n_missing > 0:
            result.add_problem(f"Column '{col}' has {n_missing} missing value(s).")

    return result


def validate_physical_ranges(df: pd.DataFrame) -> ValidationResult:
    """Tier 2: physically plausible ranges for each field present."""
    result = ValidationResult()

    if "ghi" in df.columns:
        if (df["ghi"] < 0).any():
            result.add_problem("GHI has negative value(s) — physically impossible.")
        if (df["ghi"] > 1400).any():
            result.add_warning("GHI exceeds 1400 W/m² on some row(s) — check for outliers.")

    if "wind_speed" in df.columns:
        if (df["wind_speed"] < 0).any():
            result.add_problem("Wind speed has negative value(s) — physically impossible.")

    return result


def validate_full_year_if_applicable(df: pd.DataFrame) -> ValidationResult:
    """Tier 3 (conditional): only checked if the file looks like a full year
    of hourly data. A shorter upload is valid — this just reports which
    regime it's in, rather than forcing every upload to be a full year.
    """
    result = ValidationResult()

    if len(df) == 8760:
        distinct_days = df.index.normalize().nunique()
        if distinct_days != 365:
            result.add_warning(
                f"8,760 rows found, but only {distinct_days} distinct calendar "
                f"days — check for duplicated or missing days."
            )
    else:
        result.add_warning(
            f"{len(df)} row(s) uploaded — not a full year of hourly data "
            f"(8,760 rows). Proceeding with the data as given."
        )

    return result


def run_all_validations(df: pd.DataFrame) -> ValidationResult:
    """Run every check and merge results into one."""
    combined = ValidationResult()

    for check in (validate_structure, validate_physical_ranges, validate_full_year_if_applicable):
        r = check(df)
        combined.passed = combined.passed and r.passed
        combined.problems.extend(r.problems)
        combined.warnings.extend(r.warnings)

    return combined