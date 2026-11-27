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
OPTIONAL — imported at call time inside :func:`carve`, which raises when a
carve is asked for and they are missing. A boolean that fails or runs past
its time limit is reported in the result's status (G.5). The carve is a
check: the terrain a model ships stays the open surface, each cut voiding
it (roadmap E.1).

Axis convention: callers hand verts as ``(n, e, z)``; :func:`carve` works in
``(e, n, z)`` internally (the x=easting, y=northing frame the boolean runs
in) and converts back to ``(n, e, z)`` on return, matching the bridge-pilot source.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import NamedTuple

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


#: what a carve came to, recorded on the terrain as ``CarveStatus`` (G.5).
#: Missing mesh-boolean libraries are not among them: a carve that is asked
#: for and cannot run raises (:class:`CarveUnavailable`), so the same spec
#: never builds different files where they are and are not installed.
NOT_ASKED = "not asked"
BOOLEAN_FAILED = "boolean failed"
TIMED_OUT = "timed out"
CARVED = "carved"
CARVE_STATUSES = (NOT_ASKED, BOOLEAN_FAILED, TIMED_OUT, CARVED)
#: how long the boolean may run, seconds, before the carve gives up
CARVE_TIMEOUT_S = 600.0


class CarveUnavailable(RuntimeError):
    """A carve was asked for and the mesh-boolean libraries are missing."""


class Carve(NamedTuple):
    """What :func:`carve` found. ``removed_cf`` is the existing ground the
    cuts take out together; ``cuts_cf`` the sum of what each takes out
    alone, so the two differ only where cuts overlap or the boolean went
    wrong. ``verts``/``tris`` are the carved closed solid, ``(n, e, z)``,
    when the status is ``carved``, and None otherwise; ``reason`` says why
    a carve did not finish."""
    status: str
    removed_cf: float = 0.0
    cuts_cf: float = 0.0
    verts: list | None = None
    tris: list | None = None
    reason: str = ""


def _boolean(top, tf, cuts):
    """The carve's boolean, (e, n, z): the closed terrain less every cut, as
    (verts, faces, removed, per-cut sum). Raises when the result is not one
    closed solid."""
    import trimesh

    cut_z0 = [(c[2] if not isinstance(c[2], (list, tuple)) else min(c[2]))
              for c in cuts]
    zbase = float(min(top[:, 2].min(), min(cut_z0)) - 5.0)
    V, F = close_surface(top, tf, zbase)
    terr = trimesh.Trimesh(vertices=V, faces=F, process=True)
    trimesh.repair.fix_normals(terr)

    def _tool(cut):
        fv, ff = frustum(*cut)
        mm = trimesh.Trimesh(vertices=fv, faces=ff, process=True)
        trimesh.repair.fix_normals(mm)
        return mm

    tools = [_tool(c) for c in cuts]
    carved = terr.difference(tools)
    if not carved.is_watertight:
        raise ValueError("the carved terrain is not closed")
    each = sum(float(terr.intersection([t]).volume) for t in tools)
    return (np.asarray(carved.vertices), np.asarray(carved.faces),
            float(terr.volume - carved.volume), each)


def _worker(job: str) -> None:
    """Run :func:`_boolean` on the arrays in ``job`` (an .npz the parent
    wrote) and write its answer beside it: ``<job>.out.npz``, or the
    exception as text in ``<job>.err``."""
    import json
    with np.load(job, allow_pickle=False) as data:
        top, tf, cuts = data["top"], data["tf"], json.loads(str(data["cuts"]))
    try:
        cv, cf, removed, each = _boolean(top, tf, cuts)
    except Exception as e:                      # noqa: BLE001 - reported
        Path(job + ".err").write_text(f"{type(e).__name__}: {e}",
                                      encoding="utf-8")
        return
    np.savez(job + ".out.npz", cv=cv, cf=cf, removed=removed, each=each)


def carve(verts, tris, cuts, *, timeout_s: float = CARVE_TIMEOUT_S,
          log=print) -> Carve:
    """Carve excavation cuts into a terrain surface, as a check (G.5).

    ``verts`` are ``(n, e, z)`` in model units; ``tris`` index them; each
    cut is a ``(base, top_base, z0, z1)`` frustum (see :func:`frustum`).
    The surface is closed into a solid and every cut subtracted with a
    manifold mesh boolean, in a child process so that a boolean that never
    returns is stopped after ``timeout_s``. Returns a :class:`Carve`: status
    ``carved`` with the closed solid and both volumes; ``boolean failed``
    when it raises or leaves no closed solid; ``timed out``; ``not asked``
    with no cuts. Raises :class:`CarveUnavailable` when the libraries are
    missing.

    A cut floating entirely above the terrain removes nothing — the
    existing-vs-future-ground classification is proven by the boolean, not
    asserted (see the module docstring).
    """
    if not cuts:
        return Carve(NOT_ASKED)
    try:
        import trimesh  # noqa: F401
        import manifold3d  # noqa: F401 — the boolean engine trimesh uses
    except Exception as e:
        raise CarveUnavailable(
            f"terrain carve asked for, but the mesh-boolean libraries are "
            f"missing ({e}): pip install \"bimforge[terrain]\"") from e
    import json
    import os
    import subprocess
    import sys
    import tempfile
    tv = np.array(verts, dtype="float64")
    top = np.column_stack([tv[:, 1], tv[:, 0], tv[:, 2]])   # (e, n, z)
    tf = np.array(tris, dtype="int64")
    with tempfile.TemporaryDirectory(prefix="bimforge-carve-") as tmp:
        job = str(Path(tmp) / "job.npz")
        np.savez(job, top=top, tf=tf,
                 cuts=json.dumps([list(c) for c in cuts]))
        # the child imports this bimforge, from the parent's own path
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
        try:
            subprocess.run(
                [sys.executable, "-c",
                 "import sys; from bimforge.terrain.solid import _worker; "
                 "_worker(sys.argv[1])", job],
                check=False, timeout=timeout_s, capture_output=True, env=env)
        except subprocess.TimeoutExpired:
            log(f"  terrain: carve timed out after {timeout_s:g} s "
                f"({len(cuts)} cuts); open surface")
            return Carve(TIMED_OUT, reason=f"over {timeout_s:g} s")
        err = Path(job + ".err")
        out = Path(job + ".out.npz")
        if not out.exists():
            why = (err.read_text(encoding="utf-8") if err.exists()
                   else "the carve process stopped with no answer")
            log(f"  terrain: mesh boolean failed ({why}); open surface")
            return Carve(BOOLEAN_FAILED, reason=why)
        with np.load(str(out)) as res:        # closed before tmp goes
            cv, cf = res["cv"], res["cf"]
            removed, each = float(res["removed"]), float(res["each"])
    out_v = [(float(y), float(x), float(z)) for x, y, z in cv]  # -> (n, e, z)
    out_t = [tuple(int(i) for i in f) for f in cf]
    log(f"  terrain: carve check, {len(cuts)} cuts take out {removed:.0f} "
        f"units^3 of existing ground ({each:.0f} cut by cut)")
    return Carve(CARVED, removed, each, out_v, out_t)
