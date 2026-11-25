"""Plan extent of one body_solids() dict: the true (x0, y0, x1, y1) a body
covers in its element's frame, in the dict's own units.

`gate._solid_points` yields representative points (one per feature), enough
to localize an element but not to bound it: a tube gives only its origin, a
box its centre. A caller that needs the footprint (the terrain spec's
model_footprint) uses `plan_extent` instead. Each kind reads the same keys
`emit_ifc.solids_for` builds from:

    prism/fill  base ring (holes lie inside it)
    mesh        verts
    swept_disk  directrix verts +/- radius (a fillet arc's bulge past its
                three index points is not sampled; it is under a bar radius
                for the shipped bars)
    ribbon      the draped strip's own vertices (ribbon_mesh), so the width
                is counted
    box         each (cx, cy, _, dx, dy, _) +/- half size
    rod         each centre +/- radius across the axis, +/- length/2 along it
    tube        origin (x0, y0) runs `length` along "x" or "y" (+/- r_outer
                across); any other axis is a vertical column at (x0, y0)
    arc_band    cx +/- width/2 in x; y from the arc's own points
    gusset      each placement's cx +/- thickness/2 in x; ring u is y
"""
from __future__ import annotations

import math


def _of(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def plan_extent(d):
    """(x0, y0, x1, y1) in the dict's own units, or None for a body with no
    plan (kind "none", an empty one)."""
    kind = d.get("kind")
    if kind in ("prism", "fill"):
        return _of(d.get("base", ()))
    if kind == "mesh":
        return _of(d.get("verts", ()))
    if kind == "swept_disk":
        e = _of(d.get("verts", ()))
        r = d.get("radius", 0.0)
        return None if e is None else (e[0] - r, e[1] - r, e[2] + r, e[3] + r)
    if kind == "ribbon":
        from bimforge.author.ribbon import ribbon_mesh
        pts = list(d.get("points", ()))
        if len(pts) < 2:
            return _of(pts)
        return _of(ribbon_mesh(pts, d["width"])[0])
    if kind == "box":
        return _of([(b[0] + sx * b[3] / 2.0, b[1] + sy * b[4] / 2.0)
                    for b in d.get("boxes", ()) for sx in (-1, 1)
                    for sy in (-1, 1)])
    if kind == "rod":
        r, half = d["radius"], d["length"] / 2.0
        ax = d.get("axis", "z")
        hx = half if ax == "x" else r
        hy = half if ax == "y" else r
        return _of([(c[0] + sx * hx, c[1] + sy * hy)
                    for c in d.get("centres", ()) for sx in (-1, 1)
                    for sy in (-1, 1)])
    if kind == "tube":
        x0, y0 = d.get("x0", 0.0), d.get("y0", 0.0)
        r, n = d["r_outer"], d["length"]
        ax = d.get("axis", "x")
        if ax == "x":
            return (x0, y0 - r, x0 + n, y0 + r)
        if ax == "y":
            return (x0 - r, y0, x0 + r, y0 + n)
        return (x0 - r, y0 - r, x0 + r, y0 + r)      # vertical column
    if kind == "arc_band":
        start = math.radians(d.get("start_deg", 180.0))
        wrap, nseg = math.radians(d["wrap_deg"]), d["segments"]
        ys = [r * math.cos(start + wrap * i / nseg)
              for r in (d["r_inner"], d["r_outer"]) for i in range(nseg + 1)]
        half = d["width"] / 2.0
        return (d["cx"] - half, min(ys), d["cx"] + half, max(ys))
    if kind == "gusset":
        half = d["thickness"] / 2.0
        pts = [(cx + sx * half, u) for cx, ring in d.get("placements", ())
               for u, _v in ring for sx in (-1, 1)]
        return _of(pts)
    # An unknown kind: fall back to the representative points, which
    # localize it but may under-bound it.
    from bimforge.author.gate import _solid_points
    return _of(list(_solid_points(d)))
