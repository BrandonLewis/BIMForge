"""FootingRun — a B3 toe/heel footing lofted along a plan line-of-layout,
mitred at interior corners (the BatteredWall lineage: reuse outward_normals +
mitre_offset so the corner where the headwall footing meets a flared-wingwall
footing is one continuous solid, not two overlapping boxes).

The cross-section perpendicular to the LOL spans `toe` on the +`side` normal
and `heel` on the -`side` normal (W = toe + heel); the slab runs from the
bottom to the top elevation. The top of footing is either a constant `top_el`
(flat bottom) or a piecewise-linear `top_profile` keyed on the plan
coordinate `key_index` names (0 = x, 1 = y) — the BatteredWall pattern.
With a `top_profile`, `bottom` selects how the top-of-footing follows it:
"swept" (default) slopes continuously at constant thickness; "stepped"
snaps the swept top DOWN to the nearest multiple of the Caltrans B3-5 step
rise (`step_rise_ft(design_h)`, `design_h` required), giving LEVEL runs
that drop in vertical risers where the snapped level changes — two
co-located sections (upper level, then lower level, ordered by direction
of travel) so the loft face between them is a plumb riser rather than a
slope. Bottom = top - thickness throughout in every mode. Declared
volume_cf IS the emitted-mesh volume (face_volume of the loft), per
BatteredWall discipline.
"""
from __future__ import annotations

import math

from bimforge.author.primitives import (face_volume, loft_faces, mitre_offset,
                                         outward_normals, profile_at,
                                         _outward_tris)


def step_rise_ft(design_h: float) -> float:
    """Caltrans B3-5 footing-step rise by design H: 1.0 ft for H 4-22,
    1.5 ft for H 24-36. Boundary between the discrete even-foot rows is 22/24.
    """
    return 1.0 if design_h <= 22.0 else 1.5


def _offset_point(vtx, m, dist):
    return (vtx[0] + m[0] * dist, vtx[1] + m[1] * dist)


def _mitres(lol, side):
    """Per-vertex mitred offset directions for a LOL (endpoints use the
    adjacent segment normal; interior vertices use mitre_offset)."""
    normals = outward_normals(lol, side)
    out = []
    for i in range(len(lol)):
        if i == 0:
            out.append(normals[0])
        elif i == len(lol) - 1:
            out.append(normals[-1])
        else:
            out.append(mitre_offset(normals[i - 1], normals[i]))
    return out


