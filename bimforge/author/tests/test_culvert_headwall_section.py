import math
import pathlib

import pytest
import yaml
from bimforge.author.alignment import WallSection
from bimforge.author.barrier_section import BarrierSection
from bimforge.author.culvert_headwall_section import (
    elliptical_void, headwall_stem, headwall_footing)
from bimforge.author.families.pipe_headwall import circular_void
from bimforge.author.primitives import poly_area

B3 = {"type_1_case_1": {"table": {
    "6": {"W_ft": 5.0, "C_ft": 1.5, "B_ft": 3.5, "T_ft": 1.0, "F_ft": 1.0,
          "batter": "NONE"}}}}


def test_headwall_stem_volume_is_panel_minus_pipe():
    wall = WallSection("1", 6.0, B3)
    stem = headwall_stem("HW stem", wall, length=10.0,
                         pipe={"dia_ft": 3.0, "center_ft": 5.0})
    # Track what the code actually integrates: the faceted 32-gon void, not the
    # analytic pi r^2 (the primitive's own net section) times thickness T.
    face = [(0.0, 0.0), (10.0, 0.0), (10.0, 6.0), (0.0, 6.0)]
    void = circular_void(3.0, 5.0, 3.0 / 2.0 + 0.5)
    expected = (poly_area(face) - poly_area(void)) * 1.0   # * T
    assert stem.volume_cf == pytest.approx(expected, rel=1e-9)


def test_headwall_footing_is_clean_box():
    wall = WallSection("1", 6.0, B3)
    foot = headwall_footing("HW footing", wall, length=10.0)
    assert foot.volume_cf == pytest.approx(10.0 * 5.0 * 1.0)  # L*W*F
    # clean box: dims reproduce volume (gate invariant)
    assert foot.dims_ft == (10.0, 5.0)


def test_pipe_wider_than_wall_raises():
    wall = WallSection("1", 6.0, B3)
    with pytest.raises(ValueError, match="pipe"):
        headwall_stem("x", wall, length=10.0,
                      pipe={"dia_ft": 7.0, "center_ft": 5.0})  # > H


def test_pipe_pokes_through_panel_top_raises():
    wall = WallSection("1", 6.0, B3)
    # dia < H (5.8 < 6) but the placed void top = dia+0.5 = 6.3 > H
    with pytest.raises(ValueError, match="pipe"):
        headwall_stem("x", wall, length=10.0,
                      pipe={"dia_ft": 5.8, "center_ft": 5.0})


def test_pipe_pokes_through_panel_side_raises():
    wall = WallSection("1", 6.0, B3)
    # cu = 1.0 < r = 1.5, so the void pokes out the left edge
    with pytest.raises(ValueError, match="pipe"):
        headwall_stem("x", wall, length=10.0,
                      pipe={"dia_ft": 3.0, "center_ft": 1.0})


def test_elliptical_void_area_matches_skew():
    r = 1.5
    ring = elliptical_void(dia=3.0, skew_deg=30.0, cu=5.0, cz=2.0)
    a = r / math.cos(math.radians(30.0))
    assert abs(poly_area(ring)) == pytest.approx(math.pi * a * r, rel=0.01)


def test_elliptical_void_skew0_is_circle():
    # skew 0 reduces to the circular void (equal semi-axes)
    ring = elliptical_void(dia=3.0, skew_deg=0.0, cu=5.0, cz=2.0)
    xs = [p[0] for p in ring]; zs = [p[1] for p in ring]
    assert (max(xs) - min(xs)) == pytest.approx(max(zs) - min(zs), rel=1e-9)


def test_headwall_stem_skew_widens_opening_only():
    class W:
        H, T, W, C, B, F, batter = 6.0, 1.0, 5.0, 1.5, 3.5, 1.0, 0.0
    stem = headwall_stem("p", W(), length=12.0,
                         pipe={"dia_ft": 3.0, "center_ft": 6.0,
                               "center_z_ft": 2.0, "material": "rc"},
                         skew_deg=30.0)
    a = 1.5 / math.cos(math.radians(30.0))
    assert stem.volume_cf == pytest.approx((12.0 * 6.0 - math.pi * a * 1.5) * 1.0,
                                           rel=0.01)


