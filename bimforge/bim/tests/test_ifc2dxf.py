"""ifc2dxf: IFC -> plan-view takeoff DXF."""
from bimforge.bim.ifc2dxf import layer_name


class _P:
    """Stub product: just enough surface for layer_name."""
    def __init__(self, cls, ptype=None):
        self._cls = cls
        self.PredefinedType = ptype

    def is_a(self):
        return self._cls


def test_layer_name_class_only():
    assert layer_name(_P("IfcWall")) == "IFCWALL"


def test_layer_name_with_predefined_type():
    assert layer_name(_P("IfcSlab", "FLOOR")) == "IFCSLAB-FLOOR"


def test_layer_name_ignores_noise_types():
    assert layer_name(_P("IfcColumn", "NOTDEFINED")) == "IFCCOLUMN"
    assert layer_name(_P("IfcColumn", "USERDEFINED")) == "IFCCOLUMN"
    assert layer_name(_P("IfcColumn", None)) == "IFCCOLUMN"


from bimforge.bim.ifc2dxf import footprint


def test_footprint_unions_triangles_into_square():
    # unit square as two triangles, extruded nowhere (2D pts with z=0)
    pts = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
    faces = [0, 1, 2, 0, 2, 3]
    poly = footprint(pts, faces)
    assert poly is not None
    assert abs(poly.area - 1.0) < 1e-9
    assert poly.geom_type == "Polygon"


def test_footprint_vertical_plane_is_none():
    # a vertical wall face: projects to a zero-area line in plan
    pts = [(0, 0, 0), (1, 0, 0), (1, 0, 3), (0, 0, 3)]
    faces = [0, 1, 2, 0, 2, 3]
    assert footprint(pts, faces) is None


def test_footprint_box_projects_to_footprint_not_double_area():
    # closed 1x1x1 box (12 triangles): plan footprint is the 1x1 square,
    # even though top+bottom faces both project onto it
    v = [(x, y, z) for z in (0, 1) for y in (0, 1) for x in (0, 1)]
    # bottom z=0: v0..v3 (x,y): (0,0),(1,0),(0,1),(1,1); top z=1: v4..v7
    faces = [
        0, 1, 3, 0, 3, 2,      # bottom
        4, 5, 7, 4, 7, 6,      # top
        0, 1, 5, 0, 5, 4,      # y=0 side
        2, 3, 7, 2, 7, 6,      # y=1 side
        0, 2, 6, 0, 6, 4,      # x=0 side
        1, 3, 7, 1, 7, 5,      # x=1 side
    ]
    poly = footprint(v, faces)
    assert abs(poly.area - 1.0) < 1e-9


from ezdxf import units as dxf_units

from bimforge.bim.ifc2dxf import _crs_unit


def test_crs_unit_us_foot():
    # EPSG:2226 = NAD83 / California zone 2 (ftUS)
    assert _crs_unit(2226) == ("ft", dxf_units.FT)


def test_crs_unit_metre():
    # EPSG:32610 = WGS84 / UTM 10N (metre)
    assert _crs_unit(32610) == ("m", dxf_units.M)


def test_crs_unit_geographic_crs_is_error():
    # EPSG:4326 = WGS84 lon/lat (degrees) — not a projected CRS; labeling
    # degrees as metres would be silently wrong (pytest is module-imported
    # below, bound before any test runs)
    with pytest.raises(ValueError, match="projected CRS"):
        _crs_unit(4326)


import ezdxf
import ifcopenshell
import ifcopenshell.api.aggregate as aggregate_api
import ifcopenshell.api.context as context_api
import ifcopenshell.api.geometry as geometry_api
import ifcopenshell.api.profile as profile_api
import ifcopenshell.api.root as root
import ifcopenshell.api.spatial as spatial_api
import ifcopenshell.api.unit as unit_api
import pytest

from bimforge.bim.ifc2dxf import M_TO_FT, ifc_to_dxf


