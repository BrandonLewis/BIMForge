"""pipe-supports — aerial pipe-crossing supports: footing + grout pad +
fabricated steel saddle assembly + anchor/collar bolts, per support.

Port of the pipe-supports-pilot builder (1,913 lines) onto the author kernel. Every
quantity is a closed form; the sheet-underdetermined dimensions arrive as
`assumptions` (each with a documented reason — the gate refuses a bare one);
the ~30 validate() checks are registered gate checks.

Model frame: X along the pipe, 0 at the FIRST support's station; Y transverse
from the pipe centreline; Z from the LOWER of the footing bottoms. Set
`project.epsg` when survey control exists; otherwise the spec must opt in to
a local IFC (`outputs.ifc_allow_local: true`) — the kernel refuses silently
local models.
"""
from __future__ import annotations

from bimforge.author.model import Element, StructureModel
from bimforge.author.primitives import (
    ARC_SEGMENTS, IN3_PER_CF, ArcBand, Bolt, Plate, ShapedStiffener,
    equal_area_polygon_radius)

REQUIRED = ("supports", "span", "footing", "grout", "rebar", "saddle",
            "reference", "assumptions", "validation")

#: Anchor bolts sit at the strap's quarter points in X and inboard of the
#: base plate's ends by this much in Y (pipe-supports-pilot 3/S2.1 read: 24.75/2 - 1.875
#: = the 10.5 in gauge).
ANCHOR_BOLT_END_INSET_IN = 1.875

#: A 3/4 in finished hex nut is 0.641 in deep — the figure pipe-supports-pilot's
#: collar-bolt length check and its anchor-bolt-projection assumption both
#: carry ("A 3/4 in nut is 0.641 in deep").
HEX_NUT_DEPTH_IN = 0.641


# ------------------------------------------------------------- (a) closed forms
def assumption(m: dict, key: str):
    for a in m["assumptions"]:
        if a["key"] == key:
            return a["value"]
    raise KeyError(f"undocumented assumption: {key}")


def arc_segments_for(m: dict) -> int:
    return m.get("validation", {}).get("arc_segments", ARC_SEGMENTS)


def footing_cy(m: dict) -> float:
    f = m["footing"]
    return f["count"] * f["length_ft"] * f["width_ft"] * f["depth_ft"] / 27.0


def rebar_bar_length_ft(m: dict) -> float:
    f = m["footing"]
    return f["length_ft"] - 2 * f["cover_in"] / 12.0


def rebar_bars_per_footing(m: dict) -> int:
    r = m["rebar"]
    return r["bars_each_way"] * r["directions"] * r["mats"]


def rebar_lf(m: dict) -> float:
    return m["footing"]["count"] * rebar_bars_per_footing(m) * rebar_bar_length_ft(m)


def rebar_lb(m: dict) -> float:
    return rebar_lf(m) * m["rebar"]["lb_per_ft"]


def grout_cf(m: dict) -> float:
    g, bp = m["grout"], m["saddle"]["base_plate"]
    return g["count"] * bp["length_in"] * bp["width_in"] * g["thickness_in"] / IN3_PER_CF


# --------------------------------------------------------------- (b) elevations
def casing_cl_ft(m: dict, support: dict) -> float:
    carrier_od_ft = m["reference"]["carrier"]["od_in"] / 12.0
    return support["pipe_invert_ft"] + carrier_od_ft / 2.0


def footing_top_ft(m: dict, support: dict) -> float:
    return casing_cl_ft(m, support) - plate_datums(m)["cl"] / 12.0


def footing_bottom_ft(m: dict, support: dict) -> float:
    return footing_top_ft(m, support) - m["footing"]["depth_ft"]


def freeboard_ft(m: dict) -> float:
    gw_high = max(m["validation"]["groundwater_elevation_ft"])
    return min(footing_bottom_ft(m, s) for s in m["supports"]) - gw_high


def local_origin(m: dict) -> tuple[float, float]:
    """(station_ft, elevation_ft) of the model's local (0, 0, 0)."""
    return (m["supports"][0]["station"],
            min(footing_bottom_ft(m, s) for s in m["supports"]))


def _span_direction(m: dict, sup: dict) -> int:
    mid = sum(s["station"] for s in m["supports"]) / len(m["supports"])
    return 1 if sup["station"] < mid else -1


