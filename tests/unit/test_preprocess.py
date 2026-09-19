from pathlib import Path

import pandas as pd
import pytest

from pvdials.data.column_mapper import detect_columns
from pvdials.data.preprocess import (
    PreprocessError,
    build_canonical_dataframe,
    parse_timestamp,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_builds_canonical_dataframe_from_complete_file():
    raw_df = pd.read_csv(FIXTURES / "sample_weather_complete.csv")
    mapping = detect_columns(raw_df)

    canonical_df = build_canonical_dataframe(raw_df, mapping)

    assert list(canonical_df.columns) == ["timestamp", "ghi", "temp_air", "wind_speed"]
    assert len(canonical_df) == 3


def test_parses_pvgis_style_timestamp():
    raw_df = pd.read_csv(FIXTURES / "sample_weather_complete.csv")
    mapping = detect_columns(raw_df)
    canonical_df = build_canonical_dataframe(raw_df, mapping)

    result = parse_timestamp(canonical_df)

    assert isinstance(result.index, pd.DatetimeIndex)
    assert result.index.is_monotonic_increasing
    assert result.index[0].year == 2020


def test_parses_iso_style_timestamp_too():
    raw_df = pd.read_csv(FIXTURES / "sample_weather_incomplete.csv")
    mapping = detect_columns(raw_df)
    canonical_df = build_canonical_dataframe(raw_df, mapping)

    result = parse_timestamp(canonical_df)

    assert isinstance(result.index, pd.DatetimeIndex)


def test_raises_when_no_columns_recognized():
    empty_df = pd.DataFrame({"totally_unknown_column": [1, 2, 3]})
    from pvdials.data.column_mapper import ColumnMapping

    empty_mapping = ColumnMapping(found={}, missing=["timestamp", "ghi", "temp_air", "wind_speed"])

    with pytest.raises(PreprocessError):
        build_canonical_dataframe(empty_df, empty_mapping)