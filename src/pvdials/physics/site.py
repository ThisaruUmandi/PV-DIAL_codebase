"""Shared site context: solar position, airmass, extraterrestrial DNI, daylight mask.

Built ONCE per comparison from the cleaned weather table and shared by every
configuration (decision D6). This is the only file that computes solar
position. Every setting used is passed explicitly — nothing is left to
pvlib's internal defaults — and is kept in `settings` for provenance.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

import numpy as np
import pandas as pd
import pvlib

from pvdials.config import load_defaults
from pvdials.data.column_mapper import TAG_FILE, TAG_USER_ENTERED, SiteMetadata, TimeOffset
from pvdials.data.preprocess import RecordedStep

# Pressure source tags. Provenance always carries exactly one.
TAG_DERIVED_FROM_ELEVATION = "derived_from_elevation"
TAG_FIXED_STANDARD = "fixed_standard"
PRESSURE_TAGS = (TAG_FILE, TAG_DERIVED_FROM_ELEVATION, TAG_USER_ENTERED, TAG_FIXED_STANDARD)

# Hourly data: each value covers the hour whose midpoint is the effective time
HALF_STEP = pd.Timedelta(minutes=30)

ERA5_OFFSET_H = 0.5

FIXED_STANDARD_NOTICE = (
    "No surface pressure in the file and no elevation available. Standard "
    "pressure {pressure:.0f} Pa and 0 m altitude are used for solar position."
)


class SiteContextError(Exception):
    """Raised when the site context can't be built from the given inputs."""


@dataclass(frozen=True)
class SiteContext:
    """Everything about the site and sun that all configurations share.

    All series are indexed by the canonical HH:00 UTC index (the join key).
    Treat the series and tables as read-only.
    """

    latitude: float
    longitude: float
    elevation: float | None
    time_offset_h: float
    pressure: pd.Series
    pressure_source: str
    solpos: pd.DataFrame  # includes 'time_effective'
    zenith_start: pd.Series  # true zenith at the start of each hour (Tier 4 only)
    zenith_end: pd.Series  # true zenith at the end of each hour (Tier 4 only)
    airmass_relative: pd.Series
    dni_extra: pd.Series
    daylight: pd.Series
    steps: tuple[RecordedStep, ...]
    notices: tuple[str, ...]
    settings: MappingProxyType


def _resolve_pressure(
    weather: pd.DataFrame,
    elevation: float | None,
    cfg: dict,
    steps: list[RecordedStep],
    notices: list[str],
) -> tuple[pd.Series, str]:
    """Surface pressure series (Pa) and its source tag."""
    if "pressure" in weather.columns:
        pressure = weather["pressure"].astype(float)
        if elevation is None:
            steps.append(
                RecordedStep(
                    "pressure_surface_check_skipped",
                    "No elevation available, so file pressure was not checked against "
                    "the pressure expected at site elevation.",
                )
            )
        else:
            # Catch sea-level (MSL-reduced) pressure supplied as if it were surface pressure
            expected = pvlib.atmosphere.alt2pres(elevation)
            median = float(pressure.median())
            if abs(median - expected) / expected > cfg["sp_surface_tolerance"]:
                raise SiteContextError(
                    f"Median file pressure {median:.0f} Pa differs from the {expected:.0f} Pa "
                    f"expected at {elevation} m by more than "
                    f"{cfg['sp_surface_tolerance']:.0%}. It may be sea-level pressure, "
                    f"not surface pressure."
                )
        return pressure, TAG_FILE

    if elevation is not None:
        value = float(pvlib.atmosphere.alt2pres(elevation))
        steps.append(
            RecordedStep(
                "pressure_derived_from_elevation",
                f"No surface pressure in the file. Used {value:.1f} Pa (constant) from "
                f"pvlib.atmosphere.alt2pres(elevation={elevation} m).",
            )
        )
        return pd.Series(value, index=weather.index, name="pressure"), TAG_DERIVED_FROM_ELEVATION

    value = float(cfg["standard_pressure_pa"])
    steps.append(
        RecordedStep(
            "pressure_fixed_standard",
            f"No surface pressure and no elevation. Used standard pressure {value:.0f} Pa.",
        )
    )
    notices.append(FIXED_STANDARD_NOTICE.format(pressure=value))
    return pd.Series(value, index=weather.index, name="pressure"), TAG_FIXED_STANDARD


