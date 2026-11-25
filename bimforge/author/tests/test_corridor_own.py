"""road-corridor V1.2 part C: own stretches, where the path leaves the road
(P.6)."""
import copy
import math
import re

import pytest

from bimforge.author.alignment import Alignment, sta
from bimforge.author.corridor.params import parse
from bimforge.author.corridor import own as own_mod
from bimforge.author.tests.test_corridor_path import (BASE, PROF, TREAD, corridor,
                                                      grade, level, path, pt)

#: a bump away from the road and back: 20 deg right, 40 left, 20 right on
#: 300 ft radii; it advances 4 R sin 20 deg = 410.42417 ft along the road
BUMP = [{"kind": "curve", "delta": "20-0-0", "radius": 300.0, "turn": "R",
         "length": 104.71976},
        {"kind": "curve", "delta": "40-0-0", "radius": 300.0, "turn": "L",
         "length": 209.43951},
        {"kind": "curve", "delta": "20-0-0", "radius": 300.0, "turn": "R",
         "length": 104.71976}]
REJOIN = 1510.424


def flat(length, elev=99.51):
    return {"curves": [{"bvc_station": 0.0, "bvc_elev": elev, "g_in_pct": 0.0,
                        "g_out_pct": 0.0, "length_ft": length,
                        "evc_station": length, "evc_elev": elev}]}


def own_path(run=BUMP, to=REJOIN, elev=99.51, separation=20.0, **over):
    # the run's length, or a foot where a bad run has none (it is refused
    # before the profile is read)
    length = sum(x.get("length", 0.0) for x in run if isinstance(x, dict)) or 1.0
    own = dict({"from": 1100, "to": to, "run": copy.deepcopy(run),
                "profile": flat(length, elev)}, **over)
    sep = separation if isinstance(separation, list) else [[1000, separation]]
    return path(side="R", separation=sep, own=[own])


def test_the_hand_over_point_and_heading_are_derived():
    (own,) = corridor(own_path()).path.own
    assert (own.index, own.start, own.end) == (1, 1100.0, REJOIN)
    pob = own.alignment.pob
    assert (pob["station"], pob["northing"], pob["easting"], pob["azimuth"]) == (
        0.0, pytest.approx(100.0), pytest.approx(43.0), pytest.approx(0.0))
    assert own.alignment.name == "T path 1"
    assert own.length == pytest.approx(418.87903)
    n, e = own.alignment.end_point
    assert (n, e) == (pytest.approx(100.0 + 410.42417, abs=1e-4),
                      pytest.approx(43.0, abs=1e-4))
    assert own.profile.elev(200.0) == pytest.approx(99.51) and own.gaps == ()


def test_own_stretches_are_numbered_by_start_station():
    # a straight own stretch, the road's way 100 ft, after the bump but
    # given before it: it is own 2, and its alignment "T path 2"
    p = own_path()
    p["own"].insert(0, {"from": 1600, "to": 1700, "profile": flat(100.0),
                        "run": [{"kind": "tangent", "bearing": "N 0-0-0 E",
                                 "length": 100.0}]})
    got = corridor(p).path.own
    assert [(o.index, o.entry, o.start, o.alignment.name) for o in got] == [
        (1, 1, 1100.0, "T path 1"), (2, 0, 1600.0, "T path 2")]


def test_an_entry_is_named_by_its_place_in_the_list():
    # the bump is own 1 by station but path.own[1] by its place in the list
    p = own_path(to=REJOIN + 0.2)
    p["own"].insert(0, {"from": 1600, "to": 1700, "profile": flat(100.0),
                        "run": [{"kind": "tangent", "bearing": "N 0-0-0 E",
                                 "length": 100.0}]})
    with pytest.raises(ValueError, match=r"path\.own\[1\]: its run ends"):
        corridor(p)


def test_along_an_own_stretch_the_section_is_the_road_s():
    c = corridor(own_path())
    assert [c.path_at(s) for s in (1100.0, 1100.01, 1300.0, 1510.414, REJOIN)] == [
        True, False, False, False, True]
    assert {1100.0, 1100.01, 1510.414, REJOIN} <= set(
        round(s, 3) for s in c.stations(1050.0, 1550.0))


def test_the_separation_is_not_checked_along_an_own_stretch():
    # 3 ft at 13+00 is under the 5 ft minimum, but the path is on its own
    # corridor there; the ends keep 20 ft, so the run still rejoins
    sep = [[1000, 20.0], [1150, 20.0], [1300, 3.0], [1450, 20.0]]
    c = corridor(own_path(separation=sep))
    assert c.path.separation_at(1300.0) == 3.0
    bad = own_path(separation=sep)
    del bad["own"]
    with pytest.raises(ValueError, match=r"path\.separation: 3\.00 ft at 13\+00\.00"):
        corridor(bad)


def test_a_road_bridge_along_an_own_stretch_has_no_path_to_meet():
    # the road's structure gap 12+00 to 13+00 is under the own stretch: the
    # path is not beside the road there, so no approach leads to the deck and
    # 20 ft at its ends is not refused as other than deck_separation_ft
    c = corridor(own_path(), gaps=[{"from": 1200, "to": 1300, "kind": "structure"}])
    assert c.path.waived(1200.0) and c.path.waived(1100.0) and not c.path.waived(1099.9)


def test_a_run_ending_0_2_ft_off_is_refused():
    with pytest.raises(ValueError, match=(
            r"path\.own\[0\]: its run ends at N 510\.42 E 43\.00 heading .* not on the "
            r"path's centreline at 15\+10\.62 \(N 510\.62 E 43\.00.* 0\.20 ft and")):
        corridor(own_path(to=REJOIN + 0.2))


def test_a_run_ending_off_the_road_s_heading_is_refused():
    # the last curve 0.2 deg short: it ends 0.2 deg off the road's way, at
    # N 509.377 E 43.002, so a rejoin put there is off by its heading alone
    run = copy.deepcopy(BUMP)
    run[2].update(delta="19-48-0", length=103.67256)
    with pytest.raises(ValueError, match=r"heading 359\.8000 deg, not on .*\(N 509\.38 "
                                         r"E 43\.00, heading 0\.0000 deg\): 0\.00 ft "
                                         r"and 0\.2000 deg off"):
        corridor(own_path(run=run, to=1509.377))


@pytest.mark.parametrize("over, match", [
    ({"run": [{"kind": "tangent", "bearing": "N 1-0-0 E", "length": 410.0}]},
     r"path\.own\[0\]\.run\[0\]: bearing N 1-0-0 E is not the road's heading at "
     r"the hand-over 11\+00\.00"),
    ({"run": []}, r"path\.own\[0\]\.run: the path's own horizontal"),
    ({"run": ["tangent"]}, r"path\.own\[0\]\.run\[0\]: a mapping"),
    ({"run": [{"kind": "spiral", "length": 410.0}]},
     r"path\.own\[0\]\.run\[0\]\.kind: 'spiral' is not tangent or curve"),
    ({"run": [{"kind": "tangent", "bearing": "N 0-0-0 E", "length": 0.0}]},
     r"path\.own\[0\]\.run\[0\]\.length: must be positive"),
    ({"run": [dict(BUMP[0], radius=-300.0)] + BUMP[1:]},
     r"path\.own\[0\]\.run\[0\]\.radius: must be positive"),
    ({"run": [dict(BUMP[0], length=100.0)] + BUMP[1:]},
     r"path\.own\[0\]\.run\[0\]\.length: 100 ft is not the curve's 104\.7198 ft"),
    ({"run": [{"kind": "tangent", "length": 410.0}]},
     r"path\.own\[0\]\.run\[0\]\.bearing: "),
    ({"from": 2500}, r"path\.own\[0\]: 'to' must be past 'from'"),
    ({"from": 900}, r"path\.own\[0\]: 9\+00\.00 to 15\+10\.42 is outside the "
                    r"path's stations"),
    ({"colour": "red"}, r"path\.own\[0\]: unknown keys \['colour'\]"),
    ({"run": [dict(BUMP[0], turn="X")] + BUMP[1:]},
     r"path\.own\[0\]\.run\[0\]\.turn: 'X' is not L or R"),
    ({"run": [dict(BUMP[0], delta="400-0-0")] + BUMP[1:]},
     r"path\.own\[0\]\.run\[0\]\.delta: '400-0-0' is not between 0 and 360 deg"),
    ({"run": [dict(BUMP[0], delta="0-0-0")] + BUMP[1:]},
     r"path\.own\[0\]\.run\[0\]\.delta: '0-0-0' is not between 0 and 360 deg"),
    ({"gaps": [{"from": 400, "to": 500, "kind": "structure"}]},
     r"path\.own\[0\]\.gaps\[0\]: 4\+00\.00 to 5\+00\.00 is outside its own stations "
     r"\(0\+00\.00 to 4\+18\.88\)"),
])
def test_bad_own_stretches_are_refused(over, match):
    with pytest.raises(ValueError, match=match):
        corridor(own_path(**over))


@pytest.mark.parametrize("value, match", [
    ({"from": 1100}, r"path\.own: a list of"),
    (["x"], r"path\.own\[0\]: a mapping"),
])
def test_own_must_be_a_list_of_mappings(value, match):
    p = own_path()
    p["own"] = value
    with pytest.raises(ValueError, match=match):
        corridor(p)


def test_an_own_stretch_takes_its_own_gaps_on_its_own_stations():
    p = own_path(gaps=[{"from": 150, "to": 250, "kind": "structure"}])
    (own,) = corridor(p).path.own
    assert [(g.start, g.end) for g in own.gaps] == [(150.0, 250.0)]


