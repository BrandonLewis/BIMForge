"""IFC -> plan-view takeoff DXF (the reverse geometry route).

Flattens any IFC's elements — ours or a foreign Tekla/Revit export — into
the takeoff-mapped-DXF shape the rest of the pipeline consumes (measure /
dxf2bim conventions: closed LWPOLYLINEs in world coordinates, R2018,
$INSUNITS). Layers are named IFCCLASS[-PREDEFINEDTYPE] so an office
layer_map.yaml can be written against a small predictable set. Georeferenced
IFCs (IfcMapConversion) land in real CRS coordinates; un-georeferenced ones
fall back to local model feet, flagged in the result and sidecar.

Design: docs/superpowers/specs/2026-08-11-ifc2dxf-design.md
Requires the `bim` extra (ifcopenshell, shapely, ezdxf, pyproj).
"""
from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field
from pathlib import Path

from bimforge.bim.georef import read_map_conversion

M_TO_FT = 1.0 / 0.3048
_LEGACY_COORD_LIMIT_M = 1e6  # same pre-0.1.11 broken-georef guard as kml.py
_AREA_EPS_M2 = 1e-9          # degenerate projected-triangle cutoff


def layer_name(prod) -> str:
    """DXF layer for an element: IFCCLASS, plus -PREDEFINEDTYPE when it says
    something (NOTDEFINED/USERDEFINED are noise, not types)."""
    cls = prod.is_a().upper()
    ptype = str(getattr(prod, "PredefinedType", "") or "").upper()
    if ptype and ptype not in ("NOTDEFINED", "USERDEFINED"):
        return f"{cls}-{ptype}"
    return cls


def footprint(pts, faces):
    """XY footprint of a triangulated element.

    Projects every triangle to the XY plane, drops degenerates (vertical
    faces), unions the rest. Returns a shapely Polygon/MultiPolygon, or None
    when nothing has plan-view area. `pts` are (x, y, z) tuples; `faces` a
    flat triangle-index list (ifcopenshell.geom layout).
    """
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    tris = []
    for f in range(0, len(faces), 3):
        tri = [pts[faces[f]][:2], pts[faces[f + 1]][:2], pts[faces[f + 2]][:2]]
        p = Polygon(tri)
        if p.area > _AREA_EPS_M2:
            tris.append(p)
    if not tris:
        return None
    merged = unary_union(tris).buffer(0)
    if merged.is_empty or merged.area <= _AREA_EPS_M2:
        return None
    if merged.geom_type == "GeometryCollection":
        polys = [g for g in merged.geoms if g.geom_type == "Polygon"]
        if not polys:
            return None
        merged = unary_union(polys)
    return merged


def _join_chains(a, b):
    """Concatenate two ordered vertex-index chains if they share an endpoint
    (in either orientation), else return None."""
    if a[-1] == b[0]:
        return a + b[1:]
    if a[-1] == b[-1]:
        return a + b[-2::-1]
    if a[0] == b[-1]:
        return b + a[1:]
    if a[0] == b[0]:
        return a[::-1] + b[1:]
    return None


def _chains_from_edges(edges):
    """Group a flat ``[a, b, a, b, ...]`` edge-index list into ordered
    vertex-index chains. Segments that share an endpoint merge into one path --
    even when the bridging edge arrives out of order -- so a single centreline
    comes back as one chain and disjoint pieces (e.g. separate station ticks)
    stay separate. Turns an IfcAnnotation's tessellated curve set into as few
    open polylines as possible.
    """
    chains: list[list[int]] = []
    for i in range(0, len(edges), 2):
        a, b = edges[i], edges[i + 1]
        for ch in chains:
            if ch[-1] == a:
                ch.append(b)
            elif ch[-1] == b:
                ch.append(a)
            elif ch[0] == a:
                ch.insert(0, b)
            elif ch[0] == b:
                ch.insert(0, a)
            else:
                continue
            break
        else:
            chains.append([a, b])
    # A later edge can bridge two chains that were built earlier out of order;
    # join any chains that now share an endpoint until none remain adjacent.
    i = 0
    while i < len(chains):
        for j in range(i + 1, len(chains)):
            joined = _join_chains(chains[i], chains[j])
            if joined is not None:
                chains[i] = joined
                del chains[j]
                break
        else:
            i += 1
    return chains


