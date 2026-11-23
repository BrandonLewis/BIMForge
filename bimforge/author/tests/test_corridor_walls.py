"""road-corridor automatic walls (V1.1): runs, heights, structure candidates."""
import copy

import pytest

from bimforge.author.corridor import walls
from bimforge.author.corridor.params import Gap, parse
from bimforge.author.corridor.section import resolve

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
    return lambda s, u, v: h - v


def test_failing_stations_make_a_wall_that_ends_where_the_slope_fits_again():
    # the left fill finds no ground within 150 ft from 4+49.5 to 5+20.5:
    # 4+50, 4+75 and 5+00 fail; 4+25 and 5+25 fit. Back from 4+50, 4+49
    # fits, so the wall starts at 4+50. On from 5+00, 5+01 to 5+20 fail and
    # 5+21 fits, so it ends at 5+20. The right side fits throughout
    def dz(s, u, v):
        deep = u > 0.0 and 449.5 <= s <= 520.5
        return (-500.0 if deep else -5.0) - v
    found = walls.find(corridor(walls="auto"),
                       [400.0, 425.0, 450.0, 475.0, 500.0, 525.0, 550.0], dz)
    assert found == [Gap(450.0, 520.0, "wall", "L", None, auto="fill")]


def test_a_wall_from_the_first_station_starts_there():
    # no ground from 4+40 to 5+10.5: 4+50 (the run's first station), 4+75
    # and 5+00 fail; on from 5+00, 5+11 fits, so the wall is 4+50 to 5+10
    def dz(s, u, v):
        return (-500.0 if u > 0.0 and 440.0 <= s <= 510.5 else -5.0) - v
    found = walls.find(corridor(walls="auto"), [450.0, 475.0, 500.0, 525.0], dz)
    assert found == [Gap(450.0, 510.0, "wall", "L", None, auto="fill")]


def test_a_wall_stops_a_foot_short_of_the_next_station_that_fits():
    # no ground from 4+50 to 4+74.5: back from 4+50, 4+49 fits; on from
    # 4+50, 4+51 to 4+74 fail, and the next foot is 4+75, the station that
    # fits: the wall ends at 4+74, its lead-in the last foot
    def dz(s, u, v):
        return (-500.0 if u > 0.0 and 450.0 <= s <= 474.5 else -5.0) - v
    found = walls.find(corridor(walls="auto"), [425.0, 450.0, 475.0], dz)
    assert found == [Gap(450.0, 474.0, "wall", "L", None, auto="fill")]


def test_a_cut_that_finds_no_ground_is_a_cut_wall():
    # 500 ft of cut on the left at both stations, 3 ft on the right
    def dz(s, u, v):
        return (500.0 if u > 0.0 else 3.0) - v
    assert walls.find(corridor(walls="auto"), [400.0, 425.0], dz) == [
        Gap(400.0, 425.0, "wall", "L", None, auto="cut")]


def test_a_fill_wall_turning_into_a_cut_wall_is_refused():
    # fill fails before 4+37.75 and cut after. The fill wall reaches on
    # from 4+25.40 to 4+37.40; a foot on, 4+38.40, needs a cut wall: no
    # slope fits between them, so neither wall has its lead-in
    def dz(s, u, v):
        if u > 0.0:
            return (-500.0 if s < 437.75 else 500.0) - v
        return -5.0 - v
    c = corridor(walls="auto")
    with pytest.raises(ValueError, match=r"L side needs a fill wall at 4\+37\.40 "
                       r"and a cut wall at 4\+38\.40.*list a wall or a structure "
                       r"gap there"):
        c.with_walls(walls.find(c, [400.4, 425.4, 450.0, 475.0], dz))


def test_automatic_walls_under_two_lead_ins_apart_are_refused():
    c = corridor(walls="auto")
    fill = Gap(400.0, 437.4, "wall", "L", None, auto="fill")
    cut = Gap(438.0, 475.0, "wall", "L", None, auto="cut")
    with pytest.raises(ValueError, match=r"fill wall on the L side from 4\+00\.00 "
                       r"to 4\+37\.40 and a cut wall from 4\+38\.00 to 4\+75\.00.*"
                       r"list a wall or a structure gap there"):
        c.with_walls([fill, cut])
    # two lead-ins apart, the slope fits between them; on the other side,
    # walls may share stations
    c.with_walls([fill, Gap(439.4, 475.0, "wall", "L", None, auto="cut")])
    c.with_walls([fill, Gap(400.0, 437.4, "wall", "R", None, auto="fill")])
    # a wall already added counts too
    with pytest.raises(ValueError, match="list a wall or a structure gap"):
        c.with_walls([fill]).with_walls([cut])


