"""Core shared types."""

from __future__ import annotations

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