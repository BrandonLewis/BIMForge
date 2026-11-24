"""road-corridor V1.2 part C: own stretches, where the path leaves the road
(P.6)."""
import copy

import pytest

from bimforge.author.tests.test_corridor_path import corridor, path

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
    assert [(o.index, o.start, o.alignment.name) for o in got] == [
        (1, 1100.0, "T path 1"), (2, 1600.0, "T path 2")]


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
    ({"gaps": [{"from": 400, "to": 500, "kind": "structure"}]},
     r"path\.own\[0\]\.gaps\[0\]: 4\+00\.00 to 5\+00\.00 is outside"),
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
