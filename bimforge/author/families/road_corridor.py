"""road-corridor -- a road from an alignment, a profile, a typical section
and the ground (roadmap P.6): pavement courses lofted along the alignment,
cut and fill out to daylight, and the mass haul, in IFC4.3's road terms
(IfcRoad > ROADSEGMENT > CARRIAGEWAY / SHOULDER / CENTRALRESERVE, IfcCourse
typed by IfcCourseType, IfcEarthworksCut and IfcEarthworksFill).

One element per course, component and station band (both sides' lofts),
and one cut and one fill per band. A structure gap ends a run: each run is
its own ROADSEGMENT, and its first and last sections close the courses with
their caps and the earthwork with vertical columns, so nothing lies inside
the gap.

V1.1: with `walls: auto` the family first finds where no slope fits
(corridor.walls) and adds a wall gap there, built as a listed wall is, then
writes the wall and structure-candidate tables (StructureModel.tables).
With a steep rule or a `guardrail:` block it lays guardrail
(corridor.guardrail) from the sections' guarded spans and at the structure
gaps, re-resolves every section a rail runs past with the 10:1 widening
behind it (section.resolve's `rail`), and writes each run as an IfcRailing
GUARDRAIL and the guardrail table.

Spec: docs/superpowers/specs/2026-11-21-road-corridor-design.md.
"""
from __future__ import annotations

import math
import sys

REQUIRED = ("alignment", "profile", "ground", "section")
LAYER = "C-ROAD"
#: how far a course's exact volume may stray from its average end areas,
#: and its mesh from its exact volume (check_arc_faceting's
#: FACET_TOLERANCE, the same 0.5%)
AEA_TOL = 0.005
#: no section is added where a side turns closer than this to a station,
#: feet: the strip either side would be a sliver
TURN_GAP_FT = 0.01
#: how many times walls: auto may add walls the guardrail's widening needs
#: and lay the rail again
RAIL_WALL_ROUNDS = 5


#: stations closer than this are one station, feet
STATION_TOL_FT = 1e-6


def merge_stations(have: list, more, tol: float = STATION_TOL_FT) -> list:
    """`have` (ascending, distinct) with each of `more` not within `tol` of
    a station already kept, ascending: two rails ending at one station, or
    a rail end on a wall's or a band's station, cut one section."""
    out = list(have)
    for s in sorted(more):
        if all(abs(s - k) > tol for k in out):
            out.append(s)
    return sorted(out)


def bands(stations: list, s_start: float, band: float) -> list:
    """[(i0, i1)]: the index range of `stations` in each station band. The
    band boundaries are stations already (params.Corridor.stations)."""
    out = []
    for i in range(len(stations) - 1):
        k = math.floor((stations[i] - s_start) / band + 1e-9)
        if out and out[-1][0] == k:
            out[-1][2] = i + 1
        else:
            out.append([k, i, i + 1])
    return [(i0, i1) for _k, i0, i1 in out]


def geometry_stations(al, prof, s0: float, s1: float) -> list:
    """The alignment's and the profile's own points strictly inside (s0,
    s1): segment ends (PC, PT, and the PI where tangents meet), and each
    vertical curve's BVC, PVI and EVC. frame.densify steps between the
    stations it is given and does not add these, so a section must be cut
    at each one."""
    # alignment.Profile's vertical curves are symmetric: the PVI is mid-curve
    pvis = [c["bvc_station"] + 0.5 * c["length_ft"] for c in prof.curves]
    out = set(al.seg_breaks(s0, s1)) | set(prof.breaks(s0, s1))
    out.update(s for s in pvis if s0 + 1e-9 < s < s1 - 1e-9)
    return sorted(out)


def per_component(c, ground) -> list:
    """How many parts to cut each component's subgrade into for the
    earthwork (section.Section.earthwork_line): its widest anywhere on the
    corridor, either side, over the ground's cell size, so the ground is
    read about once a cell across the road. One count per corridor, so every
    station's earthwork line has the same points; a plane needs no division."""
    from bimforge.author.corridor.params import SIDES
    spacing = getattr(ground, "spacing_ft", None)
    out = []
    for comp in c.components:
        if not spacing:
            out.append(1)
            continue
        widest = max(_widest(c, comp, side) for side in SIDES)
        out.append(max(1, math.ceil(widest / spacing - 1e-9)))
    return out


