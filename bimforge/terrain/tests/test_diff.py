"""terrain/diff: sample_grid, diff_surface, write_diff_csv, plot_diff (Work port)."""
import types

import numpy as np
import pytest

from bimforge.terrain.diff import (M_PER_FT, TIN_CSV_HEADER, diff_surface,
                                   diff_tins, plot_diff, sample_grid,
                                   sample_mesh, summarize_tin_diff,
                                   write_diff_csv, write_tin_diff_csv)
from bimforge.terrain.grid import TerrainGrid


def planar_grid(a=2.0, b=3.0, c=5.0, rows=4, cols=4, bbox=(0.0, 0.0, 4.0, 4.0)):
    """A grid whose pixel-centre values lie on the plane z = a*e + b*n + c,
    using the package's north-up pixel-centre convention (row 0 = ymax edge:
    n = ymax - (r+0.5)*dy, e = xmin + (c+0.5)*dx).
    """
    xmin, ymin, xmax, ymax = bbox
    dx = (xmax - xmin) / cols
    dy = (ymax - ymin) / rows
    z = np.empty((rows, cols))
    for r in range(rows):
        n = ymax - (r + 0.5) * dy
        for col in range(cols):
            e = xmin + (col + 0.5) * dx
            z[r, col] = a * e + b * n + c
    return z, bbox


# --- sample_grid -----------------------------------------------------------

def test_sample_grid_bilinear_exact_on_planar_grid():
    # Bilinear interpolation reproduces a plane exactly, so sampling a grid
    # built from z = 2e + 3n + 5 at arbitrary interior points must return the
    # plane's own value — this pins the pixel-centre convention (an off-by-
    # half-a-cell bug shows up as a constant a*dx/2 + b*dy/2 error).
    z, bbox = planar_grid()
    ex = np.array([1.2, 2.0, 3.49, 0.5])
    ny = np.array([2.7, 1.0, 0.51, 3.5])
    got = sample_grid(z, bbox, ex, ny)
    want = 2.0 * ex + 3.0 * ny + 5.0
    assert got == pytest.approx(want, abs=1e-9)


def test_sample_grid_outside_coverage_is_nan():
    # Points off the grid — and inside the bbox but outside the pixel-CENTRE
    # coverage (no complete 2x2 neighbourhood) — come back NaN, never
    # extrapolated.
    z, bbox = planar_grid()
    got = sample_grid(z, bbox, np.array([10.0, 0.2, 2.0]),
                      np.array([10.0, 0.2, 3.9]))
    assert np.isnan(got).all()


def test_sample_grid_nodata_corner_poisons_the_quad():
    # NaN and esri-sentinel corners poison any sample touching their quad
    # instead of inventing ground.
    z, bbox = planar_grid()
    z[1, 1] = np.nan
    z[2, 2] = -3.4e38
    # (1.2, 2.7) interpolates among cols 0-1 / rows 0-1 -> touches z[1, 1];
    # (2.3, 1.4) among cols 1-2 / rows 2-3... touches z[2, 2].
    got = sample_grid(z, bbox, np.array([1.2, 2.6]), np.array([2.7, 1.4]))
    assert np.isnan(got).all()
    # A quad far from both holes still samples fine.
    ok = sample_grid(z, bbox, np.array([0.7]), np.array([0.7]))
    assert np.isfinite(ok).all()


# --- diff_surface ----------------------------------------------------------

def flat_grid(z_m, bbox=(0.0, 0.0, 4.0, 4.0), rows=4, cols=4, epsg=32610):
    return TerrainGrid(z=np.full((rows, cols), float(z_m)), bbox_m=bbox,
                       spacing_m=1.0, crs_epsg=epsg, info={})


def test_diff_surface_sign_convention_plan_above_is_positive():
    # Sign convention: plan minus terrain. A metric surface 1 m ABOVE a flat
    # 10 m terrain must come back delta = +1.
    grid = flat_grid(10.0)
    pts = np.array([[1.0, 1.0, 11.0],
                    [2.5, 2.5, 11.0]])
    rows = diff_surface(pts, grid, unit_scale_to_m=1.0, vshift_m=0.0)
    assert rows.shape == (2, 5)
    e, n, plan_z, terrain_z, delta = rows.T
    assert e == pytest.approx([1.0, 2.5])
    assert n == pytest.approx([1.0, 2.5])
    assert plan_z == pytest.approx([11.0, 11.0])
    assert terrain_z == pytest.approx([10.0, 10.0])
    assert delta == pytest.approx([1.0, 1.0])


