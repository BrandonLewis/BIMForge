"""Type 732SW end blocks (B11-58/59/59A): the approach and departure blocks
that terminate a barrier run. Each is a tapered concrete solid lofted from the
running Section A-A profile (inboard) to a solidified "nose" section at the
traffic/departure end -- the 2" back relief is filled to a full 1'-0" parapet,
and (approach only) the top is raised 2'-8" -> 2'-11" above the sidewalk face.

The loft is a LINEAR taper (both the 2'-8" -> 2'-11" top rise and the back-
relief fill distribute evenly over the 6' block), an estimate-level
approximation of the sheet's actual "6:1 taper near the running-barrier
transition, full section elsewhere" -- a small, conservative-direction under-
count on the block (sub-percent on the run), in the same spirit as the
omitted chamfer/fillets.

CF is measured from the emitted triangles (_signed_volume of the emitted
triangles), never a parallel hand formula (spillway-pilot QC rule). The 3"x4" chamfer
nose and R-fillets are omitted as a documented sub-percent over-count,
matching the R28 sharp-corner convention.
"""
from __future__ import annotations

from bimforge.author.barrier_732sw_rebar import barrier_732sw_bars
from bimforge.author.barrier_section import type_732sw_profile
from bimforge.author.primitives import (
    ear_clip, loft_faces, _outward_tris, _signed_area2, _signed_volume,
    _wound)

#: end-block barrier height above the sidewalk face, feet.
APPROACH_BARRIER_H = 2.0 + 11.0 / 12.0    # 2'-11"


def nose_section(row: dict, *, approach: bool) -> list[tuple[float, float]]:
    """The solidified nose (x, z) ring, same 8-vertex topology/frame as
    `type_732sw_profile`. The 2" back relief is collapsed to the outboard face
    (full-width solid parapet); for `approach` the barrier top is raised to
    2'-11" above the sidewalk face, else it keeps the running 2'-8".
    """
    prof = list(type_732sw_profile(row))          # 8 pts, see barrier_section
    sw_top_face = float(row["sw_top_face_ft"])
    top_h = float(row["top_h_ft"])
    bh = APPROACH_BARRIER_H if approach else float(row["barrier_h_ft"])
    z_top = sw_top_face + bh
    z_topblock_bot = z_top - top_h
    x_out = prof[2][0]                             # outboard face x (== 0.0)
    # indices per type_732sw_profile: 0,1 = outboard stem base/relief (move to
    # x_out); 2,3 = top-block outboard corners (raise to z_top); 4 = inboard
    # top corner (raise); 5,6,7 = sidewalk (unchanged).
    # on a sloped deck the outboard base keeps the running deck-z at the old x
    # (flat-deck-exact; the ~1/25" gap at 2% is a conservative sub-percent
    # under-count, consistent with the family's chamfer/fillet omissions).
    prof[0] = (x_out, prof[0][1])
    prof[1] = (x_out, z_topblock_bot)
    prof[2] = (x_out, z_topblock_bot)
    prof[3] = (x_out, z_top)
    prof[4] = (prof[4][0], z_top)
    return prof


def _key(p) -> tuple:
    return (round(p[0], 9), round(p[1], 9), round(p[2], 9))


def _tri_face(face_pts: list) -> list:
    """Triangulate one planar loft cap (constant y) into point-triples,
    PRESERVING its outward winding. Drops the collapsed-relief duplicate
    vertex; non-convex safe (ear-clip, since the 732SW section is an L).
    ear_clip needs CCW input, so a CW cap is clipped reversed and each output
    triangle is reversed back to restore the CW (outward) winding."""
    xz = [(p[0], p[2]) for p in face_pts]
    n = len(xz)
    keep = [i for i in range(n) if xz[i] != xz[(i - 1) % n]]
    ring = [xz[i] for i in keep]
    pts = [face_pts[i] for i in keep]
    if len(ring) < 3:
        return []
    if _signed_area2(ring) >= 0.0:                       # CCW: clip directly
        return [(pts[a], pts[b], pts[c]) for a, b, c in ear_clip(ring)]
    rr, rp = list(reversed(ring)), list(reversed(pts))   # CW: clip reversed ...
    return [(rp[a], rp[c], rp[b]) for a, b, c in ear_clip(rr)]  # ... reverse tri


