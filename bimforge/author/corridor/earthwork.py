"""Cut and fill between two corridor sections (roadmap P.6).

The strip between two stations' earthwork lines is cut into triangles, two
per quad, in the sections' own (s, u) coordinates. Each triangle is split
where the ground crosses the design line, with depth interpolated linearly
along its edges. Each piece becomes a triangular column between the design
line and the ground: cut where the ground is above, fill where it is below.

A section stands square to the road's 3D tangent, so a section point v up
sits v sin(grade angle) back along the line (frame.survey_point). Each of a
column's edges therefore runs along its corner's v-ray, the line the point
moves on as v changes, to where that ray meets the ground; it is not
vertical. Columns stood vertically over plan triangles fold over where a
short bay's design line climbs steeply (a wall's 1 ft lead-in, a path's
1 ft end transition on a 7 % grade): two corners at one station sit farther
apart along the line than the bay is long, the plan triangle winds the
other way, and the body is no longer closed. In (s, u) no triangle folds.

A leaning column's side is a twisted quad, so each is fanned through its
centroid into planar triangles (the private trail family's lesson: a warped
face is not a plane, and the STEP true-volume check then disagrees by
several percent). Its base and top are triangles. The mesh volume is exact
for the surfaces it carries; a column with no volume, or turned inside out
by rays that cross, is refused. An earthwork line repeats points where a
hinge sits on the ground or a wall stands at the hinge; the triangles those
make have no (s, u) area and are dropped, as are pieces with no depth. A
wall side (a level line out to the wall's offset) ends on a face along the
rays there.
"""
from __future__ import annotations

from bimforge.author.primitives import Prismatoid, _outward_tris, _signed_volume
from bimforge.author.sweep import to_model

LAYER = "C-ROAD"
IFC = {"cut": "IfcEarthworksCut", "fill": "IfcEarthworksFill"}
#: (s, u) area (sf) and depth (ft) below which a piece is no solid
_TINY = 1e-6
#: decimal places the columns' corners are welded at when merged, feet
_WELD = 7
#: how far a v-ray's ground point may sit off the ground, feet
_ON_GROUND_FT = 1e-6


def _signed_area(pts: list) -> float:
    x0, y0 = pts[0][0], pts[0][1]
    return 0.5 * sum((p[0] - x0) * (q[1] - y0) - (q[0] - x0) * (p[1] - y0)
                     for p, q in zip(pts, pts[1:] + pts[:1]))


def _ground_v(survey, ground_z, s: float, u: float, v: float,
              tag: str = "") -> float:
    """The v at which the v-ray through section point (u, v) at station s
    meets the ground: secant steps from v, the ray climbing about a foot per
    foot of v, so the first step lands nearly on it. `tag` names the strip
    in the error."""
    def above(w):
        n, e, z = survey(s, u, w)
        return ground_z(n, e) - z

    w0, f0 = v, above(v)
    if f0 == 0.0:
        return v
    w1 = v + f0
    f1 = above(w1)
    for _ in range(50):
        if abs(f1) < 1e-10 or f1 == f0:
            break
        w0, f0, w1 = w1, f1, w1 - f1 * (w1 - w0) / (f1 - f0)
        f1 = above(w1)
    if not abs(f1) <= _ON_GROUND_FT:            # NaN fails too
        raise ValueError(f"{tag}: the ground under station {s:g}, offset "
                         f"{u:g} is not found along its section ray "
                         f"({f1:.3g} ft off)")
    return w1


def _clip(tri: list, sign: float) -> list:
    """The part of `tri`, corners (key, design, earth, depth, (s, u)), where
    sign x depth >= 0, split where the depth crosses zero. The crossing is
    lerped along the design edge from its lower-keyed end, so the two
    triangles sharing an edge split it at the same point; design and earth
    meet there."""
    out = []
    for p, q in zip(tri, tri[1:] + tri[:1]):
        dp, dq = sign * p[3], sign * q[3]
        if dp >= 0.0:
            out.append(p)
        if (dp > 0.0 > dq) or (dq > 0.0 > dp):
            lo, hi = (p, q) if p[0] < q[0] else (q, p)
            t = lo[3] / (lo[3] - hi[3])
            x = tuple(a + t * (b - a) for a, b in zip(lo[1], hi[1]))
            su = tuple(a + t * (b - a) for a, b in zip(lo[4], hi[4]))
            # its key is lo's and hi's together, a 4-tuple, never fed back
            # into _clip (each kind clips the triangle's own corners)
            out.append((lo[0] + hi[0], x, x, 0.0, su))
    return out if len(out) >= 3 else []


