"""StationLoft and the corridor frame (P.6)."""
import math

import pytest

from bimforge.author.alignment import Alignment, Profile
from bimforge.author.corridor.frame import densify, survey_point
from bimforge.author.corridor.loft import StationLoft, pappus
from bimforge.author.primitives import exact_of
from bimforge.author.sweep import MAX_ARC_STEP_RAD

POB = {"station": 0.0, "northing": 0.0, "easting": 0.0}
RECT = [(5.0, 0.0), (-5.0, 0.0), (-5.0, -1.0), (5.0, -1.0)]


def line(length=100.0):
    return Alignment(POB, [{"kind": "tangent", "bearing": "N 0-0-0 E",
                            "length": length}], name="T")


def curve():
    """10 ft tangent, a 100 ft right curve of radius 500, 10 ft tangent."""
    return Alignment(POB, [
        {"kind": "tangent", "bearing": "N 0-0-0 E", "length": 10.0},
        {"kind": "curve", "delta": "11-27-33", "radius": 500.0, "turn": "R",
         "length": 100.0},
        {"kind": "tangent", "bearing": "N 11-27-33 E", "length": 10.0}], name="C")


def level(elev=100.0, length=120.0, grade_pct=0.0):
    return Profile([{"bvc_station": 0.0, "bvc_elev": elev, "g_in_pct": grade_pct,
                     "g_out_pct": grade_pct, "length_ft": length,
                     "evc_station": length,
                     "evc_elev": elev + grade_pct / 100.0 * length}])


def test_a_section_point_sits_left_and_below_on_a_level_tangent():
    assert survey_point(line(), level(), 50.0, 5.0, -1.0) == pytest.approx(
        (50.0, -5.0, 99.0))


def test_densify_keeps_chords_on_the_curve():
    al = curve()
    got = densify(al, level(), [0.0, 10.0, 110.0, 120.0])
    steps = [b - a for a, b in zip(got, got[1:])]
    assert got[0] == 0.0 and got[-1] == 120.0
    assert max(steps[1:-1]) <= MAX_ARC_STEP_RAD * 500.0 + 1e-9
    assert len(got) > 4


def test_a_straight_loft_is_its_prism():
    lf = StationLoft("slab", line(), level(), None, [0.0, 50.0, 100.0], [RECT] * 3)
    assert lf.volume_cf == pytest.approx(1000.0, rel=1e-9)
    assert lf.average_end_area_cf == pytest.approx(1000.0, rel=1e-9)
    assert lf.mean_width_ft == pytest.approx(10.0)
    assert lf.length_ft == 100.0


def test_a_curved_loft_agrees_with_its_curvature_corrected_end_areas():
    al, prof = curve(), level()
    ring = [(12.0, 0.0), (2.0, 0.0), (2.0, -1.0), (12.0, -1.0)]   # left of the line
    ss = densify(al, prof, [0.0, 10.0, 110.0, 120.0])
    lf = StationLoft("outer", al, prof, None, ss, [ring] * len(ss))
    assert lf.volume_cf > 1210.0            # the outside of a right curve is longer
    assert lf.volume_cf == pytest.approx(lf.average_end_area_cf, rel=1e-3)


def test_grade_lengthens_the_loft():
    lf = StationLoft("slab", line(), level(grade_pct=6.0), None, [0.0, 100.0], [RECT] * 2)
    assert lf.average_end_area_cf == pytest.approx(1000.0 * (1 + 0.06 ** 2) ** 0.5)
    assert lf.volume_cf == pytest.approx(lf.average_end_area_cf, rel=1e-6)


def test_its_exact_form_is_one_section_per_station():
    ss = [0.0, 50.0, 100.0]
    lf = StationLoft("slab", line(), level(), None, ss, [RECT] * 3, ifc="IfcCourse")
    d = lf.body_solids()[0]
    ex = exact_of(d)
    assert ex is not None and ex["kind"] == "sectioned"
    assert [sec["s"] for sec in ex["sections"]] == ss
    d["verts"][0] = (d["verts"][0][0] + 1.0,) + tuple(d["verts"][0][1:])
    assert exact_of(d) is None              # an edited mesh is written as itself


