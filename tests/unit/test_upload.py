from pathlib import Path

import pytest

from pvdials.data.upload import UploadError, load_uploaded_csv

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_finds_table_below_pvgis_preamble():
    uploaded = load_uploaded_csv(FIXTURES / "sample_pvgis_tmy.csv")

    assert uploaded.table.columns[0] == "time(UTC)"
    assert "Gb(n)" in uploaded.table.columns
    assert uploaded.preamble[0] == "Latitude (decimal degrees): 6.944"
    assert len(uploaded.preamble) == 17  # 4 site lines + month/year table


def test_footer_is_not_read_as_data():
    uploaded = load_uploaded_csv(FIXTURES / "sample_pvgis_tmy.csv")

    assert len(uploaded.table) == 4
    assert uploaded.table["time(UTC)"].iloc[-1] == "20080301:0100"


def test_plain_csv_has_no_preamble():
    uploaded = load_uploaded_csv(FIXTURES / "sample_weather_complete.csv")

    assert uploaded.preamble == []
    assert len(uploaded.table) == 3


def test_rejects_non_csv_file(tmp_path):
    bad = tmp_path / "weather.txt"
    bad.write_text("time,ghi\n", encoding="utf-8")

    with pytest.raises(UploadError):
        load_uploaded_csv(bad)


def test_rejects_file_with_no_rows(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("time(UTC),G(h),T2m,WS10m\n", encoding="utf-8")

    with pytest.raises(UploadError):
        load_uploaded_csv(empty)