def _foreign_ifc(path):
    """Revit-ish IFC: mm units, no georef, no classification.

    One 10 m x 5 m x 0.3 m slab (FLOOR) with a 2 m x 1 m hole, one
    0.6 m square, 3 m tall column. All authored coordinates in mm.
    """
    f = ifcopenshell.file(schema="IFC4")
    root.create_entity(f, ifc_class="IfcProject", name="Foreign")
    unit_api.assign_unit(f)  # ifcopenshell default: millimetres
    ctx = context_api.add_context(f, context_type="Model")
    body = context_api.add_context(
        f, context_type="Model", context_identifier="Body",
        target_view="MODEL_VIEW", parent=ctx)
    site = root.create_entity(f, ifc_class="IfcSite", name="Site")

    def add(ifc_class, ring, depth, predefined_type=None, voids=None):
        el = root.create_entity(f, ifc_class=ifc_class,
                                predefined_type=predefined_type)
        if voids:
            profile = profile_api.add_arbitrary_profile_with_voids(
                f, outer_profile=ring, inner_profiles=voids)
        else:
            profile = profile_api.add_arbitrary_profile(f, profile=ring)
        rep = geometry_api.add_profile_representation(
            f, context=body, profile=profile, depth=depth)
        geometry_api.assign_representation(f, product=el, representation=rep)
        spatial_api.assign_container(f, products=[el], relating_structure=site)
        return el

    add("IfcSlab",
        [(0.0, 0.0), (10000.0, 0.0), (10000.0, 5000.0), (0.0, 5000.0),
         (0.0, 0.0)],
        300.0, predefined_type="FLOOR",
        voids=[[(4000.0, 2000.0), (6000.0, 2000.0), (6000.0, 3000.0),
                (4000.0, 3000.0), (4000.0, 2000.0)]])
    add("IfcColumn",
        [(0.0, 0.0), (600.0, 0.0), (600.0, 600.0), (0.0, 600.0), (0.0, 0.0)],
        3000.0)
    f.write(str(path))
    return path


@pytest.fixture()
def foreign_ifc(tmp_path):
    return _foreign_ifc(tmp_path / "foreign.ifc")


def test_foreign_ifc_flattens_to_local_feet(foreign_ifc, tmp_path):
    out = tmp_path / "foreign.plan.dxf"
    res = ifc_to_dxf(foreign_ifc, out)
    assert res.georef == {"status": "ungeoreferenced", "unit": "ft"}
    assert res.elements == 2
    assert res.skipped == []

    doc = ezdxf.readfile(str(out))
    assert doc.header["$INSUNITS"] == ezdxf.units.FT
    assert doc.header["$MEASUREMENT"] == 0
    layers = {e.dxf.layer for e in doc.modelspace()}
    assert layers == {"IFCSLAB-FLOOR", "IFCCOLUMN"}

    slab_polys = [e for e in doc.modelspace().query("LWPOLYLINE")
                  if e.dxf.layer == "IFCSLAB-FLOOR"]
    assert len(slab_polys) == 2            # exterior + hole ring
    assert all(p.closed for p in slab_polys)
    # outer ring bbox: 10 m x 5 m in feet
    outer = max(slab_polys, key=lambda p: len(p))
    xs = [pt[0] for pt in outer.get_points()]
    ys = [pt[1] for pt in outer.get_points()]
    assert abs((max(xs) - min(xs)) - 10.0 * M_TO_FT) < 0.01
    assert abs((max(ys) - min(ys)) - 5.0 * M_TO_FT) < 0.01


def test_foreign_ifc_sidecar_rows(foreign_ifc, tmp_path):
    res = ifc_to_dxf(foreign_ifc, tmp_path / "f.dxf")
    slab = next(e for e in res.entities if e["layer"] == "IFCSLAB-FLOOR")
    assert slab["ifc_class"] == "IfcSlab"
    assert slab["predefined_type"] == "FLOOR"
    assert slab["rings"] == 2
    # 50 m2 minus the 2 m2 hole, in ft2
    assert abs(slab["area"] - 48.0 * M_TO_FT ** 2) < 1.0
    # 300 mm thick slab -> ~0.98 ft z-range
    assert abs((slab["z_max"] - slab["z_min"]) - 0.3 * M_TO_FT) < 0.01
    assert slab["global_id"] and slab["vertices"] >= 8