def ground_reach(c) -> float:
    """How far from the line the corridor can reach, feet: its widest side
    and the daylight limit past it, or a listed wall's face if farther."""
    from bimforge.author.corridor.params import SIDES
    half = max(sum(_widest(c, comp, side) for comp in c.components)
               for side in SIDES)
    walls = [g.offset for g in c.gaps if g.kind == "wall" and g.offset is not None]
    return max([half + c.slopes.daylight_limit] + walls)


def _widest(c, comp, side: str) -> float:
    """The widest `comp` gets on `side` anywhere in its width table; with
    walls: auto the outermost shoulder at least CUT_WALL_SHOULDER_FT, which a
    cut wall found later may widen it to, on either side."""
    from bimforge.author.corridor.params import CUT_WALL_SHOULDER_FT
    w = max([comp.width] + [w for _s, w in c.widths.get((comp.name, side), ())])
    if c.auto_walls and comp.name == c.widened():
        w = max(w, CUT_WALL_SHOULDER_FT)
    return w


def across_crown(left: list, right: list) -> list:
    """One ring from the left and right rings of a component that meets
    its other side at the crown: the left ring, then the right ring back,
    less the crown edge they share. Both are [crown top, outer top, outer
    bottom, crown bottom] (section.resolve), so the ring has six points at
    every station and winds as the left ring does."""
    if left[0] != right[0] or left[-1] != right[-1]:
        raise ValueError(f"the left and right rings do not share a crown edge "
                         f"({left[0]}, {left[-1]} vs {right[0]}, {right[-1]})")
    return list(left) + list(right[::-1][1:-1])


def _in_lead_in(c, s: float) -> bool:
    """Whether station s is strictly inside an automatic wall's
    WALL_TRANSITION_FT lead-in, either side of the road: a turn on one side
    is a section across both, and the wall's side there is a slope that
    walls.find has not checked."""
    from bimforge.author.corridor.params import WALL_TRANSITION_FT
    return any(g.start - WALL_TRANSITION_FT < s < g.start
               or g.end < s < g.end + WALL_TRANSITION_FT
               for g in c.gaps if g.auto is not None)


def _terrain(model) -> str | None:
    """The TERRAIN element's name, when the ground added one (3DEP)."""
    for el in model.elements:
        if (el.ifc_class == "IfcGeographicElement"
                and (el.predefined_type or "").upper() == "TERRAIN"):
            return el.name
    return None


def _parts(r: int) -> tuple:
    """Run r's ROADSEGMENT, and its lateral parts by component kind."""
    from bimforge.author.corridor.params import PART_TYPES
    seg = {"name": f"Segment {r}", "predefined_type": "ROADSEGMENT",
           "usage_type": "LONGITUDINAL"}
    return seg, {kind: {"name": f"Segment {r} {kind}", "predefined_type": pt,
                        "usage_type": "LATERAL", "parent": seg}
                 for kind, pt in PART_TYPES.items()}


def lay_rails(c, runs: list) -> list:
    """The guardrail runs (corridor.guardrail.RailRun) of corridor `c`, from
    `runs`, each corridor run's sections (section.Section) by station: each
    side's guarded spans, run by run so none straddles a structure gap, and
    bridge rail at each structure gap's ends, tied into the side's walls.

    The rail face is the shoulder edge; its offsets (L2 from the edge of
    traveled way, L from the centreline) are read where each length of
    need is laid (guardrail.lay_out's `offsets`), so a shoulder widening
    elsewhere on the run changes no rail; one widening under a rail is
    refused (rail_element). An
    automatic cut wall's 10 ft shoulder widens over its 1 ft lead-ins, so a
    rail tying into one ends at the lead-in's far end, the shoulder edge not
    moving under it (rail_element)."""
    from bimforge.author.corridor import guardrail
    from bimforge.author.corridor.params import SIDES, WALL_TRANSITION_FT
    from bimforge.author.corridor.section import grade_edge
    out = []
    for side in SIDES:
        walls = [(g.start - WALL_TRANSITION_FT, g.end + WALL_TRANSITION_FT)
                 if g.auto == "cut" else (g.start, g.end)
                 for g in c.gaps if g.kind == "wall" and g.side == side]
        for secs in runs:
            s0, s1 = secs[0].s, secs[-1].s
            spans = guardrail.spans([sec.s for sec in secs],
                                    [sec.sides[side].guarded for sec in secs])

            def offsets(s, side=side):
                face = abs(grade_edge(c, s, side)[0])
                return face - c.etw(side, s), face

            out += guardrail.side_runs(side, spans, None, None,
                                       c.guard.speed_mph, [(s0, s1)],
                                       c.s_start, c.s_end, walls=walls,
                                       offsets=offsets)
    # side_runs drops empty runs; rail_element is never handed one
    return [r for r in out if r.length > guardrail.EDGE_TOL_FT]


