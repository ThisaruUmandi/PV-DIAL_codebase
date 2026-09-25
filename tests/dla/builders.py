"""Shared test fixtures for the dla/ test suite.

make_pipeline_result() builds a real PipelineResult from real StageOutputs
and real per-stage Result dataclasses (DecompositionResult etc., from
physics/adapters/*.py) with fabricated DataFrames — never a parallel
dict-like stand-in, so Phase 1/2 are tested against the exact type
contracts they see in production.
"""

from __future__ import annotations

import pandas as pd

from pvdials.physics.adapters.ac import ACResult
from pvdials.physics.adapters.dc import DCResult
from pvdials.physics.adapters.decomposition import DecompositionResult
from pvdials.physics.adapters.temperature import TemperatureResult
from pvdials.physics.adapters.transposition import TranspositionResult
from pvdials.physics.pipeline import PipelineResult, StageOutputs
from pvdials.types import PipelineConfig

DEFAULT_INDEX = pd.date_range("2023-06-21 08:00", periods=6, freq="h", tz="UTC")


def make_pipeline_result(
    label: str,
    *,
    decomposition_model: str = "erbs",
    transposition_model: str = "isotropic",
    temperature_model: str = "faiman",
    dc_model: str = "singlediode_cec",
    ac_model: str = "sandia",
    dni: list[float],
    dhi: list[float],
    poa_global: list[float],
    temp_cell: list[float],
    p_dc: list[float],
    p_ac: list[float],
    index: pd.DatetimeIndex = DEFAULT_INDEX,
) -> PipelineResult:
    """Build a real PipelineResult with fabricated stage outputs."""
    config = PipelineConfig(
        label=label,
        decomposition_model=decomposition_model,
        transposition_model=transposition_model,
        temperature_model=temperature_model,
        dc_model=dc_model,
        ac_model=ac_model,
    )
    decomposition = DecompositionResult(
        outputs=pd.DataFrame({"dni": dni, "dhi": dhi}, index=index), records={}
    )
    transposition = TranspositionResult(
        outputs=pd.DataFrame({"poa_global": poa_global}, index=index), records={}
    )
    temperature = TemperatureResult(
        outputs=pd.DataFrame({"temp_cell": temp_cell}, index=index), records={}
    )
    dc = DCResult(outputs=pd.DataFrame({"p_dc": p_dc}, index=index), records={})
    ac = ACResult(outputs=pd.DataFrame({"p_ac": p_ac}, index=index), records={})

    outputs = StageOutputs(
        decomposition=decomposition, transposition=transposition, temperature=temperature, dc=dc, ac=ac
    )
    return PipelineResult(config=config, outputs=outputs, validations={})


def all_daylight(index: pd.DatetimeIndex = DEFAULT_INDEX) -> pd.Series:
    """A daylight mask that's True for every row — the common test case."""
    return pd.Series(True, index=index)
