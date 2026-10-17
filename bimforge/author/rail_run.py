"""B11-51 tubular-handrailing rail-run primitive: post layout + element
build. Pure geometry + quantity; no file I/O.

v1 accepts a STRAIGHT run in a local frame: `build_run(length_ft=...)` (+Y =
run). An alignment + station-range path (curved / staged host geometry) is a
follow-on -- the seam is the single `build_run` call, so it can grow a
`path=` argument without host families changing how they invoke it.

Host families (bridge barrier, wingwall, wall_run) reuse this by calling
`build_run(...)` directly with their own top-of-wall run -- no dependency on
StructureModel or I/O.
"""
from __future__ import annotations

import math

from bimforge.author import rail_section as rs
from bimforge.author.model import Element
from bimforge.author.primitives import (
    BAR_PROPS, FACET_TOLERANCE, Prism, SectionPrism, _outward_tris,
    _signed_volume, _wound, clean_ring2d, ear_clip, keyhole_ring, poly_area)

STEEL_LAYER = "S-METAL"

#: Max arc-angle step per facet bay so the chorded sweep's volume defect
#: (~step^2/6) stays inside the gate's FACET_TOLERANCE band -- the same
#: sqrt(1.5 * tol) bound author.sweep derives for its plan/roll arcs.
_MAX_ARC_STEP_RAD = math.sqrt(1.5 * FACET_TOLERANCE)

#: run_name is used as an element-name PREFIX; it must not contain the
#: element-type tokens build_run appends, or a paycode rule matching those
#: tokens would misclassify the run's parts (the recurring name-coupling bug).
_RESERVED_RUN_NAME_TOKENS = ("top rail", "lower rail", "post", "pocket mortar",
                             "dowel", "end return", "rail cap", "splice sleeve")


def post_stations(length_ft: float, nominal_ft: float = 6.0 + 2.0 / 12.0,
                  min_bay_ft: float = 5.0, max_bay_ft: float = 9.5) -> list:
    """Equal-bay post positions along [0, length_ft], a post at each end.

    `max_bay_ft` is a HARD ceiling (the rail must never span more than this);
    `min_bay_ft` is a SOFT floor -- honoured where possible but yielding to
    the ceiling and to short runs. Because max_bay/min_bay < 2 there is a
    length band (max_bay, 2*min_bay) where no equal spacing satisfies both,
    and closer posts are harmless while a too-long span is not. Always >= 2
    posts so the top rail is continuous over >= 2 posts (B11-51 Note 4).
    Deck/wall-joint short bays are NOT re-laid-out here (uniform spacing is
    estimate-correct, per estimator direction 2026-08-25); joints only add splice sleeves
    in `build_run`.
    """
    if length_ft <= 0:
        raise ValueError(f"run length must be positive, got {length_ft}")
    n_bays = max(1, round(length_ft / nominal_ft))
    while length_ft / n_bays > max_bay_ft:                 # hard ceiling
        n_bays += 1
    while (n_bays > 1 and length_ft / n_bays < min_bay_ft
           and length_ft / (n_bays - 1) <= max_bay_ft):    # soft floor, ceiling-safe
        n_bays -= 1
    bay = length_ft / n_bays
    return [round(i * bay, 9) for i in range(n_bays + 1)]


def _swept_member(geom, **kw):
    """Element.from_geometry for a member SWEPT along its length (a SectionPrism
    rail/sleeve, a bent-tube return/cap): drop the cross-section area_sf that
    from_geometry copies off the primitive. It is NOT a plan footprint, and
    emit_ifc would otherwise read a present area_sf as one and derive a bogus
    Qto GrossArea/Length from it — on the payment rail, overriding the declared
    LF pay line (the 9.52-vs-166.77 regression). Posts/mortar stay on
    from_geometry: a vertical Prism's area_sf genuinely IS its footprint. (#252)
    """
    el = Element.from_geometry(geom.name, geom, **kw)
    el.quantities.pop("area_sf", None)
    return el


def _rail_element(run_name: str, rail, length_ft: float, base_z_ft: float,
                  x0: float = 0.0):
    """One continuous rail as a hollow section extruded along +Y (the run).
    The payment rail is classed IfcRailing and carries length_ft (the LF pay
    line); others are IfcMember and carry volume only (weight)."""
    outer, voids = rs.hollow_ring(rail.size, x0, base_z_ft + rail.z_center_ft)
    label = "top rail" if rail.is_payment else "lower rail"
    sp = SectionPrism(f"{run_name} {label}", outer, length_ft, voids=voids,
                      ifc="IfcRailing" if rail.is_payment else "IfcMember",
                      layer=STEEL_LAYER)
    q = {"volume_cf": sp.volume_cf}
    if rail.is_payment:
        q["length_ft"] = length_ft          # plan payment length, explicit
    return _swept_member(sp, ifc_class=sp.ifc, layer=sp.layer, quantities=q)


