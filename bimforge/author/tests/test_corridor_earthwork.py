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


def flat(points):
    return [c for p in points for c in p]


#: ROCK whose faces bench every 10 ft of height, 4 ft wide (up to the
#: default 4), a face taller than 10 ft taking a 6 ft wide, 3 ft deep ditch
TALL_ROCK = parse({"section": {**SECTION, "side_slopes": {
    "cut": {"ratio": 2.0, "ditch": {"width": 4.0, "depth": 1.5},
            "rock": {"depth_ft": 8.0, "ratio": 0.5, "bench_ft": 6.0,
                     "face_bench": {"every_ft": 10.0, "width_ft": 4.0},
                     "catchment": {"width_ft": 6.0, "depth_ft": 3.0}}},
    "fill": {"ratio": 2.0}}}}, 0.0, 100.0)


def test_a_benched_rock_cut_merges_into_one_closed_body():
    # ground at 135, 35 ft over the PGL; rock at v = 27. With the ditch the
    # face would rise 29.5 ft from (17, -2.5), over 10 ft, so the ditch is
    # the catchment's: (10, -1) down 3 ft at 2:1 to (16, -4), 6 ft across to
    # (22, -4). The face rises 31 ft: benches at v = 6, 16 and 26, (27, 6)
    # to (31, 6), (36, 16) to (40, 16), (45, 26) to (49, 26), then 1 ft to
    # (49.5, 27); the soil bench to (55.5, 27) and the soil 8 ft in 16 to
    # (71.5, 35). Depths under the ground, each side: 10 x 36 + 6 x 37.5
    # + 6 x 39 + 5 x 34 + 4 x 29 + 5 x 24 + 4 x 19 + 5 x 14 + 4 x 9
    # + 0.5 x 8.5 + 6 x 8 + 16 x 4 = 1523.25 sf; both sides over 100 ft:
    # 304,650 cf
    ground = PlaneGround(135.0)
    a, b = sections(ground, TALL_ROCK)
    assert flat(a.sides["L"].line[2:12]) == pytest.approx(flat(
        [(22.0, -4.0), (27.0, 6.0), (31.0, 6.0), (36.0, 16.0), (40.0, 16.0),
         (45.0, 26.0), (49.0, 26.0), (49.5, 27.0), (49.5, 27.0), (49.5, 27.0)]))
    cut, fill, _cd, _fd = earthwork.strip("t", a, b, survey, ground.z, None)
    assert fill == []
    assert sum(p.volume_cf for p in cut) == pytest.approx(304650.0, rel=1e-9)
    assert_closed(cut)
    assert_one_closed_body(cut)


@pytest.mark.parametrize("at_0", [
    # 0+00 at 115: the 9.5 ft face from the ditch's edge (17, -2.5) takes no
    # bench and no catchment; its four benches collapse onto its top
    115.0,
    # 0+00 at 105: the ditch's edge is 7.5 ft under, in soil; the face, its
    # benches and the soil bench collapse onto the toe
    105.0,
])
def test_benches_appearing_between_stations_merge_into_one_closed_body(at_0):
    # rising to 135 at 1+00: three benches and the catchment, as above
    ground = PlaneGround(at_0, slope_n=(135.0 - at_0) / 100.0)
    a, b = sections(ground, TALL_ROCK)
    top = (21.75, 7.0) if at_0 == 115.0 else (17.0, -2.5)
    assert flat(a.sides["L"].line[3:12]) == pytest.approx(flat([top] * 9))
    assert b.sides["L"].line[3] == pytest.approx((27.0, 6.0))
    assert len(a.earthwork_line()) == len(b.earthwork_line())
    cut, fill, _cd, _fd = earthwork.strip("t", a, b, survey, ground.z, None)
    assert fill == []
    assert_closed(cut)
    assert_one_closed_body(cut)


