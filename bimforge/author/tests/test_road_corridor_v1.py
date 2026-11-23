"""The V1 road corridor builds as it did before V1.1 (P.6).

fixtures/road-corridor-v1/ holds the shipped example as V1 shipped it, its
spec and paycodes copied before V1.1 changed the example, and what it built
then: every element's and root's GlobalId, every element's
Qto_BaseQuantities GrossVolume, and the mass-haul CSV. V1.1's keys are all
optional: without them the corridor builds the same bodies, the same
earthwork quantities and mass haul, and the same GlobalIds. V1.1 may ADD
roots (the dimension sets and the class references, written after the
GlobalId sweep); it may not move or drop one, and it adds no element. One
quantity changes on purpose: a course declares its exact volume (V1.1
Task 10), which V1's chorded mesh was within 0.125% of, so a course's
volume is held to 0.5% and every other volume exactly.
"""
from __future__ import annotations

import contextlib
import io
import json
import shutil
from pathlib import Path

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

FIXTURE = Path(__file__).parent / "fixtures" / "road-corridor-v1"
SPEC = "road-corridor.spec.yaml"


def _recorded(name: str):
    return json.loads((FIXTURE / name).read_text("utf-8"))


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    from bimforge.author.families.registry import build_from_spec
    tmp = tmp_path_factory.mktemp("v1")
    for name in (SPEC, "road-corridor.paycodes.yaml"):
        shutil.copy(FIXTURE / name, tmp / name)
    with contextlib.redirect_stderr(io.StringIO()):
        assert build_from_spec(str(tmp / SPEC)) == 0
    return ifcopenshell.open(str(tmp / "out" / "road-corridor.ifc")), tmp / "out"


def test_every_v1_element_keeps_its_globalid(built):
    f, _out = built
    was = _recorded("globalids.json")["elements"]
    now = {el.Name: el.GlobalId for el in f.by_type("IfcElement")}
    assert {n: now.get(n) for n in was} == was
    assert set(now) == set(was)                  # and no element is added


def test_every_v1_root_keeps_its_globalid(built):
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
    assert not moved, f"{len(moved)} V1 root(s) moved or dropped: {moved}"


def test_every_v1_volume_is_unchanged(built):
    import ifcopenshell.util.element as E
    f, _out = built
    was = _recorded("volumes.json")
    now = {}
    for el in f.by_type("IfcElement"):
        base = E.get_psets(el, qtos_only=True).get("Qto_BaseQuantities", {})
        if "GrossVolume" in base:
            now[el.Name] = base["GrossVolume"]
    assert set(now) == set(was)
    for name, v in was.items():
        course = name.startswith(("HMA ", "AB "))
        assert now[name] == pytest.approx(v, rel=5e-3 if course else 1e-9), name


def test_the_v1_mass_haul_is_unchanged(built):
    _f, out = built
    assert (out / "road-corridor.masshaul.csv").read_text("utf-8") == (
        FIXTURE / "masshaul.csv").read_text("utf-8")