def test_an_own_profile_must_meet_the_path_s_at_both_ends():
    p = own_path()
    cv = p["own"][0]["profile"]["curves"][0]
    g = 0.02 / cv["length_ft"] * 100.0           # 0.02 ft up over the stretch
    cv.update(g_in_pct=g, g_out_pct=g, evc_elev=99.53)
    with pytest.raises(ValueError, match=(
            r"path\.own\[0\]\.profile: at the rejoin \(4\+18\.88, road 15\+10\.42\) it "
            r"is at 99\.5300 ft and path\.profile at 99\.5100 ft, 0\.0200 ft off")):
        corridor(p)
    with pytest.raises(ValueError, match=r"path\.own\[0\]\.profile: at the hand-over "
                                         r"\(0\+00\.00, road 11\+00\.00\)"):
        corridor(own_path(elev=99.53))
    p = own_path()
    p["own"][0]["profile"] = flat(400.0)
    with pytest.raises(ValueError, match=r"path\.own\[0\]\.profile: covers 0\+00\.00 "
                                         r"to 4\+00\.00, not the path's 0\+00\.00 to "
                                         r"4\+18\.88"):
        corridor(p)


def test_own_stretches_may_not_overlap_each_other_or_a_path_gap():
    p = own_path()
    p["gaps"] = [{"from": 1500, "to": 1600, "kind": "structure"}]
    with pytest.raises(ValueError, match=r"path\.own: 11\+00\.00 to 15\+10\.42 overlaps "
                                         r"the path gap 15\+00\.00 to 16\+00\.00"):
        corridor(p)
    p = own_path()
    p["own"].append(copy.deepcopy(p["own"][0]))
    with pytest.raises(ValueError, match=r"path\.own: 11\+00\.00 to 15\+10\.42 overlaps "
                                         r"11\+00\.00 to 15\+10\.42"):
        corridor(p)


def test_an_own_stretch_keeps_a_path_gap_s_transition_clear():
    # a path gap ending 0.5 ft before the hand-over: its 1 ft transition back
    # to the beside section would run into the own stretch
    p = own_path()
    p["gaps"] = [{"from": 1000, "to": 1099.5, "kind": "structure"}]
    with pytest.raises(ValueError, match=r"overlaps the path gap 10\+00\.00 to "
                                         r"10\+99\.50"):
        corridor(p)
    p["gaps"] = [{"from": 1000, "to": 1099.0, "kind": "structure"}]
    assert corridor(p).path.own[0].start == 1100.0


def test_own_stretches_may_not_meet_end_to_end():
    # a rejoin that is also the next hand-over leaves no beside section
    p = own_path()
    p["own"].append({"from": REJOIN, "to": REJOIN + 100.0, "profile": flat(100.0),
                     "run": [{"kind": "tangent", "bearing": "N 0-0-0 E",
                              "length": 100.0}]})
    with pytest.raises(ValueError, match=r"path\.own: 11\+00\.00 to 15\+10\.42 overlaps "
                                         r"15\+10\.42 to 16\+10\.42"):
        corridor(p)
    p["own"][1].update({"from": REJOIN + 0.5, "to": REJOIN + 100.5})
    assert len(corridor(p).path.own) == 2


#: an S out 9.11535 ft further from the road: 10 deg right, 10 left on
#: 300 ft radii, 2 R (1 - cos 10 deg) out over 2 R sin 10 deg = 104.18891 ft
S_OUT = [{"kind": "curve", "delta": "10-0-0", "radius": 300.0, "turn": "R",
          "length": 52.35988},
         {"kind": "curve", "delta": "10-0-0", "radius": 300.0, "turn": "L",
          "length": 52.35988}]


def test_the_rejoin_is_at_the_separation_there():
    # 20 ft at the hand-over and 29.11535 ft at the rejoin 12+04.19: the run
    # ends on the path's centreline there, 52.11535 ft right of the road's
    sep = [[1000, 20.0], [1100, 20.0], [1204.18891, 29.11535]]
    (own,) = corridor(own_path(run=S_OUT, to=1204.18891, separation=sep)).path.own
    assert own.alignment.end_point == (pytest.approx(204.18891, abs=1e-4),
                                       pytest.approx(52.11535, abs=1e-4))


def test_the_separation_is_checked_at_the_hand_over_and_the_rejoin():
    # 4.76 ft at 11+00 and 15+10.42, under the 5 ft minimum: the beside
    # section stands at both
    sep = [[1000, 20.0], [1105, 4.0], [1505.424, 4.0], [1610.424, 20.0]]
    with pytest.raises(ValueError, match=r"path\.separation: 4\.76 ft at 11\+00\.00 is "
                                         r"under the 5 ft minimum"):
        corridor(own_path(separation=sep))


def test_a_kinked_run_is_refused():
    # tangents N 0 E, N 5 E, N 5 W, N 0 E: each bearing is taken as given,
    # so the run would turn 5, 10 and 5 deg at points
    run = [{"kind": "tangent", "bearing": "N 0-0-0 E", "length": 50.0},
           {"kind": "tangent", "bearing": "N 5-0-0 E", "length": 100.0},
           {"kind": "tangent", "bearing": "N 5-0-0 W", "length": 100.0},
           {"kind": "tangent", "bearing": "N 0-0-0 E", "length": 50.0}]
    adv = 100.0 + 200.0 * math.cos(math.radians(5.0))
    with pytest.raises(ValueError, match=r"path\.own\[0\]\.run: T path 1: 5\.000000 deg "
                                         r"kink at station 0\+50\.00"):
        corridor(own_path(run=run, to=1100.0 + adv))


def test_a_first_tangent_a_second_west_of_north_is_the_road_s_way():
    # azimuth 359.9997 against the road's 0: folded, 0.0003 deg apart
    run = [{"kind": "tangent", "bearing": "N 0-0-1 W", "length": 410.0}]
    assert corridor(own_path(run=run, to=1510.0)).path.own[0].end == 1510.0


def test_a_rejoin_past_the_path_s_end_is_refused():
    p = own_path()
    p["stations"] = [1000, 1500]
    with pytest.raises(ValueError, match=r"path\.own\[0\]: 11\+00\.00 to 15\+10\.42 is "
                                         r"outside the path's stations \(10\+00\.00 to "
                                         r"15\+00\.00\)"):
        corridor(p)


def test_a_long_curve_s_length_is_held_to_its_radius():
    # a delta rounded to the second on a 2957 ft radius (a path concentric
    # with a 3000 ft road curve) is up to 0.0072 ft off its arc: within
    # 5e-6 R = 0.0148 ft is taken, 0.02 ft is not
    from bimforge.author.corridor.own import _run
    arc = 2957.0 * math.radians(10.0)
    ok = [{"kind": "curve", "delta": "10-0-0", "radius": 2957.0, "turn": "R",
           "length": arc + 0.012}]
    assert _run(ok, "x") == ok
    with pytest.raises(ValueError, match=r"x\[0\]\.length: .* is not the curve's "
                                         r"516\.0939 ft"):
        _run([dict(ok[0], length=arc + 0.02)], "x")


@pytest.mark.parametrize("gap, which, at", [
    ((1050, 1150), "hand-over", "11+00.00"),
    ((1500, 1600), "rejoin", "15+10.42"),
])
def test_a_hand_over_or_rejoin_on_a_road_deck_is_refused(gap, which, at):
    msg = (f"path.own[0]: the {which} at {at} is on the road's structure gap "
           f"{sta(gap[0])} to {sta(gap[1])}")
    with pytest.raises(ValueError, match=re.escape(msg)):
        corridor(own_path(), gaps=[{"from": gap[0], "to": gap[1], "kind": "structure"}])


def test_a_hand_over_or_rejoin_at_a_road_deck_s_end_is_not_on_it():
    # the deck ends where the path starts (its far end is off the path, so
    # no approach leads to it): the beside section stands at the end
    p = own_path()
    p["stations"] = [1100, 2000]
    c = corridor(p, gaps=[{"from": 1000, "to": 1100, "kind": "structure"}])
    assert c.path.own[0].start == 1100.0 and c.path_at(1100.0)
    p = own_path()
    p["stations"] = [1000, REJOIN]
    c = corridor(p, gaps=[{"from": REJOIN, "to": 1600, "kind": "structure"}])
    assert c.path.own[0].end == REJOIN and c.path_at(REJOIN)


def test_the_road_s_curvature_is_not_held_to_a_separation_along_an_own_stretch():
    # a 400 ft radius right under the stretch: 400 ft at 13+00 would put the
    # beside path past its centre, but the path is on its own corridor there
    d = math.degrees(200.0 / 400.0)
    deg = f"{int(d)}-{int(d * 60) % 60}-{(d * 3600) % 60:.10f}"
    al = Alignment({"station": 1000.0, "northing": 0.0, "easting": 0.0},
                   [{"kind": "tangent", "bearing": "N 0-0-0 E", "length": 200.0},
                    {"kind": "curve", "delta": deg, "radius": 400.0, "turn": "R",
                     "length": 200.0},
                    {"kind": "tangent", "bearing": f"N {deg} E", "length": 600.0}],
                   name="C")
    r2 = 400.0 - 43.0              # concentric with the road, 43 ft inside
    run = [{"kind": "tangent", "bearing": "N 0-0-0 E", "length": 100.0},
           {"kind": "curve", "delta": deg, "radius": r2, "turn": "R",
            "length": r2 * math.radians(d)},
           {"kind": "tangent", "bearing": f"N {deg} E", "length": 100.0}]
    params = copy.deepcopy(BASE)
    params["path"] = own_path(
        run=run, to=1500.0,
        separation=[[1000, 20.0], [1150, 20.0], [1300, 400.0], [1450, 20.0]])
    c = parse(params, 1000.0, 2000.0, alignment=al, profile=PROF)
    assert c.path.own[0].end == 1500.0


