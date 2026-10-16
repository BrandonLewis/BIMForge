"""author.sweep: swept sections along an Alignment - Pappus vs facet."""
import math

import pytest

from bimforge.author.alignment import Alignment, Profile
from bimforge.author.primitives import FACET_TOLERANCE
from bimforge.author.sweep import (
    SweptSection, net_area_centroid, ring_centroid, ring_self_intersects)

POB = {"station": 0.0, "northing": 0.0, "easting": 0.0}
NORTH_100 = [{"kind": "tangent", "bearing": "N 0-0-0 E", "length": 100.0}]
RECT = [(-2.0, 0.0), (2.0, 0.0), (2.0, 1.0), (-2.0, 1.0)]     # 4 sf, c=(0, .5)


def test_ring_centroid_rectangle_and_offset():
    assert ring_centroid(RECT) == (pytest.approx(0.0), pytest.approx(0.5))
    off = [(1.0, 2.0), (3.0, 2.0), (3.0, 5.0), (1.0, 5.0)]
    assert ring_centroid(off) == (pytest.approx(2.0), pytest.approx(3.5))


def test_ring_centroid_winding_independent():
    assert ring_centroid(list(reversed(RECT))) == (
        pytest.approx(0.0), pytest.approx(0.5))


def test_net_area_centroid_with_void():
    outer = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]     # 16 sf @ (2,2)
    void = [(1.0, 1.0), (2.0, 1.0), (2.0, 2.0), (1.0, 2.0)]      # 1 sf @ (1.5,1.5)
    a, x, z = net_area_centroid(outer, [void])
    assert a == pytest.approx(15.0)
    assert x == pytest.approx((16 * 2.0 - 1 * 1.5) / 15.0)
    assert z == pytest.approx((16 * 2.0 - 1 * 1.5) / 15.0)


def test_net_area_centroid_void_winding_independent():
    outer = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]
    void = [(1.0, 1.0), (2.0, 1.0), (2.0, 2.0), (1.0, 2.0)]
    a1, x1, z1 = net_area_centroid(outer, [void])
    a2, x2, z2 = net_area_centroid(outer, [list(reversed(void))])
    assert (a1, x1, z1) == (pytest.approx(a2), pytest.approx(x2),
                            pytest.approx(z2))


def test_degenerate_net_section_refuses():
    outer = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    with pytest.raises(ValueError, match="section"):
        net_area_centroid(outer, [outer])


def test_straight_sweep_equals_section_prism():
    from bimforge.author.primitives import SectionPrism, exact_of
    sw = SweptSection("s", RECT, Alignment(POB, NORTH_100), 0.0, 100.0)
    sp = SectionPrism("p", RECT, 100.0)
    assert sw.volume_cf == pytest.approx(sp.volume_cf)          # 400 cf
    assert sw.faceted_volume_cf == pytest.approx(sp.volume_cf)
    assert sw.length_ft == pytest.approx(100.0)
    d = sw.body_solids()[0]
    # plumb and square-ended: the exact sweep (#332) rides on the mesh
    assert d["kind"] == "mesh" and d["units"] == "ft"
    assert d["exact"]["kind"] == "sectioned" and exact_of(d) is d["exact"]
    assert d["verts"] and d["tris"]


def test_void_reduces_both_volumes():
    outer = [(-2.0, 0.0), (2.0, 0.0), (2.0, 2.0), (-2.0, 2.0)]
    void = [(-1.0, 0.5), (1.0, 0.5), (1.0, 1.5), (-1.0, 1.5)]
    al = Alignment(POB, NORTH_100)
    solid = SweptSection("solid", outer, al, 0.0, 100.0)
    holed = SweptSection("holed", outer, al, 0.0, 100.0, voids=[void])
    assert solid.volume_cf - holed.volume_cf == pytest.approx(200.0)
    assert holed.faceted_volume_cf == pytest.approx(holed.volume_cf)


def test_kinked_run_refuses():
    kinked = Alignment(POB, [
        {"kind": "tangent", "bearing": "N 0-0-0 E", "length": 100.0},
        {"kind": "tangent", "bearing": "N 45-0-0 E", "length": 100.0}])
    with pytest.raises(ValueError, match="kink"):
        SweptSection("k", RECT, kinked, 0.0, 200.0)


