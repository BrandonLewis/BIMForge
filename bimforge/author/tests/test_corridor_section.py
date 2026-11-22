"""road-corridor section resolver: hand-worked sections (P.6)."""
import copy

import pytest

from bimforge.author.corridor.params import parse
from bimforge.author.corridor.section import (GUARD_STEP_FT, SIDE_SAMPLES,
                                              NoDaylight, grade_edge,
                                              needs_wall, resolve)

BASE = {"section": {
    "components": [{"name": "lane", "kind": "carriageway", "width": 12.0},
                   {"name": "shoulder", "kind": "shoulder", "width": 5.0,
                    "slope": -0.05}],
    "courses": [{"name": "HMA", "type": "PAVEMENT", "thickness": 0.4},
                {"name": "AB", "type": "CORE", "thickness": 1.0}],
    "side_slopes": {"cut": {"ratio": 2.0, "ditch": {"width": 4.0, "depth": 1.5}},
                    "fill": {"ratio": 2.0}, "daylight_limit_ft": 150}}}


def corridor(**over):
    p = copy.deepcopy(BASE)
    p.update(over)
    return parse(p, 0.0, 2000.0)


def level(h):
    """Level ground h ft above the profile grade line."""
    return lambda s, u, v: h - v


def flat(points):
    return [c for p in points for c in p]


def test_normal_crown_grade_and_hinges():
    sec = resolve(corridor(), 500.0, level(-5.0))
    assert flat(sec.grade["L"]) == pytest.approx(flat([(0, 0), (12, -0.24), (17, -0.49)]))
    assert flat(sec.grade["R"]) == pytest.approx(flat([(0, 0), (-12, -0.24), (-17, -0.49)]))
    assert flat(sec.subgrade["L"][-1:]) == pytest.approx([17.0, -1.89])


def test_full_super_tilts_the_lanes_and_keeps_the_shoulder_slope():
    sec = resolve(corridor(superelevation=[[0, 0.06, -0.06], [2000, 0.06, -0.06]]),
                  500.0, level(-5.0))
    assert flat(sec.grade["L"]) == pytest.approx(flat([(0, 0), (12, 0.72), (17, 0.47)]))
    assert flat(sec.grade["R"]) == pytest.approx(flat([(0, 0), (-12, -0.72), (-17, -0.97)]))


def test_halfway_through_a_super_transition():
    # at 12+00, halfway from 10+00 (-0.02, -0.02) to 14+00 (0.06, -0.06):
    # left 0.02, right -0.04; the shoulders keep -0.05
    sec = resolve(corridor(superelevation=[[0, -0.02, -0.02], [1000, -0.02, -0.02],
                                           [1400, 0.06, -0.06], [2000, 0.06, -0.06]]),
                  1200.0, level(-5.0))
    assert flat(sec.grade["L"]) == pytest.approx(flat([(0, 0), (12, 0.24), (17, -0.01)]))
    assert flat(sec.grade["R"]) == pytest.approx(flat([(0, 0), (-12, -0.48), (-17, -0.73)]))


def test_course_rings_split_by_component_and_side():
    sec = resolve(corridor(), 500.0, level(-5.0))
    assert flat(sec.courses[0, 0, "L"]) == pytest.approx(
        flat([(0, 0), (12, -0.24), (12, -0.64), (0, -0.4)]))
    assert flat(sec.courses[1, 1, "R"]) == pytest.approx(
        flat([(-12, -0.64), (-17, -0.89), (-17, -1.89), (-12, -1.64)]))


def test_fill_daylights_at_the_fill_ratio():
    sec = resolve(corridor(), 500.0, level(-5.0))
    side = sec.sides["L"]
    assert side.kind == "fill"
    assert flat(side.line) == pytest.approx(flat([(17, -1.89), (23.22, -5.0)]))
    assert flat(sec.sides["R"].line[-1:]) == pytest.approx([-23.22, -5.0])


def test_cut_runs_through_the_ditch_then_up_the_backslope():
    sec = resolve(corridor(), 500.0, level(3.0))
    side = sec.sides["L"]
    assert side.kind == "cut"
    assert flat(side.line) == pytest.approx(
        flat([(17, -1.89), (20, -3.39), (24, -3.39), (36.78, 3.0)]))


def side_hill(s, u, v):
    """Ground 0.5 ft above the hinge (17, -1.89), falling 1 on 3 outward on
    the left; level at that height on the right."""
    if u <= 17.0:
        return -1.39 - v
    return -1.39 - (u - 17.0) / 3.0 - v


