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
    assert g.spacing_ft == pytest.approx(1.0 / k)      # 1 m cells, in feet
    assert PlaneGround(0.0).spacing_ft is None


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


US_FT = 0.30480060960121924


@pytest.mark.parametrize("epsg, crs_m", [(2226, US_FT), (26942, 1.0)])
def test_3dep_fetches_in_crs_units_and_reads_back_in_feet(monkeypatch, tmp_path,
                                                          epsg, crs_m):
    """A ftUS CRS gets its bbox in ft and 1 m spacing as ~3.28 ftUS; a metric
    CRS gets metres. Either way the ground and the TERRAIN mesh come back in
    model ft, with vshift_m taken off in metres. The fetch is stubbed."""
    import bimforge.terrain as T
    import bimforge.terrain.attach as A
    from bimforge.author.model import StructureModel
    calls = []

    def fake_fetch(bbox_m, spacing_m, crs_epsg, cache_path, refresh=False, log=print):
        calls.append((bbox_m, spacing_m, crs_epsg, str(cache_path)))
        xmin, ymin, xmax, ymax = bbox_m
        cols = max(2, int(round((xmax - xmin) / spacing_m)))
        rows = max(2, int(round((ymax - ymin) / spacing_m)))
        e = xmin + (np.arange(cols) + 0.5) * (xmax - xmin) / cols
        z = np.tile(30.48 + 0.01 * e, (rows, 1))      # rises 0.01 m per CRS unit east
        return TerrainGrid(z=z, bbox_m=bbox_m, spacing_m=spacing_m, crs_epsg=crs_epsg)

    monkeypatch.setattr(T, "fetch_3dep_dem", fake_fetch)
    monkeypatch.setattr(A, "fetch_3dep_dem", fake_fetch)
    ctx = ProjectContext(name="g", epsg=epsg, guid_ns=uuid.UUID(int=5))
    model = StructureModel("g", ctx)
    stem = str(tmp_path / "ml")
    g = from_params({"source": "3dep", "cache": stem, "margin_ft": 10.0,
                     "vshift_m": 0.5}, line(), ctx, 40.0, model, log=lambda *_: None)

    c = US_FT / crs_m                                  # CRS units per model ft
    bbox, spacing, got_epsg, cache = calls[0]
    assert bbox == pytest.approx((-50 * c, -50 * c, 50 * c, 150 * c))
    assert spacing == pytest.approx(1.0 / crs_m)       # 3.2808 ftUS, or 1 m
    assert (got_epsg, cache) == (epsg, stem + "-3DEP-DEM.tif")

    # E 10 ft is 10 c CRS units: z_m = 30.48 + 0.1 c, less 0.5 m, in ft
    assert g.z(50.0, 10.0) == pytest.approx((30.48 + 0.1 * c - 0.5) / US_FT)
    with pytest.raises(ValueError, match="N 5000.0 E 0.0.*does not cover"):
        g.z(5000.0, 0.0)

    (terrain,) = [el for el in model.elements if el.predefined_type == "TERRAIN"]
    # 100 x 200 ft at 1 m: 30 cols x 61 rows; vertex 0 is the NW pixel centre
    n0, e0 = 150.0 - 0.5 * 200.0 / 61, -50.0 + 0.5 * 100.0 / 30
    assert terrain.geometry["verts"][0] == pytest.approx(
        (n0, e0, (30.48 + 0.01 * e0 * c - 0.5) / US_FT))


@pytest.mark.parametrize("nodata", [np.nan, -3.4e38])
def test_a_nodata_cell_inside_the_grid_is_no_ground(nodata):
    # 4 x 4 over 0..4 m; the cell at row 1, col 1 (N 2.5 m, E 1.5 m) is a hole
    z = np.full((4, 4), 10.0)
    z[1, 1] = nodata
    grid = TerrainGrid(z=z, bbox_m=(0.0, 0.0, 4.0, 4.0), spacing_m=1.0,
                       crs_epsg=26942)
    g = GridGround(grid, 1.0)                          # 1 CRS unit per model ft
    assert g.z(1.0, 3.0) == pytest.approx(10.0)        # clear of the hole
    with pytest.raises(ValueError, match=r"N 2\.0 E 2\.0.*does not cover"):
        g.z(2.0, 2.0)                                  # its 2x2 holds the hole


def test_the_fetch_margin_is_at_least_two_dem_cells(monkeypatch, tmp_path):
    # margin_ft 0 at 1 m spacing is floored to 2 m = 6.5617 ft, so a daylight
    # at the reach still has pixel centres around it
    import bimforge.terrain as T
    import bimforge.terrain.attach as A
    from bimforge.author.model import StructureModel
    calls = []

    def fake_fetch(bbox_m, spacing_m, crs_epsg, cache_path, refresh=False, log=print):
        calls.append(bbox_m)
        return TerrainGrid(z=np.full((4, 4), 30.0), bbox_m=bbox_m,
                           spacing_m=spacing_m, crs_epsg=crs_epsg)

    monkeypatch.setattr(T, "fetch_3dep_dem", fake_fetch)
    monkeypatch.setattr(A, "fetch_3dep_dem", fake_fetch)
    ctx = ProjectContext(name="g", epsg=2226, guid_ns=uuid.UUID(int=5))
    from_params({"source": "3dep", "cache": str(tmp_path / "ml"), "margin_ft": 0.0},
                line(), ctx, 40.0, StructureModel("g", ctx), log=lambda *_: None)
    r = 40.0 + 2.0 / US_FT
    assert calls[0] == pytest.approx((-r, -r, r, 100.0 + r))
