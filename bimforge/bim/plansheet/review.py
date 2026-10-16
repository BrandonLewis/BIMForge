"""Contour reconciliation review: the findings a person has to look at.

What ``est-bim contour-surface --review-dir`` writes: ``review.md`` (one
section per finding), ``findings.json`` (the same, as data), ``lines.csv``
(one row per contour — the audit trail) and, with the plan PDF, one overlay
crop per finding plus a contact sheet. pymupdf (``fitz``) is imported only
inside the crop functions.
"""
from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path

__all__ = ["REVIEW_OUTPUT", "REVIEW_MARKER", "LINE_COLUMNS", "check_review_dir",
           "clear_stale", "line_rows", "write_review", "affine_of",
           "world_to_page", "render_crops", "contact_sheet"]

#: what --review-dir writes, and so may clear from a previous run
REVIEW_OUTPUT = (r"(?:F[0-9]{2,}\.png|contact-sheet\.pdf|contact-sheet-[0-9]{2,}\.png"
                 r"|review\.md|findings\.json|lines\.csv)")
#: marks a directory --review-dir wrote, so a later run may clear it
REVIEW_MARKER = ".contour-review"
LINE_COLUMNS = ["line", "sheet", "layer", "role", "length_ft", "faces", "same",
                "joints", "contacts", "status", "lo", "hi", "values",
                "assigned", "reason"]


def _review_outputs(out_dir):
    """The review outputs already in ``out_dir``. ``ValueError`` when there
    are some but the directory carries no ``REVIEW_MARKER``: they are
    somebody's own files, not a previous run's."""
    out = Path(out_dir)
    if out.exists() and not out.is_dir():
        raise ValueError(f"{out} is a file, not a directory")
    if not out.is_dir():
        return []
    found = sorted(p for p in out.iterdir()
                   if p.is_file() and re.fullmatch(REVIEW_OUTPUT, p.name))
    if found and not (out / REVIEW_MARKER).is_file():
        raise ValueError(
            f"{out} already has {', '.join(p.name for p in found[:3])}"
            f"{' …' if len(found) > 3 else ''} but no {REVIEW_MARKER}: it is "
            "not a review directory this command wrote — use a new or empty "
            "directory")
    return found


def check_review_dir(out_dir) -> None:
    """Refuse (``ValueError``) a directory :func:`clear_stale` would not clear."""
    _review_outputs(out_dir)


def clear_stale(out_dir) -> int:
    """Remove a previous run's review outputs (only those); return the count.

    The directory is marked (``REVIEW_MARKER``) as a review directory. One
    that holds review-output names but no marker is refused, never cleared
    (see :func:`check_review_dir`).
    """
    found = _review_outputs(out_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / REVIEW_MARKER).write_text(
        "written by est-bim contour-surface --review-dir\n", encoding="utf-8")
    for p in found:
        p.unlink()
    return len(found)


def line_rows(polys, graph, rec, elev, *, roles=None, added=None, prop_rows=()):
    """One ``lines.csv`` row per contour (keys: ``LINE_COLUMNS``)."""
    from bimforge.terrain.reconcile import _length
    roles, added = roles or {}, added or {}
    reason = {r["line"]: r["reason"] for r in prop_rows}
    deg = {k: {"faces": 0, "same": 0, "joints": 0, "contacts": 0}
           for k in range(len(polys))}
    for name, pairs in (("faces", graph.faces), ("same", graph.same),
                        ("joints", graph.joints),
                        ("contacts", [c.pair for c in graph.contacts])):
        for a, b in pairs:
            deg[a][name] += 1
            deg[b][name] += 1
    rows = []
    for i, (p, src, lay) in enumerate(polys):
        lr = rec.lines.get(i) if rec is not None else None
        if lr is not None:
            status, vals = lr.status, lr.values
        else:
            status = "lettered" if i in elev else "unreconciled"
            vals = [elev[i]] if i in elev else []
        rows.append({
            "line": i, "sheet": src, "layer": lay, "role": roles.get(i) or "",
            "length_ft": round(_length(p), 2), **deg[i], "status": status,
            "lo": "" if lr is None or lr.lo is None else f"{lr.lo:g}",
            "hi": "" if lr is None or lr.hi is None else f"{lr.hi:g}",
            "values": " ".join(f"{v:g}" for v in vals),
            "assigned": added.get(i, ""), "reason": reason.get(i) or ""})
    return rows


