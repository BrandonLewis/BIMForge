"""Difference a plan-frame surface against a gridded terrain on one datum.

Compares an XYZ surface in the project frame (project CRS units, project
vertical datum — what the contour-TIN source writes) against a
:class:`~bimforge.terrain.grid.TerrainGrid` (metric grid, NAVD88 metres).
Both unit and datum conversions happen here, using the same cached NCAT
shift :func:`~bimforge.terrain.datum.ncat_vertshift` derives, so the two
surfaces are compared on one datum rather than by eye.

Sign convention: **plan minus terrain**. Positive means the plan surface
sits ABOVE the terrain — fill placed since the terrain was flown, or a plan
surface that is simply higher. Negative means the plan sits below it.

The terrain epoch matters more than the arithmetic. 3DEP holdings at a
given site are often a single flight republished as several products, so
check the acquisition year before reading a difference as change over time:
an 8-year gap makes this change detection, a same-year pair makes it an
accuracy check.

The optional difference map degrades: without matplotlib, ``plot_diff``
logs a line and returns ``False`` instead of raising (matplotlib lives in
the ``bimforge[draw]`` extra, not ``[terrain]``).

TIN vs TIN (``diff_tins``) samples two contour TINs on a common grid
through their own stored triangles — never a re-triangulation, so dropped
void triangles stay empty — and reports differences, never volumes: not a
pay quantity.

Ported from the Work surface_diff.py arc.
"""
from __future__ import annotations

M_PER_FT = 1200.0 / 3937.0          # the US survey foot

CSV_HEADER = "easting_m,northing_m,plan_navd88_m,terrain_navd88_m,delta_m"


def sample_grid(z, bbox_m, ex_m, ny_m):
    """Bilinear sample of a north-up grid whose row 0 is the ymax edge.

    Matches the package's own pixel-centre convention
    (``n = ymax - (r+0.5)*dy``, ``e = xmin + (c+0.5)*dx`` — see
    :func:`~bimforge.terrain.grid.grid_to_mesh`), so a value read here is
    the value that model would have used. Points outside the pixel-centre
    coverage, and samples whose 2x2 neighbourhood touches nodata (NaN or
    the huge-negative esri sentinel), come back NaN — never extrapolated.

    ``z`` is the ``(rows, cols)`` elevation array, ``bbox_m`` its
    ``(xmin, ymin, xmax, ymax)``; ``ex_m``/``ny_m`` are the metric sample
    coordinates. Returns an array of sampled elevations parallel to them.
    """
    import numpy as np
    z = np.asarray(z, dtype="float64")
    ex_m = np.atleast_1d(np.asarray(ex_m, dtype="float64"))
    ny_m = np.atleast_1d(np.asarray(ny_m, dtype="float64"))
    xmin, ymin, xmax, ymax = bbox_m
    rows, cols = z.shape
    dx = (xmax - xmin) / cols
    dy = (ymax - ymin) / rows
    fc = (ex_m - xmin) / dx - 0.5
    fr = (ymax - ny_m) / dy - 0.5
    c0 = np.floor(fc).astype(int)
    r0 = np.floor(fr).astype(int)
    tc = fc - c0
    tr = fr - r0
    out = np.full(len(ex_m), np.nan)
    ok = (r0 >= 0) & (c0 >= 0) & (r0 + 1 < rows) & (c0 + 1 < cols)
    if not ok.any():
        return out
    r0o, c0o, tro, tco = r0[ok], c0[ok], tr[ok], tc[ok]
    q = [z[r0o, c0o], z[r0o, c0o + 1], z[r0o + 1, c0o], z[r0o + 1, c0o + 1]]
    # esri nodata can land as a huge negative float rather than NaN.
    q = [np.where(np.isfinite(v) & (v > -1e10), v, np.nan) for v in q]
    val = ((1 - tro) * ((1 - tco) * q[0] + tco * q[1])
           + tro * ((1 - tco) * q[2] + tco * q[3]))
    out[ok] = val
    return out


