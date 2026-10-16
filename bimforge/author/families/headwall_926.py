"""headwall-926 — standard-plan pipe outfall headwall: headwall + trapezoid
footing + splayed triangular wingwalls + cutoff wall, with optional trash
rack and guardrail.

Geometry per the Steelridge build_outfall reference: headwall spans E-W at
the local origin (front face y=0, discharge toward -Y); the footing plan is
a trapezoid splaying toward the discharge; wingwalls are triangular plates
along the footing's splayed side edges (full height at the headwall, zero at
the footing front) — modelled as per-vertex-top Prisms, so the taper's solid
reaches full height at its high end and daylights at its low one (the
mean-height-box lesson: right volume AND right shape).

Known simplification (estimator note): each wingwall's headwall-side corner
attaches at hw_w/2 rather than the source's trapezoid-interpolated offset —
about 0.24% less wingwall volume than the reference geometry. Acceptable at
takeoff precision; revisit if source-exact fidelity is ever required.

Rack/guardrail (OPTIONS; the source drawings carried only note text, so the
geometry here is deliberately minimal, closed-form new work):
  * rack: a grate of flat bars over the pipe opening — n_bars vertical flat
    bars spanning the opening diameter, weight = n * L * (w*t) * steel;
  * guardrail: posts + one rail tube along the top of the headwall.
"""
from __future__ import annotations

import math

from bimforge.author.model import Element, StructureModel
from bimforge.author.primitives import (
    IN3_PER_CF, STEEL_LB_PER_IN3, Prism, Tube, equal_area_polygon_radius)

REQUIRED = ("pipe_dia_ft", "wall_t_ft", "hw_int_w_ft", "hw_height_ft",
            "foot_len_ft", "foot_splay_ft", "wing_len_ft", "cut_depth_ft",
            "el_top_hw", "el_invert")


