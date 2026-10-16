import pytest
from bimforge.author.headwall_section import HeadwallSection, _parse_h_key

TABLE = {"headwall": {
    "3-11": {"T_ft": 0.8333, "W_ft": 4.8333, "C_ft": 1.0, "B_ft": 3.8333,
             "F_ft": 1.0, "c": "#4@12", "d": "#5@12",
             "conc_cy_lf": 0.33, "reinf_lb_lf": 32},
    "4-8":  {"T_ft": 0.8333, "W_ft": 5.3333, "C_ft": 1.3333, "B_ft": 4.0,
             "F_ft": 1.0, "c": "#4@12", "d": "#5@8",
             "conc_cy_lf": 0.37, "reinf_lb_lf": 37}}}


def test_parse_h_key():
    assert _parse_h_key("4-8") == pytest.approx(4.6667, abs=1e-3)
    assert _parse_h_key("5") == 5.0


def test_lookup_rounds_up_design_h():
    s = HeadwallSection(4.3, TABLE)          # 4.3 -> next tabulated 4-8
    assert s.H_key == "4-8"
    assert s.T == pytest.approx(0.8333)
    assert s.W == pytest.approx(s.C + s.B)   # W == C + B
    assert s.reinf_lb_lf == 37


def test_exact_low_row():
    s = HeadwallSection(3.9, TABLE)          # <= 3.917 -> "3-11"
    assert s.H_key == "3-11"
    assert s.conc_cy_lf == 0.33


def test_over_range_raises():
    with pytest.raises(ValueError):
        HeadwallSection(99.0, TABLE)


def test_section_area_matches_tabulated_concrete():
    # T*(H+1) + W*F ~= conc_cy_lf * 27 (concrete incl. the 1'-0" stem extension)
    for h in (3.9, 4.3):
        s = HeadwallSection(h, TABLE)
        assert s.stem_height == pytest.approx(s.H + 1.0)
        assert s.section_area_sf == pytest.approx(s.conc_cy_lf * 27.0, abs=0.15)


def test_headwall_production_catalog_if_present():
    """Validate the real D89 catalog when available locally:
    W == C + B and section area T*(H+1)+W*F ~= conc_cy_lf*27 on every row."""
    import yaml
    from bimforge.author.box_section import parse_bar_spec
    from bimforge.author.tests._tables import require_caltrans_table
    cat = require_caltrans_table("caltrans-d89-pipe-headwall.yaml")
    t = yaml.safe_load(cat.read_text(encoding="utf-8"))
    for key, row in t["headwall"].items():
        assert row["W_ft"] == pytest.approx(row["C_ft"] + row["B_ft"], abs=0.02), key
        for m in ("c", "d"):
            parse_bar_spec(row[m])
        s = HeadwallSection(_parse_h_key(key), t)
        assert s.section_area_sf == pytest.approx(row["conc_cy_lf"] * 27.0,
                                                  abs=0.2), key
