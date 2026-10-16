"""author.alignment: parsing delegation, radial exactness, anchor POB, sections."""
from __future__ import annotations

import math

import pytest

from bimforge.author.alignment import (
    Alignment, Datum, Profile, WallSection, _resolve_pob, parse_batter,
    parse_bearing, parse_dms, poly_area)


def test_parse_dms_two_and_three_part():
    assert parse_dms("40-51-47") == pytest.approx(40.863055555, abs=1e-9)
    assert parse_dms("56-17-32.22") == pytest.approx(56.292283333, abs=1e-9)
    assert parse_dms("90") == 90.0


def test_parse_bearing_all_quadrants():
    assert parse_bearing("N 58-16-11 E") == pytest.approx(58.269722222, abs=1e-9)
    assert parse_bearing("S 82-50-40.44 E") == pytest.approx(180 - 82.844566666, abs=1e-8)
    assert parse_bearing("S 30-0-0 W") == pytest.approx(210.0)
    assert parse_bearing("N 30-0-0 W") == pytest.approx(330.0)


def test_parse_batter():
    assert parse_batter("0.5:12") == pytest.approx(0.5 / 12)
    assert parse_batter("NONE") == 0.0


NORTH_TANGENT = {"kind": "tangent", "bearing": "N 0-0-0 E", "length": 100.0}
POB = {"station": 0.0, "northing": 0.0, "easting": 0.0}


def test_station_offset_on_tangent():
    al = Alignment(POB, [NORTH_TANGENT])
    n, e = al.station_offset(50.0, 10.0, "Rt")
    assert (n, e) == (pytest.approx(50.0), pytest.approx(10.0))
    n, e = al.station_offset(50.0, 10.0, "Lt")
    assert (n, e) == (pytest.approx(50.0), pytest.approx(-10.0))
    with pytest.raises(ValueError):
        al.station_offset(50.0, 10.0, "up")


def test_station_offset_is_radial_on_a_curve():
    # 100 ft tangent north, then a 90-degree right curve of radius 200.
    run = [NORTH_TANGENT,
           {"kind": "curve", "delta": "90-0-0", "turn": "R",
            "radius": 200.0, "length": math.pi * 200.0 / 2.0}]
    al = Alignment(POB, run)
    curve = al.segments[1]
    centre = (curve["cn"], curve["ce"])
    assert centre == (pytest.approx(100.0), pytest.approx(200.0))
    # a right offset on a right-hand curve moves TOWARD the centre: exactly R-o
    s_mid = 100.0 + curve["length"] / 2.0
    n, e = al.station_offset(s_mid, 25.0, "Rt")
    assert math.hypot(n - centre[0], e - centre[1]) == pytest.approx(175.0, abs=1e-9)
    # end point: quarter circle from BC (100,0) about (100,200) exits heading
    # east with the radial pointing due north, so EC = centre + R north.
    assert al.end_point == (pytest.approx(centre[0] + 200.0),
                            pytest.approx(centre[1], abs=1e-9))
    n_end, e_end, az_end = al.point_az(al.s_end)
    assert az_end == pytest.approx(90.0)
    assert (n_end, e_end) == (pytest.approx(al.end_point[0]), pytest.approx(al.end_point[1]))


def test_point_az_extends_past_the_ends():
    al = Alignment(POB, [NORTH_TANGENT])
    n, e, az = al.point_az(-25.0)
    assert (n, e, az) == (pytest.approx(-25.0), pytest.approx(0.0), pytest.approx(0.0))
    n, e, az = al.point_az(150.0)
    assert n == pytest.approx(150.0)


def test_closure_precision():
    al = Alignment(POB, [NORTH_TANGENT])
    c = al.closure({"northing": 100.0, "easting": 0.02, "station": 100.0})
    assert c["dist"] == pytest.approx(0.02)
    assert c["precision"] == pytest.approx(100.0 / 0.02)


