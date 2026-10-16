"""Caltrans D84-D86 box-culvert wingwall geometry (spec Section4/5).

A wingwall is a cantilever retaining wall that flares away from the culvert and
TAPERS in height as the embankment falls to the toe of slope. There is no
`Conc CY/LF` design table for the straight types, so concrete is geometry-
derived and the tests hand-check the volumes.

Local frame: the wall runs +x for `length` from the culvert (x=0) to the toe
(x=L); thickness along +y; height +z; footing top at z = foot_t. Stem height
above the footing goes `h_max` (at the culvert) -> `h_min` (at the toe).

Every quantity is analytic. The straight stem is a sloped-top `Prism` whose fan
triangulation integrates the wedge exactly; the warped stem (D86) is a
hexahedral loft that declares the EXACT closed-form shear-preserved volume
(the batter is a volume-neutral horizontal shear) while holding the emitted
faceted loft within MESH_TOLERANCE -- the exact + faceted discipline the curved
primitives carry (e.g. `ArcBand.volume_in3` vs `faceted_volume_in3`).
"""
from __future__ import annotations

from bimforge.author.primitives import (
    Prism, clean_ring, face_volume, loft_faces, triangulate_planar_face,
    _outward_tris)


def taper_stem_prism(length: float, stem_t: float, toe: float, foot_t: float,
                     h_max: float, h_min: float, name: str = "wingwall stem",
                     ifc: str = "IfcWall", layer: str = "S-CONC") -> Prism:
    """Straight (A/B/C/D) stem: plan strip `length x stem_t` at y in
    [toe, toe+stem_t], z_bot = foot_t, per-vertex top elevation tapering
    F+h_max (culvert) -> F+h_min (toe). Volume = stem_t*length*(h_max+h_min)/2.
    """
    C, F, T, L = toe, foot_t, stem_t, length
    base = [(0.0, C), (L, C), (L, C + T), (0.0, C + T)]
    top_z = [F + h_max, F + h_min, F + h_min, F + h_max]   # taper along +x
    return Prism(name, base, z_bot=F, top_z=top_z, ifc=ifc, layer=layer)


def taper_footing_prism(length: float, toe: float, heel: float, foot_t: float,
                        heel_toe: float | None = None,
                        name: str = "wingwall footing",
                        ifc: str = "IfcFooting", layer: str = "S-CONC") -> Prism:
    """Footing, thickness `foot_t`, width W = toe + heel. A clean box by
    default (carries L x W x H); when `heel_toe` is given the heel tapers in
    plan (D84 "B tapers in plan") to a trapezoid W -> W_toe = toe + heel_toe,
    volume foot_t*length*(W+W_toe)/2, carried as length + volume only."""
    C, F, L = toe, foot_t, length
    W = C + heel
    if heel_toe is None or abs(heel_toe - heel) < 1e-9:
        base = [(0.0, 0.0), (L, 0.0), (L, W), (0.0, W)]
        return Prism(name, base, z_bot=0.0, z_top=F, dims_ft=(L, W),
                     ifc=ifc, layer=layer)
    W_toe = C + heel_toe
    base = [(0.0, 0.0), (L, 0.0), (L, W_toe), (0.0, W)]     # trapezoid heel
    return Prism(name, base, z_bot=0.0, z_top=F, ifc=ifc, layer=layer)


def stiffening_beam_prism(length: float, w: float, d: float, z0: float,
                          toe: float = 0.0, name: str = "wingwall stiffening beam",
                          ifc: str = "IfcBeam", layer: str = "S-CONC") -> Prism:
    """D86 stiffening beam along the top of the wall: a clean box plan
    `length x w`, depth `d`, its base at z = z0. Volume = length*w*d."""
    base = [(0.0, toe), (length, toe), (length, toe + w), (0.0, toe + w)]
    return Prism(name, base, z_bot=z0, z_top=z0 + d, dims_ft=(length, w),
                 ifc=ifc, layer=layer)


class WarpedStem:
    """D86 warped wingwall stem: a hexahedral loft from a VERTICAL rectangular
    section at the culvert (x=0) to a BATTERED parallelogram section at the toe
    (x=L). The exposed face twists vertical -> `batter_toe` (:12 run-over-rise)
    while the top tapers h_max -> h_min.

    The batter is a pure horizontal SHEAR: every cross-section stays a
    parallelogram of area stem_t*h (shear-invariant), so the concrete volume is
    EXACTLY the straight taper's stem_t*L*(h_max+h_min)/2. `volume_cf` returns
    that exact closed form -- the physically correct pay quantity, independent
    of faceting. `faceted_volume_cf` is `face_volume` of the loft `body_solids`
    emits; a triangulated warped face systematically over-encloses (O(1/n)
    diagonal bias), so it is NOT the declared quantity -- it is the tessellated
    counterpart the post-gate holds within MESH_TOLERANCE (the same exact +
    faceted discipline the curved primitives carry, e.g. `ArcBand.volume_in3`
    vs `faceted_volume_in3`). `n_sections=48` keeps that band < 0.5% for
    realistic batters (<= ~2:12).
    """

    def __init__(self, name: str, length: float, stem_t: float, toe: float,
                 foot_t: float, h_max: float, h_min: float, batter_toe: float,
                 n_sections: int = 48, ifc: str = "IfcWall",
                 layer: str = "S-CONC") -> None:
        if length <= 0:
            raise ValueError(f"{name}: length must be positive")
        if n_sections < 1:
            raise ValueError(f"{name}: n_sections must be >= 1")
        self.name, self.length, self.stem_t = name, float(length), float(stem_t)
        self.toe, self.foot_t, self.ifc, self.layer = toe, foot_t, ifc, layer
        C, F, T, L = float(toe), float(foot_t), float(stem_t), float(length)
        self._analytic_vol = T * L * (float(h_max) + float(h_min)) / 2.0
        secs: list = []
        for i in range(n_sections + 1):
            x = L * i / n_sections
            t = x / L
            h = h_max + (h_min - h_max) * t
            dy = batter_toe * t * h                     # top edge lean (+y)
            z0, z1 = F, F + h
            secs.append([
                (x, C, z0),                             # 0 front bottom
                (x, C + T, z0),                         # 1 back bottom
                (x, C + T + dy, z1),                    # 2 back top (leaned)
                (x, C + dy, z1),                        # 3 front top (leaned)
            ])
        self.sections = secs

    def _faces(self) -> list:
        return loft_faces(self.sections)

    @property
    def volume_cf(self) -> float:
        # exact closed form (shear-invariant cross-section area); the emitted
        # faceted loft is reconciled to this by the gate within MESH_TOLERANCE.
        return self._analytic_vol

    @property
    def faceted_volume_cf(self) -> float:
        return face_volume(self._faces())

    @property
    def base(self) -> list:
        return ([(s[0][0], s[0][1]) for s in self.sections]
                + [(s[1][0], s[1][1]) for s in reversed(self.sections)])

    def body_solids(self) -> list[dict]:
        verts: list = []
        index: dict = {}

        def vid(p):
            if p not in index:
                index[p] = len(verts)
                verts.append(tuple(float(c) for c in p))
            return index[p]

        tris = []
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
