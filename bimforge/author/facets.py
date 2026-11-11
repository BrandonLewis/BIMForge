"""Coplanar facet merging for the IFC brep writer.

A triangulated body (a tapered prism, a loft, a terrain, an alignment sweep
written as its mesh under IFC4) used to reach the IFC as one IfcFace per
triangle. Every importer then shows every triangle edge: FreeCAD selects a
box's top as two triangles, Revit's DirectShape draws the diagonal, and a
30-facet end block is 30 faces where a drafter sees 11. The STEP emitter has
merged coplanar facets since the hand-off work (OCCT's UnifySameDomain); this
is the same operation for IFC, in pure Python, on the triangles the emitter
already holds.

`merge_coplanar_facets` groups the triangles by their plane, unions each
group's triangles in that plane (shapely), and returns one planar polygon per
connected region, with its holes. What it guarantees:

* **the surface is unchanged** -- a merged face covers exactly the triangles
  it replaces, so the enclosed volume is the mesh's to the last bit;
* **the shell stays closed** -- every vertex of the group's triangles that
  lies on a merged face's boundary is kept on it, so a neighbouring face that
  ends at that vertex still shares an edge with this one (no T-junction
  opened by the merge);
* **orientation is kept** -- the outer loop runs counter-clockwise about the
  facets' outward normal and a hole loop clockwise, the IfcFaceOuterBound /
  IfcFaceBound convention;
* **a triangle that merges with nothing is written as it was**.

Curved surfaces stay faceted: the model authors them as facets, and only
exactly coplanar facets (to `PLANE_TOL`) merge.
"""
from __future__ import annotations

import math

#: Two facets are coplanar when their unit normals agree to this and their
#: plane offsets (along the normal) to `PLANE_TOL` of the model unit. The
#: emitter works in metres, so 1e-7 is a tenth of a micron: only facets the
#: author laid in one plane merge, never a gently curved surface.
NORMAL_DECIMALS = 7
PLANE_TOL = 1e-7
#: Below this (unit^2) a polygon the union leaves behind is a sliver, not a
#: face: dropped.
AREA_EPS = 1e-14
#: A merged polygon whose vertices come closer than this (unit) to an edge
#: they are not on (shapely `minimum_clearance`: a near self-touch, a notch
#: left by a boolean sliver) is not written: a CAD kernel's tolerance closes
#: the gap and mis-triangulates the face, opening the shell and changing its
#: volume. Its plane group is written as the triangles it came from, which
#: the kernel sews. 1 mm in the emitter's metres.
MIN_CLEARANCE = 1e-3


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _unit(v):
    n = math.sqrt(_dot(v, v))
    return (v[0] / n, v[1] / n, v[2] / n) if n > 0 else None


def facet_plane(tri):
    """(unit normal, offset) of a triangle's plane, or None when degenerate."""
    n = _unit(_cross(_sub(tri[1], tri[0]), _sub(tri[2], tri[0])))
    if n is None:
        return None
    return n, _dot(n, tri[0])


def _plane_key(n, d):
    key_n = tuple(round(c, NORMAL_DECIMALS) + 0.0 for c in n)   # -0.0 -> 0.0
    return key_n, round(d / PLANE_TOL)


def _frame(n):
    """Orthonormal (u, v) in the plane with u x v = n, chosen from the
    world axis least aligned with n so the frame is stable."""
    axis = min(((abs(n[0]), (1.0, 0.0, 0.0)), (abs(n[1]), (0.0, 1.0, 0.0)),
                (abs(n[2]), (0.0, 0.0, 1.0))), key=lambda t: t[0])[1]
    u = _unit(_cross(axis, n))
    v = _unit(_cross(n, u))
    return u, v


def _insert_on_edges(ring, pts, eps):
    """`ring` (2D, open) with every point of `pts` that lies strictly inside
    one of its edges inserted there, in order along the edge. A merged
    polygon's boundary may run straight through a vertex a neighbouring
    facet ends at; keeping that vertex keeps the shell closed."""
    out = []
    for p, q in zip(ring, ring[1:] + ring[:1]):
        out.append(p)
        dx, dy = q[0] - p[0], q[1] - p[1]
        L2 = dx * dx + dy * dy
        if L2 <= eps * eps:
            continue
        L = math.sqrt(L2)
        mids = []
        for c in pts:
            t = ((c[0] - p[0]) * dx + (c[1] - p[1]) * dy) / L2
            if not (eps / L < t < 1.0 - eps / L):
                continue
            cross = ((c[0] - p[0]) * dy - (c[1] - p[1]) * dx) / L
            if abs(cross) <= eps:
                mids.append((t, c))
        seen = set()
        for _t, c in sorted(mids):
            if c not in seen:
                seen.add(c)
                out.append(c)
    return out


def _dedupe_ring(ring):
    """Drop consecutive repeats (and the closing repeat of the first point)."""
    out = []
    for p in ring:
        if not out or p != out[-1]:
            out.append(p)
    while len(out) > 1 and out[-1] == out[0]:
        out.pop()
    return out