@pytest.mark.parametrize("stations, rings, match", [
    ([0.0], [RECT], "one ring per station"),
    ([0.0, 0.0], [RECT, RECT], "strictly ascending"),
    ([0.0, 10.0], [RECT, RECT[:3]], "same vertex count"),
    ([0.0, 10.0], [RECT, RECT[::-1]], "wind the same way"),
])
def test_bad_lofts_are_refused(stations, rings, match):
    with pytest.raises(ValueError, match=match):
        StationLoft("x", line(), level(), None, stations, rings)


# ---------------------------------------------------- the gate's interface
# gate._ifc_exact_sweep_check holds a drawn IfcSectionedSolidHorizontal to
# the loft it came from: these are the four legs it measures with.

def _ring(s, grow=0.0):
    """Left of the line, widening 0.02 ft per foot of station."""
    w = 12.0 + 0.02 * s
    return [(w + grow, 0.0), (2.0 - grow, 0.0), (2.0 - grow, -1.0),
            (w + grow, -1.0)]


def _lofts():
    al, prof = curve(), level()
    ss = densify(al, prof, [0.0, 10.0, 110.0, 120.0])
    return [StationLoft("slab", line(), level(), None, [0.0, 50.0, 100.0],
                        [RECT] * 3),
            StationLoft("outer", al, prof, None, ss, [_ring(s) for s in ss])]


def _ring_points(lf):
    """Every ring vertex at every station: the loft's mesh, less the fan
    centres, which sit a chord's sag inside the surface."""
    return [p for i in range(len(lf.stations)) for p in lf._world(i)]


@pytest.mark.parametrize("i", [0, 1])
def test_its_own_mesh_lies_on_its_surface_and_spans_its_stations(i):
    lf = _lofts()[i]
    res, lo, hi = lf.surface_residual_ft(_ring_points(lf))
    assert res == pytest.approx(0.0, abs=1e-6)
    assert lo == pytest.approx(lf.s0, abs=1e-6)
    assert hi == pytest.approx(lf.s1, abs=1e-6)


@pytest.mark.parametrize("i", [0, 1])
def test_a_mesh_pushed_out_strays_by_the_push(i):
    lf = _lofts()[i]
    grown = [[(u + (0.1 if u > 0 else -0.1), v) for u, v in r] for r in lf.rings]
    if i == 1:
        grown = [_ring(s, grow=0.1) for s in lf.stations]
    big = StationLoft("big", lf.alignment, lf.profile, None, lf.stations, grown)
    res, _lo, _hi = lf.surface_residual_ft(_ring_points(big))
    assert res == pytest.approx(0.1, abs=1e-6)


@pytest.mark.parametrize("i", [0, 1])
def test_its_own_caps_sit_in_their_end_sections(i):
    lf = _lofts()[i]
    d = lf.body_solids()[0]
    assert lf.cap_station_error_ft(d["verts"], d["tris"]) == pytest.approx(
        0.0, abs=1e-6)


def test_a_leaned_end_cap_is_seen():
    lf = _lofts()[0]
    d = lf.body_solids()[0]
    # shear the far cap along travel (+y, north) by 0.04 ft per foot left
    verts = [(x, y + 0.04 * -x, z) if abs(y - lf.s1) < 1e-9 else (x, y, z)
             for x, y, z in d["verts"]]
    assert lf.cap_station_error_ft(verts, d["tris"]) == pytest.approx(0.2,
                                                                      abs=1e-6)


@pytest.mark.parametrize("i", [0, 1])
def test_its_wall_area_is_its_own_and_a_missing_wall_shows(i):
    lf = _lofts()[i]
    d = lf.body_solids()[0]
    want = lf.wall_area_sf(d["verts"], d["tris"])
    assert want > 0.0
    assert lf.wall_area_sf(d["verts"], d["tris"]) == want
    # drop the top surface (v = 0, at elevation 100)
    tris = [t for t in d["tris"]
            if not all(abs(d["verts"][j][2] - 100.0) < 1e-9 for j in t)]
    assert lf.wall_area_sf(d["verts"], tris) < 0.9 * want


