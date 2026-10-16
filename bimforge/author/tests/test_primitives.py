"""Primitives: hand-computed closed forms, faceting bands, fillet lengths."""
import math

import pytest

from bimforge.author.primitives import (
    ARC_SEGMENTS, FACET_TOLERANCE, STEEL_LB_PER_IN3, ArcBand, Bar, Bolt,
    Plate, Prism, RebarBuilder, ShapedStiffener, Tube, bar_stations,
    circle_poly, equal_area_polygon_radius, fillet_polyline, obround_poly,
    profile_at)


def test_prism_flat_volume_and_height():
    p = Prism("ftg", [(0, 0), (4, 0), (4, 4), (0, 4)], z_bot=0.0, z_top=2.0,
              ifc="IfcFooting")
    assert p.area_sf == pytest.approx(16.0)
    assert p.volume_cf == pytest.approx(32.0)
    assert p.height_ft == pytest.approx(2.0)


def test_prism_per_vertex_top_is_exact_for_a_planar_taper():
    # 10x2 plan tapering 4 ft -> 0 along x: volume = mean height 2 * area 20.
    base = [(0, 0), (10, 0), (10, 2), (0, 2)]
    p = Prism("wing", base, z_bot=0.0, top_z=[4.0, 0.0, 0.0, 4.0])
    assert p.volume_cf == pytest.approx(40.0)
    assert p.height_ft == pytest.approx(2.0)   # Height x Area == Volume exactly


def test_prism_holes_and_arg_validation():
    hole = [(1, 1), (2, 1), (2, 2), (1, 2)]
    p = Prism("slab", [(0, 0), (4, 0), (4, 4), (0, 4)], 0.0, z_top=1.0,
              holes=[hole])
    assert p.area_sf == pytest.approx(15.0)
    assert p.volume_cf == pytest.approx(15.0)
    with pytest.raises(ValueError, match="exactly one"):
        Prism("x", [(0, 0), (1, 0), (1, 1)], 0.0)
    with pytest.raises(ValueError, match="vertex count"):
        Prism("x", [(0, 0), (1, 0), (1, 1)], 0.0, top_z=[1.0, 1.0])


def test_prism_per_vertex_bottom_makes_a_wedge_without_decomposition():
    """A per-vertex `bottom_z` (mirror of `top_z`) lets a single Prism carry a
    sloping BASE — the wedge that previously forced a two-piece slab+wedge
    decomposition (which then got emitted mirrored, since Prism had top_z but
    no bottom_z). 10x2 plan, flat top at 4, base sloping 0 -> 2 along x: the
    depth runs 4 -> 2, mean 3, volume = 3 * 20 = 60. (#251)"""
    base = [(0, 0), (10, 0), (10, 2), (0, 2)]
    p = Prism("wedge", base, z_bot=0.0, z_top=4.0,
              bottom_z=[0.0, 2.0, 2.0, 0.0])
    assert p.volume_cf == pytest.approx(60.0)
    assert p.height_ft == pytest.approx(3.0)         # Height x Area == Volume


def test_prism_bottom_z_and_top_z_together_integrate_exactly():
    """Both surfaces per-vertex: depth = top - bottom evaluated per vertex,
    fan-integrated. Top 5->3, bottom 1->0 along x over a 6x1 plan:
    depth 4 at x=0, 3 at x=6, mean 3.5, volume 3.5 * 6 = 21."""
    base = [(0, 0), (6, 0), (6, 1), (0, 1)]
    p = Prism("both", base, z_bot=0.0,
              top_z=[5.0, 3.0, 3.0, 5.0], bottom_z=[1.0, 0.0, 0.0, 1.0])
    assert p.volume_cf == pytest.approx(21.0)


def test_prism_bottom_z_length_must_match_base():
    with pytest.raises(ValueError, match="vertex count"):
        Prism("x", [(0, 0), (1, 0), (1, 1)], 0.0, z_top=1.0,
              bottom_z=[0.0, 0.0])


