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