def test_a_drawn_loft_passes_the_exact_sweep_check(tmp_path):
    pytest.importorskip("ifcopenshell")
    import uuid

    from bimforge.author import gate
    from bimforge.author.emit_ifc import emit_ifc
    from bimforge.author.model import Element, StructureModel
    from bimforge.author.project import ProjectContext
    ctx = ProjectContext(name="Loft Fixture", schema="IFC4X3_ADD2", epsg=2226,
                         base_e=0.0, base_n=0.0, base_h=0.0,
                         guid_ns=uuid.UUID(int=6004))
    al = curve()
    prof = Profile([{"bvc_station": 20.0, "bvc_elev": 100.0, "g_in_pct": 3.0,
                     "g_out_pct": -2.0, "length_ft": 80.0, "evc_station": 100.0,
                     "evc_elev": 100.0 + 2.4 - 0.05 / 160.0 * 80.0 ** 2}])
    ss = densify(al, prof, [0.0, 10.0, 20.0, 100.0, 110.0, 120.0])
    lf = StationLoft("course", al, prof, ctx, ss, [_ring(s) for s in ss],
                     ifc="IfcCourse")
    m = StructureModel("loft", ctx)
    m.add(Element.from_geometry("course", lf, ifc_class="IfcCourse",
                                quantities={"volume_cf": lf.volume_cf}))
    out = tmp_path / "loft.ifc"
    emit_ifc(m, str(out))
    assert gate._exact_sweep_names(out) == {"course"}
    assert gate._ifc_exact_sweep_check(m, out) == []


#: 10 degrees of a 500 ft curve: 500 x pi / 18 = 87.266463 ft
LS = 500.0 * math.pi / 18.0
SHOULDER = [(12.0, -0.24), (17.0, -0.49), (17.0, -0.89), (12.0, -0.64)]
LANE = [(0.0, 0.0), (12.0, -0.24), (12.0, -0.64), (0.0, -0.4), (-12.0, -0.64),
        (-12.0, -0.24)]


def arc():
    """10 ft tangent, 10 degrees of a 500 ft right curve, 10 ft tangent: the
    curve's length is its radius x delta exactly."""
    return Alignment(POB, [
        {"kind": "tangent", "bearing": "N 0-0-0 E", "length": 10.0},
        {"kind": "curve", "delta": "10-0-0", "radius": 500.0, "turn": "R",
         "length": LS},
        {"kind": "tangent", "bearing": "N 10-0-0 E", "length": 10.0}], name="A")


def _on_the_curve(ring):
    al, prof = arc(), level(grade_pct=2.0)
    ss = densify(al, prof, [10.0, 10.0 + LS])
    return StationLoft("c", al, prof, None, ss, [ring] * len(ss))


def test_a_shoulder_on_a_curve_at_2_percent_is_its_area_times_its_centroid_s_path():
    lf = _on_the_curve(SHOULDER)
    p = pappus([lf])
    # A = 5 x 0.4 = 2.0 sf; centroid (14.5, -0.565), left of a right curve
    # (kappa = -1/500). sqrt(1 + 0.02^2) = 1.00019998, cos = 0.99980006.
    # V = A x LS x (1.00019998 + 14.5 / 500 x 0.99980006)
    #   = 2.0 x 87.266463 x 1.02919418 = 179.628271 cf
    assert (p.offset_ft, p.height_ft) == pytest.approx((14.5, -0.565))
    assert lf.volume_cf == pytest.approx(179.628271, rel=1e-8)
    # the centroid's line is a helix: 87.266463 x 514.5 / 500 = 89.797190 ft
    # in plan, rising 0.02 x 87.266463 = 1.745329 ft:
    # sqrt(89.797190^2 + 1.745329^2) = 89.814150 ft
    assert p.path_ft == pytest.approx(89.814150, rel=1e-8)
    # PathLength x Width x Thickness = 89.814150 x 5 x 0.4 = 179.628300:
    # 1.6e-7 over the volume, inside the gate's 1e-6
    assert abs(p.path_ft * 5.0 * 0.4 - lf.volume_cf) <= 1e-6 * lf.volume_cf
    # the mesh, chorded over 3 bays of 3.33 degrees, is 5.6e-4 short:
    # inside 0.5%
    assert lf.faceted_volume_cf < lf.volume_cf
    assert lf.faceted_volume_cf == pytest.approx(lf.volume_cf, rel=5e-3)


def test_a_lane_across_the_crown_rides_the_profile_grade_line():
    lf = _on_the_curve(LANE)
    p = pappus([lf])
    # A = 24 x 0.4 = 9.6 sf, centroid (0, -0.32): on the centreline, so the
    # curve does not lengthen it: PathLength = 87.266463 x 1.00019998 =
    # 87.283914 ft; V = 9.6 x 87.283914 = 837.925576 cf
    assert (p.offset_ft, p.height_ft) == pytest.approx((0.0, -0.32), abs=1e-12)
    assert p.path_ft == pytest.approx(87.283914, rel=1e-8)
    assert lf.volume_cf == pytest.approx(837.925576, rel=1e-8)
    assert p.path_ft * 24.0 * 0.4 == pytest.approx(lf.volume_cf, rel=1e-9)


