"""IFC4X3 facility spatial tree in emit_ifc + federate (#318)."""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

from bimforge.author.emit_ifc import emit_combined_ifc, emit_ifc  # noqa: E402
from bimforge.author.federate import (MixedSchemaError,  # noqa: E402
                                      federate)
from bimforge.author.gate import _ifc_spatial_chain_check  # noqa: E402
from bimforge.author.model import Element, StructureModel  # noqa: E402
from bimforge.author.paycodes import apply as pc_apply  # noqa: E402
from bimforge.author.paycodes import from_dict  # noqa: E402
from bimforge.author.primitives import Prism  # noqa: E402
from bimforge.author.project import ProjectContext  # noqa: E402
from bimforge.author.spatial import (Facility, SpatialPart,  # noqa: E402
                                     apply_spatial_parts, parse_rules,
                                     resolve_part_type)

X3 = "IFC4X3_ADD2"
NS = uuid.UUID("5e1d0b7a-9c3f-4e21-8d64-318031803180")


def _ctx(schema=X3, facility=None):
    return ProjectContext(name="Mariposa Fixture", schema=schema, epsg=2226,
                          base_e=6_594_000.0, base_n=1_943_000.0, base_h=200.0,
                          guid_ns=NS, facility=facility)


def _box(name, x=0.0, ifc="IfcFooting", z=(0.0, 3.0), **kw):
    p = Prism(name, [(-4, -10), (4, -10), (4, 10), (-4, 10)],
              z_bot=z[0], z_top=z[1], ifc=ifc)
    return Element.from_geometry(name, p, ifc_class=ifc, x_ft=x, **kw)


def _bridge(schema=X3, facility=Facility("bridge", "Br 39-0063", "GIRDER")):
    m = StructureModel("Bridge", _ctx(schema, facility))
    m.add(_box("Abut 1 footing", 0.0, spatial_part="ABUTMENT"))
    m.add(_box("Abut 2 footing", 60.0, spatial_part="ABUTMENT"))
    m.add(_box("Deck slab", 30.0, "IfcSlab", (12.0, 13.5),
               spatial_part={"name": "Deck", "predefined_type": "DECK"}))
    m.add(_box("Pier 1 cap", 30.0, "IfcBeam", (8.0, 11.0),
               spatial_part="Pier 1"))
    m.add(_box("Approach slab", 70.0, "IfcSlab", (11.0, 12.0)))   # unparted
    m.assemblies["Abutment footings"] = ["Abut 1 footing", "Abut 2 footing"]
    return m


def _validate(path):
    import ifcopenshell.validate as V
    log = V.json_logger()
    V.validate(ifcopenshell.open(str(path)), log, express_rules=True)
    return [s.get("message", s) for s in log.statements]


def _contained_in(f, name):
    p = next(x for x in f.by_type("IfcProduct") if x.Name == name)
    rels = p.ContainedInStructure
    return rels[0].RelatingStructure if rels else None


def _children(ent):
    return sorted((c.is_a(), c.Name) for r in ent.IsDecomposedBy or ()
                  for c in r.RelatedObjects)


