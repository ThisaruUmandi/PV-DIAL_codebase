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
