"""road-corridor params: validation and by-station reads (P.6)."""
import copy

import pytest

from bimforge.author.corridor.params import (CUT_WALL_SHOULDER_FT, NORMAL_CROWN,
                                             Catchment, FaceBench, Gap, Guard,
                                             Rock, Steep, parse)

BASE = {"section": {
    "components": [{"name": "lane", "kind": "carriageway", "width": 12.0},
                   {"name": "shoulder", "kind": "shoulder", "width": 5.0,
                    "slope": -0.05}],
    "courses": [{"name": "HMA", "type": "PAVEMENT", "thickness": 0.4},
                {"name": "AB", "type": "CORE", "thickness": 1.0}],
    "side_slopes": {"cut": {"ratio": 2.0, "ditch": {"width": 4.0, "depth": 1.5}},
                    "fill": {"ratio": 2.0}, "daylight_limit_ft": 150}}}


def params(**over):
    p = copy.deepcopy(BASE)
    p.update(over)
    return p


def test_defaults_are_a_normal_crown_and_25_ft_sections():
    c = parse(params(), 1000.0, 2000.0)
    assert c.cross_slope("L", 1500.0) == NORMAL_CROWN == c.cross_slope("R", 1500.0)
    assert (c.interval, c.band, c.shrink, c.swell) == (25.0, 100.0, 0.0, 0.0)
    assert c.depth() == pytest.approx(1.4)


def test_superelevation_interpolates_each_side():
    c = parse(params(superelevation=[[1000, -0.02, -0.02], [1400, 0.06, -0.06]]),
              1000.0, 2000.0)
    assert c.cross_slope("L", 1200.0) == pytest.approx(0.02)
    assert c.cross_slope("R", 1200.0) == pytest.approx(-0.04)
    assert c.cross_slope("L", 1900.0) == pytest.approx(0.06)


def test_a_width_table_tapers_one_side():
    c = parse(params(widths=[{"component": "shoulder", "side": "R",
                              "at": [[1200, 5.0], [1300, 10.0]]}]), 1000.0, 2000.0)
    shoulder = c.components[1]
    assert c.width(shoulder, "R", 1250.0) == pytest.approx(7.5)
    assert c.width(shoulder, "L", 1250.0) == 5.0
    assert c.max_half_width() == 22.0


def test_structure_gaps_split_the_runs():
    c = parse(params(gaps=[{"from": 1400, "to": 1500, "kind": "structure"}]),
              1000.0, 2000.0)
    assert c.runs() == [(1000.0, 1400.0), (1500.0, 2000.0)]


def test_stations_take_every_interval_band_table_and_wall_end():
    c = parse(params(gaps=[{"from": 1110, "to": 1130, "kind": "wall", "side": "L",
                            "offset": 30}],
                     stations={"interval": 50, "band": 100}), 1000.0, 2000.0)
    assert c.stations(1000.0, 1200.0, extra=[1075.5]) == [
        1000.0, 1050.0, 1075.5, 1100.0, 1109.0, 1110.0, 1130.0, 1131.0,
        1150.0, 1200.0]
    assert c.wall("L", 1120.0).offset == 30.0
    assert c.wall("R", 1120.0) is None


