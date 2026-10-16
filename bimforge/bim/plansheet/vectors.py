"""Harvest a PDF plan sheet's vector paths and text spans (pymupdf).

Agency plan sets are plotted from CAD — the PDF's vector paths ARE the
geometry. ``extract_sheet`` normalizes ``page.get_drawings()`` into flat
2-point ``Segment``s carrying their style (dash pattern, width, color), plus
every text span with its position (dimension strings live there).

Coordinate frame: **unrotated page points** — raw PDF content coordinates
(y down), the frame ``get_drawings()`` and ``get_text("dict")`` both report
in regardless of the page's /Rotate. A /Rotate 90 sheet's linework therefore
comes out sideways; ``rotate_to_visual`` maps unrotated points into the
as-rendered (visual) frame, and the calibration zone transform applies it so
world coordinates match the sheet a human sees. Verified empirically: text
and drawing coordinates stay identical under ``page.set_rotation`` (the
Sheet-4 control-script behaviour).

Hatches explode into thousands of micro-paths; ``min_path_pt`` drops whole
drawing paths whose total polyline length is below the threshold before they
reach classification or snapping.

Requires pymupdf (the ``bim`` extra).
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

import fitz  # pymupdf

__all__ = [
    "Segment", "TextSpan", "SheetVectors",
    "extract_sheet", "rotate_to_visual", "visual_to_unrotated",
    "style_layer", "normalize_dashes", "load_classes", "class_name",
]

#: dash strings pymupdf reports for an undashed (solid) stroke
_SOLID_DASHES = ("", "[] 0", "[ ] 0", None)

_BEZIER_STEPS = 12


@dataclass(frozen=True)
class Segment:
    """One straight stroke in unrotated page points, with its style."""

    x1: float
    y1: float
    x2: float
    y2: float
    dashes: str = ""                       # "" = solid, else the fitz dash string
    width: float = 0.0
    color: tuple[float, float, float] | None = None
    curved: bool = False                   # chord of a flattened bezier curve
    #: PDF optional-content group (OCG) name — the plotting CAD layer, e.g.
    #: "1116.099 Grading|C-TOPO-MINR-N" — from get_drawings()'s grp["layer"];
    #: None when the path is on no OCG (issue #200).
    layer: str | None = None

    @property
    def length(self) -> float:
        return math.hypot(self.x2 - self.x1, self.y2 - self.y1)

    @property
    def direction(self) -> tuple[float, float]:
        """Unit direction vector; (0, 0) for a degenerate segment."""
        n = self.length
        if n <= 0.0:
            return (0.0, 0.0)
        return ((self.x2 - self.x1) / n, (self.y2 - self.y1) / n)

    def in_bbox(self, bbox: tuple[float, float, float, float]) -> bool:
        """Both endpoints inside bbox (x0, y0, x1, y1), unrotated points."""
        x0, y0, x1, y1 = bbox
        return (x0 <= self.x1 <= x1 and y0 <= self.y1 <= y1
                and x0 <= self.x2 <= x1 and y0 <= self.y2 <= y1)


@dataclass(frozen=True)
class TextSpan:
    """One text span: content plus its center in unrotated page points."""

    text: str
    x: float
    y: float
    bbox: tuple[float, float, float, float]
    dir: tuple[float, float] = (1.0, 0.0)  # writing direction (unrotated frame)

    def in_bbox(self, bbox: tuple[float, float, float, float]) -> bool:
        x0, y0, x1, y1 = bbox
        return x0 <= self.x <= x1 and y0 <= self.y <= y1


@dataclass
class SheetVectors:
    """Everything harvested from one page."""

    page_index: int                        # 0-based
    rotation: int                          # /Rotate: 0 | 90 | 180 | 270
    width: float                           # unrotated page width, points
    height: float                          # unrotated page height, points
    segments: list[Segment] = field(default_factory=list)
    texts: list[TextSpan] = field(default_factory=list)


def rotate_to_visual(x: float, y: float, rotation: int,
                     width: float, height: float) -> tuple[float, float]:
    """Map an unrotated page point into the as-rendered (visual) frame.

    ``width``/``height`` are the *unrotated* page dimensions. The visual frame
    is what ``page.rect`` describes and what a rendered PNG shows (y down).
    Matches fitz's ``page.rotation_matrix`` for axis-aligned rotations.
    """
    r = rotation % 360
    if r == 0:
        return (x, y)
    if r == 90:
        return (height - y, x)
    if r == 180:
        return (width - x, height - y)
    if r == 270:
        return (y, width - x)
    raise ValueError(f"unsupported /Rotate value {rotation} (must be a multiple of 90)")


def visual_to_unrotated(vx: float, vy: float, rotation: int,
                        width: float, height: float) -> tuple[float, float]:
    """Inverse of ``rotate_to_visual``: as-rendered point -> unrotated point.

    ``width``/``height`` are the *unrotated* page dimensions. This is the
    conversion for agent-supplied locations read off a rendered PNG
    (pixel * pt-per-pixel gives visual page points).
    """
    r = rotation % 360
    if r == 0:
        return (vx, vy)
    if r == 90:
        return (vy, height - vx)
    if r == 180:
        return (width - vx, height - vy)
    if r == 270:
        return (width - vy, vx)
    raise ValueError(f"unsupported /Rotate value {rotation} (must be a multiple of 90)")


def _norm_dashes(dashes) -> str:
    return "" if dashes in _SOLID_DASHES else str(dashes)


def normalize_dashes(dashes) -> str:
    """Normalize a dash pattern into a canonical signature string.

    Accepts the fitz dash string (``"[ 7.92 3 1.98 3 ] 0"``), a bare
    number list (``[7.92, 3, 1.98, 3]``), or ``""``/``None``/solid forms.
    Returns ``""`` for solid, else the on/off lengths joined by commas with
    trailing zeros trimmed (``"7.92,3,1.98,3"``). The dash *phase* is
    ignored — two strokes with the same pattern but different phase are the
    same feature class.
    """
    if dashes in _SOLID_DASHES:
        return ""
    if isinstance(dashes, (list, tuple)):
        nums = [float(v) for v in dashes]
    else:
        s = str(dashes)
        body = s[s.find("[") + 1:s.find("]")] if "[" in s and "]" in s else s
        nums = [float(tok) for tok in body.replace(",", " ").split()]
    if not nums or all(v == 0 for v in nums):
        return ""
    return ",".join(f"{v:g}" for v in nums)


def load_classes(path) -> dict[str, str]:
    """Load a dash-pattern feature-class map (classes.yaml).

    Schema — ``classes: {<CLASS-NAME>: <dash pattern>}`` where the pattern is
    a fitz dash string, a number list, or ``solid``/``""`` for undashed
    strokes (see ``plansheet/classes.example.yaml``). Returns a mapping of
    normalized dash signature -> class name. Class names are upper-cased;
    they become ``V-<class>`` layers in ``est-bim vectors`` output. This is
    agency-profile material: patterns come from the plan set's legend.
    """
    import yaml

    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    classes = data.get("classes")
    if not isinstance(classes, dict) or not classes:
        raise ValueError(f"{path}: expected a top-level 'classes:' mapping")
    out: dict[str, str] = {}
    for name, pattern in classes.items():
        if pattern in ("solid", "SOLID"):
            pattern = ""
        sig = normalize_dashes(pattern)
        if sig in out:
            raise ValueError(
                f"{path}: classes {out[sig]!r} and {name!r} share the same "
                f"dash signature {sig!r}")
        out[sig] = str(name).upper()
    return out


def class_name(seg: Segment, classes: dict[str, str] | None = None) -> str:
    """Feature-class token for a segment: mapped class, SOLID, or DASH-<hash>."""
    sig = normalize_dashes(seg.dashes)
    if classes and sig in classes:
        return classes[sig]
    if not sig:
        return "SOLID"
    h = hashlib.sha1(sig.encode("utf-8")).hexdigest()[:6].upper()
    return f"DASH-{h}"


def style_layer(seg: Segment, classes: dict[str, str] | None = None) -> str:
    """DXF layer name for a segment's style class.

    ``V-<class>`` when a classes map (``load_classes``) recognizes the dash
    signature, ``V-SOLID`` for undashed strokes, ``V-DASH-<hash>`` otherwise.
    """
    return f"V-{class_name(seg, classes)}"


def _flatten_bezier(p0, p1, p2, p3, n: int = _BEZIER_STEPS) -> list[tuple[float, float]]:
    """Cubic bezier -> n chord points (excluding p0)."""
    out = []
    for i in range(1, n + 1):
        t = i / n
        u = 1.0 - t
        out.append((
            u ** 3 * p0.x + 3 * u * u * t * p1.x + 3 * u * t * t * p2.x + t ** 3 * p3.x,
            u ** 3 * p0.y + 3 * u * u * t * p1.y + 3 * u * t * t * p2.y + t ** 3 * p3.y,
        ))
    return out


def _item_points(item) -> list[tuple[float, float]]:
    """Flatten one get_drawings() item into a polyline point chain."""
    kind = item[0]
    if kind == "l":
        return [(item[1].x, item[1].y), (item[2].x, item[2].y)]
    if kind == "c":
        return [(item[1].x, item[1].y)] + _flatten_bezier(item[1], item[2], item[3], item[4])
    if kind == "re":
        r = item[1]
        return [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1), (r.x0, r.y0)]
    if kind == "qu":
        q = item[1]
        return [(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.lr.x, q.lr.y),
                (q.ll.x, q.ll.y), (q.ul.x, q.ul.y)]
    return []


def extract_sheet(pdf_path, page_index: int, *, min_path_pt: float = 2.0) -> SheetVectors:
    """Extract one page's vector segments and text spans.

    ``page_index`` is 0-based. ``min_path_pt`` drops any drawing path whose
    total flattened length is shorter (hatch/pattern noise filter); pass 0.0
    to keep everything.
    """
    doc = fitz.open(pdf_path)
    try:
        if not 0 <= page_index < doc.page_count:
            raise ValueError(f"page index {page_index} out of range (document has "
                             f"{doc.page_count} pages)")
        page = doc[page_index]
        rotation = int(page.rotation) % 360
        # page.rect reflects rotation; recover the unrotated (content) dims.
        if rotation in (90, 270):
            width, height = page.rect.height, page.rect.width
        else:
            width, height = page.rect.width, page.rect.height

        sv = SheetVectors(page_index=page_index, rotation=rotation,
                          width=float(width), height=float(height))

        for grp in page.get_drawings():
            dashes = _norm_dashes(grp.get("dashes"))
            stroke_w = float(grp.get("width") or 0.0)
            color = grp.get("color")
            color = tuple(color) if color else None
            # OCG (CAD layer) name, when the plotted set kept its layers as
            # optional-content groups; "" for an untagged path -> None (#200).
            layer = grp.get("layer") or None
            for item in grp["items"]:
                pts = _item_points(item)
                if len(pts) < 2:
                    continue
                total = sum(math.hypot(b[0] - a[0], b[1] - a[1])
                            for a, b in zip(pts, pts[1:]))
                if total < min_path_pt:
                    continue        # micro-path (hatch noise)
                curved = item[0] == "c"
                for a, b in zip(pts, pts[1:]):
                    if a == b:
                        continue
                    sv.segments.append(Segment(a[0], a[1], b[0], b[1],
                                               dashes=dashes, width=stroke_w,
                                               color=color, curved=curved,
                                               layer=layer))

        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                ldir = tuple(line.get("dir", (1.0, 0.0)))
                for span in line.get("spans", []):
                    text = span.get("text", "")
                    if not text.strip():
                        continue
                    bx0, by0, bx1, by1 = span["bbox"]
                    sv.texts.append(TextSpan(
                        text=text,
                        x=(bx0 + bx1) / 2.0,
                        y=(by0 + by1) / 2.0,
                        bbox=(bx0, by0, bx1, by1),
                        dir=(float(ldir[0]), float(ldir[1])),
                    ))
        return sv
    finally:
        doc.close()
