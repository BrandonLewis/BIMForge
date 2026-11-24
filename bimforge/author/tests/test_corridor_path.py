"""road-corridor V1.2 part C: the shared-use path's params, geometry and
section, hand-worked on a level road on a tangent (P.6)."""
import copy
import math

import pytest

from bimforge.author.alignment import Alignment, Profile
from bimforge.author.corridor.params import Gap, Guard, parse
from bimforge.author.corridor.path import approaches, deck_elevation, on_approach

AL = Alignment({"station": 1000.0, "northing": 0.0, "easting": 0.0},
               [{"kind": "tangent", "bearing": "N 0-0-0 E", "length": 1000.0}],
               name="T")


def grade(elev, pct=0.0, s0=1000.0, s1=2000.0):
    """A profile at one grade from s0 to s1: one curve whose grades are
    equal, as the road's profiles are written."""
    return {"curves": [{"bvc_station": s0, "bvc_elev": elev, "g_in_pct": pct,
                        "g_out_pct": pct, "length_ft": s1 - s0,
                        "evc_station": s1,
                        "evc_elev": elev + pct / 100.0 * (s1 - s0)}]}


#: the road: level at elevation 100
PROF = Profile(grade(100.0)["curves"])
BASE = {"section": {
    "components": [{"name": "lane", "kind": "carriageway", "width": 12.0},
                   {"name": "shoulder", "kind": "shoulder", "width": 5.0,
                    "slope": -0.05}],
    "courses": [{"name": "HMA", "type": "PAVEMENT", "thickness": 0.4},
                {"name": "AB", "type": "CORE", "thickness": 1.0}],
    "side_slopes": {"cut": {"ratio": 2.0, "ditch": {"width": 4.0, "depth": 1.5}},
                    "fill": {"ratio": 2.0}, "daylight_limit_ft": 150}}}
#: on BASE at a normal crown the road's left edge of shoulder is 12 ft at
#: -2 % and 5 ft at -5 % out: (17, -0.49); its hinge 1.4 ft lower, (17, -1.89)
PATH = {"side": "L", "separation": [[1000, 10.0]], "width": 12.0,
        "courses": [{"name": "PATH-HMA", "type": "PAVEMENT", "thickness": 0.25},
                    {"name": "PATH-AB", "type": "CORE", "thickness": 0.5}],
        "profile": grade(99.51)}       # level with the road's edge of shoulder


def path(**over):
    d = copy.deepcopy(PATH)
    d.update(copy.deepcopy(over))
    return d


def corridor(p=None, prof=PROF, **over):
    params = copy.deepcopy(BASE)
    params.update(copy.deepcopy(over))
    params["path"] = copy.deepcopy(PATH if p is None else p)
    return parse(params, 1000.0, 2000.0, alignment=AL, profile=prof)


def test_without_a_path_a_corridor_is_v11():
    c = parse(copy.deepcopy(BASE), 1000.0, 2000.0)
    assert c.path is None and c.guard is None
    assert not c.path_at(1500.0)


def test_a_path_takes_its_defaults():
    p = corridor().path
    assert (p.side, p.sign, p.s_start, p.s_end) == ("L", 1.0, 1000.0, 2000.0)
    assert (p.width, p.cross_slope, p.shoulder_width, p.shoulder_slope) == (
        12.0, -0.02, 2.0, -0.05)
    assert (p.design_speed, p.strip_ratio, p.approach, p.deck_separation,
            p.rail_height) == (20, 2.0, 100.0, 1.5, 3.5)
    assert [x.name for x in p.courses] == ["PATH-HMA", "PATH-AB"]
    assert p.depth() == pytest.approx(0.75)
    assert p.separation_at(1500.0) == 10.0
    assert p.profile.elev(1500.0) == pytest.approx(99.51)
    assert p.road_profile is PROF and p.alignment is AL


def test_a_path_brings_a_guardrail_at_its_defaults():
    # a strip steeper than fill.ratio below a higher road is guarded, as a
    # V1.1 steep fill is: 45 mph, the MGS depth
    assert corridor().guard == Guard(speed_mph=45, rail_depth=1.44)
    assert corridor(path(side="R")).path.sign == -1.0


def test_separation_interpolates_by_station_and_holds_its_ends():
    p = corridor(path(separation=[[1100, 10.0], [1300, 20.0]])).path
    # 12+00 is halfway from 11+00 (10 ft) to 13+00 (20 ft): 15 ft
    assert [p.separation_at(s) for s in (1000.0, 1200.0, 1900.0)] == [10.0, 15.0, 20.0]


def test_path_stations_limit_it():
    c = corridor(path(stations=[1200, 1800]))
    assert (c.path.s_start, c.path.s_end) == (1200.0, 1800.0)
    assert c.path_at(1500.0) and not c.path_at(1100.0)


def test_the_path_s_ends_and_rows_are_stations():
    c = corridor(path(stations=[1210, 1790],
                      separation=[[1210, 10.0], [1240, 12.0]]))
    # the interval (25 ft) and band stations, 1 ft outside the path's start
    # (where its section turns into the road's own), its start, and the
    # separation rows
    assert c.stations(1150.0, 1260.0) == [1150.0, 1175.0, 1200.0, 1209.0,
                                          1210.0, 1225.0, 1240.0, 1250.0, 1260.0]


def test_a_path_vertical_curve_is_densified():
    # a 200 ft sag from -4 % to +4 %: a chord's sagitta r h^2 / 8 within
    # 0.01 ft (sweep.VC_SAGITTA_FT) takes h <= sqrt(8 x 0.01 x 200 / 0.08),
    # 14.14 ft: 15 parts of 13.33 ft
    prof = {"curves": [
        {"bvc_station": 1000.0, "bvc_elev": 99.51, "g_in_pct": -4.0,
         "g_out_pct": -4.0, "length_ft": 400.0, "evc_station": 1400.0,
         "evc_elev": 83.51},
        {"bvc_station": 1400.0, "bvc_elev": 83.51, "g_in_pct": -4.0,
         "g_out_pct": 4.0, "length_ft": 200.0, "evc_station": 1600.0,
         "evc_elev": 83.51},
        {"bvc_station": 1600.0, "bvc_elev": 83.51, "g_in_pct": 4.0,
         "g_out_pct": 4.0, "length_ft": 400.0, "evc_station": 2000.0,
         "evc_elev": 99.51}]}
    got = corridor(path(profile=prof)).stations(1400.0, 1600.0)
    assert max(b - a for a, b in zip(got, got[1:])) <= 200.0 / 15 + 1e-9
    assert 1500.0 in got                                   # the PVI


@pytest.mark.parametrize("over, match", [
    ({"side": "X"}, r"path\.side: 'X' is not L or R"),
    ({"width": 0}, r"path\.width: must be positive"),
    ({"shoulder": {"width": 0}}, r"path\.shoulder\.width: must be positive"),
    ({"shoulder": {"slope": -0.06}}, r"path\.shoulder\.slope: -0\.06 is outside 2-5 %"),
    ({"shoulder": {"slope": 0.03}}, r"path\.shoulder\.slope: 0\.03 does not slope away"),
    ({"cross_slope": -0.03}, r"path\.cross_slope: -0\.03 is outside 1-2 %"),
    ({"cross_slope": 0.005}, r"path\.cross_slope: 0\.005 is outside 1-2 %"),
    ({"design_speed_mph": 25}, r"path\.design_speed_mph: 25 is not 20 or 30"),
    ({"courses": [{"name": "X", "type": "PAVEMENT", "thickness": 0}]},
     r"path\.courses\[0\]\.thickness: must be positive"),
    ({"courses": [{"name": "X", "type": "TOPSOIL", "thickness": 0.5}]},
     r"path\.courses\[0\]: type 'TOPSOIL' is not one of"),
    ({"courses": []}, r"path\.courses: needs at least one course"),
    ({"approach_ft": 0}, r"path\.approach_ft: must be positive"),
    ({"rail_height_ft": -1}, r"path\.rail_height_ft: must be positive"),
    ({"deck_separation_ft": 0}, r"path\.deck_separation_ft: must be positive"),
    ({"strip": {"max_ratio": 0}}, r"path\.strip\.max_ratio: must be positive"),
    ({"stations": [1200, 2500]}, r"path\.stations: station 25\+00\.00 is off the alignment"),
    ({"stations": [1500, 1200]}, r"path\.stations: 'to' 12\+00\.00 must be past 'from' 15\+00\.00"),
    ({"separation": [[2500, 10.0]]}, r"path\.separation: station 25\+00\.00 is off"),
    ({"separation": []}, r"path\.separation: needs \[station, ft\] rows"),
    ({"profile": grade(99.51, s0=1100.0)},
     r"path\.profile: covers 11\+00\.00 to 20\+00\.00, not the path's "
     r"10\+00\.00 to 20\+00\.00"),
    ({"profile": {"curves": [dict(grade(99.51)["curves"][0], evc_elev=99.6)]}},
     r"path\.profile\.curves\[0\]: evc_elev 99\.6 is not the curve's 99\.5100"),
    ({"profile": {"curves": [dict(grade(99.51)["curves"][0], length_ft=0)]}},
     r"path\.profile\.curves\[0\]\.length_ft: must be positive"),
    ({"profile": None}, r"path\.profile: a profile is \{curves: \[\.\.\.\]\}"),
    ({"colour": "red"}, r"path: unknown keys \['colour'\]"),
])
def test_bad_path_params_are_refused(over, match):
    with pytest.raises(ValueError, match=match):
        corridor(path(**over))