@pytest.mark.parametrize("over, match", [
    ({"gaps": [{"from": 1100, "to": 1300, "kind": "structure"},
               {"from": 1200, "to": 1400, "kind": "structure"}]}, "overlaps"),
    ({"gaps": [{"from": 1100, "to": 1300, "kind": "wall", "side": "L", "offset": 30},
               {"from": 1200, "to": 1400, "kind": "wall", "side": "L", "offset": 30}]},
     "overlaps"),
    ({"gaps": [{"from": 1100, "to": 1300, "kind": "wall", "side": "L", "offset": 30},
               {"from": 1200, "to": 1400, "kind": "structure"}]}, "overlaps"),
    ({"gaps": [{"from": 1100, "to": 1500, "kind": "wall", "side": "L", "offset": 30},
               {"from": 1200, "to": 1300, "kind": "wall", "side": "L", "offset": 30}]},
     "overlaps"),
    ({"gaps": [{"from": 1100, "to": float("nan"), "kind": "structure"}]}, "gaps.*finite"),
    ({"section": {**BASE["section"], "components": [{"kind": "carriageway", "width": 12}]}},
     r"components\[0\].name"),
    ({"widths": [{"component": "shoulder", "side": "R", "at": [[1200]]}]},
     r"\[station, width\]"),
    ({"widths": [{"component": "shoulder", "side": "R",
                  "at": [[3000, 5.0], [3100, 6.0]]}]}, "off the alignment"),
    ({"widths": [{"component": "shoulder", "side": "R",
                  "at": [[1200, 0.0], [1300, 5.0]]}]}, "must be positive"),
    ({"section": {**BASE["section"], "components": [
        {"name": "lane", "kind": "carriageway", "width": 0.0}]}}, "must be positive"),
    ({"section": {**BASE["section"], "courses": [
        {"name": "HMA", "type": "PAVEMENT", "thickness": 0.0}]}}, "must be positive"),
    ({"superelevation": [[1000, -0.02, float("inf")]]}, "finite"),
    ({"superelevation": [[1000, -0.02, -0.02, 0.0]]}, r"\[station, left, right\]"),
    ({"gaps": [{"from": 1900, "to": 2100, "kind": "structure"}]}, "off the alignment"),
    ({"gaps": [{"from": 1100, "to": 1200, "kind": "wall", "offset": 30}]}, "side L or R"),
    ({"superelevation": [[900, -0.02, -0.02]]}, "off the alignment"),
    ({"superelevation": [[1000, -0.02]]}, r"\[station, left, right\]"),
    ({"widths": [{"component": "shoulder", "side": "R",
                  "at": [[1200, 5.0], [1300, 0.0]]}]}, "must be positive"),
    ({"widths": [{"component": "verge", "side": "R", "at": [[1200, 5.0]]}]},
     "no component named"),
    ({"mass_haul": {"shrink": 1.0}}, "below 1"),
    ({"stations": {"interval": 0}}, "must be positive"),
])
def test_bad_params_are_refused(over, match):
    with pytest.raises(ValueError, match=match):
        parse(params(**over), 1000.0, 2000.0)


def test_a_course_needs_a_course_type():
    p = params()
    p["section"]["courses"][0]["type"] = "BASE"
    with pytest.raises(ValueError, match="BASE"):
        parse(p, 1000.0, 2000.0)


def test_a_corridor_needs_components_and_courses():
    p = params()
    p["section"]["courses"] = []
    with pytest.raises(ValueError, match="at least one course"):
        parse(p, 1000.0, 2000.0)


def test_walls_on_opposite_sides_may_overlap():
    c = parse(params(gaps=[
        {"from": 1100, "to": 1300, "kind": "wall", "side": "L", "offset": 30},
        {"from": 1200, "to": 1400, "kind": "wall", "side": "R", "offset": 25}]),
        1000.0, 2000.0)
    assert c.wall("L", 1250.0).offset == 30.0
    assert c.wall("R", 1250.0).offset == 25.0
    assert c.wall("L", 1350.0) is None
    assert c.stations(1000.0, 1500.0) == [
        1000.0, 1025.0, 1050.0, 1075.0, 1099.0, 1100.0, 1125.0, 1150.0, 1175.0,
        1199.0, 1200.0, 1225.0, 1250.0, 1275.0, 1300.0, 1301.0, 1325.0,
        1350.0, 1375.0, 1400.0, 1401.0, 1425.0, 1450.0, 1475.0, 1500.0]


def test_an_alignment_must_have_length():
    with pytest.raises(ValueError, match="alignment"):
        parse(params(), 1000.0, 1000.0)


def test_a_missing_field_names_the_field():
    p = params()
    del p["section"]["courses"][0]["thickness"]
    with pytest.raises(ValueError, match=r"courses\[0\].thickness"):
        parse(p, 1000.0, 2000.0)


@pytest.mark.parametrize("crown", ["centerline", None])
def test_the_crown_is_the_centreline(crown):
    sec = dict(BASE["section"], crown=crown) if crown else BASE["section"]
    parse({"section": sec}, 1000.0, 2000.0)


@pytest.mark.parametrize("crown", ["offset", "left edge", 3.0])
def test_another_crown_is_refused(crown):
    with pytest.raises(ValueError, match=r"section\.crown.*centerline"):
        parse({"section": dict(BASE["section"], crown=crown)}, 1000.0, 2000.0)



