"""Stage 1 settings must stay consistent with the decisions that depend on them."""

import inspect
import math

import pvlib

from pvdials.config import load_defaults
from pvdials.physics.registry import stage_pool
from pvdials.types import Stage

DEFAULTS = load_defaults()
STAGE1 = {k: v for k, v in DEFAULTS["stage1"].items() if isinstance(v, dict)}


def _guard_zenith(coefficients: dict) -> float:
    limits = [coefficients["max_zenith"]]
    if "min_cos_zenith" in coefficients:
        limits.append(math.degrees(math.acos(coefficients["min_cos_zenith"])))
    return min(limits)


def test_every_selectable_model_has_coefficients_and_no_others():
    selectable = {c.name for c in stage_pool(Stage.DECOMPOSITION) if c.selectable}
    assert set(STAGE1) == selectable


def test_daylight_mask_is_inside_every_stage1_guard():
    # The 85 deg cut-off (23/09) was justified against these guards
    mask_max = DEFAULTS["dla"]["daylight_mask_zenith_max_deg"]
    for model, coefficients in STAGE1.items():
        assert mask_max < _guard_zenith(coefficients), model


def test_extraterrestrial_settings_match_pvlib_internal_default():
    # erbs, boland and louche compute ET-DNI internally with pvlib's defaults
    params = inspect.signature(pvlib.irradiance.get_extra_radiation).parameters
    assert DEFAULTS["extraterrestrial"]["method"] == params["method"].default
    assert DEFAULTS["extraterrestrial"]["solar_constant_w_m2"] == params["solar_constant"].default
