"""The ground a road corridor is measured against (roadmap P.6).

`terrain`: the spec's top-level `terrain:` block (G.9), the USGS 3DEP
ground fetched over the corridor's footprint, cached under its path stem as
bimforge.terrain caches it (rebuilds are offline), and added as the model's
TERRAIN element. `plane`: a plane through the alignment's point of
beginning, for tests and the shipped example, so CI never touches the
network; with a `terrain:` block the corridor still measures against the
plane, and the TERRAIN element is the fetched ground. `3dep` (0.1.132) is
read as a `terrain:` block of its own `cache`, `spacing_m`, `margin_ft` and
`vshift_m`. A ground answers `z(northing, easting)` in the project's
vertical datum, feet.
"""
from __future__ import annotations

import math


class PlaneGround:
    """z = elevation + slope_n (n - n0) + slope_e (e - e0)."""

    #: a plane has no cells: one ground reading per subgrade segment is exact
    spacing_ft = None

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

    @property
    def spacing_ft(self) -> float:
        """The grid's cell size, model feet."""
        return self.grid.spacing_m / self.crs_per_ft


def footprint(alignment, reach: float) -> tuple:
    """(e_min, n_min, e_max, n_max), survey feet: the alignment, sampled
    every 10 ft or closer, grown by `reach` each way."""
    run = alignment.s_end - alignment.s_start
    n = max(1, math.ceil(run / 10.0))
    pts = [alignment.point_az(alignment.s_start + run * i / n)[:2]
           for i in range(n + 1)]
    ns, es = [p[0] for p in pts], [p[1] for p in pts]
    return (min(es) - reach, min(ns) - reach, max(es) + reach, max(ns) + reach)


#: the plane's TERRAIN mesh cell, feet: a plane needs no density
PLANE_CELL_FT = 50.0


def _plane_terrain(ground, alignment, ctx, reach: float, margin: float,
                   model) -> None:
    """The plane as a TERRAIN element over the footprint a 3DEP fetch would
    cover: a coarse grid of the plane, meshed by bimforge.terrain as a DEM
    is, so a cut voids it exactly as it voids 3DEP ground."""
    import numpy as np

    from bimforge.terrain.attach import add_terrain, to_model_frame
    from bimforge.terrain.grid import TerrainGrid, grid_to_mesh
    cell = PLANE_CELL_FT
    margin = max(margin, 2.0 * cell)
    e0, n0, e1, n1 = footprint(alignment, reach + margin)
    cols = max(2, math.ceil((e1 - e0) / cell))
    rows = max(2, math.ceil((n1 - n0) / cell))
    e1, n1 = e0 + cols * cell, n0 + rows * cell
    # pixel centres, row 0 north (TerrainGrid); z in metres, as a DEM's
    es = e0 + (np.arange(cols) + 0.5) * cell
    ns = n1 - (np.arange(rows) + 0.5) * cell
    k = ctx.ft_to_m
    z = np.array([[ground.z(n, e) * k for e in es] for n in ns])
    grid = TerrainGrid(z=z, bbox_m=(e0, n0, e1, n1), spacing_m=cell,
                       crs_epsg=ctx.epsg)
    verts, tris = grid_to_mesh(grid, 1.0 / k, 0.0, plan_scale=1.0)
    prov = {"Source": "Design plane (ground: plane)",
            "PlaneElevation": ground.elevation, "PlaneSlopeN": ground.slope_n,
            "PlaneSlopeE": ground.slope_e, "MeshSpacing": cell,
            "MeshSpacingUnit": "ftUS" if abs(k - 1200.0 / 3937.0) < 1e-12 else "ft",
            "Carved": False, "SurveyGrade": False}
    to_model_frame(add_terrain(model, "Existing ground - design plane",
                               verts, tris, prov), ctx)


def from_params(gp: dict, alignment, ctx, reach: float, model, log=print,
                terrain=None):
    """The ground `gp` (the spec's `ground:`) names, which the corridor
    calculates against. `reach` is how far from the line the corridor can
    reach, feet; `terrain` is the spec's `terrain:` block (a
    `bimforge.terrain.spec.TerrainSpec`), or None.

    `source: terrain`: the terrain block's 3DEP ground, fetched over the
    corridor's footprint, which it adds as the TERRAIN element. `source:
    plane`: a test plane; the TERRAIN element is the terrain block's ground
    when there is one, else the plane meshed over the same footprint.
    `source: 3dep` (0.1.132) is read as a terrain block of its own settings.
    The element is added in the model frame."""
    source = str((gp or {}).get("source", "")).lower()
    if source == "3dep":
        if terrain is not None:
            raise ValueError("ground: source 3dep and a terrain: block both "
                             "name the ground; keep the terrain: block")
        if not gp.get("cache"):
            raise ValueError("ground: source 3dep needs `cache`, the path stem "
                             "its downloads are kept under")
        from bimforge.terrain.spec import from_ground
        terrain, source = from_ground(gp), "terrain"
    if source == "plane":
        n0, e0, _az = alignment.point_az(alignment.s_start)
        ground = PlaneGround(float(gp["elevation"]), n0=n0, e0=e0,
                             slope_n=float(gp.get("slope_n", 0.0)),
                             slope_e=float(gp.get("slope_e", 0.0)))
        if model is not None and ctx is not None:
            if terrain is not None:
                from bimforge.terrain.spec import attach_over
                attach_over(model, ctx, terrain, footprint(alignment, reach),
                            log=log)
            else:
                _plane_terrain(ground, alignment, ctx, reach,
                               float(gp.get("margin_ft", 200.0)), model)
        return ground
    if source == "terrain":
        if terrain is None:
            raise ValueError("ground: source terrain needs a top-level "
                             "terrain: block")
        if ctx is None or ctx.epsg is None:
            raise ValueError("ground: the terrain needs project.epsg")
        from bimforge.author.model import StructureModel
        from bimforge.terrain.spec import attach_over, crs_per_ft
        target = model if model is not None else StructureModel("ground", ctx)
        _el, grid, shift = attach_over(target, ctx, terrain,
                                       footprint(alignment, reach), log=log)
        return GridGround(grid, ctx.ft_to_m, shift, crs_per_ft=crs_per_ft(ctx))
    raise ValueError(f"ground: source {gp.get('source') if gp else None!r} is "
                     f"not plane, terrain or 3dep")
