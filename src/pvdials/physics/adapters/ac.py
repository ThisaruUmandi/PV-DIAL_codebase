"""Stage 5 adapter: DC power -> AC power.

sandia/adr call the DC-side v_dc/p_dc directly against the chosen inverter's
own parameters (from the matching database, per KT §7.4). pvwatts needs no
inverter database entry at all — it reuses Stage 4's pdc0(module) derivation
(N38), scaled by the same array size, as its own array-scale DC nameplate
input. This is the last physics stage; validate.py's AC <= DC check (N21)
is the permanent regression guard over every combination built here.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from pvlib import inverter as inverter_models

from pvdials.config import load_defaults
from pvdials.physics.adapters import AdapterError
from pvdials.physics.adapters.dc import DCResult
from pvdials.physics.hardware import ArraySize, InverterRecord, ModuleRecord, pdc0
from pvdials.physics.registry import get_candidate, stage5_selectable
from pvdials.types import Stage


@dataclass(frozen=True)
class ACResult:
    """outputs: 'p_ac' on the canonical index. records: for provenance."""

    outputs: pd.DataFrame
    records: dict


def _check_selectable(
    model: str, inverter: InverterRecord | None, dc_has_v_dc: bool
) -> None:
    candidate = get_candidate(Stage.AC, model)
    if candidate is None:
        raise AdapterError(f"'{model}' is not a Stage 5 candidate.")
    if not candidate.selectable:
        raise AdapterError(f"'{model}' can't be selected for Stage 5: {candidate.reason}.")
    libraries = {inverter.library} if inverter is not None else set()
    ok, reason = stage5_selectable(model, libraries, dc_has_v_dc)
    if not ok:
        raise AdapterError(f"'{model}' can't be selected for Stage 5: {reason}.")


def ac_power(
    model: str,
    dc_result: DCResult,
    inverter: InverterRecord | None = None,
    module: ModuleRecord | None = None,
    array_size: ArraySize | None = None,
    defaults: dict | None = None,
) -> ACResult:
    """AC power with one Stage 5 model."""
    dc_has_v_dc = "v_dc" in dc_result.outputs.columns
    _check_selectable(model, inverter, dc_has_v_dc)

    defaults = defaults or load_defaults()
    index = dc_result.outputs.index
    records: dict = {"model": model}

    if model in ("sandia", "adr"):
        if inverter is None:
            raise AdapterError(f"'{model}' needs the selected inverter.")
        v_dc = dc_result.outputs["v_dc"]
        p_dc = dc_result.outputs["p_dc"]
        if model == "sandia":
            p_ac = inverter_models.sandia(v_dc, p_dc, inverter.params)
        else:
            vtol = defaults["stage5"]["adr"]["vtol"]
            p_ac = inverter_models.adr(v_dc, p_dc, inverter.params, vtol=vtol)
        records["inverter_name"] = inverter.name
        records["inverter_library"] = inverter.library

    elif model == "pvwatts":
        if module is None or array_size is None:
            raise AdapterError("'pvwatts' needs the selected module and array size.")
        per_module_pdc0, formula = pdc0(module)
        scale = array_size.modules_per_string * array_size.strings_per_inverter
        array_pdc0 = per_module_pdc0 * scale
        cfg = defaults["stage5"]["pvwatts"]
        p_ac = inverter_models.pvwatts(
            dc_result.outputs["p_dc"],
            pdc0=array_pdc0,
            eta_inv_nom=cfg["eta_inv_nom"],
            eta_inv_ref=cfg["eta_inv_ref"],
        )
        records["pdc0"] = array_pdc0
        records["pdc0_formula"] = formula
        records["pdc0_source"] = "Stage 4 module pdc0 (N38), scaled by array size"

    else:  # pragma: no cover - guarded by _check_selectable
        raise AdapterError(f"'{model}' has no adapter implementation.")

    outputs = pd.DataFrame({"p_ac": p_ac}, index=index)
    return ACResult(outputs=outputs, records=records)