STEEP_FILL = {"ratio": 4.0, "steep": {"ratio": 2.0, "above_height_ft": 10.0}}
ROCK_CUT = {"ratio": 2.0, "ditch": {"width": 4.0, "depth": 1.5},
            "rock": {"depth_ft": 8.0, "ratio": 0.5, "bench_ft": 6.0}}


def slopes(**ss):
    """BASE with side_slopes keys replaced."""
    p = copy.deepcopy(BASE)
    p["section"]["side_slopes"].update(copy.deepcopy(ss))
    return p


def test_without_the_v11_keys_a_corridor_is_v1():
    c = parse(params(), 1000.0, 2000.0)
    assert (c.slopes.steep, c.slopes.rock, c.slopes.footprint) == (None, None, None)
    assert (c.auto_walls, c.max_wall_height, c.guard) == (False, 30.0, None)


def test_a_steep_rule_brings_a_guardrail_at_its_defaults():
    c = parse(slopes(fill=STEEP_FILL), 1000.0, 2000.0)
    assert c.slopes.fill_ratio == 4.0
    assert c.slopes.steep == Steep(ratio=2.0, above_height=10.0)
    assert c.guard == Guard(speed_mph=45, rail_depth=1.44)
    # the hinge 30 in behind the back of post: 1.44 + 2.5 = 3.94 ft from
    # the rail face
    assert c.guard.widening == pytest.approx(3.94)


def test_a_guardrail_block_sets_its_speed_and_depth():
    p = slopes(fill=STEEP_FILL)
    p["guardrail"] = {"design_speed_mph": 50, "rail_depth_ft": 1.77}
    assert parse(p, 1000.0, 2000.0).guard == Guard(speed_mph=50, rail_depth=1.77)


def test_rock_depth_is_one_value_or_rows_by_station():
    c = parse(slopes(cut=ROCK_CUT), 1000.0, 2000.0)
    assert c.slopes.rock == Rock(depth=((1000.0, 8.0),), ratio=0.5, bench=6.0)
    assert c.slopes.rock.depth_at(1500.0) == 8.0
    rows = copy.deepcopy(ROCK_CUT)
    rows["rock"]["depth_ft"] = [[1200, 8.0], [1600, 12.0]]
    rock = parse(slopes(cut=rows), 1000.0, 2000.0).slopes.rock
    # 14+00 is halfway from 12+00 (8 ft) to 16+00 (12 ft): 10 ft; the end
    # values hold outside the rows
    assert (rock.depth_at(1400.0), rock.depth_at(1100.0),
            rock.depth_at(1900.0)) == (10.0, 8.0, 12.0)


def tall_rock(**rock):
    """BASE with ROCK_CUT's rock taking `rock`'s keys besides its own."""
    cut = copy.deepcopy(ROCK_CUT)
    cut["rock"].update(rock)
    return slopes(cut=cut)


def test_face_benches_and_a_catchment_are_optional_rock_keys():
    rock = parse(slopes(cut=ROCK_CUT), 1000.0, 2000.0).slopes.rock
    assert (rock.face_bench, rock.catchment) == (None, None)
    rock = parse(tall_rock(face_bench={"every_ft": 30, "width_ft": 10},
                           catchment={"width_ft": 10, "depth_ft": 3}),
                 1000.0, 2000.0).slopes.rock
    assert rock.face_bench == FaceBench(every=30.0, width=10.0, max=4)
    assert rock.catchment == Catchment(width=10.0, depth=3.0)
    rock = parse(tall_rock(face_bench={"every_ft": 30, "width_ft": 10, "max": 2}),
                 1000.0, 2000.0).slopes.rock
    assert rock.face_bench.max == 2


FACE = {"every_ft": 30, "width_ft": 10}


