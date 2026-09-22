from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pvdials.data.column_mapper import ColumnMapping, detect_columns
from pvdials.data.preprocess import (
    PreprocessError,
    build_canonical_dataframe,
    parse_timestamp,
    preprocess,
)
from pvdials.data.upload import load_uploaded_csv

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
YEAR = 2023  # passed explicitly so tests don't depend on run_defaults.yaml


def _run(filename: str):
    uploaded = load_uploaded_csv(FIXTURES / filename)
    return preprocess(uploaded.table, detect_columns(uploaded.table), canonical_year=YEAR)


def _step(result, name):
    matches = [s for s in result.steps if s.name == name]
    assert len(matches) == 1, f"expected one '{name}' step, got {len(matches)}"
    return matches[0]


def test_builds_canonical_dataframe_from_complete_file():
    raw_df = pd.read_csv(FIXTURES / "sample_weather_complete.csv")
    mapping = detect_columns(raw_df)

    canonical_df = build_canonical_dataframe(raw_df, mapping)

    assert list(canonical_df.columns) == ["timestamp", "ghi", "temp_air", "wind_speed"]
    assert len(canonical_df) == 3


def test_parses_pvgis_style_timestamp():
    raw_df = pd.read_csv(FIXTURES / "sample_weather_complete.csv")
    canonical_df = build_canonical_dataframe(raw_df, detect_columns(raw_df))

    result = parse_timestamp(canonical_df)

    assert isinstance(result.index, pd.DatetimeIndex)
    assert result.index[0] == pd.Timestamp("2020-01-01 00:00")


def test_parses_iso_style_timestamp_too():
    df = pd.DataFrame({"timestamp": ["2020-01-01 00:00", "2020-01-01 01:00"]})

    result = parse_timestamp(df)

    assert isinstance(result.index, pd.DatetimeIndex)


def test_raises_when_no_columns_recognized():
    empty_df = pd.DataFrame({"totally_unknown_column": [1, 2, 3]})
    empty_mapping = ColumnMapping(found={}, missing=["timestamp", "ghi", "temp_air", "wind_speed"])

    with pytest.raises(PreprocessError):
        build_canonical_dataframe(empty_df, empty_mapping)


def test_rejects_file_missing_a_required_field():
    raw_df = pd.read_csv(FIXTURES / "sample_weather_incomplete.csv")  # no wind speed

    with pytest.raises(PreprocessError, match="wind_speed"):
        build_canonical_dataframe(raw_df, detect_columns(raw_df))


def test_supplied_dni_dhi_dropped_and_recorded():
    result = _run("sample_pvgis_tmy.csv")

    assert "dni" not in result.df.columns
    assert "dhi" not in result.df.columns
    detail = _step(result, "drop_supplied_dni_dhi").detail
    assert "Gb(n)" in detail and "Gd(h)" in detail


def test_months_in_calendar_order_after_reindex():
    # Fixture rows: Feb 2019 then Mar 2008. Sorting by real date would put March first.
    result = _run("sample_pvgis_tmy.csv")

    assert list(result.df.index.month) == [2, 2, 3, 3]
    assert set(result.df.index.year) == {YEAR}
    assert list(result.df.index.dayofyear) == [59, 59, 60, 60]
    assert result.df["timestamp_original"].iloc[2] == pd.Timestamp("2008-03-01 00:00")
    _step(result, "reindex_canonical_year")


def test_index_is_utc_and_marked_provisional():
    result = _run("sample_pvgis_tmy.csv")

    assert str(result.df.index.tz) == "UTC"
    assert _step(result, "localise_utc").provisional == "B3"


def test_negative_zero_normalised_and_recorded():
    result = _run("sample_pvgis_tmy.csv")

    assert not np.signbit(result.df["ghi"]).any()
    assert "ghi: 1" in _step(result, "normalise_negative_zero").detail


def test_negative_wind_clamped_and_recorded():
    result = _run("sample_pvgis_tmy.csv")

    assert (result.df["wind_speed"] >= 0).all()
    step = _step(result, "clamp_negative_wind")
    assert "20080301:0000 (-0.22)" in step.detail
    assert step.provisional == "B3"


def test_duplicate_month_day_hour_is_rejected():
    df = pd.DataFrame(
        {
            "timestamp": ["20190101:0000", "20200101:0000"],
            "ghi": [0.0, 0.0],
            "temp_air": [25.0, 25.0],
            "wind_speed": [1.0, 1.0],
        }
    )

    with pytest.raises(PreprocessError, match="same month, day and hour"):
        preprocess(df, detect_columns(df), canonical_year=YEAR)


def test_29_february_is_rejected():
    df = pd.DataFrame(
        {"timestamp": ["20200229:1200"], "ghi": [500.0], "temp_air": [30.0], "wind_speed": [1.0]}
    )

    with pytest.raises(PreprocessError, match="29 February"):
        preprocess(df, detect_columns(df), canonical_year=YEAR)


def test_leap_canonical_year_is_rejected():
    with pytest.raises(PreprocessError, match="leap year"):
        preprocess(
            pd.read_csv(FIXTURES / "sample_weather_complete.csv"),
            detect_columns(pd.read_csv(FIXTURES / "sample_weather_complete.csv")),
            canonical_year=2024,
        )
