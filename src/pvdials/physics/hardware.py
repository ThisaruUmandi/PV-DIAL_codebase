"""Minimal module handling for Stage 3's NOCT gate and module_efficiency.

Deliberately small: just enough for the fuentes/noct_sam/ross gate and
their module_efficiency input. The full hardware step (module/inverter
pairing, DC parameter sourcing, N38, N40) is built separately in Step 4.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from pvlib import pvsystem

from pvdials.physics.adapters import AdapterError

CEC = "CECMod"
SANDIA = "SandiaMod"
CEC_INVERTER = "CECInverter"
ADR_INVERTER = "ADRInverter"


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


# --- N38: pdc0 / gamma_pdc derivation for Stage 4's pvwatts_dc -------------------

PDC0_FORMULA_CEC = "STC"
PDC0_FORMULA_SANDIA = "Vmpo * Impo"
GAMMA_PDC_FORMULA_CEC = "gamma_r / 100"
# Product rule for P = V*I: (1/P)(dP/dT) = (1/V)(dV/dT) + (1/I)(dI/dT). Both terms
# are SAPM's own published coefficients at reference conditions (Ee=1): sapm()'s own
# source confirms Bvmpo's irradiance-dependence term (Mbvmp) vanishes there, and
# Aimp is already the fractional (1/degC) coefficient (checked 23/09).
GAMMA_PDC_FORMULA_SANDIA = "Bvmpo / Vmpo + Aimp"


def pdc0(module: ModuleRecord) -> tuple[float, str]:
    """Nameplate DC power at STC. PROVISIONAL (N38)."""
    p = module.params
    if module.library == CEC:
        if "STC" not in p.index:
            raise AdapterError(f"Module '{module.name}' ({CEC}) has no STC field.")
        return float(p["STC"]), PDC0_FORMULA_CEC
    if module.library == SANDIA:
        missing = [f for f in ("Vmpo", "Impo") if f not in p.index]
        if missing:
            raise AdapterError(f"Module '{module.name}' ({SANDIA}) is missing {missing}.")
        return float(p["Vmpo"]) * float(p["Impo"]), PDC0_FORMULA_SANDIA
    raise AdapterError(f"pdc0 has no derivation rule for library '{module.library}'.")


def gamma_pdc(module: ModuleRecord) -> tuple[float, str]:
    """Temperature coefficient of DC power, 1/degC. PROVISIONAL (N38)."""
    p = module.params
    if module.library == CEC:
        if "gamma_r" not in p.index:
            raise AdapterError(f"Module '{module.name}' ({CEC}) has no gamma_r field.")
        return float(p["gamma_r"]) / 100.0, GAMMA_PDC_FORMULA_CEC
    if module.library == SANDIA:
        missing = [f for f in ("Bvmpo", "Vmpo", "Aimp") if f not in p.index]
        if missing:
            raise AdapterError(f"Module '{module.name}' ({SANDIA}) is missing {missing}.")
        value = float(p["Bvmpo"]) / float(p["Vmpo"]) + float(p["Aimp"])
        return value, GAMMA_PDC_FORMULA_SANDIA
    raise AdapterError(f"gamma_pdc has no derivation rule for library '{module.library}'.")


# --- CEC single-diode reference parameters ---------------------------------------

_CEC_DIODE_FIELDS = ("alpha_sc", "a_ref", "I_L_ref", "I_o_ref", "R_sh_ref", "R_s")


def cec_diode_params(module: ModuleRecord, *, need_adjust: bool) -> dict:
    """calcparams_desoto/calcparams_cec kwargs, read straight from a CECMod entry.

    CECMod's own field names already match the calcparams_* kwargs 1:1.
    """
    if module.library != CEC:
        raise AdapterError(
            f"Module '{module.name}' ({module.library}) has no CEC single-diode "
            f"reference parameters."
        )
    fields = _CEC_DIODE_FIELDS + (("Adjust",) if need_adjust else ())
    missing = [f for f in fields if f not in module.params.index]
    if missing:
        raise AdapterError(f"Module '{module.name}' ({CEC}) is missing {missing}.")
    return {f: float(module.params[f]) for f in fields}


@dataclass(frozen=True)
class ArraySize:
    """modules_per_string, strings_per_inverter. Always user-entered, no default (N40) —
    1x1 would itself be an unstated assumption, same reasoning as tilt/azimuth.
    """

    modules_per_string: int
    strings_per_inverter: int


def resolve_array_size(
    modules_per_string: int | None, strings_per_inverter: int | None
) -> ArraySize:
    if modules_per_string is None or strings_per_inverter is None:
        raise AdapterError(
            "Array size (modules_per_string, strings_per_inverter) is required; it has no "
            "default (N40)."
        )
    return ArraySize(int(modules_per_string), int(strings_per_inverter))


# --- Inverters (Stage 5) ----------------------------------------------------------

@dataclass(frozen=True)
class InverterRecord:
    """One entry from pvlib.pvsystem.retrieve_sam(). params is the raw column.

    library: CEC_INVERTER or ADR_INVERTER — which database this record's params
    came from. A name may exist in both; the caller picks which one to load from
    depending on the Stage 5 model (KT §7.4: same physical inverter, two datasets).
    """

    library: str
    name: str
    params: pd.Series


def inverter_libraries(name: str, cec_inverters: pd.DataFrame, adr_inverters: pd.DataFrame) -> set[str]:
    """Which inverter database(s) carry this name.

    Every CECInverter name also exists in ADRInverter (checked 23/09: 3,264/3,264
    overlap), so this is {CEC_INVERTER, ADR_INVERTER} for most names, and
    {ADR_INVERTER} alone for the ADR-only remainder.
    """
    libraries = set()
    if name in cec_inverters.columns:
        libraries.add(CEC_INVERTER)
    if name in adr_inverters.columns:
        libraries.add(ADR_INVERTER)
    return libraries


def load_module(library: str, name: str) -> ModuleRecord:
    """Load a module by library + name from pvlib's own database.

    A thin wrapper around pvsystem.retrieve_sam() — the single place outside
    the adapters that needs to touch pvlib's static databases directly (e.g.
    provenance/replay.py, rebuilding a ModuleRecord from a stored record).
    """
    params = pvsystem.retrieve_sam(library)[name]
    return ModuleRecord(library, name, params)


def load_inverter(library: str, name: str) -> InverterRecord:
    """Load an inverter by library + name from pvlib's own database. See load_module()."""
    params = pvsystem.retrieve_sam(library)[name]
    return InverterRecord(library, name, params)
