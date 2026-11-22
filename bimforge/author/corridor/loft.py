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

from bimforge.author.alignment import poly_area
from bimforge.author.corridor.frame import survey_point
from bimforge.author.primitives import (_outward_tris, _signed_area2,
                                        clean_ring, ear_clip, face_volume)
from bimforge.author.sweep import SweptSection, _seg_dist, ring_centroid, to_model


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
        return abs(face_volume(self._faces()))

    @property
    def mean_width_ft(self) -> float:
        return sum(max(u for u, _v in r) - min(u for u, _v in r)
                   for r in self.rings) / len(self.rings)

    @property
    def average_end_area_cf(self) -> float:
        """The volume by average end areas, each bay lengthened by the plan
        curvature at the rings' centroid (Pappus) and by the grade: a figure
        independent of the mesh, for the gate to hold the mesh to."""
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