def _post_element(run_name: str, i: int, s: float, cfg, base_z_ft: float,
                  embed_ft: float = 0.0, x0: float = 0.0):
    """A hollow vertical post at run position `s` (+Y), x=x0. When set in a
    mortar pocket (`embed_ft` > 0) the shaft extends that far below the
    barrier top, filling the pocket void."""
    outer, holes = rs.hollow_ring(cfg.post_size, x0, s)   # plan is (x, y)
    z_bot = base_z_ft - embed_ft
    z_top = base_z_ft + cfg.height_ft
    p = Prism(f"{run_name} post {i}", outer, z_bot, z_top, holes=holes,
              ifc="IfcMember", layer=STEEL_LAYER)
    return Element.from_geometry(p.name, p, ifc_class="IfcMember",
                                 layer=STEEL_LAYER,
                                 quantities={"height_ft": z_top - z_bot,
                                             "volume_cf": p.volume_cf})


POCKET_W_IN, POCKET_L_IN, POCKET_D_IN = 4.0, 5.0, 9.0
POST_SIDE_IN = 2.0


def _mortar_element(run_name: str, i: int, s: float, base_z_ft: float,
                    x0: float = 0.0):
    """Pocket mortar around the post: 4x5 plan void by the 2x2 post, 9 deep."""
    outer = rs.rect_ring(POCKET_W_IN / 12.0, POCKET_L_IN / 12.0, x0, s)
    void = rs.rect_ring(POST_SIDE_IN / 12.0, POST_SIDE_IN / 12.0, x0, s)
    depth = POCKET_D_IN / 12.0
    p = Prism(f"{run_name} pocket mortar {i}", outer, base_z_ft - depth,
              base_z_ft, holes=[void], ifc="IfcBuildingElementProxy",
              layer="S-CONC")
    return Element.from_geometry(p.name, p, ifc_class="IfcBuildingElementProxy",
                                 layer="S-CONC",
                                 quantities={"volume_cf": p.volume_cf})


def _dowel_elements(run_name: str, i: int) -> list:
    """B11-51 post dowels: 2-#4 x 2'-6" and 2-#4 x 1'-0" (weight-only bars)."""
    out = []
    lb_per_ft = BAR_PROPS[4][2]
    for length_ft in (2.5, 1.0):
        w = 2 * length_ft * lb_per_ft
        out.append(Element(
            f"{run_name} dowel #4 x {length_ft} @{i}",
            "IfcReinforcingBar",
            quantities={"count": 2, "length_ft": 2 * length_ft, "weight_lb": w},
            layer="S-REBAR", description="#4 pocket dowel"))
    return out


END_RETURN_RADIUS_FT = 4.0
SLEEVE_LEN_FT = 1.5
SLEEVE_WALL_IN = 0.1875
CAP_PLATE_IN = 0.1875


def _top_rail(cfg):
    return next(r for r in cfg.rails if r.is_payment)


