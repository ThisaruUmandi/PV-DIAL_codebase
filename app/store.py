"""Thin access to the provenance store for pages. S2 only checks reachability."""

from __future__ import annotations

from pvdials.provenance.db import is_reachable


def db_reachable() -> bool:
    return is_reachable()
