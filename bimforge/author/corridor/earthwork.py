"""Cut and fill between two corridor sections (roadmap P.6).

The strip between two stations' earthwork lines is cut into triangles, two
per quad. Each triangle is split where the ground crosses the design line,
with depth interpolated linearly along its edges. Each piece becomes a
vertical triangular Prismatoid between the design line and the ground: cut
where the ground is above, fill where it is below. Every face is planar, so
the mesh volume is exact for the surfaces it carries (the private trail
family's lesson: a warped quad top is not a plane, and the STEP true-volume
check then disagrees by several percent).

The ground is read at each design vertex's own plan position, so every
column is vertical, and a wall side (a level line out to the wall's offset)
ends on a vertical face there. An earthwork line repeats points where a
hinge sits on the ground or a wall stands at the hinge; the triangles those
make have no plan area and are dropped, as are pieces with no depth.
"""
from __future__ import annotations

from bimforge.author.primitives import Prismatoid, _outward_tris, _signed_volume
from bimforge.author.sweep import to_model

LAYER = "C-ROAD"
IFC = {"cut": "IfcEarthworksCut", "fill": "IfcEarthworksFill"}
#: plan area (sf) and depth (ft) below which a piece is no solid
_TINY = 1e-6
#: decimal places the columns' corners are welded at when merged, feet
_WELD = 7


def _signed_area(pts: list) -> float:
    x0, y0 = pts[0][0], pts[0][1]
    return 0.5 * sum((p[0] - x0) * (q[1] - y0) - (q[0] - x0) * (p[1] - y0)
                     for p, q in zip(pts, pts[1:] + pts[:1]))


def _clip(tri: list, sign: float) -> list:
    """The part of `tri`, vertices (n, e, z, ground), where sign x (ground -
    z) >= 0, split at the crossing by linear interpolation."""
    out = []
    for p, q in zip(tri, tri[1:] + tri[:1]):
        dp, dq = sign * (p[3] - p[2]), sign * (q[3] - q[2])
        if dp >= 0.0:
            out.append(p)
        if (dp > 0.0 > dq) or (dq > 0.0 > dp):
            t = dp / (dp - dq)
            out.append(tuple(a + t * (b - a) for a, b in zip(p, q)))
    return out if len(out) >= 3 else []


def _column(name: str, kind: str, tri: list, origin):
    """The vertical prismatoid between the design line and the ground over
    one triangle, or None when it has no plan area or no depth."""
    design = [to_model(origin, n, e, z) for n, e, z, _g in tri]
    earth = [to_model(origin, n, e, g) for n, e, _z, g in tri]
    bottom, top = (design, earth) if kind == "cut" else (earth, design)
    if max(t[2] - b[2] for b, t in zip(bottom, top)) < _TINY:
        return None
    area = _signed_area(bottom)
    if abs(area) < _TINY:
        return None
    if area < 0.0:
        bottom, top = bottom[::-1], top[::-1]
    return Prismatoid(name, bottom, top, ifc=IFC[kind], layer=LAYER)


def strip(tag: str, a, b, survey, ground_z, origin, per_component=1) -> tuple:
    """(cut prismatoids, fill prismatoids, max cut depth, max fill depth)
    between sections `a` and `b` (section.Section). `survey(s, u, v)` places
    a section point (frame.survey_point); `ground_z(n, e)` is the ground;
    `per_component` divides the subgrade (Section.earthwork_line)."""
    la = a.earthwork_line(per_component)
    lb = b.earthwork_line(per_component)
    if len(la) != len(lb):
        raise ValueError(f"{tag}: earthwork lines at {a.s:g} and {b.s:g} have "
                         f"different point counts ({len(la)}, {len(lb)})")

    def corner(sec, p):
        n, e, z = survey(sec.s, *p)
        return (n, e, z, ground_z(n, e))

    ca, cb = [corner(a, p) for p in la], [corner(b, p) for p in lb]
    out = {"cut": [], "fill": []}
    depth = {"cut": 0.0, "fill": 0.0}
    for i in range(len(la) - 1):
        for t, tri in enumerate(((ca[i], cb[i], cb[i + 1]),
                                 (ca[i], cb[i + 1], ca[i + 1]))):
            for kind, sign in (("cut", 1.0), ("fill", -1.0)):
                poly = _clip(list(tri), sign)
                for f, piece in enumerate((poly[0], poly[k], poly[k + 1])
                                          for k in range(1, len(poly) - 1)):
                    col = _column(f"{kind} {tag} {i}.{t}.{f}", kind, list(piece),
                                  origin)
                    if col is None:
                        continue
                    out[kind].append(col)
                    depth[kind] = max(depth[kind],
                                      max(abs(q[3] - q[2]) for q in piece))
    return out["cut"], out["fill"], depth["cut"], depth["fill"]


def plan_area_sf(columns: list) -> float:
    """The plan area under `columns` (strip's prismatoids): their bases."""
    return sum(abs(p.area_sf) for p in columns)


class EarthMesh:
    """One closed body of earthwork: a connected region of columns, merged
    (see `merge`)."""

    def __init__(self, name: str, kind: str, verts: list, tris: list,
                 plan: list) -> None:
        self.name, self.ifc, self.layer = name, IFC[kind], LAYER
        self.verts, self.tris, self.plan = verts, tris, plan

    @property
    def volume_cf(self) -> float:
        v = self.verts
        return abs(_signed_volume([(v[a], v[b], v[c]) for a, b, c in self.tris]))

    def body_solids(self) -> list[dict]:
        return [{"kind": "mesh", "units": "ft", "verts": list(self.verts),
                 "tris": list(self.tris), "plan": self.plan}]


