"""Contour polylines off a flattened vector plan sheet, in world feet.

Agency CONTOUR GRADING sheets draw existing topography and proposed grading
as two different pen styles on the same page. A signed set is normally
flattened — every letter is vector outlines and there is no text layer — but
the *linework* is still real CAD geometry, so the contours themselves come
out exactly.

This keeps the plansheet extractor's segments matching a style selector
(grey level + pen width — the pen table IS the layer table on a plotted
set), chains them back into polylines, optionally re-stitches dashed
linetypes across gaps, and transforms them to world feet with an `est-bim
calibrate` calibration or a survey-tie georeference. Elevations are NOT
assigned here: contour labels on a flattened sheet are outlined glyphs with
no text layer, so they have to be read visually and fed to the surface side
(``bimforge.terrain.contours``) as an anchor list.

Style selectors are ``grey[@width]``, e.g. ``0.753@0.72`` for a light-grey
0.72 pt existing-topo pen, or ``0@0.72`` for a black proposed-grading pen.
Profile a sheet's pen table first (``pen_table`` / the CLI's ``--profile``)
to see what pens it actually uses.

Dependency posture: this module operates on the segment objects
``bimforge.bim.plansheet.vectors.extract_sheet`` produces (duck-typed —
anything with ``x1/y1/x2/y2/width/color/length``) and the calibration zones
``bimforge.bim.plansheet.calibrate.load_calibration`` loads, but imports
neither, so the pure cores run without pymupdf. ``bridge`` uses scipy's
cKDTree when it is installed (the ``bimforge[terrain]`` extra) and falls
back to a brute-force endpoint scan otherwise — chain-end counts are small.
"""
from __future__ import annotations

import fnmatch
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Callable

__all__ = [
    "CHAIN_TOL_PT",
    "parse_selector", "parse_layer", "matches", "pen_table",
    "LayerSpec", "parse_layer_spec", "select_segments", "ocg_table",
    "chain", "bridge",
    "parse_tie", "solve_georef",
    "Georef", "affine_coeffs", "solve_georef_affine",
    "georef_from_ties", "georef_from_zone", "georef_from_viewport",
    "crosscheck_ties_vs_viewport",
    "clip_segment",
    "polyline_length", "is_closed",
    "extract_contours",
]

#: endpoint snap tolerance when chaining segments, in page points.  CAD writes
#: a polyline's vertices exactly, so this only has to absorb float noise.
CHAIN_TOL_PT = 0.05


# ----------------------------------------------------------------- selectors
def parse_selector(style: str) -> tuple[float, float | None]:
    """``grey[@width]`` -> (grey, width or None for any width)."""
    try:
        grey, _, width = style.partition("@")
        return float(grey), float(width) if width else None
    except ValueError:
        raise ValueError(f"bad style selector {style!r}; expected grey[@width]")


def parse_layer(spec: str) -> tuple[str, float, float | None]:
    """``NAME=grey[@width]`` -> (name, grey, width or None for any width)."""
    try:
        name, style = spec.split("=", 1)
        grey, width = parse_selector(style)
        return name.strip(), grey, width
    except ValueError:
        raise ValueError(f"bad layer spec {spec!r}; expected NAME=grey[@width]")


def matches(seg, grey: float, width: float | None) -> bool:
    """Does a segment's stroke style match a ``grey[@width]`` selector?"""
    if seg.color is None:
        return False
    # plotted sheets use neutral pens; a coloured stroke is never a contour
    if max(seg.color) - min(seg.color) > 1e-3:
        return False
    if abs(seg.color[0] - grey) > 1e-3:
        return False
    return width is None or abs(seg.width - width) < 0.01


def pen_table(segs) -> list[dict]:
    """The sheet's pen table: (grey, width, coloured) by count and length.

    On a plotted set the pen table IS the layer table — profile a sheet with
    this before picking selectors. Rows are dicts (``grey`` is None for
    unstroked paths) sorted by segment count, ready for tabular printing.
    """
    n: Counter = Counter()
    length: Counter = Counter()
    for s in segs:
        grey = None if s.color is None else round(s.color[0], 3)
        chroma = 0.0 if s.color is None else max(s.color) - min(s.color)
        key = (grey, round(s.width, 2), chroma > 1e-3)
        n[key] += 1
        length[key] += s.length
    return [{"grey": grey, "width": width, "coloured": coloured,
             "segments": count,
             "length_pt": round(length[(grey, width, coloured)], 1)}
            for (grey, width, coloured), count in n.most_common()]


