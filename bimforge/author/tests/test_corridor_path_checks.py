"""road-corridor V1.2 part C: the path's advisory checks (HDM 1003.1)."""
import csv
import io

import pytest

from bimforge.author.alignment import Profile
from bimforge.author.corridor import path_checks as pc
from bimforge.author.tests.test_corridor_path import (GAP, NARROW, corridor, deck_path,
                                                      grade, path)


def curves(rows, s=1000.0, z=100.0):
    """A profile from (g_in, g_out, length) rows, end to end from s."""
    out = []
    for g1, g2, length in rows:
        z1 = z + g1 / 100.0 * length + (g2 - g1) / 100.0 * length / 2.0
        out.append({"bvc_station": s, "bvc_elev": round(z, 6), "g_in_pct": g1,
                    "g_out_pct": g2, "length_ft": length,
                    "evc_station": s + length, "evc_elev": round(z1, 6)})
        s, z = s + length, z1
    return {"curves": out}


def rows(found, check):
    return [(r.start, r.end, r.value, r.limit) for r in found if r.check.startswith(check)]


def test_a_6_percent_path_is_listed():
    found = pc.grade_rows(corridor(path(profile=grade(99.51, pct=6.0))))
    assert rows(found, "grade>5%") == [(pytest.approx(1000.0), pytest.approx(2000.0),
                                        pytest.approx(6.0), 5.0)]
    assert rows(found, "sustained grade>2%") == [(pytest.approx(1000.0),
                                                  pytest.approx(2000.0),
                                                  pytest.approx(1000.0), 500.0)]


def test_a_crest_short_of_ssd_at_20_mph_is_listed():
    c = corridor(path(profile=curves([(5, 5, 490), (5, -3, 20), (-3, -3, 490)])))
    assert rows(pc.crest_rows(c), "crest") == [(1490.0, 1510.0, 20.0,
                                                pytest.approx(50.0))]


def test_a_long_steep_downgrade_makes_it_30_mph():
    long_down = curves([(3, 3, 300), (3, -4.5, 100), (-4.5, -4.5, 600)])
    (row,) = pc.crest_rows(corridor(path(profile=long_down)))
    assert row.check == "crest VC short of SSD at 30 mph"
    assert (row.value, row.limit) == (100.0, pytest.approx(7.5 * 230 ** 2 / 1600))
    short_down = curves([(3, 3, 300), (3, -4.5, 100), (-4.5, -4.5, 400),
                         (-4.5, 0, 100), (0, 0, 100)])
    assert pc.crest_rows(corridor(path(profile=short_down))) == []


def test_the_crest_length_rule():
    assert pc.crest_length(8.0, 125.0) == pytest.approx(50.0)      # S > L
    assert pc.crest_length(7.5, 230.0) == pytest.approx(247.96875)  # S < L
    assert pc.crest_length(2.0, 125.0) == 0.0                      # none needed


class Rail:
    def __init__(self, side, start, end):
        self.side, self.start, self.end = side, start, end


def test_a_separation_under_10_ft_needs_a_barrier_where_no_rail_runs():
    c = corridor(path(separation=[[1000, 12.0], [1100, 8.0], [1300, 8.0], [1400, 12.0]]))
    assert rows(pc.barrier_rows(c, []), "barrier") == [
        (pytest.approx(1050.0), pytest.approx(1350.0), pytest.approx(8.0), 10.0)]
    shielded = pc.barrier_rows(c, [Rail("L", 1000.0, 1200.0), Rail("R", 1000.0, 2000.0)])
    assert rows(shielded, "barrier") == [
        (pytest.approx(1200.0), pytest.approx(1350.0), pytest.approx(8.0), 10.0)]