# ------------------------------------------------------------ single bridge
def test_bridge_facility_tree_parts_and_containment(tmp_path):
    out = tmp_path / "bridge.ifc"
    emit_ifc(_bridge(), str(out))
    f = ifcopenshell.open(str(out))

    assert not f.by_type("IfcBuilding") and not f.by_type("IfcBuildingStorey")
    site = f.by_type("IfcSite")[0]
    assert _children(site) == [("IfcBridge", "Br 39-0063")]
    bridge = f.by_type("IfcBridge")[0]
    assert bridge.PredefinedType == "GIRDER"
    assert _children(bridge) == [("IfcBridgePart", "ABUTMENT"),
                                 ("IfcBridgePart", "Deck"),
                                 ("IfcBridgePart", "Pier 1")]
    parts = {p.Name: p for p in f.by_type("IfcBridgePart")}
    assert parts["ABUTMENT"].PredefinedType == "ABUTMENT"
    assert parts["Deck"].PredefinedType == "DECK"
    # a name that is no enum value -> USERDEFINED + ObjectType
    assert parts["Pier 1"].PredefinedType == "USERDEFINED"
    assert parts["Pier 1"].ObjectType == "Pier 1"
    assert {p.UsageType for p in parts.values()} == {"NOTDEFINED"}

    assert _contained_in(f, "Deck slab") == parts["Deck"]
    assert _contained_in(f, "Pier 1 cap") == parts["Pier 1"]
    assert _contained_in(f, "Approach slab") == bridge     # unparted
    # the assembly carries its members' part; members are aggregated into it
    assert _contained_in(f, "Abutment footings") == parts["ABUTMENT"]
    asm = next(x for x in f.by_type("IfcElementAssembly"))
    assert sorted(n for _c, n in _children(asm)) == ["Abut 1 footing",
                                                     "Abut 2 footing"]
    # origin placements on every spatial element
    for sp in (site, bridge, *parts.values()):
        assert sp.ObjectPlacement is not None

    assert _validate(out) == []
    assert _ifc_spatial_chain_check(None, str(out)) == []


def test_bridge_facility_guids_are_deterministic(tmp_path):
    a, b = tmp_path / "a.ifc", tmp_path / "b.ifc"
    emit_ifc(_bridge(), str(a))
    emit_ifc(_bridge(), str(b))
    assert a.read_bytes() == b.read_bytes()
    f = ifcopenshell.open(str(a))
    ctx = _ctx()
    assert f.by_type("IfcBridge")[0].GlobalId == ctx.guid("spatial/facility")
    deck = next(p for p in f.by_type("IfcBridgePart") if p.Name == "Deck")
    assert deck.GlobalId == ctx.guid("spatial/part/Deck")


def test_facility_is_ignored_under_ifc4_with_a_note(tmp_path, capsys):
    a, b = tmp_path / "fac.ifc", tmp_path / "plain.ifc"
    emit_ifc(_bridge(schema="IFC4"), str(a))
    assert "ignored under schema IFC4" in capsys.readouterr().err
    emit_ifc(_bridge(schema="IFC4", facility=None), str(b))
    assert a.read_bytes() == b.read_bytes()
    assert len(ifcopenshell.open(str(a)).by_type("IfcBuildingStorey")) == 1


def test_site_kind_contains_products_in_the_site(tmp_path):
    m = StructureModel("Terrain", _ctx(facility=Facility("site")))
    m.add(_box("Existing ground", ifc="IfcGeographicElement",
               spatial_part="ignored"))
    out = tmp_path / "terrain.ifc"
    emit_ifc(m, str(out))
    f = ifcopenshell.open(str(out))
    assert _contained_in(f, "Existing ground").is_a("IfcSite")
    assert not f.by_type("IfcFacility")
    assert _validate(out) == []
    assert _ifc_spatial_chain_check(None, str(out)) == []


def test_generic_facility_uses_facility_part_common(tmp_path):
    m = StructureModel("Drainage", _ctx(facility=Facility("facility")))
    m.add(_box("Inlet", spatial_part="BELOWGROUND"))
    out = tmp_path / "drain.ifc"
    emit_ifc(m, str(out))
    f = ifcopenshell.open(str(out))
    fac = f.by_type("IfcFacility")[0]
    assert fac.is_a() == "IfcFacility" and fac.Name == "Drainage"
    part = f.by_type("IfcFacilityPartCommon")[0]
    assert part.PredefinedType == "BELOWGROUND"
    assert _validate(out) == []


def test_combined_emit_gives_each_model_its_own_facility(tmp_path):
    road = StructureModel("Road", _ctx(facility=Facility("road")))
    road.add(_box("Lane 1", spatial_part="Carriageway"))
    out = tmp_path / "combined.ifc"
    emit_combined_ifc([_bridge(), road], str(out))
    f = ifcopenshell.open(str(out))
    site = f.by_type("IfcSite")[0]
    assert _children(site) == [("IfcBridge", "Br 39-0063"), ("IfcRoad", "Road")]
    rp = f.by_type("IfcRoadPart")[0]
    assert rp.PredefinedType == "CARRIAGEWAY"
    assert _validate(out) == []
    assert _ifc_spatial_chain_check(None, str(out)) == []