@dataclass(frozen=True)
class LayerSpec:
    """One ``--layer`` selector: a pen style (``kind="pen"``) or an OCG-name
    glob (``kind="ocg"``, matched case-sensitively against the full
    ``Parent|Child`` name the extractor reports)."""

    name: str
    kind: str
    grey: float | None = None
    width: float | None = None
    glob: str | None = None

    @property
    def selector(self) -> str:
        if self.kind == "ocg":
            return f"ocg:{self.glob}"
        return f"{self.grey:g}" + ("" if self.width is None else f"@{self.width:g}")


_SPEC_HELP = "expected NAME=grey[@width] or NAME=ocg:<glob>"


def parse_layer_spec(spec: str) -> LayerSpec:
    """``NAME=grey[@width]`` or ``NAME=ocg:<glob>`` -> LayerSpec."""
    name, sep, style = spec.partition("=")
    name = name.strip()
    if not sep or not name:
        raise ValueError(f"bad layer spec {spec!r}; {_SPEC_HELP}")
    if style.startswith("ocg:"):
        if not style[4:]:
            raise ValueError(f"bad layer spec {spec!r}; empty ocg glob")
        return LayerSpec(name, "ocg", glob=style[4:])
    try:
        grey, width = parse_selector(style)
    except ValueError:
        raise ValueError(f"bad layer spec {spec!r}; {_SPEC_HELP}") from None
    return LayerSpec(name, "pen", grey=grey, width=width)


def select_segments(segs, spec: LayerSpec) -> list:
    """The segments a LayerSpec picks (OCG glob, or pen style via ``matches``)."""
    if spec.kind == "ocg":
        return [s for s in segs
                if getattr(s, "layer", None)
                and fnmatch.fnmatchcase(s.layer, spec.glob)]
    return [s for s in segs if matches(s, spec.grey, spec.width)]


def ocg_table(segs) -> list[dict]:
    """The sheet's OCG table: layer name -> segment count, length, pens.

    A plotted Civil 3D set often keeps its CAD layer names as PDF optional
    content; when it does, this is a better layer table than the pen table.
    Rows are sorted by segment count; untagged paths form one ``layer: None``
    row. Returns ``[]`` when no segment carries a layer (layer-flattened).
    """
    n: Counter = Counter()
    length: Counter = Counter()
    pens: dict = defaultdict(set)
    for s in segs:
        lay = getattr(s, "layer", None)
        n[lay] += 1
        length[lay] += s.length
        grey = "-" if s.color is None else f"{round(s.color[0], 3):g}"
        pens[lay].add(f"{grey}@{round(s.width, 2):g}")
    if set(n) <= {None}:
        return []
    return [{"layer": lay, "segments": count,
             "length_pt": round(length[lay], 1), "pens": sorted(pens[lay])}
            for lay, count in n.most_common()]


def _as_spec(selector) -> LayerSpec:
    if isinstance(selector, LayerSpec):
        return selector
    if isinstance(selector, str):
        if selector.startswith("ocg:"):
            if not selector[4:]:
                raise ValueError(f"bad selector {selector!r}; empty ocg glob")
            return LayerSpec("", "ocg", glob=selector[4:])
        grey, width = parse_selector(selector)
        return LayerSpec("", "pen", grey=grey, width=width)
    grey, width = selector
    return LayerSpec("", "pen", grey=grey, width=width)


