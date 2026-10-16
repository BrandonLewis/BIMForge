"""Frame an existing takeoff-mapped DXF (measure-plans output or hand-drawn)
into a submittable sheet: verify its layers against the layer map, add the bundled
title-block layout + fitted viewport, save AS A NEW FILE. The source DXF's
modelspace is never modified — it remains the dxf2bim/BIM source of truth.

The grade caveat (when `meta.not_for_layout`) is stamped into the *paperspace*
layout, in paper-inch coordinates near the border — not into modelspace. That
keeps the output's modelspace byte-for-byte the same geometry as the source
(so downstream dxf2bim/BIM consumers see exactly what the takeoff produced),
while the printed sheet still carries the caveat where a reviewer will see it."""
from __future__ import annotations

from pathlib import Path

import yaml

from bimforge.sheets.control import _layout_name, _title_fields
from bimforge.sheets.model import NOT_FOR_LAYOUT_NOTE, SheetMeta

_ANNO_LAYERS = {"C-ANNO-TEXT", "S-ANNO-SYMB", "DEFPOINTS", "0"}

_CAVEAT_CHAR_HEIGHT = 0.2

#: Paper-inch margin inside the sheet's border window, per `dxf_length_unit`
#: — how far the caveat MTEXT sits from the window's lower-left corner.
_CAVEAT_INSET = (0.5, 0.6)

#: Extents margin (in the map's world units) around the swept geometry,
#: keyed by `dxf_length_unit`; falls back to the feet value if unknown.
_MARGIN_BY_UNIT = {"mm": 500.0, "cm": 50.0, "m": 5.0, "ft": 15.0, "in": 180.0}


