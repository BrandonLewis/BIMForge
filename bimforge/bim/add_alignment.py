"""bim.add_alignment: IfcAlignment added to a finished IFC4X3 from pob/run blocks.

`bimforge.author.emit_alignment` writes a model's alignments at build time.
This is the post-processor for everything else: a federated file, a
foreign IFC, or a model whose alignment is only known after the build. It
reads alignment blocks, `pob` + `run` (tangent / curve) in survey feet, the
same shape `bimforge.author.alignment.Alignment` takes. Each horizontal
segment is written as bimforge's traverse has it (a LINE or CIRCULARARC per
tangent or curve); ifcopenshell builds the IfcCompositeCurve of
IfcCurveSegments (geometry) from them and the zero-length terminator. An
IfcReferent with Pset_Stationing marks the start, every segment break and
any extra stations asked for.

The horizontal is not laid out with ifcopenshell's PI method: it misplaces a
curve that follows a curve with no tangent between (a curve split across two
sheets came out as a 313-degree loop the other way; a reverse curve divides
by zero) while the start and end still match (#52). The vertical still is.

Coordinates go through the file's own IfcMapConversion (CRS feet -> model
metres, with its rotation), so the alignment lands in the same engineering
frame as the elements.

Vertical (optional): a block may carry `profile:` with
`pvis: [{station, elevation}, ...]` (feet, the CRS vertical datum),
`vc_length_ft` (parabolic vertical curve length at each interior PVI,
0 = an angle point) and an optional `desc`. It must span the horizontal
exactly, from the POB station to the traverse end. Elevations go to model Z
through the IfcMapConversion: (EL - OrthogonalHeight) / Scale.

Gated before the caller writes anything. Each alignment's start and end,
recovered from the written curve, must match the traverse within `tol_ft`.
Every angle point must be the start of a written horizontal segment, and
every horizontal segment must end where the next one starts. With a
profile, each PVI elevation recovered from the written vertical segments must
match as well. `add_alignments` raises `AlignmentGateError` on any miss. The
file is then left changed in memory, so do not write it. `est-bim
add-alignments` writes only on success.
"""
from __future__ import annotations

import math
import re
import sys

from bimforge.author.alignment import M_PER_FT
from bimforge.author.emit_alignment import fix_terminator
from bimforge.bim.alignment_station import format_station

#: the pre-#51 name; callers outside bimforge (job wrappers) still import it
_fix_terminator = fix_terminator


class AlignmentGateError(ValueError):
    """A written alignment does not match its traverse (or the file cannot
    take one); the in-memory file must not be written."""


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _fmt_sta(s: float) -> str:
    return format_station(s, "ft")


def map_conversion(f) -> tuple[float, float, float, float]:
    """The file's IfcMapConversion as (Eastings, Northings, rotation rad, Scale)."""
    mcs = f.by_type("IfcMapConversion")
    if not mcs:
        raise AlignmentGateError("no IfcMapConversion - the model is not georeferenced")
    mc = mcs[0]
    a = mc.XAxisAbscissa if mc.XAxisAbscissa is not None else 1.0
    o = mc.XAxisOrdinate if mc.XAxisOrdinate is not None else 0.0
    return mc.Eastings, mc.Northings, math.atan2(o, a), mc.Scale or 1.0


def to_model(e: float, n: float, mc) -> tuple[float, float]:
    """CRS (E, N) -> model (x, y): the inverse of IfcMapConversion."""
    e0, n0, rot, scale = mc
    de, dn = (e - e0) / scale, (n - n0) / scale
    c, s = math.cos(rot), math.sin(rot)
    return de * c + dn * s, -de * s + dn * c


