"""Model adapters: one module per stage, uniform interface over pvlib."""

from __future__ import annotations


class AdapterError(Exception):
    """Raised when a model can't be run in a given stage slot."""