class _BentTube:
    """The B11-51 R=4'-0" end-post bent-down return: the top-rail hollow
    section swept through a circular arc in the y-z plane, curling down from
    the rail centerline to the barrier top and capped at the tip.

    The sweep is a pure partial rotation (angle `phi1 - phi0`) of the (x, z)
    section about the x-parallel axis one radius below the rail centerline,
    so Pappus applies EXACTLY: the net-section centroid rides the arc
    centerline (radius R), and the swept volume is `net_area * R * dphi`.
    `volume_cf` declares that closed form; `faceted_volume_cf` sums the
    emitted chorded mesh; `check_arc_faceting` gate-checks the two agree
    within FACET_TOLERANCE -- so the drawn geometry and the paid steel
    weight stay one number (the rail_section.py QC discipline).

    A section point (xa, za) -- absolute (x, z), centred on (x0, z_center) --
    maps to world (for `toward` = -1 curling toward -Y, +1 toward +Y)::

        w = za - z_center
        x = xa
        y = y_bc + toward * sin(phi) * (R + w)
        z = z_center - R * (1 - cos(phi)) + w * cos(phi)

    At phi = 0 this is the flat section at the begin-curve station `y_bc`,
    tangent horizontal, so the return meets the straight top rail flush.
    Passing `voids` sweeps the true hollow tube (the return); omitting them
    sweeps a solid slice (the rail-cap plate at the tip).
    """

    def __init__(self, name: str, *, outer: list, voids: list, x0: float,
                 z_center: float, radius_ft: float, phi0: float, phi1: float,
                 y_bc: float, toward: float, ifc: str, layer: str) -> None:
        if not phi1 > phi0:
            raise ValueError(f"{name}: sweep angle must be positive")
        self.name = name
        self.outer = [(float(x), float(z)) for x, z in outer]
        self.voids = [[(float(x), float(z)) for x, z in v] for v in (voids or [])]
        self.x0, self.z_center = float(x0), float(z_center)
        self.R, self.phi0, self.phi1 = float(radius_ft), float(phi0), float(phi1)
        self.y_bc = float(y_bc)
        self.toward = -1.0 if toward < 0 else 1.0
        self.ifc, self.layer = ifc, layer

    @property
    def _net_area(self) -> float:
        return poly_area(self.outer) - sum(poly_area(v) for v in self.voids)

    @property
    def volume_cf(self) -> float:
        # Pappus, centroid on the arc centerline (radius R): exact.
        return self._net_area * self.R * (self.phi1 - self.phi0)

    def _map(self, xa: float, za: float, phi: float) -> tuple:
        w = za - self.z_center
        return (xa,
                self.y_bc + self.toward * math.sin(phi) * (self.R + w),
                self.z_center - self.R * (1.0 - math.cos(phi)) + w * math.cos(phi))

    def _stations(self) -> list:
        span = self.phi1 - self.phi0
        n = max(1, math.ceil(span / _MAX_ARC_STEP_RAD))
        return [self.phi0 + span * i / n for i in range(n + 1)]

    @property
    def arc_segments(self) -> int:
        return len(self._stations()) - 1

    def _mesh(self) -> tuple:
        # Same keyhole-cap + per-ring-wall scheme as SectionPrism, extended to
        # N arc stations; _outward_tris fixes the global orientation, so only
        # CONSISTENT winding across the caps and bays is required (it holds
        # because every bay reuses one wall rule and the caps mirror it).
        # clean -> check -> wind (SectionPrism's order): a degenerate profile
        # cleans to [], and winding [] would IndexError inside _signed_area2
        # before this guard could fail loud.
        outer = clean_ring2d(self.outer)
        if len(outer) < 3:
            raise ValueError(f"{self.name}: section collapses to < 3 points")
        outer = _wound(outer, ccw=True)
        voids = [c for c in (clean_ring2d(v) for v in self.voids) if len(c) >= 3]
        merged = keyhole_ring(outer, voids) if voids else outer
        caps = ear_clip(merged)
        phis = self._stations()
        verts: list = []
        index: dict = {}

        def vid(x, y, z):
            key = (round(x, 9), round(y, 9), round(z, 9))
            if key not in index:
                index[key] = len(verts)
                verts.append((float(x), float(y), float(z)))
            return index[key]

        tris = []
        p_lo, p_hi = phis[0], phis[-1]
        for i0, i1, i2 in caps:
            (xa, za), (xb, zb), (xc, zc) = merged[i0], merged[i1], merged[i2]
            tris.append((vid(*self._map(xa, za, p_lo)),
                         vid(*self._map(xb, zb, p_lo)),
                         vid(*self._map(xc, zc, p_lo))))
            tris.append((vid(*self._map(xa, za, p_hi)),
                         vid(*self._map(xc, zc, p_hi)),
                         vid(*self._map(xb, zb, p_hi))))
        for r in [outer] + [_wound(v, ccw=False) for v in voids]:
            for a, b in zip(phis, phis[1:]):
                for p, q in zip(r, r[1:] + r[:1]):
                    qa, pa = vid(*self._map(q[0], q[1], a)), vid(*self._map(p[0], p[1], a))
                    pb, qb = vid(*self._map(p[0], p[1], b)), vid(*self._map(q[0], q[1], b))
                    tris.append((qa, pa, pb))
                    tris.append((qa, pb, qb))
        return verts, _outward_tris(verts, tris)

    @property
    def faceted_volume_cf(self) -> float:
        verts, tris = self._mesh()
        return abs(_signed_volume([(verts[a], verts[b], verts[c])
                                   for a, b, c in tris]))

    def body_solids(self) -> list:
        verts, tris = self._mesh()
        xs = [p[0] for p in verts]
        ys = [p[1] for p in verts]
        plan = [[(min(xs), min(ys)), (max(xs), min(ys)),
                 (max(xs), max(ys)), (min(xs), max(ys))]]
        return [{"kind": "mesh", "units": "ft", "verts": verts,
                 "tris": tris, "plan": plan, "exact": self._revolution()}]

    def _revolution(self) -> dict:
        """The solid this mesh chords: the section turned phi1 - phi0 about
        the x-parallel axis one radius below the rail centerline (#331), one
        IfcRevolvedAreaSolid. The profile plane is the section at phi0, with
        u = x - x0 and v = w (up the section at that angle); the axis runs
        -toward along x, so the right-handed turn carries the section the
        way `_map` does."""
        outer = clean_ring2d(self.outer)
        voids = [c for c in (clean_ring2d(v) for v in self.voids) if len(c) >= 3]
        s0, c0 = math.sin(self.phi0), math.cos(self.phi0)

        def uv(ring):
            return [(x - self.x0, z - self.z_center) for x, z in ring]

        return {"kind": "revolution", "profile": uv(outer),
                "voids": [uv(v) for v in voids],
                "plane": {"o": self._map(self.x0, self.z_center, self.phi0),
                          "x": (1.0, 0.0, 0.0),
                          "y": (0.0, self.toward * s0, c0)},
                "axis": {"o": (self.x0, self.y_bc, self.z_center - self.R),
                         "dir": (-self.toward, 0.0, 0.0)},
                "angle": self.phi1 - self.phi0}


