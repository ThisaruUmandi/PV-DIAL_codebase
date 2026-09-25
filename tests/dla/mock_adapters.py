"""Mock stage models for the DLA's constructed cases (KT §14, C1-C5).

Test-only infrastructure: never imported by pvdials.dla or any shipped
module. Monkeypatches the adapter functions as imported into
physics.pipeline, so a registered mock model name flows through
run_pipeline() exactly like a real one -- same Result dataclasses, same
call shape -- with an output computed as output * (1+delta) or output +
delta (KT's own two forms), relative to a real baseline model's own output,
never a fresh pvlib computation.

Installing a mock at one stage never touches other stages or other model
names at the same stage: any model name that isn't the registered mock
still calls the real adapter unchanged.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Literal

import pvdials.physics.pipeline as pipeline_module
from pvdials.types import Stage

Mode = Literal["multiplicative", "additive"]

_ADAPTER_ATTR = {
    Stage.DECOMPOSITION: "decompose",
    Stage.TRANSPOSITION: "transpose",
    Stage.TEMPERATURE: "cell_temperature",
    Stage.DC: "dc_power",
    Stage.AC: "ac_power",
}


def _perturb(outputs, delta: float, mode: Mode):
    if mode == "multiplicative":
        return outputs * (1.0 + delta)
    if mode == "additive":
        return outputs + delta
    raise ValueError(f"Unknown perturbation mode: {mode!r}")


def install_mock_model(
    monkeypatch,
    stage: Stage,
    mock_name: str,
    real_model: str,
    delta: float,
    mode: Mode = "multiplicative",
) -> None:
    """Register mock_name at `stage`: real_model's own output, perturbed by delta."""
    attr = _ADAPTER_ATTR[stage]
    real_function = getattr(pipeline_module, attr)

    def wrapped(model, *args, **kwargs):
        if model != mock_name:
            return real_function(model, *args, **kwargs)
        baseline = real_function(real_model, *args, **kwargs)
        perturbed_outputs = _perturb(baseline.outputs, delta, mode)
        records = dict(baseline.records)
        records.update(
            {"model": mock_name, "mock": True, "base_model": real_model, "delta": delta, "mode": mode}
        )
        return replace(baseline, outputs=perturbed_outputs, records=records)

    monkeypatch.setattr(pipeline_module, attr, wrapped)
