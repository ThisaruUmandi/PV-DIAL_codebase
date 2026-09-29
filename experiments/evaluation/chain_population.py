"""The 2,058-chain population (evaluation KT, section 3: "the 2,058 valid
chains"), and a seeded sample from it.

build_configs() isn't packaged anywhere in src/pvdials/ -- it's duplicated
verbatim in experiments/tau_calibration/tau_ensemble_timing.py and
experiments/pool_scan.py, neither importable without a sys.path hack. This
reimplements it fresh, same registry calls, same fixed hardware, guarded by
an exact-match check (test_chain_population.py) against the existing
labels_n2058_exhaustive.txt.

sample_chains() uses random.Random(seed).sample(...), the same convention
already established in experiments/tau_calibration/n34_calibration.py
(random.sample draws without replacement, matching the KT's own wording).
"""

from __future__ import annotations

import itertools
import random
from pathlib import Path

from pvlib import pvsystem

from pvdials.config import load_defaults
from pvdials.physics.hardware import ADR_INVERTER, CEC, CEC_INVERTER, load_module
from pvdials.physics.mounting import resolve_mounting
from pvdials.physics.registry import (
    stage1_pool_view,
    stage2_pool_view,
    stage3_pool_view,
    stage4_pool_view,
    stage5_pool_view,
)
from pvdials.types import PipelineConfig

MODULE_NAME = "Canadian_Solar_Inc__CS6K_300MS"
INVERTER_NAME = "ABB__PVI_6000_OUTD_S_US_A__208V_"

EXHAUSTIVE_CACHE = (
    Path(__file__).resolve().parents[1]
    / "tau_calibration" / "outputs" / "trivial_plateau_amendment" / "exhaustive_cache"
)
LABELS_FILE = EXHAUSTIVE_CACHE / "labels_n2058_exhaustive.txt"


def build_configs(module, mounting) -> list[PipelineConfig]:
    """Enumerate every valid PipelineConfig for the fixed hardware -- same
    registry calls, same order, as tau_ensemble_timing.py's own build_configs
    (verified byte-identical against labels_n2058_exhaustive.txt).
    """
    cec_inverters = pvsystem.retrieve_sam(CEC_INVERTER)
    adr_inverters = pvsystem.retrieve_sam(ADR_INVERTER)

    stage1 = [c.name for c in stage1_pool_view() if c.selectable]
    stage2 = [c.name for c in stage2_pool_view() if c.selectable]
    stage3 = [c.name for c in stage3_pool_view(module, mounting) if c.selectable]
    stage4 = [c.name for c in stage4_pool_view(module) if c.selectable]

    configs = []
    index = 0
    for s1, s2, s3, s4 in itertools.product(stage1, stage2, stage3, stage4):
        stage5 = [
            c.name
            for c in stage5_pool_view(INVERTER_NAME, cec_inverters, adr_inverters, s4)
            if c.selectable
        ]
        for s5 in stage5:
            index += 1
            configs.append(
                PipelineConfig(
                    label=f"chain-{index:04d}",
                    decomposition_model=s1,
                    transposition_model=s2,
                    temperature_model=s3,
                    dc_model=s4,
                    ac_model=s5,
                )
            )
    return configs


def default_hardware():
    """The fixed module/mounting every chain in the population is built
    against -- matches analysis.yaml's own hardware section.
    """
    module = load_module(CEC, MODULE_NAME)
    mounting = resolve_mounting(None, None, load_defaults())
    return module, mounting


def load_cached_labels() -> list[str]:
    return LABELS_FILE.read_text().splitlines()


def sample_chains(labels: list[str], n: int, seed: int) -> list[str]:
    """n labels drawn without replacement -- the project's own established
    convention (experiments/tau_calibration/n34_calibration.py).
    """
    return random.Random(seed).sample(labels, n)


if __name__ == "__main__":
    module, mounting = default_hardware()
    configs = build_configs(module, mounting)
    cached_labels = load_cached_labels()
    print(f"Regenerated {len(configs)} configs; cache has {len(cached_labels)} labels.")
    print(f"Labels match exactly: {[c.label for c in configs] == cached_labels}")
