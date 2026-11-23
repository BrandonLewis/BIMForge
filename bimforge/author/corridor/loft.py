"""StationLoft: a closed solid through one (u, v) ring per station along an
alignment (roadmap P.6), the road corridor's course body.

The sweep engine's SweptSection sweeps ONE section; a corridor's changes
with width transitions and superelevation, so each station brings its own
ring, with the same vertex count at every station. Rings sit in the
corridor frame (corridor.frame), the plane IFC4.3 places an
IfcSectionedSolidHorizontal's sections in, so on IFC4X3 the loft is written
as that solid (one profile per station) and as its mesh everywhere else.
The stations are the caller's: densify them (frame.densify) so the mesh's
chords stay on the curve the IFC solid follows.
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass

from bimforge.author.alignment import poly_area
from bimforge.author.corridor.frame import survey_point
from bimforge.author.primitives import (_outward_tris, _signed_area2,
                                        clean_ring, ear_clip, face_volume)
from bimforge.author.sweep import SweptSection, _seg_dist, ring_centroid, to_model

#: Gauss-Legendre nodes and weights on [-1, 1], 5 points: exact for a
#: polynomial of degree 9 in station, ample for a bay's blended ring (area
#: quadratic, first moments cubic) in a frame constant on an arc
_GAUSS = ((-0.9061798459386640, 0.2369268850561891),
          (-0.5384693101056831, 0.4786286704993665),
          (0.0, 0.5688888888888889),
          (0.5384693101056831, 0.4786286704993665),
          (0.9061798459386640, 0.2369268850561891))


def _moments(ring: list) -> tuple:
    """(area, first moment in u, first moment in v) of a (u, v) ring wound
    counterclockwise."""
    a = qu = qv = 0.0
    for (u0, v0), (u1, v1) in zip(ring, ring[1:] + ring[:1]):
        cr = u0 * v1 - u1 * v0
        a += cr
        qu += (u0 + u1) * cr
        qv += (v0 + v1) * cr
    return a / 2.0, qu / 6.0, qv / 6.0


@dataclass(frozen=True)
class Pappus:
    volume_cf: float       # the exact volume of the lofts together
    path_ft: float         # the 3D length of their centroid's line
    offset_ft: float       # that line's offset, left positive
    height_ft: float       # its height above the profile grade line


def pappus(lofts: list) -> Pappus:
    """The exact volume of `lofts` (StationLofts on the same stations) and
    the path of their combined centroid.

    In the corridor frame (frame.survey_point: N the horizontal left normal,
    T3 the 3D tangent, B the section's up axis) a section point moves along
    T3 at J = sqrt(1 + g^2) - kappa cos(gamma) u - gamma' v, the Jacobian of
    (s, u, v), so the volume is the integral over station of A sqrt(1 + g^2)
    - kappa cos(gamma) Qu - gamma' Qv (A, Qu, Qv the blended ring's area and
    first moments). The centroid's line, held at the band's area-weighted
    mean (u, v) parallel to the profile grade line, has speed |P'|: its T3
    part is J at (u, v), plus kappa u sin(gamma) along B and -kappa v
    sin(gamma) along N. Both by 5-point Gauss-Legendre per bay, on the rings
    blended as IFC blends them (ring_at): within a bay A is quadratic and
    the moments cubic in station, and kappa and the grade's rate constant,
    since the stations hold every geometry point."""
    first = lofts[0]
    al, prof, ss = first.alignment, first.profile, first.stations
    if any(lf.stations != ss for lf in lofts[1:]):
        raise ValueError(f"{first.name}: pappus needs lofts on the same stations")
    nodes = []
    for i, (a, b) in enumerate(zip(ss, ss[1:])):
        h = b - a
        # grade() is the left limit at a shared station: sample inside. A
        # bay never straddles a vertical curve's end, so its grade changes
        # linearly across it
        eps = 1e-9 * h
        gp = (prof.grade(b - eps) - prof.grade(a + eps)) / h
        pairs = [(lf.rings[i], lf.rings[i + 1]) for lf in lofts]
        for x, w in _GAUSS:
            t = 0.5 * (1.0 + x)
            s = a + h * t
            area = qu = qv = 0.0
            for ra, rb in pairs:
                da, du, dv = _moments([(ua + t * (ub - ua), va + t * (vb - va))
                                       for (ua, va), (ub, vb) in zip(ra, rb)])
                area, qu, qv = area + da, qu + du, qv + dv
            g = prof.grade(s)
            nodes.append((0.5 * h * w, area, qu, qv, al.curvature(s), g,
                          gp / (1.0 + g * g)))
    weight = sum(n[0] * n[1] for n in nodes)
    ub = sum(n[0] * n[2] for n in nodes) / weight
    vb = sum(n[0] * n[3] for n in nodes) / weight
    volume = path = 0.0
    for dw, area, qu, qv, k, g, dgam in nodes:
        root = math.sqrt(1.0 + g * g)
        cg, sg = 1.0 / root, g / root
        volume += dw * (area * root - k * cg * qu - dgam * qv)
        along = root - k * cg * ub - dgam * vb
        path += dw * math.sqrt(along ** 2 + (k * ub * sg) ** 2
                               + (k * vb * sg) ** 2)
    return Pappus(volume, path, ub, vb)


def centroid_path(lofts: list, h: float = 0.01) -> Pappus:
    """pappus, the centroid's line following the blended rings' own
    centroid at each station rather than held parallel to the profile
    grade line: a path course rises and falls on its own profile and
    drifts with its separation (V1.2 C). The volume is pappus's exact one;
    the path is 5-point Gauss-Legendre per bay of the centroid's speed, the
    chord of its survey points over station +/- h, as path.cos_theta takes
    the paved centre's tangent (so a course's depth, thickness / cos theta,
    and its centroid's line read the same tangent); h is held to 0.04 of a
    short bay, so the chord stays inside it (the outer nodes sit 0.047 of
    a bay in). Offset and height are the centroid's area-weighted means."""
    first = lofts[0]
    al, prof, ss = first.alignment, first.profile, first.stations
    if any(lf.stations != ss for lf in lofts[1:]):
        raise ValueError(f"{first.name}: centroid_path needs lofts on the same "
                         f"stations")
    volume = pappus(lofts).volume_cf
    path = weight = usum = vsum = 0.0
    for i, (a, b) in enumerate(zip(ss, ss[1:])):
        bay = b - a
        pairs = [(lf.rings[i], lf.rings[i + 1]) for lf in lofts]

        def centroid(t, pairs=pairs):
            area = qu = qv = 0.0
            for ra, rb in pairs:
                da, du, dv = _moments([(ua + t * (ub - ua), va + t * (vb - va))
                                       for (ua, va), (ub, vb) in zip(ra, rb)])
                area, qu, qv = area + da, qu + du, qv + dv
            return area, qu / area, qv / area

        d = min(h, 0.04 * bay)
        dt = d / bay
        for x, w in _GAUSS:
            t = 0.5 * (1.0 + x)
            area, u, v = centroid(t)
            p0 = survey_point(al, prof, a + bay * t - d, *centroid(t - dt)[1:])
            p1 = survey_point(al, prof, a + bay * t + d, *centroid(t + dt)[1:])
            speed = math.dist(p0, p1) / (2.0 * d)
            dw = 0.5 * bay * w
            path += dw * speed
            weight += dw * area
            usum += dw * area * u
            vsum += dw * area * v
    return Pappus(volume, path, usum / weight, vsum / weight)