def test_diff_surface_converts_units_and_datum():
    # A ftUS surface on a project vertical datum vs a metric NAVD88 grid:
    # unit_scale_to_m converts the horizontal AND vertical units, vshift_m
    # (project datum -> NAVD88, metres — the cached NCAT shift) moves the
    # plan onto NAVD88, and both surfaces meet on one datum.
    grid = flat_grid(10.0)
    vshift = 0.7                               # NAVD88 = project datum + 0.7
    z_even_ft = (10.0 - vshift) / M_PER_FT     # lands exactly ON the terrain
    z_above_ft = (10.0 - vshift + 1.0) / M_PER_FT   # 1 m above it
    pts_ft = np.array([[2.0 / M_PER_FT, 2.0 / M_PER_FT, z_even_ft],
                       [1.0 / M_PER_FT, 3.0 / M_PER_FT, z_above_ft]])
    rows = diff_surface(pts_ft, grid, unit_scale_to_m=M_PER_FT,
                        vshift_m=vshift)
    e, n, plan_z, terrain_z, delta = rows.T
    assert e == pytest.approx([2.0, 1.0])
    assert n == pytest.approx([2.0, 3.0])
    assert terrain_z == pytest.approx([10.0, 10.0])
    assert delta == pytest.approx([0.0, 1.0], abs=1e-9)


def test_diff_surface_keeps_off_grid_points_as_nan_rows():
    # Output stays parallel to the input points; off-grid points carry NaN
    # terrain/delta rather than being silently dropped.
    grid = flat_grid(10.0)
    pts = np.array([[1.0, 1.0, 11.0],
                    [100.0, 100.0, 11.0]])
    rows = diff_surface(pts, grid, unit_scale_to_m=1.0, vshift_m=0.0)
    assert rows.shape == (2, 5)
    assert np.isfinite(rows[0]).all()
    assert np.isnan(rows[1, 3]) and np.isnan(rows[1, 4])


# --- write_diff_csv --------------------------------------------------------

def test_write_diff_csv_roundtrip_drops_nan_rows(tmp_path):
    grid = flat_grid(10.0)
    pts = np.array([[1.0, 1.0, 11.0],
                    [2.5, 2.5, 9.25],
                    [100.0, 100.0, 11.0]])      # off-grid -> not written
    rows = diff_surface(pts, grid, unit_scale_to_m=1.0, vshift_m=0.0)
    path = tmp_path / "diff.csv"
    n = write_diff_csv(rows, path)
    assert n == 2
    lines = path.read_text().splitlines()
    assert lines[0] == ("easting_m,northing_m,plan_navd88_m,"
                       "terrain_navd88_m,delta_m")
    back = np.loadtxt(path, delimiter=",", skiprows=1)
    assert back.shape == (2, 5)
    assert back == pytest.approx(rows[:2], abs=1e-3)
    assert back[1, 4] == pytest.approx(-0.75, abs=1e-3)


# --- plot_diff -------------------------------------------------------------

def test_plot_diff_degrades_with_a_log_line_without_matplotlib(tmp_path,
                                                               monkeypatch):
    import bimforge.terrain.diff as diff_mod

    def no_mpl():
        raise ImportError("No module named 'matplotlib'")

    monkeypatch.setattr(diff_mod, "_import_pyplot", no_mpl)
    logged = []
    rows = np.array([[1.0, 1.0, 11.0, 10.0, 1.0]])
    path = tmp_path / "diff.png"
    assert plot_diff(rows, path, log=logged.append) is False
    assert not path.exists()
    assert any("matplotlib" in m for m in logged)


def test_plot_diff_writes_png_when_matplotlib_present(tmp_path):
    pytest.importorskip("matplotlib")
    grid = flat_grid(10.0)
    pts = np.array([[1.0, 1.0, 11.0],
                    [2.5, 2.5, 9.25],
                    [1.5, 2.5, 10.0]])
    rows = diff_surface(pts, grid, unit_scale_to_m=1.0, vshift_m=0.0)
    path = tmp_path / "diff.png"
    assert plot_diff(rows, path, log=lambda m: None) is True
    assert path.exists() and path.stat().st_size > 0


