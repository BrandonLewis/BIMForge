"""Contour-label candidates for ``est-bim label-crops``.

A flattened plan set letters its contours as outlined glyphs, so a reader
(the agent's vision, spot-checked by the estimator) has to see every label.
This finds where the labels are so each gets a crop and nothing is guessed.
Three sources, layer-agnostic by default (spec §4):

  mask   white-filled small closed paths that a selected contour passes
         through — the background mask behind a contour label. Primary: on
         a real foundation-plan sheet the labels were stroked, on the
         structures annotation layer, over unbroken contours, and masks
         alone found 15 of 16 hand-read labels within 10 pt.
  gap    facing ends of the same layer's contours across a label-sized gap,
         both sides at least ``min_line`` long — sheets that break the line
         for the label (and, in phase 4, raster sheets).
  layer  small path clusters on a named label layer (``--labels ocg:GLOB``)
         within a few points of a contour. Opt-in: an annotation layer can
         hold hundreds of unrelated glyphs.

Spot elevations come from marker clusters on a named layer; their crop is
enlarged to take in the adjacent number.

Everything is in unrotated page points (y down) — the frame of
``page.get_drawings()`` and of anchors ``page:`` records. The finders take
duck-typed drawings (dicts with ``layer``, ``fill``, ``rect``) and v2
manifests, so they test without pymupdf. A mask can only be found over a
line the manifest carries: extract every contour class, with a small
minimum length, first. No elevation is ever proposed.
"""
from __future__ import annotations

import fnmatch
import math
from dataclasses import dataclass

__all__ = [
    "Candidate", "page_lines", "mask_candidates", "gap_candidates",
    "layer_candidates", "spot_candidates", "nearest_line", "dedupe",
    "find_candidates",
]

#: a contour-label mask is a small white-filled box (page points)
MASK_MAX_W_PT, MASK_MAX_H_PT, MASK_MIN_AREA_PT2 = 80.0, 40.0, 4.0
#: a label gap: its length, how squarely the ends face, and the minimum
#: length of each side (short fragments make hundreds of false gaps)
GAP_MIN_PT, GAP_MAX_PT, GAP_COS_MIN, GAP_MIN_LINE_PT = 4.0, 40.0, 0.8, 80.0
#: label-layer glyph clusters: largest side, distance to a contour, join gap
LAYER_MAX_PT, LAYER_NEAR_PT, GLYPH_JOIN_PT = 30.0, 6.0, 2.5
#: candidates closer than this are one label (kept by source priority)
DEDUPE_PT = 6.0
#: crop half-size around a label candidate / a spot marker, page points
CROP_HALF_PT, SPOT_HALF_PT = 24.0, 36.0
_PRIORITY = {"mask": 0, "gap": 1, "layer": 2, "spot": 3}


@dataclass
class Candidate:
    """A place a reader should look: page point, source, crop box, contour."""

    page: tuple
    source: str
    bbox: tuple
    line: int | None = None
    dist_ft: float | None = None
    margin_ft: float | None = None


def _rect(d):
    x0, y0, x1, y1 = (float(v) for v in d["rect"])
    return x0, y0, x1, y1


def _box(cx, cy, half):
    return (cx - half, cy - half, cx + half, cy + half)


def _affine(manifest):
    t = (manifest.get("georef") or {}).get("transform")
    if not t or len(t) != 6:
        raise ValueError("label-crops needs a v2 contours manifest (its "
                         "georef.transform maps page points to world feet)")
    return tuple(float(v) for v in t)


def page_lines(manifest):
    """Manifest lines back in page points: ``[{"id", "layer", "page", "world"}]``."""
    import numpy as np
    a, b, c, d, e, f = _affine(manifest)
    det = a * e - b * d
    if det == 0:
        raise ValueError("manifest georef.transform is singular")
    out = []
    for name, rec in manifest["layers"].items():
        for ln in rec["lines"]:
            w = np.asarray(ln["points"], dtype=float).reshape(-1, 2)
            du, dv = w[:, 0] - c, w[:, 1] - f
            out.append({"id": len(out), "layer": name, "world": w,
                        "page": np.column_stack([(e * du - b * dv) / det,
                                                 (-d * du + a * dv) / det])})
    return out


def _page_length(pts):
    import numpy as np
    return float(np.sum(np.hypot(*np.diff(pts, axis=0).T))) if len(pts) > 1 else 0.0


def _line_tree(lines, key="page"):
    from shapely import STRtree
    from shapely.geometry import LineString
    geoms = [LineString(ln[key]) if len(ln[key]) > 1 else None for ln in lines]
    keep = [i for i, g in enumerate(geoms) if g is not None]
    return STRtree([geoms[i] for i in keep]), keep, geoms


def mask_candidates(drawings, lines, *, max_w=MASK_MAX_W_PT,
                    max_h=MASK_MAX_H_PT, min_area=MASK_MIN_AREA_PT2):
    """White-filled small closed paths that a contour line passes through."""
    from shapely.geometry import box
    tree, _keep, _geoms = _line_tree(lines)
    out = []
    for d in drawings:
        fill = d.get("fill")
        if not fill or min(fill) < 0.99:
            continue
        x0, y0, x1, y1 = _rect(d)
        w, h = x1 - x0, y1 - y0
        if w > max_w or h > max_h or w * h < min_area:
            continue
        if len(tree.query(box(x0, y0, x1, y1), predicate="intersects")):
            cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            half = max(CROP_HALF_PT, w / 2.0 + 8.0, h / 2.0 + 8.0)
            out.append(Candidate((cx, cy), "mask", _box(cx, cy, half)))
    return out


