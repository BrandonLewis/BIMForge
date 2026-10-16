"""Caltrans D80/D81 box-culvert cross-section as a function of span x height x
earth cover. Local 2D coords: origin at the bottom-left OUTER corner, x
transverse (right), z up. One haunched-octagon void per cell; concrete area =
outer minus the voids (haunches are the chamfered void corners, so they are
counted in).

The section thicknesses (roof / walls / invert) are earth-cover dependent -- the
D80/D81 tables give a distinct set for each MAXIMUM EARTH COVER column -- so they
live on the per-cover row alongside the a/b/e bar marks and the tabulated
concrete CF/LF and reinforcement LB/LF:

    single:                       # `double:` for D81
      "8x5":                      # span x height key (ft)
        covers:
          10: {wall_t_ft, top_slab_ft, bot_slab_ft, a, b, e,
               conc_cf_lf, lb_per_lf, interior_wall_t_ft?, haunch_ft?}
          20: {...}

`wall_t_ft` is the earth-loaded exterior wall (table T2). Multi-cell boxes carry
a thinner shared interior wall via `interior_wall_t_ft` (defaults to the exterior
thickness, so single boxes and uniform-wall tables are unchanged).
"""
from __future__ import annotations

import re

from bimforge.author.primitives import BAR_PROPS, poly_area  # size -> (dia_in, area_in2, plf)


def _parse_size_key(key: str) -> tuple[float, float]:
    s, h = key.lower().split("x")
    return float(s), float(h)


def parse_bar_spec(spec: str) -> tuple[int, float]:
    """'#5@8' / '#4 @ 12' -> (bar_size, spacing_in)."""
    m = re.fullmatch(r"#(\d+)\s*@\s*([\d.]+)", str(spec).strip())
    if not m:
        raise ValueError(f"unparseable bar spec {spec!r}")
    return int(m.group(1)), float(m.group(2))


