"""Earthwork/loft primitives: mitred offsets, face volumes, lofted walls,
section extrusions with voids, backfill-with-cuts (spillway-pilot/bridge-pilot lineage)."""
import math
import uuid

import pytest

from bimforge.author.primitives import (
    BatteredWall, Fill, Prism, SectionPrism, _signed_volume, as_mesh,
    face_volume, loft_faces, mitre_offset, outward_normals)


# ------------------------------------------------------------ plan offsets
def test_outward_normals_per_segment():
    assert outward_normals([(0, 0), (10, 0), (10, 10)], side=+1) == [
        (0, -1), (1, 0)]


def test_outward_normals_other_side_flips():
    assert outward_normals([(0, 0), (10, 0)], side=-1) == [(0, 1)]


def test_mitre_offset_right_angle_is_longer_than_unit():
    m = mitre_offset((0, -1), (1, 0))
    assert m == (pytest.approx(1.0), pytest.approx(-1.0))
    # a 90 deg mitre is sqrt(2) long — that's the point: offsetting the
    # corner by t*m keeps BOTH adjacent faces at distance t.
    assert math.hypot(*m) == pytest.approx(math.sqrt(2.0))


def test_mitre_offset_antiparallel_raises():
    with pytest.raises(ValueError):
        mitre_offset((0, 1), (0, -1))


def test_mitre_offset_near_hairpin_raises():
    # 179 deg deflection: |m| = 1/cos(89.5 deg) ~ 115, so the corner vertex
    # would spike to 115x the wall thickness — and the spike's volume lands
    # honestly in the declared Qto. Beyond the ~135 deg limit the mitre must
    # raise, not silently emit the spike.
    th = math.radians(179.0)
    with pytest.raises(ValueError, match="deflection"):
        mitre_offset((0.0, -1.0), (math.sin(th), -math.cos(th)))


# ------------------------------------------------------------- face_volume
def _cube_faces(ox=0.0, oy=0.0, oz=0.0, s=1.0):
    """Six outward-facing rings of an axis-aligned cube at (ox, oy, oz)."""
    p = lambda x, y, z: (ox + x * s, oy + y * s, oz + z * s)
    return [
        [p(0, 0, 0), p(0, 1, 0), p(1, 1, 0), p(1, 0, 0)],   # bottom, -Z
        [p(0, 0, 1), p(1, 0, 1), p(1, 1, 1), p(0, 1, 1)],   # top, +Z
        [p(0, 0, 0), p(1, 0, 0), p(1, 0, 1), p(0, 0, 1)],   # -Y
        [p(1, 0, 0), p(1, 1, 0), p(1, 1, 1), p(1, 0, 1)],   # +X
        [p(1, 1, 0), p(0, 1, 0), p(0, 1, 1), p(1, 1, 1)],   # +Y
        [p(0, 1, 0), p(0, 0, 0), p(0, 0, 1), p(0, 1, 1)],   # -X
    ]


def test_face_volume_unit_cube():
    assert face_volume(_cube_faces()) == pytest.approx(1.0)


def test_face_volume_is_translation_invariant_at_state_plane_magnitude():
    # The local-origin regression: sum(a.(b x c))/6 is origin-independent in
    # exact arithmetic but not in float64 at ~1e6-ft coordinates.
    v = face_volume(_cube_faces(ox=6_592_000.0, oy=1_943_000.0, oz=0.0))
    assert abs(v - 1.0) < 1e-9


# -------------------------------------------------------------- loft_faces
def test_loft_faces_counts_and_volume():
    s0 = [(0, 0, 0.0), (1, 0, 0.0), (1, 1, 0.0), (0, 1, 0.0)]
    s1 = [(x, y, 1.0) for x, y, _z in s0]
    faces = loft_faces([s0, s1])          # default: single-diagonal 2-tri
    assert len(faces) == 2 + 8            # two caps + 2 triangles x 4 edges
    tri_sides = [f for f in faces[2:]]
    assert all(len(f) == 3 for f in tri_sides)
    assert face_volume(faces) == pytest.approx(1.0)