def under_rail(c, rails: list, s: float) -> tuple:
    """The sides a rail of `rails` runs past at station s, its ends
    included, that take its widening there: not in a wall's 1 ft lead-in
    on that side (WALL_TRANSITION_FT), whose far end is the slope
    walls.find checked fits, and which turns into the wall as V1's does.
    The widening starts a foot further out (rail_stations)."""
    from bimforge.author.corridor.params import WALL_TRANSITION_FT
    lead = WALL_TRANSITION_FT + 1e-6

    def in_lead_in(side):
        return any(g.start - lead <= s < g.start - 1e-6
                   or g.end + 1e-6 < s <= g.end + lead
                   for g in c.gaps if g.kind == "wall" and g.side == side)

    return tuple(sorted({r.side for r in rails
                         if r.start - 1e-6 <= s <= r.end + 1e-6
                         and not in_lead_in(r.side)}))


def rail_stations(c, rails: list, s0: float, s1: float) -> list:
    """The stations on [s0, s1] a section is cut at for `rails`: each rail's
    ends, and a foot past each wall lead-in under a rail, so the widening
    starts and stops at them."""
    from bimforge.author.corridor.params import WALL_TRANSITION_FT
    out = [s for r in rails for s in (r.start, r.end)]
    for g in c.gaps:
        if g.kind != "wall":
            continue
        for s in (g.start - 2 * WALL_TRANSITION_FT, g.end + 2 * WALL_TRANSITION_FT):
            if any(r.side == g.side and r.start - 1e-6 <= s <= r.end + 1e-6
                   for r in rails):
                out.append(s)
    return [s for s in out if s0 - 1e-6 <= s <= s1 + 1e-6]


def rail_segment(rail, runs: list) -> int:
    """The number (from 1) of the corridor run, of `runs` (each its
    sections), that `rail` starts on: its ROADSEGMENT."""
    from bimforge.author.alignment import sta
    r = next((r for r, secs in enumerate(runs, start=1)
              if secs[0].s - 1e-6 <= rail.start <= secs[-1].s + 1e-6), None)
    if r is None:
        raise ValueError(f"{rail_name(rail)}: starts at {sta(rail.start)}, on "
                         f"no corridor run (inside a structure gap?)")
    return r


def mean_depth(volume_cf: float, columns: list) -> float:
    """A band's mean cut or fill depth: its volume over the plan area under
    its columns (earthwork.plan_area_sf). Every column has plan area
    (earthwork._column drops one that has none), so a band with earthwork
    has some; MeanDepth is a required dimension, so none gives 0 rather
    than a division by zero."""
    from bimforge.author.corridor import earthwork
    area = earthwork.plan_area_sf(columns)
    return volume_cf / area if area > 0.0 else 0.0


def rail_name(rail) -> str:
    from bimforge.author.alignment import sta
    return f"Guardrail {rail.side} STA {sta(rail.start)} to {sta(rail.end)}"


