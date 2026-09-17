"""Step 1 verification spike — inspects the N21 bug mechanism.
NOT part of the shipped package.
"""

import pandas as pd
import pvlib

modules = pvlib.pvsystem.retrieve_sam("CECMod")
module = modules["Canadian_Solar_Inc__CS6K_300MS"]

# One representative daylight condition, just to compare magnitudes
effective_irradiance = 800  # W/m^2
temp_cell = 45  # deg C

params = pvlib.pvsystem.calcparams_cec(
    effective_irradiance=effective_irradiance,
    temp_cell=temp_cell,
    alpha_sc=module["alpha_sc"],
    a_ref=module["a_ref"],
    I_L_ref=module["I_L_ref"],
    I_o_ref=module["I_o_ref"],
    R_sh_ref=module["R_sh_ref"],
    R_s=module["R_s"],
    Adjust=module["Adjust"],
)
IL, I0, Rs, Rsh, nNsVth = params

result = pvlib.pvsystem.singlediode(IL, I0, Rs, Rsh, nNsVth)
p_mp_single_module = result["p_mp"]

print(f"singlediode() p_mp for ONE module: {p_mp_single_module:.1f} W")
print(f"Module nameplate (STC): {module['STC']:.1f} W")
print()

modules_per_string = 10
strings_per_inverter = 2

result_df = pd.DataFrame([result])  # wrap the single-row dict as a DataFrame

p_mp_scaled = pvlib.pvsystem.scale_voltage_current_power(
    result_df, voltage=modules_per_string, current=strings_per_inverter
)
print(
    f"After scale_voltage_current_power "
    f"({modules_per_string} modules/string x {strings_per_inverter} strings): "
    f"{p_mp_scaled['p_mp'].iloc[0]:.1f} W"
)
print()
print(
    "If scale_voltage_current_power is skipped, downstream code sees only the "
    "per-module number above — small enough that any array-scale AC figure "
    "computed elsewhere in the same pipeline will exceed it, exactly matching "
    "the N21 symptom (AC 2355 W > DC 2171 W)."
)