def _add_map_conversion(path, *, scale, epsg=32610,
                        eastings=500000.0, northings=4000000.0, height=0.0):
    """Georeference an existing IFC in place: IfcMapConversion whose Scale
    applies to the file's NATIVE length unit (IFC4 semantics)."""
    f = ifcopenshell.open(str(path))
    ctx = f.by_type("IfcGeometricRepresentationContext")[0]
    crs = f.create_entity("IfcProjectedCRS", Name=f"EPSG:{epsg}")
    f.create_entity("IfcMapConversion", SourceCRS=ctx, TargetCRS=crs,
                    Eastings=eastings, Northings=northings,
                    OrthogonalHeight=height, Scale=scale)
    f.write(str(path))
    return path


def test_invalid_georef_is_loud_not_silent_local_feet(foreign_ifc, tmp_path):
    # a PRESENT but broken georeference (Scale=0) must raise, never silently
    # fall back to an ungeoreferenced local-feet file
    _add_map_conversion(foreign_ifc, scale=0.0)
    with pytest.raises(ValueError, match="Scale is 0.0"):
        ifc_to_dxf(foreign_ifc, tmp_path / "bad.dxf")


def test_georeferenced_mm_ifc_lands_in_crs_metres(foreign_ifc, tmp_path):
    # mm-native file into a metre CRS: IFC4 MapConversion Scale applies to
    # NATIVE (mm) coordinates, so Scale=0.001 takes mm -> CRS metres. The
    # 10 m x 5 m slab must land as a 10 x 5 CRS-metre box at the base point.
    _add_map_conversion(foreign_ifc, scale=0.001, epsg=32610)
    out = tmp_path / "geo.plan.dxf"
    res = ifc_to_dxf(foreign_ifc, out)
    assert res.georef == {"status": "crs", "epsg": 32610, "unit": "m"}

    doc = ezdxf.readfile(str(out))
    assert doc.header["$INSUNITS"] == ezdxf.units.M
    # $MEASUREMENT follows the output unit: metric CRS -> metric (1), so CAD
    # consumers pick metric linetype/hatch defaults (PR #104 review)
    assert doc.header["$MEASUREMENT"] == 1
    slab_polys = [e for e in doc.modelspace().query("LWPOLYLINE")
                  if e.dxf.layer == "IFCSLAB-FLOOR"]
    outer = max(slab_polys, key=lambda p: len(p))
    xs = [pt[0] for pt in outer.get_points()]
    ys = [pt[1] for pt in outer.get_points()]
    assert abs((max(xs) - min(xs)) - 10.0) < 0.01
    assert abs((max(ys) - min(ys)) - 5.0) < 0.01
    assert abs(min(xs) - 500000.0) < 0.01
    assert abs(min(ys) - 4000000.0) < 0.01
    # z too: OrthogonalHeight + native_z * Scale -> 0.3 CRS-metre thickness
    slab = next(e for e in res.entities if e["layer"] == "IFCSLAB-FLOOR")
    assert abs((slab["z_max"] - slab["z_min"]) - 0.3) < 0.01
    assert abs(slab["z_min"] - 0.0) < 0.01


from importlib.resources import files as _res_files

import ifcopenshell.util.element as ifc_el
import yaml

from bimforge.bim.dxf2bim import UNIT_TO_M, build_ifc, extract_features
from bimforge.bim.sample import write_sample_dxf


