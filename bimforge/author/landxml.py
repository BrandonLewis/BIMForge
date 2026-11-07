"""author.landxml: LandXML horizontal alignments as pob/run traverses.

Reads every <Alignment> in one or more LandXML 1.2 files (e.g. Civil 3D
exports) and returns the `pob` + `run` blocks that
`bimforge.author.alignment.Alignment` and `bimforge.bim.add_alignment` consume.
Each element of <CoordGeom> becomes one run entry:

    <Line>   -> {kind: tangent, bearing: "N dd-mm-ss.ss E", length}
    <Curve>  -> {kind: curve, turn: L|R, radius, delta: "d-m-s", length}

LandXML conventions: coordinates are written NORTHING first, and `dir` /
`dirStart` are decimal degrees CCW from grid east. `rot="ccw"` is a LEFT turn.
Spirals are refused, because the pob/run traverse has no spiral segment kind.

A traverse is tangent-continuous by construction, but some alignments carry an
angle point between elements. Each one is split at every kink above
`kink_deg` into pieces named "<name> [i/n]". Each piece keeps its own true
stationing, and the kink angles are recorded on every piece.

Files that repeat an alignment name with identical geometry are deduplicated
(the repeat is listed under `also_in`). A repeated name with different
geometry fails.

Gated: each traverse is rebuilt with `Alignment` and its computed end is
compared against the LandXML end point, and the gap between consecutive
LandXML elements is checked too. Either one above `tol_ft` fails, as do two
files naming different EPSG codes; `read_landxml` then raises `LandXMLGateError`
and returns nothing.
"""
from __future__ import annotations

import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


