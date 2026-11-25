"""Every shipped example declares its IFC4X3 facility, by what it serves.

A wall, headwall or barrier beside a road is the road's (IfcRoad, its
ROADSIDE part); a culvert is a bridge (IfcBridge CULVERT); a barrier or
railing mounted on a bridge deck is the bridge's surface structure. Every
element is contained in the facility or one of its parts, and the ground,
when there is one, in the site.
"""
from __future__ import annotations

import contextlib
import io
from importlib.resources import files

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
yaml = pytest.importorskip("yaml")

#: example -> (facility class, its PredefinedType, the part types it holds)
FACILITIES = {
    "bridge-standard": ("IfcBridge", "GIRDER",
                        {"SUPERSTRUCTURE", "SUBSTRUCTURE", "ABUTMENT", "PIER"}),
    "caltrans-box-culvert": ("IfcBridge", "CULVERT", set()),
    "caltrans-culvert-wingwall": ("IfcBridge", "CULVERT", {"ABUTMENT"}),
    "caltrans-b3-retaining-wall": ("IfcRoad", None, {"ROADSIDE"}),
    "caltrans-b3-wall-types": ("IfcRoad", None, {"ROADSIDE"}),
    "caltrans-d90-headwall": ("IfcRoad", None, {"ROADSIDE"}),
    "caltrans-pipe-headwall": ("IfcRoad", None, {"ROADSIDE"}),
    "concrete-barrier-732sw": ("IfcRoad", None, {"ROADSIDE"}),
    "concrete-barrier-842": ("IfcBridge", None, {"SURFACESTRUCTURE"}),
    "tubular-handrail": ("IfcBridge", None, {"SURFACESTRUCTURE"}),
    "demo-box": ("IfcFacility", None, set()),
    "road-corridor": ("IfcRoad", None,
                      {"ROADSEGMENT", "CARRIAGEWAY", "SHOULDER"}),
}


def _examples() -> list[str]:
    return sorted(e.name[:-len(".spec.yaml")]
                  for e in (files("bimforge.author") / "examples").iterdir()
                  if e.name.endswith(".spec.yaml"))


def test_every_example_is_listed():
    assert _examples() == sorted(FACILITIES)


@pytest.mark.parametrize("example", sorted(FACILITIES))
def test_the_example_declares_its_facility(example):
    spec = yaml.safe_load((files("bimforge.author") / "examples"
                           / f"{example}.spec.yaml").read_text("utf-8"))
    cls = FACILITIES[example][0]
    kind = {"IfcBridge": "bridge", "IfcRoad": "road",
            "IfcFacility": "facility"}[cls]
    assert spec["project"]["facility"]["kind"] == kind


#: the road corridor is built (and its tree checked) by test_road_corridor
BUILT = sorted(set(FACILITIES) - {"road-corridor"})


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> dict:
    from bimforge.author.families.registry import build_from_spec
    tmp = tmp_path_factory.mktemp("facilities")
    for entry in (files("bimforge.author") / "examples").iterdir():
        if entry.name.endswith(".yaml"):
            (tmp / entry.name).write_text(entry.read_text("utf-8"), "utf-8")
    out = {}
    for name in BUILT:
        spec = tmp / f"{name}.spec.yaml"
        with contextlib.redirect_stderr(io.StringIO()):
            assert build_from_spec(str(spec)) == 0, name   # incl. the gate
        ifc = yaml.safe_load(spec.read_text("utf-8"))["outputs"]["ifc"]
        out[name] = ifcopenshell.open(str(tmp / ifc))
    return out


@pytest.mark.parametrize("example", BUILT)
def test_the_example_is_written_in_its_facility(built, example):
    import ifcopenshell.util.element as E
    f = built[example]
    cls, pdt, part_types = FACILITIES[example]
    assert not f.by_type("IfcBuilding") and not f.by_type("IfcBuildingStorey")
    (fac,) = [x for x in f.by_type("IfcFacility") if x.is_a() == cls]
    assert getattr(fac, "PredefinedType", None) == pdt
    parts = f.by_type("IfcFacilityPart")
    assert {p.PredefinedType for p in parts} == part_types
    assert all(p.UsageType for p in parts)
    home = {fac.id()} | {p.id() for p in parts}
    for el in f.by_type("IfcElement"):
        if el.is_a("IfcFeatureElement"):
            continue
        container = E.get_container(el)
        if container is None:                    # aggregated, nested
            continue
        if el.is_a("IfcGeographicElement"):
            assert container.is_a("IfcSite")
        else:
            assert container.id() in home, (el.Name, container.is_a())


def test_the_facility_is_named_for_the_structure(built):
    # the example's structure, not the family id the facility defaults to
    names = {n: next(x for x in f.by_type("IfcFacility")
                     if not x.is_a("IfcBuilding")).Name
             for n, f in built.items()}
    assert names["caltrans-b3-retaining-wall"] == "B3 Retaining Wall"
    assert names["caltrans-box-culvert"] == "Box Culvert"
    assert not set(names.values()) & {
        "standard-plan", "box-culvert", "culvert-wingwall", "culvert-headwall",
        "pipe-headwall", "bridge-standard", "demo-box", "tubular-handrail",
        "concrete-barrier-732sw", "concrete-barrier-842"}


def _homes(f) -> dict:
    """{element name: its container's name} for the contained elements."""
    import ifcopenshell.util.element as E
    return {el.Name: E.get_container(el).Name for el in f.by_type("IfcElement")
            if E.get_container(el) is not None}


def _parent(f, name) -> str:
    (part,) = [p for p in f.by_type("IfcFacilityPart") if p.Name == name]
    return part.Decomposes[0].RelatingObject.Name


def test_the_bridge_parts_hold_their_members(built):
    f = built["bridge-standard"]
    homes = _homes(f)
    assert {n for n, h in homes.items() if h == "Superstructure"} == {
        "span 1 superstructure", "span 2 superstructure",
        "B2 diaphragm cell 1", "B2 diaphragm cell 2"}
    assert {n for n, h in homes.items() if h == "Bent 2"} == {
        "B2 column 1", "B2 column 2", "B2 bent cap"}
    assert {n for n, h in homes.items() if h == "Abutment 1"} == {
        "A1 abutment stem", "A1 abutment backwall"}
    assert {n for n, h in homes.items() if h == "Abutment 3"} == {
        "A3 abutment stem", "A3 abutment backwall"}
    for part in ("Abutment 1", "Bent 2", "Abutment 3"):
        assert _parent(f, part) == "Substructure"
    assert _parent(f, "Substructure") == _parent(f, "Superstructure")         == "Fixture Overcrossing"


def test_each_wingwall_is_its_own_part(built):
    homes = _homes(built["caltrans-culvert-wingwall"])
    assert homes
    for name, home in homes.items():
        assert home == f"Wingwall {name.split()[0]}", name
    assert set(homes.values()) == {
        "Wingwall WW1", "Wingwall WWE", "Wingwall WWW"}
