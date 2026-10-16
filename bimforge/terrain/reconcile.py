"""Contour reconciliation: which contours are neighbours, what every label
allows each contour to be, and where the linework does not add up.

Redrawing a plan sheet is plan verification. This module turns extracted
contour polylines (``(points Nx2, source, layer)`` records, as in
:mod:`bimforge.terrain.contours`) into:

  :func:`neighbour_graph`  which contours face each other across open
                           ground (``faces``: values differ by at most one
                           interval), which are one contour (``same``:
                           duplicate linework; ``joints``: a contour broken
                           into pieces), and which touch or cross
                           (``contacts`` — no limit, a finding).
  :func:`reconcile`        every lettered contour limits every contour it
                           reaches (``|z - z_a| <= hops * interval``); the
                           intersection, filtered by the pen role, pins,
                           leaves ambiguous, or empties each contour's range.
  :func:`build_findings`   located findings for a person to review.

numpy only; scipy's cKDTree speeds the neighbour search when installed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = ["Contact", "NeighbourGraph", "neighbour_graph", "LineRange",
          "Reconciliation", "reconcile", "CHECKS", "Finding", "build_findings"]

_EPS = 1e-6
_END_FT = 1.0          # within this (along its line) of an end is "at the end"
_PIN_TIE_FT = 1e-6     # two lines this close to equidistant from a spot tie


def _densify(points, step):
    """``points`` resampled so no segment is longer than ``step``: (M, 2)."""
    import numpy as np
    p = np.asarray(points, dtype=float).reshape(-1, 2)
    if len(p) < 2:
        return p
    out = [p[:1]]
    for a, b in zip(p[:-1], p[1:]):
        k = max(1, int(math.ceil(math.dist(a, b) / step)))
        out.append(a + (np.arange(1, k + 1) / k)[:, None] * (b - a))
    return np.vstack(out)


def _arc(p):
    """Cumulative length along ``p`` (M, 2): (M,)."""
    import numpy as np
    if len(p) < 2:
        return np.zeros(len(p))
    step = np.sqrt((np.diff(p, axis=0) ** 2).sum(axis=1))
    return np.concatenate([[0.0], np.cumsum(step)])


def _length(points):
    import numpy as np
    p = np.asarray(points, dtype=float).reshape(-1, 2)
    return float(_arc(p)[-1]) if len(p) > 1 else 0.0


def _centre(points):
    import numpy as np
    p = np.asarray(points, dtype=float).reshape(-1, 2)
    return (float(p[:, 0].mean()), float(p[:, 1].mean()))


def _near_ends(p):
    """True where a point of ``p`` lies within ``_END_FT`` of either end."""
    import numpy as np
    if len(p) == 0:
        return np.zeros(0, dtype=bool)
    a = _arc(p)
    return (a <= _END_FT) | (a[-1] - a <= _END_FT)


_VERTEX_FT = 1e-6     # a point this close to a vertex is at it; closer points are one


def _closed(line):
    """``line`` ends where it starts: a closed contour, whose seam is a vertex."""
    return len(line) > 2 and math.dist(line[0], line[-1]) <= _VERTEX_FT


def _distinct_neighbours(line, v, x):
    """The nearest points of ``line`` before/after its vertex ``v`` that lie
    more than ``_VERTEX_FT`` from ``x`` (the touching point, within
    ``_VERTEX_FT`` of ``line[v]``) — skipping duplicate vertices and
    shorter-than-tolerance segments. A closed line wraps across its seam.
    ``None`` where no such point exists in that direction: ``v`` is
    effectively ``line``'s own end there.
    """
    n, closed = len(line), _closed(line)

    def walk(step):
        k = v
        for _ in range(n):
            k += step
            if not 0 <= k < n:
                if not closed:
                    return None
                k %= n
            if math.dist(line[k], x) > _VERTEX_FT:
                return line[k]
        return None

    return walk(-1), walk(1)


def _rays_at(line, seg, x):
    """The two points a ray from the touching point ``x`` on ``line``'s
    segment ``seg`` can aim at. ``x`` within ``_VERTEX_FT`` of either end
    of the segment is *at* that vertex (the nearer one, however short the
    segment): the vertex's distinct neighbours (see
    :func:`_distinct_neighbours`). Otherwise ``x`` is interior: the
    segment's own endpoints. Every point returned lies more than
    ``_VERTEX_FT`` from ``x``, so no ray is degenerate. ``None`` for a side
    that runs off the end of an open polyline — a touch there is an end
    (a T), never a crossing.
    """
    d0, d1 = math.dist(x, line[seg]), math.dist(x, line[seg + 1])
    if min(d0, d1) <= _VERTEX_FT:
        return _distinct_neighbours(line, seg if d0 <= d1 else seg + 1, x)
    return line[seg], line[seg + 1]


def _interleaved(rp1, rp2, rq1, rq2):
    """True iff, sweeping the plane around their common point, ``p``'s two
    rays and ``q``'s two rays alternate — ``q``'s rays split the circle
    into two open arcs with one ``p`` ray in each. Symmetric in p/q by
    construction (it only asks whether the four directions alternate), so
    it cannot depend on which polyline is passed first. A ray of ``p``
    running in the exact same direction as a ray of ``q`` (a shared
    stretch) is never a proper crossing.
    """
    import math
    ap1, ap2 = math.atan2(rp1[1], rp1[0]), math.atan2(rp2[1], rp2[0])
    aq1, aq2 = math.atan2(rq1[1], rq1[0]), math.atan2(rq2[1], rq2[0])

    def same_direction(a, b):
        d = abs(a - b)
        return d < _EPS or abs(d - 2 * math.pi) < _EPS

    if (same_direction(ap1, aq1) or same_direction(ap1, aq2)
            or same_direction(ap2, aq1) or same_direction(ap2, aq2)):
        return False
    order = sorted([(ap1, "p"), (ap2, "p"), (aq1, "q"), (aq2, "q")])
    labels = [label for _, label in order]
    return all(labels[k] != labels[(k + 1) % 4] for k in range(4))


_PAIR_CHUNK = 1 << 20      # candidate segment pairs generated at a time


def _segment_pairs(p, q):
    """The segment pairs of polylines ``p`` and ``q`` whose bounding boxes
    overlap (within ``_VERTEX_FT``) — every pair that can touch or cross —
    yielded as ``(i, j)`` index arrays a chunk at a time, in ``i`` then
    ``j`` order across the chunks, so nothing ever holds the ``|p|·|q|``
    table or even every candidate at once.

    A sweep along the axis the two lines spread over most: with ``q``'s
    segments sorted by their low end, a segment of ``p`` can only meet those
    whose low end lies between its own low end less the widest ``q``
    segment and its own high end; that window is then box-tested. Rows are
    batched up to ``_PAIR_CHUNK`` window entries; a single window wider
    than that (one long segment) is box-tested a chunk at a time, keeping
    only its matches.
    """
    import numpy as np
    pa, pb, qa, qb = p[:-1], p[1:], q[:-1], q[1:]
    plo = np.minimum(pa, pb) - _VERTEX_FT
    phi = np.maximum(pa, pb) + _VERTEX_FT
    qlo, qhi = np.minimum(qa, qb), np.maximum(qa, qb)
    both = np.vstack([p, q])
    ax = int(np.argmax(both.max(axis=0) - both.min(axis=0)))
    order = np.argsort(qlo[:, ax], kind="stable")
    keys = qlo[order, ax]
    widest = float((qhi[:, ax] - qlo[:, ax]).max())
    start = np.searchsorted(keys, plo[:, ax] - widest, side="left")
    stop = np.searchsorted(keys, phi[:, ax], side="right")
    counts = np.maximum(stop - start, 0)
    total = np.cumsum(counts)

    def boxed(ii, jj):
        keep = ((plo[ii, 0] <= qhi[jj, 0]) & (qlo[jj, 0] <= phi[ii, 0])
                & (plo[ii, 1] <= qhi[jj, 1]) & (qlo[jj, 1] <= phi[ii, 1]))
        return ii[keep], jj[keep]

    r0 = 0
    while r0 < len(pa):
        if counts[r0] > _PAIR_CHUNK:          # one window alone is too wide
            got = [boxed(np.full(k1 - k0, r0), order[k0:k1])[1]
                   for k0 in range(int(start[r0]), int(stop[r0]), _PAIR_CHUNK)
                   for k1 in (min(k0 + _PAIR_CHUNK, int(stop[r0])),)]
            jj = np.sort(np.concatenate(got))
            if len(jj):
                yield np.full(len(jj), r0), jj
            r0 += 1
            continue
        done = int(total[r0 - 1]) if r0 else 0
        r1 = max(r0 + 1, int(np.searchsorted(total, done + _PAIR_CHUNK,
                                             side="right")))
        n = counts[r0:r1]
        if n.sum():
            ii = np.repeat(np.arange(r0, r1), n)
            offs = np.arange(int(n.sum())) - np.repeat(np.cumsum(n) - n, n)
            ii, jj = boxed(ii, order[np.repeat(start[r0:r1], n) + offs])
            if len(ii):
                s = np.lexsort((jj, ii))
                yield ii[s], jj[s]
        r0 = r1


def _crossing(p, q):
    """A point where polylines ``p`` and ``q`` properly cross, else None.

    Candidates come from a relaxed segment-pair test (``<=0``, not ``<0``)
    over the pairs whose bounding boxes overlap (:func:`_segment_pairs`):
    a shared or grid-aligned vertex often lands exactly on the other line,
    which the strict test alone would miss (collinear pairs — all four
    endpoints within ``_VERTEX_FT`` of the other segment's line — are
    excluded outright). Each candidate point is then judged by splitting
    both polylines there and looking at the four local *directions* leaving
    it (each polyline's real neighbouring vertices, not a chord that would
    skip a bend): it is a proper crossing iff ``q``'s two rays separate
    ``p``'s two rays into different arcs of the circle (see
    :func:`_interleaved`) — a touch that lands on a vertex and turns back
    leaves both of the other line's rays in the same arc.

    Whether the point is *at* a vertex is decided by distance alone
    (``_VERTEX_FT``, the same tolerance that merges near-duplicate points
    and that de-duplicates candidates), never by a segment parameter, so a
    segment of any length — however short — gives the same verdict from
    either of its ends, and a closed line's seam is an ordinary vertex. The
    verdict is therefore symmetric in ``p``/``q`` and independent of the
    direction either polyline runs.
    """
    import numpy as np
    p = np.asarray(p, dtype=float).reshape(-1, 2)
    q = np.asarray(q, dtype=float).reshape(-1, 2)
    if len(p) < 2 or len(q) < 2:
        return None
    def orient(o, s, t):
        return ((s[..., 0] - o[..., 0]) * (t[..., 1] - o[..., 1])
                - (s[..., 1] - o[..., 1]) * (t[..., 0] - o[..., 0]))

    seen: list = []            # touching points already judged
    for ii, jj in _segment_pairs(p, q):          # chunks, in (i, j) order
        a0, a1, b0, b1 = p[ii], p[ii + 1], q[jj], q[jj + 1]
        o1, o2 = orient(a0, a1, b0), orient(a0, a1, b1)
        o3, o4 = orient(b0, b1, a0), orient(b0, b1, a1)
        # |orient| over a segment's length is a distance from its line
        la = np.sqrt(((a1 - a0) ** 2).sum(axis=-1))
        lb = np.sqrt(((b1 - b0) ** 2).sum(axis=-1))
        collinear = ((np.abs(o1) <= _VERTEX_FT * la)
                     & (np.abs(o2) <= _VERTEX_FT * la)
                     & (np.abs(o3) <= _VERTEX_FT * lb)
                     & (np.abs(o4) <= _VERTEX_FT * lb))
        hit = np.flatnonzero((o1 * o2 <= 0) & (o3 * o4 <= 0) & ~collinear)
        for c in hit:
            i, j = int(ii[c]), int(jj[c])
            d34 = o3[c] - o4[c]            # = cross(p's segment, q's segment)
            if abs(d34) <= 1e-12 * float(la[c] * lb[c]):
                continue      # parallel: a touching pair would be collinear
            x = p[i] + (o3[c] / d34) * (p[i + 1] - p[i])
            if any(math.dist(x, s) <= _VERTEX_FT for s in seen):
                continue

            p_prev, p_next = _rays_at(p, i, x)
            q_prev, q_next = _rays_at(q, j, x)
            if any(r is None for r in (p_prev, p_next, q_prev, q_next)):
                continue       # a line ends exactly at the touch: not a cross
            seen.append(x)     # judged from four real (non-degenerate) rays

            if _interleaved(p_prev - x, p_next - x, q_prev - x, q_next - x):
                return (float(x[0]), float(x[1]))
    return None


def _nearest_others(S, i, xy, own, tree):
    """For each sample in ``S``, the distance to the nearest point of any
    line other than ``i``, and the target index of each line tied at it.

    ``xy``/``own`` are every line's densified points and their line ids;
    ``tree`` is a cKDTree over ``xy`` or None (numpy scan).
    """
    import numpy as np
    d_out = np.full(len(S), np.inf)
    t_out: list = [[] for _ in range(len(S))]

    def settle(row, d, j):
        other = own[j] != i
        if not other.any():
            return False
        d, j = d[other], j[other]
        d0 = float(d.min())
        best: dict = {}
        for dd, jj in zip(d, j):
            if dd <= d0 + _EPS and own[jj] not in best:
                best[own[jj]] = int(jj)
        d_out[row], t_out[row] = d0, list(best.values())
        return True

    todo = list(range(len(S)))
    k = 16
    while todo and tree is not None and k <= 4096:
        kk = min(k, len(xy))
        rest = []
        for c in range(0, len(todo), 256):          # bounded memory per query
            rows = todo[c:c + 256]
            d, j = tree.query(S[rows], k=kk)
            d = np.asarray(d).reshape(len(rows), -1)
            j = np.asarray(j).reshape(len(rows), -1)
            rest += [row for r, row in enumerate(rows)
                     if not settle(row, d[r], j[r])]
        if kk == len(xy):
            return d_out, t_out          # no other line anywhere
        todo, k = rest, k * 4
    if todo:
        others = np.flatnonzero(own != i)
        if len(others) == 0:
            return d_out, t_out
        P = xy[others]
        for row in todo:
            d = np.sqrt(((P - S[row]) ** 2).sum(axis=1))
            settle(row, d, others)
    return d_out, t_out


@dataclass
class Contact:
    """Two contours closer than ``contact_ft``: they touch or cross."""

    pair: tuple
    kind: str            # "cross" | "touch"
    length_ft: float
    xy: tuple


@dataclass
class NeighbourGraph:
    """The neighbour relation between ``n`` contours (see :func:`neighbour_graph`)."""

    n: int
    faces: set = field(default_factory=set)
    same: set = field(default_factory=set)
    joints: set = field(default_factory=set)
    contacts: list = field(default_factory=list)
    params: dict = field(default_factory=dict)

    def adjacency(self):
        """``{line: [(neighbour, hops)]}`` — ``faces`` cost 1, ``same`` 0."""
        nbr: dict = {i: [] for i in range(self.n)}
        for a, b in sorted(self.faces):
            nbr[a].append((b, 1))
            nbr[b].append((a, 1))
        for a, b in sorted(self.same):
            nbr[a].append((b, 0))
            nbr[b].append((a, 0))
        return nbr


def neighbour_graph(polys, *, sample_ft=1.0, contact_ft=0.5, min_facing_ft=4.0,
                    target_ft=0.5) -> NeighbourGraph:
    """Which contours face each other, which are one contour, which touch.

    Every line is sampled every ``sample_ft``; each sample finds the nearest
    point on any *other* line (targets densified to ``target_ft``, so the
    distance is within ``target_ft / 2`` of the segment distance). A vote
    cannot skip a line: any line crossing the connector would be nearer.
    A sample votes **contact** when that point is closer than ``contact_ft``,
    is ignored when the point is the other line's end (end-on), and votes
    **facing** otherwise; exact ties vote for every tied line.

    Pairs, decided in this order: ``same`` (same source and layer, contact
    over >= 50% of the shorter line — duplicate linework, one contour),
    ``joints`` (same source and layer, contact only where both lines end — a
    contour broken into pieces), a ``cross`` contact (the polylines properly
    intersect), a ``touch`` contact (>= 2 ft of contact otherwise), and
    ``faces`` (>= ``min_facing_ft`` of facing votes and none of the above).
    A ``cross`` pair, or one with >= 2 ft of contact, is never ``faces``: at
    a vertical face the one-interval rule fails, and a limit we cannot trust
    is worse than none. Every candidate ``faces`` pair is crossing-tested,
    so a steep crossing that falls between samples (no contact vote at all)
    is still a ``cross`` (with ``length_ft`` 0). A shorter graze that does
    not cross — a single-point V-touch — can still be ``faces``.
    """
    import numpy as np
    n = len(polys)
    g = NeighbourGraph(n=n, params={"sample_ft": sample_ft,
                                    "contact_ft": contact_ft,
                                    "min_facing_ft": min_facing_ft})
    if n < 2:
        return g
    dense = [_densify(p, target_ft) for p, _, _ in polys]
    xy = np.vstack([d for d in dense if len(d)])
    own = np.concatenate([np.full(len(d), k) for k, d in enumerate(dense)])
    at_end = np.concatenate([
        (np.arange(len(d)) == 0) | (np.arange(len(d)) == len(d) - 1)
        for d in dense])
    near_end = np.concatenate([_near_ends(d) for d in dense])
    try:
        from scipy.spatial import cKDTree
        tree = cKDTree(xy)
    except ImportError:
        tree = None

    facing: dict = {}
    contact: dict = {}      # (i, o) directed -> [(x, y, i_near_end, o_near_end)]
    for i, (p, _, _) in enumerate(polys):
        S = _densify(p, sample_ft)
        if len(S) == 0:
            continue
        s_end = _near_ends(S)
        d0, tied = _nearest_others(S, i, xy, own, tree)
        for k in range(len(S)):
            if not math.isfinite(d0[k]):
                continue
            for t in tied[k]:
                o = int(own[t])
                if d0[k] < contact_ft:
                    contact.setdefault((i, o), []).append(
                        (float(S[k, 0]), float(S[k, 1]),
                         bool(s_end[k]), bool(near_end[t])))
                elif not at_end[t]:
                    key = (min(i, o), max(i, o))
                    facing[key] = facing.get(key, 0) + 1

    lengths = [max(_length(p), sample_ft) for p, _, _ in polys]
    for a, b in sorted({(min(i, o), max(i, o)) for i, o in contact}):
        ab, ba = contact.get((a, b), []), contact.get((b, a), [])
        votes = ab + ba
        same_layer = tuple(polys[a][1:]) == tuple(polys[b][1:])
        short, other = (a, b) if lengths[a] <= lengths[b] else (b, a)
        covered = len(contact.get((short, other), [])) * sample_ft
        if same_layer and covered >= 0.5 * lengths[short]:
            g.same.add((a, b))
            continue
        if same_layer and all(v[2] and v[3] for v in votes):
            g.joints.add((a, b))
            continue
        length = max(len(ab), len(ba)) * sample_ft
        x = _crossing(polys[a][0], polys[b][0])
        if x is not None:
            g.contacts.append(Contact((a, b), "cross", length, x))
            continue
        if length >= 2.0:
            pts = np.array([(v[0], v[1]) for v in votes])
            g.contacts.append(Contact((a, b), "touch", length,
                                      (float(pts[:, 0].mean()),
                                       float(pts[:, 1].mean()))))
    blocked = g.same | g.joints | {c.pair for c in g.contacts}
    checked = {(min(i, o), max(i, o)) for i, o in contact}   # crossing-tested above
    for a, b in sorted(facing):
        if facing[(a, b)] * sample_ft < min_facing_ft or (a, b) in blocked:
            continue
        if (a, b) not in checked:
            # a steep crossing can fall between samples, every one of them
            # >= contact_ft from the other line: no contact vote, still a cross
            x = _crossing(polys[a][0], polys[b][0])
            if x is not None:
                g.contacts.append(Contact((a, b), "cross", 0.0, x))
                continue
        g.faces.add((a, b))
    g.contacts.sort(key=lambda c: c.pair)
    return g


# ----------------------------------------------------------------- reconcile
def _on(v, step):
    """``v`` is a multiple of ``step`` (to a millionth of a foot)."""
    return abs(v / step - round(v / step)) * step <= _EPS


def _bfs01(graph, starts):
    """0-1 BFS (``faces`` 1 hop, ``same`` 0) from each ``{key: start line}``.

    Returns ``(reach, prev)``, both keyed like ``starts``: hop counts and
    predecessor maps.
    """
    from collections import deque
    nbr = graph.adjacency()
    reach, prev = {}, {}
    for key, s in starts.items():
        dist, back = {s: 0}, {s: None}
        dq = deque([s])
        while dq:
            u = dq.popleft()
            for v, w in nbr[u]:
                nd = dist[u] + w
                if v not in dist or nd < dist[v]:
                    dist[v], back[v] = nd, u
                    if w == 0:
                        dq.appendleft(v)
                    else:
                        dq.append(v)
        reach[key], prev[key] = dist, back
    return reach, prev


@dataclass
class LineRange:
    """What the labels allow one contour to be."""

    status: str                      # lettered|pinned|ambiguous|conflict|unreached
    lo: float | None = None
    hi: float | None = None
    values: list = field(default_factory=list)
    lo_from: tuple | None = None     # (source key, hops) that set lo
    hi_from: tuple | None = None


@dataclass
class Reconciliation:
    """The range check over one sheet's contours (see :func:`reconcile`)."""

    lines: dict
    pinned: dict
    label_conflicts: list
    off_interval: list
    interval: float
    reach: dict
    prev: dict
    pins: list = field(default_factory=list)
    spot_ties: list = field(default_factory=list)
    # a cache for ``reuse`` (sources x lines, and source -> row): not part
    # of the value, so it neither prints nor takes part in ==
    hops: object = field(default=None, repr=False, compare=False)
    hop_rows: dict = field(default_factory=dict, repr=False, compare=False)

    @property
    def unreached(self):
        """The lines no label reaches, in index order."""
        return sorted(i for i, lr in self.lines.items()
                      if lr.status == "unreached")

    def path(self, src, dst):
        """Lines from source ``src``'s start line to ``dst`` ([] if unreached)."""
        back = self.prev.get(src, {})
        if dst not in back:
            return []
        out = [dst]
        while back[out[-1]] is not None:
            out.append(back[out[-1]])
        return out[::-1]

    def counts(self):
        c = {"pinned": 0, "ambiguous": 0, "conflict": 0, "unreached": 0}
        for lr in self.lines.values():
            if lr.status in c:
                c[lr.status] += 1
        c["label_conflicts"] = len(self.label_conflicts)
        c["off_interval"] = len(self.off_interval)
        return c