def diff_surface(points_xyz_prj, grid, *, unit_scale_to_m, vshift_m):
    """Per-point plan-minus-terrain differences on one datum (NAVD88 metres).

    ``points_xyz_prj`` — ``(N, 3)`` surface points in the project frame
    (project CRS units, project vertical datum); ``grid`` — a
    :class:`~bimforge.terrain.grid.TerrainGrid` (NAVD88 metres) in the same
    horizontal CRS; ``unit_scale_to_m`` — metres per project unit (e.g.
    :data:`M_PER_FT` for a ftUS frame); ``vshift_m`` — the project vertical
    datum -> NAVD88 shift in metres (the cached NCAT shift; ``0.0`` when the
    plan is already NAVD88).

    Returns an ``(N, 5)`` array ``(e_m, n_m, plan_navd88_m,
    terrain_navd88_m, delta_m)`` parallel to the input points — off-grid
    and nodata points carry NaN terrain/delta rather than being dropped.
    ``delta_m`` is plan minus terrain: positive = the plan sits above.
    """
    import numpy as np
    P = np.asarray(points_xyz_prj, dtype="float64")
    e_m = P[:, 0] * unit_scale_to_m
    n_m = P[:, 1] * unit_scale_to_m
    plan_m = P[:, 2] * unit_scale_to_m + vshift_m
    terrain_m = sample_grid(grid.z, grid.bbox_m, e_m, n_m)
    delta_m = plan_m - terrain_m                # plan minus terrain
    return np.column_stack([e_m, n_m, plan_m, terrain_m, delta_m])


def write_diff_csv(rows, path, *, log=print):
    """Write ``diff_surface`` rows to a CSV (header, mm precision).

    Rows with a non-finite delta (off-grid / nodata points) are dropped —
    the CSV holds only real comparisons. Returns the number written.
    """
    import numpy as np
    from pathlib import Path
    rows = np.asarray(rows, dtype="float64")
    ok = np.isfinite(rows[:, 4])
    np.savetxt(Path(path), rows[ok], delimiter=",", header=CSV_HEADER,
               comments="", fmt="%.3f")
    log(f"  terrain diff: wrote {int(ok.sum())}/{len(rows)} rows to {path}")
    return int(ok.sum())


