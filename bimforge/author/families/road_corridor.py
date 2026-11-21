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

Spec: docs/superpowers/specs/2026-11-21-road-corridor-design.md.
"""
from __future__ import annotations

import math
import sys

REQUIRED = ("alignment", "profile", "ground", "section")
LAYER = "C-ROAD"
#: how far a course's mesh volume may stray from its average end area
AEA_TOL = 0.005
#: no section is added where a side turns closer than this to a station,
#: feet: the strip either side would be a sliver
TURN_GAP_FT = 0.01


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
        widest = max([comp.width] + [w for side in SIDES
                                     for _s, w in c.widths.get((comp.name, side), ())])
        out.append(max(1, math.ceil(widest / spacing - 1e-9)))
    return out


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


def build(params: dict, ctx) -> "StructureModel":
    from bimforge.author.alignment import Alignment, Profile, sta
    from bimforge.author.corridor import earthwork, masshaul
    from bimforge.author.corridor.frame import densify, survey_point
    from bimforge.author.corridor.ground import from_params
    from bimforge.author.corridor.loft import StationLoft
    from bimforge.author.corridor.params import SIDES, parse
    from bimforge.author.corridor.section import kind_changes, resolve
    from bimforge.author.model import Element, StructureModel

    missing = [k for k in REQUIRED if params.get(k) is None]
    if missing:
        raise ValueError(f"road-corridor params missing {missing}")
    al_p = params["alignment"]
    al = Alignment(al_p["pob"], al_p["run"], name=al_p.get("name", "ML"))
    prof = Profile(params["profile"]["curves"])
    c = parse(params, al.s_start, al.s_end)
    model = StructureModel("road-corridor", ctx)
    walls = [g.offset for g in c.gaps if g.kind == "wall"]
    reach = max([c.max_half_width() + c.slopes.daylight_limit] + walls)
    ground = from_params(params["ground"], al, ctx, reach, model,
                         log=lambda m: print(m, file=sys.stderr))
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

    hauls, haul_elements = [], []
    for r, (s0, s1) in enumerate(c.runs(), start=1):
        segment, parts = _parts(r)
        stations = densify(al, prof, c.stations(
            s0, s1, geometry_stations(al, prof, s0, s1)))
        secs = [resolve(c, s, ground_dz) for s in stations]
        # a section where a side turns between cut and fill
        # (section.kind_changes), unless a station is already that close
        turns = [t for a, b in zip(secs, secs[1:])
                 for t in kind_changes(c, a, b, ground_dz)
                 if min(t - a.s, b.s - t) > TURN_GAP_FT]
        if turns:
            stations = sorted(stations + turns)
            known = {sec.s: sec for sec in secs}
            secs = [known.get(s) or resolve(c, s, ground_dz) for s in stations]
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
                    vol = sum(lf.volume_cf for lf in lofts)
                    aea = sum(lf.average_end_area_cf for lf in lofts)
                    model.add(Element(
                        name, ifc_class="IfcCourse", geometry=lofts,
                        predefined_type=course.type, type_name=course.name,
                        material=course.name, layer=LAYER, body="solids",
                        spatial_part=parts[comp.kind],
                        quantities={"length_ft": b1 - b0, "volume_cf": vol},
                        standard_qto={"Qto_CourseBaseQuantities": {
                            "Length": ("length", b1 - b0),
                            "Width": ("length", sum(lf.mean_width_ft for lf in lofts)),
                            "Thickness": ("length", course.thickness),
                            "Volume": ("volume", vol)}}))
                    # the mesh against a figure that does not read it: the
                    # post gate's volume leg for an exact sweep is the
                    # loft's own mesh volume, so this is the independent one
                    model.stated_quantities.append(
                        (f"{name}: mesh volume vs average end area", vol, aea,
                         AEA_TOL * max(aea, 1.0)))
            cut, fill, cut_d, fill_d = [], [], 0.0, 0.0
            for a, b in zip(bs, bs[1:]):
                cp, fp, cd, fd = earthwork.strip(f"{tag} {sta(a.s)}", a, b,
                                                 survey, ground.z, ctx,
                                                 per_component=divide)
                cut += cp
                fill += fp
                cut_d, fill_d = max(cut_d, cd), max(fill_d, fd)
            width = sum(sec.width() for sec in bs) / len(bs)
            cut_cf = sum(p.volume_cf for p in cut)
            fill_cf = sum(p.volume_cf for p in fill)
            els = []
            if cut:
                els.append(model.add(Element(
                    f"Cut {tag}", ifc_class="IfcEarthworksCut",
                    geometry=earthwork.merge(f"Cut {tag}", "cut", cut),
                    predefined_type="CUT", layer=LAYER, body="solids",
                    spatial_part=segment, voids=host,
                    quantities={"length_ft": b1 - b0, "volume_cf": cut_cf},
                    standard_qto={"Qto_EarthworksCutBaseQuantities": {
                        "Length": ("length", b1 - b0), "Width": ("length", width),
                        "Depth": ("length", cut_d),
                        "UndisturbedVolume": ("volume", cut_cf),
                        "LooseVolume": ("volume", cut_cf * (1.0 + c.swell))}})))
            if fill:
                bank = fill_cf / (1.0 - c.shrink)
                els.append(model.add(Element(
                    f"Fill {tag}", ifc_class="IfcEarthworksFill",
                    geometry=earthwork.merge(f"Fill {tag}", "fill", fill),
                    predefined_type="EMBANKMENT", layer=LAYER, body="solids",
                    spatial_part=segment,
                    quantities={"length_ft": b1 - b0, "volume_cf": fill_cf},
                    standard_qto={"Qto_EarthworksFillBaseQuantities": {
                        "Length": ("length", b1 - b0), "Width": ("length", width),
                        "Depth": ("length", fill_d),
                        "CompactedVolume": ("volume", fill_cf),
                        "LooseVolume": ("volume", bank * (1.0 + c.swell))}})))
            hauls.append((b0, b1, cut_cf, fill_cf))
            haul_elements.append(els)
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
    return model