def test_under_5_ft_on_an_approach_is_listed():
    c = corridor(deck_path(), gaps=GAP)
    assert rows(pc.approach_rows(c), "separation<5ft") == [
        (pytest.approx(1358.8235, abs=1e-3), pytest.approx(1400.0), pytest.approx(1.5), 5.0),
        (pytest.approx(1500.0), pytest.approx(1541.1765, abs=1e-3), pytest.approx(1.5), 5.0)]
    # the deck itself is not the path's to list: no barrier row inside the gap
    assert all(r.end <= 1400.0 + 1e-6 or r.start >= 1500.0 - 1e-6
               for r in pc.barrier_rows(c, []))


def test_the_tables_have_their_headers():
    assert pc.CHECK_HEADER == "check,from,to,value,limit,reference"
    assert pc.PATH_HEADER.startswith("station,side,separation_ft,offset_ft,")
    row = pc.CheckRow("grade>5%", 1000.0, 1100.0, 6.0, 5.0, "HDM 1003.1(14)")
    assert pc.checks_csv([row]).splitlines()[1] == (
        "grade>5%,1000.00,1100.00,6.00,5.00,HDM 1003.1(14)")


def test_every_csv_row_has_the_headers_columns():
    short = curves([(5, 5, 490), (5, -3, 20), (-3, -3, 490)])
    found = pc.crest_rows(corridor(path(profile=short)))
    assert found and "," in found[0].reference
    parsed = list(csv.reader(io.StringIO(pc.checks_csv(found))))
    assert len(parsed) == 1 + len(found)
    assert all(len(r) == len(pc.CHECK_HEADER.split(",")) for r in parsed)
    assert parsed[1][5] == "HDM 1003.1(11), (12)"


def test_no_checks_is_the_header_only():
    assert pc.checks_csv([]) == pc.CHECK_HEADER + chr(10)


def test_a_path_with_no_curve_has_no_crest_rows():
    flat = curves([(2, 2, 1000)])
    assert pc.crest_rows(corridor(path(profile=flat))) == []
    assert pc.crest_rows(corridor(path(profile=grade(99.51)))) == []


def test_a_steep_grade_before_the_crest_makes_it_30_mph():
    # +4.5 % for 600 ft up to the crest: a steep run on the before side
    before = curves([(4.5, 4.5, 600), (4.5, -3, 100), (-3, -3, 300)])
    (row,) = pc.crest_rows(corridor(path(profile=before)))
    assert row.check == "crest VC short of SSD at 30 mph"
    short = curves([(4.5, 4.5, 400), (4.5, -3, 100), (-3, -3, 500)])
    assert pc.crest_rows(corridor(path(profile=short))) == []


def test_a_grade_at_exactly_5_percent_is_not_listed():
    assert pc.grade_rows(corridor(path(profile=grade(99.51, pct=5.0)))) != []  # 2 % rule
    assert rows(pc.grade_rows(corridor(path(profile=grade(99.51, pct=5.0)))),
                "grade>5%") == []
    over = pc.grade_rows(corridor(path(profile=grade(99.51, pct=5.0001))))
    assert len(rows(over, "grade>5%")) == 1


def test_a_deck_graded_over_5_percent_is_listed():
    road = Profile(grade(100.0, pct=6.0)["curves"])
    p = deck_path()
    p["profile"] = grade(99.4809, pct=6.0)
    c = corridor(p, gaps=GAP, prof=road)
    found = pc.deck_rows(c)
    assert [(r.check, r.start, r.end) for r in found] == [("deck grade>5% (or a separate path structure)", 1400.0, 1500.0)]
    assert found[0].value == pytest.approx(6.0)


def test_inside_a_path_gap_over_a_road_gap_the_path_s_grade_is_checked():
    road = Profile(grade(100.0, pct=6.0)["curves"])
    c = corridor(path(profile=grade(99.51, pct=6.0),
                      gaps=[{"from": 1380, "to": 1520, "kind": "structure"}]), gaps=GAP,
                 prof=road)
    assert rows(pc.grade_rows(c), "grade>5%") == [
        (pytest.approx(1000.0), pytest.approx(2000.0), pytest.approx(6.0), 5.0)]
    assert pc.deck_rows(c) == []
    assert rows(pc.path_gap_rows(c), "path gap over a road structure gap") == [
        (1400.0, 1500.0, 100.0, None)]
    # wired into checks(), with the overlap length as its value
    assert rows(pc.checks(c, [], []), "path gap over a road structure gap") == [
        (1400.0, 1500.0, 100.0, None)]