def test_loft_faces_fan_emits_four_triangles_per_edge():
    s0 = [(0, 0, 0.0), (1, 0, 0.0), (1, 1, 0.0), (0, 1, 0.0)]
    s1 = [(x, y, 1.0) for x, y, _z in s0]
    faces = loft_faces([s0, s1], fan=True)
    assert len(faces) == 2 + 16           # two caps + centroid 4-fan x 4 edges
    assert all(len(f) == 3 for f in faces[2:])
    # planar quads are flux-identical: fan is a no-op on the enclosed volume.
    assert face_volume(faces) == pytest.approx(1.0)
    assert face_volume(faces) == pytest.approx(face_volume(loft_faces([s0, s1])))


def test_loft_faces_fan_twisted_quad_integrates_to_prismatoid():
    # A loft with ONE vertex sliding tangentially at the top makes a twisted
    # (non-planar) lateral quad. The centroid 4-fan integrates it to the exact
    # linear-morph (prismatoid) volume; the single-diagonal default biases it
    # high. z from 0->3.5, one section over length 9.833.
    L = 9.0 + 10.0 / 12.0
    run = [(0.0, 0.0), (1.75, 0.0), (1.1875, 3.5), (0.0, 3.5)]
    nose = [(0.0, 0.0), (1.75, 0.0), (1.75, 3.5), (0.0, 3.5)]
    a0 = [(x, 0.0, z) for x, z in run]
    a1 = [(x, L, z) for x, z in nose]

    def area(ring2d):
        s = 0.0
        for (x0, z0), (x1, z1) in zip(ring2d, ring2d[1:] + ring2d[:1]):
            s += x0 * z1 - x1 * z0
        return abs(s) / 2.0

    mid = [((x0 + x1) / 2.0, (z0 + z1) / 2.0)
           for (x0, z0), (x1, z1) in zip(run, nose)]
    prismatoid = L * (area(run) + 4 * area(mid) + area(nose)) / 6.0
    assert face_volume(loft_faces([a0, a1], fan=True)) == pytest.approx(
        prismatoid, rel=1e-9)
    # the single-diagonal default does NOT hit the prismatoid here (twist bias)
    assert face_volume(loft_faces([a0, a1])) != pytest.approx(
        prismatoid, rel=1e-6)


# ------------------------------------------------------------ SectionPrism
def test_section_prism_quantities():
    sp = SectionPrism("s", profile=[(0, 0), (4, 0), (4, 2), (0, 2)],
                      y0=0, length=10)
    assert sp.area_sf == pytest.approx(8.0)
    assert sp.volume_cf == pytest.approx(80.0)


def test_section_prism_void_comes_off_the_volume():
    sp = SectionPrism("s", profile=[(0, 0), (4, 0), (4, 2), (0, 2)],
                      y0=0, length=10,
                      voids=[[(1, 0.5), (3, 0.5), (3, 1.5), (1, 1.5)]])
    assert sp.area_sf == pytest.approx(6.0)
    assert sp.volume_cf == pytest.approx((8.0 - 2.0) * 10.0)


def test_section_prism_body_solids_mesh_closes_to_declared_volume():
    sp = SectionPrism("s", profile=[(0, 0), (4, 0), (4, 2), (0, 2)],
                      y0=0, length=10,
                      voids=[[(1, 0.5), (3, 0.5), (3, 1.5), (1, 1.5)]])
    (d,) = sp.body_solids()
    assert d["kind"] == "mesh"               # #330: the extrusion rides
    assert d["exact"]["kind"] == "extrusion"  # under d["exact"]
    assert d["units"] == "ft"
    tris = [tuple(d["verts"][i] for i in tri) for tri in d["tris"]]
    assert face_volume(tris) == pytest.approx(sp.volume_cf, abs=1e-6)
    # plan footprint: profile x-extent by the extrusion run
    (ring,) = d["plan"]
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    assert (min(xs), max(xs)) == (pytest.approx(0.0), pytest.approx(4.0))
    assert (min(ys), max(ys)) == (pytest.approx(0.0), pytest.approx(10.0))