def test_a_side_hill_cut_whose_ditch_edge_is_above_ground_runs_fill_down():
    # the ditch edge (24, -3.39) sits 1/3 ft above the ground there
    # (-1.39 - 7/3 = -3.7233); the 2:1 fill slope gains 1/2 - 1/3 = 1/6 ft per
    # ft on the ground, so it meets it 2 ft out: (26, -4.39), where the ground
    # is -1.39 - 9/3 = -4.39
    sec = resolve(corridor(), 500.0, side_hill)
    side = sec.sides["L"]
    assert side.kind == "cut"
    assert flat(side.line) == pytest.approx(
        flat([(17, -1.89), (20, -3.39), (24, -3.39), (26, -4.39)]))
    u, v = side.line[-1]
    assert side_hill(500.0, u, v) == pytest.approx(0.0, abs=1e-6)
    assert len(sec.earthwork_line()) == 2 * SIDE_SAMPLES - 1 + 2 * 2


def test_a_daylight_off_the_ground_is_refused():
    # a cliff at 30 ft: the backslope reaches it below the ground beyond, so
    # the search stops at the step, 10+ ft off the ground
    def cliff(s, u, v):
        return (3.0 if abs(u) < 30.0 else -10.0) - v
    with pytest.raises(ValueError, match=r"5\+00.*L cut slope.*off the ground"):
        resolve(corridor(), 500.0, cliff)


def test_a_width_taper_moves_the_hinge():
    sec = resolve(corridor(widths=[{"component": "shoulder", "side": "R",
                                    "at": [[1200, 5.0], [1300, 10.0]]}]),
                  1250.0, level(-5.0))
    assert flat(sec.grade["R"][-1:]) == pytest.approx([-19.5, -0.615])


def test_a_wall_gap_runs_level_at_subgrade_to_the_wall():
    sec = resolve(corridor(gaps=[{"from": 400, "to": 600, "kind": "wall",
                                  "side": "L", "offset": 30.0}]), 500.0, level(-5.0))
    assert sec.sides["L"].kind == "wall"
    assert flat(sec.sides["L"].line) == pytest.approx(flat([(17, -1.89), (30, -1.89)]))
    assert sec.sides["R"].kind == "fill"


def test_walls_on_both_sides_at_one_station():
    sec = resolve(corridor(gaps=[
        {"from": 400, "to": 600, "kind": "wall", "side": "L", "offset": 30.0},
        {"from": 450, "to": 700, "kind": "wall", "side": "R", "offset": 25.0}]),
        500.0, level(-5.0))
    assert flat(sec.sides["L"].line) == pytest.approx(flat([(17, -1.89), (30, -1.89)]))
    assert flat(sec.sides["R"].line) == pytest.approx(flat([(-17, -1.89), (-25, -1.89)]))
    assert sec.width() == pytest.approx(55.0)
    assert len(sec.earthwork_line()) == 2 * SIDE_SAMPLES - 1 + 2 * 2


def test_a_wall_inside_the_hinge_is_refused():
    c = corridor(gaps=[{"from": 400, "to": 600, "kind": "wall", "side": "L",
                        "offset": 10.0}])
    with pytest.raises(ValueError, match="inside the hinge"):
        resolve(c, 500.0, level(-5.0))


def test_a_slope_that_finds_no_ground_names_the_station_and_side():
    with pytest.raises(ValueError, match=r"5\+00.*L fill slope finds no ground within 150"):
        resolve(corridor(), 500.0, level(-500.0))


def test_the_earthwork_line_has_one_count_in_cut_and_in_fill():
    c = corridor()
    a, b = resolve(c, 500.0, level(-5.0)), resolve(c, 525.0, level(3.0))
    n = 2 * SIDE_SAMPLES - 1 + 2 * len(c.components)
    assert len(a.earthwork_line()) == len(b.earthwork_line()) == n
    line = a.earthwork_line()
    assert line[0] == pytest.approx((23.22, -5.0))
    assert line[-1] == pytest.approx((-23.22, -5.0))
    assert a.width() == pytest.approx(46.44)