def test_assembly_spanning_parts_is_refused(tmp_path):
    m = _bridge()
    m.assemblies["mixed"] = ["Deck slab", "Pier 1 cap"]
    with pytest.raises(ValueError, match="spans spatial containers"):
        emit_ifc(m, str(tmp_path / "x.ifc"))


def test_one_part_with_two_types_is_refused(tmp_path):
    m = _bridge()
    m.add(_box("Deck overlay", spatial_part={"name": "Deck",
                                              "predefined_type": "PIER"}))
    with pytest.raises(ValueError, match="declared twice"):
        emit_ifc(m, str(tmp_path / "x.ifc"))


# ------------------------------------------------------------- spec surface
def test_facility_and_rules_parse_and_apply():
    ctx = ProjectContext.from_spec({
        "name": "x", "guid_ns": str(NS), "schema": X3,
        "facility": {"kind": "bridge", "predefined_type": "girder"}})
    assert ctx.facility == Facility("bridge", None, "girder")
    assert ProjectContext.from_spec(
        {"name": "x", "guid_ns": str(NS)}).facility is None
    with pytest.raises(ValueError, match="unknown kind"):
        Facility.from_spec({"kind": "tunnel"})
    with pytest.raises(ValueError, match="unknown keys"):
        Facility.from_spec({"kind": "road", "nme": "typo"})

    rules = parse_rules([{"match": "(?i)abut", "part": "ABUTMENT"},
                         {"match": "(?i)deck", "part": {"name": "Deck"}}])
    m = StructureModel("m", ctx)
    m.add(Element("Abut 1 stem"))
    m.add(Element("Deck slab"))
    m.add(Element("Pier 1", spatial_part="Pier 1"))      # explicit wins
    assert apply_spatial_parts(m, rules) == 2
    assert m.element("Abut 1 stem").spatial_part == SpatialPart("ABUTMENT")
    assert m.element("Pier 1").spatial_part == SpatialPart("Pier 1")
    with pytest.raises(ValueError, match=r"spatial_parts\[0\]"):
        parse_rules([{"match": "(", "part": "X"}])


def test_paycodes_carry_spatial_parts():
    pc = from_dict({
        "rules": [{"match": ".", "group": "g"}],
        "groups": {"g": {"measure": "GrossVolume"}},
        "codes": {"C": {"group": "g", "measure": "GrossVolume", "unit": "CY"}},
        "spatial_parts": [{"match": "(?i)abut", "part": "ABUTMENT"}],
    })
    m = StructureModel("m", _ctx())
    m.add(Element("Abut 2 wall"))
    pc_apply(m, pc)
    assert m.element("Abut 2 wall").spatial_part.name == "ABUTMENT"


def test_part_type_resolution():
    assert resolve_part_type(X3, "IfcBridgePart",
                             SpatialPart("pier segment")) == ("PIER_SEGMENT", None)
    assert resolve_part_type(X3, "IfcBridgePart",
                             SpatialPart("Wing", "wingwall")) == (
        "USERDEFINED", "wingwall")
    assert resolve_part_type(X3, "IfcRoadPart",
                             SpatialPart("Lane", "USERDEFINED")) == (
        "USERDEFINED", "Lane")


