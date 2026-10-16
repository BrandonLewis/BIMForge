"""Closed-form parametric primitives (spec §1).

Every primitive computes its quantities analytically — never from meshes.
Curved members carry BOTH the exact closed form and the faceted counterpart
the emitted tessellation will produce; the gate holds the two within
tolerance (the FACET_TOLERANCE discipline that caught the 1.7% arc faceting
error on the bridge pilot's predecessor).

Units: `Prism`/`Tube` take FEET (structure domain). `Plate`/`ArcBand`/
`ShapedStiffener`/`Bolt` take INCHES with `_in` suffixes (fabrication
domain, verbatim from the pipe-supports-pilot lineage). `fillet_polyline`/`Bar` take FEET
(the rebar-pilot lineage). `SectionPrism`/`BatteredWall`/`Fill` take FEET
(the spillway-pilot / bridge-pilot earthwork lineage). `body_solids()`
dicts carry a "units" key ("ft" | "in") so emitters convert unambiguously.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from bimforge.author.alignment import poly_area

STEEL_PCF = 490.0
STEEL_LB_PER_IN3 = STEEL_PCF / 1728.0        # 0.2835648
IN3_PER_CF = 1728.0
IN_PER_FT = 12.0
FACET_TOLERANCE = 0.005                      # 0.5% default arc-faceting band
ARC_SEGMENTS = 64


def equal_area_polygon_radius(r: float, segments: int) -> float:
    """Circumradius of a regular `segments`-gon with the SAME area as a circle
    of radius `r`. Round bars/bolts/holes are emitted as explicit equal-area
    polygons on the model's own faceting knob, so the volume is exact and
    independent of any consumer's tessellation settings (pipe-supports-pilot lesson: the
    default mesher under-reported a #5 bar's section by 0.97%)."""
    return r * math.sqrt(2.0 * math.pi / (segments * math.sin(2.0 * math.pi / segments)))


def circle_poly(r: float, segments: int, cx: float = 0.0, cy: float = 0.0,
                exact_area: bool = True, clockwise: bool = False):
    """A circle as a regular polygon; `exact_area` sizes it to the true area.
    Clockwise winding is what a VOID (hole ring) wants."""
    rr = equal_area_polygon_radius(r, segments) if exact_area else r
    sgn = -1.0 if clockwise else 1.0
    return [(cx + rr * math.cos(sgn * 2 * math.pi * i / segments),
             cy + rr * math.sin(sgn * 2 * math.pi * i / segments))
            for i in range(segments)]


