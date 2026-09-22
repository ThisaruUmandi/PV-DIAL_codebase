from pathlib import Path

import pandas as pd

from pvdials.data.column_mapper import detect_columns
from pvdials.data.preprocess import build_canonical_dataframe, parse_timestamp
from pvdials.data.validate import run_all_validations

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _load_clean(filename: str) -> pd.DataFrame:
    raw_df = pd.read_csv(FIXTURES / filename)
    mapping = detect_columns(raw_df)
    canonical_df = build_canonical_dataframe(raw_df, mapping)
    return parse_timestamp(canonical_df)


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