def test_skewed_opening_containment_guard():
    class W:
        H, T, W, C, B, F, batter = 6.0, 1.0, 5.0, 1.5, 3.5, 1.0, 0.0
    with pytest.raises(ValueError, match="does not fit"):
        headwall_stem("p", W(), length=6.0,
                      pipe={"dia_ft": 3.0, "center_ft": 5.5, "center_z_ft": 2.0},
                      skew_deg=60.0)   # widened ellipse runs off the panel end


def test_near_90_skew_fails_loud():
    # r/cos(skew) diverges as skew -> 90 deg; both entry points must reject it
    # with a clear "too extreme" message rather than emit a runaway ellipse or
    # trip the containment guard with a misleading "does not fit".
    with pytest.raises(ValueError, match="too extreme"):
        elliptical_void(dia=3.0, skew_deg=89.0, cu=5.0, cz=2.0)

    class W:
        H, T, W, C, B, F, batter = 6.0, 1.0, 5.0, 1.5, 3.5, 1.0, 0.0
    with pytest.raises(ValueError, match="too extreme"):
        headwall_stem("p", W(), length=100.0,   # long panel: NOT a fit failure
                      pipe={"dia_ft": 3.0, "center_ft": 50.0, "center_z_ft": 2.0},
                      skew_deg=89.0)


def _type_836_section():
    # the table is repository data (see tests/_tables.py); skip, don't error,
    # when the catalog isn't available
    from bimforge.author.tests._tables import require_caltrans_table
    cat = yaml.safe_load(
        require_caltrans_table("caltrans-d90-headwall.yaml").read_text(encoding="utf-8"))
    tcb = cat["d90"]["type_c_barrier"]
    table = {"barriers": {tcb["barrier_type"]:
                          {"shape": tcb["shape"],
                           "variants": {str(tcb["h_ft"]): tcb}}}}
    return tcb, BarrierSection(tcb["barrier_type"], str(tcb["h_ft"]), table)


def test_type_836_profile_matches_sheet_440_dimensions():
    # Non-vacuous: assert the transcribed Type 836 outline against the
    # INDEPENDENT dimensions read off 2025 Standard Plan sheet 440 (B11-80) --
    # a typo in any profile vertex breaks one of these, and the area check
    # compares the shoelace to a band-integration value derived separately from
    # the profile (so it is not a trapezoid tautology).
    tcb, sec = _type_836_section()
    o = sec.outline
    xs = [x for x, _z in o]
    assert sec.top_z == pytest.approx(3.0, abs=1e-3)                 # 3'-0" tall
    base = [x for x, z in o if abs(z) < 1e-6]                        # at the deck
    assert min(base) == pytest.approx(0.0, abs=1e-3)                 # recessed backface
    assert max(base) == pytest.approx(17.0 / 12.0, abs=2e-3)        # 17" base at traffic
    assert min(xs) == pytest.approx(-4.0 / 12.0, abs=2e-3)          # thickened upper 4" proud
    top = [x for x, z in o if abs(z - 3.0) < 1e-6]                   # the flat top face
    # nominal top is 1'-2" (14") to the theoretical traffic corner; the 1"
    # chamfer there trims the flat top face to ~13".
    assert max(top) - min(top) == pytest.approx(13.0 / 12.0, abs=0.02)
    assert min(top) == pytest.approx(-2.75 / 12.0, abs=2e-3)         # top-back after 1-1/4" return
    # recess ledge at 1'-10" (22") -- the plumb-face x jumps between the two backfaces there
    assert any(abs(z - 22.0 / 12.0) < 1e-3 for _x, z in o)
    # shoelace area vs the independently documented band-integration CF/LF
    assert sec.area_sf == pytest.approx(tcb["concrete_cf_per_lf"], rel=0.01)
    assert sec.area_sf == pytest.approx(3.908, rel=0.01)