def obround_poly(length: float, width: float, segments: int = ARC_SEGMENTS,
                 exact_area: bool = True):
    """A stadium/obround (rectangle `length` x `width` with semicircular ends),
    centred at the origin, long axis on X. `exact_area` sizes the end arcs so
    the faceted polygon's area equals the closed form
    L*W + pi*(W/2)^2 exactly (per-end equal-area radius)."""
    r = width / 2.0
    half = (length - width) / 2.0
    if half < 0:
        raise ValueError("obround length must be >= width")
    n = max(2, segments // 2)
    if exact_area:
        # Pushing the cap vertices out to the equal-area circumradius makes
        # the CAPS' combined area exact, but over-counts the rectangle
        # between them by the same ratio; pull the straight length back to
        # compensate so the polygon's total area is exact at every segment
        # count (mirrors the pipe-supports-pilot/bridge-pilot `obround_poly` lineage).
        rr = equal_area_polygon_radius(r, 2 * n)
        half *= r / rr
    else:
        rr = r
    pts = []
    for i in range(n + 1):                       # right cap, -90 -> +90
        a = -math.pi / 2 + math.pi * i / n
        pts.append((half + rr * math.cos(a), rr * math.sin(a)))
    for i in range(n + 1):                       # left cap, +90 -> +270
        a = math.pi / 2 + math.pi * i / n
        pts.append((-half + rr * math.cos(a), rr * math.sin(a)))
    return pts


# ---------------------------------------------------------------- ft solids
class Prism:
    """A vertical prism: closed plan polygon (feet) extruded z_bot -> z_top.

    `top_z` (per-vertex top elevations) makes it a loft with a planar-faceted
    top: the volume integral is the fan triangulation's mean-height sum, which
    is EXACT for any planar or bilinear top. Optional `holes` are inner rings
    subtracted from the plan (and the volume). Optional `dims_ft=(L, W)`
    records a known section so emit_ifc's L*W==area invariant uses the real
    width rather than the perimeter-derived rectangle.
    """

    def __init__(self, name: str, base: list, z_bot: float, z_top: float | None = None,
                 top_z: list | None = None, holes: list | None = None,
                 dims_ft: tuple | None = None, layer: str | None = None,
                 ifc: str = "IfcBuildingElementProxy", kind: str = "",
                 bottom_z: list | None = None) -> None:
        if (z_top is None) == (top_z is None):
            raise ValueError(f"{name}: give exactly one of z_top / top_z")
        if top_z is not None and len(top_z) != len(base):
            raise ValueError(f"{name}: top_z must match base vertex count")
        # `bottom_z` is the per-vertex BASE, the mirror of `top_z`: it lets a
        # single Prism carry a sloping floor (a wedge) instead of forcing a
        # slab+wedge decomposition that has to pick — and can get backwards —
        # the wedge's orientation. `z_bot` stays the scalar nominal floor used
        # when bottom_z is None (and as the flat fallback in the mesh path). (#251)
        if bottom_z is not None and len(bottom_z) != len(base):
            raise ValueError(f"{name}: bottom_z must match base vertex count")
        # Holes are punched only on the flat-extrude path: both B-rep emitters
        # ignore holes for a per-vertex face, so allowing the combination would
        # let volume_cf (which DOES subtract the hole) diverge from the emitted
        # solid and make true_volume_check delete an otherwise-correct output.
        if (holes) and (top_z is not None or bottom_z is not None):
            raise ValueError(
                f"{name}: holes are not supported with a per-vertex "
                f"top_z/bottom_z face (only with a flat z_top)")
        self.name, self.base, self.z_bot = name, list(base), z_bot
        self.z_top, self.top_z = z_top, top_z
        self.bottom_z = list(bottom_z) if bottom_z is not None else None
        self.holes = [list(h) for h in (holes or [])]
        self.dims_ft, self.layer, self.ifc, self.kind = dims_ft, layer, ifc, kind

    @property
    def area_sf(self) -> float:
        return poly_area(self.base) - sum(poly_area(h) for h in self.holes)

    @property
    def volume_cf(self) -> float:
        if self.top_z is None and self.bottom_z is None:
            return self.area_sf * (self.z_top - self.z_bot)
        # Per-vertex top and/or bottom: fan triangulation about vertex 0, each
        # triangle's volume its plan area times the MEAN of its three per-vertex
        # DEPTHS (top - bottom). Exact for a bilinear top over a bilinear bottom
        # (the depth field is then linear over each triangle). Reduces to the
        # scalar cases when either side is uniform. (#251 adds the bottom leg.)
        b, n = self.base, len(self.base)
        top = self.top_z if self.top_z is not None else [self.z_top] * n
        bot = self.bottom_z if self.bottom_z is not None else [self.z_bot] * n
        v = 0.0
        for i in range(1, n - 1):
            tri = [b[0], b[i], b[i + 1]]
            h = ((top[0] - bot[0]) + (top[i] - bot[i])
                 + (top[i + 1] - bot[i + 1])) / 3.0
            v += poly_area(tri) * h
        v -= sum(poly_area(h) for h in self.holes) * (max(top) - min(bot))
        return v

    @property
    def height_ft(self) -> float:
        """Volume-equivalent mean height (volume / plan area), so
        Height x GrossArea reproduces GrossVolume exactly on tapers."""
        a = self.area_sf
        return self.volume_cf / a if a > 1e-9 else 0.0

    def body_solids(self) -> list[dict]:
        return [{"kind": "prism", "units": "ft", "base": self.base,
                 "holes": self.holes, "z_bot": self.z_bot,
                 "z_top": self.z_top, "top_z": self.top_z,
                 "bottom_z": self.bottom_z}]


def _tri_normal_len2(tri) -> float:
    (x0, y0, z0), (x1, y1, z1), (x2, y2, z2) = tri
    ux, uy, uz = x1 - x0, y1 - y0, z1 - z0
    vx, vy, vz = x2 - x0, y2 - y0, z2 - z0
    cx, cy, cz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    return cx * cx + cy * cy + cz * cz


def taper_prism_triangles(base: list, top_z: list, z_bot: float,
                          bottom_z: list | None = None) -> list:
    """Triangular facets [(p0, p1, p2), ...] for a per-vertex-top loft, in
    whatever units `base`/`top_z`/`z_bot` are given in (callers pre-scale).

    Uses the SAME fan triangulation `Prism.volume_cf` integrates (a fan from
    vertex 0), so a triangulated B-rep built from this list has EXACTLY the
    analytic volume — not the flat-topped box a uniform IfcExtrudedAreaSolid/
    build123d `extrude` would draw (neither IFC nor STEP has a primitive for
    a swept solid whose depth varies per profile vertex; emit_ifc/emit_step
    both consume this for the `top_z` case).

    `bottom_z` (optional, mirror of `top_z`) sweeps a PER-VERTEX base too; when
    None the base is the flat plane `z_bot`. This is what lets a wedge Prism
    with a sloping floor build a single exact solid. (#251)

    Degenerate (zero-area) facets are dropped: where a vertex's top meets
    its bottom (H -> 0, the taper daylighting), the corresponding side facet
    legitimately has zero area, and a zero-area IfcFace/build123d Face is
    invalid, not merely superfluous.
    """
    if not base:
        return []
    bots = list(bottom_z) if bottom_z is not None else [z_bot] * len(base)
    pairs = list(zip(base, top_z, bots))
    x0, y0 = base[0]                                 # shift: same cancellation
    area2 = sum((x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
                for (x1, y1), (x2, y2) in zip(base, base[1:] + base[:1]))
    if area2 < 0:                                    # normalize to CCW-from-above
        pairs = list(reversed(pairs))
    n = len(pairs)
    bot = [(u, v, bz) for (u, v), _tz, bz in pairs]
    top = [(u, v, tz) for (u, v), tz, _bz in pairs]
    tris = []
    # Caps ear-clipped in plan (#315), not fanned from vertex 0: a fan is valid
    # only on a convex base, and THESE triangles are emitted (emit_ifc's
    # _faceted_brep). The exact-volume contract in the docstring is unaffected
    # -- ear_clip's summed area is exactly the ring's, and the fan integral it
    # is matched against is exact at any convexity -- so only the facets of a
    # re-entrant base move.
    cap = ear_clip([(u, v) for (u, v), _tz, _bz in pairs])
    for i0, i1, i2 in cap:
        tris.append((top[i0], top[i1], top[i2]))             # CCW -> +Z outward
        tris.append((bot[i0], bot[i2], bot[i1]))             # CW -> -Z outward
    for i in range(n):                                # sides, 2 triangles/edge
        j = (i + 1) % n
        tris.append((bot[i], bot[j], top[j]))
        tris.append((bot[i], top[j], top[i]))
    return [t for t in tris if _tri_normal_len2(t) > 1e-18]


class Tube:
    """A hollow circular cylinder swept along an axis (feet)."""

    def __init__(self, name: str, length_ft: float, r_out_ft: float,
                 wall_ft: float, axis: str = "x", x0_ft: float = 0.0,
                 cz_ft: float = 0.0, ifc: str = "IfcPipeSegment") -> None:
        if not 0.0 < wall_ft <= r_out_ft:
            raise ValueError(f"{name}: wall must be in (0, r_out]")
        self.name, self.length_ft = name, length_ft
        self.r_out, self.wall = r_out_ft, wall_ft
        self.axis, self.x0_ft, self.cz_ft, self.ifc = axis, x0_ft, cz_ft, ifc
        self.is_tube = True

    @property
    def r_in(self) -> float:
        return self.r_out - self.wall

    @property
    def volume_cf(self) -> float:
        return math.pi * (self.r_out ** 2 - self.r_in ** 2) * self.length_ft

    def body_solids(self) -> list[dict]:
        return [{"kind": "tube", "units": "ft", "x0": self.x0_ft,
                 "length": self.length_ft, "cz": self.cz_ft,
                 "r_outer": self.r_out, "wall": self.wall, "axis": self.axis}]


# ------------------------------------------------------------ ft earthwork
def outward_normals(poly: list, side: float = 1.0) -> list:
    """Per-segment unit normal of a plan polyline (spillway-pilot wall
    lineage). For travel direction (dx, dy) the `side`=+1 normal is
    (dy, -dx) — the right-hand side of travel; -1 flips it."""
    out = []
    for (x0, y0), (x1, y1) in zip(poly, poly[1:]):
        dx, dy = x1 - x0, y1 - y0
        n = math.hypot(dx, dy)
        if n < 1e-12:
            raise ValueError("zero-length polyline segment")
        out.append((side * dy / n, -side * dx / n))
    return out


def mitre_offset(n0: tuple, n1: tuple) -> tuple:
    """Offset direction at a corner where segments with unit normals `n0`,
    `n1` meet: m = (n0 + n1) / (1 + n0.n1).

    |m| = 1/cos(theta/2) at deflection theta — LONGER than unit at any real
    corner, deliberately: offsetting the corner vertex by t*m keeps BOTH
    adjacent faces at distance t, which a normalized bisector would not (a
    90 deg mitre is sqrt(2) long). That growth is the guard's business too:
    deflections beyond ~135 deg raise, not just the exact 180 deg reversal —
    a threshold that only caught within ~0.0026 deg of antiparallel let a
    179 deg corner through SILENTLY at |m| = 114.6, a spike 115x the wall
    thickness whose volume then landed honestly in the declared Qto.
    """
    d = n0[0] * n1[0] + n0[1] * n1[1]
    if 1.0 + d < 0.3:                        # deflection beyond ~135 deg
        deg = math.degrees(math.acos(max(-1.0, min(1.0, d))))
        raise ValueError(
            f"{deg:.1f} deg deflection has no usable mitre (the corner "
            f"offset grows as 1/cos(theta/2)); split a near-hairpin LOL "
            f"into separate walls")
    return ((n0[0] + n1[0]) / (1.0 + d), (n0[1] + n1[1]) / (1.0 + d))


def clean_ring(ring: list) -> list:
    """Round a 3D face ring to the model tolerance and drop repeated /
    closing points. A ring left with fewer than 3 points is degenerate (two
    loft edges coincide — e.g. a section where the wall height goes to
    zero) and returns [], so callers skip it rather than emit an invalid
    zero-area face.

    Tolerance is 1e-9 ft: coarse enough to merge a point computed twice by
    different arithmetic, fine enough to be invisible in any quantity — a
    1e-6 rounding visibly moved a lofted wall's volume at the 1e-5 cf
    level."""
    out = []
    for p in ring:
        k = (round(p[0], 9), round(p[1], 9), round(p[2], 9))
        if not out or out[-1] != k:
            out.append(k)
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out if len(out) >= 3 else []


def clean_ring2d(ring: list) -> list:
    """The 2D analogue of `clean_ring`: round a plan (x, y) ring to the model
    tolerance and drop consecutive-coincident and closing-duplicate vertices.
    A ring left with < 3 points is degenerate (a zero-area profile) and
    returns [].

    A section's meshing must tolerate the same degenerate rings its shoelace
    area already does: a box-culvert cell void whose haunch is 0 is authored as
    an octagon whose chamfer edges have zero length, so adjacent vertices
    coincide. `poly_area` sums those to the right net area, but `keyhole_ring`/
    `ear_clip` choke on the zero-length edges -- so `SectionPrism.body_solids`
    cleans its rings here, the same way `BatteredWall`/`WarpedStem` body_solids
    already run every loft face through `clean_ring`.
    """
    out = []
    for p in ring:
        k = (round(p[0], 9), round(p[1], 9))
        if not out or out[-1] != k:
            out.append(k)
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out if len(out) >= 3 else []


def face_volume(faces: list) -> float:
    """Volume enclosed by outward-facing planar 3D rings (divergence
    theorem, fan-triangulated per ring).

    This is the volume of the solid that actually gets emitted, so the
    declared Qto and the tessellated geometry cannot drift apart — which
    matters on mitred wall corners, where "section area x centreline
    length" is NOT the volume of the mitred solid (spillway-pilot QC lesson).

    Computed about the vertex centroid so it is translation-invariant:
    sum(a.(b x c))/6 is origin-independent in exact arithmetic, but on
    State-Plane-magnitude coordinates (~1e6 ft) each term is ~1e19 while
    the answer is ~1e2, and float64 cancellation eats it — a measured 2.3%
    volume error against the Qto declared on the very same elements (the
    same lesson `poly_area` carries in 2D; areas are built from differences
    and need no shift, volumes do).
    """
    rings = [r for r in (clean_ring(f) for f in faces) if r]
    pts = [p for r in rings for p in r]
    if not pts:
        return 0.0
    ox = sum(p[0] for p in pts) / len(pts)
    oy = sum(p[1] for p in pts) / len(pts)
    oz = sum(p[2] for p in pts) / len(pts)
    v = 0.0
    for r in rings:
        ax, ay, az = r[0][0] - ox, r[0][1] - oy, r[0][2] - oz
        for (bx, by, bz), (cx, cy, cz) in zip(r[1:], r[2:]):
            bx, by, bz = bx - ox, by - oy, bz - oz
            cx, cy, cz = cx - ox, cy - oy, cz - oz
            v += (ax * (by * cz - bz * cy)
                  - ay * (bx * cz - bz * cx)
                  + az * (bx * cy - by * cx))
    return abs(v) / 6.0


def _signed_volume(tris: list) -> float:
    """SIGNED volume of a closed triangle set (point-triples) — the same
    centroid-shifted tet sum `face_volume` integrates, WITHOUT the abs.

    Positive means the windings face outward; negative means the shell is
    inside-out — spec-invalid orientation for an IfcClosedShell, so
    backface-culling viewers and signed-volume consumers see faces pointing
    INTO the solid. `face_volume`'s abs() deliberately masks the sign (its
    contract is magnitude), so mesh emitters normalize on THIS before
    handing the shell out (a side=+1 wall loft measured -213.33 while the
    declared Qto read +213.33)."""
    if not tris:
        return 0.0
    pts = [p for t in tris for p in t]
    ox = sum(p[0] for p in pts) / len(pts)
    oy = sum(p[1] for p in pts) / len(pts)
    oz = sum(p[2] for p in pts) / len(pts)
    v = 0.0
    for (ax, ay, az), (bx, by, bz), (cx, cy, cz) in tris:
        ax, ay, az = ax - ox, ay - oy, az - oz
        bx, by, bz = bx - ox, by - oy, bz - oz
        cx, cy, cz = cx - ox, cy - oy, cz - oz
        v += (ax * (by * cz - bz * cy)
              - ay * (bx * cz - bz * cx)
              + az * (bx * cy - by * cx))
    return v / 6.0


def _outward_tris(verts: list, tris: list) -> list:
    """Normalize an indexed shell's winding to outward-facing: if the
    signed volume is negative, every triangle flips. Applied at the
    `body_solids()` boundary so no emitted mesh can be inside-out however
    the section rings happened to wind."""
    if _signed_volume([(verts[a], verts[b], verts[c])
                       for a, b, c in tris]) < 0.0:
        return [(a, c, b) for a, b, c in tris]
    return tris


def loft_faces(sections: list, *, fan: bool = False) -> list:
    """Outward-facing rings of a prism swept through same-length 3D
    sections: the two end caps plus the side faces per edge per bay.

    Side faces are split into triangles because where a wall mitres a
    corner AND changes thickness, the four corners of a side quad are not
    coplanar — a non-planar face is invalid IFC, and it also lets the
    declared volume and the tessellated volume disagree depending on which
    diagonal each side happens to pick (spillway-pilot lesson).

    `fan` selects the side-quad triangulation:

    * ``fan=False`` (default): two triangles per quad on a single fixed
      diagonal. This is the historical output — BYTE-IDENTICAL for every
      existing consumer (SectionPrism, BatteredWall, footing/wingwall runs,
      the 836 rail_barrier, the 732SW end block) — so their emitted meshes,
      STEP B-reps and declared volumes are all unchanged. For a PLANAR quad
      this is exact; for a mildly twisted one it carries a small
      first-order-in-twist bias (kept within MESH_TOLERANCE by the callers
      that have twist, e.g. WarpedStem/rail).

    * ``fan=True``: split each quad through its centroid into four triangles
      (the same 4-fan SweptSection._faces uses). The 4-fan's flux is the
      MEAN of the two diagonal splits (= the bilinear patch), so a TWISTED
      quad integrates to the true prismatoid volume instead of the
      single-diagonal-biased value — every diagonal bows the same rotational
      way, so single-diagonal errors ADD around the ring instead of
      cancelling. Opt in only where that bias matters and the mesh feeds a
      clean B-rep (the 842 sloping->vertical end-block loft); the sliver
      triangles a 4-fan makes at a severe mitre can flip OCCT's shell
      orientation, so it is NOT the default for mitred runs.

    The two end-cap rings are returned unchanged -- and must be EAR-CLIPPED,
    not fanned from vertex 0 (#315). A fan is valid only on a convex ring; on a
    re-entrant one it lays the notch twice, once each way, so the facets cancel
    in any volume integral and survive only on the emitted SURFACE. Use
    `triangulate_planar_face`, which projects onto the face's own plane,
    preserves the ring's winding, and returns the single triangle unchanged for
    the side faces. The caps stay RINGS here because `face_volume` integrates
    rings directly and each emitting caller triangulates in its own plane; what
    this docstring owes the caller is the rule, which it did not say before.
    """
    faces = [list(reversed(sections[0])), list(sections[-1])]
    n = len(sections[0])
    for sa, sb in zip(sections, sections[1:]):
        for j in range(n):
            k = (j + 1) % n
            a, b, c, d = sa[j], sa[k], sb[k], sb[j]
            if not fan:
                faces.append([a, b, c])
                faces.append([a, c, d])
                continue
            mid = ((a[0] + b[0] + c[0] + d[0]) / 4.0,
                   (a[1] + b[1] + c[1] + d[1]) / 4.0,
                   (a[2] + b[2] + c[2] + d[2]) / 4.0)
            faces.append([a, b, mid])
            faces.append([b, c, mid])
            faces.append([c, d, mid])
            faces.append([d, a, mid])
    return faces


def _signed_area2(ring: list) -> float:
    """2x signed area of a 2D ring, shifted to the first vertex (the same
    cancellation insurance `poly_area` carries)."""
    x0, y0 = ring[0]
    return sum((x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
               for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]))


def _wound(ring: list, ccw: bool = True) -> list:
    return list(ring) if (_signed_area2(list(ring)) >= 0.0) == ccw \
        else list(reversed(ring))


def _orient(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])