def test_an_element_s_bodies_both_sides_share_one_centroid():
    al, prof = arc(), level(grade_pct=2.0)
    ss = densify(al, prof, [10.0, 10.0 + LS])
    right = [(-u, v) for u, v in SHOULDER]
    lofts = [StationLoft(n, al, prof, None, ss, [r] * len(ss))
             for n, r in (("L", SHOULDER), ("R", right))]
    p = pappus(lofts)
    # left at +14.5 and right at -14.5, equal areas: the centroid on the line
    assert p.offset_ft == pytest.approx(0.0, abs=1e-12)
    assert p.volume_cf == pytest.approx(sum(lf.volume_cf for lf in lofts), rel=1e-12)
    assert [round(w, 9) for w in lofts[0].widths_ft] == [5.0] * len(ss)


def test_a_vertical_curve_s_grade_change_bends_the_section_planes():
    # a crest on a tangent: the section planes close in below the grade
    # line (gamma' < 0), so a slab under it holds less than its area times
    # the grade line's length; pappus integrates that, and a fine mesh of
    # the same solid agrees
    al = line(200.0)
    prof = Profile([{"bvc_station": 50.0, "bvc_elev": 100.0, "g_in_pct": 4.0,
                     "g_out_pct": -4.0, "length_ft": 100.0,
                     "evc_station": 150.0, "evc_elev": 100.0}])
    ss = [50.0 + i for i in range(101)]
    lf = StationLoft("slab", al, prof, None, ss, [RECT] * len(ss))
    along = sum(math.hypot(b - a, prof.elev(b) - prof.elev(a))
                for a, b in zip(ss, ss[1:]))
    assert lf.volume_cf < 10.0 * along
    assert lf.volume_cf == pytest.approx(lf.faceted_volume_cf, rel=1e-6)


def test_pappus_refuses_lofts_on_different_stations():
    a = StationLoft("a", line(), level(), None, [0.0, 50.0, 100.0], [RECT] * 3)
    b = StationLoft("b", line(), level(), None, [0.0, 100.0], [RECT] * 2)
    with pytest.raises(ValueError, match="a: pappus needs lofts on the same stations"):
        pappus([a, b])


def test_the_mean_width_is_weighted_by_station_length():
    # 10 ft wide over the first 90 ft, widening to 20 ft over the last 10:
    # (90 x 10 + 10 x 15) / 100 = 10.5 ft, not the stations' mean 13.33
    wide = [(10.0, 0.0), (-10.0, 0.0), (-10.0, -1.0), (10.0, -1.0)]
    lf = StationLoft("w", line(), level(), None, [0.0, 90.0, 100.0],
                     [RECT, RECT, wide])
    assert lf.widths_ft == pytest.approx([10.0, 10.0, 20.0])
    assert lf.mean_width_ft == pytest.approx(10.5)


from bimforge.author.corridor.loft import centroid_path  # noqa: E402


def _box(u0, v0, w=12.0, t=0.5):
    return [(u0 + w, v0), (u0, v0), (u0, v0 - t), (u0 + w, v0 - t)]


def test_a_rising_ring_s_centroid_climbs_on_its_own_grade():
    lf = StationLoft("r", line(), level(), None, [0.0, 50.0, 100.0],
                     [_box(20.0, 0.0), _box(20.0, 1.0), _box(20.0, 2.0)])
    got = centroid_path([lf])
    assert got.path_ft == pytest.approx(100.0 * math.sqrt(1.0004), rel=1e-9)
    assert got.volume_cf == pytest.approx(pappus([lf]).volume_cf, rel=1e-12)
    assert got.offset_ft == pytest.approx(26.0)


def test_a_drifting_ring_s_centroid_runs_long():
    lf = StationLoft("d", line(), level(), None, [0.0, 100.0],
                     [_box(20.0, 0.0), _box(28.5, 0.0)])
    assert centroid_path([lf]).path_ft == pytest.approx(
        100.0 * math.sqrt(1.0 + 0.085 ** 2), rel=1e-9)