def test_a_path_needs_the_road_s_alignment_and_profile():
    params = copy.deepcopy(BASE)
    params["path"] = copy.deepcopy(PATH)
    with pytest.raises(ValueError, match=r"path: needs the road's alignment and profile"):
        parse(params, 1000.0, 2000.0)


def test_a_listed_wall_gap_on_the_path_s_side_is_refused():
    with pytest.raises(ValueError, match=r"gaps: a listed wall gap on the L side, "
                       r"12\+00\.00 to 13\+00\.00, overlaps the path's stations"):
        corridor(gaps=[{"from": 1200, "to": 1300, "kind": "wall", "side": "L",
                        "offset": 40.0}])
    corridor(gaps=[{"from": 1200, "to": 1300, "kind": "wall", "side": "R",
                    "offset": 40.0}])                    # the other side


@pytest.mark.parametrize("gap_end, refused", [
    (1198.0, True),        # 2 ft before the path starts: V1.1's margin, touching
    (1199.0, True),
    (1197.5, False),       # just outside the margin
])
def test_a_listed_wall_gap_near_the_path_s_start_is_refused_within_the_margin(
        gap_end, refused):
    gaps = [{"from": 1100, "to": gap_end, "kind": "wall", "side": "L",
             "offset": 40.0}]
    if refused:
        with pytest.raises(ValueError, match=r"overlaps the path's stations"):
            corridor(path(stations=[1200, 1800]), gaps=gaps)
    else:
        corridor(path(stations=[1200, 1800]), gaps=gaps)


@pytest.mark.parametrize("gap_start, refused", [
    (1802.0, True), (1801.0, True), (1802.5, False)])
def test_a_listed_wall_gap_near_the_path_s_end_is_refused_within_the_margin(
        gap_start, refused):
    gaps = [{"from": gap_start, "to": 1900, "kind": "wall", "side": "L",
             "offset": 40.0}]
    if refused:
        with pytest.raises(ValueError, match=r"overlaps the path's stations"):
            corridor(path(stations=[1200, 1800]), gaps=gaps)
    else:
        corridor(path(stations=[1200, 1800]), gaps=gaps)


@pytest.mark.parametrize("courses, match", [
    ("HMA", r"path\.courses: a list of"),
    ({"name": "X"}, r"path\.courses: a list of"),
    (["HMA"], r"path\.courses\[0\]: a mapping"),
    ([{"name": "X", "type": "PAVEMENT", "thickness": 0.25}, 5],
     r"path\.courses\[1\]: a mapping"),
    (None, r"path\.courses: needs at least one course"),
])
def test_bad_course_shapes_are_value_errors(courses, match):
    with pytest.raises(ValueError, match=match):
        corridor(path(courses=courses))


@pytest.mark.parametrize("cs", [-0.01, -0.02, 0.01, 0.02])
def test_cross_slope_boundaries_pass_and_a_positive_one_is_a_magnitude(cs):
    # the sign is not read: the cross slope is stored falling away from the road
    assert corridor(path(cross_slope=cs)).path.cross_slope == -abs(cs)


@pytest.mark.parametrize("cs", [-0.0099, -0.0201, 0.0099, 0.0201])
def test_cross_slope_outside_the_boundaries_is_refused(cs):
    with pytest.raises(ValueError, match=r"path\.cross_slope: .* is outside 1-2 %"):
        corridor(path(cross_slope=cs))


def test_a_stations_error_echoes_both_stations():
    with pytest.raises(ValueError, match=r"'to' 12\+00\.00 must be past 'from' 15\+00\.00"):
        corridor(path(stations=[1500, 1200]))


def test_a_long_station_in_a_profile_error_is_not_cut_short():
    bad = dict(grade(99.51)["curves"][0], evc_station=1234567.5)
    with pytest.raises(ValueError, match=r"evc_station 12345\+67\.50 is not"):
        corridor(path(profile={"curves": [bad]}))


def two_curves(**second):
    """Two flat curves, 10+00 to 15+00 and 15+00 to 20+00 at elevation 99.51,
    the second's fields overridden."""
    a = grade(99.51, s0=1000.0, s1=1500.0)["curves"][0]
    b = dict(grade(99.51, s0=1500.0, s1=2000.0)["curves"][0])
    b.update(second)
    return {"curves": [a, b]}


def test_two_whole_curves_are_a_profile():
    assert corridor(path(profile=two_curves())).path.profile.elev(1700.0) == \
        pytest.approx(99.51)


@pytest.mark.parametrize("second, match", [
    ({"g_in_pct": 1.0, "g_out_pct": 1.0, "evc_elev": 104.51},
     r"path\.profile\.curves\[1\]: g_in_pct 1 is not the grade before it, 0"),
    ({"bvc_station": 1400.0, "evc_station": 1900.0},
     r"path\.profile\.curves\[1\]: starts at 14\+00\.00, inside the curve before it"),
    ({"bvc_elev": 99.7, "evc_elev": 99.7},
     r"path\.profile\.curves\[1\]: bvc_elev 99\.7 is off the tangent before it"),
])
def test_a_profile_s_curves_must_join(second, match):
    with pytest.raises(ValueError, match=match):
        corridor(path(profile=two_curves(**second)))


def test_a_profile_ending_before_the_path_does_is_refused():
    with pytest.raises(ValueError, match=r"path\.profile: covers 10\+00\.00 to "
                       r"19\+00\.00, not the path's 10\+00\.00 to 20\+00\.00"):
        corridor(path(profile=grade(99.51, s1=1900.0)))


def test_separation_rows_must_ascend():
    with pytest.raises(ValueError, match=r"path\.separation: stations must be "
                       r"strictly ascending"):
        corridor(path(separation=[[1300, 10.0], [1100, 12.0]]))
    with pytest.raises(ValueError, match=r"path\.separation: stations must be "
                       r"strictly ascending"):
        corridor(path(separation=[[1100, 10.0], [1100, 12.0]]))


def test_path_at_inside_at_the_edge_of_and_outside_a_structure_gap():
    # a path beside a structure gap meets the deck at its ends (Task 3)
    c = corridor(deck_path(), gaps=GAP)
    assert not c.path_at(1450.0)                      # on the deck
    assert c.path_at(1400.0) and c.path_at(1500.0)    # the gap's ends are sections
    assert c.path_at(1399.0) and c.path_at(1501.0)


def test_an_explicit_guardrail_block_overrides_the_path_s_default():
    c = corridor(guardrail={"design_speed_mph": 50, "rail_depth_ft": 1.6})
    assert c.guard == Guard(speed_mph=50, rail_depth=1.6)


def test_the_path_s_vertical_curve_ends_are_the_curves_own_stations():
    from bimforge.author.corridor.path import stations_extra
    c = corridor(path(profile=two_curves()))
    assert {1000.0, 1500.0, 2000.0} <= set(stations_extra(c))


GAP = [{"from": 1400, "to": 1500, "kind": "structure"}]
#: the deck at its paved edge on the level road: the left edge of shoulder
#: (99.51) and the lane's -2 % over the 1.5 ft deck separation, 0.03 down
DECK = 99.48
#: 10 ft, narrowing over each 100 ft approach to the deck's 1.5 ft
NARROW = [[1000, 10.0], [1300, 10.0], [1400, 1.5], [1500, 1.5], [1600, 10.0]]


