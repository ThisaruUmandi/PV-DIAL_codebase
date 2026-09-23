"""Mounting for Stage 3 (cell temperature).

Two user-entered inputs, not one, feed one translation table (decided
23/09): SAPM's coefficient keys encode geometry AND glazing/backsheet
construction, while pvsyst's encode geometry only. One input can't drive
both without silently assuming the other, so geometry and construction are
asked separately and mapped into each model's own key. This keeps the
installation invariant across every model in the pool (D2-style confound
avoided): every temperature model in a comparison describes the same
physical rack, never two answers that happen to have drifted apart.

Neither CECMod nor SandiaMod carries a construction field (checked 23/09),
so construction is always asked, never derived from the module.
"""

from __future__ import annotations

from dataclasses import dataclass

from pvdials.physics.geometry import TAG_DEFAULT, TAG_USER_ENTERED

GEOMETRIES = ("open_rack", "close_mount", "insulated_back")
CONSTRUCTIONS = ("glass_glass", "glass_polymer")

# pvlib.temperature.TEMPERATURE_MODEL_PARAMETERS["sapm"] has exactly these 4 keys —
# not the full 3x2 cross of geometry x construction (checked 23/09). The two
# combinations below have no SAPM entry; sapm_key() returns None for them rather
# than inventing one.
_SAPM_KEYS = {
    ("open_rack", "glass_glass"): "open_rack_glass_glass",
    ("open_rack", "glass_polymer"): "open_rack_glass_polymer",
    ("close_mount", "glass_glass"): "close_mount_glass_glass",
    ("insulated_back", "glass_polymer"): "insulated_back_glass_polymer",
}

# pvlib.temperature.TEMPERATURE_MODEL_PARAMETERS["pvsyst"]: one key per geometry,
# always resolvable.
_PVSYST_KEYS = {
    "open_rack": "freestanding",
    "close_mount": "semi_integrated",
    "insulated_back": "insulated",
}


@dataclass(frozen=True)
class Mounting:
    """geometry/construction plus where each value came from."""

    geometry: str
    geometry_source: str
    construction: str
    construction_source: str


def resolve_mounting(
    geometry: str | None, construction: str | None, defaults: dict
) -> Mounting:
    """Mounting from the user, or the pre-filled defaults for whichever is missing."""
    cfg = defaults["stage3"]["mounting"]

    if geometry is None:
        geometry, geometry_source = cfg["geometry_default"], TAG_DEFAULT
    else:
        geometry_source = TAG_USER_ENTERED
    if geometry not in GEOMETRIES:
        raise ValueError(f"Unknown mounting geometry: {geometry!r}")

    if construction is None:
        construction, construction_source = cfg["construction_default"], TAG_DEFAULT
    else:
        construction_source = TAG_USER_ENTERED
    if construction not in CONSTRUCTIONS:
        raise ValueError(f"Unknown mounting construction: {construction!r}")

    return Mounting(geometry, geometry_source, construction, construction_source)


def sapm_key(mounting: Mounting) -> str | None:
    """SAPM's TEMPERATURE_MODEL_PARAMETERS key, or None if this combination has none."""
    return _SAPM_KEYS.get((mounting.geometry, mounting.construction))


def pvsyst_key(mounting: Mounting) -> str:
    """pvsyst's TEMPERATURE_MODEL_PARAMETERS key. Always resolvable."""
    return _PVSYST_KEYS[mounting.geometry]


def resolve_array_height(user_value: int | None, defaults: dict) -> tuple[int, str]:
    """noct_sam's array_height (storeys, 1 or 2), user-entered or the pre-filled default."""
    if user_value is None:
        return int(defaults["stage3"]["mounting"]["array_height_default"]), TAG_DEFAULT
    return int(user_value), TAG_USER_ENTERED