class BoxCulvertSection:
    #: bar marks carried on each cover row (Caltrans a/b/e -- no i in the table)
    BAR_MARKS = ("a", "b", "e")

    def __init__(self, cells, span_ft, height_ft, cover_ft, table) -> None:
        self.cells = int(cells)
        self.S = float(span_ft)
        self.H = float(height_ft)
        group = {1: "single", 2: "double"}.get(self.cells)
        if group is None or group not in table:
            raise ValueError(f"no box-culvert table for {self.cells} cell(s)")
        self.S_key, row = self._lookup(table[group], self.S, self.H)
        self.cover_key, cov = self._cover_row(row["covers"], cover_ft)
        self.wall_t = cov["wall_t_ft"]           # exterior walls (table T2)
        # Interior (shared) walls of a multi-cell box are a thinner minimum
        # thickness than the earth-loaded exterior walls (Caltrans D81: 6" for
        # spans <= 8', 8" for spans >= 10'); default to the exterior thickness so
        # single boxes and older uniform-wall tables are unchanged.
        self.interior_wall = cov.get("interior_wall_t_ft", self.wall_t)
        self.top_slab = cov["top_slab_ft"]
        self.bot_slab = cov["bot_slab_ft"]
        self.haunch = cov.get("haunch_ft", 0.0)
        self.bars = {m: cov[m] for m in self.BAR_MARKS}
        self.lb_per_lf = cov["lb_per_lf"]
        self.conc_cf_lf = cov.get("conc_cf_lf")
        self.W_out = (self.cells * self.S + 2 * self.wall_t
                      + (self.cells - 1) * self.interior_wall)
        self.H_out = self.bot_slab + self.H + self.top_slab

    @staticmethod
    def _lookup(group: dict, S: float, H: float):
        """Smallest tabulated box whose span AND height both cover the request
        ('use next greater size box')."""
        best = None
        for key in group:
            s, h = _parse_size_key(key)
            if s + 1e-9 >= S and h + 1e-9 >= H:
                if best is None or (s, h) < best[0]:
                    best = ((s, h), key)
        if best is None:
            raise ValueError(f"box {S}x{H} exceeds the tabulated sizes")
        return best[1], group[best[1]]

    @staticmethod
    def _cover_row(covers: dict, cover_ft: float):
        """Smallest tabulated MAX-EARTH-COVER row that covers the request."""
        for c in sorted(float(k) for k in covers):
            if cover_ft <= c + 1e-9:
                key = int(c) if float(c).is_integer() else c
                return key, covers[key]
        raise ValueError(f"earth cover {cover_ft} exceeds the tabulated covers")

    def outer_profile(self) -> list[tuple[float, float]]:
        return [(0.0, 0.0), (self.W_out, 0.0),
                (self.W_out, self.H_out), (0.0, self.H_out)]

    def cell_voids(self) -> list[list[tuple[float, float]]]:
        h = self.haunch
        zb, zt = self.bot_slab, self.bot_slab + self.H
        rings = []
        for k in range(self.cells):
            xk = self.wall_t + k * (self.S + self.interior_wall)
            xr = xk + self.S
            rings.append([                    # CCW octagon, corners chamfered by h
                (xk + h, zb), (xr - h, zb),   # bottom
                (xr, zb + h), (xr, zt - h),   # right
                (xr - h, zt), (xk + h, zt),   # top
                (xk, zt - h), (xk, zb + h),   # left
            ])
        return rings

    def area_sf(self) -> float:
        return (poly_area(self.outer_profile())
                - sum(poly_area(v) for v in self.cell_voids()))

    #: Transverse bar path as a fraction of the OUTER perimeter, per cell.
    #: Calibrated once against all 168 rows of the real D80/D81 catalog
    #: (issue #150); `schedule_lb_per_lf` carries the derivation and the
    #: reason one constant covers single and double boxes alike.
    TRANSVERSE_PATH_FRACTION = 0.78

    def schedule_lb_per_lf(self) -> float:
        """Approximate LB/LF recomputed from the a/b/e schedule -- a
        transcription sanity check against the tabulated `lb_per_lf`.

        Transverse marks (a wraps the cell, e ties the corners) repeat ALONG
        the barrel at their spacing -> per barrel-foot, (12/spacing_in) bars
        each as long as the transverse path. Longitudinal marks (b run ALONG
        the barrel) contribute n_around bars each 1 ft long.

        The transverse path is `TRANSVERSE_PATH_FRACTION x outer perimeter x
        cells`. It used to be the CELL perimeter x cells, which ran double
        boxes ~22% light against the real catalog (mean -22.1%, worst
        -45.8%): a double box's outer perimeter is far more than twice one
        cell's, so the proxy degraded exactly where the section got bigger.
        Solving each row for the path its tabulated LB/LF implies gives
        outer-perimeter multipliers of 0.796 (single) and 1.608 (double) -- a
        ratio of 2.02, i.e. ONE constant of ~0.8 PER CELL covers both. That
        is why this is a single calibrated fraction rather than a per-group
        fudge factor; the physical reading is that the bars follow a
        mid-depth path lying between the cell and outer perimeters.

        Accuracy over the whole catalog: mean +0.1% (unbiased), sd 12.2%,
        worst row 34.4%.

        The residual is IRREDUCIBLE from this input, which is the thing to
        understand before trusting it: every geometric proxy tried (cell
        perimeter, outer perimeter, their sum, outer + interior wall,
        concrete area) leaves a 19-24% coefficient of variation. The a/b/e
        marks do not determine the tabulated weight -- the sheets' LB/LF also
        carries the `i` bars absent from the main table, plus laps, hooks and
        bends. So this catches a decimal slip or a doubled figure; it cannot
        catch a few-percent typo, and over these inputs no tolerance could.
        The exact ground truth on this section is `area_sf()` against the
        tabulated `conc_cf_lf`."""
        path_ft = (self.TRANSVERSE_PATH_FRACTION
                   * 2.0 * (self.W_out + self.H_out) * self.cells)
        lb = 0.0
        for mark in ("a", "e"):
            size, sp_in = parse_bar_spec(self.bars[mark])
            lb += (12.0 / sp_in) * path_ft * BAR_PROPS[size][2]
        size, sp_in = parse_bar_spec(self.bars["b"])
        n_around = max(1.0, 2.0 * (self.W_out + self.H_out) / (sp_in / 12.0))
        lb += n_around * 1.0 * BAR_PROPS[size][2]
        return lb
