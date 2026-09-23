from pvdials.physics.registry import stage_pool
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