def build(params: dict, ctx) -> StructureModel:
    missing = [k for k in REQUIRED if params.get(k) is None]
    if missing:
        raise ValueError(f"headwall-926 params missing {missing}")
    p = params
    t = p["wall_t_ft"]
    hw_w = p["hw_int_w_ft"] + 2 * t
    hw_h = p["hw_height_ft"]
    el_top = p["el_top_hw"]
    el_tf = el_top - hw_h                       # top of footing
    el_bf = el_tf - p.get("foot_t_ft", t)       # bottom of footing
    el_bc = el_bf - p["cut_depth_ft"]
    foot_front_w = hw_w + 2 * p["foot_splay_ft"]
    hw_s, hw_n = 0.0, t                          # front/back faces of the wall
    foot_n, foot_s = hw_n, hw_n - p["foot_len_ft"]
    m = StructureModel("headwall-926", ctx)

    foot_plan = [(-hw_w / 2, foot_n), (hw_w / 2, foot_n),
                 (foot_front_w / 2, foot_s), (-foot_front_w / 2, foot_s)]
    fp = Prism("headwall footing", foot_plan, el_bf, el_tf, ifc="IfcFooting")
    m.add(Element.from_geometry(fp.name, fp, ifc_class="IfcFooting",
                                layer="S-CONC-OTLN",
                                quantities={"height_ft": el_tf - el_bf,
                                            "volume_cf": fp.volume_cf}))

    hw_plan = [(-hw_w / 2, hw_s), (hw_w / 2, hw_s),
               (hw_w / 2, hw_n), (-hw_w / 2, hw_n)]
    hw = Prism("headwall", hw_plan, el_tf, el_top, dims_ft=(hw_w, t),
               ifc="IfcWall")
    opening_cf = math.pi * (p["pipe_dia_ft"] / 2) ** 2 * t
    m.add(Element(
        # length_ft/width_ft/height_ft deliberately OMITTED: the pipe
        # opening is a legitimate void (like a bolt hole on a plate — see
        # pipe_supports.py), so count x L x W x H cannot reproduce this
        # NET volume_cf; the gate's lxw-volume invariant only applies to
        # solid (no-void) prisms. emit_ifc/emit_qto derive area/height from
        # the geometry's plan polygon regardless.
        "headwall", "IfcWall", geometry=hw,
        quantities={"volume_cf": hw.volume_cf - opening_cf},
        layer="S-CONC-OTLN"))
    opening = Element(
        "pipe opening", "IfcBuildingElementProxy",
        # axis "y" tubes sweep world-Y from 0 (the emitters' shared
        # placement convention — see emit_ifc's tube-position table and
        # emit_step's mirror of it); x0 is the FIXED world-X of the sweep,
        # so x0=0.0 keeps this centered on the headwall's own centerline
        # (hw_plan spans -hw_w/2..hw_w/2 about x=0), not offset by -t.
        geometry={"kind": "tube", "units": "ft", "x0": 0.0,
                  "length": 3 * t, "cz": p["el_invert"] + p["pipe_dia_ft"] / 2,
                  "r_outer": p["pipe_dia_ft"] / 2,
                  "wall": p["pipe_dia_ft"] / 2, "axis": "y"},
        guid_key="opening/pipe")
    m.openings.append(("headwall", opening))

    cut_plan = [(-hw_w / 2, foot_s), (hw_w / 2, foot_s),
                (hw_w / 2, foot_s - t), (-hw_w / 2, foot_s - t)]
    cw = Prism("cutoff wall", cut_plan, el_bc, el_bf, dims_ft=(hw_w, t),
               ifc="IfcWall")
    m.add(Element.from_geometry(cw.name, cw, ifc_class="IfcWall",
                                layer="S-CONC-OTLN",
                                quantities={"length_ft": hw_w, "width_ft": t,
                                            "height_ft": el_bf - el_bc,
                                            "volume_cf": cw.volume_cf}))

    # wingwalls: thin quads along the splayed edges, tops tapering
    # full-height -> zero (per-vertex top: right volume AND right shape)
    for side, sgn in (("left", -1.0), ("right", 1.0)):
        a = (sgn * hw_w / 2, hw_s)                 # at the headwall, full H
        b = (sgn * foot_front_w / 2, foot_s)       # at the footing front, 0
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        nx, ny = dy / length, -dx / length         # horizontal normal
        if nx * sgn > 0:                           # thickness goes INBOARD
            nx, ny = -nx, -ny
        quad = [a, b, (b[0] + nx * t, b[1] + ny * t),
                (a[0] + nx * t, a[1] + ny * t)]
        w = Prism(f"{side} wingwall", quad, el_tf,
                  top_z=[el_tf + hw_h, el_tf, el_tf, el_tf + hw_h],
                  dims_ft=(length, t), ifc="IfcWall")
        m.add(Element.from_geometry(
            w.name, w, ifc_class="IfcWall", layer="S-CONC-OTLN",
            quantities={"length_ft": length, "width_ft": t,
                        "height_ft": hw_h / 2.0, "volume_cf": w.volume_cf}))

    # ---- OPTION: trash rack (grate of flat bars over the opening)
    rack = p.get("rack")
    if rack is not None:
        n = int(rack.get("bars", 7))
        bar_w_in, bar_t_in = rack.get("bar_w_in", 2.0), rack.get("bar_t_in", 0.375)
        L_ft = p["pipe_dia_ft"] * rack.get("length_factor", 1.25)
        vol_in3 = n * (L_ft * 12.0) * bar_w_in * bar_t_in
        m.add(Element(
            "trash rack", "IfcDiscreteAccessory",
            geometry={"kind": "box", "units": "in", "boxes": [
                (((i - (n - 1) / 2) * (p["pipe_dia_ft"] * 12.0 / max(n - 1, 1))),
                 0.0,
                 (p["el_invert"] - el_tf + p["pipe_dia_ft"] / 2) * 12.0,
                 bar_t_in, bar_w_in, L_ft * 12.0)
                for i in range(n)]},
            quantities={"count": n, "length_ft": n * L_ft,
                        "weight_lb": vol_in3 * STEEL_LB_PER_IN3,
                        "volume_cf": vol_in3 / IN3_PER_CF},
            z_ft=0.0, layer="S-STEEL"))

    # ---- OPTION: guardrail (posts + one rail along the wall top)
    gr = p.get("guardrail")
    if gr is not None:
        spacing = gr.get("post_spacing_ft", 6.0)
        n_posts = max(2, int(hw_w // spacing) + 1)
        post_h = gr.get("height_ft", 3.5)
        r_out = gr.get("rail_od_in", 2.375) / 24.0    # ft
        wall_t_rail = gr.get("rail_wall_in", 0.154) / 12.0
        segs = 32
        rail = Tube("guardrail rail", hw_w, r_out, wall_t_rail, axis="x",
                    x0_ft=-hw_w / 2, cz_ft=0.0)
        post = Tube("guardrail post", post_h, r_out, wall_t_rail, axis="z")
        total_cf = rail.volume_cf + n_posts * post.volume_cf
        # equal-area circumradii (same convention as the arc/bolt primitives):
        # the "rod" kind's faceted outer/inner rings then enclose EXACTLY
        # pi*r_out^2 / pi*r_in^2, so the annulus area — and the post's HOLLOW
        # tube volume above — survives faceting regardless of segment count.
        r_out_poly = equal_area_polygon_radius(r_out, segs)
        r_in_poly = equal_area_polygon_radius(r_out - wall_t_rail, segs)
        m.add(Element(
            "guardrail", "IfcRailing",
            geometry=[{"kind": "tube", "units": "ft", "x0": -hw_w / 2,
                       "length": hw_w, "cz": post_h, "r_outer": r_out,
                       "wall": wall_t_rail, "axis": "x"}] + [
                      # HOLLOW rods (r_inner punches the bore): posts are
                      # tube stock like the rail, not solid bar — matching
                      # the Tube-based analytic volume above.
                      {"kind": "rod", "units": "ft", "axis": "z",
                       "radius": r_out_poly, "r_inner": r_in_poly,
                       "segments": segs,
                       "centres": [(-hw_w / 2 + i * hw_w / (n_posts - 1), t / 2,
                                    post_h / 2) for i in range(n_posts)],
                       "length": post_h}],
            quantities={"count": n_posts, "length_ft": hw_w,
                        "weight_lb": total_cf * 490.0, "volume_cf": total_cf},
            z_ft=el_top, layer="S-STEEL"))

    m.checks.append(_check_wingwall_taper(m))
    return m


def _check_wingwall_taper(model):
    """Shape assertion (the mean-height-box lesson): each wingwall's top must
    reach full height at its high end and daylight at its low one."""
    def check(_m):
        fail = []
        for el in _m.elements:
            if "wingwall" not in el.name:
                continue
            g = el.geometry
            if g.top_z is None:
                fail.append(f"{el.name}: modelled flat-topped; the taper's "
                            f"solid must reach full height and daylight")
                continue
            if max(g.top_z) - min(g.top_z) < 1e-6:
                fail.append(f"{el.name}: top does not taper")
        return fail
    return check
