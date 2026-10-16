"""Stroked-text + station annotation — a kernel annotation layer (#195).

The kernel could draw a station line into a DXF (`ops.station_line`) and write
CAD text (`emit_dxf.txt`), but it had no way to put stationing into an IFC as
first-class, instanced annotation. This module fills that gap with an
emitter-agnostic *instancing plan*:

* a **stamp** is a shape authored once in a local em/foot frame — the tick, and
  one per distinct glyph of a single-stroke (Hershey-style) font;
* an **instance** places a stamp at a model-frame point with a rotation.

`emit_ifc` turns each stamp into ONE `IfcRepresentationMap` and each instance
into ONE `IfcMappedItem`, so a label reuses its glyphs instead of duplicating
polylines — the whole reason the field `stationing_to_ifc` script used mapped
items.
`emit_dxf` (and `annotate_dxf`) draw the same resolved polylines, so the two
emitters cannot drift. Coordinates here are FEET; emitters scale to SI.

The v1 font covers what stationing needs — digits, ``+ - .`` and space. An
unsupported glyph fails loud (a silently-dropped character is a wrong label);
a broader A-Z set is a documented follow-up.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from bimforge.cad.formats import station as fmt_station

#: em-box glyph width and monospace advance (both in em; scaled by height).
GLYPH_W = 0.5
ADVANCE = 0.7

# Seven-segment skeleton points (em box: baseline y=0, cap y=1).
_TL, _TR = (0.0, 1.0), (GLYPH_W, 1.0)
_ML, _MR = (0.0, 0.5), (GLYPH_W, 0.5)
_BL, _BR = (0.0, 0.0), (GLYPH_W, 0.0)
_A, _B, _C = [_TL, _TR], [_TR, _MR], [_MR, _BR]      # top, upper-R, lower-R
_D, _E, _F = [_BL, _BR], [_BL, _ML], [_TL, _ML]      # bottom, lower-L, upper-L
_G = [_ML, _MR]                                      # middle

_DIGITS = {
    "0": [_A, _B, _C, _D, _E, _F],
    "1": [_B, _C],
    "2": [_A, _B, _G, _E, _D],
    "3": [_A, _B, _G, _C, _D],
    "4": [_F, _G, _B, _C],
    "5": [_A, _F, _G, _C, _D],
    "6": [_A, _F, _G, _E, _D, _C],
    "7": [_A, _B, _C],
    "8": [_A, _B, _C, _D, _E, _F, _G],
    "9": [_A, _B, _C, _D, _F, _G],
}
_PLUS = [[(0.05, 0.5), (0.45, 0.5)], [(0.25, 0.3), (0.25, 0.7)]]
_MINUS = [[(0.05, 0.5), (0.45, 0.5)]]
#: a period is a small closed square sitting on the baseline.
_DOT = [[(0.20, 0.0), (0.28, 0.0), (0.28, 0.08), (0.20, 0.08), (0.20, 0.0)]]

#: char -> list of polylines (each a list of (x, y) in the em box). Space is [].
FONT: dict[str, list[list[tuple[float, float]]]] = {
    **_DIGITS, "+": _PLUS, "-": _MINUS, ".": _DOT, " ": [],
}


def text_strokes(text: str, height: float = 1.0, *,
                 start: tuple[float, float] = (0.0, 0.0),
                 advance: float = ADVANCE) -> list[list[tuple[float, float]]]:
    """Lay a string out left-to-right as stroke polylines, baseline-left at
    `start`, cap height `height`. Monospace: every glyph advances `advance`
    ems. Raises on a glyph the font does not define (fail loud)."""
    sx, sy = start
    out: list[list[tuple[float, float]]] = []
    for i, ch in enumerate(text):
        polys = FONT.get(ch)
        if polys is None:
            raise ValueError(
                f"text_strokes: unsupported glyph {ch!r} — the v1 font covers "
                "digits, '+', '-', '.', and space")
        ox = sx + i * advance * height
        for poly in polys:
            out.append([(ox + px * height, sy + py * height) for px, py in poly])
    return out


def _glyph(ch: str, height: float) -> list[list[tuple[float, float]]]:
    """One glyph's strokes, scaled to `height`, at the local origin."""
    return [[(px * height, py * height) for px, py in poly] for poly in FONT[ch]]


