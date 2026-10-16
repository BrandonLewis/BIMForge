"""bridge-standard -- a CIP box-girder superstructure swept along an
alignment (compound radii, vertical profile, superelevation, camber) with
seat abutments and multi-column bents placed on skewed bearing lines.

Concrete only this cycle: bridge rebar is schedule-driven and gets its own
spec (spec 8). Spec: docs/superpowers/specs/2026-08-18-r13-sweep-engine-
bridge-design.md section 4.
"""
from __future__ import annotations

import math

REQUIRED = ("alignment", "section", "supports")


def bearing_line(alignment, station: float, skew_deg: float) -> tuple:
    """((n, e), (dn, de)) of a support's bearing line: the plan normal at
    `station` rotated by `skew_deg` toward the alignment.

    Skew is measured FROM the normal (the standard-plan convention), so 0
    deg is square to the alignment and the deck end plane at that station
    shears by tan(skew) -- exactly the engine's `end_skew` argument.
    `(dn, de)` is a unit vector; at zero skew it is `Alignment.left_normal`.
    """
    n, e, az = alignment.point_az(station)
    a = math.radians(az - 90.0 + skew_deg)
    return (n, e), (math.cos(a), math.sin(a))


def spans(supports: list) -> list:
    """[(support_a, support_b), ...] for consecutive station intervals."""
    if len(supports) < 2:
        raise ValueError("a bridge needs at least two supports")
    ss = [s["station"] for s in supports]
    if ss != sorted(ss) or len(set(ss)) != len(ss):
        raise ValueError("support stations must be strictly ascending")
    return list(zip(supports, supports[1:]))


def deck_span(name: str, section, alignment, s0: float, s1: float,
              skew0: float, skew1: float, profile=None, roll=None,
              camber=None, frame: str = "plumb", origin=None):
    """One span's superstructure: the box section swept station-to-station
    with the supports' skews shearing the two end planes.

    The engine's closed form pays the run A*ds plus an end-plane term
    +/- A*x_bar'*tan(skew) at each end, so PARALLEL skews cancel exactly
    (a square-volume deck on a slanted footprint) while opposed ones do
    not. Returns the `SweptSection` itself; the Element wrapper that
    declares length_ft + volume_cf only is `build`'s job.
    """
    from bimforge.author.sweep import SweptSection
    return SweptSection(
        name, section.outline, alignment, s0, s1, profile=profile,
        roll=roll, camber=camber, voids=section.voids, frame=frame,
        end_skew=(skew0, skew1), ifc="IfcSlab", layer="S-CONC-OTLN",
        origin=origin)


def _roll_phi(roll, station: float) -> float:
    from bimforge.author.primitives import profile_at
    return math.atan(profile_at(roll, station)) if roll else 0.0


def soffit_elev(profile, roll, camber, station: float, offset_x: float,
                depth: float) -> float:
    """Elevation of the deck soffit at a plan offset from the pivot, through
    the SAME mapping the sweep uses (no parallel formula: the bridge-pilot lesson).

    The sweep places a section point (x, z) at `elev + x*sin(phi) +
    z*cos(phi)`; the soffit is z = -depth, so the soffit under offset x sits
    at `elev + x*sin(phi) - depth*cos(phi)`.
    """
    from bimforge.author.primitives import profile_at
    elev = profile.elev(station) if profile is not None else 0.0
    if camber:
        elev += profile_at(camber, station)
    phi = _roll_phi(roll, station)
    return elev + offset_x * math.sin(phi) - depth * math.cos(phi)


def _plan_rect(x0: float, y0: float, dx: float, dy: float,
               length: float, width: float) -> list:
    """Closed MODEL-frame rectangle centred at (x0, y0), `length` along the
    unit bearing direction (dx, dy) and `width` across it.

    Frame-agnostic on purpose: callers convert survey (n, e) through
    `to_model` / `to_model_dir` BEFORE calling, so this never has to know
    which frame its inputs are in (issue #156)."""
    ux, uy = dx, dy
    vx, vy = -dy, dx
    hl, hw = length / 2.0, width / 2.0
    return [(x0 + ux * hl + vx * hw, y0 + uy * hl + vy * hw),
            (x0 + ux * hl - vx * hw, y0 + uy * hl - vy * hw),
            (x0 - ux * hl - vx * hw, y0 - uy * hl - vy * hw),
            (x0 - ux * hl + vx * hw, y0 - uy * hl + vy * hw)]