def _segment_blocked(p, q, ring: list) -> bool:
    """Does the open segment p-q cross any edge of `ring` (or run through
    one of its vertices)? Edges incident to a point coincident with p or q
    do not count — a keyhole bridge lands ON ring vertices by design."""
    for a, b in zip(ring, ring[1:] + ring[:1]):
        if a in (p, q) or b in (p, q):
            continue
        d1, d2 = _orient(p, q, a), _orient(p, q, b)
        d3, d4 = _orient(a, b, p), _orient(a, b, q)
        if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
            return True
        for w, d in ((a, d1), (b, d2)):     # ring vertex ON the open segment
            if d == 0 and (min(p[0], q[0]) <= w[0] <= max(p[0], q[0])
                           and min(p[1], q[1]) <= w[1] <= max(p[1], q[1])):
                return True
    return False


def keyhole_ring(outer: list, voids: list) -> list:
    """One weakly-simple CCW ring: `voids` spliced into `outer` through
    zero-width bridge cuts (the spillway-pilot ogee technique: the weir's ASTM C578
    expanded-polystyrene void was carried as a keyhole in the section
    profile, so ONE ring both draws and integrates to the net area — no
    boolean, no second code path to disagree with the Qto).

    Each void is bridged from its max-x vertex to the nearest visible ring
    vertex; voids are taken right-to-left so later bridges see earlier
    splices and cannot cross them.
    """
    ring = _wound(outer, ccw=True)
    for void in sorted(voids, key=lambda v: max(p[0] for p in v),
                       reverse=True):
        h = _wound(void, ccw=False)          # a hole winds opposite the outer
        j = max(range(len(h)), key=lambda i: h[i])
        hj = h[j]
        for i in sorted(range(len(ring)),
                        key=lambda i: (ring[i][0] - hj[0]) ** 2
                        + (ring[i][1] - hj[1]) ** 2):
            if not (_segment_blocked(hj, ring[i], ring)
                    or _segment_blocked(hj, ring[i], h)):
                ring = ring[:i + 1] + h[j:] + h[:j] + [hj] + ring[i:]
                break
        else:
            raise ValueError("void has no visible bridge to the outer ring")
    return ring


def _pt_in_tri(p, a, b, c, eps: float) -> bool:
    """Inside-or-on test against a CCW triangle; on-edge counts as inside
    (a conservative ear blocker)."""
    return (_orient(a, b, p) >= -eps and _orient(b, c, p) >= -eps
            and _orient(c, a, p) >= -eps)


def ear_clip(ring: list) -> list:
    """Triangulate a weakly-simple CCW 2D ring by ear clipping; returns
    index triples into `ring`, whose summed area is exactly the ring's.

    Fan triangulation (the `taper_prism_triangles` shortcut) is only valid
    on convex plans; section profiles — ogee weirs, chute blocks, keyholed
    voids — are not convex, so caps must be ear-clipped. Handles the
    bridged rings `keyhole_ring` builds: a vertex coincident with an ear's
    own corners (a bridge duplicate) does not block the ear.
    """
    n = len(ring)
    if n < 3:
        return []
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    span2 = (max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2
    eps = 1e-12 * max(span2, 1.0)
    idx = list(range(n))
    tris = []
    while len(idx) > 3:
        m = len(idx)
        for k in range(m):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % m]
            a, b, c = ring[i0], ring[i1], ring[i2]
            if _orient(a, b, c) <= eps:      # reflex or degenerate corner
                continue
            if any(_pt_in_tri(ring[j], a, b, c, eps) for j in idx
                   if j not in (i0, i1, i2) and ring[j] not in (a, b, c)):
                continue
            tris.append((i0, i1, i2))
            del idx[k]
            break
        else:
            raise ValueError("ear clipping failed: self-intersecting profile?")
    a, b, c = (ring[i] for i in idx)
    if abs(_orient(a, b, c)) > eps:          # a collinear remainder is empty
        tris.append(tuple(idx))
    return tris


def triangulate_planar_face(ring: list) -> list:
    """Index triples triangulating a planar 3D polygon (convex OR re-entrant)
    by projecting onto its own plane and ear-clipping, preserving the ring's
    given winding so the emitted facet normals stay consistent.

    A fan from vertex 0 — the historical loft-cap triangulation — is valid
    only for a CONVEX ring; a re-entrant section (the transcribed Type 836
    barrier) fans into overlapping, inverted triangles and a non-manifold
    shell whose STEP true volume comes back negated (#253). Ear clipping is
    correct for both.
    """
    m = len(ring)
    if m < 3:
        return []
    if m == 3:
        return [(0, 1, 2)]
    # Newell's method: an area-weighted face normal, robust to small
    # out-of-plane noise and defined BY the ring's winding (right-hand rule).
    nx = ny = nz = 0.0
    for (x0, y0, z0), (x1, y1, z1) in zip(ring, ring[1:] + ring[:1]):
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    # In-plane orthonormal basis (u, w = n x u). Seed u from the world axis
    # least aligned with n so the cross product is well conditioned. Because
    # w = n x u, a ring wound CCW about n projects to POSITIVE signed area.
    au, av, aw = abs(nx), abs(ny), abs(nz)
    ref = ((1.0, 0.0, 0.0) if au <= av and au <= aw
           else (0.0, 1.0, 0.0) if av <= aw else (0.0, 0.0, 1.0))
    ux, uy, uz = (ref[1] * nz - ref[2] * ny,
                  ref[2] * nx - ref[0] * nz,
                  ref[0] * ny - ref[1] * nx)
    ul = math.hypot(ux, uy, uz) or 1.0
    ux, uy, uz = ux / ul, uy / ul, uz / ul
    wx, wy, wz = (ny * uz - nz * uy, nz * ux - nx * uz, nx * uy - ny * ux)
    wl = math.hypot(wx, wy, wz) or 1.0
    wx, wy, wz = wx / wl, wy / wl, wz / wl
    proj = [(x * ux + y * uy + z * uz, x * wx + y * wy + z * wz)
            for x, y, z in ring]
    if _signed_area2(proj) >= 0.0:
        return ear_clip(proj)
    # Degenerate/near-planar case where the projection came out CW: ear-clip
    # the reversed ring (now CCW) and map indices back, so the triangles keep
    # the ORIGINAL ring's winding for _outward_tris to normalise globally.
    rev = list(range(m))[::-1]
    return [(rev[a], rev[b], rev[c])
            for a, b, c in ear_clip([proj[i] for i in rev])]


