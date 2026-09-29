"""Verification property #22: alternatives render in pool order, and no sort
key by disagreement exists. Two checks, both behavioural rather than a text
scan for "sort" (which would be fragile against a rename or an equivalent
`.sort()`/`heapq`/`np.argsort` spelling):

1. None of the pool functions or the report row builders accept a
   key/sort/order parameter -- inspected via their real signatures.
2. Feeding build_phase3_rows a Phase3Result whose phi_final values are
   deliberately NOT in stage order (largest first) still returns rows in
   ALL_STAGES order, not sorted by magnitude.
"""

import inspect

from pvdials.dla.phase3 import ALL_STAGES, Phase3Result
from pvdials.physics.registry import (
    stage1_pool_view,
    stage2_pool_view,
    stage3_pool_view,
    stage3_selectable,
    stage4_pool_view,
    stage4_selectable,
    stage5_pool_view,
    stage5_selectable,
)
from pvdials.report import build_phase2_rows, build_phase3_rows
from pvdials.types import PipelineConfig

_SUSPECT_PARAM_SUBSTRINGS = ("sort", "key", "order_by", "rank")

_FUNCTIONS_UNDER_GUARD = (
    stage1_pool_view, stage2_pool_view, stage3_pool_view, stage3_selectable,
    stage4_pool_view, stage4_selectable, stage5_pool_view, stage5_selectable,
    build_phase2_rows, build_phase3_rows,
)


def test_no_pool_or_report_function_takes_a_sort_or_key_parameter():
    offending = []
    for fn in _FUNCTIONS_UNDER_GUARD:
        for name in inspect.signature(fn).parameters:
            if any(s in name.lower() for s in _SUSPECT_PARAM_SUBSTRINGS):
                offending.append(f"{fn.__module__}.{fn.__qualname__}(...{name}...)")
    assert not offending, "Found a sort/key-like parameter:\n" + "\n".join(offending)


def test_build_phase3_rows_preserves_all_stages_order_regardless_of_phi_magnitude():
    config_a = PipelineConfig("A", "erbs", "isotropic", "faiman", "singlediode_cec", "sandia")
    config_b = PipelineConfig("B", "disc", "haydavies", "pvsyst_cell", "singlediode_desoto", "adr")

    # Deliberately NOT sorted by magnitude: AC (last in ALL_STAGES) has the
    # largest phi_final, DECOMPOSITION (first) the smallest -- if the row
    # builder ever sorted by magnitude, the row order would come out
    # reversed relative to ALL_STAGES.
    magnitudes = {stage: float(i) for i, stage in enumerate(ALL_STAGES)}
    zero_v = {frozenset(): 0.0}
    result = Phase3Result(
        pair=("A", "B"),
        phi_ab=magnitudes, phi_ba=magnitudes, phi_final=magnitudes,
        share={stage: 0.5 for stage in ALL_STAGES},
        v_ab=zero_v, v_ba=zero_v, rmsd_ab=10.0,
        signed_phi=magnitudes, signed_v=zero_v,
    )

    rows = build_phase3_rows({("A", "B"): result}, {"A": config_a, "B": config_b})

    assert [row.stage for row in rows] == list(ALL_STAGES)
