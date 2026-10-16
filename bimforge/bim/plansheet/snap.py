"""Snap proposed (agent-traced) vertices onto extracted vector geometry.

The agent reads the rendered sheet and proposes polylines in world feet;
every vertex is then snapped to the nearest extracted vector endpoint or
segment within a tolerance, so tracing has CAD precision, not eyeball
precision. Vertices with no snap target inside the tolerance keep their
proposed position and are flagged ``unsnapped`` — the caller decides whether
that blocks the takeoff (``est-bim measure`` exits nonzero unless
``--allow-unsnapped``).

Endpoint snaps are preferred over mid-segment projections: a projection onto
an edge is never farther than the edge's corner, so without the preference a
traced corner could slide down the edge instead of locking onto it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = ["SnapResult", "snap_point", "snap_polyline", "DEFAULT_TOL_FT"]

DEFAULT_TOL_FT = 0.15

WorldSegment = tuple[tuple[float, float], tuple[float, float]]


@dataclass(frozen=True)
class SnapResult:
    """One vertex's snap outcome (world feet)."""

    point: tuple[float, float]     # snapped position (proposed one if unsnapped)
    distance: float                # distance moved (or to nearest target if unsnapped)
    snapped: bool

    @property
    def unsnapped(self) -> bool:
        return not self.snapped


def _project(px: float, py: float, seg: WorldSegment) -> tuple[float, tuple[float, float]]:
    (ax, ay), (bx, by) = seg
    dx, dy = bx - ax, by - ay
    d2 = dx * dx + dy * dy
    if d2 <= 0.0:
        return math.hypot(px - ax, py - ay), (ax, ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / d2))
    qx, qy = ax + t * dx, ay + t * dy
    return math.hypot(px - qx, py - qy), (qx, qy)


def snap_point(point: tuple[float, float], segments: list[WorldSegment],
               tol: float = DEFAULT_TOL_FT) -> SnapResult:
    """Snap one world-feet point to the nearest endpoint or segment within tol."""
    px, py = point
    best_end: tuple[float, tuple[float, float]] | None = None
    best_proj: tuple[float, tuple[float, float]] | None = None
    for seg in segments:
        for ex, ey in seg:
            d = math.hypot(px - ex, py - ey)
            if best_end is None or d < best_end[0]:
                best_end = (d, (ex, ey))
        d, q = _project(px, py, seg)
        if best_proj is None or d < best_proj[0]:
            best_proj = (d, q)
    if best_end is not None and best_end[0] <= tol:
        return SnapResult(point=best_end[1], distance=best_end[0], snapped=True)
    if best_proj is not None and best_proj[0] <= tol:
        return SnapResult(point=best_proj[1], distance=best_proj[0], snapped=True)
    nearest = min(x[0] for x in (best_end, best_proj) if x is not None) \
        if (best_end or best_proj) else math.inf
    return SnapResult(point=(px, py), distance=nearest, snapped=False)


def snap_polyline(points: list[tuple[float, float]], segments: list[WorldSegment],
                  tol: float = DEFAULT_TOL_FT) -> list[SnapResult]:
    """Snap every vertex of a proposed polyline; order preserved."""
    return [snap_point((float(x), float(y)), segments, tol) for x, y in points]
