from pathlib import Path

import pandas as pd
import pytest

from pvdials.data.column_mapper import detect_columns
from pvdials.data.preprocess import preprocess
from pvdials.data.upload import load_uploaded_csv
from pvdials.data.validate import run_all_validations, validate_physical_consistency

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _load_clean(filename: str) -> pd.DataFrame:
    uploaded = load_uploaded_csv(FIXTURES / filename)
    return preprocess(uploaded.table, detect_columns(uploaded.table), canonical_year=2023).df


def test_clean_sample_passes_structural_and_range_checks():
    df = _load_clean("sample_weather_complete.csv")
    result = run_all_validations(df)

    assert result.passed
    assert not result.problems


def test_short_file_warns_but_does_not_fail():
    df = _load_clean("sample_weather_complete.csv")  # only 3 rows
    result = run_all_validations(df)

    assert result.passed  # short files are valid, just noted
    assert any("not a full year" in w for w in result.warnings)


def test_negative_ghi_is_caught():
    df = _load_clean("sample_weather_complete.csv")
    df.loc[df.index[0], "ghi"] = -50

    result = run_all_validations(df)

    assert not result.passed
    assert any("GHI has negative" in p for p in result.problems)


def test_negative_wind_speed_is_caught():
    # Backstop only: preprocessing clamps negative wind, so inject one afterwards
    df = _load_clean("sample_weather_complete.csv")
    df.loc[df.index[0], "wind_speed"] = -0.22  # the exact known bad value from decisions.md

    result = run_all_validations(df)

    assert not result.passed
    assert any("Wind speed has negative" in p for p in result.problems)


def test_duplicate_timestamp_is_caught():
    df = _load_clean("sample_weather_complete.csv")
    df_with_dupe = pd.concat([df, df.iloc[[0]]])

    result = run_all_validations(df_with_dupe)

    assert not result.passed
    assert any("duplicate timestamp" in p for p in result.problems)

def test_pvgis_fixture_passes_after_preprocessing():
    df = _load_clean("sample_pvgis_tmy.csv")
    result = run_all_validations(df)

    assert result.passed, result.problems


def test_gap_in_hourly_series_is_caught():
    df = _load_clean("sample_weather_complete.csv")
    df_with_gap = df.drop(df.index[1])

    result = run_all_validations(df_with_gap)

    assert not result.passed
    assert any("gap" in p for p in result.problems)


def test_rh_out_of_range_is_caught():
    df = _load_clean("sample_pvgis_tmy.csv")
    df.loc[df.index[0], "rh"] = 104.0

    result = run_all_validations(df)

    assert not result.passed
    assert any("Relative humidity" in p for p in result.problems)


def test_pressure_in_hpa_is_caught():
    df = _load_clean("sample_pvgis_tmy.csv")
    df["pressure"] = df["pressure"] / 100  # hPa, not Pa

    result = run_all_validations(df)

    assert not result.passed
    assert any("Pressure must be in Pa" in p for p in result.problems)


def _tier4_case():
    """Four hours: sunrise artefact, night fault, daytime, clean night."""
    idx = pd.date_range("2023-03-21 00:00", periods=4, freq="h", tz="UTC")
    df = pd.DataFrame({"ghi": [5.0, 10.0, 400.0, 0.0]}, index=idx)
    mid = pd.Series([91.0, 150.0, 40.0, 150.0], index=idx)
    start = pd.Series([95.0, 151.0, 45.0, 151.0], index=idx)
    end = pd.Series([87.0, 149.0, 35.0, 149.0], index=idx)
    return df, mid, start, end


def test_tier4_sunrise_hour_is_a_sampling_artefact_note():
    result = validate_physical_consistency(*_tier4_case())

    assert result.counts["tier4_sampling_artefacts"] == 1
    assert len(result.notes) == 1
    assert "midpoint sampling" in result.notes[0]


def test_tier4_night_ghi_is_an_unexplained_warning():
    result = validate_physical_consistency(*_tier4_case())

    assert result.counts["tier4_unexplained"] == 1
    assert len(result.warnings) == 1
    assert "21 Mar 01:00" in result.warnings[0]


def test_tier4_never_fails_the_file():
    result = validate_physical_consistency(*_tier4_case())

    assert result.passed
    assert not result.problems


def test_tier4_clean_data_gives_zero_counts():
    df, mid, start, end = _tier4_case()
    df["ghi"] = [0.0, 0.0, 400.0, 0.0]

    result = validate_physical_consistency(df, mid, start, end)

    assert result.counts == {"tier4_sampling_artefacts": 0, "tier4_unexplained": 0}
    assert not result.notes and not result.warnings


def test_tier4_rejects_mismatched_index():
    df, mid, start, end = _tier4_case()

    with pytest.raises(ValueError, match="index"):
        validate_physical_consistency(df, mid.iloc[:3], start, end)
