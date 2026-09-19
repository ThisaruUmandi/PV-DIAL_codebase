from pathlib import Path

import pandas as pd

from pvdials.data.column_mapper import detect_columns

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_detects_pvgis_style_columns():
    df = pd.read_csv(FIXTURES / "sample_weather_complete.csv")
    mapping = detect_columns(df)

    assert mapping.found["timestamp"] == "time(UTC)"
    assert mapping.found["ghi"] == "G(h)"
    assert mapping.found["temp_air"] == "T2m"
    assert mapping.found["wind_speed"] == "WS10m"
    assert mapping.is_complete()


def test_detects_missing_field():
    df = pd.read_csv(FIXTURES / "sample_weather_incomplete.csv")
    mapping = detect_columns(df)

    assert mapping.found["timestamp"] == "Date"
    assert mapping.found["ghi"] == "GHI"
    assert mapping.found["temp_air"] == "Temperature"
    assert "wind_speed" in mapping.missing
    assert not mapping.is_complete()