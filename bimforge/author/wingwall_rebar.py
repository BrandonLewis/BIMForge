"""Wingwall reinforcement bar-schedule generator (Caltrans D85 Type E + D86
warped). Each bar's LENGTH is a scalar -- its geometry run (from the family's
own wingwall parameters) plus RebarBuilder hook/lap allowances -- and is built
as a straight `Bar` so `Bar.length` equals that scalar exactly; weight =
length x plf (BAR_PROPS). 3D bent-bar solids are out of scope (spec s3); the
scalar length is exact for the LB pay quantity and the BBS.
"""
from __future__ import annotations

import math

from bimforge.author.box_section import parse_bar_spec
from bimforge.author.primitives import RebarBuilder, bar_stations
from bimforge.author.wingwall_steel import parse_bar_size, parse_bar_total


def _straight_bar(rb: RebarBuilder, mark: str, host: str, length: float,
                  shape: str = "straight"):
    """A mark whose centreline is a straight run of `length` ft (hooks/laps are
    already folded into `length`)."""
    return rb.bar(mark, host, [(0.0, 0.0, 0.0), (0.0, 0.0, length)], shape)


def type_e_bars(hw: dict, row: dict, cover_in: float = 2.0) -> list:
    """Type E stepped wingwall: `k` stem verticals (one per @spacing station
    per step, length = step height + footing embed + hook) and `L` horizontals
    (`L_each_wall` bars running the full wall length + 2 hooks)."""
    name = hw["name"]
    F = float(hw["foot_t_ft"])
    steps = hw["steps"]
    L_total = sum(float(s["length_ft"]) for s in steps)

    k_size, k_sp_in = parse_bar_spec(row["k_bar"])
    rk = RebarBuilder(size=k_size, cover_in=cover_in, spacing_in=k_sp_in)
    x = 0.0
    for i, st in enumerate(steps, start=1):
        li, h = float(st["length_ft"]), float(st["h_ft"])
        n = len(bar_stations(x, x + li, k_sp_in / 12.0))     # spacing ft
        for _ in range(n):
            _straight_bar(rk, "k", f"{name} k step {i}", h + F + rk.hook, "L")
        x += li

    L_size = parse_bar_size(row["L_bar"])   # L_bar has no spacing; count is explicit
    rL = RebarBuilder(size=L_size, cover_in=cover_in, spacing_in=12.0)
    for _ in range(int(row["L_each_wall"])):
        _straight_bar(rL, "L", f"{name} L", L_total + 2 * rL.hook, "straight")

    return rk.bars + rL.bars


def _slope_ratio(slope: str) -> float:
    """'1.5:1' -> 1.5 (horizontal run per 1 vertical)."""
    h, v = slope.split(":")
    return float(h) / float(v)


def warped_bars(hw: dict, wall_row: dict, beam_region: dict,
                cover_in: float = 2.0) -> list:
    """D86 warped wingwall: FRONT face verticals up the battered face
    (length = along-face warped height + embed + hook), REAR face verticals up
    the near-vertical face, and the stiffening-beam longitudinal bars."""
    name = hw["name"]
    L = float(hw["length_ft"])
    F = float(hw["foot_t_ft"])
    h_max = float(hw["wall_h_ft"]) + 0.5   # stem is 6" taller than culvert wall H at the culvert (matches R19 WarpedStem geometry)
    h_min = float(hw["min_h_ft"])
    s = _slope_ratio(hw["face_slope"])
    face_factor = math.sqrt(1.0 + s * s)

    def h_at(x: float) -> float:
        return h_max + (h_min - h_max) * (x / L)

    out = []
    for mark, spec, factor in (("front", wall_row["front"], face_factor),
                               ("rear", wall_row["rear"], 1.0)):
        size, sp_in = parse_bar_spec(spec)
        rb = RebarBuilder(size=size, cover_in=cover_in, spacing_in=sp_in)
        for x in bar_stations(0.0, L, sp_in / 12.0):
            _straight_bar(rb, mark, f"{name} {mark} face",
                          h_at(x) * factor + F + rb.hook, "L")
        out += rb.bars

    n_beam, beam_size = parse_bar_total(beam_region["total"])
    rbm = RebarBuilder(size=beam_size, cover_in=cover_in, spacing_in=12.0)
    for _ in range(n_beam):
        _straight_bar(rbm, "beam", f"{name} beam", L + 2 * rbm.hook, "straight")
    out += rbm.bars
    return out


def minor_bars(hw: dict, cover_in: float = 2.0) -> list:
    """Full-detailing minor bars common to Type E + warped: #4 x 5'-0 dowels
    @12 and #4 spacers @12 along the wall length (fixed lengths from the sheet
    notes)."""
    name = hw["name"]
    L = float(hw.get("length_ft") or sum(float(s["length_ft"]) for s in hw["steps"]))
    out = []
    rd = RebarBuilder(size=4, cover_in=cover_in, spacing_in=12.0)
    for _ in bar_stations(0.0, L, 1.0):
        _straight_bar(rd, "dowel", f"{name} dowel", 5.0, "straight")
    rs = RebarBuilder(size=4, cover_in=cover_in, spacing_in=12.0)
    for _ in bar_stations(0.0, L, 1.0):
        _straight_bar(rs, "spacer", f"{name} spacer", float(hw["stem_t_ft"]), "straight")
    return rd.bars + rs.bars


def wingwall_bars(hw: dict, steel, cover_in: float = 2.0) -> list:
    """All bars for a stepped/warped wingwall (WingwallSteel `steel`)."""
    kind = hw["kind"]
    if kind == "stepped":
        h_max = max(float(s["h_ft"]) for s in hw["steps"])
        bars = type_e_bars(hw, steel.type_e(h_max), cover_in)
    elif kind == "warped":
        h = float(hw["wall_h_ft"])
        wall = steel.warped_wall(h, hw["face_slope"])
        beam = steel.beam_region(float(hw["length_ft"]), h)
        bars = warped_bars(hw, wall, beam, cover_in)
    else:
        return []
    return bars + minor_bars(hw, cover_in)
