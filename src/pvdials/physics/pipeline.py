"""The pipeline runner (KT Step 5): wires the five stage adapters together.

Runs ONE pipeline. Running A, B, C together and keeping every output (KT §5)
is the orchestrator's job, not this module's. SharedInputs holds everything
comparison-level — built once by the caller and reused across every
PipelineConfig, so calling run_pipeline three times for A/B/C never rebuilds
the SiteContext or re-picks the hardware (D6, §7.4).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from pvdials.data.validate import (
    ValidationResult,
    validate_ac_not_exceeding_dc,
    validate_post_dc,
    validate_post_decomposition,
    validate_post_temperature,
    validate_post_transposition,
)
from pvdials.physics.adapters.ac import ACResult, ac_power
from pvdials.physics.adapters.dc import DCResult, dc_power
from pvdials.physics.adapters.decomposition import DecompositionResult, decompose
from pvdials.physics.adapters.temperature import TemperatureResult, cell_temperature
from pvdials.physics.adapters.transposition import TranspositionResult, transpose
from pvdials.physics.geometry import Albedo, ArrayGeometry
from pvdials.physics.hardware import ArraySize, InverterRecord, ModuleRecord
from pvdials.physics.mounting import Mounting
from pvdials.physics.site import SiteContext
from pvdials.types import PipelineConfig


@dataclass(frozen=True)
class SharedInputs:
    """Everything comparison-level: the same weather, site and physical
    hardware for every pipeline in a comparison. Build once, reuse for A/B/C.

    inverter/module_height_m/array_height are optional because they're only
    needed by some model choices (sandia/adr; fuentes; noct_sam) — the
    adapters themselves raise clearly if a chosen model needs one that's
    missing.
    """

    weather: pd.DataFrame
    ctx: SiteContext
    geometry: ArrayGeometry
    albedo: Albedo
    mounting: Mounting
    module: ModuleRecord
    array_size: ArraySize
    inverter: InverterRecord | None = None
    module_height_m: float | None = None
    array_height: int | None = None


@dataclass(frozen=True)
class StageOutputs:
    """The five adapter results, unchanged from Stages 1-5 (4.1-4.5)."""

    decomposition: DecompositionResult
    transposition: TranspositionResult
    temperature: TemperatureResult
    dc: DCResult
    ac: ACResult


@dataclass(frozen=True)
class PipelineResult:
    """config: what was run. outputs: every stage's result. validations: every
    sanity/regression check that takes only stage output, run automatically.
    """

    config: PipelineConfig
    outputs: StageOutputs
    validations: dict[str, ValidationResult]


def run_pipeline(
    config: PipelineConfig, shared: SharedInputs, defaults: dict | None = None
) -> PipelineResult:
    """Run one pipeline's five stages in order and collect the results.

    Tier 4 (physical consistency) isn't re-run here — it's about the weather/
    SiteContext, identical for every pipeline in a comparison, so it belongs
    at the comparison level, run once, not duplicated per pipeline.
    """
    decomposition = decompose(config.decomposition_model, shared.weather, shared.ctx, defaults)
    transposition = transpose(
        config.transposition_model,
        shared.weather,
        decomposition,
        shared.ctx,
        shared.geometry,
        shared.albedo,
        defaults,
    )
    temperature = cell_temperature(
        config.temperature_model,
        transposition,
        shared.weather,
        shared.mounting,
        shared.geometry,
        module=shared.module,
        module_height_m=shared.module_height_m,
        array_height=shared.array_height,
        defaults=defaults,
    )
    dc = dc_power(
        config.dc_model,
        transposition,
        temperature,
        shared.ctx,
        shared.module,
        modules_per_string=shared.array_size.modules_per_string,
        strings_per_inverter=shared.array_size.strings_per_inverter,
        defaults=defaults,
    )
    ac = ac_power(
        config.ac_model,
        dc,
        inverter=shared.inverter,
        module=shared.module,
        array_size=shared.array_size,
        defaults=defaults,
    )

    validations = {
        "decomposition": validate_post_decomposition(decomposition.outputs),
        "transposition": validate_post_transposition(transposition.outputs),
        "temperature": validate_post_temperature(temperature.outputs, shared.weather),
        "dc": validate_post_dc(dc.outputs),
        "ac_not_exceeding_dc": validate_ac_not_exceeding_dc(ac.outputs, dc.outputs),
    }

    outputs = StageOutputs(
        decomposition=decomposition, transposition=transposition, temperature=temperature, dc=dc, ac=ac
    )
    return PipelineResult(config=config, outputs=outputs, validations=validations)