def test_a_wall_ends_a_foot_short_of_a_fractional_neighbour():
    # the left fill fails from 4+40 to 5+10.20 and again from 5+10.80; the
    # stations are 4+50, 4+75, 5+00 and 5+10.50, which fits. On from 5+00,
    # 5+01 to 5+10 fail; 5+11, a foot on, is past 5+10.50 and fails, so the
    # wall ends a foot short of the neighbour, 5+09.50, its lead-in ending
    # on 5+10.50
    def dz(s, u, v):
        deep = u > 0.0 and (440.0 <= s <= 510.2 or s >= 510.8)
        return (-500.0 if deep else -5.0) - v
    found = walls.find(corridor(walls="auto"), [450.0, 475.0, 500.0, 510.5], dz)
    assert found[0] == Gap(450.0, 509.5, "wall", "L", None, auto="fill")


def test_a_lead_in_with_no_room_is_refused():
    # the fill fails up to 4+75.20 and from 4+76: 4+75.50 fits, under a
    # foot past 4+75, and 4+76, the lead-in's end, fails
    def dz(s, u, v):
        deep = u > 0.0 and (s <= 475.2 or s >= 476.0)
        return (-500.0 if deep else -5.0) - v
    with pytest.raises(ValueError, match=r"L fill wall ending at 4\+75\.00 has "
                       r"no room for its 1 ft lead-in.*fits at 4\+75\.50 but not "
                       r"at 4\+76\.00"):
        walls.find(corridor(walls="auto"), [450.0, 475.0, 475.5], dz)


def test_a_fill_wall_s_heights_are_read_off_its_sections():
    # the ground falls 0.01 per ft along the road from 30 ft under the PGL
    # at 5+00. The wall's face is the shoulder edge (17, -0.49): at 4+50
    # the ground is at -29.5, 29.01 ft of wall; at 5+50, -30.5: 30.01 ft.
    # Over 25 ft it is too tall: a structure candidate. 4+25 and 5+75 lie
    # outside the wall and are not read
    def dz(s, u, v):
        return (-30.0 - 0.01 * (s - 500.0)) - v
    c = corridor(walls="auto", max_wall_height_ft=25).with_walls(
        [Gap(450.0, 550.0, "wall", "L", None, auto="fill")])
    secs = [resolve(c, s, dz) for s in (425.0, 450.0, 500.0, 550.0, 575.0)]
    (row,) = walls.rows(c, secs, dz)
    assert (row.side, row.kind, row.start, row.end) == ("L", "fill", 450.0, 550.0)
    assert row.offset == pytest.approx(17.0)
    assert (row.min_height, row.max_height) == pytest.approx((29.01, 30.01))
    assert row.barrier and row.too_tall


def test_a_fill_wall_at_the_height_limit_is_not_too_tall():
    # level ground 30.49 ft under the PGL: 30 ft of wall under the shoulder
    # edge (17, -0.49), at the 30 ft default and not over it
    c = corridor(walls="auto").with_walls(
        [Gap(450.0, 550.0, "wall", "L", None, auto="fill")])
    secs = [resolve(c, s, level(-30.49)) for s in (450.0, 550.0)]
    (row,) = walls.rows(c, secs, level(-30.49))
    assert row.max_height == pytest.approx(30.0)
    assert row.barrier and not row.too_tall


def test_a_cut_wall_is_as_tall_as_the_ground_over_its_shoulder_edge():
    # 40 ft of ground over the PGL; the 10 ft shoulder's edge is at
    # (22, -0.74): 40.74 ft of wall, no barrier, never a structure
    c = corridor(walls="auto").with_walls(
        [Gap(450.0, 550.0, "wall", "L", None, auto="cut")])
    secs = [resolve(c, s, level(40.0)) for s in (450.0, 500.0, 550.0)]
    (row,) = walls.rows(c, secs, level(40.0))
    assert (row.kind, row.offset) == ("cut", pytest.approx(22.0))
    assert (row.min_height, row.max_height) == pytest.approx((40.74, 40.74))
    assert not row.barrier and not row.too_tall


