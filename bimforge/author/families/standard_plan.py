"""standard-plan — section-table retaining walls: tables keyed by design H
(XLOOKUP semantics: round UP with the standard plans' 6-in grace),
instantiated per station along an alignment.

Params (all data, no client content in the plugin — real agency tables live
bid-side):

    alignment: {pob: {...}|anchor form, run: [...]}     # author.alignment
    tables: {type_1_case_1: {...}, type_5_case_1: {...}}  # WallSection format
    walls:
      - name: R1
        wall_type: 1
        front_side: Lt
        beg: {station: 3026.0}
        end: {station: 3410.0}
        grid_ft: 8.0
        design_h_segments: [{length_ft: 128.0, H_ft: 8}, ...]
        top_of_wall: {start_station: 3026.0, grid_ft: 8.0, elevs: [...]}
        footing_bottom: {steps: [{station: 3026.0, elev: 100.0}, ...]}
"""
from __future__ import annotations

import math

from bimforge.author import family_dictionary as fd
from bimforge.author.alignment import (Alignment, WallSection, _resolve_pob,
                                       check_pob_survey, sta)
from bimforge.author.model import Element, StructureModel
from bimforge.author.modified import FIELD_DIMENSIONS
from bimforge.author.primitives import Prism
from bimforge.author.sweep import to_model, to_model_elev

REQUIRED = ("alignment", "tables", "walls")


def _wall_H(w, station):
    s = w["beg"]["station"]
    for seg in w["design_h_segments"]:
        if station <= s + seg["length_ft"] + 1e-6:
            return seg["H_ft"]
        s += seg["length_ft"]
    return w["design_h_segments"][-1]["H_ft"]


def _wall_top(w, station):
    t = w["top_of_wall"]
    g, s0, ev = t["grid_ft"], t["start_station"], t["elevs"]
    x = (station - s0) / g
    i = max(0, min(len(ev) - 2, int(x)))
    frac = min(1.0, max(0.0, x - i))
    return ev[i] + (ev[i + 1] - ev[i]) * frac


def _wall_footing_bottom(w, station):
    z = w["footing_bottom"]["steps"][0]["elev"]
    for st in w["footing_bottom"]["steps"]:
        if station >= st["station"] - 1e-6:
            z = st["elev"]
    return z


def _cuts(w):
    """Slice at every grid point, design-H break and footing step, so no
    slice ever spans a change in section or elevation (bridge-pilot lesson)."""
    s0, s1 = w["beg"]["station"], w["end"]["station"]
    cuts = {s0, s1}
    t = w["top_of_wall"]
    x = t["start_station"]
    while x < s1:
        if s0 < x < s1:
            cuts.add(x)
        x += t["grid_ft"]
    acc = s0
    for seg in w["design_h_segments"]:
        acc += seg["length_ft"]
        if s0 < acc < s1:
            cuts.add(round(acc, 4))
    for st in w["footing_bottom"]["steps"]:
        if s0 < st["station"] < s1:
            cuts.add(st["station"])
    return sorted(cuts)


#: The wall types whose stem is one constant thickness, both faces vertical
#: (B3-3A, B3-7A): an IfcWall with a material layer set (X.6). Types 1 and 5
#: are battered, a section IFC writes with a plain material, not layers.
CONSTANT_STEM = ("1a", "6a", "6b")


def _own_frame(ring):
    """A stem slice's plan [front a, front b, back b, back a] in its own
    frame, with the placement that puts it back where it was: the origin
    at whichever face's start leaves the other face on +y, the x-axis along
    that face. The layer-set wall concept reads the layer off that axis."""
    fa, fb, bb, ba = ring
    ux, uy = fb[0] - fa[0], fb[1] - fa[1]
    n = math.hypot(ux, uy)
    ux, uy = ux / n, uy / n
    if (ba[0] - fa[0]) * -uy + (ba[1] - fa[1]) * ux < 0.0:
        fa, fb, bb, ba = ba, bb, fb, fa      # start on the back face instead
    ox, oy = fa
    local = [((x - ox) * ux + (y - oy) * uy, (x - ox) * -uy + (y - oy) * ux)
             for x, y in (fa, fb, bb, ba)]
    return local, {"x_ft": ox, "y_ft": oy,
                   "bearing_deg": math.degrees(math.atan2(uy, ux))}


def _dimensions(cls, ws) -> dict:
    """The dimensions `cls` declares (M.2), from the slice's section: design
    H, the stem's thickness at top and base and its batter, the footing's
    toe and heel (its width and thickness are quantities)."""
    have = {"DesignHeight": ws.H, "StemThickness": ws.T,
            "StemBaseThickness": ws.stem_base_thickness, "Batter": ws.batter,
            "ToeWidth": ws.C, "HeelWidth": ws.B}
    return {code: have[code] for code in fd.dimensions(cls)}


#: The section attributes each element of a slice is built from (M.9)
_STEM_PARTS = ("T", "batter")
_FOOTING_PARTS = ("W", "C", "B", "F")