def deck_path(elev=DECK, separation=NARROW, **over):
    return path(separation=separation, profile=grade(elev), **over)


def test_an_approach_narrowing_to_the_deck_builds():
    c = corridor(deck_path(), gaps=GAP)
    assert approaches(c) == [(1300.0, 1400.0, 1400.0), (1500.0, 1600.0, 1500.0)]
    assert on_approach(c, 1350.0) and on_approach(c, 1600.0)
    assert not on_approach(c, 1250.0)
    assert deck_elevation(c, 1400.0) == pytest.approx(DECK)
    # the path is on the deck inside the gap: no section is cut there
    assert c.path_at(1400.0) and not c.path_at(1450.0) and c.path_at(1500.0)


def test_the_deck_takes_the_road_s_superelevation():
    # +4 % on the left through the gap: the edge of shoulder 12 x 0.04 -
    # 5 x 0.05 = +0.23 up, and +0.04 x 1.5 = +0.06 more to the path's edge
    se = [[1000, 0.04, -0.04], [2000, 0.04, -0.04]]
    c = corridor(deck_path(100.29), gaps=GAP, superelevation=se)
    assert deck_elevation(c, 1500.0) == pytest.approx(100.29)


@pytest.mark.parametrize("separation, match", [
    ([[1000, 10.0], [1200, 4.0], [1300, 10.0], [1400, 1.5], [1500, 1.5],
      [1600, 10.0]],
     r"path\.separation: 4\.00 ft at 12\+00\.00 is under the 5 ft minimum "
     r"\(HDM 1003\.1\(7\)\) outside an approach to a structure gap"),
    # 5 ft at 12+80 to 1.5 at 14+00: 4.42 ft at 13+00, where the approach
    # starts, so a hair outside it too
    ([[1000, 10.0], [1280, 5.0], [1400, 1.5], [1500, 1.5], [1600, 10.0]],
     r"path\.separation: 4\.42 ft just before the approach that starts at "
     r"13\+00\.00 is under the 5 ft minimum"),
    ([[1000, 10.0], [1300, 10.0], [1350, 1.0], [1400, 1.5], [1500, 1.5],
      [1600, 10.0]],
     r"path\.separation: 1\.00 ft at 13\+50\.00 is under deck_separation_ft 1\.5"),
    ([[1000, 10.0]],
     r"path\.separation: 10\.00 ft at the structure gap's end 14\+00\.00 is not "
     r"deck_separation_ft 1\.5"),
])
def test_bad_separations_are_refused(separation, match):
    with pytest.raises(ValueError, match=match):
        corridor(deck_path(separation=separation), gaps=GAP)


def test_a_path_0_02_ft_off_the_deck_is_refused_and_0_005_builds():
    with pytest.raises(ValueError, match=(
            r"path\.profile: at the structure gap's end 14\+00\.00 the path is "
            r"at 99\.5000 ft and the deck at its paved edge 99\.4800 ft, "
            r"0\.0200 ft off \(more than 0\.01 ft\)")):
        corridor(deck_path(DECK + 0.02), gaps=GAP)
    corridor(deck_path(DECK + 0.005), gaps=GAP)


def test_a_gap_off_the_path_s_stations_is_no_approach():
    c = corridor(path(stations=[1000, 1300]), gaps=GAP)
    assert approaches(c) == []


def test_exactly_0_01_ft_off_the_deck_and_in_separation_passes():
    # the tolerance is inclusive: 0.01 ft is within "within 0.01 ft"
    corridor(deck_path(DECK + 0.01), gaps=GAP)
    near = [[1000, 10.0], [1300, 10.0], [1400, 1.51], [1500, 1.51], [1600, 10.0]]
    corridor(deck_path(99.4798, separation=near), gaps=GAP)


def test_a_right_path_meets_a_superelevated_deck():
    # +4 % left, -4 % right: the right edge of shoulder is 12 x -0.04 +
    # 5 x -0.05 = -0.73 down, and -0.04 x 1.5 = -0.06 more to the path's edge
    se = [[1000, 0.04, -0.04], [2000, 0.04, -0.04]]
    c = corridor(deck_path(99.21, side="R"), gaps=GAP, superelevation=se)
    assert deck_elevation(c, 1500.0) == pytest.approx(99.21)
    with pytest.raises(ValueError, match=r"path\.profile: at the structure gap's end"):
        corridor(deck_path(99.23, side="R"), gaps=GAP, superelevation=se)


def test_two_gaps_closer_than_the_approach_have_overlapping_windows():
    two = [{"from": 1400, "to": 1500, "kind": "structure"},
           {"from": 1550, "to": 1650, "kind": "structure"}]
    rows = [[1000, 10.0], [1300, 10.0], [1400, 1.5], [1650, 1.5], [1750, 10.0]]
    c = corridor(deck_path(separation=rows), gaps=two)
    assert approaches(c) == [(1300.0, 1400.0, 1400.0), (1500.0, 1600.0, 1500.0),
                             (1450.0, 1550.0, 1550.0), (1650.0, 1750.0, 1650.0)]
    assert on_approach(c, 1525.0)
    # a gap end off the deck's separation is refused, windows overlapping or not
    with pytest.raises(ValueError, match=r"is not deck_separation_ft"):
        corridor(deck_path(separation=[[1000, 10.0], [1300, 10.0], [1400, 1.5],
                                       [1500, 4.0], [1750, 10.0]]), gaps=two)


def test_an_approach_may_start_before_the_path_does():
    rows = [[1000, 1.5], [1150, 1.5], [1250, 10.0]]
    g = [{"from": 1050, "to": 1150, "kind": "structure"}]
    c = corridor(deck_path(separation=rows), gaps=g)
    assert approaches(c) == [(950.0, 1050.0, 1050.0), (1150.0, 1250.0, 1150.0)]


def test_a_gap_straddling_the_path_s_end_has_one_approach():
    rows = [[1000, 10.0], [1300, 10.0], [1400, 1.5]]
    c = corridor(deck_path(separation=rows, stations=[1000, 1450]), gaps=GAP)
    assert approaches(c) == [(1300.0, 1400.0, 1400.0)]


from bimforge.author.corridor.path import (course_rings, cos_theta, section_v,  # noqa: E402
                                           surface)


def pt(xy):
    return pytest.approx(xy, abs=1e-9)


def test_the_path_s_surface_on_a_level_road():
    sf = surface(corridor(), 1500.0)
    assert sf.edge == pt((17.0, -0.49))
    assert sf.inner == pt((27.0, -0.49))
    assert sf.outer == pt((39.0, -0.73))
    assert sf.q == pt((25.0, -0.59))
    assert sf.o == pt((41.0, -0.83))
    assert (sf.separation, sf.cg) == (10.0, 1.0)
    assert sf.cos_theta == pytest.approx(1.0, abs=1e-12)
    assert sf.depth == pytest.approx(0.75)


def test_on_the_right_the_path_mirrors():
    sf = surface(corridor(path(side="R")), 1500.0)
    assert sf.inner == pt((-27.0, -0.49))
    assert sf.o == pt((-41.0, -0.83))


def test_a_widened_shoulder_moves_the_path_out():
    # the left shoulder is 10 ft from 11+00: the edge of shoulder 22 ft out
    # and 0.24 + 0.50 down; the path keeps its 10 ft from it
    c = corridor(widths=[{"component": "shoulder", "side": "L",
                          "at": [[1000, 5.0], [1100, 10.0]]}])
    sf = surface(c, 1150.0)
    assert sf.edge == pt((22.0, -0.74))
    assert (sf.inner[0], sf.q[0], sf.o[0]) == pytest.approx((32.0, 30.0, 46.0))


def test_near_the_deck_the_inner_shoulder_narrows_to_the_separation():
    # 1.5 ft from the edge: the inner shoulder is 1.49 ft wide (STEP_FT less
    # than the separation), so q is 0.01 ft out from the road's edge of
    # shoulder, never on it
    c = corridor(deck_path(), gaps=GAP)
    sf = surface(c, 1400.0)
    assert sf.q[0] == pytest.approx(17.0 + 0.01)


def test_section_v_finds_an_elevation_in_the_leaning_plane():
    road = Profile(grade(100.0, pct=3.0)["curves"])
    c = corridor(path(profile=grade(97.51, pct=3.0)), prof=road)
    got = section_v(c.path, 1500.0, 30.0, lambda st: road.elev(st) - 2.0)
    assert got == pytest.approx(-2.0 / math.sqrt(1.0009), rel=1e-9)