def test_a_steep_deck_is_listed_with_its_note():
    road = Profile(grade(100.0, pct=6.0)["curves"])
    c = corridor(path(separation=NARROW, profile=grade(99.48088, pct=6.0)), gaps=GAP,
                 prof=road)
    (row,) = pc.deck_rows(c)
    assert row.check == "deck grade>5% (or a separate path structure)"
    assert (row.start, row.end, row.value) == (pytest.approx(1400.0),
                                               pytest.approx(1500.0),
                                               pytest.approx(6.0))


def test_a_path_gap_takes_no_barrier_row():
    c = corridor(path(separation=[[1000, 10.0], [1450, 10.0], [1500, 3.0], [1550, 3.0],
                                  [1600, 10.0]],
                      gaps=[{"from": 1440, "to": 1610, "kind": "structure"}]))
    assert pc.barrier_rows(c, []) == []


def test_a_path_gap_s_stations_are_in_the_table_without_a_barrier():
    c = corridor(path(profile=grade(99.51, pct=6.0),
                      gaps=[{"from": 1380, "to": 1520, "kind": "structure"}]), gaps=GAP)
    lines = pc.path_csv(c, [], []).splitlines()[1:]
    gap = [l.split(",") for l in lines if l.endswith(",path gap")]
    assert gap and all(f[8] == "path gap" and f[9] == "" and f[10] == "path gap"
                       for f in gap)
    assert float(gap[0][0]) == pytest.approx(1380.0)
    assert float(gap[-1][0]) == pytest.approx(1520.0)


def test_a_path_gap_inside_a_road_gap_leaves_one_row_per_station():
    road = Profile(grade(100.0, pct=6.0)["curves"])
    c = corridor(path(separation=NARROW, profile=grade(99.48088, pct=6.0),
                      gaps=[{"from": 1430, "to": 1470, "kind": "structure"}]),
                 gaps=GAP, prof=road)
    fields = [l.split(",") for l in pc.path_csv(c, [], []).splitlines()[1:]]
    at = [round(float(f[0]), 2) for f in fields]
    assert len(at) == len(set(at))
    assert {f[10] for f in fields if 1430.0 <= float(f[0]) <= 1470.0} == {"path gap"}
    deck = [float(f[0]) for f in fields if f[10] == "deck"]
    assert deck and all(x < 1430.0 or x > 1470.0 for x in deck)


from bimforge.author.tests.test_corridor_path import TREAD  # noqa: E402


def test_the_equestrian_guidance_is_advisory():
    c = corridor(path(equestrian=dict(TREAD, buffer=4.0, width=6.0, clear_ft=2.0,
                                      cross_slope=-0.01)))
    got = {r.check: (r.value, r.limit) for r in pc.equestrian_rows(c)}
    assert got == {"equestrian buffer<6ft": (4.0, 6.0),
                   "equestrian tread width<8ft": (6.0, 8.0),
                   "equestrian clear<3ft": (2.0, 3.0),
                   "equestrian cross slope outside 2-5%": (pytest.approx(1.0), 2.0)}
    assert pc.equestrian_rows(corridor(path(equestrian=TREAD))) == []
    assert pc.equestrian_rows(corridor()) == []


def test_a_cross_slope_over_5_percent_is_listed_against_the_upper_limit():
    c = corridor(path(equestrian=dict(TREAD, cross_slope=-0.08)))
    (row,) = pc.equestrian_rows(c)
    assert (row.value, row.limit) == (pytest.approx(8.0), pytest.approx(5.0))