def gap_candidates(lines, *, min_gap=GAP_MIN_PT, max_gap=GAP_MAX_PT,
                   cos_min=GAP_COS_MIN, min_line=GAP_MIN_LINE_PT):
    """Facing ends of same-layer contours across a label-sized gap."""
    import numpy as np
    ends = []
    for ln in lines:
        p = ln["page"]
        if len(p) < 2 or _page_length(p) < min_line:
            continue
        for tip, prev in ((p[0], p[1]), (p[-1], p[-2])):
            v = tip - prev
            n = float(np.hypot(*v))
            if n > 0:
                ends.append((ln["layer"], ln["id"], tip, v / n))
    out = []
    for i in range(len(ends)):
        li, idi, pi, di = ends[i]
        for j in range(i + 1, len(ends)):
            lj, idj, pj, dj = ends[j]
            if lj != li or idj == idi:
                continue
            v = pj - pi
            gap = float(np.hypot(*v))
            if not min_gap <= gap <= max_gap:
                continue
            u = v / gap
            if di @ u >= cos_min and -(dj @ u) >= cos_min:
                cx, cy = (float(x) for x in (pi + pj) / 2.0)
                half = max(CROP_HALF_PT, gap / 2.0 + 8.0)
                out.append(Candidate((cx, cy), "gap", _box(cx, cy, half)))
    return out


def _clusters(rects, join):
    """Union rectangles closer than ``join`` points (union-find)."""
    parent = list(range(len(rects)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(rects)):
        a = rects[i]
        for j in range(i + 1, len(rects)):
            b = rects[j]
            if (b[0] <= a[2] + join and b[2] >= a[0] - join
                    and b[1] <= a[3] + join and b[3] >= a[1] - join):
                parent[root(i)] = root(j)
    groups: dict = {}
    for i in range(len(rects)):
        groups.setdefault(root(i), []).append(rects[i])
    return [(min(r[0] for r in g), min(r[1] for r in g),
             max(r[2] for r in g), max(r[3] for r in g))
            for g in groups.values()]


def _on_layer(drawings, glob, max_pt):
    out = []
    for d in drawings:
        lay = d.get("layer")
        if lay and fnmatch.fnmatchcase(lay, glob):
            x0, y0, x1, y1 = _rect(d)
            if max(x1 - x0, y1 - y0) <= max_pt:
                out.append((x0, y0, x1, y1))
    return out


def layer_candidates(drawings, glob, lines, *, max_pt=LAYER_MAX_PT,
                     near=LAYER_NEAR_PT, join=GLYPH_JOIN_PT):
    """Glyph clusters on a label layer within ``near`` pt of a contour."""
    from shapely.geometry import box
    tree, _keep, _geoms = _line_tree(lines)
    out = []
    for x0, y0, x1, y1 in _clusters(_on_layer(drawings, glob, max_pt), join):
        if max(x1 - x0, y1 - y0) > max_pt:
            continue
        if len(tree.query(box(x0, y0, x1, y1).buffer(near),
                          predicate="intersects")):
            cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            out.append(Candidate((cx, cy), "layer", _box(cx, cy, CROP_HALF_PT)))
    return out


def spot_candidates(drawings, glob, *, max_pt=20.0, join=GLYPH_JOIN_PT):
    """Spot-elevation marker clusters; the crop takes in the adjacent number."""
    out = []
    for x0, y0, x1, y1 in _clusters(_on_layer(drawings, glob, max_pt), join):
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        out.append(Candidate((cx, cy), "spot", _box(cx, cy, SPOT_HALF_PT)))
    return out


def nearest_line(cands, lines, manifest):
    """Fill each candidate's nearest contour, distance and margin (world ft)."""
    from shapely.geometry import Point
    a, b, c, d, e, f = _affine(manifest)
    _tree, keep, geoms = _line_tree(lines, key="world")
    for cand in cands:
        x, y = cand.page
        pt = Point(a * x + b * y + c, d * x + e * y + f)
        dists = sorted((geoms[i].distance(pt), i) for i in keep)
        if dists:
            cand.dist_ft = round(float(dists[0][0]), 3)
            cand.line = int(lines[dists[0][1]]["id"])
            cand.margin_ft = (round(float(dists[1][0] - dists[0][0]), 3)
                              if len(dists) > 1 else None)
    return cands


def dedupe(cands, radius=DEDUPE_PT):
    """One candidate per label: the highest-priority source within ``radius``."""
    kept = []
    for cand in sorted(cands, key=lambda c: (_PRIORITY.get(c.source, 9),
                                             c.page[1], c.page[0])):
        if all(math.dist(cand.page, k.page) > radius for k in kept):
            kept.append(cand)
    return sorted(kept, key=lambda c: (c.page[1], c.page[0]))


def find_candidates(drawings, manifest, *, sources=("mask", "gap"),
                    labels_glob=None, spots_glob=None):
    """``(labels, spots)``: deduplicated label candidates and spot markers."""
    lines = page_lines(manifest)
    cands = []
    if "mask" in sources:
        cands += mask_candidates(drawings, lines)
    if "gap" in sources:
        cands += gap_candidates(lines)
    if labels_glob:
        cands += layer_candidates(drawings, labels_glob, lines)
    labels = nearest_line(dedupe(cands), lines, manifest)
    spots = spot_candidates(drawings, spots_glob) if spots_glob else []
    return labels, spots
