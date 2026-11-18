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


def _typed_wall(path, ctx, type_name):
    m = StructureModel("wall", ctx)
    p = Prism("footing", [(-2, -2), (2, -2), (2, 2), (-2, 2)],
              z_bot=0.0, z_top=2.0, ifc="IfcFooting")
    m.add(Element.from_geometry(p.name, p, ifc_class="IfcFooting",
                                type_name=type_name))
    emit_ifc(m, str(path))


def test_federate_declares_the_carried_types_to_its_project(tmp_path):
    # C.4: emit_ifc declares every type to its project, but each source's
    # declaration hangs off a project federate does not carry; the federated
    # file declares every type it holds to its own project, once, keyed as
    # emit_ifc keys it
    import ifcopenshell
    import ifcopenshell.validate

    from bimforge.bim import stable_ids
    a, b = tmp_path / "w1.ifc", tmp_path / "w2.ifc"
    _typed_wall(a, _ctx(), "FTG-A")
    _typed_wall(b, _ctx(), "FTG-B")
    out = tmp_path / "fed.ifc"
    federate([(a, "Wall 1"), (b, "Wall 2")], str(out), _ctx())
    f = ifcopenshell.open(str(out))
    (project,) = f.by_type("IfcProject")
    (rel,) = f.by_type("IfcRelDeclares")
    assert rel.RelatingContext == project
    assert set(rel.RelatedDefinitions) == set(f.by_type("IfcTypeObject"))
    assert {t.Name for t in rel.RelatedDefinitions} == {"FTG-A", "FTG-B"}
    assert rel.GlobalId == stable_ids.stable_id(
        f, f"rel/IfcRelDeclares/{project.GlobalId}")
    lg = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(f, lg, express_rules=True)
    assert [s for s in lg.statements if "IfcRelDeclares" in str(s)] == []
    # the same sources write the same file
    again = tmp_path / "fed2.ifc"
    federate([(a, "Wall 1"), (b, "Wall 2")], str(again), _ctx())
    assert out.read_bytes() == again.read_bytes()


def test_federate_of_untyped_sources_declares_nothing(tmp_path):
    import ifcopenshell
    a = tmp_path / "w1.ifc"
    _typed_wall(a, _ctx(), None)
    out = tmp_path / "fed.ifc"
    federate([(a, "Wall 1")], str(out), _ctx())
    assert not ifcopenshell.open(str(out)).by_type("IfcRelDeclares")


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


def _wall_on(path, ctx):
    m = StructureModel("wall", ctx)
    p = Prism("footing", [(-2, -2), (2, -2), (2, 2), (-2, 2)],
              z_bot=0.0, z_top=2.0, ifc="IfcFooting")
    m.add(Element.from_geometry(p.name, p, ifc_class="IfcFooting"))
    emit_ifc(m, str(path), allow_local=ctx.epsg is None)


@pytest.mark.parametrize("change", [
    {"base_e": 6_594_100.0},           # another base point: MapConversion
    {"epsg": 2227},                    # another CRS
    {"epsg": None},                    # no georeference at all
])
def test_federate_refuses_sources_on_different_georeferences(tmp_path, change):
    # C.4: the federated file has ONE MapConversion and CRS; sources on
    # different ones would be silently placed in the first's frame
    import dataclasses
    a, b = tmp_path / "w1.ifc", tmp_path / "w2.ifc"
    _wall_on(a, _ctx())
    _wall_on(b, dataclasses.replace(_ctx(), **change))
    out = tmp_path / "fed.ifc"
    with pytest.raises(ValueError, match="georeferenc") as exc:
        federate([(a, "Wall 1"), (b, "Wall 2")], str(out), _ctx())
    # the per-source check against the ctx names the odd source; sources
    # that disagree only with each other (one not georeferenced) name both
    assert "w2.ifc" in str(exc.value)
    assert not out.exists()


def test_federate_refuses_a_target_on_another_georeference(tmp_path):
    import dataclasses
    a, b = tmp_path / "w1.ifc", tmp_path / "w2.ifc"
    _wall_on(a, _ctx())
    _wall_on(b, _ctx())
    with pytest.raises(ValueError, match="georeferenc.*ctx|ctx.*georeferenc"):
        federate([(a, "Wall 1"), (b, "Wall 2")], str(tmp_path / "fed.ifc"),
                 dataclasses.replace(_ctx(), base_n=1_943_050.0))


def test_federate_keeps_storeys_decomposed_from_building(tmp_path):
    # audit 0.2: dropping the placeholder storey removed the whole
    # Building->storeys IfcRelAggregates, orphaning every real storey (WR41)
    import ifcopenshell
    import ifcopenshell.validate as V
    a, b = tmp_path / "w1.ifc", tmp_path / "w2.ifc"
    _wall_ifc(a, "footing A")
    _wall_ifc(b, "footing B")
    out = tmp_path / "fed.ifc"
    federate([(a, "Wall 1"), (b, "Wall 2")], str(out), _ctx())
    f = ifcopenshell.open(str(out))
    building = f.by_type("IfcBuilding")[0]
    storeys = f.by_type("IfcBuildingStorey")
    assert sorted(s.Name for s in storeys) == ["Wall 1", "Wall 2"]
    for s in storeys:
        assert s.Decomposes, s.Name
        assert s.Decomposes[0].RelatingObject == building
    # no aggregation is left behind with an empty member list
    assert all(r.RelatedObjects for r in f.by_type("IfcRelAggregates"))
    log = V.json_logger()
    V.validate(f, log, express_rules=True)
    msgs = [str(s.get("message", s)) for s in log.statements]
    assert not any("WR41" in m for m in msgs), msgs
    assert msgs == []


def test_federate_leaves_no_stranded_placement(tmp_path):
    # bSI IFC106 (#94): re-hanging each source's products under the target's
    # storeys strands the copies of the source's own site/building/storey
    # placements; nothing rooted may be left referencing nothing
    import ifcopenshell
    a, b = tmp_path / "w1.ifc", tmp_path / "w2.ifc"
    _wall_ifc(a, "footing A")
    _wall_ifc(b, "footing B")
    out = tmp_path / "fed.ifc"
    federate([(a, "Wall 1"), (b, "Wall 2")], str(out), _ctx())
    f = ifcopenshell.open(str(out))
    stranded = [p.id() for p in f.by_type("IfcLocalPlacement")
                if not f.get_total_inverses(p)]
    assert stranded == []
    # ...nor the merged contexts' WorldCoordinateSystem and TrueNorth
    loose = [e.id() for cls in ("IfcAxis2Placement3D", "IfcDirection")
             for e in f.by_type(cls) if not f.get_total_inverses(e)]
    assert loose == []