# ------------------------------------------------------------ BatteredWall
def test_battered_wall_straight_matches_trapezoid_closed_form():
    w = BatteredWall("w", lol=[(0, 0), (20, 0)], top_profile=[(0, 8), (20, 8)],
                     key_index=0, base_el=0, t_top=1.0, batter=1 / 12,
                     side=+1)
    h = 8.0
    area = h * (1.0 + (1.0 + h / 12.0)) / 2.0     # trapezoid section
    assert w.volume_cf == pytest.approx(area * 20.0, abs=1e-6)
    assert w.report[0] == (pytest.approx(0.0), pytest.approx(8.0),
                           pytest.approx(1.0 + 8.0 / 12.0))
    assert w.report[1][0] == pytest.approx(20.0)


def test_battered_wall_reversed_lol_same_volume():
    # the direction-agnostic breakpoint filter: a mirrored wall runs the
    # other way along the key axis and must not straight-line its top.
    kw = dict(top_profile=[(0, 8), (10, 6), (20, 8)], key_index=0, base_el=0,
              t_top=1.0, batter=1 / 12, side=+1)
    a = BatteredWall("a", lol=[(0, 0), (20, 0)], **kw)
    b = BatteredWall("b", lol=[(20, 0), (0, 0)], **kw)
    assert len(a.report) == len(b.report) == 3    # the EL break is honored
    assert b.volume_cf == pytest.approx(a.volume_cf, abs=1e-9)


def test_battered_wall_mitred_corner_qto_is_the_emitted_solids_volume():
    w = BatteredWall("w", lol=[(0, 0), (10, 0), (10, 10)],
                     top_profile=[(0, 8), (10, 8)], key_index=0, base_el=0,
                     t_top=1.0, batter=1 / 12, side=+1)
    (d,) = w.body_solids()
    assert d["kind"] == "mesh"
    assert d["units"] == "ft"
    tris = [tuple(d["verts"][i] for i in tri) for tri in d["tris"]]
    # self-consistency: the declared Qto IS the emitted solid's volume
    assert face_volume(tris) == pytest.approx(w.volume_cf, abs=1e-6)
    # ... but self-consistency alone passes under a dropped second leg
    # (213.33 is also self-consistent) or unit corner normals, so pin the
    # analytic value: two 10-ft straight legs at trapezoid area
    # 8*(1 + 5/3)/2 = 32/3 sf each, plus the outside-corner wedge
    # integral t(z)^2 dz = integral (5/3 - z/12)^2 dz over 0..8 = 392/27.
    # Total 640/3 + 392/27 = 6152/27 ~ 227.851852 cf.
    assert w.volume_cf == pytest.approx(
        20.0 * (8.0 * (1.0 + (1.0 + 8.0 / 12.0)) / 2.0) + 392.0 / 27.0,
        rel=1e-6)
    # both legs are present: the second leg runs to y=10
    assert max(v[1] for v in d["verts"]) == pytest.approx(10.0)
    assert d["plan"] == [w.base]
    assert w.ifc == "IfcWall"


def test_battered_wall_mesh_winds_outward_for_both_sides():
    # An inside-out shell (negative signed volume) is spec-invalid as an
    # IfcClosedShell: backface-culling viewers and signed-volume consumers
    # see the faces pointing INTO the solid. face_volume's abs() masks it,
    # so pin the SIGN at the body_solids() boundary for both offset sides.
    for side in (+1.0, -1.0):
        w = BatteredWall("w", lol=[(0, 0), (20, 0)],
                         top_profile=[(0, 8), (20, 8)], key_index=0,
                         base_el=0, t_top=1.0, batter=1 / 12, side=side)
        (d,) = w.body_solids()
        sv = _signed_volume([tuple(d["verts"][i] for i in t)
                             for t in d["tris"]])
        assert sv > 0.0
        assert sv == pytest.approx(w.volume_cf, abs=1e-6)


