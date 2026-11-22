"""road-corridor guardrail runs (V1.1): the length of need by hand.

The cases are a two-lane road with 12 ft lanes and 5 ft shoulders, the rail
face at the shoulder edge: 5 ft from the edge of traveled way (L2), 17 ft
from the centreline (the opposing lane's L). LH is 20 ft.
"""
import pytest

from bimforge.author.corridor import guardrail as gr
from bimforge.author.corridor.guardrail import AGT, TERMINAL, WALL, RailRun

ENDS = ((1000.0, TERMINAL), (2000.0, TERMINAL))


def test_length_of_need_at_45_and_50_mph():
    # 45 mph, LR 195: own lane (20 - 5) / (20 / 195) = 146.25, 11.7
    # elements, so 12: 150 ft; opposing (20 - 17) / (20 / 195) = 29.25, so
    # 3 elements: 37.5 ft
    assert gr.need(5.0, 45) == 150.0
    assert gr.need(17.0, 45) == 37.5
    # 50 mph, LR 230: 15 x 230 / 20 = 172.5, so 14 elements: 175 ft;
    # 3 x 230 / 20 = 34.5, so 37.5 ft
    assert gr.need(5.0, 50) == 175.0
    assert gr.need(17.0, 50) == 37.5
    # a rail face beyond the clear zone needs no length: 20 - 22 < 0
    assert gr.need(22.0, 45) == 0.0


def test_a_right_side_run_extends_up_station_for_its_own_lane():
    # 150 ft before 13+00, 37.5 ft past 14+00: 11+50 to 14+37.5, 287.5 ft
    # = 23 elements; 287.5 / 6.25 = 46 spaces, 47 posts. Posts stand at
    # 11+50 + 6.25 i: i = 24 to 40 (13+00 to 14+00) are in the guarded span,
    # 17 six-foot posts; the other 30 are 8 ft (no widening behind them)
    (run,) = gr.lay_out("R", [(1300.0, 1400.0)], 5.0, 17.0, 45, *ENDS)
    assert run == RailRun("R", 1150.0, 1437.5, TERMINAL, TERMINAL, ((1300.0, 1400.0),))
    assert (run.length, run.posts, run.terminals, run.agts) == (287.5, 47, 2, 0)
    assert (run.posts_6ft, run.posts_8ft) == (17, 30)


def test_a_left_side_run_extends_down_station_for_its_own_lane():
    # 37.5 ft before 13+00, 150 ft past 14+00: 12+62.5 to 15+50
    assert gr.lay_out("L", [(1300.0, 1400.0)], 5.0, 17.0, 45, *ENDS) == [
        RailRun("L", 1262.5, 1550.0, TERMINAL, TERMINAL, ((1300.0, 1400.0),))]


def test_at_50_mph_the_run_is_longer():
    # 175 ft before, 37.5 past: 11+25 to 14+37.5, 312.5 ft = 25 elements,
    # 312.5 / 6.25 = 50 spaces, 51 posts
    (run,) = gr.lay_out("R", [(1300.0, 1400.0)], 5.0, 17.0, 50, *ENDS)
    assert (run.start, run.end, run.posts) == (1125.0, 1437.5, 51)


def test_a_short_run_is_whole_elements_and_150_ft_at_least():
    # 8 ft shoulders: the face 8 ft from the ETW, 20 from the centreline.
    # Own lane (20 - 8) x 195 / 20 = 117, so 10 elements, 125 ft; opposing
    # 20 - 20 = 0. 13+00 to 13+10 becomes 11+75 to 13+10, 135 ft; whole
    # elements 137.5, at least 150: 15 ft more, 7.5 at each terminal:
    # 11+67.5 to 13+17.5
    (run,) = gr.lay_out("R", [(1300.0, 1310.0)], 8.0, 20.0, 45, *ENDS)
    assert (run.start, run.end, run.length) == (1167.5, 1317.5, 150.0)


def test_runs_closer_than_a_terminal_join():
    # 11+50 to 14+37.5 and 14+50 to 16+87.5 are 12.5 ft apart, under a
    # 50 ft terminal: one run, 11+50 to 16+87.5, 537.5 ft = 43 elements
    assert gr.lay_out("R", [(1300.0, 1400.0), (1600.0, 1650.0)], 5.0, 17.0, 45,
                      *ENDS) == [RailRun("R", 1150.0, 1687.5, TERMINAL, TERMINAL,
                                         ((1300.0, 1400.0), (1600.0, 1650.0)))]
    # 15+50 is 112.5 ft past 14+37.5: two runs, the second 15+50 to
    # 17+87.5, 237.5 ft = 19 elements
    assert gr.lay_out("R", [(1300.0, 1400.0), (1700.0, 1750.0)], 5.0, 17.0, 45,
                      *ENDS) == [
        RailRun("R", 1150.0, 1437.5, TERMINAL, TERMINAL, ((1300.0, 1400.0),)),
        RailRun("R", 1550.0, 1787.5, TERMINAL, TERMINAL, ((1700.0, 1750.0),))]


