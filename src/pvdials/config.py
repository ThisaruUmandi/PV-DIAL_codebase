"""Load run defaults."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULTS_PATH = ROOT / "configs" / "run_defaults.yaml"


def load_defaults(path: Path = DEFAULTS_PATH) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)
