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
