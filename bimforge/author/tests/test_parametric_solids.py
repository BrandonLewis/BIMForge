"""Exact IFC solids and honest RepresentationTypes (#329, #330).

#329: every IfcFacetedBrep used to ship labelled "SweptSolid", invisible to
ifcopenshell.validate. #330: SectionPrism is literally one
IfcExtrudedAreaSolid and now emits one — the placement checks below compare
the IFC solid against the mesh view the same dict still carries, because a
volume match alone cannot see a solid that is mirrored or misplaced.

The dict stays kind "mesh" with the extrusion under d["exact"], and the mesh
is the authority: code written before #330 that edits the verts (a subclass
grading a girder, a wrapper placing one) must get the edited mesh in the IFC,
not the stale extrusion.
"""
from __future__ import annotations

import uuid

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
import ifcopenshell.geom  # noqa: E402
import numpy as np  # noqa: E402

from bimforge.author import gate  # noqa: E402
from bimforge.author.emit_ifc import emit_ifc, representation_type  # noqa: E402
from bimforge.author.model import Element, StructureModel  # noqa: E402
from bimforge.author.primitives import (  # noqa: E402
    Affine, MirrorX, Prism, SectionPrism, ShearedZ, exact_of, place_exact)
from bimforge.author.project import ProjectContext  # noqa: E402

PROFILE = [(0, 0), (4, 0), (4, 3), (1, 3), (0, 1)]           # asymmetric
VOID = [(1.5, 0.5), (3, 0.5), (3, 2), (1.5, 2)]


def _model():
    ctx = ProjectContext(name="Parametric Fixture", epsg=2226,
                         base_e=6_594_000.0, base_n=1_943_000.0,
                         guid_ns=uuid.UUID(int=330))
    return StructureModel("parametric", ctx)


def _sp():
    return SectionPrism("s", PROFILE, length=10.0, y0=2.0, voids=[VOID])


def _emit(tmp_path, *pairs):
    m = _model()
    for name, geom in pairs:
        m.add(Element(name, ifc_class="IfcBuildingElementProxy",
                      classifications=[], geometry=geom))
    out = tmp_path / "p.ifc"
    emit_ifc(m, str(out))
    return m, ifcopenshell.open(str(out)), out


def _shape(f, name):
    st = ifcopenshell.geom.settings()
    st.set("use-world-coords", True)
    (p,) = [p for p in f.by_type("IfcBuildingElementProxy") if p.Name == name]
    g = ifcopenshell.geom.create_shape(st, p).geometry
    v = np.array(g.verts).reshape(-1, 3)
    import ifcopenshell.util.shape as us
    return p, v.min(0), v.max(0), us.get_volume(g)


def _mesh_box(m, d):
    k = m.ctx.ft_to_m
    v = np.array(d["verts"]) * k
    return v.min(0), v.max(0)


@pytest.mark.parametrize("wrap", [
    lambda s: s,
    MirrorX,
    lambda s: ShearedZ(s, slope=0.05, y_ref=3.0),
    # a girder on two seats, turned in plan and set on its line of layout
    lambda s: Affine.placed(s, (120.0, -40.0, 7.5), angle_deg=33.0,
                            grade=-0.036),
    lambda s: Affine.placed(s, (5.0, 6.0, 0.0), angle_deg=-120.0, grade=0.02),
    # nested: a handed copy, then placed
    lambda s: Affine.placed(MirrorX(s), (10.0, 0.0, 2.0), angle_deg=90.0),
], ids=["plain", "mirror", "sheared", "placed", "placed-reversed", "nested"])
def test_section_prism_is_one_extrusion_in_the_mesh_place(tmp_path, wrap):
    g = wrap(_sp())
    (d,) = g.body_solids()
    assert d["kind"] == "mesh" and exact_of(d)["kind"] == "extrusion"
    m, f, _ = _emit(tmp_path, ("s", d))
    p, lo, hi, vol = _shape(f, "s")
    (rep,) = p.Representation.Representations
    (item,) = rep.Items
    assert item.is_a("IfcExtrudedAreaSolid")
    assert rep.RepresentationType == "SweptSolid"
    # the void rides as the profile's inner curve — no keyhole bridge
    assert item.SweptArea.is_a("IfcArbitraryProfileDefWithVoids")
    assert len(item.SweptArea.InnerCurves) == 1
    assert not f.by_type("IfcFacetedBrep")
    mlo, mhi = _mesh_box(m, d)
    assert lo == pytest.approx(mlo, abs=1e-9)
    assert hi == pytest.approx(mhi, abs=1e-9)
    assert vol == pytest.approx(_sp().volume_cf * m.ctx.ft_to_m ** 3, rel=1e-9)


