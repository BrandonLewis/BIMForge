"""Swept-disk directrix tessellation + Bar.body_solids (#191)."""
from __future__ import annotations

import math

from bimforge.author.primitives import (
    Bar, arc_points_3d, densify_directrix, fillet_polyline, swept_disk_mesh,
)


def _tri_volume(verts, tris):
    """|signed volume| of a closed triangle mesh (divergence / tetra sum)."""
    v = 0.0
    for i, j, k in tris:
        a, b, c = verts[i], verts[j], verts[k]
        v += (a[0] * (b[1] * c[2] - b[2] * c[1])
              - a[1] * (b[0] * c[2] - b[2] * c[0])
              + a[2] * (b[0] * c[1] - b[1] * c[0]))
    return abs(v) / 6.0


def test_arc_points_on_a_known_quarter_circle():
    a, m, b = (1.0, 0.0, 0.0), (math.cos(math.pi / 4), math.sin(math.pi / 4), 0.0), (0.0, 1.0, 0.0)
    pts = arc_points_3d(a, m, b, 4)
    assert len(pts) == 4
    # every sample is on the unit circle about the origin
    for p in pts:
        assert math.isclose(math.hypot(p[0], p[1]), 1.0, abs_tol=1e-9)
        assert abs(p[2]) < 1e-9
    # last sample lands on b
    assert all(math.isclose(pts[-1][i], b[i], abs_tol=1e-9) for i in range(3))


def test_densify_expands_arcs_keeps_lines():
    # an L-bar: two legs meeting at a filleted right angle
    verts, segs, _ = fillet_polyline([(0, 0, 0), (0, 0, 1.0), (1.0, 0, 1.0)], 0.1)
    chain = densify_directrix(verts, segs, arc_segments=6)
    # starts at the first vertex, ends at the last
    assert chain[0] == (0.0, 0.0, 0.0)
    assert all(math.isclose(chain[-1][i], (1.0, 0.0, 1.0)[i], abs_tol=1e-9)
               for i in range(3))
    # more points than the raw fillet vertices (the arc was tessellated)
    assert len(chain) > len(verts)


def test_swept_disk_mesh_straight_volume():
    r, L = 0.05, 10.0
    verts, segs, _ = fillet_polyline([(0, 0, 0), (L, 0, 0)], 0.1)
    mv, tris = swept_disk_mesh(verts, segs, r, sides=48)
    # closed tube volume ~= pi r^2 L (n-gon slightly under a true circle)
    assert math.isclose(_tri_volume(mv, tris), math.pi * r * r * L, rel_tol=0.01)


def test_swept_disk_mesh_bent_volume_tracks_centreline():
    r = 0.05
    verts, segs, length = fillet_polyline(
        [(0, 0, 0), (0, 0, 1.0), (1.0, 0, 1.0)], 0.1)
    mv, tris = swept_disk_mesh(verts, segs, r, sides=48, arc_segments=16)
    # volume tracks pi r^2 * the EXACT filleted centreline length
    assert math.isclose(_tri_volume(mv, tris), math.pi * r * r * length,
                        rel_tol=0.02)


def test_bar_body_solids_is_a_swept_disk():
    b = Bar(mark="T1", host="deck", size=5, pts=[(0, 0, 0), (0, 0, 1.0),
            (1.0, 0, 1.0)], bend_r=0.15, shape="L")
    (d,) = b.body_solids()
    assert d["kind"] == "swept_disk"
    assert d["units"] == "ft"
    assert math.isclose(d["radius"], b.dia / 2.0)
    # directrix carries the fillet arc as an ("arc", i, j, k) segment
    assert any(s[0] == "arc" for s in d["segments"])
    assert d["verts"][0] == (0.0, 0.0, 0.0)


# --------------------------------------------------------------------------
# gate: the directrix must feed the local-coordinate check (pure, no IFC)
# --------------------------------------------------------------------------

def test_swept_disk_feeds_the_local_coordinate_gate():
    from bimforge.author.gate import _solid_points
    (d,) = Bar(mark="T1", host="d", size=5, pts=[(0, 0, 0), (0, 0, 1.0),
               (1.0, 0, 1.0)], bend_r=0.15, shape="L").body_solids()
    pts = list(_solid_points(d))
    assert pts and all(len(p) == 3 for p in pts)     # directrix verts, (x,y,z)
    assert (0.0, 0.0, 0.0) in [tuple(p) for p in pts]


# --------------------------------------------------------------------------
# emitter integration (needs the optional ifcopenshell/build123d/ezdxf deps)
# --------------------------------------------------------------------------

import uuid  # noqa: E402

import pytest  # noqa: E402


def _bar_model():
    from bimforge.author.model import Element, StructureModel
    from bimforge.author.project import ProjectContext
    ctx = ProjectContext(name="Rebar Fixture", epsg=2226, base_e=6_594_000.0,
                         base_n=1_943_000.0, base_h=200.0,
                         guid_ns=uuid.UUID(int=191))
    m = StructureModel("rebar", ctx)
    bar = Bar(mark="T1", host="deck", size=5,
              pts=[(0, 0, 0), (0, 0, 1.0), (1.0, 0, 1.0)],
              bend_r=0.15, shape="L")
    m.add(Element("T1 bent bar", ifc_class="IfcReinforcingBar", geometry=bar))
    return m


def test_emit_ifc_bent_bar_is_one_swept_disk_not_a_mesh(tmp_path):
    ifcopenshell = pytest.importorskip("ifcopenshell")
    from bimforge.author.emit_ifc import emit_ifc
    out = tmp_path / "rebar.ifc"
    emit_ifc(_bar_model(), str(out))
    f = ifcopenshell.open(str(out))
    assert len(f.by_type("IfcSweptDiskSolid")) == 1
    assert len(f.by_type("IfcFacetedBrep")) == 0        # no mesh fallback
    curve = f.by_type("IfcSweptDiskSolid")[0].Directrix
    assert curve.is_a("IfcIndexedPolyCurve")
    assert any(s.is_a("IfcArcIndex") for s in curve.Segments)  # exact bend
    rep = [r for r in f.by_type("IfcShapeRepresentation")
           if r.RepresentationIdentifier == "Body"][0]
    assert rep.RepresentationType == "AdvancedSweptSolid"
    # the whole point: a bent bar costs a handful of entities, not thousands
    assert len(list(f)) < 60


def test_emit_ifc_bent_bar_is_byte_deterministic(tmp_path):
    pytest.importorskip("ifcopenshell")
    from bimforge.author.emit_ifc import emit_ifc
    a, b = tmp_path / "a.ifc", tmp_path / "b.ifc"
    emit_ifc(_bar_model(), str(a))
    emit_ifc(_bar_model(), str(b))
    assert a.read_bytes() == b.read_bytes()          # byte-for-byte identical


def test_emit_dxf_bent_bar_draws_directrix(tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    from bimforge.author.emit_dxf import emit_dxf
    out = tmp_path / "rebar.dxf"
    emit_dxf(_bar_model(), str(out))
    doc = ezdxf.readfile(str(out))
    assert len(doc.modelspace().query("LWPOLYLINE")) >= 1


def test_emit_step_bent_bar_builds_a_solid(tmp_path):
    pytest.importorskip("build123d")
    from bimforge.author.emit_step import emit_step
    out = tmp_path / "rebar.step"
    emit_step(_bar_model(), str(out))
    assert out.is_file() and out.stat().st_size > 0
