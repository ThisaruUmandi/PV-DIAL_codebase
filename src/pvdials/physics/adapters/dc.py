"""Stage 4 adapter: plane-of-array irradiance + cell temperature -> DC power.

Runs directly on the canonical index. Every DC model in pvlib computes a
single module's output; array scaling (N40) is applied uniformly to all
four branches here, not just singlediode (the N21 bug's root cause,
generalised: scale_voltage_current_power's own column list — v_mp, v_oc,
i_mp, i_x, i_xx, i_sc, p_mp — matches sapm()'s and singlediode()'s output
exactly, and pvwatts_dc's pdc0, derived here from one module's nameplate,
is per-module too until scaled).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from pvlib import atmosphere, iam, pvsystem

from pvdials.config import load_defaults
from pvdials.physics.adapters import AdapterError
from pvdials.physics.adapters.temperature import TemperatureResult
from pvdials.physics.adapters.transposition import TranspositionResult
from pvdials.physics.hardware import (
    ModuleRecord,
    cec_diode_params,
    gamma_pdc,
    pdc0,
    resolve_array_size,
)
from pvdials.physics.registry import get_candidate, stage4_selectable
from pvdials.physics.site import SiteContext
from pvdials.types import Stage

NO_SPECTRAL_MODELS = {"pvwatts_dc", "singlediode_desoto", "singlediode_cec"}


@dataclass(frozen=True)
class DCResult:
    """outputs: p_dc always; v_dc/i_dc when the model produces them. records: for provenance."""

    outputs: pd.DataFrame
    records: dict


def _check_selectable(model: str, module: ModuleRecord) -> None:
    candidate = get_candidate(Stage.DC, model)
    if candidate is None:
        raise AdapterError(f"'{model}' is not a Stage 4 candidate.")
    if not candidate.selectable:
        raise AdapterError(f"'{model}' can't be selected for Stage 4: {candidate.reason}.")
    ok, reason = stage4_selectable(model, module)
    if not ok:
        raise AdapterError(f"'{model}' can't be selected for Stage 4: {reason}.")


def _no_spectral_effective_irradiance(
    transposition: TranspositionResult, module: ModuleRecord, defaults: dict
) -> pd.Series:
    """physical IAM, no spectral (N16): poa_direct * iam.physical(aoi) + FD * poa_diffuse."""
    cfg = defaults["stage4"]["iam_physical"]
    aoi_modifier = iam.physical(transposition.outputs["aoi"], n=cfg["n"], K=cfg["K"], L=cfg["L"])
    fd = float(module.params["FD"]) if "FD" in module.params.index else 1.0
    return transposition.outputs["poa_direct"] * aoi_modifier + fd * transposition.outputs[
        "poa_diffuse"
    ]


def _sapm_effective_irradiance(
    transposition: TranspositionResult, ctx: SiteContext, module: ModuleRecord
) -> pd.Series:
    """Sandia's own F1 (spectral) x F2 (AOI) pretreatment, bundled in one call (N16)."""
    airmass_absolute = atmosphere.get_absolute_airmass(ctx.airmass_relative, ctx.pressure)
    return pvsystem.sapm_effective_irradiance(
        transposition.outputs["poa_direct"],
        transposition.outputs["poa_diffuse"],
        airmass_absolute,
        transposition.outputs["aoi"],
        module.params,
    )


