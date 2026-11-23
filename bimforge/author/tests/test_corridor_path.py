"""road-corridor V1.2 part C: the shared-use path's params, geometry and
section, hand-worked on a level road on a tangent (P.6)."""
import copy
import math

import pytest

from bimforge.author.alignment import Alignment, Profile
from bimforge.author.corridor.params import Gap, Guard, parse

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
    ({"stations": [1500, 1200]}, r"path\.stations: 'to' must be past 'from'"),
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
