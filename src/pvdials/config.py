"""Load run defaults and check the environment matches them."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULTS_PATH = ROOT / "configs" / "run_defaults.yaml"


def load_defaults(path: Path = DEFAULTS_PATH) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def check_pvlib_version(defaults: dict | None = None) -> str:
    """Raise if the installed pvlib differs from the pinned version."""
    import pvlib

    defaults = defaults or load_defaults()
    pinned = defaults["versions"]["pvlib"]
    if pvlib.__version__ != pinned:
        raise RuntimeError(
            f"pvlib {pvlib.__version__} installed, but {pinned} is pinned in run_defaults.yaml"
        )
    return pinned