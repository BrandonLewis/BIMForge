"""Closed-region detection: polygonize the extracted linework into faces.

Agents should pick regions, not trace edges: a plan-view footprint (the
sheet-20 RSP polygons are the driving case) is drawn as CAD edges that meet
at corners, get crossed by centerlines and match lines, and terminate in
T-junctions on other linework. This module snaps segment endpoints together
within a tolerance, nodes every crossing/T-junction (shapely
``unary_union``), and polygonizes the planar arrangement into faces with
areas — ``est-bim vectors --regions`` emits them as closed polylines on
``V-REGION-<class>`` layers sorted by area, so a takeoff trace can reference
whole regions instead of re-tracing boundaries.

Because the result is the planar subdivision, an outline crossed by interior
lines arrives as several adjacent faces — pick them all and sum (the region
JSON carries the areas). ``area_pt2`` is the NET face area (island holes
subtracted); ``points`` is the exterior ring. Micro-paths are the caller's
job (``extract_sheet(min_path_pt=...)`` already drops hatch noise);
``min_area_pt2`` drops sliver faces.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from bimforge.bim.plansheet.vectors import Segment, class_name

__all__ = ["Region", "find_regions", "DEFAULT_ENDPOINT_TOL_PT",
           "DEFAULT_MIN_AREA_PT2"]

DEFAULT_ENDPOINT_TOL_PT = 0.75
DEFAULT_MIN_AREA_PT2 = 25.0


@dataclass
class Region:
    """One closed face in unrotated page points."""

    points: list[tuple[float, float]]     # exterior ring, first != last
    area_pt2: float                       # net area (holes subtracted)
    feature_class: str                    # dominant dash class of the boundary

    @property
    def layer(self) -> str:
        return f"V-REGION-{self.feature_class}"

    def centroid(self) -> tuple[float, float]:
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return (sum(xs) / len(xs), sum(ys) / len(ys))


def _cluster_nodes(points: list[tuple[float, float]], tol: float):
    """Grid-hash endpoint clustering: index -> node id, node id -> position."""
    cell = tol if tol > 0 else 1e-9
    grid: dict[tuple[int, int], list[int]] = {}
    node_pos: list[tuple[float, float]] = []
    node_of: list[int] = []
    for x, y in points:
        cx, cy = int(math.floor(x / cell)), int(math.floor(y / cell))
        found = None
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for nid in grid.get((gx, gy), ()):
                    px, py = node_pos[nid]
                    if math.hypot(px - x, py - y) <= tol:
                        found = nid
                        break
                if found is not None:
                    break
            if found is not None:
                break
        if found is None:
            found = len(node_pos)
            node_pos.append((x, y))
            grid.setdefault((cx, cy), []).append(found)
        node_of.append(found)
    return node_of, node_pos


def find_regions(
    segments: list[Segment],
    bbox: tuple[float, float, float, float] | None = None,
    *,
    tol_pt: float = DEFAULT_ENDPOINT_TOL_PT,
    min_area_pt2: float = DEFAULT_MIN_AREA_PT2,
    classes: dict[str, str] | None = None,
    include_curves: bool = False,
) -> list[Region]:
    """Polygonize segments into closed faces; sorted by area, largest first.

    ``include_curves=False`` (the default) drops bezier-derived chords
    before polygonizing: hatch symbols (RSP stone blobs, concrete hatch)
    are drawn as closed curves that touch the real boundaries and would
    shatter the arrangement into hundreds of inter-hatch slivers. CAD
    footprint boundaries are straight polylines; genuinely curved
    boundaries can opt back in.
    """
    from shapely.geometry import LineString, Point
    from shapely.ops import polygonize, unary_union
    from shapely.strtree import STRtree

    segs = [s for s in segments if (bbox is None or s.in_bbox(bbox))
            and s.length > 0.0 and (include_curves or not s.curved)]
    if not segs:
        return []

    # snap endpoints within tol so hairline gaps at corners still close
    endpoints: list[tuple[float, float]] = []
    for s in segs:
        endpoints.append((s.x1, s.y1))
        endpoints.append((s.x2, s.y2))
    node_of, node_pos = _cluster_nodes(endpoints, tol_pt)

    lines = []
    line_segs: list[Segment] = []
    for i, s in enumerate(segs):
        a = node_pos[node_of[2 * i]]
        b = node_pos[node_of[2 * i + 1]]
        if a == b:
            continue
        lines.append(LineString([a, b]))
        line_segs.append(s)
    if not lines:
        return []

    # unary_union nodes every crossing and T-junction; polygonize returns
    # the planar arrangement's faces (holes handled)
    faces = list(polygonize(unary_union(lines)))
    tree = STRtree(lines)

    out: list[Region] = []
    for poly in faces:
        if poly.area < min_area_pt2:
            continue
        coords = [(float(x), float(y)) for x, y in poly.exterior.coords[:-1]]
        # dominant dash class among the boundary's source segments
        counts: dict[str, int] = {}
        for (ax, ay), (bx, by) in zip(coords, coords[1:] + coords[:1]):
            mid = Point((ax + bx) / 2.0, (ay + by) / 2.0)
            idx = tree.nearest(mid)
            if idx is None:
                continue
            idx = int(idx)
            if lines[idx].distance(mid) <= max(tol_pt, 1.0):
                cn = class_name(line_segs[idx], classes)
                counts[cn] = counts.get(cn, 0) + 1
        feature = max(counts, key=lambda k: counts[k]) if counts else "SOLID"
        out.append(Region(points=coords, area_pt2=float(poly.area),
                          feature_class=feature))
    out.sort(key=lambda r: -r.area_pt2)
    return out
