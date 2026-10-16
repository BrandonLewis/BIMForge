"""terrain/grid: TerrainGrid, fill_nodata, grid_to_mesh (bridge-pilot port)."""
import numpy as np
import pytest

from bimforge.terrain.grid import TerrainGrid, fill_nodata, grid_to_mesh

FT_PER_M = 1 / 0.3048


def test_fill_nodata_fills_interior_nans_with_neighbour_mean():
    z = np.array([[1.0, 2.0, 3.0, 4.0],
                  [5.0, np.nan, 7.0, 8.0],
                  [9.0, 10.0, np.nan, 12.0],
                  [13.0, 14.0, 15.0, 16.0]])
    out = fill_nodata(z)
    assert not np.isnan(out).any()
    # Each hole's 4-neighbours are finite, so one pass fills it with their mean.
    assert out[1, 1] == pytest.approx((2.0 + 10.0 + 5.0 + 7.0) / 4)   # 6.0
    assert out[2, 2] == pytest.approx((7.0 + 15.0 + 10.0 + 12.0) / 4)  # 11.0
    # Finite cells are untouched.
    assert out[0, 0] == 1.0
    assert out[3, 3] == 16.0


def test_fill_nodata_does_not_wrap_edges():
    # An edge hole must fill from its true (edge-clipped) neighbours only —
    # the bridge-pilot np.roll original was toroidal and could pull the value from
    # the raster's opposite side (Copilot review, PR #124).
    z = np.array([[np.nan, 5.0, 100.0],
                  [5.0, 5.0, 100.0],
                  [5.0, 5.0, 100.0]])
    out = fill_nodata(z)
    # True neighbours of (0,0) are 5.0 (right) and 5.0 (below) -> 5.0.
    # A wrapped implementation would average in 100.0 from column 2 and/or
    # row 2 and land above 5.0.
    assert out[0, 0] == pytest.approx(5.0)


def test_fill_nodata_all_nan_returns_unchanged():
    # Contract: an all-NaN grid has no seed values — the loop exhausts its 64
    # iterations and the grid comes back still NaN (caller's problem to notice).
    z = np.full((3, 3), np.nan)
    out = fill_nodata(z)
    assert np.isnan(out).all()
    assert out.shape == (3, 3)


def test_terrain_grid_dataclass():
    z = np.zeros((2, 2))
    g = TerrainGrid(z=z, bbox_m=(0.0, 0.0, 2.0, 2.0), spacing_m=1.0,
                    crs_epsg=32610, info={"project": "x"})
    assert g.z is z
    assert g.bbox_m == (0.0, 0.0, 2.0, 2.0)
    assert g.spacing_m == 1.0
    assert g.crs_epsg == 32610
    assert g.info == {"project": "x"}


def test_grid_to_mesh_2x2_all_valid():
    z = np.array([[10.0, 11.0],
                  [12.0, 13.0]])
    g = TerrainGrid(z=z, bbox_m=(0.0, 0.0, 2.0, 2.0), spacing_m=1.0,
                    crs_epsg=32610, info={})
    verts, tris = grid_to_mesh(g, unit_scale=FT_PER_M, vshift_m=0.5)
    assert len(verts) == 4
    # Row-major pixel CENTRES as (n, e, z) in model units;
    # z = (z_m - vshift_m) * unit_scale.
    expected_m = [(1.5, 0.5, 9.5), (1.5, 1.5, 10.5),
                  (0.5, 0.5, 11.5), (0.5, 1.5, 12.5)]
    for got, (n_m, e_m, z_m) in zip(verts, expected_m):
        assert got == pytest.approx((n_m * FT_PER_M, e_m * FT_PER_M,
                                     z_m * FT_PER_M))
    assert tris == [(0, 2, 1), (1, 2, 3)]


def test_grid_to_mesh_skips_nodata_pixels():
    z = np.array([[np.nan, 11.0],
                  [12.0, 13.0]])
    g = TerrainGrid(z=z, bbox_m=(0.0, 0.0, 2.0, 2.0), spacing_m=1.0,
                    crs_epsg=32610, info={})
    verts, tris = grid_to_mesh(g, unit_scale=1.0, vshift_m=0.0)
    assert len(verts) == 3
    # Only the fully-valid corner triple emits (the a-corner triangle drops).
    assert tris == [(0, 1, 2)]
    assert verts[0] == pytest.approx((1.5, 1.5, 11.0))
    assert verts[1] == pytest.approx((0.5, 0.5, 12.0))
    assert verts[2] == pytest.approx((0.5, 1.5, 13.0))


def test_grid_to_mesh_treats_esri_sentinel_as_nodata():
    # esri nodata often lands as a huge negative float, not NaN.
    z = np.array([[-3.4e38, 11.0],
                  [12.0, 13.0]])
    g = TerrainGrid(z=z, bbox_m=(0.0, 0.0, 2.0, 2.0), spacing_m=1.0,
                    crs_epsg=32610, info={})
    verts, tris = grid_to_mesh(g, unit_scale=1.0, vshift_m=0.0)
    assert len(verts) == 3
    assert tris == [(0, 1, 2)]
