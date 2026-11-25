"""attach_terrain — the fetch -> shift -> mesh -> carve -> provenance arc.

The bridge-pilot ``terrain()`` orchestration generalized: explicit bbox / CRS /
unit scale — no hidden project assumptions; the caller (family, script, or
CLI) owns the footprint and margin. The result is a REFERENCE Element
(IfcGeographicElement/TERRAIN, ``classifications=[]``, no quantities) whose
mesh geometry carries the provenance Pset dict, added to the model.
"""

from __future__ import annotations

from pathlib import Path

from .datum import ncat_vertshift
from .fetch import fetch_3dep_dem, fetch_3dep_lpc, workunit_meta
from .grid import grid_to_mesh
from .provenance import build_provenance, spacing_unit
from .solid import carve


def fetch_grid(bbox_m, *, crs_epsg, cache_stem, spacing_m, source="dem",
               refresh=False, log=print):
    """The 3DEP TerrainGrid over ``bbox_m`` (CRS units), fetched or read from
    the cache under ``cache_stem``: the 1 m DEM (``source="dem"``) or the
    lidar point cloud's bare earth (``"lpc"``, its WGS84 discovery bbox
    derived from ``bbox_m`` via pyproj). Elevations are NAVD88 metres."""
    cache_stem = str(cache_stem)
    if source == "lpc":
        try:
            from pyproj import Transformer
        except ImportError as e:
            raise RuntimeError(
                "pyproj is required for the lpc terrain source — "
                'pip install "bimforge[terrain]"') from e
        to_ll = Transformer.from_crs(crs_epsg, 4326, always_xy=True)
        lo1, la1 = to_ll.transform(bbox_m[0], bbox_m[1])
        lo2, la2 = to_ll.transform(bbox_m[2], bbox_m[3])
        wgs = (f"{min(lo1, lo2)},{min(la1, la2)},"
               f"{max(lo1, lo2)},{max(la1, la2)}")
        return fetch_3dep_lpc(bbox_m, spacing_m, crs_epsg, wgs, cache_stem,
                              refresh=refresh, log=log)
    return fetch_3dep_dem(bbox_m, spacing_m, crs_epsg,
                          Path(cache_stem + "-3DEP-DEM.tif"),
                          refresh=refresh, log=log)


