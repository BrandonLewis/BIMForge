"""road-corridor section resolver: hand-worked sections (P.6)."""
import copy

import pytest

from bimforge.author.corridor.params import parse
from bimforge.author.corridor.section import SIDE_SAMPLES, resolve

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