def test_two_lofts_centroid_is_their_area_weighted_mean():
    # a 12 x 0.5 box at u 20 (6 sf, centroid (26, -0.25)) and a 4 x 1 at
    # u -10 (4 sf, centroid (-8, -0.5)) on a level tangent: offset
    # (6 x 26 - 4 x 8) / 10 = 12.4, height (-1.5 - 2) / 10 = -0.35
    ss = [0.0, 100.0]
    a = StationLoft("a", line(), level(), None, ss, [_box(20.0, 0.0)] * 2)
    b = StationLoft("b", line(), level(), None, ss,
                    [_box(-10.0, 0.0, w=4.0, t=1.0)] * 2)
    got = centroid_path([a, b])
    assert got.path_ft == pytest.approx(100.0, rel=1e-12)
    assert got.volume_cf == pytest.approx(1000.0, rel=1e-12)
    assert got.offset_ft == pytest.approx(12.4, rel=1e-12)
    assert got.height_ft == pytest.approx(-0.35, rel=1e-12)


def test_centroid_path_refuses_lofts_on_different_stations():
    a = StationLoft("a", line(), level(), None, [0.0, 100.0], [_box(20.0, 0.0)] * 2)
    b = StationLoft("b", line(), level(), None, [0.0, 50.0, 100.0],
                    [_box(20.0, 0.0)] * 3)
    with pytest.raises(ValueError, match=r"a: centroid_path needs lofts on the "
                                         r"same stations"):
        centroid_path([a, b])


@pytest.mark.parametrize("h", [0.0, -0.01])
def test_centroid_path_refuses_a_chord_that_is_not_positive(h):
    lf = StationLoft("r", line(), level(), None, [0.0, 100.0], [_box(20.0, 0.0)] * 2)
    with pytest.raises(ValueError, match=r"r: centroid_path's chord h must be "
                                         r"positive"):
        centroid_path([lf], h=h)


FLAT = [(1.0, 0.0), (0.0, 0.0), (0.5, 0.0)]      # no area


def test_a_loft_with_no_area_is_refused_by_name_and_stations():
    lf = StationLoft("z", line(), level(), None, [0.0, 100.0], [FLAT, FLAT])
    for f in (pappus, centroid_path):
        with pytest.raises(ValueError, match=r"z: no area from 0\+00\.00 to "
                                             r"1\+00\.00"):
            f([lf])


def test_a_band_with_next_to_no_area_is_refused_by_its_stations():
    sliver = [(12.0, 0.0), (0.0, 0.0), (0.0, -1e-14), (12.0, -1e-14)]
    lf = StationLoft("z", line(), level(), None, [0.0, 50.0, 100.0],
                     [_box(20.0, 0.0), sliver, sliver])
    with pytest.raises(ValueError, match=r"z: no area from 0\+50\.00 to "
                                         r"1\+00\.00"):
        centroid_path([lf])


def _true_arc():
    """10 ft tangent, a 100 ft right curve of radius 500 stationed at its
    arc (0.2 rad), 10 ft tangent."""
    return Alignment(POB, [
        {"kind": "tangent", "bearing": "N 0-0-0 E", "length": 10.0},
        {"kind": "curve", "delta": "11-27-32.961249419", "radius": 500.0,
         "turn": "R", "length": 100.0},
        {"kind": "tangent", "bearing": "N 11-27-32.961249419 E", "length": 10.0}],
        name="A")


@pytest.mark.parametrize("stations, h", [([10.0, 11.0, 60.0, 110.0], 0.05),
                                         ([10.0, 10.01, 60.0, 110.0], 0.01)])
def test_a_short_bay_at_the_pc_keeps_its_chord_inside(stations, h):
    # the chord is held to 0.04 of the bay (0.04 and 0.0004 ft here), so it
    # does not reach back over the PC onto the tangent: the centroid 26 ft
    # outside a 500 ft right curve runs 100 x 526 / 500 = 105.2 ft. The
    # chord's own error is O(h^2), (h / 526)^2 / 6 = 1.5e-9 at h = 0.05;
    # unclamped, the chords over the PC miss by 1.8e-6 and 1.2e-6
    lf = StationLoft("p", _true_arc(), level(), None, stations,
                     [_box(20.0, 0.0)] * len(stations))
    assert centroid_path([lf], h=h).path_ft == pytest.approx(105.2, rel=1e-8)