class LandXMLGateError(ValueError):
    """A traverse failed closure / gap, a name repeated with other geometry,
    or the files disagree on the EPSG code."""


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _ns(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _pt(el) -> tuple[float, float]:
    """LandXML '<N> <E>' text -> (northing, easting)."""
    n, e = (float(v) for v in el.text.split()[:2])
    return n, e


def _child(el, name):
    for c in el:
        if _ns(c.tag) == name:
            return c
    return None


def _dms(deg: float) -> str:
    deg = abs(deg)
    d = int(deg)
    m_f = (deg - d) * 60.0
    m = int(m_f)
    s = (m_f - m) * 60.0
    if s >= 59.99995:
        s, m = 0.0, m + 1
    if m == 60:
        m, d = 0, d + 1
    return f"{d}-{m:02d}-{s:08.5f}"


def _quadrant(az: float) -> str:
    """Azimuth (deg CW from north) -> 'N dd-mm-ss.sssss E' quadrant bearing."""
    az %= 360.0
    if az <= 90.0:
        return f"N {_dms(az)} E"
    if az <= 180.0:
        return f"S {_dms(180.0 - az)} E"
    if az <= 270.0:
        return f"S {_dms(az - 180.0)} W"
    return f"N {_dms(360.0 - az)} W"


def _az_from_ccw_east(d: float) -> float:
    return (90.0 - d) % 360.0


def _elements(al, path: Path) -> list[dict]:
    """<CoordGeom> children -> dicts with start/end points, directions, run entry."""
    out = []
    for el in _child(al, "CoordGeom"):
        kind = _ns(el.tag)
        start, end = _pt(_child(el, "Start")), _pt(_child(el, "End"))
        if el.get("length") is not None:
            length = float(el.get("length"))
        elif kind == "Line":               # optional in LandXML 1.2: the chord is the line
            length = math.dist(start, end)
        else:
            raise LandXMLGateError(f"{path.name}: {al.get('name')}: <{kind}> has no length")
        if kind == "Line":
            if el.get("dir") is not None:
                az = _az_from_ccw_east(float(el.get("dir")))
            else:
                az = math.degrees(math.atan2(end[1] - start[1], end[0] - start[0])) % 360.0
            out.append({"start": start, "end": end, "az0": az, "az1": az,
                        "run": {"kind": "tangent", "bearing": _quadrant(az),
                                "length": round(length, 6)}})
        elif kind == "Curve":
            left = (el.get("rot") or "").lower() == "ccw"
            out.append({"start": start, "end": end,
                        "az0": _az_from_ccw_east(float(el.get("dirStart"))),
                        "az1": _az_from_ccw_east(float(el.get("dirEnd"))),
                        "run": {"kind": "curve", "turn": "L" if left else "R",
                                "radius": round(float(el.get("radius")), 6),
                                "delta": _dms(float(el.get("delta"))),
                                "length": round(length, 6)}})
        else:
            raise LandXMLGateError(f"{path.name}: {al.get('name')}: unsupported "
                                   f"element <{kind}> (pob/run has no spirals)")
    return out


def _angle_diff(a: float, b: float) -> float:
    return abs((b - a + 180.0) % 360.0 - 180.0)


def convert(path: Path | str, tol_ft: float = 0.01, kink_deg: float = 0.01) -> list[dict]:
    """One LandXML file -> its alignment records (ungated; see `read_landxml`)."""
    from bimforge.author.alignment import Alignment

    path = Path(path)
    root = ET.parse(path).getroot()
    out = []
    for al in root.iter():
        if _ns(al.tag) != "Alignment" or _child(al, "CoordGeom") is None:
            continue
        els = _elements(al, path)
        gaps = [math.dist(els[i]["end"], els[i + 1]["start"]) for i in range(len(els) - 1)]
        kinks = [(i + 1, _angle_diff(els[i]["az1"], els[i + 1]["az0"]))
                 for i in range(len(els) - 1)]
        cuts = [i for i, k in kinks if k > kink_deg]
        bounds = [0] + cuts + [len(els)]
        pieces = list(zip(bounds, bounds[1:]))
        station = float(al.get("staStart"))
        for pi, (a, b) in enumerate(pieces):
            part = els[a:b]
            run = [e["run"] for e in part]
            pob = {"station": round(station, 6),
                   "northing": part[0]["start"][0], "easting": part[0]["start"][1]}
            if run[0]["kind"] == "curve":
                pob["azimuth"] = round(part[0]["az0"], 9)
            name = al.get("name") if len(pieces) == 1 else \
                f"{al.get('name')} [{pi + 1}/{len(pieces)}]"
            A = Alignment(pob, run, name=name)
            closure = math.dist(A.end_point, part[-1]["end"])
            piece_gaps = gaps[a:b - 1]
            rec = {"name": name, "source": path.name,
                   "desc": f"LandXML {path.name}; {len(run)} elements, "
                           f"Sta {A.s_start:.2f} to {A.s_end:.2f}",
                   "pob": pob, "run": run,
                   "landxml_end": {"northing": part[-1]["end"][0],
                                   "easting": part[-1]["end"][1]},
                   "closure_ft": round(closure, 6),
                   "max_gap_ft": round(max(piece_gaps, default=0.0), 6)}
            if cuts:
                rec["kinks_deg"] = [round(k, 4) for i, k in kinks if i in cuts]
                rec["desc"] += (f"; split at {len(cuts)} angle point(s) of "
                                f"{', '.join(f'{k:.3f}' for k in rec['kinks_deg'])} deg")
            out.append(rec)
            flag = "" if max(closure, rec["max_gap_ft"]) <= tol_ft else "  <-- FAIL"
            _log(f"{name:>14}: {len(run):2d} el, L={A.s_end - A.s_start:9.3f} ft, "
                 f"closure {closure:.5f} ft, max gap {rec['max_gap_ft']:.5f} ft{flag}")
            station = A.s_end
    return out


def _same_geometry(a: dict, b: dict) -> bool:
    return a["pob"] == b["pob"] and a["run"] == b["run"]


def read_landxml(paths, tol_ft: float = 0.01, kink_deg: float = 0.01) -> dict:
    """LandXML files -> {"epsg", "tol_ft", "alignments": [...]}, gated.

    Raises `LandXMLGateError` (nothing returned) on a closure or gap above
    `tol_ft`, a name repeated with different geometry, or conflicting EPSG codes.
    """
    aligns, epsgs, by_name, dupes, bad = [], set(), {}, [], []
    for p in sorted(Path(x) for x in paths):
        cs = next((e for e in ET.parse(p).getroot().iter()
                   if _ns(e.tag) == "CoordinateSystem"), None)
        if cs is not None and cs.get("epsgCode"):
            epsgs.add(int(cs.get("epsgCode")))
        for rec in convert(p, tol_ft, kink_deg):
            # gate every record, a deduplicated repeat included: two files can
            # carry the same traverse but state different end points
            if max(rec["closure_ft"], rec["max_gap_ft"]) > tol_ft:
                bad.append(f"{rec['name']} ({rec['source']})")
            prior = by_name.get(rec["name"])
            if prior is None:
                by_name[rec["name"]] = rec
                aligns.append(rec)
            elif _same_geometry(prior, rec):
                prior.setdefault("also_in", []).append(rec["source"])
                _log(f"  dedupe: {rec['name']} in {rec['source']} repeats "
                     f"{prior['source']} with identical geometry - kept once")
            else:
                dupes.append(rec["name"])
    if bad or dupes or len(epsgs) > 1:
        raise LandXMLGateError(f"closure/gap {bad}, duplicate names {dupes}, "
                               f"EPSG codes {sorted(epsgs)}")
    return {"epsg": epsgs.pop() if epsgs else None, "tol_ft": tol_ft,
            "alignments": aligns}
