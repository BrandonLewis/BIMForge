"""culvert-headwall -- Caltrans D90 pipe-culvert headwall (inlet) / endwall
(outlet) with a circular/elliptical pipe opening and flared wingwalls (Types
A/B/C), assembled on ONE continuous B3 toe/heel footing (R25).

The headwall panel and both wingwalls stand on a single FootingRun that runs
under all three along a 3-segment plan line-of-layout (LOL):

    [left_free, (0, 0), (L, 0), right_free]

+X is along the headwall; +Y is the channel (footing toe C); -Y is the
retained earth (footing heel B). The wingwalls flare toward +Y; their free-end
plan vertices come from each side's catalog `angle_deg`/`length_ft`:

    right wing free end: (L + cos(a)*wl,  sin(a)*wl)
    left  wing free end: (   - cos(a)*wl,  sin(a)*wl)     a = radians(angle_deg)

Each wingwall stem is a BatteredWall lofted along its leg of the LOL, its top
daylighting from `wall.H` at the headwall corner to catalog `h_far` at the free
end. The top-of-footing (= wall base) descends by its OWN grade via a per-
wingwall `base_drop_ft` (total drop from the headwall corner at z=0 to the free
end), in `footing` mode "flat" (default; treat drop as 0), "swept" (linear
descent) or "stepped" (level runs snapped to the B3-5 step rise). The single
`foot_top` elevation profile is fed to BOTH the FootingRun (as its swept top)
and each stem (as its `base_profile`) so the footing top and the stem base stay
bit-for-bit identical. The mitred footing and battered stems are irregular
prisms -- they carry length + volume only (no L x W x H, per the box-culvert
precedent). The Type-C barrier is the REAL swept Type 836 section (Caltrans
Standard Plans sheet 440 / B11-80): a `wingwall_barrier` solid lofted between
the headwall corner and the wingwall free end, its base riding the sloping
wingwall top, fed by a `BarrierSection` built from the catalog's
`d90.type_c_barrier` row (explicit profile or parametric dims).
"""
from __future__ import annotations

import math
from collections import defaultdict

from bimforge.author.alignment import WallSection
from bimforge.author.barrier_rebar import barrier_bars
from bimforge.author.culvert_headwall_rebar import headwall_bars
from bimforge.author.culvert_headwall_section import headwall_stem
from bimforge.author.culvert_headwall_wingwall import rail_barrier
from bimforge.author.footing_run import FootingRun, step_rise_ft
from bimforge.author.model import Element, StructureModel
from bimforge.author.primitives import BatteredWall, mitre_offset, outward_normals
from bimforge.author.type_836_section import type_836_section

REQUIRED = ("tables", "structures")


def _emit_bars(model, sname, bars):
    groups = defaultdict(list)
    for b in bars:
        groups[(b.mark, b.size)].append(b)
    for (mark, size), bs in sorted(groups.items()):
        model.add(Element(
            f"{sname} headwall reinforcing {mark} #{size}", "IfcReinforcingBar",
            quantities={"count": len(bs),
                        "length_ft": sum(b.length for b in bs),
                        "weight_lb": sum(b.weight for b in bs)},
            layer="S-REBAR", description=f"#{size} {mark}"))


def _lol_length(lol: list) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1])
               for a, b in zip(lol, lol[1:]))