def reconcile(polys, graph, elev, interval, *, roles=None,
              index_interval=None, spot_pins=None, reuse=None) -> Reconciliation:
    """What every lettered contour allows every other contour to be.

    Neighbouring contours differ by at most one ``interval`` (a step, or 0
    across a crest or trough), so a line ``h`` hops from lettered ``z_a``
    lies in ``z_a ± h·interval``. Intersecting that over every lettered line
    that reaches it gives its range; the candidate values are the multiples
    of ``interval`` in it that fit its role (``index``: a multiple of
    ``index_interval``; ``intermediate``: not; no role, or no
    ``index_interval``: unfiltered). One value is ``pinned``, several
    ``ambiguous``, none ``conflict``; no label reaching it is ``unreached``.

    Each lettered line is checked the same way against the *other* labels;
    a value outside that range is a label conflict. Conflicting labels are
    reported, never dropped — which one is wrong is for a person to decide —
    and the lines around them get empty ranges, so nothing there is
    assigned. A lettered value off the ``interval`` grid constrains nothing
    and is listed in ``off_interval``.

    ``spot_pins`` (``[{"elev", "xy"}]``) lets spot elevations constrain the
    contours: a spot pins its nearest line (segment distance — nothing lies
    between them) to within one interval of its value, and a line ``h`` hops
    from that line to within ``(h + 1)·interval``. Pins are recorded in
    ``pins`` and keyed ``("spot", k)`` as sources; exact ties are recorded in
    ``spot_ties`` and used only for findings; neither makes a lettered value.

    ``reuse`` is an earlier result over the same graph, ``interval`` and
    spot pins whose lettered lines include every one here — the CLI's
    single-label recheck sets one label aside. A source's hop counts do not
    depend on the other sources, so the searches are not re-run: the ranges
    come from the earlier hop table, in one vectorized pass.
    """
    import numpy as np
    if not interval or interval <= 0:
        raise ValueError(f"reconcile needs a contour interval > 0 (got {interval!r})")
    roles = roles or {}
    grid = {a: float(z) for a, z in elev.items() if _on(float(z), interval)}
    off = sorted(a for a in elev if a not in grid)
    if reuse is not None:
        if (abs(reuse.interval - float(interval)) > _EPS
                or any(a not in reuse.hop_rows for a in grid)):
            raise ValueError("reuse needs an earlier reconciliation with the "
                             "same interval and every lettered line here")
        pins, spot_ties, reach, prev = (reuse.pins, reuse.spot_ties,
                                        reuse.reach, reuse.prev)
    else:
        pins, spot_ties = [], []
        if spot_pins:
            from bimforge.terrain.contours import _line_distances, _segments
            segs = _segments(polys)
            for s in spot_pins:
                xy = (float(s["xy"][0]), float(s["xy"][1]))
                d = _line_distances(np.asarray(xy), segs, len(polys))
                if len(d) and math.isfinite(float(d.min())):
                    dmin = float(d.min())
                    near = np.flatnonzero(d <= dmin + _PIN_TIE_FT)
                    # a spot exactly as far from two lines is ambiguous: pin
                    # neither, not the arbitrary lower-index argmin.
                    if near.size == 1:
                        pins.append({"elev": float(s["elev"]), "xy": xy,
                                     "line": int(near[0])})
                    elif near.size > 1:
                        spot_ties.append({"elev": float(s["elev"]), "xy": xy,
                                          "lines": [int(k) for k in near],
                                          "dist_ft": dmin})
        starts = {a: a for a in sorted(grid)}
        starts.update({("spot", k): p["line"] for k, p in enumerate(pins)})
        reach, prev = _bfs01(graph, starts)
    sources = ([(a, grid[a], 0) for a in sorted(grid)]      # (key, value, extra hops)
               + [(("spot", k), p["elev"], 1) for k, p in enumerate(pins)])
    keys = [key for key, _, _ in sources]
    rows = {key: r for r, key in enumerate(keys)}
    if reuse is not None:
        hops = reuse.hops[[reuse.hop_rows[key] for key in keys]].reshape(
            len(keys), graph.n)
    else:
        hops = np.full((len(keys), graph.n), np.inf)
        for r, key in enumerate(keys):
            got = reach[key]
            if got:
                hops[r, list(got)] = list(got.values())
            if not isinstance(key, tuple):
                hops[r, key] = np.inf        # a label never limits its own line
    # the limit every source puts on every line (unreached: -inf / +inf);
    # argmax/argmin keep the first source at the bound, as a loop would
    z = np.array([v for _, v, _ in sources], dtype=float)[:, None]
    extra = np.array([x for _, _, x in sources], dtype=float)[:, None]
    lo_all = z - (hops + extra) * interval
    hi_all = z + (hops + extra) * interval
    if keys:
        cols = np.arange(graph.n)
        lo_src, hi_src = lo_all.argmax(axis=0), hi_all.argmin(axis=0)
        lo_v, hi_v = lo_all[lo_src, cols], hi_all[hi_src, cols]

    def role_ok(i, v):
        r = roles.get(i)
        if not index_interval or r not in ("index", "intermediate"):
            return True
        return _on(v, index_interval) == (r == "index")

    def bounds(i):
        if not keys or not math.isfinite(lo_v[i]):
            return None, None, None, None
        a, b = int(lo_src[i]), int(hi_src[i])
        return (float(lo_v[i]), float(hi_v[i]),
                (keys[a], int(hops[a, i])), (keys[b], int(hops[b, i])))

    lines, pinned, conflicts = {}, {}, []
    for i in range(graph.n):
        lo, hi, lf, hf = bounds(i)
        if i in elev:
            lines[i] = LineRange("lettered", lo, hi, [float(elev[i])], lf, hf)
            if (i in grid and lo is not None
                    and not lo - _EPS <= grid[i] <= hi + _EPS):
                conflicts.append({"line": i, "elev": grid[i], "lo": lo, "hi": hi,
                                  "lo_from": lf, "hi_from": hf})
            continue
        if lo is None:
            lines[i] = LineRange("unreached")
            continue
        vals = []
        if lo <= hi + _EPS:
            k0 = math.ceil(lo / interval - 1e-9)
            k1 = math.floor(hi / interval + 1e-9)
            vals = [round(k * interval, 9) for k in range(k0, k1 + 1)
                    if role_ok(i, k * interval)]
        status = ("pinned" if len(vals) == 1 else
                  "ambiguous" if vals else "conflict")
        lines[i] = LineRange(status, lo, hi, vals, lf, hf)
        if status == "pinned":
            pinned[i] = vals[0]
    return Reconciliation(lines, pinned, conflicts, off, float(interval),
                          reach, prev, pins, spot_ties, hops, rows)


