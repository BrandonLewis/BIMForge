"""Emitters: takeoff round-trip, georef, GUID/byte determinism, DXF, QTO."""
import uuid

import pytest

pytest.importorskip("ifcopenshell")

from bimforge.author.emit_dxf import emit_dxf
from bimforge.author.emit_ifc import (DuplicateGuidError, GeoreferenceError,
                                      emit_ifc, plan_dims_ft)
from bimforge.author.gate import run_post, run_pre
from bimforge.author.model import Element, StructureModel
from bimforge.author.annotate import AnnotationPlan
from bimforge.author.paycodes import apply as pc_apply
from bimforge.author.paycodes import from_dict
from bimforge.author.primitives import Bolt, Fill, Prism
from bimforge.author.project import ProjectContext

PC = from_dict({
    "project_ref": "fixture",
    "rules": [
        {"match": "(?i)footing", "ifc_class": "IfcFooting", "group": "ftg"},
        {"match": "(?i)anchor bolt", "group": "bolt"},
    ],
    "groups": {"ftg": {"measure": "GrossVolume"},
               "bolt": {"measure": "Count"}},
    "codes": {
        "F-CONC": {"group": "ftg", "measure": "GrossVolume", "unit": "CY",
                   "item_number": "0040", "description": "Fixture footings"},
        "B-AB": {"group": "bolt", "measure": "Count", "unit": "EA",
                 "elements_carry_weight": True},
    },
})


def test_emit_ifc_classifies_under_paycodes_identity(tmp_path):
    import dataclasses

    import ifcopenshell

    m = _fixture_model()
    mf_pc = dataclasses.replace(PC, source_system="MasterFormat", edition="2020")
    out = tmp_path / "mf.ifc"
    emit_ifc(m, str(out), mf_pc)
    f = ifcopenshell.open(str(out))
    cls = f.by_type("IfcClassification")
    assert len(cls) == 1
    assert cls[0].Name == "MasterFormat"
    assert cls[0].Edition == "2020"
    # per-code references still emit under that classification
    refs = f.by_type("IfcClassificationReference")
    assert refs and all(r.ReferencedSource == cls[0] for r in refs)


def test_emit_ifc_handles_geometryless_none_sentinel(tmp_path):
    """emit_ifc must treat a geometry={"kind":"none"} element as shape-less
    (exactly like geometry=None), not raise KeyError on an unknown 'none'
    geometry kind. (#255)"""
    import ifcopenshell

    m = _fixture_model()
    m.add(Element("PS-1 headwall reinforcing", ifc_class="IfcReinforcingBar",
                  geometry={"kind": "none"},
                  quantities={"length_ft": 4.0, "weight_lb": 12.0}))
    out = tmp_path / "none.ifc"
    emit_ifc(m, str(out), PC)
    f = ifcopenshell.open(str(out))
    bars = f.by_type("IfcReinforcingBar")
    assert len(bars) == 1
    assert bars[0].Representation is None        # shape-less, no crash


def test_emit_ifc_defaults_to_bidschedule_without_identity(tmp_path):
    import ifcopenshell

    m = _fixture_model()
    out = tmp_path / "bs.ifc"
    emit_ifc(m, str(out), PC)  # PC leaves source_system/edition at their defaults
    f = ifcopenshell.open(str(out))
    cls = f.by_type("IfcClassification")
    assert len(cls) == 1
    assert cls[0].Name == "BidSchedule"
    assert not cls[0].Edition  # unchanged from historical output


def _fixture_model():
    # The apostrophe in the project name is deliberate: it regression-tests
    # SPF string escaping end-to-end (spec lesson row: an unescaped quote once
    # silently corrupted a hand-authored STEP entity).
    ctx = ProjectContext(name="Fixture Structure (Smith's Crossing)", epsg=2226,
                         base_e=6_594_000.0, base_n=1_943_000.0, base_h=200.0,
                         guid_ns=uuid.UUID("6b1f3c8e-5a2d-4e77-9c31-0b2f4a6d8e10"))
    m = StructureModel("fixture", ctx)
    for i, x in enumerate((0.0, 90.0)):
        p = Prism(f"PS-{i+1} footing", [(-2, -2), (2, -2), (2, 2), (-2, 2)],
                  z_bot=0.0, z_top=2.0, ifc="IfcFooting")
        m.add(Element.from_geometry(p.name, p, ifc_class="IfcFooting", x_ft=x))
    bolt = Bolt("anchor bolt", 0.75, 18.0, count=4, nuts=2)
    m.add(Element("PS-1 anchor bolt", ifc_class="IfcMechanicalFastener",
                  geometry={"kind": "rod", "units": "in", "axis": "z",
                            "radius": 0.375, "length": 18.0, "segments": 32,
                            "centres": [(3, 10.5, 9), (-3, 10.5, 9),
                                        (3, -10.5, 9), (-3, -10.5, 9)]},
                  quantities={"count": 4, "length_ft": 18.0 / 12.0 * 4,
                              "weight_lb": bolt.weight_lb}))
    pc_apply(m, PC)
    return m


def test_pre_gate_passes_and_refuse_local(tmp_path):
    m = _fixture_model()
    assert run_pre(m, PC).passed
    local = StructureModel("x", ProjectContext(name="x", guid_ns=uuid.UUID(int=2)))
    with pytest.raises(GeoreferenceError, match="allow_local"):
        emit_ifc(local, str(tmp_path / "x.ifc"))


def test_emit_ifc_rejects_guid_key_collisions(tmp_path):
    """Carry-forward from the Task 2 review: StructureModel.add dedupes
    elements by NAME only, so an explicit guid_key override on two
    differently-named elements collides silently unless emit_ifc checks."""
    ctx = ProjectContext(name="dup", epsg=2226, guid_ns=uuid.UUID(int=3))
    m = StructureModel("dup", ctx)
    m.add(Element("footing A", ifc_class="IfcFooting", guid_key="shared/key"))
    m.add(Element("footing B", ifc_class="IfcFooting", guid_key="shared/key"))
    with pytest.raises(DuplicateGuidError, match="footing A") as exc:
        emit_ifc(m, str(tmp_path / "dup.ifc"))
    assert "footing B" in str(exc.value)
    assert not (tmp_path / "dup.ifc").exists()


def test_emit_ifc_rejects_element_annotation_guid_collisions(tmp_path):
    ctx = ProjectContext(name="dup", epsg=2226, guid_ns=uuid.UUID(int=31))
    m = StructureModel("dup", ctx)
    m.add(Element("footing A", ifc_class="IfcFooting",
                  guid_key="annotation/0/Stationing"))
    m.annotations.append(
        AnnotationPlan(stamps={"tick": [[(-1.0, 0.0), (1.0, 0.0)]]},
                       instances=[], name="Stationing"))
    with pytest.raises(DuplicateGuidError, match="footing A") as exc:
        emit_ifc(m, str(tmp_path / "dup.ifc"))
    assert "annotation Stationing" in str(exc.value)
    assert not (tmp_path / "dup.ifc").exists()


def test_emit_ifc_rejects_assembly_guid_collisions(tmp_path):
    """Assemblies share the keyed-GlobalId space too: an element whose explicit
    guid_key resolves to `assembly/<name>` collides with that assembly."""
    ctx = ProjectContext(name="dup", epsg=2226, guid_ns=uuid.UUID(int=32))
    m = StructureModel("dup", ctx)
    m.add(Element("footing A", ifc_class="IfcFooting", guid_key="assembly/rig"))
    m.add(Element("post", ifc_class="IfcColumn"))
    m.assemblies["rig"] = ["post"]
    with pytest.raises(DuplicateGuidError, match="assembly rig"):
        emit_ifc(m, str(tmp_path / "dup.ifc"))
    assert not (tmp_path / "dup.ifc").exists()


def test_emit_ifc_round_trips_through_build_takeoff(tmp_path):
    import ifcopenshell
    from bimforge.bim.ifc_takeoff import build_takeoff
    m = _fixture_model()
    out = tmp_path / "fixture.ifc"
    emit_ifc(m, str(out), PC)
    takeoff, warnings = build_takeoff(str(out), PC.takeoff_map(m.codes_used()))
    rows = {r["cost_code"]: r for r in takeoff["rows"]}
    # two 4x4x2 footings -> 64 cf = 2.3704 CY
    assert rows["F-CONC"]["quantity"] == pytest.approx(64.0 / 27.0, rel=1e-4)
    assert rows["F-CONC"]["unit"] == "CY"
    assert rows["F-CONC"]["item_number"] == "0040"
    assert rows["B-AB"]["quantity"] == pytest.approx(4.0)
    assert rows["B-AB"]["unit"] == "EA"
    # georef: base written in CRS units, scale converts model metres back
    f = ifcopenshell.open(str(out))
    conv = f.by_type("IfcMapConversion")[0]
    assert conv.Eastings == pytest.approx(6_594_000.0)
    assert conv.Northings == pytest.approx(1_943_000.0)
    assert conv.Scale == pytest.approx(1.0 / m.ctx.ft_to_m)
    assert f.by_type("IfcProjectedCRS")[0].Name == "EPSG:2226"
    # L x W invariant on the emitted Qto (contract: L*W == GrossArea)
    from bimforge.bim.ifc_takeoff import quantities_of
    el = [e for e in f.by_type("IfcFooting")][0]
    q = quantities_of(el)
    assert q["Length"] * q["Width"] == pytest.approx(q["GrossArea"], rel=1e-9)
    assert q["Height"] * q["GrossArea"] == pytest.approx(q["GrossVolume"], rel=1e-9)