@pytest.fixture()
def pipeline_ifc(tmp_path):
    """A georeferenced IFC from our own sample pipeline (ft CRS)."""
    dxf = write_sample_dxf(str(tmp_path / "sample.dxf"))
    cfg = yaml.safe_load(
        (_res_files("bimforge.bim") / "examples" /
         "layer_map.example.yaml").read_text(encoding="utf-8"))
    # dxf2bim's georeferencing contract (test_georef.py) is
    # Scale = 1 / unit_to_m(dxf_length_unit): the DXF drawing unit IS the
    # CRS's own linear unit, by design. The shipped example pairs
    # dxf_length_unit: mm with a *metric* CRS (EPSG:6423) -- already an
    # inconsistent pairing under that contract (mm has no real EPSG unit),
    # and not the ft CRS this test wants. Override both here (fixture-local,
    # not the shipped example) to a self-consistent ft CRS pairing; leave
    # base_easting/base_northing unset so build_ifc's bbox-min fallback
    # derives a base point matching write_sample_dxf's own (large,
    # mm-scale-looking) coordinate origin -- an explicit fixed base far from
    # that origin would trip the legacy-georef coordinate guard.
    cfg["units"] = {"dxf_length_unit": "ft"}
    cfg["georeference"] = {"crs_epsg": 2226, "base_easting": None,
                           "base_northing": None, "base_height": 0.0}
    scale = UNIT_TO_M["ft"]
    feats = extract_features(dxf, cfg.get("layers", {}), scale)
    out = tmp_path / "sample.ifc"
    build_ifc(feats, cfg, str(out))
    return out


def test_georeferenced_ifc_lands_in_crs_feet(pipeline_ifc, tmp_path):
    out = tmp_path / "sample.plan.dxf"
    res = ifc_to_dxf(pipeline_ifc, out)
    assert res.georef["status"] == "crs"
    assert res.georef["unit"] == "ft"
    assert res.elements > 0

    doc = ezdxf.readfile(str(out))
    assert doc.header["$INSUNITS"] == ezdxf.units.FT
    # every vertex carries the georef base offset (large magnitude from the
    # sample DXF's survey-ish origin), not raw local-origin coordinates
    for e in doc.modelspace().query("LWPOLYLINE"):
        for x, y, *_ in e.get_points():
            assert abs(x) > 1e5 and abs(y) > 1e5


def test_footprint_area_matches_authored_qto(pipeline_ifc, tmp_path):
    res = ifc_to_dxf(pipeline_ifc, tmp_path / "s.dxf")
    model = ifcopenshell.open(str(pipeline_ifc))
    by_gid = {e.GlobalId: e for e in model.by_type("IfcElement")}
    checked = 0
    for row in res.entities:
        if row["ifc_class"] != "IfcSlab":
            continue
        qtos = ifc_el.get_psets(by_gid[row["global_id"]], qtos_only=True)
        gross_m2 = next((q["GrossArea"] for q in qtos.values()
                         if "GrossArea" in q), None)
        if gross_m2 is None:
            continue
        # measured agreement on this fixture is ~1e-11; the 2% bound is
        # deliberate headroom for curved/tessellated foreign geometry
        assert abs(row["area"] - gross_m2 * M_TO_FT ** 2) / row["area"] < 0.02
        checked += 1
    assert checked > 0


def test_include_filter_keeps_subtypes_only(foreign_ifc, tmp_path):
    res = ifc_to_dxf(foreign_ifc, tmp_path / "a.dxf", include=["IfcSlab"])
    assert res.elements == 1
    assert res.entities[0]["ifc_class"] == "IfcSlab"
    # is_a semantics: a supertype matches its subtypes -- IfcSlab and
    # IfcColumn are both IfcBuildingElement in IFC4, so both survive
    res = ifc_to_dxf(foreign_ifc, tmp_path / "a2.dxf",
                     include=["IfcBuildingElement"])
    assert {e["ifc_class"] for e in res.entities} == {"IfcSlab", "IfcColumn"}


def test_exclude_wins_over_include(foreign_ifc, tmp_path):
    res = ifc_to_dxf(foreign_ifc, tmp_path / "b.dxf",
                     include=["IfcSlab", "IfcColumn"], exclude=["IfcColumn"])
    assert {e["ifc_class"] for e in res.entities} == {"IfcSlab"}