def test_a_listed_wall_turning_into_a_guarded_fill_merges_into_one_closed_body():
    # a listed left wall to 0+50, 30 ft out; past it, ground 15 ft under
    # the PGL, 14 ft of fill at the hinge (10, -1): over 10 ft, so 2:1
    # behind the widening. The wall's line keeps the widening's two points,
    # collapsed on the hinge, so its level run lofts to the guarded slope
    # and not up onto the widening
    import copy
    sec = copy.deepcopy(SECTION)
    sec["side_slopes"]["fill"] = {"ratio": 4.0,
                                  "steep": {"ratio": 2.0, "above_height_ft": 10.0}}
    c = parse({"section": sec, "gaps": [{"from": 0, "to": 50, "kind": "wall",
                                         "side": "L", "offset": 30.0}]}, 0.0, 100.0)
    ground = PlaneGround(85.0)

    def dz(s, u, v):
        n, e, z = survey(s, u, v)
        return ground.z(n, e) - z

    a, b = resolve(c, 50.0, dz), resolve(c, 51.0, dz)
    assert a.sides["L"].line == [(10.0, -1.0)] * 3 + [(30.0, -1.0)]
    assert b.sides["L"].guarded
    _cut, fill, _cd, _fd = earthwork.strip("t", a, b, survey, ground.z, None)
    bodies = earthwork.merge("t", "fill", fill)
    assert len(bodies) == 1
    edges = Counter(frozenset(e) for x, y, z in bodies[0].tris
                    for e in ((x, y), (y, z), (z, x)))
    assert set(edges.values()) == {2}


def test_the_plan_area_of_columns_is_their_ground_triangles():
    # two columns on a 10 x 10 ft right triangle: 50 sf each, wherever their
    # rays lean
    p = earthwork.Column("t", "fill", [(0, 0, 0), (10, 0, 0), (0, 10, 0)],
                         [(-1, 0, 1), (9, 0, 1), (-1, 10, 1)],
                         [(0, 0), (10, 0), (0, 10)])
    assert earthwork.plan_area_sf([p, p]) == pytest.approx(100.0)
    assert p.volume_cf == pytest.approx(50.0)


class Line:
    """A section stand-in: station `s` and its earthwork line, given."""

    def __init__(self, s, line):
        self.s, self.line = s, line

    def earthwork_line(self, per_component=1):
        return list(self.line)


#: a straight road climbing 30 %: a section point v up leans 0.287 v back
#: along the line, so on a 1 ft bay a 20 ft rise in the design line puts its
#: top corner behind the bay's start in plan
STEEP = Profile([{"bvc_station": 0.0, "bvc_elev": 100.0, "g_in_pct": 30.0,
                  "g_out_pct": 30.0, "length_ft": 100.0, "evc_station": 100.0,
                  "evc_elev": 130.0}])


def steep(s, u, v):
    return survey_point(AL, STEEP, s, u, v)


def test_a_leaning_bay_is_one_closed_body_holding_the_volume_along_its_rays():
    # level ground at 60, 40 ft or more under the line: all fill. The design
    # line at 51 rises 20 ft to its left end, as a fill wall's lead-in does
    import math
    ground = PlaneGround(60.0)
    a = Line(50.0, [(20.0, -1.0), (0.0, -1.0), (-20.0, -1.0)])
    b = Line(51.0, [(20.0, 19.0), (0.0, -1.0), (-20.0, -1.0)])
    # the vertical columns' plan triangles fold: one winds the other way
    pa = [steep(a.s, *p) for p in a.line]
    pb = [steep(b.s, *p) for p in b.line]
    winds = [earthwork._signed_area([(e, n) for n, e, _z in tri]) > 0.0
             for tri in ((pa[0], pb[0], pb[1]), (pa[0], pb[1], pa[1]))]
    assert len(set(winds)) == 2
    cut, fill, _cd, _fd = earthwork.strip("t", a, b, steep, ground.z, None)
    assert cut == []
    # independently: the survey map is affine, its volume scale sec(gamma);
    # over each (s, u) triangle the depth along the rays is linear, from
    # the design v down to the ground's, (60 - elev(s)) / cos(gamma)
    cg = math.cos(math.atan(0.3))

    def depth(s, v):
        return v - (60.0 - STEEP.elev(s)) / cg

    want = 0.0
    for i in range(2):
        for tri in (((a.s, *a.line[i]), (b.s, *b.line[i]), (b.s, *b.line[i + 1])),
                    ((a.s, *a.line[i]), (b.s, *b.line[i + 1]), (a.s, *a.line[i + 1]))):
            area = abs(earthwork._signed_area([(s, u) for s, u, _v in tri]))
            want += area * sum(depth(s, v) for s, _u, v in tri) / 3.0 / cg
    assert sum(p.volume_cf for p in fill) == pytest.approx(want, rel=1e-9)
    (body,) = earthwork.merge("t", "fill", fill)
    directed = Counter((x, y) for t in body.tris for x, y in zip(t, t[1:] + t[:1]))
    assert all(n == 1 and directed[y, x] == 1 for (x, y), n in directed.items())
    assert body.volume_cf == pytest.approx(want, rel=1e-9)