def test_plot_diff_no_finite_deltas_degrades(tmp_path):
    # All-NaN deltas must skip the PNG with a log line, not raise on the
    # percentile of an empty slice (Copilot, PR #125).
    import numpy as np
    from bimforge.terrain.diff import plot_diff
    rows = np.array([[0.0, 0.0, 0.0, 0.0, np.nan]])
    msgs = []
    out = tmp_path / "d.png"
    assert plot_diff(rows, out, log=msgs.append) is False
    assert not out.exists()
    assert any("no finite deltas" in m for m in msgs)


# ------------------------------------------------------------ TIN vs TIN

def _square_tin(z0, slope=0.1, size=100.0):
    """Two triangles over [0, size]^2 with z = z0 + slope * x."""
    xy = np.array([[0, 0], [size, 0], [size, size], [0, size]], float)
    pts = np.column_stack([xy, z0 + slope * xy[:, 0]])
    return types.SimpleNamespace(points=pts, simplices=np.array([[0, 1, 2], [0, 2, 3]]))


def test_sample_mesh_is_exact_on_a_plane_and_nan_outside():
    t = _square_tin(100.0)
    z = sample_mesh(t.points, t.simplices, [[25.0, 40.0], [100.0, 100.0], [-1.0, 5.0]])
    assert z[0] == pytest.approx(102.5) and z[1] == pytest.approx(110.0)
    assert np.isnan(z[2])


def test_sample_mesh_leaves_a_missing_triangle_empty():
    t = _square_tin(100.0)
    z = sample_mesh(t.points, t.simplices[:1], [[75.0, 10.0], [10.0, 75.0]])
    assert z[0] == pytest.approx(107.5) and np.isnan(z[1])   # 2nd triangle dropped


def test_sample_mesh_skips_a_sliver_triangle():
    # three state-plane points a hair off collinear: a zero-area sliver whose
    # barycentric z would be rounding noise — it samples as empty
    x0, y0 = 6_692_000.0, 2_008_000.0
    pts = np.array([[x0, y0, 10.0], [x0 + 100.0, y0, 10.0],
                    [x0 + 50.0, y0 + 1e-9, 500.0]])
    z = sample_mesh(pts, [[0, 1, 2]], [[x0 + 50.0, y0 + 5e-10]])
    assert np.isnan(z[0])
    # a thin but real triangle (0.01 ft over a 100 ft base) still samples
    pts[2, 1] = y0 + 0.01
    z = sample_mesh(pts, [[0, 1, 2]], [[x0 + 50.0, y0 + 0.005]])
    assert z[0] == pytest.approx(255.0)


def test_diff_tins_offset_and_no_overlap():
    rows = diff_tins(_square_tin(100.0), _square_tin(98.0), step=10.0)
    assert rows.shape == (121, 5)
    np.testing.assert_allclose(rows[:, 4], 2.0)
    far = _square_tin(98.0)
    far.points = far.points + [5000.0, 0.0, 0.0]
    assert diff_tins(_square_tin(100.0), far, step=10.0).shape == (0, 5)


def test_summarize_tin_diff_tie_share_and_zones():
    rows = diff_tins(_square_tin(100.3), _square_tin(100.0), step=10.0)
    s = summarize_tin_diff(rows, step=10.0, tie_tol=0.5, zones=[
        {"name": "west", "polygon": [[0, 0], [45, 0], [45, 100], [0, 100]]}])
    assert s["all"]["n"] == 121 and s["all"]["area_sqft"] == pytest.approx(12100.0)
    assert s["all"]["within_tie_tol"] == pytest.approx(1.0)
    assert s["all"]["median"] == pytest.approx(0.3)
    assert 0 < s["zones"]["west"]["n"] < 121


def test_summarize_tin_diff_empty_is_honest():
    s = summarize_tin_diff(np.zeros((0, 5)), step=5.0, tie_tol=0.5)
    assert s["all"]["n"] == 0 and s["all"]["median"] is None


def test_write_tin_diff_csv(tmp_path):
    rows = diff_tins(_square_tin(100.0), _square_tin(98.0), step=50.0)
    p = tmp_path / "d.csv"
    assert write_tin_diff_csv(rows, p, log=lambda m: None) == len(rows)
    assert p.read_text().splitlines()[0] == TIN_CSV_HEADER
