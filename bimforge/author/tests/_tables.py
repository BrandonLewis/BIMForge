"""Locate the Caltrans standard-plan tables the production-catalog tests validate.

The tables ship in the wheel as `bimforge.caltrans` package data. Set
``$BIMFORGE_CALTRANS_TABLES`` to a directory to validate another copy (a new
edition being transcribed, say); a test then skips when that directory lacks
the table it needs.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from bimforge import caltrans


def caltrans_tables_dir() -> Path | None:
    env = os.environ.get("BIMFORGE_CALTRANS_TABLES")
    p = Path(env) if env else Path(str(caltrans.tables_dir()))
    return p if p.is_dir() else None


def caltrans_table(name: str) -> Path | None:
    """Path to ``<tables>/<name>`` or None when it is absent."""
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