def traverse_pis(al: dict):
    """Traverse -> (Alignment, PI list in survey (E, N), radii, break stations).

    A tangent -> tangent break is an angle point: a PI at radius 0, which
    create_by_pi_method writes as two LINE segments.
    """
    from bimforge.author.alignment import Alignment
    A = Alignment(al["pob"], al["run"], name=al["name"])
    pts = [(A.pob["easting"], A.pob["northing"])]
    radii, breaks = [], [A.s_start]
    segs = A.segments
    for i, seg in enumerate(segs):
        breaks.append(seg["s1"])
        if seg["kind"] != "curve":
            if i + 1 < len(segs) and segs[i + 1]["kind"] != "curve":
                n1, e1, _ = A.point_az(seg["s1"])
                pts.append((e1, n1))
                radii.append(0.0)
            continue
        n0, e0, az0 = A.point_az(seg["s0"])
        t = seg["radius"] * math.tan(math.radians(seg["delta"]) / 2.0)
        pts.append((e0 + t * math.sin(math.radians(az0)),
                    n0 + t * math.cos(math.radians(az0))))
        radii.append(seg["radius"])
    pts.append((A.end_point[1], A.end_point[0]))
    return A, pts, radii, sorted(set(breaks))


def _horizontal(f, alapi, layout, A, mc) -> None:
    """Write the traverse's tangents and curves as horizontal segments.

    Survey azimuth (clockwise from grid north) -> model angle: counter-
    clockwise from model +x, which the IfcMapConversion turns by `mc[2]` from
    grid east. IFC's positive radius turns left; bimforge's sign is +1 right.
    """
    for seg in A.segments:
        if seg["kind"] == "tangent":
            n0, e0, az = seg["n0"], seg["e0"], seg["az"]
            r, kind = 0.0, "LINE"
        else:
            n0, e0, az = A.point_az(seg["s0"])
            r, kind = -seg["sign"] * seg["radius"] * M_PER_FT, "CIRCULARARC"
        x, y = to_model(e0, n0, mc)
        d = math.radians(90.0 - az) - mc[2]
        alapi.create_layout_segment(f, layout, f.create_entity(
            "IfcAlignmentHorizontalSegment",
            StartPoint=f.create_entity("IfcCartesianPoint", Coordinates=(x, y)),
            StartDirection=math.atan2(math.sin(d), math.cos(d)),
            StartRadiusOfCurvature=r, EndRadiusOfCurvature=r,
            SegmentLength=seg["length"] * M_PER_FT, PredefinedType=kind))


def _seg_end(sp) -> tuple[float, float]:
    """A horizontal segment's end, evaluated from its own design parameters."""
    x, y = sp.StartPoint.Coordinates
    d, L, r = sp.StartDirection, sp.SegmentLength, sp.StartRadiusOfCurvature
    if not r:
        return x + L * math.cos(d), y + L * math.sin(d)
    cx, cy = x - r * math.sin(d), y + r * math.cos(d)
    return cx + r * math.sin(d + L / r), cy - r * math.cos(d + L / r)


def _rename_referents(f, ifc_al) -> list[float]:
    """Rename the API's metric-stationed referents to US-feet stationing.

    Pset_Stationing values stay in metres (the file's length unit); only the
    human-readable Name changes. Returns the referents' stations in feet.
    """
    out = []
    for r in f.by_type("IfcReferent"):
        if not any(rel.RelatingObject == ifc_al for rel in (r.Nests or [])):
            continue
        m = re.search(r"(\d+)\+(\d+\.\d+)", r.Name or "")
        if not m:
            continue
        s_ft = (int(m.group(1)) * 1000 + float(m.group(2))) / M_PER_FT
        label = _fmt_sta(s_ft)
        new = re.sub(r"\d+\+\d+\.\d+", label, r.Name)
        r.Name = new if new != label else f"{label} (start station)"
        r.Description = "station in US survey feet; Pset_Stationing values are metres"
        out.append(s_ft)
    return out