def dc_power(
    model: str,
    transposition: TranspositionResult,
    temperature: TemperatureResult,
    ctx: SiteContext,
    module: ModuleRecord,
    modules_per_string: int | None = None,
    strings_per_inverter: int | None = None,
    defaults: dict | None = None,
) -> DCResult:
    """DC power with one Stage 4 model, scaled to the array (N40)."""
    _check_selectable(model, module)
    if not transposition.outputs.index.equals(temperature.outputs.index):
        raise AdapterError("Transposition and temperature output must share the same index.")

    array = resolve_array_size(modules_per_string, strings_per_inverter)

    defaults = defaults or load_defaults()
    cfg = defaults["stage4"]
    temp_cell = temperature.outputs["temp_cell"]
    index = transposition.outputs.index
    records: dict = {"model": model, "array_size": (array.modules_per_string, array.strings_per_inverter)}

    if model in NO_SPECTRAL_MODELS:
        effective_irradiance = _no_spectral_effective_irradiance(transposition, module, defaults)
        records["effective_irradiance_path"] = "no_spectral (iam.physical)"
    else:
        effective_irradiance = _sapm_effective_irradiance(transposition, ctx, module)
        records["effective_irradiance_path"] = "sapm (F1 spectral x F2 AOI)"

    if model == "pvwatts_dc":
        eta0, formula0 = pdc0(module)
        eta1, formula1 = gamma_pdc(module)
        p_cfg = cfg["pvwatts_dc"]
        pdc_per_module = pvsystem.pvwatts_dc(
            effective_irradiance,
            temp_cell,
            pdc0=eta0,
            gamma_pdc=eta1,
            temp_ref=p_cfg["temp_ref"],
            k=p_cfg["k"],
            cap_adjustment=p_cfg["cap_adjustment"],
        )
        scale = array.modules_per_string * array.strings_per_inverter
        outputs = pd.DataFrame({"p_dc": pdc_per_module * scale}, index=index)
        records["pdc0"] = eta0
        records["pdc0_formula"] = formula0
        records["gamma_pdc"] = eta1
        records["gamma_pdc_formula"] = formula1
        records["v_dc"] = "not produced by this model"
        records["i_dc"] = "not produced by this model"

    elif model == "sapm":
        s_cfg = cfg["sapm"]
        dc = pvsystem.sapm(
            effective_irradiance,
            temp_cell,
            module.params,
            temperature_ref=s_cfg["temperature_ref"],
            irradiance_ref=s_cfg["irradiance_ref"],
        )
        # sapm()'s own v_mp formula uses log(Ee): at Ee = 0, log(0) = -inf, and i_mp is
        # exactly 0 there (its own Ee/Ee^2 terms), so v_mp*i_mp = -inf*0 = NaN, when
        # zero irradiance means zero power (found on the real Colombo file, 23/09 —
        # same class of issue as perez's 0/0 in Stage 2). Fix only actual NaN at
        # zero irradiance.
        zero_irradiance = effective_irradiance.to_numpy(dtype=float) == 0.0
        nan_fixed = 0
        for col in ("v_mp", "p_mp"):
            broken = zero_irradiance & dc[col].isna().to_numpy()
            if broken.any():
                dc.loc[broken, col] = 0.0
                nan_fixed += int(broken.sum())
        records["nan_at_zero_irradiance_set_zero"] = nan_fixed

        scaled = pvsystem.scale_voltage_current_power(
            dc, voltage=array.modules_per_string, current=array.strings_per_inverter
        )
        outputs = scaled.rename(columns={"p_mp": "p_dc", "v_mp": "v_dc", "i_mp": "i_dc"})
        outputs = outputs[["p_dc", "v_dc", "i_dc"]]

    elif model in ("singlediode_desoto", "singlediode_cec"):
        sd_cfg = cfg["singlediode"]
        cp_cfg = sd_cfg["calcparams"]
        need_adjust = model == "singlediode_cec"
        diode_params = cec_diode_params(module, need_adjust=need_adjust)
        calc = pvsystem.calcparams_cec if need_adjust else pvsystem.calcparams_desoto
        IL, I0, Rs, Rsh, nNsVth = calc(
            effective_irradiance,
            temp_cell,
            **diode_params,
            EgRef=cp_cfg["EgRef"],
            dEgdT=cp_cfg["dEgdT"],
            irrad_ref=cp_cfg["irrad_ref"],
            temp_ref=cp_cfg["temp_ref"],
        )
        dc = pvsystem.singlediode(IL, I0, Rs, Rsh, nNsVth, method=sd_cfg["method"])
        scaled = pvsystem.scale_voltage_current_power(
            dc, voltage=array.modules_per_string, current=array.strings_per_inverter
        )
        outputs = scaled.rename(columns={"p_mp": "p_dc", "v_mp": "v_dc", "i_mp": "i_dc"})
        outputs = outputs[["p_dc", "v_dc", "i_dc"]]
        records["diode_params"] = diode_params

    else:  # pragma: no cover - guarded by _check_selectable
        raise AdapterError(f"'{model}' has no adapter implementation.")

    return DCResult(outputs=outputs, records=records)
