"""Draw a layout sheet: the chord alignment on C-ROAD-CNTR with station ticks
and labels, structure locations by station/offset, and the grade caveat.

Offsets: looking up-station, RT = +90° clockwise from the chord direction."""
from __future__ import annotations

import math
from pathlib import Path

from bimforge.sheets.control import _layout_name, _title_fields
from bimforge.sheets.model import NOT_FOR_LAYOUT_NOTE, Alignment, SheetMeta

# Paper-relative annotation targets (see control.py — same calibration).
TICK_HALF_PAPER_IN = 10.0 / 30.0    # == the old TICK_HALF_FT = 10.0 at 1"=30'
TEXT_PAPER_IN = 0.10                # == the old TEXT_H_FT = 3.0 at 1"=30'
STRUCT_MARKER_PAPER_IN = 5.0 / 30.0  # == the old hardcoded r=5.0 at 1"=30'


def _chord_dir(a: Alignment, sta: float) -> tuple:
    """Unit (dN, dE) of the chord containing sta."""
    pts = a.points
    for p, q in zip(pts, pts[1:]):
        if p["station"] <= sta <= q["station"]:
            dn, de = q["northing"] - p["northing"], q["easting"] - p["easting"]
            length = math.hypot(dn, de) or 1.0
            return dn / length, de / length
    raise ValueError(f"station {sta} outside alignment")


def station_offset_to_ne(a: Alignment, sta: float, offset_ft: float,
                         side: str | None) -> tuple:
    """(northing, easting) of a station/offset pair on `a`.

    Looking up-station, RT is +90° clockwise from the chord direction:
    (dN, dE) -> (-dE, dN). LT is the mirror (-90°)."""
    n, e = a.at_station(sta)
    dn, de = _chord_dir(a, sta)
    rn, re_ = -de, dn
    sign = -1.0 if (side or "RT").upper().startswith("L") else 1.0
    return n + sign * rn * offset_ft, e + sign * re_ * offset_ft


def draw_layout_sheet(alignment: Alignment, meta: SheetMeta, out_path, *,
                      structures: list | None = None, tick_interval: float = 100.0,
                      size: str = "ARCH_D", scale: float | None = None) -> Path:
    """Render a layout sheet: the chord alignment on C-ROAD-CNTR, station ticks
    + labels every `tick_interval`, structure markers by station/offset/side,
    and a bundled title-block layout with fitted viewport.

    Args:
        alignment: Chord `Alignment` to plot (ground coords: x=Easting, y=Northing).
        meta: Sheet metadata — grade, CRS, basis note, title-block fields.
        out_path: Where to save the DXF.
        structures: Optional list of dicts with `structure_id`, `station`,
            `offset_ft`, `side` (RT/LT) to mark relative to the alignment.
        tick_interval: Station interval (ft) for centerline ticks + labels.
        size: Sheet size (`"ARCH_D"` or `"11x17"`).
        scale: Paper-inch per world-foot (e.g. 1/30 for 1"=30'); None auto-fits.

    Returns:
        The saved DXF path.
    """
    from bimforge.cad.doc import new_doc
    from bimforge.cad.formats import station as fmt_station
    from bimforge.cad.sheet import SHEET_WINDOWS, compose_sheet
    from bimforge.cad.viewport import bbox, resolve_scale

    doc = new_doc()
    if "C-ANNO-TEXT" not in doc.layers:
        doc.layers.add("C-ANNO-TEXT", color=2, lineweight=18)
    msp = doc.modelspace()
    path = [(p["easting"], p["northing"]) for p in alignment.points]
    ticks = []
    for sta, n, e in alignment.ticks(tick_interval):
        dn, de = _chord_dir(alignment, min(sta, alignment.points[-1]["station"]))
        ticks.append((sta, n, e, -de, dn))            # (sta, n, e, rn, re)
    structs = []
    for s in structures or []:
        side = (s.get("side") or "RT").upper()
        n, e = station_offset_to_ne(alignment, float(s["station"]),
                                    float(s.get("offset_ft", 0.0)), side)
        structs.append((s, side, n, e))
    xy = list(path) + [(e, n) for _s, n, e, _rn, _re in ticks] \
        + [(e, n) for _s, _side, n, e in structs]
    extents = bbox(xy, margin=50.0)
    # SHEET_WINDOWS keys mirror titleblock.SHEET_SIZES (compose_sheet's
    # own check) - keep the two dicts in sync.
    if size not in SHEET_WINDOWS:
        raise ValueError(
            f"unknown sheet size {size!r} (use one of {list(SHEET_WINDOWS)})")
    eff = resolve_scale(extents, scale, size=SHEET_WINDOWS[size]["size"])
    text_h = TEXT_PAPER_IN / eff
    tick_half = TICK_HALF_PAPER_IN / eff
    struct_r = STRUCT_MARKER_PAPER_IN / eff

    msp.add_lwpolyline(path, dxfattribs={"layer": "C-ROAD-CNTR"})
    for sta, n, e, rn, re_ in ticks:
        msp.add_line((e - re_ * tick_half, n - rn * tick_half),
                     (e + re_ * tick_half, n + rn * tick_half),
                     dxfattribs={"layer": "C-ANNO-TEXT"})
        msp.add_text(fmt_station(sta), dxfattribs={"layer": "C-ANNO-TEXT",
                                                   "height": text_h}
                     ).set_placement((e + re_ * (tick_half + text_h),
                                      n + rn * (tick_half + text_h)))
    for s, side, n, e in structs:
        msp.add_circle((e, n), struct_r, dxfattribs={"layer": "S-ANNO-SYMB"})
        msp.add_mtext(f"{s['structure_id']}\\P{fmt_station(float(s['station']))} "
                      f"{float(s.get('offset_ft', 0.0)):g}' {side}",
                      dxfattribs={"layer": "C-ANNO-TEXT", "char_height": text_h}
                      ).set_location((e + 1.6 * struct_r, n))  # == old +8.0 at r=5.0

    if meta.not_for_layout:
        ext = bbox(xy, margin=25.0)
        msp.add_mtext(NOT_FOR_LAYOUT_NOTE,
                      dxfattribs={"layer": "C-ANNO-TEXT", "char_height": text_h}
                      ).set_location((ext[0], ext[1]))

    compose_sheet(doc, size=size, fields=_title_fields(meta),
                  layout_name=_layout_name(meta.sheet_title, "LAYOUT"),
                  extents=extents, scale=scale)
    out = Path(out_path)
    doc.saveas(out)
    return out


