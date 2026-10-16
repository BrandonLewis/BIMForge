"""Watertight terrain solid + excavation carve (bridge-pilot ``_carve_terrain`` port).

Builds the terrain as a watertight SOLID — the surface on top, a flat bottom
below the deepest dig, a perimeter skirt — and subtracts each excavation
frustum with a manifold mesh boolean. The trick is that a cut which floats
entirely ABOVE the terrain is a no-op: digs in future approach-embankment
fill are not in existing ground, so they must not carve the terrain — and
the geometry enforces that for free, leaving only the cuts into existing
ground as real pits. A solid terrain that gets earth removed is also the
right shape for staging and shoring study later.

The mesh-boolean deps (trimesh + manifold3d, plus networkx for repair) are
OPTIONAL — imported at call time inside :func:`carve`; when they are missing
or the boolean fails, the degradation is logged and the open surface comes
back unchanged, so terrain works everywhere.

Axis convention: callers hand verts as ``(n, e, z)``; :func:`carve` works in
``(e, n, z)`` internally (the x=easting, y=northing frame the boolean runs
in) and converts back to ``(n, e, z)`` on return, matching the bridge-pilot source.
"""

from __future__ import annotations

from collections import Counter

import numpy as np


def close_surface(verts, tris, zbase):
    """Close an open triangulated surface into a watertight solid.

    Stacks a flat mirrored copy of the vertices at ``zbase`` (which the
    caller puts below the surface minimum and any planned dig) under the
    surface, keeps the top faces wound up, winds the bottom faces down, and
    joins the two along the boundary with a skirt of wall quads. Boundary
    edges are found by pure counting: an undirected edge used by exactly one
    triangle is on the rim. Pure numpy/stdlib — no trimesh needed.

    Returns ``(verts, faces)``: ``2n`` vertices (top block then bottom
    block) and the combined top/bottom/skirt face list.
    """
    tv = np.asarray(verts, dtype="float64")
    tf = np.asarray(tris, dtype="int64")
    nv = len(tv)
    bot = tv.copy()
    bot[:, 2] = float(zbase)
    edges = Counter()
    for a, b, c in tf:
        for u, v in ((a, b), (b, c), (c, a)):
            edges[(min(u, v), max(u, v))] += 1
    boundary = [e for e, cnt in edges.items() if cnt == 1]
    V = np.vstack([tv, bot])
    F = [[a, b, c] for a, b, c in tf]                       # top, up
    F += [[nv + a, nv + c, nv + b] for a, b, c in tf]       # bottom, down
    for u, v in boundary:                                   # skirt walls
        F += [[u, v, nv + v], [u, nv + v, nv + u]]
    return V, np.asarray(F, dtype="int64")


def frustum(base, top_base, z0, z1):
    """Closed frustum solid between two n-gon rings; returns (verts, faces).

    ``base``/``top_base`` are matching-length sequences of ``(n, e)`` pairs;
    the verts come back in the ``(e, n, z)`` frame :func:`carve` booleans in.
    ``z0``/``z1`` may be scalars or sequences (min of ``z0`` and max of
    ``z1`` are taken), matching the bridge-pilot cut tuples. Caps are triangle
    fans, sides are split quads.
    """
    z0 = z0 if not isinstance(z0, (list, tuple)) else min(z0)
    z1 = z1 if not isinstance(z1, (list, tuple)) else max(z1)
    n = len(base)
    v = np.array([(e, nn, z0) for nn, e in base]
                 + [(e, nn, z1) for nn, e in top_base], dtype="float64")
    f = []
    for i in range(1, n - 1):                               # bottom + top caps
        f += [[0, i + 1, i], [n, n + i, n + i + 1]]
    for i in range(n):                                      # sides
        j = (i + 1) % n
        f += [[i, j, n + j], [i, n + j, n + i]]
    return v, np.asarray(f, dtype="int64")


def carve(verts, tris, cuts, log=print):
    """Carve excavation cuts into a terrain surface.

    ``verts`` are ``(n, e, z)`` in model units; ``tris`` index them; each
    cut is a ``(base, top_base, z0, z1)`` frustum (see :func:`frustum`).
    Returns ``(verts, tris, closed, removed_cf)``: the carved watertight
    solid with ``closed=True`` and ``removed_cf`` — the volume of existing
    ground removed, ``terr.volume - carved.volume`` in input units cubed —
    on success; the input open surface with ``closed=False`` and
    ``removed_cf=0.0`` (degradation logged) when the mesh-boolean deps are
    missing or the boolean fails.

    A cut floating entirely above the terrain removes nothing — the
    existing-vs-future-ground classification is proven by the boolean, not
    asserted (see the module docstring).
    """
    try:
        import trimesh
        import manifold3d  # noqa: F401 — the boolean engine trimesh uses
    except Exception as e:
        log(f"  terrain: carve skipped (mesh-boolean deps missing: {e})")
        return verts, tris, False, 0.0
    tv = np.array(verts, dtype="float64")
    tf = np.array(tris, dtype="int64")
    top = np.column_stack([tv[:, 1], tv[:, 0], tv[:, 2]])   # (e, n, z)
    cut_z0 = [(c[2] if not isinstance(c[2], (list, tuple)) else min(c[2]))
              for c in cuts]
    zbase = float(min(tv[:, 2].min(), min(cut_z0)) - 5.0)
    V, F = close_surface(top, tf, zbase)
    terr = trimesh.Trimesh(vertices=V, faces=F, process=True)
    trimesh.repair.fix_normals(terr)

    def _tool(cut):
        fv, ff = frustum(*cut)
        mm = trimesh.Trimesh(vertices=fv, faces=ff, process=True)
        trimesh.repair.fix_normals(mm)
        return mm

    tools = [_tool(c) for c in cuts]
    try:
        carved = terr.difference(tools)
    except Exception as e:
        log(f"  terrain: mesh boolean failed ({e}); open surface")
        return verts, tris, False, 0.0
    removed_cf = float(terr.volume - carved.volume)
    cv = np.asarray(carved.vertices)
    cf = np.asarray(carved.faces)
    out_v = [(float(y), float(x), float(z)) for x, y, z in cv]  # -> (n, e, z)
    out_t = [tuple(int(i) for i in f) for f in cf]
    log(f"  terrain: carved solid, {len(out_v)} verts, {len(out_t)} tris, "
        f"{removed_cf:.0f} units^3 existing-ground dig removed")
    return out_v, out_t, True, removed_cf
