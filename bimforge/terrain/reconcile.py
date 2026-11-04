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
                           (``contacts`` — no limit, a finding); a
                           barrier (a grading layer, a break line) between
                           two lines sets their ``faces`` pair aside
                           (``barred`` — a finding, never silent).
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

__all__ = ["Contact", "Barred", "NeighbourGraph", "neighbour_graph", "LineRange",
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


_BARRIER_STEP_FT = 5.0     # barrier segments split to this for the search


def _barrier_segments(barriers):
    """``(P0, P1, owner, labels)`` for ``barriers`` (``[(points, label)]``):
    every segment, split to at most ``_BARRIER_STEP_FT`` (the same
    geometry, so a short search radius finds it), the barrier it belongs to,
    and each barrier's label. Zero-length segments are dropped, so a
    barrier of one point, or of coincident points, has no segment and
    blocks nothing."""
    import numpy as np
    p0, p1, owner, labels = [], [], [], []
    for b, (points, label) in enumerate(barriers):
        labels.append(str(label))
        d = _densify(points, _BARRIER_STEP_FT)
        if len(d) < 2:
            continue
        keep = np.sqrt(((d[1:] - d[:-1]) ** 2).sum(axis=1)) > _EPS
        if not keep.any():
            continue
        p0.append(d[:-1][keep])
        p1.append(d[1:][keep])
        owner.append(np.full(int(keep.sum()), b))
    if not p0:
        z = np.zeros((0, 2))
        return z, z, np.zeros(0, dtype=int), labels
    return np.vstack(p0), np.vstack(p1), np.concatenate(owner), labels


def _in_band(A, B, P0, P1, tol):
    """Row-wise: segment ``P0–P1`` enters the band of half-width ``tol``
    around the interior of connector ``A→B`` — the connector less ``tol``
    at each end (a rectangle, no rounded caps). A connector no longer than
    ``2·tol`` has no interior and nothing enters it.

    So a barrier crossing the connector mid-way, or passing within ``tol``
    of it there, blocks; one within ``tol`` of either end lies on that
    contour, as two contours that close are in contact, and is not
    between the two lines. Clipped Liang–Barsky style in the connector's
    frame (``t`` along it, ``v`` across)."""
    import numpy as np
    d = B - A
    L = np.sqrt((d ** 2).sum(axis=1))
    ok = L > 2 * tol
    Ls = np.where(ok, L, 1.0)
    u = d / Ls[:, None]
    nrm = np.column_stack([-u[:, 1], u[:, 0]])
    r0, r1 = P0 - A, P1 - A
    t0, t1 = (r0 * u).sum(axis=1), (r1 * u).sum(axis=1)
    v0, v1 = (r0 * nrm).sum(axis=1), (r1 * nrm).sum(axis=1)
    lo, hi = np.zeros(len(A)), np.ones(len(A))
    for x0, x1, m, M in ((t0, t1, tol, L - tol), (v0, v1, -tol, tol)):
        dx = x1 - x0
        flat = np.abs(dx) <= 1e-12
        with np.errstate(divide="ignore", invalid="ignore"):
            a = (m - x0) / np.where(flat, 1.0, dx)
            b = (M - x0) / np.where(flat, 1.0, dx)
        lo = np.where(flat, lo, np.maximum(lo, np.minimum(a, b)))
        hi = np.where(flat, hi, np.minimum(hi, np.maximum(a, b)))
        ok &= ~flat | ((m <= x0) & (x0 <= M))
    return ok & (lo <= hi)


_BAR_CHUNK = 1 << 18       # connector x segment pairs tested at a time


def _barrier_hits(A, B, bar, tol):
    """For connectors ``A[c]``→``B[c]``, the barriers (owner ids) in the
    way of each (:func:`_in_band`): a list of sorted tuples, ``()`` where
    nothing is.

    Candidates come from a cKDTree over the barrier segments' midpoints,
    queried 256 rows at a time (a segment within ``tol`` of a connector has
    its midpoint within the connector's half-length + the longest
    half-segment + ``tol`` of the connector's midpoint) or, without scipy,
    a bounding-box sweep; each candidate is then tested exactly.
    """
    import numpy as np
    P0, P1, owner, _, tree, half = bar
    out: list = [() for _ in range(len(A))]
    if len(A) == 0 or len(P0) == 0:
        return out
    if tree is not None:
        mid = (A + B) / 2.0
        reach = np.sqrt(((B - A) ** 2).sum(axis=1)) / 2.0 + half + tol
        cis, sis = [], []
        for r0 in range(0, len(A), 256):           # bounded memory per query
            got = tree.query_ball_point(mid[r0:r0 + 256], reach[r0:r0 + 256])
            n = np.fromiter((len(g) for g in got), dtype=int, count=len(got))
            if n.sum():
                cis.append(np.repeat(np.arange(r0, r0 + len(got)), n))
                sis.append(np.fromiter((j for g in got for j in g), dtype=int,
                                       count=int(n.sum())))
        if not cis:
            return out
        ci, si = np.concatenate(cis), np.concatenate(sis)
    else:
        # sweep on x: a segment can meet a connector only if their extents
        # (the connector's widened by tol) overlap; then box-test
        slo, shi = np.minimum(P0, P1), np.maximum(P0, P1)
        clo, chi = np.minimum(A, B) - tol, np.maximum(A, B) + tol
        order = np.argsort(slo[:, 0], kind="stable")
        keys = slo[order, 0]
        widest = float((shi[:, 0] - slo[:, 0]).max())
        start = np.searchsorted(keys, clo[:, 0] - widest, side="left")
        stop = np.searchsorted(keys, chi[:, 0], side="right")
        cis, sis = [], []
        for c in range(len(A)):
            j = order[start[c]:stop[c]]
            j = j[(slo[j, 0] <= chi[c, 0]) & (clo[c, 0] <= shi[j, 0])
                  & (slo[j, 1] <= chi[c, 1]) & (clo[c, 1] <= shi[j, 1])]
            if len(j):
                cis.append(np.full(len(j), c))
                sis.append(j)
        if not cis:
            return out
        ci, si = np.concatenate(cis), np.concatenate(sis)
    hits: dict = {}
    for k0 in range(0, len(ci), _BAR_CHUNK):
        c, j = ci[k0:k0 + _BAR_CHUNK], si[k0:k0 + _BAR_CHUNK]
        ok = _in_band(A[c], B[c], P0[j], P1[j], tol)
        for cc, oo in zip(c[ok].tolist(), owner[j[ok]].tolist()):
            hits.setdefault(cc, set()).add(oo)
    for cc, owners in hits.items():
        out[cc] = tuple(sorted(owners))
    return out


@dataclass
class Barred:
    """A ``faces`` pair set aside: a barrier lies between the two lines (or
    ``--no-face`` dropped it), so they are not counted as one interval
    apart. ``by`` names what set it aside (barrier labels, most votes
    first, or ``"--no-face"``); ``length_ft`` is the facing set aside,
    ``kept_ft`` what still faced past the barrier (< ``min_facing_ft``);
    ``xy`` is where (the mean midpoint of the blocked connectors).

    ``partial`` — the barrier leaked: the pair still faces along
    ``kept_ft`` >= ``min_facing_ft``, so it stays a ``faces`` pair, but at
    least as much (``length_ft``) was blocked. Recorded so blocked facing
    is never dropped silently: the barrier probably stops short of the
    ends of the interrupted contours."""

    pair: tuple
    by: list
    length_ft: float
    kept_ft: float
    xy: tuple
    partial: bool = False


@dataclass
class NeighbourGraph:
    """The neighbour relation between ``n`` contours (see :func:`neighbour_graph`)."""

    n: int
    faces: set = field(default_factory=set)
    same: set = field(default_factory=set)
    joints: set = field(default_factory=set)
    contacts: list = field(default_factory=list)
    params: dict = field(default_factory=dict)
    barred: list = field(default_factory=list)
    # every pair's unblocked facing votes: {pair: (length_ft, (x, y) mean
    # connector midpoint)} — a working table, not part of the value
    facing: dict = field(default_factory=dict, repr=False, compare=False)

    def set_aside_faces(self, pairs, reason="--no-face"):
        """Drop each ``(a, b)`` from ``faces`` and record it in ``barred``
        with ``reason``. An index out of range is a ``ValueError``; a pair
        that is not a ``faces`` pair is left alone and returned as a
        warning (a list of strings) — naming the barrier when one already
        set it aside. A pair with no facing votes recorded (a graph not
        built by :func:`neighbour_graph`) is a ``ValueError``: there is no
        length or place to report. Dropping a pair a barrier only partly
        blocked replaces that ``partial`` record."""
        warnings, dropped = [], []
        for a, b in pairs:
            a, b = int(a), int(b)
            for k in (a, b):
                if not 0 <= k < self.n:
                    raise ValueError(f"{reason} {a},{b}: line {k} is out of "
                                     f"range (0..{self.n - 1})")
            if a == b:
                raise ValueError(f"{reason} {a},{b}: needs two different lines")
            key = (min(a, b), max(a, b))
            if key not in self.faces:
                prior = [r for r in self.barred
                         if r.pair == key and not r.partial]
                if prior:
                    warnings.append(f"{reason} {a},{b}: already set aside by "
                                    + ", ".join(prior[0].by))
                else:
                    warnings.append(f"{reason} {a},{b}: not a faces pair — "
                                    "nothing set aside")
                continue
            if key not in self.facing:
                raise ValueError(f"{reason} {a},{b}: no facing votes recorded "
                                 "for this pair — build the graph with "
                                 "neighbour_graph")
            self.faces.discard(key)
            self.barred = [r for r in self.barred if r.pair != key]
            length, xy = self.facing[key]
            self.barred.append(Barred(key, [reason], float(length), 0.0,
                                      (float(xy[0]), float(xy[1]))))
            dropped.append([key[0], key[1]])
        if dropped:
            self.params.setdefault("no_face", []).extend(dropped)
        return warnings

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
                    target_ft=0.5, barriers=()) -> NeighbourGraph:
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

    ``barriers`` (``[(points Nx2, label)]``) are obstacles, not contours:
    no node, no value, no index. A facing vote from sample ``s`` to its
    nearest point ``t`` is *blocked* when a barrier enters the connector's
    interior — crosses it, or passes within ``contact_ft`` of it, more than
    ``contact_ft`` from either end (:func:`_in_band`). A barrier merely near
    but not between them blocks nothing, and neither does one lying along
    either contour (within ``contact_ft`` of it): it is on that line, not
    between the two. A pair whose unblocked facing falls below
    ``min_facing_ft`` when blocked and unblocked together reach it is not
    ``faces``: it is recorded in ``barred`` (:class:`Barred`), naming the
    barrier(s), for review. A pair that keeps ``min_facing_ft`` unblocked
    stays ``faces``, but when at least as much was blocked it is recorded
    too, ``partial`` — blocked facing is never dropped silently. Where
    a roadway cut erases a band of contours, the lines either side of the
    gap face across empty ground and would count one hop; the proposed
    grading (or a drawn break line) through the gap stops that. Contacts,
    ``same`` and ``joints`` never depend on barriers.
    """
    import numpy as np
    n = len(polys)
    g = NeighbourGraph(n=n, params={"sample_ft": sample_ft,
                                    "contact_ft": contact_ft,
                                    "min_facing_ft": min_facing_ft})
    bar = None
    if barriers:
        P0, P1, owner, bar_labels = _barrier_segments(barriers)
        counts: dict = {}
        for lab in bar_labels:
            counts[lab] = counts.get(lab, 0) + 1
        g.params["barriers"] = counts
        try:
            from scipy.spatial import cKDTree
            btree = cKDTree((P0 + P1) / 2.0) if len(P0) else None
        except ImportError:
            btree = None
        half = (float(np.sqrt(((P1 - P0) ** 2).sum(axis=1)).max()) / 2.0
                if len(P0) else 0.0)
        bar = (P0, P1, owner, bar_labels, btree, half)
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

    facing: dict = {}        # pair -> [votes, sum of connector midpoints x, y]
    walled: dict = {}        # pair -> [votes, sum x, sum y, {barrier: votes}]
    contact: dict = {}      # (i, o) directed -> [(x, y, i_near_end, o_near_end)]
    for i, (p, _, _) in enumerate(polys):
        S = _densify(p, sample_ft)
        if len(S) == 0:
            continue
        s_end = _near_ends(S)
        d0, tied = _nearest_others(S, i, xy, own, tree)
        votes = []          # facing votes: (sample, target, pair)
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
                    votes.append((k, int(t), (min(i, o), max(i, o))))
        if not votes:
            continue
        ks = np.array([v[0] for v in votes])
        ts = np.array([v[1] for v in votes])
        mids = (S[ks] + xy[ts]) / 2.0
        hit = (_barrier_hits(S[ks], xy[ts], bar, contact_ft) if bar is not None
               else [()] * len(votes))
        for (_, _, key), (mx, my), by in zip(votes, mids.tolist(), hit):
            if by:
                w = walled.setdefault(key, [0, 0.0, 0.0, {}])
                for b in by:
                    w[3][b] = w[3].get(b, 0) + 1
            else:
                w = facing.setdefault(key, [0, 0.0, 0.0])
            w[0] += 1
            w[1] += mx
            w[2] += my
    g.facing = {key: (v[0] * sample_ft, (v[1] / v[0], v[2] / v[0]))
                for key, v in sorted(facing.items())}

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
    for a, b in sorted(set(facing) | set(walled)):
        kept = facing.get((a, b), [0])[0]
        wall = walled.get((a, b), [0])[0]
        if (kept + wall) * sample_ft < min_facing_ft or (a, b) in blocked:
            continue
        if (a, b) not in checked:
            # a steep crossing can fall between samples, every one of them
            # >= contact_ft from the other line: no contact vote, still a cross
            x = _crossing(polys[a][0], polys[b][0])
            if x is not None:
                g.contacts.append(Contact((a, b), "cross", 0.0, x))
                continue
        full = kept * sample_ft < min_facing_ft
        if wall and (full or wall >= kept):
            # a barrier lies between them: set aside (or, leaking, kept)
            # — named, for review either way
            w = walled[(a, b)]
            by = sorted(w[3], key=lambda o: (-w[3][o], o))
            names = list(dict.fromkeys(bar[3][o] for o in by))
            g.barred.append(Barred((a, b), names, wall * sample_ft,
                                   kept * sample_ft,
                                   (w[1] / wall, w[2] / wall),
                                   partial=not full))
        if full:
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
    "barrier": "two contours facing each other across this ground were not "
               "counted as neighbours, because a barrier (a grading layer, a "
               "break line) or --no-face sets them aside: confirm contours "
               "really are missing between them (a cut, a fill, an erased "
               "area); if not, the barrier is wrong. A partial one (the "
               "pair is kept) means the barrier stops short of the ends of "
               "the interrupted contours",
    "label-unmatched": "the anchor's position, or a missing contour",
    "label-not-index": "the reading, or the line's pen/layer",
    "label-off-interval": "the reading",
}
_KINDS = ("conflict", "spot-tie", "cross", "touch", "barrier",
          "label-unmatched", "label-not-index", "label-off-interval")


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
    chains: list = field(default_factory=list)
    partial: bool = False      # a barrier finding whose barrier leaked

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
                "paths": list(self.paths),
                "chains": [dict(c) for c in self.chains],
                **({"partial": bool(self.partial)} if self.kind == "barrier"
                   else {})}


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


def _source_value(rec, elev, src):
    """A source's value and its extra hops: a spot is one hop off its line."""
    if isinstance(src, tuple):
        return float(rec.pins[src[1]]["elev"]), 1
    return float(elev[src]), 0


