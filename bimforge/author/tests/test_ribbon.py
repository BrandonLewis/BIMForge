"""Draped ribbon-mesh emitter (#192)."""
from __future__ import annotations

import math
import uuid

import pytest

from bimforge.author.ribbon import Ribbon, ribbon_mesh


def test_ribbon_mesh_two_triangles_per_segment():
    pts = [(0, 0, 0), (10, 0, 0), (10, 10, 5)]     # 2 segments
    verts, tris = ribbon_mesh(pts, 2.0)
    assert len(tris) == 4                          # 2 per segment
    assert len(verts) == 8                         # 4 per segment


def test_ribbon_mesh_offsets_perpendicular_in_plan_and_drapes_z():
    verts, _ = ribbon_mesh([(0, 0, 3.0), (10, 0, 7.0)], 2.0)
    # a segment along +x, width 2 -> edges at y = +/-1, z carried per end
    ys = sorted({round(v[1], 6) for v in verts})
    assert ys == [-1.0, 1.0]
    # the two start verts keep z=3, the two end verts keep z=7 (draped)
    assert {round(v[2], 6) for v in verts if v[0] == 0} == {3.0}
    assert {round(v[2], 6) for v in verts if v[0] == 10} == {7.0}


def test_ribbon_mesh_skips_zero_length_segments():
    verts, tris = ribbon_mesh([(0, 0, 0), (0, 0, 0), (5, 0, 0)], 1.0)
    assert len(tris) == 2                          # only the real segment


def test_ribbon_area_is_width_times_plan_length():
    r = Ribbon([(0, 0, 0), (0, 30, 4.0)], width=3.0)   # plan length 30
    assert math.isclose(r.plan_length_ft, 30.0)
    assert math.isclose(r.area_sf, 90.0)


def test_ribbon_body_solids_shape():
    (d,) = Ribbon([(0, 0, 0), (10, 0, 0)], 2.0).body_solids()
    assert d["kind"] == "ribbon" and d["units"] == "ft"
    assert d["width"] == 2.0 and len(d["points"]) == 2


def test_ribbon_along_alignment_uses_offset_and_z():
    # a straight east-running alignment; a Rt offset ribbon at constant z
    from bimforge.author.alignment import Alignment
    al = Alignment({"northing": 0.0, "easting": 0.0, "station": 0.0},
                   [{"kind": "tangent", "bearing": "N 45-00-00 E",
                     "length": 100.0}], name="A")
    r = Ribbon.along_alignment(al, 0.0, 100.0, width=4.0, offset=10.0,
                               side="Rt", z_of=lambda s: 12.0, step=50.0)
    assert r.width == 4.0
    assert all(math.isclose(p[2], 12.0) for p in r.points)   # z from z_of
    assert len(r.points) >= 3                                 # sampled by step
    # the 10 ft Rt offset actually applied: at station 0 (origin, az 45), a
    # right offset points along az 135 -> survey (n,e)=(-7.07,+7.07); origin
    # None maps to model (x,y)=(e,n). Pins the offset + axis-swap behavior.
    assert math.isclose(r.points[0][0], 7.071, abs_tol=0.01)   # model x = e
    assert math.isclose(r.points[0][1], -7.071, abs_tol=0.01)  # model y = n


# --------------------------------------------------------------------------
# gate: the centreline must feed the local-coordinate check (pure, no IFC)
# --------------------------------------------------------------------------

def test_ribbon_feeds_the_local_coordinate_gate():
    from bimforge.author.gate import _solid_points
    (d,) = Ribbon([(0, 0, 0), (20, 0, 1.0)], 2.0).body_solids()
    pts = [tuple(p) for p in _solid_points(d)]
    assert (0.0, 0.0, 0.0) in pts and (20.0, 0.0, 1.0) in pts


# --------------------------------------------------------------------------
# emitter integration (needs the optional ifcopenshell/ezdxf/build123d deps)
# --------------------------------------------------------------------------

def _ribbon_model():
    from bimforge.author.model import Element, StructureModel
    from bimforge.author.project import ProjectContext
    ctx = ProjectContext(name="Ribbon Fixture", epsg=2226, base_e=6_594_000.0,
                         base_n=1_943_000.0, base_h=200.0,
                         guid_ns=uuid.UUID(int=192))
    m = StructureModel("ribbon", ctx)
    rib = Ribbon([(0, 0, 0), (20, 0, 1.0), (40, 10, 2.0)], width=2.0)
    m.add(Element("EOP ribbon", ifc_class="IfcGeographicElement", geometry=rib))
    return m


def test_emit_ifc_ribbon_is_open_tessellation(tmp_path):
    pytest.importorskip("ifcopenshell")
    import ifcopenshell
    from bimforge.author.emit_ifc import emit_ifc
    out = tmp_path / "ribbon.ifc"
    emit_ifc(_ribbon_model(), str(out))
    f = ifcopenshell.open(str(out))
    fs = f.by_type("IfcTriangulatedFaceSet")
    assert len(fs) == 1
    assert fs[0].Closed is False                   # open surface, not a solid
    assert len(fs[0].CoordIndex) == 4              # 2 segments x 2 tris
    rep = [r for r in f.by_type("IfcShapeRepresentation")
           if r.RepresentationIdentifier == "Body"][0]
    assert rep.RepresentationType == "Tessellation"


def test_emit_ifc_ribbon_is_byte_deterministic(tmp_path):
    pytest.importorskip("ifcopenshell")
    from bimforge.author.emit_ifc import emit_ifc
    a, b = tmp_path / "a.ifc", tmp_path / "b.ifc"
    emit_ifc(_ribbon_model(), str(a))
    emit_ifc(_ribbon_model(), str(b))
    assert a.read_bytes() == b.read_bytes()          # byte-for-byte identical


def test_emit_dxf_ribbon_draws_a_polyline(tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    from bimforge.author.emit_dxf import emit_dxf
    out = tmp_path / "ribbon.dxf"
    emit_dxf(_ribbon_model(), str(out))
    doc = ezdxf.readfile(str(out))
    assert len(doc.modelspace().query("LWPOLYLINE")) >= 1


def test_emit_step_ribbon_yields_no_solid():
    # a zero-thickness layout surface is not a STEP solid: the ribbon branch
    # yields no build123d part (it lands only in the IFC / DXF).
    b3d = pytest.importorskip("build123d")
    from bimforge.author.emit_step import _solid_from_dict
    parts = _solid_from_dict(b3d, {"kind": "ribbon", "units": "ft",
                                   "points": [(0, 0, 0), (10, 0, 0)],
                                   "width": 2.0})
    assert parts == []