#: a road with a 400 ft radius right from 12+00 to 14+00, 28-38-52.403
#: (28.64789 deg) of turn: a hand-over at 13+00 on the curve heads 14.32394
#: deg, as no bearing written to the second does
TURN = math.degrees(200.0 / 400.0)
CURVED = Alignment(
    {"station": 1000.0, "northing": 0.0, "easting": 0.0},
    [{"kind": "tangent", "bearing": "N 0-0-0 E", "length": 200.0},
     {"kind": "curve", "delta": f"{TURN:.12f}", "radius": 400.0, "turn": "R",
      "length": 200.0},
     {"kind": "tangent", "bearing": f"N {TURN:.12f} E", "length": 600.0}],
    name="C")


def curved_own(bearing):
    """On CURVED, a path 43 ft right handing over at 13+00: the rest of the
    road's curve concentric 43 ft inside, then 100 ft of tangent written
    `bearing`, rejoining at 15+00."""
    r = 400.0 - 43.0
    run = [{"kind": "curve", "delta": f"{TURN / 2:.12f}", "radius": r, "turn": "R",
            "length": r * math.radians(TURN / 2)},
           {"kind": "tangent", "bearing": bearing, "length": 100.0}]
    params = copy.deepcopy(BASE)
    params["path"] = own_path(run=run, to=1500.0)
    params["path"]["own"][0]["from"] = 1300
    return parse(params, 1000.0, 2000.0, alignment=CURVED, profile=PROF)


def test_a_bearing_to_the_second_after_a_curve_is_taken_as_its_heading():
    # N 28-38-52 E is 0.403 arc-seconds off the curve's end heading: within
    # a second it joins, and the run is built on the heading it comes in on
    (own,) = curved_own("N 28-38-52 E").path.own
    al = own.alignment
    assert al.kink_check(al.s_start, al.s_end) == []
    assert al.segments[1]["az"] == pytest.approx(TURN, abs=1e-9)
    assert al.pob["azimuth"] == pytest.approx(TURN / 2, abs=1e-9)


def test_a_join_more_than_a_second_off_is_refused():
    # N 28-38-50 E is 2.403 arc-seconds off the curve's end heading
    with pytest.raises(ValueError, match=r"path\.own\[0\]\.run: C path 1: 0\.000668 deg "
                                         r"kink at station 0\+89\.25 \(more than 1 "
                                         r"arc-second\)"):
        curved_own("N 28-38-50 E")


def test_a_first_tangent_within_a_tenth_of_a_degree_is_the_road_s_heading():
    # N 0-3-0 E is 0.05 deg off the road's way: taken as the road's heading,
    # so it rejoins 410 ft on (as written it would end 0.36 ft out)
    run = [{"kind": "tangent", "bearing": "N 0-3-0 E", "length": 410.0}]
    (own,) = corridor(own_path(run=run, to=1510.0)).path.own
    assert own.alignment.segments[0]["az"] == 0.0
    assert own.alignment.end_point == (pytest.approx(510.0), pytest.approx(43.0))
    assert run[0]["bearing"] == "N 0-3-0 E"      # the spec's run is left as given


@pytest.mark.parametrize("az", [0.0, 14.323944878, 90.0, 123.4, 180.0, 200.5,
                                270.0, 359.9999997, 374.5])
def test_a_snapped_bearing_reads_back_as_its_azimuth(az):
    from bimforge.author.alignment import parse_bearing
    from bimforge.author.corridor.own import _bearing
    assert parse_bearing(_bearing(az)) == pytest.approx(az % 360.0, abs=1e-10)


def own_of(p, **over):
    c = corridor(p, **over)
    (own,) = c.path.own
    return c, own, own_mod.own_corridor(c, own)


def test_the_own_section_on_level_ground():
    # the path on the right (inward +1), level, its own profile 99.51 and
    # the ground 4.51 under it: the paved width centred on the own
    # alignment, its inner edge on the left where the road was, falling
    # away at 2 %; a 2 ft shoulder each side at 5 %; 2:1 fill both sides
    c, own, oc = own_of(own_path())
    sec = own_mod.own_section(c, oc, own, 200.0, level(-4.51))
    sf = sec.surface
    assert sf.inward == 1.0
    assert (sf.inner, sf.outer, sf.q, sf.o) == (pt((6.0, 0.0)), pt((-6.0, -0.24)),
                                                pt((8.0, -0.10)), pt((-8.0, -0.34)))
    # the courses thickness deep: the section is square to its own tangent
    assert sec.courses[0] == [pt(x) for x in [(6, 0), (-6, -0.24), (-6, -0.49),
                                               (6, -0.25)]]
    assert sec.courses[1][2] == pt((-6.0, -0.99))
    assert {k: x.kind for k, x in sec.sides.items()} == {"L": "fill", "R": "fill"}
    line = sec.earthwork_line()
    assert line[0] == pt((16.82, -4.51)) and line[-1] == pt((-16.34, -4.51))
    assert len(line) == 2 * sec.count + 6 - 2
    # the fill: 19.4481 (left), 8.8749025 + 0.0413475 + 43.68 + 0.0389475 +
    # 8.3973025 (the top, q to o), 17.3889 (right)
    d = [(u, -4.51 - v) for u, v in line]
    fill = -sum(0.5 * (d0 + d1) * abs(u1 - u0) for (u0, d0), (u1, d1) in zip(d, d[1:]))
    assert fill == pytest.approx(97.8695, abs=1e-6)
    assert sec.width() == pytest.approx(16.82 + 16.34)


def test_a_path_on_the_left_keeps_its_inner_edge_on_the_right():
    p = own_path()
    p["side"] = "L"
    p["own"][0]["run"] = [dict(x, turn="L" if x["turn"] == "R" else "R") for x in BUMP]
    c, own, oc = own_of(p)
    sf = own_mod.own_surface(c.path, own, 100.0)
    assert sf.inward == -1.0
    assert (sf.inner, sf.outer, sf.q, sf.o) == (pt((-6.0, 0.0)), pt((6.0, -0.24)),
                                                pt((-8.0, -0.10)), pt((8.0, -0.34)))
    # the earthwork line still runs left daylight to right: o's side first
    sec = own_mod.own_section(c, oc, own, 100.0, level(-4.51))
    line = sec.earthwork_line()
    assert line[0] == pt((16.34, -4.51)) and line[-1] == pt((-16.82, -4.51))
    assert pt((8.0, -0.34)) in line and pt((-8.0, -0.10)) in line
    assert [u for u, _v in line] == sorted((u for u, _v in line), reverse=True)


def test_the_tread_goes_with_the_path():
    p = own_path()
    p["equestrian"] = dict(TREAD, fence=True)
    c, own, oc = own_of(p)
    sf = own_mod.own_surface(c.path, own, 100.0)
    # 6 ft of buffer at -5 % past the outer edge (-6, -0.24): (-12, -0.54);
    # 8 ft of tread at -2 %: (-20, -0.70); 3 ft clear at -5 %: o (-23, -0.85);
    # the fence 3 ft in from the tread: (-9, -0.39)
    assert sf.tread == (pt((-12.0, -0.54)), pt((-20.0, -0.70)))
    assert (sf.o, sf.fence) == (pt((-23.0, -0.85)), pt((-9.0, -0.39)))
    assert sf.tread_depth == pytest.approx(0.33)
    sec = own_mod.own_section(c, oc, own, 100.0, level(-4.51))
    assert sec.tread_courses[0] == [pt(x) for x in [(-12, -0.54), (-20, -0.70),
                                                     (-20, -1.03), (-12, -0.87)]]
    # the right slope starts at o past the tread: 2:1 down 3.66 ft
    line = sec.earthwork_line()
    assert line[-1] == pt((-30.32, -4.51))
    assert len(line) == 2 * sec.count + 10 - 2


def test_an_own_corridor_reads_the_road_s_slopes_on_own_stations():
    # rock 10 ft down at the hand-over (11+00) and 20 ft at the rejoin
    # (15+10.42) on the road's rows: on own stations 0 to 4+18.88, linear
    sides = dict(BASE["section"]["side_slopes"])
    sides["cut"] = dict(sides["cut"], rock={
        "depth_ft": [[1000, 5.0], [1200, 15.0], [1510.424, 20.0], [1800, 50.0]],
        "ratio": 0.5, "bench_ft": 4.0})
    section = dict(BASE["section"], side_slopes=sides)
    p = own_path(gaps=[{"from": 150, "to": 250, "kind": "structure"}])
    c, own, oc = own_of(p, section=section)
    assert oc.slopes.rock.depth == (pytest.approx((0.0, 10.0)),
                                    pytest.approx((own.length, 20.0)))
    assert oc.slopes.rock.depth_at(own.length / 2.0) == pytest.approx(15.0)
    assert (oc.s_start, oc.s_end) == (0.0, pytest.approx(own.length))
    assert oc.path is None and oc.guard is None
    # its own gaps are its structure gaps
    assert [(g.start, g.end, g.kind) for g in oc.gaps] == [(150.0, 250.0, "structure")]
    assert oc.runs() == [(0.0, 150.0), (250.0, pytest.approx(own.length))]


