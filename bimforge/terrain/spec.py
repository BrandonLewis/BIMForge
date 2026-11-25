"""The spec's `terrain:` block (roadmap G.9): a model's one existing ground.

`terrain: {source, cache, margin_ft, spacing_m, vshift_m}` names the USGS
3DEP ground a model carries as its TERRAIN element, for any family. The
road corridor calculates against the same ground (`ground: {source:
terrain}`). 3DEP heights are NAVD88; the shift to the project's datum comes
from `vshift_m`, else from `project.vertical_datum` (`terrain_vshift`).
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

#: the keys a `terrain:` block may hold
KEYS = ("source", "cache", "margin_ft", "spacing_m", "vshift_m")
#: dem: the 3DEP 1 m DEM; lpc: the lidar point cloud's bare earth
SOURCES = ("dem", "lpc")


@dataclass
class TerrainSpec:
    """A parsed `terrain:` block. `cache` is the path stem every download
    hangs off; `spacing_m` is in the CRS's own unit, as `attach_terrain`
    takes it (the name is historical); `refresh` is set only by `est-bim
    terrain --refresh`, never by a spec."""

    cache: str
    source: str = "dem"
    margin_ft: float = 200.0
    spacing_m: float = 1.0
    vshift_m: float | None = None
    refresh: bool = False


def parse(block, base_dir, where: str = "terrain") -> TerrainSpec:
    """The `terrain:` mapping as a TerrainSpec; a relative `cache` resolves
    against `base_dir` (the spec's directory) unless that is None."""
    if not isinstance(block, dict):
        raise ValueError(  # noqa: TRY004 - a spec error, like the rest
            f"{where}: must be a mapping ({{source, cache, "
            f"margin_ft, spacing_m, vshift_m}})")
    unknown = sorted(set(block) - set(KEYS))
    if unknown:
        raise ValueError(f"{where}: unknown keys {unknown}; it takes "
                         f"{', '.join(KEYS)}")
    if not block.get("cache"):
        raise ValueError(f"{where}: needs `cache`, the path stem its "
                         f"downloads are kept under")
    source = str(block.get("source", "dem")).lower()
    if source not in SOURCES:
        raise ValueError(f"{where}: source {block['source']!r} is not dem or lpc")
    cache = Path(str(block["cache"]))
    if base_dir is not None and not cache.is_absolute():
        cache = Path(base_dir) / cache
    vs = block.get("vshift_m")
    return TerrainSpec(cache=str(cache), source=source,
                       margin_ft=float(block.get("margin_ft", 200.0)),
                       spacing_m=float(block.get("spacing_m", 1.0)),
                       vshift_m=None if vs is None else float(vs))


def from_ground(gp: dict) -> TerrainSpec:
    """The road corridor's 0.1.132 `ground: {source: 3dep, cache,
    spacing_m, margin_ft, vshift_m}` as the `terrain:` block it now is (its
    cache path as written, as it was read then)."""
    return parse({k: gp[k] for k in ("cache", "spacing_m", "margin_ft",
                                     "vshift_m") if k in gp},
                 None, "ground")


def crs_per_ft(ctx) -> float:
    """CRS units per model foot: 1.0 for a ftUS CRS under a ftUS model."""
    from bimforge.bim.georef import crs_unit
    return ctx.ft_to_m / crs_unit(ctx.epsg)[1]


def base_lonlat(ctx) -> tuple:
    """(lon, lat) of the project base point."""
    from pyproj import Transformer
    c = crs_per_ft(ctx)
    t = Transformer.from_crs(ctx.epsg, 4326, always_xy=True)
    return t.transform(ctx.base_e * c, ctx.base_n * c)


def _datum(name) -> str:
    return re.sub(r"[\s_\-]", "", str(name or "")).upper()


def terrain_vshift(ctx, cache_stem, vshift_m=None, log=print) -> tuple:
    """(shift_m, source): the NAVD88 -> project-datum shift 3DEP heights take,
    in metres (the mesh moves by -shift_m), and where it came from.
    `vshift_m` when given; NAVD88 none; NGVD29 from NOAA NCAT at the base
    point, cached beside the downloads; anything else fails."""
    if vshift_m is not None:
        return float(vshift_m), "spec vshift_m"
    d = _datum(ctx.vertical_datum)
    if d == "NAVD88":
        return 0.0, "NAVD88: none"
    if d == "NGVD29":
        from bimforge.terrain import datum
        path = Path(str(cache_stem) + "-3DEP-vshift.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        lon, lat = base_lonlat(ctx)
        try:
            shift = datum.ncat_vertshift(lat, lon, path, log=log)
        except RuntimeError as e:
            raise ValueError(f"terrain: the NGVD29 shift comes from NOAA NCAT, "
                             f"which did not answer ({e}); give "
                             f"terrain.vshift_m") from None
        source = json.loads(path.read_text()).get("source",
                                                  "NOAA NCAT VERTCON 3.0")
        return float(shift), source
    raise ValueError(f"terrain: 3DEP heights are NAVD88; "
                     f"project.vertical_datum {ctx.vertical_datum!r} has no "
                     f"rule; give terrain.vshift_m")


def model_footprint(model, ctx) -> tuple:
    """(e_min, n_min, e_max, n_max), survey feet: the plan extent of every
    element's placed geometry, leaving out the ground itself."""
    from bimforge.author.emit_ifc import body_dicts
    from bimforge.author.gate import _solid_points
    from bimforge.terrain.attach import is_terrain
    xs, ys = [], []
    for el in model.elements:
        if is_terrain(el):
            continue
        th = math.radians(el.bearing_deg or 0.0)
        c, s = math.cos(th), math.sin(th)
        for dicts in body_dicts(el):
            for d in dicts:
                k = 1.0 if d.get("units", "ft") == "ft" else 1.0 / 12.0
                for p in _solid_points(d):
                    x, y = p[0] * k, p[1] * k
                    xs.append(x * c - y * s + el.x_ft)
                    ys.append(x * s + y * c + el.y_ft)
    if not xs:
        raise ValueError("terrain: the model has no geometry to put the "
                         "ground around")
    return (min(xs) + ctx.base_e, min(ys) + ctx.base_n,
            max(xs) + ctx.base_e, max(ys) + ctx.base_n)


def attach_over(model, ctx, ts: TerrainSpec, bbox_ft, *, log=print) -> tuple:
    """Fetch `ts`'s ground over `bbox_ft` ((e0, n0, e1, n1), survey feet)
    grown by its margin (at least two cells, so a point at the edge has
    pixel centres around it), and add it to `model` as the TERRAIN element
    in the model frame. Returns (element, grid, shift_m): the corridor
    measures against the grid."""
    from bimforge.bim.georef import crs_unit
    from bimforge.terrain.attach import attach_terrain, fetch_grid, to_model_frame
    if ctx is None or ctx.epsg is None:
        raise ValueError("terrain: needs project.epsg")
    c = crs_per_ft(ctx)
    spacing = ts.spacing_m / crs_unit(ctx.epsg)[1]       # in CRS units
    margin = max(ts.margin_ft, 2.0 * ts.spacing_m / ctx.ft_to_m)
    e0, n0, e1, n1 = bbox_ft
    bbox = ((e0 - margin) * c, (n0 - margin) * c,
            (e1 + margin) * c, (n1 + margin) * c)
    Path(ts.cache).parent.mkdir(parents=True, exist_ok=True)
    shift, source = terrain_vshift(ctx, ts.cache, ts.vshift_m, log=log)
    grid = fetch_grid(bbox, crs_epsg=ctx.epsg, cache_stem=ts.cache,
                      spacing_m=spacing, source=ts.source,
                      refresh=ts.refresh, log=log)
    el = attach_terrain(model, bbox, crs_epsg=ctx.epsg, cache_stem=ts.cache,
                        unit_scale=1.0 / ctx.ft_to_m, plan_scale=1.0 / c,
                        spacing_m=spacing, source=ts.source, vshift_m=shift,
                        vshift_source=source, lonlat=base_lonlat(ctx),
                        grid=grid, log=log)
    to_model_frame(el, ctx)
    return el, grid, shift


def add_spec_terrain(model, ctx, ts: TerrainSpec, *, log=print):
    """The spec's ground over the model's footprint, unless the model already
    has one (a family that calculates against it added it while it built).
    Returns the TERRAIN element."""
    from bimforge.terrain.attach import is_terrain
    for el in model.elements:
        if is_terrain(el):
            return el
    return attach_over(model, ctx, ts, model_footprint(model, ctx), log=log)[0]


def report_lines(el, ctx, ts: TerrainSpec) -> list:
    """What `est-bim terrain` prints for one TERRAIN element."""
    from bimforge.terrain.provenance import spacing_unit
    v = el.geometry["verts"]
    c = crs_per_ft(ctx)
    x0, x1 = min(p[0] for p in v), max(p[0] for p in v)
    y0, y1 = min(p[1] for p in v), max(p[1] for p in v)
    unit = spacing_unit(ctx.epsg) or "CRS units"
    p = el.geometry.get("provenance") or {}
    lines = [
        el.name,
        (f"  footprint: E {(x0 + ctx.base_e) * c:,.1f} to "
         f"{(x1 + ctx.base_e) * c:,.1f}, N {(y0 + ctx.base_n) * c:,.1f} to "
         f"{(y1 + ctx.base_n) * c:,.1f} {unit} "
         f"({x1 - x0:,.0f} x {y1 - y0:,.0f} ft)"),
        (f"  cells: {len(v):,} points at "
         f"{p.get('MeshSpacing', ts.spacing_m):g} "
         f"{p.get('MeshSpacingUnit', unit)}"),
        f"  source: {p.get('Source', '')}",
    ]
    if p.get("SourceProject"):
        lines.append(f"  project: {p['SourceProject']}")
    if p.get("AcquisitionStart") or p.get("AcquisitionEnd"):
        lines.append(f"  acquired: {p.get('AcquisitionStart', '')} to "
                     f"{p.get('AcquisitionEnd', '')}")
    if p.get("QualityLevel"):
        lines.append(f"  quality level: {p['QualityLevel']}")
    lines.append(f"  shift {-float(p.get('AppliedVerticalShift', 0.0)):.3f} m "
                 f"({p.get('VerticalShiftSource', '')})")
    stem = Path(ts.cache)
    for f in sorted(stem.parent.glob(stem.name + "-3DEP-*")):
        lines.append(f"  cache: {f}")
    return lines