def test_cos_theta_is_the_road_s_tangent_against_the_path_s():
    road = Profile(grade(100.0, pct=3.0)["curves"])
    c = corridor(path(profile=grade(99.51, pct=5.0)), prof=road)
    want = (1 + 0.03 * 0.05) / math.sqrt(1.0009 * 1.0025)
    assert cos_theta(c, 1500.0) == pytest.approx(want, rel=1e-9)
    sf = surface(c, 1500.0)
    rings = course_rings(c.path, sf)
    # each course thickness / cos theta deep in the plane, top down
    (ui, vi), (uo, vo) = sf.inner, sf.outer
    d0, d1 = 0.25 / want, 0.5 / want
    flat = lambda ring: [x for pt_ in ring for x in pt_]  # noqa: E731
    assert flat(rings[0]) == pytest.approx(flat([(ui, vi), (uo, vo), (uo, vo - d0),
                                                 (ui, vi - d0)]))
    assert flat(rings[1]) == pytest.approx(flat([(ui, vi - d0), (uo, vo - d0),
                                                 (uo, vo - d0 - d1),
                                                 (ui, vi - d0 - d1)]))
    assert sf.depth == pytest.approx(d0 + d1)


# -- follow-ups: curves, mirrors, convergence, edge points ------------------

from bimforge.author.corridor.frame import survey_point, tangent3  # noqa: E402


def curved(turn, side, radius=60.0, road_pct=0.0, path_pct=0.0,
           origin=(0.0, 0.0), **over):
    """A 90 degree curve of `radius` from 1000 on a corridor 1000-1090, the
    path on `side`, the road at road_pct and the path at path_pct; the
    alignment starts at `origin` (northing, easting)."""
    length = math.pi * radius / 2.0
    al = Alignment({"station": 1000.0, "northing": origin[0],
                    "easting": origin[1], "azimuth": 0.0},
                   [{"kind": "curve", "delta": "90-0-0", "turn": turn,
                     "radius": radius, "length": length}], name="C")
    road = Profile(grade(100.0, pct=road_pct, s1=1000.0 + length)["curves"])
    pp = path(side=side, profile=grade(99.51, pct=path_pct, s1=1000.0 + length),
              **over)
    params = copy.deepcopy(BASE)
    params["path"] = pp
    return parse(params, 1000.0, 1000.0 + length, alignment=al, profile=road)


def test_cos_theta_on_a_tight_curve_agrees_with_a_fine_chord():
    c = curved("L", "L", 60.0, road_pct=8.0, path_pct=-6.0)
    for s in (1010.0, 1040.0, 1080.0):
        assert cos_theta(c, s) == pytest.approx(cos_theta(c, s, 1e-4), abs=1e-8)


def test_tangent3_is_the_unit_road_tangent():
    road = Profile(grade(100.0, pct=3.0)["curves"])
    t = tangent3(AL, road, 1500.0)
    root = math.sqrt(1.0009)
    assert t == pytest.approx((1 / root, 0.0, 0.03 / root), abs=1e-12)
    assert math.sqrt(sum(x * x for x in t)) == pytest.approx(1.0)


def test_a_right_path_mirrors_a_left_one_on_a_graded_road():
    road = Profile(grade(100.0, pct=3.0)["curves"])
    pf = grade(99.51, pct=5.0)
    left = corridor(path(profile=pf), prof=road)
    right = corridor(path(side="R", profile=pf), prof=road)
    assert cos_theta(right, 1500.0) == pytest.approx(cos_theta(left, 1500.0),
                                                     abs=1e-12)
    sl, sr = surface(left, 1500.0), surface(right, 1500.0)
    for a, b in ((sl.q, sr.q), (sl.outer, sr.outer), (sl.o, sr.o),
                 (sl.inner, sr.inner)):
        assert (-b[0], b[1]) == pytest.approx(a, abs=1e-10)
    rl, rr = course_rings(left.path, sl), course_rings(right.path, sr)
    for k in rl:
        got = [x for u, v in rr[k] for x in (-u, v)]
        assert got == pytest.approx([x for pt_ in rl[k] for x in pt_], abs=1e-10)


def test_a_path_inside_a_curve_differs_from_one_outside_it():
    ll = curved("L", "L", road_pct=3.0, path_pct=5.0)
    rr = curved("R", "R", road_pct=3.0, path_pct=5.0)
    lr = curved("L", "R", road_pct=3.0, path_pct=5.0)
    s = 1040.0
    a, b = surface(ll, s), surface(rr, s)
    assert cos_theta(ll, s) == pytest.approx(cos_theta(rr, s), abs=1e-10)
    for x, y in ((a.q, b.q), (a.outer, b.outer), (a.inner, b.inner)):
        assert (-y[0], y[1]) == pytest.approx(x, abs=1e-10)
    assert abs(cos_theta(lr, s) - cos_theta(ll, s)) > 1e-5
    assert abs(surface(lr, s).outer[1] - a.outer[1]) > 1e-4


def test_section_v_on_a_curve_lands_on_the_path_s_profile():
    c = curved("L", "L", road_pct=6.0, path_pct=6.0)
    p = c.path
    sf = surface(c, 1040.0)
    # the point survey_point places at (u, v) is at the profile's elevation
    # where it lies; its station is found by the lean back v sin(gamma) / (1 - ku)
    ui, vi = sf.inner
    pt3 = survey_point(p.alignment, p.road_profile, 1040.0, ui, vi)
    g = p.road_profile.grade(1040.0)
    sg = g / math.sqrt(1 + g * g)
    st = 1040.0 - vi * sg / (1 - p.alignment.curvature(1040.0) * ui)
    assert pt3[2] == pytest.approx(p.profile.elev(st), abs=1e-9)


def test_section_v_refuses_a_point_at_the_centre_of_curvature():
    c = curved("L", "L", radius=60.0)
    with pytest.raises(ValueError, match="curvature"):
        section_v(c.path, 1040.0, 61.0, lambda st: 100.0)


def test_a_path_beyond_the_centre_of_curvature_is_refused():
    # the outer shoulder is 41 ft out: parse runs validate
    with pytest.raises(ValueError, match=r"10\+00.*centre of curvature"):
        curved("L", "L", radius=40.0)


def test_edge_points_are_found_in_their_own_planes():
    road = Profile(grade(100.0, pct=8.0)["curves"])
    c = corridor(path(profile=grade(99.51, pct=8.0)), prof=road)
    p = c.path
    sf = surface(c, 1500.0)
    g = 0.08
    sg = g / math.sqrt(1 + g * g)
    u, v = sf.outer
    pt3 = survey_point(p.alignment, p.road_profile, 1500.0, u, v)
    st = 1500.0 - v * sg
    assert pt3[2] == pytest.approx(p.profile.elev(st) + p.cross_slope * p.width,
                                   abs=1e-9)


def test_cg_is_the_cosine_of_the_road_s_grade():
    road = Profile(grade(100.0, pct=8.0)["curves"])
    c = corridor(path(profile=grade(99.51, pct=8.0)), prof=road)
    assert surface(c, 1500.0).cg == pytest.approx(1 / math.sqrt(1.0064), abs=1e-12)


def test_cos_theta_with_a_drifting_separation():
    # the separation grows 0.2 ft per ft: the path's centre drifts 0.2 sideways
    # for each foot on: cos theta = 1 / sqrt(1.04) on a level road and path
    c = corridor(path(separation=[[1000, 10.0], [2000, 210.0]]))
    assert cos_theta(c, 1500.0) == pytest.approx(1 / math.sqrt(1.04), rel=1e-9)


def test_cos_theta_at_state_plane_coordinates_matches_a_small_origin():
    # the chord over s +/- 0.01 is a difference of coordinates near 1e6 ft:
    # its round-off is about 1e-10 / h, far inside 1e-7
    small = curved("L", "L", 60.0, road_pct=8.0, path_pct=-6.0)
    big = curved("L", "L", 60.0, road_pct=8.0, path_pct=-6.0,
                 origin=(2.0e6, 6.8e6))
    for s in (1010.0, 1040.0, 1080.0):
        assert cos_theta(big, s) == pytest.approx(cos_theta(small, s), abs=1e-7)


# -- Task 5: the strip, and the path's side of the section -------------------

from bimforge.author.corridor.path import TOP_POINTS, side_count, strip_count  # noqa: E402
from bimforge.author.corridor.section import (SIDE_SAMPLES, NoDaylight,  # noqa: E402
                                              needs_wall, resolve)