def _wing_points(xc: float, xf: float, drop: float, mode: str,
                 rise: float) -> list:
    """Top-of-footing (x, elev) points for one wing leg, from the headwall
    corner (xc, elev 0) to the free end (xf, elev -drop), inclusive.

    flat  -> level at 0.
    swept -> a single linear descent to -drop.
    stepped -> level runs joined by plumb risers (near-coincident stations
               1e-3 ft apart) snapped DOWN to multiples of `rise`. The first
               riser sits at the corner (the wing footing steps below the flat
               headwall footing); each further riser is where the linear
               descent crosses the next multiple of the rise.
    """
    if mode == "flat" or drop == 0.0:
        return [(xc, 0.0), (xf, 0.0)]
    if mode == "swept":
        return [(xc, 0.0), (xf, -drop)]
    # stepped
    sign = 1.0 if xf > xc else -1.0
    lf = math.floor((-drop) / rise + 1e-9) * rise      # snapped free-end level
    count = int(round(-lf / rise))                     # number of down-steps
    pts = [(xc, 0.0)]
    prev = 0.0
    for m in range(count):
        new_level = -(m + 1) * rise
        if m == 0:
            x_r = xc                                    # first riser at corner
        else:
            t = (m * rise) / drop
            x_r = xc + (xf - xc) * t
            pts.append((x_r, prev))                     # top of the riser
        pts.append((x_r + sign * 1e-3, new_level))      # bottom of the riser
        prev = new_level
    pts.append((xf, lf))
    return pts


def _merge_profile(pts: list) -> list:
    """Sort (x, elev) points by x and drop exact duplicates (shared corners)."""
    out = sorted(pts, key=lambda p: p[0])
    dedup: list = []
    for x, e in out:
        if (dedup and abs(dedup[-1][0] - x) < 1e-9
                and abs(dedup[-1][1] - e) < 1e-9):
            continue
        dedup.append((x, e))
    return dedup


def _seg_cross(p1, p2, p3, p4) -> bool:
    """True iff open segments p1p2 and p3p4 properly cross (pure Python -- the
    author path has no shapely)."""
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])

    d1, d2 = ccw(p3, p4, p1), ccw(p3, p4, p2)
    d3, d4 = ccw(p1, p2, p3), ccw(p1, p2, p4)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def _footing_plan_ring(lol: list, toe: float, heel: float, side: float) -> list:
    """The mitred toe/heel PLAN ring at the LOL vertices only (FootingRun's
    convention: toe on +side, heel on -side). This is the essential plan
    shape -- independent of how densely the top profile is sampled -- so the
    self-intersection guard reads a real skew/flare fold, not a z-only riser
    sliver that leaves the plan unchanged."""
    def mitres(sd):
        nrm = outward_normals(lol, sd)
        out = []
        for i in range(len(lol)):
            if i == 0:
                out.append(nrm[0])
            elif i == len(lol) - 1:
                out.append(nrm[-1])
            else:
                out.append(mitre_offset(nrm[i - 1], nrm[i]))
        return out

    mt, mh = mitres(side), mitres(-side)
    toe_pts = [(v[0] + mt[i][0] * toe, v[1] + mt[i][1] * toe)
               for i, v in enumerate(lol)]
    heel_pts = [(v[0] + mh[i][0] * heel, v[1] + mh[i][1] * heel)
                for i, v in enumerate(lol)]
    return toe_pts + list(reversed(heel_pts))