def test_a_wall_s_height_is_sampled_between_its_sections():
    # a cut wall from 4+50 to 5+50, sections every 50 ft; the ground is 40
    # ft up but for a 5 ft bump peaking at 4+75, between sections: 45 ft
    # there, 45.74 ft of wall over the shoulder edge (22, -0.74). Read every
    # 5 ft, the peak is caught; the sections alone would give 40.74
    def dz(s, u, v):
        return 40.0 + max(0.0, 5.0 - abs(s - 475.0)) - v
    c = corridor(walls="auto").with_walls(
        [Gap(450.0, 550.0, "wall", "L", None, auto="cut")])
    secs = [resolve(c, s, dz) for s in (450.0, 500.0, 550.0)]
    (row,) = walls.rows(c, secs, dz)
    assert (row.min_height, row.max_height) == pytest.approx((40.74, 45.74))


def test_too_tall_walls_side_by_side_are_one_structure_candidate():
    rows = [walls.WallRow("L", "fill", 450.0, 550.0, 17.0, 29.0, 31.0, True),
            walls.WallRow("R", "fill", 500.0, 600.0, 17.0, 26.0, 28.0, True),
            walls.WallRow("L", "fill", 700.0, 750.0, 17.0, 31.0, 32.5, True),
            walls.WallRow("R", "fill", 800.0, 850.0, 17.0, 10.0, 12.0, False)]
    stations = [450.0 + 25.0 * i for i in range(17)]           # 4+50 to 8+50

    def ground(s):
        # lowest at 5+20; of the stations, 5+25 is nearest (0.0025 ft up);
        # on 7+00 to 7+50 the ground falls toward 5+20, lowest at 7+00
        return 270.0 + 0.0001 * (s - 520.0) ** 2
    assert walls.structures(rows, stations, ground) == [
        walls.StructureRow("both", 450.0, 600.0, 31.0, 525.0),
        walls.StructureRow("L", 700.0, 750.0, 32.5, 700.0)]


def test_the_wall_and_structure_tables():
    rows = [walls.WallRow("R", "fill", 1000.0, 1111.0, 17.0, 15.66, 21.21, True)]
    assert walls.walls_csv(rows) == (
        walls.WALL_HEADER + "\n" "R,fill,outer,1000.00,1111.00,17.00,15.66,21.21,yes,yes\n")
    assert walls.walls_csv([]) == walls.WALL_HEADER + "\n"
    assert walls.structures_csv([walls.StructureRow("R", 1000.0, 1111.0, 21.21, 1000.0)]) == (
        walls.STRUCTURE_HEADER + "\n" "R,1000.00,1111.00,21.21,1000.00,road\n")


def test_same_kind_walls_closer_than_a_station_interval_are_one_wall():
    # the left fill finds no ground from 4+49.5 to 5+00.5 and from 5+10.5 to
    # 5+60.5, fitting for 10 ft between (a station at 5+05 sees it). find
    # makes 4+50 to 5+00 (5+01 fits) and 5+11 (5+10 fits) to 5+60 (5+61
    # fits): 11 ft apart, under the 25 ft station interval, so one wall,
    # not two with a sliver of slope between
    def dz(s, u, v):
        deep = u > 0.0 and (449.5 <= s <= 500.5 or 510.5 <= s <= 560.5)
        return (-500.0 if deep else -5.0) - v
    c = corridor(walls="auto")
    found = walls.find(c, [425.0, 450.0, 475.0, 500.0, 505.0, 525.0, 550.0, 575.0], dz)
    assert found == [Gap(450.0, 500.0, "wall", "L", None, auto="fill"),
                     Gap(511.0, 560.0, "wall", "L", None, auto="fill")]
    assert [g for g in c.with_walls(found).gaps if g.auto] == [
        Gap(450.0, 560.0, "wall", "L", None, auto="fill")]


