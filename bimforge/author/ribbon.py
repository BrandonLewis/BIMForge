"""Draped ribbon-mesh surface along a polyline / alignment (#192).

The `ribbon()` helper every corridor / edge-of-pavement / layout-line job
re-implemented (five earlier site builds did), promoted into the kernel: a
flat strip of constant `width` along a 3D polyline, each vertex keeping its
own z (draped), two triangles per segment, offset perpendicular in the XY
(plan) plane. It is an OPEN surface — emit_ifc lands it as an
`IfcTriangulatedFaceSet(Closed=False)`, not a closed solid.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from bimforge.author.sweep import to_model


def ribbon_mesh(points, width: float):
    """(verts, tris) for a flat ribbon of constant `width` along `points`.

    `points` are (x, y, z) in the model frame; the perpendicular offset is
    taken in the XY plane so the strip drapes with whatever z the polyline
    carries. Degenerate (zero plan-length) segments are skipped.
    """
    half = width / 2.0
    verts: list[tuple] = []
    tris: list[tuple] = []
    for (x0, y0, z0), (x1, y1, z1) in zip(points, points[1:]):
        dx, dy = x1 - x0, y1 - y0
        L = math.hypot(dx, dy)
        if L < 1e-9:
            continue
        px, py = -dy / L * half, dx / L * half
        b = len(verts)
        verts += [(x0 + px, y0 + py, z0), (x0 - px, y0 - py, z0),
                  (x1 - px, y1 - py, z1), (x1 + px, y1 + py, z1)]
        tris += [(b, b + 1, b + 2), (b, b + 2, b + 3)]
    return verts, tris


@dataclass
class Ribbon:
    """A draped ribbon surface: a model-frame polyline plus a strip width (ft)."""

    points: list                    # [(x, y, z), …] model frame, feet
    width: float

    @classmethod
    def along_alignment(cls, alignment, s0: float, s1: float, width: float, *,
                        offset: float = 0.0, side: str = "Rt", origin=None,
                        z_of=None, step: float = 2.0) -> "Ribbon":
        """Ribbon of `width` following an `Alignment` from station s0 to s1.

        Samples the radial `offset` line (0 = centreline) every <= `step` ft,
        maps each survey (n, e) to the model frame via `to_model(origin, …)`
        (origin = a ProjectContext, or None for already-local), and takes z
        from `z_of(station)` (e.g. a `Profile.elev`), 0 if omitted.
        """
        pts = [to_model(origin, n, e, z_of(s) if z_of else 0.0)
               for n, e, s in alignment.offset_curve(s0, s1, offset, side,
                                                     step=step)]
        return cls(points=pts, width=width)

    @property
    def plan_length_ft(self) -> float:
        return sum(math.hypot(b[0] - a[0], b[1] - a[1])
                   for a, b in zip(self.points, self.points[1:]))

    @property
    def area_sf(self) -> float:
        return self.plan_length_ft * self.width

    def body_solids(self) -> list[dict]:
        return [{"kind": "ribbon", "units": "ft",
                 "points": [tuple(p) for p in self.points], "width": self.width}]