def test_section_prism_mesh_winds_outward_for_cw_profile():
    # a clockwise-given profile ring must still come out as an outward-
    # facing (positive signed volume) shell
    sp = SectionPrism("s", profile=[(0, 0), (0, 2), (4, 2), (4, 0)],  # CW
                      y0=0, length=10)
    (d,) = sp.body_solids()
    sv = _signed_volume([tuple(d["verts"][i] for i in t) for t in d["tris"]])
    assert sv > 0.0
    assert sv == pytest.approx(sp.volume_cf, abs=1e-6)


def test_battered_wall_inverted_base_thickness_raises():
    # batter=-1.0 at H=8, t_top=1: tb = 1 - 8 = -7 flips the offset side
    # and lofts a self-intersecting solid with a plausible abs volume
    with pytest.raises(ValueError, match="tb"):
        BatteredWall("w", lol=[(0, 0), (20, 0)], top_profile=[(0, 8), (20, 8)],
                     key_index=0, base_el=0, t_top=1.0, batter=-1.0, side=+1)


def _flat_top(a, b, z):
    return [(a, z), (b, z)]


def test_base_profile_none_matches_scalar_base_el():
    lol = [(0.0, 0.0), (10.0, 0.0)]
    top = _flat_top(0.0, 10.0, 6.0)
    old = BatteredWall("w", lol, top, key_index=0, base_el=0.0, t_top=1.0,
                       batter=0.0, side=1.0)
    new = BatteredWall("w", lol, top, key_index=0, base_el=0.0, t_top=1.0,
                       batter=0.0, side=1.0, base_profile=None)
    assert new.volume_cf == pytest.approx(old.volume_cf, rel=1e-12)


def test_swept_base_lowers_free_end_and_grows_height():
    # top flat at 6; base 0 -> -4 over 10 ft. No batter straight wall:
    # volume == t_top * avg_height * length = 1 * ((6-0)+(6-(-4)))/2 * 10 = 80
    lol = [(0.0, 0.0), (10.0, 0.0)]
    w = BatteredWall("w", lol, _flat_top(0.0, 10.0, 6.0), key_index=0,
                     base_el=0.0, t_top=1.0, batter=0.0, side=1.0,
                     base_profile=[(0.0, 0.0), (10.0, -4.0)])
    assert w.volume_cf == pytest.approx(80.0, rel=1e-9)
    zbots = [s[0][2] for s in w._sections]
    assert min(zbots) == pytest.approx(-4.0) and max(zbots) == pytest.approx(0.0)


def test_stepped_base_via_near_coincident_stations_is_vertical_riser():
    # pre-stepped base: level 0 for 0..5, drop to -1 for 5..10, riser at ~5.
    base = [(0.0, 0.0), (5.0, 0.0), (5.0 + 1e-3, -1.0), (10.0, -1.0)]
    w = BatteredWall("w", lol=[(0.0, 0.0), (10.0, 0.0)],
                     top_profile=_flat_top(0.0, 10.0, 6.0), key_index=0,
                     base_el=0.0, t_top=1.0, batter=0.0, side=1.0,
                     base_profile=base)
    zbots = sorted({round(s[0][2], 6) for s in w._sections})
    assert zbots == [-1.0, 0.0]
    # two level runs, heights 6 and 7 (approx; the 1e-3 riser bay is negligible)
    assert w.volume_cf == pytest.approx(65.0, rel=1e-3)


# -------------------------------------------------------------------- Fill
def _footing():
    return Prism("ftg", [(2, 2), (8, 2), (8, 8), (2, 8)], 0.0, 2.0)


