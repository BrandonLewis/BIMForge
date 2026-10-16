import pytest
from bimforge.author.barrier_section import (
    BarrierSection, safety_shape_profile, single_slope_profile,
    type_732sw_profile)

TABLE = {"barriers": {
    "type_60": {"shape": "single_slope", "variants": {
        "32": {"height_ft": 2.667, "base_width_ft": 2.0, "top_width_ft": 0.667,
               "concrete_cf_per_lf": (2.0 + 0.667) / 2.0 * 2.667,
               "bars": {"longitudinal": {"size": 4, "count": 6},
                        "ties": {"size": 4, "spacing_in": 12}}}}}}}


def test_single_slope_profile_is_symmetric_trapezoid():
    prof = single_slope_profile(height=2.667, base_width=2.0, top_width=0.667)
    assert prof == [(-1.0, 0.0), (1.0, 0.0), (0.3335, 2.667), (-0.3335, 2.667)]


def test_single_slope_section_area_matches_trapezoid():
    sec = BarrierSection("type_60", "32", TABLE)
    assert sec.area_sf == pytest.approx((2.0 + 0.667) / 2.0 * 2.667)
    assert sec.top_z == pytest.approx(2.667)
    import math
    slant = math.hypot((2.0 - 0.667) / 2.0, 2.667)
    assert sec.perimeter_ft == pytest.approx(2.0 + 0.667 + 2 * slant)


def test_section_area_equals_catalog_cf_per_lf():
    sec = BarrierSection("type_60", "32", TABLE)
    row = TABLE["barriers"]["type_60"]["variants"]["32"]
    assert sec.area_sf == pytest.approx(row["concrete_cf_per_lf"], rel=1e-9)


def test_explicit_profile_row_is_used_verbatim():
    table = {"barriers": {"type_x": {"shape": "single_slope", "variants": {
        "40": {"profile": [[-1.0, 0.0], [1.0, 0.0], [0.25, 3.0], [-0.25, 3.0]],
               "concrete_cf_per_lf": 1.875}}}}}
    sec = BarrierSection("type_x", "40", table)
    assert sec.outline == [(-1.0, 0.0), (1.0, 0.0), (0.25, 3.0), (-0.25, 3.0)]
    assert sec.top_z == pytest.approx(3.0)
    assert sec.describe().startswith("type_x (H=3.000 ft")


def test_unknown_type_raises():
    with pytest.raises(ValueError, match="unknown barrier type"):
        BarrierSection("type_99", "32", TABLE)


SAFETY_TABLE = {"barriers": {"type_736": {
    "shape": "safety_shape", "variants": {"32": {
        "height_ft": 2.667, "base_width_ft": 2.0, "top_width_ft": 0.5,
        "break_height_ft": 0.833, "break_width_ft": 1.271,
        # trapezoid(base->break) + trapezoid(break->top), doubled about centre
        "concrete_cf_per_lf": (
            (2.0 + 1.271) / 2.0 * 0.833
            + (1.271 + 0.5) / 2.0 * (2.667 - 0.833)),
        "bars": {"longitudinal": {"size": 4, "count": 8},
                 "ties": {"size": 4, "spacing_in": 12}}}}}}}


def test_safety_shape_is_compound_hexagon():
    prof = safety_shape_profile(height=2.667, base_width=2.0, top_width=0.5,
                                break_height=0.833, break_width=1.271)
    # 6 vertices: base-L, base-R, break-R, top-R, top-L, break-L
    assert len(prof) == 6
    assert prof == [(-1.0, 0.0), (1.0, 0.0), (0.6355, 0.833), (0.25, 2.667),
                    (-0.25, 2.667), (-0.6355, 0.833)]


def test_safety_shape_area_matches_two_trapezoids():
    sec = BarrierSection("type_736", "32", SAFETY_TABLE)
    row = SAFETY_TABLE["barriers"]["type_736"]["variants"]["32"]
    assert sec.area_sf == pytest.approx(row["concrete_cf_per_lf"], rel=1e-9)
    assert sec.top_z == pytest.approx(2.667)


# Type 732SW governing dims (feet), flat-slab base (deck_slope 0):
_SW_ROW = {
    "top_w_ft": 1.0, "top_h_ft": 14.0 / 12.0, "stem_w_ft": 10.0 / 12.0,
    "barrier_h_ft": 2.0 + 8.0 / 12.0, "sw_top_face_ft": 0.7624,
    "sw_thick_toe_ft": 8.0 / 12.0, "sw_width_ft": 6.0 + 2.0 / 12.0,
    "deck_slope_pct": 0.0,
}


def _hand_area_flat(r):
    # independent decomposition: thickened top + stem + sidewalk trapezoid
    top = r["top_w_ft"] * r["top_h_ft"]
    z_top = r["sw_top_face_ft"] + r["barrier_h_ft"]
    stem = r["stem_w_ft"] * (z_top - r["top_h_ft"])          # stem down to deck z=0
    sw = r["sw_width_ft"] * (r["sw_top_face_ft"] + r["sw_thick_toe_ft"]) / 2.0
    return top + stem + sw


def test_732sw_area_matches_independent_hand_calc_flat_slab():
    sec = BarrierSection("type_732sw", "std", {"barriers": {"type_732sw": {
        "shape": "type_732sw", "variants": {"std": _SW_ROW}}}})
    assert sec.area_sf == pytest.approx(_hand_area_flat(_SW_ROW), rel=1e-9)
    assert sec.area_sf == pytest.approx(7.4583, abs=1e-3)   # sanity anchor


def test_732sw_top_z_is_barrier_top():
    sec = BarrierSection("type_732sw", "std", {"barriers": {"type_732sw": {
        "shape": "type_732sw", "variants": {"std": _SW_ROW}}}})
    assert sec.top_z == pytest.approx(0.7624 + 2.0 + 8.0 / 12.0)   # 3.42907


def test_732sw_transverse_faces_and_rail_mount():
    prof = type_732sw_profile(_SW_ROW)
    xs = sorted({x for x, _z in prof})
    # four transverse stations: outside top-block face, 2" relief/stem face,
    # inboard plumb ped face, sidewalk toe.
    assert xs == pytest.approx([0.0, 1.0 / 6.0, 1.0, 1.0 + 6.0 + 2.0 / 12.0])
    rail_cl = min(xs) + 0.5                      # post CL = 6" inboard of outside face
    assert xs[1] < rail_cl < 1.0                 # CL sits on the 12" top block, past the relief


def test_732sw_deck_slope_adds_concrete():
    flat = BarrierSection("type_732sw", "std", {"barriers": {"type_732sw": {
        "shape": "type_732sw", "variants": {"std": _SW_ROW}}}}).area_sf
    sloped_row = dict(_SW_ROW, deck_slope_pct=2.0)
    sloped = BarrierSection("type_732sw", "std", {"barriers": {"type_732sw": {
        "shape": "type_732sw", "variants": {"std": sloped_row}}}}).area_sf
    stem_w = _SW_ROW["stem_w_ft"]                 # x_ped - x_stem_out = stem width
    wedge = 0.5 * stem_w * (0.02 * stem_w)        # triangular stem-base drop at 2%
    assert sloped > flat
    assert sloped == pytest.approx(flat + wedge, abs=1e-6)
