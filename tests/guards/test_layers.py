"""Layer guards (KT §4): pvlib stays in physics/, solar position stays in site.py."""

from ._scan import find

PHYSICS = "src/pvdials/physics/"
SITE = "src/pvdials/physics/site.py"


def test_pvlib_imported_only_in_physics():
    hits = [h for h in find(r"^\s*(import|from)\s+pvlib\b") if not h.startswith(PHYSICS)]
    assert not hits, "pvlib imported outside physics/:\n" + "\n".join(hits)


def test_solar_position_only_in_site():
    hits = [h for h in find(r"solarposition") if not h.startswith(SITE + ":")]
    assert not hits, "Solar position used outside physics/site.py:\n" + "\n".join(hits)


def test_pool_view_kept_separate_from_the_serialized_pair_results():
    """Verification property #24, "pool view kept separate": the picker's
    candidate-model view (stageN_pool_view, physics/registry.py) must never
    be wired into the DLA output object (phase1_to_dict/phase2_to_dict/
    phase3_to_dict/build_results_dict) or the report module -- those
    describe what a pair's models actually did, not what else could have
    been picked. guided_reexecution.py's own use of pool_view (O4's
    alternatives_at_stage, a different concern -- candidates for a proposed
    substitution) is not part of this check.
    """
    SERIALIZATION_FILES = ("src/pvdials/analysis.py:", "src/pvdials/report.py:", "src/pvdials/__main__.py:")
    hits = [h for h in find(r"pool_view") if h.startswith(SERIALIZATION_FILES)]
    assert not hits, "pool_view referenced in serialization code:\n" + "\n".join(hits)