def attach_terrain(model, bbox_m, *, crs_epsg, cache_stem, unit_scale,
                   spacing_m=3.0, source="dem", vshift_m=None,
                   vshift_lookup=None, lonlat=None, cuts=(), refresh=False,
                   plan_scale=None, grid=None, vshift_source=None,
                   log=print):
    """Fetch USGS 3DEP existing ground over ``bbox_m`` and attach it to
    ``model`` as site-context terrain; returns the added Element.

    ``bbox_m`` is the ``(xmin, ymin, xmax, ymax)`` footprint in the project
    CRS ``crs_epsg``, and ``spacing_m`` the cell size, both in that CRS's own
    linear unit (US survey feet for a ftUS CRS; the names are historical);
    elevations come back in metres. ``unit_scale`` takes metres to model
    units (for z); ``plan_scale`` takes CRS units to model units (for n and
    e), None meaning ``unit_scale`` (a metric CRS). ``source`` is ``"dem"`` (1 m raster) or
    ``"lpc"`` (lidar bare-earth; the WGS84 discovery bbox is derived from
    ``bbox_m`` via pyproj). ``cache_stem`` is the path stem every cache
    artifact (DEM TIFF, LPC grid npz, vshift/workunit JSON) hangs off, so
    rebuilds are offline and deterministic; ``refresh=True`` refetches each.

    Vertical datum — exactly one of:

    - ``vshift_m`` — an explicit NAVD88 -> project-datum shift in metres;
    - ``vshift_lookup`` — a ``(lat, lon, fallback)`` tuple resolved through
      :func:`~bimforge.terrain.datum.ncat_vertshift` (NOAA NCAT authority,
      named fallback, nothing silent).

    ``lonlat`` — optional ``(lon, lat)`` for the 3DEP work-unit vintage
    lookup. When omitted it derives from ``vshift_lookup``; with neither,
    the vintage is skipped with a logged note and the build continues
    (matching ``workunit_meta``'s own degradation posture).

    ``cuts`` are ``(base, top_base, z0, z1)`` excavation frustums in model
    units (see :func:`~bimforge.terrain.solid.frustum`); when supplied the
    open surface is carved into a watertight solid by
    :func:`~bimforge.terrain.solid.carve` (which closes the surface itself —
    and degrades, logged, to the open surface if the mesh-boolean deps are
    missing). The element name gains "(excavation carved)" only when the
    carve actually produced the closed solid.

    ``grid`` is an already-fetched TerrainGrid over ``bbox_m``, which is then
    not fetched again; ``vshift_source`` is written into the provenance as
    ``VerticalShiftSource``.
    """
    cache_stem = str(cache_stem)
    if grid is None:
        grid = fetch_grid(bbox_m, crs_epsg=crs_epsg, cache_stem=cache_stem,
                          spacing_m=spacing_m, source=source,
                          refresh=refresh, log=log)

    if vshift_m is not None:
        shift = float(vshift_m)
    elif vshift_lookup is not None:
        lat, lon, fallback = vshift_lookup
        shift = ncat_vertshift(lat, lon,
                               Path(cache_stem + "-3DEP-vshift.json"),
                               fallback=fallback, refresh=refresh, log=log)
    else:
        raise ValueError(
            "attach_terrain needs a vertical datum: pass vshift_m (explicit "
            "metres) or vshift_lookup=(lat, lon, fallback) for NCAT")

    if lonlat is None and vshift_lookup is not None:
        lonlat = (vshift_lookup[1], vshift_lookup[0])
    if lonlat is not None:
        wu = workunit_meta(lonlat[0], lonlat[1],
                           Path(cache_stem + "-3DEP-workunit.json"),
                           refresh=refresh, log=log)
    else:
        wu = {}
        log("  terrain: no lon/lat available; work-unit vintage skipped")

    verts, tris = grid_to_mesh(grid, unit_scale, shift, plan_scale)
    unit = spacing_unit(crs_epsg) or "CRS units"
    log(f"  terrain: {len(verts)} {source.upper()} verts @ {spacing_m:g} {unit}, "
        f"shift -{shift:.3f} m")

    closed = False
    if cuts:
        # carve builds the watertight solid internally (close_surface +
        # boolean); no separate close here. Above-terrain cuts no-op — the
        # existing-vs-future-ground classification is proven by geometry.
        verts, tris, closed, _removed = carve(verts, tris, list(cuts),
                                              log=log)

    info = dict(grid.info)
    info.setdefault("crs_epsg", grid.crs_epsg)
    prov = build_provenance(source, info, wu, shift, spacing_m, closed,
                            shift_source=vshift_source)

    name = ("Existing ground - USGS 3DEP %s%s"
            % ("lidar" if source == "lpc" else "DEM",
               " (excavation carved)" if closed else ""))
    return add_terrain(model, name, verts, tris, prov, closed)


def add_terrain(model, name, verts, tris, provenance, closed=False):
    """Add the TERRAIN reference element: IfcGeographicElement/TERRAIN, no
    pay code, no quantities, its mesh carrying `provenance`. An open sheet
    of ground is declared a surface (Element.body), so the solid-body check
    does not read its rim as a broken solid; a carved one is a solid."""
    from bimforge.author.model import Element
    return model.add(Element(
        name, ifc_class="IfcGeographicElement", predefined_type="TERRAIN",
        classifications=[], quantities={},
        body="solid" if closed else "surface",
        geometry={"kind": "mesh", "verts": verts, "tris": tris,
                  "units": "ft", "provenance": provenance}))


def is_terrain(el) -> bool:
    """The element is the model's existing ground: IfcGeographicElement
    TERRAIN."""
    return (el.ifc_class == "IfcGeographicElement"
            and (el.predefined_type or "").upper() == "TERRAIN")


def to_model_frame(el, ctx) -> None:
    """Move a TERRAIN element's mesh, (northing, easting, elevation) in survey
    feet as `attach_terrain` and `add_terrain` mesh it, into the model frame
    every other body is in (x east, y north, local to the project base)."""
    from bimforge.author.sweep import to_model
    d = el.geometry
    d["verts"] = [to_model(ctx, n, e, z) for n, e, z in d["verts"]]
