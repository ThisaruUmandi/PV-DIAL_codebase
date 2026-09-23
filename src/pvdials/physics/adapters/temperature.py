"""Stage 3 adapter: plane-of-array irradiance -> cell temperature.

Runs directly on the canonical index; none of the 6 selectable models make
internal date-based lookups. Every coefficient is explicit — mounting
coefficients come from pvlib's own TEMPERATURE_MODEL_PARAMETERS table via
the resolved mounting key, module-derived values come from hardware.py,
and everything else comes from run_defaults.yaml.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from pvlib import temperature as T

from pvdials.config import load_defaults
from pvdials.physics.adapters import AdapterError
from pvdials.physics.adapters.transposition import TranspositionResult
from pvdials.physics.geometry import ArrayGeometry
from pvdials.physics.hardware import (
    ModuleRecord,
    module_dimensions,
    module_efficiency,
    noct,
)
from pvdials.physics.mounting import Mounting, pvsyst_key, resolve_array_height, sapm_key
from pvdials.physics.registry import get_candidate, stage3_selectable
from pvdials.types import Stage

MODULE_DEPENDENT = {"fuentes", "noct_sam", "ross"}


@dataclass(frozen=True)
class TemperatureResult:
    """outputs: 'temp_cell' on the canonical index. records: for provenance."""

    outputs: pd.DataFrame
    records: dict


def _check_selectable(model: str, module: ModuleRecord | None, mounting: Mounting) -> None:
    candidate = get_candidate(Stage.TEMPERATURE, model)
    if candidate is None:
        raise AdapterError(f"'{model}' is not a Stage 3 candidate.")
    if not candidate.selectable:
        raise AdapterError(f"'{model}' can't be selected for Stage 3: {candidate.reason}.")
    if model in MODULE_DEPENDENT and module is None:
        raise AdapterError(f"'{model}' needs the selected module (to read its NOCT).")
    ok, reason = stage3_selectable(model, module, mounting)
    if not ok:
        raise AdapterError(f"'{model}' can't be selected for Stage 3: {reason}.")


def cell_temperature(
    model: str,
    transposition: TranspositionResult,
    weather: pd.DataFrame,
    mounting: Mounting,
    geometry: ArrayGeometry,
    module: ModuleRecord | None = None,
    module_height_m: float | None = None,
    array_height: int | None = None,
    defaults: dict | None = None,
) -> TemperatureResult:
    """Cell temperature from POA irradiance with one Stage 3 model."""
    _check_selectable(model, module, mounting)
    if not transposition.outputs.index.equals(weather.index):
        raise AdapterError("Transposition output and weather table must share the same index.")

    defaults = defaults or load_defaults()
    stage3 = defaults["stage3"]

    poa_global = transposition.outputs["poa_global"]
    temp_air = weather["temp_air"]
    wind_speed = weather["wind_speed"]
    records: dict = {"model": model}

    if model == "sapm_cell":
        key = sapm_key(mounting)  # always not-None here: _check_selectable already gated it
        coeff = T.TEMPERATURE_MODEL_PARAMETERS["sapm"][key]
        temp_cell = T.sapm_cell(poa_global, temp_air, wind_speed, coeff["a"], coeff["b"], coeff["deltaT"])
        records["sapm_mounting_key"] = key
        records["coefficients"] = coeff

    elif model == "pvsyst_cell":
        key = pvsyst_key(mounting)
        coeff = dict(T.TEMPERATURE_MODEL_PARAMETERS["pvsyst"][key])
        cfg = stage3["pvsyst_cell"]
        temp_cell = T.pvsyst_cell(
            poa_global,
            temp_air,
            wind_speed,
            u_c=coeff["u_c"],
            u_v=coeff["u_v"],
            module_efficiency=cfg["module_efficiency"],
            alpha_absorption=cfg["alpha_absorption"],
        )
        records["pvsyst_mounting_key"] = key
        records["coefficients"] = {**coeff, **cfg}

    elif model == "faiman":
        cfg = stage3["faiman"]
        temp_cell = T.faiman(poa_global, temp_air, wind_speed, u0=cfg["u0"], u1=cfg["u1"])
        records["coefficients"] = cfg

    elif model == "fuentes":
        if module_height_m is None:
            raise AdapterError("fuentes needs module_height_m; it has no default.")
        cfg = stage3["fuentes"]
        length_m, width_m = module_dimensions(module)
        eta, formula = module_efficiency(module)
        temp_cell = T.fuentes(
            poa_global,
            temp_air,
            wind_speed,
            noct_installed=noct(module),
            module_height=module_height_m,
            wind_height=cfg["wind_height_m"],
            emissivity=cfg["emissivity"],
            absorption=cfg["absorption"],
            surface_tilt=geometry.surface_tilt_deg,
            module_width=width_m,
            module_length=length_m,
        )
        records["module_height_m"] = module_height_m
        records["module_efficiency"] = eta
        records["module_efficiency_formula"] = formula
        records["coefficients"] = cfg

    elif model == "noct_sam":
        cfg = stage3["noct_sam"]
        height, height_source = resolve_array_height(array_height, defaults)
        eta, formula = module_efficiency(module)
        mount_standoff_in = cfg["mount_standoff_in"]
        temp_cell = T.noct_sam(
            poa_global,
            temp_air,
            wind_speed,
            noct=noct(module),
            module_efficiency=eta,
            transmittance_absorptance=cfg["transmittance_absorptance"],
            array_height=height,
            mount_standoff=mount_standoff_in,
        )
        records["array_height"] = height
        records["array_height_source"] = height_source
        records["module_efficiency"] = eta
        records["module_efficiency_formula"] = formula
        records["coefficients"] = cfg

    elif model == "ross":
        # k has no source anywhere in this project; always use noct (23/09 extension)
        temp_cell = T.ross(poa_global, temp_air, noct=noct(module))
        records["noct_used"] = noct(module)

    else:  # pragma: no cover - guarded by _check_selectable
        raise AdapterError(f"'{model}' has no adapter implementation.")

    outputs = pd.DataFrame({"temp_cell": temp_cell}, index=weather.index)
    return TemperatureResult(outputs=outputs, records=records)
