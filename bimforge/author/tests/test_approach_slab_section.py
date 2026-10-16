import pytest
from bimforge.author.approach_slab_section import (
    ApproachSlabSection, length_from_type_key)

# Illustrative rows — real thickness/bars transcribed bid-side from B9-1..B9-5.
TABLE = {
    "type_n_30": {"length_ft": 30.0, "thickness_ft": 1.25, "design_span_ft": 24.5,
                  "bars": {"bottom_main": "#10@6", "bottom_transverse": "#6@12",
                           "top_mat": "#5@18", "edge_cont": {"size": 5, "count": 4}},
                  "dowels": {"seat": "#5@12", "seat_len_ft": 2.0,
                             "diaphragm": "#5@9", "diaphragm_len_ft": 2.667}},
    "type_eq_10": {"length_ft": 10.0, "thickness_ft": 1.0, "design_span_ft": 7.83,
                   "bars": {"bottom_main": "#7@6", "bottom_transverse": "#6@12",
                            "top_mat": "#5@18", "edge_cont": {"size": 5, "count": 2}},
                   "dowels": {"seat": "#5@12", "seat_len_ft": 2.0,
                              "diaphragm": "#5@9", "diaphragm_len_ft": 2.667}},
}


def test_length_from_type_key():
    assert length_from_type_key("type_n_30") == 30.0
    assert length_from_type_key("type_eq_10") == 10.0


def test_length_from_type_key_rejects_unkeyed():
    with pytest.raises(ValueError, match="must end in"):
        length_from_type_key("type_weird")


def test_section_loads_dims():
    sec = ApproachSlabSection("type_n_30", TABLE)
    assert sec.length_ft == 30.0
    assert sec.thickness_ft == 1.25
    assert sec.design_span_ft == 24.5
    assert sec.key_length_ft == 30.0


def test_section_unknown_type_raises():
    with pytest.raises(ValueError, match="no approach-slab table row"):
        ApproachSlabSection("type_missing", TABLE)


def test_section_empty_bars_raises():
    bad = {"type_n_30": {"length_ft": 30.0, "thickness_ft": 1.25, "bars": {}}}
    with pytest.raises(ValueError, match="bar schedule"):
        ApproachSlabSection("type_n_30", bad)


def test_section_nonpositive_thickness_raises():
    bad = {"type_n_30": {"length_ft": 30.0, "thickness_ft": 0.0,
                         "bars": {"top_mat": "#5@18"}}}
    with pytest.raises(ValueError, match="positive"):
        ApproachSlabSection("type_n_30", bad)


def test_missing_length_raises():
    bad = {"type_n_30": {"thickness_ft": 1.25, "bars": {"top_mat": "#5@18"}}}
    with pytest.raises(ValueError, match="required"):
        ApproachSlabSection("type_n_30", bad)


def test_key_length_independent_of_row_length():
    # key encodes 30, row says 25 — key_length_ft reflects the key, not the row
    tbl = {"type_n_30": {"length_ft": 25.0, "thickness_ft": 1.25,
                         "bars": {"top_mat": "#5@18"}}}
    sec = ApproachSlabSection("type_n_30", tbl)
    assert sec.length_ft == 25.0
    assert sec.key_length_ft == 30.0


def test_malformed_type_key_raises_at_construction():
    # A key with no _<int> suffix must fail loud at construction, NOT later
    # inside key_length_ft (which runs in a gate check that doesn't catch).
    bad = {"type_weird": {"length_ft": 30.0, "thickness_ft": 1.25,
                          "bars": {"top_mat": "#5@18"}}}
    with pytest.raises(ValueError, match="must end in"):
        ApproachSlabSection("type_weird", bad)
    # and once constructed, key_length_ft never raises
    good = ApproachSlabSection("type_n_30", {"type_n_30": bad["type_weird"]})
    assert good.key_length_ft == 30.0