class StationLoft:
    """Rings `rings[i]` at `stations[i]`, lofted point to point and capped."""

    #: the sweep engine's frame, which the borrowed measures below read
    frame = "normal"
    camber = None

    def __init__(self, name: str, alignment, profile, origin, stations: list,
                 rings: list, ifc: str = "IfcBuildingElementProxy",
                 layer: str | None = None) -> None:
        if profile is None:
            raise ValueError(f"{name}: a station loft needs a vertical profile")
        if len(stations) < 2 or len(stations) != len(rings):
            raise ValueError(f"{name}: needs one ring per station, at least two")
        if any(b <= a for a, b in zip(stations, stations[1:])):
            raise ValueError(f"{name}: stations must be strictly ascending")
        counts = {len(r) for r in rings}
        if len(counts) != 1 or min(counts) < 3:
            raise ValueError(f"{name}: every ring needs the same vertex count, "
                             f"at least three")
        rings = [[(float(u), float(v)) for u, v in r] for r in rings]
        # one winding for all, so vertex j still meets vertex j: reversing
        # one ring alone would loft it against its neighbours back to front
        wind = [_signed_area2(r) for r in rings]
        if any(w <= 0.0 for w in wind) and any(w > 0.0 for w in wind):
            raise ValueError(f"{name}: every ring must wind the same way, "
                             f"vertex for vertex")
        if wind[0] < 0.0:
            rings = [r[::-1] for r in rings]
        self.name, self.ifc, self.layer = name, ifc, layer
        #: what model_alignments finds the loft's IfcAlignment by
        self.alignment, self.profile, self.origin = alignment, profile, origin
        self.stations = [float(s) for s in stations]
        self.rings = rings
        self.s0, self.s1 = self.stations[0], self.stations[-1]
        self._verts = None

    # ------------------------------------------------------------- geometry
    def _world(self, i: int) -> list:
        s = self.stations[i]
        return [to_model(self.origin,
                         *survey_point(self.alignment, self.profile, s, u, v))
                for u, v in self.rings[i]]

    def _faces(self) -> list:
        world = [self._world(i) for i in range(len(self.stations))]
        faces = []
        for i0, i1, i2 in ear_clip(self.rings[0]):
            faces.append([world[0][i2], world[0][i1], world[0][i0]])
        for i0, i1, i2 in ear_clip(self.rings[-1]):
            faces.append([world[-1][i0], world[-1][i1], world[-1][i2]])
        m = len(self.rings[0])
        for wa, wb in zip(world, world[1:]):
            for j in range(m):
                k = (j + 1) % m
                a, b, c, d = wa[j], wa[k], wb[k], wb[j]
                # the 4-fan through the quad's centroid, as SweptSection
                # lofts: a twisted quad's flux is the mean of its diagonals
                mid = tuple((a[x] + b[x] + c[x] + d[x]) / 4.0 for x in range(3))
                faces += [[a, b, mid], [b, c, mid], [c, d, mid], [d, a, mid]]
        return faces

    def _plan_ring(self) -> list:
        """The footprint: the left edge out, the right edge back."""
        left, right = [], []
        for s, ring in zip(self.stations, self.rings):
            for pick, out in ((max, left), (min, right)):
                u, v = pick(ring, key=lambda p: p[0])
                x, y, _z = to_model(self.origin, *survey_point(
                    self.alignment, self.profile, s, u, v))
                out.append((x, y))
        return left + right[::-1]

    def ifc_sections(self) -> list[dict]:
        """[{"s", "outer", "voids"}]: the IFC cross-sections, one per station,
        (u, v) in the section plane as emit_ifc._sectioned_solid reads them."""
        return [{"s": s, "outer": list(ring), "voids": []}
                for s, ring in zip(self.stations, self.rings)]

    def body_solids(self) -> list[dict]:
        verts: list = []
        index: dict = {}

        def vid(p):
            # SweptSection's weld: round-9 matches clean_ring's 1e-9
            key = (round(p[0], 9), round(p[1], 9), round(p[2], 9))
            if key not in index:
                index[key] = len(verts)
                verts.append((float(p[0]), float(p[1]), float(p[2])))
            return index[key]

        tris = []
        for ring in self._faces():
            r = clean_ring(ring)
            if not r:
                continue
            for b, c in zip(r[1:], r[2:]):
                tris.append((vid(r[0]), vid(b), vid(c)))
        self._verts = list(verts)
        return [{"kind": "mesh", "units": "ft", "verts": verts,
                 "tris": _outward_tris(verts, tris), "plan": [self._plan_ring()],
                 "exact": {"kind": "sectioned", "sweep": self,
                           "alignment": self.alignment, "vprofile": self.profile,
                           "origin": self.origin,
                           "sections": self.ifc_sections()}}]

    def mesh_is_exact(self, verts) -> bool:
        """Whether `verts` are still this loft's own mesh (primitives.exact_of):
        anything that edits them is written as the mesh it made."""
        return self._verts is not None and [tuple(p) for p in verts] == self._verts

    # ------------------------------------------------- exact-solid residual
    # What gate._ifc_exact_sweep_check measures a drawn IFC solid with. The
    # station lookup, the section-plane mapping and the cap and wall
    # measures read only the alignment, profile, origin, s0/s1 and the frame,
    # which a loft shares with a "normal" sweep, so they are SweptSection's
    # own rather than copies; only the ring a point is measured against
    # differs (it changes with station here).
    _station_of = SweptSection._station_of
    _survey = SweptSection._survey
    _section_coords = SweptSection._section_coords
    wall_area_sf = SweptSection.wall_area_sf
    cap_station_error_ft = SweptSection.cap_station_error_ft
    CAP_WINDOW_FT = SweptSection.CAP_WINDOW_FT

    def ring_at(self, s: float) -> list:
        """The (u, v) ring at station s: blended linearly, vertex for vertex,
        between the stations either side, as IFC blends an
        IfcSectionedSolidHorizontal's profiles; the end ring past either end."""
        ss = self.stations
        i = min(max(bisect.bisect_right(ss, s) - 1, 0), len(ss) - 2)
        t = min(max((s - ss[i]) / (ss[i + 1] - ss[i]), 0.0), 1.0)
        return [(ua + t * (ub - ua), va + t * (vb - va))
                for (ua, va), (ub, vb) in zip(self.rings[i], self.rings[i + 1])]

    def surface_residual_ft(self, points,
                            margin: float = 1.0) -> tuple[float, float, float]:
        """(max distance to the lofted surface, min station, max station) over
        model-frame points (feet), as SweptSection.surface_residual_ft: each
        point is taken to its section plane, then measured in (u, v) against
        the ring blended at its station. An engine draws the caps from the
        rings' own vertices, so those lie on the boundary too."""
        worst, s_min, s_max = 0.0, math.inf, -math.inf
        for x, y, z in points:
            s, u, v = self._section_coords(x, y, z, margin)
            s_min, s_max = min(s_min, s), max(s_max, s)
            r = self.ring_at(s)
            worst = max(worst, min(_seg_dist(u, v, a, b)
                                   for a, b in zip(r, r[1:] + r[:1])))
        return worst, s_min, s_max

    # ----------------------------------------------------------- quantities
    @property
    def length_ft(self) -> float:
        return self.s1 - self.s0

    @property
    def volume_cf(self) -> float:
        """The exact volume of the solid IFC4X3 describes (pappus): what the
        corridor declares, as the kernel's sweeps declare their closed form."""
        return pappus([self]).volume_cf

    @property
    def faceted_volume_cf(self) -> float:
        """The chorded mesh's volume, held to volume_cf by the pre gate's
        arc-faceting check."""
        return abs(face_volume(self._faces()))

    @property
    def widths_ft(self) -> list:
        """Each station's ring width, its u extent, feet."""
        return [max(u for u, _v in r) - min(u for u, _v in r) for r in self.rings]

    @property
    def mean_width_ft(self) -> float:
        """The ring width's mean over the loft's length: each bay's mean
        width weighted by its length, so densified bays of unequal length
        do not tilt it."""
        w, ss = self.widths_ft, self.stations
        return sum(0.5 * (a + b) * (s1 - s0) for a, b, s0, s1
                   in zip(w, w[1:], ss, ss[1:])) / (self.s1 - self.s0)

    @property
    def average_end_area_cf(self) -> float:
        """The volume by average end areas, each bay lengthened by the plan
        curvature at the rings' centroid (Pappus) and by the grade: a figure
        independent of the exact volume (pappus), for the stated
        quantity to hold it to."""
        out = 0.0
        for i in range(len(self.stations) - 1):
            a, b = self.stations[i], self.stations[i + 1]
            mid = 0.5 * (a + b)
            # curvature is left-positive (Alignment.curvature): a centroid
            # left of a left curve runs short, left of a right curve long
            k = self.alignment.curvature(mid)
            g = self.profile.grade(mid)
            area = 0.5 * (poly_area(self.rings[i]) + poly_area(self.rings[i + 1]))
            ubar = 0.5 * (ring_centroid(self.rings[i])[0]
                          + ring_centroid(self.rings[i + 1])[0])
            out += area * (b - a) * (1.0 - k * ubar) * math.sqrt(1.0 + g * g)
        return out
