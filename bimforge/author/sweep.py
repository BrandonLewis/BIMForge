"""author.sweep: a constant (x, z) section swept along an Alignment
(R13a; spec docs/superpowers/specs/2026-08-18-r13-sweep-engine-bridge-design.md).

Section coordinates: x positive to the LEFT of travel (the "Lt" /
`left_normal` direction), z up, origin on the directrix. Declared
quantities follow the kernel's closed-form-vs-facet discipline: plumb
frames declare Pappus (gate-checked against the faceted loft); normal
frames and skewed ends on arcs declare `face_volume` of the emitted
solid (the BatteredWall precedent).
"""
from __future__ import annotations

import math

from bimforge.author.alignment import poly_area, sta
from bimforge.author.primitives import (
    FACET_TOLERANCE, _orient, _outward_tris, _wound, clean_ring, ear_clip,
    face_volume, keyhole_ring, profile_at)

#: Max facet step for BOTH plan-arc angle and roll-angle change per bay.
#: The chorded loft's per-bay defect is 1 - sinc(delta) ~= delta^2/6 for
#: a plan arc (measured to 7 digits; Task-5 review proved facet/exact ==
#: sin(delta)/delta exactly) and the same delta^2/6 for a roll-twist bay
#: (pinch (1 - cos delta)/3), so one bound serves both at the
#: FACET_TOLERANCE/4 stacking budget: delta <= sqrt(1.5 * tol). An
#: earlier sqrt(6 * tol) came from a wrong 1 - sinc(delta/2) derivation
#: and let a max-step arc alone consume the whole band (review-caught).
MAX_ARC_STEP_RAD = math.sqrt(1.5 * FACET_TOLERANCE)
#: Max parabola/chord sagitta inside vertical curves (shape fidelity;
#: plumb-mode volume is shear-exact regardless).
VC_SAGITTA_FT = 0.01


def ring_centroid(ring: list) -> tuple[float, float]:
    """Area centroid of a 2D ring, shifted to the first vertex (the
    same float64-cancellation insurance _signed_area2 carries)."""
    x0, y0 = ring[0]
    a2 = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        u1, v1 = x1 - x0, y1 - y0
        u2, v2 = x2 - x0, y2 - y0
        cr = u1 * v2 - u2 * v1
        a2 += cr
        cx += (u1 + u2) * cr
        cy += (v1 + v2) * cr
    if abs(a2) < 1e-12:
        raise ValueError("degenerate ring has no centroid")
    return x0 + cx / (3.0 * a2), y0 + cy / (3.0 * a2)


def ring_self_intersects(ring: list) -> bool:
    """Do any two non-adjacent edges of the closed ring properly cross?

    A bowtie section is the one degeneracy NOTHING downstream catches:
    `poly_area` takes the lobes' signed DIFFERENCE and `ear_clip`'s
    triangle sum reproduces that same net, so the declared Pappus volume
    and its faceted counterpart AGREE on a fiction — measured 300.0 cf
    both ways for [(0,0),(3,3),(3,0),(0,1)] over a 100 ft tangent. The
    gate's closed-form-vs-facet pair therefore cannot see it (Task-8
    probe, correcting the Task-3 review's assumption that the gate was
    the backstop), which leaves refuse-early as the only defense.
    """
    n = len(ring)
    for i in range(n):
        a, b = ring[i], ring[(i + 1) % n]
        for j in range(i + 1, n):
            if j == (i + 1) % n or i == (j + 1) % n:
                continue                      # edges share a vertex
            c, d = ring[j], ring[(j + 1) % n]
            d1, d2 = _orient(a, b, c), _orient(a, b, d)
            d3, d4 = _orient(c, d, a), _orient(c, d, b)
            if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
                return True
    return False


def net_area_centroid(outer: list,
                      voids: list | None) -> tuple[float, float, float]:
    """(area, x_bar, z_bar) of the keyholed net section: outer minus
    voids, centroid area-weighted the same way.

    Precondition: voids disjoint and strictly inside outer;
    keyhole_ring / ear_clip refuse violations downstream."""
    a = poly_area(outer)
    x, z = ring_centroid(outer)
    an, ax, az_ = a, a * x, a * z
    for v in voids or []:
        av = poly_area(v)
        vx, vz = ring_centroid(v)
        an -= av
        ax -= av * vx
        az_ -= av * vz
    if an <= 1e-12:
        raise ValueError("voids consume the whole section")
    return an, ax / an, az_ / an