def test_emit_ifc_solid_tube_uses_circle_profile(tmp_path):
    """wall == r_outer is a solid cylinder (a boolean void tool, e.g. the
    headwall pipe opening); IfcCircleHollowProfileDef requires
    WallThickness < Radius, so the emitter must fall back to the solid
    IfcCircleProfileDef there."""
    import ifcopenshell
    ctx = ProjectContext(name="tubes", epsg=2226,
                         base_e=6_594_000.0, base_n=1_943_000.0,
                         guid_ns=uuid.UUID(int=7))
    m = StructureModel("tubes", ctx)
    tube = {"kind": "tube", "units": "ft", "x0": 0.0, "length": 4.0,
            "cz": 1.0, "r_outer": 1.0, "axis": "x"}
    m.add(Element("hollow pipe", ifc_class="IfcPipeSegment",
                  geometry={**tube, "wall": 0.25}))
    m.add(Element("solid plug", ifc_class="IfcBuildingElementProxy",
                  geometry={**tube, "wall": 1.0}))
    out = tmp_path / "t.ifc"
    emit_ifc(m, str(out))
    f = ifcopenshell.open(str(out))
    hollow = f.by_type("IfcCircleHollowProfileDef")
    assert len(hollow) == 1
    assert hollow[0].WallThickness < hollow[0].Radius
    assert len(f.by_type("IfcCircleProfileDef", include_subtypes=False)) == 1


def test_emit_ifc_is_byte_deterministic(tmp_path):
    m1, m2 = _fixture_model(), _fixture_model()
    a, b = tmp_path / "a.ifc", tmp_path / "b.ifc"
    emit_ifc(m1, str(a), PC)
    emit_ifc(m2, str(b), PC)
    ca, cb = a.read_bytes(), b.read_bytes()
    assert ca == cb


def _voids_assembly_model():
    """One element voided by an opening + a two-member IfcElementAssembly —
    the relationship paths Task 9's families populate."""
    ctx = ProjectContext(name="Voids Fixture", epsg=2226,
                         base_e=6_594_000.0, base_n=1_943_000.0,
                         guid_ns=uuid.UUID("2c9d4a1b-7e35-4f08-8a66-1d3b5c7e9f21"))
    m = StructureModel("voids", ctx)
    for i, x in enumerate((0.0, 40.0)):
        p = Prism(f"WW-{i+1} footing", [(-3, -3), (3, -3), (3, 3), (-3, 3)],
                  z_bot=0.0, z_top=2.0, ifc="IfcFooting")
        m.add(Element.from_geometry(p.name, p, ifc_class="IfcFooting", x_ft=x))
    sleeve = Element("WW-1 sleeve opening",
                     geometry={"kind": "prism", "units": "ft",
                               "base": [(-0.5, -0.5), (0.5, -0.5),
                                        (0.5, 0.5), (-0.5, 0.5)],
                               "z_bot": 0.5, "z_top": 1.5})
    m.openings.append(("WW-1 footing", sleeve))
    m.assemblies["footing group"] = ["WW-1 footing", "WW-2 footing"]
    return m


def test_emit_ifc_openings_assembly_topology_and_determinism(tmp_path):
    """The generic relationship sort protects the openings/assembly paths:
    two separately-built file objects are byte-identical, AND the topology is
    right by GlobalId — the void links the right host/opening, the assembly
    aggregate carries exactly its two members."""
    import ifcopenshell
    m1, m2 = _voids_assembly_model(), _voids_assembly_model()
    a, b = tmp_path / "a.ifc", tmp_path / "b.ifc"
    emit_ifc(m1, str(a))
    emit_ifc(m2, str(b))
    assert a.read_bytes() == b.read_bytes()

    f = ifcopenshell.open(str(a))
    guid = m1.ctx.guid
    voids = f.by_type("IfcRelVoidsElement")
    assert len(voids) == 1
    assert voids[0].RelatingBuildingElement.GlobalId == guid("element/WW-1 footing")
    assert voids[0].RelatedOpeningElement.GlobalId == guid("element/WW-1 sleeve opening")
    asms = f.by_type("IfcElementAssembly")
    assert len(asms) == 1
    assert asms[0].GlobalId == guid("assembly/footing group")
    aggs = [r for r in f.by_type("IfcRelAggregates")
            if r.RelatingObject == asms[0]]
    assert len(aggs) == 1
    assert {o.GlobalId for o in aggs[0].RelatedObjects} == {
        guid("element/WW-1 footing"), guid("element/WW-2 footing")}


def test_project_context_defaults_to_ifc4x3_with_ifc4_opt_out(tmp_path):
    """#332 reverses #133's default: IFC4X3_ADD2 is the civil schema
    (IfcAlignment, the facility tree, IfcEarthworksFill) and the only one that
    can carry an alignment-swept solid. #133's reason still holds for the
    opt-out — Navisworks, Revit, Solibri, BIMcollab and most browser viewers
    open IFC4X3 as an empty model with no error — so `schema: IFC4` must keep
    working, and the emitted file must honour whichever is chosen.
    """
    import ifcopenshell
    assert ProjectContext(name="x", guid_ns=uuid.UUID(int=1)).schema == \
        "IFC4X3_ADD2"
    spec = ProjectContext.from_spec(
        {"name": "x", "guid_ns": "00000000-0000-0000-0000-000000000001"})
    assert spec.schema == "IFC4X3_ADD2"
    opt_out = ProjectContext.from_spec(
        {"name": "x", "guid_ns": "00000000-0000-0000-0000-000000000001",
         "schema": "IFC4"})
    assert opt_out.schema == "IFC4"

    m = _fixture_model()
    assert m.ctx.schema == "IFC4X3_ADD2"
    out = tmp_path / "s.ifc"
    emit_ifc(m, str(out), PC)
    assert ifcopenshell.open(str(out)).schema_identifier == "IFC4X3_ADD2"


def _offset_void_model(y0: float):
    """A wall voided by a pipe sleeve, BOTH placed at y = `y0`.

    The issue #131 field case reduced: two identical Caltrans dual-pipe
    headwalls in one family, the second offset down the culvert run. The
    declared volume is net of the sleeve, so any emitter that leaves the void
    behind at y = 0 reports the GROSS volume and the gate catches it.
    """
    ctx = ProjectContext(name="Offset Voids", epsg=2226,
                         base_e=6_594_000.0, base_n=1_943_000.0,
                         guid_ns=uuid.UUID("9f2e7c41-3b6a-4d95-8e02-5a7c1f3b9d64"))
    m = StructureModel("offset voids", ctx)
    wall_base = [(-4, -1), (4, -1), (4, 1), (-4, 1)]
    gross_cf = 8.0 * 2.0 * 6.0                       # 8 x 2 plan, 6 tall
    sleeve_cf = 1.0 * 2.0 * 2.0                      # 1 wide, through the 2 ft
    #                                                  thickness, 2 tall
    m.add(Element("headwall", ifc_class="IfcWall", y_ft=y0,
                  geometry={"kind": "prism", "units": "ft", "base": wall_base,
                            "z_bot": 0.0, "z_top": 6.0},
                  quantities={"volume_cf": gross_cf - sleeve_cf}))
    m.openings.append(("headwall", Element(
        "headwall sleeve", y_ft=y0,
        geometry={"kind": "prism", "units": "ft",
                  "base": [(-0.5, -1), (0.5, -1), (0.5, 1), (-0.5, 1)],
                  "z_bot": 2.0, "z_top": 4.0})))
    return m


def test_emit_ifc_applies_an_opening_elements_placement(tmp_path):
    """Issue #131: emit_ifc built openings with `root.create_entity` and never
    read the opening Element's x_ft/y_ft/z_ft, so a void stayed at the origin
    while its host moved. Regular elements honoured those fields all along.
    """
    import ifcopenshell
    import ifcopenshell.util.placement
    m = _offset_void_model(35.0)
    out = tmp_path / "v.ifc"
    emit_ifc(m, str(out))
    f = ifcopenshell.open(str(out))
    op = f.by_type("IfcOpeningElement")[0]
    mtx = ifcopenshell.util.placement.get_local_placement(op.ObjectPlacement)
    assert mtx[1, 3] == pytest.approx(35.0 * m.ctx.ft_to_m)
    # and it still voids the right host
    assert op.VoidsElements[0].RelatingBuildingElement.Name == "headwall"