# -------------------------------------------------------------- (c) steel stack
def plate_datums(m: dict) -> dict:
    """Z datums / Y gauges the steel stack shares, inches above top of footing.
    ONE source of truth for steel_components and the solids, so the weight and
    the geometry can never drift apart. The springline is DERIVED from the
    dimensioned web height (a dimensioned member beats an APPROX callout);
    the gate cross-checks it against the sheet's figure."""
    s = m["saddle"]
    gt = m["grout"]["thickness_in"]
    bpt = s["base_plate"]["thickness_in"]
    r_i = m["reference"]["casing"]["od_in"] / 2.0
    web_h = s["bearing_plate"]["height_in"]
    r_o = r_i + s["saddle_plate"]["thickness_in"]
    return {
        "z_base": gt,
        "z_bear": gt + bpt,
        "web_h": web_h,
        "z_web_top": gt + bpt + web_h,
        "cl": gt + bpt + web_h + r_o,
        "r_inner": r_i,
        "r_outer": r_o,
        "y_web_face": s["bearing_plate"]["thickness_in"] / 2.0,
        "y_endplate_inner": r_i,
        "y_base_edge": s["base_plate"]["length_in"] / 2.0,
    }


def end_plate_height_in(m: dict) -> float:
    d = plate_datums(m)
    return d["cl"] - d["z_bear"]


def stiffener_x_positions(m: dict) -> list[float]:
    n = m["saddle"]["stiffener_plate"]["locations"]
    off = assumption(m, "stiffener_x_offset_in")
    return [0.0] if n == 1 else [-off, off]


def shaped_stiffener(m: dict) -> ShapedStiffener:
    st = m["saddle"]["stiffener_plate"]
    d = plate_datums(m)
    w = assumption(m, "stiffener_half_width_in")
    return ShapedStiffener(
        "Stiffener plate", st["thickness_in"], d["r_outer"], d["cl"], w,
        d["z_bear"], d["z_bear"], w,
        pieces=len(stiffener_x_positions(m)) * st["pieces_per_location"],
        arc_segments=arc_segments_for(m), y_start_in=d["y_web_face"])


