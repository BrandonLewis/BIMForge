"""road-corridor guardrail runs (V1.1): the length of need by hand.

The cases are a two-lane road with 12 ft lanes and 5 ft shoulders, the rail
face at the shoulder edge: 5 ft from the edge of traveled way (L2), 17 ft
from the centreline (the opposing lane's L). LH is 20 ft. A run's stations
are its rail's ends: a terminal's nose, 12.5 ft (the gating length) beyond
the length-of-need point; an AGT, a wall tie-in or an SFT-M anchor at the
point itself.
"""
import pytest

from bimforge.author.corridor import guardrail as gr
from bimforge.author.corridor.guardrail import AGT, SFT_M, TERMINAL, WALL, RailRun

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
    # LON points 150 ft before 13+00 and 37.5 ft past 14+00: 11+50 to
    # 14+37.5, 287.5 ft = 23 elements. The noses 12.5 ft beyond: 11+37.5 to
    # 14+50, 312.5 ft; 312.5 / 6.25 = 50 spaces, 51 posts, all 6 ft
    (run,) = gr.lay_out("R", [(1300.0, 1400.0)], 5.0, 17.0, 45, *ENDS)
    assert run == RailRun("R", 1137.5, 1450.0, TERMINAL, TERMINAL, ((1300.0, 1400.0),))
    assert (run.length, run.posts, run.terminals, run.agts, run.anchors) == (
        312.5, 51, 2, 0, 0)
    assert not run.below_minimum


def test_a_left_side_run_extends_down_station_for_its_own_lane():
    # 37.5 ft before 13+00, 150 ft past 14+00: 12+62.5 to 15+50; noses
    # 12+50 to 15+62.5
    assert gr.lay_out("L", [(1300.0, 1400.0)], 5.0, 17.0, 45, *ENDS) == [
        RailRun("L", 1250.0, 1562.5, TERMINAL, TERMINAL, ((1300.0, 1400.0),))]


def test_at_50_mph_the_run_is_longer():
    # 175 ft before, 37.5 past: 11+25 to 14+37.5; noses 11+12.5 to 14+50,
    # 337.5 ft, 337.5 / 6.25 = 54 spaces, 55 posts
    (run,) = gr.lay_out("R", [(1300.0, 1400.0)], 5.0, 17.0, 50, *ENDS)
    assert (run.start, run.end, run.posts) == (1112.5, 1450.0, 55)


def test_a_short_run_is_150_ft_of_need_and_beyond_lh_ends_on_an_anchor():
    # 8 ft shoulders: the face 8 ft from the ETW, 20 from the centreline.
    # Own lane (20 - 8) x 195 / 20 = 117, so 10 elements, 125 ft; opposing
    # 20 - 20 = 0: the trailing end is outside the opposing clear zone, an
    # SFT-M anchor. 13+00 to 13+10 becomes 11+75 to 13+10, 135 ft; whole
    # elements 137.5, at least 150: 15 ft more, 7.5 at each end: 11+67.5 to
    # 13+17.5. The terminal's nose 12.5 ft before: 11+55; no gating at the
    # anchor
    (run,) = gr.lay_out("R", [(1300.0, 1310.0)], 8.0, 20.0, 45, *ENDS)
    assert run == RailRun("R", 1155.0, 1317.5, TERMINAL, SFT_M, ((1300.0, 1310.0),))
    assert (run.terminals, run.anchors, run.below_minimum) == (1, 1, False)


def test_runs_200_ft_or_less_apart_join():
    # noses 11+37.5 to 14+50 and 14+37.5 to 17+00 overlap: one run, LON
    # points 11+50 to 16+87.5 (537.5 ft = 43 elements), noses 11+37.5 to 17+00
    assert gr.lay_out("R", [(1300.0, 1400.0), (1600.0, 1650.0)], 5.0, 17.0, 45,
                      *ENDS) == [RailRun("R", 1137.5, 1700.0, TERMINAL, TERMINAL,
                                         ((1300.0, 1400.0), (1600.0, 1650.0)))]
    # the second's nose at 15+37.5 is 87.5 ft past 14+50, under 200
    # (TSSM 3.6(11)): one run, 11+37.5 to 18+00
    assert gr.lay_out("R", [(1300.0, 1400.0), (1700.0, 1750.0)], 5.0, 17.0, 45,
                      *ENDS) == [RailRun("R", 1137.5, 1800.0, TERMINAL, TERMINAL,
                                         ((1300.0, 1400.0), (1700.0, 1750.0)))]
    # 18+12.5 - 150 = 16+62.5, its nose 16+50: exactly 200 ft past 14+50,
    # "200 ft or less", so they join: to 18+50 + 12.5 = 19+00 (LON points
    # 11+50 to 18+87.5, 737.5 ft = 59 elements)
    (run,) = gr.lay_out("R", [(1300.0, 1400.0), (1812.5, 1850.0)], 5.0, 17.0, 45,
                        *ENDS)
    assert (run.start, run.end) == (1137.5, 1900.0)