def _gate(f, alapi, ifc_al, A, hp, radii, prof, mc, oh, tol_ft) -> list[str]:
    """Why this written alignment misses its traverse (empty: it matches)."""
    import ifcopenshell.geom
    problems = []
    if prof:
        segs = [s.DesignParameters
                for s in alapi.get_layout_segments(alapi.get_vertical_layout(ifc_al))]

        def z_at(d):
            for sp in segs:
                if sp.StartDistAlong - 1e-9 <= d <= sp.StartDistAlong + sp.HorizontalLength + 1e-9:
                    x = d - sp.StartDistAlong
                    g0 = sp.StartGradient
                    g1 = sp.EndGradient if sp.EndGradient is not None else g0
                    L_ = sp.HorizontalLength or 1e-12
                    return sp.StartHeight + g0 * x + (g1 - g0) * x * x / (2 * L_)
            return None
        worst = 0.0
        for p in prof["pvis"]:
            d = (min(p["station"], A.s_end) - A.s_start) * M_PER_FT
            z = z_at(d)
            if z is None:
                problems.append(f"no vertical segment at sta {p['station']}")
                continue
            el = z * mc[3] + oh
            if prof.get("vc_length_ft", 0.0) == 0.0 or p is prof["pvis"][0] or p is prof["pvis"][-1]:
                worst = max(worst, abs(el - p["elevation"]))
        span = sum(sp.HorizontalLength for sp in segs) / M_PER_FT
        _log(f"  gate {ifc_al.Name} vertical: {len(segs)} segments over {span:.3f} ft, "
             f"worst PVI miss {worst:.4f} ft")
        if worst > tol_ft:
            problems.append(f"PVI elevation miss {worst:.4f} ft")
        if abs(span - (A.s_end - A.s_start)) > tol_ft:
            problems.append(f"vertical spans {span:.3f} ft, horizontal "
                            f"{A.s_end - A.s_start:.3f} ft")
    # every angle point (radius-0 PI) must start a written segment; the start/end
    # check below cannot see a dropped interior PI. Compared on the segments'
    # StartPoint, not the tessellated curve, which the kernel densifies.
    starts = [s.DesignParameters.StartPoint.Coordinates
              for s in alapi.get_layout_segments(alapi.get_horizontal_layout(ifc_al))]
    for (x, y), r in zip(hp[1:-1], radii):
        if r == 0.0:
            miss = min(math.hypot(x - sx, y - sy) for sx, sy, *_ in starts) / M_PER_FT
            if miss > tol_ft:
                problems.append(f"angle point missing from the layout ({miss:.3f} ft)")
    hsegs = [s.DesignParameters for s in
             alapi.get_layout_segments(alapi.get_horizontal_layout(ifc_al))]
    for a, b in zip(hsegs, hsegs[1:]):
        gap = math.dist(_seg_end(a), b.StartPoint.Coordinates) / M_PER_FT
        if gap > tol_ft:
            problems.append(f"a {a.PredefinedType} segment ends {gap:.3f} ft "
                            "from the next one's start")
    shape = ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(),
                                           alapi.get_basis_curve(ifc_al))
    v = shape.verts
    xs, ys = v[0::3], v[1::3]
    ex, ey = to_model(A.end_point[1], A.end_point[0], mc)
    sx, sy = to_model(A.pob["easting"], A.pob["northing"], mc)
    d_end = min(math.hypot(x - ex, y - ey) for x, y in zip(xs, ys)) / M_PER_FT
    d_start = min(math.hypot(x - sx, y - sy) for x, y in zip(xs, ys)) / M_PER_FT
    _log(f"  gate {ifc_al.Name}: start miss {d_start:.4f} ft, end miss {d_end:.4f} ft")
    if max(d_end, d_start) > tol_ft:
        problems.append(f"start miss {d_start:.4f} ft, end miss {d_end:.4f} ft")
    return problems


