import pytest

from bimforge.author.barrier_842_transition import (
    HSS, HSS_LEN_FT, hss_weight_lb, transition_elements)


def test_hss_weight_is_hollow_section_times_490():
    # HSS2.5x1.5x3/16: area = 2.5*1.5 - (2.5-.375)*(1.5-.375) in^2
    w = hss_weight_lb("2.5x1.5x3/16", 10.0)
    area = 2.5 * 1.5 - (2.5 - 0.375) * (1.5 - 0.375)
    from bimforge.author.primitives import STEEL_LB_PER_IN3
    assert w == pytest.approx(area * 120.0 * STEEL_LB_PER_IN3, rel=1e-9)


def test_approach_has_two_hss_and_two_bolt_sizes():
    els = transition_elements("NB (approach)", approach=True, length_ft=6.0)
    hss = [e for e in els if "transition HSS" in e.name]
    bolts = [e for e in els if "transition HS bolts" in e.name]
    assert len(hss) == 2                         # 2.5x1.5 + 2.5x1
    assert {e.ifc_class for e in hss} == {"IfcMember"}
    assert sorted(b.quantities["count"] for b in bolts) == [2, 4]   # 5/8 x2, 7/8 x4
    assert all(b.ifc_class == "IfcMechanicalFastener" for b in bolts)


def test_departure_has_one_hss_and_one_bolt():
    els = transition_elements("NB (departure)", approach=False, length_ft=6.0)
    hss = [e for e in els if "transition HSS" in e.name]
    bolts = [e for e in els if "transition HS bolts" in e.name]
    assert len(hss) == 1
    assert len(bolts) == 1 and bolts[0].quantities["count"] == 1     # 1" x1


def test_names_are_disambiguated_per_end():
    ap = transition_elements("NB (approach)", approach=True)
    dp = transition_elements("NB (departure)", approach=False)
    assert not ({e.name for e in ap} & {e.name for e in dp})   # no collisions


def test_default_hss_length_is_the_block_length():
    # No length_ft -> HSS is billed at the 3'-6" end-block length (B11-82A);
    # the tubes are block-mounted hardware, not the 6'-8" transition span.
    assert HSS_LEN_FT == pytest.approx(3.5)
    for approach in (True, False):
        els = transition_elements("NB", approach=approach)
        hss = [e for e in els if "transition HSS" in e.name]
        assert hss
        assert all(e.quantities["length_ft"] == pytest.approx(3.5)
                   for e in hss)