def test_fill_volume_is_gross_less_cuts():
    f = Fill("bf", base=[(0, 0), (10, 0), (10, 10), (0, 10)], z_bot=0,
             z_top=5, cuts=[_footing()])
    assert f.volume_cf == pytest.approx(500.0 - 72.0)
    assert f.ifc == "IfcEarthworksFill"


def test_fill_rejects_cut_outside_its_z_range():
    with pytest.raises(ValueError, match="z-range"):
        Fill("bf", base=[(0, 0), (10, 0), (10, 10), (0, 10)], z_bot=0,
             z_top=5, cuts=[Prism("deep", [(2, 2), (8, 2), (8, 8), (2, 8)],
                                  -1.0, 2.0)])


def test_fill_rejects_cut_outside_its_plan_bbox():
    # a footing at x~50 on a 10x10 fill: the z-range guard alone let its
    # full 72 cf come off the fill (428 instead of 500) even though the cut
    # never stood inside it
    with pytest.raises(ValueError, match="x-range"):
        Fill("bf", base=[(0, 0), (10, 0), (10, 10), (0, 10)], z_bot=0,
             z_top=5, cuts=[Prism("ftg", [(52, 2), (58, 2), (58, 8), (52, 8)],
                                  0.0, 2.0)])


def test_fill_rejects_cuts_consuming_the_gross_volume():
    with pytest.raises(ValueError, match="gross"):
        Fill("bf", base=[(0, 0), (10, 0), (10, 10), (0, 10)], z_bot=0,
             z_top=5, cuts=[Prism("all", [(0, 0), (10, 0), (10, 10), (0, 10)],
                                  0.0, 5.0)])


def test_fill_body_solids_carries_nested_cut_dicts():
    f = Fill("bf", base=[(0, 0), (10, 0), (10, 10), (0, 10)], z_bot=0,
             z_top=5, cuts=[_footing()])
    (d,) = f.body_solids()
    assert d["kind"] == "fill"
    assert d["units"] == "ft"
    assert d["base"] == [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert d["holes"] == []
    assert (d["z_bot"], d["z_top"]) == (0, 5)
    (cut,) = d["cuts"]
    assert cut["base"] == [(2, 2), (8, 2), (8, 8), (2, 8)]
    assert (cut["z_bot"], cut["z_top"]) == (0.0, 2.0)


# ------------------------------------------------- emit_ifc compatibility
def test_emit_ifc_mesh_branch_ignores_the_new_plan_key(tmp_path):
    """`plan` is a NEW optional key on "mesh" dicts (emit_dxf will learn to
    draw it); emit_ifc must keep ignoring it."""
    ifcopenshell = pytest.importorskip("ifcopenshell")
    from bimforge.author.emit_ifc import emit_ifc
    from bimforge.author.model import Element, StructureModel
    from bimforge.author.project import ProjectContext

    ctx = ProjectContext(name="Earthwork Fixture", epsg=2226,
                         base_e=6_594_000.0, base_n=1_943_000.0,
                         guid_ns=uuid.UUID(int=12))
    m = StructureModel("earthwork", ctx)
    sp = SectionPrism("weir", profile=[(0, 0), (4, 0), (4, 2), (0, 2)],
                      length=10.0)
    # the extrusion dropped: the plain "mesh" branch under test
    d = as_mesh(sp.body_solids()[0])
    assert "plan" in d
    m.add(Element("weir", ifc_class="IfcBuildingElementProxy",
                  classifications=[], geometry=d))
    out = tmp_path / "e.ifc"
    emit_ifc(m, str(out))
    f = ifcopenshell.open(str(out))
    (el,) = f.by_type("IfcBuildingElementProxy")
    breps = [i for r in el.Representation.Representations
             for i in r.Items if i.is_a("IfcFacetedBrep")]
    assert len(breps) == 1
    assert len(breps[0].Outer.CfsFaces) == len(d["tris"])