def _seg_dist(px: float, pz: float, a: tuple, b: tuple) -> float:
    """Distance from (px, pz) to the segment a-b."""
    dx, dz = b[0] - a[0], b[1] - a[1]
    ll = dx * dx + dz * dz
    t = 0.0 if ll == 0.0 else max(0.0, min(1.0, ((px - a[0]) * dx
                                                  + (pz - a[1]) * dz) / ll))
    return math.hypot(px - a[0] - t * dx, pz - a[1] - t * dz)


def to_model(origin, n: float, e: float, z: float = 0.0) -> tuple:
    """Survey (northing, easting, elevation) -> model-frame (x, y, z).

    THE single conversion point between the survey frame an `Alignment`
    speaks and the model frame every emitter reads. Two things happen here,
    and getting either wrong is invisible to the volume gates (issue #156):

    * **Axis order.** The house frame is x=EAST, y=NORTH — fixed by
      `ProjectContext.local(e, n, z)` and by `kml.lonlat`, which maps
      `base_e + x*Scale` / `base_n + y*Scale`. An `Alignment` speaks
      (northing, easting), so the pair MUST be swapped on the way in.
      Emitting them unswapped mirrored the model about the 45 deg diagonal:
      an alignment declared N 10-00-00 E rendered at 80 deg azimuth.

    * **Origin.** Coordinates are made LOCAL to the project base. Survey
      coordinates baked into vertices put geometry millions of feet from the
      origin, where a viewer's default view never frames it and single
      precision loses resolution — the datum belongs in IfcMapConversion,
      not in every vertex.

    `origin` is a `ProjectContext` (anything exposing `.local(e, n, z)`).
    None means "already local": the swap still applies, because the axis
    order is a property of the frame, not of where the origin sits.
    """
    if origin is None:
        return e, n, z
    return origin.local(e, n, z)


def _unit_az(az_deg: float) -> tuple[float, float]:
    """Survey azimuth -> unit (d_north, d_east)."""
    a = math.radians(az_deg)
    return math.cos(a), math.sin(a)


def to_model_dir(dn: float, de: float) -> tuple:
    """A survey DIRECTION (d_north, d_east) -> model (dx, dy).

    The axis swap ALONE. A direction rotates but never translates, so
    pushing one through `to_model` would add the project base to a unit
    vector — a mistake that survives every volume check, because it moves
    members without changing their size. Named separately so the two cases
    cannot be confused at the call site.
    """
    return de, dn


def to_model_elev(origin, elev: float) -> float:
    """An absolute elevation -> model z: the vertical half of `to_model`."""
    return elev if origin is None else to_model(origin, 0.0, 0.0, elev)[2]


