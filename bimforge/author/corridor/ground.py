"""The ground a road corridor is measured against (roadmap P.6).

`plane`: a plane through the alignment's point of beginning, for tests and
the shipped example, so CI never touches the network. `3dep`: the USGS 3DEP
1 m DEM over the corridor's footprint, read through bimforge.terrain. A
ground answers `z(northing, easting)` in the project's vertical datum, feet.
"""
from __future__ import annotations

import math


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
    """A bimforge.terrain TerrainGrid (metres, NAVD88), read in feet in the
    project datum. Where the grid has no ground (outside its pixel centres,
    or a nodata pixel) `z` raises, naming the point: the corridor is never
    measured against invented ground."""

    def __init__(self, grid, ft_to_m: float, vshift_m: float = 0.0) -> None:
        self.grid, self.ft_to_m, self.vshift_m = grid, float(ft_to_m), float(vshift_m)

    def z(self, n: float, e: float) -> float:
        from bimforge.terrain.diff import sample_grid
        zm = float(sample_grid(self.grid.z, self.grid.bbox_m,
                               e * self.ft_to_m, n * self.ft_to_m)[0])
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
        # The fetch is pending a decision: bimforge.terrain passes its bbox
        # to 3DEP in the CRS's own units and scales the mesh by one factor
        # for plan and height alike, which holds only for a metric CRS.
        raise NotImplementedError("ground: source 3dep is not wired yet")
    raise ValueError(f"ground: source {gp.get('source') if gp else None!r} is "
                     f"not plane or 3dep")