def _import_pyplot():
    """The matplotlib import seam (tests monkeypatch THIS). Agg backend —
    file output only, no display needed."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def plot_diff(rows, path, *, log=print,
             label="plan − terrain, m  (+ = plan is higher)", unit="m"):
    """Render ``diff_surface`` (or ``diff_tins``) rows as a difference map PNG.

    Diverging colours symmetric about zero (limits at the 98th percentile of
    |delta| so a few outliers do not wash the map out). Degrades without
    matplotlib: logs a line and returns ``False`` instead of raising —
    matplotlib is the ``bimforge[draw]`` extra, optional here. Returns
    ``True`` when the PNG was written. ``label``/``unit`` default to
    reproduce the original plan-vs-terrain output.
    """
    import numpy as np
    try:
        plt = _import_pyplot()
    except ImportError:
        log("  terrain diff: matplotlib not installed — skipping the PNG "
            '(pip install "bimforge[draw]")')
        return False
    rows = np.asarray(rows, dtype="float64")
    ok = rows.size and np.isfinite(rows[:, 4])
    if not np.any(ok):
        log("  terrain diff: no finite deltas to plot — skipping the PNG")
        return False
    d = rows[ok, 4]
    lim = float(np.nanpercentile(np.abs(d), 98)) or 1.0
    fig, ax = plt.subplots(figsize=(15, 8))
    s = ax.scatter(rows[ok, 0], rows[ok, 1], c=d, cmap="RdBu_r",
                   vmin=-lim, vmax=lim, s=9)
    fig.colorbar(s, ax=ax, label=label)
    ax.set_aspect("equal")
    ax.set_xlabel(f"Easting, {unit}")
    ax.set_ylabel(f"Northing, {unit}")
    fig.tight_layout()
    fig.savefig(path, dpi=90)
    plt.close(fig)
    log(f"  terrain diff: wrote {path}")
    return True


TIN_CSV_HEADER = "x,y,z_surface,z_against,delta"


def sample_mesh(points_xyz, simplices, query_xy, *, cell=None):
    """Barycentric z at query points over an explicit triangle list.

    NaN outside the mesh — including inside any triangle the TIN dropped as
    void-spanning, because this samples the stored triangles rather than
    re-triangulating the points. Triangles are bucketed on a grid (cell =
    the median triangle extent unless given) so each query tests only its
    own cell. Pure numpy.
    """
    import numpy as np
    P = np.asarray(points_xyz, dtype=float).reshape(-1, 3)
    S = np.asarray(simplices, dtype=int).reshape(-1, 3)
    Q = np.asarray(query_xy, dtype=float).reshape(-1, 2)
    out = np.full(len(Q), np.nan)
    if len(S) == 0 or len(Q) == 0:
        return out
    tri = P[S]
    lo = tri[:, :, :2].min(axis=1)
    hi = tri[:, :, :2].max(axis=1)
    if cell is None:
        span = hi - lo
        cell = float(max(np.median(np.maximum(span[:, 0], span[:, 1])), 1e-9))
    origin = lo.min(axis=0)
    i0 = np.floor((lo - origin) / cell).astype(int)
    i1 = np.floor((hi - origin) / cell).astype(int)
    buckets: dict = {}
    for t in range(len(S)):
        for ix in range(i0[t, 0], i1[t, 0] + 1):
            for iy in range(i0[t, 1], i1[t, 1] + 1):
                buckets.setdefault((ix, iy), []).append(t)
    qi = np.floor((Q - origin) / cell).astype(int)
    for k in range(len(Q)):
        cand = buckets.get((int(qi[k, 0]), int(qi[k, 1])))
        if not cand:
            continue
        qx, qy = Q[k]
        for t in cand:
            (ax, ay, az), (bx, by, bz), (cx, cy, cz) = tri[t]
            det = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
            # a sliver (twice its area next to nothing against its squared
            # edges) covers no ground and only amplifies rounding into z
            scale = (ax - cx) ** 2 + (ay - cy) ** 2 + (bx - cx) ** 2 \
                + (by - cy) ** 2
            if abs(det) <= 1e-9 * scale:
                continue
            l1 = ((by - cy) * (qx - cx) + (cx - bx) * (qy - cy)) / det
            l2 = ((cy - ay) * (qx - cx) + (ax - cx) * (qy - cy)) / det
            l3 = 1.0 - l1 - l2
            if l1 >= -1e-9 and l2 >= -1e-9 and l3 >= -1e-9:
                out[k] = l1 * az + l2 * bz + l3 * cz
                break
    return out


def diff_tins(a, b, *, step):
    """``a`` minus ``b`` on a ``step`` grid over the two TINs' shared bbox.

    ``a``/``b`` expose ``points`` (N, 3) and ``simplices`` (M, 3) (a
    ``TinFile``). Returns rows ``(x, y, z_a, z_b, z_a - z_b)`` only where both
    surfaces exist; ``(0, 5)`` when they do not overlap.
    """
    import numpy as np
    pa = np.asarray(a.points, dtype=float)
    pb = np.asarray(b.points, dtype=float)
    x0, x1 = max(pa[:, 0].min(), pb[:, 0].min()), min(pa[:, 0].max(), pb[:, 0].max())
    y0, y1 = max(pa[:, 1].min(), pb[:, 1].min()), min(pa[:, 1].max(), pb[:, 1].max())
    if x1 < x0 or y1 < y0:
        return np.zeros((0, 5))
    xs = np.arange(x0, x1 + step / 2.0, step)
    ys = np.arange(y0, y1 + step / 2.0, step)
    gx, gy = np.meshgrid(xs, ys)
    q = np.column_stack([gx.ravel(), gy.ravel()])
    za = sample_mesh(pa, a.simplices, q)
    zb = sample_mesh(pb, b.simplices, q)
    ok = np.isfinite(za) & np.isfinite(zb)
    return np.column_stack([q[ok], za[ok], zb[ok], za[ok] - zb[ok]])


def summarize_tin_diff(rows, *, step, tie_tol, zones=()):
    """Difference statistics — shared footprint, tie-in share, per zone.

    ``within_tie_tol`` is the share of the shared footprint where the two
    surfaces agree within ``tie_tol`` (the tie-in / daylight zone). Not a
    pay quantity: there are no volumes here.
    """
    import numpy as np

    def stats(d):
        if len(d) == 0:
            return {"n": 0, "area_sqft": 0.0, "within_tie_tol": None,
                    "mean": None, "median": None, "sd": None,
                    "min": None, "max": None}
        return {"n": int(len(d)), "area_sqft": float(len(d) * step * step),
                "within_tie_tol": float(np.mean(np.abs(d) <= tie_tol)),
                "mean": float(d.mean()), "median": float(np.median(d)),
                "sd": float(d.std()), "min": float(d.min()), "max": float(d.max())}

    rows = np.asarray(rows, dtype=float).reshape(-1, 5)
    out = {"all": stats(rows[:, 4]), "zones": {}}
    if len(zones):
        from shapely import contains_xy
        from shapely.geometry import Polygon
        for z in zones:
            inside = contains_xy(Polygon(z["polygon"]), rows[:, 0], rows[:, 1])
            out["zones"][z["name"]] = stats(rows[inside, 4])
    return out


def write_tin_diff_csv(rows, path, *, log=print):
    """Write ``diff_tins`` rows (header ``TIN_CSV_HEADER``); returns the count."""
    import numpy as np
    from pathlib import Path
    rows = np.asarray(rows, dtype=float).reshape(-1, 5)
    np.savetxt(Path(path), rows, delimiter=",", header=TIN_CSV_HEADER,
               comments="", fmt="%.3f")
    log(f"  surface diff: wrote {len(rows)} rows to {path}")
    return len(rows)
