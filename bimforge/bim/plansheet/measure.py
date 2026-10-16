"""Write the plan-sheet measurement outputs: vectors DXF and takeoff DXF.

``write_vectors_dxf`` dumps every extracted path in world feet, one layer per
style class (V-SOLID, V-DASH-<hash> …) — the tracing surface the agent/CAD
works against.

``measure_traces`` takes agent-proposed traces (world feet), snaps every
vertex to the extracted vectors, and writes the same takeoff-mapped DXF that
``est-bim dxf2bim`` consumes (closed traces → closed LWPOLYLINEs, open →
open, count layers → block INSERTs, which dxf2bim reads via ``e.dxf.insert``),
plus a provenance sidecar with per-vertex snap distances and unsnapped flags.

The DXF is written in the calibration's world units — feet — matching a
layer map with ``dxf_length_unit: ft``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import ezdxf
from ezdxf import units

from bimforge.bim.plansheet.calibrate import Calibration, Zone
from bimforge.bim.plansheet.snap import (
    DEFAULT_TOL_FT, WorldSegment, snap_polyline,
)
from bimforge.bim.plansheet.vectors import SheetVectors, style_layer

__all__ = ["MeasureError", "MeasureResult", "world_segments",
           "write_vectors_dxf", "measure_traces"]

#: block used for count-layer point traces (dxf2bim reads the INSERT point;
#: the block body is cosmetic)
_COUNT_BLOCK = "EST-PT"
_COUNT_BLOCK_RADIUS_FT = 0.5


class MeasureError(ValueError):
    """Bad traces / layer map / calibration combination."""


def world_segments(sv: SheetVectors, zone: Zone) -> list[WorldSegment]:
    """Extracted segments inside the zone, transformed to world feet."""
    out: list[WorldSegment] = []
    for s in sv.segments:
        if not s.in_bbox(zone.bbox_pt):
            continue
        out.append((zone.to_world(s.x1, s.y1), zone.to_world(s.x2, s.y2)))
    return out


def write_vectors_dxf(sv: SheetVectors, zone: Zone, out_path, *,
                      classes: dict | None = None,
                      regions: list | None = None) -> dict:
    """All extracted paths in the zone as a world-feet DXF, layered by style.

    ``classes`` (``vectors.load_classes``) maps dash signatures to feature
    classes: layers become ``V-<CLASS>`` instead of ``V-DASH-<hash>``.
    ``regions`` (``regions.find_regions``, page points) are added as closed
    LWPOLYLINEs on their ``V-REGION-<class>`` layers, largest first.
    """
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = units.FT
    doc.header["$MEASUREMENT"] = 0
    msp = doc.modelspace()
    layers: dict[str, int] = {}
    for s in sv.segments:
        if not s.in_bbox(zone.bbox_pt):
            continue
        layer = style_layer(s, classes)
        if layer not in doc.layers:
            doc.layers.add(layer)
        a = zone.to_world(s.x1, s.y1)
        b = zone.to_world(s.x2, s.y2)
        msp.add_line(a, b, dxfattribs={"layer": layer})
        layers[layer] = layers.get(layer, 0) + 1
    n_regions = 0
    region_rows: list[dict] = []
    for r in (regions or []):
        if r.layer not in doc.layers:
            doc.layers.add(r.layer)
        pts = [zone.to_world(x, y) for x, y in r.points]
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": r.layer})
        n_regions += 1
        area_ft2 = r.area_pt2 * zone.ft_per_pt ** 2
        cx, cy = r.centroid()
        wx, wy = zone.to_world(cx, cy)
        region_rows.append({
            "layer": r.layer,
            "area_ft2": round(area_ft2, 2),
            "area_sy": round(area_ft2 / 9.0, 2),
            "vertices": len(r.points),
            "centroid_ft": [round(wx, 2), round(wy, 2)],
            "points_ft": [[round(px, 4), round(py, 4)] for px, py in pts],
        })
    doc.saveas(str(out_path))
    return {"out": str(out_path), "segments": sum(layers.values()),
            "layers": layers, "regions": n_regions, "region_rows": region_rows}


@dataclass
class MeasureResult:
    out: str
    entities: int = 0
    vertices: int = 0
    unsnapped: int = 0
    max_snap_ft: float = 0.0
    sidecar: list[dict] = field(default_factory=list)


def _zone_for(calib: Calibration, trace: dict, layer: str, index: int) -> Zone:
    name = trace.get("zone")
    if name is None and len(calib.zones) > 1:
        raise MeasureError(
            f"trace {layer}[{index}]: calibration has {len(calib.zones)} zones — "
            'each trace must carry a "zone" key naming one of '
            f"{[z.name for z in calib.zones]}")
    return calib.zone(name)


def measure_traces(
    sv: SheetVectors,
    calib: Calibration,
    traces: dict,
    layer_map: dict,
    out_path,
    *,
    tol_ft: float = DEFAULT_TOL_FT,
) -> MeasureResult:
    """Snap and write agent traces as a takeoff-mapped DXF + provenance rows.

    ``traces``: ``{"layers": {"S-DECK": [{"closed": true, "points": [[x, y], …],
    "zone": "plan"?}, …]}}`` in world feet. Every trace layer must exist in the
    layer map's ``layers:`` section. Count layers take single-point traces and
    become block INSERTs. Raises ``MeasureError`` on structural problems;
    unsnapped vertices are *reported*, not raised (the CLI turns them into a
    nonzero exit unless --allow-unsnapped).
    """
    rules = {str(k).upper(): (v or {}) for k, v in (layer_map.get("layers") or {}).items()}
    trace_layers = traces.get("layers")
    if not isinstance(trace_layers, dict) or not trace_layers:
        raise MeasureError('traces.json must carry {"layers": {"<DXF layer>": [...]}}')

    unknown = [ly for ly in trace_layers if str(ly).upper() not in rules]
    if unknown:
        raise MeasureError(
            f"trace layers not in the layer map: {sorted(unknown)} "
            f"(layer map has: {sorted(rules)})")

    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = units.FT
    doc.header["$MEASUREMENT"] = 0
    blk = doc.blocks.new(_COUNT_BLOCK)
    blk.add_circle((0.0, 0.0), _COUNT_BLOCK_RADIUS_FT)
    blk.add_line((-_COUNT_BLOCK_RADIUS_FT, 0.0), (_COUNT_BLOCK_RADIUS_FT, 0.0))
    blk.add_line((0.0, -_COUNT_BLOCK_RADIUS_FT), (0.0, _COUNT_BLOCK_RADIUS_FT))
    msp = doc.modelspace()

    seg_cache: dict[str, list[WorldSegment]] = {}
    res = MeasureResult(out=str(out_path))

    for layer, entries in trace_layers.items():
        if layer not in doc.layers:
            doc.layers.add(layer)
        rule = rules[str(layer).upper()]
        kind = rule.get("feature", "area")
        for i, trace in enumerate(entries or []):
            points = trace.get("points") or []
            if kind == "count":
                if len(points) != 1:
                    raise MeasureError(
                        f"trace {layer}[{i}]: count layers take exactly one point "
                        f"per trace, got {len(points)}")
            elif len(points) < 2:
                raise MeasureError(
                    f"trace {layer}[{i}]: need at least 2 points, got {len(points)}")
            zone = _zone_for(calib, trace, layer, i)
            if zone.name not in seg_cache:
                seg_cache[zone.name] = world_segments(sv, zone)
            snaps = snap_polyline([(p[0], p[1]) for p in points],
                                  seg_cache[zone.name], tol_ft)
            snapped_pts = [s.point for s in snaps]
            closed = bool(trace.get("closed"))
            if kind == "count":
                msp.add_blockref(_COUNT_BLOCK, snapped_pts[0],
                                 dxfattribs={"layer": layer})
            else:
                msp.add_lwpolyline(snapped_pts, close=closed,
                                   dxfattribs={"layer": layer})
            n_uns = sum(1 for s in snaps if not s.snapped)
            res.entities += 1
            res.vertices += len(snaps)
            res.unsnapped += n_uns
            res.max_snap_ft = max(
                [res.max_snap_ft] + [s.distance for s in snaps if s.snapped])
            res.sidecar.append({
                "layer": layer,
                "index": i,
                "zone": zone.name,
                "feature": kind,
                "closed": closed,
                "points": [[round(x, 4), round(y, 4)] for x, y in snapped_pts],
                "snap_dist_ft": [round(s.distance, 4) for s in snaps],
                "unsnapped": [not s.snapped for s in snaps],
            })

    doc.saveas(str(out_path))
    return res


def write_sidecar(res: MeasureResult, calib: Calibration, path, *,
                  pdf: str = "", tol_ft: float = DEFAULT_TOL_FT) -> None:
    """Provenance sidecar: per entity, per-vertex snap distances + flags."""
    data = {
        "pdf": pdf,
        "sheet": calib.sheet,
        "page_index": calib.page_index,
        "tolerance_ft": tol_ft,
        "zones": {z.name: {"ft_per_pt": z.ft_per_pt, "method": z.method,
                           "residual_ft": z.residual_ft, "evidence": z.evidence}
                  for z in calib.zones},
        "entities": res.sidecar,
        "unsnapped_vertices": res.unsnapped,
        "max_snap_ft": round(res.max_snap_ft, 4),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
