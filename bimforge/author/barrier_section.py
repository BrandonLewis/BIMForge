"""Caltrans concrete-barrier cross-sections. A barrier is a CONSTANT (x, z)
profile swept along the alignment (author.sweep), z up, origin on the base.

Two flavours of profile are supported:
  - the parametric GENERATORS (`single_slope_profile`, `safety_shape_profile`)
    build median-barrier sections SYMMETRIC about the directrix, x positive to
    the left of travel;
  - an explicit `profile` row (e.g. the D90 Type 836 rail) may be ASYMMETRIC --
    there x is simply the transverse axis, running from the channel/back face
    (min x) to the traffic face (max x); the consumer decides handedness.

The section area (SF) is the concrete quantity per LF, checked against the
sheet's tabulated CF/LF (or an independent hand computation) by the caller.
"""
from __future__ import annotations

import math

from bimforge.author.alignment import poly_area


def single_slope_profile(height: float, base_width: float,
                         top_width: float) -> list[tuple[float, float]]:
    """Symmetric single-slope trapezoid (Type 60 / 842), origin on the
    directrix at base centre. CCW from the base-left corner."""
    bh, th = base_width / 2.0, top_width / 2.0
    return [(-bh, 0.0), (bh, 0.0), (th, height), (-th, height)]


def safety_shape_profile(height: float, base_width: float, top_width: float,
                         break_height: float,
                         break_width: float) -> list[tuple[float, float]]:
    """Symmetric compound (F-shape) barrier: a steep lower face from the base
    to the break, then a flatter upper face to the top. CCW from base-left."""
    bh, th, kh = base_width / 2.0, top_width / 2.0, break_width / 2.0
    return [(-bh, 0.0), (bh, 0.0), (kh, break_height), (th, height),
            (-th, height), (-kh, break_height)]


def type_732sw_profile(row: dict) -> list[tuple[float, float]]:
    """Caltrans Type 732SW compound section (barrier parapet + integral
    sidewalk) as a single closed (x, z) ring in FEET. x = 0 at the OUTSIDE
    (outboard) barrier face, x increasing inboard toward the gutter/traffic;
    z = 0 at top of deck at the pedestrian (inboard) face (x_ped, where
    `deck_z()` pivots), z up.

    Reads (feet unless noted):
      top_w_ft, top_h_ft   thickened top block width x height (1.0 x 1.1667)
      stem_w_ft            stem width (0.8333); 2" back relief = top_w - stem_w
      barrier_h_ft         barrier height above the sidewalk face (2.6667)
      sw_top_face_ft       top of sidewalk at the barrier face (0.7624)
      sw_thick_toe_ft      sidewalk thickness at the gutter/toe (0.6667 = 8")
      sw_width_ft          sidewalk width, barrier face -> toe (6.1667)
      deck_slope_pct       deck cross slope; 0 = flat barrier-slab/on-wall,
                           ~2 = bridge deck sloping toward the outboard edge.

    The bottom edge is top-of-deck: level at the pedestrian (inboard) face,
    tilting DOWN toward the outboard edge by deck_slope_pct on a bridge deck (the sheet's
    "Var" dimensions). Chamfers (1") and fillets (R=1/2") are omitted -- a
    documented, slightly non-conservative simplification of a few tenths of a
    percent, matching the R27 sharp-corner convention. The 6" embedment key
    into the deck is a deferred refinement (a small under-count).
    """
    top_w = float(row["top_w_ft"])
    top_h = float(row["top_h_ft"])
    stem_w = float(row["stem_w_ft"])
    barrier_h = float(row["barrier_h_ft"])
    sw_top_face = float(row["sw_top_face_ft"])
    sw_thick_toe = float(row["sw_thick_toe_ft"])
    sw_w = float(row["sw_width_ft"])
    slope = float(row.get("deck_slope_pct", 0.0)) / 100.0

    x_out = 0.0                       # outside face of the thickened top block
    x_stem_out = top_w - stem_w       # 2" back relief -> stem outside face
    x_ped = top_w                     # inboard plumb pedestrian face
    x_toe = x_ped + sw_w              # sidewalk toe

    z_top = sw_top_face + barrier_h   # top of barrier (== rail base_z)
    z_topblock_bot = z_top - top_h    # bottom of the thickened top block

    # top-of-deck z at plan x (level at the barrier face x_ped, dropping toward
    # the outboard edge as x decreases on a bridge deck):
    def deck_z(x: float) -> float:
        return slope * (x - x_ped)

    z_sw_top_toe = deck_z(x_toe) + sw_thick_toe   # sidewalk top at the toe

    return [
        (x_stem_out, deck_z(x_stem_out)),   # outboard base of the stem
        (x_stem_out, z_topblock_bot),       # up the stem outside face to relief
        (x_out, z_topblock_bot),            # 2" relief step out to the top block
        (x_out, z_top),                     # up to the top, outboard corner
        (x_ped, z_top),                     # across the top to the inboard corner
        (x_ped, sw_top_face),               # down the plumb ped face to sidewalk
        (x_toe, z_sw_top_toe),              # sidewalk top slopes to the toe
        (x_toe, deck_z(x_toe)),             # down the toe face to the deck
    ]


def _perimeter(ring: list[tuple[float, float]]) -> float:
    return sum(math.hypot(x2 - x1, z2 - z1)
               for (x1, z1), (x2, z2) in zip(ring, ring[1:] + ring[:1]))


class BarrierSection:
    """One barrier type's constant section, from the catalog table.

    `table` is `{"barriers": {type: {"shape", "variants": {height: row}}}}`.
    A row carries either an explicit `profile` (list of [x, z], from DXF
    extraction) or the parametric dims the shape's generator needs.
    """

    def __init__(self, barrier_type: str, height: str, table: dict) -> None:
        barriers = table.get("barriers") or {}
        if barrier_type not in barriers:
            raise ValueError(
                f"unknown barrier type {barrier_type!r} "
                f"(available: {sorted(barriers)})")
        spec = barriers[barrier_type]
        variants = spec.get("variants") or {}
        if str(height) not in variants:
            raise ValueError(
                f"{barrier_type}: unknown height variant {height!r} "
                f"(available: {sorted(variants)})")
        self.barrier_type = barrier_type
        self.height = str(height)
        self.shape = spec["shape"]
        self.row = variants[str(height)]
        self.outline = self._build_outline()
        self.area_sf = poly_area(self.outline)
        self.top_z = max(z for _x, z in self.outline)
        self.perimeter_ft = _perimeter(self.outline)

    def _build_outline(self) -> list[tuple[float, float]]:
        row = self.row
        if row.get("profile"):
            return [(float(x), float(z)) for x, z in row["profile"]]
        if self.shape == "single_slope":
            return single_slope_profile(
                float(row["height_ft"]), float(row["base_width_ft"]),
                float(row["top_width_ft"]))
        if self.shape == "safety_shape":
            return safety_shape_profile(
                float(row["height_ft"]), float(row["base_width_ft"]),
                float(row["top_width_ft"]), float(row["break_height_ft"]),
                float(row["break_width_ft"]))
        if self.shape == "type_732sw":
            return type_732sw_profile(row)
        raise ValueError(
            f"{self.barrier_type}: shape {self.shape!r} needs an explicit "
            f"profile or a parametric generator")

    def describe(self) -> str:
        return (f"{self.barrier_type} (H={self.top_z:.3f} ft, "
                f"{self.area_sf:.2f} SF/LF)")