def test_emit_ifc_and_emit_step_agree_on_an_offset_void(tmp_path):
    """The half of #131 that mattered most: after setting y_ft on the opening,
    emit_step's true-volume check passed while emit_ifc's mesh check still
    failed — the two emitters disagreed about the same model. Both legs of
    the post-emit gate must now pass on the same offset-void model.
    """
    m = _offset_void_model(35.0)
    ifc = tmp_path / "agree.ifc"
    emit_ifc(m, str(ifc))
    rep = run_post(m, {"ifc": str(ifc)})
    assert rep.passed, rep.format("post")

    b3d = pytest.importorskip("build123d")     # noqa: F841 - [solids] extra
    from bimforge.author.emit_step import true_volume_check
    assert true_volume_check(m, {}) == []


def test_base_quantities_declared_length_keeps_lxw_equals_area():
    """A declared length_ft overrides the perimeter-derived Length (#252), but
    Width must then be recomputed from the area so L x W == GrossArea still
    holds — otherwise check_lxw_volume fails on any element that carries both a
    real footprint area and a declared pay length."""
    from bimforge.author.emit_ifc import base_quantities
    el = Element("footprint", classifications=["F"], quantities={
        "area_sf": 40.0, "length_ft": 10.0, "perimeter_ft": 28.0,
        "volume_cf": 80.0})
    q = {name: val for _entity, name, val in base_quantities(el, ft_to_m=1.0)}
    assert q["Length"] == pytest.approx(10.0)          # the declared pay length
    assert q["Width"] == pytest.approx(4.0)            # area / length, not perim
    assert q["Length"] * q["Width"] == pytest.approx(q["GrossArea"])


def test_emit_ifc_prism_per_vertex_bottom_meshes_the_wedge(tmp_path):
    """A Prism carrying a per-vertex `bottom_z` (sloping floor) has no uniform
    sweep depth, so emit_ifc must build the triangulated B-rep — the same path
    a per-vertex `top_z` takes — and the read-back GrossVolume must equal the
    analytic wedge. The post-emit mesh gate must also pass. (#251)"""
    import ifcopenshell
    from bimforge.bim.ifc_takeoff import quantities_of
    ctx = ProjectContext(name="wedge", epsg=2226, base_e=6_594_000.0,
                         base_n=1_943_000.0, guid_ns=uuid.UUID(int=13))
    m = StructureModel("wedge", ctx)
    base = [(0, 0), (10, 0), (10, 2), (0, 2)]
    p = Prism("wedge", base, z_bot=0.0, z_top=4.0,       # depth 4 -> 2, mean 3
              bottom_z=[0.0, 2.0, 2.0, 0.0], ifc="IfcWall")
    m.add(Element.from_geometry("wedge", p, ifc_class="IfcWall"))
    out = tmp_path / "wedge.ifc"
    emit_ifc(m, str(out))
    # A faceted B-rep, not a uniform extrude, carries the wedge:
    f = ifcopenshell.open(str(out))
    assert not f.by_type("IfcExtrudedAreaSolid")
    assert f.by_type("IfcFacetedBrep")
    q = quantities_of(f.by_type("IfcWall")[0])
    # Qto is in model units (metres): 60 cf * (ft->m)^3.
    assert q["GrossVolume"] == pytest.approx(60.0 * ctx.ft_to_m ** 3, rel=1e-6)
    assert run_post(m, {"ifc": str(out)}).passed


def test_emit_ifc_tube_honours_a_y_origin(tmp_path):
    """The second half of #131: the tube branch hard-coded the Y component of
    its placement, so a Y-axis tube always swept world-Y FROM ZERO and the
    geometry dict exposed no y-origin key beside `x0`. Both emitters now read
    `y0` (default 0.0, so every existing dict is untouched)."""
    import ifcopenshell
    ctx = ProjectContext(name="ytube", epsg=2226, base_e=6_594_000.0,
                         base_n=1_943_000.0, guid_ns=uuid.UUID(int=11))
    m = StructureModel("ytube", ctx)
    m.add(Element("y sleeve", ifc_class="IfcPipeSegment",
                  geometry={"kind": "tube", "units": "ft", "axis": "y",
                            "x0": 2.0, "y0": 7.0, "cz": 1.5,
                            "r_outer": 0.5, "wall": 0.5, "length": 4.0}))
    out = tmp_path / "y.ifc"
    emit_ifc(m, str(out))
    f = ifcopenshell.open(str(out))
    loc = f.by_type("IfcExtrudedAreaSolid")[0].Position.Location.Coordinates
    k = ctx.ft_to_m
    assert loc == pytest.approx((2.0 * k, 7.0 * k, 1.5 * k))


def test_emit_step_tube_honours_the_same_y_origin():
    """Companion to the IFC assertion: the STEP emitter reads `y0` too, so the
    two never disagree about where a Y-axis tube starts (the #131 lesson)."""
    pytest.importorskip("build123d")
    from bimforge.author.emit_step import _solid_from_dict
    d = {"kind": "tube", "units": "ft", "axis": "y", "x0": 2.0, "y0": 7.0,
         "cz": 1.5, "r_outer": 0.5, "wall": 0.5, "length": 4.0}
    part = _solid_from_dict(None, d)[0]
    bb = part.bounding_box()
    assert bb.min.Y == pytest.approx(7.0, abs=1e-9)
    assert bb.max.Y == pytest.approx(11.0, abs=1e-9)


def _spatial_children(obj):
    """The IfcRelAggregates children of one spatial element — the traversal an
    importer performs walking Project -> Site -> Building -> Storey."""
    return [o for rel in obj.IsDecomposedBy for o in rel.RelatedObjects]


def test_emit_ifc_decomposes_project_site_building_storey(tmp_path):
    """Issue #132: the storey used to aggregate DIRECTLY under the site.

    That is an invalid spatial decomposition in every IFC schema — a storey
    decomposes a BUILDING, and a site contains buildings, not storeys — so an
    importer walking Project -> Site -> Building -> Storey never reaches the
    storey and the whole model renders as nothing (confirmed empty in
    Bonsai 0.8.5). Neither `ifcopenshell.validate()` nor `geom.iterator`
    catches it, because products carry ABSOLUTE placements and never traverse
    the spatial tree; only walking the chain does. `dxf2bim.build_ifc` has
    always written the building — this is emit_ifc catching up.
    """
    import ifcopenshell
    m = _fixture_model()
    out = tmp_path / "b.ifc"
    emit_ifc(m, str(out), PC)
    f = ifcopenshell.open(str(out))

    sites = _spatial_children(f.by_type("IfcProject")[0])
    assert [s.is_a() for s in sites] == ["IfcSite"]
    buildings = _spatial_children(sites[0])
    assert [b.is_a() for b in buildings] == ["IfcBuilding"]
    storeys = _spatial_children(buildings[0])
    assert [s.is_a() for s in storeys] == ["IfcBuildingStorey"]

    # and every product still lands in the storey the walk now reaches
    contained = {p.GlobalId
                 for rel in storeys[0].ContainsElements
                 for p in rel.RelatedElements}
    assert {m.ctx.guid(el.guid_key) for el in m.elements} <= contained


def test_emit_ifc_gives_every_spatial_container_an_origin_placement(tmp_path):
    """Companion to #132: the spatial containers carried NO ObjectPlacement.

    Products place absolutely (PlacementRelTo $), so nothing moves either
    way — but an importer that resolves a product's container chain to build
    a transform hits a null placement on the way up. The postprocess proven
    to open in Bonsai adds these, so the emitter writes them itself.
    """
    import ifcopenshell
    import ifcopenshell.util.placement
    m = _fixture_model()
    out = tmp_path / "p.ifc"
    emit_ifc(m, str(out), PC)
    f = ifcopenshell.open(str(out))
    for cls in ("IfcSite", "IfcBuilding", "IfcBuildingStorey"):
        spatial = f.by_type(cls)[0]
        assert spatial.ObjectPlacement is not None, f"{cls} has no placement"
        mtx = ifcopenshell.util.placement.get_local_placement(
            spatial.ObjectPlacement)
        assert list(mtx[:3, 3]) == [0.0, 0.0, 0.0], f"{cls} is not at the origin"


def test_post_gate_rejects_a_storey_unreachable_from_the_project(tmp_path):
    """The gate check that would have caught #132 before delivery: an IFC
    whose storey cannot be reached from IfcProject through IfcRelAggregates
    fails post-emit and the outputs are DELETED."""
    import ifcopenshell
    m = _fixture_model()
    ifc = tmp_path / "orphan.ifc"
    emit_ifc(m, str(ifc), PC)

    # sever the building -> storey link, reproducing the pre-fix topology
    f = ifcopenshell.open(str(ifc))
    storey = f.by_type("IfcBuildingStorey")[0]
    for rel in list(storey.Decomposes):
        f.remove(rel)
    f.write(str(ifc))

    rep = run_post(m, {"ifc": str(ifc)}, PC)
    assert not rep.passed
    assert any("spatial" in msg.lower() for msg in rep.failures), rep.failures
    assert not ifc.exists()