def test_an_own_slope_past_its_footprint_takes_a_wall():
    # the right (outer) 2:1 from o (-8, -0.34) down to -20.51 is 20.17 ft of
    # fill: it would daylight 40.34 ft on, at (-48.34, -20.51), past a 30 ft
    # footprint; the inner side has none
    section = dict(BASE["section"], side_slopes=dict(BASE["section"]["side_slopes"],
                                                     footprint_ft={"R": 30.0}))
    c = corridor(own_path(), walls="auto", section=section)
    (own,) = c.path.own
    oc = own_mod.own_corridor(c, own)
    ground = level(-20.51)
    assert own_mod.own_needs_wall(c, oc, own, 200.0, "R", ground) == "path-fill"
    assert own_mod.own_needs_wall(c, oc, own, 200.0, "L", ground) is None
    own2, oc2 = own_mod.find_walls(c, oc, own, ground)
    assert {(g.side, g.auto) for g in own2.walls} == {("R", "path-fill")}
    (g,) = own2.walls
    assert (g.start, g.end) == (0.0, pytest.approx(own.length))
    assert oc2.wall("R", 200.0) == g
    sec = own_mod.own_section(c, oc2, own2, 200.0, ground)
    assert sec.sides["R"].kind == "wall" and sec.sides["L"].kind == "fill"
    assert sec.earthwork_line()[-1] == pt((-8.0, -0.34))
    (row,) = own_mod.wall_rows(c, oc2, own2, ground)
    assert (row.kind, row.location, row.carries) == ("fill", "own 1", "path")
    assert row.max_height == pytest.approx(20.17)
    assert row.offset == pytest.approx(8.0) and not row.barrier


def test_an_own_cut_past_its_footprint_takes_a_cut_wall():
    # ground 6 ft over the own grade line: the left (inner) cut from q
    # (8, -0.10) takes its ditch and backslope past a 12 ft footprint
    section = dict(BASE["section"], side_slopes=dict(BASE["section"]["side_slopes"],
                                                     footprint_ft={"L": 12.0}))
    c = corridor(own_path(), walls="auto", section=section)
    (own,) = c.path.own
    oc = own_mod.own_corridor(c, own)
    own2, oc2 = own_mod.find_walls(c, oc, own, level(6.0))
    assert {(g.side, g.auto) for g in own2.walls} == {("L", "path-cut")}
    (row,) = own_mod.wall_rows(c, oc2, own2, level(6.0))
    assert (row.kind, row.location) == ("cut", "own 1")
    assert row.max_height == pytest.approx(6.10) and not row.too_tall


def test_own_walls_are_found_on_each_own_run():
    # an own path gap from 1+50 to 2+50: no section there, so the wall
    # stops at its ends
    section = dict(BASE["section"], side_slopes=dict(BASE["section"]["side_slopes"],
                                                     footprint_ft={"R": 30.0}))
    c = corridor(own_path(gaps=[{"from": 150, "to": 250, "kind": "structure"}]),
                 walls="auto", section=section)
    (own,) = c.path.own
    own2, oc2 = own_mod.find_walls(c, own_mod.own_corridor(c, own), own,
                                   level(-20.51))
    assert [(g.start, g.end) for g in own2.walls] == [
        (0.0, 150.0), (250.0, pytest.approx(own.length))]
    runs = own_mod.own_sections(c, oc2, own2, level(-20.51))
    assert [(r[0].s, r[-1].s) for r in runs] == [
        (0.0, 150.0), (250.0, pytest.approx(own.length))]
    assert all(sec.sides["R"].kind == "wall" for r in runs for sec in r)


def test_an_own_slope_that_does_not_fit_names_the_stretch():
    # without walls: auto the outer slope past the footprint is refused, on
    # its own stations
    section = dict(BASE["section"], side_slopes=dict(BASE["section"]["side_slopes"],
                                                     footprint_ft={"R": 30.0}))
    c, own, oc = own_of(own_path(), section=section)
    with pytest.raises(ValueError, match=(
            r"path\.own\[0\] \(T path 1, own stations\): station 2\+00\.00: the R "
            r"fill slope daylights 48\.34 ft out, past the R footprint of 30 ft")):
        own_mod.own_section(c, oc, own, 200.0, level(-20.51))


def test_an_own_corridor_takes_no_strip_wall():
    from bimforge.author.corridor.params import Gap
    c, own, oc = own_of(own_path())
    got = oc.with_walls([Gap(100.0, 200.0, "wall", "L", None, auto="path-cut")])
    assert [g.auto for g in got.gaps] == ["path-cut"]
    with pytest.raises(ValueError, match=r"a strip-road wall on the L side .* with no "
                                         r"path"):
        oc.with_walls([Gap(100.0, 200.0, "wall", "L", None, auto="strip-road")])


#: the bump's length, as its run gives it
BUMP_FT = sum(x["length"] for x in BUMP)


def crest(length=BUMP_FT, elev=99.51, g=6.0):
    """One crest over the whole stretch, +g % to -g %: it meets the level
    path's profile at both ends."""
    return {"curves": [{"bvc_station": 0.0, "bvc_elev": elev, "g_in_pct": g,
                        "g_out_pct": -g, "length_ft": length,
                        "evc_station": length, "evc_elev": elev}]}


def crest_path(**over):
    p = own_path(**over)
    p["own"][0]["profile"] = crest()
    return joined(p)


def test_an_own_section_on_a_grade_is_in_the_plane_square_to_it():
    # a straight own run at 2 %, the path's profile 2 % too: on a constant
    # grade the plane leans back v sin(gamma), so a point dz above the
    # profile is v = dz cos(gamma) up the plane (not dz / cos)
    p = path(side="R", separation=[[1000, 20.0]], profile=grade(99.51, 2.0),
             own=[{"from": 1100, "to": 1510,
                   "run": [{"kind": "tangent", "bearing": "N 0-0-0 E",
                            "length": 410.0}],
                   "profile": grade(101.51, 2.0, 0.0, 410.0)}])
    (own,) = corridor(p).path.own
    sf = own_mod.own_surface(corridor(p).path, own, 100.0)
    cg = 1.0 / math.sqrt(1.0 + 0.02 ** 2)
    assert sf.cg == pytest.approx(cg, abs=1e-15)
    assert (sf.inner, sf.outer, sf.q, sf.o) == (
        pt((6.0, 0.0)), pt((-6.0, -0.24 * cg)), pt((8.0, -0.10 * cg)),
        pt((-8.0, -0.34 * cg)))
    # the point is on the profile's grade line dz above it where it lies
    from bimforge.author.corridor.frame import survey_point
    n, _e, z = survey_point(own.alignment, own.profile, 100.0, *sf.o)
    assert z == pytest.approx(own.profile.elev(n - 100.0) - 0.34, abs=1e-12)


def test_the_tread_s_cos_theta_on_a_graded_own_curve():
    # at own station 50, on the bump's first curve (300 ft right) and the
    # crest at +4.57 %: the tread's centre, 16 ft right (radius 284 ft),
    # rises g x 300 / 284 along its own length, so its courses are deeper
    # than their thickness by 1 / cos theta; the paved courses, centred on
    # the own alignment, are not
    p = crest_path()
    p["equestrian"] = dict(TREAD)
    c, own, oc = own_of(p)
    sf = own_mod.own_surface(c.path, own, 50.0)
    g = own.profile.grade(50.0)
    gt = g * 300.0 / 284.0
    want = (1.0 + g * gt) / math.sqrt((1.0 + g * g) * (1.0 + gt * gt))
    assert 1.0 - want > 3e-6
    # (within 1 %: the plane's lean and the crest's curvature move it a little)
    assert 1.0 - sf.tread_cos_theta == pytest.approx(1.0 - want, rel=1e-2)
    assert sf.tread_depth == pytest.approx(0.33 / sf.tread_cos_theta, abs=1e-15)
    assert sf.cos_theta == 1.0 and sf.depth == pytest.approx(0.75)
    sec = own_mod.own_section(c, oc, own, 50.0, level(-4.51))
    ring = sec.tread_courses[0]
    assert ring[0][1] - ring[3][1] == pytest.approx(0.33 / sf.tread_cos_theta,
                                                    abs=1e-12)
    # at the crest's top the grade is 0, and so is the tread's: 1 again
    assert own_mod.own_surface(c.path, own, BUMP_FT / 2.0).tread_cos_theta == (
        pytest.approx(1.0, abs=1e-12))


def test_an_own_run_is_cut_at_its_curves_ends_and_its_pvi():
    c, own, oc = own_of(crest_path())
    (ss,) = own_mod.own_runs(oc, own)
    for s in (104.71976, 104.71976 + 209.43951, BUMP_FT / 2.0):
        assert min(abs(t - s) for t in ss) < 1e-4, s


def test_on_a_graded_own_curve_a_tall_fill_wall_is_too_tall_and_a_cut_wall_not():
    section = dict(BASE["section"], side_slopes=dict(
        BASE["section"]["side_slopes"], footprint_ft={"L": 20.0, "R": 20.0}))
    c = corridor(crest_path(), walls="auto", section=section)
    (own,) = c.path.own
    oc = own_mod.own_corridor(c, own)
    for ground, kind, tall in ((level(-40.0), "fill", True),
                               (level(35.0), "cut", False)):
        own2, oc2 = own_mod.find_walls(c, oc, own, ground)
        rows = own_mod.wall_rows(c, oc2, own2, ground)
        assert {(r.side, r.kind) for r in rows} == {("L", kind), ("R", kind)}
        assert all(r.max_height > 34.0 for r in rows)
        assert all(r.too_tall == tall for r in rows)