def test_table_validation_refuses():
    al = Alignment(POB, NORTH_100)
    with pytest.raises(ValueError, match="ascending"):
        SweptSection("r", RECT, al, 0.0, 100.0,
                     roll=[(50.0, 0.02), (10.0, 0.04)])
    with pytest.raises(ValueError, match="cover"):
        SweptSection("r", RECT, al, 0.0, 100.0,
                     roll=[(10.0, 0.02), (60.0, 0.04)])   # table stops short
    with pytest.raises(ValueError, match="s1"):
        SweptSection("r", RECT, al, 100.0, 100.0)
    with pytest.raises(ValueError, match="frame"):
        SweptSection("r", RECT, al, 0.0, 100.0, frame="diagonal")
    with pytest.raises(ValueError, match="skew"):
        SweptSection("r", RECT, al, 0.0, 100.0, end_skew=(75.0, 0.0))


def test_skewed_straight_end_closed_form_is_end_plane_rule():
    # asymmetric section: centroid off the pivot -> nonzero correction
    sec = [(0.0, 0.0), (4.0, 0.0), (4.0, 1.0), (0.0, 1.0)]      # x_bar = 2
    al = Alignment(POB, NORTH_100)
    sk = SweptSection("sk", sec, al, 0.0, 100.0, end_skew=(0.0, 30.0))
    want = 4.0 * 100.0 + 4.0 * 2.0 * math.tan(math.radians(30.0))
    assert sk.volume_cf == pytest.approx(want)
    # facet agrees exactly on a straight run (linear shear of the sheets)
    assert sk.faceted_volume_cf == pytest.approx(want, rel=1e-9)
    # symmetric section about the pivot: correction is zero
    sym = SweptSection("sym", RECT, al, 0.0, 100.0, end_skew=(0.0, 30.0))
    assert sym.volume_cf == pytest.approx(400.0)


def test_ring_centroid_degenerate_refuses():
    with pytest.raises(ValueError, match="degenerate"):
        ring_centroid([(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)])


def test_ring_centroid_tolerates_closing_vertex():
    closed = RECT + [RECT[0]]
    assert ring_centroid(closed) == (pytest.approx(0.0), pytest.approx(0.5))


def test_crossing_skew_planes_refuse():
    sec = [(0.0, 0.0), (4.0, 0.0), (4.0, 1.0), (0.0, 1.0)]
    al = Alignment(POB, NORTH_100)
    with pytest.raises(ValueError, match="cross"):
        SweptSection("x", sec, al, 0.0, 0.5, end_skew=(0.0, 30.0))
    # ample run: same skew is fine
    SweptSection("ok", sec, al, 0.0, 100.0, end_skew=(0.0, 30.0))


def test_short_run_skew_at_join_classifies_by_arc_side():
    # 1-ft skewed run STARTING exactly at the tangent->arc join: the whole
    # run is on the arc, so the skewed end must be face-declared even
    # though a proportional eps would sample the tangent side of the join
    arc = {"kind": "curve", "delta": "90-0-0", "radius": 200.0, "turn": "R",
           "length": math.pi * 200.0 / 2.0}
    al = Alignment(POB, [{"kind": "tangent", "bearing": "N 0-0-0 E",
                          "length": 100.0}, arc])
    sw = SweptSection("j", RECT, al, 100.0, 101.0, end_skew=(10.0, 0.0))
    assert sw._face_declared
    assert sw.volume_cf == pytest.approx(sw.faceted_volume_cf)


def test_plan_ring_covers_skewed_end():
    sw = SweptSection("ps", RECT, Alignment(POB, NORTH_100), 0.0, 100.0,
                      end_skew=(0.0, 30.0))
    # index 1 is NORTH: the model frame is x=east, y=north (see `to_model`),
    # and this alignment runs due north, so the run is the y extent.
    ns = [p[1] for p in sw.body_solids()[0]["plan"][0]]
    assert max(ns) == pytest.approx(100.0 + 2.0 * math.tan(math.radians(30.0)))
    assert min(ns) == pytest.approx(0.0)      # unskewed start stays square


def test_both_ends_parallel_skew_cancels():
    sec = [(0.0, 0.0), (4.0, 0.0), (4.0, 1.0), (0.0, 1.0)]      # x_bar = 2
    al = Alignment(POB, NORTH_100)
    par = SweptSection("par", sec, al, 0.0, 100.0, end_skew=(20.0, 20.0))
    assert par.volume_cf == pytest.approx(4.0 * 100.0)          # parallelogram
    assert par.faceted_volume_cf == pytest.approx(4.0 * 100.0, rel=1e-9)