def layout_qc(alignment: Alignment, meta: SheetMeta, structures: list | None = None) -> str:
    """Render the layout sheet's QC report as Markdown (control's `qc_report`
    pattern): grade/CRS/basis header, the alignment point table, the
    structure-marker table (if any), and a Checks section left for the agent
    to fill with actual verification against the plans."""
    lines = [f"# QC — {meta.sheet_title} ({meta.project})", "",
             f"- Grade: **{meta.grade}**"
             + (" — " + NOT_FOR_LAYOUT_NOTE if meta.not_for_layout else ""),
             f"- CRS: {'EPSG:' + str(meta.crs_epsg) if meta.crs_epsg else 'local/unknown'}",
             f"- Basis: {meta.basis_note or '(none recorded)'}", "",
             f"- Station span: {alignment.points[0]['station']:.2f} - "
             f"{alignment.points[-1]['station']:.2f}",
             f"- Point count: {len(alignment.points)}", "",
             "| Station | Northing | Easting |", "|---|---|---|"]
    lines += [f"| {p['station']:.2f} | {p['northing']:.2f} | {p['easting']:.2f} |"
              for p in alignment.points]
    if structures:
        lines += ["", "| Structure | Station | Offset | Side |", "|---|---|---|---|"]
        lines += [f"| {s['structure_id']} | {float(s['station']):.2f} | "
                  f"{float(s.get('offset_ft', 0.0)):g} | {(s.get('side') or 'RT').upper()} |"
                  for s in structures]
    lines += ["", "## Checks", "",
              "_(record tie checks / closure / residuals here — see the "
              "Pioneer project-control-report.md pattern)_", ""]
    return "\n".join(lines)


def layout_kml(alignment: Alignment, meta: SheetMeta, structures: list | None = None) -> str | None:
    """KML: the alignment as a linestring + structure points, or None if
    `meta.crs_epsg` is unset (the layout DXF is ground coordinates only —
    projection needs a known CRS, unlike `control_kml` which can fall back
    to each point's own lat/lon)."""
    if not meta.crs_epsg:
        return None
    from bimforge.cad.geo import StatePlane
    from bimforge.cad.kml import KMLDocument

    sp = StatePlane(meta.crs_epsg)
    kml = KMLDocument(meta.sheet_title or "Layout")
    folder = kml.folder("Alignment")
    coords = [sp.to_lonlat_ne(p["northing"], p["easting"],
                              combined_factor=meta.combined_factor)
              for p in alignment.points]
    folder.line(alignment.name or "alignment", coords)
    if structures:
        sfolder = kml.folder("Structures")
        for s in structures:
            side = (s.get("side") or "RT").upper()
            n, e = station_offset_to_ne(alignment, float(s["station"]),
                                        float(s.get("offset_ft", 0.0)), side)
            lon, lat = sp.to_lonlat_ne(n, e, combined_factor=meta.combined_factor)
            sfolder.point(s["structure_id"], (lon, lat))
    return kml.to_string()