def test_prism_rejects_holes_with_a_per_vertex_face():
    """Holes are punched only on the flat-extrude path; both B-rep emitters
    ignore them for a per-vertex face, so allowing the combination would let
    volume_cf (which subtracts the hole) diverge from the emitted solid and
    make true_volume_check delete a correct output. Reject it loudly. A flat
    z_top + holes stays supported."""
    tri = [(0, 0), (4, 0), (4, 4), (0, 4)]
    hole = [[(1, 1), (2, 1), (2, 2), (1, 2)]]
    with pytest.raises(ValueError, match="holes are not supported"):
        Prism("x", tri, 0.0, top_z=[2.0, 2.0, 1.0, 1.0], holes=hole)
    with pytest.raises(ValueError, match="holes are not supported"):
        Prism("x", tri, 0.0, z_top=2.0, bottom_z=[0.0, 0.0, 1.0, 1.0],
              holes=hole)
    # flat z_top + holes still fine:
    Prism("ok", tri, 0.0, z_top=2.0, holes=hole)


def test_prism_body_solids_carries_bottom_z():
    base = [(0, 0), (10, 0), (10, 2), (0, 2)]
    p = Prism("wedge", base, z_bot=0.0, z_top=4.0,
              bottom_z=[0.0, 2.0, 2.0, 0.0])
    (d,) = p.body_solids()
    assert d["bottom_z"] == [0.0, 2.0, 2.0, 0.0]


def test_taper_prism_triangles_honours_per_vertex_bottom():
    """The shared mesh builder sweeps a per-vertex bottom too; its faceted
    volume must equal the analytic wedge (via the divergence-theorem
    face_volume of the closed shell)."""
    from bimforge.author.primitives import (taper_prism_triangles,
                                             face_volume)
    base = [(0, 0), (10, 0), (10, 2), (0, 2)]
    tris = taper_prism_triangles(base, [4.0, 4.0, 4.0, 4.0], 0.0,
                                 bottom_z=[0.0, 2.0, 2.0, 0.0])
    faces = [list(t) for t in tris]
    assert face_volume(faces) == pytest.approx(60.0)


def test_tube_volume():
    t = Tube("casing", length_ft=10.0, r_out_ft=1.0, wall_ft=0.25)
    assert t.volume_cf == pytest.approx(math.pi * (1.0 - 0.75 ** 2) * 10.0)
    with pytest.raises(ValueError):
        Tube("bad", 10.0, 1.0, 1.5)


def test_plate_holes_come_off_weight_and_barrels_join_surface():
    # pipe-supports-pilot base plate: 0.75 x 24.75 x 12, 4 holes of 1.3125 in.
    p = Plate("base", 0.75, 24.75, 12.0, count=1, holes_each=4,
              hole_dia_in=1.3125)
    hole_a = 4 * math.pi * (1.3125 / 2) ** 2
    want_vol = 0.75 * 24.75 * 12.0 - hole_a * 0.75
    assert p.volume_in3 == pytest.approx(want_vol)
    assert p.weight_lb == pytest.approx(want_vol * STEEL_LB_PER_IN3)
    gross_s = 2 * (24.75 * 12 + 24.75 * 0.75 + 12 * 0.75)
    barrel = 4 * math.pi * 1.3125 * 0.75
    assert p.surface_in2 == pytest.approx(gross_s - 2 * hole_a + barrel)


def test_arcband_exact_vs_faceted_within_tolerance_at_64_and_out_at_4():
    band = ArcBand("saddle", 0.375, 12.0, inner_dia_in=24.0, wrap_deg=180.0,
                   arc_segments=ARC_SEGMENTS)
    exact, faceted = band.volume_in3, band.faceted_volume_in3
    assert abs(faceted - exact) / exact < FACET_TOLERANCE          # 64 segs pass
    r_mean = 12.0 + 0.375 / 2
    assert band.arc_length_in == pytest.approx(r_mean * math.pi)
    coarse = ArcBand("saddle", 0.375, 12.0, 24.0, 180.0, arc_segments=4)
    err = abs(coarse.faceted_volume_in3 - coarse.volume_in3) / coarse.volume_in3
    assert err > FACET_TOLERANCE                                   # 4 segs fail