def _return_sweep_angle(rail, radius_ft: float) -> float:
    """Arc angle for the top rail to curl down until the tube's lowest fibre
    lands on the barrier top (the sheet's 3/8" gap ignored).

    At the tip the section is tilted by phi, so its half-depth projects onto
    world-z as (d/2)*cos phi. The lowest fibre sits at
    z_center - R(1 - cos phi) - (d/2)cos phi above the barrier, which is 0
    when cos phi = (R - z_center_ft)/(R - d/2) -- a slightly larger angle than
    the naive centerline drop would give."""
    half_depth = rs.HSS[rail.size][1] / 12.0 / 2.0        # tube half-height (z)
    if not half_depth < rail.z_center_ft < radius_ft:
        raise ValueError(
            f"end return: a {rail.z_center_ft:g} ft rail centerline needs "
            f"d/2 < z_center < R={radius_ft:g} to curl down to the barrier on "
            f"a single sub-90-degree R={radius_ft:g} arc")
    return math.acos((radius_ft - rail.z_center_ft) / (radius_ft - half_depth))


def _end_return_element(run_name: str, end: str, cfg, base_z_ft: float,
                        y_bc: float, toward: float, x0: float = 0.0):
    """The R=4'-0" top-rail bent-down return as a true arc-swept hollow tube
    (weight-only IfcMember). Steel weight follows the swept volume, so the
    drawn curl and the paid weight are one number."""
    rail = _top_rail(cfg)
    z_center = base_z_ft + rail.z_center_ft
    outer, voids = rs.hollow_ring(rail.size, x0, z_center)
    phi1 = _return_sweep_angle(rail, END_RETURN_RADIUS_FT)
    tube = _BentTube(f"{run_name} end return {end}", outer=outer, voids=voids,
                     x0=x0, z_center=z_center, radius_ft=END_RETURN_RADIUS_FT,
                     phi0=0.0, phi1=phi1, y_bc=y_bc, toward=toward,
                     ifc="IfcMember", layer=STEEL_LAYER)
    return _swept_member(tube, ifc_class="IfcMember", layer=STEEL_LAYER,
                         quantities={"volume_cf": tube.volume_cf}), phi1


def _rail_cap_element(run_name: str, end: str, cfg, base_z_ft: float,
                      y_bc: float, toward: float, phi_start: float,
                      x0: float = 0.0):
    """Thin closure plate (3/16) capping the tube at the return TIP, swept as
    a solid slice on the same arc so it sits square to the tube axis there."""
    rail = _top_rail(cfg)
    z_center = base_z_ft + rail.z_center_ft
    outer, _ = rs.hollow_ring(rail.size, x0, z_center)
    dphi = (CAP_PLATE_IN / 12.0) / END_RETURN_RADIUS_FT   # dev length = plate t
    cap = _BentTube(f"{run_name} rail cap {end}", outer=outer, voids=[],
                    x0=x0, z_center=z_center, radius_ft=END_RETURN_RADIUS_FT,
                    phi0=phi_start, phi1=phi_start + dphi, y_bc=y_bc,
                    toward=toward, ifc="IfcPlate", layer=STEEL_LAYER)
    return _swept_member(cap, ifc_class="IfcPlate", layer=STEEL_LAYER,
                         quantities={"volume_cf": cap.volume_cf})


