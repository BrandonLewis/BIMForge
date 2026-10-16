"""B11-51 tubular-handrail HSS members: nominal sections + hollow keyhole
rings for true-hollow sweeps, and the B11-51 rail-set config.

WEIGHT NOTE (R27, per estimator direction 2026-08-25): reported steel weight is DERIVED
from the true-hollow swept/extruded volume x 490 pcf (the ps_steel paycode
path), NOT from an AISC table. The section is modelled with SHARP corners at
the NOMINAL wall thickness -- unlike AISC's 0.93x design wall plus rounded
corners -- so the volume-derived weight reads ~a few percent OVER the AISC
HSS nominal weight. That is intentional and acceptable for estimating; do
NOT "correct" it by substituting table weights without also changing the
geometry (the two must stay one number, the spillway-pilot QC discipline).
"""
from __future__ import annotations

from dataclasses import dataclass

#: nominal HSS -> (width_b_in, depth_d_in, wall_t_in). Only B11-51's members.
HSS: dict[str, tuple[float, float, float]] = {
    "HSS3x2x3/16": (3.0, 2.0, 0.1875),
    "HSS2x2x3/16": (2.0, 2.0, 0.1875),
}


def rect_ring(b_ft: float, d_ft: float, c1: float, c2: float) -> list:
    """CCW rectangle, `b_ft` across axis-1, `d_ft` across axis-2, centred at
    (c1, c2). Axes are the caller's plane: (x, z) for a rail profile, (x, y)
    for a post plan."""
    hb, hd = b_ft / 2.0, d_ft / 2.0
    return [(c1 - hb, c2 - hd), (c1 + hb, c2 - hd),
            (c1 + hb, c2 + hd), (c1 - hb, c2 + hd)]


def hollow_ring(size: str, c1: float = 0.0, c2: float = 0.0) -> tuple:
    """(outer_ring, [inner_ring]) in FEET for `size`, centred at (c1, c2).
    The inner ring is the wall void, ready to pass as a keyhole `voids`."""
    if size not in HSS:
        raise KeyError(f"unknown HSS {size!r} (have {sorted(HSS)})")
    b, d, t = (v / 12.0 for v in HSS[size])
    return rect_ring(b, d, c1, c2), [rect_ring(b - 2 * t, d - 2 * t, c1, c2)]


def area_sf(size: str) -> float:
    """Net cross-section area (sf) of the hollow section."""
    if size not in HSS:
        raise KeyError(f"unknown HSS {size!r} (have {sorted(HSS)})")
    b, d, t = HSS[size]
    return (b * d - (b - 2 * t) * (d - 2 * t)) / 144.0


@dataclass(frozen=True)
class Rail:
    size: str
    z_center_ft: float   # rail CENTERLINE height above top of barrier/curb
    is_payment: bool     # the continuous top rail bears the LF pay line


@dataclass(frozen=True)
class RailConfig:
    rails: tuple
    post_size: str
    #: top-rail CENTERLINE height above barrier top = the post-top elevation
    #: (posts terminate at the top rail). This is a centerline, NOT top-of-
    #: steel: the modelled top of the top rail sits half its depth higher
    #: (e.g. +1" for an HSS3x2). Both here and in z_center_ft the B11-51 1'-4"
    #: dimension is read as the top-rail centerline, so geometry (posts,
    #: rails) and quantities stay one consistent number.
    height_ft: float


#: Caltrans B11-51: two rails (top HSS3x2 centerline @ 16", lower HSS2x2 @ 8")
#: + HSS2x2 posts; top-rail centerline / post top at 1'-4".
CONFIG_B11_51 = RailConfig(
    rails=(Rail("HSS3x2x3/16", 16.0 / 12.0, True),
           Rail("HSS2x2x3/16", 8.0 / 12.0, False)),
    post_size="HSS2x2x3/16",
    height_ft=16.0 / 12.0,
)