# ------------------------------------------------------------------ findings
CHECKS = {
    "conflict": "the labels and the lines between them do not add up: a "
                "missing or extra contour, a misread label, or a label on "
                "the wrong line",
    "spot-tie": "the spot is exactly as close to multiple contours, so it "
                "cannot pin one line uniquely",
    "cross": "contours cannot cross: a drafting error, or a line on the "
             "wrong layer",
    "touch": "contours meet: expect a wall or grade break; if there is "
             "none, a drafting error",
    "label-unmatched": "the anchor's position, or a missing contour",
    "label-not-index": "the reading, or the line's pen/layer",
    "label-off-interval": "the reading",
}
_KINDS = ("conflict", "spot-tie", "cross", "touch", "label-unmatched",
          "label-not-index", "label-off-interval")


@dataclass
class Finding:
    """One place a person should look at, and why."""

    id: str
    kind: str
    lines: list
    labels: list
    xy: tuple
    detail: str = ""
    check: str = ""
    paths: list = field(default_factory=list)
    page: tuple | None = None

    def as_dict(self):
        def pt(p):
            if p is None:
                return None
            x, y = float(p[0]), float(p[1])
            return [x, y] if math.isfinite(x) and math.isfinite(y) else None

        return {"id": self.id, "kind": self.kind,
                "lines": [int(k) for k in self.lines],
                "labels": [dict(lab) for lab in self.labels],
                "xy": pt(self.xy), "page": pt(self.page),
                "detail": self.detail, "check": self.check,
                "paths": list(self.paths)}