def merge_coplanar_facets(triangles) -> list:
    """[(outer, holes), ...] planar faces covering exactly `triangles`.

    `triangles` are ((x, y, z), ...) triples wound with the outward normal.
    Each returned face is an outer ring (list of 3D points, counter-clockwise
    about the outward normal, not closed) and a list of hole rings (clockwise).
    Faces are returned in first-triangle order, so the output is as
    deterministic as the input.
    """
    groups: dict = {}
    order: list = []
    for tri in triangles:
        pl = facet_plane(tri)
        if pl is None:
            continue                           # zero-area facet: not a face
        n, d = pl
        key = _plane_key(n, d)
        g = groups.get(key)
        if g is None:
            g = groups[key] = {"n": n, "d": d, "tris": []}
            order.append(key)
        g["tris"].append(tri)
    faces = []
    for key in order:
        g = groups[key]
        if len(g["tris"]) == 1:
            faces.append((list(g["tris"][0]), []))
            continue
        faces.extend(_merge_group(g["n"], g["d"], g["tris"]))
    return faces


def _hole_touches(poly) -> bool:
    """Whether an inner ring of `poly` comes within MIN_CLEARANCE of its
    outer ring or of another inner ring."""
    rings = list(poly.interiors)
    for i, ring in enumerate(rings):
        if ring.distance(poly.exterior) < MIN_CLEARANCE:
            return True
        if any(ring.distance(other) < MIN_CLEARANCE for other in rings[i + 1:]):
            return True
    return False


def _merge_group(n, d, tris) -> list:
    from shapely.geometry import MultiPolygon, Polygon
    from shapely.geometry.polygon import orient
    from shapely.ops import unary_union

    u, v = _frame(n)
    to2d: dict = {}          # 2D point -> original 3D point (exact coords)

    def proj(p):
        q = (_dot(p, u), _dot(p, v))
        to2d.setdefault(q, p)
        return q

    polys = []
    for tri in tris:
        poly = Polygon([proj(p) for p in tri])
        if poly.area > AREA_EPS:
            polys.append(poly)
    if not polys:
        return []
    merged = unary_union(polys)
    if isinstance(merged, Polygon):
        parts = [merged]
    elif isinstance(merged, MultiPolygon):
        parts = list(merged.geoms)
    else:                                      # a collection: keep its polygons
        parts = [geom for geom in getattr(merged, "geoms", ())
                 if isinstance(geom, Polygon)]
    if len(parts) == len(polys) and all(
            len(p.exterior.coords) == 4 and not p.interiors for p in parts):
        # nothing touched anything: the triangles, as they were
        return [(list(t), []) for t in tris]
    if any(p.area > AREA_EPS and p.minimum_clearance < MIN_CLEARANCE
           for p in parts):
        # a near self-touch a kernel would close: the triangles are safer
        return [(list(t), []) for t in tris]
    if any(p.area > AREA_EPS and _hole_touches(p) for p in parts):
        # a hole meeting the outer bound (or another hole) at a vertex: valid
        # to OGC, but viewers drop the face (#42), and minimum_clearance
        # misses it, the shared vertex being on the edges it is near
        return [(list(t), []) for t in tris]

    # the group's own vertices, for T-junction closure on the merged boundary
    own = list(to2d)
    origin = (n[0] * d, n[1] * d, n[2] * d)

    def lift(q):
        p = to2d.get(q)
        if p is None:                          # a point the union minted
            p = (origin[0] + q[0] * u[0] + q[1] * v[0],
                 origin[1] + q[0] * u[1] + q[1] * v[1],
                 origin[2] + q[0] * u[2] + q[1] * v[2])
            to2d[q] = p
        return p

    def ring3d(coords, ccw: bool):
        ring = _dedupe_ring([(float(x), float(y)) for x, y in coords])
        if len(ring) < 3:
            return None
        ring = _insert_on_edges(ring, own, PLANE_TOL)
        # shapely's orient() fixed the sense; a numerically flat ring is
        # dropped by the area test on its polygon above
        return [lift(q) for q in ring]

    out = []
    # sort by the first vertex so the output does not depend on GEOS's
    # internal ordering of disjoint pieces
    for poly in sorted((p for p in parts if p.area > AREA_EPS),
                       key=lambda p: tuple(p.exterior.coords[0])):
        poly = orient(poly, 1.0)              # exterior CCW, holes CW
        outer = ring3d(poly.exterior.coords, True)
        if outer is None:
            continue
        holes = []
        for ring in poly.interiors:
            h = ring3d(ring.coords, False)
            if h is not None:
                holes.append(h)
        out.append((outer, holes))
    return out


def merged_face_count(triangles) -> int:
    """How many faces `merge_coplanar_facets` makes of these triangles."""
    return len(merge_coplanar_facets(triangles))