def _column_tris(bottom: list, top: list) -> list:
    """A leaning triangular column's outward faces as point triangles: its
    base, its top and three sides, each side's quad fanned through its
    centroid. The centroid is summed in sorted order, so the neighbour
    sharing a side fans it through the same point, the other way round. A
    side with no height at a corner is a triangle; one with none at all is
    no face."""
    def key(q):
        return tuple(round(c, _WELD) for c in q)

    out = [tuple(bottom[::-1]), tuple(top)]   # the base is wound CCW in (s, u)
    for i in range(3):
        j = (i + 1) % 3
        quad = [bottom[i], bottom[j], top[j], top[i]]
        ring = [q for k, q in enumerate(quad) if key(q) != key(quad[k - 1])]
        if len({key(q) for q in ring}) < 3:
            continue
        if len(ring) == 3:
            out.append(tuple(ring))
            continue
        mid = tuple(round(sum(q[x] for q in sorted(quad)) / 4.0, 9)
                    for x in range(3))
        out += [(quad[k], quad[(k + 1) % 4], mid) for k in range(4)]
    return out


class Column(Prismatoid):
    """One triangular column of earthwork from `strip`: `bottom` to `top`
    corner by corner along the section rays, wound CCW in (s, u). `plan` is
    its ground corners in plan, where it stands on the terrain."""

    def __init__(self, name: str, kind: str, bottom: list, top: list,
                 plan: list) -> None:
        super().__init__(name, bottom, top, ifc=IFC[kind], layer=LAYER)
        self.plan = plan

    def _faces(self) -> list:
        return _column_tris(self.bottom, self.top)

    @property
    def area_sf(self) -> float:
        return abs(_signed_area(self.plan))

    @property
    def volume_cf(self) -> float:
        """Signed: negative when the column is inside out."""
        return _signed_volume(self._faces())


def _column(name: str, kind: str, piece: list):
    """The column between the design line and the ground over one piece
    (corners as `_clip` keeps them), or None when it has no (s, u) area or
    no depth."""
    area = _signed_area([q[4] for q in piece])
    if abs(area) < _TINY or max(abs(q[3]) for q in piece) < _TINY:
        return None
    if area < 0.0:
        piece = piece[::-1]
    design, earth = [q[1] for q in piece], [q[2] for q in piece]
    bottom, top = (design, earth) if kind == "cut" else (earth, design)
    col = Column(name, kind, bottom, top, [(x, y) for x, y, _z in earth])
    if col.volume_cf <= 0.0:
        raise ValueError(f"{name}: the column is inside out "
                         f"({col.volume_cf:.6g} cf): its section rays cross")
    return col


def strip(tag: str, a, b, survey, ground_z, origin, per_component=1) -> tuple:
    """(cut columns, fill columns, max cut depth, max fill depth) between
    sections `a` and `b` (section.Section). `survey(s, u, v)` places a
    section point (frame.survey_point); `ground_z(n, e)` is the ground;
    `per_component` divides the subgrade (Section.earthwork_line). A depth
    is the elevation difference between a corner's design point and its
    ray's ground point."""
    la = a.earthwork_line(per_component)
    lb = b.earthwork_line(per_component)
    if len(la) != len(lb):
        raise ValueError(f"{tag}: earthwork lines at {a.s:g} and {b.s:g} have "
                         f"different point counts ({len(la)}, {len(lb)})")

    def corner(sec, k, p):
        # (key, design, earth, depth along the ray, where in (s, u))
        u, v = p
        w = _ground_v(survey, ground_z, sec.s, u, v, tag)
        return ((sec.s, k), to_model(origin, *survey(sec.s, u, v)),
                to_model(origin, *survey(sec.s, u, w)), w - v, (sec.s, u))

    ca = [corner(a, k, p) for k, p in enumerate(la)]
    cb = [corner(b, k, p) for k, p in enumerate(lb)]
    out = {"cut": [], "fill": []}
    depth = {"cut": 0.0, "fill": 0.0}
    for i in range(len(la) - 1):
        for t, tri in enumerate(((ca[i], cb[i], cb[i + 1]),
                                 (ca[i], cb[i + 1], ca[i + 1]))):
            for kind, sign in (("cut", 1.0), ("fill", -1.0)):
                poly = _clip(list(tri), sign)
                for f, piece in enumerate((poly[0], poly[k], poly[k + 1])
                                          for k in range(1, len(poly) - 1)):
                    col = _column(f"{kind} {tag} {i}.{t}.{f}", kind, list(piece))
                    if col is None:
                        continue
                    out[kind].append(col)
                    depth[kind] = max(depth[kind], max(abs(q[2][2] - q[1][2])
                                                       for q in piece))
    return out["cut"], out["fill"], depth["cut"], depth["fill"]


def plan_area_sf(columns: list) -> float:
    """The plan area under `columns` (strip's columns): their ground corners'
    triangles."""
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


def _column_faces(p: Column, vid) -> list:
    """A column's outward faces (`_column_tris`) as vertex-id triangles; one
    welded to fewer than three corners is no face."""
    out = []
    for f in p._faces():
        ring = [vid(q) for q in f]
        if len(set(ring)) == 3:
            out.append(ring)
    return out


def _plan_loops(columns: list) -> list:
    """The outline of the columns' plan triangles: edges no other triangle
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
    """`columns` (one kind's columns from `strip`) as closed meshes, one
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
        for x, y in p.plan:
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