class _EndBlockSolid:
    """A prismatoid loft between the running (inboard) ring at y=`y_inboard`
    and the nose ring at y=`y_nose`. Exposes `body_solids()` (a mesh dict, same
    schema SectionPrism emits) and `volume_cf` measured from the SAME emitted
    triangles (Qto == geometry, the spillway-pilot QC rule).

    Both rings are wound CCW identically (same source order => same winding =>
    lateral edges still correspond). `loft_faces` supplies the outward-oriented
    caps + lateral triangles; the two n-gon caps are ear-clipped by `_tri_face`
    (winding preserved); `_outward_tris` normalizes the shell as a final guard.
    The measured volume matches `face_volume(loft_faces(...))` and the smooth
    prismatoid formula to machine precision."""

    def __init__(self, name: str, inboard: list, nose: list,
                 y_inboard: float, y_nose: float,
                 ifc: str, layer: str | None, fan: bool = False) -> None:
        self.name, self.ifc, self.layer = name, ifc, layer
        self._a2 = _wound(list(inboard), ccw=True)
        self._b2 = _wound(list(nose), ccw=True)
        self._yi, self._yn = float(y_inboard), float(y_nose)
        # `fan`: centroid 4-fan the side quads so a twisted (sloping->vertical)
        # taper integrates to the exact prismatoid volume. Off by default so the
        # 732SW block's single-diagonal mesh/volume stays byte-identical; the
        # 842 taper (which the single diagonal biases ~2.9% high) opts in.
        self._fan = fan

    def _point_tris(self) -> list:
        a3 = [(x, self._yi, z) for x, z in self._a2]
        b3 = [(x, self._yn, z) for x, z in self._b2]
        faces = loft_faces([a3, b3], fan=self._fan)
        tris: list = []
        for cap in faces[:2]:                       # two end caps
            tris += _tri_face(cap)
        for s in faces[2:]:                          # lateral loft triangles
            if len({_key(p) for p in s}) == 3:       # skip collapsed-relief edge
                tris.append((s[0], s[1], s[2]))
        return tris

    def _mesh(self):
        verts: list = []
        index: dict = {}

        def vid(p):
            key = _key(p)
            if key not in index:
                index[key] = len(verts)
                verts.append((float(p[0]), float(p[1]), float(p[2])))
            return index[key]

        tris = [tuple(vid(p) for p in t) for t in self._point_tris()]
        return verts, _outward_tris(verts, tris)

    @property
    def volume_cf(self) -> float:
        return abs(_signed_volume(self._point_tris()))

    def body_solids(self) -> list[dict]:
        verts, tris = self._mesh()
        xs = [x for x, _z in self._a2]
        y0, y1 = min(self._yi, self._yn), max(self._yi, self._yn)
        plan = [[(min(xs), y0), (max(xs), y0), (max(xs), y1), (min(xs), y1)]]
        return [{"kind": "mesh", "units": "ft", "verts": verts,
                 "tris": tris, "plan": plan}]


def endblock_solid(name: str, row: dict, *, approach: bool,
                   y_inboard: float, y_nose: float,
                   ifc: str = "IfcWall",
                   layer: str | None = "S-CONC") -> _EndBlockSolid:
    """Build the tapered end-block loft. The extrusion length is the actual
    |y_nose - y_inboard|."""
    return _EndBlockSolid(name, type_732sw_profile(row),
                          nose_section(row, approach=approach),
                          y_inboard, y_nose, ifc, layer)


#: block length (feet), B11-58/59 "6'-0" Min".
ENDBLOCK_LEN = 6.0


def endblock_bars(length_ft: float = ENDBLOCK_LEN, *, approach: bool) -> list:
    """Developed-length reinforcing estimate for one end block (Sections
    D-D / H-H / F-F). Approach uses the heavier Type E-1 schedule (#6 traffic
    face); departure is the lighter all-#5 layout. Reuses the straight
    weight-only bar builder -- exact hooks/laps are the documented follow-on.
    """
    # vertical bars develop over the barrier height ABOVE the sidewalk (the
    # block sits ON the sidewalk) -- intentionally shorter than the running
    # section's _rebar_groups basis, which uses the full top_z incl. sw thick.
    height = APPROACH_BARRIER_H if approach else 2.0 + 8.0 / 12.0
    face_size = 6 if approach else 5
    groups = [
        # longitudinal continuous bars along the 6' block:
        {"mark": "eb-long", "size": 5, "kind": "long", "count": 4},
        {"mark": "eb-long-top", "size": 5, "kind": "long", "count": 12},
        # transverse/vertical mat, traffic face then back face + stirrups:
        {"mark": "eb-face", "size": face_size, "kind": "vert",
         "spacing_in": 6.0, "length_ft": height},
        {"mark": "eb-stirrup", "size": 5, "kind": "vert",
         "spacing_in": 6.0, "length_ft": height},
        {"mark": "eb-tie", "size": 5, "kind": "vert",
         "spacing_in": 12.0, "length_ft": 1.0},
    ]
    return barrier_732sw_bars(length_ft, groups)