def _groups(items, xy_of, radius):
    """Single-linkage groups of ``items`` whose ``xy_of`` lie within ``radius``."""
    parent = list(range(len(items)))

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for a in range(len(items)):
        for b in range(a + 1, len(items)):
            if math.dist(xy_of(items[a]), xy_of(items[b])) <= radius:
                parent[find(a)] = find(b)
    out: dict = {}
    for k in range(len(items)):
        out.setdefault(find(k), []).append(items[k])
    return list(out.values())


def _path_text(rec, elev, src, dst, bound):
    """``4(20) – 3 – 2 – 1 – 0(25): 4 hops → ≤ 24`` for one limit."""
    nodes = rec.path(src, dst)
    head = f"spot {rec.pins[src[1]]['elev']:g} – " if isinstance(src, tuple) else ""
    h = rec.reach[src].get(dst)
    body = " – ".join(f"{k}({elev[k]:g})" if k in elev else str(k) for k in nodes)
    return f"{head}{body}: {h} hop{'' if h == 1 else 's'} → {bound}"


def build_findings(polys, graph, elev, rec=None, *, labels=(), label_rows=(),
                   index_rows=(), line_ids=None, group_ft=40.0, recheck=None):
    """Every place the contours do not add up, located and grouped.

    ``conflict`` — the lettered values in conflict and the unlabelled lines
    whose ranges went empty, grouped by connectivity through ``faces`` /
    ``same``; each carries the neighbour paths behind its limits, and, when
    ``recheck`` is given and setting aside exactly one of its labels
    reconciles the whole cluster, says which label to check first.
    ``spot-tie`` — a spot exactly equidistant from multiple contours, so it
    is reported for review but not used as a pin. ``cross`` / ``touch`` —
    graph contacts, grouped single-linkage within
    ``group_ft`` (half a review crop), so contours meeting at one wall are
    one finding. ``label-unmatched`` — a label that attached to no line
    (``label_rows`` zipped with ``labels``). ``label-not-index`` — the
    ``index_rows`` of :func:`~bimforge.terrain.contours.check_index_labels`.
    ``label-off-interval`` — ``rec.off_interval``.
    """
    import numpy as np
    line_ids = line_ids or {}
    found: list = []

    def centre_of(lines):
        cs = [_centre(polys[k][0]) for k in lines if len(polys[k][0])]
        if not cs:
            return (math.nan, math.nan)
        return (float(np.mean([c[0] for c in cs])),
                float(np.mean([c[1] for c in cs])))

    def label_of(k):
        return {"id": ", ".join(line_ids.get(k, [])) or None,
                "elev": float(elev[k]), "line": int(k)}

    def empty(r):
        return ({c["line"] for c in r.label_conflicts}
                | {i for i, lr in r.lines.items() if lr.status == "conflict"})

    if rec is not None:
        bad = empty(rec)
        nbr = graph.adjacency()
        seen: set = set()
        for s in sorted(bad):
            if s in seen:
                continue
            comp, stack = [], [s]
            seen.add(s)
            while stack:
                u = stack.pop()
                comp.append(u)
                for v, _ in nbr[u]:
                    if v in bad and v not in seen:
                        seen.add(v)
                        stack.append(v)
            comp.sort()
            paths = []
            for k in comp:
                lr = rec.lines[k]
                if lr.lo_from is None:
                    continue
                what = f"label {elev[k]:g} on line {k}" if k in elev else f"line {k}"
                paths.append(
                    f"{what}: "
                    + _path_text(rec, elev, lr.lo_from[0], k, f"≥ {lr.lo:g}")
                    + "; "
                    + _path_text(rec, elev, lr.hi_from[0], k, f"≤ {lr.hi:g}"))
            labs = [k for k in comp if k in elev]
            detail = (f"{len(labs)} lettered value(s) and {len(comp) - len(labs)} "
                      "line(s) the labels leave no value for")
            if recheck is not None and labs:
                fixes = [k for k in labs
                         if not empty(recheck({a: z for a, z in elev.items()
                                               if a != k})) & (set(comp) - {k})]
                if len(fixes) == 1:
                    k = fixes[0]
                    detail += (f"; everything here reconciles without the "
                               f"{elev[k]:g} label on line {k} — check that "
                               "reading first")
            found.append(Finding("", "conflict", comp, [label_of(k) for k in labs],
                                 centre_of(comp), detail, CHECKS["conflict"], paths))

    for kind in ("cross", "touch"):
        cs = [c for c in graph.contacts if c.kind == kind]
        for grp in _groups(cs, lambda c: c.xy, group_ft):
            lines = sorted({k for c in grp for k in c.pair})
            parts = [f"lines {c.pair[0]} and {c.pair[1]} {kind}"
                     + (f" over {c.length_ft:.0f} ft" if kind == "touch" else "")
                     for c in grp[:6]]
            detail = "; ".join(parts) + (f"; and {len(grp) - 6} more"
                                         if len(grp) > 6 else "")
            xy = (float(np.mean([c.xy[0] for c in grp])),
                  float(np.mean([c.xy[1] for c in grp])))
            found.append(Finding("", kind, lines,
                                 [label_of(k) for k in lines if k in elev],
                                 xy, detail, CHECKS[kind]))

    for lab, row in zip(labels, label_rows):
        if row["accepted"]:
            continue
        if row.get("conflict") is not None:
            detail = (f"label {row['elev']:g}: line {row['line']} already "
                      f"carries {row['conflict']:g}")
        elif row["line"] is None:
            detail = f"label {row['elev']:g}: there are no contour lines"
        else:
            detail = (f"label {row['elev']:g}: nearest line {row['line']} is "
                      f"{row['dist_ft']:.1f} ft away")
        found.append(Finding(
            "", "label-unmatched",
            [] if row["line"] is None else [int(row["line"])],
            [{"id": row.get("id"), "elev": float(row["elev"]), "line": row["line"]}],
            (float(lab["xy"][0]), float(lab["xy"][1])), detail,
            CHECKS["label-unmatched"]))

    for r in index_rows:
        k = r["line"]
        found.append(Finding("", "label-not-index", [k],
                             [{"id": r.get("id"), "elev": float(r["elev"]), "line": k}],
                             centre_of([k]), r["detail"], CHECKS["label-not-index"]))

    if rec is not None:
        for t in rec.spot_ties:
            lines = [int(k) for k in t["lines"]]
            found.append(Finding(
                "", "spot-tie", lines, [], tuple(t["xy"]),
                f"spot {t['elev']:g} is equally near ({t['dist_ft']:g} ft) to lines "
                f"{', '.join(str(k) for k in lines)}; it was not used as a pin",
                CHECKS["spot-tie"]))
        for k in rec.off_interval:
            found.append(Finding(
                "", "label-off-interval", [k], [label_of(k)], centre_of([k]),
                f"lettered {elev[k]:g} is not a multiple of the "
                f"{rec.interval:g} ft contour interval", CHECKS["label-off-interval"]))

    found.sort(key=lambda f: _KINDS.index(f.kind))      # stable within a kind
    for n, f in enumerate(found, start=1):
        f.id = f"F{n:02d}"
    return found
