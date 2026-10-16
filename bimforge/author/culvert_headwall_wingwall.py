"""Caltrans D90 flared wingwalls (Types A/B/C) + the Type C Type-836 barrier.

A wingwall is a thin plate that leaves the headwall end at a splay angle and
runs `length` ft, its top tapering from `h_near` (full, at the headwall) to
`h_far` at the free end -- a per-vertex-`top_z` Prism so the solid reaches full
height at its high end and daylights at its low one (the headwall_926
mean-height-box lesson: right volume AND right shape). Type A/B/C differ only
in parameters (splay/length/height), carried in the catalog; Type C adds a
Type 836 concrete barrier, emitted as ONE continuous `rail_barrier` swept along
the wingwall tops AND across the headwall (with the Section H-H haunch).

Dimensional validation (length/t/w/h > 0) is the CALLER's responsibility: the
underlying `Prism` does not guard these, and the family supplies already-
validated catalog params -- so the deferral is intentional, not an oversight.
"""
from __future__ import annotations

import math

from bimforge.author.primitives import (
    Prism, loft_faces, face_volume, clean_ring, _outward_tris,
    outward_normals, mitre_offset, profile_at, triangulate_planar_face)


def flared_wingwall(name: str, x0: float, y0: float, angle_deg: float,
                    length: float, h_near: float, h_far: float, t: float,
                    z_base: float) -> Prism:
    """Tapered wingwall plate from (x0, y0) at `angle_deg` from the wall line,
    top tapering h_near -> h_far over `length`.

    Thickness `t` is offset to the +90-deg-CCW side of the run direction. The
    caller (family) chooses `angle_deg`/side so that side lands inboard (toward
    the footing/fill); this helper does not decide handedness.
    """
    a = math.radians(angle_deg)
    dx, dy = math.cos(a) * length, math.sin(a) * length
    nx, ny = -math.sin(a), math.cos(a)                 # +90-deg-CCW of the run direction
    p0 = (x0, y0)
    p1 = (x0 + dx, y0 + dy)
    quad = [p0, p1, (p1[0] + nx * t, p1[1] + ny * t),
            (p0[0] + nx * t, p0[1] + ny * t)]
    return Prism(name, quad, z_bot=z_base,
                 top_z=[z_base + h_near, z_base + h_far,
                        z_base + h_far, z_base + h_near],
                 dims_ft=(length, t), ifc="IfcWall", layer="S-CONC")


class _BarrierSolid:
    """A constant barrier section lofted between two 3D end sections (the
    headwall-corner end and the free end). The section is vertical and sheared
    along z to ride the sloping wingwall top, so volume_cf == section area x
    plan length. Mirrors BatteredWall's loft/mesh tail so the declared volume
    IS the emitted-mesh volume."""

    def __init__(self, name, sections, ifc="IfcWall", layer="S-CONC"):
        self.name, self._sections = name, sections
        self.ifc, self.layer = ifc, layer
        self.base = ([(x, y) for (x, y, _z) in sections[0]]
                     + [(x, y) for (x, y, _z) in reversed(sections[-1])])

    @property
    def volume_cf(self):
        return face_volume(loft_faces(self._sections))

    def body_solids(self):
        verts, index, tris = [], {}, []

        def vid(p):
            if p not in index:
                index[p] = len(verts)
                verts.append(tuple(float(c) for c in p))
            return index[p]

        for ring in loft_faces(self._sections):
            r = clean_ring(ring)
            if len(r) < 3:
                continue
            # Ear-clip every face in its own plane: a fan from r[0] is only
            # valid for a convex ring, and the transcribed Type 836 section is
            # re-entrant, so the two full-ring end caps would fan into an
            # inside-out, non-manifold shell (#253). Side faces are triangles,
            # for which this returns the single triangle unchanged.
            for i0, i1, i2 in triangulate_planar_face(r):
                tris.append((vid(r[i0]), vid(r[i1]), vid(r[i2])))
        return [{"kind": "mesh", "units": "ft",
                 "verts": verts, "tris": _outward_tris(verts, tris),
                 "plan": [self.base]}]


def _haunched_outline(outline, tmin, haunch_ft, wall_face):
    """Add the Section A-A haunch at the barrier's EARTH-side base edge (max-x
    base corner): the earth face drops STRAIGHT DOWN `haunch_ft` from the rail
    face, then a 1:1 soffit slopes DOWN back to the wall face (section-x
    `wall_face`), reaching it `tmax - wall_face` lower. Then straight up the wall
    face to the base. The haunch hangs below the base on the earth-side
    overhang, inside it (never crossing the wall stem)."""
    tmax = max(t for t, _z in outline)
    if not (haunch_ft > 0 and tmin < wall_face < tmax):
        return list(outline)                    # disabled, or no earth-side overhang
    drop = haunch_ft + (tmax - wall_face)       # vertical + 1:1 run to the wall
    out = []
    for t, z in outline:
        out.append((t, z))
        if abs(t - tmax) < 1e-9 and abs(z) < 1e-9:
            out.append((tmax, -haunch_ft))       # straight down the earth face 1 ft
            out.append((wall_face, -drop))       # 1:1 soffit down to the wall face
            out.append((wall_face, 0.0))         # up the wall face to the base
    return out


def rail_barrier(name, lol, top_profile, section, *, key_index=0,
                 side_sign=1.0, seat=0.0, haunch_ft=0.0):
    """One CONTINUOUS Type 836 rail swept along the plan polyline `lol`
    (left wingwall -> across the headwall -> right wingwall), mitred at the
    interior corners like the footing, its base riding `top_profile` (the
    wall-top elevation, piecewise-linear, keyed on the plan coordinate
    `key_index`: 0=x, 1=y).

    The section's transverse x runs from the plumb BACK face (min x, the
    channel/water side) to the battered TRAFFIC face base (max x). The body is
    laid toward `side_sign` * the run's outward normal so the battered face
    points to the EARTH/roadway side; the plumb back is seated `seat` ft off the
    LOL toward the channel side (so the barrier rides on top of the wall). When
    `haunch_ft` > 0 a Section A-A 1:1 haunch fillet drops the earth-side base
    `haunch_ft` down to the wall."""
    normals = outward_normals(lol, side_sign)
    # Seat datum = the section's CHANNEL-MOST point (min transverse x). For
    # Type 836 that is the thickened upper backface, which `seat` places on the
    # wall's channel face; the recessed lower backface then sits a few inches
    # inboard (the sheet's back reveal). This is intentional -- NOT the base
    # backface -- and matches the reviewed placement (earth-side overhang ~0.75
    # ft, haunch soffit landing on the wall face).
    tmin = min(t for t, _z in section.outline)
    outline = _haunched_outline(section.outline, tmin, haunch_ft, tmin + seat)
    sections = []
    for i, (px, py) in enumerate(lol):
        if i == 0:
            m = normals[0]
        elif i == len(lol) - 1:
            m = normals[-1]
        else:
            m = mitre_offset(normals[i - 1], normals[i])
        be = profile_at(top_profile, (px, py)[key_index])
        sections.append([
            (px + m[0] * ((t - tmin) - seat), py + m[1] * ((t - tmin) - seat),
             be + z) for (t, z) in outline])
    return _BarrierSolid(name, sections)
