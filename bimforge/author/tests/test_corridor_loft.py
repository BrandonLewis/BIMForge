"""StationLoft and the corridor frame (P.6)."""
import pytest

from bimforge.author.alignment import Alignment, Profile
from bimforge.author.corridor.frame import densify, survey_point
from bimforge.author.corridor.loft import StationLoft
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