def rail_element(rail, c, al, prof, ctx, segment):
    """`rail` (corridor.guardrail.RailRun) as an IfcRailing GUARDRAIL: the
    W-beam band at the shoulder edge, 31 in to the top of rail, a plumb
    SweptSection along the alignment and profile, raised by the edge's
    height off the profile grade line (its camber, at the corridor's
    stations, linear between them as superelevation is). Posts, terminals,
    AGTs and anchors are counted (BIMForge_Guardrail), not modelled; its
    class, BIMForge_Dimensions and Length formula are corridor.dimensions'.
    A rail
    is one section, so a shoulder edge moving sideways under it (a width
    transition) is refused."""
    from bimforge.author.corridor import dimensions as dims
    from bimforge.author.corridor import guardrail
    from bimforge.author.corridor.section import grade_edge
    from bimforge.author.model import Element
    from bimforge.author.sweep import SweptSection
    name = rail_name(rail)
    stations = c.stations(rail.start, rail.end)
    edges = [grade_edge(c, s, rail.side) for s in stations]
    faces = [abs(u) for u, _v in edges]
    if max(faces) - min(faces) > guardrail.EDGE_TOL_FT:
        raise ValueError(
            f"{name}: the shoulder edge moves {max(faces) - min(faces):.2f} ft "
            f"under the rail (a width transition); a rail is one section, so "
            f"end the transition outside the run")
    sweep = SweptSection(name, guardrail.band(rail.side, edges[0][0]), al,
                         rail.start, rail.end, profile=prof,
                         camber=[(s, v) for s, (_u, v) in zip(stations, edges)],
                         frame="plumb", ifc="IfcRailing", layer=LAYER, origin=ctx)
    return Element.from_geometry(
        name, sweep, ifc_class="IfcRailing", predefined_type="GUARDRAIL",
        type_name=guardrail.TYPE_NAME, typed_late=True,
        family_class=dims.GUARDRAIL, material="Steel", layer=LAYER,
        spatial_part=segment,
        quantities={"length_ft": rail.length},
        dimensions={"RailHeight": guardrail.RAIL_TOP_FT,
                    "PostSpacing": guardrail.POST_SPACING_FT,
                    **dims.stations(rail.start, rail.end)},
        psets={"BIMForge_Guardrail": {
            "PostCount": rail.posts, "StartTreatment": rail.start_end,
            "EndTreatment": rail.end_end, "Terminals": rail.terminals,
            "AGTTransitions": rail.agts, "Anchors": rail.anchors}},
        standard_qto={"Qto_RailingBaseQuantities": {
            "Length": ("length", rail.length, dims.LENGTH)}})


def _rail_warnings(rail, c) -> list:
    """What the build warns of for `rail`: a run held short of its minimum,
    a terminal held at the alignment's end."""
    from bimforge.author.alignment import sta
    from bimforge.author.corridor import guardrail
    from bimforge.author.corridor.guardrail import TERMINAL
    name = rail_name(rail)
    out = []
    if rail.below_minimum:
        out.append(f"road-corridor: guardrail {name}: {rail.length:.2f} ft "
                   f"between fixed ends, under the {guardrail.MIN_RUN_FT:g} ft "
                   f"minimum length of need (TSSM 3.6(1))")
    if rail.short_end:
        for s, kind in ((rail.start, rail.start_end), (rail.end, rail.end_end)):
            if kind != TERMINAL or min(abs(s - c.s_start), abs(s - c.s_end)) > 1e-6:
                continue
            out.append(f"road-corridor: guardrail {name}: its terminal at STA "
                       f"{sta(s)} is held at the alignment's end, with no room "
                       f"for its gating; its length of need may run past it")
    return out


