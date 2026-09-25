from pathlib import Path

import pandas as pd

from pvdials.data.column_mapper import (
    FROM_CSV,
    PRESET_HOUR_CENTRE_H,
    PRESET_HOUR_START_H,
    TAG_ASSUMED_ABSENT,
    TAG_FILE,
    TAG_USER_ENTERED,
    USER_ENTERED,
    detect_columns,
    detect_site_metadata,
    detect_time_offset,
)
from pvdials.data.upload import load_uploaded_csv

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

def test_detects_optional_rh_and_supplied_dni_dhi():
    uploaded = load_uploaded_csv(FIXTURES / "sample_pvgis_tmy.csv")
    mapping = detect_columns(uploaded.table)

    assert mapping.found["rh"] == "RH"
    assert mapping.found["dni"] == "Gb(n)"
    assert mapping.found["dhi"] == "Gd(h)"
    assert mapping.found["pressure"] == "SP"
    assert mapping.is_complete()


def test_site_metadata_read_from_preamble():
    uploaded = load_uploaded_csv(FIXTURES / "sample_pvgis_tmy.csv")
    site = detect_site_metadata(uploaded.preamble, uploaded.table)

    assert site.values == {"latitude": 6.944, "longitude": 79.856, "elevation": 16.0}
    assert set(site.sources.values()) == {FROM_CSV}
    assert site.is_complete()


def test_site_metadata_read_from_constant_columns():
    df = pd.DataFrame({"time": ["a", "b"], "Lat": [7.1, 7.1], "Lon": [80.0, 80.0]})
    site = detect_site_metadata([], df)

    assert site.values == {"latitude": 7.1, "longitude": 80.0}
    assert site.missing == ["elevation"]


def test_site_metadata_missing_when_not_in_file():
    df = pd.read_csv(FIXTURES / "sample_weather_complete.csv")
    site = detect_site_metadata([], df)

    assert site.missing == ["latitude", "longitude", "elevation"]
    assert not site.is_complete()


def test_user_entered_value_is_tagged():
    df = pd.read_csv(FIXTURES / "sample_weather_complete.csv")
    site = detect_site_metadata([], df)

    site.set_user_value("latitude", 6.026)

    assert site.values["latitude"] == 6.026
    assert site.sources["latitude"] == USER_ENTERED
    assert "latitude" not in site.missing


def test_time_offset_read_from_pvgis_header():
    uploaded = load_uploaded_csv(FIXTURES / "sample_pvgis_tmy.csv")
    offset = detect_time_offset(uploaded.preamble)

    assert offset.value_h == 0.5
    assert offset.source == TAG_FILE
    assert offset.notice is None


def test_time_offset_assumed_zero_with_notice_when_absent():
    offset = detect_time_offset([])

    assert offset.value_h == 0.0
    assert offset.source == TAG_ASSUMED_ABSENT
    assert offset.notice


def test_time_offset_user_override_is_tagged():
    offset = detect_time_offset([])

    offset.set_user_value(0.25)

    assert offset.value_h == 0.25
    assert offset.source == TAG_USER_ENTERED
    assert offset.notice is None
    assert offset.override_reason is None


def test_time_offset_user_override_can_carry_a_reason():
    offset = detect_time_offset([])

    offset.set_user_value(0.0, reason="header states 0.5 h; file day/night content aligns with 0 h")

    assert offset.value_h == 0.0
    assert offset.source == TAG_USER_ENTERED
    assert offset.override_reason == "header states 0.5 h; file day/night content aligns with 0 h"


def test_presets_reconstruct_the_named_offsets():
    assert PRESET_HOUR_START_H == 0.0
    assert PRESET_HOUR_CENTRE_H == 0.5
