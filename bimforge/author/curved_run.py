"""Curved-run shared machinery (#149): a barrier `path` (straight/arc segments)
becomes a local Alignment, a constant-section SweptSection running prism, and
section-morphing end blocks that follow the alignment. Straight terminals are
the zero-curvature case, so one path serves straight and arc terminals. See
docs/superpowers/specs/2026-08-31-curved-run-shared-machinery-design.md.
"""
from __future__ import annotations

import math

from bimforge.author.alignment import Alignment
from bimforge.author.model import Element
from bimforge.author.primitives import (
    clean_ring, ear_clip, face_volume, _outward_tris, _wound)
from bimforge.author.sweep import MAX_ARC_STEP_RAD, SweptSection, to_model


def _az_to_bearing(az: float) -> str:
    """Decimal azimuth (deg cw from north) -> a `parse_bearing` quadrant string
    (`"N dd-mm-ss.ssssss E"`). Seconds carry 6 decimals (~3e-10 deg) so the
    az -> string -> az round-trip stays far under kink_check's 1e-6 deg."""
    az %= 360.0
    if az <= 90.0:
        ns, ang, ew = "N", az, "E"
    elif az < 180.0:
        ns, ang, ew = "S", 180.0 - az, "E"
    elif az <= 270.0:
        ns, ang, ew = "S", az - 180.0, "W"
    else:
        ns, ang, ew = "N", 360.0 - az, "W"
    d = int(ang)
    mf = (ang - d) * 60.0
    m = int(mf)
    s = (mf - m) * 60.0
    return f"{ns} {d}-{m}-{s:.6f} {ew}"


def alignment_from_path(path: list, name: str = "P") -> Alignment:
    """Build a LOCAL Alignment (origin, station 0, initial azimuth 0 = +y) from
    an ordered list of tangent-continuous barrier segments:
      {kind: straight, length}      and      {kind: arc, radius, delta, turn}.
    Arc length is computed (R * radians(delta)). Each straight's bearing is the
    running azimuth, so joins are tangent-continuous by construction."""
    az = 0.0
    run: list[dict] = []
    for seg in path:
        kind = seg.get("kind")
        if kind == "straight":
            length = float(seg["length"])
            if length <= 0:
                raise ValueError(f"straight segment length must be > 0, got {length}")
            run.append({"kind": "tangent", "bearing": _az_to_bearing(az),
                        "length": length})
        elif kind == "arc":
            radius = float(seg["radius"])
            delta = float(seg["delta"])
            if radius <= 0:
                raise ValueError(f"arc radius must be > 0, got {radius}")
            if delta <= 0:
                raise ValueError(f"arc delta must be > 0 deg, got {delta}")
            turn = str(seg.get("turn", "R")).upper()
            if turn not in ("L", "R"):
                raise ValueError(f"arc turn must be 'L' or 'R', got {turn!r}")
            run.append({"kind": "curve", "delta": delta, "radius": radius,
                        "turn": turn, "length": radius * math.radians(delta)})
            az += delta if turn == "R" else -delta
        else:
            raise ValueError(f"path segment kind must be 'straight' or 'arc', "
                             f"got {kind!r}")
    pob = {"northing": 0.0, "easting": 0.0, "station": 0.0, "azimuth": 0.0}
    return Alignment(pob, run, name=name)


def build_running_prism(name: str, outline: list, align, s0: float, s1,
                        *, ifc: str, layer: str) -> Element:
    """The running barrier as a constant-section plumb SweptSection over
    [s0, s1] of `align` (s1=None -> align.s_end). Volume is SweptSection's
    closed-form Pappus, gate-checked against the faceted loft; length_ft is the
    arc length s1 - s0."""
    if s1 is None:
        s1 = align.s_end
    sw = SweptSection(name, outline, align, s0, s1, frame="plumb",
                      origin=None, ifc=ifc, layer=layer)
    return Element.from_geometry(name, sw, ifc_class=ifc, layer=layer,
                                 quantities={"length_ft": s1 - s0})


def _morph_stations(align, s0, s1) -> list:
    """Stations across [s0, s1] fine enough that no arc sub-step exceeds the
    facet bound; segment ends are always cut points. Straight spans -> 2."""
    cuts = sorted({s0, s1, *align.seg_breaks(s0, s1)})
    out: list[float] = []
    for a, b in zip(cuts, cuts[1:]):
        k = abs(align.curvature((a + b) / 2.0))
        turn = k * (b - a)
        m = max(1, int(math.ceil(turn / MAX_ARC_STEP_RAD)))
        for i in range(m):
            out.append(a + (b - a) * i / m)
    out.append(cuts[-1])
    return out


def _world_ring(align, s: float, ring2d: list) -> list:
    """Place a plumb (x, z) ring at station s: +x along left_normal, z up."""
    n0, e0, _az = align.point_az(s)
    ln, le = align.left_normal(s)
    return [to_model(None, n0 + x * ln, e0 + x * le, z) for x, z in ring2d]