def _box(name: str, x0, y0, dx, dy, length, width, z_bot, z_top, ifc,
         quote=None):
    """A MODEL-frame rectangular concrete member + its Element quantities.

    Rectangular members declare the full L/W/H set on purpose: the gate's
    `count x L x W x H == GrossVolume` built-in then checks them, which it
    cannot do for the swept deck.

    `quote` is the (z_bot, z_top) pair to NAME if the ordering check fails —
    the ABSOLUTE elevations the spec was written in, once z has been
    localized for geometry. Telling an estimator their base is at 5 ft when
    they typed `base_el: 99.0` sends them hunting the wrong thing.
    """
    from bimforge.author.model import Element
    from bimforge.author.primitives import Prism
    if z_top <= z_bot:
        qb, qt = quote if quote is not None else (z_bot, z_top)
        raise ValueError(
            f"{name}: top {qt:g} is at or below the base {qb:g} - "
            f"check base_el against the profile")
    p = Prism(name, _plan_rect(x0, y0, dx, dy, length, width), z_bot, z_top,
              dims_ft=(length, width), ifc=ifc, layer="S-CONC-OTLN")
    return Element.from_geometry(
        p.name, p, ifc_class=ifc, layer="S-CONC-OTLN",
        quantities={"length_ft": length, "width_ft": width,
                    "height_ft": z_top - z_bot, "volume_cf": p.volume_cf})


def bent_elements(tag: str, sup: dict, section, alignment, profile, roll,
                  camber, origin=None) -> list:
    """Bent cap on the skewed bearing line plus its columns, both keyed off
    the deck soffit over the pivot."""
    from bimforge.author.model import Element
    from bimforge.author.primitives import ARC_SEGMENTS, Prism, circle_poly
    from bimforge.author.sweep import to_model, to_model_dir, to_model_elev
    st, skew = float(sup["station"]), float(sup.get("skew_deg", 0.0))
    cols, cap = sup["columns"], sup["cap"]
    (n0, e0), (dn, de) = bearing_line(alignment, st, skew)
    # survey -> model frame: the point translates, the direction only swaps
    x0, y0, _z = to_model(origin, n0, e0)
    dx, dy = to_model_dir(dn, de)
    # Elevations stay ABSOLUTE while they are being validated, so the error
    # quotes the same datum the spec's base_el was written in; only the
    # values that become geometry are localized.
    soffit_abs = soffit_elev(profile, roll, camber, st, 0.0, section.depth)
    cap_len = section.soffit_width + 2.0 * float(cap.get("overhang", 1.0))
    soffit = to_model_elev(origin, soffit_abs)
    out = [_box(f"{tag} bent cap", x0, y0, dx, dy, cap_len,
                float(cap["width"]), soffit - float(cap["depth"]), soffit,
                "IfcBeam",
                quote=(soffit_abs - float(cap["depth"]), soffit_abs))]
    n_col, dia = int(cols["count"]), float(cols["dia"])
    base_abs = float(cols["base_el"])
    top_abs = soffit_abs - float(cap["depth"])
    if top_abs <= base_abs:
        raise ValueError(
            f"{tag}: column top {top_abs:g} is at or below the base "
            f"{base_abs:g} - check base_el against the profile")
    base, top = to_model_elev(origin, base_abs), soffit - float(cap["depth"])
    spacing = cap_len / (n_col + 1)
    for i in range(n_col):
        t = -cap_len / 2.0 + spacing * (i + 1)
        cx, cy = x0 + dx * t, y0 + dy * t
        # circle_poly sizes the equal-area polygon itself: pass the TRUE
        # radius or the correction lands twice
        ring = circle_poly(dia / 2.0, ARC_SEGMENTS, cx=cx, cy=cy)
        col = Prism(f"{tag} column {i + 1}", ring, base, top,
                    ifc="IfcColumn", layer="S-CONC-OTLN")
        out.append(Element.from_geometry(
            col.name, col, ifc_class="IfcColumn", layer="S-CONC-OTLN",
            quantities={"height_ft": top - base,
                        "volume_cf": col.volume_cf}))
    return out


def abutment_elements(tag: str, sup: dict, section, alignment, profile, roll,
                      camber, origin=None) -> list:
    """Seat-type abutment: stem wall base -> seat, backwall seat -> soffit,
    both run along the skewed bearing line."""
    from bimforge.author.sweep import to_model, to_model_dir, to_model_elev
    st, skew = float(sup["station"]), float(sup.get("skew_deg", 0.0))
    stem, seat, back = sup["stem"], sup["seat"], sup["backwall"]
    (n0, e0), (dn, de) = bearing_line(alignment, st, skew)
    # survey -> model frame: the point translates, the direction only swaps
    x0, y0, _z = to_model(origin, n0, e0)
    dx, dy = to_model_dir(dn, de)
    # Elevations are kept in BOTH frames: the absolute pair is what any
    # error quotes (the datum the spec's base_el was written in), the
    # localized pair is what becomes geometry. Localization is a uniform
    # shift, so it cannot change which of the two is higher.
    soffit_abs = soffit_elev(profile, roll, camber, st, 0.0, section.depth)
    seat_abs = soffit_abs - float(seat["bearing_depth"])
    base_abs = float(stem["base_el"])
    soffit = to_model_elev(origin, soffit_abs)
    seat_el = to_model_elev(origin, seat_abs)
    base = to_model_elev(origin, base_abs)
    length = section.soffit_width + 2.0 * float(seat.get("overhang", 1.0))
    return [
        _box(f"{tag} abutment stem", x0, y0, dx, dy, length,
             float(stem["thickness"]), base, seat_el, "IfcWall",
             quote=(base_abs, seat_abs)),
        _box(f"{tag} abutment backwall", x0, y0, dx, dy, length,
             float(back["thickness"]), seat_el, soffit, "IfcWall",
             quote=(seat_abs, soffit_abs)),
    ]