def _positive_part(area, f):
    """The integral of max(F, 0) over a triangle of `area` where F is linear
    and `f` its corner values: where one corner alone is positive, the part
    is a triangle of area x p^2 / ((p - n1)(p - n2)) and mean height p / 3;
    where two are, the whole less the negative corner's part."""
    pos = [x for x in f if x > 0.0]
    neg = [x for x in f if x <= 0.0]
    if not pos:
        return 0.0
    if not neg:
        return area * sum(f) / 3.0
    if len(pos) == 1:
        (p,), (n1, n2) = pos, neg
        return area * p ** 3 / (3.0 * (p - n1) * (p - n2))
    (n,), (p1, p2) = neg, pos
    return area * sum(f) / 3.0 + area * (-n) ** 3 / (3.0 * (p1 - n) * (p2 - n))


def test_a_leaning_bay_over_a_side_hill_splits_cut_from_fill_along_its_rays():
    # the bay above over ground rising 0.3 to the east (the right) and 0.1
    # to the north: fill on the left, cut on the right, the ground crossing
    # the design line inside triangles of the bay
    import math
    ground = PlaneGround(114.0, n0=50.0, slope_n=0.1, slope_e=0.3)
    a = Line(50.0, [(20.0, -1.0), (0.0, -1.0), (-20.0, -1.0)])
    b = Line(51.0, [(20.0, 19.0), (0.0, -1.0), (-20.0, -1.0)])
    cut, fill, _cd, _fd = earthwork.strip("t", a, b, steep, ground.z, None)
    assert cut and fill
    # independently: on a plane the depth along a ray is linear in v, so two
    # readings place the ground; over each (s, u) triangle the depth is
    # linear, and the survey map scales volume by sec(gamma)
    sec = 1.0 / math.cos(math.atan(0.3))

    def depth(s, u, v):
        def above(w):
            n, e, z = steep(s, u, w)
            return ground.z(n, e) - z
        f0, f1 = above(0.0), above(1.0)
        return -f0 / (f1 - f0) - v

    want = {"cut": 0.0, "fill": 0.0}
    crossed = 0
    for i in range(2):
        for tri in (((a.s, *a.line[i]), (b.s, *b.line[i]), (b.s, *b.line[i + 1])),
                    ((a.s, *a.line[i]), (b.s, *b.line[i + 1]), (a.s, *a.line[i + 1]))):
            area = abs(earthwork._signed_area([(s, u) for s, u, _v in tri]))
            d = [depth(*q) for q in tri]
            crossed += min(d) < 0.0 < max(d)
            want["cut"] += sec * _positive_part(area, d)
            want["fill"] += sec * _positive_part(area, [-x for x in d])
    assert crossed >= 2
    for kind, cols in (("cut", cut), ("fill", fill)):
        assert sum(p.volume_cf for p in cols) == pytest.approx(want[kind], rel=1e-9)
        (body,) = earthwork.merge("t", kind, cols)
        directed = Counter((x, y) for t in body.tris for x, y in zip(t, t[1:] + t[:1]))
        assert all(n == 1 and directed[y, x] == 1 for (x, y), n in directed.items())
        assert body.volume_cf == pytest.approx(want[kind], rel=1e-9)


def test_a_column_turned_inside_out_is_refused():
    # a survey whose v points down: each column's top lies under its base
    def down(s, u, v):
        n, e, z = survey(s, u, v)
        return n, e, 200.0 - z

    ground = PlaneGround(95.0)
    a = Line(0.0, [(10.0, -1.0), (-10.0, -1.0)])
    b = Line(100.0, [(10.0, -1.0), (-10.0, -1.0)])
    with pytest.raises(ValueError, match="inside out"):
        earthwork.strip("t", a, b, down, ground.z, None)