def test_densify_forward_spacing():
    al = Alignment(POB, [NORTH_TANGENT])
    pts = al.densify(0.0, 10.0, step=2.0)
    assert len(pts) == 6                     # ceil(10/2)=5 steps -> 6 points
    stations = [s for _, _, s in pts]
    assert stations[0] == pytest.approx(0.0)
    assert stations[-1] == pytest.approx(10.0)
    diffs = [b - a for a, b in zip(stations, stations[1:])]
    assert all(d == pytest.approx(2.0) for d in diffs)   # spacing == step here
    # points lie on the (north) tangent: n == station, e == 0
    for n, e, s in pts:
        assert n == pytest.approx(s)
        assert e == pytest.approx(0.0)


def test_densify_backward_runs_downstation():
    al = Alignment(POB, [NORTH_TANGENT])
    pts = al.densify(10.0, 0.0, step=2.0)
    stations = [s for _, _, s in pts]
    assert stations[0] == pytest.approx(10.0)
    assert stations[-1] == pytest.approx(0.0)
    assert all(b < a for a, b in zip(stations, stations[1:]))
    diffs = [a - b for a, b in zip(stations, stations[1:])]
    assert all(d == pytest.approx(2.0) for d in diffs)


def test_densify_tiny_and_zero_range():
    al = Alignment(POB, [NORTH_TANGENT])
    # tiny range: the max(2, ...) floor still yields 3 points spanning s0..s1
    pts = al.densify(50.0, 50.001, step=2.0)
    assert len(pts) == 3
    assert pts[0][2] == pytest.approx(50.0)
    assert pts[-1][2] == pytest.approx(50.001)
    # degenerate s0 == s1: 3 coincident points, no ZeroDivisionError
    pts = al.densify(50.0, 50.0, step=2.0)
    assert len(pts) == 3
    assert all(s == pytest.approx(50.0) for _, _, s in pts)


def test_offset_curve_matches_station_offset():
    run = [NORTH_TANGENT,
           {"kind": "curve", "delta": "90-0-0", "turn": "R",
            "radius": 200.0, "length": math.pi * 200.0 / 2.0}]
    al = Alignment(POB, run)
    curve = al.segments[1]
    centre = (curve["cn"], curve["ce"])
    pts = al.offset_curve(100.0, 100.0 + curve["length"], 25.0, "Rt", step=5.0)
    for n, e, s in pts:
        # right offset on a right-hand curve: exactly R - 25 from the centre
        assert math.hypot(n - centre[0], e - centre[1]) == pytest.approx(175.0, abs=1e-9)
        # round-trip: each point is exactly station_offset at its station
        nn, ee = al.station_offset(s, 25.0, "Rt")
        assert (nn, ee) == (pytest.approx(n), pytest.approx(e))
    stations = [s for _, _, s in pts]
    diffs = [b - a for a, b in zip(stations, stations[1:])]
    assert all(d <= 5.0 + 1e-9 for d in diffs)           # spacing <= step
    assert all(d == pytest.approx(diffs[0]) for d in diffs)


def test_datum_lazy_construction_and_friendly_error(monkeypatch):
    pyproj = pytest.importorskip("pyproj")

    def boom(*args, **kwargs):
        raise RuntimeError("grid not found (simulated)")

    monkeypatch.setattr(pyproj.Transformer, "from_crs", boom)
    d = Datum()                              # lazy: must NOT touch pyproj here
    with pytest.raises(RuntimeError) as ei:
        d.lonlat(2_000_000.0, 6_000_000.0)   # first USE builds -> friendly error
    msg = str(ei.value)
    assert "Datum transforms unavailable" in msg
    assert "grid not found (simulated)" in msg
    assert Datum.VERTCON in msg
    assert "Datum.verify()" in msg


def test_resolve_pob_anchor_form():
    pl = {"anchor": {"station": 100.0, "northing": 100.0, "easting": 0.0},
          "run_start_station": 0.0, "run": [NORTH_TANGENT]}
    pob = _resolve_pob(pl)
    assert pob["station"] == 0.0
    assert pob["northing"] == pytest.approx(0.0, abs=1e-9)
    assert pob["easting"] == pytest.approx(0.0, abs=1e-9)
    with pytest.raises(ValueError):
        _resolve_pob({"anchor": {}, "run_start_station": 0,
                      "run": [{"kind": "curve"}]})


