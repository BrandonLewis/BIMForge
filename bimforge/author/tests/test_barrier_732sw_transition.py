import pytest

from bimforge.author.barrier_732sw_transition import (
    HSS, hss_weight_lb, transition_elements)
from bimforge.author.primitives import STEEL_LB_PER_IN3


def test_hss_weight_matches_sharp_rect_hollow_hand_value():
    # HSS2.5x1.5x3/16 over 6': (outer - inner) rect area x length x steel.
    h, w, t = HSS["2.5x1.5x3/16"]
    area = h * w - (h - 2 * t) * (w - 2 * t)          # in^2
    expect = area * (6.0 * 12.0) * STEEL_LB_PER_IN3   # lb
    assert hss_weight_lb("2.5x1.5x3/16", 6.0) == pytest.approx(expect)
    # independent literal pin (catches a wrong catalog dim or steel constant):
    assert hss_weight_lb("2.5x1.5x3/16", 6.0) == pytest.approx(27.76, abs=0.05)


def test_approach_transition_has_two_hss_and_six_bolts():
    els = transition_elements("NB", approach=True, length_ft=6.0)
    hss = [e for e in els if "transition HSS" in e.name]
    bolts = [e for e in els if "transition HS bolts" in e.name]
    assert len(hss) == 2                                  # 2.5x1.5 + 2.5x1
    total_bolts = sum(e.quantities["count"] for e in bolts)
    assert total_bolts == 6                               # 7/8"x4 + 5/8"x2
    for e in hss + bolts:
        assert e.quantities["weight_lb"] > 0.0


def test_departure_transition_has_one_hss_and_one_bolt():
    els = transition_elements("NB", approach=False, length_ft=6.0)
    hss = [e for e in els if "transition HSS" in e.name]
    bolts = [e for e in els if "transition HS bolts" in e.name]
    assert len(hss) == 1
    assert sum(e.quantities["count"] for e in bolts) == 1     # 1" Detail C


def test_hss_elements_carry_length_for_lf_and_metl_layer():
    els = transition_elements("NB", approach=True, length_ft=6.0)
    hss = [e for e in els if "transition HSS" in e.name]
    assert all(e.quantities["length_ft"] == pytest.approx(6.0) for e in hss)
    assert all(e.layer == "S-METL" for e in hss)