def level(h):
    """Level ground h ft above the road's profile grade line."""
    return lambda s, u, v: h - v


def on(line, xy):
    return any(abs(u - xy[0]) < 1e-6 and abs(v - xy[1]) < 1e-6 for u, v in line)


def test_point_counts():
    c = corridor()
    assert strip_count(c) == 2 * SIDE_SAMPLES + GROUND_SAMPLES
    assert side_count(c) == strip_count(c) + TOP_POINTS - 1 + SIDE_SAMPLES - 1


def test_a_path_level_with_the_road_takes_a_strip_slope():
    c = corridor()
    sec = resolve(c, 1500.0, level(-5.0))
    ps, side = sec.path, sec.sides["L"]
    assert (ps.strip, side.kind, side.guarded) == ("slope", "path", False)
    assert ps.ratio == pytest.approx(8.0 / 1.30)
    assert len(side.line) == side_count(c) == sec.count("L")
    assert side.line[0] == pt((17.0, -1.89))
    for xy in ((25.0, -0.59), (26.99, -0.4905), (27.0, -1.24), (39.0, -1.48),
               (39.01, -0.7305), (41.0, -0.83)):
        assert on(side.line, xy), xy                     # the path's top
    assert side.line[-1] == pt((49.34, -5.0))            # 2:1 from o
    want = [(27, -0.49), (39, -0.73), (39, -0.98), (27, -0.74)]
    assert [x for xy in ps.courses[0] for x in xy] == pytest.approx(
        [x for xy in want for x in xy])
    # the road's other side is V1.1's: 2:1 from its hinge to the ground
    assert sec.sides["R"].line[-1] == pt((-23.22, -5.0))
    assert sec.count("R") == SIDE_SAMPLES
    assert len(sec.earthwork_line()) == (
        side_count(c) + 2 + 2 + SIDE_SAMPLES - 1)        # + the road's subgrade


def test_a_path_3_ft_below_takes_a_slope_that_fits():
    sec = resolve(corridor(path(profile=grade(96.51))), 1500.0, level(-5.0))
    assert sec.path.strip == "slope"
    assert sec.path.ratio == pytest.approx(8.0 / 1.70)


def test_a_steep_strip_below_a_higher_road_is_guarded():
    p = path(separation=[[1000, 20.0]], profile=grade(93.51))
    side_slopes = dict(BASE["section"]["side_slopes"], fill={"ratio": 4.0})
    c = corridor(p, section=dict(BASE["section"], side_slopes=side_slopes))
    sec = resolve(c, 1500.0, level(-5.0))
    assert (sec.path.strip, sec.sides["L"].guarded) == ("guarded", True)
    assert sec.path.ratio == pytest.approx(14.06 / 5.706)
    assert on(sec.sides["L"].line, (17.01, -0.491))
    assert on(sec.sides["L"].line, (20.94, -0.884))


def test_a_path_12_ft_below_needs_a_wall_at_the_road_s_hinge():
    p = path(profile=grade(87.51))
    c = corridor(p)
    assert needs_wall(c, 1500.0, "L", level(-5.0), location="strip") == "strip-road"
    with pytest.raises(NoDaylight, match=r"station 15\+00\.00: the L strip between "
                       r"the road and the path does not fit at 2:1 or flatter"):
        resolve(c, 1500.0, level(-5.0))
    c = corridor(p, walls="auto").with_walls(
        [Gap(1400.0, 1600.0, "wall", "L", None, auto="strip-road")])
    sec = resolve(c, 1500.0, level(-5.0))
    assert sec.path.strip == "wall-road"
    line = sec.sides["L"].line
    assert line[0] == pt((17.0, -1.89))
    assert on(line, (17.01, -12.59)) and on(line, (25.0, -12.59))


def test_a_path_12_ft_above_needs_a_wall_at_its_shoulder():
    p = path(profile=grade(111.51))
    assert needs_wall(corridor(p), 1500.0, "L", level(-5.0),
                      location="strip") == "strip-path"
    c = corridor(p, walls="auto").with_walls(
        [Gap(1400.0, 1600.0, "wall", "L", None, auto="strip-path")])
    sec = resolve(c, 1500.0, level(-5.0))
    assert sec.path.strip == "wall-path"
    assert on(sec.sides["L"].line, (24.99, -1.89))
    assert on(sec.sides["L"].line, (25.0, 11.41))


def test_a_path_drifted_out_leaves_natural_ground_between():
    c = corridor(path(separation=[[1000, 10.0], [1100, 60.0]]))
    sec = resolve(c, 1150.0, level(-3.0))
    assert sec.path.strip == "ground"
    line = sec.sides["L"].line
    assert on(line, (19.22, -3.0)) and on(line, (70.18, -3.0))
    between = [(u, v) for u, v in line if 19.22 + 1e-6 < u < 70.18 - 1e-6]
    assert len(between) >= 8 and all(v == pytest.approx(-3.0) for _u, v in between)


def test_without_the_path_the_side_pads_to_the_path_s_count():
    c = corridor(path(stations=[1200, 1800]))
    sec = resolve(c, 1100.0, level(-5.0))
    assert sec.path is None and sec.sides["L"].kind == "fill"
    assert sec.count("L") == side_count(c)
    assert len(sec.earthwork_line()) == len(
        resolve(c, 1500.0, level(-5.0)).earthwork_line())


# -- Task 5 review follow-ups ------------------------------------------------

from bimforge.author.corridor.path import GROUND_SAMPLES, _fixed  # noqa: E402


@pytest.mark.parametrize("side, sign", [("L", 1.0), ("R", -1.0)])
def test_a_slope_strip_mirrors(side, sign):
    c = corridor(path(side=side))
    sec = resolve(c, 1500.0, level(-5.0))
    assert sec.path.strip == "slope"
    assert sec.path.ratio == pytest.approx(8.0 / 1.30)
    line = sec.sides[side].line
    assert len(line) == side_count(c) == sec.count(side)
    assert line[0] == pt((sign * 17.0, -1.89))
    assert on(line, (sign * 25.0, -0.59)) and on(line, (sign * 41.0, -0.83))
    assert line[-1] == pt((sign * 49.34, -5.0))


@pytest.mark.parametrize("side, sign", [("L", 1.0), ("R", -1.0)])
def test_natural_ground_between_mirrors(side, sign):
    c = corridor(path(side=side, separation=[[1000, 10.0], [1100, 60.0]]))
    sec = resolve(c, 1150.0, level(-3.0))
    assert (sec.path.strip, sec.path.ratio) == ("ground", None)
    line = sec.sides[side].line
    assert len(line) == side_count(c)
    assert on(line, (sign * 19.22, -3.0)) and on(line, (sign * 70.18, -3.0))
    between = [(u, v) for u, v in line if 19.22 + 1e-6 < sign * u < 70.18 - 1e-6]
    assert len(between) == GROUND_SAMPLES
    assert all(v == pytest.approx(-3.0) for _u, v in between)


def test_natural_ground_between_two_cuts_keeps_both_ditches():
    # the ground 3 ft above the grade line, the path 60 ft out (q at 75):
    # the road's ditch 1.5 below its hinge, (20, -3.39) to (24, -3.39), then
    # 2:1 up 6.39 to (36.78, 3); the path's from q (75, -0.59) mirrored:
    # (72, -2.09), (68, -2.09), up 5.09 to (57.82, 3)
    c = corridor(path(separation=[[1000, 60.0]]))
    sec = resolve(c, 1500.0, level(3.0))
    assert sec.path.strip == "ground"
    line = sec.sides["L"].line
    for xy in ((20.0, -3.39), (24.0, -3.39), (36.78, 3.0), (57.82, 3.0),
               (68.0, -2.09), (72.0, -2.09), (75.0, -0.59)):
        assert on(line, xy), xy
    between = [(u, v) for u, v in line if 36.78 + 1e-6 < u < 57.82 - 1e-6]
    assert len(between) == GROUND_SAMPLES
    assert all(v == pytest.approx(3.0) for _u, v in between)


def test_a_strip_at_exactly_the_max_ratio_fits():
    # the path at 102.21: q (25, 2.11), 4.00 above the hinge over 8: 2.0:1
    sec = resolve(corridor(path(profile=grade(102.21))), 1500.0, level(-5.0))
    assert sec.path.strip == "slope"
    assert sec.path.ratio == pytest.approx(2.0)