def test_profile_curve_and_tangents():
    curves = [{"bvc_station": 0.0, "evc_station": 200.0, "bvc_elev": 100.0,
               "evc_elev": 101.0, "g_in_pct": 2.0, "g_out_pct": -1.0,
               "length_ft": 200.0}]
    p = Profile(curves)
    assert p.elev(0.0) == 100.0
    # crest: g flips 2% -> -1% over 200 ft; at x=100: 100 + 2 + 0.5*(-0.03/200)*1e4
    assert p.elev(100.0) == pytest.approx(100.0 + 2.0 - 0.75)
    assert p.elev(-50.0) == pytest.approx(99.0)           # back tangent
    assert p.elev(250.0) == pytest.approx(100.5)          # ahead tangent
    assert p.deck_elev(0.0, 10.0, -2.0) == pytest.approx(100.0 - 0.2)


# Neutral fixture in the wall_type_1_mod keyed-by-design-H table format
# (structure per the bridge-pilot section-table blocks; values are FIXTURE data).
TABLES = {
    "type_1_case_1": {
        "stem_top_thickness_ft": 1.0,
        "table": {
            6:  {"W_ft": 5.75, "C_ft": 1.75, "B_ft": 4.0, "F_ft": 1.3333,
                 "T_ft": 1.0, "batter": "0.5:12"},
            8:  {"W_ft": 6.00, "C_ft": 2.00, "B_ft": 4.0, "F_ft": 1.3333,
                 "T_ft": 1.0, "batter": "0.5:12"},
            10: {"W_ft": 6.75, "C_ft": 2.25, "B_ft": 4.5, "F_ft": 1.3333,
                 "T_ft": 1.0, "batter": "0.5:12"},
        },
    },
    "type_5_case_1": {
        "stem_top_thickness_ft": 0.9583, "footing_thickness_ft": 1.5,
        "table": {
            6: {"W_ft": 6.5, "batter": "0.25:12"},
            8: {"W_ft": 7.0, "batter": "0.25:12"},
        },
    },
}


def test_wallsection_lookup_rounds_up_with_6in_grace():
    assert WallSection(1, 8.0, TABLES).W == 6.00     # exact row
    assert WallSection(1, 8.4, TABLES).W == 6.00     # within the 6 in grace
    assert WallSection(1, 8.6, TABLES).W == 6.75     # next size up
    with pytest.raises(ValueError):
        WallSection(1, 11.0, TABLES)


def test_wallsection_type1_w_equals_c_plus_b_and_area():
    ws = WallSection(1, 8.0, TABLES)
    assert ws.W == pytest.approx(ws.C + ws.B)
    # stem trapezoid: H * (T + (T + b*H)) / 2
    b = 0.5 / 12
    want_stem = 8.0 * (1.0 + (1.0 + b * 8.0)) / 2.0
    assert poly_area(ws.stem_polygon()) == pytest.approx(want_stem)
    assert poly_area(ws.footing_polygon()) == pytest.approx(ws.W * ws.F)
    assert ws.area_sf() == pytest.approx(want_stem + ws.W * ws.F)


def test_wallsection_type5_derived_toe():
    ws = WallSection(5, 8.0, TABLES)
    assert ws.C == pytest.approx(WallSection.TYPE5_TOE_FT + (0.25 / 12) * 8.0)
    assert ws.B == pytest.approx(ws.W - ws.C)
    assert ws.front_face_x(0.0) == pytest.approx(-(0.25 / 12) * 8.0)
    assert ws.front_face_x(8.0) == 0.0


