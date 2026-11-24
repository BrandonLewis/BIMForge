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
                                                      level, path, pt)

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