def _cap_tris(ring2d: list) -> list:
    """Triangulate a CCW (x, z) cap ring with ear_clip, returning index triples
    into `ring2d`. THE single source of cap triangulation, shared by
    `volume_cf` and `body_solids` so the declared volume is the emitted mesh's.

    A vertex-0 fan would net the correct VOLUME on any simple ring (fan area ==
    shoelace area), but on a section that is not star-shaped from vertex 0 (a
    U/channel, the real 732sw/842 L) it emits triangles crossing the cut-out --
    a self-overlapping cap that OCCT can reject when the loft is B-repped
    (emit_ifc). ear_clip keeps every triangle inside the ring. Collapsed-
    duplicate vertices (a relief that closes to zero width) are dropped first,
    the same guard `_EndBlockSolid._tri_face` carries, and the returned indices
    still point into the ORIGINAL ring so callers stay index-aligned with the
    placed 3-D ring and the side-wall quads."""
    n = len(ring2d)
    keep = [i for i in range(n)
            if (round(ring2d[i][0], 9), round(ring2d[i][1], 9))
            != (round(ring2d[i - 1][0], 9), round(ring2d[i - 1][1], 9))]
    reduced = [ring2d[i] for i in keep]
    if len(reduced) < 3:
        return []
    return [(keep[a], keep[b], keep[c]) for a, b, c in ear_clip(reduced)]


class _MorphSweep:
    """A section-morphing loft along an alignment. `ring_at(s)` returns the
    (x, z) ring at station s (constant vertex count). Volume is face_volume of
    the emitted mesh (no closed form exists for a varying section -- the
    in-discipline fallback, BatteredWall precedent)."""

    def __init__(self, name, ring_at, align, s0, s1):
        self.name = name
        self._ss = _morph_stations(align, s0, s1)
        # 2-D rings wound CCW in (x, z) so caps/walls face outward; the world
        # rings are index-aligned lifts of these, so ear_clip index triples on
        # a 2-D ring apply verbatim to the matching world ring.
        self._rings2d = [_wound(ring_at(s), ccw=True) for s in self._ss]
        self._rings = [_world_ring(align, s, r2)
                       for s, r2 in zip(self._ss, self._rings2d)]
        self.length_ft = float(s1 - s0)

    def _faces(self) -> list:
        rings = self._rings
        faces: list = []
        # end caps: ear_clip each end's OWN 2-D ring (the sections morph), then
        # index into the matching world ring. Near cap faces back (triangles
        # reversed), far cap faces forward -- the SweptSection cap convention.
        near, far = rings[0], rings[-1]
        for i0, i1, i2 in _cap_tris(self._rings2d[0]):
            faces.append([near[i2], near[i1], near[i0]])
        for i0, i1, i2 in _cap_tris(self._rings2d[-1]):
            faces.append([far[i0], far[i1], far[i2]])
        # side walls: centroid 4-fan per quad (kills twist volume bias)
        for wa, wb in zip(rings, rings[1:]):
            m = len(wa)
            for j in range(m):
                k = (j + 1) % m
                a, b, c, d = wa[j], wa[k], wb[k], wb[j]
                mid = ((a[0] + b[0] + c[0] + d[0]) / 4.0,
                       (a[1] + b[1] + c[1] + d[1]) / 4.0,
                       (a[2] + b[2] + c[2] + d[2]) / 4.0)
                faces += [[a, b, mid], [b, c, mid], [c, d, mid], [d, a, mid]]
        return faces

    @property
    def volume_cf(self) -> float:
        return abs(face_volume(self._faces()))

    def body_solids(self) -> list:
        verts: list = []
        index: dict = {}

        def vid(p):
            key = (round(p[0], 9), round(p[1], 9), round(p[2], 9))
            if key not in index:
                index[key] = len(verts)
                verts.append((float(p[0]), float(p[1]), float(p[2])))
            return index[key]

        tris = []
        for ring in self._faces():
            r = clean_ring(ring)
            if len(r) < 3:
                continue
            for b, c in zip(r[1:], r[2:]):
                tris.append((vid(r[0]), vid(b), vid(c)))
        return [{"kind": "mesh", "units": "ft", "verts": verts,
                 "tris": _outward_tris(verts, tris), "plan": [self._plan()]}]

    def _plan(self) -> list:
        # outline of the swept footprint in the model XY plane
        left = [(p[0], p[1]) for p in (r[0] for r in self._rings)]
        right = [(p[0], p[1]) for p in (r[len(r) // 2] for r in self._rings)]
        return left + list(reversed(right))


def sweep_morph(name: str, ring_at, align, s0: float, s1: float,
                *, ifc: str, layer: str) -> Element:
    """End-block solid as a section-morphing loft along the alignment. Returns
    an Element carrying face_volume (volume_cf) and length_ft = s1 - s0."""
    geom = _MorphSweep(name, ring_at, align, s0, s1)
    return Element.from_geometry(name, geom, ifc_class=ifc, layer=layer,
                                 quantities={"length_ft": s1 - s0})