def test_no_matching_elements_raises(foreign_ifc, tmp_path):
    with pytest.raises(ValueError, match="no element produced"):
        ifc_to_dxf(foreign_ifc, tmp_path / "c.dxf", include=["IfcBeam"])


def _collinear_slab_ifc(path):
    """One mm-unit slab whose profile carries an explicit collinear midpoint
    at (5000, 0) on the bottom edge. The redundant vertex survives
    tessellation and the footprint union (5 ring vertices), making it a real
    decimation target for simplify -- unlike _foreign_ifc's plain rectangles,
    whose rings come out already minimal (simplify is a no-op there)."""
    f = ifcopenshell.file(schema="IFC4")
    root.create_entity(f, ifc_class="IfcProject", name="Collinear")
    unit_api.assign_unit(f)  # ifcopenshell default: millimetres
    ctx = context_api.add_context(f, context_type="Model")
    body = context_api.add_context(
        f, context_type="Model", context_identifier="Body",
        target_view="MODEL_VIEW", parent=ctx)
    site = root.create_entity(f, ifc_class="IfcSite", name="Site")
    el = root.create_entity(f, ifc_class="IfcSlab", predefined_type="FLOOR")
    profile = profile_api.add_arbitrary_profile(
        f, profile=[(0.0, 0.0), (5000.0, 0.0), (10000.0, 0.0),
                    (10000.0, 5000.0), (0.0, 5000.0), (0.0, 0.0)])
    rep = geometry_api.add_profile_representation(
        f, context=body, profile=profile, depth=300.0)
    geometry_api.assign_representation(f, product=el, representation=rep)
    spatial_api.assign_container(f, products=[el], relating_structure=site)
    f.write(str(path))
    return path


def test_simplify_decimates_collinear_vertices(tmp_path):
    ifc = _collinear_slab_ifc(tmp_path / "collinear.ifc")
    plain = ifc_to_dxf(ifc, tmp_path / "d.dxf")
    simplified = ifc_to_dxf(ifc, tmp_path / "e.dxf", simplify_ft=0.05)
    # without simplify, the authored collinear midpoint survives...
    assert plain.entities[0]["vertices"] == 5
    # ...and simplify_ft removes exactly it, leaving the minimal rectangle
    assert simplified.entities[0]["vertices"] == 4


from bimforge.bim.ifc2dxf import _chains_from_edges


def test_chains_from_edges_merges_sequential_and_splits_disjoint():
    # a flat [a,b,a,b,...] edge list -> ordered vertex-index chains
    assert _chains_from_edges([0, 1, 1, 2]) == [[0, 1, 2]]       # one centreline
    assert _chains_from_edges([0, 1, 2, 3]) == [[0, 1], [2, 3]]  # two ticks
    assert _chains_from_edges([1, 2, 0, 1]) == [[0, 1, 2]]       # reversed adjacency
    # a bridging edge that arrives out of order still joins the two chains
    assert _chains_from_edges([0, 1, 2, 3, 1, 2]) == [[0, 1, 2, 3]]
    assert _chains_from_edges([]) == []