def diaphragm_elements(tag: str, sup: dict, section, alignment, profile,
                       roll, camber, span_list, origin=None) -> list:
    """Solid diaphragms filling the cells at a support.

    Each is a SHORT SWEPT SECTION whose profile is the cell ring -- NOT a
    local-frame SectionPrism. The cells live in section coordinates (x from
    the directrix, z down from the deck), so only the engine's own mapping
    puts them in the right world place under profile + roll + camber; a
    local extrusion would sit flat and unrotated (the Task-4 frame lesson).
    The support's skew carries onto BOTH ends, so the diaphragm is cut on
    the skew like the deck it sits in, and the parallel end planes make its
    volume exactly cell area x thickness.

    Cells were already deducted from the deck sweep, so these add precisely
    their own volume -- no double count.
    """
    from bimforge.author.model import Element
    from bimforge.author.sweep import SweptSection
    st, skew = float(sup["station"]), float(sup.get("skew_deg", 0.0))
    th = float(sup["diaphragm"]["thickness"])
    # keep the block inside the deck: at the first/last support it sits
    # wholly inboard rather than half-overhanging the end of the structure
    lo = min(a["station"] for a, _b in span_list)
    hi = max(b["station"] for _a, b in span_list)
    if th > hi - lo:
        raise ValueError(
            f"{tag}: diaphragm thickness {th:g} ft exceeds the whole "
            f"{hi - lo:g} ft structure")
    s0, s1 = st - th / 2.0, st + th / 2.0
    if s0 < lo:
        s0, s1 = lo, lo + th
    elif s1 > hi:
        s0, s1 = hi - th, hi
    out = []
    for k, cell in enumerate(section.voids, start=1):
        sw = SweptSection(f"{tag} diaphragm cell {k}", cell, alignment,
                          s0, s1, profile=profile, roll=roll, camber=camber,
                          end_skew=(skew, skew), ifc="IfcPlate",
                          layer="S-CONC-OTLN", origin=origin)
        out.append(Element.from_geometry(
            sw.name, sw, ifc_class="IfcPlate", layer="S-CONC-OTLN",
            quantities={"length_ft": sw.length_ft,
                        "volume_cf": sw.volume_cf}))
    return out


def build(params: dict, ctx) -> "StructureModel":
    """Assemble the whole bridge: one swept span per bearing interval, then
    each support's substructure and its optional diaphragms."""
    from bimforge.author.alignment import Alignment, Profile
    from bimforge.author.box_girder_section import BoxGirderSection
    from bimforge.author.model import Element, StructureModel
    missing = [k for k in REQUIRED if params.get(k) is None]
    if missing:
        raise ValueError(f"bridge-standard params missing {missing}")
    al_p = params["alignment"]
    al = Alignment(al_p["pob"], al_p["run"], name=al_p.get("name", "P"))
    prof = (Profile(params["profile"]["curves"])
            if params.get("profile") else None)
    roll = [tuple(r) for r in params["superelevation"]] \
        if params.get("superelevation") else None
    camber = [tuple(c) for c in params["camber"]] \
        if params.get("camber") else None
    sp = params["section"]
    sec = BoxGirderSection(
        deck_width=sp["deck_width"], depth=sp["depth"],
        overhang=sp["overhang"], web_count=sp["webs"]["count"],
        web_thickness=sp["webs"]["thickness"], top_slab=sp["top_slab"],
        bot_slab=sp["bot_slab"])
    frame = params.get("frame", "plumb")
    span_list = spans(params["supports"])
    model = StructureModel("bridge-standard", ctx)

    for i, (a, b) in enumerate(span_list, start=1):
        sw = deck_span(f"span {i} superstructure", sec, al,
                       a["station"], b["station"],
                       a.get("skew_deg", 0.0), b.get("skew_deg", 0.0),
                       profile=prof, roll=roll, camber=camber, frame=frame,
                       origin=ctx)
        model.add(Element.from_geometry(
            sw.name, sw, ifc_class="IfcSlab", layer="S-CONC-OTLN",
            description=sec.describe(),
            quantities={"length_ft": sw.length_ft,
                        "volume_cf": sw.volume_cf}))

    for j, sup in enumerate(params["supports"], start=1):
        kind = sup.get("type")
        tag = f"{'A' if kind == 'abutment' else 'B'}{j}"
        if kind == "bent":
            els = bent_elements(tag, sup, sec, al, prof, roll, camber,
                                origin=ctx)
        elif kind == "abutment":
            els = abutment_elements(tag, sup, sec, al, prof, roll, camber,
                                    origin=ctx)
        else:
            raise ValueError(
                f"{tag}: unknown support type {kind!r} (expected 'bent' or "
                f"'abutment')")
        for el in els:
            model.add(el)
        if sup.get("diaphragm"):
            for el in diaphragm_elements(tag, sup, sec, al, prof, roll,
                                         camber, span_list, origin=ctx):
                model.add(el)
    return model