def test_negative_skew_antisymmetric():
    sec = [(0.0, 0.0), (4.0, 0.0), (4.0, 1.0), (0.0, 1.0)]
    al = Alignment(POB, NORTH_100)
    plus = SweptSection("p+", sec, al, 0.0, 100.0, end_skew=(0.0, 30.0))
    minus = SweptSection("p-", sec, al, 0.0, 100.0, end_skew=(0.0, -30.0))
    assert plus.volume_cf - 400.0 == pytest.approx(-(minus.volume_cf - 400.0))
    assert minus.faceted_volume_cf == pytest.approx(minus.volume_cf, rel=1e-9)


def test_void_shifts_skew_correction_through_net_centroid():
    outer = [(0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (0.0, 2.0)]
    void = [(2.5, 0.5), (3.5, 0.5), (3.5, 1.5), (2.5, 1.5)]      # off-centre
    al = Alignment(POB, NORTH_100)
    sw = SweptSection("vs", outer, al, 0.0, 100.0, voids=[void],
                      end_skew=(0.0, 30.0))
    # straight run: the facet is exact, so it IS the check on the net-x_bar
    # end-plane correction - no hand formula needed
    assert sw.faceted_volume_cf == pytest.approx(sw.volume_cf, rel=1e-9)
    a, xb, _zb = net_area_centroid(outer, [void])
    want = a * 100.0 + a * xb * math.tan(math.radians(30.0))
    assert sw.volume_cf == pytest.approx(want)


def test_camber_table_validation_refuses():
    al = Alignment(POB, NORTH_100)
    with pytest.raises(ValueError, match="ascending"):
        SweptSection("c", RECT, al, 0.0, 100.0,
                     camber=[(50.0, 0.1), (10.0, 0.2)])
    with pytest.raises(ValueError, match="cover"):
        SweptSection("c", RECT, al, 0.0, 100.0,
                     camber=[(10.0, 0.1), (60.0, 0.2)])


def test_section_reaching_arc_centre_refuses():
    wide = [(-20.0, 0.0), (20.0, 0.0), (20.0, 1.0), (-20.0, 1.0)]
    tight = Alignment(POB, [
        {"kind": "tangent", "bearing": "N 0-0-0 E", "length": 5.0},
        {"kind": "curve", "delta": "90-0-0", "radius": 15.0, "turn": "R",
         "length": math.pi * 15.0 / 2.0}])
    with pytest.raises(ValueError, match="centre"):
        SweptSection("w", wide, tight, 0.0, tight.s_end)
    # same section on a generous radius is fine
    big = Alignment(POB, [
        {"kind": "tangent", "bearing": "N 0-0-0 E", "length": 5.0},
        {"kind": "curve", "delta": "20-0-0", "radius": 800.0, "turn": "R",
         "length": math.pi * 800.0 / 9.0}])
    SweptSection("ok", wide, big, 0.0, big.s_end)


ARC90_R200 = [
    {"kind": "tangent", "bearing": "N 0-0-0 E", "length": 10.0},
    {"kind": "curve", "delta": "90-0-0", "radius": 200.0, "turn": "R",
     "length": math.pi * 200.0 / 2.0},
]


def test_quarter_annulus_hand_check():
    # rectangle x in [1, 3] (x_bar = 2, A = 2), height 1, on a 90 deg
    # RIGHT turn R=200: Lt (+x) is the OUTSIDE, radius of a point at
    # offset x is R + x. Quarter-annulus volume, height h:
    #   V = h * (pi/4) * ((R+3)^2 - (R+1)^2)
    sec = [(1.0, 0.0), (3.0, 0.0), (3.0, 1.0), (1.0, 1.0)]
    al = Alignment(POB, ARC90_R200)
    arc0 = 10.0
    sw = SweptSection("q", sec, al, arc0, arc0 + math.pi * 200.0 / 2.0)
    want = 1.0 * (math.pi / 4.0) * ((200.0 + 3.0) ** 2 - (200.0 + 1.0) ** 2)
    assert sw.volume_cf == pytest.approx(want, rel=1e-12)
    assert sw.faceted_volume_cf == pytest.approx(want, rel=FACET_TOLERANCE)


def test_compound_curve_sums_per_arc_pieces():
    run = [
        {"kind": "tangent", "bearing": "N 0-0-0 E", "length": 50.0},
        {"kind": "curve", "delta": "30-0-0", "radius": 400.0, "turn": "L",
         "length": math.pi * 400.0 / 6.0},
        {"kind": "curve", "delta": "20-0-0", "radius": 150.0, "turn": "L",
         "length": math.pi * 150.0 / 9.0},
        {"kind": "tangent", "bearing": "N 50-0-0 W", "length": 40.0},
    ]
    al = Alignment(POB, run)
    sw = SweptSection("c", RECT, al, 0.0, al.s_end)
    # RECT has x_bar = 0, so every piece reduces to A * ds:
    assert sw.volume_cf == pytest.approx(4.0 * al.s_end)
    # offset the section: closed form picks up per-arc curvature
    sec = [(0.0, 0.0), (4.0, 0.0), (4.0, 1.0), (0.0, 1.0)]      # x_bar = 2
    sw2 = SweptSection("c2", sec, al, 0.0, al.s_end)
    l1, l2 = math.pi * 400.0 / 6.0, math.pi * 150.0 / 9.0
    # LEFT turns, x_bar = +2 is INSIDE: swept path shortens, (1 - kappa*x_bar)
    want = 4.0 * (50.0 + 40.0) \
        + 4.0 * l1 * (1.0 - (1.0 / 400.0) * 2.0) \
        + 4.0 * l2 * (1.0 - (1.0 / 150.0) * 2.0)
    assert sw2.volume_cf == pytest.approx(want, rel=1e-12)
    assert sw2.faceted_volume_cf == pytest.approx(want, rel=FACET_TOLERANCE)


def test_facet_band_on_arcs():
    al = Alignment(POB, ARC90_R200)
    sw = SweptSection("g", RECT, al, 0.0, al.s_end)
    err = abs(sw.faceted_volume_cf - sw.volume_cf) / sw.volume_cf
    assert err <= FACET_TOLERANCE
    # and the facet must be the UNDER-estimate (chords cut the arc)
    assert sw.faceted_volume_cf < sw.volume_cf


VC_SWEEP = {"bvc_station": 100.0, "bvc_elev": 50.0, "g_in_pct": 2.0,
            "g_out_pct": -1.0, "length_ft": 200.0,
            "evc_station": 300.0, "evc_elev": 51.0}


def test_vertical_curve_and_camber_are_volume_exact_shear():
    p = Profile([VC_SWEEP])
    al = Alignment(POB, [{"kind": "tangent", "bearing": "N 0-0-0 E",
                          "length": 400.0}])
    plain = SweptSection("p0", RECT, al, 0.0, 400.0)
    vced = SweptSection("p1", RECT, al, 0.0, 400.0, profile=p,
                        camber=[(0.0, 0.0), (200.0, 0.35), (400.0, 0.0)])
    assert vced.volume_cf == pytest.approx(plain.volume_cf)     # exactly
    assert vced.faceted_volume_cf == pytest.approx(plain.volume_cf, rel=1e-9)
    # and on an arc the shear STILL changes nothing (Pappus in plan)
    al2 = Alignment(POB, ARC90_R200)
    a0 = SweptSection("a0", RECT, al2, 0.0, al2.s_end)
    a1 = SweptSection("a1", RECT, al2, 0.0, al2.s_end, profile=p)
    assert a1.volume_cf == pytest.approx(a0.volume_cf)


def test_vc_densifies_stations():
    p = Profile([VC_SWEEP])
    al = Alignment(POB, [{"kind": "tangent", "bearing": "N 0-0-0 E",
                          "length": 400.0}])
    flat = SweptSection("f", RECT, al, 0.0, 400.0)
    vced = SweptSection("v", RECT, al, 0.0, 400.0, profile=p)
    assert len(vced._s) > len(flat._s)      # sagitta rule adds stations
    # the emitted crest actually bows: mid-run z sits above the chord of
    # the profile ends
    # bucket by NORTH (index 1) — this alignment runs due north, and the
    # model frame is x=east, y=north (see `to_model`).
    zs = {}
    for v in vced.body_solids()[0]["verts"]:
        zs.setdefault(round(v[1]), []).append(v[2])
    z0, z200, z400 = (max(zs[k]) for k in (0, 200, 400))
    assert z200 > (z0 + z400) / 2.0 + 0.5   # crest VC bows up (~0.75 ft)


def test_roll_on_straight_is_volume_noop():
    al = Alignment(POB, NORTH_100)
    r = SweptSection("r", RECT, al, 0.0, 100.0,
                     roll=[(0.0, 0.0), (100.0, 0.08)])
    assert r.volume_cf == pytest.approx(400.0)      # kappa=0 kills roll
    # The facet is NOT shear-exact under roll: rotation pinches each
    # lofted bay to exactly A*ds*(2 + cos dphi)/3 (mixed area of a ring
    # and its rotation is A*cos dphi), a second-order defect spec 3.4
    # budgets into the facet band via the roll-step rule -- no station
    # mesh can beat it.  Pin the facet to that closed form tightly
    # (proving no first-order twist bias survives) and to the band.
    n = len(r._s) - 1
    dphi = math.atan(0.08) / n
    want = 400.0 * (2.0 + math.cos(dphi)) / 3.0
    assert r.faceted_volume_cf == pytest.approx(want, rel=1e-9)
    assert abs(r.faceted_volume_cf - 400.0) / 400.0 <= FACET_TOLERANCE / 4.0


def test_roll_transition_integral_vs_fine_facet():
    sec = [(0.0, 0.0), (4.0, 0.0), (4.0, 1.0), (0.0, 1.0)]   # x_bar=2, z_bar=.5
    al = Alignment(POB, ARC90_R200)
    roll = [(10.0, 0.0), (al.s_end, 0.10)]
    sw = SweptSection("rt", sec, al, 10.0, al.s_end, roll=roll)
    closed = sw.volume_cf
    faceted = sw.faceted_volume_cf
    assert abs(faceted - closed) / closed <= FACET_TOLERANCE
    # quartering the facet step converges TOWARD the closed form
    import bimforge.author.sweep as sweep_mod
    coarse_err = abs(faceted - closed)
    old = sweep_mod.MAX_ARC_STEP_RAD
    try:
        sweep_mod.MAX_ARC_STEP_RAD = old / 4.0
        fine = SweptSection("rt2", sec, al, 10.0, al.s_end, roll=roll)
        assert fine.volume_cf == pytest.approx(closed)   # closed form is step-free
        assert abs(fine.faceted_volume_cf - closed) < coarse_err
    finally:
        sweep_mod.MAX_ARC_STEP_RAD = old


def test_roll_rotates_the_emitted_section():
    al = Alignment(POB, NORTH_100)
    r = SweptSection("rot", RECT, al, 0.0, 100.0,
                     roll=[(0.0, 0.10), (100.0, 0.10)])
    zs = [v[2] for v in r.body_solids()[0]["verts"]]
    # a 0.10 cross slope tips the 4-ft-wide rectangle: the (+2, 1) corner
    # rises to 2 sin(phi) + cos(phi)
    phi = math.atan(0.10)
    want_top = 2.0 * math.sin(phi) + 1.0 * math.cos(phi)
    assert max(zs) == pytest.approx(want_top, abs=1e-9)


def test_normal_mode_declares_face_volume_with_helix_cross_check():
    # constant 5% grade, constant curvature: helix closed form
    p = Profile([{"bvc_station": 0.0, "bvc_elev": 100.0, "g_in_pct": 5.0,
                  "g_out_pct": 5.0, "length_ft": 1.0,
                  "evc_station": 1.0, "evc_elev": 100.05}])
    al = Alignment(POB, ARC90_R200)
    sec = [(0.0, 0.0), (4.0, 0.0), (4.0, 1.0), (0.0, 1.0)]
    nm = SweptSection("n", sec, al, 10.0, al.s_end, profile=p,
                      frame="normal")
    assert nm._face_declared
    assert nm.volume_cf == pytest.approx(nm.faceted_volume_cf)  # declared-from-faces
    ds = al.s_end - 10.0
    k, xb = -1.0 / 200.0, 2.0
    helix = 4.0 * math.hypot(ds * (1.0 - k * xb), 0.05 * ds)
    assert nm.volume_cf == pytest.approx(helix, rel=0.005)      # MESH_TOLERANCE


def test_normal_vs_plumb_differ_by_grade_family_factor():
    p = Profile([{"bvc_station": 0.0, "bvc_elev": 0.0, "g_in_pct": 8.0,
                  "g_out_pct": 8.0, "length_ft": 1.0,
                  "evc_station": 1.0, "evc_elev": 0.08}])
    al = Alignment(POB, NORTH_100)
    pl = SweptSection("pl", RECT, al, 0.0, 100.0, profile=p)
    nm = SweptSection("nm", RECT, al, 0.0, 100.0, profile=p, frame="normal")
    gam = math.atan(0.08)
    # straight run, constant grade: consecutive pitched planes are PARALLEL,
    # the solid is an oblique prism along the slope - A * L / cos(gamma)
    # exactly, at the facet level too
    assert nm.volume_cf == pytest.approx(400.0 / math.cos(gam), rel=1e-6)
    assert pl.volume_cf == pytest.approx(400.0)


def test_skew_on_arc_switches_to_face_declared():
    al = Alignment(POB, ARC90_R200)
    sw = SweptSection("sa", RECT, al, 20.0, al.s_end, end_skew=(20.0, 0.0))
    assert sw._face_declared
    assert sw.volume_cf == pytest.approx(sw.faceted_volume_cf)
    st = SweptSection("st", RECT, al, 0.0, 10.0, end_skew=(20.0, 0.0))
    assert not st._face_declared       # both ends on the entry tangent
    # and the tangent-end case still carries the end-plane closed form
    assert st.volume_cf == pytest.approx(4.0 * 10.0)   # RECT x_bar = 0


def test_normal_mode_without_profile_is_plumb_equivalent():
    al = Alignment(POB, NORTH_100)
    nm = SweptSection("n0", RECT, al, 0.0, 100.0, frame="normal")
    # no profile -> grade 0 -> pitch 0: still face-declared by mode, but
    # numerically identical to the plumb straight extrusion
    assert nm._face_declared
    assert nm.volume_cf == pytest.approx(400.0, rel=1e-9)


def test_ring_self_intersects_predicate():
    assert not ring_self_intersects(RECT)
    assert not ring_self_intersects(list(reversed(RECT)))
    assert ring_self_intersects([(0.0, 0.0), (3.0, 3.0), (3.0, 0.0),
                                 (0.0, 1.0)])
    # a concave but SIMPLE L-section is not self-intersecting
    ell = [(0.0, 0.0), (4.0, 0.0), (4.0, 1.0), (1.0, 1.0), (1.0, 3.0),
           (0.0, 3.0)]
    assert not ring_self_intersects(ell)


def test_bowtie_section_refused_at_construction():
    # The lobes' areas partially CANCEL in poly_area AND ear_clip's
    # triangle sum reproduces that same net, so declared and faceted agree
    # on the fiction - the gate's cf pair cannot see it and refuse-early
    # is the only defense (Task-8 probe).
    bowtie = [(0.0, 0.0), (3.0, 3.0), (3.0, 0.0), (0.0, 1.0)]
    al = Alignment(POB, NORTH_100)
    with pytest.raises(ValueError, match="self-intersects"):
        SweptSection("bt", bowtie, al, 0.0, 100.0)


def test_bowtie_void_refused_at_construction():
    outer = [(-4.0, 0.0), (4.0, 0.0), (4.0, 4.0), (-4.0, 4.0)]
    bad_void = [(-1.0, 1.0), (1.0, 3.0), (1.0, 1.0), (-1.0, 3.0)]
    al = Alignment(POB, NORTH_100)
    with pytest.raises(ValueError, match="void ring self-intersects"):
        SweptSection("bv", outer, al, 0.0, 100.0, voids=[bad_void])


def test_parallel_skew_accepted_on_a_short_run():
    # Copilot PR-141: end planes close at the RELATIVE shear, so equal
    # skews stay parallel and never cross - a 2 ft run the old summed
    # reach (4.76 ft) wrongly refused is valid geometry.
    sec = [(0.0, 0.0), (4.0, 0.0), (4.0, 1.0), (0.0, 1.0)]      # maxr 4.123
    al = Alignment(POB, NORTH_100)
    par = SweptSection("shortpar", sec, al, 0.0, 2.0, end_skew=(30.0, 30.0))
    assert par.volume_cf == pytest.approx(4.0 * 2.0)            # parallelogram
    assert par.faceted_volume_cf == pytest.approx(8.0, rel=1e-9)
    # opposed ends over the same run still refuse (they close twice as fast)
    with pytest.raises(ValueError, match="cross"):
        SweptSection("shortopp", sec, al, 0.0, 2.0, end_skew=(-30.0, 30.0))


# ---------------------------------------------------------------------------
# Model frame (issue #156). The sweep engine used to emit raw
# (northing, easting, absolute elevation) tuples straight into vertices. Two
# defects in one, and the POB={0,0} fixture above hides both:
#
#   * ABSOLUTE, not local — geometry landed millions of feet from the origin,
#     where a viewer's default view never frames it (the #134 lesson, ~2700x
#     over). Volume gates cannot see it: volume is translation-invariant.
#   * TRANSPOSED — the house frame is x=EAST, y=NORTH, fixed by
#     `ProjectContext.local(e, n, z)` and by `kml.lonlat`'s
#     `base_e + x*Scale` / `base_n + y*Scale`. Emitting (n, e) put the model
#     at the wrong azimuth: an alignment declared N 10-00-00 E rendered at
#     80 deg, mirrored about the 45 deg diagonal.
#
# Every world -> model conversion now funnels through `ctx.local`.
# ---------------------------------------------------------------------------
import uuid  # noqa: E402

from bimforge.author.project import ProjectContext  # noqa: E402

EAST_100 = [{"kind": "tangent", "bearing": "N 90-0-0 E", "length": 100.0}]


def _ctx(base_e=0.0, base_n=0.0, base_h=0.0):
    return ProjectContext(name="frame", epsg=2226, base_e=base_e,
                          base_n=base_n, base_h=base_h,
                          guid_ns=uuid.UUID(int=42))


def _plan_extent(sw):
    """(x span, y span) of the emitted solid, model frame."""
    verts = sw.body_solids()[0]["verts"]
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    return max(xs) - min(xs), max(ys) - min(ys)


def test_due_north_alignment_runs_along_model_y():
    """North is +y. The section is only 4 ft wide, so a 100 ft due-north run
    must span ~100 ft in y and ~4 ft in x — not the other way round."""
    sw = SweptSection("n", RECT, Alignment(POB, NORTH_100), 0.0, 100.0,
                      origin=_ctx())
    dx, dy = _plan_extent(sw)
    assert dy == pytest.approx(100.0, abs=0.01)
    assert dx == pytest.approx(4.0, abs=0.01)


def test_due_east_alignment_runs_along_model_x():
    """The other half of the convention, so neither axis can be assumed."""
    sw = SweptSection("e", RECT, Alignment(POB, EAST_100), 0.0, 100.0,
                      origin=_ctx())
    dx, dy = _plan_extent(sw)
    assert dx == pytest.approx(100.0, abs=0.01)
    assert dy == pytest.approx(4.0, abs=0.01)


def test_geometry_is_local_to_the_project_base():
    """A structure surveyed at State Plane coordinates emits near the ORIGIN;
    the base lives in IfcMapConversion, not in every vertex."""
    base_e, base_n, base_h = 6_594_000.0, 1_943_000.0, 300.0
    pob = {"station": 0.0, "northing": base_n, "easting": base_e}
    al = Alignment(pob, NORTH_100)
    prof = Profile([{"bvc_station": 0.0, "bvc_elev": base_h + 20.0,
                     "g_in_pct": 0.0, "g_out_pct": 0.0, "length_ft": 200.0,
                     "evc_station": 200.0, "evc_elev": base_h + 20.0}])
    sw = SweptSection("l", RECT, al, 0.0, 100.0, profile=prof,
                      origin=_ctx(base_e, base_n, base_h))
    for v in sw.body_solids()[0]["verts"]:
        assert abs(v[0]) < 500.0, f"x={v[0]} is not local to the project base"
        assert abs(v[1]) < 500.0, f"y={v[1]} is not local to the project base"
        assert abs(v[2]) < 500.0, f"z={v[2]} is not local to the project base"


def test_local_frame_does_not_move_the_declared_volume():
    """Translating the frame must not change any declared quantity — if it
    does, the fix broke the closed form rather than relocating the solid."""
    world = SweptSection("w", RECT, Alignment(
        {"station": 0.0, "northing": 1_943_000.0, "easting": 6_594_000.0},
        NORTH_100), 0.0, 100.0, origin=_ctx(6_594_000.0, 1_943_000.0))
    local = SweptSection("l", RECT, Alignment(POB, NORTH_100), 0.0, 100.0,
                         origin=_ctx())
    assert world.volume_cf == pytest.approx(local.volume_cf)
    assert world.faceted_volume_cf == pytest.approx(local.faceted_volume_cf)
