"""B11 barrier reinforcement: continuous LONGITUDINAL bars (one straight Bar
per bar, length = run length) and transverse TIES at a tabulated spacing
(length = section perimeter pulled in by cover, plus two hooks). Each bar's
LENGTH is a scalar; weight = length x plf (BAR_PROPS). Weight-only bars for
the LB pay quantity + the BBS -- 3D bent solids are out of scope, matching the
wingwall_rebar precedent.
"""
from __future__ import annotations

from bimforge.author.barrier_section import BarrierSection
from bimforge.author.primitives import RebarBuilder, bar_stations


def _straight_bar(rb: RebarBuilder, mark: str, host: str, length: float,
                  shape: str = "straight"):
    """A mark whose centreline is a straight run of `length` ft."""
    return rb.bar(mark, host, [(0.0, 0.0, 0.0), (0.0, 0.0, length)], shape)


def barrier_bars(section: "BarrierSection", row: dict, run_length: float,
                 cover_in: float = 2.0) -> list:
    """Longitudinal + tie bars for one barrier run of `run_length` ft."""
    bars_spec = row["bars"]
    out = []

    lng = bars_spec["longitudinal"]
    rl = RebarBuilder(size=int(lng["size"]), cover_in=cover_in, spacing_in=12.0)
    for _ in range(int(lng["count"])):
        _straight_bar(rl, "long", "barrier longitudinal", run_length)
    out += rl.bars

    tie = bars_spec["ties"]
    sp_in = float(tie["spacing_in"])
    rt = RebarBuilder(size=int(tie["size"]), cover_in=cover_in,
                      spacing_in=sp_in)
    # tie loop = section perimeter drawn in by cover on the 4 governing sides,
    # closed with two standard hooks (an explicit, documented approximation
    # for the LB quantity)
    # 8 = 4 governing sides x 2 (cover pulled off each side); safety_shape is
    # slightly under-inset, within the documented approximation
    tie_len = section.perimeter_ft - 8.0 * (cover_in / 12.0) + 2.0 * rt.hook
    if tie_len <= 0:
        raise ValueError(
            f"tie length {tie_len:.3f} ft <= 0 (section perimeter "
            f"{section.perimeter_ft:.3f} ft too small for {cover_in} in cover)")
    for _ in bar_stations(0.0, run_length, sp_in / 12.0):
        _straight_bar(rt, "tie", "barrier tie", tie_len, "U")
    out += rt.bars

    # optional haunch reinforcing (D90 Section H-H): continuous longitudinal
    # bars + transverse U-dowels tying the barrier haunch to the wall.
    haunch = bars_spec.get("haunch")
    if haunch:
        cont = haunch.get("cont")
        if cont:
            rc = RebarBuilder(size=int(cont["size"]), cover_in=cover_in,
                              spacing_in=12.0)
            for _ in range(int(cont["count"])):
                _straight_bar(rc, "haunch_cont", "barrier haunch continuous",
                              run_length)
            out += rc.bars
        dow = haunch.get("dowels")
        if dow:
            sp = float(dow["spacing_in"])
            rd = RebarBuilder(size=int(dow["size"]), cover_in=cover_in,
                              spacing_in=sp)
            dlen = float(dow.get("length_ft", 3.0))
            for _ in bar_stations(0.0, run_length, sp / 12.0):
                for _ in range(int(dow.get("count", 1))):
                    _straight_bar(rd, "haunch_dowel", "barrier haunch dowel",
                                  dlen, "U")
            out += rd.bars
    return out
