"""Caltrans D90 culvert headwall: the headwall PANEL (a Retaining-Wall-Type-1
wall spanning the pipe) with a pipe opening, plus its footing box.

The panel is modelled as elevation (length x design-H) extruded by the Type-1
top thickness T, with the pipe cut as a void in the panel face. A pipe that
crosses the vertical wall square (skew_deg = 0) cuts a circle; at plan skew
angle theta it cuts a true ELLIPSE -- horizontal semi-axis (along the wall
length u) = r / cos(theta), vertical semi-axis = r -- so `elliptical_void`
generalizes the proven pipe_headwall._main_leg circular-void model and
`circular_void` is its skew=0 special case. The panel carries the Type-1 BATTER
on its earth face (-Y), its creek face (+Y) plumb, the same faces as the
wingwalls (#24), and its ends may be mitred into the wingwalls that meet it. A
voided panel carries length + net volume only (the gate's LxWxH invariant
applies to solid prisms only).
"""
from __future__ import annotations

import math

from bimforge.author.primitives import (CircleRing, Prism, SectionPrism,
                                        circle_poly)

#: A pipe skew approaching 90 deg makes the ellipse's horizontal semi-axis
#: r/cos(theta) diverge (the pipe runs parallel to the wall face -- not a real
#: culvert-headwall condition). Fail loud with a clear message rather than let
#: an enormous semi-axis silently trip the containment guard with a misleading
#: "does not fit" error, or emit a degenerate void.
_MAX_SKEW_DEG = 85.0


def _skew_widen(r: float, skew_deg: float) -> float:
    """Skew-widened horizontal semi-axis r/cos(skew), guarded near 90 deg."""
    if abs(skew_deg) >= _MAX_SKEW_DEG:
        raise ValueError(
            f"skew_deg {skew_deg} too extreme: |skew| must be < {_MAX_SKEW_DEG} "
            "deg (r/cos(skew) diverges as the pipe nears parallel to the wall)")
    return r / math.cos(math.radians(skew_deg))


def elliptical_void(dia: float, skew_deg: float, cu: float, cz: float,
                    n: int = 32) -> list:
    """CCW ellipse for a circular pipe of diameter `dia` cutting the vertical
    wall at plan skew `skew_deg` (0 = square): horizontal semi-axis r/cos(skew)
    along the wall length u, vertical semi-axis r, centred at (cu, cz) in the
    (u = along length, z = height) face."""
    r = dia / 2.0
    a = _skew_widen(r, skew_deg)
    # an equal-area polygon that REMEMBERS its curve (CircleRing): the panel's
    # net volume is the true ellipse's, and IFC/STEP draw the true arc
    ring = circle_poly(r, n)                          # equal-area circle at 0, 0
    out = CircleRing((cu + u * (a / r), cz + v) for u, v in ring)
    out.circle = (cu, cz, r) if abs(a - r) < 1e-12 else (cu, cz, a, r)
    return out


def headwall_stem(name: str, wall, length: float, pipe: dict,
                  skew_deg: float = 0.0,
                  end_slopes: tuple = (0.0, 0.0)) -> SectionPrism:
    """Headwall panel: length x H elevation, thickness T at the top battering
    by `wall.batter` toward the earth (-Y) with the creek face (y = T) plumb,
    elliptical pipe void widened by plan skew (skew_deg = 0 -> circular void).

    `end_slopes = (k0, k1)`: the ends cut on the vertical planes
    x = k0*y and x = length + k1*y (the mitres the wingwalls close on), as
    `SectionPrism` takes them."""
    H, T = wall.H, wall.T
    dia = float(pipe["dia_ft"])
    r = dia / 2.0
    a = _skew_widen(r, skew_deg)
    cu = float(pipe["center_ft"])
    cz = float(pipe.get("center_z_ft", r + 0.5))   # invert ~6in up
    # Full containment of the PLACED void: SectionPrism.area_sf subtracts the
    # whole ellipse regardless of where it lands, so a pipe poking through the
    # panel top/side/end would silently under-report net volume. Guard the
    # actual position, not just dia vs H (using the skew-widened semi-axis a
    # along u, and the unwidened r along z).
    # ... and a mitred end trims the creek face back by k*T: the void has to
    # clear the panel where it is shortest
    lo = max(0.0, end_slopes[0] * T)
    hi = length + min(0.0, end_slopes[1] * T)
    if not (lo + a <= cu <= hi - a and r <= cz <= H - r):
        raise ValueError(
            f"pipe (dia {dia}, center u={cu}, z={cz}, skew {skew_deg}) "
            f"does not fit inside the {length} x {H} ft headwall panel")
    face = [(0.0, 0.0), (length, 0.0), (length, H), (0.0, H)]
    void = elliptical_void(dia, skew_deg, cu, cz)
    return SectionPrism(name, face, T, y0=0.0, voids=[void],
                        ifc="IfcWall", layer="S-CONC",
                        batter=float(getattr(wall, "batter", 0.0) or 0.0),
                        end_slopes=end_slopes)


def headwall_footing(name: str, wall, length: float) -> Prism:
    """Footing box under the panel: length x W x F."""
    W, F = wall.W, wall.F
    return Prism(name, [(0.0, 0.0), (length, 0.0), (length, W), (0.0, W)],
                 z_bot=-F, z_top=0.0, dims_ft=(length, W),
                 ifc="IfcFooting", layer="S-CONC")
