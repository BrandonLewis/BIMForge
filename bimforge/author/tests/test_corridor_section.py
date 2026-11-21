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
