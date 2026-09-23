"""Sanity checks on cleaned, canonical weather data.

Source-agnostic: works for any uploaded file, not just a fixed 8,760-row
PVGIS TMY. Checks that make sense only for a full year of hourly data are
applied conditionally, based on what was actually uploaded.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# Plausible surface pressure range in Pa (sea level ~101,325; ~5,000 m ~54,000)
PRESSURE_MIN_PA = 30_000
PRESSURE_MAX_PA = 110_000

# True zenith at or above this means the sun is below the horizon
HORIZON_ZENITH_DEG = 90.0


@dataclass
class ValidationResult:
    """problems fail the check; warnings and notes never do.

    notes: informational only (e.g. known sampling artefacts), never findings
    counts: named counts recorded for provenance
    """

    passed: bool = True
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def add_problem(self, message: str) -> None:
        self.passed = False
        self.problems.append(message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def add_note(self, message: str) -> None:
        self.notes.append(message)

    def merge(self, other: ValidationResult) -> None:
        self.passed = self.passed and other.passed
        self.problems.extend(other.problems)
        self.warnings.extend(other.warnings)
        self.notes.extend(other.notes)
        self.counts.update(other.counts)


def validate_structure(df: pd.DataFrame) -> ValidationResult:
    """Tier 1: basic structural sanity — no missing values, no duplicate
    timestamps, and regular hourly steps (no gaps). Any length is allowed.
    """
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

    steps = df.index.to_series().diff().dropna()
    irregular = steps[steps != pd.Timedelta(hours=1)]
    if not irregular.empty:
        result.add_problem(
            f"{len(irregular)} gap(s) or irregular step(s) in the hourly series "
            f"(first at {irregular.index[0]:%d %b %H:%M})."
        )

    return result


def validate_physical_ranges(df: pd.DataFrame) -> ValidationResult:
    """Tier 2: physically plausible ranges for each field present."""
    result = ValidationResult()

    if "ghi" in df.columns:
        if (df["ghi"] < 0).any():
            result.add_problem("GHI has negative value(s) — physically impossible.")
        if (df["ghi"] > 1400).any():
            result.add_warning("GHI exceeds 1400 W/m² on some row(s) — check for outliers.")

    # Backstop: preprocessing clamps negative wind speed, so none should remain
    if "wind_speed" in df.columns and (df["wind_speed"] < 0).any():
        result.add_problem("Wind speed has negative value(s) — physically impossible.")

    if "rh" in df.columns and ((df["rh"] < 0) | (df["rh"] > 100)).any():
        result.add_problem("Relative humidity outside 0–100 % on some row(s).")

    # Surface pressure must be in Pa. hPa (~1000) or kPa (~100) values fall outside.
    if "pressure" in df.columns and (
        (df["pressure"] < PRESSURE_MIN_PA) | (df["pressure"] > PRESSURE_MAX_PA)
    ).any():
        result.add_problem(
            f"Surface pressure outside {PRESSURE_MIN_PA:,}–{PRESSURE_MAX_PA:,} Pa on some "
            f"row(s). Pressure must be in Pa."
        )

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
        combined.merge(check(df))

    return combined


def validate_physical_consistency(
    df: pd.DataFrame,
    zenith_mid: pd.Series,
    zenith_start: pd.Series,
    zenith_end: pd.Series,
) -> ValidationResult:
    """Tier 4: GHI > 0 while the sun is below the horizon at the hour's midpoint.

    Uses true zenith from the shared SiteContext (Step 3). A flagged row is a
    sampling artefact if the sun is above the horizon at the hour's start or
    end: midpoint sampling misses a partial hour of sun at sunrise/sunset.
    Artefacts are counted in a note only. Any other flagged row is a warning.
    Nothing here fails the file — the tiers check the input is sound and
    complete, not accurate.
    """
    for series in (zenith_mid, zenith_start, zenith_end):
        if not series.index.equals(df.index):
            raise ValueError("Zenith series must share the weather table's index.")

    result = ValidationResult()

    flagged = (df["ghi"] > 0) & (zenith_mid >= HORIZON_ZENITH_DEG)
    sun_up_at_boundary = (zenith_start < HORIZON_ZENITH_DEG) | (zenith_end < HORIZON_ZENITH_DEG)
    artefact = flagged & sun_up_at_boundary
    unexplained = flagged & ~sun_up_at_boundary

    result.counts["tier4_sampling_artefacts"] = int(artefact.sum())
    result.counts["tier4_unexplained"] = int(unexplained.sum())

    if artefact.any():
        result.add_note(
            f"{int(artefact.sum())} sunrise/sunset hour(s) have GHI > 0 while the sun is "
            f"below the horizon at the hour's midpoint but above it at the hour's start "
            f"or end. This comes from midpoint sampling, not from the data."
        )
    if unexplained.any():
        first = df.index[unexplained.to_numpy()][0]
        result.add_warning(
            f"{int(unexplained.sum())} hour(s) have GHI > 0 while the sun is below the "
            f"horizon at the hour's start, midpoint and end (first at {first:%d %b %H:%M})."
        )

    return result


def validate_post_decomposition(outputs: pd.DataFrame) -> ValidationResult:
    """Tier 6: Stage 1 DNI and DHI are finite and >= 0 on every row.

    The Stage 1 adapters already set out-of-guard NaN to 0 and clip negative
    DHI, so a failure here points to a fault in the adapter, not the data.
    """
    result = ValidationResult()
    for col in ("dni", "dhi"):
        values = outputs[col].to_numpy(dtype=float)
        n_nonfinite = int((~np.isfinite(values)).sum())
        n_negative = int((values < 0).sum())
        if n_nonfinite:
            result.add_problem(f"Stage 1 {col.upper()} has {n_nonfinite} non-finite value(s).")
        if n_negative:
            result.add_problem(f"Stage 1 {col.upper()} has {n_negative} negative value(s).")
    return result


def validate_post_transposition(outputs: pd.DataFrame) -> ValidationResult:
    """Structural sanity check on Stage 2 output: poa_global finite and >= 0.

    Not one of the KT's six named tiers — a basic engineering guard, the
    same shape as the AC <= DC invariant, catching an adapter fault rather
    than describing the input.
    """
    result = ValidationResult()
    values = outputs["poa_global"].to_numpy(dtype=float)
    n_nonfinite = int((~np.isfinite(values)).sum())
    n_negative = int((values < 0).sum())
    if n_nonfinite:
        result.add_problem(f"POA global has {n_nonfinite} non-finite value(s).")
    if n_negative:
        result.add_problem(f"POA global has {n_negative} negative value(s).")
    return result


def validate_post_temperature(outputs: pd.DataFrame, weather: pd.DataFrame) -> ValidationResult:
    """Structural sanity check on Stage 3 output: temp_cell finite, and never
    far below air temperature. Not one of the KT's six named tiers — catches
    an adapter fault (a sign or unit slip), not a claim about how the model
    performs.
    """
    result = ValidationResult()
    temp_cell = outputs["temp_cell"].to_numpy(dtype=float)
    temp_air = weather["temp_air"].to_numpy(dtype=float)

    n_nonfinite = int((~np.isfinite(temp_cell)).sum())
    if n_nonfinite:
        result.add_problem(f"Cell temperature has {n_nonfinite} non-finite value(s).")

    n_too_cold = int((temp_cell < temp_air - 5.0).sum())
    if n_too_cold:
        result.add_problem(
            f"Cell temperature is more than 5 C below air temperature on {n_too_cold} row(s)."
        )
    return result


def validate_post_dc(outputs: pd.DataFrame) -> ValidationResult:
    """Structural sanity check on Stage 4 output: p_dc finite and >= 0.

    Not one of the KT's six named tiers. The AC <= DC regression test is
    Stage 5's job (N21).
    """
    result = ValidationResult()
    values = outputs["p_dc"].to_numpy(dtype=float)
    n_nonfinite = int((~np.isfinite(values)).sum())
    n_negative = int((values < 0).sum())
    if n_nonfinite:
        result.add_problem(f"DC power has {n_nonfinite} non-finite value(s).")
    if n_negative:
        result.add_problem(f"DC power has {n_negative} negative value(s).")
    return result