def write_review(out_dir, findings, rows, *, crops=None,
                 title="Contour reconciliation review"):
    """``review.md``, ``findings.json`` and ``lines.csv`` in ``out_dir``."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    crops = crops or {}
    md = [f"# {title}", "",
          f"{len(findings)} finding(s). Each is a place to look at on the "
          "sheet: classify it as a plan issue, an extraction artefact, or a "
          "real wall or grade break.", ""]
    if not findings:
        md.append("No findings — every contour reconciles.")
    for f in findings:
        labs = ", ".join(f"{lab['elev']:g}"
                         + (f" ({lab['id']})" if lab.get("id") else "")
                         for lab in f.labels) or "—"
        md += [f"## {f.id} · {f.kind}", "",
               f"- lines: {', '.join(str(k) for k in f.lines) or '—'}",
               f"- labels: {labs}",
               (f"- world: x {f.xy[0]:.1f}, y {f.xy[1]:.1f} ft"
                if math.isfinite(f.xy[0]) else "- world: —")]
        if f.page is not None:
            md.append(f"- page: {f.page[0]:.1f}, {f.page[1]:.1f} pt")
        md += [f"- check: {f.check}", "", f.detail]
        md += [f"- {p}" for p in f.paths]
        if f.id in crops:
            md += ["", f"![{f.id}]({Path(crops[f.id]).name})"]
        md.append("")
    (out / "review.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (out / "findings.json").write_text(
        json.dumps({"findings": [f.as_dict() for f in findings]}, indent=2),
        encoding="utf-8")
    with open(out / "lines.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=LINE_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return {"review": out / "review.md", "findings": out / "findings.json",
            "lines": out / "lines.csv"}


# --------------------------------------------------------------- crops
def affine_of(page_to_world):
    """The coefficients ``(a, b, c, d, e, f)`` of an affine page -> world
    callable (world = ``(a·x + b·y + c, d·x + e·y + f)``), read by evaluating
    it at three points — so a manifest georef and a ``--tie`` fit both work.
    """
    c, f = page_to_world(0.0, 0.0)
    x1, y1 = page_to_world(1.0, 0.0)
    x2, y2 = page_to_world(0.0, 1.0)
    return (x1 - c, x2 - c, c, y1 - f, y2 - f, f)


def world_to_page(coef):
    """The inverse of an affine page -> world placement."""
    a, b, c, d, e, f = (float(v) for v in coef)
    det = a * e - b * d
    if abs(det) < 1e-12:
        raise ValueError("the page -> world placement is singular")
    return lambda x, y: ((e * (x - c) - b * (y - f)) / det,
                         (-d * (x - c) + a * (y - f)) / det)


_COLOURS = {"lettered": (0.0, 0.35, 1.0), "assigned": (0.0, 0.6, 0.55),
            "other": (1.0, 0.55, 0.0)}


def _overlaps(pl, box):
    return not (pl[:, 0].max() < box.x0 or pl[:, 0].min() > box.x1
                or pl[:, 1].max() < box.y0 or pl[:, 1].min() > box.y1)


def _clip_seg(p1, p2, box):
    """Liang-Barsky clip of segment p1->p2 to a box; (q1, q2) or None."""
    x1, y1 = float(p1[0]), float(p1[1])
    x2, y2 = float(p2[0]), float(p2[1])
    dx, dy = x2 - x1, y2 - y1
    p = (-dx, dx, -dy, dy)
    q = (x1 - box.x0, box.x1 - x1, y1 - box.y0, box.y1 - y1)
    u1, u2 = 0.0, 1.0
    for pi, qi in zip(p, q):
        if pi == 0.0:
            if qi < 0.0:
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
    return ((x1 + u1 * dx, y1 + u1 * dy), (x1 + u2 * dx, y1 + u2 * dy))


def _clip_polyline(pl, box):
    """In-box sub-polylines of ``pl`` (N x 2). Off-canvas geometry is dropped
    so a line mostly outside the crop is not drawn off-canvas — get_pixmap
    already clips the IMAGE, this saves the drawing work on dense sheets."""
    runs, cur = [], []
    for i in range(len(pl) - 1):
        seg = _clip_seg(pl[i], pl[i + 1], box)
        if seg is None:
            if len(cur) >= 2:
                runs.append(cur)
            cur = []
            continue
        q1, q2 = seg
        if cur and abs(cur[-1][0] - q1[0]) < 1e-9 and abs(cur[-1][1] - q1[1]) < 1e-9:
            cur.append(q2)
        else:
            if len(cur) >= 2:
                runs.append(cur)
            cur = [q1, q2]
    if len(cur) >= 2:
        runs.append(cur)
    return runs


def _crop_box(w2p, xy, crop_ft):
    """The page-space bounding box (``x0, y0, x1, y1``) of the world square
    ``crop_ft`` on a side centred at ``xy``, mapped through ``w2p`` — so a
    non-uniform or sheared placement still yields the right page-space
    extent (a scale-factor shortcut only works for a similarity).
    """
    x, y = xy
    half = crop_ft / 2.0
    corners = [w2p(x + dx, y + dy) for dx in (-half, half) for dy in (-half, half)]
    xs = [p[0] for p in corners]
    ys = [p[1] for p in corners]
    return (min(xs), min(ys), max(xs), max(ys))


def _label_point(pl, box, centre):
    """The point on page-space polyline ``pl`` nearest ``centre`` that lies
    inside ``box``, or None when no point of the path enters it.

    ``pl`` is densified to roughly ``box``-width / 50 spacing first, so a
    long line whose extent dwarfs the crop still gets a label placed inside
    the visible crop rather than at its raw (possibly off-crop) midpoint
    vertex. A line whose bounding box overlaps ``box`` but whose path stays
    outside it (e.g. an L bent around a corner) returns None.
    """
    import numpy as np
    step = max(1e-6, (box.x1 - box.x0) / 50.0)
    pts = []
    for i in range(len(pl) - 1):
        p0, p1 = pl[i], pl[i + 1]
        length = float(np.hypot(*(p1 - p0)))
        n = max(1, int(length / step))
        pts += [p0 + (p1 - p0) * (j / n) for j in range(n)]
    pts.append(pl[-1])
    pts = np.asarray(pts)
    inside = ((pts[:, 0] >= box.x0) & (pts[:, 0] <= box.x1)
              & (pts[:, 1] >= box.y0) & (pts[:, 1] <= box.y1))
    if not inside.any():
        return None
    cand = pts[inside]
    d = np.hypot(cand[:, 0] - centre[0], cand[:, 1] - centre[1])
    return tuple(cand[int(np.argmin(d))])


def render_crops(pdf_path, coef, polys, findings, out_dir, *, sheet_of, elev,
                 assigned=None, spots=(), crop_ft=80.0, dpi=300,
                 line_sheet=None):
    """One overlay crop per finding: ``{finding id: png path}``.

    The traced lines are drawn onto a fresh SCRATCH COPY of the finding's page
    (drawing mutates the page, so each finding needs a clean one) — but the
    source PDF is parsed ONCE, not reopened per finding. Lines are drawn in
    unrotated page points (the manifest frame), CLIPPED to the crop box so
    nothing is drawn off-canvas, each labelled where its path enters the crop
    (``_label_point``) with its id and value: lettered blue, assigned teal, the
    rest orange, the finding's own lines red and heavier; spots green crosses.
    The crop is the page-space image of the ``crop_ft`` world square around the
    finding (``_crop_box``; a ``conflict`` widens it per axis to cover its
    lines, up to 3x the base half-extents), rendered through
    ``page.rotation_matrix``. ``sheet_of(finding)`` gives the 1-based sheet or
    None. ``line_sheet[k]``, when given, is line ``k``'s sheet: only the
    finding's sheet's lines are drawn or widen its crop. A sheet past the PDF's
    last page is a ``ValueError``.
    """
    import fitz
    import numpy as np
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    assigned = assigned or {}
    w2p = world_to_page(coef)
    page_lines = [np.array([w2p(x, y) for x, y in np.asarray(p, float).reshape(-1, 2)])
                  .reshape(-1, 2) for p, _, _ in polys]
    made = {}
    src = fitz.open(str(pdf_path))
    try:
        for f in findings:
            sheet = sheet_of(f)
            if sheet is None or not math.isfinite(f.xy[0]):
                continue
            off = (set() if line_sheet is None else
                   {k for k, s in enumerate(line_sheet) if s != sheet})
            cx, cy = w2p(*f.xy)
            x0, y0, x1, y1 = _crop_box(w2p, f.xy, crop_ft)
            hx, hy = (x1 - x0) / 2.0, (y1 - y0) / 2.0
            own = [page_lines[k] for k in f.lines
                   if k not in off and len(page_lines[k])]
            if f.kind == "conflict" and own:
                pts = np.vstack(own)
                need_x = float(np.abs(pts[:, 0] - cx).max())
                need_y = float(np.abs(pts[:, 1] - cy).max())
                hx = min(max(hx, need_x), 3.0 * hx)
                hy = min(max(hy, need_y), 3.0 * hy)
            box = fitz.Rect(cx - hx, cy - hy, cx + hx, cy + hy)
            size = max(4.0, max(hx, hy) / 20.0)
            if not 0 <= sheet - 1 < src.page_count:
                raise ValueError(f"{Path(pdf_path).name} has {src.page_count} "
                                 f"page(s); finding {f.id} is on sheet {sheet}")
            scratch = None
            try:
                scratch = fitz.open()
                scratch.insert_pdf(src, from_page=sheet - 1, to_page=sheet - 1)
                page = scratch[0]
                mine = set(f.lines)
                for k, pl in enumerate(page_lines):
                    if k in off or len(pl) < 2 or not _overlaps(pl, box):
                        continue
                    kind = ("lettered" if k in elev else
                            "assigned" if k in assigned else "other")
                    colour, width = (((1.0, 0.0, 0.0), 1.6) if k in mine
                                     else (_COLOURS[kind], 0.8))
                    for run in _clip_polyline(pl, box):
                        page.draw_polyline([fitz.Point(*q) for q in run],
                                           color=colour, width=width)
                    m = _label_point(pl, box, (cx, cy))
                    if m is not None:
                        z = elev.get(k, assigned.get(k))
                        page.insert_text(fitz.Point(*m),
                                         f"{k}" if z is None else f"{k}={z:g}",
                                         fontsize=size, color=colour)
                for s in spots:
                    sx, sy = w2p(*s["xy"])
                    if box.contains(fitz.Point(sx, sy)):
                        r, g = max(2.0, max(hx, hy) / 40.0), (0.0, 0.6, 0.0)
                        page.draw_line(fitz.Point(sx - r, sy - r), fitz.Point(sx + r, sy + r),
                                       color=g, width=0.8)
                        page.draw_line(fitz.Point(sx - r, sy + r), fitz.Point(sx + r, sy - r),
                                       color=g, width=0.8)
                        page.insert_text(fitz.Point(sx + r, sy - r), f"{s['elev']:g}",
                                         fontsize=size, color=g)
                path = out / f"{f.id}.png"
                # get_pixmap clips in the rotated (visual) frame
                page.get_pixmap(clip=box * page.rotation_matrix, dpi=dpi).save(str(path))
                made[f.id] = path
            finally:
                if scratch is not None:
                    scratch.close()
    finally:
        src.close()
    return made

def _ellipsize(text, max_w, measure):
    """``text`` trimmed with an ellipsis until ``measure(text) <= max_w``."""
    if not text or measure(text) <= max_w:
        return text
    ell = "…"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if measure(text[:mid] + ell) <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + ell if lo else ell


def contact_sheet(tiles, out_dir, *, cols=6, tile=120.0, cap=14.0):
    """Every crop on letter-high pages: centre ringed, tile captioned.

    ``tiles`` are ``(id, caption)``; each tile is the crop PNG
    ``<out_dir>/<id>.png``, already rendered in the visual frame, so a tile
    always equals its crop — re-clipping the page here would mean a second
    clip frame on rotated sheets. Returns the PDF path, or None when there
    is nothing to show. Shared by ``label-crops`` and the contour review.
    """
    import fitz
    if not tiles:
        return None
    out_dir = Path(out_dir)
    sheet = fitz.open()
    try:
        width, height = cols * tile + 20.0, 11 * 72.0
        per_page = cols * max(1, int((height - 20.0) // (tile + cap)))
        pg = None
        for n, (cid, caption) in enumerate(tiles):
            slot = n % per_page
            if slot == 0:
                pg = sheet.new_page(width=width, height=height)
            row, col = divmod(slot, cols)
            x0, y0 = 10.0 + col * tile, 10.0 + row * (tile + cap)
            target = fitz.Rect(x0 + 2, y0 + 2, x0 + tile - 2, y0 + tile - 2)
            pg.insert_image(target, filename=str(out_dir / f"{cid}.png"))
            centre = fitz.Point((target.x0 + target.x1) / 2,
                                (target.y0 + target.y1) / 2)
            pg.draw_circle(centre, 6, color=(1, 0, 0), width=0.8)
            cap_text = _ellipsize(caption, tile - 4.0,
                                  lambda t: fitz.get_text_length(t, fontsize=7))
            pg.insert_text((x0 + 2, y0 + tile + 10), cap_text, fontsize=7)
        path = out_dir / "contact-sheet.pdf"
        sheet.save(str(path), deflate=True, garbage=3)
        for i, p in enumerate(sheet):
            p.get_pixmap(dpi=110).save(str(out_dir / f"contact-sheet-{i + 1:02d}.png"))
    finally:
        sheet.close()
    return path