def test_build_from_spec_writes_the_facility_tree(tmp_path):
    import shutil

    import yaml
    from bimforge.author.families import registry as reg
    ex = Path(reg.__file__).parent.parent / "examples"
    for name in ("demo-box.spec.yaml", "demo-box.paycodes.yaml"):
        shutil.copy(ex / name, tmp_path / name)
    spec_path = tmp_path / "demo-box.spec.yaml"
    doc = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    doc["project"]["schema"] = X3
    doc["project"]["facility"] = {"kind": "bridge", "name": "Demo Bridge"}
    doc["spatial_parts"] = [{"match": "DB-1", "part": "ABUTMENT"},
                            {"match": "DB-2", "part": {"name": "Pier 2",
                                                       "predefined_type": "PIER"}}]
    spec_path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    assert reg.build_from_spec(spec_path) == 0      # gate post incl. validate
    f = ifcopenshell.open(str(tmp_path / "out" / "demo-box.ifc"))
    assert _children(f.by_type("IfcBridge")[0]) == [
        ("IfcBridgePart", "ABUTMENT"), ("IfcBridgePart", "Pier 2")]


# ------------------------------------------------------------------- gates
def test_gate_flags_an_empty_part_and_an_uncontained_product(tmp_path):
    out = tmp_path / "bridge.ifc"
    emit_ifc(_bridge(), str(out))
    f = ifcopenshell.open(str(out))
    deck = next(p for p in f.by_type("IfcBridgePart") if p.Name == "Deck")
    for rel in list(deck.ContainsElements):
        f.remove(rel)                       # deck part now empty, slab orphaned
    bad = tmp_path / "bad.ifc"
    f.write(str(bad))
    fails = _ifc_spatial_chain_check(None, str(bad))
    assert any("'Deck' is empty" in m for m in fails)
    assert any("no container chain" in m and "Deck slab" in m for m in fails)


# -------------------------------------------------------------- federation
def _terrain_ifc(path):
    m = StructureModel("Terrain", _ctx(facility=Facility("site")))
    m.add(_box("Existing ground", ifc="IfcGeographicElement", z=(-5.0, 0.0)))
    emit_ifc(m, str(path))


def _road_ifc(path):
    m = StructureModel("Road", _ctx(facility=Facility("road", "SR 140")))
    m.add(_box("Lane 1 pavement", 100.0, "IfcSlab",
               spatial_part="Carriageway"))
    m.add(_box("Shoulder", 110.0, "IfcSlab", spatial_part="SHOULDER"))
    emit_ifc(m, str(path))


def _federation(tmp_path, out_name="fed.ifc"):
    br, te, rd = (tmp_path / "bridge.ifc", tmp_path / "terrain.ifc",
                  tmp_path / "road.ifc")
    emit_ifc(_bridge(), str(br))
    _terrain_ifc(te)
    _road_ifc(rd)
    out = tmp_path / out_name
    res = federate([(br, "Bridge"), (te, "Terrain"), (rd, "Road")], str(out),
                   _ctx())
    return out, res


def test_federate_carries_facility_subtrees_and_site_terrain(tmp_path):
    out, res = _federation(tmp_path)
    f = ifcopenshell.open(str(out))
    site = f.by_type("IfcSite")
    assert len(site) == 1
    site = site[0]
    # facilities hang off the ONE target site; no building/storey left behind
    assert _children(site) == [("IfcBridge", "Br 39-0063"), ("IfcRoad", "SR 140")]
    assert not f.by_type("IfcBuilding") and not f.by_type("IfcBuildingStorey")
    assert res.facilities == 2 and res.site_products == 1 and res.storeys == 0
    assert res.per_source == {"Bridge": 6, "Terrain": 1, "Road": 2}

    bridge = f.by_type("IfcBridge")[0]
    assert bridge.PredefinedType == "GIRDER"
    assert _children(bridge) == [("IfcBridgePart", "ABUTMENT"),
                                 ("IfcBridgePart", "Deck"),
                                 ("IfcBridgePart", "Pier 1")]
    road = f.by_type("IfcRoad")[0]
    rparts = {p.Name: p for p in f.by_type("IfcRoadPart")}
    assert rparts["Carriageway"].PredefinedType == "CARRIAGEWAY"
    assert rparts["SHOULDER"].PredefinedType == "SHOULDER"
    assert _children(road) == [("IfcRoadPart", "Carriageway"),
                               ("IfcRoadPart", "SHOULDER")]

    # containment survives the merge
    assert _contained_in(f, "Existing ground") == site
    assert _contained_in(f, "Deck slab").Name == "Deck"
    assert _contained_in(f, "Approach slab") == bridge
    assert _contained_in(f, "Lane 1 pavement") == rparts["Carriageway"]
    assert _contained_in(f, "Abutment footings").Name == "ABUTMENT"
    # carried spatial placements hang off the target site's placement
    assert bridge.ObjectPlacement.PlacementRelTo == site.ObjectPlacement
    assert road.ObjectPlacement.PlacementRelTo == site.ObjectPlacement

    gids = [r.GlobalId for r in f.by_type("IfcRoot")]
    assert len(gids) == len(set(gids))
    assert _validate(out) == []
    assert _ifc_spatial_chain_check(None, str(out)) == []