def test_a_steep_tread_is_listed():
    # 0 % to 12+00, a 10 ft curve to 12 %, 12 % to 15+00, a 10 ft curve to
    # 16 %, 16 % to 18+00, a 10 ft curve back to 0. Inside a curve from g1
    # to g2 over L the grade is g1 + (g2 - g1) x / L: over 10 % from
    # 12+00 + 10 x 10/12 = 12+08.33 to 18+00 + 10 x 6/16 = 18+03.75, 595 ft;
    # over 15 % from 15+00 + 10 x 3/4 = 15+07.50 to 18+00 + 10 x 1/16 =
    # 18+00.625, 293 ft: both over 200 ft
    prof = curves([(0, 0, 200), (0, 12, 10), (12, 12, 290), (12, 16, 10),
                   (16, 16, 290), (16, 0, 10), (0, 0, 190)])
    c = corridor(path(profile=prof, equestrian=TREAD))
    got = {r.check: (r.start, r.end, r.value) for r in pc.equestrian_rows(c)}
    assert got["equestrian grade>10% for over 200ft"] == (
        pytest.approx(1208.3333, abs=1e-3), pytest.approx(1803.75, abs=1e-3),
        pytest.approx(16.0))
    assert got["equestrian grade>15% for over 200ft"] == (
        pytest.approx(1507.5, abs=1e-3), pytest.approx(1800.625, abs=1e-3),
        pytest.approx(16.0))
    # no tread, no rows; with one, the rows are among the path's checks
    assert pc.equestrian_rows(corridor(path(profile=prof))) == []
    assert {r.check for r in pc.checks(c, [], [])} >= set(got)


def test_a_steep_descending_tread_is_listed():
    # the mirror of the climb above: -12 % and -16 % over the same stretches
    prof = curves([(0, 0, 200), (0, -12, 10), (-12, -12, 290), (-12, -16, 10),
                   (-16, -16, 290), (-16, 0, 10), (0, 0, 190)])
    c = corridor(path(profile=prof, equestrian=TREAD))
    got = {r.check: (r.start, r.end, r.value) for r in pc.equestrian_rows(c)}
    assert got["equestrian grade>10% for over 200ft"] == (
        pytest.approx(1208.3333, abs=1e-3), pytest.approx(1803.75, abs=1e-3),
        pytest.approx(16.0))
    assert got["equestrian grade>15% for over 200ft"] == (
        pytest.approx(1507.5, abs=1e-3), pytest.approx(1800.625, abs=1e-3),
        pytest.approx(16.0))


@pytest.mark.parametrize("cs", [-0.02, -0.05])
def test_a_tread_cross_slope_of_exactly_2_or_5_percent_is_not_listed(cs):
    assert pc.equestrian_rows(corridor(path(equestrian=dict(TREAD, cross_slope=cs)))) == []


def test_a_steep_stretch_of_200_ft_or_less_is_not_listed():
    # 12 % for 150 ft between two 10 ft curves: over 10 % for under 200 ft
    prof = curves([(0, 0, 300), (0, 12, 10), (12, 12, 150), (12, 0, 10),
                   (0, 0, 530)])
    assert pc.equestrian_rows(corridor(path(profile=prof, equestrian=TREAD))) == []


def test_the_tread_s_grade_is_not_checked_on_a_deck():
    # a 12 % road, the path on its deck from 1400 to 1500: the tread's grade
    # rows (over 10 % for over 200 ft) stop at the deck's ends
    road = Profile(grade(100.0, pct=12.0)["curves"])
    p = deck_path(equestrian=TREAD)
    p["profile"] = grade(99.4809, pct=12.0)
    c = corridor(p, gaps=GAP, prof=road)
    got = rows(pc.equestrian_rows(c), "equestrian grade>10%")
    assert [(a, b) for a, b, _v, _l in got] == [(pytest.approx(1000.0), 1400.0),
                                                 (1500.0, pytest.approx(2000.0))]