def test_own_wall_heights_are_read_at_the_own_sections_too():
    # a 5 ft deeper hollow at own station 113.3, between the 5 ft height
    # stations: the section cut there shows it, and so does the row
    section = dict(BASE["section"], side_slopes=dict(BASE["section"]["side_slopes"],
                                                     footprint_ft={"R": 30.0}))
    c = corridor(own_path(), walls="auto", section=section)
    (own,) = c.path.own

    def ground(s, u, v):
        return (-25.51 if abs(s - 113.3) < 0.01 else -20.51) - v

    own2, oc2 = own_mod.find_walls(c, own_mod.own_corridor(c, own), own,
                                   level(-20.51))
    (row,) = own_mod.wall_rows(c, oc2, own2, ground)
    assert row.max_height == pytest.approx(20.17)
    sec = own_mod.own_section(c, oc2, own2, 113.3, ground)
    (row,) = own_mod.wall_rows(c, oc2, own2, ground, [sec])
    assert row.max_height == pytest.approx(25.17)


def test_an_own_section_is_cut_where_a_side_turns():
    # ground level at elevation 103 under the crest: each side's start (q
    # or o) is in cut near the ends and in fill over the top. Lofted point
    # to point, a ditch would run onto a fill slope; so where a side's
    # kind changes between two sections, the fill one has its start on the
    # ground (the turn, found to 1e-9 ft)
    from bimforge.author.corridor.frame import survey_point
    c, own, oc = own_of(crest_path())

    def ground(s, u, v):
        return 103.0 - survey_point(own.alignment, own.profile, s, u, v)[2]

    (secs,) = own_mod.own_sections(c, oc, own, ground)
    turns = {"L": 0, "R": 0}
    for a, b in zip(secs, secs[1:]):
        for side in ("L", "R"):
            kinds = (a.sides[side].kind, b.sides[side].kind)
            if set(kinds) != {"cut", "fill"}:
                continue
            fill = a if kinds[0] == "fill" else b
            start = own_mod._start(fill.surface, side)[0]
            assert abs(ground(fill.s, *start)) < 1e-6, (side, fill.s)
            turns[side] += 1
    assert turns == {"L": 2, "R": 2}


def test_an_own_ground_error_names_the_stretch_and_side():
    c, own, oc = own_of(own_path())

    def ground(s, u, v):
        if u < -10.0:
            raise ValueError("no ground")
        return -4.51 - v

    with pytest.raises(ValueError, match=(
            r"path\.own\[0\] \(T path 1, own stations\): station 2\+00\.00, R side, "
            r"offset 1\d\.\d\d ft: no ground")):
        own_mod.own_section(c, oc, own, 200.0, ground)
    with pytest.raises(ValueError, match=r"path\.own\[0\] .*R side.*no ground"):
        own_mod.own_needs_wall(c, oc, own, 200.0, "R", ground)


def test_no_own_section_is_added_where_a_side_turns_in_a_wall_s_lead_in():
    # a plane rising 1 in 10 eastward under the crest, 25 ft footprints:
    # the R cut takes path-cut walls at both ends. Its side turns inside
    # the first wall's lead-in (0+36.50 to 0+37.50), where walls.find
    # checked only the far end: a section there would not fit
    from bimforge.author.corridor.frame import survey_point
    section = dict(BASE["section"], side_slopes=dict(
        BASE["section"]["side_slopes"], footprint_ft={"L": 25.0, "R": 25.0}))
    c = corridor(crest_path(), walls="auto", section=section)
    (own,) = c.path.own

    def ground(s, u, v):
        n, e, z = survey_point(own.alignment, own.profile, s, u, v)
        return 102.0 + 0.1 * (e - 43.0) - z

    own2, oc2 = own_mod.find_walls(c, own_mod.own_corridor(c, own), own, ground)
    assert [(g.side, g.auto, round(g.start, 2), round(g.end, 2))
            for g in own2.walls] == [("R", "path-cut", 0.0, 36.5),
                                     ("R", "path-cut", 381.5, round(own.length, 2))]
    (secs,) = own_mod.own_sections(c, oc2, own2, ground)
    assert len(secs) == 40


def test_a_hand_over_needs_natural_ground_between():
    # the path 20 ft out on level ground 3 ft under the road's grade line:
    # the road's 2:1 fill from its hinge (-17, -1.89) daylights 2.22 ft
    # out, the path's inner fill from q (-35, -0.59) 4.82 ft in, at
    # -30.18: ground between. 10 ft out over ground 5 ft under, the path's
    # inner slope from q (-25, -0.59) needs 8.82 ft, more than the strip
    from bimforge.author.corridor.section import resolve
    c = corridor(own_path())
    (own,) = c.path.own
    secs = [resolve(c, s, level(-3.0)) for s in (own.start, own.end)]
    assert [s.path.strip for s in secs] == ["ground", "ground"]
    own_mod.check_handover(own, *secs)
    # 8 ft under at the rejoin the two slopes meet: it is named
    at_to = resolve(c, own.end, level(-8.0))
    assert at_to.path.strip == "slope"
    with pytest.raises(ValueError, match=(
            r"path\.own\[0\]: the rejoin at 15\+10\.42 does not leave natural "
            r"ground between the road and the path \(the strip is slope\)")):
        own_mod.check_handover(own, secs[0], at_to)
    c = corridor(own_path(separation=10.0))
    (own,) = c.path.own
    secs = [resolve(c, s, level(-5.0)) for s in (own.start, own.end)]
    with pytest.raises(ValueError, match=(
            r"path\.own\[0\]: the hand-over at 11\+00\.00 does not leave natural "
            r"ground between the road and the path \(the strip is slope\)")):
        own_mod.check_handover(own, *secs)


def test_a_hand_over_names_its_entry_by_its_place_in_the_list():
    # the bump is own 1 by station but path.own[1] in the list
    p = own_path(separation=10.0)
    p["own"].insert(0, {"from": 1600, "to": 1700, "profile": flat(100.0),
                        "run": [{"kind": "tangent", "bearing": "N 0-0-0 E",
                                 "length": 100.0}]})
    from bimforge.author.corridor.section import resolve
    own = corridor(p).path.own[0]
    assert (own.index, own.entry) == (1, 1)
    secs = [resolve(corridor(p), s, level(-5.0)) for s in (own.start, own.end)]
    with pytest.raises(ValueError, match=r"path\.own\[1\]: the hand-over at 11\+00"):
        own_mod.check_handover(own, *secs)


def test_a_hand_over_at_a_road_deck_s_end_is_checked_as_any_other():
    # the path starts at the deck's end: the beside section stands there
    # and is read for ground between as anywhere
    from bimforge.author.corridor.section import resolve
    p = own_path()
    p["stations"] = [1100, 2000]
    c = corridor(p, gaps=[{"from": 1000, "to": 1100, "kind": "structure"}])
    (own,) = c.path.own
    own_mod.check_handover(own, *[resolve(c, s, level(-3.0))
                                  for s in (own.start, own.end)])
    with pytest.raises(ValueError, match=r"the hand-over at 11\+00\.00 .*slope"):
        own_mod.check_handover(own, *[resolve(c, s, level(-10.0))
                                      for s in (own.start, own.end)])


#: the road: 40 ft wide, stations 0 to 100 along y, in plan (x, y)
ROAD = [(0.0, (-20.0, 0.0), (20.0, 0.0)), (100.0, (-20.0, 100.0), (20.0, 100.0))]


def test_footprints_that_cross_are_refused():
    # the path beside the road at x 25 to 45, then swinging in to 15 to 35
    # at its station 0+40: its cross-section there crosses the road's edge
    clear = [(0.0, (25.0, 10.0), (45.0, 10.0)), (40.0, (26.0, 50.0), (46.0, 50.0))]
    own = own_mod.Own(1, 0, 1100.0, 1200.0, None, None)
    own_mod.check_footprints(own, ROAD, clear)
    swing = [(0.0, (25.0, 10.0), (45.0, 10.0)), (40.0, (15.0, 50.0), (35.0, 50.0))]
    with pytest.raises(ValueError, match=(
            r"path\.own\[0\]: its footprint at path station 0\+40\.00 crosses the "
            r"road's at 0\+00\.00")):
        own_mod.check_footprints(own, ROAD, swing)


def test_footprints_that_touch_are_refused():
    # the path's inner edge on the road's at x 20 from its 0+20 on
    touch = [(0.0, (25.0, 10.0), (45.0, 10.0)), (20.0, (20.0, 30.0), (40.0, 30.0)),
             (40.0, (20.0, 50.0), (40.0, 50.0))]
    own = own_mod.Own(1, 0, 1100.0, 1200.0, None, None)
    with pytest.raises(ValueError, match=r"at path station 0\+20\.00 crosses"):
        own_mod.check_footprints(own, ROAD, touch)


def test_a_footprint_within_the_other_is_refused():
    # no edge crosses, but the path lies on the road's footprint, or the
    # road's on the path's: the earthwork would still be counted twice
    own = own_mod.Own(1, 2, 1100.0, 1200.0, None, None)
    inside = [(0.0, (-5.0, 10.0), (5.0, 10.0)), (40.0, (-5.0, 50.0), (5.0, 50.0))]
    with pytest.raises(ValueError, match=(
            r"path\.own\[2\]: its footprint at path station 0\+00\.00 lies on the "
            r"road's at 0\+00\.00")):
        own_mod.check_footprints(own, ROAD, inside)
    around = [(0.0, (-50.0, -10.0), (50.0, -10.0)), (130.0, (-50.0, 120.0), (50.0, 120.0))]
    with pytest.raises(ValueError, match=(
            r"path\.own\[2\]: its footprint at path station 0\+00\.00 lies on the "
            r"road's at 0\+00\.00")):
        own_mod.check_footprints(own, ROAD, around)


