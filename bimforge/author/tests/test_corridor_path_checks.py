"""road-corridor V1.2 part C: the path's advisory checks (HDM 1003.1)."""
import pytest

from bimforge.author.corridor import path_checks as pc
from bimforge.author.tests.test_corridor_path import (GAP, NARROW, corridor,
                                                      deck_path, grade, path)


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