#: The exact form of a mesh solid (#330, #332). A body_solids() dict stays
#: kind "mesh" — every consumer that knows meshes (emit_dxf, emit_step, the
#: gate's coordinate sweep, wrappers outside this package that refuse any
#: other kind) reads it unchanged — and MAY carry d["exact"], the solid that
#: mesh tessellates, which emit_ifc writes in its place:
#:   {"kind": "extrusion", "profile", "voids", "plane", "dir"}
#:       plane {"o", "x", "y"}: profile (u, v) -> o + u*x + v*y, x and y
#:       orthonormal; dir the sweep vector (its length IS the depth; it need
#:       not be normal to the plane — a sheared extrusion is still one)
#:   {"kind": "sectioned", "sweep", "alignment", "vprofile", "origin",
#:    "sections"} — an alignment sweep (author.sweep), which no rigid map of
#:       the dict can move: any transform drops it.
#: The mesh is the authority. Code that edits a dict's verts without knowing
#: about "exact" (a subclass that grades a girder, a wrapper that places it)
#: leaves a stale exact form behind, so exact_of() trusts it only while the
#: mesh still IS that solid, and the edited mesh is what gets written.
EXACT_KINDS = ("extrusion", "sectioned")

#: how far a mesh vertex may sit from its exact solid, feet
EXACT_MATCH_TOL_FT = 1e-6


def _mat_vec(lin, v):
    return tuple(sum(lin[r][c] * v[c] for c in range(3)) for r in range(3))


def as_mesh(d: dict) -> dict:
    """`d` without its exact form: written as the mesh it carries."""
    return {k: v for k, v in d.items() if k != "exact"}


def place_exact(d: dict, lin, off=(0.0, 0.0, 0.0)) -> dict:
    """A copy of `d` whose exact form is moved by x' = lin @ x + off.

    Only the exact form is moved — the caller transforms verts/tris/plan
    exactly as it does for any mesh, so the two views stay one solid. A map
    that skews the profile plane off orthonormal no longer leaves an
    extrusion of that profile, and nothing moves an alignment sweep, so those
    drop the exact form rather than emit a solid the map did not produce.
    """
    ex = d.get("exact")
    if ex is None:
        return dict(d)
    if ex["kind"] != "extrusion":
        return as_mesh(d)
    pl = ex["plane"]
    x, y = _mat_vec(lin, pl["x"]), _mat_vec(lin, pl["y"])
    if (abs(math.hypot(*x) - 1.0) > 1e-9 or abs(math.hypot(*y) - 1.0) > 1e-9
            or abs(sum(a * b for a, b in zip(x, y))) > 1e-9):
        return as_mesh(d)
    o = tuple(a + b for a, b in zip(_mat_vec(lin, pl["o"]), off))
    return dict(d, exact=dict(ex, plane={"o": o, "x": x, "y": y},
                              dir=_mat_vec(lin, ex["dir"])))


def _extrusion_points(ex: dict) -> list:
    pl, dv = ex["plane"], ex["dir"]
    pts = []
    for ring in [ex["profile"]] + list(ex.get("voids") or ()):
        for u, v in ring:
            p = tuple(pl["o"][i] + u * pl["x"][i] + v * pl["y"][i]
                      for i in range(3))
            pts.append(p)
            pts.append(tuple(p[i] + dv[i] for i in range(3)))
    return pts


def _same_points(a: list, b: list, tol: float) -> bool:
    """Every point of `a` is within `tol` of one of `b`, and vice versa."""
    import numpy as np
    if not a or not b:
        return False
    pa, pb = np.asarray(a, float), np.asarray(b, float)
    for p, q in ((pa, pb), (pb, pa)):
        for i in range(0, len(p), 512):
            d2 = ((p[i:i + 512, None, :] - q[None, :, :]) ** 2).sum(-1)
            if d2.min(axis=1).max() > tol * tol:
                return False
    return True


def exact_of(d: dict) -> dict | None:
    """d["exact"] while `d`'s mesh still is that solid, else None.

    An extrusion's mesh vertices are its profile points at both ends; an
    alignment sweep's lie on its swept surface within its stations. A mesh
    edited after the exact form was attached fails the test and is written
    as the mesh it now is.
    """
    ex = d.get("exact") if isinstance(d, dict) else None
    if ex is None or d.get("kind") != "mesh" or not d.get("verts"):
        return None
    if ex.get("kind") == "extrusion":
        ok = _same_points(list(d["verts"]), _extrusion_points(ex),
                          EXACT_MATCH_TOL_FT)
    elif ex.get("kind") == "sectioned":
        ok = ex["sweep"].mesh_is_exact(d["verts"])
    else:
        ok = False
    return ex if ok else None


class SectionPrism:
    """A constant (x, z) cross-section extruded along +Y from `y0` for
    `length` feet (spillway-pilot lineage: chute slabs, ogee weirs, chute blocks,
    dentated sills — anything the plans give as a section times a run).

    `voids` are inner (x, z) rings carried as keyholes in the emitted
    profile (the ogee's expanded-polystyrene void), so one ring both draws
    and integrates to the net section — never a boolean.

    Mindset (spillway-pilot QC lesson): the declared Qto must come from the faces of
    the emitted solid, not a parallel hand formula. A straight extrusion is
    the one case where net-section-area x run IS the face volume, and
    `body_solids()` emits exactly that mesh, so the two are one number; on
    battered or mitred geometry the shortcut is wrong by a few percent — in
    OPPOSITE directions for the two cases — which is why `BatteredWall`
    measures its faces instead.
    """

    def __init__(self, name: str, profile: list, length: float,
                 y0: float = 0.0, voids: list | None = None,
                 ifc: str = "IfcBuildingElementProxy",
                 layer: str | None = None) -> None:
        if length <= 0:
            raise ValueError(f"{name}: length must be positive")
        self.name, self.profile = name, list(profile)
        self.length, self.y0 = float(length), float(y0)
        self.voids = [list(v) for v in (voids or [])]
        self.ifc, self.layer = ifc, layer

    @property
    def area_sf(self) -> float:
        return poly_area(self.profile) - sum(poly_area(v) for v in self.voids)

    @property
    def volume_cf(self) -> float:
        return self.area_sf * self.length

    def body_solids(self) -> list[dict]:
        # Clean coincident/closing-duplicate vertices so the mesh path tolerates
        # the same degenerate rings `area_sf`'s shoelace already does (a
        # haunch-0 box cell void arrives as an octagon with zero-length chamfer
        # edges); a void that collapses entirely (< 3 points) drops out.
        outer = clean_ring2d(self.profile)
        if len(outer) < 3:
            raise ValueError(f"{self.name}: profile collapses to < 3 points")
        outer = _wound(outer, ccw=True)
        voids = [c for c in (clean_ring2d(v) for v in self.voids) if c]
        merged = keyhole_ring(outer, voids) if voids else outer
        caps = ear_clip(merged)
        y0, y1 = self.y0, self.y0 + self.length
        verts: list = []
        index: dict = {}

        def vid(x, y, z):
            key = (round(x, 9), round(y, 9), round(z, 9))
            if key not in index:
                index[key] = len(verts)
                verts.append((float(x), float(y), float(z)))
            return index[key]

        tris = []
        for i0, i1, i2 in caps:
            (xa, za), (xb, zb), (xc, zc) = merged[i0], merged[i1], merged[i2]
            # a CCW (x, z) triangle faces -Y: outward on the near cap; the
            # far cap is the same triangle reversed (+Y outward).
            tris.append((vid(xa, y0, za), vid(xb, y0, zb), vid(xc, y0, zc)))
            tris.append((vid(xa, y1, za), vid(xc, y1, zc), vid(xb, y1, zb)))
        # Side walls run along the ORIGINAL rings, not the bridged one: the
        # bridge edges are zero-width and would emit coincident wall pairs.
        # The CW void rings get inward-facing walls from the same edge rule,
        # which is outward from the solid — orientation stays consistent.
        for r in [outer] + [_wound(v, ccw=False) for v in voids]:
            for p, q in zip(r, r[1:] + r[:1]):
                qa, pa = vid(q[0], y0, q[1]), vid(p[0], y0, p[1])
                pb, qb = vid(p[0], y1, p[1]), vid(q[0], y1, q[1])
                tris.append((qa, pa, pb))
                tris.append((qa, pb, qb))
        xs = [p[0] for p in outer]
        plan = [[(min(xs), y0), (max(xs), y0), (max(xs), y1), (min(xs), y1)]]
        # The section in the x-z plane at y0, swept +Y for `length`: exactly
        # one IfcExtrudedAreaSolid (#330). The voids ride as the profile's
        # inner curves, so the IFC path needs no keyhole bridge at all.
        return [{"kind": "mesh", "units": "ft", "verts": verts,
                 "tris": _outward_tris(verts, tris), "plan": plan,
                 "exact": {"kind": "extrusion", "profile": outer,
                           "voids": voids,
                           "plane": {"o": (0.0, y0, 0.0), "x": (1.0, 0.0, 0.0),
                                     "y": (0.0, 0.0, 1.0)},
                           "dir": (0.0, self.length, 0.0)}}]


