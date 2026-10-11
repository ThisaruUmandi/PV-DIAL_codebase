import pytest

from pvdials.config import load_defaults
from pvdials.physics.geometry import TAG_DEFAULT, TAG_USER_ENTERED
from pvdials.physics.mounting import (
    resolve_array_height,
    resolve_mounting,
    sapm_key,
)

DEFAULTS = load_defaults()


def test_defaults_reconstruct_open_rack_glass_polymer():
    mounting = resolve_mounting(None, None, DEFAULTS)

    assert mounting.geometry == "open_rack"
    assert mounting.construction == "glass_polymer"
    assert mounting.geometry_source == TAG_DEFAULT
    assert mounting.construction_source == TAG_DEFAULT
    assert sapm_key(mounting) == "open_rack_glass_polymer"


def test_user_values_are_tagged_user_entered():
    mounting = resolve_mounting("close_mount", "glass_glass", DEFAULTS)

    assert mounting.geometry_source == TAG_USER_ENTERED
    assert mounting.construction_source == TAG_USER_ENTERED
    assert sapm_key(mounting) == "close_mount_glass_glass"


def test_partial_override_only_tags_the_given_value():
    mounting = resolve_mounting("close_mount", None, DEFAULTS)

    assert mounting.geometry == "close_mount"
    assert mounting.geometry_source == TAG_USER_ENTERED
    assert mounting.construction == "glass_polymer"
    assert mounting.construction_source == TAG_DEFAULT


@pytest.mark.parametrize(
    "geometry,construction",
    [("close_mount", "glass_polymer"), ("insulated_back", "glass_glass")],
)
def test_unsupported_sapm_combinations_return_none(geometry, construction):
    from pvdials.physics.mounting import pvsyst_key

    mounting = resolve_mounting(geometry, construction, DEFAULTS)

    assert sapm_key(mounting) is None
    assert pvsyst_key(mounting) is not None  # pvsyst always resolves


@pytest.mark.parametrize("geometry", ["open_rack", "close_mount", "insulated_back"])
def test_pvsyst_key_always_resolves(geometry):
    from pvdials.physics.mounting import pvsyst_key

    mounting = resolve_mounting(geometry, "glass_polymer", DEFAULTS)

    assert pvsyst_key(mounting) in ("freestanding", "semi_integrated", "insulated")


def test_pvsyst_default_geometry_is_freestanding():
    from pvdials.physics.mounting import pvsyst_key

    mounting = resolve_mounting(None, None, DEFAULTS)

    assert pvsyst_key(mounting) == "freestanding"


def test_unknown_geometry_or_construction_is_rejected():
    with pytest.raises(ValueError, match="geometry"):
        resolve_mounting("on_the_roof", None, DEFAULTS)
    with pytest.raises(ValueError, match="construction"):
        resolve_mounting(None, "aluminium", DEFAULTS)


def test_array_height_default_and_override():
    default = resolve_array_height(None, DEFAULTS)
    override = resolve_array_height(2, DEFAULTS)

    assert default == (1, TAG_DEFAULT)
    assert override == (2, TAG_USER_ENTERED)