def test_a_strip_just_steeper_than_the_max_ratio_needs_a_wall():
    # 0.01 higher: 8 / 4.01, steeper than 2:1 below the path
    c = corridor(path(profile=grade(102.22)))
    assert needs_wall(c, 1500.0, "L", level(-5.0), location="strip") == "strip-path"
    with pytest.raises(NoDaylight) as exc:
        resolve(c, 1500.0, level(-5.0))
    assert exc.value.kind == "strip-path"


def test_a_strip_level_with_the_hinge_has_no_ratio():
    # the path at 98.21: q (25, -1.89), level with the road's hinge
    sec = resolve(corridor(path(profile=grade(98.21))), 1500.0, level(-5.0))
    assert (sec.path.strip, sec.path.ratio, sec.sides["L"].ratio) == (
        "slope", None, None)


def test_a_rail_past_a_higher_path_asks_for_the_path_s_wall():
    # the path at 105 (q at 4.9), a rail on the road: the road's widening
    # behind it, and the rest up to q steeper than 2:1: the wall is the
    # path's, at q
    c = corridor(path(profile=grade(105.0)))
    assert needs_wall(c, 1500.0, "L", level(-5.0), rail=True,
                      location="strip") == "strip-path"
    with pytest.raises(NoDaylight) as exc:
        resolve(c, 1500.0, level(-5.0), rail=("L",))
    assert exc.value.kind == "strip-path"


@pytest.mark.parametrize("ground, kind", [(-200.0, "path-fill"),
                                          (200.0, "path-cut")])
def test_the_path_s_outer_slope_asks_for_its_own_wall(ground, kind):
    # 150 ft daylight limit: the outer slope from o finds no ground
    c = corridor()
    assert needs_wall(c, 1500.0, "L", level(ground), location="outer") == kind


def test_on_an_approach_a_steep_strip_is_taken_as_it_is():
    # 13+90: 2.35 ft out, q 0.35 ft past the edge (17.35, -0.62); the hinge
    # 1.27 ft higher: 0.28:1, taken (the deck's barrier layout stands there)
    c = corridor(deck_path(), gaps=GAP)
    assert needs_wall(c, 1390.0, "L", level(-5.0), location="strip") is None
    sec = resolve(c, 1390.0, level(-5.0))
    assert (sec.path.strip, sec.sides["L"].guarded) == ("slope", False)
    assert sec.path.ratio == pytest.approx(0.35 / 1.27)


def test_at_the_deck_a_rail_s_widening_has_no_room_and_the_strip_does_not_fold():
    # 14+00, the deck's end: 1.5 ft out, q 0.01 ft past the edge (17.01,
    # -0.5945). A rail runs past (the bridge rail): its widening has no room
    # in the strip, so it collapses onto the hinge and the strip runs
    # straight up to q; it does not climb to the finished grade at 17.01 and
    # come back down to q on the same offset (a fold the earthwork's columns
    # cannot close)
    c = corridor(deck_path(), gaps=GAP)
    sec = resolve(c, 1400.0, level(-5.0), rail=("L",))
    line = sec.sides["L"].line[:strip_count(c)]
    assert line[0] == pt((17.0, -1.89)) and line[-1] == pt((17.01, -0.5945))
    assert all(b[0] >= a[0] - 1e-12 for a, b in zip(line, line[1:]))
    # the line runs one way only: no point is above q
    assert max(v for _u, v in line) == pytest.approx(-0.5945)
    # (q stays 0.01 ft past the edge until the separation passes 2.01 ft.)
    # At 15+10, 2.35 ft out, there is room, and the widening is as it was
    sec = resolve(c, 1510.0, level(-5.0), rail=("L",))
    assert sec.sides["L"].line[1] == pt((17.01, -0.491))


def test_gap_strip_and_carries():
    def gap(auto):
        return Gap(1400.0, 1600.0, "wall", "L", None, auto=auto)
    assert [gap(a).strip for a in ("strip-road", "strip-path", "path-fill",
                                   "fill", None)] == [True, True, False, False,
                                                      False]
    assert [gap(a).carries for a in ("strip-road", "strip-path", "path-fill",
                                     "path-cut", "fill", "cut", None)] == [
        "path", "path", "path", "path", "road", "road", "road"]


def test_corridor_wall_reads_strip_and_outer_walls_apart():
    c = corridor(path(profile=grade(87.51)), walls="auto").with_walls(
        [Gap(1400.0, 1600.0, "wall", "L", None, auto="strip-road")])
    assert c.wall("L", 1500.0) is None
    assert c.wall("L", 1500.0, strip=True).auto == "strip-road"
    assert c.wall("L", 1700.0, strip=True) is None


def test_fixed_cuts_one_segment_evenly():
    pts = [(0.0, 0.0), (1.0, 0.0), (4.0, 0.0)]
    got = _fixed(pts, 5, 1500.0)
    assert [x for xy in got for x in xy] == pytest.approx(
        [0.0, 0.0, 1.0, 0.0, 2.0, 0.0, 3.0, 0.0, 4.0, 0.0])
    got = _fixed(pts, 5, 1500.0, seg=0)
    assert [x for xy in got for x in xy] == pytest.approx(
        [0.0, 0.0, 1 / 3, 0.0, 2 / 3, 0.0, 1.0, 0.0, 4.0, 0.0])


def test_fixed_names_the_station_when_there_are_too_many_points():
    with pytest.raises(ValueError, match=r"station 15\+00\.00: the path's strip "
                                         r"has 5 points, more than its 3"):
        _fixed([(float(i), 0.0) for i in range(5)], 3, 1500.0)


from bimforge.author.corridor import earthwork  # noqa: E402
from bimforge.author.corridor.ground import PlaneGround  # noqa: E402


def fill_area(c, ground, s=1500.0):
    """The section's fill area at s: trapezoids along its earthwork line,
    down to the ground (earthwork tests' signed_area, negated)."""
    def dz(st, u, v):
        n, e, z = survey_point(AL, PROF, st, u, v)
        return ground.z(n, e) - z
    sec = resolve(c, s, dz)
    d = [(u, dz(s, u, v)) for u, v in sec.earthwork_line()]
    return -sum(0.5 * (d0 + d1) * abs(u1 - u0) for (u0, d0), (u1, d1) in zip(d, d[1:]))


def prism_fill(c, ground, s0=1400.0, s1=1500.0):
    """The fill earthwork.strip builds between two sections."""
    def survey(st, u, v):
        return survey_point(AL, PROF, st, u, v)

    def dz(st, u, v):
        n, e, z = survey(st, u, v)
        return ground.z(n, e) - z
    _cut, fill, _cd, _fd = earthwork.strip("t", resolve(c, s0, dz), resolve(c, s1, dz),
                                           survey, ground.z, None)
    return sum(p.volume_cf for p in fill)


def test_the_section_s_fill_is_its_hand_polygon():
    c = corridor()
    ground = PlaneGround(95.0)
    assert fill_area(c, ground) == pytest.approx(234.0435, abs=1e-6)
    assert prism_fill(c, ground) == pytest.approx(23404.35, rel=1e-9)


def test_with_natural_ground_between_it_is_the_road_s_plus_the_path_s():
    ground = PlaneGround(97.0)
    with_path = corridor(path(separation=[[1000, 10.0], [1100, 60.0]]))
    road = parse(copy.deepcopy(BASE), 1000.0, 2000.0)
    assert fill_area(road, ground) == pytest.approx(50.3342, abs=1e-6)
    assert fill_area(with_path, ground) == pytest.approx(50.3342 + 39.5495, abs=1e-6)


# -- Task 8: a course's centroid line on its own grade -----------------------

from bimforge.author.corridor.loft import StationLoft, centroid_path, pappus  # noqa: E402
from bimforge.author.gate import FORMULA_TOLERANCE  # noqa: E402


def _course_box(c, k, stations):
    """(exact volume, PathLength x Width x Thickness) of path course k as
    the family lofts it over `stations`."""
    al, prof = c.path.alignment, c.path.road_profile
    rings = [course_rings(c.path, surface(c, s))[k] for s in stations]
    got = centroid_path([StationLoft("t", al, prof, None, stations, rings)])
    return got.volume_cf, got.path_ft * c.path.width * c.path.courses[k].thickness