class BatteredWall:
    """A battered retaining wall lofted along a plan line-of-layout (the
    spillway-pilot training-wall builder, parameterized).

    `lol` is the plan polyline of the wall's VERTICAL face; the body
    offsets to `side` (per `outward_normals`), mitred at interior corners.
    `top_profile` is piecewise-linear top-of-wall ELEVATION keyed on the
    plan coordinate `key_index` names (0 = x, 1 = y). Every section is a
    trapezoid: `t_top` thick at the top of wall, t_top + H*batter at the
    base (H = top of wall - `base_el`), the batter on the offset face.

    Mindset (spillway-pilot QC lesson): `volume_cf` IS `face_volume` of the loft
    `body_solids()` emits — the declared Qto comes from the faces of the
    emitted solid. "Section area x centreline length" is wrong by a few
    percent in OPPOSITE directions on battered vs mitred geometry (the
    corner wedge a mitre adds and the flare a batter adds do not commute
    with the centreline shortcut), so that shortcut is never declared.
    """

    def __init__(self, name: str, lol: list, top_profile: list,
                 key_index: int, base_el: float, t_top: float, batter: float,
                 side: float, base_profile: list | None = None,
                 ifc: str = "IfcWall",
                 layer: str | None = None) -> None:
        if len(lol) < 2:
            raise ValueError(f"{name}: lol needs at least two points")
        if key_index not in (0, 1):
            raise ValueError(f"{name}: key_index must be 0 (x) or 1 (y)")
        if t_top <= 0:
            raise ValueError(f"{name}: t_top must be positive")
        self.name, self.lol = name, [tuple(p) for p in lol]
        self.top_profile = [tuple(p) for p in top_profile]
        self.key_index, self.base_el = key_index, base_el
        self.t_top, self.batter, self.side = t_top, batter, side
        self.base_profile = (None if base_profile is None
                             else [tuple(p) for p in base_profile])
        self.ifc, self.layer = ifc, layer

        normals = outward_normals(self.lol, side)
        sections: list = []
        report: list = []

        def base_at(s):
            if self.base_profile is None:
                return base_el
            return profile_at(self.base_profile, s)

        def add(px, py, s, m):
            tow = profile_at(self.top_profile, s)
            b0 = base_at(s)
            h = tow - b0
            if h < 0:
                raise ValueError(
                    f"{name}: top of wall below base_el at station {s:g}")
            tb = t_top + h * batter
            if tb <= 0:
                # a negative batter big enough to invert the base thickness
                # flips the offset side and lofts a self-intersecting solid
                # whose abs volume still looks plausible — raise instead
                raise ValueError(
                    f"{name}: base thickness tb = {tb:g} ft <= 0 at station "
                    f"{s:g} (t_top {t_top:g} + H {h:g} x batter {batter:g} "
                    f"inverts the section)")
            sections.append([
                (px, py, b0),
                (px + m[0] * tb, py + m[1] * tb, b0),
                (px + m[0] * t_top, py + m[1] * t_top, tow),
                (px, py, tow),
            ])
            report.append((s, h, tb))

        for i, (px, py) in enumerate(self.lol):
            m = (normals[0] if i == 0 else normals[-1] if i == len(normals)
                 else mitre_offset(normals[i - 1], normals[i]))
            add(px, py, (px, py)[key_index], m)
            if i >= len(self.lol) - 1:
                continue
            # Sections at every LOL vertex plus every top-of-wall breakpoint
            # falling INSIDE the segment, in traversal order. A wall's
            # mirrored copy runs the other way along the key axis, so the
            # range test has to be direction-agnostic — filtering with
            # lol[0] <= s <= lol[-1] silently drops every breakpoint on that
            # side and straight-lines the wall top (spillway-pilot lesson).
            a, b = self.lol[i], self.lol[i + 1]
            sa, sb = a[key_index], b[key_index]
            if abs(sb - sa) < 1e-9:
                continue          # the leg runs normal to the key axis
            # Breakpoints are the UNION of interior top-of-wall stations and
            # (when base_profile is given) interior base stations, so a base
            # slope/level change mid-segment gets its own section instead of
            # being straight-lined across (same spillway-pilot lesson as the top). De-
            # duplicate stations that coincide.
            breaks = [s for s, _el in self.top_profile]
            if self.base_profile is not None:
                breaks += [s for s, _el in self.base_profile]
            lo, hi = min(sa, sb) + 1e-9, max(sa, sb) - 1e-9
            interior = {s for s in breaks if lo < s < hi}
            for s in sorted(interior, reverse=sb < sa):
                t = (s - sa) / (sb - sa)
                add(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t,
                    s, normals[i])

        self._sections = sections
        self.report = report
        self.base = ([(sx, sy) for sx, sy, _z in (sec[0] for sec in sections)]
                     + [(sx, sy) for sx, sy, _z in
                        (sec[1] for sec in reversed(sections))])

    def _faces(self) -> list:
        return loft_faces(self._sections)

    @property
    def volume_cf(self) -> float:
        return face_volume(self._faces())

    def body_solids(self) -> list[dict]:
        verts: list = []
        index: dict = {}

        def vid(p):
            if p not in index:
                index[p] = len(verts)
                verts.append(tuple(float(c) for c in p))
            return index[p]

        tris = []
        for ring in self._faces():
            r = clean_ring(ring)
            if not r:
                continue          # a degenerate loft face (edges coincide)
            # Ear-clip in the face's own plane (#315). The mesh volume is
            # still volume_cf bit for bit -- `face_volume`'s fan integral is
            # exact for ANY simple polygon, because a fan's SIGNED areas are
            # the shoelace whatever the convexity. That is also why a fanned
            # re-entrant cap emitted facets lying outside the solid at exactly
            # the right volume, and nothing downstream noticed.
            for i0, i1, i2 in triangulate_planar_face(r):
                tris.append((vid(r[i0]), vid(r[i1]), vid(r[i2])))
        return [{"kind": "mesh", "units": "ft", "verts": verts,
                 "tris": _outward_tris(verts, tris), "plan": [self.base]}]


class Fill(Prism):
    """A prism with prisms cut out of it (the bridge-pilot backfill port).

    Structure backfill is the only honest use here: it is the excavation
    void LESS whatever structure stands inside it, which is a real shape
    but not one any single extrusion describes. Building a plain prism
    sized to carry the right number would be geometry that does not exist,
    so this carries the actual difference and lets the volume fall out of
    it.

    Each cut is itself a `Prism`. Cuts must not overlap each other — in the
    originating use they never do, because the cutters are a footing
    (bottom of fill to top of footing) and the stem or columns standing ON
    it (top of footing upward), which stack. Three guards catch the common
    authoring mistakes: a cut poking outside the fill's z-range (volume
    subtracted that was never inside the fill), a cut whose base bbox falls
    outside the fill base's bbox (same disease in plan — a footing typo'd
    to x~50 on a 10x10 fill silently took its full 72 cf off, 428 instead
    of 500), and cuts consuming the whole gross volume (an empty fill is a
    spec error, not a quantity). The plan guard is a bbox gate, NOT exact
    polygon containment — cheap insurance against the gross case; the
    non-overlap contract between cuts, and true in-polygon placement,
    remain the caller's.
    """

    def __init__(self, name: str, base: list, z_bot: float, z_top: float,
                 cuts: list, holes: list | None = None,
                 dims_ft: tuple | None = None, layer: str | None = None,
                 ifc: str = "IfcEarthworksFill", kind: str = "") -> None:
        super().__init__(name, base, z_bot, z_top=z_top, holes=holes,
                         dims_ft=dims_ft, layer=layer, ifc=ifc, kind=kind)
        self.cuts = list(cuts)
        bbox = {"x": [p[0] for p in self.base], "y": [p[1] for p in self.base]}
        for c in self.cuts:
            c_top = c.z_top if c.z_top is not None else max(c.top_z)
            if c.z_bot < z_bot - 1e-9 or c_top > z_top + 1e-9:
                raise ValueError(
                    f"{name}: cut {c.name} z-range [{c.z_bot:g}, {c_top:g}] "
                    f"outside the fill's [{z_bot:g}, {z_top:g}]")
            for k, i in (("x", 0), ("y", 1)):
                cv = [p[i] for p in c.base]
                if (min(cv) < min(bbox[k]) - 1e-6
                        or max(cv) > max(bbox[k]) + 1e-6):
                    raise ValueError(
                        f"{name}: cut {c.name} {k}-range "
                        f"[{min(cv):g}, {max(cv):g}] outside the fill "
                        f"base's [{min(bbox[k]):g}, {max(bbox[k]):g}]")
        gross = Prism.volume_cf.fget(self)
        if sum(c.volume_cf for c in self.cuts) >= gross - 1e-9:
            raise ValueError(f"{name}: cuts consume the entire gross volume")

    @property
    def volume_cf(self) -> float:
        return (Prism.volume_cf.fget(self)
                - sum(c.volume_cf for c in self.cuts))

    def body_solids(self) -> list[dict]:
        return [{"kind": "fill", "units": "ft", "base": self.base,
                 "holes": self.holes, "z_bot": self.z_bot,
                 "z_top": self.z_top,
                 "cuts": [c.body_solids()[0] for c in self.cuts]}]


# ---------------------------------------------------------------- in. steel
class Plate:
    """A flat rectangular plate, optionally pierced for bolts (pipe-supports-pilot port).

    `holes_each` holes of `hole_dia_in` are punched through EVERY one of the
    `count` plates: the hole volume comes off the weight and the hole barrel
    joins the wetted (galvanized) surface.
    """

    def __init__(self, name: str, thickness_in: float, a_in: float, b_in: float,
                 count: int = 1, holes_each: int = 0,
                 hole_dia_in: float = 0.0) -> None:
        self.name = name
        self.count = count
        self.thickness_in = thickness_in
        self.a_in, self.b_in = a_in, b_in
        self.holes_each = holes_each
        self.hole_dia_in = hole_dia_in

    @property
    def hole_area_in2(self) -> float:
        r = self.hole_dia_in / 2.0
        return self.holes_each * math.pi * r * r

    @property
    def volume_in3(self) -> float:
        gross = self.thickness_in * self.a_in * self.b_in
        return self.count * (gross - self.hole_area_in2 * self.thickness_in)

    @property
    def surface_in2(self) -> float:
        t, a, b = self.thickness_in, self.a_in, self.b_in
        gross = 2 * (a * b + a * t + b * t)
        barrel = self.holes_each * math.pi * self.hole_dia_in * t
        return self.count * (gross - 2 * self.hole_area_in2 + barrel)

    @property
    def weight_lb(self) -> float:
        return self.volume_in3 * STEEL_LB_PER_IN3

    @property
    def volume_cf(self) -> float:
        return self.volume_in3 / IN3_PER_CF

    @property
    def surface_sf(self) -> float:
        return self.surface_in2 / 144.0