def _chain(rec, elev, a, b):
    """The shortest neighbour chain between sources ``a`` and ``b`` and the
    feet per hop it implies, or None when one does not reach the other.

    Two sources in conflict are further apart in value than one interval per
    hop allows, so the chain between them is steeper than the interval. A
    chain well over the interval (2 ft/hop on a 1 ft interval) usually means
    a ``faces`` edge on it spans a gap — contours missing between two
    lines that face each other across open ground (a roadway prism, an
    erased area) — rather than a
    misread label; the chain names the lines to look at.
    """
    line_b = rec.pins[b[1]]["line"] if isinstance(b, tuple) else b
    h = rec.reach.get(a, {}).get(line_b)
    if h is None:
        return None
    za, xa = _source_value(rec, elev, a)
    zb, xb = _source_value(rec, elev, b)
    hops = int(h) + xa + xb
    if hops <= 0:
        return None
    nodes = rec.path(a, line_b)
    body = [f"{k}({elev[k]:g})" if k in elev else str(k) for k in nodes]
    if isinstance(a, tuple):
        body.insert(0, f"spot {za:g}")
    if isinstance(b, tuple):
        body.append(f"spot {zb:g}")
    dz = abs(za - zb)
    rate = dz / hops
    text = (f"chain {' – '.join(body)}: {hops} hop{'' if hops == 1 else 's'} "
            f"for {dz:g} ft = {rate:.2f} ft/hop against the "
            f"{rec.interval:g} ft interval")
    if rate > rec.interval + _EPS:
        text += (" — more than one interval per hop: a faces edge on this "
                 "chain likely spans a gap (contours missing between two "
                 "lines that face each other), or a label is misread")
    return {"from": _src_json(a), "to": _src_json(b),
            "lines": [int(k) for k in nodes], "hops": hops,
            "dz_ft": round(dz, 6), "ft_per_hop": round(rate, 6),
            "interval_ft": float(rec.interval), "text": text}


