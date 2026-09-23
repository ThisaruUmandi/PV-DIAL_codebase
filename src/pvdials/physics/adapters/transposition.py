"""Stage 2 adapter: GHI/DNI/DHI -> plane-of-array (POA) irradiance.

All 7 candidates fit through one call, pvlib.irradiance.get_total_irradiance():
it forwards dni_extra/airmass only to the models that need them (verified in
pvlib 0.15.2 source, 23/09), so there is no per-model dispatch here, unlike
Stage 1. Runs directly on the canonical index — no HH:30 relabelling, because
get_total_irradiance makes no internal date-based lookups.

Uses apparent zenith, not true zenith: this follows pvlib's own ModelChain/
PVSystem.get_irradiance convention (verified 23/09), which also computes
airmass from apparent zenith — exactly what the SiteContext already provides.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pvlib

from pvdials.config import load_defaults
from pvdials.physics.adapters import AdapterError
from pvdials.physics.adapters.decomposition import DecompositionResult
from pvdials.physics.geometry import Albedo, ArrayGeometry
from pvdials.physics.registry import get_candidate
from pvdials.physics.site import SiteContext
from pvdials.types import Stage

# Models that use dni_extra / airmass, per get_sky_diffuse's dispatch (informational only)
USES_DNI_EXTRA = {"haydavies", "reindl", "perez", "perez-driesse"}
USES_AIRMASS = {"perez", "perez-driesse"}


@dataclass(frozen=True)
class TranspositionResult:
    """outputs: poa_global/direct/diffuse/sky_diffuse/ground_diffuse + aoi. records: for provenance."""

    outputs: pd.DataFrame
    records: dict


def _check_selectable(model: str) -> None:
    candidate = get_candidate(Stage.TRANSPOSITION, model)
    if candidate is None:
        raise AdapterError(f"'{model}' is not a Stage 2 candidate.")
    if not candidate.selectable:
        raise AdapterError(f"'{model}' can't be selected for Stage 2: {candidate.reason}.")


def transpose(
    model: str,
    weather: pd.DataFrame,
    decomposition: DecompositionResult,
    ctx: SiteContext,
    geometry: ArrayGeometry,
    albedo: Albedo,
    defaults: dict | None = None,
) -> TranspositionResult:
    """Split GHI/DNI/DHI into plane-of-array irradiance with one Stage 2 model."""
    _check_selectable(model)
    if not weather.index.equals(ctx.solpos.index):
        raise AdapterError("Weather table and site context must share the same index.")
    if not decomposition.outputs.index.equals(weather.index):
        raise AdapterError("Decomposition output and weather table must share the same index.")

    defaults = defaults or load_defaults()
    model_perez = defaults["stage2"]["model_perez"]

    apparent_zenith = ctx.solpos["apparent_zenith"]
    azimuth = ctx.solpos["azimuth"]

    irrads = pvlib.irradiance.get_total_irradiance(
        surface_tilt=geometry.surface_tilt_deg,
        surface_azimuth=geometry.surface_azimuth_deg,
        solar_zenith=apparent_zenith,
        solar_azimuth=azimuth,
        dni=decomposition.outputs["dni"],
        ghi=weather["ghi"],
        dhi=decomposition.outputs["dhi"],
        dni_extra=ctx.dni_extra,
        airmass=ctx.airmass_relative,
        albedo=albedo.value,
        model=model,
        model_perez=model_perez,
    )
    outputs = pd.DataFrame(irrads, index=ctx.solpos.index)
    outputs["aoi"] = pvlib.irradiance.aoi(
        geometry.surface_tilt_deg, geometry.surface_azimuth_deg, apparent_zenith, azimuth
    )

    # perez's own formula divides by DHI (eps = (dhi+dni)/dhi + ...), so GHI = 0
    # (hence DNI = DHI = 0) gives a 0/0 -> NaN there, when GHI = 0 implies no
    # irradiance at all (23/09, found on the real Colombo file). Fix only actual
    # NaN at GHI = 0; other models are unaffected and are left untouched.
    ghi_zero = weather["ghi"].to_numpy(dtype=float) == 0.0
    nan_fixed = 0
    for col in ("poa_sky_diffuse", "poa_global"):
        broken = ghi_zero & outputs[col].isna().to_numpy()
        if broken.any():
            outputs.loc[broken, col] = 0.0
            nan_fixed += int(broken.sum())

    records = {
        "model": model,
        "surface_tilt_deg": geometry.surface_tilt_deg,
        "surface_azimuth_deg": geometry.surface_azimuth_deg,
        "albedo": albedo.value,
        "albedo_source": albedo.source,
        "model_perez": model_perez,
        "zenith_used": "apparent",
        "dni_extra_source": "SiteContext" if model in USES_DNI_EXTRA else "not used by this model",
        "airmass_source": "SiteContext" if model in USES_AIRMASS else "not used by this model",
        "nan_at_zero_ghi_set_zero": nan_fixed,
    }

    return TranspositionResult(outputs=outputs, records=records)
