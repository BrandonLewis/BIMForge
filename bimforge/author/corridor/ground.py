"""The ground a road corridor is measured against (roadmap P.6).

`plane`: a plane through the alignment's point of beginning, for tests and
the shipped example, so CI never touches the network. `3dep`: the USGS 3DEP
1 m DEM over the corridor's footprint, cached under a path stem as
bimforge.terrain caches it (rebuilds are offline), with the TERRAIN element
added from the same cache. A ground answers `z(northing, easting)` in the
project's vertical datum, feet.
"""
from __future__ import annotations

import math
from pathlib import Path


class PlaneGround:
    """z = elevation + slope_n (n - n0) + slope_e (e - e0)."""

    def __init__(self, elevation: float, n0: float = 0.0, e0: float = 0.0,
                 slope_n: float = 0.0, slope_e: float = 0.0) -> None:
        self.elevation, self.n0, self.e0 = float(elevation), float(n0), float(e0)
        self.slope_n, self.slope_e = float(slope_n), float(slope_e)

    def z(self, n: float, e: float) -> float:
        return (self.elevation + self.slope_n * (n - self.n0)
                + self.slope_e * (e - self.e0))


class GridGround:
    """A bimforge.terrain TerrainGrid (plan in CRS units, z in NAVD88
    metres), read in feet in the project datum. `crs_per_ft` is CRS units
    per model foot: 1.0 for a ftUS CRS under a ftUS model, `ft_to_m` (the
    default) for a metric CRS. Where the grid has no ground (outside its
    pixel centres, or a nodata pixel) `z` raises, naming the point: the
    corridor is never measured against invented ground."""

    def __init__(self, grid, ft_to_m: float, vshift_m: float = 0.0,
                 crs_per_ft: float | None = None) -> None:
        self.grid, self.ft_to_m, self.vshift_m = grid, float(ft_to_m), float(vshift_m)
        self.crs_per_ft = self.ft_to_m if crs_per_ft is None else float(crs_per_ft)

    def z(self, n: float, e: float) -> float:
        from bimforge.terrain.diff import sample_grid
        zm = float(sample_grid(self.grid.z, self.grid.bbox_m,
                               e * self.crs_per_ft, n * self.crs_per_ft)[0])
        if math.isnan(zm):
            raise ValueError(f"ground: no ground at N {n:.1f} E {e:.1f}: the "
                             f"DEM does not cover it")
        return (zm - self.vshift_m) / self.ft_to_m


def footprint(alignment, reach: float) -> tuple:
    """(e_min, n_min, e_max, n_max), survey feet: the alignment, sampled
    every 10 ft or closer, grown by `reach` each way."""
    run = alignment.s_end - alignment.s_start
    n = max(1, math.ceil(run / 10.0))
    pts = [alignment.point_az(alignment.s_start + run * i / n)[:2]
           for i in range(n + 1)]
    ns, es = [p[0] for p in pts], [p[1] for p in pts]
    return (min(es) - reach, min(ns) - reach, max(es) + reach, max(ns) + reach)


def from_params(gp: dict, alignment, ctx, reach: float, model, log=print):
    """The ground `gp` (the spec's `ground:`) names. `reach` is how far from
    the line the corridor can reach, feet; a 3DEP ground adds the TERRAIN
    element to `model`."""
    source = str((gp or {}).get("source", "")).lower()
    if source == "plane":
        n0, e0, _az = alignment.point_az(alignment.s_start)
        return PlaneGround(float(gp["elevation"]), n0=n0, e0=e0,
                           slope_n=float(gp.get("slope_n", 0.0)),
                           slope_e=float(gp.get("slope_e", 0.0)))
    if source == "3dep":
        if not gp.get("cache"):
            raise ValueError("ground: source 3dep needs `cache`, the path stem "
                             "its downloads are kept under")
        if ctx is None or ctx.epsg is None:
            raise ValueError("ground: source 3dep needs project.epsg")
        import bimforge.terrain as terrain
        from bimforge.bim.georef import crs_unit
        # 3DEP reads the bbox and spacing in the CRS's own unit (ftUS for a
        # State Plane zone in feet); elevations come back in metres. The
        # model is in feet, so plan and height convert apart.
        ft = ctx.ft_to_m
        _unit, crs_m = crs_unit(ctx.epsg)
        c = ft / crs_m                                 # CRS units per model ft
        spacing_m = float(gp.get("spacing_m", 1.0))
        spacing = spacing_m / crs_m
        vshift = float(gp.get("vshift_m", 0.0))
        # at least two DEM cells past the reach: a daylight in the grid's
        # last half pixel would have no pixel centre beyond it to read
        margin = max(float(gp.get("margin_ft", 200.0)), 2.0 * spacing_m / ft)
        e0, n0, e1, n1 = footprint(alignment, reach + margin)
        bbox = (e0 * c, n0 * c, e1 * c, n1 * c)
        stem = str(gp["cache"])
        grid = terrain.fetch_3dep_dem(bbox, spacing, ctx.epsg,
                                      Path(stem + "-3DEP-DEM.tif"), log=log)
        terrain.attach_terrain(model, bbox, crs_epsg=ctx.epsg, cache_stem=stem,
                               unit_scale=1.0 / ft, plan_scale=1.0 / c,
                               spacing_m=spacing, vshift_m=vshift, log=log)
        return GridGround(grid, ft, vshift, crs_per_ft=c)
    raise ValueError(f"ground: source {gp.get('source') if gp else None!r} is "
                     f"not plane or 3dep")