def _table_reads(cls, ws, parts) -> dict:
    """{table path: name} of the values `parts` of `ws` were read from: a
    field named by the dimension `cls` declares for it, else by itself."""
    declared = set(fd.dimensions(cls))
    reads = {}
    for part in parts:
        for p in ws.sources.get(part, ()):
            code = FIELD_DIMENSIONS.get(p[-1])
            reads[p] = code if code in declared else str(p[-1])
    return reads


def _plan(align, ctx, station, offset, side):
    """A station/offset as a model-frame plan point. `station_offset` speaks
    survey (northing, easting); the model is x=east, y=north, local to the
    project base, so it goes through `to_model` like every alignment family
    (#156: used raw, the pair mirrors the wall about the 45 deg diagonal)."""
    n, e = align.station_offset(station, offset, side)
    x, y, _z = to_model(ctx, n, e)
    return x, y


def wall_class(wall_type) -> str:
    """The dictionary class of a B3 wall type's stem ("retaining-wall-b3-
    type-1"); its footing's is the same code with "-footing"."""
    return f"retaining-wall-b3-type-{str(wall_type).strip().lower()}"


def build(params: dict, ctx) -> StructureModel:
    missing = [k for k in REQUIRED if params.get(k) is None]
    if missing:
        raise ValueError(f"standard-plan params missing {missing}")
    pl = params["alignment"]
    pob = _resolve_pob(pl)
    check_pob_survey(pob, ctx, "standard-plan")
    align = Alignment(pob, pl["run"], name=pl.get("name", "P"))
    tables = params["tables"]
    model = StructureModel("standard-plan", ctx)
    model.row_lookup = WallSection._lookup_key      # how a row is chosen

    for w in params["walls"]:
        tag = w["name"]
        front = w["front_side"]
        back = "Rt" if str(front).upper().startswith("L") else "Lt"
        cuts = _cuts(w)
        stem_cls = wall_class(w["wall_type"])
        foot_cls = f"{stem_cls}-footing"
        for a, b in zip(cuts[:-1], cuts[1:]):
            mid = (a + b) / 2.0
            H = _wall_H(w, mid)
            ws = WallSection(w["wall_type"], H, tables)
            # elevations -> model z (E - base_h), the frame every emitter reads
            fb = to_model_elev(ctx, _wall_footing_bottom(w, mid))
            ft_top = fb + ws.F
            z_top = to_model_elev(ctx, (_wall_top(w, a) + _wall_top(w, b)) / 2.0)
            h = z_top - ft_top
            if h <= 0.0:
                continue
            foot = [_plan(align, ctx, a, ws.C, front),
                    _plan(align, ctx, b, ws.C, front),
                    _plan(align, ctx, b, ws.B, back),
                    _plan(align, ctx, a, ws.B, back)]
            p = Prism(f"{tag} retaining wall footing {sta(a)}", foot, fb, ft_top,
                      dims_ft=(b - a, ws.W), ifc="IfcFooting")
            model.add(Element.from_geometry(
                p.name, p, ifc_class="IfcFooting", layer="S-CONC-OTLN",
                predefined_type="STRIP_FOOTING",
                type_name=fd.type_name(foot_cls),
                psets=fd.reference_psets(foot_cls), family_class=foot_cls,
                typed_late=True,
                dimensions=_dimensions(foot_cls, ws), volume_formula="box",
                table_reads=_table_reads(foot_cls, ws, _FOOTING_PARTS),
                table_rows=dict(ws.rows),
                quantities={"length_ft": b - a, "width_ft": ws.W,
                            "height_ft": ws.F, "volume_cf": p.volume_cf}))
            # stem at MID-HEIGHT thickness: the prism volume IS the trapezoid's
            th = ws.T + ws.batter * h / 2.0
            stem = [_plan(align, ctx, a, 0.0, front),
                    _plan(align, ctx, b, 0.0, front),
                    _plan(align, ctx, b, th, back),
                    _plan(align, ctx, a, th, back)]
            layered = ws.wall_type in CONSTANT_STEM
            place = {}
            if layered:
                stem, place = _own_frame(stem)
            p = Prism(f"{tag} retaining wall stem {sta(a)}", stem, ft_top, z_top,
                      dims_ft=(b - a, th), ifc="IfcWall")
            model.add(Element.from_geometry(
                p.name, p, ifc_class="IfcWall", layer="S-CONC-OTLN",
                predefined_type="RETAININGWALL",
                type_name=fd.type_name(stem_cls),
                psets=fd.reference_psets(stem_cls), family_class=stem_cls,
                typed_late=True,
                dimensions=_dimensions(stem_cls, ws), volume_formula="box",
                table_reads=_table_reads(stem_cls, ws, _STEM_PARTS),
                table_rows=dict(ws.rows),
                layer_thickness_ft=th if layered else None, **place,
                quantities={"length_ft": b - a, "width_ft": th,
                            "height_ft": h, "volume_cf": p.volume_cf}))

    model.checks.append(_check_segments_cover_runs(params))
    return model


def _check_segments_cover_runs(params):
    def check(model):
        fail = []
        for w in params["walls"]:
            run = w["end"]["station"] - w["beg"]["station"]
            segs = sum(s["length_ft"] for s in w["design_h_segments"])
            if abs(run - segs) > 1e-3:
                fail.append(f"{w['name']}: design-H segments sum {segs} ft but "
                            f"the run is {run} ft")
        return fail
    return check
