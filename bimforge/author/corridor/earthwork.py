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

from bimforge.author.primitives import Prismatoid
from bimforge.author.sweep import to_model

LAYER = "C-ROAD"
IFC = {"cut": "IfcEarthworksCut", "fill": "IfcEarthworksFill"}
#: plan area (sf) and depth (ft) below which a piece is no solid
_TINY = 1e-6


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