def build_site_context(
    weather: pd.DataFrame,
    site: SiteMetadata,
    offset: TimeOffset,
    defaults: dict | None = None,
) -> SiteContext:
    """Compute solar position once, plus airmass, extraterrestrial DNI and the daylight mask.

    weather: cleaned table from data.preprocess (canonical UTC index, temp_air,
    optional pressure in Pa).
    """
    defaults = defaults or load_defaults()
    sp_cfg = defaults["solar_position"]
    am_cfg = defaults["airmass"]
    et_cfg = defaults["extraterrestrial"]
    mask_max = float(defaults["dla"]["daylight_mask_zenith_max_deg"])

    for required in ("latitude", "longitude"):
        if required not in site.values:
            raise SiteContextError(f"Site {required} is missing; it must be entered.")
    if weather.index.tz is None or str(weather.index.tz) != "UTC":
        raise SiteContextError("Weather index must be UTC (see data.preprocess).")

    latitude = site.values["latitude"]
    longitude = site.values["longitude"]
    elevation = site.values.get("elevation")

    steps: list[RecordedStep] = []
    notices: list[str] = [offset.notice] if offset.notice else []

    pressure, pressure_source = _resolve_pressure(weather, elevation, sp_cfg, steps, notices)

    altitude = elevation
    if altitude is None:
        altitude = 0.0
        steps.append(
            RecordedStep("spa_altitude_zero", "No elevation available; SPA altitude set to 0 m.")
        )

    # Irradiance values represent index + offset (PVGIS: HH:30). The canonical
    # HH:00 index stays the join key; the shifted time is kept as its own column.
    time_effective = weather.index + pd.Timedelta(hours=offset.value_h)
    steps.append(
        RecordedStep(
            "solar_position_time_offset",
            f"Solar position computed at timestamp + {offset.value_h} h "
            f"(offset source: {offset.source}). Kept in solpos['time_effective'].",
        )
    )

    # SP and T2m set refraction, which changes apparent_zenith (and so airmass)
    # only. True zenith is unaffected, and the Stage 1 decomposition models take
    # true zenith, so these inputs cannot reach Stage 1 or the daylight mask.
    def solar_position(times: pd.DatetimeIndex) -> pd.DataFrame:
        out = pvlib.solarposition.get_solarposition(
            times,
            latitude,
            longitude,
            altitude=altitude,
            pressure=pressure.to_numpy(),
            temperature=weather["temp_air"].to_numpy(dtype=float),
            method=sp_cfg["method"],
            delta_t=sp_cfg["delta_t_s"],
            atmos_refract=sp_cfg["atmos_refract_deg"],
        )
        out.index = weather.index
        return out

    solpos = solar_position(time_effective)
    solpos.insert(0, "time_effective", time_effective)
    zenith_start = solar_position(time_effective - HALF_STEP)["zenith"].rename("zenith_start")
    zenith_end = solar_position(time_effective + HALF_STEP)["zenith"].rename("zenith_end")

    airmass_relative = pvlib.atmosphere.get_relative_airmass(
        solpos["apparent_zenith"], model=am_cfg["model"]
    ).rename("airmass_relative")

    dni_extra = pd.Series(
        np.asarray(
            pvlib.irradiance.get_extra_radiation(
                time_effective,
                solar_constant=et_cfg["solar_constant_w_m2"],
                method=et_cfg["method"],
            ),
            dtype=float,
        ),
        index=weather.index,
        name="dni_extra",
    )

    # Mask from TRUE zenith only, so refraction settings can't change which rows count
    daylight = (solpos["zenith"] < mask_max).rename("daylight")

    if offset.source == TAG_FILE and offset.value_h == ERA5_OFFSET_H:
        radiation_database = f"ERA5 (inferred from offset {ERA5_OFFSET_H:.3f} h)"
    else:
        radiation_database = "not inferred"

    settings = {
        "latitude": latitude,
        "longitude": longitude,
        "elevation": elevation,
        "site_sources": dict(site.sources),
        "spa_altitude_m": altitude,
        "solar_position_method": sp_cfg["method"],
        "delta_t_s": sp_cfg["delta_t_s"],
        "atmos_refract_deg": sp_cfg["atmos_refract_deg"],
        "pressure_source": pressure_source,
        "temperature_source": "temp_air column (file)",
        "sp_surface_tolerance": sp_cfg["sp_surface_tolerance"],
        "time_offset_h": offset.value_h,
        "time_offset_source": offset.source,
        "radiation_database": radiation_database,
        "airmass_model": am_cfg["model"],
        "airmass_zenith": "apparent",
        "extraterrestrial_method": et_cfg["method"],
        "solar_constant_w_m2": et_cfg["solar_constant_w_m2"],
        "daylight_mask_zenith_max_deg": mask_max,
        "daylight_mask_zenith": "true",
        "pvlib_version": pvlib.__version__,
    }

    return SiteContext(
        latitude=latitude,
        longitude=longitude,
        elevation=elevation,
        time_offset_h=offset.value_h,
        pressure=pressure.rename("pressure"),
        pressure_source=pressure_source,
        solpos=solpos,
        zenith_start=zenith_start,
        zenith_end=zenith_end,
        airmass_relative=airmass_relative,
        dni_extra=dni_extra,
        daylight=daylight,
        steps=tuple(steps),
        notices=tuple(notices),
        settings=MappingProxyType(settings),
    )
