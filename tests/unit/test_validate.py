from pathlib import Path

import pandas as pd

from pvdials.data.column_mapper import detect_columns
from pvdials.data.preprocess import preprocess
from pvdials.data.upload import load_uploaded_csv
from pvdials.data.validate import run_all_validations

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