def test_the_plan_footprint_is_the_earthwork_s_ground_corners():
    # a straight own run at 2 %, ground level at 83.51, 20 ft under the own
    # profile at own station 100: the right (outer) side takes a fill wall
    # at o (-8, -0.34 cg), 51 ft east. The earthwork's corner there is
    # where o's section ray meets the ground: 20 / cg down it, which leans
    # 20 tan(gamma) = 0.4 ft on along the run. The left (inner) side's 2:1
    # daylights on the ground, its corner the daylight point itself
    from bimforge.author.corridor.frame import survey_point
    section = dict(BASE["section"], side_slopes=dict(BASE["section"]["side_slopes"],
                                                     footprint_ft={"R": 30.0}))
    p = path(side="R", separation=[[1000, 20.0]], profile=grade(99.51, 2.0),
             own=[{"from": 1100, "to": 1510,
                   "run": [{"kind": "tangent", "bearing": "N 0-0-0 E",
                            "length": 410.0}],
                   "profile": grade(101.51, 2.0, 0.0, 410.0)}])
    c = corridor(p, walls="auto", section=section)
    (own,) = c.path.own
    al, prof = own.alignment, own.profile

    def survey(s, u, v):
        return survey_point(al, prof, s, u, v)

    def ground_dz(s, u, v):
        return 83.51 - survey(s, u, v)[2]

    own2, oc2 = own_mod.find_walls(c, own_mod.own_corridor(c, own), own, ground_dz)
    sec = own_mod.own_section(c, oc2, own2, 100.0, ground_dz)
    assert (sec.sides["L"].kind, sec.sides["R"].kind) == ("fill", "wall")
    ((s, left, right),) = own_mod.plan(survey, lambda n, e: 83.51, [sec])
    assert s == 100.0
    assert right == (pytest.approx(51.0, abs=1e-9), pytest.approx(200.4, abs=1e-6))
    u, v = sec.earthwork_line()[0]
    n, e, z = survey(100.0, u, v)
    assert z == pytest.approx(83.51, abs=1e-6)
    assert left == (pytest.approx(e, abs=1e-6), pytest.approx(n, abs=1e-6))


def test_footprints_beside_a_line_s_extension_are_apart():
    # the road's cross-section at y 0 runs on, past x 20, through the
    # path's inner edge at (30, 0); the segment itself stops 10 ft short
    own = own_mod.Own(1, 0, 1100.0, 1200.0, None, None)
    beside = [(0.0, (30.0, -10.0), (50.0, -10.0)), (20.0, (30.0, 10.0), (50.0, 10.0))]
    own_mod.check_footprints(own, ROAD, beside)
    # and where the two segments' boxes overlap: the path's inner edge,
    # (30, 95) to (18, 110), crosses the line of the road's end section at
    # (26, 100) and of its right edge at (20, 107.5), past each segment
    past = [(0.0, (30.0, 95.0), (50.0, 95.0)), (20.0, (18.0, 110.0), (38.0, 110.0))]
    own_mod.check_footprints(own, ROAD, past)


def test_an_own_footprint_s_ground_error_names_the_stretch():
    from bimforge.author.corridor.frame import survey_point
    c, own, oc = own_of(own_path())
    sec = own_mod.own_section(c, oc, own, 100.0, level(-4.51))

    def survey(s, u, v):
        return survey_point(own.alignment, own.profile, s, u, v)

    with pytest.raises(ValueError, match=(
            r"^path\.own\[0\] \(T path 1, own stations\): station 1\+00\.00: the "
            r"ground under")):
        own_mod.plan(survey, lambda n, e: float("nan"), [sec], own=own)
    with pytest.raises(ValueError, match=r"^station 1\+00\.00: the ground under"):
        own_mod.plan(survey, lambda n, e: float("nan"), [sec])


# -- the path's checks on its own stretches (Task 23) --------------------

from bimforge.author.corridor import path_checks as pc

TIGHT = [dict(x, radius=150.0, length=round(x["length"] / 2.0, 5)) for x in BUMP]
TIGHT_TO = 1100.0 + 205.212


def test_a_150_ft_radius_is_listed_at_25_and_30_mph_but_not_20():
    c = corridor(own_path(run=TIGHT, to=TIGHT_TO))
    (own,) = c.path.own
    assert own_mod.radius_rows(own, 20) == []
    for speed in (25, 30):
        found = own_mod.radius_rows(own, speed)
        assert len(found) == 6
        assert {r.check for r in found} == {
            f"own 1 radius under the minimum at {speed} mph",
            f"own 1 radius under the no-superelevation radius at {speed} mph"}
        assert {r.limit for r in found} == {own_mod.MIN_RADIUS_FT[speed],
                                           own_mod.NO_SUPER_RADIUS_FT[speed]}
        assert all(r.value == 150.0 for r in found)
        # the curves' own stations
        assert sorted({(round(r.start, 5), round(r.end, 5)) for r in found}) == [
            (0.0, 52.35988), (52.35988, 157.07964), (157.07964, 209.43952)]


def test_a_radius_at_the_limit_is_not_listed():
    # 160 ft is the 25 mph minimum, though under its no-superelevation 180
    run = [dict(x, radius=160.0, length=round(x["length"] * 160.0 / 300.0, 5))
           for x in BUMP]
    (own,) = corridor(own_path(run=run, to=1100.0 + 4 * 160.0 * math.sin(
        math.radians(20.0)))).path.own
    assert {r.check for r in own_mod.radius_rows(own, 25)} == {
        "own 1 radius under the no-superelevation radius at 25 mph"}


def test_the_path_s_checks_take_in_its_own_stretches():
    p = own_path(run=TIGHT, to=TIGHT_TO)
    p["design_speed_mph"] = 30
    checks = pc.checks(corridor(p), [], [])
    assert sum(r.check == "own 1 radius under the minimum at 30 mph"
               for r in checks) == 3
    # beside the road the path is level: no grade rows there
    assert not any(r.check.startswith("grade>5%") for r in checks)
    assert "own 1 radius under the minimum at 30 mph" in pc.checks_csv(checks)


def test_a_level_own_stretch_at_20_mph_adds_no_row():
    c = corridor(own_path())
    assert pc.checks(c, [], []) == [r for r in pc.checks(c, [], [])
                                    if not r.check.startswith("own")]


def test_the_path_beside_the_road_is_not_checked_inside_its_own_stretch():
    # the path climbs 6 % to the hand-over, the stretch crests (+6 to -6 %) and
    # the path falls 6 % from the rejoin: beside the road its 6 % is listed
    # before and after the stretch, never across it; the profile's own curves
    # inside the stretch's span (the joined profile's 50 ft curves, 6 % to
    # level and back) are not the path's crests
    p = own_path()
    p["own"][0]["profile"] = two_grades(6.0, -6.0)
    checks = pc.checks(corridor(joined(p)), [], [])
    beside = [r for r in checks if not r.check.startswith("own")]
    assert [(r.check, r.start, r.end) for r in beside
            if r.check == "grade>5%"] == [
        ("grade>5%", 1000.0, 1100.0), ("grade>5%", pytest.approx(REJOIN), 2000.0)]
    assert not any(r.check.startswith("crest") for r in beside)
    # on the stretch's own stations: the crest's grade falls to 5 % 1/12 of
    # the way along it, and is 5 % again 1/12 from its end
    assert [(r.check, round(r.start, 3), round(r.end, 3)) for r in checks
            if r.check == "own 1 grade>5%"] == [
        ("own 1 grade>5%", 0.0, round(BUMP_FT / 12.0, 3)),
        ("own 1 grade>5%", round(BUMP_FT * 11.0 / 12.0, 3), round(BUMP_FT, 3))]


def test_an_own_stretch_s_grade_and_crest_are_checked_on_its_own_stations():
    # the stretch climbs 6 %, crests over 50 ft and falls 6 %, back to the
    # level path's 99.51: steeper than 5 % either side of a short crest
    half = (BUMP_FT - 50.0) / 2.0
    top = 99.51 + 0.06 * half
    prof = {"curves": [
        {"bvc_station": 0.0, "bvc_elev": 99.51, "g_in_pct": 6.0, "g_out_pct": 6.0,
         "length_ft": half, "evc_station": half, "evc_elev": top},
        {"bvc_station": half, "bvc_elev": top, "g_in_pct": 6.0, "g_out_pct": -6.0,
         "length_ft": 50.0, "evc_station": half + 50.0, "evc_elev": top},
        {"bvc_station": half + 50.0, "bvc_elev": top, "g_in_pct": -6.0,
         "g_out_pct": -6.0, "length_ft": half, "evc_station": BUMP_FT,
         "evc_elev": 99.51}]}
    p = own_path(profile=prof)
    checks = pc.checks(corridor(joined(p)), [], [])
    own_rows = [r for r in checks if r.check.startswith("own")
                and "sustained" not in r.check]
    assert [r.check for r in own_rows] == [
        "own 1 grade>5%", "own 1 crest VC short of SSD at 30 mph", "own 1 grade>5%"]
    up, crest_row, down = own_rows
    # on its own stations, from 0+00: the grade runs to where the crest's
    # grade falls to 5 %, 1/12 of the way through the crest
    assert (up.start, up.end) == (0.0, pytest.approx(half + 50.0 * 1.0 / 12.0))
    assert (down.start, down.end) == (pytest.approx(half + 50.0 * 11.0 / 12.0),
                                    pytest.approx(BUMP_FT))
    assert up.value == down.value == pytest.approx(6.0)
    assert (crest_row.start, crest_row.end, crest_row.value) == (
        pytest.approx(half), pytest.approx(half + 50.0), 50.0)
    # (the path falls 6 % for 184 ft on the stretch and 490 ft beside it: 30 mph)
    assert crest_row.limit == pytest.approx(12.0 * 230.0 ** 2 / 1600.0)
    # beside the road: its 6 % before and after the stretch, and no crest
    assert [(r.start, r.end) for r in checks if r.check == "grade>5%"] == [
        (1000.0, 1100.0), (pytest.approx(REJOIN), 2000.0)]
    assert not any(r.check.startswith("crest") for r in checks)
    p = joined(own_path(profile=prof))
    p["design_speed_mph"] = 30
    (crest30,) = [r for r in pc.checks(corridor(p), [], [])
                  if r.check.startswith("own 1 crest")]
    assert crest30.check == "own 1 crest VC short of SSD at 30 mph"
    assert crest30.limit == pytest.approx(12.0 * 230.0 ** 2 / 1600.0)