def _column_faces(p: Prismatoid, vid) -> list:
    """A triangular column's outward faces as vertex-id polygons: its base,
    its top and three vertical sides. A side with no height at a corner
    loses that corner; one with none at all is no face."""
    b, t = [vid(q) for q in p.bottom], [vid(q) for q in p.top]
    faces = [b[::-1], t]                      # the base is wound CCW in plan
    for i in range(3):
        j = (i + 1) % 3
        faces.append([b[i], b[j], t[j], t[i]])
    out = []
    for f in faces:
        ring = [x for k, x in enumerate(f) if x != f[k - 1]]
        if len(set(ring)) >= 3:
            out.append(ring)
    return out


def _plan_loops(columns: list) -> list:
    """The outline of the columns' bases in plan: base edges no other base
    shares, chained into loops. Where two loops meet at a point (a vertex
    with two outline edges out of it), the walk runs through both; it is
    cut there into simple loops, so no outline visits a point twice."""
    seen = set()
    for base in columns:
        seen.update(zip(base, base[1:] + base[:1]))
    nxt: dict = {}
    for (a, b) in sorted(seen):
        if (b, a) not in seen:
            nxt.setdefault(a, []).append(b)
    loops = []
    while nxt:
        start = next(iter(nxt))
        walk, a = [start], start
        while a in nxt:
            b = nxt[a].pop()
            if not nxt[a]:
                del nxt[a]
            walk.append(b)
            a = b
        # walk returns to start; peel off a loop each time a point repeats
        stack = []
        for v in walk[:-1]:
            if v in stack:
                k = stack.index(v)
                loops.append(stack[k:])
                del stack[k + 1:]
            else:
                stack.append(v)
        loops.append(stack)
    return loops


def merge(name: str, kind: str, columns: list) -> list:
    """`columns` (one kind's prismatoids from `strip`) as closed meshes, one
    per connected region: corners welded, and every face two neighbouring
    columns share dropped from both, so only the region's skin is left.

    Neighbours meet face to face: a strip's triangles share whole edges,
    the ground crossing splits a shared edge at the same point for both,
    and consecutive strips share a station's earthwork line. Regions are
    joined through faces only; two that touch at a corner or along an edge
    without a face between them stay separate bodies (emit writes them as
    separate items of one element)."""
    verts, index = [], {}

    def vid(q):
        key = tuple(round(c, _WELD) for c in q)
        if key not in index:
            index[key] = len(verts)
            verts.append(tuple(float(c) for c in q))
        return index[key]

    faces, bases, plan_id = [], [], {}
    for p in columns:
        faces += _column_faces(p, vid)
        base = []
        for x, y, _z in p.bottom:
            key = (round(x, _WELD), round(y, _WELD))
            base.append(plan_id.setdefault(key, (len(plan_id), (x, y))))
        bases.append([i for i, _xy in base])
    dropped = _shared_faces(faces)
    skin = [f for i, f in enumerate(faces) if i not in dropped]
    # regions: faces joined through an edge two of them share
    parent = list(range(len(skin)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    by_edge: dict = {}
    for i, f in enumerate(skin):
        for a, b in zip(f, f[1:] + f[:1]):
            by_edge.setdefault((min(a, b), max(a, b)), []).append(i)
    for users in by_edge.values():
        if len(users) == 2:
            parent[root(users[0])] = root(users[1])
    regions: dict = {}
    for i, f in enumerate(skin):
        regions.setdefault(root(i), []).append(f)
    xy = {i: q for i, q in plan_id.values()}
    plan = [[xy[i] for i in loop] for loop in _plan_loops(bases)]
    out = []
    for k, region in enumerate(regions.values()):
        used = sorted({x for f in region for x in f})
        local = {x: n for n, x in enumerate(used)}
        vs = [verts[x] for x in used]
        tris = [(local[f[0]], local[f[m]], local[f[m + 1]])
                for f in region for m in range(1, len(f) - 1)]
        # the element's plan outline rides on its first body, once
        out.append(EarthMesh(f"{name} {k + 1}", kind, vs,
                             _outward_tris(vs, tris), plan if k == 0 else []))
    return out


def _shared_faces(faces: list) -> set:
    """Indices of the faces two neighbours share: a shared face appears
    once each way round, the same corners reversed. Each face pairs with
    at most one other; one with no reversed partner stays."""
    by_corners: dict = {}
    for i, f in enumerate(faces):
        by_corners.setdefault(frozenset(f), []).append(i)
    dropped = set()
    for group in by_corners.values():
        for n, a in enumerate(group):
            if a in dropped:
                continue
            twin = next((b for b in group[n + 1:] if b not in dropped
                         and _reversed(faces[a], faces[b])), None)
            if twin is not None:
                dropped.update((a, twin))
    return dropped


def _reversed(f: list, g: list) -> bool:
    """Whether polygon g is polygon f traversed the other way round."""
    if len(f) != len(g):
        return False
    r = g[::-1]
    k = r.index(f[0])
    return r[k:] + r[:k] == f
