"""Tests for bimforge.terrain.solid — close_surface, frustum, carve.

Watertightness is asserted by pure edge recounting (no trimesh); frustum
volume by a signed-tet sum; the degraded carve path by a monkeypatched
failing import; and the flagship carve semantics (through-cut removes
volume, above-terrain cut is a no-op) under importorskip'd
trimesh + manifold3d.
"""

import builtins
from collections import Counter

import numpy as np
import pytest

from bimforge.terrain.solid import carve, close_surface, frustum


def _edge_counts(faces):
    """Undirected-edge usage counts across a face list."""
    edges = Counter()
    for a, b, c in np.asarray(faces, dtype=int):
        for u, v in ((a, b), (b, c), (c, a)):
            edges[(min(u, v), max(u, v))] += 1
    return edges


def _signed_volume(verts, faces):
    """Signed volume of a closed triangle mesh via the signed-tet sum."""
    v = np.asarray(verts, dtype=float)
    total = 0.0
    for a, b, c in np.asarray(faces, dtype=int):
        total += float(np.linalg.det(np.array([v[a], v[b], v[c]]))) / 6.0
    return total


def _grid_surface(n, z):
    """An n x n open grid surface at height z, verts (n, e, z), spacing 1."""
    verts = [(float(r), float(c), float(z)) for r in range(n) for c in range(n)]
    tris = []
    for r in range(n - 1):
        for c in range(n - 1):
            a = r * n + c
            tris += [(a, a + 1, a + n), (a + 1, a + n + 1, a + n)]
    return verts, tris


# A 2x2 square footprint (points are (n, e) pairs, CCW) used as the cut
# base/top in the carve tests.
SQUARE = [(3.0, 3.0), (3.0, 5.0), (5.0, 5.0), (5.0, 3.0)]


def test_close_surface_is_watertight():
    verts, tris = _grid_surface(3, z=2.0)
    V, F = close_surface(verts, tris, zbase=-3.0)  # zbase below the surface min
    assert len(V) == 2 * len(verts)
    # top half preserved, bottom half flattened to zbase
    assert np.allclose(V[: len(verts)], np.asarray(verts))
    assert np.all(V[len(verts):, 2] == -3.0)
    # watertight: every undirected edge is used by exactly two faces
    bad = {e: c for e, c in _edge_counts(F).items() if c != 2}
    assert bad == {}


def test_frustum_unit_cube():
    base = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)]  # (n, e) unit square
    v, f = frustum(base, base, 0.0, 1.0)
    assert len(v) == 8
    assert abs(_signed_volume(v, f)) == pytest.approx(1.0, abs=1e-9)


def test_carve_degrades_without_trimesh(monkeypatch):
    verts, tris = _grid_surface(3, z=0.0)
    real_import = builtins.__import__

    def _no_mesh_deps(name, *args, **kwargs):
        if name in ("trimesh", "manifold3d"):
            raise ImportError(f"No module named '{name}'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_mesh_deps)
    msgs = []
    out_v, out_t, closed, removed = carve(
        verts, tris, [(SQUARE, SQUARE, -5.0, -1.0)], log=msgs.append)
    assert out_v is verts and out_t is tris  # open surface returned untouched
    assert closed is False
    assert removed == 0.0
    assert any("carve skipped" in m for m in msgs)


def test_carve_through_cut_reduces_volume():
    pytest.importorskip("trimesh")
    pytest.importorskip("manifold3d")
    verts, tris = _grid_surface(10, z=0.0)
    # Cut frustum z -5 -> -1: entirely within the terrain solid
    # (zbase = min(0, -5) - 5 = -10), so the whole 2x2x4 frustum is removed.
    msgs = []
    out_v, out_t, closed, removed = carve(
        verts, tris, [(SQUARE, SQUARE, -5.0, -1.0)], log=msgs.append)
    assert closed is True
    assert removed == pytest.approx(16.0, rel=1e-4)
    # 9x9 footprint x 10 deep = 810, minus the removed frustum
    assert abs(_signed_volume(out_v, out_t)) == pytest.approx(810.0 - 16.0,
                                                              rel=1e-4)


def test_carve_above_terrain_cut_is_noop():
    pytest.importorskip("trimesh")
    pytest.importorskip("manifold3d")
    verts, tris = _grid_surface(10, z=0.0)
    # The SAME cut floated entirely above the surface (z +1 -> +5): future
    # embankment fill, not existing ground — the boolean makes it a no-op.
    msgs = []
    out_v, out_t, closed, removed = carve(
        verts, tris, [(SQUARE, SQUARE, 1.0, 5.0)], log=msgs.append)
    assert closed is True
    assert removed == pytest.approx(0.0, abs=1e-4)
    # zbase = min(0, 1) - 5 = -5 -> 9x9 x 5 deep = 405, unchanged
    assert abs(_signed_volume(out_v, out_t)) == pytest.approx(405.0, rel=1e-4)