@pytest.mark.parametrize("p, match", [
    (tall_rock(face_bench=30), r"rock\.face_bench: a mapping"),
    (tall_rock(face_bench={"width_ft": 10}),
     r"rock\.face_bench\.every_ft: expected a number"),
    (tall_rock(face_bench={"every_ft": 0, "width_ft": 10}),
     r"rock\.face_bench\.every_ft: must be positive"),
    (tall_rock(face_bench={"every_ft": 30, "width_ft": -1}),
     r"rock\.face_bench\.width_ft: must be positive"),
    (tall_rock(face_bench={**FACE, "max": 0}),
     r"rock\.face_bench\.max: a whole number of at least 1, got 0"),
    (tall_rock(face_bench={**FACE, "max": 2.5}),
     r"rock\.face_bench\.max: a whole number of at least 1, got 2\.5"),
    (tall_rock(face_bench={**FACE, "max": True}),
     r"rock\.face_bench\.max: a whole number of at least 1, got True"),
    (tall_rock(face_bench=FACE, catchment=[10, 3]), r"rock\.catchment: a mapping"),
    (tall_rock(face_bench=FACE, catchment={"width_ft": 0, "depth_ft": 3}),
     r"rock\.catchment\.width_ft: must be positive"),
    (tall_rock(face_bench=FACE, catchment={"width_ft": 10}),
     r"rock\.catchment\.depth_ft: expected a number"),
    # the catchment is for faces taller than face_bench.every_ft
    (tall_rock(catchment={"width_ft": 10, "depth_ft": 3}),
     r"rock\.catchment: needs rock\.face_bench"),
])
def test_bad_tall_rock_params_are_refused(p, match):
    with pytest.raises(ValueError, match=match):
        parse(p, 1000.0, 2000.0)


def test_a_catchment_needs_a_ditch_to_widen():
    cut = {k: v for k, v in copy.deepcopy(ROCK_CUT).items() if k != "ditch"}
    cut["rock"].update(face_bench=FACE, catchment={"width_ft": 10, "depth_ft": 3})
    with pytest.raises(ValueError, match=r"rock\.catchment: needs a cut\.ditch"):
        parse(slopes(cut=cut), 1000.0, 2000.0)


def test_walls_auto_the_footprint_and_the_wall_height():
    p = slopes(footprint_ft={"L": 120, "R": 100})
    p.update(walls="auto", max_wall_height_ft=25)
    c = parse(p, 1000.0, 2000.0)
    assert c.slopes.footprint == {"L": 120.0, "R": 100.0}
    assert (c.auto_walls, c.max_wall_height) == (True, 25.0)


def test_a_cut_wall_widens_its_shoulder_to_10_ft_over_a_1_ft_lead_in():
    c = parse(params(walls="auto"), 1000.0, 2000.0).with_walls(
        [Gap(1400.0, 1600.0, "wall", "L", None, auto="cut")])
    lane, shoulder = c.components
    assert CUT_WALL_SHOULDER_FT == 10.0
    assert c.wall("L", 1500.0).auto == "cut"
    assert c.wall("L", 1500.0).offset is None
    # 10 ft through the wall; halfway through each 1 ft lead-in, 7.5 ft
    # (5 + (10 - 5) x 0.5); 1 ft outside each end, the 5 ft shoulder again
    assert [c.width(shoulder, "L", s)
            for s in (1399.0, 1399.5, 1400.0, 1500.0, 1600.0, 1600.5, 1601.0)
            ] == pytest.approx([5.0, 7.5, 10.0, 10.0, 10.0, 7.5, 5.0])
    assert c.width(shoulder, "R", 1500.0) == 5.0
    assert c.width(lane, "L", 1500.0) == 12.0
    assert c.etw("L", 1500.0) == 12.0
    # the wall's ends and 1 ft outside them are stations, as a listed wall's
    assert c.stations(1350.0, 1650.0) == [
        1350.0, 1375.0, 1399.0, 1400.0, 1425.0, 1450.0, 1475.0, 1500.0,
        1525.0, 1550.0, 1575.0, 1600.0, 1601.0, 1625.0, 1650.0]


def test_a_fill_wall_leaves_the_shoulder_alone():
    c = parse(params(walls="auto"), 1000.0, 2000.0).with_walls(
        [Gap(1400.0, 1600.0, "wall", "R", None, auto="fill")])
    assert c.width(c.components[1], "R", 1500.0) == 5.0


def test_an_automatic_wall_against_a_listed_one_is_refused():
    c = parse(params(walls="auto", gaps=[{"from": 1100, "to": 1300, "kind": "wall",
                                          "side": "L", "offset": 30}]), 1000.0, 2000.0)
    # 13+00.50's lead-in, 12+99.50, is inside the listed wall
    with pytest.raises(ValueError, match=r"walls: auto puts a fill wall on the L "
                       r"side from 13\+00\.50 to 14\+00\.00, against the listed "
                       r"wall gap 11\+00\.00 to 13\+00\.00"):
        c.with_walls([Gap(1300.5, 1400.0, "wall", "L", None, auto="fill")])
    c.with_walls([Gap(1300.5, 1400.0, "wall", "R", None, auto="fill")])  # the other side


