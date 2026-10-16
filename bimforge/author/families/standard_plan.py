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

from bimforge.author.alignment import Alignment, WallSection, _resolve_pob, sta
from bimforge.author.model import Element, StructureModel
from bimforge.author.primitives import Prism

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


def build(params: dict, ctx) -> StructureModel:
    missing = [k for k in REQUIRED if params.get(k) is None]
    if missing:
        raise ValueError(f"standard-plan params missing {missing}")
    pl = params["alignment"]
    align = Alignment(_resolve_pob(pl), pl["run"], name=pl.get("name", "P"))
    tables = params["tables"]
    model = StructureModel("standard-plan", ctx)

    for w in params["walls"]:
        tag = w["name"]
        front = w["front_side"]
        back = "Rt" if str(front).upper().startswith("L") else "Lt"
        cuts = _cuts(w)
        for a, b in zip(cuts[:-1], cuts[1:]):
            mid = (a + b) / 2.0
            H = _wall_H(w, mid)
            ws = WallSection(w["wall_type"], H, tables)
            fb = _wall_footing_bottom(w, mid)
            ft_top = fb + ws.F
            z_top = (_wall_top(w, a) + _wall_top(w, b)) / 2.0
            h = z_top - ft_top
            if h <= 0.0:
                continue
            foot = [align.station_offset(a, ws.C, front),
                    align.station_offset(b, ws.C, front),
                    align.station_offset(b, ws.B, back),
                    align.station_offset(a, ws.B, back)]
            p = Prism(f"{tag} retaining wall footing {sta(a)}", foot, fb, ft_top,
                      dims_ft=(b - a, ws.W), ifc="IfcFooting")
            model.add(Element.from_geometry(
                p.name, p, ifc_class="IfcFooting", layer="S-CONC-OTLN",
                quantities={"length_ft": b - a, "width_ft": ws.W,
                            "height_ft": ws.F, "volume_cf": p.volume_cf}))
            # stem at MID-HEIGHT thickness: the prism volume IS the trapezoid's
            th = ws.T + ws.batter * h / 2.0
            stem = [align.station_offset(a, 0.0, front),
                    align.station_offset(b, 0.0, front),
                    align.station_offset(b, th, back),
                    align.station_offset(a, th, back)]
            p = Prism(f"{tag} retaining wall stem {sta(a)}", stem, ft_top, z_top,
                      dims_ft=(b - a, th), ifc="IfcWall")
            model.add(Element.from_geometry(
                p.name, p, ifc_class="IfcWall", layer="S-CONC-OTLN",
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
