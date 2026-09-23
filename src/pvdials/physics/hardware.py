"""Minimal module handling for Stage 3's NOCT gate and module_efficiency.

Deliberately small: just enough for the fuentes/noct_sam/ross gate and
their module_efficiency input. The full hardware step (module/inverter
pairing, DC parameter sourcing, N38, N40) is built separately in Step 4.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from pvdials.physics.adapters import AdapterError

CEC = "CECMod"
SANDIA = "SandiaMod"


@dataclass(frozen=True)
class ModuleRecord:
    """One entry from pvlib.pvsystem.retrieve_sam(). params is the raw column."""

    library: str
    name: str
    params: pd.Series


def has_noct(module: ModuleRecord) -> bool:
    """True if the module carries NOCT (only CECMod does, checked 23/09)."""
    return "T_NOCT" in module.params.index and pd.notna(module.params["T_NOCT"])


def noct(module: ModuleRecord) -> float:
    if not has_noct(module):
        raise AdapterError(f"Module '{module.name}' ({module.library}) has no T_NOCT.")
    return float(module.params["T_NOCT"])


# Matches pvlib.temperature.noct_sam's documented formula exactly (checked against
# a real CECMod entry, 23/09): eta_m = V_mp * I_mp / (A * 1000 W/m^2).
MODULE_EFFICIENCY_FORMULA = "I_mp_ref * V_mp_ref / (A_c * 1000)"


def module_efficiency(module: ModuleRecord) -> tuple[float, str]:
    """Module efficiency derived from CEC reference values. PROVISIONAL, like N38."""
    required = ("I_mp_ref", "V_mp_ref", "A_c")
    missing = [f for f in required if f not in module.params.index]
    if missing:
        raise AdapterError(
            f"Module '{module.name}' ({module.library}) is missing {missing}; "
            f"module_efficiency needs a CEC-style entry."
        )
    p = module.params
    value = float(p["I_mp_ref"]) * float(p["V_mp_ref"]) / (float(p["A_c"]) * 1000.0)
    return value, MODULE_EFFICIENCY_FORMULA


def module_dimensions(module: ModuleRecord) -> tuple[float, float]:
    """(length_m, width_m) from CECMod's own fields."""
    if "Length" not in module.params.index or "Width" not in module.params.index:
        raise AdapterError(f"Module '{module.name}' ({module.library}) has no Length/Width.")
    return float(module.params["Length"]), float(module.params["Width"])
