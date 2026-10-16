"""Locate the Caltrans standard-plan tables the production-catalog tests validate.

The tables (hand-transcribed from the Caltrans 2025 Standard Plans, ~70 KB of
YAML) are repository data, not package data: they live at
``data/caltrans-2025/tables/`` in whichever repository carries bimforge — the
estimating monorepo or the standalone public repo, whose layouts put that
directory at different depths relative to this file. Resolution order:

1. ``$BIMFORGE_CALTRANS_TABLES`` — an explicit directory;
2. the first ``data/caltrans-2025/tables`` found walking up from this file.

A test that needs a table calls :func:`require_caltrans_table`, which skips
(never errors) when the catalog is not present.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

_REL = Path("data") / "caltrans-2025" / "tables"


def caltrans_tables_dir() -> Path | None:
    env = os.environ.get("BIMFORGE_CALTRANS_TABLES")
    if env:
        p = Path(env)
        return p if p.is_dir() else None
    for parent in Path(__file__).resolve().parents:
        cand = parent / _REL
        if cand.is_dir():
            return cand
    return None


def caltrans_table(name: str) -> Path | None:
    """Path to ``<tables>/<name>`` or None when the catalog is absent."""
    d = caltrans_tables_dir()
    if d is None:
        return None
    p = d / name
    return p if p.is_file() else None


def require_caltrans_table(name: str) -> Path:
    """The table's path, or ``pytest.skip`` when it is not available."""
    p = caltrans_table(name)
    if p is None:
        pytest.skip(f"Caltrans catalog {name} not present (set BIMFORGE_CALTRANS_TABLES)")
    return p