def test_post_gate_mesh_and_map_coverage(tmp_path):
    import yaml
    m = _fixture_model()
    ifc = tmp_path / "m.ifc"
    emit_ifc(m, str(ifc), PC)
    tmap = tmp_path / "map.yaml"
    tmap.write_text(yaml.safe_dump(PC.takeoff_map(m.codes_used())),
                    encoding="utf-8")
    rep = run_post(m, {"ifc": str(ifc), "takeoff_map": str(tmap)}, PC)
    assert rep.passed, rep.format("post")
    assert ifc.exists()
    # coverage failure deletes outputs
    bad = tmp_path / "bad-map.yaml"
    bad.write_text("codes: {GHOST: {measure: Count, unit: EA}}\n",
                   encoding="utf-8")
    ifc2 = tmp_path / "m2.ifc"
    emit_ifc(m, str(ifc2), PC)
    rep = run_post(m, {"ifc": str(ifc2), "takeoff_map": str(bad)}, PC)
    assert not rep.passed
    assert not ifc2.exists() and not bad.exists()


def test_emit_dxf_draws_and_is_deterministic(tmp_path):
    import ezdxf
    m = _fixture_model()
    m.dxf_annotations.append(
        lambda msp, model: msp.add_text("FIXTURE PLAN", height=0.2,
                                        dxfattribs={"layer": "S-ANNO-TEXT"}))
    a, b = tmp_path / "a.dxf", tmp_path / "b.dxf"
    emit_dxf(m, str(a))
    emit_dxf(m, str(b))
    assert a.read_bytes() == b.read_bytes()
    doc = ezdxf.readfile(str(a))
    kinds = [e.dxftype() for e in doc.modelspace()]
    assert kinds.count("LWPOLYLINE") == 2      # two footing footprints
    assert kinds.count("CIRCLE") == 4          # four bolt circles
    assert "TEXT" in kinds                     # the annotation callback ran


def test_emit_qto_workbook(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from bimforge.author.emit_qto import emit_qto
    m = _fixture_model()
    out = tmp_path / "q.xlsx"
    emit_qto(m, str(out), PC)
    wb = openpyxl.load_workbook(str(out))
    rows = {r[0]: r for r in wb["Summary"].iter_rows(min_row=2, values_only=True)}
    assert rows["F-CONC"][3] == pytest.approx(64.0 / 27.0, abs=1e-3)
    assert rows["B-AB"][3] == 4
    assert wb["Elements"].max_row == 4          # header + 3 elements


def test_plan_dims_rectangle_and_squat_fallback():
    el = Element("x", quantities={})
    L, W = plan_dims_ft(el, area_ft2=16.0, perim_ft=16.0)   # 4x4 rectangle
    assert (L, W) == (pytest.approx(4.0), pytest.approx(4.0))
    L, W = plan_dims_ft(el, area_ft2=16.0, perim_ft=10.0)   # impossible: square
    assert L == W == pytest.approx(4.0)
    el2 = Element("y", quantities={"width_ft": 2.0})
    assert plan_dims_ft(el2, 16.0, 100.0) == (pytest.approx(8.0), 2.0)


def test_plan_dims_uses_a_real_side_when_width_ft_is_a_thickness():
    """#180: width_ft serves two masters — the gate's count×L×W×H invariant
    wants the solid's SECTION width, plan_dims wants a side of the plan/face
    rectangle. When area_sf is a FACE, dividing it by the section thickness
    invents an absurd Length (RW2 lagging: 126.5 sf / 0.5 ft = 253 ft). Derive
    the rectangle from a real side (length_ft) instead, keeping L×W == area."""
    el = Element("RW2 lagging", quantities={
        "area_sf": 126.5, "width_ft": 0.5, "length_ft": 12.0,
        "height_ft": 0.9583, "volume_cf": 63.25, "count": 11})
    L, W = plan_dims_ft(el, area_ft2=126.5, perim_ft=25.0)
    assert L * W == pytest.approx(126.5)              # the invariant still holds
    assert L == pytest.approx(12.0)                  # the real course length
    assert W == pytest.approx(126.5 / 12.0)          # ~10.54 ft, the face height
    assert L / W < 500                               # NOT the 506:1 thickness ratio


def test_plan_dims_falls_back_to_rectangle_solve_without_a_real_side():
    """When width_ft is a thickness and there is no length_ft to lean on, fall
    back to the area+perimeter rectangle solve (then a square) — never the
    thickness-divided nonsense."""
    el = Element("skin", quantities={"area_sf": 240.0, "width_ft": 0.02})
    L, W = plan_dims_ft(el, area_ft2=240.0, perim_ft=62.0)   # footprint perim
    assert L * W == pytest.approx(240.0)
    assert L / max(W, 1e-9) < 500                     # no 12000×0.02 phantom


def test_plan_dims_keeps_a_genuine_long_thin_run():
    """A real long-thin run (area IS the footprint, width_ft IS the plan side)
    can exceed the aspect threshold too. With no length_ft and no rectangle
    solution, keep (length, width) — do NOT regress it to a square."""
    el = Element("long run", quantities={"area_sf": 1000.0, "width_ft": 1.0})
    # perim = 4*sqrt(area): the squat default that has no rectangle solution
    L, W = plan_dims_ft(el, area_ft2=1000.0, perim_ft=4.0 * (1000.0 ** 0.5))
    assert (L, W) == (pytest.approx(1000.0), pytest.approx(1.0))


def _terrain_model():
    ctx = ProjectContext(name="Terrain Fixture", epsg=2226,
                         base_e=6_594_000.0, base_n=1_943_000.0,
                         guid_ns=uuid.UUID(int=11))
    m = StructureModel("terrain", ctx)
    verts = [(0.0, 0.0, 100.0), (10.0, 0.0, 101.0),
             (0.0, 10.0, 102.0), (10.0, 10.0, 103.0)]
    m.add(Element(
        "Existing ground — USGS 3DEP DEM",
        ifc_class="IfcGeographicElement", predefined_type="TERRAIN",
        classifications=[],                       # reference geometry
        geometry={"kind": "mesh", "verts": verts,
                  "tris": [(0, 1, 2), (1, 3, 2)], "units": "ft",
                  "provenance": {"Source": "USGS 3DEP DEM",
                                 "SurveyGrade": False}}))
    return m


def test_emit_ifc_mesh_kind_terrain_reference_element(tmp_path):
    """The "mesh" geometry kind (terrain): an IfcGeographicElement/TERRAIN
    whose representation is a faceted brep with one face per triangle, verts
    scaled by the dict's units factor; reference geometry (classifications
    []) gets NO IfcElementQuantity and no classification association, and
    the provenance dict on the mesh rides as Pset_BimforgeTerrain."""
    import ifcopenshell
    import ifcopenshell.util.element
    m = _terrain_model()
    out = tmp_path / "terrain.ifc"
    emit_ifc(m, str(out))
    f = ifcopenshell.open(str(out))
    geo = f.by_type("IfcGeographicElement")
    assert len(geo) == 1
    assert geo[0].PredefinedType == "TERRAIN"
    breps = [i for r in geo[0].Representation.Representations
             for i in r.Items if i.is_a("IfcFacetedBrep")]
    assert len(breps) == 1
    assert len(breps[0].Outer.CfsFaces) == 2      # one face per triangle
    coords = {tuple(p.Coordinates)
              for face in breps[0].Outer.CfsFaces
              for p in face.Bounds[0].Bound.Polygon}
    k = m.ctx.ft_to_m
    assert (10.0 * k, 10.0 * k, 103.0 * k) in coords
    # reference geometry: never a pay quantity — no Qto, and no
    # classification reference on the product (the empty BidSchedule
    # IfcClassification itself is always declared, associated to the
    # project — pre-existing behavior, not a product classification).
    assert not f.by_type("IfcElementQuantity")
    assert not f.by_type("IfcClassificationReference")
    assert not [r for r in f.by_type("IfcRelAssociatesClassification")
                if geo[0] in r.RelatedObjects]
    # provenance pset
    psets = ifcopenshell.util.element.get_psets(geo[0])
    assert psets["Pset_BimforgeTerrain"]["Source"] == "USGS 3DEP DEM"
    assert psets["Pset_BimforgeTerrain"]["SurveyGrade"] is False


def test_emit_ifc_terrain_is_byte_deterministic(tmp_path):
    a, b = tmp_path / "a.ifc", tmp_path / "b.ifc"
    emit_ifc(_terrain_model(), str(a))
    emit_ifc(_terrain_model(), str(b))
    assert a.read_bytes() == b.read_bytes()


def _fill_model(schema="IFC4X3_ADD2"):
    """A 10x10 backfill 0->5 ft gross with a 6x6 footing cut 0->2 ft:
    gross 500 cf less 72 cf = 428 cf net (the bridge-pilot backfill shape).

    Pinned to IFC4X3 by default because `Fill` defaults to IfcEarthworksFill,
    a 4X3-only class — this fixture exercises the CSG geometry, and the
    schema-downgrade path gets its own test.
    """
    ctx = ProjectContext(name="Fill Fixture", epsg=2226, schema=schema,
                         base_e=6_594_000.0, base_n=1_943_000.0,
                         guid_ns=uuid.UUID(int=13))
    m = StructureModel("fill", ctx)
    fill = Fill("backfill", base=[(0, 0), (10, 0), (10, 10), (0, 10)],
                z_bot=0.0, z_top=5.0,
                cuts=[Prism("ftg", [(2, 2), (8, 2), (8, 8), (2, 8)],
                            0.0, 2.0)])
    # off-origin placement on purpose: a regression that offsets the cuts (or
    # the gross) by element placement a second time would shift the cut out
    # of the gross and the difference silently no-ops — at the origin that
    # bug is invisible to the volume assertion.
    m.add(Element.from_geometry(fill.name, fill, ifc_class=fill.ifc,
                                classifications=[], x_ft=25.0, y_ft=10.0))
    return m, fill


def test_emit_ifc_fill_boolean_difference_is_the_real_shape(tmp_path):
    """The "fill" geometry kind: gross prism chained-DIFFERENCEd by its cuts
    (IfcBooleanResult), the body ShapeRepresentation typed "CSG", and the
    emitted boolean IS the backfill — re-tessellating it through the geometry
    iterator integrates to the analytic net volume (bridge-pilot port: the viewer
    shows the real shape and ifcopenshell derives the real volume from it)."""
    import ifcopenshell
    import ifcopenshell.geom
    import numpy as np
    m, fill = _fill_model()
    out = tmp_path / "fill.ifc"
    emit_ifc(m, str(out))
    f = ifcopenshell.open(str(out))
    bools = f.by_type("IfcBooleanResult")
    assert len(bools) >= 1
    assert all(b.Operator == "DIFFERENCE" for b in bools)
    (el,) = f.by_type("IfcEarthworksFill")
    (rep,) = el.Representation.Representations
    assert rep.RepresentationIdentifier == "Body"
    assert rep.RepresentationType == "CSG"
    # the boolean is the real shape: mesh volume within 0.5% of 428 cf
    shape = ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(), el)
    v = np.asarray(shape.geometry.verts, dtype=float).reshape(-1, 3)
    t = np.asarray(shape.geometry.faces, dtype=int).reshape(-1, 3)
    vol = abs(np.einsum("ij,ij->i", v[t[:, 0]],
                        np.cross(v[t[:, 1]], v[t[:, 2]])).sum()) / 6.0
    assert fill.volume_cf == pytest.approx(500.0 - 72.0)
    assert vol == pytest.approx(fill.volume_cf * m.ctx.ft_to_m ** 3, rel=5e-3)