class ArcBand(Plate):
    """An annular-sector band wrapping a circular section (pipe-supports-pilot's SaddleBand,
    generalized: `inner_dia_in` replaces the casing coupling).

    volume_in3 is the exact closed form (arc length x width x thickness);
    faceted_volume_in3 is what an n-segment tessellation encloses, and the
    gate holds the two within tolerance.
    """

    def __init__(self, name: str, thickness_in: float, width_in: float,
                 inner_dia_in: float, wrap_deg: float, count: int = 1,
                 arc_segments: int = ARC_SEGMENTS,
                 start_deg: float = 180.0) -> None:
        self.name = name
        self.count = count
        self.thickness_in = thickness_in
        self.width_in = width_in
        self.r_inner_in = inner_dia_in / 2.0
        self.r_mean_in = self.r_inner_in + thickness_in / 2.0
        self.r_outer_in = self.r_inner_in + thickness_in
        self.wrap_deg = wrap_deg
        self.wrap_rad = math.radians(wrap_deg)
        self.arc_segments = arc_segments
        self.start_deg = start_deg

    @property
    def arc_length_in(self) -> float:
        return self.r_mean_in * self.wrap_rad

    @property
    def volume_in3(self) -> float:
        return self.count * self.arc_length_in * self.width_in * self.thickness_in

    @property
    def faceted_volume_in3(self) -> float:
        """Area of the faceted annulus sector, times width."""
        n = self.arc_segments
        half = self.wrap_rad / (2 * n)
        chord_area = n * math.sin(half) * math.cos(half) * (
            self.r_outer_in ** 2 - self.r_inner_in ** 2)
        return self.count * chord_area * self.width_in

    @property
    def surface_in2(self) -> float:
        inner = self.r_inner_in * self.wrap_rad * self.width_in
        outer = self.r_outer_in * self.wrap_rad * self.width_in
        ends = 2 * self.arc_length_in * self.thickness_in
        edges = 2 * self.thickness_in * self.width_in
        return self.count * (inner + outer + ends + edges)

    @property
    def weight_lb(self) -> float:
        return self.volume_in3 * STEEL_LB_PER_IN3


class ShapedStiffener(Plate):
    """A transverse diaphragm plate whose top edge is cut to a circular arc
    (pipe-supports-pilot's shaped stiffener, kept general: it fills the void between an
    outer radius `r_outer_in` about a centreline at `cl_in` and a floor).

    Every area is closed-form; `faceted_area_in2` is the shoelace area of the
    polygon the emitters actually carry, held within tolerance by the gate.
    """

    def __init__(self, name: str, thickness_in: float, r_outer_in: float,
                 cl_in: float, half_width_in: float, z_inner_in: float,
                 z_outer_in: float, y_step_in: float, pieces: int = 2,
                 arc_segments: int = ARC_SEGMENTS,
                 y_start_in: float = 0.0) -> None:
        self.y_start_in = y_start_in      # inner edge - e.g. a web face
        self.name = name
        self.count = pieces
        self.thickness_in = thickness_in
        self.r_outer_in = r_outer_in
        self.cl_in = cl_in
        self.half_width_in = half_width_in
        self.z_inner_in = z_inner_in      # floor for |y| <= y_step
        self.z_outer_in = z_outer_in      # floor beyond it
        self.y_step_in = y_step_in
        self.arc_segments = arc_segments

    @property
    def arc_rad(self) -> float:
        """Half-angle the shaped edge subtends, measured from the crown."""
        return math.asin(self.half_width_in / self.r_outer_in)

    def _under_arc(self, y: float) -> float:
        """Integral of (cl - sqrt(r^2 - t^2)) dt from 0 to y."""
        r = self.r_outer_in
        return self.cl_in * y - (y * math.sqrt(r * r - y * y) / 2.0
                                 + r * r / 2.0 * math.asin(y / r))

    @property
    def area_in2(self) -> float:
        """Closed-form area of ONE piece, from y_start out to half_width."""
        w, y0 = self.half_width_in, self.y_start_in
        under_arc = self._under_arc(w) - self._under_arc(y0)
        step = max(self.y_step_in, y0)
        floor = (self.z_inner_in * (step - y0)
                 + self.z_outer_in * (w - step))
        return under_arc - floor

    def profile(self, segments: int | None = None) -> list[tuple[float, float]]:
        """One piece's polygon, CCW, in (y, z - centreline) inches."""
        n = segments or self.arc_segments
        r, w, y0 = self.r_outer_in, self.half_width_in, self.y_start_in
        v_inner = self.z_inner_in - self.cl_in
        v_outer = self.z_outer_in - self.cl_in
        step = max(self.y_step_in, y0)
        pts = [(y0, v_inner)]
        # only emit the cope riser when there IS one; a flat floor would
        # otherwise repeat the same vertex and hand the IFC a degenerate ring.
        if step > y0 and abs(v_inner - v_outer) > 1e-12:
            pts += [(step, v_inner), (step, v_outer)]
        pts.append((w, v_outer))
        a0 = math.asin(y0 / r)
        for i in range(n + 1):
            a = a0 + (self.arc_rad - a0) * (1.0 - i / n)
            pts.append((r * math.sin(a), -r * math.cos(a)))
        return pts

    @property
    def faceted_area_in2(self) -> float:
        return poly_area(self.profile())

    @property
    def perimeter_in(self) -> float:
        r, w, y0 = self.r_outer_in, self.half_width_in, self.y_start_in
        a0 = math.asin(y0 / r)
        return ((w - y0)
                + abs(self.z_inner_in - self.z_outer_in)
                + (self.cl_in - r * math.cos(self.arc_rad) - self.z_outer_in)
                + r * (self.arc_rad - a0)
                + (self.cl_in - r * math.cos(a0) - self.z_inner_in))

    @property
    def volume_in3(self) -> float:
        return self.count * self.area_in2 * self.thickness_in

    @property
    def faceted_volume_in3(self) -> float:
        return self.count * self.faceted_area_in2 * self.thickness_in

    @property
    def surface_in2(self) -> float:
        return self.count * (2.0 * self.area_in2
                             + self.perimeter_in * self.thickness_in)

    @property
    def weight_lb(self) -> float:
        return self.volume_in3 * STEEL_LB_PER_IN3


class Bolt:
    """A bolt as a plain cylinder plus an allowance per nut (pipe-supports-pilot port —
    nuts are real weight the galvanizer dips and the buyer pays for)."""

    NUT_LB = 0.3
    NUT_IN2 = 4.5

    def __init__(self, name: str, diameter_in: float, length_in: float,
                 count: int = 1, nuts: int = 2) -> None:
        self.name, self.count = name, count
        self.diameter_in, self.length_in = diameter_in, length_in
        self.nuts = nuts

    @property
    def volume_in3(self) -> float:
        r = self.diameter_in / 2.0
        return self.count * math.pi * r * r * self.length_in

    @property
    def surface_in2(self) -> float:
        r = self.diameter_in / 2.0
        return self.count * (2 * math.pi * r * self.length_in + 2 * math.pi * r * r
                             + self.nuts * self.NUT_IN2)

    @property
    def weight_lb(self) -> float:
        return (self.volume_in3 * STEEL_LB_PER_IN3
                + self.count * self.nuts * self.NUT_LB)


# ------------------------------------------------------------------- rebar
# ASTM A615 bar properties: size -> (nominal diameter in, area sq in, lb/ft)
BAR_PROPS: dict[int, tuple[float, float, float]] = {
    3: (0.375, 0.11, 0.376),
    4: (0.500, 0.20, 0.668),
    5: (0.625, 0.31, 1.043),
    6: (0.750, 0.44, 1.502),
    7: (0.875, 0.60, 2.044),
    8: (1.000, 0.79, 2.670),
    9: (1.128, 1.00, 3.400),
    10: (1.270, 1.27, 4.303),
    11: (1.410, 1.56, 5.313),
}

_IN = 1.0 / 12.0


def _v_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _v_add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _v_mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _v_len(a):
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def _v_unit(a):
    n = _v_len(a)
    if n < 1e-12:
        raise ValueError("zero-length direction")
    return (a[0] / n, a[1] / n, a[2] / n)


def _v_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _v_cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _v_rotate(v, axis, angle):
    """Rotate vector `v` about a unit `axis` by `angle` (Rodrigues)."""
    c, s = math.cos(angle), math.sin(angle)
    return _v_add(_v_add(_v_mul(v, c),
                         _v_mul(_v_cross(axis, v), s)),
                  _v_mul(axis, _v_dot(axis, v) * (1.0 - c)))


