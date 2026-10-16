"""Labelled contour polylines -> an existing-ground TIN (a terrain source).

Takes the contour polylines extracted off a plan sheet
(``bimforge.bim.plansheet.contours``) plus an anchors list (what the contour
labels actually say, read visually — a flattened plan set has no text layer),
attaches an elevation to every contour it can, triangulates, and scores the
result against spot elevations, each scored against a surface built
without it.

Elevation assignment happens in two tiers and the output says which tier
each contour came from:

  lettered    the contour carries a label read off the sheet.  Every vertex
              on it is as good as the plan's own lettering
              (:func:`assign_lettered`).
  inferred    unlabelled contour, assigned by :func:`propagate`: the one
              value every lettered contour and the pen role allow it
              (:func:`bimforge.terrain.reconcile.reconcile`), accepted only
              when interpolating between the two lettered contours that
              bracket it lands within ``snap_tol``.  Cheap resolution,
              weaker provenance.  Off by default — the caller opts in.

Spot elevations are never TIN vertices.  They are the scorecard
(:func:`score_against_spots`), which is the number worth quoting when
somebody asks how good the surface is.  The one opt-in exception is the
CLI's ``--spot-pins``: spots then also limit the contour ranges, which can
withdraw an inferred contour a spot contradicts (never add one), and with
``--propagate`` each spot is scored leave-one-out.

The result is an irregular TIN in plan world feet — not a ``TerrainGrid`` —
and :func:`tin_provenance` builds the Pset dict that rides it
(``SurveyGrade: False``: this is a plotted sheet's linework, not survey).

Polylines are ``(points Nx2, source, layer)`` records throughout; the
``source``/``layer`` pair keys fragment merging so a bridge never joins
across sheets or pen styles.  Dependency posture: scipy (Delaunay) is
required only by :func:`build_tin` and raises an actionable RuntimeError
naming the ``bimforge[terrain]`` extra when missing; everything else runs on
numpy alone (:func:`build_adjacency` uses scipy's cKDTree when present and a
brute-force scan otherwise).

Ported from the Work Tools contour-surface arc.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from bimforge.bim.plansheet.contours import bridge

__all__ = [
    "ContourTIN",
    "merge_fragments", "assign_lettered", "build_adjacency", "propagate",
    "check_index_labels", "find_misreads",
    "build_tin", "sample_tin",
    "score_against_spots", "score_stats",
    "tin_provenance",
    "flat_triangle_share", "TinFile", "save_tin_npz", "load_tin_npz",
]


# ------------------------------------------------------------------ assembly
def merge_fragments(polys, gap_ft, angle_deg, *, contact_ft=0.5, stats=None):
    """Rejoin one contour that the extraction left as several polylines.

    A contour is broken wherever the sheet interrupts it — most importantly
    at its own label gap, which is far wider than the dash gap the
    extraction's ``bridge`` already closes.  Left alone those fragments are
    separate graph nodes, so a single contour costs a hop and every
    neighbour count comes out too high.

    Reuses the extraction's end-to-end
    :func:`~bimforge.bim.plansheet.contours.bridge`, which only joins ends
    that point at each other; parallel neighbours fail that test even when
    they are closer than ``gap_ft``, which is what makes a generous gap safe
    here.  ``gap_ft <= 0`` is the off switch (identity).

    A join is **refused** when its connecting segment crosses, or comes
    within ``contact_ft`` of, any third line on any layer, or a join already
    made on another contour: contours cannot cross, and on a real sheet a 15 ft merge turned 4 raw crossings into
    121, nearly all of them on join segments between different contours.
    ``stats`` (a dict) receives ``refused``, the number of joins refused.
    """
    import numpy as np
    if stats is not None:
        stats["refused"] = 0
    if gap_ft <= 0:
        return polys

    def pts_of(p):
        return [tuple(float(c) for c in v)
                for v in np.asarray(p, dtype=float).reshape(-1, 2)]

    seg_owner: dict = {}
    for k, (p, _, _) in enumerate(polys):
        pts = pts_of(p)
        for u, v in zip(pts[:-1], pts[1:]):
            seg_owner.setdefault((u, v), set()).add(k)
            seg_owner.setdefault((v, u), set()).add(k)
    a, ab, owner = _segments(polys)

    def grazes_a_third_line(m, k):
        u, v = m[k], m[k + 1]
        joined: set = set()
        if k - 1 >= 0:
            joined |= seg_owner.get((m[k - 1], m[k]), set())
        if k + 2 <= len(m) - 1:
            joined |= seg_owner.get((m[k + 1], m[k + 2]), set())
        keep = ~np.isin(owner, sorted(joined))
        return bool(keep.any()) and float(
            _seg_dist(u, v, a[keep], ab[keep]).min()) < contact_ft

    by_layer: dict[tuple[str, str], list[int]] = {}
    for i, (_, src, lay) in enumerate(polys):
        by_layer.setdefault((src, lay), []).append(i)
    joins_a: list = []          # the joins made so far, as a + t*ab
    joins_ab: list = []

    def crosses_a_join(u, v):
        return bool(joins_a) and float(
            _seg_dist(u, v, joins_a, joins_ab).min()) < contact_ft

    out, refused = [], 0
    for (src, lay), idxs in by_layer.items():
        group = set(idxs)
        for m in bridge([pts_of(polys[i][0]) for i in idxs], gap_ft, angle_deg):
            piece, made = [m[0]], []
            for k in range(len(m) - 1):
                u, v = m[k], m[k + 1]
                # a segment of this layer's own fragments is not a join; one
                # that only another line owns (it lies exactly on the join)
                # still has to pass the check
                if u != v and not seg_owner.get((u, v), set()) & group:
                    if grazes_a_third_line(m, k) or crosses_a_join(u, v):
                        out.append((np.asarray(piece, dtype=float), src, lay))
                        piece, refused = [v], refused + 1
                        continue
                    made.append((u, v))
                piece.append(v)
            out.append((np.asarray(piece, dtype=float), src, lay))
            # this contour's joins now bind every later contour's
            for u, v in made:
                joins_a.append(u)
                joins_ab.append((v[0] - u[0], v[1] - u[1]))
    if stats is not None:
        stats["refused"] = refused
    return out


def _segments(polys):
    """Every polyline's segments as ``(a (S,2), ab (S,2), owner (S,))``.

    A single-vertex polyline is one zero-length segment, so it still has a
    distance; an empty one contributes nothing (it is never nearest).
    """
    import numpy as np
    a, b, owner = [], [], []
    for k, (p, _, _) in enumerate(polys):
        p = np.asarray(p, dtype=float).reshape(-1, 2)
        if len(p) == 0:
            continue
        if len(p) == 1:
            p = np.vstack([p, p])
        a.append(p[:-1])
        b.append(p[1:])
        owner.append(np.full(len(p) - 1, k))
    if not a:
        return np.zeros((0, 2)), np.zeros((0, 2)), np.zeros(0, dtype=int)
    a, b = np.vstack(a), np.vstack(b)
    return a, b - a, np.concatenate(owner)


def _line_distances(xy, segs, n):
    """Distance from ``xy`` to each of ``n`` polylines (inf when empty)."""
    import numpy as np
    a, ab, owner = segs
    d = np.full(n, np.inf)
    if len(a) == 0:
        return d
    ll = (ab ** 2).sum(axis=1)
    t = np.divide(((xy - a) * ab).sum(axis=1), ll,
                  out=np.zeros_like(ll), where=ll > 0)
    t = np.clip(t, 0.0, 1.0)
    seg_d = np.sqrt(((a + t[:, None] * ab - xy) ** 2).sum(axis=1))
    np.minimum.at(d, owner, seg_d)
    return d


def _seg_dist(p, q, a, ab):
    """Distance from segment ``p``-``q`` to each segment ``a + t*ab``: (S,)."""
    import numpy as np
    p, q = np.asarray(p, dtype=float), np.asarray(q, dtype=float)
    a = np.asarray(a, dtype=float).reshape(-1, 2)
    ab = np.asarray(ab, dtype=float).reshape(-1, 2)
    b, pq = a + ab, q - p

    def to_segs(x):                      # one point -> every segment
        ll = (ab ** 2).sum(axis=1)
        t = np.divide(((x - a) * ab).sum(axis=1), ll, out=np.zeros_like(ll),
                      where=ll > 0)
        t = np.clip(t, 0.0, 1.0)
        return np.sqrt(((a + t[:, None] * ab - x) ** 2).sum(axis=1))

    def to_pq(xs):                       # every point -> segment p-q
        ll = float((pq ** 2).sum())
        t = (np.clip(((xs - p) @ pq) / ll, 0.0, 1.0) if ll > 0
             else np.zeros(len(xs)))
        return np.sqrt(((p + t[:, None] * pq - xs) ** 2).sum(axis=1))

    d = np.minimum.reduce([to_segs(p), to_segs(q), to_pq(a), to_pq(b)])

    def cross(u, v):
        return u[..., 0] * v[..., 1] - u[..., 1] * v[..., 0]

    o1, o2 = cross(pq, a - p), cross(pq, b - p)
    o3, o4 = cross(ab, p - a), cross(ab, q - a)
    d[(o1 * o2 < 0) & (o3 * o4 < 0)] = 0.0
    return d


def assign_lettered(polys, labels, max_dist):
    """Attach each lettered value to its nearest polyline.

    A contour label sits in a gap the contour is broken for, so the correct
    parent is the nearest line — but only just: on a 1 ft interval the next
    contour over can be a couple of feet away, so ``max_dist`` is a real
    gate and an unmatched label is reported, never silently dropped.

    Distance is to the polyline's *segments*, not its vertices: extracted
    linework is sparse (a straight run is two vertices however long), so a
    vertex distance can hand a label to the wrong contour. It is the same
    measure ``label-crops`` records as the skeleton's ``dist_ft``.

    ``labels`` are ``{"elev": float, "xy": (e, n), "id"?: str}`` records in
    world feet. Returns ``(elev, rows)``: line-index -> elevation for the
    accepted labels, plus a per-label report row carrying the record ``id``
    (None when the anchors record has none), the nearest distance, the
    margin to the second-nearest line (the number that says how sure the
    match is), and a ``conflict`` elevation when two labels disagree about
    one line.
    """
    import numpy as np
    elev: dict[int, float] = {}
    rows = []
    segs = _segments(polys)
    for lab in labels:
        if not polys:
            rows.append({"id": lab.get("id"), "elev": lab["elev"],
                         "dist_ft": float("inf"), "line": None,
                         "margin_ft": float("inf"), "accepted": False})
            continue
        xy = np.asarray(lab["xy"], dtype=float)
        d = _line_distances(xy, segs, len(polys))
        i = int(np.argmin(d))
        near = float(d[i])
        ok = near <= max_dist
        second = float(np.partition(d, 1)[1]) if len(d) > 1 else float("inf")
        margin = second - near if math.isfinite(near) else float("inf")
        rows.append({"id": lab.get("id"), "elev": lab["elev"],
                     "dist_ft": near, "line": i,
                     "margin_ft": margin, "accepted": ok})
        if not ok:
            continue
        if i in elev and elev[i] != lab["elev"]:
            rows[-1]["accepted"] = False
            rows[-1]["conflict"] = elev[i]
            continue
        elev[i] = float(lab["elev"])
    return elev, rows


def build_adjacency(polys, min_votes=2):
    """Which contours are neighbours — nothing else lying between them.

    Every vertex votes for whichever *other* contour is closest to it.  On a
    slope the vertices on one flank all vote for the contour above and those
    on the other flank for the contour below, which is exactly the neighbour
    relation contour interpolation needs.  ``min_votes`` keeps a single
    stray vertex (a crossing leader, a hairpin) from inventing a neighbour.

    With scipy installed the vote costs one KD-tree query per vertex; the
    numpy fallback is a per-pair brute-force scan — quadratic, but plan-
    sheet contour sets are small enough, and it keeps the graph available on
    the base install.
    """
    import numpy as np
    if len(polys) < 2:
        return set()
    votes: dict[tuple[int, int], int] = {}

    def vote(me, other):
        key = (int(me), int(other)) if me < other else (int(other), int(me))
        votes[key] = votes.get(key, 0) + 1

    try:
        from scipy.spatial import cKDTree
    except ImportError:
        pts = [np.asarray(p, dtype=float) for p, _, _ in polys]
        for i, mine in enumerate(pts):
            best_d = np.full(len(mine), np.inf)
            best_j = np.full(len(mine), -1)
            for j, other in enumerate(pts):
                if j == i:
                    continue
                d = np.sqrt(((mine[:, None, :] - other[None, :, :]) ** 2)
                            .sum(axis=2)).min(axis=1)
                closer = d < best_d
                best_d[closer], best_j[closer] = d[closer], j
            for j in best_j:
                if j >= 0:
                    vote(i, j)
    else:
        xy = np.vstack([p for p, _, _ in polys])
        owner = np.concatenate([np.full(len(p), i)
                                for i, (p, _, _) in enumerate(polys)])
        tree = cKDTree(xy)
        k = min(48, len(xy))
        _, idx = tree.query(xy, k=k)
        pts_by_owner = [np.asarray(p, dtype=float) for p, _, _ in polys]
        for row, me, mine_xy in zip(np.atleast_2d(idx), owner, xy):
            for j in np.atleast_1d(row):
                other = owner[j]
                if other != me:
                    vote(me, other)
                    break
            else:
                # All k nearest belong to this vertex's own (dense) contour
                # — fall back to a brute nearest-other-contour scan for this
                # vertex so it still casts its vote (Copilot, PR #125).
                best_d, best_j = np.inf, -1
                for j2, other_pts in enumerate(pts_by_owner):
                    if j2 == me:
                        continue
                    d = np.sqrt(((other_pts - mine_xy) ** 2).sum(axis=1)).min()
                    if d < best_d:
                        best_d, best_j = d, j2
                if best_j >= 0:
                    vote(me, best_j)
    return {p for p, v in votes.items() if v >= min_votes}


def _hops(adj, n, sources):
    """Unweighted BFS hop counts: ``{source: {reachable line: hops}}``."""
    nbr: dict[int, set[int]] = {i: set() for i in range(n)}
    for a, b in adj:
        nbr[a].add(b)
        nbr[b].add(a)
    out = {}
    for s in sources:
        dist = {s: 0}
        frontier = [s]
        while frontier:
            nxt = []
            for u in frontier:
                for v in nbr[u]:
                    if v not in dist:
                        dist[v] = dist[u] + 1
                        nxt.append(v)
            frontier = nxt
        out[s] = dist
    return out


def _dist_to_line(pts, line):
    """Distance from each of ``pts`` (N,2) to the polyline ``line``: (N,)."""
    import numpy as np
    a, ab, _ = _segments([(line, None, None)])
    rel = np.asarray(pts, dtype=float).reshape(-1, 1, 2) - a[None, :, :]
    ll = (ab ** 2).sum(axis=1)
    t = np.divide((rel * ab).sum(axis=2), ll, out=np.zeros(rel.shape[:2]),
                  where=ll > 0)
    t = np.clip(t, 0.0, 1.0)
    return np.sqrt(((rel - t[..., None] * ab) ** 2).sum(axis=2)).min(axis=1)


def propagate(polys, elev, interval, *, snap_tol=0.35, roles=None,
              index_interval=None, reconciliation=None):
    """Assign unlabelled contours the one value the labels allow them.

    The candidate comes from :func:`bimforge.terrain.reconcile.reconcile`:
    every lettered contour limits every contour it reaches (neighbours
    differ by at most one ``interval``), the pen role filters the range, and
    only a contour left with exactly one value (``pinned``) is a candidate.
    That still assumes the neighbour graph is faithful, so the candidate is
    checked locally: among the lettered contours that reach it, the pair
    below and above its value that is spatially tightest (median summed
    distance over its vertices) is interpolated by distance at every vertex,
    and the candidate is REJECTED unless the median lands within
    ``snap_tol`` (ft). A contour off by one interval is a silent 1 ft error
    over its whole length. The chosen pair is also REJECTED unless its hop
    counts actually match the candidate value (``reach[a][i]·interval ==
    v - z_a`` and ``reach[b][i]·interval == z_b - v``, tolerance 1e-6): a
    dropped intermediate makes the two contours either side of the gap
    ``faces`` neighbours two intervals apart, which can pin the wrong
    (mirror-image) value while still interpolating inside ``[z_a, z_b]``.

    ``reconciliation`` reuses a :class:`~bimforge.terrain.reconcile.Reconciliation`
    the caller already built (the CLI does); otherwise one is built here
    from :func:`~bimforge.terrain.reconcile.neighbour_graph`.

    Returns ``(added, rows)``: ``added`` maps line-index -> elevation for the
    accepted contours (the caller merges it over the lettered dict, which is
    never mutated here); ``rows`` is the per-unlabelled-contour report with
    the provenance ``tier`` (``"inferred"`` when accepted, ``None``
    otherwise), the reconciled ``range`` and ``values``, the deciding pair
    (``between`` elevations and ``hops``), the interpolated value it was
    checked against (``trend``) and the rejection ``reason``:
    ``no-hop-path`` (no label reaches it), ``ambiguous``, ``conflict``,
    ``no-bracket`` (pinned, but no lettered value on one side of it),
    ``hop-count`` (the chosen bracket pair's hop counts do not match the
    candidate value — checked before ``snap-tol``) or ``snap-tol``.
    """
    import numpy as np

    from bimforge.terrain.reconcile import neighbour_graph, reconcile
    rec = reconciliation
    if rec is None:
        rec = reconcile(polys, neighbour_graph(polys), elev, interval,
                        roles=roles, index_interval=index_interval)
    added: dict[int, float] = {}
    rows = []
    for i in range(len(polys)):
        if i in elev:
            continue
        lr = rec.lines[i]
        row = {"line": i, "accepted": False, "tier": None, "elev": None,
               "between": None, "hops": None, "trend": None, "reason": None,
               "range": None if lr.lo is None else (lr.lo, lr.hi),
               "values": list(lr.values)}
        rows.append(row)
        if lr.status != "pinned":
            row["reason"] = {"unreached": "no-hop-path"}.get(lr.status, lr.status)
            continue
        v = float(lr.values[0])
        row["elev"] = v
        srcs = [a for a in elev if i in rec.reach.get(a, {})]
        below = [a for a in srcs if elev[a] < v - 1e-6]
        above = [a for a in srcs if elev[a] > v + 1e-6]
        pts = np.asarray(polys[i][0], dtype=float).reshape(-1, 2)
        dist: dict[int, Any] = {}
        best = None
        for a in below:
            for b in above:
                for k in (a, b):
                    if k not in dist:
                        dist[k] = _dist_to_line(pts, polys[k][0])
                w = dist[a] + dist[b]
                ok = w > 0
                if not ok.any():
                    continue
                width = float(np.median(w[ok]))
                if best is None or width < best[0]:
                    z_hat = float(np.median(
                        elev[a] + (elev[b] - elev[a]) * dist[a][ok] / w[ok]))
                    best = (width, z_hat, a, b)
        if best is None:
            row["reason"] = "no-bracket"
            continue
        _, z_hat, a, b = best
        ha, hb = rec.reach[a][i], rec.reach[b][i]
        row.update({"between": (elev[a], elev[b]),
                    "hops": (ha, hb),
                    "trend": z_hat})
        if (abs(ha * rec.interval - (v - elev[a])) > 1e-6
                or abs(hb * rec.interval - (elev[b] - v)) > 1e-6):
            row["reason"] = "hop-count"
            continue
        if abs(z_hat - v) > snap_tol:
            row["reason"] = "snap-tol"
            continue
        row["accepted"] = True
        row["tier"] = "inferred"
        added[i] = v
    return added, rows


# ------------------------------------------------------------- label checks
def check_index_labels(elev, index_lines, index_interval, *, tol=1e-6):
    """Lettered values on index contours must be multiples of the index interval.

    ``index_lines`` are the line ids whose manifest layer has
    ``role: index``. Returns ``(kept, rows)``: ``kept`` is ``elev`` without
    the violators, ``rows`` one report record per dropped value. No
    ``index_interval`` means no check.
    """
    if not index_interval:
        return dict(elev), []
    kept, rows = {}, []
    for i, z in elev.items():
        if i in index_lines:
            q = z / index_interval
            if abs(q - round(q)) * index_interval > tol:
                rows.append({"line": i, "elev": z, "check": "index-multiple",
                             "detail": f"{z:g} is not a multiple of the "
                                       f"{index_interval:g} ft index interval"})
                continue
        kept[i] = z
    return kept, rows


def find_misreads(polys, elev, interval, *, max_hops=6, tol=1e-6,
                  min_agreement=0.5, margins=None):
    """Lettered values that contradict the step count from their neighbours.

    Two lettered contours ``h`` hops apart agree when their values differ by
    exactly ``h`` intervals (the monotonic-run assumption ``propagate``
    makes). A value is flagged when at least two lettered neighbours within
    ``max_hops`` disagree with it, those neighbours agree with each other,
    and no lettered neighbour within two hops agrees with it — the last
    clause keeps a ridge or valley, where the assumption breaks, from
    flagging a correct label beside it. Flagged values are reported, not
    assigned: one lost label, never a wrong one.

    The rule presumes the hop graph is faithful, and on real linework it
    often is not (a contour missing from the extraction, or a crossing
    leader, shifts every count behind it). So before flagging, the other
    lettered pairs within ``max_hops`` are checked against their own hop
    counts: unless at least ``min_agreement`` of them agree, the value is
    reported as ``unverified-misread`` and kept — a check whose premise is
    measurably false must not remove a label; with no other pair in reach
    there is nothing to measure, so the value is kept then too.
    ``min_agreement=0`` is otherwise the ungated rule. ``margins``
    (line -> label match margin, ft) adds the
    margin to a ``likely-misread`` detail, since a wrong line match is an
    equally likely cause.
    """
    if not interval or len(elev) < 3:
        return []
    adj = build_adjacency(polys)
    if not adj:
        return []
    ids = sorted(elev)
    hops = _hops(adj, len(polys), ids)

    def agree(a, b):
        h = hops[a].get(b)
        return h is not None and abs(abs(elev[a] - elev[b]) - h * interval) <= tol

    rows = []
    for i in ids:
        near = [j for j in ids
                if j != i and hops[i].get(j) is not None and hops[i][j] <= max_hops]
        dis = [j for j in near if not agree(i, j)]
        close_ok = [j for j in near if agree(i, j) and hops[i][j] <= 2]
        consistent = all(agree(a, b) for a in dis for b in dis if a < b)
        if len(dis) >= 2 and not close_ok and consistent:
            vals = ", ".join(f"{elev[j]:g}" for j in dis[:4])
            pairs = [(a, b) for a in ids for b in ids
                     if a < b and i not in (a, b)
                     and hops[a].get(b) is not None and hops[a][b] <= max_hops]
            k, n = sum(1 for a, b in pairs if agree(a, b)), len(pairs)
            if n > 0 and k / n >= min_agreement:
                detail = f"disagrees with {len(dis)} lettered neighbours ({vals})"
                m = (margins or {}).get(i)
                if m is not None:
                    detail += (f"; its label matched this line by a {m:.2f} ft "
                               "margin — a wrong line match is as likely a cause")
                rows.append({"line": i, "elev": elev[i],
                             "check": "likely-misread", "detail": detail})
            else:
                rows.append({
                    "line": i, "elev": elev[i], "check": "unverified-misread",
                    "detail": f"would flag as a likely misread (disagrees with "
                              f"{len(dis)} lettered neighbours ({vals})), but "
                              f"hop counts agree for only {k}/{n} of the other "
                              f"lettered pairs within {max_hops} hops — kept"})
    return rows


# ------------------------------------------------------------------- the TIN
@dataclass
class ContourTIN:
    """An irregular contour-derived TIN.

    ``points[N, 3]`` — world-feet vertices; ``delaunay`` — the scipy
    triangulation (kept for point location); ``simplices`` — the kept
    triangles after the void filter; ``dropped`` — how many the filter
    removed.
    """

    points: Any
    delaunay: Any
    simplices: Any
    dropped: int


def build_tin(points_xyz, max_edge):
    """Delaunay over the plan projection, minus triangles that span voids.

    Delaunay always returns the convex hull, and contours leave real holes
    (unmapped areas, sheet edges), so any triangle whose longest edge
    exceeds ``max_edge`` (ft) is dropped rather than letting the surface
    invent ground across a void.
    """
    try:
        from scipy.spatial import Delaunay
    except ImportError as e:
        raise RuntimeError(
            "scipy is required for the contour-TIN terrain source — "
            'pip install "bimforge[terrain]"') from e
    import numpy as np
    p = np.asarray(points_xyz, dtype=float)
    xy = p[:, :2]
    tri = Delaunay(xy)
    simp = tri.simplices
    a, b, c = xy[simp[:, 0]], xy[simp[:, 1]], xy[simp[:, 2]]
    longest = np.maximum.reduce([
        np.linalg.norm(a - b, axis=1),
        np.linalg.norm(b - c, axis=1),
        np.linalg.norm(c - a, axis=1)])
    keep = longest <= max_edge
    return ContourTIN(p, tri, simp[keep], int((~keep).sum()))


def sample_tin(tin, query_xy):
    """Barycentric interpolation of the TIN at query points; NaN outside it.

    "Outside" includes inside a dropped void-spanning triangle — the surface
    refuses to answer where it has no contour support.
    """
    import numpy as np
    query_xy = np.asarray(query_xy, dtype=float)
    keep = set(map(tuple, np.sort(tin.simplices, axis=1).tolist()))
    out = np.full(len(query_xy), np.nan)
    found = tin.delaunay.find_simplex(query_xy)
    pts = tin.points
    for k, s in enumerate(found):
        if s < 0:
            continue
        verts = tin.delaunay.simplices[s]
        if tuple(np.sort(verts).tolist()) not in keep:
            continue
        p = pts[verts]
        m = np.array([[p[0, 0] - p[2, 0], p[1, 0] - p[2, 0]],
                      [p[0, 1] - p[2, 1], p[1, 1] - p[2, 1]]])
        try:
            lam = np.linalg.solve(m, query_xy[k] - p[2, :2])
        except np.linalg.LinAlgError:
            continue
        w = np.array([lam[0], lam[1], 1 - lam.sum()])
        out[k] = float((w * p[:, 2]).sum())
    return out


# ----------------------------------------------------------------- scorecard
def score_stats(errs):
    """Summary stats over spot residuals; ``None`` entries (spots outside
    the TIN) are excluded, and an empty scorecard reports ``n: 0`` with
    ``None`` stats rather than pretending to a number."""
    vals = [float(e) for e in errs if e is not None]
    if not vals:
        return {"n": 0, "mean": None, "mae": None, "rmse": None,
                "max_abs": None}
    n = len(vals)
    return {"n": n,
            "mean": sum(vals) / n,
            "mae": sum(abs(e) for e in vals) / n,
            "rmse": math.sqrt(sum(e * e for e in vals) / n),
            "max_abs": max(abs(e) for e in vals)}


def score_against_spots(tin, spots):
    """Score the TIN against spot elevations it was built without.

    Spot elevations are never TIN vertices — they are the scorecard, which is the
    number worth quoting when somebody asks how good the surface is.
    Feeding them into the TIN instead spends the scorecard: the delivery
    surface gets better and the quoted error stops meaning anything.

    ``spots`` are ``{"elev": float, "xy": (e, n)}`` records.  Returns
    ``{"rows", "stats"}``; each row carries the sampled TIN elevation and
    the signed error (TIN minus spot).  A spot outside the TIN (or over a
    dropped void) reports ``tin: None`` and is excluded from the stats
    rather than guessed at.
    """
    import numpy as np
    if not spots:
        return {"rows": [], "stats": score_stats([])}
    q = np.asarray([s["xy"] for s in spots], dtype=float)
    got = sample_tin(tin, q)
    rows = [{"elev": float(s["elev"]),
             "tin": None if np.isnan(g) else float(g),
             "err": None if np.isnan(g) else float(g - s["elev"])}
            for s, g in zip(spots, got)]
    return {"rows": rows, "stats": score_stats([r["err"] for r in rows])}


# ---------------------------------------------------------------- provenance
def tin_provenance(tiers, rmse, spacing_note):
    """The Pset dict that rides a contour-TIN terrain element.

    Same posture as :func:`bimforge.terrain.provenance.build_provenance` —
    terrain is reference geometry, ``SurveyGrade: False`` — but the honesty
    here is about elevations: ``ElevationTiers`` says how many contours were
    lettered (as good as the plan's own lettering) versus inferred
    (propagated, weaker), and ``SpotRMSE`` is the spot scorecard (each spot
    scored against a surface built without it).
    An unscored surface says so instead of carrying a silent blank.

    ``tiers`` is a ``{"lettered": n, "inferred": n}`` count dict; ``rmse``
    is the scorecard RMSE in feet (``None`` when no spot fell inside the
    TIN); ``spacing_note`` describes the vertex spacing (a TIN has no single
    cell size, so this is prose, e.g. ``"contour vertices thinned to 8 ft"``).
    """
    return {
        "Source": "plan-sheet contours",
        "ElevationTiers": " / ".join(f"{k} {v}" for k, v in dict(tiers).items()),
        "SpotRMSE": (float(rmse) if rmse is not None
                     else "unscored (no spot scored)"),
        "MeshSpacing": spacing_note,
        "SurveyGrade": False,
    }


# ---------------------------------------------------------- TIN file (v2)
_TIERS = ("lettered", "inferred")
_ROLE_CODE = {"intermediate": 0, "index": 1}
_ROLE_NAME = {0: "intermediate", 1: "index", -1: None}


def flat_triangle_share(points_xyz, simplices, point_line):
    """Share of the TIN's plan area in triangles on a single contour.

    A triangle whose three vertices all come from one contour is flat — the
    classic contour-TIN artifact along valleys and ridges. Measured and
    reported (spec §5), not repaired. ``0.0`` for an empty TIN.
    """
    import numpy as np
    P = np.asarray(points_xyz, dtype=float)
    S = np.asarray(simplices, dtype=int).reshape(-1, 3)
    if len(S) == 0:
        return 0.0
    L = np.asarray(point_line)
    a, b, c = P[S[:, 0], :2], P[S[:, 1], :2], P[S[:, 2], :2]
    area = 0.5 * np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1])
                        - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1]))
    flat = (L[S[:, 0]] == L[S[:, 1]]) & (L[S[:, 1]] == L[S[:, 2]])
    total = float(area.sum())
    return float(area[flat].sum()) / total if total > 0 else 0.0


@dataclass
class TinFile:
    """A contour TIN as ``est-bim contour-surface`` writes it (npz v1 or v2)."""

    points: Any
    simplices: Any
    info: dict
    lines: list
    point_line: Any = None


def save_tin_npz(path, points, simplices, info, lines, point_line):
    """Write a v2 TIN npz (arrays only — never pickle); returns the path."""
    import json

    import numpy as np
    out = str(path) if str(path).endswith(".npz") else f"{path}.npz"
    offsets = [0]
    for ln in lines:
        offsets.append(offsets[-1] + len(ln["points"]))
    line_points = (np.vstack([np.asarray(ln["points"], dtype=float).reshape(-1, 2)
                              for ln in lines]) if lines else np.zeros((0, 2)))
    meta = dict(info)
    meta["npz_version"] = 2
    meta["sources"] = [ln.get("source", "") for ln in lines]
    np.savez_compressed(
        out,
        points=np.asarray(points, dtype=float).reshape(-1, 3),
        simplices=np.asarray(simplices, dtype=np.int64).reshape(-1, 3),
        info=json.dumps(meta),
        line_points=line_points,
        line_offsets=np.asarray(offsets, dtype=np.int64),
        line_elev=np.asarray([ln["elev"] for ln in lines], dtype=float),
        line_tier=np.asarray([_TIERS.index(ln["tier"]) for ln in lines],
                             dtype=np.int8),
        line_role=np.asarray([_ROLE_CODE.get(ln.get("role"), -1) for ln in lines],
                             dtype=np.int8),
        point_line=np.asarray(point_line, dtype=np.int64))
    return out


def load_tin_npz(path) -> TinFile:
    """Read a TIN npz (``allow_pickle=False``); v1 files have no lines."""
    import json

    import numpy as np
    with np.load(path, allow_pickle=False) as d:
        info = json.loads(str(d["info"])) if "info" in d.files else {}
        points = np.asarray(d["points"], dtype=float)
        simplices = np.asarray(d["simplices"], dtype=np.int64)
        lines, point_line = [], None
        if "line_offsets" in d.files:
            lp, off = d["line_points"], d["line_offsets"]
            sources = info.get("sources", [])
            for k in range(len(off) - 1):
                lines.append({
                    "points": np.asarray(lp[off[k]:off[k + 1]], dtype=float),
                    "elev": float(d["line_elev"][k]),
                    "tier": _TIERS[int(d["line_tier"][k])],
                    "role": _ROLE_NAME[int(d["line_role"][k])],
                    "source": sources[k] if k < len(sources) else ""})
            point_line = np.asarray(d["point_line"], dtype=np.int64)
    return TinFile(points, simplices, info, lines, point_line)