def test_a_path_2_percent_off_the_road_s_grade_is_its_path_box():
    road = Profile(grade(100.0, pct=3.0)["curves"])
    c = corridor(path(profile=grade(99.51, pct=5.0)), prof=road)
    for k in (0, 1):
        vol, box = _course_box(c, k, [1400.0 + 25.0 * i for i in range(5)])
        assert abs(box - vol) <= FORMULA_TOLERANCE * vol
    want = (1 + 0.03 * 0.05) / math.sqrt(1.0009 * 1.0025)
    # without the correction the box misses by 1 / cos(theta) - 1
    assert 1.0 / want - 1.0 == pytest.approx(1.9938e-4, rel=1e-3)


def test_a_path_on_a_graded_curve_is_its_path_box():
    # a 500 ft right curve with the road at 7 %, the path on the right at
    # 3 %, level with the plain strip at 11+50 (99.48 + 0.07 x 150 = 109.98,
    # so 105.48 at 10+00): 1.6 ft above it at 11+10, 1.6 below at 11+90, its
    # centre about 33 ft out, its bands inside the curve. theta takes in
    # the grade difference and the twist on the curve together; pappus's
    # line, parallel to the road's grade, misses by 7.0e-4, about the
    # grades' 3.8 % difference squared over 2.
    # The arc is stationed at its length on purpose: 500 x 0.2 rad = 100 ft
    al = Alignment({"station": 1000.0, "northing": 0.0, "easting": 0.0},
                   [{"kind": "tangent", "bearing": "N 0-0-0 E", "length": 100.0},
                    {"kind": "curve", "delta": "11-27-32.961249419",
                     "radius": 500.0, "turn": "R", "length": 100.0},
                    {"kind": "tangent", "bearing": "N 11-27-32.961249419 E",
                     "length": 800.0}],
                   name="C")
    road = Profile(grade(100.0, pct=7.0)["curves"])
    params = copy.deepcopy(BASE)
    params["path"] = path(side="R", profile=grade(105.48, pct=3.0))
    c = parse(params, 1000.0, 2000.0, alignment=al, profile=road)
    stations = [1110.0 + 5.0 * i for i in range(17)]
    vol, box = _course_box(c, 1, stations)
    assert abs(box - vol) <= FORMULA_TOLERANCE * vol
    rings = [course_rings(c.path, surface(c, s))[1] for s in stations]
    held = pappus([StationLoft("t", al, road, None, stations, rings)])
    held_box = held.path_ft * c.path.width * c.path.courses[1].thickness
    assert abs(held_box - vol) > 100 * FORMULA_TOLERANCE * vol


def test_a_strip_wall_s_fill_is_its_hand_polygon():
    # the path 12 ft below (87.51), the wall at the road's hinge, the ground
    # at 85 (v = -15), so the fill is the line's height h = v + 15 over u.
    # The road: subgrade (0, -1.40), (+-12, -1.64), hinge (+-17, -1.89); its
    # R fill 2:1 down 13.11 to (-43.22, -15). The wall from the hinge to
    # (17.01, -12.59), level to q (25, -12.59); the inner shoulder up 5 %
    # to (26.99, -12.4905), the courses' 0.75 down to (27, -13.24) and
    # (39, -13.48), up to (39.01, -12.7305), the outer shoulder to
    # (41, -12.83), 2:1 down 2.17 to (45.34, -15). Trapezoids, R to L:
    #   26.22 x 6.555 = 171.8721      5 x 13.235 = 66.175 (twice)
    #   12 x 13.48 = 161.76 (twice)    0.01 x 7.76 = 0.0776 (the wall)
    #   7.99 x 2.41 = 19.2559         1.99 x 2.45975 = 4.8949025
    #   0.01 x 2.13475 = 0.0213475    12 x 1.64 = 19.68
    #   0.01 x 1.89475 = 0.0189475    1.99 x 2.21975 = 4.4173025
    #   4.34 x 1.085 = 4.7089                             total 680.817
    c = corridor(path(profile=grade(87.51)), walls="auto").with_walls(
        [Gap(1400.0, 1600.0, "wall", "L", None, auto="strip-road")])
    ground = PlaneGround(85.0)
    assert resolve(c, 1500.0, level(-15.0)).path.strip == "wall-road"
    assert fill_area(c, ground) == pytest.approx(680.817, abs=1e-6)


# -- Task 9: a curve's ends ----------------------------------------------------

#: a 100 ft left curve of radius 500 from 11+00 (its PC) to 12+00 (its PT),
#: stationed at its length (500 x 0.2 rad)
PC_AL = Alignment({"station": 1000.0, "northing": 0.0, "easting": 0.0},
                  [{"kind": "tangent", "bearing": "N 0-0-0 E", "length": 100.0},
                   {"kind": "curve", "delta": "11-27-32.961249419",
                    "radius": 500.0, "turn": "L", "length": 100.0},
                   {"kind": "tangent", "bearing": "N 11-27-32.961249419 W",
                    "length": 800.0}], name="C")


def pc_corridor():
    """The road at 7 %, the path on the left (inside the curve) at 3 %."""
    road = Profile(grade(100.0, pct=7.0)["curves"])
    params = copy.deepcopy(BASE)
    params["path"] = path(profile=grade(99.51, pct=3.0))
    return parse(params, 1000.0, 2000.0, alignment=PC_AL, profile=road)


def test_curvature_toward_reads_one_side_of_a_segment_end():
    k = 1.0 / 500.0
    # point_az's rule at a join: the segment before it
    assert (PC_AL.curvature(1100.0), PC_AL.curvature(1200.0)) == (0.0, k)
    assert (PC_AL.curvature(1100.0, toward=1.0),
            PC_AL.curvature(1100.0, toward=-1.0)) == (k, 0.0)
    assert (PC_AL.curvature(1200.0, toward=1.0),
            PC_AL.curvature(1200.0, toward=-1.0)) == (0.0, k)
    # inside a segment, or within its 1e-6 ft of a join, as before
    assert PC_AL.curvature(1150.0, toward=-1.0) == k
    assert PC_AL.curvature(1100.0 + 5e-7, toward=-1.0) == 0.0
    assert PC_AL.curvature(1000.0, toward=-1.0) == 0.0     # the POB


def test_cos_theta_toward_takes_the_path_s_tangent_on_one_side_of_the_pc():
    # on the tangent the path's centre runs at 3 % and the road at 7 %:
    # cos theta = (1 + 0.07 x 0.03) / sqrt(1.0049 x 1.0009). Inside the
    # curve it is steeper along its own length, 0.03 / (1 - 33 / 500),
    # nearer the road's 7 %, so theta steps down at the PC: each side's
    # value is the one a chord wholly on that side reads. The two-sided
    # chord across the PC is neither: its ends' points are solved with
    # different curvatures (section_v), a step it reads as a slope
    c = pc_corridor()
    tangent = (1 + 0.07 * 0.03) / math.sqrt(1.0049 * 1.0009)
    before, after = cos_theta(c, 1100.0, toward=-1.0), cos_theta(c, 1100.0, toward=1.0)
    assert before == pytest.approx(tangent, abs=1e-10)
    assert before == pytest.approx(cos_theta(c, 1099.9), abs=1e-10)
    assert after == pytest.approx(cos_theta(c, 1100.1), abs=1e-9)
    assert after - before > 5e-5
    across = cos_theta(c, 1100.0)
    assert min(abs(across - before), abs(across - after)) > 1e-5
    # at the PT the other way round (inside the curve theta drifts a
    # little as the path falls away from the road and the plane's lean
    # reaches further)
    assert cos_theta(c, 1200.0, toward=-1.0) == pytest.approx(
        cos_theta(c, 1199.95), abs=1e-9)
    assert cos_theta(c, 1200.0, toward=1.0) == pytest.approx(tangent, abs=1e-10)
    # away from a segment end the one-sided chord agrees with the two-sided
    for toward in (-1.0, 1.0):
        assert cos_theta(c, 1150.0, toward=toward) == pytest.approx(
            cos_theta(c, 1150.0), abs=1e-9)


def test_a_surface_toward_one_side_of_the_pc_is_that_side_s():
    # its points are solved with that side's curvature, its depth read
    # with that side's theta (constant on each side: a chord 0.05 ft off)
    c = pc_corridor()
    for toward in (-1.0, 1.0):
        sf, ref = surface(c, 1100.0, toward=toward), surface(c, 1100.0 + toward * 1e-5)
        assert sf.inner == pytest.approx(ref.inner, abs=1e-6)
        assert sf.outer == pytest.approx(ref.outer, abs=1e-6)
        assert sf.cos_theta == pytest.approx(
            cos_theta(c, 1100.0 + toward * 0.05), abs=1e-9)
    assert abs(surface(c, 1100.0, toward=1.0).inner[1]
               - surface(c, 1100.0, toward=-1.0).inner[1]) > 1e-4