def steel_components(m: dict) -> list:
    """Every steel component of ONE support, in fabrication order, as
    (primitive, solids_dict) PAIRS built together in one pass.

    The pipe-supports-pilot source split this across steel_components() and _steel_geom(),
    correlated by matching name strings between two independently-walked
    functions — a silent-divergence trap once other families copy this file
    with different component counts. Building each primitive and its placed
    geometry side by side makes the weight and the solid inseparable.
    Solids dicts are inches relative to the top of footing (pipe-supports-pilot
    `_steel_geom`, verbatim geometry)."""
    s = m["saddle"]
    d = plate_datums(m)
    wrap = assumption(m, "saddle_wrap_deg")
    lug = s["lug_plate"]
    od = m["reference"]["casing"]["od_in"]
    segments = arc_segments_for(m)
    r_i, r_o, cl = d["r_inner"], d["r_outer"], d["cl"]
    leg_t = s["end_plate"]["thickness_in"]
    y_leg = r_i + leg_t / 2.0
    out = []

    # -- the two-piece collar: saddle plate wraps the bottom half
    # (start 180), the upper strap the top (start 0).
    for name, plate, start_deg in (("Saddle plate", s["saddle_plate"], 180.0),
                                   ("Upper strap", s["upper_strap"], 0.0)):
        band = ArcBand(name, plate["thickness_in"], plate["width_in"], od,
                       wrap, arc_segments=segments, start_deg=start_deg)
        out.append((band, {
            "kind": "arc_band", "units": "in", "cx": 0.0, "cz": cl,
            "r_inner": r_i, "r_outer": r_o, "wrap_deg": wrap,
            "start_deg": start_deg, "width": band.width_in,
            "segments": band.arc_segments}))

    # -- end-plate legs: seat on the base plate, top out on the springline.
    ep = Plate("End plate", leg_t, s["end_plate"]["width_in"],
               end_plate_height_in(m), s["end_plate"]["count_per_support"])
    out.append((ep, {"kind": "box", "units": "in", "boxes": [
        (0.0, sgn * y_leg, d["z_bear"] + ep.b_in / 2.0,
         ep.a_in, ep.thickness_in, ep.b_in)
        for sgn in (-1.0, 1.0)]}))

    # -- shaped stiffener: pieces flank the web, mirrored about it.
    stiff = shaped_stiffener(m)
    out.append((stiff, {
        "kind": "gusset", "units": "in", "cz": stiff.cl_in,
        "thickness": stiff.thickness_in,
        "placements": [
            (x, [(sy * u, v) for u, v in stiff.profile()])
            for x in stiffener_x_positions(m) for sy in (1.0, -1.0)]}))

    # -- horizontal bolt tabs, stacked about each springline.
    lp = Plate("Lug plate", lug["thickness_in"], lug["length_in"],
               lug["projection_in"], lug["count_per_support"],
               holes_each=s["collar_bolts"]["count"] // 2,
               hole_dia_in=s["holes"]["collar_bolt_dia_in"])
    gx = assumption(m, "collar_bolt_gauge_in")
    tab_cy = r_o + lp.b_in / 2.0
    hx = [(sx * gx, lug["bolt_edge_distance_in"] - lp.b_in / 2.0)
          for sx in (-1.0, 1.0)]
    out.append((lp, {
        "kind": "box", "units": "in", "hole_dia": lp.hole_dia_in,
        "segments": segments, "boxes": [
            (0.0, sgn * tab_cy, cl + up * lp.thickness_in / 2.0,
             lp.a_in, lp.b_in, lp.thickness_in,
             [(u, sgn * v) for u, v in hx])
            for sgn in (-1.0, 1.0) for up in (-1.0, 1.0)]}))

    # -- THE WEB: vertical at the centreline, standing on the base plate.
    web = Plate("Bearing plate", s["bearing_plate"]["thickness_in"],
                s["bearing_plate"]["length_in"], s["bearing_plate"]["height_in"],
                s["bearing_plate"]["count_per_support"])
    out.append((web, {"kind": "box", "units": "in", "boxes": [
        (0.0, 0.0, d["z_bear"] + d["web_h"] / 2.0,
         web.a_in, web.thickness_in, d["web_h"])]}))

    # -- base plate, pierced for the anchor bolts.
    base = Plate("Base plate", s["base_plate"]["thickness_in"],
                 s["base_plate"]["length_in"], s["base_plate"]["width_in"],
                 s["base_plate"]["count_per_support"],
                 holes_each=s["anchor_bolts"]["count"],
                 hole_dia_in=s["holes"]["anchor_bolt_dia_in"])
    out.append((base, {
        "kind": "box", "units": "in", "hole_dia": base.hole_dia_in,
        "segments": segments, "boxes": [
            (0.0, 0.0, d["z_base"] + base.thickness_in / 2.0,
             base.b_in, base.a_in, base.thickness_in,
             anchor_bolt_holes(m))]}))
    return out


def anchor_bolts(m: dict) -> Bolt:
    ab = m["saddle"]["anchor_bolts"]
    return Bolt("Anchor bolt", ab["diameter_in"], ab["length_in"], ab["count"],
                nuts=2 if ab.get("leveling_nuts") else 1)


def collar_bolts(m: dict) -> Bolt:
    cb = m["saddle"]["collar_bolts"]
    return Bolt("Collar strap bolt", assumption(m, "collar_bolt_diameter_in"),
                assumption(m, "collar_bolt_length_in"), cb["count"], nuts=2)


def bolt_gauges(m: dict) -> dict:
    s = m["saddle"]
    d = plate_datums(m)
    return {
        "anchor_x": s["saddle_plate"]["width_in"] / 4.0,
        "anchor_y": s["base_plate"]["length_in"] / 2.0 - ANCHOR_BOLT_END_INSET_IN,
        "collar_x": assumption(m, "collar_bolt_gauge_in"),
        "collar_y": d["r_outer"] + s["lug_plate"]["bolt_edge_distance_in"],
    }


def anchor_bolt_holes(m: dict) -> list[tuple[float, float]]:
    g = bolt_gauges(m)
    return [(sx * g["anchor_x"], sy * g["anchor_y"])
            for sy in (-1.0, 1.0) for sx in (-1.0, 1.0)]


