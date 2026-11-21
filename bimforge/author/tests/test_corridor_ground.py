"""road-corridor ground: a plane, and a 3DEP grid (P.6)."""
import uuid

import numpy as np
import pytest

from bimforge.author.alignment import Alignment
from bimforge.author.corridor.ground import (GridGround, PlaneGround, footprint,
                                             from_params)
from bimforge.author.project import ProjectContext
from bimforge.terrain.grid import TerrainGrid


def line():
    return Alignment({"station": 0.0, "northing": 0.0, "easting": 0.0},
                     [{"kind": "tangent", "bearing": "N 0-0-0 E", "length": 100.0}],
                     name="T")


def test_a_plane_through_a_point():
    # 100 + 0.02 (60 - 10) - 0.01 (120 - 20) = 100 + 1 - 1
    g = PlaneGround(100.0, n0=10.0, e0=20.0, slope_n=0.02, slope_e=-0.01)
    assert g.z(60.0, 120.0) == pytest.approx(100.0)
    assert g.z(10.0, 20.0) == pytest.approx(100.0)


def test_a_plane_from_params_passes_through_the_point_of_beginning():
    pob = Alignment({"station": 0.0, "northing": 500.0, "easting": 300.0},
                    [{"kind": "tangent", "bearing": "N 0-0-0 E", "length": 100.0}])
    g = from_params({"source": "plane", "elevation": 95.0, "slope_e": 0.1},
                    pob, None, 50.0, None)
    assert g.z(500.0, 300.0) == pytest.approx(95.0)
    assert g.z(0.0, 310.0) == pytest.approx(96.0)      # slope_e only


def test_the_footprint_is_the_line_plus_its_reach():
    assert footprint(line(), 50.0) == pytest.approx((-50.0, -50.0, 50.0, 150.0))


def test_a_grid_is_read_bilinearly_in_feet():
    # 3 x 3 grid over 0..3 m each way: pixel centres at 0.5, 1.5, 2.5 m.
    # Row 0 is the north edge. z rises 1 m per metre east, 0 north-south.
    z = np.array([[10.0, 11.0, 12.0]] * 3)
    grid = TerrainGrid(z=z, bbox_m=(0.0, 0.0, 3.0, 3.0), spacing_m=1.0,
                       crs_epsg=26942)
    k = 0.3048
    g = GridGround(grid, k, vshift_m=0.5)
    # E 1.0 m is halfway between the 0.5 m and 1.5 m centres: 10.5 m
    assert g.z(1.5 / k, 1.0 / k) == pytest.approx((10.5 - 0.5) / k)
    with pytest.raises(ValueError, match=r"N 0\.0 E 0\.0.*does not cover"):
        g.z(0.0, 0.0)                                  # outside the centres


@pytest.mark.parametrize("gp, ctx, match", [
    ({"source": "3dep"}, ProjectContext(name="g", epsg=2226, guid_ns=uuid.UUID(int=5)),
     "cache"),
    ({"source": "3dep", "cache": "x"}, ProjectContext(name="g", guid_ns=uuid.UUID(int=5)),
     "epsg"),
    ({"source": "lidar"}, None, "plane or 3dep"),
    (None, None, "plane or 3dep"),
])
def test_bad_ground_is_refused(gp, ctx, match):
    with pytest.raises(ValueError, match=match):
        from_params(gp, line(), ctx, 50.0, None)
