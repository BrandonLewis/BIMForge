"""Sheet triage: is a plan page vector linework or a scan, and is it GeoPDF?

A plotted CAD sheet is vector paths; a scanned one is images — often dozens
of thin strips, so coverage is the UNION of every placed image's box over the
page, not the largest image. Plan-size pages only (long side >= 1000 pt,
11x17 and up): a letter-size report page full of a photo is not a raster
plan sheet. pymupdf is imported inside functions only (``image_coverage``,
``sheet_triage``), never at module level.
"""
from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["RASTER_COVERAGE", "PLAN_LONG_SIDE_PT", "SheetTriage",
           "image_coverage", "classify", "sheet_triage"]

#: placed images covering at least this share of a plan-size page -> raster
RASTER_COVERAGE = 0.6
#: long side at or above this many points makes a page plan-size (11x17 up)
PLAN_LONG_SIDE_PT = 1000.0


@dataclass
class SheetTriage:
    kind: str                       # "vector" | "raster"
    image_coverage: float           # union of placed-image area / page area
    long_side_pt: float
    viewports: list = field(default_factory=list)   # geopdf.Viewport
    viewport_error: str = ""


def image_coverage(page, cell_pt: float = 4.0) -> float:
    """Share of ``page`` covered by placed images (union, 0..1).

    Rasterizes image boxes onto a ``cell_pt`` grid so overlapping or
    duplicated strips count once. ``page.rect`` is the rotated (visual)
    rect but ``get_image_info()`` bboxes are unrotated, so each bbox is
    mapped through ``page.rotation_matrix`` into the visual frame first —
    otherwise a 90/270-rotated page's coverage is capped at short/long.
    """
    import fitz  # pymupdf
    import numpy as np

    r = page.rect
    nx = max(1, int(r.width // cell_pt))
    ny = max(1, int(r.height // cell_pt))
    mask = np.zeros((ny, nx), dtype=bool)
    for info in page.get_image_info():
        b = fitz.Rect(info["bbox"]) * page.rotation_matrix
        x0, y0, x1, y1 = b.x0, b.y0, b.x1, b.y1
        c0 = max(0, int((x0 - r.x0) // cell_pt))
        c1 = min(nx, int(np.ceil((x1 - r.x0) / cell_pt)))
        r0 = max(0, int((y0 - r.y0) // cell_pt))
        r1 = min(ny, int(np.ceil((y1 - r.y0) / cell_pt)))
        if c1 > c0 and r1 > r0:
            mask[r0:r1, c0:c1] = True
    return float(mask.mean())


def classify(coverage: float, long_side_pt: float) -> str:
    """``raster`` for a plan-size page mostly covered by images, else ``vector``."""
    if long_side_pt >= PLAN_LONG_SIDE_PT and coverage >= RASTER_COVERAGE:
        return "raster"
    return "vector"


def sheet_triage(pdf_path, page_index: int) -> SheetTriage:
    """Classify one page and list its GeoPDF viewports (0-based index)."""
    import fitz  # pymupdf

    from .geopdf import read_viewports

    doc = fitz.open(pdf_path)
    try:
        if not 0 <= page_index < doc.page_count:
            raise ValueError(f"page index {page_index} out of range "
                             f"(document has {doc.page_count} pages)")
        page = doc[page_index]
        coverage = image_coverage(page)
        long_side = float(max(page.rect.width, page.rect.height))
    finally:
        doc.close()
    viewports, err = [], ""
    try:
        viewports = read_viewports(pdf_path, page_index)
    except (ValueError, KeyError, RuntimeError) as exc:
        err = str(exc)
    return SheetTriage(classify(coverage, long_side), coverage, long_side,
                       viewports, err)