def test_emit_ifc_downgrades_a_4x3_only_class_and_says_so(tmp_path, capsys):
    """Fallout from #133 that the issue did not anticipate: `Fill` defaults to
    IfcEarthworksFill, which exists ONLY in IFC4X3 — under the new IFC4
    default ifcopenshell raises "Entity ... not found in schema 'IFC4'".

    Refusing to emit would make IFC4 unusable for earthwork; silently
    swapping the class would hide it. So: carry the element as an
    IfcBuildingElementProxy, record the intended class in ObjectType so a
    civil consumer can still recover it, and WARN — which is what makes the
    IFC4X3 opt-in discoverable at the moment it matters.
    """
    import ifcopenshell
    m, fill = _fill_model(schema="IFC4")
    out = tmp_path / "fill4.ifc"
    emit_ifc(m, str(out))
    f = ifcopenshell.open(str(out))
    assert f.schema == "IFC4"
    # (no by_type("IfcEarthworksFill") here — it RAISES on a schema that has
    # no such declaration rather than returning an empty list)
    (el,) = [p for p in f.by_type("IfcBuildingElementProxy")
             if p.Name == "backfill"]
    assert el.ObjectType == "IfcEarthworksFill"
    err = capsys.readouterr().err
    assert "IfcEarthworksFill" in err and "IFC4" in err
    assert "IFC4X3_ADD2" in err              # names the default to return to


def test_emit_ifc_keeps_a_4x3_class_when_4x3_is_opted_into(tmp_path, capsys):
    """The other side of the downgrade: opting in keeps the real class and
    emits no warning at all."""
    import ifcopenshell
    m, _fill = _fill_model(schema="IFC4X3_ADD2")
    out = tmp_path / "fill43.ifc"
    emit_ifc(m, str(out))
    f = ifcopenshell.open(str(out))
    assert len(f.by_type("IfcEarthworksFill")) == 1
    assert "IfcEarthworksFill" not in capsys.readouterr().err


def test_emit_ifc_fill_is_byte_deterministic(tmp_path):
    a, b = tmp_path / "a.ifc", tmp_path / "b.ifc"
    emit_ifc(_fill_model()[0], str(a))
    emit_ifc(_fill_model()[0], str(b))
    assert a.read_bytes() == b.read_bytes()


def test_emit_dxf_mesh_plan_ring_draws_one_closed_polyline(tmp_path):
    """A "mesh" dict WITH the new "plan" key draws its ring(s) as closed
    LWPOLYLINEs at the element offset; a mesh WITHOUT "plan" still draws
    nothing (the R5a terrain behavior must not change)."""
    import ezdxf
    ctx = ProjectContext(name="mesh dxf", epsg=2226, guid_ns=uuid.UUID(int=14))
    m = StructureModel("meshdxf", ctx)
    verts = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (0.0, 10.0, 0.0),
             (4.0, 10.0, 1.0)]
    tris = [(0, 1, 2), (1, 3, 2)]
    m.add(Element("weir with plan",
                  geometry={"kind": "mesh", "units": "ft", "verts": verts,
                            "tris": tris,
                            "plan": [[(0, 0), (4, 0), (4, 10), (0, 10)]]},
                  x_ft=100.0))
    m.add(Element("terrain no plan",
                  geometry={"kind": "mesh", "units": "ft", "verts": verts,
                            "tris": tris}))
    out = tmp_path / "m.dxf"
    emit_dxf(m, str(out))
    doc = ezdxf.readfile(str(out))
    ents = list(doc.modelspace())
    assert [e.dxftype() for e in ents] == ["LWPOLYLINE"]
    (poly,) = ents
    assert poly.closed
    pts = {(round(x, 6), round(y, 6)) for x, y, *_ in poly.get_points()}
    assert pts == {(100.0, 0.0), (104.0, 0.0), (104.0, 10.0), (100.0, 10.0)}


def test_emit_dxf_fill_draws_gross_base_on_element_layer(tmp_path):
    """A "fill" dict draws its GROSS base ring (one closed polyline, not the
    cuts) on the element's layer."""
    import ezdxf
    ctx = ProjectContext(name="fill dxf", epsg=2226, guid_ns=uuid.UUID(int=15))
    m = StructureModel("filldxf", ctx)
    fill = Fill("backfill", base=[(0, 0), (10, 0), (10, 10), (0, 10)],
                z_bot=0.0, z_top=5.0,
                cuts=[Prism("ftg", [(2, 2), (8, 2), (8, 8), (2, 8)],
                            0.0, 2.0)])
    m.add(Element.from_geometry(fill.name, fill, ifc_class=fill.ifc,
                                classifications=[], layer="S-EW-FILL"))
    out = tmp_path / "f.dxf"
    emit_dxf(m, str(out))
    doc = ezdxf.readfile(str(out))
    ents = list(doc.modelspace())
    assert [e.dxftype() for e in ents] == ["LWPOLYLINE"]
    (poly,) = ents
    assert poly.closed
    assert poly.dxf.layer == "S-EW-FILL"
    pts = {(round(x, 6), round(y, 6)) for x, y, *_ in poly.get_points()}
    assert pts == {(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)}