def _src_json(src):
    """A source key as plain JSON: a line index, or ``"spot k"``."""
    return f"spot {src[1]}" if isinstance(src, tuple) else int(src)


def _conflict_chains(rec, elev, comp):
    """One chain per pair of sources in conflict within ``comp``, steepest
    first: a lettered line and the source whose limit it breaks, and the two
    sources whose limits empty an unlabelled line."""
    pairs: list = []
    by_line = {c["line"]: c for c in rec.label_conflicts}
    for k in comp:
        lr = rec.lines[k]
        if k in by_line:
            c = by_line[k]
            if c["lo"] is not None and elev[k] < c["lo"] - _EPS:
                pairs.append((c["lo_from"][0], k))
            if c["hi"] is not None and elev[k] > c["hi"] + _EPS:
                pairs.append((c["hi_from"][0], k))
        elif lr.status == "conflict" and lr.lo_from and lr.hi_from:
            pairs.append((lr.lo_from[0], lr.hi_from[0]))
    seen, chains = set(), []
    for a, b in pairs:
        key = frozenset((a, b))
        if a == b or key in seen:
            continue
        seen.add(key)
        ch = _chain(rec, elev, a, b)
        if ch is not None:
            chains.append(ch)
    chains.sort(key=lambda c: -c["ft_per_hop"])         # stable: steepest first
    return chains