def _annotation_ifc(path):
    """A slab (IfcElement) plus an IfcAnnotation centreline polyline -- the
    survey/layout content (alignments, stationing) ifc2dxf used to drop."""
    f = ifcopenshell.file(schema="IFC4")
    root.create_entity(f, ifc_class="IfcProject", name="Anno")
    unit_api.assign_unit(f)  # ifcopenshell default: millimetres
    ctx = context_api.add_context(f, context_type="Model")
    body = context_api.add_context(
        f, context_type="Model", context_identifier="Body",
        target_view="MODEL_VIEW", parent=ctx)
    site = root.create_entity(f, ifc_class="IfcSite", name="Site")
    slab = root.create_entity(f, ifc_class="IfcSlab", predefined_type="FLOOR")
    profile = profile_api.add_arbitrary_profile(
        f, profile=[(0.0, 0.0), (10000.0, 0.0), (10000.0, 5000.0),
                    (0.0, 5000.0), (0.0, 0.0)])
    rep = geometry_api.add_profile_representation(
        f, context=body, profile=profile, depth=300.0)
    geometry_api.assign_representation(f, product=slab, representation=rep)
    spatial_api.assign_container(f, products=[slab], relating_structure=site)
    # an alignment centreline: a 3-point (2-segment) polyline annotation
    ann = root.create_entity(f, ifc_class="IfcAnnotation", name="CL")
    cpts = [f.create_entity("IfcCartesianPoint", Coordinates=p) for p in
            [(0.0, 0.0, 0.0), (10000.0, 0.0, 0.0), (10000.0, 5000.0, 0.0)]]
    poly = f.create_entity("IfcPolyline", Points=cpts)
    arep = f.create_entity(
        "IfcShapeRepresentation", ContextOfItems=body,
        RepresentationIdentifier="Annotation", RepresentationType="Curve3D",
        Items=[poly])
    ann.Representation = f.create_entity(
        "IfcProductDefinitionShape", Representations=[arep])
    spatial_api.assign_container(f, products=[ann], relating_structure=site)
    f.write(str(path))
    return path


def test_annotation_products_are_emitted_not_silently_dropped(tmp_path):
    # #175: IfcAnnotation is an IfcProduct but not an IfcElement, so walking
    # IfcElement alone dropped every annotation AND never counted it (skipped
    # is only appended inside the loop) -- the summary read "1 element, 0
    # skipped" while losing the centreline. Both halves must be fixed.
    ifc = _annotation_ifc(tmp_path / "anno.ifc")
    res = ifc_to_dxf(ifc, tmp_path / "anno.dxf")
    assert res.elements == 2            # slab + annotation, not just the slab
    assert res.skipped == []            # nothing silently dropped or miscounted
    anno = [e for e in res.entities if e["ifc_class"] == "IfcAnnotation"]
    assert len(anno) == 1
    assert anno[0]["layer"] == "IFCANNOTATION"
    assert anno[0]["vertices"] == 3     # the 3-point centreline survives

    doc = ezdxf.readfile(str(res.out))
    plines = [e for e in doc.modelspace().query("LWPOLYLINE")
              if e.dxf.layer == "IFCANNOTATION"]
    assert plines and not any(p.closed for p in plines)   # curves are OPEN
    assert sum(len(list(p.get_points())) for p in plines) == 3


def test_annotation_does_not_perturb_the_solid_footprint(tmp_path):
    # curve-inclusive geom settings must not change how solids tessellate: the
    # slab in the annotation fixture keeps its full 10x5 m (in ft) footprint.
    ifc = _annotation_ifc(tmp_path / "anno.ifc")
    res = ifc_to_dxf(ifc, tmp_path / "anno.dxf")
    slab = next(e for e in res.entities if e["ifc_class"] == "IfcSlab")
    assert abs(slab["area"] - 50.0 * M_TO_FT ** 2) < 1.0


import json as _json

from bimforge.bim.ifc2dxf import write_sidecar


def test_write_sidecar_payload(foreign_ifc, tmp_path):
    res = ifc_to_dxf(foreign_ifc, tmp_path / "f.dxf")
    side = tmp_path / "f.dxf.sidecar.json"
    write_sidecar(res, foreign_ifc, side)
    payload = _json.loads(side.read_text(encoding="utf-8"))
    assert payload["georef"] == {"status": "ungeoreferenced", "unit": "ft"}
    assert payload["ifc"].endswith("foreign.ifc")
    assert payload["out"].endswith("f.dxf")
    assert payload["elements"] == 2
    assert payload["skipped"] == []
    assert {e["layer"] for e in payload["entities"]} == \
        {"IFCSLAB-FLOOR", "IFCCOLUMN"}
    assert payload["params"] == {"include": None, "exclude": None,
                                 "simplify_ft": 0.0}