def steel_plate_lb(m: dict) -> float:
    """Fabricated PLATE weight for ALL supports, EXCLUDING bolts (bolts are
    paid by the each; plate weight is what reconciles the steel item)."""
    return sum(c.weight_lb for c, _g in steel_components(m)) * m["saddle"]["count"]


# ---------------------------------------------------------- (d) element schedule
def build(params: dict, ctx) -> StructureModel:
    missing = [k for k in REQUIRED if params.get(k) is None]
    if missing:
        raise ValueError(f"pipe-supports params missing {missing}")
    m = params
    f, r, g = m["footing"], m["rebar"], m["grout"]
    segments = arc_segments_for(m)
    x0_ft, z0_ft = local_origin(m)
    model = StructureModel("pipe-supports", ctx)

    for sup in m["supports"]:
        sid = sup["id"]
        top = footing_top_ft(m, sup)
        x_ft = sup["station"] - x0_ft

        def z(el_ft: float) -> float:
            return el_ft - z0_ft

        # -- footing
        L, W, D = f["length_ft"], f["width_ft"], f["depth_ft"]
        model.add(Element(
            f"{sid} pipe support footing", "IfcFooting",
            geometry={"kind": "box", "units": "in", "boxes": [
                (0.0, 0.0, D * 6.0, L * 12.0, W * 12.0, D * 12.0)]},
            quantities={"length_ft": L, "width_ft": W, "height_ft": D,
                        "volume_cf": L * W * D},
            x_ft=x_ft, z_ft=z(top - D), layer="S-CONC-OTLN"))

        # -- rebar: one product per mat/direction (product count is contractual)
        bar_len = rebar_bar_length_ft(m)
        bar_r = equal_area_polygon_radius(r["bar_size"] / 16.0, segments)
        d_bar = 2 * (r["bar_size"] / 16.0)
        depth_in = D * 12.0
        span_in = (r["bars_each_way"] - 1) * r["spacing_in"]
        z_of = {("bottom", "EW"): f["cover_in"] + d_bar / 2.0,
                ("bottom", "NS"): f["cover_in"] + d_bar * 1.5,
                ("top", "EW"): depth_in - f["cover_in"] - d_bar * 1.5,
                ("top", "NS"): depth_in - f["cover_in"] - d_bar / 2.0}
        for mat in ("bottom", "top"):
            for direction in ("EW", "NS"):
                n = r["bars_each_way"]
                axis = "x" if direction == "EW" else "y"
                cz = z_of[(mat, direction)]
                offs = [-span_in / 2.0 + i * r["spacing_in"] for i in range(n)]
                bars = [((0.0, o, cz) if axis == "x" else (o, 0.0, cz))
                        for o in offs]
                model.add(Element(
                    f"{sid} footing rebar #{r['bar_size']} {mat} {direction}",
                    "IfcReinforcingBar",
                    geometry={"kind": "rod", "units": "in", "axis": axis,
                              "radius": bar_r, "length": bar_len * 12.0,
                              "segments": segments, "centres": bars},
                    quantities={"count": n, "length_ft": bar_len * n,
                                "weight_lb": bar_len * n * r["lb_per_ft"]},
                    x_ft=x_ft, z_ft=z(top - D), layer="S-REBAR"))

        # -- grout pad
        bp = m["saddle"]["base_plate"]
        model.add(Element(
            f"{sid} grout pad", "IfcBuildingElementProxy",
            geometry={"kind": "box", "units": "in", "boxes": [
                (0.0, 0.0, g["thickness_in"] / 2.0,
                 bp["width_in"], bp["length_in"], g["thickness_in"])]},
            quantities={"length_ft": bp["length_in"] / 12.0,
                        "width_ft": bp["width_in"] / 12.0,
                        "height_ft": g["thickness_in"] / 12.0,
                        "volume_cf": (bp["length_in"] * bp["width_in"]
                                      * g["thickness_in"] / IN3_PER_CF)},
            x_ft=x_ft, z_ft=z(top), layer="S-CONC-OTLN"))

        # -- steel, one product per component. Each Element's geometry lists
        # the primitive and its placed-solids dict — by convention primitive
        # first, though order is cosmetic: every consumer duck-types each
        # entry (the gate reads exact/faceted attributes wherever they
        # appear; the emitters draw only dicts and body_solids() carriers,
        # and Plate/ArcBand/ShapedStiffener have no body_solids(), so only
        # the dict emits geometry — no double emission).
        for c, geom in steel_components(m):
            model.add(Element(
                f"{sid} {c.name.lower()}", "IfcPlate",
                geometry=[c, geom],
                quantities={"count": c.count,
                            "volume_cf": c.volume_in3 / IN3_PER_CF,
                            "surface_sf": c.surface_in2 / 144.0,
                            "weight_lb": c.weight_lb},
                x_ft=x_ft, z_ft=z(top), layer="S-STEEL"))

        # -- anchor bolts: ONE product, four solids
        ab = anchor_bolts(m)
        gg = bolt_gauges(m)
        z_bolt_top = (D * 12.0 + g["thickness_in"] + bp["thickness_in"]
                      + assumption(m, "anchor_bolt_projection_above_plate_in"))
        model.add(Element(
            f"{sid} anchor bolt", "IfcMechanicalFastener",
            geometry={"kind": "rod", "units": "in", "axis": "z",
                      "radius": equal_area_polygon_radius(ab.diameter_in / 2.0,
                                                          segments),
                      "length": ab.length_in, "segments": segments,
                      "centres": [(sx * gg["anchor_x"], sy * gg["anchor_y"],
                                   z_bolt_top - ab.length_in / 2.0)
                                  for sy in (-1.0, 1.0) for sx in (-1.0, 1.0)]},
            quantities={"count": ab.count, "length_ft": ab.length_in / 12.0,
                        "surface_sf": ab.surface_in2 / 144.0,
                        "weight_lb": ab.weight_lb},
            x_ft=x_ft, z_ft=z(top - D), layer="S-BOLT"))

        # -- collar strap bolts
        cb = collar_bolts(m)
        model.add(Element(
            f"{sid} collar strap bolt", "IfcMechanicalFastener",
            geometry={"kind": "rod", "units": "in", "axis": "z",
                      "radius": equal_area_polygon_radius(cb.diameter_in / 2.0,
                                                          segments),
                      "length": cb.length_in, "segments": segments,
                      "centres": [(sx * gg["collar_x"], sy * gg["collar_y"],
                                   plate_datums(m)["cl"])
                                  for sy in (-1.0, 1.0) for sx in (-1.0, 1.0)]},
            quantities={"count": cb.count, "length_ft": cb.length_in / 12.0,
                        "surface_sf": cb.surface_in2 / 144.0,
                        "weight_lb": cb.weight_lb},
            x_ft=x_ft, z_ft=z(top), layer="S-BOLT"))

        # -- reference geometry: named so NO pay rule matches; [] stays []
        ref = m["reference"]
        half_in = m["span"]["clear_span_ft"] / 2 * 12.0
        run_dir = _span_direction(m, sup)
        x0_in = 0.0 if run_dir > 0 else -half_in
        model.add(Element(
            f"{sid} casing pipe (REFERENCE)", "IfcPipeSegment",
            geometry={"kind": "tube", "units": "in", "x0": x0_in,
                      "length": half_in, "cz": ref["casing"]["od_in"] / 2.0,
                      "r_outer": ref["casing"]["od_in"] / 2.0,
                      "wall": ref["casing"]["wall_in"], "axis": "x"},
            quantities={"length_ft": m["span"]["clear_span_ft"] / 2,
                        "width_ft": ref["casing"]["od_in"] / 12.0},
            x_ft=x_ft,
            z_ft=z(casing_cl_ft(m, sup) - ref["casing"]["od_in"] / 24.0),
            layer="S-PIPE-REF"))
        assembly = [e.name for e in model.elements
                    if e.name.startswith(sid) and e.layer in ("S-STEEL", "S-BOLT")]
        model.assemblies[f"{sid} saddle assembly"] = assembly

    model.stated_quantities.extend(_stated(m))
    model.checks.extend(gate_checks(m))
    model.dxf_annotations.append(_annotate_section(m))
    return model


