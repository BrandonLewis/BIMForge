"""Caltrans D85 Type E + D86 warped wingwall reinforcement callouts.

The sheets tabulate BAR CALLOUTS only (size/spacing/count), never a weight:
- Type E, keyed by wall height H (ft): `k` bars (size@spacing) + `L` bars
  (size, number each wall).
- Warped WALL, keyed by H then face slope `s:1`: FRONT/REAR face size@spacing
  plus the `D` dimensions.
- Warped stiffening BEAM, an H x L staircase reduced to per-L height
  breakpoints (each carries the `TOTAL n-#m` bar count and A/B beam dims).

Weight is computed downstream from a generated bar schedule (wingwall_rebar),
so this module is pure lookup with round-up on H (sheet: "for H not shown use
the next greater height").
"""
from __future__ import annotations

import re


def _round_up_key(group: dict, h: float) -> str:
    best = None
    for key in group:
        hk = float(key)
        if hk + 1e-9 >= h and (best is None or hk < float(best)):
            best = key
    if best is None:
        raise ValueError(f"wingwall H {h} exceeds the tabulated heights")
    return best


class WingwallSteel:
    def __init__(self, table: dict) -> None:
        self.table = table

    def type_e(self, h_ft: float) -> dict:
        g = self.table["type_e"]
        return g[_round_up_key(g, h_ft)]

    def warped_wall(self, h_ft: float, slope: str) -> dict:
        g = self.table["warped"]["wall"]
        row = g[_round_up_key(g, h_ft)]
        if slope not in row["slopes"]:
            raise ValueError(f"no warped-wall row for slope {slope!r}")
        return row["slopes"][slope]

    def beam_region(self, l_ft: float, h_ft: float) -> dict:
        by_l = self.table["warped"]["beam"]["by_l"]
        col = by_l[_round_up_key(by_l, l_ft)]           # round up on L
        for region in col:                              # first region whose h_max covers h
            if float(region["h_max"]) + 1e-9 >= h_ft:
                return region
        raise ValueError(f"beam H {h_ft} exceeds L={l_ft} column")


def parse_bar_total(spec: str) -> tuple[int, int]:
    """'6-#7' -> (count=6, bar_size=7). For the beam TOTAL callouts."""
    m = re.fullmatch(r"(\d+)\s*-\s*#(\d+)", str(spec).strip())
    if not m:
        raise ValueError(f"unparseable bar-total spec {spec!r}")
    return int(m.group(1)), int(m.group(2))


def parse_bar_size(spec: str) -> int:
    """'#6' -> 6 (a bare bar size with no spacing/count)."""
    m = re.fullmatch(r"#(\d+)", str(spec).strip())
    if not m:
        raise ValueError(f"unparseable bar-size spec {spec!r}")
    return int(m.group(1))