def test_poly_area_survives_large_world_coordinates():
    # Mirror of bim/tests/test_ifc_mesh.py::
    # test_mesh_volume_survives_large_world_coordinates: the shoelace on raw
    # State-Plane coordinates loses ~5 digits to cancellation. Fractional
    # offsets + rotation so integer coordinates don't accidentally cancel.
    base = [(0.0, 0.0), (12.5, 0.0), (12.5, 8.25), (0.0, 8.25)]
    local = poly_area(base)
    assert local == pytest.approx(12.5 * 8.25)
    dx, dy, rot = 6_592_000.12345, 1_943_000.54321, 0.3
    c, s = math.cos(rot), math.sin(rot)
    world = [(dx + x * c - y * s, dy + x * s + y * c) for x, y in base]
    assert abs(poly_area(world) - local) / local < 1e-9
    # Thin sliver: area tiny relative to the coordinate products — this is
    # where the unshifted shoelace measurably loses digits (the rectangle
    # above cancels benignly pre-fix — relerr exactly 0 there; the shifted
    # form measures ~1.4e-11). Measured at
    # these offsets: pre-fix relerr ~1.95e-3, post-fix ~3.4e-9 — TOL=1e-6
    # sits >=100x from both, so this assertion is a real regression trap.
    TOL = 1e-6
    sliver = [(0.0, 0.0), (100.0, 0.005), (100.0, -0.005)]
    local_s = poly_area(sliver)
    assert local_s == pytest.approx(0.5)
    world_s = [(dx + x * c - y * s, dy + x * s + y * c) for x, y in sliver]
    assert abs(poly_area(world_s) - local_s) / local_s < TOL


# --- Caltrans B3 retaining-wall tables -------------------------------------
def _b3_yaml(p):
    import yaml
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def _b3_heights_monotonic(table):
    heights = [float(k) for k in table]
    assert heights == sorted(heights)


def _b3_check_table(table):
    """Type 1 full-row schema: monotonic design H, all dimension keys present,
    and the tabulated footing width equals toe + heel (W == C + B)."""
    _b3_heights_monotonic(table)
    for h, row in table.items():
        assert {"W_ft", "C_ft", "B_ft", "F_ft", "T_ft", "batter"} <= set(row), h
        assert row["C_ft"] + row["B_ft"] == pytest.approx(row["W_ft"], abs=1e-3), h


def _b3_check_wcb(table):
    """Type 1A: W/C/B tabulated (T/F constant at the type level); W == C + B."""
    _b3_heights_monotonic(table)
    for h, row in table.items():
        assert {"W_ft", "C_ft", "B_ft"} <= set(row), h
        assert row["C_ft"] + row["B_ft"] == pytest.approx(row["W_ft"], abs=1e-3), h


def _b3_check_w_only(table):
    """Type 5 / 6A / 6B: only W tabulated; require positive, monotonic-H W."""
    _b3_heights_monotonic(table)
    for h, row in table.items():
        assert row.get("W_ft", 0) > 0, h


def _b3_check_catalog(tables):
    """Validate every section type present, each against its own schema."""
    _b3_check_table(tables["type_1_case_1"]["table"])
    if "type_1a_case_1" in tables:
        _b3_check_wcb(tables["type_1a_case_1"]["table"])
    for key in ("type_5_case_1", "type_6a_case_1", "type_6b_case_1"):
        if key in tables:
            _b3_check_w_only(tables[key]["table"])


def test_b3_example_fixture_schema():
    from pathlib import Path
    p = (Path(__file__).resolve().parents[1]
         / "examples" / "caltrans-b3-tables.example.yaml")
    _b3_check_catalog(_b3_yaml(p))


def test_b3_production_catalog_if_present():
    """Validate the real B3 catalog when it is available locally; the
    W == C + B check independently verifies the Type 1/1A transcription."""
    from bimforge.author.tests._tables import require_caltrans_table
    _b3_check_catalog(_b3_yaml(require_caltrans_table("caltrans-b3-tables.yaml")))


def _fixture_tables():
    from pathlib import Path
    return _b3_yaml(Path(__file__).resolve().parents[1]
                    / "examples" / "caltrans-b3-tables.example.yaml")


def test_wallsection_type1_reads_example_fixture():
    ws = WallSection(1, 8.0, _fixture_tables())
    assert ws.W == pytest.approx(ws.C + ws.B)
    assert ws.area_sf() > 0.0


