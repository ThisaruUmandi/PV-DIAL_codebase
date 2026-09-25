from pathlib import Path

import pandas as pd
import pvlib
import pytest

from pvdials.config import load_defaults
from pvdials.data.column_mapper import (
    TAG_ASSUMED_ABSENT,
    TAG_FILE,
    SiteMetadata,
    TimeOffset,
    detect_columns,
    detect_site_metadata,
    detect_time_offset,
)
from pvdials.data.preprocess import preprocess
from pvdials.data.upload import load_uploaded_csv
from pvdials.physics.site import (
    TAG_DERIVED_FROM_ELEVATION,
    TAG_FIXED_STANDARD,
    SiteContextError,
    build_site_context,
    offset_consistency_report,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
COLOMBO = {"latitude": 6.944, "longitude": 79.856, "elevation": 16.0}


def _from_fixture():
    uploaded = load_uploaded_csv(FIXTURES / "sample_pvgis_tmy.csv")
    weather = preprocess(uploaded.table, detect_columns(uploaded.table), canonical_year=2023).df
    site = detect_site_metadata(uploaded.preamble, uploaded.table)
    return weather, site, detect_time_offset(uploaded.preamble)


def _day(pressure=101000.0, temp_air=28.0):
    """One synthetic day at 5-minute steps, so every zenith band is sampled."""
    idx = pd.date_range("2023-03-21", periods=288, freq="5min", tz="UTC")
    return pd.DataFrame(
        {"ghi": 0.0, "temp_air": temp_air, "wind_speed": 1.0, "pressure": pressure}, index=idx
    )


def _site(**values):
    return SiteMetadata(values=values, sources={k: "From CSV" for k in values})


NO_OFFSET = TimeOffset(0.0, TAG_ASSUMED_ABSENT, "notice")


def test_building_twice_gives_identical_results():
    first = build_site_context(*_from_fixture())
    second = build_site_context(*_from_fixture())

    pd.testing.assert_frame_equal(first.solpos, second.solpos)
    pd.testing.assert_series_equal(first.daylight, second.daylight)
    pd.testing.assert_series_equal(first.airmass_relative, second.airmass_relative)
    pd.testing.assert_series_equal(first.dni_extra, second.dni_extra)
    assert dict(first.settings) == dict(second.settings)
    assert first.steps == second.steps


def test_time_effective_is_index_plus_header_offset():
    ctx = build_site_context(*_from_fixture())

    assert (ctx.solpos.index.minute == 0).all()  # canonical HH:00 join key unchanged
    expected = ctx.solpos.index + pd.Timedelta(hours=0.5)
    assert (ctx.solpos["time_effective"] == expected).all()
    assert ctx.settings["time_offset_source"] == TAG_FILE


def test_refraction_inputs_change_apparent_zenith_only():
    base = build_site_context(_day(), _site(**COLOMBO), NO_OFFSET)
    other = build_site_context(_day(pressure=97000.0, temp_air=5.0), _site(**COLOMBO), NO_OFFSET)

    pd.testing.assert_series_equal(base.solpos["zenith"], other.solpos["zenith"])
    pd.testing.assert_series_equal(base.daylight, other.daylight)
    assert not base.solpos["apparent_zenith"].equals(other.solpos["apparent_zenith"])


def test_daylight_mask_is_true_zenith_below_cutoff():
    ctx = build_site_context(_day(), _site(**COLOMBO), NO_OFFSET)
    zenith = ctx.solpos["zenith"]
    band = (zenith >= 85) & (zenith < 90)

    assert band.any()  # the 85-90 degree band is sampled
    assert not ctx.daylight[band].any()
    assert (ctx.daylight == (zenith < 85.0)).all()


def test_pressure_from_file_is_tagged_file():
    ctx = build_site_context(*_from_fixture())

    assert ctx.pressure_source == TAG_FILE
    assert ctx.settings["pressure_source"] == TAG_FILE


def test_pressure_derived_from_elevation_when_absent():
    weather = _day().drop(columns="pressure")

    ctx = build_site_context(weather, _site(**COLOMBO), NO_OFFSET)

    assert ctx.pressure_source == TAG_DERIVED_FROM_ELEVATION
    assert ctx.pressure.iloc[0] == pytest.approx(pvlib.atmosphere.alt2pres(16.0))
    assert any(s.name == "pressure_derived_from_elevation" for s in ctx.steps)


def test_fixed_standard_pressure_when_no_pressure_and_no_elevation():
    weather = _day().drop(columns="pressure")

    ctx = build_site_context(weather, _site(latitude=6.944, longitude=79.856), NO_OFFSET)

    assert ctx.pressure_source == TAG_FIXED_STANDARD
    assert ctx.pressure.iloc[0] == 101325
    assert ctx.settings["spa_altitude_m"] == 0.0
    assert any("Standard pressure" in n for n in ctx.notices)


def test_sea_level_pressure_at_high_site_is_rejected():
    weather = _day(pressure=101325.0)  # MSL value, but the site is at 1,500 m

    with pytest.raises(SiteContextError, match="sea-level"):
        build_site_context(
            weather, _site(latitude=7.0, longitude=80.8, elevation=1500.0), NO_OFFSET
        )


def test_missing_latitude_is_rejected():
    with pytest.raises(SiteContextError, match="latitude"):
        build_site_context(_day(), _site(longitude=79.856, elevation=16.0), NO_OFFSET)


def test_radiation_database_inferred_only_from_file_offset_of_half_hour():
    from_file = build_site_context(*_from_fixture())
    assumed = build_site_context(_day(), _site(**COLOMBO), NO_OFFSET)

    assert from_file.settings["radiation_database"].startswith("ERA5")
    assert assumed.settings["radiation_database"] == "not inferred"
    assert "notice" in assumed.notices  # assumed-offset notice is carried through


def test_settings_carry_every_value_used():
    ctx = build_site_context(_day(), _site(**COLOMBO), NO_OFFSET)
    d = load_defaults()

    assert ctx.settings["delta_t_s"] == d["solar_position"]["delta_t_s"]
    assert ctx.settings["atmos_refract_deg"] == d["solar_position"]["atmos_refract_deg"]
    assert ctx.settings["airmass_model"] == d["airmass"]["model"]
    assert ctx.settings["extraterrestrial_method"] == d["extraterrestrial"]["method"]
    assert ctx.settings["solar_constant_w_m2"] == d["extraterrestrial"]["solar_constant_w_m2"]
    assert ctx.settings["daylight_mask_zenith_max_deg"] == 85.0
    assert ctx.settings["time_offset_h"] == 0.0
    assert ctx.settings["pvlib_version"] == "0.15.2"


def test_airmass_and_dni_extra_defined_on_daylight_rows():
    ctx = build_site_context(_day(), _site(**COLOMBO), NO_OFFSET)

    assert ctx.airmass_relative[ctx.daylight].notna().all()
    assert (ctx.dni_extra > 1300).all()


def test_offset_consistency_report_does_not_mutate_the_detected_offset():
    # additive, opt-in: building the report never changes the header-driven
    # TimeOffset the caller already has, and never affects a later call to
    # build_site_context() with that same original offset.
    weather, site, offset = _from_fixture()

    offset_consistency_report(weather, site, {"header": offset.value_h, "hour_start": 0.0})

    assert offset.value_h == 0.5  # the fixture's real header value, untouched
    assert offset.source == TAG_FILE
    ctx = build_site_context(weather, site, offset)
    assert ctx.time_offset_h == 0.5


def test_offset_consistency_report_counts_both_mismatch_directions():
    weather, site, _ = _from_fixture()

    report = offset_consistency_report(
        weather, site, {"header": 0.5, "hour_start": 0.0, "hour_centre": 0.5}
    )

    labels = [c.label for c in report]
    assert labels == ["header", "hour_start", "hour_centre"]
    for candidate in report:
        assert candidate.ghi_positive_sun_down >= 0
        assert candidate.ghi_zero_sun_up >= 0
    # header and hour_centre are the same numeric value on this fixture
    header, _, hour_centre = report
    assert header.ghi_positive_sun_down == hour_centre.ghi_positive_sun_down
    assert header.ghi_zero_sun_up == hour_centre.ghi_zero_sun_up