def test_same_kind_walls_merge_and_other_kinds_or_a_bridge_keep_them_apart():
    c = corridor(walls="auto")
    a = Gap(400.0, 437.4, "wall", "L", None, auto="fill")
    # under two lead-ins apart but the same kind: one wall, no error, and a
    # wall added later merges with one already there
    assert [g for g in c.with_walls([a, Gap(438.0, 475.0, "wall", "L", None,
                                            auto="fill")]).gaps if g.auto] == [
        Gap(400.0, 475.0, "wall", "L", None, auto="fill")]
    assert [g for g in c.with_walls([a]).with_walls(
        [Gap(450.0, 475.0, "wall", "L", None, auto="fill")]).gaps if g.auto] == [
        Gap(400.0, 475.0, "wall", "L", None, auto="fill")]
    # 25 ft apart is not under the interval; across a structure gap never
    b = Gap(462.4, 475.0, "wall", "L", None, auto="fill")
    assert len([g for g in c.with_walls([a, b]).gaps if g.auto]) == 2
    bridged = corridor(walls="auto", gaps=[{"from": 440, "to": 445, "kind": "structure"}])
    assert len([g for g in bridged.with_walls(
        [a, Gap(446.0, 475.0, "wall", "L", None, auto="fill")]).gaps if g.auto]) == 2


# --- V1.2 C: walls in the strip and on the path's outer side ---------------

from dataclasses import replace

from bimforge.author.alignment import Alignment, Profile
from bimforge.author.corridor import walls as W
from bimforge.author.corridor.params import Gap as _Gap
from bimforge.author.corridor.params import parse as _parse

_AL = Alignment({"station": 1000.0, "northing": 0.0, "easting": 0.0},
                [{"kind": "tangent", "bearing": "N 0-0-0 E", "length": 1000.0}],
                name="T")
_PROF = Profile([{"bvc_station": 1000.0, "bvc_elev": 100.0, "g_in_pct": 0.0,
                  "g_out_pct": 0.0, "length_ft": 1000.0, "evc_station": 2000.0,
                  "evc_elev": 100.0}])


def _path_corridor(elev, **over):
    """BASE (the module's) with walls: auto and a path on the left 10 ft
    out, level at `elev`."""
    p = copy.deepcopy(BASE)
    p.update(walls="auto", **over)
    p["path"] = {"side": "L", "separation": [[1000, 10.0]], "width": 12.0,
                 "courses": [{"name": "PATH-AB", "type": "CORE", "thickness": 0.75}],
                 "profile": {"curves": [{"bvc_station": 1000.0, "bvc_elev": elev,
                                         "g_in_pct": 0.0, "g_out_pct": 0.0,
                                         "length_ft": 1000.0, "evc_station": 2000.0,
                                         "evc_elev": elev}]}}
    return _parse(p, 1000.0, 2000.0, alignment=_AL, profile=_PROF)


def _level(h):
    return lambda s, u, v: h - v


def test_a_wall_s_token_says_where_it_stands_and_what_it_carries():
    assert [(_Gap(0, 1, "wall", "L", auto=a).strip, _Gap(0, 1, "wall", "L", auto=a).carries)
            for a in ("fill", "cut", "path-fill", "strip-road", "strip-path")] == [
        (False, "road"), (False, "road"), (False, "path"), (True, "path"),
        (True, "path")]


def test_a_path_far_below_the_road_takes_a_strip_wall_over_its_stations():
    c = _path_corridor(87.51)                              # 12 ft below the edge
    found = W.find(c, [1400.0, 1425.0, 1450.0], _level(-5.0))
    assert [(g.side, g.auto, g.start, g.end) for g in found] == [
        ("L", "strip-road", 1400.0, 1450.0)]               # the run's ends
    c = c.with_walls(found)
    (row,) = [r for r in W.rows(c, [], _level(-5.0)) if r.location == "strip"]
    assert (row.kind, row.carries, row.barrier) == ("wall-road", "path", True)
    # the road's edge of shoulder (-0.49) over the strip at q (-12.59)
    assert row.max_height == pytest.approx(12.10)
    assert row.offset == pytest.approx(17.0)


