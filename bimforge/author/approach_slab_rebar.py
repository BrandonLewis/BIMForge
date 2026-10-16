"""Approach-slab reinforcement as scalar-length bars (headwall_bars pattern):
each mat/edge/dowel bar is a straight stick generated for weight + BBS, not
placed 3D geometry. Bar counts come from bar_stations over the slab dimension.

Mat-bar rule:
  * Longitudinal bars (bottom_main, top_long) run parallel to travel: they are
    distributed across the PERPENDICULAR roadway width (skew-invariant count)
    and each spans the slab length.
  * Transverse bars (bottom_transverse, top_tran) run parallel to BB/EB: they
    are distributed along the slab length and each spans the skewed width
    width/cos(skew).
"""
from __future__ import annotations

import math

from bimforge.author.box_section import parse_bar_spec
from bimforge.author.primitives import Bar, RebarBuilder, bar_stations

_COVER_IN = 2.0                       # top-mat clear cover (B9 sheets: 2")


def _straight(rb: RebarBuilder, mark: str, host: str, length: float) -> Bar:
    return rb.bar(mark, host, [(0.0, 0.0, 0.0), (0.0, 0.0, length)], "straight")


def _mat_bars(bars, spec: str, mark: str, host: str, run_ft: float,
              bar_len_ft: float) -> None:
    """One mat line: bars at the spec's spacing across `run_ft`, each
    `bar_len_ft` long."""
    size, spacing_in = parse_bar_spec(spec)
    rb = RebarBuilder(size=size, cover_in=_COVER_IN, spacing_in=spacing_in)
    n = len(bar_stations(0.0, run_ft, spacing_in / 12.0))
    for i in range(n):
        _straight(rb, mark, host, bar_len_ft)
    bars.extend(rb.bars)


def approach_slab_bars(sec, width_ft: float, skew_deg: float) -> list:
    """All slab mat + edge bars for one slab (excludes abutment dowels)."""
    bars: list = []
    length = sec.length_ft
    skew_w = width_ft / math.cos(math.radians(skew_deg))   # skewed transverse span
    cover_ft = _COVER_IN / 12.0
    long_len = length - 2 * cover_ft                        # parallel to lane lines
    tran_len = skew_w - 2 * cover_ft                        # parallel to BB/EB
    b = sec.bars
    # longitudinal bars run parallel to travel, spaced across the perpendicular
    # roadway width -> count from width_ft (skew-invariant); each spans the slab length
    _mat_bars(bars, b["bottom_main"], "bottom_main", "slab", width_ft, long_len)
    _mat_bars(bars, b["bottom_transverse"], "bottom_transverse", "slab", length, tran_len)
    _mat_bars(bars, b["top_mat"], "top_long", "slab", width_ft, long_len)
    _mat_bars(bars, b["top_mat"], "top_tran", "slab", length, tran_len)
    edge = b.get("edge_cont")
    if edge:
        rb = RebarBuilder(size=int(edge["size"]), cover_in=_COVER_IN,
                          spacing_in=12.0)  # spacing unused: count+length are explicit
        for _ in range(int(edge["count"])):
            _straight(rb, "edge_cont", "slab", tran_len)
        bars.extend(rb.bars)
    return bars


def approach_dowel_bars(sec, width_ft: float, skew_deg: float,
                        abutment_type: str) -> list:
    """Abutment-tie dowels along the seat, spec-selected by abutment type."""
    kind = "diaphragm" if str(abutment_type).lower().startswith("d") else "seat"
    d = sec.dowels
    spec = d.get(kind)
    if not spec:
        return []
    length = float(d.get(f"{kind}_len_ft", 2.0))
    size, spacing_in = parse_bar_spec(spec)
    skew_w = width_ft / math.cos(math.radians(skew_deg))
    rb = RebarBuilder(size=size, cover_in=_COVER_IN, spacing_in=spacing_in)
    for _ in bar_stations(0.0, skew_w, spacing_in / 12.0):
        _straight(rb, f"dowel_{kind}", "abut", length)
    return rb.bars
