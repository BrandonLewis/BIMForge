"""Draw a survey-control sheet: point markers + labels on NCS layers, a
control table, the basis note, and (grade=approximate) the not-for-layout
caveat — then a bundled title-block layout with a fitted viewport.

DXF stays in ground coordinates, x=Easting y=Northing (Work-repo rule)."""
from __future__ import annotations

import re
from pathlib import Path

from bimforge.sheets.model import NOT_FOR_LAYOUT_NOTE, SheetMeta

# Paper-relative annotation targets (inches on the plotted sheet). The old
# world-foot constants (r=2.0 ft markers, 3.0 ft text) plotted at ~0.10 in
# only near 1"=30'; at site scale (1"=1200') annotation rendered ~0.0025 in
# and the sheet read as blank (Work fix_annotation_scale.py evidence).
TEXT_PAPER_IN = 0.10          # == the old TEXT_H_FT = 3.0 at 1"=30'
MARKER_PAPER_IN = 2.0 / 30.0  # == the old MARKER_RADIUS_FT = 2.0 at 1"=30'

_LAYOUT_BAD = re.compile(r"[/\\:;?*|='\"<>,`]")


def _layout_name(title: str, default: str) -> str:
    """DXF-safe layout name: strip invalid chars, collapse whitespace, cap 60."""
    name = _LAYOUT_BAD.sub(" ", title or "")
    name = " ".join(name.split())[:60]
    return name or default


def _title_fields(meta: SheetMeta):
    """Build a `bimforge.cad.titleblock.TitleBlockFields` from `SheetMeta`.

    Maps the subset of `SheetMeta` that corresponds to title-block fields,
    then layers `meta.extra_fields` on top (dropping any keys that are not
    real `TitleBlockFields` fields, so callers can pass a superset safely).
    """
    from bimforge.cad.titleblock import TitleBlockFields

    base = dict(project=meta.bid_number or "", project_name=meta.project,
                sheet_title=meta.sheet_title, date=meta.date,
                scale=meta.scale_text, drafter=meta.drafter)
    base.update(meta.extra_fields)
    valid = set(TitleBlockFields.__dataclass_fields__)
    return TitleBlockFields(**{k: v for k, v in base.items() if k in valid})


def draw_control_sheet(points: list, meta: SheetMeta, out_path, *,
                       size: str = "ARCH_D", scale: float | None = None) -> Path:
    """Render a control-point sheet: markers+labels in modelspace, a control
    table and notes block, and a bundled title-block layout with fitted viewport.

    Args:
        points: `ControlPoint` list to plot (ground coords: x=Easting, y=Northing).
        meta: Sheet metadata — grade, CRS, basis note, title-block fields.
        out_path: Where to save the DXF.
        size: Sheet size (`"ARCH_D"` or `"11x17"`).
        scale: Paper-inch per world-foot (e.g. 1/30 for 1"=30'); None auto-fits.

    Returns:
        The saved DXF path.
    """
    from bimforge.cad.doc import new_doc
    from bimforge.cad.sheet import SHEET_WINDOWS, compose_sheet
    from bimforge.cad.viewport import bbox, resolve_scale

    doc = new_doc()
    if "C-ANNO-TEXT" not in doc.layers:
        doc.layers.add("C-ANNO-TEXT", color=2, lineweight=18)
    msp = doc.modelspace()
    xy = [(p.easting_ft, p.northing_ft) for p in points]
    extents = bbox(xy, margin=50.0)
    # SHEET_WINDOWS keys mirror titleblock.SHEET_SIZES (compose_sheet's
    # own check) - keep the two dicts in sync.
    if size not in SHEET_WINDOWS:
        raise ValueError(
            f"unknown sheet size {size!r} (use one of {list(SHEET_WINDOWS)})")
    eff = resolve_scale(extents, scale, size=SHEET_WINDOWS[size]["size"])
    text_h = TEXT_PAPER_IN / eff
    marker_r = MARKER_PAPER_IN / eff
    for p in points:
        x, y = p.easting_ft, p.northing_ft
        msp.add_circle((x, y), marker_r, dxfattribs={"layer": "V-CTRL-PNTS"})
        msp.add_line((x - marker_r, y), (x + marker_r, y),
                     dxfattribs={"layer": "V-CTRL-PNTS"})
        msp.add_line((x, y - marker_r), (x, y + marker_r),
                     dxfattribs={"layer": "V-CTRL-PNTS"})
        label = (f"{p.point_id}\\P{p.northing_ft:.2f} N\\P{p.easting_ft:.2f} E"
                 + (f"\\P{p.elevation_ft:.2f} EL" if p.elevation_ft is not None else ""))
        msp.add_mtext(label, dxfattribs={"layer": "C-ANNO-TEXT",
                                         "char_height": text_h}
                      ).set_location((x + 2 * marker_r, y))
    # control table + notes block, top-left of the point cloud
    ext = bbox(xy, margin=25.0)
    rows = ["POINT  NORTHING       EASTING        ELEV    DESCRIPTION"]
    for p in points:
        elev = f"{p.elevation_ft:<7.2f}" if p.elevation_ft is not None else f"{'-':<7}"
        rows.append(f"{p.point_id:<6} {p.northing_ft:<14.2f} {p.easting_ft:<14.2f} "
                    f"{elev} {p.description}")
    notes = [meta.basis_note] if meta.basis_note else []
    if meta.combined_factor:
        notes.append(f"GRID-TO-GROUND COMBINED FACTOR = {meta.combined_factor}")
    if meta.not_for_layout:
        notes.append(NOT_FOR_LAYOUT_NOTE)
    block = "\\P".join(rows + [""] + notes)
    msp.add_mtext(block, dxfattribs={"layer": "C-ANNO-TEXT",
                                     "char_height": text_h}
                  ).set_location((ext[0], ext[3]))

    compose_sheet(doc, size=size, fields=_title_fields(meta),
                  layout_name=_layout_name(meta.sheet_title, "CONTROL"),
                  extents=extents, scale=scale)
    out = Path(out_path)
    doc.saveas(out)
    return out


