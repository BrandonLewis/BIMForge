import math
import pytest
from bimforge.author.footing_run import FootingRun, step_rise_ft
from bimforge.author.primitives import poly_area


def test_straight_footing_volume_is_L_W_F():
    fr = FootingRun("f", lol=[(0.0, 0.0), (10.0, 0.0)], toe=1.5, heel=3.5,
                    side=1.0, top_el=0.0, thickness=1.0)
    assert fr.volume_cf == pytest.approx(10.0 * 5.0 * 1.0, rel=1e-9)
    ys = [p[1] for p in fr.base]
    # side=+1 is right-of-travel (per outward_normals docstring); travelling
    # +x, right-of-travel is -y. toe sits on +side (per this module's
    # docstring: "toe on the +side normal"), so toe (1.5) lands at -y and
    # heel (3.5) at +y for this LOL/side combination.
    assert max(ys) == pytest.approx(3.5) and min(ys) == pytest.approx(-1.5)


def test_L_corner_footing_is_continuous_mitred():
    lol = [(0.0, 0.0), (10.0, 0.0), (10.0, 8.0)]
    fr = FootingRun("f", lol=lol, toe=1.5, heel=3.5, side=1.0,
                    top_el=0.0, thickness=1.0)
    W = 5.0
    naive = (10.0 * W) + (8.0 * W)
    assert fr.plan_area_sf < naive - 1e-6
    assert fr.volume_cf == pytest.approx(fr.plan_area_sf, rel=1e-9)


def test_step_rise_rule():
    assert step_rise_ft(4) == 1.0 and step_rise_ft(22) == 1.0
    assert step_rise_ft(24) == 1.5 and step_rise_ft(36) == 1.5


def test_swept_footing_bottom_follows_top_profile():
    # top-of-footing slopes 6 -> 2 over 8 ft (a wingwall daylighting); constant
    # thickness F=1 -> bottom is top-1 at every station, a sloped slab.
    fr = FootingRun("f", lol=[(0.0, 0.0), (8.0, 0.0)], toe=1.0, heel=2.0,
                    side=1.0, thickness=1.0,
                    top_profile=[(0.0, 6.0), (8.0, 2.0)], key_index=0)
    tops = [s[2][2] for s in fr._sections]     # heel-top z at each vertex
    assert tops[0] == pytest.approx(6.0) and tops[1] == pytest.approx(2.0)
    bots = [s[0][2] for s in fr._sections]     # toe-bottom z
    assert bots[0] == pytest.approx(5.0) and bots[1] == pytest.approx(1.0)
    # constant-thickness sloped slab: volume == W*F*horizontal_len exactly
    assert fr.volume_cf == pytest.approx(3.0 * 1.0 * 8.0, rel=1e-9)


def _assert_stepped_shape(fr):
    # every adjacent section pair is EITHER a horizontal bay (plan point moves,
    # top z equal) OR a vertical riser (same plan point, top z differs) --
    # never a sloped ramp.
    for a, b in zip(fr._sections, fr._sections[1:]):
        ax, ay, az = a[3]                      # toe-top corner
        bx, by, bz = b[3]
        same_xy = abs(ax - bx) < 1e-9 and abs(ay - by) < 1e-9
        if same_xy:
            assert abs(bz - az) > 1e-9, "co-located sections must be a vertical riser"
        else:
            assert abs(bz - az) < 1e-9, f"bay from {(ax,ay,az)} to {(bx,by,bz)} is sloped, not level"


def test_stepped_footing_drops_by_step_rise():
    # ground slopes 6 -> 0 over 12 ft; design H=8 -> step rise 1.0 ft.
    fr = FootingRun("f", lol=[(0.0, 0.0), (12.0, 0.0)], toe=1.0, heel=1.0,
                    side=1.0, thickness=1.0,
                    top_profile=[(0.0, 6.0), (12.0, 0.0)], key_index=0,
                    bottom="stepped", design_h=8.0)
    tops = sorted({round(s[2][2], 6) for s in fr._sections})
    diffs = [round(b - a, 6) for a, b in zip(tops, tops[1:])]
    assert diffs and all(d == pytest.approx(1.0) for d in diffs)   # all drops == rise
    assert fr.volume_cf > 0
    assert min(tops) >= 0.0                                        # snapped to grid
    _assert_stepped_shape(fr)                                      # level runs + risers


def test_stepped_footing_uphill_also_level_runs():
    fr = FootingRun("f", lol=[(0.0, 0.0), (12.0, 0.0)], toe=1.0, heel=1.0,
                    side=1.0, thickness=1.0,
                    top_profile=[(0.0, 0.0), (12.0, 6.0)], key_index=0,
                    bottom="stepped", design_h=8.0)
    tops = sorted({round(s[2][2], 6) for s in fr._sections})
    diffs = [round(b - a, 6) for a, b in zip(tops, tops[1:])]
    assert diffs and all(d == pytest.approx(1.0) for d in diffs)
    assert fr.volume_cf > 0
    _assert_stepped_shape(fr)


def test_stepped_footing_interior_on_grid_breakpoint():
    # interior breakpoint (4,5.0) sits exactly on the grid -- the old
    # snap-by-knot code sloped the bays that touched it.
    fr = FootingRun("f", lol=[(0.0, 0.0), (12.0, 0.0)], toe=1.0, heel=1.0,
                    side=1.0, thickness=1.0,
                    top_profile=[(0.0, 7.0), (4.0, 5.0), (12.0, 0.0)],
                    key_index=0, bottom="stepped", design_h=8.0)
    assert fr.volume_cf > 0
    _assert_stepped_shape(fr)