def test_a_close_path_is_no_barrier_row_inside_its_own_stretch():
    # 8 ft from the road beside it, with no rail: needed before and after
    # the own stretch, not along it (the path is away from the road there)
    c = corridor(own_path(separation=8.0))
    rows = [r for r in pc.barrier_rows(c, [])]
    assert [(r.start, r.end) for r in rows] == [
        (pytest.approx(1000.0), pytest.approx(1100.0, abs=1e-3)),
        (pytest.approx(1510.424, abs=1e-3), pytest.approx(2000.0))]


# -- the checks across the hand-over and the rejoin (review of Task 23) ---

from bimforge.author.alignment import Profile


def vc(s0, z, g0, g1, length):
    """A curve of `length` from station s0 at elevation z, grades in %: the
    curve and the elevation at its end."""
    z1 = z + length * (g0 + g1) / 200.0
    return ({"bvc_station": s0, "bvc_elev": z, "g_in_pct": g0, "g_out_pct": g1,
             "length_ft": length, "evc_station": s0 + length, "evc_elev": z1}, z1)


def beside_tail(x0, z, g0, z_end, g1, to=REJOIN, end=2000.0):
    """The path's profile from x0 (at z, grade g0 %) to the rejoin at `to`
    (at z_end, grade g1 %) and on to `end`: a 50 ft curve to a grade that
    carries it to a 50 ft curve into g1."""
    gm = 100.0 * ((z_end - z) - 0.25 * (g0 + g1)) / (to - x0 - 50.0)
    out = []
    for s0, g_a, g_b, ln in ((x0, g0, gm, 50.0), (x0 + 50.0, gm, gm, to - x0 - 100.0),
                             (to - 50.0, gm, g1, 50.0), (to, g1, g1, end - to)):
        cv, z = vc(s0, z, g_a, g_b, ln)
        out.append(cv)
    return out


def joined(p, g0=None, g1=None):
    """Give path `p` a profile that carries on its (only) own stretch's grade
    at the hand-over and the rejoin (or at g0, g1 %), meeting its elevations."""
    o = p["own"][0]
    pr = Profile(o["profile"]["curves"])
    length = o["profile"]["curves"][-1]["evc_station"]
    z0, zl = pr.elev(0.0), pr.elev(length)
    g0 = 100.0 * pr.grade(0.0) if g0 is None else g0
    g1 = 100.0 * pr.grade(length) if g1 is None else g1
    head, _z = vc(1000.0, z0 - (o["from"] - 1000.0) * g0 / 100.0, g0, g0,
                  o["from"] - 1000.0)
    p["profile"] = {"curves": [head] + beside_tail(o["from"], z0, g0, zl, g1, o["to"])}
    return p


def two_grades(g0, g1, length=BUMP_FT, z0=99.51):
    cv, _z = vc(0.0, z0, g0, g1, length)
    return {"curves": [cv]}


def test_the_helper_joins_a_graded_stretch():
    p = own_path()
    p["own"][0]["profile"] = two_grades(6.0, 6.0)
    (own,) = corridor(joined(p)).path.own
    assert own.profile.grade(0.0) == pytest.approx(0.06)


@pytest.mark.parametrize("end,over", [("hand-over", {"g0": 0.0}),
                                      ("rejoin", {"g1": 0.0})])
def test_a_grade_break_at_a_hand_over_or_rejoin_is_refused(end, over):
    # the own profile goes from -6 % to 0 % (hand-over) or from 0 % to -6 %
    # (rejoin); the path's profile there is level
    p = own_path()
    p["own"][0]["profile"] = two_grades(*((-6.0, 0.0) if end == "hand-over"
                                          else (0.0, -6.0)))
    joined(p, **over)
    with pytest.raises(ValueError, match=rf"path\.own\[0\]\.profile.*{end}.*grade"):
        corridor(p)


def test_a_grade_that_carries_on_across_both_ends_is_accepted():
    p = own_path()
    p["own"][0]["profile"] = two_grades(6.0, -6.0)
    corridor(joined(p))


def test_an_own_stretch_s_equestrian_grade_runs_on_its_own_stations():
    # 12 % for 150 ft, a 10 ft curve, -12 %: each run is over 200 ft with the
    # path's grade beside the stretch; the first is 100 ft beside it (to its
    # hand-over) and 150.8 ft on it; the second 258 ft on it and 490 ft beside
    p = own_path()
    a, z = vc(0.0, 99.51, 12.0, 12.0, 150.0)
    b, z = vc(150.0, z, 12.0, -12.0, 10.0)
    d, z = vc(160.0, z, -12.0, -12.0, BUMP_FT - 160.0)
    p["own"][0]["profile"] = {"curves": [a, b, d]}
    p["equestrian"] = copy.deepcopy(TREAD)
    joined(p)
    rows = [r for r in pc.checks(corridor(p), [], [])
            if r.check.endswith("equestrian grade>10% for over 200ft")]
    # (the grade falls to 10 % 1/12 of the way into the curve)
    got = [(r.check.split("equestrian")[0], round(r.start, 3), round(r.end, 3),
            round(r.value, 2)) for r in rows]
    # (the road's stations first, then the stretch's)
    assert got == [("", 1000.0, 1100.0, 12.0),
                   ("", 1510.424, 2000.0, 12.0),
                   ("own 1 ", 0.0, 150.833, 12.0),
                   ("own 1 ", 159.167, round(BUMP_FT, 3), 12.0)]


def test_an_own_stretch_without_a_tread_has_no_equestrian_rows():
    p = own_path()
    p["own"][0]["profile"] = two_grades(12.0, 12.0)
    rows = pc.checks(corridor(joined(p)), [], [])
    assert not any("equestrian" in r.check for r in rows)
    assert any(r.check == "own 1 grade>5%" for r in rows)


def crest_across_the_rejoin():
    """An own crest (+2 to -4.5 % over its first 50 ft) and -4.5 % to its end,
    then the path's -4.5 % beside the road to 2000: -4.5 % for 858 ft either
    side of the rejoin."""
    a, z = vc(0.0, 99.51, 2.0, -4.5, 50.0)
    b, z = vc(50.0, z, -4.5, -4.5, BUMP_FT - 50.0)
    p = own_path()
    p["own"][0]["profile"] = {"curves": [a, b]}
    return joined(p)


def test_a_crest_on_an_own_stretch_reads_the_grade_beyond_its_rejoin():
    rows = pc.checks(corridor(crest_across_the_rejoin()), [], [])
    (crest_row,) = [r for r in rows if r.check.startswith("own 1 crest")]
    # -4.5 % for 368.9 ft on the stretch and 489.6 ft beside it: over 500 ft,
    # so the 30 mph rule applies (need 2 x 230 - 1600 / 6.5 = 213.85 ft)
    assert crest_row.check == "own 1 crest VC short of SSD at 30 mph"
    assert (crest_row.start, crest_row.end, crest_row.value) == (0.0, 50.0, 50.0)
    assert crest_row.limit == pytest.approx(2.0 * 230.0 - 1600.0 / 6.5)


def test_a_sustained_grade_runs_across_the_rejoin_on_both_systems():
    rows = pc.checks(corridor(crest_across_the_rejoin()), [], [])
    sus = [r for r in rows if r.check.endswith("sustained grade>2%")]
    # the grade passes -2 % 30.769 ft into the stretch's crest; the run is
    # reported on each system it lies on, with its whole length
    first = 50.0 * 4.0 / 6.5
    whole = (BUMP_FT - first) + (2000.0 - REJOIN)
    assert [(r.check, round(r.start, 3), round(r.end, 3), round(r.value, 3))
            for r in sus] == [
        ("sustained grade>2%", REJOIN, 2000.0, round(whole, 3)),
        ("own 1 sustained grade>2%", round(first, 3), round(BUMP_FT, 3), round(whole, 3))]


def test_a_beside_crest_across_the_hand_over_reads_the_stretch_s_grade():
    # the path's crest from 10+50 to 11+50 (+3 to -3 %) holds the hand-over
    # at 11+00, where the stretch takes up the 0 % grade and falls to -5 %:
    # beyond the crest the path's grade is the stretch's, -5 % for 858 ft
    z0 = 99.51
    a, z = vc(1000.0, z0 - 0.75 - 0.03 * 50.0, 3.0, 3.0, 50.0)
    b, z = vc(1050.0, z, 3.0, -3.0, 100.0)
    own_a, oz = vc(0.0, z0, 0.0, -5.0, 50.0)
    own_b, oz = vc(50.0, oz, -5.0, -5.0, BUMP_FT - 50.0)
    p = own_path()
    p["own"][0]["profile"] = {"curves": [own_a, own_b]}
    p["profile"] = {"curves": [a, b] + beside_tail(1150.0, z, -3.0, oz, -5.0)}
    c = corridor(p)
    (row,) = [r for r in pc.checks(c, [], []) if r.check.startswith("crest")]
    assert row.check == "crest VC short of SSD at 30 mph"
    assert (row.start, row.end, row.value) == (1050.0, 1150.0, 100.0)
    # the path beyond it is the stretch's -5 %, not the profile's -3 %: 8 %
    assert row.limit == pytest.approx(8.0 * 230.0 ** 2 / 1600.0)


