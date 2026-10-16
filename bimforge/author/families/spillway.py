"""spillway — concrete spillway structures (the spillway-pilot build_spillways port,
generalized: no station constants, no project elevations — everything comes
from params).

Two optional structure groups, one or both:

  principal — a symmetric flared concrete chute:
      slab             level top, `half_outline` mirrored about x=0
      cutoff walls     straight across the inlet/outlet slab faces
      chute walls (2)  vertical LOL face, `wall_top_thickness_ft` at the top,
                       battered `wall_batter_run_over_rise` outward, lofted
                       along the mirrored `half_lol` (BatteredWall)
      wing walls (2)   the 90-degree return at the outlet, keyed on x
      sloped concrete  the 2:1 fill between the chute floor and the wall:
                       z = top_el + (|x| - half_width)/slope, a per-vertex-top
                       Prism whose plan TERMINATES at `ends_at_local_y_ft`
      boxes            optional plain appurtenance Prisms

  auxiliary — a constant section swept across a clear width B:
      chute slab       one (t, el) profile ring x B (SectionPrism)
      ogee weir        coordinate-table ring less a keyholed void former ring
      chute blocks /   arrayed SectionPrisms with the end-piece width solve
      dentated sill    and a +/-0.02 ft closure check (refuse-to-build)
      end walls (2)    the same BatteredWall family, plus footing + cutoff key

Local frames are right-handed with +Z up; each structure carries an explicit
`placement:` — `origin: [E, N]` (project CRS feet), `y_dir: [dE, dN]` (or
`y_axis: [[E,N],[E,N]]`, two points defining +Y), and `el0`, the elevation
datum the params were transcribed against (local z = elevation - el0).
Placement re-shifts emitted z onto the PROJECT datum (model z = elevation -
ctx.base_h), so el0 never leaks into the outputs. The family does NOT solve
alignments; a bid-side step resolves stations to the origin/direction it
passes in.

Geometry objects are built in the LOCAL frame (their analytic volumes are the
declared Qtos) and their `body_solids()` dicts are rigid-transformed into the
model frame — a rotation about +Z moves no volume, so the declared quantity
still IS the emitted solid's volume (the spillway-pilot QC invariant).
"""
from __future__ import annotations

import math

from bimforge.author.alignment import poly_area
from bimforge.author.model import Element, StructureModel
from bimforge.author.primitives import (
    BatteredWall, Prism, SectionPrism, place_exact)

REQUIRED_COMMON = ("wall_top_thickness_ft", "wall_batter_run_over_rise",
                   "cutoff_wall_thickness_ft")

_WINDS = ("north", "north-east", "east", "south-east",
          "south", "south-west", "west", "north-west")


