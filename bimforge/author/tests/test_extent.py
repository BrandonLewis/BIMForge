"""author/extent: the true plan extent of each body kind."""
import math

import pytest

from bimforge.author.extent import plan_extent


def test_prism_and_fill_read_the_base():
    d = {"kind": "prism", "base": [(1, 2), (5, 2), (5, 9)], "z_bot": 0}
    assert plan_extent(d) == (1, 2, 5, 9)
    assert plan_extent({**d, "kind": "fill"}) == (1, 2, 5, 9)


def test_mesh_reads_its_verts():
    d = {"kind": "mesh", "verts": [(0, 3, 1), (4, -2, 1), (2, 2, 9)],
         "tris": []}
    assert plan_extent(d) == (0, -2, 4, 3)


def test_tube_runs_along_its_axis_with_its_outer_radius():
    t = {"kind": "tube", "x0": 2.0, "y0": 5.0, "length": 100.0,
         "r_outer": 1.5, "wall": 0.1, "cz": 0.0}
    assert plan_extent({**t, "axis": "x"}) == (2.0, 3.5, 102.0, 6.5)
    assert plan_extent({**t, "axis": "y"}) == (0.5, 5.0, 3.5, 105.0)
    assert plan_extent({**t, "axis": "z"}) == (0.5, 3.5, 3.5, 6.5)


def test_rod_is_half_length_about_each_centre_on_its_axis():
    r = {"kind": "rod", "radius": 0.5, "length": 10.0,
         "centres": [(0, 0, 0), (20, 4, 0)]}
    assert plan_extent({**r, "axis": "x"}) == (-5.0, -0.5, 25.0, 4.5)
    assert plan_extent({**r, "axis": "y"}) == (-0.5, -5.0, 20.5, 9.0)
    assert plan_extent({**r, "axis": "z"}) == (-0.5, -0.5, 20.5, 4.5)


def test_box_ribbon_and_swept_disk():
    assert plan_extent({"kind": "box", "boxes": [(10, 0, 0, 4, 2, 1)]}) == (
        8, -1, 12, 1)
    rb = plan_extent({"kind": "ribbon", "width": 8.0,
                      "points": [(0, 0, 0), (50, 0, 0)]})
    assert rb == pytest.approx((0, -4, 50, 4))
    sd = plan_extent({"kind": "swept_disk", "radius": 0.25,
                      "verts": [(0, 0, 0), (6, 3, 0)], "segments": []})
    assert sd == (-0.25, -0.25, 6.25, 3.25)


def test_arc_band_and_gusset():
    ab = plan_extent({"kind": "arc_band", "cx": 10.0, "width": 4.0,
                      "r_inner": 2.0, "r_outer": 3.0, "wrap_deg": 180.0,
                      "start_deg": 180.0, "segments": 2})
    assert ab[:1] + ab[2:3] == (8.0, 12.0)
    assert ab[1] == pytest.approx(-3.0) and ab[3] == pytest.approx(
        3.0 * math.cos(math.pi * 2))
    g = plan_extent({"kind": "gusset", "thickness": 1.0,
                     "placements": [(4.0, [(-1, 0), (2, 0), (2, 3)]),
                                    (9.0, [(-1, 0), (2, 0), (2, 3)])]})
    assert g == (3.5, -1, 9.5, 2)


def test_no_geometry_is_none():
    assert plan_extent({"kind": "box", "boxes": []}) is None