def test_the_path_beside_the_road_reads_the_stretch_s_grade_through_it():
    # 12 % beside the road for 100 ft, 12 % on the stretch, 12 % after: one
    # run over 200 ft on three pieces, and no row beside the road across the
    # stretch's span (10+00 to 20+00 is not one row)
    p = own_path()
    p["own"][0]["profile"] = two_grades(12.0, 12.0)
    p["equestrian"] = copy.deepcopy(TREAD)
    rows = [r for r in pc.checks(corridor(joined(p)), [], [])
            if r.check.endswith("equestrian grade>10% for over 200ft")]
    assert [(r.check.split("equestrian")[0], r.start, r.end) for r in rows] == [
        ("", 1000.0, 1100.0), ("", pytest.approx(REJOIN), 2000.0),
        ("own 1 ", 0.0, pytest.approx(BUMP_FT))]


def test_the_approach_rows_skip_an_own_stretch():
    # a 3 ft separation from 11+10 inside the stretch (which starts at 11+00)
    # is not an approach row, though a road structure gap ends at 10+80
    p = own_path(elev=99.48, separation=[[1000, 1.5], [1080, 1.5], [1100, 20.0],
                                         [1110, 3.0], [1500, 3.0], [1510.424, 20.0]])
    p["profile"] = grade(99.48)
    c = corridor(p, gaps=[{"from": 1040, "to": 1080, "kind": "structure"}])
    assert [(r.start, r.end) for r in pc.approach_rows(c)] == [
        (1000.0, 1040.0), (1080.0, pytest.approx(1083.8, abs=0.1))]


def test_a_road_structure_inside_an_own_stretch_is_not_a_deck_the_path_is_on():
    # the path is off on its own stretch there: no deck width to carry, no
    # deck grade, no deck row in the path table
    p = own_path()
    p["equestrian"] = copy.deepcopy(TREAD)
    c = corridor(p, gaps=[{"from": 1250, "to": 1300, "kind": "structure"}])
    assert not pc.on_deck(c, 1275.0)
    assert [r for r in pc.checks(c, [], []) if "deck" in r.check] == []
    assert pc.deck_rows(c) == []
    assert ",deck," not in pc.path_csv(c, [], [])


def test_without_a_section_row_the_hand_over_and_rejoin_take_an_own_row():
    # written as a path gap's row is: no hinge, no barrier, the strip and
    # the note naming the stretch
    c = corridor(own_path())
    rows = [r.split(",") for r in pc.path_csv(c, [], []).splitlines()[1:]]
    assert [(r[0], r[4], r[6], r[8], r[9], r[10]) for r in rows] == [
        ("1100.00", "", "", "own 1", "", "own 1 hand-over"),
        (f"{REJOIN:.2f}", "", "", "own 1", "", "own 1 rejoin")]


def test_a_steep_road_deck_inside_an_own_stretch_is_not_the_path_s_deck_grade():
    p = own_path()
    c = corridor(p, Profile(grade(100.0, 6.0)["curves"]),
                 gaps=[{"from": 1250, "to": 1300, "kind": "structure"}])
    assert pc.deck_rows(c) == []


def test_a_crest_of_the_path_s_profile_inside_its_own_stretch_is_not_checked():
    # a short crest (a 12 % angle over 40 ft between two 10 ft curves) at
    # 12+50 to 13+10, inside the stretch's span: the path is on the stretch
    a, z = vc(1000.0, 99.51, 0.0, 0.0, 250.0)
    b, z = vc(1250.0, z, 0.0, 6.0, 10.0)
    d, z = vc(1260.0, z, 6.0, -6.0, 40.0)
    e, z = vc(1300.0, z, -6.0, 0.0, 10.0)
    f, z = vc(1310.0, z, 0.0, 0.0, 690.0)
    p = own_path()
    p["profile"] = {"curves": [a, b, d, e, f]}
    assert not [r for r in pc.checks(corridor(p), [], []) if r.check.startswith("crest")]


# -- second review of the Task 23 checks ----------------------------------

def test_a_grade_written_to_five_places_meets_the_path_s_at_a_hand_over():
    # the path's profile is mid-curve at 11+00, -14/3 %; the stretch's g_in,
    # written to 5 dp, is 3e-6 % off it
    p = own_path()
    p["own"][0]["profile"] = two_grades(-4.66667, -4.66667)
    corridor(joined(p, g0=-14.0 / 3.0))


def test_a_grade_a_hundredth_of_a_percent_off_is_a_break_at_the_rejoin():
    p = own_path()
    p["own"][0]["profile"] = two_grades(-6.0, -6.0)
    corridor(joined(p, g1=-6.00003))                       # a 2 dp length's worth
    with pytest.raises(ValueError, match=r"path\.own\[0\]\.profile.*rejoin.*-6 %.*-5\.99"):
        corridor(joined(p, g1=-5.99))


def test_a_run_over_two_systems_says_so_in_its_rows():
    rows = pc.checks(corridor(crest_across_the_rejoin()), [], [])
    sus = {r.check: r.reference for r in rows if r.check.endswith("sustained grade>2%")}
    assert sus == {
        "sustained grade>2%":
            "HDM 1003.1(14); run 877.69 ft continues on own 1",
        "own 1 sustained grade>2%":
            "HDM 1003.1(14); run 877.69 ft continues on road"}
    # a run on one piece keeps the plain reference
    assert {r.reference for r in rows if r.check == "own 1 crest VC short of SSD at 30 mph"
            } == {"HDM 1003.1(11), (12)"}


def test_an_own_crest_short_of_its_distance_at_20_mph():
    # 4 % up, a 20 ft curve to -4 %, 4 % down (never over 4 %): A = 8,
    # L = 2 x 125 - 1600 / 8 = 50 ft needed
    half = (BUMP_FT - 20.0) / 2.0
    a, z = vc(0.0, 99.51, 4.0, 4.0, half)
    b, z = vc(half, z, 4.0, -4.0, 20.0)
    d, z = vc(half + 20.0, z, -4.0, -4.0, half)
    p = own_path()
    p["own"][0]["profile"] = {"curves": [a, b, d]}
    (row,) = [r for r in pc.checks(corridor(joined(p)), [], [])
              if r.check.startswith("own 1 crest")]
    assert row.check == "own 1 crest VC short of SSD at 20 mph"
    assert (row.value, row.limit) == (20.0, pytest.approx(2.0 * 125.0 - 1600.0 / 8.0))


def _dms(deg):
    d = int(deg)
    m = int((deg - d) * 60.0)
    return f"{d}-{m}-{(deg - d - m / 60.0) * 3600.0:.9f}"


def concentric_own(g0, g1):
    """The road on a 500 ft left curve at 5 %, the path on the right 33 ft
    out (17 + 10 + 6) on the road's grade, and an own stretch from 11+00 to
    13+00 concentric with it (radius 533), its profile one curve from g0 %
    to g1 % rising the path's 10 ft. Beside the road the path's centreline
    runs 533 / 500 ft per road station, so its true grade is 5 / 1.066 =
    4.6904 %."""
    from bimforge.author.alignment import Profile
    road = Alignment({"station": 1000.0, "northing": 0.0, "easting": 0.0,
                      "azimuth": 0.0},
                     [{"kind": "curve", "delta": _dms(math.degrees(1000.0 / 500.0)),
                       "turn": "L", "radius": 500.0, "length": 1000.0}], name="T")
    length = 533.0 * 200.0 / 500.0
    run = [{"kind": "curve", "delta": _dms(math.degrees(200.0 / 500.0)), "turn": "L",
            "radius": 533.0, "length": length}]
    z0 = 99.51 + 0.05 * 100.0
    own = {"from": 1100, "to": 1300, "run": run, "profile": {"curves": [{
        "bvc_station": 0.0, "bvc_elev": z0, "g_in_pct": g0, "g_out_pct": g1,
        "length_ft": length, "evc_station": length,
        "evc_elev": z0 + length * (g0 + g1) / 200.0}]}}
    params = copy.deepcopy(BASE)
    params["path"] = path(side="R", separation=[[1000, 10.0]],
                          profile=grade(99.51, pct=5.0), own=[own])
    return parse(params, 1000.0, 2000.0, alignment=road,
                 profile=Profile(grade(100.0, pct=5.0)["curves"]))


#: the path's true grade beside the road, % along its centreline
TRUE_PCT = 5.0 / (1.0 + 33.0 / 500.0)


def test_a_curved_hand_over_compares_the_path_s_true_grade():
    # 4.6904 % along the own stretch carries the path's grade on: built
    (own,) = concentric_own(TRUE_PCT, TRUE_PCT).path.own
    assert own.length == pytest.approx(213.2)
    assert own.profile.elev(own.length) == pytest.approx(99.51 + 0.05 * 300.0)
    # leaving at the road's 5 % per station and easing to 4.38 % to rise
    # the same 10 ft: a 0.31 % break in the path's grade at the hand-over
    g1 = 2.0 * 1000.0 / 213.2 - 5.0
    with pytest.raises(ValueError, match=r"path\.own\[0\]\.profile: its grade at "
                                         r"the hand-over .* is 5 % and path\.profile's "
                                         r"4\.6904"):
        concentric_own(5.0, g1)
