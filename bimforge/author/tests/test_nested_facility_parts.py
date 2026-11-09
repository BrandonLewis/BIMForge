"""Nested IFC4X3 facility parts: SpatialPart.parent (Substructure > Abutment > Foundation)."""
from __future__ import annotations

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

from bimforge.author.emit_ifc import emit_ifc  # noqa: E402
from bimforge.author.federate import federate  # noqa: E402
from bimforge.author.gate import _ifc_spatial_chain_check  # noqa: E402
from bimforge.author.model import StructureModel  # noqa: E402
from bimforge.author.spatial import (Facility, SpatialPart, parse_part,  # noqa: E402
                                     parse_rules)
from bimforge.author.tests.test_ifc4x3_facility import (  # noqa: E402
    _box, _children, _contained_in, _ctx, _validate)

SUB = SpatialPart("Substructure", "SUBSTRUCTURE", "VERTICAL")
A1 = SpatialPart("Abutment 1", "ABUTMENT", "LONGITUDINAL", parent=SUB)
A1_FDN = SpatialPart("Abutment 1 foundation", "FOUNDATION", "VERTICAL", parent=A1)
SUPER = SpatialPart("Superstructure", "SUPERSTRUCTURE", "VERTICAL")


def _nested():
    m = StructureModel("Bridge", _ctx(facility=Facility("bridge", "Br 44-0300", "GIRDER")))
    # the foundation first: its ancestors must still be written before it
    m.add(_box("Pile A1-1", 0.0, "IfcPile", (-40.0, 0.0), spatial_part=A1_FDN))
    m.add(_box("A1 stem", 0.0, "IfcWall", (3.0, 20.0), spatial_part=A1))
    # a bare-name parent resolves to the part declared in full
    m.add(_box("A1 wingwall", 5.0, "IfcWall", (3.0, 20.0),
               spatial_part=SpatialPart("A1 wing", parent=SpatialPart("Abutment 1"))))
    m.add(_box("Deck slab", 30.0, "IfcSlab", (20.0, 21.0), spatial_part=SUPER))
    return m


def test_parts_nest_under_their_parents(tmp_path):
    out = tmp_path / "nested.ifc"
    emit_ifc(_nested(), str(out))
    f = ifcopenshell.open(str(out))
    bridge = f.by_type("IfcBridge")[0]
    parts = {p.Name: p for p in f.by_type("IfcBridgePart")}
    assert _children(bridge) == [("IfcBridgePart", "Substructure"),
                                 ("IfcBridgePart", "Superstructure")]
    assert _children(parts["Substructure"]) == [("IfcBridgePart", "Abutment 1")]
    assert _children(parts["Abutment 1"]) == [("IfcBridgePart", "A1 wing"),
                                              ("IfcBridgePart", "Abutment 1 foundation")]
    assert parts["Abutment 1"].PredefinedType == "ABUTMENT"
    assert parts["Abutment 1"].UsageType == "LONGITUDINAL"
    assert parts["Abutment 1 foundation"].PredefinedType == "FOUNDATION"
    # a part no element names directly is still a container in the tree
    assert not parts["Substructure"].ContainsElements
    assert _contained_in(f, "Pile A1-1") == parts["Abutment 1 foundation"]
    assert _contained_in(f, "A1 stem") == parts["Abutment 1"]
    assert _validate(out) == []
    assert _ifc_spatial_chain_check(None, str(out)) == []


def test_federate_carries_the_nested_tree(tmp_path):
    src = tmp_path / "nested.ifc"
    emit_ifc(_nested(), str(src))
    out = tmp_path / "fed.ifc"
    federate([(src, "Bridge")], str(out), _ctx())
    f = ifcopenshell.open(str(out))
    parts = {p.Name: p for p in f.by_type("IfcBridgePart")}
    assert _children(parts["Abutment 1"]) == [("IfcBridgePart", "A1 wing"),
                                              ("IfcBridgePart", "Abutment 1 foundation")]
    assert _contained_in(f, "Pile A1-1").Name == "Abutment 1 foundation"
    assert _validate(out) == []