def test_runs_more_than_200_ft_apart_stay_two():
    # the second: 17+50 to 19+57.5, 207.5 ft; whole elements 212.5, 2.5 at
    # each end: 17+47.5 to 19+60; noses 17+35 to 19+72.5, 285 ft past 14+50
    assert gr.lay_out("R", [(1300.0, 1400.0), (1900.0, 1920.0)], 5.0, 17.0, 45,
                      *ENDS) == [
        RailRun("R", 1137.5, 1450.0, TERMINAL, TERMINAL, ((1300.0, 1400.0),)),
        RailRun("R", 1735.0, 1972.5, TERMINAL, TERMINAL, ((1900.0, 1920.0),))]


def test_a_run_into_a_structure_gap_ends_on_an_agt():
    # the bridge starts at 14+50: 14+30 + 37.5 = 14+67.5 is cut back to it,
    # an AGT. 13+05 - 150 = 11+55 to 14+50 is 295 ft; 300 in whole
    # elements, the 5 ft at the one terminal: 11+50, its nose 11+37.5
    (run,) = gr.lay_out("R", [(1305.0, 1430.0)], 5.0, 17.0, 45,
                        (1000.0, TERMINAL), (1450.0, AGT))
    assert run == RailRun("R", 1137.5, 1450.0, TERMINAL, AGT, ((1305.0, 1430.0),))
    assert (run.terminals, run.agts) == (1, 1)


def test_bridge_rail_runs_at_each_end_of_a_structure_gap():
    # A bridge ends at 10+00 and the next begins at 20+00. Each bridge rail
    # end is a hazard for the traffic heading toward it (LH the clear zone).
    # Right side: at 10+00 that is the down-station (opposing) lane, X 37.5;
    # 10+00 to 10+37.5 is made 150 ft at its free end, 11+50, nose 11+62.5.
    # At 20+00 the up-station (own) lane, X 150: 18+50, nose 18+37.5.
    agts = ((1000.0, AGT), (2000.0, AGT))
    assert gr.lay_out("R", [], 5.0, 17.0, 45, *agts, bridge_rail=True) == [
        RailRun("R", 1000.0, 1162.5, AGT, TERMINAL),
        RailRun("R", 1837.5, 2000.0, TERMINAL, AGT)]
    # Left side, the mirror: own lane at 10+00 (150 ft to 11+50, nose
    # 11+62.5); opposing at 20+00 (37.5 ft, made 150: 18+50, nose 18+37.5)
    assert gr.lay_out("L", [], 5.0, 17.0, 45, *agts, bridge_rail=True) == [
        RailRun("L", 1000.0, 1162.5, AGT, TERMINAL),
        RailRun("L", 1837.5, 2000.0, TERMINAL, AGT)]
    # a guarded span 14+25 to 14+50 on the right: LON points 12+75 to
    # 14+87.5 (212.5 ft, whole), nose 12+62.5, 100 ft past 11+62.5: it joins
    # the bridge rail, one run from the AGT, LON 10+00 to 14+87.5 (487.5 ft
    # = 39 elements), nose 15+00. The 20+00 end's nose 18+37.5 is 337.5 ft on
    (run, upper) = gr.lay_out("R", [(1425.0, 1450.0)], 5.0, 17.0, 45, *agts,
                              bridge_rail=True)
    assert run == RailRun("R", 1000.0, 1500.0, AGT, TERMINAL, ((1425.0, 1450.0),))
    assert upper == RailRun("R", 1837.5, 2000.0, TERMINAL, AGT)


def test_side_runs_splits_the_alignment_at_structure_gaps():
    # 10+00 to 30+00 with a bridge 15+00 to 16+00, right side, no guarded
    # fill: rail at the bridge's two ends only. Approaching 15+00 up-station
    # (own lane) 150 ft: 13+50, nose 13+37.5; leaving 16+00 (the opposing
    # lane approaches it) 37.5 ft, made 150: 17+50, nose 17+62.5
    assert gr.side_runs("R", [], 5.0, 17.0, 45, [(1000.0, 1500.0), (1600.0, 3000.0)],
                        1000.0, 3000.0) == [
        RailRun("R", 1337.5, 1500.0, TERMINAL, AGT),
        RailRun("R", 1600.0, 1762.5, AGT, TERMINAL)]