def frame_structure_sheet(dxf_path, layer_map_path, meta: SheetMeta, out_path, *,
                          size: str = "ARCH_D", scale: float | None = None) -> Path:
    """Frame a takeoff DXF into a submittable sheet, without touching it.

    Reads `dxf_path`, verifies every layer used in its modelspace is either
    mapped in `layer_map_path` or a recognized annotation layer, then saves a
    *new* file at `out_path` carrying the original modelspace geometry plus a
    bundled title-block paperspace layout with a fitted viewport. The source file
    is only read, never re-saved.

    Args:
        dxf_path: Path to the takeoff DXF (measure-plans output or hand-drawn).
        layer_map_path: Path to the layer-map YAML (measure-plans schema) used
            to validate that every drawn layer is BIM-mapped.
        meta: Sheet metadata — grade, CRS, basis note, title-block fields.
        out_path: Where to save the framed sheet DXF.
        size: Sheet size (`"ARCH_D"` or `"11x17"`).
        scale: Paper-inch per world-foot (e.g. 1/30 for 1"=30'); None auto-fits.

    Returns:
        The saved DXF path.

    Raises:
        ValueError: If modelspace uses a layer that is neither in the layer
            map nor a recognized annotation layer, or if modelspace has no
            measurable geometry.
    """
    import ezdxf
    from bimforge.cad.layers import add_layers
    from bimforge.cad.sheet import SHEET_WINDOWS, compose_sheet
    from bimforge.cad.viewport import bbox

    lm = yaml.safe_load(Path(layer_map_path).read_text(encoding="utf-8")) or {}
    mapped = {k.upper() for k in (lm.get("layers") or {})}
    unit = ((lm.get("units") or {}).get("dxf_length_unit") or "mm").lower()
    margin = _MARGIN_BY_UNIT.get(unit, 15.0)

    doc = ezdxf.readfile(str(dxf_path))
    if "C-ANNO-TEXT" not in doc.layers:
        # defensive: also created by add_layers below; kept so a future
        # add_layers change can't silently drop it
        doc.layers.add("C-ANNO-TEXT", color=2, lineweight=18)
    msp = doc.modelspace()
    used = {e.dxf.layer.upper() for e in msp}
    unmapped = sorted(used - mapped - _ANNO_LAYERS)
    if unmapped:
        raise ValueError(
            f"layers {unmapped} are not in the layer map — the sheet would not "
            "be BIM-ready; map them (or move annotation to C-ANNO-TEXT/S-ANNO-SYMB)")

    xy = []
    for e in msp:
        if e.dxftype() == "LWPOLYLINE":
            xy.extend((p[0], p[1]) for p in e.get_points())
        elif e.dxftype() == "LINE":
            xy.extend([(e.dxf.start[0], e.dxf.start[1]), (e.dxf.end[0], e.dxf.end[1])])
        elif e.dxftype() == "INSERT":
            xy.append((e.dxf.insert[0], e.dxf.insert[1]))
        elif e.dxftype() == "POLYLINE":
            xy.extend((v.dxf.location[0], v.dxf.location[1]) for v in e.vertices)
        elif e.dxftype() == "HATCH":
            for path in e.paths:
                verts = getattr(path, "vertices", None)
                if verts:
                    xy.extend((v[0], v[1]) for v in verts)
    if not xy:
        raise ValueError("takeoff DXF has no measurable modelspace geometry")

    add_layers(doc)  # standard annotation/title layers for the frame (idempotent)

    lay = compose_sheet(doc, size=size, fields=_title_fields(meta),
                        layout_name=_layout_name(meta.sheet_title, "STRUCTURE"),
                        extents=bbox(xy, margin=margin), scale=scale)

    if meta.not_for_layout:
        # Paperspace, not modelspace: the caveat is a sheet annotation, not
        # takeoff geometry — it must not perturb the BIM source of truth.
        # Placed from the sheet's border window (not a fixed page offset) so
        # it lands inside the border, in the printed area, not the trim strip.
        win = SHEET_WINDOWS[size]
        cx, cy = win["center"]
        w, h = win["size"]
        dx, dy = _CAVEAT_INSET
        caveat_pos = (cx - w / 2 + dx, cy - h / 2 + dy)
        lay.add_mtext(NOT_FOR_LAYOUT_NOTE,
                      dxfattribs={"layer": "C-ANNO-TEXT",
                                  "char_height": _CAVEAT_CHAR_HEIGHT,
                                  "color": 7}
                      ).set_location(caveat_pos)

    out = Path(out_path)
    doc.saveas(out)
    return out


def structure_qc(dxf_path, meta: SheetMeta) -> str:
    """Render the structure sheet's QC report as Markdown (control's
    `qc_report` pattern): grade/CRS/basis header, the source-DXF filename
    with its layer/entity summary, and a Checks section left for the agent
    to fill with actual BIM-readiness verification.

    Reads `dxf_path` itself (rather than taking a `used_layers` argument) so
    it doesn't need `frame_structure_sheet`'s already-frozen signature to
    hand back internal state — `dxf_path` should be the source takeoff DXF
    (the one framed into the sheet, not the framed sheet itself).
    """
    import ezdxf

    doc = ezdxf.readfile(str(dxf_path))
    msp = doc.modelspace()
    layers = sorted({e.dxf.layer for e in msp})
    entity_count = sum(1 for _ in msp)
    lines = [f"# QC — {meta.sheet_title} ({meta.project})", "",
             f"- Grade: **{meta.grade}**"
             + (" — " + NOT_FOR_LAYOUT_NOTE if meta.not_for_layout else ""),
             f"- CRS: {'EPSG:' + str(meta.crs_epsg) if meta.crs_epsg else 'local/unknown'}",
             f"- Basis: {meta.basis_note or '(none recorded)'}", "",
             f"- Source DXF: `{Path(dxf_path).name}`",
             f"- Layers used: {', '.join(layers) if layers else '(none)'}",
             f"- Entity count: {entity_count}", "",
             "## Checks", "",
             "_(record checks here — layers vs takeoff map, measure/unit "
             "sanity vs the bid frame, dims spot-checked against the "
             "plans)_", ""]
    return "\n".join(lines)