def test_shaped_stiffener_closed_form_matches_facets():
    # the pipe-supports-pilot arrangement: r_outer 12.375, cl 20.375, flat floor at 2.25.
    st = ShapedStiffener("stiff", 0.375, r_outer_in=12.375, cl_in=20.375,
                         half_width_in=12.0, z_inner_in=2.25, z_outer_in=2.25,
                         y_step_in=12.0, pieces=2, y_start_in=0.375)
    assert st.area_in2 > 0
    err = abs(st.faceted_area_in2 - st.area_in2) / st.area_in2
    assert err < FACET_TOLERANCE
    assert st.volume_in3 == pytest.approx(2 * st.area_in2 * 0.375)


def test_bolt_weight_includes_nuts():
    b = Bolt("ab", 0.75, 18.0, count=4, nuts=2)
    rod = 4 * math.pi * 0.375 ** 2 * 18.0 * STEEL_LB_PER_IN3
    assert b.weight_lb == pytest.approx(rod + 4 * 2 * Bolt.NUT_LB)


def test_equal_area_polygon_radius_is_exact():
    r = equal_area_polygon_radius(0.3125, 64)
    n = 64
    poly_a = 0.5 * n * r * r * math.sin(2 * math.pi / n)
    assert poly_a == pytest.approx(math.pi * 0.3125 ** 2, rel=1e-12)
    from bimforge.author.alignment import poly_area
    assert poly_area(circle_poly(0.3125, 64)) == pytest.approx(
        math.pi * 0.3125 ** 2, rel=1e-9)


def test_obround_poly_exact_area():
    from bimforge.author.alignment import poly_area
    want = 4.0 * 2.0 + math.pi * 1.0 ** 2   # 6x2 obround: 4x2 rect + r=1 circle
    assert poly_area(obround_poly(6.0, 2.0, 64)) == pytest.approx(want, rel=1e-9)
    with pytest.raises(ValueError):
        obround_poly(1.0, 2.0)


def test_fillet_polyline_90_deg_bend_deduction():
    pts = [(0, 0, 0), (10, 0, 0), (10, 10, 0)]
    verts, segs, length = fillet_polyline(pts, r=1.0)
    assert length == pytest.approx(20.0 - 2.0 + math.pi / 2.0)
    assert [s[0] for s in segs] == ["line", "arc", "line"]
    with pytest.raises(ValueError, match="reversal"):
        fillet_polyline([(0, 0, 0), (10, 0, 0), (0, 0, 0)], 1.0)
    with pytest.raises(ValueError, match="setback"):
        fillet_polyline([(0, 0, 0), (0.5, 0, 0), (0.5, 10, 0)], 1.0)


def test_bar_and_builder():
    rb = RebarBuilder(size=5, cover_in=3.0, spacing_in=6.0)
    assert rb.bend_r == pytest.approx(3.5 * 0.625 / 12.0)
    b = rb.bar("A1", "footing", [(0.25, 0, 0), (3.75, 0, 0)], "straight")
    assert b.length == pytest.approx(3.5)
    assert b.weight == pytest.approx(3.5 * 1.043)
    assert b.n_bends == 0
    assert rb.total_weight_lb == pytest.approx(b.weight)


def test_bar_stations_centred():
    got = bar_stations(0.0, 3.5, 0.5)
    assert len(got) == 8
    assert got[0] == pytest.approx(0.0)
    assert got[-1] == pytest.approx(3.5)
    assert bar_stations(1.0, 1.0, 0.5) == []


def test_profile_at_clamps_and_interpolates():
    prof = [(0.0, 10.0), (10.0, 20.0)]
    assert profile_at(prof, -1.0) == 10.0
    assert profile_at(prof, 5.0) == pytest.approx(15.0)
    assert profile_at(prof, 99.0) == 20.0