# ------------------------------------------------------------------ chaining
def chain(segs, tol: float = CHAIN_TOL_PT) -> list[list[tuple[float, float]]]:
    """Reassemble 2-point segments into polylines by shared endpoints.

    Walks each unused segment out in both directions.  A vertex with more than
    two incident segments (contours crossing linework, or a label gap closed by
    a leader) stops the walk rather than guessing a branch — a contour that
    breaks into two polylines is recoverable, one that wrongly jumps onto a
    neighbouring contour is not.
    """
    def key(x: float, y: float) -> tuple[int, int]:
        return (int(round(x / tol)), int(round(y / tol)))

    incident: dict[tuple[int, int], list[int]] = defaultdict(list)
    ends = []
    for i, s in enumerate(segs):
        a, b = key(s.x1, s.y1), key(s.x2, s.y2)
        if a == b:                                   # degenerate
            ends.append(None)
            continue
        ends.append((a, b))
        incident[a].append(i)
        incident[b].append(i)

    used = [False] * len(segs)
    out: list[list[tuple[float, float]]] = []

    def step(node, came_from):
        """The single unused continuation at `node`, or None at a branch/end."""
        nxt = [j for j in incident[node] if not used[j] and j != came_from]
        return nxt[0] if len(nxt) == 1 and len(incident[node]) <= 2 else None

    for i, s in enumerate(segs):
        if used[i] or ends[i] is None:
            continue
        used[i] = True
        pts = [(s.x1, s.y1), (s.x2, s.y2)]
        # walk forward off the tail, then backward off the head
        for forward in (True, False):
            node = ends[i][1] if forward else ends[i][0]
            prev = i
            while (j := step(node, prev)) is not None:
                used[j] = True
                t = segs[j]
                a, b = ends[j]
                nxt, pt = (b, (t.x2, t.y2)) if a == node else (a, (t.x1, t.y1))
                if forward:
                    pts.append(pt)
                else:
                    pts.insert(0, pt)
                node, prev = nxt, j
        out.append(pts)
    return out