@pytest.mark.parametrize("lin", [
    ((2.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),      # scales
    # unit determinant, yet a 10x5x2 footprint doubles and its height halves
    ((2.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 0.5)),
    # a rigid tip of z into plan: the plan footprint is no longer area_sf
    ((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
    ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, float("nan"))),
    ((float("inf"), 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
], ids=["scale", "det-one-squash", "tip", "nan", "inf"])
def test_affine_refuses_maps_that_change_a_declared_quantity(lin):
    with pytest.raises(ValueError):
        Affine(_sp(), lin)


def test_affine_keeps_every_declared_quantity():
    from bimforge.author.primitives import Prismatoid
    deck = Prismatoid("d", [(0, 0, 0), (10, 0, 0), (10, 5, 0), (0, 5, 0)],
                      [(0, 0, 2), (10, 0, 2), (10, 5, 2), (0, 5, 2)])
    a = Affine.placed(MirrorX(deck), (7.0, -3.0, 1.0), angle_deg=40.0,
                      grade=0.1)
    assert a.volume_cf == pytest.approx(deck.volume_cf)
    assert a.area_sf == deck.area_sf and a.height_ft == deck.height_ft
    tris = [[a.body_solids()[0]["verts"][i] for i in t]
            for t in a.body_solids()[0]["tris"]]
    from bimforge.author.primitives import face_volume
    assert face_volume(tris) == pytest.approx(deck.volume_cf)


def test_affine_moves_the_plan_footprint_with_the_solid():
    (d,) = Affine.placed(_sp(), (100.0, 50.0, 0.0), angle_deg=90.0).body_solids()
    (ring,) = d["plan"]
    # x in [0, 4], y in [2, 12] turned +90 deg: x' = 100 - y, y' = 50 + x
    assert sorted(ring) == pytest.approx(sorted(
        [(98.0, 50.0), (98.0, 54.0), (88.0, 54.0), (88.0, 50.0)]))


def test_grading_across_the_section_degrades_to_the_placed_mesh(tmp_path):
    # a section in x-z graded along x tilts the profile plane off
    # orthonormal: no longer an extrusion of that profile, so the mesh
    g = Affine.placed(_sp(), (5.0, 6.0, 0.0), angle_deg=30.0, grade=0.02,
                      along="x")
    (d,) = g.body_solids()
    assert "exact" not in d
    m, f, _ = _emit(tmp_path, ("s", g))
    _p, lo, hi, vol = _shape(f, "s")
    assert f.by_type("IfcFacetedBrep") and not f.by_type("IfcExtrudedAreaSolid")
    mlo, mhi = _mesh_box(m, d)
    assert lo == pytest.approx(mlo, abs=1e-9)
    assert hi == pytest.approx(mhi, abs=1e-9)
    assert vol == pytest.approx(_sp().volume_cf * m.ctx.ft_to_m ** 3, rel=1e-9)


def test_a_plane_skewing_map_degrades_to_the_mesh():
    (d,) = _sp().body_solids()
    skew = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.3, 0.0, 1.0))  # tilts x-z
    out = place_exact(d, skew)
    assert out["kind"] == "mesh" and "exact" not in out
    assert out["verts"] is d["verts"]


def test_spillway_rigid_placement_keeps_the_extrusion_in_place(tmp_path):
    from bimforge.author.families.spillway import _xf_solid
    c, s = 0.6, 0.8                                   # a rotated plan frame

    def world(x, y):
        return (100.0 + c * x - s * y, 50.0 + s * x + c * y)
    d = _xf_solid(_sp().body_solids()[0], world, 7.0)
    assert exact_of(d)["kind"] == "extrusion"
    m, f, _ = _emit(tmp_path, ("s", d))
    _p, lo, hi, _v = _shape(f, "s")
    mlo, mhi = _mesh_box(m, d)
    assert lo == pytest.approx(mlo, abs=1e-9)
    assert hi == pytest.approx(mhi, abs=1e-9)


class _GradedPrism(SectionPrism):
    """The pre-#330 idiom (barrier-pilot's SlopedPrism): grade the girder by editing
    the verts super() returns, knowing nothing of d["exact"]."""

    def body_solids(self):
        sols = super().body_solids()
        for s in sols:
            s["verts"] = [(x, y, z + 0.05 * y) for x, y, z in s["verts"]]
        return sols


class _MeshOnlyWrapper:
    """The pre-#330 wrapper idiom (Work's OnLine/Placed): refuse anything
    but kind "mesh", copy the dict, replace its verts."""

    def __init__(self, inner, dz):
        self.inner, self.dz = inner, dz

    def body_solids(self):
        out = []
        for s in self.inner.body_solids():
            if s.get("kind") != "mesh":
                raise TypeError(f"needs a mesh solid, got {s.get('kind')!r}")
            d = dict(s)
            d["verts"] = [(x, y, z + self.dz) for x, y, z in s["verts"]]
            out.append(d)
        return out


@pytest.mark.parametrize("geom", [
    _GradedPrism("s", PROFILE, length=10.0, y0=2.0, voids=[VOID]),
    _MeshOnlyWrapper(_sp(), 5.0),
], ids=["graded-subclass", "mesh-only-wrapper"])
def test_an_edited_mesh_is_written_as_edited_not_as_the_stale_extrusion(
        tmp_path, geom):
    (d,) = geom.body_solids()
    assert "exact" in d and exact_of(d) is None
    m, f, out = _emit(tmp_path, ("s", geom))
    p, lo, hi, _vol = _shape(f, "s")
    assert p.Representation.Representations[0].Items[0].is_a("IfcFacetedBrep")
    mlo, mhi = _mesh_box(m, d)
    assert lo == pytest.approx(mlo, abs=1e-9)
    assert hi == pytest.approx(mhi, abs=1e-9)


def test_a_pass_through_wrapper_keeps_the_extrusion(tmp_path):
    _m, f, _ = _emit(tmp_path, ("s", _MeshOnlyWrapper(_sp(), 0.0)))
    assert f.by_type("IfcExtrudedAreaSolid") and not f.by_type("IfcFacetedBrep")


# ------------------------------------------------------------------ #329
def test_a_faceted_brep_is_labelled_brep_not_swept_solid(tmp_path):
    taper = Prism("t", [(0, 0), (4, 0), (4, 4), (0, 4)], 0.0,
                  top_z=[1.0, 2.0, 2.0, 1.0])
    _m, f, _ = _emit(tmp_path, ("t", taper))
    (rep,) = f.by_type("IfcShapeRepresentation")
    assert rep.Items[0].is_a("IfcFacetedBrep")
    assert rep.RepresentationType == "Brep"


def test_representation_type_names_mixes_and_refuses_the_unnameable():
    f = ifcopenshell.file(schema="IFC4")
    brep = f.create_entity("IfcFacetedBrep")
    ext = f.create_entity("IfcExtrudedAreaSolid")
    disk = f.create_entity("IfcSweptDiskSolid")
    boolean = f.create_entity("IfcBooleanResult")
    assert representation_type([ext]) == "SweptSolid"
    assert representation_type([ext, disk]) == "AdvancedSweptSolid"
    assert representation_type([brep]) == "Brep"
    assert representation_type([ext, brep]) == "SolidModel"
    assert representation_type([boolean]) == "CSG"
    with pytest.raises(ValueError, match="no RepresentationType"):
        representation_type([boolean, ext], "el")


def test_post_gate_rejects_a_mislabelled_representation(tmp_path):
    taper = Prism("t", [(0, 0), (4, 0), (4, 4), (0, 4)], 0.0,
                  top_z=[1.0, 2.0, 2.0, 1.0])
    m, f, out = _emit(tmp_path, ("t", taper))
    assert gate._ifc_representation_type_check(m, out) == []
    (rep,) = f.by_type("IfcShapeRepresentation")
    rep.RepresentationType = "SweptSolid"          # the pre-#329 label
    f.write(str(out))
    (msg,) = gate._ifc_representation_type_check(m, out)
    assert "'SweptSolid' does not admit ['IfcFacetedBrep']" in msg
    assert msg.startswith("t:")