def test_a_path_far_above_the_road_takes_a_wall_at_its_shoulder():
    c = _path_corridor(111.51)                             # 12 ft above
    c = c.with_walls(W.find(c, [1400.0, 1450.0], _level(-5.0)))
    rows = [r for r in W.rows(c, [], _level(-5.0)) if r.location == "strip"]
    (row,) = rows
    assert (row.kind, row.barrier) == ("wall-path", False)
    assert row.max_height == pytest.approx(13.30)          # q 11.41 over -1.89
    assert row.offset == pytest.approx(25.0)


def test_a_strip_wall_and_an_outer_wall_may_share_stations():
    # 12 ft above, and a footprint at 50 ft: the path's 2:1 outer fill from
    # o (41, 11.17) would daylight 32.34 ft beyond it, past the footprint
    c = _path_corridor(111.51, section=dict(BASE["section"], side_slopes=dict(
        BASE["section"]["side_slopes"], footprint_ft={"L": 50.0})))
    found = W.find(c, [1400.0, 1450.0], _level(-5.0))
    assert sorted((g.auto, g.strip) for g in found) == [
        ("path-fill", False), ("strip-path", True)]
    c = c.with_walls(found)                                # no "too close" error
    assert c.wall("L", 1425.0).auto == "path-fill"
    assert c.wall("L", 1425.0, strip=True).auto == "strip-path"


def test_a_too_tall_strip_wall_is_a_structure_candidate_carrying_the_path():
    c = _path_corridor(87.51, max_wall_height_ft=10)
    c = c.with_walls(W.find(c, [1400.0, 1450.0], _level(-5.0)))
    rows = W.rows(c, [], _level(-5.0))
    (cand,) = W.structures(rows, [1400.0, 1450.0], lambda s: 95.0)
    assert (cand.side, cand.carries) == ("L", "path")
    assert W.STRUCTURE_HEADER.endswith(",carries")
    assert W.structures_csv([cand]).splitlines()[1].endswith(",path")
    assert W.WALL_HEADER.split(",")[:3] == ["side", "kind", "location"]


def test_only_a_path_wall_ends_the_path_s_outer_slope():
    # a road fill wall on the path's side at a path station (set by hand:
    # with_walls refuses one over the path's stations, and one can only
    # touch them at its end) is the road's, not the path's: the path's
    # outer slope there is still a slope, and asks for its own wall
    from bimforge.author.corridor import path as path_mod
    from bimforge.author.corridor.section import grade_edge
    c = _path_corridor(99.51)                              # level with the road
    road = replace(c, gaps=(_Gap(1000.0, 1400.0, "wall", "L", None, auto="fill"),))
    hinge = (lambda u, v: (u, v - c.depth()))(*grade_edge(c, 1400.0, "L"))
    sec = resolve(road, 1400.0, _level(-5.0))
    assert sec.sides["L"].line[-1] != sec.sides["L"].line[-2]   # a slope
    assert path_mod.needs_wall(road, 1400.0, hinge, _level(-500.0)) == "path-fill"
    path = replace(c, gaps=(_Gap(1000.0, 1400.0, "wall", "L", None,
                                 auto="path-fill"),))
    assert path_mod.needs_wall(path, 1400.0, hinge, _level(-500.0)) is None
    sec = resolve(path, 1400.0, _level(-5.0))
    assert sec.sides["L"].line[-1] == sec.sides["L"].line[-2]   # [o, o]


def test_road_walls_on_either_side_of_the_path_are_not_merged_over_it():
    # path stations shorter than an interval: two road fill walls just
    # outside them stay two, so no road wall stands on the path's stations
    c = _path_corridor(99.51, stations={"interval": 50.0})
    c = replace(c, path=replace(c.path, s_start=1410.0, s_end=1430.0))
    merged = c.with_walls([_Gap(1380.0, 1408.0, "wall", "L", None, auto="fill"),
                           _Gap(1432.0, 1460.0, "wall", "L", None, auto="fill")])
    assert [(g.start, g.end) for g in merged.gaps if g.auto == "fill"] == [
        (1380.0, 1408.0), (1432.0, 1460.0)]
    # and one handed in over the path's stations is refused
    with pytest.raises(ValueError, match="road fill wall on the L side .* overlaps "
                                         "the path's stations"):
        c.with_walls([_Gap(1400.0, 1420.0, "wall", "L", None, auto="fill")])