def build_findings(polys, graph, elev, rec=None, *, labels=(), label_rows=(),
                   index_rows=(), line_ids=None, group_ft=40.0, recheck=None):
    """Every place the contours do not add up, located and grouped.

    ``conflict`` — the lettered values in conflict and the unlabelled lines
    whose ranges went empty, grouped by connectivity through ``faces`` /
    ``same``; each carries the neighbour paths behind its limits, the chain
    between each pair of conflicting sources with the feet per hop it
    implies against the interval (``chains``: steeper than the interval
    usually means a ``faces`` edge across a gap), and, when
    ``recheck`` is given and setting aside exactly one of its labels
    reconciles the whole cluster, says which label to check first.
    ``spot-tie`` — a spot exactly equidistant from multiple contours, so it
    is reported for review but not used as a pin. ``cross`` / ``touch`` —
    graph contacts, grouped single-linkage within
    ``group_ft`` (half a review crop), so contours meeting at one wall are
    one finding. ``barrier`` — ``graph.barred``: faces pairs a barrier
    layer, a break line or ``--no-face`` set aside, grouped the same way,
    each naming its lines, what set it aside and the facing it set aside;
    ``partial`` ones (``Finding.partial``) are pairs a barrier blocked at
    least half of but that still face, kept — grouped on their own.
    ``label-unmatched`` — a label that attached to no line
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
            chains = _conflict_chains(rec, elev, comp)
            if chains:
                detail += (f"; steepest chain {chains[0]['ft_per_hop']:.2f} "
                           f"ft/hop against the {rec.interval:g} ft interval "
                           f"({chains[0]['hops']} hop"
                           f"{'' if chains[0]['hops'] == 1 else 's'} for "
                           f"{chains[0]['dz_ft']:g} ft)")
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
                                 centre_of(comp), detail, CHECKS["conflict"], paths,
                                 chains=chains))

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

    def line_text(k):
        return f"{k} ({elev[k]:g})" if k in elev else str(k)

    def barred_text(b):
        head = f"lines {line_text(b.pair[0])} and {line_text(b.pair[1])}: "
        if b.partial:
            return (head + f"{b.length_ft:.0f} ft of facing blocked by "
                    f"{', '.join(b.by)}, but {b.kept_ft:.0f} ft still faces "
                    "— the pair is kept; extend the barrier/break line to "
                    "cover it")
        return (head + f"{b.length_ft:.0f} ft of facing set aside by "
                f"{', '.join(b.by)}"
                + (f" ({b.kept_ft:.0f} ft left unblocked)" if b.kept_ft else ""))

    for partial in (False, True):
        rows = [b for b in graph.barred if b.partial == partial]
        for grp in _groups(rows, lambda b: b.xy, group_ft):
            lines = sorted({k for b in grp for k in b.pair})
            detail = "; ".join(barred_text(b) for b in grp[:6]) + (
                f"; and {len(grp) - 6} more" if len(grp) > 6 else "")
            xy = (float(np.mean([b.xy[0] for b in grp])),
                  float(np.mean([b.xy[1] for b in grp])))
            found.append(Finding("", "barrier", lines,
                                 [label_of(k) for k in lines if k in elev],
                                 xy, detail, CHECKS["barrier"],
                                 partial=partial))

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