# -- Task 13: path gaps -------------------------------------------------------
from bimforge.author.corridor.path import PathGap  # noqa: E402


def test_a_path_gap_takes_the_path_off_the_section():
    c = corridor(path(gaps=[{"from": 1400, "to": 1600, "kind": "structure"}]))
    assert c.path.gaps == (PathGap(1400.0, 1600.0),)
    # built up to 1 ft outside each end; the road's own section inside
    assert [c.path_at(s) for s in (1399.0, 1399.5, 1400.0, 1500.0, 1600.0,
                                   1601.0)] == [True, False, False, False, False, True]
    assert {1399.0, 1400.0, 1600.0, 1601.0} <= set(c.stations(1375.0, 1625.0))


def test_inside_a_path_gap_the_section_is_the_road_s_alone():
    c = corridor(path(gaps=[{"from": 1400, "to": 1600, "kind": "structure"}]))
    road = parse(dict(copy.deepcopy(BASE), guardrail={"design_speed_mph": 45}),
                 1000.0, 2000.0)                      # the same guardrail rule
    sec, alone = resolve(c, 1500.0, level(-5.0)), resolve(road, 1500.0, level(-5.0))
    assert sec.path is None
    assert sec.sides["L"].line == alone.sides["L"].line
    ground = PlaneGround(95.0)
    assert fill_area(c, ground) == pytest.approx(fill_area(road, ground), abs=1e-9)


def test_a_path_gap_over_a_road_gap_waives_the_deck_and_the_approach():
    # 10 ft from the road at the bridge's ends and 0.03 ft off the deck's
    # line: refused without the path gap, built with it
    with pytest.raises(ValueError, match=r"is not deck_separation_ft"):
        corridor(path(), gaps=GAP)
    c = corridor(path(gaps=[{"from": 1380, "to": 1520, "kind": "structure"}]), gaps=GAP)
    assert approaches(c) == []


def test_inside_a_path_gap_the_separation_is_not_held_to_5_ft():
    sep = [[1000, 10.0], [1450, 10.0], [1500, 3.0], [1550, 3.0], [1600, 10.0]]
    with pytest.raises(ValueError, match=r"3\.00 ft at 15\+00\.00 is under the 5 ft"):
        corridor(path(separation=sep))
    corridor(path(separation=sep, gaps=[{"from": 1440, "to": 1610, "kind": "structure"}]))


@pytest.mark.parametrize("gaps, match", [
    ([{"from": 900, "to": 1100, "kind": "structure"}],
     r"path\.gaps\[0\]: 9\+00\.00 to 11\+00\.00 is outside the path's stations"),
    ([{"from": 1200, "to": 1400, "kind": "structure"},
      {"from": 1300, "to": 1500, "kind": "structure"}],
     r"path\.gaps: 12\+00\.00 to 14\+00\.00 overlaps 13\+00\.00 to 15\+00\.00"),
    ([{"from": 1200, "to": 1400, "kind": "wall"}],
     r"path\.gaps\[0\]: kind 'wall' is not 'structure'"),
    ([{"from": 1400, "to": 1200, "kind": "structure"}],
     r"path\.gaps\[0\]: 'to' must be past 'from'"),
])
def test_bad_path_gaps_are_refused(gaps, match):
    with pytest.raises(ValueError, match=match):
        corridor(path(gaps=gaps))


def test_a_road_gap_end_within_a_foot_of_a_path_gap_is_waived_as_its_separation_is():
    # the road gap ends 0.5 ft past the path gap's end: no approach and no
    # deck meeting there, as no separation check
    gap = [{"from": 1400, "to": 1520.5, "kind": "structure"}]
    with pytest.raises(ValueError, match=r"is not deck_separation_ft"):
        corridor(path(gaps=[{"from": 1380, "to": 1519, "kind": "structure"}]), gaps=gap)
    c = corridor(path(gaps=[{"from": 1380, "to": 1520, "kind": "structure"}]), gaps=gap)
    assert approaches(c) == []


def test_a_road_gap_end_exactly_a_foot_outside_a_path_gap_keeps_its_approach():
    # the path's section is built at that station: the deck is met there and
    # the approach leads to it; the separation is the deck's, not 5 ft
    sep = [[1000, 10.0], [1300, 10.0], [1400, 1.5], [1501, 1.5], [1601, 10.0]]
    c = corridor(deck_path(separation=sep, gaps=[{"from": 1380, "to": 1500,
                                                  "kind": "structure"}]),
                 gaps=[{"from": 1400, "to": 1501, "kind": "structure"}])
    assert approaches(c) == [(1501.0, 1601.0, 1501.0)]
    with pytest.raises(ValueError, match=r"is not deck_separation_ft"):
        corridor(path(separation=[[1000, 10.0]],
                      gaps=[{"from": 1380, "to": 1500, "kind": "structure"}]),
                 gaps=[{"from": 1400, "to": 1501, "kind": "structure"}])


def test_a_road_gap_start_exactly_a_foot_outside_a_path_gap_keeps_its_approach():
    sep = [[1000, 10.0], [1399, 10.0], [1499, 1.5], [1620, 1.5], [1650, 1.5],
           [1750, 10.0]]
    c = corridor(deck_path(separation=sep, gaps=[{"from": 1500, "to": 1620,
                                                  "kind": "structure"}]),
                 gaps=[{"from": 1499, "to": 1650, "kind": "structure"}])
    assert approaches(c) == [(1399.0, 1499.0, 1499.0), (1650.0, 1750.0, 1650.0)]


from bimforge.author.corridor.path import Equestrian  # noqa: E402

TREAD = {"courses": [{"name": "EQ-DG", "type": "PAVEMENT", "thickness": 0.33}]}


def test_an_equestrian_tread_takes_its_defaults():
    eq = corridor(path(equestrian=TREAD)).path.equestrian
    assert isinstance(eq, Equestrian)
    assert (eq.width, eq.buffer, eq.clear, eq.cross_slope) == (8.0, 6.0, 3.0, -0.02)
    assert (eq.fence, eq.fence_height, eq.rail_height) == (False, 4.5, 4.5)
    assert eq.depth() == pytest.approx(0.33)
    assert corridor().path.equestrian is None


@pytest.mark.parametrize("over, match", [
    ({"width": 0}, r"path\.equestrian\.width: must be positive"),
    ({"buffer": 1.5}, r"path\.equestrian\.buffer: 1\.5 ft is narrower than "
                      r"path\.shoulder\.width \(2 ft\)"),
    ({"clear_ft": 0}, r"path\.equestrian\.clear_ft: must be positive"),
    ({"fence_height_ft": 0}, r"path\.equestrian\.fence_height_ft: must be positive"),
    ({"rail_height_ft": 0}, r"path\.equestrian\.rail_height_ft: must be positive"),
    ({"courses": [{"name": "EQ-DG", "type": "PAVEMENT", "thickness": 0}]},
     r"path\.equestrian\.courses\[0\]\.thickness: must be positive"),
    ({"courses": []}, r"path\.equestrian\.courses: needs at least one course"),
    ({"fence": "yes"}, r"path\.equestrian\.fence: true or false"),
    ({"horses": 2}, r"path\.equestrian: unknown keys \['horses'\]"),
])
def test_bad_equestrian_params_are_refused(over, match):
    with pytest.raises(ValueError, match=match):
        corridor(path(equestrian=dict(TREAD, **over)))


def test_a_tread_without_courses_or_not_a_mapping_is_refused():
    with pytest.raises(ValueError, match=r"path\.equestrian\.courses: needs at least"):
        corridor(path(equestrian={}))
    with pytest.raises(ValueError, match=r"path\.equestrian: a mapping"):
        corridor(path(equestrian=[TREAD]))


def test_an_unusual_tread_is_not_an_error():
    # USFS-EDG's figures are guidance: only the buffer's floor is a "shall"
    eq = corridor(path(equestrian=dict(TREAD, buffer=2.0, width=4.0, clear_ft=1.0,
                                       cross_slope=0.08))).path.equestrian
    assert (eq.buffer, eq.width, eq.clear, eq.cross_slope) == (2.0, 4.0, 1.0, 0.08)
