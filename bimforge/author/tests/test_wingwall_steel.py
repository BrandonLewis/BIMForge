import pytest
from bimforge.author.wingwall_steel import WingwallSteel

TABLE = {
    "type_e": {
        "8":  {"k_bar": "#5@8", "L_bar": "#5", "L_each_wall": 2},
        "10": {"k_bar": "#5@7", "L_bar": "#6", "L_each_wall": 3},
    },
    "warped": {
        "wall": {
            "8": {"D_cutoff_in": 6.5, "D_culvert_in": 6.5,
                  "slopes": {"0.5:1": {"front": "#4@12", "rear": "#4@12"},
                             "1.5:1": {"front": "#4@12", "rear": "#4@8"}}},
        },
        "beam": {"by_l": {
            "12": [{"h_max": 20, "kind": "none", "face_bars": "2-#6", "total": "6-#6"}],
            "16": [{"h_max": 12, "A_ft": 1.0, "B_ft": 0.75, "total": "6-#7"},
                   {"h_max": 20, "A_ft": 1.0, "B_ft": 0.75, "total": "6-#7"}],
        }},
    },
}


def test_type_e_lookup_rounds_up():
    s = WingwallSteel(TABLE)
    row = s.type_e(7.0)                       # 7 -> next tabulated 8
    assert row["k_bar"] == "#5@8"
    assert row["L_each_wall"] == 2


def test_warped_wall_lookup_by_h_and_slope():
    s = WingwallSteel(TABLE)
    row = s.warped_wall(8.0, "1.5:1")
    assert row["front"] == "#4@12"
    assert row["rear"] == "#4@8"


def test_beam_region_lookup_by_l_and_h():
    s = WingwallSteel(TABLE)
    assert s.beam_region(l_ft=12.0, h_ft=8.0)["total"] == "6-#6"      # no-beam region
    assert s.beam_region(l_ft=16.0, h_ft=10.0)["total"] == "6-#7"     # h<=12 breakpoint


def test_parse_bar_total():
    from bimforge.author.wingwall_steel import parse_bar_total
    assert parse_bar_total("6-#7") == (6, 7)
    assert parse_bar_total("2-#6") == (2, 6)
    with pytest.raises(ValueError):
        parse_bar_total("garbage")


def test_parse_bar_size():
    from bimforge.author.wingwall_steel import parse_bar_size
    assert parse_bar_size("#6") == 6
    with pytest.raises(ValueError):
        parse_bar_size("#6@12")


def test_wingwall_production_catalog_if_present():
    import yaml
    from bimforge.author.box_section import parse_bar_spec
    from bimforge.author.tests._tables import require_caltrans_table
    from bimforge.author.wingwall_steel import (
        WingwallSteel, parse_bar_size, parse_bar_total)
    cat = require_caltrans_table("caltrans-d84-wingwall.yaml")
    t = yaml.safe_load(cat.read_text())
    steel = t["steel"]
    for h, row in steel["type_e"].items():
        parse_bar_spec(row["k_bar"]); parse_bar_size(row["L_bar"])
        assert int(row["L_each_wall"]) >= 1, h
    for h, row in steel["warped"]["wall"].items():
        for sl in row["slopes"].values():
            parse_bar_spec(sl["front"]); parse_bar_spec(sl["rear"])
    for l, col in steel["warped"]["beam"]["by_l"].items():
        for reg in col:
            parse_bar_total(reg["total"])
    # exercise real lookups so a structurally-valid but mislinked catalog fails
    ww = WingwallSteel(steel)
    assert ww.type_e(8.0)["k_bar"]
    assert ww.warped_wall(8.0, "0.5:1")["front"]
    assert ww.beam_region(16.0, 8.0)["total"]