def _unit(ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    n = math.hypot(dx, dy)
    return (0.0, 0.0) if n == 0 else (dx / n, dy / n)


def _close_pairs(pts, radius: float) -> list[tuple[int, int]]:
    """Index pairs within ``radius`` — cKDTree when scipy is present, else O(n²).

    Chain-end counts are small (hundreds on a busy grading sheet), so the
    brute-force fallback keeps ``bridge`` usable without the
    ``bimforge[terrain]`` extra installed.
    """
    try:
        import numpy as np
        from scipy.spatial import cKDTree
    except ImportError:
        return [(i, j) for i in range(len(pts)) for j in range(i + 1, len(pts))
                if math.dist(pts[i], pts[j]) <= radius]
    tree = cKDTree(np.asarray(pts))
    return [(int(a), int(b))
            for a, b in tree.query_pairs(radius, output_type="ndarray")]


def bridge(chains, gap_pt: float, max_turn_deg: float):
    """Re-stitch a dashed linetype that CAD exploded into separate strokes.

    Existing-ground contours are routinely plotted dashed, so shared-endpoint
    chaining leaves one polyline per dash.  This joins two chain ends when the
    jump is short enough AND both ends point at each other — the direction test
    is what stops it hopping onto the neighbouring contour, which at a 1 ft
    interval on a 2:1 slope can sit only a few points away.
    """
    cos_max = math.cos(math.radians(max_turn_deg))
    chains = [list(c) for c in chains]
    alive = [True] * len(chains)

    def ends_of(i):
        """((pos, outward dir) for head, for tail) of chain i."""
        c = chains[i]
        head = (c[0], _unit(c[1][0], c[1][1], c[0][0], c[0][1]))
        tail = (c[-1], _unit(c[-2][0], c[-2][1], c[-1][0], c[-1][1]))
        return head, tail

    for _ in range(64):                              # converges long before this
        idx, meta = [], []
        for i, c in enumerate(chains):
            if not alive[i] or len(c) < 2 or is_closed(c, gap_pt * 0.05):
                continue
            for which, (pos, direction) in enumerate(ends_of(i)):
                idx.append(pos)
                meta.append((i, which, direction))
        if len(idx) < 2:
            break

        scored = []
        for a, b in _close_pairs(idx, gap_pt):
            ia, wa, da = meta[a]
            ib, wb, db = meta[b]
            if ia == ib:                             # would close the loop
                continue
            v = _unit(idx[a][0], idx[a][1], idx[b][0], idx[b][1])
            if v == (0.0, 0.0):
                continue
            fwd = da[0] * v[0] + da[1] * v[1]        # A points at B
            back = -(db[0] * v[0] + db[1] * v[1])    # B points at A
            turn = -(da[0] * db[0] + da[1] * db[1])  # the two runs stay parallel
            if fwd < cos_max or back < cos_max or turn < cos_max:
                continue
            scored.append((min(fwd, back, turn), a, b))

        scored.sort(reverse=True)
        taken, joined = set(), 0
        for _score, a, b in scored:
            if a in taken or b in taken:
                continue
            ia, wa, _ = meta[a]
            ib, wb, _ = meta[b]
            if not (alive[ia] and alive[ib]) or ia == ib:
                continue
            ca = chains[ia][::-1] if wa == 0 else chains[ia]   # A's tail meets B
            cb = chains[ib][::-1] if wb == 1 else chains[ib]   # B's head leads
            chains[ia] = ca + cb
            alive[ib] = False
            taken.add(a)
            taken.add(b)
            joined += 1
        if not joined:
            break
    return [c for i, c in enumerate(chains) if alive[i]]


# -------------------------------------------------------------------- georef
def parse_tie(spec: str):
    """``px,py=northing,easting`` -> ((px, py), (n, e)), unrotated page points."""
    try:
        page, world = spec.split("=", 1)
        px, py = (float(v) for v in page.split(","))
        n, e = (float(v) for v in world.split(","))
        return (px, py), (n, e)
    except ValueError:
        raise ValueError(f"bad tie {spec!r}; expected px,py=northing,easting")


def solve_georef(ties):
    """Least-squares similarity page(pt, y down) -> survey (easting, northing).

    Returns (fn, scale_ft_per_pt, residuals_ft).  Two ties determine it exactly;
    more are averaged and the residuals become the check worth quoting.  Solved
    as a complex linear fit, which is the tidy way to get rotation and scale
    together: w = a*z + b with z = px + i*(-py) and w = E + i*N.
    """
    if len(ties) < 2:
        raise ValueError("georeferencing needs at least two tie points")
    z = [complex(p[0], -p[1]) for p, _ in ties]
    w = [complex(ne[1], ne[0]) for _, ne in ties]        # (E, N)
    zm = sum(z) / len(z)
    wm = sum(w) / len(w)
    num = sum((zi - zm).conjugate() * (wi - wm) for zi, wi in zip(z, w))
    den = sum(abs(zi - zm) ** 2 for zi in z)
    a = (num / den) if den else 0j
    b = wm - a * zm
    res = [abs(a * zi + b - wi) for zi, wi in zip(z, w)]

    def fn(px, py):
        v = a * complex(px, -py) + b
        return (v.real, v.imag)                          # (easting, northing)

    return fn, abs(a), res


def affine_coeffs(fn) -> tuple[float, float, float, float, float, float]:
    """(a, b, c, d, e, f) of an affine page->world map.

    ``E = a*x + b*y + c`` and ``N = d*x + e*y + f`` in page points (y down).
    Sampled at three points — exact for any affine map, and every georef in
    this module (similarity ties, affine ties, calibration zones, GeoPDF
    viewports) is one.
    """
    c, f = fn(0.0, 0.0)
    e1, n1 = fn(1.0, 0.0)
    e2, n2 = fn(0.0, 1.0)
    return (e1 - c, e2 - c, c, n1 - f, n2 - f, f)


def solve_georef_affine(ties):
    """Least-squares 6-parameter affine page(pt, y down) -> survey (E, N).

    Needs >= 3 non-collinear ties. Unlike ``solve_georef`` (a similarity) it
    absorbs anisotropic paper stretch, which is what a scanned sheet has.
    Returns ``(fn, (scale_x, scale_y), residuals_ft)``.
    """
    if len(ties) < 3:
        raise ValueError("an affine georeference needs at least three tie points")
    import numpy as np
    P = np.asarray([p for p, _ in ties], dtype=float)
    W = np.asarray([(ne[1], ne[0]) for _, ne in ties], dtype=float)   # (E, N)
    A = np.c_[P, np.ones(len(P))]
    if np.linalg.matrix_rank(A) < 3:
        raise ValueError("affine tie points are collinear")
    coef, *_ = np.linalg.lstsq(A, W, rcond=None)
    a, b, c = (float(v) for v in coef[:, 0])
    d, e, f = (float(v) for v in coef[:, 1])
    res = [float(r) for r in np.linalg.norm(A @ coef - W, axis=1)]

    def fn(px, py):
        return (a * px + b * py + c, d * px + e * py + f)

    return fn, (math.hypot(a, d), math.hypot(b, e)), res


@dataclass(frozen=True)
class Georef:
    """A page point (unrotated, y down) -> world feet map plus its provenance.

    ``method`` is how it was obtained (``ties`` | ``geopdf`` | ``calibration``),
    ``frame`` the manifest frame it puts points in, ``ft_per_pt`` the mean
    scale (closure tolerance and drift checks follow it).
    """

    to_world: Callable[[float, float], tuple[float, float]]
    method: str
    frame: str
    ft_per_pt: float
    model: str = "affine"
    crs_epsg: int | None = None
    residuals_ft: tuple = ()
    n_ties: int = 0

    def transform(self) -> list[float]:
        return [round(v, 9) for v in affine_coeffs(self.to_world)]

    def record(self) -> dict:
        """The manifest-v2 top-level ``georef`` block."""
        rec = {"method": self.method, "model": self.model, "frame": self.frame,
               "ft_per_pt": self.ft_per_pt, "transform": self.transform(),
               "residuals_ft": [round(r, 4) for r in self.residuals_ft]}
        if self.crs_epsg is not None:
            rec["crs_epsg"] = self.crs_epsg
        return rec


def georef_from_ties(ties, model: str = "similarity") -> Georef:
    """Survey ties -> Georef (``similarity`` needs >= 2, ``affine`` >= 3)."""
    ties = list(ties)
    if model == "affine":
        fn, (sx, sy), res = solve_georef_affine(ties)
        if not (math.isfinite(sx) and math.isfinite(sy)) or sx <= 0 or sy <= 0:
            raise ValueError("tie points are degenerate (zero fitted scale)")
        scale = (sx + sy) / 2.0
    elif model == "similarity":
        fn, scale, res = solve_georef(ties)
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError("tie points are degenerate (zero fitted scale)")
    else:
        raise ValueError(f"unknown tie model {model!r} (similarity | affine)")
    return Georef(fn, "ties", "state_plane_ft", scale, model=model,
                  residuals_ft=tuple(res), n_ties=len(ties))


def georef_from_zone(zone) -> Georef:
    """An ``est-bim calibrate`` zone -> Georef in sheet-local feet."""
    residual = getattr(zone, "residual_ft", None)
    return Georef(zone.to_world, "calibration", "sheet_local_ft",
                  zone.ft_per_pt, model="similarity",
                  residuals_ft=(residual,) if residual is not None else ())


def georef_from_viewport(vp) -> Georef:
    """A GeoPDF ``Viewport`` (``plansheet.geopdf``) -> Georef in its CRS feet."""
    return Georef(vp.to_world, "geopdf", "state_plane_ft",
                  (vp.scale_x + vp.scale_y) / 2.0, model="affine",
                  crs_epsg=vp.crs_epsg, residuals_ft=tuple(vp.residuals_ft))


def crosscheck_ties_vs_viewport(ties, ft_per_pt: float, vp):
    """Independent check of a ties georeference against a GeoPDF viewport (#231).

    When survey ties win, the page's GeoPDF viewport is the only INDEPENDENT
    witness to whether the viewport itself is trustworthy — and vice versa. A
    four-point affine fit absorbs a uniform ``/BBox`` error into its residuals,
    so the viewport's own residuals cannot reveal it; comparing the viewport's
    mapping against the surveyed ties can. Pure and non-fatal: it only measures.

    ``ties`` are ``((px, py), (n, e))`` as ``parse_tie`` returns; ``ft_per_pt``
    is the ties' fitted scale. Returns ``(scale_drift_pct, max_offset_ft,
    all_inside)`` — the viewport-vs-ties scale drift (percent), the largest
    distance between a tie's surveyed point and where the viewport maps that
    page point, and whether every tie falls inside the viewport's bbox.
    """
    vp_scale = (vp.scale_x + vp.scale_y) / 2.0
    drift = 100.0 * (ft_per_pt / vp_scale - 1.0) if vp_scale else math.inf
    max_off = 0.0
    all_inside = True
    for (px, py), (n, e) in ties:
        we, wn = vp.to_world(px, py)          # viewport maps page -> (E, N)
        max_off = max(max_off, math.hypot(we - e, wn - n))
        all_inside = all_inside and vp.contains(px, py)
    return drift, max_off, all_inside


@dataclass(frozen=True)
class _ClippedSeg:
    """A segment truncated by ``clip_segment``. A lightweight stand-in (not the
    input's type) so clipping works on any duck-typed segment, carrying only
    what the downstream chain/group step reads: endpoints, layer, pen."""

    x1: float
    y1: float
    x2: float
    y2: float
    layer: object = None
    width: float = 0.0
    color: object = None

    @property
    def length(self) -> float:
        return math.hypot(self.x2 - self.x1, self.y2 - self.y1)


def clip_segment(seg, rect):
    """Clip a 2-point segment to a page rectangle (#243), Liang-Barsky.

    Returns a lightweight clipped segment (``_ClippedSeg``) carrying the
    endpoints plus layer/pen fields used downstream, truncated to
    ``rect = (x0, y0, x1, y1)`` page points, or ``None`` if it lies wholly
    outside. A segment crossing the boundary is CUT at it, not dropped — a real
    contour running off the plan view keeps its inside portion, while a
    title-block glyph outside the view disappears entirely."""
    ax, ay, bx, by = rect
    xmin, xmax = (ax, bx) if ax <= bx else (bx, ax)
    ymin, ymax = (ay, by) if ay <= by else (by, ay)
    x1, y1, x2, y2 = seg.x1, seg.y1, seg.x2, seg.y2
    dx, dy = x2 - x1, y2 - y1
    p = (-dx, dx, -dy, dy)
    q = (x1 - xmin, xmax - x1, y1 - ymin, ymax - y1)
    u1, u2 = 0.0, 1.0
    for pi, qi in zip(p, q):
        if pi == 0.0:
            if qi < 0.0:            # parallel to an edge and outside it
                return None
        else:
            t = qi / pi
            if pi < 0.0:
                if t > u2:
                    return None
                u1 = max(u1, t)
            else:
                if t < u1:
                    return None
                u2 = min(u2, t)
    if u1 > u2:
        return None
    return _ClippedSeg(
        x1 + u1 * dx, y1 + u1 * dy, x1 + u2 * dx, y1 + u2 * dy,
        getattr(seg, "layer", None), getattr(seg, "width", 0.0),
        getattr(seg, "color", None))


def _inside(seg, bounds) -> bool:
    x0, y0, x1, y1 = bounds
    return (x0 <= seg.x1 <= x1 and y0 <= seg.y1 <= y1
            and x0 <= seg.x2 <= x1 and y0 <= seg.y2 <= y1)


# ------------------------------------------------------------------ geometry
def polyline_length(pts) -> float:
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def is_closed(pts, tol: float) -> bool:
    return len(pts) > 2 and math.dist(pts[0], pts[-1]) <= tol


# -------------------------------------------------------------- orchestrator
def extract_contours(sheet, selector, calibration=None, *,
                     zone: str | None = None,
                     ties=None,
                     georef=None,
                     bounds=None,
                     clip=None,
                     min_length_ft: float = 20.0,
                     gap_pt: float = 0.0,
                     gap_angle_deg: float = 25.0) -> dict:
    """Extract one pen style's contour polylines from an extracted sheet.

    ``sheet`` is the plansheet extractor's output (``vectors.extract_sheet``'s
    ``SheetVectors`` — only ``.segments`` is consumed).  ``selector`` is a
    ``LayerSpec``, an ``"ocg:<glob>"`` string, a ``grey[@width]`` string, or a
    ``(grey, width_or_None)`` tuple.  OCG selections chain per layer name (a
    line never joins across OCGs); each returned line carries ``source``.

    The page->world map comes from, in precedence order: an explicit
    ``georef`` (a ``Georef``, see ``georef_from_ties``/``_zone``/
    ``_viewport``); else ``ties`` (``parse_tie`` records, similarity-fit via
    ``georef_from_ties``); else ``calibration`` (a ``calibrate.Calibration``,
    with ``zone`` picking the view zone, or a zone-like object with
    ``to_world``/``ft_per_pt``/``method``) via ``georef_from_zone``. At least
    one of the three is required, or ``ValueError`` is raised. ``bounds =
    (x0, y0, x1, y1)`` (page points) drops picked segments not wholly inside
    before chaining, and the count dropped is recorded as
    ``rec["outside_bounds"]``. ``gap_pt > 0`` re-stitches dashed linetypes
    (``bridge``); polylines shorter than ``min_length_ft`` (leaders, tick
    marks, hatch remnants) are dropped.

    Returns a manifest-layer record: selection/chain counts plus ``lines`` —
    per polyline world-feet ``points``, ``length_ft``, ``closed``, ``source``,
    and ``elevation: None`` (labels are read visually downstream, never here).
    When ``georef.method == "ties"`` the record also carries the legacy
    per-layer ``rec["georef"] = {"ties", "scale_ft_per_pt", "residuals_ft"}``
    block so callers can quote the drift against the calibration.
    """
    spec = _as_spec(selector)
    selector_str = selector if isinstance(selector, str) else spec.selector

    z = None
    if calibration is not None:
        z = calibration.zone(zone) if hasattr(calibration, "zone") else calibration
    if georef is None:
        if ties:
            georef = georef_from_ties(ties)
        elif z is not None:
            georef = georef_from_zone(z)
        else:
            raise ValueError("extract_contours needs a calibration, ties, or a georef")
    to_world = georef.to_world
    frame = georef.frame
    # the EFFECTIVE ft/pt follows the frame the points are actually in
    eff_ft_per_pt = georef.ft_per_pt

    picked = select_segments(sheet.segments, spec)
    clipped_n = 0
    if clip is not None:
        # cut picked segments to the plan rectangle: a crossing contour keeps
        # its inside portion, a title-block glyph outside the view is dropped.
        kept_segs = [c for s in picked
                     if (c := clip_segment(s, clip)) is not None]
        clipped_n = len(picked) - len(kept_segs)
        picked = kept_segs
    outside = 0
    if bounds is not None:
        inside = [s for s in picked if _inside(s, bounds)]
        outside = len(picked) - len(inside)
        picked = inside
    if spec.kind == "ocg":
        groups: dict = defaultdict(list)
        for s in picked:
            groups[s.layer].append(s)
        grouped = [(lay, chain(ss)) for lay, ss in sorted(groups.items())]
    else:
        grouped = [(None, chain(picked))]
    raw_chains = sum(len(c) for _, c in grouped)
    if gap_pt > 0:
        grouped = [(lay, bridge(c, gap_pt, gap_angle_deg)) for lay, c in grouped]
    stitched = sum(len(c) for _, c in grouped)
    tol_ft = CHAIN_TOL_PT * eff_ft_per_pt

    kept = []
    for lay, chains in grouped:
        source = ({"kind": "vector-ocg", "ocg": lay} if spec.kind == "ocg"
                  else {"kind": "vector-pen", "selector": selector_str})
        for pts in chains:
            world = [to_world(x, y) for x, y in pts]
            length = polyline_length(world)
            if length < min_length_ft:
                continue
            kept.append({"points": [[round(x, 3), round(y, 3)] for x, y in world],
                         "length_ft": round(length, 2),
                         "closed": is_closed(world, tol_ft),
                         "elevation": None,
                         "source": dict(source)})
    kept.sort(key=lambda r: -r["length_ft"])

    rec = {"selector": selector_str,
           "frame": frame,
           "ft_per_pt": eff_ft_per_pt,
           "calibration_method": getattr(z, "method", "") if z is not None else "",
           "segments": len(picked),
           "raw_chains": raw_chains,
           "stitched_chains": stitched,
           "polylines": len(kept),
           "total_length_ft": round(sum(r["length_ft"] for r in kept), 1),
           "closed": sum(1 for r in kept if r["closed"]),
           "lines": kept}
    if clip is not None:
        rec["clipped"] = clipped_n
    if bounds is not None:
        rec["outside_bounds"] = outside
    if georef.method == "ties":
        rec["georef"] = {"ties": georef.n_ties,
                         "scale_ft_per_pt": georef.ft_per_pt,
                         "residuals_ft": [round(r, 4) for r in georef.residuals_ft]}
    return rec
