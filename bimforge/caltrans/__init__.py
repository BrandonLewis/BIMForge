"""Caltrans Standard Plans: the tables the standard-plan families read.

The pack ships the dimension, quantity and reinforcement tables transcribed
from the Caltrans Standard Plans, so a spec names a table and needs no file of
its own:

    family: pipe-headwall
    params:
      tables_pack: caltrans/2025/d89-pipe-headwall

or, from python:

    from bimforge import caltrans
    rows = caltrans.load_table("d89-pipe-headwall")

Each edition of the Standard Plans is a directory under `tables/`; a table's
name is the standard plan it transcribes. Which sheets each table came from,
with the URL and sha256 of every DGN, is recorded in
`data/caltrans-2025/manifest.json` in the source repository. The tables are a
public-agency source: cite the edition when you use them.

This package holds what is specific to Caltrans and nothing a family needs to
build without it, so it can become a distribution of its own later.
"""
from __future__ import annotations

from importlib.resources import files
from importlib.resources.abc import Traversable

import yaml

SOURCE = ("California Department of Transportation, Standard Plans: "
          "https://dot.ca.gov/programs/design/"
          "ccs-standard-plans-and-standard-specifications")

# edition -> table name -> file under tables/<edition>/
EDITIONS: dict[str, dict[str, str]] = {
    "2025": {
        "b3-retaining-wall": "caltrans-b3-tables.yaml",
        "d80-box-culvert": "caltrans-d80-box-culvert.yaml",
        "d84-wingwall": "caltrans-d84-wingwall.yaml",
        "d89-pipe-headwall": "caltrans-d89-pipe-headwall.yaml",
        "d90-headwall": "caltrans-d90-headwall.yaml",
    },
}
EDITION = "2025"    # the edition a call that names none reads


def tables_dir(edition: str = EDITION) -> Traversable:
    """The directory holding one edition's tables."""
    _tables(edition)
    return files(__name__) / "tables" / edition


def table_names(edition: str = EDITION) -> list[str]:
    return sorted(_tables(edition))


def table_path(name: str, edition: str = EDITION) -> Traversable:
    """The YAML file of one table, by its standard-plan name."""
    tables = _tables(edition)
    if name not in tables:
        raise KeyError(f"no Caltrans {edition} table {name!r}; "
                       f"have {', '.join(sorted(tables))}")
    return files(__name__) / "tables" / edition / tables[name]


def load_table(name: str, edition: str = EDITION) -> dict:
    """One table, parsed. A fresh mapping on every call."""
    return yaml.safe_load(table_path(name, edition).read_text(encoding="utf-8"))


def load_ref(ref: str) -> dict:
    """The table a spec's `tables_pack` names after the pack:
    `<edition>/<table>`, or `<table>` alone for the current edition."""
    edition, _, name = ref.rpartition("/")
    return load_table(name, edition or EDITION)


def _tables(edition: str) -> dict[str, str]:
    edition = str(edition)
    if edition not in EDITIONS:
        raise KeyError(f"no Caltrans Standard Plans edition {edition!r}; "
                       f"have {', '.join(sorted(EDITIONS))}")
    return EDITIONS[edition]