def test_the_earthwork_line_divides_each_component_under_the_road():
    sec = resolve(corridor(), 500.0, level(-5.0))
    base = sec.earthwork_line()
    assert sec.earthwork_line(per_component=1) == base
    # lane in 3, shoulder in 2: 2 extra under the lane and 1 under the
    # shoulder, each side
    line = sec.earthwork_line(per_component=(3, 2))
    assert len(line) == 2 * SIDE_SAMPLES - 1 + 2 * (3 + 2)
    assert len(sec.earthwork_line(per_component=4)) == 2 * SIDE_SAMPLES - 1 + 2 * 8
    # the added points lie on the subgrade, evenly between its edges, and
    # every original point is kept in order
    assert [p for p in line if p in base] == base
    i = line.index(base[SIDE_SAMPLES])                  # left lane edge, u 12
    assert flat(line[i:i + 4]) == pytest.approx(
        flat([(12, -1.64), (8, -1.56), (4, -1.48), (0, -1.4)]))
    j = line.index(base[SIDE_SAMPLES + 2])              # right lane edge
    assert flat(line[j:j + 3]) == pytest.approx(
        flat([(-12, -1.64), (-14.5, -1.765), (-17, -1.89)]))


def test_a_bad_division_count_is_refused():
    sec = resolve(corridor(), 500.0, level(-5.0))
    with pytest.raises(ValueError, match="one count per component"):
        sec.earthwork_line(per_component=(2,))
    with pytest.raises(ValueError, match="at least 1"):
        sec.earthwork_line(per_component=0)


def test_a_subgrade_with_unequal_sides_is_refused():
    sec = resolve(corridor(), 500.0, level(-5.0))
    sec.subgrade["R"].append(sec.subgrade["R"][-1])
    with pytest.raises(ValueError, match="2 components left, 3 right"):
        sec.earthwork_line()


def test_ground_missing_under_a_side_names_the_station_and_side():
    def dem(s, u, v):
        if u > 20.0:
            raise ValueError("ground: no ground at N 1.0 E 2.0: the DEM does not cover it")
        return 3.0 - v
    with pytest.raises(ValueError, match=r"station 5\+00\.00, L side.*no ground at N 1\.0 E 2\.0"):
        resolve(corridor(), 500.0, dem)


STEEP_FILL = {"ratio": 4.0, "steep": {"ratio": 2.0, "above_height_ft": 10.0}}


def sloped(fill=None, cut=None, footprint=None, **over):
    """A corridor on BASE with its side slopes changed."""
    p = copy.deepcopy(BASE)
    ss = p["section"]["side_slopes"]
    if fill is not None:
        ss["fill"] = copy.deepcopy(fill)
    if cut is not None:
        ss["cut"] = copy.deepcopy(cut)
    if footprint is not None:
        ss["footprint_ft"] = dict(footprint)
    p.update(over)
    return parse(p, 0.0, 2000.0)


def test_the_shoulder_edge_is_the_grade_s_outer_point():
    assert grade_edge(corridor(), 500.0, "R") == pytest.approx((-17.0, -0.49))


def test_fill_under_the_height_limit_takes_4_to_1():
    # 3.11 ft of fill at the hinge (17, -1.89) over ground at -5: not over
    # 10 ft, so 4:1, falling 3.11 ft in 4 x 3.11 = 12.44 ft: (29.44, -5)
    sec = resolve(sloped(fill=STEEP_FILL), 500.0, level(-5.0))
    side = sec.sides["L"]
    assert (side.kind, side.guarded, side.ratio) == ("fill", False, 4.0)
    assert flat(side.line) == pytest.approx(flat([(17, -1.89), (29.44, -5.0)]))


def test_fill_over_the_height_limit_takes_2_to_1_behind_the_rail_s_widening():
    # 13.11 ft of fill at the hinge over ground at -15: over 10, so 2:1 and
    # guarded. The rail face is at the shoulder edge (17, -0.49); the
    # widening falls 1 in 10 to the hinge 1.44 + 2.5 = 3.94 ft out:
    # (20.94, -0.49 - 0.394) = (20.94, -0.884). Its first point is 0.01 ft
    # out, on the widening: (17.01, -0.491). From the widening's hinge 2:1
    # falls 14.116 ft in 28.232 ft: daylight (49.172, -15)
    sec = resolve(sloped(fill=STEEP_FILL), 500.0, level(-15.0))
    side = sec.sides["L"]
    assert (side.kind, side.guarded, side.ratio) == ("fill", True, 2.0)
    assert GUARD_STEP_FT == 0.01
    assert flat(side.line) == pytest.approx(flat(
        [(17, -1.89), (17.01, -0.491), (20.94, -0.884), (49.172, -15.0)]))
    assert flat(sec.sides["R"].line[-1:]) == pytest.approx([-49.172, -15.0])
    assert len(sec.earthwork_line()) == 2 * SIDE_SAMPLES - 1 + 2 * 2