@dataclass(frozen=True)
class Instance:
    """One placement of a stamp: origin (feet, model frame) + CCW rotation."""

    stamp: str
    x: float
    y: float
    rot_deg: float = 0.0


@dataclass
class AnnotationPlan:
    """An instancing plan: unique stamps + their placements."""

    stamps: dict[str, list[list[tuple[float, float]]]]
    instances: list[Instance]
    name: str = "Annotation"
    layer: str = "S-ANNO-TEXT"

    def polylines(self) -> list[list[tuple[float, float]]]:
        """Every instance resolved to world-frame (feet) polylines — the shared
        vocabulary a DXF emitter or a test reads (matches the IFC mapped items
        exactly, so the two renderings cannot drift)."""
        out: list[list[tuple[float, float]]] = []
        for inst in self.instances:
            th = math.radians(inst.rot_deg)
            c, s = math.cos(th), math.sin(th)
            for poly in self.stamps[inst.stamp]:
                out.append([(inst.x + c * px - s * py, inst.y + s * px + c * py)
                            for px, py in poly])
        return out


def _first_tick(s0: float, interval: float) -> float:
    """First multiple of `interval` at or after `s0`."""
    r = s0 % interval
    return s0 if r == 0.0 else s0 - r + interval


def station_annotation(align, s0: float, s1: float, *, interval: float = 100.0,
                       tick_len: float = 5.0, text_height: float = 3.0,
                       offset: float | None = None, side: str = "Rt",
                       decimals: int = 2, label: bool = True,
                       origin=None, name: str = "Stationing",
                       layer: str = "S-ANNO-TEXT") -> AnnotationPlan:
    """Station ticks (and, unless `label=False`, the station label beside each)
    along `align` between `s0` and `s1`.

    The tick is one shared stamp, rotated per station to lie perpendicular to
    the alignment (`rot_deg == -azimuth`, azimuth being the tangent bearing
    clockwise from north, so the local +x stamp lands on the offset line).
    Labels place one instance per glyph, upright, at `offset` feet to `side`.

    `origin` (a ProjectContext, or anything exposing ``.local(e, n)``) maps the
    alignment's survey coordinates into the model frame, exactly as the geometry
    builders do with ``origin=ctx``. Pass it for any georeferenced model, or the
    annotation lands at raw survey coordinates while the base-relative structure
    sits near zero — millions of feet apart (the georef-drift trap). With no
    origin the coordinates are used as authored (base already zero).
    """
    def _model(n, e):
        return origin.local(e, n) if origin is not None else (e, n)

    if interval <= 0.0:
        raise ValueError(
            f"station_annotation: interval must be > 0 (got {interval})")

    if offset is None:
        offset = tick_len / 2.0 + text_height * 0.6
    stamps: dict[str, list[list[tuple[float, float]]]] = {
        "tick": [[(-tick_len / 2.0, 0.0), (tick_len / 2.0, 0.0)]],
    }
    instances: list[Instance] = []
    s = _first_tick(s0, interval)
    while s <= s1 + 1e-6:
        n, e, az = align.point_az(s)
        tx, ty = _model(n, e)
        instances.append(Instance("tick", tx, ty, -az))
        if label:
            text = fmt_station(s, decimals)
            ln, le = align.station_offset(s, offset, side)
            lx, ly = _model(ln, le)
            for i, ch in enumerate(text):
                if ch not in stamps:
                    if ch not in FONT:
                        raise ValueError(
                            f"station label {text!r} has unsupported glyph "
                            f"{ch!r} — the v1 font covers digits, '+', '-', "
                            "'.', space")
                    stamps[ch] = _glyph(ch, text_height)
                instances.append(
                    Instance(ch, lx + i * ADVANCE * text_height, ly, 0.0))
        s += interval
    return AnnotationPlan(stamps, instances, name=name, layer=layer)


def annotate_dxf(msp, plan: AnnotationPlan, layer: str | None = None) -> int:
    """Draw an AnnotationPlan into a DXF modelspace as (E, N) = (x, y)
    polylines; returns the entity count. Shared by emit_dxf so a model's
    annotations render the same in CAD as in the IFC mapped items."""
    lyr = layer or plan.layer
    if lyr not in msp.doc.layers:
        msp.doc.layers.add(lyr)
    n = 0
    for poly in plan.polylines():
        msp.add_lwpolyline(poly, dxfattribs={"layer": lyr})
        n += 1
    return n
