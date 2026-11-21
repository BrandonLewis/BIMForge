"""road-corridor earthwork: prismatoids between two sections (P.6)."""
from collections import Counter

import pytest

from bimforge.author.alignment import Alignment, Profile
from bimforge.author.corridor import earthwork
from bimforge.author.corridor.frame import survey_point
from bimforge.author.corridor.ground import PlaneGround
from bimforge.author.corridor.params import parse
from bimforge.author.corridor.section import resolve

AL = Alignment({"station": 0.0, "northing": 0.0, "easting": 0.0},
               [{"kind": "tangent", "bearing": "N 0-0-0 E", "length": 100.0}], name="T")
PROF = Profile([{"bvc_station": 0.0, "bvc_elev": 100.0, "g_in_pct": 0.0,
                 "g_out_pct": 0.0, "length_ft": 100.0, "evc_station": 100.0,
                 "evc_elev": 100.0}])
SECTION = {
    "components": [{"name": "lane", "kind": "carriageway", "width": 10.0, "slope": 0.0}],
    "courses": [{"name": "AB", "type": "CORE", "thickness": 1.0}],
    "side_slopes": {"cut": {"ratio": 2.0}, "fill": {"ratio": 2.0}}}
C = parse({"section": SECTION}, 0.0, 100.0)


def survey(s, u, v):
    return survey_point(AL, PROF, s, u, v)


def sections(ground, c=C):
    def dz(s, u, v):
        n, e, z = survey(s, u, v)
        return ground.z(n, e) - z
    return resolve(c, 0.0, dz), resolve(c, 100.0, dz)


def signed_area(sec, ground):
    """The section's cut less fill area, trapezoids along its earthwork line."""
    d = []
    for u, v in sec.earthwork_line():
        n, e, z = survey(sec.s, u, v)
        d.append((u, ground.z(n, e) - z))
    return sum(0.5 * (d0 + d1) * abs(u0 - u1) for (u0, d0), (u1, d1) in zip(d, d[1:]))


def assert_closed(solids):
    """Every solid has plan area and depth, and its mesh is closed: each
    edge is shared by exactly two triangles."""
    for p in solids:
        assert p.area_sf > 0.0 and p.volume_cf > 0.0, p.name
        mesh = p.body_solids()[0]
        edges = Counter(frozenset(e) for a, b, c in mesh["tris"]
                        for e in ((a, b), (b, c), (c, a)))
        assert all(len(e) == 2 for e in edges), p.name
        assert set(edges.values()) == {2}, p.name


def test_fill_on_level_ground_is_the_prism_formula():
    ground = PlaneGround(95.0)
    cut, fill, cut_depth, fill_depth = earthwork.strip("t", *sections(ground),
                                                       survey, ground.z, None)
    assert cut == []
    assert sum(p.volume_cf for p in fill) == pytest.approx(11200.0, rel=1e-9)
    assert fill_depth == pytest.approx(4.0)
    assert cut_depth == 0.0
    assert all(p.ifc == "IfcEarthworksFill" for p in fill)
    assert_closed(fill)


def test_cut_less_fill_is_the_signed_section_area_on_a_side_hill():
    ground = PlaneGround(99.0, slope_e=0.2)     # rises to the east, the right side
    a, b = sections(ground)
    cut, fill, _cd, _fd = earthwork.strip("t", a, b, survey, ground.z, None)
    assert cut and fill
    assert all(p.ifc == "IfcEarthworksCut" for p in cut)
    net = sum(p.volume_cf for p in cut) - sum(p.volume_cf for p in fill)
    assert net == pytest.approx(100.0 * signed_area(a, ground), rel=1e-9)
    assert_closed(cut + fill)


def test_a_hinge_on_the_ground_repeats_points_and_leaves_no_degenerate_solid():
    # the left hinge (u 10, subgrade 99) sits on the ground, so the left
    # side's daylight is the hinge and its samples all repeat it
    ground = PlaneGround(99.0, e0=-10.0, slope_e=0.2)
    a, b = sections(ground)
    line = a.earthwork_line()
    assert len(set(line)) < len(line)
    cut, fill, cut_depth, _fd = earthwork.strip("t", a, b, survey, ground.z, None)
    assert cut and cut_depth > 0.0
    net = sum(p.volume_cf for p in cut) - sum(p.volume_cf for p in fill)
    assert net == pytest.approx(100.0 * signed_area(a, ground), rel=1e-9)
    assert_closed(cut + fill)


def test_a_wall_side_closes_on_a_vertical_face_at_its_offset():
    # left wall 15 ft out: the fill runs level at subgrade to the wall, 4 ft
    # deep, so the section is 15 x 4 + 10 x 4 + 1/2 x 8 x 4 = 116 sf
    c = parse({"section": SECTION, "gaps": [
        {"from": 0, "to": 100, "kind": "wall", "side": "L", "offset": 15.0}]},
        0.0, 100.0)
    ground = PlaneGround(95.0)
    cut, fill, _cd, _fd = earthwork.strip("t", *sections(ground, c), survey,
                                          ground.z, None)
    assert cut == []
    assert sum(p.volume_cf for p in fill) == pytest.approx(11600.0, rel=1e-9)
    assert_closed(fill)
    # the left (west) edge is a vertical face at x = -15, from 95 up to 99
    west = [q for p in fill for q in p.bottom + p.top if q[0] == pytest.approx(-15.0)]
    assert {round(q[2], 9) for q in west} == {95.0, 99.0}
    assert min(q[0] for p in fill for q in p.bottom + p.top) == pytest.approx(-15.0)


def test_a_wall_at_the_hinge_offset_adds_nothing_past_the_hinge():
    c = parse({"section": SECTION, "gaps": [
        {"from": 0, "to": 100, "kind": "wall", "side": "L", "offset": 10.0}]},
        0.0, 100.0)
    ground = PlaneGround(95.0)
    _cut, fill, _cd, _fd = earthwork.strip("t", *sections(ground, c), survey,
                                           ground.z, None)
    assert sum(p.volume_cf for p in fill) == pytest.approx(100.0 * (80.0 + 16.0),
                                                           rel=1e-9)
    assert_closed(fill)


def test_sections_with_different_counts_are_refused():
    ground = PlaneGround(95.0)
    a, b = sections(ground)
    b.subgrade["R"].append(b.subgrade["R"][-1])
    with pytest.raises(ValueError, match="point counts"):
        earthwork.strip("t", a, b, survey, ground.z, None)