def test_the_earthwork_line_keeps_its_count_whatever_the_side_is():
    # 4:1 fill, guarded 2:1 fill, cut through the ditch, and a wall: one
    # count, so stations loft point to point
    c = sloped(fill=STEEP_FILL, gaps=[{"from": 900, "to": 1100, "kind": "wall",
                                       "side": "L", "offset": 30.0}])
    secs = [resolve(c, 500.0, level(-5.0)), resolve(c, 500.0, level(-15.0)),
            resolve(c, 500.0, level(3.0)), resolve(c, 1000.0, level(-15.0))]
    assert [s.sides["L"].kind for s in secs] == ["fill", "fill", "cut", "wall"]
    # with rock: a cut into rock, one whose bench collapses, a side-hill cut
    # (V1's 2:1 fill ratio: the 4:1 runs down shallower than its ground) and
    # fill
    rc = sloped(cut=ROCK_CUT)
    secs += [resolve(rc, 500.0, level(15.0)), resolve(rc, 500.0, level(3.0)),
             resolve(rc, 500.0, side_hill), resolve(rc, 500.0, level(-15.0))]
    assert {len(s.earthwork_line()) for s in secs} == {2 * SIDE_SAMPLES - 1 + 2 * 2}


def test_without_a_steep_rule_fill_keeps_its_one_ratio():
    # V1: 2:1 from the hinge, 13.11 ft in 26.22 ft: (43.22, -15)
    side = resolve(corridor(), 500.0, level(-15.0)).sides["L"]
    assert (side.kind, side.guarded, side.ratio) == ("fill", False, 2.0)
    assert flat(side.line) == pytest.approx(flat([(17, -1.89), (43.22, -15.0)]))


def test_a_daylight_past_the_footprint_is_refused():
    # the 2:1 daylights at 43.22 ft, past a 40 ft footprint on the left
    with pytest.raises(NoDaylight, match=r"5\+00\.00: the L fill slope daylights "
                       r"43\.22 ft out, past the L footprint of 40 ft") as exc:
        resolve(sloped(footprint={"L": 40.0}), 500.0, level(-15.0))
    assert exc.value.kind == "fill"
    assert isinstance(exc.value, ValueError)
    # inside it, the same section builds
    resolve(sloped(footprint={"L": 44.0}), 500.0, level(-15.0))


def test_needs_wall_says_which_wall_a_side_needs():
    c = corridor()
    assert needs_wall(c, 500.0, "L", level(-5.0)) is None
    assert needs_wall(c, 500.0, "L", level(-500.0)) == "fill"
    # 500 ft of cut: the backslope from the ditch's edge (24, -3.39) needs
    # 2 x 503.39 ft, past the 143 ft left of the daylight limit
    assert needs_wall(c, 500.0, "L", level(500.0)) == "cut"
    # where a wall is listed, the side is that wall: it needs none
    walled = corridor(gaps=[{"from": 400, "to": 600, "kind": "wall", "side": "L",
                             "offset": 30.0}])
    assert needs_wall(walled, 500.0, "L", level(-500.0)) is None


def test_a_cut_past_the_footprint_is_refused():
    # the backslope daylights at 36.78 ft, past a 30 ft footprint on the left
    with pytest.raises(NoDaylight, match=r"5\+00\.00: the L cut slope daylights "
                       r"36\.78 ft out, past the L footprint of 30 ft") as exc:
        resolve(sloped(footprint={"L": 30.0}), 500.0, level(3.0))
    assert exc.value.kind == "cut"


def test_needs_wall_names_the_kind_past_the_footprint():
    # fill daylights at 43.22 ft and cut at 36.78 ft: both past their footprint
    c = sloped(footprint={"L": 30.0, "R": 40.0})
    assert needs_wall(c, 500.0, "L", level(-15.0)) == "fill"
    assert needs_wall(c, 500.0, "L", level(3.0)) == "cut"
    assert needs_wall(c, 500.0, "R", level(-15.0)) == "fill"
    # inside the footprint the slope fits
    assert needs_wall(c, 500.0, "R", level(3.0)) is None