def test_federate_4x3_is_byte_deterministic(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a, _ = _federation(tmp_path / "a")
    b, _ = _federation(tmp_path / "b")
    assert a.read_bytes() == b.read_bytes()


def test_federate_namespaces_facility_guids_per_source(tmp_path):
    out, _ = _federation(tmp_path)
    f = ifcopenshell.open(str(out))
    src = ifcopenshell.open(str(tmp_path / "bridge.ifc"))
    orig = src.by_type("IfcBridge")[0].GlobalId
    assert f.by_type("IfcBridge")[0].GlobalId == _ctx().guid(f"Bridge/{orig}")


def test_federate_refuses_mixed_schemas(tmp_path):
    x3, four = tmp_path / "x3.ifc", tmp_path / "ifc4.ifc"
    emit_ifc(_bridge(), str(x3))
    emit_ifc(_bridge(schema="IFC4", facility=None), str(four))
    out = tmp_path / "fed.ifc"
    with pytest.raises(MixedSchemaError, match="mix IFC schemas"):
        federate([(x3, "A"), (four, "B")], str(out), _ctx())
    assert not out.exists()                    # refused before writing
    with pytest.raises(MixedSchemaError, match="ctx.schema is IFC4"):
        federate([(x3, "A")], str(out), _ctx(schema="IFC4"))


def test_federate_4x3_without_facility_keeps_storeys(tmp_path):
    a = tmp_path / "plain.ifc"
    emit_ifc(_bridge(facility=None), str(a))
    out = tmp_path / "fed.ifc"
    res = federate([(a, "Bridge")], str(out), _ctx())
    f = ifcopenshell.open(str(out))
    assert [s.Name for s in f.by_type("IfcBuildingStorey")] == ["Bridge"]
    assert res.storeys == 1 and res.facilities == 0
    assert not f.by_type("IfcBridge")


def test_federate_carries_nested_products(tmp_path):
    """A product reached only through IfcRelNests (no container of its own) must
    arrive nested under its host, not orphaned (PR #323 review)."""
    import ifcopenshell.api
    br = tmp_path / "bridge.ifc"
    emit_ifc(_bridge(), str(br))
    src = ifcopenshell.open(str(br))
    host = next(p for p in src.by_type("IfcProduct") if p.Name == "Deck slab")
    plates = [ifcopenshell.api.run("root.create_entity", src,
                                   ifc_class="IfcDiscreteAccessory", name=n)
              for n in ("Deck drain 1", "Deck drain 2")]
    ifcopenshell.api.run("nest.assign_object", src, related_objects=plates,
                         relating_object=host)
    src.write(str(br))

    out = tmp_path / "fed.ifc"
    federate([(br, "Bridge")], str(out), _ctx())
    f = ifcopenshell.open(str(out))
    deck = next(p for p in f.by_type("IfcProduct") if p.Name == "Deck slab")
    nests = [r for r in f.by_type("IfcRelNests") if r.RelatingObject == deck]
    assert len(nests) == 1
    # ordered membership survives
    assert [o.Name for o in nests[0].RelatedObjects] == ["Deck drain 1", "Deck drain 2"]
    assert _ifc_spatial_chain_check(None, str(out)) == []
    assert _validate(out) == []