def test_a_cut_wall_needs_a_shoulder_to_widen():
    p = params(walls="auto")
    p["section"]["components"] = [{"name": "lane", "kind": "carriageway", "width": 12.0}]
    c = parse(p, 1000.0, 2000.0)
    with pytest.raises(ValueError, match="needs a shoulder component"):
        c.with_walls([Gap(1400.0, 1600.0, "wall", "L", None, auto="cut")])


@pytest.mark.parametrize("p, match", [
    (slopes(fill={"ratio": 4.0, "steep": {"ratio": 4.0, "above_height_ft": 10.0}}),
     r"steep\.ratio: 4 is not steeper than fill\.ratio 4"),
    (slopes(fill={"ratio": 4.0, "steep": {"ratio": 2.0, "above_height_ft": 0.0}}),
     r"steep\.above_height_ft: must be positive"),
    (slopes(fill={"ratio": 4.0, "steep": {"ratio": 2.0,
                                          "above_height_ft": float("inf")}}),
     r"steep\.above_height_ft: expected a finite number"),
    (slopes(cut={**ROCK_CUT, "rock": {"depth_ft": 8.0, "ratio": 2.0, "bench_ft": 6.0}}),
     r"rock\.ratio: 2 is not steeper than cut\.ratio 2"),
    (slopes(cut={**ROCK_CUT, "rock": {"depth_ft": -1.0, "ratio": 0.5, "bench_ft": 6.0}}),
     r"rock\.depth_ft: must be positive"),
    (slopes(cut={**ROCK_CUT, "rock": {"depth_ft": 8.0, "ratio": 0.5, "bench_ft": 0.0}}),
     r"rock\.bench_ft: must be positive"),
    (slopes(cut={**ROCK_CUT, "rock": {"depth_ft": [[3000, 8.0]], "ratio": 0.5,
                                      "bench_ft": 6.0}}), "off the alignment"),
    (slopes(cut={**ROCK_CUT, "rock": {"depth_ft": [[1500, 8.0], [1200, 9.0]],
                                      "ratio": 0.5, "bench_ft": 6.0}}),
     "strictly ascending"),
    (slopes(footprint_ft={"L": 0.0}), r"footprint_ft\.L: must be positive"),
    (slopes(footprint_ft={"X": 10.0}), r"footprint_ft: a mapping of L and R"),
    (params(max_wall_height_ft=float("nan")), r"max_wall_height_ft: expected a finite"),
    (params(max_wall_height_ft=0), r"max_wall_height_ft: must be positive"),
    (params(walls="yes"), r"walls: 'yes' is not 'auto'"),
    (params(walls=[{"from": 1100, "to": 1200}]), r"walls: .* is not 'auto'"),
    (params(guardrail={"design_speed_mph": 55}),
     r"design_speed_mph: 55 mph is not in the runout table \(45, 50 mph\)"),
    (params(guardrail={"rail_depth_ft": 0}), r"rail_depth_ft: must be positive"),
    (slopes(fill={"ratio": 4.0, "steep": 2.0}), r"fill\.steep: a mapping"),
    (slopes(cut={"ratio": 2.0, "rock": 0.5}), r"cut\.rock: a mapping"),
    (params(guardrail=[]), r"guardrail: a mapping"),
    (params(guardrail=0), r"guardrail: a mapping"),
    (params(guardrail=""), r"guardrail: a mapping"),
])
def test_bad_v11_params_are_refused(p, match):
    with pytest.raises(ValueError, match=match):
        parse(p, 1000.0, 2000.0)


def test_an_automatic_wall_clears_a_listed_one_by_both_lead_ins():
    c = parse(params(walls="auto", gaps=[{"from": 1100, "to": 1300, "kind": "wall",
                                          "side": "L", "offset": 30}]), 1000.0, 2000.0)
    with pytest.raises(ValueError, match="against the listed wall gap"):
        c.with_walls([Gap(1301.5, 1400.0, "wall", "L", None, auto="fill")])
    c.with_walls([Gap(1302.5, 1400.0, "wall", "L", None, auto="fill")])