def _sleeve_element(run_name: str, j: int, cfg, y0: float, x0: float = 0.0):
    """Internal 3/16 liner inside the top rail at a joint (weight-only),
    centred on the joint station (`y0`)."""
    rail = _top_rail(cfg)
    b, d, t = (v / 12.0 for v in rs.HSS[rail.size])   # t = the RAIL's wall
    tw = SLEEVE_WALL_IN / 12.0                          # the sleeve's own wall
    # liner fits inside the rail cavity (rail dims minus the RAIL's wall t);
    # its own wall is tw thick.
    inner_b, inner_d = b - 2 * t, d - 2 * t
    outer = rs.rect_ring(inner_b, inner_d, x0, 0.0)
    void = rs.rect_ring(inner_b - 2 * tw, inner_d - 2 * tw, x0, 0.0)
    sp = SectionPrism(f"{run_name} splice sleeve {j}", outer, SLEEVE_LEN_FT,
                      y0=y0, voids=[void], ifc="IfcMember", layer=STEEL_LAYER)
    return _swept_member(sp, ifc_class="IfcMember", layer=STEEL_LAYER,
                         quantities={"volume_cf": sp.volume_cf})


def build_run(length_ft: float, base_z_ft: float = 0.0, *,
              cfg=rs.CONFIG_B11_51, run_name: str = "handrail",
              post_spacing_ft: float = 6.0 + 2.0 / 12.0,
              anchorage: bool = True,
              end_posts: tuple = ("start", "end"),
              joints: tuple = (),
              x0_ft: float = 0.0) -> list:
    """B11-51 rail run over a STRAIGHT length_ft in a local frame (+Y = run,
    x transverse, z up; base_z_ft = top of barrier/curb). Returns Elements
    for: the top and lower rails; posts (embedded in their mortar pockets
    when `anchorage` is on); post-pocket mortar + dowels (when `anchorage`);
    end-post returns + rail caps at each entry in `end_posts`; and splice
    sleeves at each station in `joints`.

    `x0_ft` shifts the whole run transversely (default 0.0) so a host (e.g. a
    732SW barrier) can seat it on the barrier top."""
    low = run_name.lower()
    bad = [t for t in _RESERVED_RUN_NAME_TOKENS if t in low]
    if bad:
        raise ValueError(
            f"run_name {run_name!r} contains reserved element token(s) {bad} "
            f"that collide with paycode name-matching; use a location label")
    for s in joints:
        if not (0.0 < s < length_ft):
            raise ValueError(
                f"joint station {s} is outside the run (0, {length_ft})")
    if len(set(joints)) != len(joints):
        raise ValueError(f"duplicate joint stations in {joints!r}")
    els: list = []
    for rail in cfg.rails:
        els.append(_rail_element(run_name, rail, length_ft, base_z_ft, x0=x0_ft))
    embed_ft = (POCKET_D_IN / 12.0) if anchorage else 0.0
    for i, s in enumerate(post_stations(length_ft, post_spacing_ft), start=1):
        els.append(_post_element(run_name, i, s, cfg, base_z_ft, embed_ft,
                                 x0=x0_ft))
        if anchorage:
            els.append(_mortar_element(run_name, i, s, base_z_ft, x0=x0_ft))
            els.extend(_dowel_elements(run_name, i))
    for end in end_posts:
        if end == "start":
            y_bc, toward = 0.0, -1.0        # curl begins at the run start, -Y
        elif end == "end":
            y_bc, toward = length_ft, 1.0   # curl begins at the run end, +Y
        else:
            raise ValueError(
                f"end_posts entries must be 'start' or 'end', got {end!r}")
        ret, phi1 = _end_return_element(run_name, end, cfg, base_z_ft, y_bc,
                                        toward, x0=x0_ft)
        els.append(ret)
        els.append(_rail_cap_element(run_name, end, cfg, base_z_ft, y_bc,
                                     toward, phi1, x0=x0_ft))
    for j, s in enumerate(joints, start=1):
        els.append(_sleeve_element(run_name, j, cfg, s - SLEEVE_LEN_FT / 2.0,
                                   x0=x0_ft))
    return els