def test_wallsection_type1a_vertical_constant_stem():
    """Type 1A: constant 1'-0" vertical stem (no batter); W == C + B, stem is a
    T x H rectangle and the footing is W x F."""
    ws = WallSection("1a", 12.0, _fixture_tables())
    assert ws.wall_type == "1a"
    assert ws.front == "vertical"
    assert ws.batter == 0.0
    assert ws.T == pytest.approx(1.0)
    assert ws.F == pytest.approx(1.1667)
    assert ws.W == pytest.approx(ws.C + ws.B, abs=1e-3)  # 4-decimal feet-inch
    assert ws.front_face_x(0.0) == 0.0
    assert poly_area(ws.stem_polygon()) == pytest.approx(1.0 * 12.0)
    assert poly_area(ws.footing_polygon()) == pytest.approx(ws.W * ws.F)


def test_wallsection_type6a_and_6b_short_vertical_stem():
    """Type 6A/6B: short vertical stem, only W tabulated; C is the constant 8"
    toe, B = W - C, stem a 7-5/8" x H rectangle, footing W x F."""
    tables = _fixture_tables()
    for wt in ("6a", "6b"):
        ws = WallSection(wt, 6.0, tables)
        assert ws.wall_type == wt
        assert ws.front == "vertical"
        assert ws.batter == 0.0
        assert ws.T == pytest.approx(0.6354)
        assert ws.F == pytest.approx(1.0)
        assert ws.C == pytest.approx(0.6667)
        assert ws.B == pytest.approx(ws.W - ws.C)
        assert poly_area(ws.stem_polygon()) == pytest.approx(0.6354 * 6.0)
        assert poly_area(ws.footing_polygon()) == pytest.approx(ws.W * ws.F)


def test_wallsection_type6_float_design_h_keys_round_up():
    """Design H keys are 8-in increments (floats); lookup rounds up within the
    6-in grace, and beyond the top tabulated size (6') it raises."""
    tables = _fixture_tables()
    assert WallSection("6a", 4.0, tables).W == pytest.approx(3.5)
    assert WallSection("6a", 5.0, tables).W == pytest.approx(4.5)  # rounds up
    with pytest.raises(ValueError):
        WallSection("6a", 7.0, tables)


def test_wallsection_unsupported_type_raises():
    with pytest.raises(ValueError):
        WallSection("9z", 6.0, _fixture_tables())


# ---------------------------------------------------------- sweep accessors
CURVE_RUN = [
    {"kind": "tangent", "bearing": "N 0-0-0 E", "length": 100.0},
    {"kind": "curve", "delta": "90-0-0", "radius": 200.0, "turn": "R",
     "length": math.pi * 200.0 / 2.0},
    {"kind": "tangent", "bearing": "N 90-0-0 E", "length": 50.0},
]


def test_curvature_signed_left_positive():
    al = Alignment(POB, CURVE_RUN)
    assert al.curvature(50.0) == 0.0
    assert al.curvature(110.0) == pytest.approx(-1.0 / 200.0)   # turn R
    left = Alignment(POB, [
        NORTH_TANGENT,
        {"kind": "curve", "delta": "45-0-0", "radius": 300.0, "turn": "L",
         "length": math.pi * 300.0 / 4.0}])
    assert left.curvature(120.0) == pytest.approx(+1.0 / 300.0)


def test_left_normal_is_lt_direction():
    al = Alignment(POB, CURVE_RUN)
    dn, de = al.left_normal(50.0)          # heading north -> left is west
    assert dn == pytest.approx(0.0, abs=1e-12)
    assert de == pytest.approx(-1.0)
    # consistency with station_offset: +x offset == Lt point
    n, e, _ = al.point_az(50.0)
    n2, e2 = al.station_offset(50.0, 7.0, "Lt")
    assert n2 == pytest.approx(n + 7.0 * dn)
    assert e2 == pytest.approx(e + 7.0 * de)


def test_seg_breaks_strictly_inside():
    al = Alignment(POB, CURVE_RUN)
    arc = math.pi * 200.0 / 2.0
    assert al.seg_breaks(0.0, 100.0 + arc + 50.0) == [
        pytest.approx(100.0), pytest.approx(100.0 + arc)]
    assert al.seg_breaks(0.0, 100.0) == []
    assert al.seg_breaks(20.0, 90.0) == []