def test_emit_ifc_writes_true_north_from_convergence(tmp_path):
    pytest.importorskip("pyproj")
    import math
    import ifcopenshell
    from bimforge.cad.geo import true_north_direction
    m = _fixture_model()
    out = tmp_path / "tn.ifc"
    emit_ifc(m, str(out), PC)
    f = ifcopenshell.open(str(out))
    ctxs = [c for c in f.by_type("IfcGeometricRepresentationContext")
            if not c.is_a("IfcGeometricRepresentationSubContext")]
    tn = ctxs[0].TrueNorth
    assert tn is not None
    x, y = float(tn.DirectionRatios[0]), float(tn.DirectionRatios[1])
    ex, ey = true_north_direction(2226, 6_594_000.0, 1_943_000.0)
    assert (x, y) != (0.0, 1.0)
    assert x == pytest.approx(ex, abs=1e-6)
    assert y == pytest.approx(ey, abs=1e-6)
    assert math.hypot(x, y) == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Local-coordinate gate (issue #156). The check that would have caught
# bridge-standard authoring at raw State Plane coordinates — and the high-elevation bridge (#134)
# authoring at true elevation — at BUILD time, with an accurate message.
#
# Nothing else can see it. Volume is translation-invariant, so the lxw,
# faceting, mesh and true-volume checks all pass on a model sitting a million
# feet from the origin; the only symptom was `est-bim kml` refusing the file
# and blaming the pre-0.1.11 georeferencing bug instead.
# ---------------------------------------------------------------------------

def test_local_coordinate_gate_passes_a_normally_placed_model():
    from bimforge.author.gate import check_local_coordinates
    assert check_local_coordinates(_fixture_model()) == []


def test_local_coordinate_gate_catches_survey_coordinates_in_geometry():
    """Geometry authored at State Plane easting instead of model feet."""
    from bimforge.author.gate import check_local_coordinates
    ctx = ProjectContext(name="survey", epsg=2226, base_e=6_594_000.0,
                         base_n=1_943_000.0, guid_ns=uuid.UUID(int=31))
    m = StructureModel("survey", ctx)
    e, n = 6_594_010.0, 1_943_010.0
    m.add(Element("footing at survey coords", ifc_class="IfcFooting",
                  geometry={"kind": "prism", "units": "ft",
                            "base": [(e, n), (e + 4, n), (e + 4, n + 4),
                                     (e, n + 4)],
                            "z_bot": 0.0, "z_top": 2.0},
                  quantities={"volume_cf": 32.0}))
    fail = check_local_coordinates(m)
    assert len(fail) == 1
    assert "footing at survey coords" in fail[0]
    assert "ctx.local" in fail[0]          # names the fix


def test_local_coordinate_gate_catches_it_via_element_placement_too():
    """The same mistake made through the placement rather than the vertices."""
    from bimforge.author.gate import check_local_coordinates
    ctx = ProjectContext(name="survey", epsg=2226, guid_ns=uuid.UUID(int=32))
    m = StructureModel("survey", ctx)
    m.add(Element("far footing", ifc_class="IfcFooting",
                  geometry={"kind": "prism", "units": "ft",
                            "base": [(0, 0), (4, 0), (4, 4), (0, 4)],
                            "z_bot": 0.0, "z_top": 2.0},
                  quantities={"volume_cf": 32.0},
                  x_ft=6_594_000.0))
    fail = check_local_coordinates(m)
    assert len(fail) == 1 and "far footing" in fail[0]


def test_local_coordinate_gate_runs_as_a_pre_emit_builtin():
    """Wired into run_pre, not merely importable — otherwise it guards
    nothing."""
    ctx = ProjectContext(name="survey", epsg=2226, guid_ns=uuid.UUID(int=33))
    m = StructureModel("survey", ctx)
    m.add(Element("far footing", ifc_class="IfcFooting",
                  geometry={"kind": "prism", "units": "ft",
                            "base": [(0, 0), (4, 0), (4, 4), (0, 4)],
                            "z_bot": 0.0, "z_top": 2.0},
                  quantities={"volume_cf": 32.0},
                  y_ft=1_943_000.0))
    rep = run_pre(m)
    assert not rep.passed
    assert any("far footing" in f for f in rep.failures), rep.failures


def test_local_coordinate_gate_reads_gusset_placements():
    """PR #157 review: a gusset carries its X positions in `placements`, not
    a `cx` key — reading `cx` silently scored every gusset at the origin and
    let a far-flung one through the gate."""
    from bimforge.author.gate import check_local_coordinates
    ctx = ProjectContext(name="g", epsg=2226, guid_ns=uuid.UUID(int=34))
    m = StructureModel("g", ctx)
    m.add(Element("survey gusset", ifc_class="IfcPlate",
                  geometry={"kind": "gusset", "units": "ft", "cz": 1.0,
                            "thickness": 0.5,
                            "placements": [(6_594_000.0,
                                            [(0.0, 0.0), (1.0, 0.0),
                                             (0.0, 1.0)])]},
                  quantities={"volume_cf": 0.25}))
    fail = check_local_coordinates(m)
    assert len(fail) == 1 and "survey gusset" in fail[0]


def _styled_model():
    import uuid as _uuid
    from bimforge.author.primitives import Prism
    ctx = ProjectContext(name="Styled", epsg=2226, base_e=6_594_000.0,
                         base_n=1_943_000.0, base_h=100.0,
                         guid_ns=_uuid.UUID("11111111-2222-4333-8444-555555555555"))
    m = StructureModel("styled", ctx)
    w = Prism("W1 wall", [(0, 0), (10, 0), (10, 1), (0, 1)], z_bot=0.0, z_top=6.0,
              ifc="IfcWall", layer="S-CONC")
    m.add(Element.from_geometry(w.name, w, ifc_class="IfcWall", layer="S-CONC",
                                quantities={"length_ft": 10.0, "width_ft": 1.0,
                                            "height_ft": 6.0, "volume_cf": 60.0}))
    w2 = Prism("W2 wall", [(0, 3), (10, 3), (10, 4), (0, 4)], z_bot=0.0, z_top=6.0,
               ifc="IfcWall", layer="S-CONC")
    m.add(Element.from_geometry(w2.name, w2, ifc_class="IfcWall", layer="S-CONC",
                                quantities={"length_ft": 10.0, "width_ft": 1.0,
                                            "height_ft": 6.0, "volume_cf": 60.0}))
    m.add(Element("W1 reinforcing", ifc_class="IfcReinforcingBar", layer="S-REBAR",
                  quantities={"weight_lb": 120.0}))
    return m


def test_surface_style_colours_each_geometric_element(tmp_path):
    import ifcopenshell
    p = str(tmp_path / "styled.ifc")
    emit_ifc(_styled_model(), p)
    f = ifcopenshell.open(p)
    assert f.by_type("IfcStyledItem"), "no IfcStyledItem emitted — styling is vacuous"
    colours = {(round(c.Red, 2), round(c.Green, 2), round(c.Blue, 2))
               for c in f.by_type("IfcColourRgb")}
    assert (0.75, 0.73, 0.68) in colours


def test_surface_style_is_shared_across_same_appearance(tmp_path):
    import ifcopenshell
    p = str(tmp_path / "styled.ifc")
    emit_ifc(_styled_model(), p)
    f = ifcopenshell.open(p)
    concrete = [s for s in f.by_type("IfcSurfaceStyleShading")
                if (round(s.SurfaceColour.Red, 2), round(s.SurfaceColour.Green, 2),
                    round(s.SurfaceColour.Blue, 2)) == (0.75, 0.73, 0.68)]
    assert len(concrete) == 1


def test_presentation_layer_per_layer_name(tmp_path):
    import ifcopenshell
    p = str(tmp_path / "styled.ifc")
    emit_ifc(_styled_model(), p)
    f = ifcopenshell.open(p)
    names = {l.Name for l in f.by_type("IfcPresentationLayerAssignment")}
    assert "S-CONC" in names
    conc = next(l for l in f.by_type("IfcPresentationLayerAssignment")
                if l.Name == "S-CONC")
    assert len(conc.AssignedItems) == 2
    assert all(i.is_a("IfcRepresentationItem") for i in conc.AssignedItems)


def test_material_created_once_and_associated(tmp_path):
    import ifcopenshell
    p = str(tmp_path / "styled.ifc")
    emit_ifc(_styled_model(), p)
    f = ifcopenshell.open(p)
    mats = {m.Name for m in f.by_type("IfcMaterial")}
    assert "Concrete" in mats and "Reinforcing Steel" in mats
    assert len([m for m in f.by_type("IfcMaterial") if m.Name == "Concrete"]) == 1
    rel = f.by_type("IfcRelAssociatesMaterial")
    associated = {prod.Name for r in rel for prod in r.RelatedObjects}
    assert "W1 reinforcing" in associated       # weight-only rebar still gets material


def test_element_material_field_overrides_default(tmp_path):
    import ifcopenshell, uuid as _uuid
    from bimforge.author.primitives import Prism
    ctx = ProjectContext(name="M", epsg=2226, base_e=6_594_000.0,
                         base_n=1_943_000.0, base_h=100.0,
                         guid_ns=_uuid.UUID("22222222-3333-4444-8555-666666666666"))
    m = StructureModel("m", ctx)
    w = Prism("W wall", [(0, 0), (10, 0), (10, 1), (0, 1)], z_bot=0.0, z_top=6.0,
              ifc="IfcWall", layer="S-CONC")
    el = Element.from_geometry(w.name, w, ifc_class="IfcWall", layer="S-CONC",
                               quantities={"volume_cf": 60.0})
    el.material = "HES Concrete"
    m.add(el)
    p = str(tmp_path / "m.ifc")
    emit_ifc(m, p)
    f = ifcopenshell.open(p)
    assert "HES Concrete" in {mm.Name for mm in f.by_type("IfcMaterial")}


def test_styling_keeps_byte_determinism(tmp_path):
    p1 = str(tmp_path / "a.ifc")
    p2 = str(tmp_path / "b.ifc")
    emit_ifc(_styled_model(), p1)
    emit_ifc(_styled_model(), p2)
    assert open(p1, "rb").read() == open(p2, "rb").read()


def test_styling_preserves_guid_uniqueness(tmp_path):
    import ifcopenshell
    p = str(tmp_path / "styled.ifc")
    emit_ifc(_styled_model(), p)          # emit_ifc calls _assert_guid_uniqueness internally
    f = ifcopenshell.open(p)
    gids = [e.GlobalId for e in f.by_type("IfcRoot")]
    assert len(gids) == len(set(gids))    # includes the new IfcRelAssociatesMaterial rels


def test_malformed_org_pack_degrades_not_crashes(tmp_path):
    import ifcopenshell
    from bimforge.cad.stylepack import StylePack
    bad = [
        {"ifc": {"surfaces": {"S-CONC": {"rgb": [0.75, 0.73, 0.68], "material": ["Concrete"]}}}},
        {"ifc": {"surfaces": {"S-CONC": {"rgb": [0.75, 0.73, 0.68], "material": 123}}}},
        {"ifc": ["not", "a", "mapping"]},
        {"ifc": {"surfaces": "nope"}},
    ]
    for i, styles in enumerate(bad):
        p = str(tmp_path / f"bad{i}.ifc")
        emit_ifc(_styled_model(), p, stylepack=StylePack(styles=styles))  # must NOT raise
        f = ifcopenshell.open(p)
        assert f.by_type("IfcStyledItem"), f"case {i}: styling vanished instead of degrading"


def test_org_pack_override_flows_through_emit(tmp_path):
    import ifcopenshell
    from bimforge.cad.stylepack import StylePack
    pack = StylePack(styles={"ifc": {"surfaces": {
        "S-CONC": {"rgb": [0.1, 0.2, 0.3], "transparency": 0.0, "material": "OrgConcrete"}}}})
    p = str(tmp_path / "o.ifc")
    emit_ifc(_styled_model(), p, stylepack=pack)
    f = ifcopenshell.open(p)
    colours = {(round(c.Red, 2), round(c.Green, 2), round(c.Blue, 2))
               for c in f.by_type("IfcColourRgb")}
    assert (0.1, 0.2, 0.3) in colours
    assert "OrgConcrete" in {m.Name for m in f.by_type("IfcMaterial")}


def test_rendering_style_carries_reflectance_and_specular(tmp_path):
    """Concrete/steel must emit IfcSurfaceStyleRendering, not flat shading.

    Rendering is a SUBTYPE of IfcSurfaceStyleShading, so the older assertions
    above still hold — this asserts the extra information is actually there.
    """
    import ifcopenshell
    p = str(tmp_path / "styled.ifc")
    emit_ifc(_styled_model(), p)
    f = ifcopenshell.open(p)
    rend = f.by_type("IfcSurfaceStyleRendering")
    assert rend, "no IfcSurfaceStyleRendering — the finish fields are vacuous"
    by_method = {r.ReflectanceMethod for r in rend}
    assert "MATT" in by_method and "METAL" in by_method
    conc = next(r for r in rend if r.ReflectanceMethod == "MATT")
    assert conc.SpecularHighlight is not None
    assert abs(conc.SpecularHighlight.wrappedValue - 0.85) < 1e-9
    assert conc.DiffuseColour is not None


def test_style_names_are_semantic_not_rgb_slugs(tmp_path):
    import ifcopenshell
    p = str(tmp_path / "styled.ifc")
    emit_ifc(_styled_model(), p)
    f = ifcopenshell.open(p)
    names = {s.Name for s in f.by_type("IfcSurfaceStyle")}
    assert "Concrete" in names and "Reinforcing Steel" in names
    assert not any((n or "").startswith("surf-") for n in names), \
        f"RGB-slug style names survived: {names}"


def test_materials_carry_their_own_appearance(tmp_path):
    """IfcMaterialDefinitionRepresentation — viewers that colour by material."""
    import ifcopenshell
    p = str(tmp_path / "styled.ifc")
    emit_ifc(_styled_model(), p)
    f = ifcopenshell.open(p)
    defs = f.by_type("IfcMaterialDefinitionRepresentation")
    assert defs, "materials have no appearance — colour-by-material shows nothing"
    styled = {d.RepresentedMaterial.Name for d in defs}
    assert "Concrete" in styled and "Reinforcing Steel" in styled
    for d in defs:
        for rep in d.Representations:
            assert rep.is_a("IfcStyledRepresentation")
            assert rep.Items and all(i.is_a("IfcStyledItem") for i in rep.Items)


def test_absurd_width_ft_warns_but_still_emits(tmp_path):
    """A thickness passed as width_ft reports a nonsense Length. Warn, don't fail."""
    import warnings
    from bimforge.author.primitives import Prism
    m = _styled_model()
    # a skin whose declared area is the FACE it covers, divided by its own
    # 1/4" thickness -> a Length nobody could build
    m.add(Element("thin skin", ifc_class="IfcCovering", layer="S-CONC",
                  geometry=Prism("skin", [(0.0, 0.0), (30.0, 0.0),
                                          (30.0, 1.0), (0.0, 1.0)], 0.0, 0.02),
                  quantities={"count": 1, "area_sf": 240.0, "width_ft": 0.02,
                              "volume_cf": 5.0}))
    p = str(tmp_path / "warned.ifc")
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        emit_ifc(m, p)
    msgs = [str(x.message) for x in w if "width_ft" in str(x.message)]
    assert any("thin skin" in m for m in msgs), [str(x.message) for x in w]
    # and the honest walls beside it must NOT be flagged
    assert not any("W1 wall" in m or "W2 wall" in m for m in msgs), msgs
    import ifcopenshell
    assert ifcopenshell.open(p).by_type("IfcCovering"), "warning must not abort"


def test_perimeter_ft_is_an_accepted_quantity_and_reaches_the_ifc():
    """base_quantities has always READ perimeter_ft; QUANTITY_KEYS rejected it."""
    from bimforge.author.emit_ifc import base_quantities
    el = Element("slab", ifc_class="IfcSlab",
                 quantities={"count": 1, "area_sf": 100.0, "perimeter_ft": 40.0,
                             "width_ft": 10.0, "volume_cf": 50.0})
    q = {n: v for _, n, v in base_quantities(el, 0.3048)}
    assert abs(q["Perimeter"] - 40.0 * 0.3048) < 1e-9


def test_specular_alone_still_promotes_to_rendering(tmp_path):
    """The two finish fields are documented as independently optional.

    A pack that sets specular but no reflectance must not have it dropped;
    ReflectanceMethod is mandatory on the entity, so NOTDEFINED fills in.
    """
    import ifcopenshell
    m = _styled_model()
    p = str(tmp_path / "spec-only.ifc")
    from bimforge.cad.stylepack import StylePack
    emit_ifc(m, p, stylepack=StylePack(styles={"ifc": {"surfaces": {
        "S-CONC": {"reflectance": None, "specular": 0.4}}}}))
    f = ifcopenshell.open(p)
    rend = [r for r in f.by_type("IfcSurfaceStyleRendering")
            if r.ReflectanceMethod == "NOTDEFINED"]
    assert rend, [r.ReflectanceMethod for r in f.by_type("IfcSurfaceStyleRendering")]
    assert abs(rend[0].SpecularHighlight.wrappedValue - 0.4) < 1e-9


def test_cleared_finish_falls_back_to_flat_shading(tmp_path):
    """Clearing both finish fields must yield plain IfcSurfaceStyleShading."""
    import ifcopenshell
    p = str(tmp_path / "flat.ifc")
    from bimforge.cad.stylepack import StylePack
    emit_ifc(_styled_model(), p, stylepack=StylePack(styles={"ifc": {"surfaces": {
        "S-CONC": {"reflectance": None, "specular": None},
        "S-REBAR": {"reflectance": None, "specular": None}}}}))
    f = ifcopenshell.open(p)
    assert not f.by_type("IfcSurfaceStyleRendering"), \
        "finish survived an explicit null"
    assert f.by_type("IfcSurfaceStyleShading"), "styling vanished entirely"


# ---- issue #188: navigable spatial tree (one IfcBuilding per structure) ----

def _combo_ctx():
    return ProjectContext(name="Combo Project", epsg=2226,
                          base_e=6_594_000.0, base_n=1_943_000.0, base_h=200.0,
                          guid_ns=uuid.UUID("aa1f3c8e-5a2d-4e77-9c31-0b2f4a6d8e10"))


def _combo_structure(ctx, struct_name, x):
    """A one-footing structure sharing the project's ProjectContext."""
    m = StructureModel(struct_name, ctx)
    p = Prism(f"{struct_name} footing", [(-2, -2), (2, -2), (2, 2), (-2, 2)],
              z_bot=0.0, z_top=2.0, ifc="IfcFooting")
    m.add(Element.from_geometry(p.name, p, ifc_class="IfcFooting", x_ft=x))
    pc_apply(m, PC)
    return m


def test_emit_combined_ifc_gives_each_structure_its_own_building(tmp_path):
    """Issue #188 Lever A: a combined project model must spread its structures
    across the spatial tree — one named IfcBuilding per structure under one
    shared IfcSite — so the Bonsai outliner branches per structure instead of
    dumping everything in a single flat storey."""
    import ifcopenshell
    from bimforge.author.emit_ifc import emit_combined_ifc

    ctx = _combo_ctx()
    a = _combo_structure(ctx, "RW1", 0.0)
    b = _combo_structure(ctx, "RW2", 90.0)
    out = tmp_path / "combo.ifc"
    emit_combined_ifc([a, b], str(out), PC)

    f = ifcopenshell.open(str(out))
    sites = f.by_type("IfcSite")
    assert len(sites) == 1, "the combined model shares ONE site"
    buildings = _spatial_children(sites[0])
    assert [x.is_a() for x in buildings] == ["IfcBuilding", "IfcBuilding"]
    assert sorted(x.Name for x in buildings) == ["RW1", "RW2"]

    # each building has exactly one storey, and each structure's element lands
    # under ITS OWN building's storey
    for bld in buildings:
        storeys = _spatial_children(bld)
        assert [s.is_a() for s in storeys] == ["IfcBuildingStorey"]
        contained = [e.Name for rel in storeys[0].ContainsElements
                     for e in rel.RelatedElements]
        assert contained == [f"{bld.Name} footing"]


def test_emit_combined_ifc_namespaces_guids_so_same_named_elements_dont_collide(
        tmp_path):
    """Two structures may hold identically-named elements (the default guid_key
    is ``element/<name>``). A combined file that shares one GUID namespace must
    namespace per structure, or the two products get the SAME GlobalId — an
    invalid IFC that silently drops one element in most importers."""
    import ifcopenshell
    from bimforge.author.emit_ifc import emit_combined_ifc

    ctx = _combo_ctx()

    def one(struct_name, x):
        m = StructureModel(struct_name, ctx)
        p = Prism("footing", [(-2, -2), (2, -2), (2, 2), (-2, 2)],
                  z_bot=0.0, z_top=2.0, ifc="IfcFooting")   # SAME element name
        m.add(Element.from_geometry(p.name, p, ifc_class="IfcFooting", x_ft=x))
        pc_apply(m, PC)
        return m

    out = tmp_path / "collide.ifc"
    emit_combined_ifc([one("RW1", 0.0), one("RW2", 90.0)], str(out), PC)
    f = ifcopenshell.open(str(out))
    footings = f.by_type("IfcFooting")
    assert len(footings) == 2
    assert footings[0].GlobalId != footings[1].GlobalId, \
        "same-named elements in different structures collided on one GlobalId"


def test_gk_namespace_is_injective():
    """The per-structure GUID-key namespace must be injective: distinct
    (scope, key) pairs must never map to the same string, or two elements get
    the same GlobalId. A plain '::' separator is NOT injective."""
    from bimforge.author.emit_ifc import _gk
    # the classic '::'-separator collision
    assert _gk("A::b", "c") != _gk("A", "b::c")
    # empty scope is the identity (single-structure byte-identity)
    assert _gk("", "element/x") == "element/x"
    # a scope whose length prefix could be confused still stays distinct
    assert _gk("1", "0:x") != _gk("10", ":x")


def test_emit_combined_ifc_passes_the_post_emit_spatial_gate(tmp_path):
    """Every structure's storey must be reachable from IfcProject and decompose
    an IfcBuilding — the check that guards issue #132/#189 — for the combined
    file too, not just single-structure emits."""
    from bimforge.author.emit_ifc import emit_combined_ifc
    from bimforge.author.gate import _ifc_spatial_chain_check

    ctx = _combo_ctx()
    models = [_combo_structure(ctx, "RW1", 0.0), _combo_structure(ctx, "RW2", 90.0)]
    out = tmp_path / "gate.ifc"
    emit_combined_ifc(models, str(out), PC)
    assert _ifc_spatial_chain_check(None, str(out)) == []


def test_emit_combined_ifc_is_byte_deterministic(tmp_path):
    from bimforge.author.emit_ifc import emit_combined_ifc

    def build(dest):
        ctx = _combo_ctx()
        emit_combined_ifc(
            [_combo_structure(ctx, "RW1", 0.0), _combo_structure(ctx, "RW2", 90.0)],
            str(dest), PC)
        return dest.read_bytes()

    assert build(tmp_path / "a.ifc") == build(tmp_path / "b.ifc")


def test_emit_ifc_names_the_lone_building_after_the_structure(tmp_path):
    """Issue #188: the single-structure building was the hardcoded placeholder
    "Building"; it now carries the structure's name so the outliner node is
    meaningful."""
    import ifcopenshell
    m = _fixture_model()
    out = tmp_path / "named.ifc"
    emit_ifc(m, str(out), PC)
    f = ifcopenshell.open(str(out))
    buildings = f.by_type("IfcBuilding")
    assert len(buildings) == 1
    assert buildings[0].Name == m.name
    assert buildings[0].Name != "Building"


def test_emit_combined_ifc_rejects_incompatible_or_duplicate_structures(tmp_path):
    from bimforge.author.emit_ifc import emit_combined_ifc

    ctx = _combo_ctx()
    # duplicate structure names -> ambiguous IfcBuildings
    with pytest.raises(ValueError, match="unique"):
        emit_combined_ifc([_combo_structure(ctx, "RW1", 0.0),
                           _combo_structure(ctx, "RW1", 5.0)],
                          str(tmp_path / "dup.ifc"), PC)

    # a structure authored against a different site/GUID-namespace can't share
    # the one IfcSite
    other = ProjectContext(name="Other Project", epsg=2226,
                           base_e=6_594_000.0, base_n=1_943_000.0, base_h=200.0,
                           guid_ns=uuid.UUID(int=999))
    with pytest.raises(GeoreferenceError, match="shares ONE IfcSite"):
        emit_combined_ifc([_combo_structure(ctx, "RW1", 0.0),
                           _combo_structure(other, "RW2", 90.0)],
                          str(tmp_path / "mix.ifc"), PC)


def test_emit_ifc_writes_element_description_onto_the_product(tmp_path):
    """Issue #190: Element.description (estimator notes — assumptions,
    placement-honesty notes, sheet cites) was carried on the model but never
    written to the product's IfcRoot.Description, so it was lost from the IFC.
    An element without a description leaves Description null (not "")."""
    import ifcopenshell
    ctx = ProjectContext(name="Desc", epsg=2226,
                         base_e=6_594_000.0, base_n=1_943_000.0,
                         guid_ns=uuid.UUID(int=190))
    m = StructureModel("desc", ctx)
    m.add(Element("noted footing", ifc_class="IfcFooting", x_ft=0.0,
                  geometry={"kind": "prism", "units": "ft",
                            "base": [(-2, -2), (2, -2), (2, 2), (-2, 2)],
                            "z_bot": 0.0, "z_top": 2.0},
                  description="EPS void 3.5 sf per sheet S-12"))
    m.add(Element("plain footing", ifc_class="IfcFooting", x_ft=20.0,
                  geometry={"kind": "prism", "units": "ft",
                            "base": [(-2, -2), (2, -2), (2, 2), (-2, 2)],
                            "z_bot": 0.0, "z_top": 2.0}))
    out = tmp_path / "desc.ifc"
    emit_ifc(m, str(out))
    f = ifcopenshell.open(str(out))
    by_name = {p.Name: p for p in f.by_type("IfcFooting")}
    assert by_name["noted footing"].Description == "EPS void 3.5 sf per sheet S-12"
    assert by_name["plain footing"].Description is None


def test_emit_ifc_writes_opening_description_onto_the_void(tmp_path):
    """Issue #190 (openings too): an estimator note on an opening Element must
    reach the IfcOpeningElement, not just regular products."""
    import ifcopenshell
    ctx = ProjectContext(name="OpDesc", epsg=2226,
                         base_e=6_594_000.0, base_n=1_943_000.0,
                         guid_ns=uuid.UUID(int=191))
    m = StructureModel("opdesc", ctx)
    m.add(Element("headwall", ifc_class="IfcWall",
                  geometry={"kind": "prism", "units": "ft",
                            "base": [(-4, -1), (4, -1), (4, 1), (-4, 1)],
                            "z_bot": 0.0, "z_top": 6.0},
                  quantities={"volume_cf": 88.0}))
    m.openings.append(("headwall", Element(
        "pipe sleeve",
        geometry={"kind": "prism", "units": "ft",
                  "base": [(-0.5, -1), (0.5, -1), (0.5, 1), (-0.5, 1)],
                  "z_bot": 2.0, "z_top": 4.0},
        description="24in RCP per sheet D-3")))
    out = tmp_path / "opdesc.ifc"
    emit_ifc(m, str(out))
    f = ifcopenshell.open(str(out))
    op = f.by_type("IfcOpeningElement")[0]
    assert op.Description == "24in RCP per sheet D-3"