def compass(u) -> str:
    """Name a (dE, dN) direction, so element names say "west wall", not
    "+x" (spillway-pilot naming convention, deterministic given the placement)."""
    az = math.degrees(math.atan2(u[0], u[1])) % 360.0
    return _WINDS[int((az + 22.5) // 45) % 8]


def mirror_half(half: list) -> list:
    """A full symmetric ring from the +x half (the spillway-pilot mirror_half trick;
    first and last points sit on/at the centreline ends)."""
    pts = [tuple(p) for p in half]
    return pts + [(-x, y) for x, y in reversed(pts[:-1])]


def solve_block_row(clear_width_ft: float, width_in: float,
                    gap_in: float) -> tuple[int, float]:
    """Fit a row of typ-width blocks at typ clear gap into a clear width:
    n = round((B + g) / (w + g)) pieces, and the end-piece width (inches)
    that closes the row exactly (the qc-spillways.md end-piece solve)."""
    w, g = width_in / 12.0, gap_in / 12.0
    if w <= 0 or g < 0:
        raise ValueError("block width must be positive and gap non-negative")
    n = int(round((clear_width_ft + g) / (w + g)))
    if n < 2:
        raise ValueError(f"only {n} block(s) fit {clear_width_ft:g} ft — "
                         f"a row needs at least the two end pieces")
    end_in = (clear_width_ft * 12.0
              - (n - 2) * width_in - (n - 1) * gap_in) / 2.0
    return n, end_in


# ------------------------------------------------------------ local frame
def _frame(placement, ctx, tag):
    if not placement:
        raise ValueError(f"spillway {tag}: 'placement' block is required")
    if placement.get("el0") is None:
        raise ValueError(f"spillway {tag}: placement needs 'el0' — the "
                         f"elevation datum (local z = elevation - el0)")
    el0 = float(placement["el0"])
    if placement.get("y_axis"):
        (e0, n0), (e1, n1) = placement["y_axis"]
        dy = (float(e1) - float(e0), float(n1) - float(n0))
    else:
        dy = tuple(placement.get("y_dir") or (0.0, 1.0))
    length = math.hypot(*dy)
    if length < 1e-9:
        raise ValueError(f"spillway {tag}: placement +Y direction is "
                         f"zero-length")
    uy = (dy[0] / length, dy[1] / length)
    ux = (uy[1], -uy[0])                       # right-handed with +Z up
    org = placement.get("origin") or (0.0, 0.0)
    ox, oy = ctx.local(float(org[0]), float(org[1]))
    # el0 is only the params' transcription datum (local z = elevation - el0);
    # the MODEL convention is z = elevation - ctx.base_h (ProjectContext.local).
    # Placement carries the difference so emitted geometry lands on the
    # project datum whatever el0 the spec was written against — otherwise
    # every IFC/DXF/KML consumer sits (el0 - base_h) ft off, silently.
    zs = el0 - ctx.base_h

    def world(x, y):
        return (ox + ux[0] * x + uy[0] * y, oy + ux[1] * x + uy[1] * y)

    return world, ux, uy, el0, zs


def _xf_solid(d: dict, world, zs: float) -> dict:
    """Rigid-place one local-frame solids dict into the model frame."""
    out = dict(d)
    kind = d["kind"]
    if kind in ("prism", "fill"):
        out["base"] = [world(x, y) for x, y in d["base"]]
        out["holes"] = [[world(x, y) for x, y in h]
                        for h in d.get("holes") or []]
        out["z_bot"] = d["z_bot"] + zs
        if d.get("z_top") is not None:
            out["z_top"] = d["z_top"] + zs
        if d.get("top_z") is not None:
            out["top_z"] = [z + zs for z in d["top_z"]]
        if d.get("bottom_z") is not None:
            out["bottom_z"] = [z + zs for z in d["bottom_z"]]
        if kind == "fill":
            out["cuts"] = [_xf_solid(c, world, zs) for c in d["cuts"]]
    elif kind == "mesh":
        # world() is a plan rotation + offset: the same rigid map moves an
        # extrusion's plane and sweep vector, so it stays exact (#330).
        (ox, oy), (ax, ay), (bx, by) = (world(0.0, 0.0), world(1.0, 0.0),
                                        world(0.0, 1.0))
        out = place_exact(
            d, ((ax - ox, bx - ox, 0.0), (ay - oy, by - oy, 0.0),
                (0.0, 0.0, 1.0)), (ox, oy, zs))
        out["verts"] = [world(x, y) + (z + zs,) for x, y, z in d["verts"]]
        out["plan"] = [[world(x, y) for x, y in ring]
                       for ring in d.get("plan") or []]
    else:
        raise ValueError(f"spillway: cannot place solids kind {kind!r}")
    return out


def _placed(geoms, world, zs: float) -> list[dict]:
    geoms = geoms if isinstance(geoms, (list, tuple)) else [geoms]
    return [_xf_solid(d, world, zs) for g in geoms for d in g.body_solids()]


def _add(m, name, geoms, world, zs, ifc, quantities, description=None):
    m.add(Element(name, ifc, geometry=_placed(geoms, world, zs),
                  quantities=quantities, layer="S-CONC-OTLN",
                  description=description))


# --------------------------------------------------------------- principal
def _build_principal(m: StructureModel, P: dict, common: dict, ctx) -> None:
    world, ux, _uy, el0, zs = _frame(P.get("placement"), ctx, "principal")
    t_top = common["wall_top_thickness_ft"]
    batter = common["wall_batter_run_over_rise"]
    hands = ((+1.0, compass(ux)), (-1.0, compass((-ux[0], -ux[1]))))

    S = P["slab"]
    top_el, th = float(S["top_el"]), float(S["thickness_ft"])
    ring = mirror_half(S["half_outline"])
    slab = Prism("principal spillway slab", ring,
                 top_el - th - el0, top_el - el0)
    _add(m, slab.name, slab, world, zs, "IfcSlab",
         {"volume_cf": slab.volume_cf, "area_sf": slab.area_sf,
          "height_ft": th},
         f"level top of slab EL {top_el:.1f}, {th:g}' thick, "
         f"{slab.area_sf:,.0f} sf")

    # cutoff walls: straight across the inlet/outlet slab faces
    ct = common["cutoff_wall_thickness_ft"]
    for c in S.get("cutoffs") or []:
        d = float(c["depth_ft"])
        if c["edge"] not in ("inlet", "outlet"):
            # inlet and outlet slab faces have different half-widths, so a
            # typo'd edge would silently build the WRONG cutoff volume.
            raise ValueError(f"cutoff edge must be 'inlet' or 'outlet', "
                             f"got {c['edge']!r}")
        if c["edge"] == "inlet":
            x = max(px for px, py in ring if abs(py) < 1e-6)
            box = [(-x, 0.0), (x, 0.0), (x, ct), (-x, ct)]
        else:
            y = max(py for _px, py in ring)
            x = max(px for px, py in ring if abs(py - y) < 1e-6)
            box = [(-x, y - ct), (x, y - ct), (x, y), (-x, y)]
        cut = Prism(f"principal spillway {c['edge']} cutoff wall", box,
                    top_el - d - el0, top_el - th - el0)
        _add(m, cut.name, cut, world, zs, "IfcWall", {"volume_cf": cut.volume_cf},
             f"{ct:g}' wide, {d:g}' below top of slab "
             f"(bottom EL {top_el - d:.1f})")

    # chute walls (2): mirrored BatteredWalls, top-of-wall keyed on local y
    W = P.get("chute_wall")
    lol = [tuple(p) for p in (W or {}).get("half_lol") or []]
    if W:
        tow = [(float(s), float(el) - el0) for s, el in W["top_profile"]]
        for sgn, hand in hands:
            poly = [(sgn * x, y) for x, y in lol]
            w = BatteredWall(f"principal spillway chute wall ({hand})", poly,
                             tow, 1, top_el - el0, t_top, batter, sgn)
            _add(m, w.name, w, world, zs, "IfcWall", {"volume_cf": w.volume_cf},
                 f"vertical LOL face, {t_top:g}' at top, battered "
                 f"{batter:g} outward to the slab")

    # outlet wing walls (2): the 90-degree return, keyed on local x, running
    # from the chute-wall LOL out to to_x_ft
    G = P.get("wing_wall")
    if G:
        if not lol:
            raise ValueError("spillway principal: wing_wall needs chute_wall "
                             "(the return starts at the chute-wall LOL)")
        gy = float(G["lol_y_ft"])
        gtow = [(float(s), float(el) - el0) for s, el in G["top_profile"]]
        x_in, x_out = lol[-1][0], float(G["to_x_ft"])
        for sgn, hand in hands:
            poly = [(sgn * x_in, gy), (sgn * x_out, gy)]
            prof = [(sgn * s, v) for s, v in gtow]
            prof = sorted(prof) if sgn < 0 else prof
            w = BatteredWall(f"principal spillway outlet wing wall ({hand})",
                             poly, prof, 0, top_el - el0, t_top, batter, -sgn)
            _add(m, w.name, w, world, zs, "IfcWall", {"volume_cf": w.volume_cf},
                 f"90-degree return at the outlet, "
                 f"{abs(x_out - x_in):.2f}' from the chute wall LOL")

    # sloped concrete (2): z = top_el + (|x| - half_width)/slope. The plan
    # TERMINATES where the wall reaches the chute floor edge
    # (`ends_at_local_y_ft`): carrying it on down the parallel throat instead
    # adds a zero-width needle, which is what a solid modeller quietly
    # repairs away — taking real volume with it (spillway-pilot l.407-410 lesson).
    SC = P.get("sloped_concrete")
    if SC:
        if not lol:
            raise ValueError("spillway principal: sloped_concrete needs "
                             "chute_wall (the slope dies into the wall LOL)")
        hw = float(SC["floor_half_width_ft"])
        slope = float(SC["slope_h_to_v"])
        face = ring[0][0]                     # inlet-face half width
        end_y = float(SC["ends_at_local_y_ft"])
        plan = ([(hw, 0.0), (face, 0.0)]
                + [p for p in lol if p[1] < end_y - 1e-6] + [(hw, end_y)])
        for sgn, hand in hands:
            pl2 = [(sgn * x, y) for x, y in plan]
            top_z = [top_el - el0 + (abs(x) - hw) / slope for x, _y in pl2]
            p = Prism(f"principal spillway sloped concrete ({hand})", pl2,
                      top_el - el0, top_z=top_z)
            _add(m, p.name, p, world, zs, "IfcSlab", {"volume_cf": p.volume_cf},
                 f"{slope:g}:1 transition from the {2 * hw:g}' chute floor "
                 f"out to the wall, top EL {top_el:.1f} + (offset-{hw:g})"
                 f"/{slope:g}")

    # optional appurtenance boxes: plain prisms, e.g. equipment pads
    for b in P.get("boxes") or []:
        p = Prism(f"principal spillway {b['name']}",
                  [tuple(q) for q in b["plan"]],
                  float(b["bot_el"]) - el0, float(b["top_el"]) - el0)
        _add(m, p.name, p, world, zs, "IfcBuildingElementProxy",
             {"volume_cf": p.volume_cf})


# --------------------------------------------------------------- auxiliary
def _build_auxiliary(m: StructureModel, A: dict, common: dict, ctx) -> None:
    world, _ux, uy, el0, zs = _frame(A.get("placement"), ctx, "auxiliary")
    t_top = common["wall_top_thickness_ft"]
    batter = common["wall_batter_run_over_rise"]
    ct = common["cutoff_wall_thickness_ft"]
    B = float(A["clear_width_ft"])
    if B <= 0:
        raise ValueError("spillway auxiliary: clear_width_ft must be positive")

    # chute slab: one closed (t, el) profile ring swept the clear width
    S = A.get("slab")
    if S:
        prof = [(float(t), float(el) - el0) for t, el in S["profile_t_el"]]
        sp = SectionPrism("auxiliary spillway chute slab", prof, B)
        _add(m, sp.name, sp, world, zs, "IfcSlab", {"volume_cf": sp.volume_cf},
             f"{sp.area_sf:.2f} sf section x {B:g}'")

    # ogee weir: the coordinate-table ring, less the void former — carried
    # as ONE profile ring that both draws and integrates to the net section
    # (never a boolean). The void former stands ON the weir base, so the
    # generic zero-width keyhole bridge (`SectionPrism(voids=...)`)
    # degenerates — instead the REVERSED void ring is spliced through the
    # shared base edge, exactly as the spillway-pilot reference builder does.
    O = A.get("ogee")
    if O:
        coords = [(float(c[0]), float(c[-1])) for c in O["coordinates"]]
        outer = ([(0.0, float(O["toe_el"]) - el0)]
                 + [(t, el - el0) for t, el in coords[1:]])
        void = [(float(t), float(el) - el0)
                for t, el in O.get("eps_void_t_el") or []]
        eps_sf = poly_area(void)
        sp = SectionPrism("auxiliary spillway ogee weir",
                          outer + list(reversed(void)), B)
        _add(m, sp.name, sp, world, zs, "IfcWall", {"volume_cf": sp.volume_cf},
             f"ogee crest from a {len(coords)}-point coordinate table; "
             f"{sp.area_sf:.2f} sf net of the {eps_sf:.2f} sf "
             f"expanded-polystyrene void former, x {B:g}'")

    # chute blocks + dentated sill: arrayed constant sections with the
    # end-piece width solve and the closure check (refuse-to-build)
    for key, label in (("chute_blocks", "chute blocks"),
                       ("dentated_sill", "dentated sills")):
        C = A.get(key)
        if not C:
            continue
        w_in, g_in = float(C["width_in"]), float(C["gap_in"])
        n, end_solved_in = solve_block_row(B, w_in, g_in)
        end = float(C.get("end_in", end_solved_in)) / 12.0
        w, g = w_in / 12.0, g_in / 12.0
        prof = [(float(t), float(el) - el0) for t, el in C["profile_t_el"]]
        solids, vol, s = [], 0.0, B
        for i in range(n):
            wi = end if i in (0, n - 1) else w
            solids.append(SectionPrism(f"{label} {i}", prof, wi, y0=s - wi))
            vol += solids[-1].volume_cf
            s -= wi + g
        got = B - (s + g)
        if abs(got - B) > 0.02:
            raise ValueError(
                f"auxiliary spillway {label} span {got:.3f} ft, not {B:g} ft "
                f"— check the {w_in:g}\" / {g_in:g}\" spacing")
        _add(m, f"auxiliary spillway {label}", solids, world, zs, "IfcMember",
             {"count": n, "volume_cf": vol},
             f"{n} off at {w_in:g}\" wide / {g_in:g}\" clear, ends "
             f"{end * 12:g}\"; {poly_area(prof):.3f} sf each")

    # end retaining walls (2) + footings with cutoff keys
    R = A.get("retaining_wall")
    if R:
        t0, t1 = float(R["from_t_ft"]), float(R["to_t_ft"])
        base_el = float(R["base_el"])
        tow = [(float(t), float(el) - el0) for t, el in R["top_profile"]]
        fw, off = float(R["footing_width_ft"]), float(R["footing_offset_ft"])
        tf = float(R["footing_thickness_ft"])
        cd = float(R["cutoff_depth_ft"])
        L = t1 - t0
        for s_lol, hand, sgn in ((0.0, compass((-uy[0], -uy[1])), -1.0),
                                 (B, compass(uy), +1.0)):
            poly = [(t0, s_lol), (t1, s_lol)]
            w = BatteredWall(f"auxiliary spillway {hand} retaining wall",
                             poly, tow, 0, base_el - el0, t_top, batter, -sgn)
            _add(m, w.name, w, world, zs, "IfcWall", {"volume_cf": w.volume_cf},
                 f"{L:.2f}' long, base EL {base_el:.1f}")

            near = s_lol - sgn * off
            far = s_lol + sgn * (fw - off)
            ftg_ring = [(t0, min(near, far)), (t1, min(near, far)),
                        (t1, max(near, far)), (t0, max(near, far))]
            ftg = Prism(f"{hand} wall footing pad", ftg_ring,
                        base_el - tf - el0, base_el - el0)
            cut_lo = min(near, near - sgn * ct)
            cut_hi = max(near, near - sgn * ct)
            key_ring = [(t0, cut_lo), (t1, cut_lo),
                        (t1, cut_hi), (t0, cut_hi)]
            keyp = Prism(f"{hand} wall footing cutoff key", key_ring,
                         base_el - cd - el0, base_el - tf - el0)
            # closed form: L*fw*tf + L*ct*(cd - tf) — exactly the two prisms
            _add(m, f"auxiliary spillway {hand} wall footing", [ftg, keyp],
                 world, zs, "IfcFooting",
                 {"volume_cf": ftg.volume_cf + keyp.volume_cf},
                 f"{fw:g}' x {tf:g}' at top EL {base_el:.1f}, with a "
                 f"{ct:g}' x {cd:g}' cutoff key")


# -------------------------------------------------------------------- build
def build(params: dict, ctx) -> StructureModel:
    common = params.get("common") or {}
    missing = [k for k in REQUIRED_COMMON if common.get(k) is None]
    if missing:
        raise ValueError(f"spillway params missing common.{missing}")
    if not (params.get("principal") or params.get("auxiliary")):
        raise ValueError("spillway params need at least one of "
                         "'principal' / 'auxiliary'")
    m = StructureModel("spillway", ctx)
    if params.get("principal"):
        _build_principal(m, params["principal"], common, ctx)
    if params.get("auxiliary"):
        _build_auxiliary(m, params["auxiliary"], common, ctx)
    return m
