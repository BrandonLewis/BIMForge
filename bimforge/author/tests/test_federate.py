"""IFC-level model federation (#193)."""
from __future__ import annotations

import uuid

import pytest

pytest.importorskip("ifcopenshell")

from bimforge.author.emit_ifc import emit_ifc
from bimforge.author.federate import federate
from bimforge.author.model import Element, StructureModel
from bimforge.author.primitives import Prism
from bimforge.author.project import ProjectContext


def _ctx():
    return ProjectContext(name="Federated Fixture", epsg=2226,
                          base_e=6_594_000.0, base_n=1_943_000.0, base_h=200.0,
                          guid_ns=uuid.UUID(int=193))


def _wall_ifc(path, footing_name):
    # two source models share the SAME ctx (guid_ns) and element name, so their
    # products collide on GlobalId -> the federation must namespace them.
    m = StructureModel("wall", _ctx())
    p = Prism(footing_name, [(-2, -2), (2, -2), (2, 2), (-2, 2)],
              z_bot=0.0, z_top=2.0, ifc="IfcFooting")
    m.add(Element.from_geometry(p.name, p, ifc_class="IfcFooting"))
    emit_ifc(m, str(path))


def test_federate_merges_under_per_source_storeys(tmp_path):
    import ifcopenshell
    a, b = tmp_path / "w1.ifc", tmp_path / "w2.ifc"
    _wall_ifc(a, "footing")            # identical name in both -> same GlobalId
    _wall_ifc(b, "footing")
    out = tmp_path / "fed.ifc"
    res = federate([(a, "Wall 1"), (b, "Wall 2")], str(out), _ctx())

    f = ifcopenshell.open(str(out))
    assert len(f.by_type("IfcBuilding")) == 1
    storeys = sorted(s.Name for s in f.by_type("IfcBuildingStorey"))
    assert storeys == ["Wall 1", "Wall 2"]          # placeholder removed
    assert len(f.by_type("IfcFooting")) == 2        # both sources' products
    assert res.products == 2
    assert res.per_source == {"Wall 1": 1, "Wall 2": 1}


def test_federate_namespaces_colliding_globalids(tmp_path):
    import ifcopenshell
    a, b = tmp_path / "w1.ifc", tmp_path / "w2.ifc"
    _wall_ifc(a, "footing")
    _wall_ifc(b, "footing")
    # the two footings DO share a GlobalId before federation
    ga = ifcopenshell.open(str(a)).by_type("IfcFooting")[0].GlobalId
    gb = ifcopenshell.open(str(b)).by_type("IfcFooting")[0].GlobalId
    assert ga == gb
    out = tmp_path / "fed.ifc"
    federate([(a, "Wall 1"), (b, "Wall 2")], str(out), _ctx())
    f = ifcopenshell.open(str(out))
    gids = [p.GlobalId for p in f.by_type("IfcFooting")]
    assert len(set(gids)) == 2                      # no collision after merge
    # no product GlobalId appears twice anywhere in the file
    all_gids = [p.GlobalId for p in f.by_type("IfcProduct")]
    assert len(all_gids) == len(set(all_gids))


def test_federate_unifies_geometric_contexts(tmp_path):
    import ifcopenshell
    a, b = tmp_path / "w1.ifc", tmp_path / "w2.ifc"
    _wall_ifc(a, "footing A")
    _wall_ifc(b, "footing B")
    out = tmp_path / "fed.ifc"
    res = federate([(a, "Wall 1"), (b, "Wall 2")], str(out), _ctx())
    f = ifcopenshell.open(str(out))
    # exactly one top-level geometric context survives (+ its Body subcontext)
    tops = [c for c in f.by_type("IfcGeometricRepresentationContext")
            if not c.is_a("IfcGeometricRepresentationSubContext")]
    assert len(tops) == 1
    assert res.merged_contexts >= 1                 # source contexts collapsed
    # every representation points at a surviving context
    kept = {c.id() for c in f.by_type("IfcGeometricRepresentationContext")}
    assert all(r.ContextOfItems.id() in kept
               for r in f.by_type("IfcShapeRepresentation"))


def test_federate_carries_type_identity(tmp_path):
    import ifcopenshell
    import ifcopenshell.api
    a, b = tmp_path / "w1.ifc", tmp_path / "w2.ifc"
    _wall_ifc(a, "footing")
    _wall_ifc(b, "footing")
    # give each source a footing TYPE assigned to its footing, sharing a
    # GlobalId across the two (so the merge must both carry AND namespace it)
    for p in (a, b):
        src = ifcopenshell.open(str(p))
        ftg = src.by_type("IfcFooting")[0]
        typ = ifcopenshell.api.run("root.create_entity", src,
                                   ifc_class="IfcFootingType", name="FTG-STD")
        typ.GlobalId = "1TYPESHARED0000000000GG"     # identical in both sources
        ifcopenshell.api.run("type.assign_type", src, related_objects=[ftg],
                             relating_type=typ)
        src.write(str(p))
    out = tmp_path / "fed.ifc"
    federate([(a, "Wall 1"), (b, "Wall 2")], str(out), _ctx())
    f = ifcopenshell.open(str(out))
    # both type assignments survived, and the two types no longer collide
    assert len(f.by_type("IfcRelDefinesByType")) == 2
    tids = [t.GlobalId for t in f.by_type("IfcFootingType")]
    assert len(tids) == 2 and len(set(tids)) == 2
    all_gids = [r.GlobalId for r in f.by_type("IfcRoot")]
    assert len(all_gids) == len(set(all_gids))       # nothing collides


def test_federate_refuses_non_metre_source(tmp_path):
    import ifcopenshell
    a = tmp_path / "w1.ifc"
    _wall_ifc(a, "footing")
    # a millimetre length unit (prefixed metre) is not plain SI metre: the
    # federation must refuse rather than silently rescale the geometry.
    src = ifcopenshell.open(str(a))
    for u in src.by_type("IfcSIUnit"):
        if u.UnitType == "LENGTHUNIT":
            u.Prefix = "MILLI"
    bad = tmp_path / "bad.ifc"
    src.write(str(bad))
    with pytest.raises(ValueError, match="SI metre"):
        federate([(bad, "Wall 1")], str(tmp_path / "fed.ifc"), _ctx())
