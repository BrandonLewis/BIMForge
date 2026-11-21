"""road-corridor params: validation and by-station reads (P.6)."""
import copy

import pytest

from bimforge.author.corridor.params import NORMAL_CROWN, parse

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
