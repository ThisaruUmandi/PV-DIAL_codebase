"""Core shared types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum


class Stage(IntEnum):
    "The five pipeline stages, in execution order."

    DECOMPOSITION = 1
    TRANSPOSITION = 2
    TEMPERATURE = 3
    DC = 4
    AC = 5


class ExecutionSet(str, Enum):
    """The three execution sets. They are never pooled (N10)."""

    ORIGINAL = "original"
    DERIVED = "derived"
    REEXEC = "reexec"


@dataclass(frozen=True)
class PipelineConfig:
    """One pipeline's model choice at each of the five stages.

    Immutable once created (KT §4): an O4 variant is built from an original,
    never edited in place. Only the model names vary between A/B/C — the
    physical/site setup (weather, hardware, geometry) is shared across every
    pipeline in a comparison (D6, §7.4), so it isn't held here.
    """

    label: str  # "A", "B", "C", or a variant label later (O4)
    decomposition_model: str
    transposition_model: str
    temperature_model: str
    dc_model: str
    ac_model: str