def fillet_polyline(pts: list[tuple[float, float, float]], r: float):
    """Replace every interior corner of a polyline with a tangent circular arc.

    Returns (verts, segments, length) where `segments` is a list of
    ("line", i, j) / ("arc", i, j, k) into `verts` (0-based), and `length` is
    the EXACT centerline length through the arcs. This is the ONE place bar
    length is computed — the IFC directrix, the STEP sweep, the DXF and the
    bar schedule all consume this same output, so they cannot disagree
    (rebar-pilot single-source-centerline lesson).

    A 90 deg bend removes r from each adjacent straight and adds an arc of
    r*pi/2, i.e. it nets 2r - r*pi/2 = 0.4292r shorter than the square
    out-to-out dimensions - the usual bend deduction.
    """
    if len(pts) < 2:
        raise ValueError("a bar needs at least two points")
    if len(pts) == 2:
        return list(pts), [("line", 0, 1)], _v_len(_v_sub(pts[1], pts[0]))

    verts: list[tuple[float, float, float]] = [pts[0]]
    segs: list[tuple] = []
    length = 0.0

    for i in range(1, len(pts) - 1):
        P, A, B = pts[i], pts[i - 1], pts[i + 1]
        u = _v_unit(_v_sub(A, P))            # away from the corner, toward A
        v = _v_unit(_v_sub(B, P))            # away from the corner, toward B
        cosphi = max(-1.0, min(1.0, _v_dot(u, v)))
        phi = math.acos(cosphi)              # interior angle between the legs
        theta = math.pi - phi                # deflection angle of the bend
        if theta < 1e-9:                     # collinear, no bend
            continue
        if phi < 1e-9:
            raise ValueError("180 deg reversal cannot be filleted")
        t = r * math.tan(theta / 2.0)        # tangent setback from the corner

        # the fillet has to fit in both adjacent legs
        for nb, lbl in ((A, "previous"), (B, "next")):
            avail = _v_len(_v_sub(nb, P))
            if t > avail - 1e-9:
                raise ValueError(
                    f"bend radius {r * 12:.3f}in needs a {t * 12:.3f}in setback but the "
                    f"{lbl} leg is only {avail * 12:.3f}in"
                )

        T1 = _v_add(P, _v_mul(u, t))         # tangent point on the incoming leg
        T2 = _v_add(P, _v_mul(v, t))         # tangent point on the outgoing leg
        bis = _v_unit(_v_add(u, v))          # bisector, away from the corner
        C = _v_add(P, _v_mul(bis, r / math.sin(phi / 2.0)))     # arc centre
        M = _v_add(C, _v_mul(_v_unit(_v_add(_v_sub(T1, C), _v_sub(T2, C))), r))

        i0 = len(verts) - 1                  # the straight that arrives at T1
        verts.append(T1)
        segs.append(("line", i0, len(verts) - 1))
        length += _v_len(_v_sub(T1, verts[i0]))
        verts.append(M)
        verts.append(T2)
        segs.append(("arc", len(verts) - 3, len(verts) - 2, len(verts) - 1))
        length += r * theta

    i0 = len(verts) - 1
    verts.append(pts[-1])
    segs.append(("line", i0, len(verts) - 1))
    length += _v_len(_v_sub(pts[-1], verts[i0]))
    return verts, segs, length


def arc_points_3d(a, m, b, n: int):
    """`n` points along the circular arc a->b through m (excl a, incl b).

    a, m, b are three points on the arc (fillet_polyline's tangent-start /
    mid / tangent-end); this is the tessellation the STEP/DXF emitters use for
    a swept-disk bar, while the IFC emitter carries the same three points as an
    exact `IfcArcIndex`.
    """
    ab, ac = _v_sub(m, a), _v_sub(b, a)
    abXac = _v_cross(ab, ac)
    denom = 2.0 * _v_dot(abXac, abXac)
    if denom < 1e-18:                        # collinear -> a straight chord
        return [tuple(b)]
    to_center = _v_mul(
        _v_add(_v_mul(_v_cross(abXac, ab), _v_dot(ac, ac)),
               _v_mul(_v_cross(ac, abXac), _v_dot(ab, ab))), 1.0 / denom)
    center = _v_add(a, to_center)
    r = _v_len(to_center)
    u = _v_unit(_v_sub(a, center))           # angle-0 axis (points at a)
    w = _v_cross(_v_unit(abXac), u)          # in-plane perpendicular, unit
    two = 2.0 * math.pi

    def ang(p):
        d = _v_sub(p, center)
        return math.atan2(_v_dot(d, w), _v_dot(d, u)) % two

    aM, aB = ang(m) or two, ang(b)
    if aB <= aM:                             # ensure the sweep passes m before b
        aB += two
    return [_v_add(center, _v_add(_v_mul(u, r * math.cos(aB * i / n)),
                                  _v_mul(w, r * math.sin(aB * i / n))))
            for i in range(1, n + 1)]


def densify_directrix(verts, segments, arc_segments: int = 8):
    """A fillet_polyline (verts, segments) -> a plain centreline point list,
    each arc tessellated into `arc_segments` chords."""
    chain = [tuple(verts[segments[0][1]])]
    for seg in segments:
        if seg[0] == "line":
            chain.append(tuple(verts[seg[2]]))
        else:                                # ("arc", i, j, k) = start, mid, end
            chain.extend(arc_points_3d(verts[seg[1]], verts[seg[2]],
                                       verts[seg[3]], arc_segments))
    return chain


def swept_disk_mesh(verts, segments, radius: float, *, sides: int = 12,
                    arc_segments: int = 8):
    """Watertight triangle tube of `radius` swept along a fillet_polyline.

    Returns (verts, tris). Parallel-transport frames keep the ring from
    twisting through bends; both ends are capped. The STEP/DXF emitters build a
    solid from this; the IFC emitter uses the exact `IfcSweptDiskSolid` instead.
    Volume is ~= pi r^2 * centreline length (to the tessellation).
    """
    chain = densify_directrix(verts, segments, arc_segments)
    C = [chain[0]]
    for p in chain[1:]:
        if _v_len(_v_sub(p, C[-1])) > 1e-9:
            C.append(p)
    if len(C) < 2:
        raise ValueError("swept_disk needs a directrix of >= 2 distinct points")

    n = len(C)
    tang = []
    for i in range(n):
        if i == 0:
            t = _v_sub(C[1], C[0])
        elif i == n - 1:
            t = _v_sub(C[-1], C[-2])
        else:
            t = _v_sub(C[i + 1], C[i - 1])
        tang.append(_v_unit(t))

    ref = (0.0, 0.0, 1.0) if abs(_v_dot(tang[0], (0, 0, 1))) < 0.9 else (1.0, 0, 0)
    U = [_v_unit(_v_cross(tang[0], ref))]
    for i in range(1, n):                    # parallel transport the frame
        axis = _v_cross(tang[i - 1], tang[i])
        al = _v_len(axis)
        if al < 1e-9:
            U.append(U[-1])
        else:
            U.append(_v_rotate(U[-1], _v_mul(axis, 1.0 / al),
                               math.atan2(al, _v_dot(tang[i - 1], tang[i]))))

    mesh_verts, rings = [], []
    for i in range(n):
        w = _v_cross(tang[i], U[i])
        ring = []
        for j in range(sides):
            a = 2.0 * math.pi * j / sides
            p = _v_add(C[i], _v_add(_v_mul(U[i], radius * math.cos(a)),
                                    _v_mul(w, radius * math.sin(a))))
            ring.append(len(mesh_verts))
            mesh_verts.append(p)
        rings.append(ring)

    tris = []
    for i in range(n - 1):
        for j in range(sides):
            a, b = rings[i][j], rings[i][(j + 1) % sides]
            c, d = rings[i + 1][j], rings[i + 1][(j + 1) % sides]
            tris.append((a, b, d))
            tris.append((a, d, c))
    c0 = len(mesh_verts)
    mesh_verts.append(C[0])
    for j in range(sides):
        tris.append((c0, rings[0][(j + 1) % sides], rings[0][j]))
    c1 = len(mesh_verts)
    mesh_verts.append(C[-1])
    for j in range(sides):
        tris.append((c1, rings[-1][j], rings[-1][(j + 1) % sides]))
    return mesh_verts, tris


@dataclass
class Bar:
    """One physical reinforcing bar (feet; rebar-pilot port)."""

    mark: str
    host: str
    size: int
    pts: list                               # centerline polyline, feet
    bend_r: float                           # CENTERLINE bend radius, feet
    shape: str                              # "straight" | "L" | "U" | "profiled"
    note: str = ""

    @property
    def dia(self) -> float:
        return BAR_PROPS[self.size][0] * _IN

    @property
    def area(self) -> float:
        return BAR_PROPS[self.size][1] / 144.0        # sq ft

    @property
    def plf(self) -> float:
        return BAR_PROPS[self.size][2]

    @property
    def geom(self):
        return fillet_polyline(self.pts, self.bend_r)

    @property
    def length(self) -> float:
        return self.geom[2]

    @property
    def weight(self) -> float:
        return self.length * self.plf

    @property
    def n_bends(self) -> int:
        return sum(1 for s in self.geom[1] if s[0] == "arc")

    def body_solids(self) -> list[dict]:
        """One `swept_disk` solid: a disk of the bar radius swept along the
        filleted centreline. The IFC emitter carries this as an exact
        `IfcSweptDiskSolid` (a handful of entities, arcs included) instead of
        the ~6-entities-per-triangle mesh a bent bar used to fall back to."""
        verts, segs, _length = self.geom
        return [{"kind": "swept_disk", "units": "ft",
                 "verts": [tuple(v) for v in verts], "segments": segs,
                 "radius": self.dia / 2.0}]


def bar_stations(a: float, b: float, sp: float) -> list[float]:
    """Bar positions from a to b at spacing sp, centred in the span
    (rebar-pilot's `_stations`)."""
    span = b - a
    if span <= 0:
        return []
    n = int(math.floor(span / sp + 1e-9)) + 1
    off = (span - (n - 1) * sp) / 2.0
    return [a + off + i * sp for i in range(n)]


def profile_at(prof: list[tuple[float, float]], u: float) -> float:
    """Piecewise-linear profile lookup, clamped at both ends."""
    if u <= prof[0][0]:
        return prof[0][1]
    for (u0, v0), (u1, v1) in zip(prof, prof[1:]):
        if u <= u1:
            return v0 if u1 == u0 else v0 + (v1 - v0) * (u - u0) / (u1 - u0)
    return prof[-1][1]


@dataclass
class RebarBuilder:
    """Per-bar-type generation base (rebar-pilot pattern, generalized).

    Holds the shared reinforcement conventions — bar size, cover, spacing,
    ACI 318-19 minimum centreline bend radius (inside 3db for #3-#5 ->
    centreline 3.5db), hook extension — and the `bar()` factory every
    bar-type method uses so a family's rebar methods stay one-liners over a
    single source of geometry (`fillet_polyline`).
    """

    size: int
    cover_in: float
    spacing_in: float
    min_bend_inside_diameter_db: float = 6.0
    standard_hook_90_extension_db: float = 12.0
    bars: list = field(default_factory=list)

    @property
    def db(self) -> float:
        return BAR_PROPS[self.size][0] * _IN

    @property
    def bend_r(self) -> float:
        return (self.min_bend_inside_diameter_db / 2.0 + 0.5) * self.db

    @property
    def hook(self) -> float:
        return self.standard_hook_90_extension_db * self.db

    @property
    def axis_drop(self) -> float:
        """Face cover -> bar axis."""
        return self.cover_in * _IN + self.db / 2.0

    def bar(self, mark: str, host: str, pts: list, shape: str,
            note: str = "") -> Bar:
        b = Bar(mark=mark, host=host, size=self.size, pts=pts,
                bend_r=self.bend_r, shape=shape, note=note)
        self.bars.append(b)
        return b

    @property
    def total_weight_lb(self) -> float:
        return sum(b.weight for b in self.bars)

    @property
    def total_length_ft(self) -> float:
        return sum(b.length for b in self.bars)