def test_conflicting_declarations_and_cycles_are_refused(tmp_path):
    m = StructureModel("Bridge", _ctx(facility=Facility("bridge")))
    m.add(_box("A1 stem", 0.0, spatial_part=A1))
    m.add(_box("A3 stem", 9.0, spatial_part=SpatialPart("Abutment 1", "PIER", parent=SUB)))
    with pytest.raises(ValueError, match="declared twice"):
        emit_ifc(m, str(tmp_path / "x.ifc"))
    loop = SpatialPart("B", parent=SpatialPart("A", parent=SpatialPart("B")))
    with pytest.raises(ValueError, match="cycle"):
        loop.lineage()


def test_rules_parse_nested_parents():
    (rule,) = parse_rules([{"match": "^Pile A1", "part": {
        "name": "Abutment 1 foundation", "predefined_type": "FOUNDATION",
        "parent": {"name": "Abutment 1", "predefined_type": "ABUTMENT",
                   "parent": "Substructure"}}}])
    assert [p.name for p in rule.part.lineage()] == [
        "Substructure", "Abutment 1", "Abutment 1 foundation"]
    assert parse_part("Deck").parent is None
    with pytest.raises(ValueError, match="unknown keys"):
        parse_part({"name": "x", "parents": "y"})


def _earthwork():
    """The same bridge's structure excavation, modelled apart (its own source)."""
    m = StructureModel("Earthwork", _ctx(facility=Facility("bridge", "Br 44-0300", "GIRDER")))
    m.add(_box("Abut 1 structure backfill", 0.0, "IfcEarthworksFill", (-2.0, 3.0),
               spatial_part=A1_FDN))
    m.add(_box("Abut 3 structure backfill", 90.0, "IfcEarthworksFill", (-2.0, 3.0),
               spatial_part=SpatialPart("Abutment 3 foundation", "FOUNDATION", parent=SpatialPart(
                   "Abutment 3", "ABUTMENT", "LONGITUDINAL", parent=SUB))))
    return m


def test_federate_merges_one_facility_modelled_in_two_sources(tmp_path):
    br, ew = tmp_path / "bridge.ifc", tmp_path / "earthwork.ifc"
    emit_ifc(_nested(), str(br))
    emit_ifc(_earthwork(), str(ew))
    out = tmp_path / "fed.ifc"
    res = federate([(br, "Bridge"), (ew, "Earthwork")], str(out), _ctx(),
                   merge_facilities=True)
    f = ifcopenshell.open(str(out))
    assert [b.Name for b in f.by_type("IfcBridge")] == ["Br 44-0300"]
    assert res.facilities == 1 and res.merged_facilities == 4  # bridge, sub, A1, A1 fdn
    parts = {p.Name: p for p in f.by_type("IfcBridgePart")}
    assert len(parts) == len(f.by_type("IfcBridgePart"))        # no duplicate parts
    assert _children(parts["Substructure"]) == [("IfcBridgePart", "Abutment 1"),
                                                ("IfcBridgePart", "Abutment 3")]
    assert _contained_in(f, "Abut 1 structure backfill") == parts["Abutment 1 foundation"]
    assert _contained_in(f, "Pile A1-1") == parts["Abutment 1 foundation"]
    assert _contained_in(f, "Abut 3 structure backfill") == parts["Abutment 3 foundation"]
    assert _validate(out) == []
    assert _ifc_spatial_chain_check(None, str(out)) == []

    # without the flag each source keeps its own facility, as before
    out2 = tmp_path / "fed2.ifc"
    federate([(br, "Bridge"), (ew, "Earthwork")], str(out2), _ctx())
    assert len(ifcopenshell.open(str(out2)).by_type("IfcBridge")) == 2
