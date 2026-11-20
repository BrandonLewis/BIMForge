"""Every shipped example keeps the GlobalIds it was written with.

BidSheet.ai keys modelled elements on their GlobalId (`upsert_modelled_
elements`), and a consumer may attach records to any id the GlobalId
contract (docs/globalid-contract.md) calls stable. The other roots
(relationships, property sets) are numbered by file order, so a writer
change that inserts an IfcRoot ahead of them would renumber them all.

`fixtures/example_globalids.json` was recorded at 0.1.121, before the
Phase 1 typing work (C.4): every element's id by name, and every IfcRoot's
id with its class. A writer change may ADD roots (a type, a declaration);
it may not move or drop one. An element may change class (a proxy that
becomes a virtual element), which the contract says keeps its id. An
example added later is recorded as it first ships (caltrans-b3-wall-types
at 0.1.128).

Re-record only for a change that is meant to renumber, and say so in the
changelog: a renumbered element is a new element to BidSheet.
"""
from __future__ import annotations

import contextlib
import io
import json
from importlib.resources import files
from pathlib import Path

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
yaml = pytest.importorskip("yaml")

RECORDED = json.loads((Path(__file__).parent / "fixtures"
                       / "example_globalids.json").read_text("utf-8"))


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> dict:
    """{example name: the opened IFC} for every shipped example spec."""
    from bimforge.author.families.registry import build_from_spec
    tmp = tmp_path_factory.mktemp("globalids")
    for entry in (files("bimforge.author") / "examples").iterdir():
        if entry.name.endswith(".yaml"):
            (tmp / entry.name).write_text(entry.read_text("utf-8"), "utf-8")
    out = {}
    for spec in sorted(tmp.glob("*.spec.yaml")):
        with contextlib.redirect_stderr(io.StringIO()):
            assert build_from_spec(str(spec)) == 0, spec.name
        ifc = yaml.safe_load(spec.read_text("utf-8"))["outputs"]["ifc"]
        out[spec.name[:-len(".spec.yaml")]] = ifcopenshell.open(str(tmp / ifc))
    return out


def test_every_example_is_recorded(built):
    assert sorted(built) == sorted(RECORDED)


@pytest.mark.parametrize("example", sorted(RECORDED))
def test_element_globalids_are_unchanged(built, example):
    now = {el.Name: el.GlobalId for el in built[example].by_type("IfcElement")}
    was = RECORDED[example]["elements"]
    assert {n: now.get(n) for n in was} == was


@pytest.mark.parametrize("example", sorted(RECORDED))
def test_every_recorded_root_keeps_its_globalid(built, example):
    f = built[example]
    elements = set(RECORDED[example]["elements"].values())
    moved = {}
    for gid, cls in RECORDED[example]["roots"].items():
        try:
            ent = f.by_guid(gid)
        except RuntimeError:
            moved[gid] = (cls, None)
            continue
        if gid not in elements and ent.is_a() != cls:
            moved[gid] = (cls, ent.is_a())
    assert not moved, f"{len(moved)} recorded root(s) moved or dropped"