ROCK_CUT = {"ratio": 2.0, "ditch": {"width": 4.0, "depth": 1.5},
            "rock": {"depth_ft": 8.0, "ratio": 0.5, "bench_ft": 6.0}}


def test_a_cut_into_rock_benches_then_runs_soil_to_daylight():
    # ground 15 ft above the PGL, rock 8 ft under it, at v = 7. The ditch's
    # outer edge (24, -3.39) is 18.39 ft under ground, 10.39 ft into rock.
    # The rock face rises 2 per ft (0.5:1): 10.39 ft in 5.195 ft, to
    # (29.195, 7). The bench runs 6 ft level: (35.195, 7). The soil, 8 ft
    # deep, rises 1 in 2: 16 ft out, daylight (51.195, 15)
    sec = resolve(sloped(cut=ROCK_CUT), 500.0, level(15.0))
    side = sec.sides["L"]
    assert (side.kind, side.ratio) == ("cut", 2.0)
    assert flat(side.line) == pytest.approx(flat(
        [(17, -1.89), (20, -3.39), (24, -3.39), (29.195, 7.0), (35.195, 7.0),
         (51.195, 15.0)]))
    assert flat(sec.sides["R"].line[-1:]) == pytest.approx([-51.195, 15.0])


def test_a_cut_that_never_reaches_rock_collapses_its_bench_onto_the_toe():
    # ground 3 ft above: the ditch's edge is 3 + 3.39 = 6.39 ft under,
    # inside the 8 ft of soil. The rock face and the bench are points at the
    # edge, and the soil runs to V1's daylight: 6.39 ft up at 1 in 2,
    # 12.78 ft out: (36.78, 3)
    sec = resolve(sloped(cut=ROCK_CUT), 500.0, level(3.0))
    assert flat(sec.sides["L"].line) == pytest.approx(flat(
        [(17, -1.89), (20, -3.39), (24, -3.39), (24, -3.39), (24, -3.39),
         (36.78, 3.0)]))
    deep = resolve(sloped(cut=ROCK_CUT), 500.0, level(15.0))
    assert len(sec.earthwork_line()) == len(deep.earthwork_line())


def test_rock_depth_follows_its_rows():
    # [0, 8] to [2000, 12]: 10 ft at 10+00, rock at v = 15 - 10 = 5. The
    # rock face rises 5 + 3.39 = 8.39 ft from the ditch's edge in 4.195 ft:
    # (28.195, 5); the bench to (34.195, 5); 10 ft of soil at 1 in 2, 20 ft
    # out: (54.195, 15)
    cut = copy.deepcopy(ROCK_CUT)
    cut["rock"]["depth_ft"] = [[0, 8.0], [2000, 12.0]]
    sec = resolve(sloped(cut=cut), 1000.0, level(15.0))
    assert flat(sec.sides["L"].line) == pytest.approx(flat(
        [(17, -1.89), (20, -3.39), (24, -3.39), (28.195, 5.0), (34.195, 5.0),
         (54.195, 15.0)]))


def test_a_side_hill_rock_cut_whose_ditch_edge_is_above_ground_runs_fill_down():
    # as V1's side hill: the ditch edge (24, -3.39) is 1/3 ft above the
    # ground, so not in rock; the bench collapses onto it and the side runs
    # down 2:1 to (26, -4.39)
    sec = resolve(sloped(cut=ROCK_CUT), 500.0, side_hill)
    side = sec.sides["L"]
    assert (side.kind, side.ratio) == ("cut", 2.0)
    assert flat(side.line) == pytest.approx(flat(
        [(17, -1.89), (20, -3.39), (24, -3.39), (24, -3.39), (24, -3.39),
         (26, -4.39)]))


def test_a_rock_face_that_finds_no_rock_surface_is_refused():
    # ground 50 ft above the PGL at the centreline, rising 3 per ft outward:
    # the ditch's edge is deep in rock, but the rock surface, 8 ft under the
    # ground, rises 3 per ft and the 0.5:1 face only 2, so it never gets there
    rising = lambda s, u, v: 50.0 + 3.0 * abs(u) - v
    with pytest.raises(NoDaylight, match=r"5\+00\.00: the L cut's rock face "
                       r"finds no rock surface within 150 ft") as exc:
        resolve(sloped(cut=ROCK_CUT), 500.0, rising)
    assert exc.value.kind == "cut"