def _stated(m: dict):
    """(label, got, want, tol) rows for INDEPENDENTLY stated quantities."""
    out = []
    for q in m.get("quantities", []):
        if q["unit"] == "CY":
            out.append(("footing CY vs stated takeoff", footing_cy(m),
                        q["qty"], 5e-4))
        elif q["unit"] == "LBS" and "rebar" in q["item"].lower():
            out.append(("rebar LBS vs stated takeoff", rebar_lb(m),
                        q["qty"], 0.01))
        elif q["unit"] == "LBS":
            out.append(("plate steel LBS vs stated takeoff", steel_plate_lb(m),
                        q["qty"], 0.01))
        elif q["unit"] == "CF":
            out.append(("grout CF vs stated takeoff", grout_cf(m),
                        q["qty"], 5e-4))
    return out


# ------------------------------------------------------------- (e) gate checks
def gate_checks(m: dict) -> list:
    """The pipe-supports-pilot validate() body, re-registered as gate checks (each closure
    returns a failure list; the gate runs them all and reports together).

    The saddle-arc and shaped-stiffener faceting checks from pipe-supports-pilot's
    validate() are NOT re-implemented here: each steel Element's geometry
    lists the ArcBand/ShapedStiffener primitive alongside its solids dict
    (see build()), so the kernel's check_arc_faceting gate built-in already
    holds both within FACET_TOLERANCE — one generic check covers every
    curved steel member instead of two bespoke ones."""
    def geometry_and_geotech(_model):
        fail = []
        f, s = m["footing"], m["saddle"]
        if f["depth_ft"] * 12 < 24.0:
            fail.append(f"footing depth {f['depth_ft'] * 12} in < 24 in minimum")
        if min(f["length_ft"], f["width_ft"]) * 12 < 18.0:
            fail.append("footing plan dimension < 18 in minimum")
        if f.get("max_wcm", 0.50) > 0.50:
            fail.append(f"w/cm {f['max_wcm']} exceeds the 0.50 limit")
        r = m["rebar"]
        spacing_span = (r["bars_each_way"] - 1) * r["spacing_in"]
        available = f["length_ft"] * 12 - 2 * f["cover_in"]
        if spacing_span > available:
            fail.append(f"rebar spacing span {spacing_span} in exceeds the "
                        f"{available} in available inside cover")
        ab = s["anchor_bolts"]
        reach = (ab["length_in"] - m["grout"]["thickness_in"]
                 - s["base_plate"]["thickness_in"]
                 - assumption(m, "anchor_bolt_projection_above_plate_in"))
        needed = f["cover_in"] + ab["min_embed_below_top_mat_in"]
        if reach < needed:
            fail.append(f"anchor bolt reach {reach} in does not achieve "
                        f"{ab['min_embed_below_top_mat_in']} in below the top "
                        f"mat (needs {needed} in)")
        return fail

    def holes_inside_plates(_model):
        fail = []
        s = m["saddle"]
        gg, dat = bolt_gauges(m), plate_datums(m)
        for label, hx, hy, half_x, half_y, dia in (
            ("base plate", gg["anchor_x"], gg["anchor_y"],
             s["base_plate"]["width_in"] / 2.0, s["base_plate"]["length_in"] / 2.0,
             s["holes"]["anchor_bolt_dia_in"]),
            ("collar tab", gg["collar_x"],
             gg["collar_y"] - (dat["r_outer"] + s["lug_plate"]["projection_in"] / 2.0),
             s["lug_plate"]["length_in"] / 2.0,
             s["lug_plate"]["projection_in"] / 2.0,
             s["holes"]["collar_bolt_dia_in"]),
        ):
            if abs(hx) + dia / 2.0 > half_x or abs(hy) + dia / 2.0 > half_y:
                fail.append(f"{label}: a {dia} in hole at ({hx}, {hy}) breaks "
                            f"the plate edge (half-extents {half_x} x {half_y})")
        return fail

    def web_and_springline(_model):
        fail = []
        s = m["saddle"]
        dat = plate_datums(m)
        bp = s["bearing_plate"]
        if bp["count_per_support"] != 1:
            fail.append("bearing plate count != 1; the section draws a single "
                        "web at the centreline")
        if bp["length_in"] != s["saddle_plate"]["width_in"]:
            fail.append(f"web {bp['length_in']} in along the pipe does not "
                        f"match the {s['saddle_plate']['width_in']} in collar width")
        if bp["thickness_in"] <= s["stiffener_plate"]["thickness_in"]:
            fail.append("web is not thicker than its stiffeners")
        approx, tol = s["cl_approx_in"], s["cl_approx_tolerance_in"]
        if abs(dat["cl"] - approx) > tol:
            fail.append(f"derived springline {dat['cl']:.4f} in is more than "
                        f"{tol} in from the sheet's APPROX {approx} in")
        if abs(dat["z_web_top"] - (dat["cl"] - dat["r_outer"])) > 1e-9:
            fail.append("web top does not meet the saddle crown")
        if end_plate_height_in(m) <= 0:
            fail.append("end plate height is not positive")
        # -- the end-plate legs seat on the base plate, so they reach the
        # springline (pipe-supports-pilot validate(): interrogates the PLACEMENT of the
        # End plate's solids boxes, not the arithmetic — z_bear +
        # end_plate_height_in is cl BY CONSTRUCTION, so re-deriving it would
        # be a tautology that can never fail. What can regress is the paired
        # geometry putting the legs somewhere other than under the
        # springline if a future edit decouples the two).
        leg_geom = next((g for c, g in steel_components(m)
                         if c.name == "End plate"), None)
        if leg_geom is not None:
            for box in leg_geom["boxes"]:
                _cx, _cy, cz, _dx, _dy, dz = box[:6]
                bottom, top = cz - dz / 2.0, cz + dz / 2.0
                if abs(bottom - dat["z_bear"]) > 1e-9:
                    fail.append(f"end plate starts at {bottom} in, not on "
                                f"the base plate at {dat['z_bear']} in")
                if abs(top - dat["cl"]) > 1e-9:
                    fail.append(f"end plate tops at {top} in, not on the "
                                f"springline {dat['cl']} in where DETAIL A's "
                                f"tabs are")
        return fail

    def stiffeners_and_bolts(_model):
        fail = []
        s = m["saddle"]
        gg = bolt_gauges(m)
        half_bolt = s["anchor_bolts"]["diameter_in"] / 2.0
        half_st = s["stiffener_plate"]["thickness_in"] / 2.0
        if s["stiffener_plate"]["locations"] not in (1, 2):
            fail.append("stiffener locations must be 1 or 2")
        for off in stiffener_x_positions(m):
            clearance = abs(abs(off) - abs(gg["anchor_x"]))
            if clearance < half_bolt + half_st:
                fail.append(f"stiffener at x {off} in fouls an anchor bolt "
                            f"(clearance {clearance:.4f} in)")
            if abs(off) + half_st > s["bearing_plate"]["length_in"] / 2.0:
                fail.append(f"stiffener at x {off} in runs past the web")
        total_wrap = assumption(m, "saddle_wrap_deg") * 2
        if abs(total_wrap - 360.0) > 1e-9:
            fail.append(f"the two collar halves wrap {total_wrap} deg; two "
                        f"halves at the springline must close 360")
        if s["upper_strap"]["thickness_in"] != s["saddle_plate"]["thickness_in"]:
            fail.append("upper strap and saddle plate thickness differ")
        cb_need = 2 * s["lug_plate"]["thickness_in"] + 2 * HEX_NUT_DEPTH_IN
        if assumption(m, "collar_bolt_length_in") < cb_need:
            fail.append(f"collar bolt cannot cross two tabs and carry two "
                        f"nuts (needs {cb_need:.3f} in)")
        return fail

    def stiffener_fits_the_void(_model):
        fail = []
        d = plate_datums(m)
        w = assumption(m, "stiffener_half_width_in")
        if w <= 0:
            return [f"stiffener half-width {w} in is not positive"]
        if w > d["y_endplate_inner"]:
            fail.append(f"stiffener half-width {w} in runs past the end "
                        f"plate's inner face at {d['y_endplate_inner']} in")
        if w > d["r_outer"]:
            fail.append(f"stiffener half-width {w} in exceeds the saddle "
                        f"outer radius {d['r_outer']} in")
        if not fail:
            stiff = shaped_stiffener(m)
            if stiff.area_in2 <= 0:
                fail.append("shaped stiffener area is not positive; the cope "
                            "has eaten the plate")
        return fail

    def freeboard(_model):
        fb = freeboard_ft(m)
        want = m["validation"]["min_freeboard_ft"]
        if fb < want:
            return [f"groundwater freeboard {fb:.2f} ft is below the {want} ft "
                    f"minimum - the dewatering exclusion is no longer supportable"]
        return []

    def assumptions_have_reasons(_model):
        return [f"assumption {a['key']} has no documented reason"
                for a in m["assumptions"] if not (a.get("reason") or "").strip()]

    return [geometry_and_geotech, holes_inside_plates, web_and_springline,
            stiffeners_and_bolts, stiffener_fits_the_void, freeboard,
            assumptions_have_reasons]