def test_a_run_ties_into_a_wall_with_an_agt():
    # a left rail's own lane runs down-station: 14+00 + 150 = 15+50, past
    # the wall at 15+00, so it ties in there (Type AGT, TSSM 3.6(10)(c)):
    # 12+62.5 to 15+00, 237.5 ft = 19 elements; the nose 12+50
    (run,) = gr.lay_out("L", [(1300.0, 1400.0)], 5.0, 17.0, 45, *ENDS,
                        walls=[(1500.0, 1600.0)])
    assert run == RailRun("L", 1250.0, 1500.0, TERMINAL, WALL, ((1300.0, 1400.0),))
    assert (run.terminals, run.agts) == (1, 1)


def test_runs_do_not_join_across_a_wall():
    # the first's LON point 14+37.5 stops short of the wall at 14+50, but
    # its nose would be at 14+50: it ties in there. The second, 15+20 - 150
    # = 13+70, is cut back to the wall's end 15+00 and runs to 16+37.5:
    # 137.5 ft, made 150 at its terminal, 16+50, nose 16+62.5
    assert gr.lay_out("R", [(1300.0, 1400.0), (1520.0, 1600.0)], 5.0, 17.0, 45,
                      *ENDS, walls=[(1450.0, 1500.0)]) == [
        RailRun("R", 1137.5, 1450.0, TERMINAL, WALL, ((1300.0, 1400.0),)),
        RailRun("R", 1500.0, 1662.5, WALL, TERMINAL, ((1520.0, 1600.0),))]


def test_a_short_wall_between_close_runs_keeps_them_apart():
    # without the wall these join (above). The wall 14+40 to 14+45 holds
    # the first to 14+40 and starts the second at 14+45 (its LON point
    # 14+50, its nose 14+37.5, cut back to the wall): two runs
    assert gr.lay_out("R", [(1300.0, 1400.0), (1600.0, 1650.0)], 5.0, 17.0, 45,
                      *ENDS, walls=[(1440.0, 1445.0)]) == [
        RailRun("R", 1137.5, 1440.0, TERMINAL, WALL, ((1300.0, 1400.0),)),
        RailRun("R", 1445.0, 1700.0, WALL, TERMINAL, ((1600.0, 1650.0),))]


def test_a_wall_over_a_guarded_span_is_refused():
    with pytest.raises(ValueError, match=r"13\+50.00 to 13\+60.00.*13\+00.00 to 14\+00.00"):
        gr.lay_out("R", [(1300.0, 1400.0)], 5.0, 17.0, 45, *ENDS,
                   walls=[(1350.0, 1360.0)])


def test_a_run_held_at_both_ends_short_of_150_ft_is_flagged():
    # between a bridge ending at 13+80 and one beginning at 14+50: 70 ft
    (run,) = gr.lay_out("R", [(1400.0, 1420.0)], 5.0, 17.0, 45,
                        (1380.0, AGT), (1450.0, AGT))
    assert (run.start, run.end, run.start_end, run.end_end) == (1380.0, 1450.0, AGT, AGT)
    assert run.below_minimum


def test_a_run_at_the_alignment_s_start_stops_there():
    # 37.5 ft before 10+00 is off the alignment: the run starts at 10+00,
    # with its terminal there; to 11+25 + 150 = 12+75: 275 ft = 22 elements,
    # whole already; the far nose 12+87.5. 287.5 / 6.25 = 46 spaces, 47 posts
    (run,) = gr.lay_out("L", [(1000.0, 1125.0)], 5.0, 17.0, 45, *ENDS)
    assert run == RailRun("L", 1000.0, 1287.5, TERMINAL, TERMINAL, ((1000.0, 1125.0),))
    assert run.posts == 47


def test_a_run_from_the_alignment_s_start_takes_its_extra_at_the_other_end():
    # 10+00 to 10+10 guarded on the left: 37.5 ft before is off the
    # alignment, so it starts at 10+00; 150 ft past, to 11+60: 160 ft; whole
    # elements 162.5, the 2.5 ft all at the free end: 11+62.5, nose 11+75
    (run,) = gr.lay_out("L", [(1000.0, 1010.0)], 5.0, 17.0, 45, *ENDS)
    assert (run.start, run.end) == (1000.0, 1175.0)


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
    # 70 ft: 11 spaces, 12 posts
    assert gr.to_csv([RailRun("L", 1000.0, 1287.5, TERMINAL, TERMINAL,
                              ((1000.0, 1125.0),)),
                      RailRun("R", 1380.0, 1450.0, AGT, AGT, (), True)]) == (
        gr.HEADER + "\n"
        "L,1000.00,1287.50,287.50,TERMINAL,TERMINAL,47,no\n"
        "R,1380.00,1450.00,70.00,AGT,AGT,12,yes\n")
