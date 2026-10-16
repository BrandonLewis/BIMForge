"""Kernel-level drawing/section operations (spec §4 'kernel ops').

* station_line — draw an author Alignment into a DXF modelspace as a
  polyline with station ticks and labels (shared vocabulary with
  `est-sheets layout`, which draws CHORD alignments; this one is exact).
* wingwall_section — a WallSection consumer producing the (footing, stem)
  prisms for one station range, for scripts that want wall slices without
  the standard-plan family's full run machinery.
"""
from __future__ import annotations

from bimforge.cad.formats import station as fmt_station


def station_line(msp, align, s0: float, s1: float, *, step: float = 2.0,
                 tick_interval: float = 100.0, tick_len: float = 5.0,
                 layer: str = "C-ROAD-CNTR", text_h: float = 3.0) -> int:
    """Draw the alignment centreline s0..s1 with ticks+labels; returns the
    entity count drawn. Coordinates land as (E, N) = (x, y), the DXF rule."""
    if layer not in msp.doc.layers:
        msp.doc.layers.add(layer)
    pts = [(e, n) for n, e, _s in align.densify(s0, s1, step)]
    msp.add_lwpolyline(pts, dxfattribs={"layer": layer})
    drawn = 1
    s = s0 - (s0 % tick_interval) + tick_interval if s0 % tick_interval else s0
    while s <= s1 + 1e-6:
        (nl, el_) = align.station_offset(s, tick_len / 2.0, "Lt")
        (nr, er) = align.station_offset(s, tick_len / 2.0, "Rt")
        msp.add_line((el_, nl), (er, nr), dxfattribs={"layer": layer})
        t = msp.add_text(fmt_station(s), height=text_h,
                         dxfattribs={"layer": layer})
        t.set_placement((er, nr))
        drawn += 2
        s += tick_interval
    return drawn


def wingwall_section(align, tables, wall_type: int, H: float,
                     s0: float, s1: float, front: str,
                     ft_top: float):
    """(footing Prism, stem Prism) for one wall slice at design H."""
    from bimforge.author.alignment import WallSection
    from bimforge.author.primitives import Prism
    ws = WallSection(wall_type, H, tables)
    back = "Rt" if str(front).upper().startswith("L") else "Lt"
    foot = [align.station_offset(s0, ws.C, front),
            align.station_offset(s1, ws.C, front),
            align.station_offset(s1, ws.B, back),
            align.station_offset(s0, ws.B, back)]
    th = ws.T + ws.batter * H / 2.0
    stem = [align.station_offset(s0, 0.0, front),
            align.station_offset(s1, 0.0, front),
            align.station_offset(s1, th, back),
            align.station_offset(s0, th, back)]
    return (Prism(f"wingwall footing {fmt_station(s0)}", foot,
                  ft_top - ws.F, ft_top, dims_ft=(s1 - s0, ws.W),
                  ifc="IfcFooting"),
            Prism(f"wingwall stem {fmt_station(s0)}", stem, ft_top, ft_top + H,
                  dims_ft=(s1 - s0, th), ifc="IfcWall"))