class FootingRun:
    def __init__(self, name: str, lol: list, toe: float, heel: float,
                 side: float, thickness: float,
                 top_el: float | None = None, top_profile: list | None = None,
                 key_index: int = 0, bottom: str | None = None,
                 design_h: float | None = None,
                 ifc: str = "IfcFooting", layer: str | None = "S-CONC") -> None:
        if len(lol) < 2:
            raise ValueError(f"{name}: lol needs at least two points")
        if toe < 0 or heel < 0 or thickness <= 0:
            raise ValueError(f"{name}: toe/heel >= 0 and thickness > 0 required")
        if (top_el is None) == (top_profile is None):
            raise ValueError(f"{name}: give exactly one of top_el / top_profile")
        if top_el is not None:
            mode = "flat"           # bottom is meaningless with a flat top
        else:
            mode = bottom if bottom is not None else "swept"
            if mode not in ("swept", "stepped"):
                raise ValueError(f"{name}: unknown bottom mode {bottom!r}")
            if mode == "stepped" and design_h is None:
                raise ValueError(f"{name}: stepped bottom requires design_h")
        rise = step_rise_ft(design_h) if mode == "stepped" else None
        self.name, self.lol, self.ifc, self.layer = name, list(lol), ifc, layer
        self.toe, self.heel, self.thickness = toe, heel, thickness
        mt = _mitres(lol, side)
        mh = _mitres(lol, -side)
        # per-segment (unmitred) normals, used for breakpoint sections that
        # fall inside a leg rather than at a mitred vertex
        seg_t = outward_normals(lol, side)
        seg_h = outward_normals(lol, -side)

        def snap(z):
            return math.floor(z / rise + 1e-9) * rise

        def top_at(v):
            if mode == "flat":
                return top_el
            return profile_at(top_profile, v[key_index])   # swept

        def section(v, m_toe, m_heel, z1=None):
            tp = _offset_point(v, m_toe, toe)
            hp = _offset_point(v, m_heel, heel)
            z1 = top_at(v) if z1 is None else z1
            z0 = z1 - thickness
            return [(tp[0], tp[1], z0), (hp[0], hp[1], z0),
                    (hp[0], hp[1], z1), (tp[0], tp[1], z1)]

        if mode == "stepped":
            self._sections = self._build_stepped(
                lol, key_index, top_profile, rise, snap, section,
                mt, mh, seg_t, seg_h)
        else:
            self._sections = []
            for i, v in enumerate(lol):
                self._sections.append(section(v, mt[i], mh[i]))
                if top_profile is None or i >= len(lol) - 1:
                    continue
                # Sections at every top-of-footing breakpoint falling
                # INSIDE the segment, in traversal order (BatteredWall
                # pattern — direction-agnostic so a mirrored run doesn't
                # silently straight-line the sloped bottom).
                a, b = lol[i], lol[i + 1]
                sa, sb = a[key_index], b[key_index]
                if abs(sb - sa) < 1e-9:
                    continue          # the leg runs normal to the key axis
                for s in sorted((u for u, _e in top_profile
                                 if min(sa, sb) + 1e-9 < u < max(sa, sb) - 1e-9),
                                reverse=sb < sa):
                    t = (s - sa) / (sb - sa)
                    mid = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                    self._sections.append(section(mid, seg_t[i], seg_h[i]))
        self.base = ([(s[0][0], s[0][1]) for s in self._sections]
                     + [(s[1][0], s[1][1]) for s in reversed(self._sections)])

    @staticmethod
    def _build_stepped(lol, key_index, top_profile, rise, snap, section,
                       mt, mh, seg_t, seg_h):
        """Level runs that drop in plumb risers, snapped by BAY MIDPOINT.

        Nodes are laid out along the whole LOL — every vertex (mitred
        normals) plus, inside each leg, the top_profile breakpoints and
        the grid-crossing stations (unmitred segment normals). Each bay
        (consecutive-node span) takes ONE level = snap(profile_at(its
        midpoint)): reading the level from the bay INTERIOR means a knot
        that lands exactly on a grid line no longer decides the level, so
        every bay top is horizontal. Where two bays meet at different
        levels a second co-located section is emitted (before then after,
        in travel order) → a vertical riser, never a sloped face.
        """
        # 1. ordered nodes: (plan_point, m_toe, m_heel)
        nodes = []
        for i in range(len(lol) - 1):
            a, b = lol[i], lol[i + 1]
            nodes.append((a, mt[i], mh[i]))          # leg start vertex
            sa, sb = a[key_index], b[key_index]
            if abs(sb - sa) < 1e-9:
                continue          # leg normal to the key axis: no interior nodes
            lo, hi = min(sa, sb), max(sa, sb)
            stations = {u for u, _e in top_profile if lo + 1e-9 < u < hi - 1e-9}
            # grid crossings inside each linear sub-span of the profile
            subs = [(u0, e0, u1, e1) for (u0, e0), (u1, e1)
                    in zip(top_profile, top_profile[1:])]
            for u0, e0, u1, e1 in subs:
                su0, su1 = min(u0, u1), max(u0, u1)
                if su1 <= lo or su0 >= hi or e0 == e1:
                    continue
                elo, ehi = min(e0, e1), max(e0, e1)
                kmin = math.floor(elo / rise + 1e-9) + 1
                kmax = math.ceil(ehi / rise - 1e-9) - 1
                for k in range(kmin, kmax + 1):
                    krise = k * rise
                    if not (elo < krise < ehi):
                        continue
                    uc = u0 + (krise - e0) * (u1 - u0) / (e1 - e0)
                    if lo + 1e-9 < uc < hi - 1e-9:
                        stations.add(uc)
            for s in sorted(stations, reverse=sb < sa):
                t = (s - sa) / (sb - sa)
                mid = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                nodes.append((mid, seg_t[i], seg_h[i]))
        nodes.append((lol[-1], mt[-1], mh[-1]))       # final vertex

        # 2. per-bay level from the bay midpoint
        levels = []
        for (pa, _ta, _ha), (pb, _tb, _hb) in zip(nodes, nodes[1:]):
            mu = (pa[key_index] + pb[key_index]) / 2.0
            levels.append(snap(profile_at(top_profile, mu)))

        # 3. walk nodes; horizontal bays share a level, level changes are risers
        sections = []
        for j, (p, m_toe, m_heel) in enumerate(nodes):
            before = levels[j - 1] if j > 0 else None
            after = levels[j] if j < len(levels) else None
            if before is None:
                sections.append(section(p, m_toe, m_heel, z1=after))
            elif after is None:
                sections.append(section(p, m_toe, m_heel, z1=before))
            elif abs(before - after) < 1e-9:
                sections.append(section(p, m_toe, m_heel, z1=before))
            else:                       # riser: before then after (travel order)
                sections.append(section(p, m_toe, m_heel, z1=before))
                sections.append(section(p, m_toe, m_heel, z1=after))
        return sections

    def _faces(self):
        return loft_faces(self._sections)

    @property
    def volume_cf(self) -> float:
        return face_volume(self._faces())

    @property
    def plan_area_sf(self) -> float:
        from bimforge.author.primitives import poly_area
        return abs(poly_area(self.base))

    def body_solids(self) -> list[dict]:
        verts, index, tris = [], {}, []

        def vid(p):
            if p not in index:
                index[p] = len(verts)
                verts.append(tuple(float(c) for c in p))
            return index[p]

        from bimforge.author.primitives import (
            clean_ring, triangulate_planar_face)
        for ring in self._faces():
            r = clean_ring(ring)
            if not r:
                continue
            # Ear-clip in the face's own plane (#315). The fan this
            # replaces is correct only while every section stays convex.
            for i0, i1, i2 in triangulate_planar_face(r):
                tris.append((vid(r[i0]), vid(r[i1]), vid(r[i2])))
        return [{"kind": "mesh", "units": "ft", "verts": verts,
                 "tris": _outward_tris(verts, tris), "plan": [self.base]}]