def test_kink_check_flags_bearing_break_only():
    smooth = Alignment(POB, CURVE_RUN)
    assert smooth.kink_check(0.0, smooth.s_end) == []
    kinked = Alignment(POB, [
        NORTH_TANGENT,
        {"kind": "tangent", "bearing": "N 45-0-0 E", "length": 100.0}])
    msgs = kinked.kink_check(0.0, 200.0)
    assert len(msgs) == 1 and "kink" in msgs[0]
    # join outside the range is not this sweep's problem
    assert kinked.kink_check(0.0, 90.0) == []


VC = {"bvc_station": 100.0, "bvc_elev": 50.0, "g_in_pct": 2.0,
      "g_out_pct": -1.0, "length_ft": 200.0,
      "evc_station": 300.0, "evc_elev": 51.0}
# evc_elev = 50 + 0.02*200 + 0.5*((-0.01-0.02)/200)*200^2 = 51.0


def test_profile_grade_through_vc_and_tangents():
    p = Profile([VC])
    assert p.grade(50.0) == pytest.approx(0.02)      # tangent extension in
    assert p.grade(100.0) == pytest.approx(0.02)     # BVC
    assert p.grade(200.0) == pytest.approx(0.005)    # mid: g1 + (g2-g1)/2
    assert p.grade(300.0) == pytest.approx(-0.01)    # EVC
    assert p.grade(400.0) == pytest.approx(-0.01)    # tangent extension out
    # derivative check against elev(): central difference at an interior s
    h = 1e-4
    num = (p.elev(180.0 + h) - p.elev(180.0 - h)) / (2 * h)
    assert p.grade(180.0) == pytest.approx(num, abs=1e-8)


def test_profile_breaks_strictly_inside():
    p = Profile([VC])
    assert p.breaks(0.0, 400.0) == [pytest.approx(100.0), pytest.approx(300.0)]
    assert p.breaks(100.0, 300.0) == []
    assert p.breaks(150.0, 400.0) == [pytest.approx(300.0)]
    assert p.breaks(400.0, 150.0) == [pytest.approx(300.0)]   # reversed args


def test_sweep_accessors_reversed_ranges():
    al = Alignment(POB, CURVE_RUN)
    arc = math.pi * 200.0 / 2.0
    assert al.seg_breaks(100.0 + arc + 50.0, 0.0) == al.seg_breaks(
        0.0, 100.0 + arc + 50.0)
    kinked = Alignment(POB, [
        NORTH_TANGENT,
        {"kind": "tangent", "bearing": "N 45-0-0 E", "length": 100.0}])
    assert kinked.kink_check(200.0, 0.0) == kinked.kink_check(0.0, 200.0)


def test_kink_check_wraps_across_north():
    near_north = Alignment(POB, [
        {"kind": "tangent", "bearing": "N 1-0-0 W", "length": 100.0},
        {"kind": "tangent", "bearing": "N 1-0-0 E", "length": 100.0}])
    msgs = near_north.kink_check(0.0, 200.0)
    assert len(msgs) == 1 and "2.000000 deg" in msgs[0]     # not 358 deg


def test_curvature_extends_past_curve_ended_run():
    al = Alignment(POB, [
        NORTH_TANGENT,
        {"kind": "curve", "delta": "45-0-0", "radius": 300.0, "turn": "L",
         "length": math.pi * 300.0 / 4.0}])
    assert al.curvature(al.s_end + 25.0) == pytest.approx(+1.0 / 300.0)
    dn, de = al.left_normal(al.s_end + 25.0)
    assert math.hypot(dn, de) == pytest.approx(1.0)


def test_profile_breaks_two_curves_dedup_shared_station():
    a = dict(VC)
    b = {"bvc_station": 300.0, "bvc_elev": 51.0, "g_in_pct": -1.0,
         "g_out_pct": 2.0, "length_ft": 100.0,
         "evc_station": 400.0, "evc_elev": 50.5}
    p = Profile([a, b])
    assert p.breaks(0.0, 500.0) == [pytest.approx(100.0),
                                    pytest.approx(300.0),
                                    pytest.approx(400.0)]   # 300 once, not twice