class SweptSection:
    """A constant (x, z) net section swept from station `s0` to `s1`
    along an `Alignment`, with optional vertical `profile` (author
    Profile), superelevation `roll` [(s, cross_slope_ft_per_ft)],
    additive `camber` [(s, ordinate_ft)], keyholed `voids`, frame mode
    "plumb" (default) or "normal", and `end_skew` degrees at (s0, s1)
    shearing the end sections along the local plan tangent.

    Declared volume: closed-form Pappus in plumb mode (gate-checked
    against `faceted_volume_cf`); `face_volume` of the emitted loft in
    normal mode or when a skewed end lands on an arc (BatteredWall
    precedent - declared-from-faces, so mesh and Qto cannot disagree).
    Roll tables are converted to angles phi = atan(slope) at the
    breakpoints and interpolated LINEARLY IN ANGLE - that is what makes
    the roll-transition Pappus integral closed-form.
    """

    def __init__(self, name: str, section: list, alignment, s0: float,
                 s1: float, profile=None, roll=None, camber=None,
                 voids=None, frame: str = "plumb",
                 end_skew: tuple = (0.0, 0.0),
                 ifc: str = "IfcBuildingElementProxy",
                 layer: str | None = None, origin=None) -> None:
        if s1 <= s0:
            raise ValueError(f"{name}: s1 must exceed s0")
        if frame not in ("plumb", "normal"):
            raise ValueError(f"{name}: frame must be 'plumb' or 'normal'")
        for sk in end_skew:
            if abs(sk) >= 60.0:
                raise ValueError(
                    f"{name}: end skew {sk:g} deg has no usable shear "
                    f"(tan grows without bound); split the deck instead")
        # A point at section offset xp spans ds + xp*(tan sk1 - tan sk0), so
        # the planes close on each other at the RELATIVE shear, not the sum
        # of the two: parallel ends (equal skews) never cross however short
        # the run, while opposed ends cross twice as fast (Copilot PR-141).
        # max hypot(x, z) bounds |xp| under any roll rotation.
        reach = abs(math.tan(math.radians(end_skew[1]))
                    - math.tan(math.radians(end_skew[0]))) * max(
                        math.hypot(x, z) for x, z in section)
        if reach >= (s1 - s0) - 1e-9:
            raise ValueError(
                f"{name}: skewed end planes cross inside the run - relative "
                f"shear reach {reach:g} ft meets or exceeds the {s1 - s0:g} "
                f"ft run; the loft would self-intersect and both the closed "
                f"form and the facet volume would be silently wrong")
        msgs = alignment.kink_check(s0, s1)
        if msgs:
            raise ValueError("; ".join(msgs))
        for lbl, tab in (("roll", roll), ("camber", camber)):
            if tab is None:
                continue
            ss = [p[0] for p in tab]
            if ss != sorted(ss) or len(ss) != len(set(ss)):
                raise ValueError(
                    f"{name}: {lbl} table stations must be strictly ascending")
            if ss[0] > s0 + 1e-9 or ss[-1] < s1 - 1e-9:
                raise ValueError(
                    f"{name}: {lbl} table must cover [{sta(s0)}, {sta(s1)}]")
        self.name = name
        self.section = [tuple(map(float, p)) for p in section]
        self.voids = [[tuple(map(float, q)) for q in v] for v in (voids or [])]
        self.alignment, self.s0, self.s1 = alignment, float(s0), float(s1)
        self.profile = profile
        self.camber = list(camber) if camber else None
        self._phi = ([(s, math.atan(v)) for s, v in roll] if roll else None)
        self.frame, self.end_skew = frame, tuple(end_skew)
        self.ifc, self.layer = ifc, layer
        #: ProjectContext supplying the model frame (see `to_model`).
        self.origin = origin
        for lbl, ring in ([("section", self.section)]
                          + [("void", v) for v in self.voids]):
            if ring_self_intersects(ring):
                raise ValueError(
                    f"{name}: {lbl} ring self-intersects - its lobes' "
                    f"areas partially cancel in the Pappus closed form "
                    f"AND in the faceted loft, so the two agree on a "
                    f"fiction that no later check can catch; fix the "
                    f"vertex order")
        self._A, self._xbar, self._zbar = net_area_centroid(
            self.section, self.voids)
        eps = max(1e-6 * (s1 - s0), 2e-6)
        # eps floor 2e-6 ft: _seg_at accepts +/-1e-6 ft of a join and
        # first-match wins, so a proportional eps on a sub-foot run could
        # sample the WRONG side of a tangent/arc join and misclassify a
        # skewed arc end as straight (review-demonstrated)
        self._face_declared = (
            frame == "normal"
            or (abs(end_skew[0]) > 1e-12
                and alignment.curvature(s0 + eps) != 0.0)
            or (abs(end_skew[1]) > 1e-12
                and alignment.curvature(s1 - eps) != 0.0))
        self._s = self._stations()
        maxr = max(math.hypot(x, z) for x, z in self.section)
        for a, b in self._pieces:
            k = self.alignment.curvature((a + b) / 2.0)
            if k != 0.0 and abs(k) * maxr >= 1.0 - 1e-9:
                raise ValueError(
                    f"{name}: section reaches the arc centre at station "
                    f"{sta((a + b) / 2.0)} (offset {maxr:g} ft vs radius "
                    f"{1.0 / abs(k):g} ft) - the loft would double back "
                    f"through itself with closed form and facet agreeing "
                    f"on a fiction; narrow the section or split the run")

    # ------------------------------------------------------------ stations
    def _stations(self) -> list[float]:
        cuts = {self.s0, self.s1}
        cuts.update(self.alignment.seg_breaks(self.s0, self.s1))
        if self.profile is not None:
            cuts.update(self.profile.breaks(self.s0, self.s1))
            # cut at each VC's PVI too: the control station where the
            # two half-parabolas of a symmetric VC meet, so densified
            # stationing runs symmetric about it and the mesh carries a
            # section at every profile-defining station (BVC, PVI, EVC)
            cuts.update(
                pvi for c in self.profile.curves
                for pvi in [(c["bvc_station"] + c["evc_station"]) / 2.0]
                if self.s0 + 1e-9 < pvi < self.s1 - 1e-9)
        for tab in (self._phi, self.camber):
            for s, _v in (tab or ()):
                if self.s0 + 1e-9 < s < self.s1 - 1e-9:
                    cuts.add(s)
        base = sorted(cuts)
        self._pieces = list(zip(base, base[1:]))
        out: list[float] = []
        for a, b in self._pieces:
            n = self._bays(a, b)
            out.extend(a + (b - a) * i / n for i in range(n))
        out.append(self.s1)
        return out

    def _bays(self, a: float, b: float) -> int:
        ds = b - a
        n = 1
        k = abs(self.alignment.curvature((a + b) / 2.0))
        if k > 0.0:
            n = max(n, math.ceil(k * ds / MAX_ARC_STEP_RAD))
        if self._phi:
            dphi = abs(profile_at(self._phi, b) - profile_at(self._phi, a))
            if dphi > 1e-12:
                # same delta^2/6 law as the plan arc (see MAX_ARC_STEP_RAD)
                n = max(n, math.ceil(dphi / MAX_ARC_STEP_RAD))
        if self.profile is not None:
            # grade() is the LEFT limit at a shared cut station, so sample
            # strictly inside the piece or a grade-break PVI next door
            # leaks into dg and mis-sizes the facets here
            eps = 1e-9 * ds
            dg = abs(self.profile.grade(b - eps) - self.profile.grade(a + eps))
            if dg > 1e-12:
                h = math.sqrt(8.0 * VC_SAGITTA_FT * ds / dg)
                n = max(n, math.ceil(ds / h))
        return int(n)

    # ------------------------------------------------------- world mapping
    def _xf(self, s: float, ring: list, skew_tan: float = 0.0) -> list:
        n0, e0, az = self.alignment.point_az(s)
        ln, le = self.alignment.left_normal(s)
        azr = math.radians(az)
        tn, te = math.cos(azr), math.sin(azr)          # plan tangent, +s
        elev = self.profile.elev(s) if self.profile is not None else 0.0
        if self.camber:
            elev += profile_at(self.camber, s)
        phi = profile_at(self._phi, s) if self._phi else 0.0
        c, sn = math.cos(phi), math.sin(phi)
        if self.frame == "normal":
            g = self.profile.grade(s) if self.profile is not None else 0.0
            gam = math.atan(g)
            cg, sg = math.cos(gam), math.sin(gam)
        out = []
        for x, z in ring:
            xp = x * c - z * sn
            zp = x * sn + z * c
            if self.frame == "normal":
                # pitch about the left_normal axis: +z tilts toward -s uphill
                dn, de = xp * ln - zp * sg * tn, xp * le - zp * sg * te
                zz = zp * cg + elev
            else:
                dn, de, zz = xp * ln, xp * le, zp + elev
            sh = xp * skew_tan
            out.append(to_model(self.origin, n0 + dn + sh * tn,
                                e0 + de + sh * te, zz))
        return out

    # -------------------------------------------------------------- faces
    def _faces(self) -> list:
        ss = self._s
        skew = {0: math.tan(math.radians(self.end_skew[0])),
                len(ss) - 1: math.tan(math.radians(self.end_skew[1]))}
        outer = _wound(self.section, ccw=True)
        rings2d = [outer] + [_wound(v, ccw=False) for v in self.voids]
        world = [[self._xf(s, r, skew.get(i, 0.0)) for r in rings2d]
                 for i, s in enumerate(ss)]
        faces: list = []
        merged = keyhole_ring(outer, self.voids) if self.voids else outer
        for i0, i1, i2 in ear_clip(merged):
            tri = [merged[i0], merged[i1], merged[i2]]
            faces.append(list(reversed(self._xf(ss[0], tri, skew[0]))))
            faces.append(self._xf(ss[-1], tri, skew[len(ss) - 1]))
        for ri in range(len(rings2d)):
            for wa, wb in zip(world, world[1:]):
                ra, rb = wa[ri], wb[ri]
                m = len(ra)
                for j in range(m):
                    k = (j + 1) % m
                    a, b, c, d = ra[j], ra[k], rb[k], rb[j]
                    # split each loft quad through its centroid: the
                    # 4-fan's flux is the MEAN of the two diagonal
                    # splits (= the bilinear patch), killing the
                    # first-order-in-twist volume bias a single
                    # diagonal carries when roll warps the quad --
                    # every diagonal bows the same rotational way, so
                    # single-diagonal errors ADD around the ring
                    # instead of cancelling. Planar quads (no roll)
                    # are flux-identical either way.
                    mid = ((a[0] + b[0] + c[0] + d[0]) / 4.0,
                           (a[1] + b[1] + c[1] + d[1]) / 4.0,
                           (a[2] + b[2] + c[2] + d[2]) / 4.0)
                    faces.append([a, b, mid])
                    faces.append([b, c, mid])
                    faces.append([c, d, mid])
                    faces.append([d, a, mid])
        return faces

    # ---------------------------------------------------------- quantities
    @property
    def length_ft(self) -> float:
        return self.s1 - self.s0

    @property
    def faceted_volume_cf(self) -> float:
        return face_volume(self._faces())

    @property
    def volume_cf(self) -> float:
        if self._face_declared:
            return self.faceted_volume_cf
        return self._closed_cf()

    def _closed_cf(self) -> float:
        A, xb, zb = self._A, self._xbar, self._zbar
        v = 0.0
        for a, b in self._pieces:
            ds = b - a
            k = self.alignment.curvature((a + b) / 2.0)
            if k == 0.0:
                v += A * ds
                continue
            p0 = profile_at(self._phi, a) if self._phi else 0.0
            p1 = profile_at(self._phi, b) if self._phi else 0.0
            if abs(p1 - p0) < 1e-12:
                v += A * ds * (1.0 - k * (xb * math.cos(p0)
                                          - zb * math.sin(p0)))
            else:
                rho = (p1 - p0) / ds
                v += A * (ds - (k / rho)
                          * (xb * (math.sin(p1) - math.sin(p0))
                             + zb * (math.cos(p1) - math.cos(p0))))
        for sk, s_end, sign in ((self.end_skew[0], self.s0, -1.0),
                                (self.end_skew[1], self.s1, +1.0)):
            if abs(sk) < 1e-12:
                continue
            phi = profile_at(self._phi, s_end) if self._phi else 0.0
            xbp = xb * math.cos(phi) - zb * math.sin(phi)
            v += sign * A * xbp * math.tan(math.radians(sk))
        return v

    # ---------------------------------------------------------------- mesh
    def body_solids(self) -> list[dict]:
        verts: list = []
        index: dict = {}

        def vid(p):
            # welds bitwise-identical recomputations; at State-Plane
            # magnitude round-9 sits at the float64 ULP, deliberately
            # matching clean_ring's 1e-9 - do not tighten
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
            # same fan face_volume integrates: mesh volume IS the faceted
            # volume, bit for bit (BatteredWall discipline)
            for b, c in zip(r[1:], r[2:]):
                tris.append((vid(r[0]), vid(b), vid(c)))
        d = {"kind": "mesh", "units": "ft", "verts": verts,
             "tris": _outward_tris(verts, tris),
             "plan": [self._plan_ring()]}
        if self.exact_reason is None:
            # #332: the exact IfcSectionedSolidHorizontal emit_ifc writes
            # along the IfcAlignment's curve, in place of this mesh while the
            # mesh still lies on it (primitives.exact_of). The mesh is what
            # DXF/STEP draw and what IFC4 falls back to.
            d["exact"] = {"kind": "sectioned", "sweep": self,
                          "alignment": self.alignment,
                          "vprofile": self.profile, "origin": self.origin,
                          "sections": self.ifc_sections()}
        return [d]

    #: how far a mesh vertex may sit off the swept surface and still be
    #: this sweep's own mesh, feet — float noise at State-Plane magnitude
    MESH_EXACT_TOL_FT = 1e-5

    def mesh_is_exact(self, verts) -> bool:
        """Whether `verts` (model frame, feet) are still this sweep's own
        mesh: every section point at every mesh station, on the swept
        surface — false once a subclass reshapes the section (a taper) or
        anything edits the mesh, so the edited mesh is written instead of a
        solid it no longer is. The fan-centre vertices between stations sit
        a chord's sag inside the surface and are not tested."""
        import bisect
        key = hash(tuple(map(tuple, verts)))
        cache = self.__dict__.setdefault("_mesh_exact", {})
        if key not in cache:
            tol = self.MESH_EXACT_TOL_FT
            ss = sorted(self._s)
            on = []
            for p in verts:
                st = self._section_coords(*p)[0]
                i = bisect.bisect_left(ss, st)
                if min(abs(st - ss[j]) for j in (i - 1, i)
                       if 0 <= j < len(ss)) <= tol:
                    on.append(p)
            sec = self.ifc_sections()[0]
            per = len(sec["outer"]) + sum(len(v) for v in sec["voids"])
            ok = len(on) == per * len(ss)
            if ok:
                res, lo, hi = self.surface_residual_ft(on)
                ok = (res <= tol and abs(lo - self.s0) <= tol
                      and abs(hi - self.s1) <= tol)
            cache[key] = ok
        return cache[key]

    #: how far an exact IFC sweep's sections may lean off this sweep's own,
    #: feet (2 mm) — see exact_reason
    EXACT_LEAN_TOL_FT = 0.002 / 0.3048

    @property
    def exact_reason(self) -> str | None:
        """Why this sweep cannot be one IfcSectionedSolidHorizontal, or None.

        With its placement axes left implicit — the one form ifcopenshell 0.9
        draws (explicit axes collapse the section, IfcOpenShell#6386) — an
        IfcAxis2PlacementLinear puts each section square to the directrix's
        3D tangent (IFC 4.3, IfcAxis2PlacementLinear.Axis): pitched with the
        grade, which is this sweep's "normal" frame. A "plumb" sweep is that
        solid only where the grade, times the section's height, leans it by
        less than EXACT_LEAN_TOL_FT; camber, added vertically here and along
        the pitched axis there, leans by its ordinate times the grade in
        either frame. A skewed end is not expressible in a form ifcopenshell
        0.9 can draw: an end clip is silently dropped (the solid is not
        closed, upstream IfcOpenShell#9820).
        """
        if any(abs(sk) > 1e-12 for sk in self.end_skew):
            return "skewed end"
        lean = self._lean_ft()
        if lean > self.EXACT_LEAN_TOL_FT:
            return (f"{self.frame} sections on grade lean {lean * 304.8:.0f} "
                    f"mm off the pitched IFC sections")
        return None

    def _lean_ft(self) -> float:
        """Bound on how far the pitched IFC sections stray from this sweep's
        own, along the alignment."""
        if self.profile is None:
            return 0.0                       # a level directrix: no pitch
        ss = sorted(set(list(self._s) + list(self.profile.breaks(self.s0,
                                                                  self.s1))))
        eps = 1e-9 * max(1.0, self.s1 - self.s0)
        g = max(abs(self.profile.grade(min(max(x, self.s0 + eps),
                                           self.s1 - eps))) for x in ss)
        cam = (max(abs(v) for _s, v in self.camber) if self.camber else 0.0)
        h = 0.0
        if self.frame == "plumb":
            # the section's reach from the grade line, whatever the roll
            h = max(math.hypot(x, z)
                    for ring in [self.section] + list(self.voids)
                    for x, z in ring)
        return (h + cam) * g
    #: max roll change between IFC sections: the sweep interpolates a
    #: section's points linearly, the engine its roll angle, and the two part
    #: by r*dphi^2/8 — 0.01 rad keeps that under 0.2 mm on a 50 ft deck
    IFC_ROLL_STEP_RAD = 0.01

    def ifc_sections(self) -> list[dict]:
        """[{"s", "outer", "voids"}]: each IFC cross-section, in the section
        plane at station s, (u, v) = (left offset, height above the profile
        grade line) with roll and camber applied — the same mapping `_xf`
        puts on the mesh, minus the plan position the curve supplies."""
        stations = []
        for a, b in zip(self._s, self._s[1:]):
            n = 1
            if self._phi:
                dphi = abs(profile_at(self._phi, b) - profile_at(self._phi, a))
                n = max(1, math.ceil(dphi / self.IFC_ROLL_STEP_RAD))
            stations.extend(a + (b - a) * i / n for i in range(n))
        stations.append(self._s[-1])
        outer = _wound(self.section, ccw=True)
        voids = [_wound(v, ccw=False) for v in self.voids]
        # with no vertical profile the directrix is the plan curve at z = 0,
        # where the mesh sits at the datum-shifted elevation 0
        base = (0.0 if self.profile is not None
                else to_model_elev(self.origin, 0.0))
        out = []
        for s in stations:
            phi = profile_at(self._phi, s) if self._phi else 0.0
            c, sn = math.cos(phi), math.sin(phi)
            lift = base + (profile_at(self.camber, s) if self.camber else 0.0)

            def place(ring):
                return [(x * c - z * sn, x * sn + z * c + lift) for x, z in ring]
            out.append({"s": s, "outer": place(outer),
                        "voids": [place(v) for v in voids]})
        return out

    # ------------------------------------------------- exact-solid residual
    def _station_of(self, n: float, e: float, margin: float = 0.0) -> float:
        """The station in [s0 - margin, s1 + margin] whose plan cross-section
        line passes through survey point (n, e): its plan foot on the
        directrix."""
        best = None
        for seg in self.alignment.segments:
            lo = max(seg["s0"], self.s0 - margin)
            hi = min(seg["s1"], self.s1 + margin)
            if hi < lo:
                continue
            if seg["kind"] == "tangent":
                az = math.radians(seg["az"])
                s = seg["s0"] + ((n - seg["n0"]) * math.cos(az)
                                 + (e - seg["e0"]) * math.sin(az))
            else:
                a = math.degrees(math.atan2(e - seg["ce"], n - seg["cn"]))
                d = (a - seg["radial0"] + 180.0) % 360.0 - 180.0
                s = seg["s0"] + seg["sign"] * d / seg["delta"] * seg["length"]
            s = min(max(s, lo), hi)
            n0, e0, az = self.alignment.point_az(s)
            along = abs((n - n0) * math.cos(math.radians(az))
                        + (e - e0) * math.sin(math.radians(az)))
            if best is None or along < best[0]:
                best = (along, s)
        return best[1]

    def _survey(self, x: float, y: float) -> tuple[float, float]:
        """Model-frame plan point -> survey (northing, easting): `to_model`
        inverted (a translation and the axis swap)."""
        if self.origin is None:
            return y, x
        return y + self.origin.base_n, x + self.origin.base_e

    def wall_area_sf(self, verts, tris) -> float:
        """Area of the facets of a tessellation that face sideways (normal
        within 60 deg of square to the local plan tangent) — the swept walls,
        outer and void, without the end caps. Comparing an engine's drawing of
        the exact solid against this sweep's own mesh catches a missing or
        extra wall, which a vertex-on-surface check cannot see."""
        total = 0.0
        for a, b, c in tris:
            pa, pb, pc = verts[a], verts[b], verts[c]
            ux, uy, uz = (pb[i] - pa[i] for i in range(3))
            vx, vy, vz = (pc[i] - pa[i] for i in range(3))
            nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
            nl = math.sqrt(nx * nx + ny * ny + nz * nz)
            if nl == 0.0:
                continue
            cx, cy = ((pa[i] + pb[i] + pc[i]) / 3.0 for i in range(2))
            s = self._station_of(*self._survey(cx, cy))
            tx, ty = to_model_dir(*_unit_az(self.alignment.point_az(s)[2]))
            if abs((nx * tx + ny * ty) / nl) < 0.5:
                total += nl / 2.0
        return total

    def _section_coords(self, x: float, y: float, z: float,
                        margin: float = 0.0) -> tuple[float, float, float]:
        """Model-frame point -> (station, u, v): the section plane through it
        and its coordinates there, u to the left of travel and v up the
        section's own axis, roll not undone. A plumb section's plane is
        vertical and square to the plan tangent; a "normal" one is pitched
        square to the 3D tangent (found by Newton from the plan foot)."""
        n, e = self._survey(x, y)
        s = self._station_of(n, e, margin)
        flat = self.profile is None
        for _ in range(8):
            n0, e0, az = self.alignment.point_az(s)
            tn, te = _unit_az(az)
            zc = (to_model_elev(self.origin, 0.0) if flat
                  else to_model_elev(self.origin, self.profile.elev(s)))
            if self.camber:
                zc += profile_at(self.camber, s)
            along, dz = (n - n0) * tn + (e - e0) * te, z - zc
            if self.frame != "normal" or flat:
                break
            g = self.profile.grade(s)
            cg = 1.0 / math.sqrt(1.0 + g * g)
            sg = g * cg
            f = along * cg + dz * sg
            if abs(f) < 1e-10:
                break
            s += f * cg
        ln, le = self.alignment.left_normal(s)
        u = (n - n0) * ln + (e - e0) * le
        if self.frame == "normal" and not flat:
            g = self.profile.grade(s)
            cg = 1.0 / math.sqrt(1.0 + g * g)
            return s, u, -g * cg * along + cg * dz
        return s, u, dz

    def surface_residual_ft(self, points,
                            margin: float = 1.0) -> tuple[float, float, float]:
        """(max distance to the true swept surface, min station, max station)
        over model-frame points (feet) — the gate's check that an exact IFC
        sweep was drawn where this sweep IS. Each point is taken back to its
        section plane, lateral offset and height, roll undone, then measured
        against the section's rings. Exact for any point on the swept surface
        or its end caps, whatever engine tessellated it. Stations are found
        up to `margin` past either end, so a solid that overshoots its
        stations shows as one."""
        rings = [_wound(self.section, ccw=True)] + list(self.voids)
        worst, s_min, s_max = 0.0, math.inf, -math.inf
        for x, y, z in points:
            s, u, v = self._section_coords(x, y, z, margin)
            s_min, s_max = min(s_min, s), max(s_max, s)
            phi = profile_at(self._phi, s) if self._phi else 0.0
            c, sn = math.cos(phi), math.sin(phi)
            px, pz = u * c + v * sn, -u * sn + v * c
            d = min(_seg_dist(px, pz, a, b)
                    for r in rings for a, b in zip(r, r[1:] + r[:1]))
            worst = max(worst, d)
        return worst, s_min, s_max

    #: how near an end a cap facet must be to count as that end's cap, feet:
    #: ifcopenshell 0.9 also leaves a stray cap inside the solid
    #: (IfcOpenShell#9820), wherever its loft happens to put one
    CAP_WINDOW_FT = 0.5

    def cap_station_error_ft(self, verts, tris) -> float:
        """Worst station error of a tessellation's end-cap vertices: every
        facet facing along the alignment within CAP_WINDOW_FT of an end must
        lie in that end's section plane. A section drawn leaning — a plumb
        sweep drawn pitched — fails here even where every vertex stays on
        the swept surface."""
        ends, win = (self.s0, self.s1), self.CAP_WINDOW_FT
        worst = 0.0
        for a, b, c in tris:
            pa, pb, pc = verts[a], verts[b], verts[c]
            ux, uy, uz = (pb[i] - pa[i] for i in range(3))
            vx, vy, vz = (pc[i] - pa[i] for i in range(3))
            nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
            nl = math.sqrt(nx * nx + ny * ny + nz * nz)
            if nl == 0.0:
                continue
            cx, cy = ((pa[i] + pb[i] + pc[i]) / 3.0 for i in range(2))
            st = self._station_of(*self._survey(cx, cy), margin=1.0)
            tx, ty = to_model_dir(*_unit_az(self.alignment.point_az(st)[2]))
            if abs((nx * tx + ny * ty) / nl) < 0.9:
                continue
            for p in (pa, pb, pc):
                sp = self._section_coords(*p, margin=1.0)[0]
                err = min(abs(sp - t) for t in ends)
                if err <= win:
                    worst = max(worst, err)
        return worst

    def _plan_ring(self) -> list:
        outer = _wound(self.section, ccw=True)
        ss = self._s
        # same end-shear _faces applies, so a skewed deck end draws
        # skewed in the DXF plan instead of square
        skew = {0: math.tan(math.radians(self.end_skew[0])),
                len(ss) - 1: math.tan(math.radians(self.end_skew[1]))}
        left, right = [], []
        for i, s in enumerate(ss):
            n0, e0, az = self.alignment.point_az(s)
            ln, le = self.alignment.left_normal(s)
            azr = math.radians(az)
            tn, te = math.cos(azr), math.sin(azr)      # plan tangent, +s
            sh = skew.get(i, 0.0)
            phi = profile_at(self._phi, s) if self._phi else 0.0
            c, sn = math.cos(phi), math.sin(phi)
            xps = [x * c - z * sn for x, z in outer]
            lo, hi = min(xps), max(xps)
            # plan ring is 2-D: same conversion, z dropped
            left.append(to_model(self.origin, n0 + hi * ln + hi * sh * tn,
                                 e0 + hi * le + hi * sh * te)[:2])
            right.append(to_model(self.origin, n0 + lo * ln + lo * sh * tn,
                                  e0 + lo * le + lo * sh * te)[:2])
        return left + list(reversed(right))