# ------------------------------------------------------------ graded solids
# Promoted from Tools/bimforge_families/solids.py (#195): the vertical-case
# primitives (Prism/SectionPrism/BatteredWall) cannot express a member whose
# soffit slopes — a deck slab on tilted girders, or a precast unit set on two
# seats at different elevations, which is what a longitudinal grade does to a
# superstructure. All three emit the existing "mesh" kind.

class Prismatoid:
    """A solid lofted between a bottom ring and a top ring of 3D points.

    The two rings must have the same vertex count and plan winding; vertex i
    of the bottom lofts to vertex i of the top. Neither ring has to be
    horizontal — a constant-thickness deck on a graded girder line is a
    prismatoid, not a prism. ``area_sf`` is the bottom ring's plan area, so
    ``Height x GrossArea`` reproduces ``GrossVolume`` under the gate's
    lxw-volume invariant.
    """

    def __init__(self, name: str, bottom: list, top: list,
                 ifc: str = "IfcBuildingElementProxy",
                 layer: str | None = None, dims_ft: tuple | None = None) -> None:
        if len(bottom) != len(top):
            raise ValueError(
                f"{name}: bottom has {len(bottom)} points, top has {len(top)}")
        if len(bottom) < 3:
            raise ValueError(f"{name}: a ring needs at least three points")
        self.name = name
        self.bottom = [tuple(float(c) for c in p) for p in bottom]
        self.top = [tuple(float(c) for c in p) for p in top]
        self.ifc, self.layer, self.dims_ft = ifc, layer, dims_ft

    def _faces(self) -> list:
        return loft_faces([self.bottom, self.top])

    @property
    def area_sf(self) -> float:
        return abs(poly_area([(x, y) for x, y, _z in self.bottom]))

    @property
    def volume_cf(self) -> float:
        return face_volume(self._faces())

    @property
    def height_ft(self) -> float:
        a = self.area_sf
        return self.volume_cf / a if a > 1e-9 else 0.0

    def body_solids(self) -> list[dict]:
        verts: list = []
        index: dict = {}

        def vid(p):
            if p not in index:
                index[p] = len(verts)
                verts.append(tuple(float(c) for c in p))
            return index[p]

        tris = []
        for ring in self._faces():
            r = clean_ring(ring)
            if not r:
                continue
            # Ear-clip in the face's own plane (#315), keeping the
            # BatteredWall contract that the mesh volume IS volume_cf. A
            # Prismatoid's rings are a PLAN polygon lifted, so a re-entrant
            # plan -- an L-shaped pad -- fanned 164 sf of cap facets over a
            # 128 sf cap pair while volume_cf stayed exactly 64.0 cf.
            for i0, i1, i2 in triangulate_planar_face(r):
                tris.append((vid(r[i0]), vid(r[i1]), vid(r[i2])))
        plan = [[(x, y) for x, y, _z in self.bottom]]
        return [{"kind": "mesh", "units": "ft", "verts": verts,
                 "tris": _outward_tris(verts, tris), "plan": plan}]


class Affine:
    """Any mesh-emitting primitive moved by ``x' = lin @ x + off``.

    The one placement wrapper: a plan rotation and offset, a reflection, a
    grade shear, or any product of them (nest them, or build ``lin`` once).
    It moves the mesh AND the exact form the mesh carries (``place_exact``),
    so a ``SectionPrism`` placed this way is still one IfcExtrudedAreaSolid
    — where a hand-rolled wrapper that only rewrites ``verts`` leaves a stale
    exact form behind and is written as the mesh it made (``exact_of``). A
    map that skews the profile plane, or anything applied to an alignment
    sweep, drops to the mesh the same way.

    Only maps that keep every quantity the inner declares are accepted: a
    plan isometry (rotation, reflection, offset) with z sheared by plan
    position — ``lin = [[a, b, 0], [c, d, 0], [gx, gy, 1]]`` with
    ``[[a, b], [c, d]]`` orthogonal. That moves no material and keeps plan
    footprints, plan lengths, vertical heights and vertical sections, so
    ``area_sf`` / ``volume_cf`` / ``length_ft`` / ``height_ft`` pass through
    exactly. A unit determinant alone would not: ``diag(2, 1, 0.5)`` keeps
    volume but doubles a footprint and halves a height. Only mesh solids can
    be moved — a "prism" dict is a vertical extrusion off a flat base, so
    wrapping one raises rather than silently emitting it unmoved.
    """

    def __init__(self, inner, lin, off=(0.0, 0.0, 0.0)) -> None:
        self.inner = inner
        self.lin = tuple(tuple(float(c) for c in row) for row in lin)
        self.off = tuple(float(c) for c in off)
        where = f"{getattr(inner, 'name', inner)}: {type(self).__name__}"
        if len(self.lin) != 3 or any(len(r) != 3 for r in self.lin) \
                or len(self.off) != 3:
            raise ValueError(f"{where} takes a 3x3 lin and a 3-vector off")
        if not all(math.isfinite(c) for c in sum(self.lin, self.off)):
            raise ValueError(f"{where}: the map has a non-finite entry")
        (a, b, c), (d, e, f), (_g, _h, i) = self.lin
        tol = 1e-9
        if not (abs(c) <= tol and abs(f) <= tol and abs(i - 1.0) <= tol
                and abs(a * a + d * d - 1.0) <= tol
                and abs(b * b + e * e - 1.0) <= tol
                and abs(a * b + d * e) <= tol):
            raise ValueError(
                f"{where} takes a plan isometry with z sheared by plan "
                f"position only (lin = [[a, b, 0], [c, d, 0], [gx, gy, 1]], "
                f"[[a, b], [c, d]] orthogonal) — any other map changes a "
                f"declared area, length or height; got {self.lin}")
        self._det = a * e - b * d          # +1 rotation, -1 reflection

    @classmethod
    def placed(cls, inner, origin=(0.0, 0.0, 0.0), angle_deg: float = 0.0,
               grade: float = 0.0, along: str = "y") -> "Affine":
        """`inner` graded, then rotated in plan and set at `origin`.

        z rises ``grade`` ft/ft along the inner's own `along` axis ("x" or
        "y"), then the plan turns ``angle_deg`` counter-clockwise and the
        inner's origin lands on `origin` — a girder set on two seats at
        different elevations, a barrier on a straight line of layout.
        """
        if along not in ("x", "y"):
            raise ValueError(f"along must be 'x' or 'y', got {along!r}")
        c, s = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))
        gx, gy = (grade, 0.0) if along == "x" else (0.0, grade)
        return cls(inner, ((c, -s, 0.0), (s, c, 0.0), (gx, gy, 1.0)), origin)

    def __getattr__(self, name):        # area_sf, volume_cf, ifc, layer, ...
        return getattr(self.inner, name)

    def body_solids(self) -> list[dict]:
        lin, off = self.lin, self.off
        out = []
        for s in self.inner.body_solids():
            if s.get("kind") != "mesh":
                raise TypeError(
                    f"{getattr(self.inner, 'name', self.inner)}: "
                    f"{type(self).__name__} needs a mesh solid, got "
                    f"{s.get('kind')!r}")
            d = place_exact(s, lin, off)
            d["verts"] = [tuple(lin[r][0] * x + lin[r][1] * y + lin[r][2] * z
                                + off[r] for r in range(3))
                          for x, y, z in s["verts"]]
            if self._det < 0:
                # reflection reverses winding; flip it back so the shell
                # faces out
                d["tris"] = [(a, c, b) for a, b, c in s["tris"]]
            if s.get("plan"):
                # x', y' depend on x, y alone: the footprint moves with it
                d["plan"] = [[(lin[0][0] * x + lin[0][1] * y + off[0],
                               lin[1][0] * x + lin[1][1] * y + off[1])
                              for x, y in ring] for ring in s["plan"]]
            out.append(d)
        return out


class MirrorX(Affine):
    """Any mesh-emitting primitive reflected about ``x = 0``.

    Caltrans compound sections are HANDED, so the same section serves both
    edges of a deck only if one is mirrored. Mirroring the emitted mesh (not
    the input profile) keeps one code path for builders whose profiles are made
    internally and never handed back. Reflection is an isometry, so ``area_sf``
    / ``volume_cf`` pass through.
    """

    def __init__(self, inner) -> None:
        super().__init__(inner, ((-1.0, 0.0, 0.0), (0.0, 1.0, 0.0),
                                 (0.0, 0.0, 1.0)))


class ShearedZ(Affine):
    """Any mesh-emitting primitive with ``z`` sheared linearly along ``y``.

    A precast box girder set on two seats at different elevations is the SAME
    section along its length, so tilting it by shearing the emitted mesh avoids
    re-deriving the section's ring/void geometry to move one coordinate. Shear
    is volume-preserving (Cavalieri), so ``area_sf`` / ``volume_cf`` pass
    through exactly. An extrusion along y shears to an oblique extrusion:
    same profile plane, tilted sweep vector.
    """

    def __init__(self, inner, slope: float, y_ref: float = 0.0) -> None:
        self.slope, self.y_ref = float(slope), float(y_ref)
        super().__init__(inner, ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0),
                                 (0.0, self.slope, 1.0)),
                         (0.0, 0.0, -self.slope * self.y_ref))
