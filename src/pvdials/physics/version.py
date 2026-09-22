"""Check the installed pvlib matches the pinned version."""

from __future__ import annotations

import pvlib

from pvdials.config import load_defaults


def check_pvlib_version(defaults: dict | None = None) -> str:
    """Raise if the installed pvlib differs from the pinned version."""
    defaults = defaults or load_defaults()
    pinned = defaults["versions"]["pvlib"]
    if pvlib.__version__ != pinned:
        raise RuntimeError(
            f"pvlib {pvlib.__version__} installed, but {pinned} is pinned in run_defaults.yaml"
        )
    return pinned
