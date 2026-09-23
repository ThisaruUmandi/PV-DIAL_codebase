from pvlib import pvsystem

from pvdials.config import load_defaults
from pvdials.physics.hardware import CEC, SANDIA, ModuleRecord
from pvdials.physics.mounting import resolve_mounting
from pvdials.physics.registry import stage3_selectable, stage_pool
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
