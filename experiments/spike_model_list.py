"""Step 1 verification spike — NOT part of the shipped package."""

import inspect
import pvlib

print("pvlib version:", pvlib.__version__)

print("\n=== transposition model options (get_total_irradiance docstring) ===")
print(pvlib.irradiance.get_total_irradiance.__doc__[:1500])

print("\n=== DC models (pvsystem) ===")
print([n for n in dir(pvlib.pvsystem) if not n.startswith("_")])

print("\n=== AC / inverter models (inverter module) ===")
print([n for n in dir(pvlib.inverter) if not n.startswith("_")])

print("\n=== module database sizes ===")
for db in ["SandiaMod", "CECMod"]:
    mods = pvlib.pvsystem.retrieve_sam(db)
    print(f"{db}: {mods.shape[1]} modules")

print("\n=== inverter database sizes ===")
for db in ["CECInverter", "SandiaInverter"]:
    invs = pvlib.pvsystem.retrieve_sam(db)
    print(f"{db}: {invs.shape[1]} inverters")