def test_a_run_into_a_structure_gap_ends_on_an_agt():
    # the bridge starts at 14+50: 14+30 + 37.5 = 14+67.5 is cut back to it,
    # an AGT. 13+05 - 150 = 11+55 to 14+50 is 295 ft; 300 in whole
    # elements, the 5 ft at the one terminal: 11+50
    (run,) = gr.lay_out("R", [(1305.0, 1430.0)], 5.0, 17.0, 45,
                        (1000.0, TERMINAL), (1450.0, AGT))
    assert run == RailRun("R", 1150.0, 1450.0, TERMINAL, AGT, ((1305.0, 1430.0),))
    assert (run.terminals, run.agts) == (1, 1)


def test_a_run_ties_into_a_wall():
    # a left rail's own lane runs down-station: 14+00 + 150 = 15+50, past
    # the wall at 15+00, so it ties in there: 12+62.5 to 15+00, 237.5 ft
    # = 19 elements
    assert gr.lay_out("L", [(1300.0, 1400.0)], 5.0, 17.0, 45, *ENDS,
                      walls=[(1500.0, 1600.0)]) == [
        RailRun("L", 1262.5, 1500.0, TERMINAL, WALL, ((1300.0, 1400.0),))]


def test_runs_do_not_join_across_a_wall():
    # the first 11+50 to 14+37.5 stops short of the wall at 14+50; the
    # second, 15+20 - 150 = 13+70, is cut back to the wall's end 15+00 and
    # runs to 16+00 + 37.5 = 16+37.5: 137.5 ft, made 150 at its terminal:
    # 15+00 to 16+50
    assert gr.lay_out("R", [(1300.0, 1400.0), (1520.0, 1600.0)], 5.0, 17.0, 45,
                      *ENDS, walls=[(1450.0, 1500.0)]) == [
        RailRun("R", 1150.0, 1437.5, TERMINAL, TERMINAL, ((1300.0, 1400.0),)),
        RailRun("R", 1500.0, 1650.0, WALL, TERMINAL, ((1520.0, 1600.0),))]


def test_a_run_at_the_alignment_s_start_stops_there():
    # 37.5 ft before 10+00 is off the alignment: the run starts at 10+00,
    # with its terminal there; to 11+25 + 150 = 12+75: 275 ft = 22 elements,
    # whole already. Posts at 10+00 + 6.25 i, i = 0 to 44: i = 0 to 20 (to
    # 11+25) are guarded, 21 six-foot posts; 24 eight-foot posts on to 12+75
    (run,) = gr.lay_out("L", [(1000.0, 1125.0)], 5.0, 17.0, 45, *ENDS)
    assert run == RailRun("L", 1000.0, 1275.0, TERMINAL, TERMINAL, ((1000.0, 1125.0),))
    assert (run.posts, run.posts_6ft, run.posts_8ft) == (45, 21, 24)


def test_a_run_from_the_alignment_s_start_takes_its_extra_at_the_other_end():
    # 10+00 to 10+10 guarded on the left: 37.5 ft before is off the
    # alignment, so it starts at 10+00; 150 ft past, to 11+60: 160 ft; whole
    # elements 162.5, the 2.5 ft all at the free end: 11+62.5
    (run,) = gr.lay_out("L", [(1000.0, 1010.0)], 5.0, 17.0, 45, *ENDS)
    assert (run.start, run.end) == (1000.0, 1162.5)


def test_guarded_stations_make_spans():
    assert gr.spans([0.0, 25.0, 50.0, 75.0, 100.0],
                    [False, True, True, False, True]) == [(25.0, 50.0), (100.0, 100.0)]


def test_the_w_beam_band_and_the_table():
    # 3 1/4 in deep outward from the face, 12 1/4 in tall up to 31 in
    top, bottom = 31.0 / 12.0, (31.0 - 12.25) / 12.0
    assert [c for p in gr.band("L", 17.0) for c in p] == pytest.approx(
        [17.0, bottom, 17.0 + 3.25 / 12.0, bottom, 17.0 + 3.25 / 12.0, top,
         17.0, top])
    assert gr.band("R", -17.0)[1] == pytest.approx((-17.0 - 3.25 / 12.0, bottom))
    assert gr.to_csv([RailRun("L", 1000.0, 1275.0, TERMINAL, TERMINAL,
                              ((1000.0, 1125.0),))]) == (
        gr.HEADER + "\n" "L,1000.00,1275.00,275.00,TERMINAL,TERMINAL,45,21,24\n")
