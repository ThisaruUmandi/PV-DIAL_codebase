import pvlib

from pvdials.config import load_defaults
from pvdials.physics.version import check_pvlib_version
from pvdials.types import ExecutionSet, Stage


def test_pvlib_matches_pin():
    assert check_pvlib_version() == pvlib.__version__


def test_defaults_load():
    d = load_defaults()
    assert d["solar_position"]["method"] == "nrel_numpy"


def test_five_stages_in_order():
    assert [s.value for s in Stage] == [1, 2, 3, 4, 5]


def test_three_execution_sets():
    assert {e.value for e in ExecutionSet} == {"original", "derived", "reexec"}
    