def _is_simple_polygon(ring: list) -> bool:
    n = len(ring)
    if n < 4:
        return True
    edges = [(ring[i], ring[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue                                # adjacent edges share a vertex
            if _seg_cross(edges[i][0], edges[i][1], edges[j][0], edges[j][1]):
                return False
    return True


def _place(elements, bearing_deg: float, dx: float, dy: float,
           zlift: float) -> None:
    """Set the per-structure placement on every element of one structure.

    Geometry stays authored in the shared element-LOCAL frame; the emitters
    compose the Z-rotation (bearing) with the x/y/z translation at emit time,
    so quantities/volumes are unaffected (rigid motion). `zlift` is the vertical
    translation the caller derived so the pipe invert lands at fl_elev_ft."""
    for e in elements:
        e.bearing_deg = bearing_deg
        e.x_ft = dx
        e.y_ft = dy
        e.z_ft = zlift


def build(params: dict, ctx) -> StructureModel:
    missing = [k for k in REQUIRED if params.get(k) is None]
    if missing:
        raise ValueError(f"culvert-headwall params missing {missing}")
    tables = params["tables"]
    # The project's tables_file merges the committed fixed-rules D90 catalog
    # (wingwall_types, type_c_barrier, pipe, design) with the project-supplied
    # field-varied wingwalls + schedule -- both halves are expected here.
    d90 = tables.get("d90") or {}
    wing_cat = d90.get("wingwalls") or {}
    sched = d90.get("schedule") or {}
    if params["structures"] and not sched:
        raise ValueError(
            "culvert-headwall: no d90.schedule in tables -- a D90 headwall "
            "always carries wall/footing reinforcing; supply the field-varied "
            "bar schedule (d90.schedule) in the project tables")
    model = StructureModel("culvert-headwall", ctx)
    hw_fls: list[float] = []      # explicit flow-line elevs by structure kind
    ew_fls: list[float] = []
    for s in params["structures"]:
        if s.get("kind", "headwall") not in ("headwall", "endwall"):
            raise ValueError(f"{s['name']}: kind must be headwall|endwall")
        start = len(model.elements)               # elements added for THIS structure
        name, L = s["name"], float(s["length_ft"])
        wall = WallSection("1", float(s["design_h_ft"]), tables)
        rise = step_rise_ft(wall.H)

        # --- gather wingwalls per side (catalog dims + field grade/mode) ------
        wings: dict = {}
        for ww in s.get("wingwalls", []):
            side = ww.get("side", "left")
            if side not in ("left", "right"):
                raise ValueError(
                    f"wingwall side must be 'left' or 'right', got {side!r}")
            typ = ww["type"]
            if typ not in wing_cat:
                raise ValueError(
                    f"{name}: wingwall type {typ!r} not in catalog "
                    f"(have {sorted(wing_cat)})"
                    " -- field-varied wingwall dims go under d90.wingwalls "
                    "(distinct from the fixed d90.wingwall_types rules)")
            wc = wing_cat[typ]
            wl = float(wc["length_ft"])
            a = math.radians(float(wc["angle_deg"]))
            if side == "right":
                free = (L + math.cos(a) * wl, math.sin(a) * wl)
            else:
                free = (-math.cos(a) * wl, math.sin(a) * wl)
            mode = ww.get("footing", "flat")
            if mode not in ("flat", "swept", "stepped"):
                raise ValueError(
                    f"{name}: wingwall footing mode must be flat|swept|stepped, "
                    f"got {mode!r}")
            drop = 0.0 if mode == "flat" else float(ww.get("base_drop_ft", 0.0))
            wings[side] = {"wc": wc, "ww": ww, "wl": wl, "free": free,
                           "mode": mode, "drop": drop, "typ": typ}

        # --- plan LOL: left_free, corner, corner, right_free -----------------
        lol = []
        if "left" in wings:
            lol.append(wings["left"]["free"])
        lol.append((0.0, 0.0))
        lol.append((L, 0.0))
        if "right" in wings:
            lol.append(wings["right"]["free"])

        # --- top-of-footing elevation profile across the whole LOL -----------
        pts = [(0.0, 0.0), (L, 0.0)]
        if "left" in wings:
            w = wings["left"]
            pts += _wing_points(0.0, w["free"][0], w["drop"], w["mode"], rise)
        if "right" in wings:
            w = wings["right"]
            pts += _wing_points(L, w["free"][0], w["drop"], w["mode"], rise)
        foot_top = _merge_profile(pts)

        # --- ONE continuous toe/heel footing ---------------------------------
        # side=-1 puts the toe (C) on +Y (channel) and the heel (B) on -Y
        # (retained earth). Feeding the PRE-STEPPED foot_top with bottom="swept"
        # renders the steps as near-vertical risers AND makes the footing top
        # match each stem base exactly.
        fr = FootingRun(f"{name} footing", lol=lol, toe=wall.C, heel=wall.B,
                        side=-1.0, thickness=wall.F, top_profile=foot_top,
                        key_index=0, bottom="swept")
        if not _is_simple_polygon(_footing_plan_ring(lol, wall.C, wall.B, -1.0)):
            raise ValueError(
                f"{name}: footing self-intersects (skew/flare too extreme)")
        model.add(Element.from_geometry(
            fr.name, fr, ifc_class="IfcFooting", layer="S-CONC",
            quantities={"length_ft": _lol_length(lol),
                        "volume_cf": fr.volume_cf}))

        # --- wingwall stems (BatteredWall lofted along each leg) -------------
        wws = []
        for side in ("left", "right"):
            if side not in wings:
                continue
            w = wings[side]
            wc, wl, free = w["wc"], w["wl"], w["free"]
            h_far = float(wc["h_far_ft"])
            if side == "left":
                leg_lol = [free, (0.0, 0.0)]
                top_prof = [(free[0], h_far), (0.0, wall.H)]
                lo, hi = free[0], 0.0
            else:
                leg_lol = [(L, 0.0), free]
                top_prof = [(L, wall.H), (free[0], h_far)]
                lo, hi = L, free[0]
            if w["mode"] == "flat":
                base_prof = None                        # flat base at base_el=0
            else:
                base_prof = [(x, e) for (x, e) in foot_top
                             if lo - 1e-9 <= x <= hi + 1e-9]
            # `BatteredWall`'s lol IS its plumb face and it batters the face it
            # offsets toward, so handing it the earth-side line battered the
            # exposed CREEK face and stood the wall plumb on the retained earth
            # -- backwards to B3-1A Type 1, which batters the earth face and
            # keeps the creek face plumb (#314). The magnitude was right, only
            # the side was wrong, so nothing in the volume or the length moved
            # and nothing caught it: on a flared wing each base stood up to
            # 2 in PROUD of the panel's creek face and crossed back inside it
            # partway up, a visible twist on the front elevation.
            #
            # So place the lol on the CREEK face -- the earth-side line
            # stepped one t_top toward the channel -- and offset back the
            # other way. The top-of-wall footprint is identical either way;
            # only the base thickening swaps sides, into the backfill where it
            # belongs, and the trapezoid section is untouched, so the volume is
            # unchanged to the digit.
            #
            # Both profiles are keyed on the plan coordinate (`key_index=0`, so
            # x) and both are curves of THIS leg's own stations: the design top
            # of wall, and the slice of the stepped footing top the base rides.
            # Moving the lol without moving them by the same delta reads both
            # at the wrong station -- the corner picks up the wrong
            # top-of-wall, and a stepped base stops coinciding with the
            # footing's own riser.
            # outward_normals(leg, -1.0) is the direction the stem USED to
            # offset into: toward the channel, the same hand the footing's toe
            # takes. So it is exactly the earth-face -> creek-face step.
            n_creek = outward_normals(leg_lol, -1.0)[0]
            dx, dy = n_creek[0] * wall.T, n_creek[1] * wall.T
            dkey = (dx, dy)[0]                        # key_index=0 -> shift x
            bw = BatteredWall(
                f"{name} wingwall {side}",
                lol=[(x + dx, y + dy) for (x, y) in leg_lol],
                top_profile=[(k + dkey, e) for (k, e) in top_prof],
                key_index=0, base_el=0.0, t_top=wall.T, batter=wall.batter,
                side=+1.0,
                base_profile=(None if base_prof is None
                              else [(k + dkey, e) for (k, e) in base_prof]),
                ifc="IfcWall", layer="S-CONC")
            model.add(Element.from_geometry(
                bw.name, bw, ifc_class="IfcWall", layer="S-CONC",
                quantities={"length_ft": wl, "volume_cf": bw.volume_cf}))
            wws.append({"length_ft": wl})

        # --- headwall panel ---------------------------------------------------
        stem = headwall_stem(f"{name} headwall panel", wall, L, s["pipe"],
                             skew_deg=float(s.get("skew_deg", 0.0)))
        model.add(Element.from_geometry(
            stem.name, stem, ifc_class="IfcWall", layer="S-CONC",
            quantities={"length_ft": L, "volume_cf": stem.volume_cf}))

        # --- Type 836 barrier: ONE continuous rail across the Type-C wings AND
        #     the headwall, battered face to the earth/roadway side ------------
        barrier_reinf = []
        typec = [side for side in ("left", "right")
                 if side in wings and wings[side]["typ"] == "C"]
        if typec:
            tcb = d90.get("type_c_barrier") or {}
            wcb = wings[typec[0]]["wc"].get("barrier")
            row = wcb if (isinstance(wcb, dict) and wcb.get("shape")) else tcb
            if not row.get("shape"):
                raise ValueError(
                    f"{name}: Type C wall requires a barrier -- supply a "
                    f"d90.type_c_barrier section (shape + profile/dims)")
            section = type_836_section(row)
            # rail LOL: cross the headwall (0,0)->(L,0), extend onto each Type-C
            # wing; top rides wall.H at the corners, h_far at the free ends.
            rail_lol = [(0.0, 0.0), (L, 0.0)]
            top = [(0.0, wall.H), (L, wall.H)]
            if "left" in typec:
                lf = wings["left"]["free"]
                rail_lol.insert(0, lf)
                top.append((lf[0], float(wings["left"]["wc"]["h_far_ft"])))
            if "right" in typec:
                rf = wings["right"]["free"]
                rail_lol.append(rf)
                top.append((rf[0], float(wings["right"]["wc"]["h_far_ft"])))
            rail = rail_barrier(f"{name} headwall barrier rail", rail_lol,
                                _merge_profile(top), section, key_index=0,
                                side_sign=1.0, seat=float(wall.T),
                                haunch_ft=float(row.get("haunch_ft", 1.0)))
            rail_len = _lol_length(rail_lol)
            model.add(Element.from_geometry(
                rail.name, rail, ifc_class="IfcWall", layer="S-CONC",
                quantities={"length_ft": rail_len, "volume_cf": rail.volume_cf}))
            barrier_reinf += barrier_bars(section, row, run_length=rail_len,
                                          cover_in=float(s.get("cover_in", 2.0)))

        # sched is guaranteed present (checked up front): a D90 headwall always
        # carries wall/footing reinforcing, so emit unconditionally.
        _emit_bars(model, name, headwall_bars(
            wall_length=L, design_h=wall.H, footing_w=wall.W,
            pipe=s["pipe"], wingwalls=wws, schedule=sched,
            cover_in=float(s.get("cover_in", 2.0))) + barrier_reinf)

        # --- per-structure placement: bearing (rotate about Z) + planar
        # offset + flow-line elevation -------------------------------------
        bearing_deg = float(s.get("bearing_deg", 0.0))
        pos = s.get("position_ft", [0.0, 0.0])
        dx, dy = float(pos[0]), float(pos[1])
        # FL = flow line = pipe INVERT elevation. The opening's invert sits at
        # local z = center_z - r (center_z defaults to r + 0.5), so lift the
        # whole structure by fl_elev - invert_local -- placing the emitted
        # invert EXACTLY at fl_elev_ft, per the spec ("FL = pipe invert"). With
        # no fl_elev_ft the structure stays on the local datum (z=0), unplaced.
        if "fl_elev_ft" in s:
            pr = float(s["pipe"]["dia_ft"]) / 2.0
            cz_local = float(s["pipe"].get("center_z_ft", pr + 0.5))
            zlift = float(s["fl_elev_ft"]) - (cz_local - pr)
            (ew_fls if s.get("kind", "headwall") == "endwall"
             else hw_fls).append(float(s["fl_elev_ft"]))
        else:
            zlift = 0.0
        _place(model.elements[start:], bearing_deg, dx, dy, zlift)

    # Flow-line sanity: when both an inlet headwall and an outlet endwall carry
    # an explicit FL, the outlet cannot sit HIGHER than the inlet (water runs
    # downhill). Compare the highest headwall FL against the lowest endwall FL.
    if hw_fls and ew_fls and min(ew_fls) > max(hw_fls):
        raise ValueError(
            f"EW flow line {min(ew_fls):.3f} > HW flow line {max(hw_fls):.3f}: "
            "the outlet endwall cannot sit higher than the inlet headwall")
    return model