# --------------------------------------------------------- (f) DXF annotation
def _annotate_section(m: dict):
    """The saddle section view + plan labels (pipe-supports-pilot `_write_dxf` port).
    Drawn to the right of the plan footprints emit_dxf lays down."""
    def annotate(msp, model):
        from bimforge.author.emit_dxf import txt
        f, s = m["footing"], m["saddle"]
        L = f["length_ft"]
        sx = L + 3.0
        cl_z = plate_datums(m)["cl"] / 12.0
        casing_r = m["reference"]["casing"]["od_in"] / 24.0
        msp.add_circle((sx, cl_z), casing_r, dxfattribs={"layer": "S-PIPE-REF"})
        # footing + grout + base plate in section
        gl = s["base_plate"]["length_in"] / 12.0
        gt = m["grout"]["thickness_in"] / 12.0
        bpt = s["base_plate"]["thickness_in"] / 12.0
        msp.add_lwpolyline(
            [(sx - L / 2, 0), (sx + L / 2, 0),
             (sx + L / 2, -f["depth_ft"]), (sx - L / 2, -f["depth_ft"])],
            close=True, dxfattribs={"layer": "S-CONC-OTLN"})
        msp.add_lwpolyline([(sx - gl / 2, 0), (sx + gl / 2, 0),
                            (sx + gl / 2, gt), (sx - gl / 2, gt)],
                           close=True, dxfattribs={"layer": "S-CONC-OTLN"})
        msp.add_lwpolyline([(sx - gl / 2, gt), (sx + gl / 2, gt),
                            (sx + gl / 2, gt + bpt), (sx - gl / 2, gt + bpt)],
                           close=True, dxfattribs={"layer": "S-STEEL"})
        # web in section
        web_t = s["bearing_plate"]["thickness_in"] / 24.0
        web_h = s["bearing_plate"]["height_in"] / 12.0
        msp.add_lwpolyline(
            [(sx - web_t, gt + bpt), (sx + web_t, gt + bpt),
             (sx + web_t, gt + bpt + web_h), (sx - web_t, gt + bpt + web_h)],
            close=True, dxfattribs={"layer": "S-STEEL"})
        # the two-arc collar
        wrap = assumption(m, "saddle_wrap_deg")
        band_r = casing_r + s["saddle_plate"]["thickness_in"] / 24.0
        msp.add_arc((sx, cl_z), band_r, 180 + (180 - wrap) / 2,
                    360 - (180 - wrap) / 2, dxfattribs={"layer": "S-STEEL"})
        msp.add_arc((sx, cl_z), band_r, (180 - wrap) / 2,
                    180 - (180 - wrap) / 2, dxfattribs={"layer": "S-STEEL"})
        # stiffener profile, both pieces
        stiff = shaped_stiffener(m)
        for sy in (1.0, -1.0):
            msp.add_lwpolyline(
                [(sx + sy * u / 12.0, cl_z + v / 12.0)
                 for u, v in stiff.profile()],
                close=True, dxfattribs={"layer": "S-STEEL"})
        txt(msp, "PIPE SUPPORT SADDLE - SECTION",
            (sx - L / 2, -f["depth_ft"] - 0.6), h=0.15)
        r = m["rebar"]
        txt(msp,
            f"#{r['bar_size']} @ {r['spacing_in']:.0f}\" OC, "
            f"({r['bars_each_way']}) EACH WAY, TOP & BOTTOM, "
            f"{f['cover_in']:.0f}\" CLR",
            (-f["length_ft"] / 2, -f["width_ft"] / 2 - 0.9), h=0.12)
    return annotate
