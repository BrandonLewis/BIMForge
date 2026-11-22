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
    # symmetric about the centreline, so cut and fill cancel
    assert net == pytest.approx(100.0 * signed_area(a, ground), abs=1e-6)
    assert_closed(cut + fill)


def test_an_asymmetric_side_hill_splits_cut_from_fill_where_ground_crosses_grade():
    # depth = -1 - 0.2u under the road: grade crossed at u -5. Left fill is 3
    # ft at the hinge and daylights 10 ft out (1/2 down less 0.2 down per
    # ft): 1/2 x 15 x 3 + 1/2 x 10 x 3 = 37.5 sf. Right cut is 1 ft at the
    # hinge, daylight 3.33 ft out (1/2 up less 0.2 up): 1/2 x 5 x 1 + 1/2 x
    # 10/3 x 1 = 4.1667 sf
    ground = PlaneGround(98.0, slope_e=0.2)
    a, b = sections(ground)
    assert a.sides["L"].line[-1][0] == pytest.approx(20.0)
    assert a.sides["R"].line[-1][0] == pytest.approx(-40.0 / 3.0)
    cut, fill, cut_depth, fill_depth = earthwork.strip("t", a, b, survey,
                                                       ground.z, None)
    assert sum(p.volume_cf for p in cut) == pytest.approx(1250.0 / 3.0, rel=1e-6)
    assert sum(p.volume_cf for p in fill) == pytest.approx(3750.0, rel=1e-6)
    assert cut_depth == pytest.approx(1.0)
    assert fill_depth == pytest.approx(3.0)
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


class Bump:
    """Level ground at 95 with a 1 ft tent between the right lane's edges,
    peaking at e 5 (u -5): zero at e 0 and e 10."""

    def z(self, n, e):
        return 95.0 + max(0.0, 1.0 - abs(e - 5.0) / 5.0)


def test_dividing_the_subgrade_changes_nothing_on_a_plane():
    ground = PlaneGround(98.0, slope_e=0.2)
    a, b = sections(ground)
    whole = earthwork.strip("t", a, b, survey, ground.z, None)
    split = earthwork.strip("t", a, b, survey, ground.z, None, per_component=3)
    for k in (0, 1):
        assert (sum(p.volume_cf for p in split[k])
                == pytest.approx(sum(p.volume_cf for p in whole[k]), rel=1e-9))
    assert len(split[0]) + len(split[1]) > len(whole[0]) + len(whole[1])


def test_dividing_the_subgrade_reads_relief_between_component_edges():
    # undivided, the ground is read at u 0 and -10 only, both 95: 11,200 cf.
    # In two, it is read at the tent's peak too (96, 3 ft of fill), and the
    # fill under the right lane loses 1/2 x 10 x 1 = 5 sf: 10,700 cf
    ground = Bump()
    a, b = sections(ground)
    whole = earthwork.strip("t", a, b, survey, ground.z, None)
    split = earthwork.strip("t", a, b, survey, ground.z, None, per_component=2)
    assert sum(p.volume_cf for p in whole[1]) == pytest.approx(11200.0, rel=1e-9)
    assert sum(p.volume_cf for p in split[1]) == pytest.approx(10700.0, rel=1e-9)
    assert split[0] == []
    assert_closed(split[1])


def test_sections_with_different_counts_are_refused():
    ground = PlaneGround(95.0)
    a, b = sections(ground)
    for side in ("L", "R"):                     # one more component at b
        b.subgrade[side].append(b.subgrade[side][-1])
    with pytest.raises(ValueError, match="point counts"):
        earthwork.strip("t", a, b, survey, ground.z, None)


def _rotations(loop):
    return {tuple(loop[k:] + loop[:k]) for k in range(len(loop))}