def build(params: dict, ctx) -> "StructureModel":
    from bimforge.author.alignment import Alignment, Profile, sta
    from bimforge.author.corridor import dimensions as dims
    from bimforge.author.corridor import earthwork, guardrail, masshaul
    from bimforge.author.corridor import walls as auto_walls
    from bimforge.author.corridor.frame import densify, survey_point
    from bimforge.author.corridor.ground import from_params
    from bimforge.author.corridor.loft import StationLoft, pappus
    from bimforge.author.corridor.params import SIDES, parse
    from bimforge.author.corridor.section import NoDaylight, kind_changes, resolve
    from bimforge.author.model import Element, StructureModel

    missing = [k for k in REQUIRED if params.get(k) is None]
    if missing:
        raise ValueError(f"road-corridor params missing {missing}")
    al_p = params["alignment"]
    al = Alignment(al_p["pob"], al_p["run"], name=al_p.get("name", "ML"))
    prof = Profile(params["profile"]["curves"])
    c = parse(params, al.s_start, al.s_end)
    model = StructureModel("road-corridor", ctx)
    def log(msg):
        print(msg, file=sys.stderr)

    ground = from_params(params["ground"], al, ctx, ground_reach(c), model,
                         log=log)
    divide = per_component(c, ground)
    # a cut is ground taken out of the TERRAIN (emit_ifc #364), when there
    # is one to void and a schema with IfcEarthworksCut to void it with
    from bimforge.author.spatial import schema_has_facilities
    host = _terrain(model) if schema_has_facilities(ctx.schema) else None

    def survey(s, u, v):
        return survey_point(al, prof, s, u, v)

    def ground_dz(s, u, v):
        n, e, z = survey(s, u, v)
        return ground.z(n, e) - z

    def run_stations(s0, s1):
        return densify(al, prof, c.stations(
            s0, s1, geometry_stations(al, prof, s0, s1)))

    if c.auto_walls:
        # V1.1: a wall wherever a side's slope cannot fit, found on the
        # stations the corridor cuts, then added as wall gaps. `c` changes
        # here, so run_stations below also cuts each wall's ends and the
        # foot outside them (params.Corridor.stations)
        c = c.with_walls([g for s0, s1 in c.runs()
                          for g in auto_walls.find(c, run_stations(s0, s1),
                                                   ground_dz)])
    def first_pass(c):
        """Each corridor run's sections, with a section where a side turns."""
        runs = []
        for s0, s1 in c.runs():
            stations = run_stations(s0, s1)
            secs = [resolve(c, s, ground_dz) for s in stations]
            # a section where a side turns between cut and fill
            # (section.kind_changes), unless a station is already that close
            # or it falls in an automatic wall's lead-in: walls.find checked
            # only the lead-in's far end, and the slope inside it may not fit
            turns = [t for a, b in zip(secs, secs[1:])
                     for t in kind_changes(c, a, b, ground_dz)
                     if min(t - a.s, b.s - t) > TURN_GAP_FT
                     and not _in_lead_in(c, t)]
            if turns:
                stations = merge_stations(stations, turns)
                known = {sec.s: sec for sec in secs}
                secs = [known.get(s) or resolve(c, s, ground_dz) for s in stations]
            runs.append(secs)
        return runs

    def with_rail_stations(c, runs, rails):
        """Each run's stations, with rail_stations added."""
        out = []
        for secs in runs:
            have = [sec.s for sec in secs]
            out.append(merge_stations(have, rail_stations(c, rails, have[0],
                                                          have[-1])))
        return out

    def second_pass(c, runs, rails):
        """`runs` with every section a rail runs past resolved again with
        the widening behind it, and one at each rail_stations station.

        The widening is full from the section at a rail's end (or a foot
        past a wall's lead-in): beyond it, it tapers to nothing over the
        station interval to the next section, lofted point to point."""
        out = []
        for secs, stations in zip(runs, with_rail_stations(c, runs, rails)):
            known = {sec.s: sec for sec in secs}
            done = []
            for s in stations:
                sides = under_rail(c, rails, s)
                if not sides and s in known:
                    done.append(known[s])
                    continue
                try:
                    done.append(resolve(c, s, ground_dz, rail=sides))
                except NoDaylight as exc:
                    # with walls: auto, walls.find has placed a wall
                    # wherever the widening does not fit (below)
                    raise ValueError(
                        f"guardrail: the widening behind the rail at {sta(s)} "
                        f"pushes the slope out: {exc}; list a wall gap there, "
                        f"widen footprint_ft, or set walls: auto") from None
            out.append(done)
        return out

    hauls, haul_elements, every = [], [], []
    runs = first_pass(c)
    rails = []
    if c.guard is not None:
        # V1.1: rail from the guarded spans and at the structure gaps, then
        # every section a rail runs past again, with the widening behind
        # it, and one at each rail end, so the widening starts and stops
        # there. The guarded flags are read at the subgrade hinge, which
        # the widening does not move. Under walls: auto, a slope the
        # widening pushes past the footprint takes a wall (walls.find with
        # the rail), the rail is laid again to tie into it, and so on until
        # no wall is added
        for _round in range(RAIL_WALL_ROUNDS + 1):
            rails = lay_rails(c, runs)
            if not c.auto_walls:
                break
            new = [g for secs, stations in zip(runs, with_rail_stations(c, runs, rails))
                   for g in auto_walls.find(
                       c, stations, ground_dz,
                       rail=lambda s, side: side in under_rail(c, rails, s))]
            if not new:
                break
            if _round == RAIL_WALL_ROUNDS:
                raise ValueError(
                    f"guardrail: walls: auto still adds a {new[0].auto} wall on "
                    f"the {new[0].side} side at {sta(new[0].start)} to "
                    f"{sta(new[0].end)} behind the rail after "
                    f"{RAIL_WALL_ROUNDS} rounds; list a wall gap there")
            c = c.with_walls(new)
            runs = first_pass(c)
        runs = second_pass(c, runs, rails)
    for r, secs in enumerate(runs, start=1):
        segment, parts = _parts(r)
        stations = [sec.s for sec in secs]
        every.extend(secs)
        for i0, i1 in bands(stations, al.s_start, c.band):
            b0, b1 = stations[i0], stations[i1]
            ss, bs = stations[i0:i1 + 1], secs[i0:i1 + 1]
            tag = f"STA {sta(b0)} to {sta(b1)}"
            for k, course in enumerate(c.courses):
                for j, comp in enumerate(c.components):
                    name = f"{course.name} {comp.name} {tag}"
                    if j == 0:
                        # the two sides meet at the crown: one body, so
                        # the element's bodies do not touch
                        rings = [[across_crown(sec.courses[k, j, "L"],
                                               sec.courses[k, j, "R"])
                                  for sec in bs]]
                        names = [name]
                    else:
                        rings = [[sec.courses[k, j, side] for sec in bs]
                                 for side in SIDES]
                        names = [f"{name} {side}" for side in SIDES]
                    lofts = [StationLoft(n, al, prof, ctx, ss, rs,
                                         ifc="IfcCourse", layer=LAYER)
                             for n, rs in zip(names, rings)]
                    # the bodies' exact volume and their combined
                    # centroid's path (loft.pappus); the Volume formula
                    # only where that path box is the volume
                    centroid = pappus(lofts)
                    vol = centroid.volume_cf
                    aea = sum(lf.average_end_area_cf for lf in lofts)
                    shape, volume = dims.course_volume(
                        vol, centroid.path_ft,
                        [sum(ws) for ws in zip(*(lf.widths_ft for lf in lofts))],
                        course.thickness)
                    model.add(Element(
                        name, ifc_class="IfcCourse", geometry=lofts,
                        predefined_type=course.type, type_name=course.name,
                        material=course.name, layer=LAYER, body="solids",
                        spatial_part=parts[comp.kind], family_class=dims.COURSE,
                        dimensions={"Thickness": course.thickness, **shape,
                                    "Offset": centroid.offset_ft,
                                    "PathLength": centroid.path_ft,
                                    **dims.stations(b0, b1)},
                        quantities={"length_ft": b1 - b0, "volume_cf": vol},
                        standard_qto={"Qto_CourseBaseQuantities": {
                            "Length": ("length", b1 - b0, dims.LENGTH),
                            "Width": ("length", sum(lf.mean_width_ft for lf in lofts)),
                            "Thickness": ("length", course.thickness),
                            "Volume": volume}}))
                    # the exact volume (loft.pappus) against a figure that
                    # does not read it; the mesh is held to the exact
                    # volume by the pre gate's arc-faceting check, and the
                    # post gate's exact-sweep leg sums the same exact figure
                    model.stated_quantities.append(
                        (f"{name}: exact volume vs average end area", vol, aea,
                         AEA_TOL * max(aea, 1.0)))
            cut, fill, cut_d, fill_d = [], [], 0.0, 0.0
            for a, b in zip(bs, bs[1:]):
                cp, fp, cd, fd = earthwork.strip(f"{tag} {sta(a.s)}", a, b,
                                                 survey, ground.z, ctx,
                                                 per_component=divide)
                cut += cp
                fill += fp
                cut_d, fill_d = max(cut_d, cd), max(fill_d, fd)
            # the band's mean width, weighted by length as a course's is
            width = dims.band_mean(ss, [sec.width() for sec in bs])
            cut_cf = sum(p.volume_cf for p in cut)
            fill_cf = sum(p.volume_cf for p in fill)
            els = []
            if cut:
                cut_dims = {"MaxDepth": cut_d,
                            "MeanDepth": mean_depth(cut_cf, cut),
                            "SlopeRatio": c.slopes.cut_ratio,
                            **dims.stations(b0, b1)}
                if c.slopes.rock is not None:
                    # how far down the rock lies, the band's mean by length
                    cut_dims["RockDepth"] = dims.band_mean(
                        ss, [c.slopes.rock.depth_at(s) for s in ss])
                els.append(model.add(Element(
                    f"Cut {tag}", ifc_class="IfcEarthworksCut",
                    geometry=earthwork.merge(f"Cut {tag}", "cut", cut),
                    predefined_type="CUT", layer=LAYER, body="solids",
                    spatial_part=segment, voids=host,
                    family_class=dims.CUT, dimensions=cut_dims,
                    quantities={"length_ft": b1 - b0, "volume_cf": cut_cf},
                    standard_qto={"Qto_EarthworksCutBaseQuantities": {
                        "Length": ("length", b1 - b0, dims.LENGTH),
                        "Width": ("length", width),
                        "Depth": ("length", cut_d),
                        "UndisturbedVolume": ("volume", cut_cf),
                        "LooseVolume": ("volume", cut_cf * (1.0 + c.swell))}})))
            if fill:
                bank = fill_cf / (1.0 - c.shrink)
                # the steepest fill slope the band's sections take; none
                # where every fill side is a wall (SlopeRatio is optional)
                ratios = [sec.sides[side].ratio for sec in bs for side in SIDES
                          if sec.sides[side].kind == "fill"
                          and sec.sides[side].ratio is not None]
                fill_dims = {"MaxDepth": fill_d,
                             "MeanDepth": mean_depth(fill_cf, fill),
                             **dims.stations(b0, b1)}
                if ratios:
                    fill_dims["SlopeRatio"] = min(ratios)
                els.append(model.add(Element(
                    f"Fill {tag}", ifc_class="IfcEarthworksFill",
                    geometry=earthwork.merge(f"Fill {tag}", "fill", fill),
                    predefined_type="EMBANKMENT", layer=LAYER, body="solids",
                    spatial_part=segment, family_class=dims.FILL,
                    dimensions=fill_dims,
                    quantities={"length_ft": b1 - b0, "volume_cf": fill_cf},
                    standard_qto={"Qto_EarthworksFillBaseQuantities": {
                        "Length": ("length", b1 - b0, dims.LENGTH),
                        "Width": ("length", width),
                        "Depth": ("length", fill_d),
                        "CompactedVolume": ("volume", fill_cf),
                        "LooseVolume": ("volume", bank * (1.0 + c.swell))}})))
            hauls.append((b0, b1, cut_cf, fill_cf))
            haul_elements.append(els)
    # after every run's courses and earthwork, so their order is V1's
    for rail in rails:
        model.add(rail_element(rail, c, al, prof, ctx,
                               _parts(rail_segment(rail, runs))[0]))
        for msg in _rail_warnings(rail, c):
            log(msg)
    model.mass_haul = masshaul.mass_haul(hauls, c.shrink)
    for els, row in zip(haul_elements, model.mass_haul):
        for el in els:
            # stations as BIMForge_LinearReference writes them: lengths,
            # with their texts; the ordinate a volume (the CSV keeps CY)
            el.psets["BIMForge_MassHaul"] = {
                "StartStation": ("length", row.start),
                "EndStation": ("length", row.station),
                "StartStationText": sta(row.start),
                "EndStationText": sta(row.station),
                "CumulativeVolume": ("volume",
                                     row.cumulative_cy * masshaul.CF_PER_CY)}
    if c.auto_walls:
        # outputs.walls and outputs.structures (the registry writes them);
        # a structure candidate's low point is the lowest ground on the
        # centreline among the stations cut
        rows = auto_walls.rows(c, every, ground_dz)
        model.tables["walls"] = auto_walls.walls_csv(rows)
        model.tables["structures"] = auto_walls.structures_csv(
            auto_walls.structures(rows, sorted(sec.s for sec in every),
                                  lambda s: ground.z(*survey(s, 0.0, 0.0)[:2])))
    if c.guard is not None:
        model.tables["guardrail"] = guardrail.to_csv(rails)
    return model
