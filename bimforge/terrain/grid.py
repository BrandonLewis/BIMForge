"""Terrain elevation grids and their conversion to model-unit meshes.

The terrain package is METRIC internally (source-native: NAVD88 metres on a
metric grid in the project CRS); conversion to model units and the project
vertical datum happens exactly once, in `grid_to_mesh(unit_scale, vshift_m)`.
Ported from the bridge-pilot build_bridge.py terrain arc.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TerrainGrid:
    """An elevation raster over a metric bbox.

    `z[rows, cols]` — elevations in NAVD88 metres (ndarray; NaN = nodata);
    `bbox_m` — `(xmin, ymin, xmax, ymax)` in the CRS named by `crs_epsg`;
    `spacing_m` — nominal cell size in metres;
    `crs_epsg` — the horizontal CRS the bbox (and grid) live in;
    `info` — source-specific metadata (LPC project/tiles/publication;
    empty for the DEM path).
    """

    z: Any
    bbox_m: tuple
    spacing_m: float
    crs_epsg: int
    info: dict = field(default_factory=dict)


def fill_nodata(z):
    """Fill NaN cells in a grid by iterated 4-neighbour averaging. Cheap and
    good enough for the rare gaps a dense class-2 lidar bin leaves — no scipy
    needed. Neighbours are true edge-clipped 4-neighbours (NaN-padded, not
    wrapped — the bridge-pilot original used np.roll, which treats the raster as
    toroidal and can fill an edge hole from the opposite side). An all-NaN
    grid comes back unchanged (the loop exhausts its 64 iterations with
    nothing to seed from) — the caller's problem to notice.
    """
    import numpy as np
    z = z.astype("float64")
    for _ in range(64):
        holes = np.isnan(z)
        if not holes.any():
            break
        p = np.pad(z, 1, constant_values=np.nan)
        with np.errstate(invalid="ignore"):
            nb = np.nanmean(np.stack([p[:-2, 1:-1], p[2:, 1:-1],
                                      p[1:-1, :-2], p[1:-1, 2:]]),
                            axis=0)
        take = holes & ~np.isnan(nb)
        z[take] = nb[take]
    return z


def grid_to_mesh(grid: TerrainGrid, unit_scale, vshift_m):
    """Triangulate a TerrainGrid into `(verts, tris)` in the model's own units.

    One vertex per valid (non-nodata) pixel CENTRE as `(n, e, z)`, with
    `z = (z_m - vshift_m) * unit_scale` — this is the single place NAVD88
    metres become the model's vertical datum and units. Two triangles per
    pixel quad, and only fully-valid corner triples emit, so nodata pixels
    leave holes instead of inventing ground.
    """
    import numpy as np
    z = np.asarray(grid.z, dtype="float64")
    rows, cols = z.shape
    xmin, ymin, xmax, ymax = grid.bbox_m
    # esri nodata can land as a huge negative float rather than NaN.
    valid = np.isfinite(z) & (z > -1e10)
    vid = np.full((rows, cols), -1, dtype=np.int64)
    verts = []
    for r in range(rows):
        n_coord = ymax - (r + 0.5) * (ymax - ymin) / rows
        for c in range(cols):
            if not valid[r, c]:
                continue
            e_coord = xmin + (c + 0.5) * (xmax - xmin) / cols
            vid[r, c] = len(verts)
            verts.append((n_coord * unit_scale, e_coord * unit_scale,
                          (float(z[r, c]) - vshift_m) * unit_scale))
    tris = []
    for r in range(rows - 1):
        for c in range(cols - 1):
            a, b, cc, d = (vid[r, c], vid[r, c + 1],
                           vid[r + 1, c], vid[r + 1, c + 1])
            if a >= 0 and cc >= 0 and b >= 0:
                tris.append((a, cc, b))
            if b >= 0 and cc >= 0 and d >= 0:
                tris.append((b, cc, d))
    return verts, tris
