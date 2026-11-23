"""The V1.1 road corridor builds as it did before the path (P.6, part C).

fixtures/road-corridor-v11/ holds the shipped example as V1.1 shipped it,
its spec and paycodes copied before part C changed the example, and what it
built then: every element's and root's GlobalId, every element's
Qto_BaseQuantities GrossVolume, and the mass-haul, walls, structures and
guardrail tables. Every part C key is optional: without `path` the corridor
builds the same elements, GlobalIds, quantities and tables. The only change
is two new columns, `location` in the walls table and `carries` in the
structures table, which are dropped before comparing.
"""
from __future__ import annotations

import contextlib
import csv
import io
import json
import shutil
from pathlib import Path

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

FIXTURE = Path(__file__).parent / "fixtures" / "road-corridor-v11"
SPEC = "road-corridor.spec.yaml"


def _recorded(name: str):
    return json.loads((FIXTURE / name).read_text("utf-8"))


def _rows(text: str, drop: str | None = None) -> list:
    """The CSV's rows, the column `drop` taken out where it is there."""
    rows = list(csv.reader(io.StringIO(text)))
    if drop is not None and drop in rows[0]:
        k = rows[0].index(drop)
        rows = [r[:k] + r[k + 1:] for r in rows]
    return rows


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    from bimforge.author.families.registry import build_from_spec
    tmp = tmp_path_factory.mktemp("v11")
    for name in (SPEC, "road-corridor.paycodes.yaml"):
        shutil.copy(FIXTURE / name, tmp / name)
    with contextlib.redirect_stderr(io.StringIO()):
        assert build_from_spec(str(tmp / SPEC)) == 0
    return ifcopenshell.open(str(tmp / "out" / "road-corridor.ifc")), tmp / "out"


def test_every_v11_element_keeps_its_globalid(built):
    f, _out = built
    was = _recorded("globalids.json")["elements"]
    now = {el.Name: el.GlobalId for el in f.by_type("IfcElement")}
    assert now == was                             # none moved, none added


def test_every_v11_root_keeps_its_globalid(built):
    f, _out = built
    moved = {}
    for gid, cls in _recorded("globalids.json")["roots"].items():
        try:
            ent = f.by_guid(gid)
        except RuntimeError:
            moved[gid] = (cls, None)
            continue
        if ent.is_a() != cls:
            moved[gid] = (cls, ent.is_a())
    assert not moved, f"{len(moved)} V1.1 root(s) moved or dropped: {moved}"


def test_every_v11_volume_is_unchanged(built):
    import ifcopenshell.util.element as E
    f, _out = built
    now = {}
    for el in f.by_type("IfcElement"):
        base = E.get_psets(el, qtos_only=True).get("Qto_BaseQuantities", {})
        if "GrossVolume" in base:
            now[el.Name] = base["GrossVolume"]
    was = _recorded("volumes.json")
    assert set(now) == set(was)
    for name, v in was.items():
        assert now[name] == pytest.approx(v, rel=1e-9), name


@pytest.mark.parametrize("key, drop", [("masshaul", None), ("guardrail", None),
                                       ("walls", "location"),
                                       ("structures", "carries")])
def test_every_v11_table_is_unchanged(built, key, drop):
    _f, out = built
    now = (out / f"road-corridor.{key}.csv").read_text("utf-8")
    was = (FIXTURE / f"{key}.csv").read_text("utf-8")
    assert _rows(now, drop) == _rows(was, drop)