def add_alignments(f, alignments: list[dict], tol_ft: float = 0.01,
                   referents: dict[str, list[float]] | None = None) -> list[dict]:
    """Lay each alignment block out as an IfcAlignment in the open file `f`.

    `referents` maps an alignment name to extra stations (feet) that get an
    IfcReferent. Returns one report per alignment. Raises AlignmentGateError,
    leaving `f` changed in memory, when the file cannot take an alignment or a
    written one misses its traverse.
    """
    import ifcopenshell.api
    import ifcopenshell.api.alignment as alapi
    import ifcopenshell.util.alignment

    if not f.schema.upper().startswith("IFC4X3"):
        raise AlignmentGateError(f"the file is {f.schema}; IfcAlignment needs IFC4X3")
    have = {a.Name for a in f.by_type("IfcAlignment")}
    clash = sorted(have & {al["name"] for al in alignments})
    if clash:
        raise AlignmentGateError(f"the file already holds IfcAlignment {clash}: "
                                 "rebuild it first, so a rerun never stacks a second copy")
    mc = map_conversion(f)
    oh = f.by_type("IfcMapConversion")[0].OrthogonalHeight or 0.0
    site = f.by_type("IfcSite")[0]
    referents = referents or {}

    made, reports = [], []
    for al in alignments:
        A, pis, radii, _breaks = traverse_pis(al)
        hp = [to_model(e, n, mc) for e, n in pis]
        vp = vlen = None
        prof = al.get("profile")
        if prof:
            pv = prof["pvis"]
            if abs(pv[0]["station"] - A.s_start) > tol_ft or abs(pv[-1]["station"] - A.s_end) > tol_ft:
                raise AlignmentGateError(
                    f"{al['name']}: profile spans {pv[0]['station']}..{pv[-1]['station']} "
                    f"but the horizontal spans {A.s_start}..{A.s_end:.4f} - it must match exactly")
            vp = [((p["station"] - A.s_start) * M_PER_FT, (p["elevation"] - oh) / mc[3]) for p in pv]
            vp[-1] = ((A.s_end - A.s_start) * M_PER_FT, vp[-1][1])
            vlen = [float(prof.get("vc_length_ft", 0.0)) * M_PER_FT] * (len(vp) - 2)
        vertical = bool(vp and vlen)       # as create_by_pi_method decided it
        ifc_al = alapi.create(f, al["name"], include_vertical=vertical)
        _horizontal(f, alapi, alapi.get_horizontal_layout(ifc_al), A, mc)
        if vertical:
            alapi.layout_vertical_alignment_by_pi_method(
                f, alapi.get_vertical_layout(ifc_al), vp, vlen)
        start = A.s_start * M_PER_FT
        alapi.add_stationing_referent(
            f, f"{al['name']} {ifcopenshell.util.alignment.station_as_string(f, start)}",
            ifc_al, 0.0, start)
        if prof and prof.get("desc"):
            vl = alapi.get_vertical_layout(ifc_al)
            if vl is not None:
                vl.Description = prof["desc"][:255]
        # spatial: aggregate under the site, not loose on the project
        for rel in list(ifc_al.Decomposes or []):
            if rel.RelatingObject.is_a("IfcProject"):
                ifcopenshell.api.run("aggregate.unassign_object", f, products=[ifc_al])
        if not ifc_al.Decomposes:
            ifcopenshell.api.run("aggregate.assign_object", f, products=[ifc_al],
                                 relating_object=site)
        ifc_al.Description = al.get("desc")
        fix_terminator(alapi, ifc_al)
        existing = _rename_referents(f, ifc_al)
        added = 0
        for s in sorted(set(referents.get(al["name"], []))):
            if any(abs(s - x) < 0.005 for x in existing):
                continue
            r = alapi.add_stationing_referent(
                f, name=_fmt_sta(s), alignment=ifc_al,
                distance_along=(s - A.s_start) * M_PER_FT, station=s * M_PER_FT)
            r.Description = "station in US survey feet; Pset_Stationing values are metres"
            added += 1
        made.append((ifc_al, A, hp, radii, prof))
        reports.append({"name": al["name"], "pis": len(pis), "radii_ft": radii,
                        "referents": len(existing) + added, "start": _fmt_sta(A.s_start),
                        "vertical": bool(prof)})
        _log(f"{al['name']}: {len(pis)} PIs, radii {radii} ft, "
             f"{len(existing)} layout referents + {added} added, start {_fmt_sta(A.s_start)}")

    failed = {}
    for ifc_al, A, hp, radii, prof in made:
        problems = _gate(f, alapi, ifc_al, A, hp, radii, prof, mc, oh, tol_ft)
        if problems:
            failed[ifc_al.Name] = problems
    if failed:
        raise AlignmentGateError(f"gate failed: {failed}")
    return reports
