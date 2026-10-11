from pvlib import pvsystem

from pvdials.config import load_defaults
from pvdials.physics.hardware import ADR_INVERTER, CEC, CEC_INVERTER, SANDIA, ModuleRecord
from pvdials.physics.mounting import resolve_mounting
from pvdials.physics.registry import (
    stage3_selectable,
    stage4_selectable,
    stage5_selectable,
    stage_pool,
)
from pvdials.types import Stage

STAGE1_POOL_ORDER = [
    "erbs",
    "erbs_driesse",
    "disc",
    "dirint",
    "dirindex",
    "boland",
    "louche",
    "orgill_hollands",
    "campbell_norman",
    "gti_dirint",
]


def test_stage1_pool_is_in_pool_order():
    assert [c.name for c in stage_pool(Stage.DECOMPOSITION)] == STAGE1_POOL_ORDER


def test_non_selectable_models_are_shown_with_a_reason():
    pool = stage_pool(Stage.DECOMPOSITION)
    shown = {c.name for c in pool if not c.selectable}

    assert shown == {"dirindex", "campbell_norman", "gti_dirint"}
    assert all(c.reason for c in pool if not c.selectable)
    assert all(c.reason is None for c in pool if c.selectable)


STAGE2_POOL_ORDER = [
    "isotropic",
    "klucher",
    "haydavies",
    "reindl",
    "king",
    "perez",
    "perez-driesse",
]


def test_stage2_pool_is_in_pool_order():
    assert [c.name for c in stage_pool(Stage.TRANSPOSITION)] == STAGE2_POOL_ORDER


def test_stage2_has_no_misfits():
    assert all(c.selectable and c.reason is None for c in stage_pool(Stage.TRANSPOSITION))


STAGE3_POOL_ORDER = [
    "faiman",
    "faiman_rad",
    "fuentes",
    "generic_linear",
    "noct_sam",
    "prilliman",
    "pvsyst_cell",
    "ross",
    "sapm_cell",
]

CEC_MODULES = pvsystem.retrieve_sam(CEC)
CEC_NAME = "Canadian_Solar_Inc__CS6K_300MS"
CEC_MODULE = ModuleRecord(CEC, CEC_NAME, CEC_MODULES[CEC_NAME])

SANDIA_MODULES = pvsystem.retrieve_sam(SANDIA)
SANDIA_NAME = SANDIA_MODULES.columns[0]
SANDIA_MODULE = ModuleRecord(SANDIA, SANDIA_NAME, SANDIA_MODULES[SANDIA_NAME])

DEFAULT_MOUNTING = resolve_mounting(None, None, load_defaults())


def test_stage3_pool_is_in_pool_order():
    assert [c.name for c in stage_pool(Stage.TEMPERATURE)] == STAGE3_POOL_ORDER


def test_stage3_structural_exclusions_are_shown_with_a_reason():
    pool = stage_pool(Stage.TEMPERATURE)
    shown = {c.name for c in pool if not c.selectable}

    assert shown == {"faiman_rad", "generic_linear", "prilliman"}
    assert all(c.reason for c in pool if not c.selectable)
    assert all(c.reason is None for c in pool if c.selectable)


def test_stage3_noct_gated_models_need_cec_module():
    for model in ("fuentes", "noct_sam", "ross"):
        ok, reason = stage3_selectable(model, CEC_MODULE, DEFAULT_MOUNTING)
        assert ok and reason is None

        ok, reason = stage3_selectable(model, SANDIA_MODULE, DEFAULT_MOUNTING)
        assert not ok
        assert "NOCT" in reason


def test_stage3_sapm_cell_gated_by_mounting_combination():
    unsupported = resolve_mounting("close_mount", "glass_polymer", load_defaults())

    ok, reason = stage3_selectable("sapm_cell", CEC_MODULE, DEFAULT_MOUNTING)
    assert ok and reason is None

    ok, reason = stage3_selectable("sapm_cell", CEC_MODULE, unsupported)
    assert not ok
    assert "SAPM" in reason


def test_stage3_unconditional_models_always_selectable():
    for model in ("faiman", "pvsyst_cell"):
        ok, reason = stage3_selectable(model, None, DEFAULT_MOUNTING)
        assert ok and reason is None


STAGE4_POOL_ORDER = [
    "pvwatts_dc",
    "sapm",
    "singlediode_desoto",
    "singlediode_cec",
    "singlediode_pvsyst",
]


def test_stage4_pool_is_in_pool_order():
    assert [c.name for c in stage_pool(Stage.DC)] == STAGE4_POOL_ORDER


def test_stage4_static_exclusion_is_singlediode_pvsyst_only():
    pool = stage_pool(Stage.DC)
    shown = {c.name for c in pool if not c.selectable}

    assert shown == {"singlediode_pvsyst"}
    assert "gamma_ref" in pool[-1].reason
    assert all(c.reason is None for c in pool if c.selectable)


def test_stage4_sapm_gated_to_sandia():
    ok, reason = stage4_selectable("sapm", SANDIA_MODULE)
    assert ok and reason is None

    ok, reason = stage4_selectable("sapm", CEC_MODULE)
    assert not ok
    assert "SAPM" in reason


def test_stage4_singlediode_gated_to_cec():
    for model in ("singlediode_desoto", "singlediode_cec"):
        ok, reason = stage4_selectable(model, CEC_MODULE)
        assert ok and reason is None

        ok, reason = stage4_selectable(model, SANDIA_MODULE)
        assert not ok
        assert "CEC" in reason


def test_stage4_pvwatts_dc_selectable_for_both_libraries():
    for module in (CEC_MODULE, SANDIA_MODULE):
        ok, reason = stage4_selectable("pvwatts_dc", module)
        assert ok and reason is None


STAGE5_POOL_ORDER = ["sandia", "adr", "pvwatts"]


def test_stage5_pool_is_in_pool_order():
    assert [c.name for c in stage_pool(Stage.AC)] == STAGE5_POOL_ORDER


def test_stage5_has_no_static_exclusions():
    assert all(c.selectable and c.reason is None for c in stage_pool(Stage.AC))


def test_stage5_sandia_and_adr_need_v_dc():
    for model in ("sandia", "adr"):
        ok, reason = stage5_selectable(model, {CEC_INVERTER, ADR_INVERTER}, dc_has_v_dc=False)
        assert not ok
        assert "v_dc" in reason


def test_stage5_sandia_needs_cec_inverter_library():
    ok, reason = stage5_selectable("sandia", {ADR_INVERTER}, dc_has_v_dc=True)
    assert not ok
    assert "CECInverter" in reason

    ok, reason = stage5_selectable("sandia", {CEC_INVERTER, ADR_INVERTER}, dc_has_v_dc=True)
    assert ok and reason is None


def test_stage5_adr_needs_adr_inverter_library():
    ok, reason = stage5_selectable("adr", set(), dc_has_v_dc=True)
    assert not ok
    assert "ADRInverter" in reason

    ok, reason = stage5_selectable("adr", {ADR_INVERTER}, dc_has_v_dc=True)
    assert ok and reason is None


def test_stage5_pvwatts_always_selectable():
    ok, reason = stage5_selectable("pvwatts", set(), dc_has_v_dc=False)
    assert ok and reason is None