def _crs_unit(epsg: int) -> tuple[str, int]:
    """('ft'|'m', ezdxf $INSUNITS code) for the CRS's axis unit.

    Raises ValueError for a non-projected (geographic) CRS — lon/lat degrees
    must not be silently labeled as metres."""
    from ezdxf import units
    from pyproj import CRS

    crs = CRS.from_epsg(epsg)
    name = crs.axis_info[0].unit_name.lower()
    if not crs.is_projected:
        raise ValueError(
            f"EPSG:{epsg} is a geographic CRS (axis unit '{name}') — "
            "ifc2dxf needs a projected CRS")
    if "foot" in name:
        return "ft", units.FT
    return "m", units.M


@dataclass
class Ifc2DxfResult:
    """What `ifc_to_dxf` did; feeds the CLI summary and the QC sidecar."""
    out: str
    georef: dict
    elements: int = 0
    skipped: list = field(default_factory=list)   # {global_id, ifc_class, reason}
    entities: list = field(default_factory=list)  # per-element sidecar rows
    params: dict = field(default_factory=dict)    # include/exclude/simplify_ft as-passed


def _world_pts(shape):
    """Apply the per-shape placement matrix by hand — the kml.py idiom
    (local-coords geom settings + column-major 4x4, last column = T)."""
    verts = shape.geometry.verts
    mt = shape.transformation.matrix

    def world(i):
        x, y, z = verts[i * 3], verts[i * 3 + 1], verts[i * 3 + 2]
        return (
            mt[0] * x + mt[4] * y + mt[8] * z + mt[12],
            mt[1] * x + mt[5] * y + mt[9] * z + mt[13],
            mt[2] * x + mt[6] * y + mt[10] * z + mt[14],
        )

    return [world(i) for i in range(len(verts) // 3)]


def ifc_to_dxf(ifc_path, out_path=None, *, include=None, exclude=None,
               simplify_ft: float = 0.0) -> Ifc2DxfResult:
    """Flatten an IFC into a plan-view takeoff DXF.

    Georeferenced input -> DXF in CRS coordinates ($INSUNITS from the CRS
    unit); no MapConversion -> local model feet, flagged 'ungeoreferenced'.
    `include`/`exclude` are IFC class-name lists (is_a semantics: subtypes
    match; exclude wins). Raises ValueError when no element yields plan-view
    geometry, and for the legacy (<= 0.1.10) broken-georef coordinates.
    """
    import ezdxf
    from ezdxf import units
    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.util.unit as unit_util
    from shapely.ops import transform as shp_transform

    ifc_path = Path(ifc_path)
    if not ifc_path.is_file():
        raise OSError(f"no such IFC file: {ifc_path}")
    out = Path(out_path) if out_path else ifc_path.with_suffix(".plan.dxf")

    model = ifcopenshell.open(str(ifc_path))
    # ifcopenshell.geom returns raw verts/placement-matrix translations in the
    # file's *native* length unit (e.g. millimetres for a Revit export), not
    # auto-converted to SI metres — unlike our own dxf2bim-authored IFCs,
    # which always declare an SI metre length unit at write time (see
    # dxf2bim.py's explicit unit.assign_unit call) so their raw values are
    # already metres. A foreign IFC has no such guarantee, so every world
    # point is scaled to true metres here before any georef/footprint math.
    model_unit_scale = unit_util.calculate_unit_scale(model)
    # Absent vs invalid georef: only a truly ABSENT georeference (no
    # MapConversion and no ProjectedCRS at all) falls back to local feet.
    # A PRESENT but broken one (zero Scale, unparseable CRS name, geographic
    # CRS) must be a loud ValueError from read_map_conversion/_crs_unit —
    # never a silently ungeoreferenced local-feet file.
    if model.by_type("IfcMapConversion") or model.by_type("IfcProjectedCRS"):
        g = read_map_conversion(model)
        unit, insunits = _crs_unit(g.epsg)
        georef = {"status": "crs", "epsg": g.epsg, "unit": unit}
        # IFC4 MapConversion: CRS coordinate = base + NATIVE-unit model
        # coordinate * Scale (native = the file's own length unit). Our pts
        # are already normalized native -> metres by model_unit_scale, so the
        # factor on metre points divides that back out. Metre-authored files
        # (our own dxf2bim output) have model_unit_scale == 1 — unaffected.
        k = g.scale / model_unit_scale

        def to_out(x_m, y_m):
            return g.base_e + x_m * k, g.base_n + y_m * k

        def z_out(z_m):
            return g.height + z_m * k
    else:
        unit, insunits = "ft", units.FT
        georef = {"status": "ungeoreferenced", "unit": unit}

        def to_out(x_m, y_m):
            return x_m * M_TO_FT, y_m * M_TO_FT

        def z_out(z_m):
            return z_m * M_TO_FT

    import ifcopenshell.ifcopenshell_wrapper as ifc_wrapper
    settings = ifcopenshell.geom.settings()
    # Include curve geometry so IfcAnnotation (alignments, stationing, control
    # points, matchlines) tessellates to edges instead of raising -- solids are
    # unaffected (identical verts/faces to the default surfaces+solids setting).
    # ONE settings object drives every product: two coexisting settings share
    # native state in this ifcopenshell build, so a separate curve-settings is
    # not an option.
    settings.set("dimensionality", ifc_wrapper.CURVES_SURFACES_AND_SOLIDS)
    from bimforge.cad.stylepack import resolve_style_pack
    layer_styles = resolve_style_pack().styles.get("layers") or {}
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = insunits
    # $MEASUREMENT tracks the output unit (0 English, 1 metric) so CAD
    # consumers pick matching linetype/hatch-pattern defaults; measure.py's
    # constant 0 is right only because it always writes feet.
    doc.header["$MEASUREMENT"] = 1 if insunits == units.M else 0
    msp = doc.modelspace()

    res = Ifc2DxfResult(out=str(out), georef=georef,
                        params={"include": include, "exclude": exclude,
                                "simplify_ft": simplify_ft})
    tol = simplify_ft if unit == "ft" else simplify_ft * 0.3048

    def _ensure_layer(layer: str) -> None:
        if layer not in doc.layers:
            attrs = layer_styles.get(layer) or {}
            doc.layers.add(layer, **{k: attrs[k]
                                     for k in ("color", "linetype") if k in attrs})

    # IfcElement covers the built structures; IfcAnnotation covers survey/layout
    # curves (alignments, stationing, control points, matchlines). Annotations
    # are IfcProducts but NOT IfcElements, so walking IfcElement alone dropped
    # them silently AND left them uncounted (skipped is only appended inside the
    # loop) -- the summary then read "N elements, 0 skipped" while losing them.
    for prod in itertools.chain(model.by_type("IfcElement"),
                                model.by_type("IfcAnnotation")):
        if not prod.Representation or prod.is_a("IfcFeatureElement"):
            continue
        if include and not any(prod.is_a(c) for c in include):
            continue
        if exclude and any(prod.is_a(c) for c in exclude):
            continue
        try:
            shape = ifcopenshell.geom.create_shape(settings, prod)
        except Exception as exc:  # ifcopenshell raises plain RuntimeError
            res.skipped.append({"global_id": prod.GlobalId,
                                "ifc_class": prod.is_a(),
                                "reason": f"tessellation failed: {exc}"})
            continue
        pts = [(x * model_unit_scale, y * model_unit_scale, z * model_unit_scale)
               for x, y, z in _world_pts(shape)]
        if georef["status"] == "crs":
            for x, y, _z in pts:
                if abs(x) > _LEGACY_COORD_LIMIT_M or abs(y) > _LEGACY_COORD_LIMIT_M:
                    raise ValueError(
                        f"{prod.is_a()} '{prod.Name}' sits at |model coordinate| "
                        "> 1e6 m — this IFC was written with the broken "
                        "pre-0.1.11 georeferencing (base subtracted without "
                        "unit conversion); regenerate the IFC with "
                        "est-bim >= 0.1.11")
        layer = layer_name(prod)
        faces = shape.geometry.faces
        poly = footprint(pts, faces) if faces else None
        if poly is None:
            # A pure-curve product (typically IfcAnnotation) has edges, not
            # faces, so it has no plan-view AREA but real plan-view GEOMETRY --
            # emit it as open polylines rather than dropping it. Anything with
            # neither faces nor edges is genuinely empty and is counted as
            # skipped, so the summary stops under-reporting.
            edges = list(shape.geometry.edges)
            if not faces and edges:
                _ensure_layer(layer)
                chains = _chains_from_edges(edges)
                nverts = 0
                for chain in chains:
                    coords = [to_out(pts[i][0], pts[i][1]) for i in chain]
                    msp.add_lwpolyline(coords, close=False,
                                       dxfattribs={"layer": layer})
                    nverts += len(coords)
                zs = [z_out(z) for _x, _y, z in pts]
                ptype = str(getattr(prod, "PredefinedType", "") or "") or None
                res.entities.append({
                    "layer": layer,
                    "global_id": prod.GlobalId,
                    "name": prod.Name,
                    "ifc_class": prod.is_a(),
                    "predefined_type": ptype,
                    "area": 0.0,             # a curve has no plan-view area
                    "rings": len(chains),
                    "vertices": nverts,
                    "z_min": round(min(zs), 4),
                    "z_max": round(max(zs), 4),
                })
                res.elements += 1
                continue
            res.skipped.append({"global_id": prod.GlobalId,
                                "ifc_class": prod.is_a(),
                                "reason": "no plan-view area"})
            continue
        poly = shp_transform(lambda x, y: to_out(x, y), poly)
        if tol > 0:
            poly = poly.simplify(tol, preserve_topology=True)

        _ensure_layer(layer)
        polys = list(poly.geoms) if poly.geom_type == "MultiPolygon" else [poly]
        rings = nverts = 0
        for p in polys:
            for ring in (p.exterior, *p.interiors):
                coords = list(ring.coords)[:-1]  # drop shapely's closing dup
                msp.add_lwpolyline(coords, close=True,
                                   dxfattribs={"layer": layer})
                rings += 1
                nverts += len(coords)
        zs = [z_out(z) for _x, _y, z in pts]
        ptype = str(getattr(prod, "PredefinedType", "") or "") or None
        res.entities.append({
            "layer": layer,
            "global_id": prod.GlobalId,
            "name": prod.Name,
            "ifc_class": prod.is_a(),
            "predefined_type": ptype,
            "area": round(sum(p.area for p in polys), 4),
            "rings": rings,
            "vertices": nverts,
            "z_min": round(min(zs), 4),
            "z_max": round(max(zs), 4),
        })
        res.elements += 1

    if res.elements == 0:
        raise ValueError(
            f"no element produced plan-view geometry ({len(res.skipped)} skipped"
            + (": " + "; ".join(s["reason"] for s in res.skipped[:5]) if res.skipped else "")
            + ")")
    doc.saveas(str(out))
    return res


def write_sidecar(res: Ifc2DxfResult, ifc_path, path) -> None:
    """QC sidecar: georef status + per-element provenance. The z-ranges are
    where layer_map.yaml heights come from when this DXF goes back through
    dxf2bim."""
    payload = {
        "ifc": str(ifc_path),
        "out": res.out,
        "georef": res.georef,
        "elements": res.elements,
        "skipped": res.skipped,
        "entities": res.entities,
        "params": res.params,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