@pytest.mark.parametrize("faces", [
    [[0, 1, 2], [2, 1, 0], [0, 1, 2]],
    [[0, 1, 2], [0, 1, 2], [2, 1, 0]],
    # same corners, a third face neither the first nor its reverse
    [[0, 1, 2, 3], [3, 2, 1, 0], [0, 2, 1, 3]],
])
def test_a_shared_face_is_dropped_in_pairs_whatever_else_coincides(faces):
    from bimforge.author.corridor.earthwork import _shared_faces
    dropped = _shared_faces(faces)
    assert len(dropped) == 2
    a, b = sorted(dropped)
    assert tuple(faces[a]) in _rotations(faces[b][::-1])


def test_bases_meeting_at_a_point_have_two_outlines():
    from bimforge.author.corridor.earthwork import _plan_loops
    # two CCW triangles touching only at point 2, and a square of two
    # triangles sharing a diagonal
    loops = _plan_loops([[0, 1, 2], [2, 3, 4], [5, 6, 7], [5, 7, 8]])
    got = sorted(loops, key=min)
    assert len(got) == 3
    assert tuple(got[0]) in _rotations([0, 1, 2])
    assert tuple(got[1]) in _rotations([2, 3, 4])
    assert tuple(got[2]) in _rotations([5, 6, 7, 8])


ROCK = parse({"section": {**SECTION, "side_slopes": {
    "cut": {"ratio": 2.0, "ditch": {"width": 4.0, "depth": 1.5},
            "rock": {"depth_ft": 8.0, "ratio": 0.5, "bench_ft": 6.0}},
    "fill": {"ratio": 2.0}}}}, 0.0, 100.0)


def assert_one_closed_body(columns):
    """`columns` merge into one closed mesh, each edge shared by exactly
    two triangles, holding the columns' volume."""
    bodies = earthwork.merge("t", "cut", columns)
    assert len(bodies) == 1
    tris = bodies[0].tris
    edges = Counter(frozenset(e) for a, b, c in tris
                    for e in ((a, b), (b, c), (c, a)))
    assert set(edges.values()) == {2}
    assert bodies[0].volume_cf == pytest.approx(
        sum(p.volume_cf for p in columns), rel=1e-9)


def test_a_rock_cut_with_its_bench_merges_into_one_closed_body():
    # ground at 115, 15 ft over the PGL; hinge (10, -1), ditch (13, -2.5) to
    # (17, -2.5), rock at v = 7: the face rises 9.5 ft in 4.75 ft to
    # (21.75, 7), the bench to (27.75, 7), the soil 8 ft in 16 to (43.75, 15).
    # Depths under the ground, each side: 10 x 16 + 3 x 16.75 + 4 x 17.5
    # + 4.75 x 12.75 + 6 x 8 + 16 x 4 = 452.8125 sf; both sides over
    # 100 ft: 90,562.5 cf
    ground = PlaneGround(115.0)
    a, b = sections(ground, ROCK)
    assert a.sides["L"].line[4] == pytest.approx((27.75, 7.0))
    cut, fill, _cd, _fd = earthwork.strip("t", a, b, survey, ground.z, None)
    assert fill == []
    assert sum(p.volume_cf for p in cut) == pytest.approx(90562.5, rel=1e-9)
    assert_closed(cut)
    assert_one_closed_body(cut)


def test_a_bench_appearing_between_stations_merges_into_one_closed_body():
    # ground 105 at 0+00, rising 1 in 10 to 115 at 1+00: the ditch's edge
    # (v -2.5) is 7.5 ft under the ground at 0+00, inside the 8 ft of soil,
    # so the bench is collapsed onto it; at 1+00 it is 17.5 ft under, and
    # the face and bench stand as above
    ground = PlaneGround(105.0, slope_n=0.1)
    a, b = sections(ground, ROCK)
    assert a.sides["L"].line[3] == a.sides["L"].line[4] == pytest.approx((17.0, -2.5))
    assert b.sides["L"].line[4] == pytest.approx((27.75, 7.0))
    cut, fill, _cd, _fd = earthwork.strip("t", a, b, survey, ground.z, None)
    assert fill == []
    assert_closed(cut)
    assert_one_closed_body(cut)
