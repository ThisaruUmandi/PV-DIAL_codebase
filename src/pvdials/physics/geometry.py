"""Array geometry and ground albedo for Stage 2 (transposition).

Tilt and azimuth are genuine site-design choices with no defensible
universal default (N40, decided 23/09): always user-entered, never
detected from the weather file and never pre-filled.

Albedo is user-entered too, but with a sensible pre-filled default
(0.2, generic ground; decided 23/09 — not pvlib's own 0.25) so it stays
optional rather than blocking a run.
"""

from __future__ import annotations

from dataclasses import dataclass

from pvdials.data.column_mapper import TAG_USER_ENTERED

TAG_DEFAULT = "default"


@dataclass(frozen=True)
class ArrayGeometry:
    """Tilt and azimuth for the shared array. Always user-entered (N40)."""

    surface_tilt_deg: float
    surface_azimuth_deg: float


@dataclass(frozen=True)
class Albedo:
    """Ground albedo. source: TAG_DEFAULT (unchanged pre-fill) or TAG_USER_ENTERED."""

    value: float
    source: str


def resolve_albedo(user_value: float | None, defaults: dict) -> Albedo:
    """Albedo from the user, or the pre-filled default if none was given."""
    if user_value is None:
        return Albedo(float(defaults["stage2"]["albedo_default"]), TAG_DEFAULT)
    return Albedo(float(user_value), TAG_USER_ENTERED)
