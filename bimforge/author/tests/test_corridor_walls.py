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


def test_a_fill_wall_and_a_cut_wall_on_one_side_are_two_walls():
    # no ground left at 4+00 and 4+25 (fill), 500 ft of cut at 4+50 and
    # 4+75: one wall of each kind, each ending at its own run's last station
    # because the station beyond is the other kind
    def dz(s, u, v):
        if u > 0.0:
            return (-500.0 if s < 437.5 else 500.0) - v
        return -5.0 - v
    found = walls.find(corridor(walls="auto"), [400.0, 425.0, 450.0, 475.0], dz)
    assert found == [Gap(400.0, 437.0, "wall", "L", None, auto="fill"),
                     Gap(438.0, 475.0, "wall", "L", None, auto="cut")]


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


def test_a_wall_with_no_section_on_it_is_refused():
    c = corridor(walls="auto").with_walls(
        [Gap(450.0, 550.0, "wall", "L", None, auto="cut")])
    with pytest.raises(ValueError, match=r"4\+50\.00 to 5\+50\.00.*no section"):
        walls.rows(c, [resolve(c, 400.0, level(40.0))], level(40.0))


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
        walls.WALL_HEADER + "\n" "R,fill,1000.00,1111.00,17.00,15.66,21.21,yes,yes\n")
    assert walls.walls_csv([]) == walls.WALL_HEADER + "\n"
    assert walls.structures_csv([walls.StructureRow("R", 1000.0, 1111.0, 21.21, 1000.0)]) == (
        walls.STRUCTURE_HEADER + "\n" "R,1000.00,1111.00,21.21,1000.00\n")