def qc_report(points: list, meta: SheetMeta) -> str:
    """Render the control sheet's QC report as Markdown (Pioneer's
    `project-control-report.md` pattern): grade/CRS/basis header, the point
    table, and a Checks section left for the agent to fill with actual ties/
    closure computations."""
    lines = [f"# QC — {meta.sheet_title} ({meta.project})", "",
             f"- Grade: **{meta.grade}**"
             + (" — " + NOT_FOR_LAYOUT_NOTE if meta.not_for_layout else ""),
             f"- CRS: {'EPSG:' + str(meta.crs_epsg) if meta.crs_epsg else 'local/unknown'}",
             f"- Basis: {meta.basis_note or '(none recorded)'}",
             f"- Combined factor: {meta.combined_factor or '-'}", "",
             "| Point | Northing | Easting | Elev | Description |",
             "|---|---|---|---|---|"]
    lines += [f"| {p.point_id} | {p.northing_ft:.2f} | {p.easting_ft:.2f} | "
              f"{p.elevation_ft if p.elevation_ft is not None else '-'} | "
              f"{p.description} |" for p in points]
    lines += ["", "## Checks", "",
              "_(record tie checks / closure / residuals here — see the "
              "Pioneer project-control-report.md pattern)_", ""]
    return "\n".join(lines)


def control_kml(points: list, meta: SheetMeta) -> str | None:
    """KML string for the points, or None if none of them are locatable.

    Prefers each point's own `latitude`/`longitude` when present, else
    projects `(northing_ft, easting_ft)` through `meta.crs_epsg` (State
    Plane). Returns None if no point can be located either way.
    """
    from bimforge.cad.kml import KMLDocument

    kml = KMLDocument(meta.sheet_title or "Control")
    folder = kml.folder("Control Points")
    if meta.crs_epsg:
        from bimforge.cad.geo import StatePlane
        sp = StatePlane(meta.crs_epsg)
    else:
        sp = None
    wrote = False
    for p in points:
        if p.longitude is not None and p.latitude is not None:
            lon, lat = p.longitude, p.latitude
        elif sp is not None:
            lon, lat = sp.to_lonlat_ne(p.northing_ft, p.easting_ft,
                                       combined_factor=meta.combined_factor)
        else:
            continue
        folder.point(p.point_id, (lon, lat), description=p.description)
        wrote = True
    return kml.to_string() if wrote else None
