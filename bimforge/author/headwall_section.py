"""Caltrans D89 pipe-headwall cross-section: a cantilever retaining wall (stem
thickness T on a spread footing W = C + B, thickness F) tabulated by design H.

The sheet tabulates the concrete for a stem 1'-0" taller than the design-H limit
(note: "Quantities include 1'-0" extension above the design H limit"), so the
concrete stem height is H + 1.0 and the perpendicular section area is
T*(H+1) + W*F -- this equals the tabulated conc_cy_lf * 27.
"""
from __future__ import annotations

from bimforge.author.box_section import parse_bar_spec  # noqa: F401 (re-exported)


def _parse_h_key(key) -> float:
    """'4-8' -> 4.6667 ft; '5' -> 5.0."""
    s = str(key).strip()
    if "-" in s:
        f, i = s.split("-")
        return float(f) + float(i) / 12.0
    return float(s)


class HeadwallSection:
    BAR_MARKS = ("c", "d")

    def __init__(self, design_h_ft, table) -> None:
        self.design_h = float(design_h_ft)
        group = table["headwall"]
        self.H_key, row = self._lookup(group, self.design_h)
        self.H = _parse_h_key(self.H_key)
        self.T = row["T_ft"]
        self.W = row["W_ft"]
        self.C = row["C_ft"]
        self.B = row["B_ft"]
        self.F = row["F_ft"]
        self.bars = {m: row[m] for m in self.BAR_MARKS}
        self.conc_cy_lf = row["conc_cy_lf"]
        self.reinf_lb_lf = row["reinf_lb_lf"]

    @staticmethod
    def _lookup(group: dict, h: float):
        """Smallest tabulated design H that covers the request (round up)."""
        best = None
        for key in group:
            hk = _parse_h_key(key)
            if hk + 1e-9 >= h and (best is None or hk < best[0]):
                best = (hk, key)
        if best is None:
            raise ValueError(f"design H {h} exceeds the tabulated headwall sizes")
        return best[1], group[best[1]]

    @property
    def stem_height(self) -> float:
        return self.H + 1.0                     # 1'-0" extension above design H

    @property
    def section_area_sf(self) -> float:
        return self.T * self.stem_height + self.W * self.F
