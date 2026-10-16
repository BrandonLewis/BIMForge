"""GeoPDF viewports: a plan sheet's own page -> world georeference.

A GeoPDF page carries ``/VP [<< /Type /Viewport /BBox [...] /Measure <<
/Subtype /GEO /GPTS [lat lon ...] /LPTS [u v ...] /GCS << /EPSG n >> >> >>]``.
``/BBox`` is in PDF user space (y up); ``/LPTS`` are reference points as
fractions of it; ``/GPTS`` the same points as latitude/longitude in the GCS's
geographic base. ``read_viewports`` maps each LPTS point into the unrotated
y-down frame the plansheet extractor uses (via pymupdf's
``page.transformation_matrix``), projects the GPTS into the CRS with pyproj,
and least-squares fits the affine page -> world map.

Residuals cannot catch a wrong ``/BBox`` — a four-point affine fit absorbs
any linear error. A real 270°-rotated sheet declared a square viewport on a
tall page: 0.09 ft residuals, scales 35 % apart. Map sheets are isotropic, so
``anisotropy_ok`` is the gate; ``bbox_mode="page"`` retries with the page
MediaBox. v1 is foot-only (``is_foot_crs``): the pipeline works in feet.

Precision floor: MuPDF stores PDF reals as 32-bit floats, so ``/GPTS`` keep
about seven significant digits (~4e-6 degree) and a GeoPDF georeference is
good to about a foot — fine for approximate-grade terrain; use survey ties
for anything tighter.

pymupdf and pyproj are imported inside ``read_viewports`` only, so the parser
and the gates run on the base install.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

__all__ = ["Name", "parse_pdf_object", "Viewport", "read_viewports",
           "ANISOTROPY_GATE_PCT", "anisotropy_ok", "is_foot_crs"]

#: two scales further apart than this mean a wrong /BBox, not a real map sheet
ANISOTROPY_GATE_PCT = 1.0

_FOOT_UNITS = ("US survey foot", "foot")


class Name(str):
    """A PDF name object: ``/Foo`` parses to ``Name("Foo")``."""


_WS = " \t\r\n\f\0"
_NAME = re.compile(r"/([^\s/\[\]<>()%{}]*)")
_REF = re.compile(r"(\d+)\s+(\d+)\s+R(?![A-Za-z])")
_NUM = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)")


def parse_pdf_object(text: str, resolve=None):
    """Parse one PDF object (as ``xref_object``/``xref_get_key`` print it).

    Dicts -> dict (str keys), arrays -> list, names -> ``Name``, literal and
    hex strings -> str, numbers, booleans, null. An indirect reference
    ``n 0 R`` becomes ``resolve(n)`` when a resolver is given, else
    ``("ref", n)``. Raises ValueError on anything it cannot read.
    """
    pos = 0
    n = len(text)

    def ws():
        nonlocal pos
        while pos < n:
            if text[pos] in _WS:
                pos += 1
            elif text[pos] == "%":
                while pos < n and text[pos] not in "\r\n":
                    pos += 1
            else:
                break

    def value():
        nonlocal pos
        ws()
        if pos >= n:
            raise ValueError("unexpected end of PDF object")
        if text.startswith("<<", pos):
            pos += 2
            out = {}
            while True:
                ws()
                if text.startswith(">>", pos):
                    pos += 2
                    return out
                key = value()
                if not isinstance(key, Name):
                    raise ValueError(f"dictionary key is not a name: {key!r}")
                out[str(key)] = value()
        c = text[pos]
        if c == "[":
            pos += 1
            arr = []
            while True:
                ws()
                if pos < n and text[pos] == "]":
                    pos += 1
                    return arr
                arr.append(value())
        if c == "/":
            m = _NAME.match(text, pos)
            pos = m.end()
            return Name(m.group(1))
        if c == "(":
            pos += 1
            depth, buf = 0, []
            while pos < n:
                ch = text[pos]
                if ch == "\\" and pos + 1 < n:
                    buf.append(text[pos + 1])
                    pos += 2
                    continue
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    if depth == 0:
                        pos += 1
                        return "".join(buf)
                    depth -= 1
                buf.append(ch)
                pos += 1
            raise ValueError("unterminated PDF string")
        if c == "<":
            end = text.find(">", pos)
            if end < 0:
                raise ValueError("unterminated hex string")
            hexs = re.sub(r"\s", "", text[pos + 1:end])
            pos = end + 1
            return bytes.fromhex(hexs + "0" * (len(hexs) % 2)).decode("latin-1")
        m = _REF.match(text, pos)
        if m:
            pos = m.end()
            xref = int(m.group(1))
            return resolve(xref) if resolve else ("ref", xref)
        m = _NUM.match(text, pos)
        if m:
            pos = m.end()
            s = m.group(0)
            return float(s) if "." in s else int(s)
        for word, v in (("true", True), ("false", False), ("null", None)):
            if text.startswith(word, pos):
                pos += len(word)
                return v
        raise ValueError(f"unparseable PDF object near {text[pos:pos + 24]!r}")

    return value()


@dataclass
class Viewport:
    """One GEO viewport: its box and fitted page -> world affine.

    ``bbox_pt`` and ``to_world`` use unrotated page points, y down (the
    extractor's frame). ``transform`` is ``(a, b, c, d, e, f)`` with
    ``E = a*x + b*y + c``, ``N = d*x + e*y + f`` in CRS units.
    """

    index: int
    bbox_pt: tuple
    crs_epsg: int
    unit: str
    transform: tuple
    residuals_ft: list
    bbox_mode: str

    @property
    def scale_x(self) -> float:
        a, _b, _c, d, _e, _f = self.transform
        return math.hypot(a, d)

    @property
    def scale_y(self) -> float:
        _a, b, _c, _d, e, _f = self.transform
        return math.hypot(b, e)

    @property
    def anisotropy_pct(self) -> float:
        if self.scale_x == 0 or self.scale_y == 0:
            return math.inf
        return abs(self.scale_x / self.scale_y - 1.0) * 100.0

    def to_world(self, x: float, y: float) -> tuple[float, float]:
        a, b, c, d, e, f = self.transform
        return (a * x + b * y + c, d * x + e * y + f)

    def contains(self, x: float, y: float) -> bool:
        x0, y0, x1, y1 = self.bbox_pt
        return x0 <= x <= x1 and y0 <= y <= y1


def anisotropy_ok(vp) -> bool:
    """True when the viewport's two scales agree within ANISOTROPY_GATE_PCT."""
    return vp.anisotropy_pct <= ANISOTROPY_GATE_PCT


def is_foot_crs(vp) -> bool:
    """True for US-survey-foot and foot CRSs (v1 works in feet only)."""
    return vp.unit in _FOOT_UNITS


def _numbers(value, name: str, i: int) -> list[float]:
    """``value`` as a list of floats, or ``ValueError`` naming the bad key.

    Guards ``/BBox``, ``/LPTS``, ``/GPTS`` against a malformed viewport (a
    non-array value, or an array with a non-numeric entry) that would
    otherwise surface as a raw ``TypeError``/``ValueError`` from the float
    conversion below.
    """
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"GeoPDF viewport {i}: /{name} is not a numeric array")
    try:
        return [float(v) for v in value]
    except (TypeError, ValueError):
        raise ValueError(f"GeoPDF viewport {i}: /{name} is not a numeric array") from None


def _fit_affine(page_pts, world_pts):
    import numpy as np
    P = np.asarray(page_pts, dtype=float)
    W = np.asarray(world_pts, dtype=float)
    A = np.c_[P, np.ones(len(P))]
    if len(P) < 3 or np.linalg.matrix_rank(A) < 3:
        raise ValueError("GeoPDF viewport needs >= 3 non-collinear reference points")
    coef, *_ = np.linalg.lstsq(A, W, rcond=None)
    res = [float(r) for r in np.linalg.norm(A @ coef - W, axis=1)]
    a, b, c = (float(v) for v in coef[:, 0])
    d, e, f = (float(v) for v in coef[:, 1])
    return (a, b, c, d, e, f), res


def read_viewports(pdf_path, page_index: int, *,
                   bbox_mode: str = "viewport") -> list[Viewport]:
    """The page's GEO viewports (``[]`` when it has none).

    ``bbox_mode="page"`` substitutes the page MediaBox for each ``/BBox`` —
    the repair for exporters that wrote the wrong box (see the module
    docstring). Raises ValueError on a malformed viewport or a CRS without an
    EPSG code.
    """
    if bbox_mode not in ("viewport", "page"):
        raise ValueError(f"bbox_mode must be 'viewport' or 'page', not {bbox_mode!r}")
    import fitz  # pymupdf
    from pyproj import CRS, Transformer

    doc = fitz.open(pdf_path)
    try:
        if not 0 <= page_index < doc.page_count:
            raise ValueError(f"page index {page_index} out of range")
        page = doc[page_index]
        kind, val = doc.xref_get_key(page.xref, "VP")
        if kind in ("null", "undefined") or not val:
            return []

        def resolve(xref):
            return parse_pdf_object(doc.xref_object(xref, compressed=True), resolve)

        vps = parse_pdf_object(val, resolve)
        if isinstance(vps, dict):
            vps = [vps]
        if not isinstance(vps, list):
            raise ValueError("GeoPDF /VP is not an array or dictionary")
        m = page.transformation_matrix
        mb = page.mediabox
        out = []
        for i, vp in enumerate(vps):
            if not isinstance(vp, dict):
                continue
            meas = vp.get("Measure") or {}
            if str(meas.get("Subtype", "")) != "GEO" or "GPTS" not in meas:
                continue
            gcs = meas.get("GCS") or {}
            if "EPSG" in gcs:
                crs = CRS.from_epsg(int(gcs["EPSG"]))
            elif "WKT" in gcs:
                crs = CRS.from_wkt(str(gcs["WKT"]))
            else:
                raise ValueError(f"GeoPDF viewport {i} has no /GCS EPSG or WKT")
            epsg = crs.to_epsg()
            if epsg is None:
                raise ValueError(f"GeoPDF viewport {i}: CRS has no EPSG code")
            if bbox_mode == "page":
                # page.mediabox is already PDF user space (raw MediaBox) —
                # use it directly, do not run it through the page transform.
                bbox = [mb.x0, mb.y0, mb.x1, mb.y1]
            else:
                bbox = _numbers(vp.get("BBox", []), "BBox", i)
            if len(bbox) != 4:
                raise ValueError(f"GeoPDF viewport {i} has no usable /BBox")
            gp = _numbers(meas["GPTS"], "GPTS", i)
            lp = _numbers(meas.get("LPTS", [0, 0, 0, 1, 1, 1, 1, 0]), "LPTS", i)
            to_crs = Transformer.from_crs(crs.geodetic_crs, crs, always_xy=True)
            page_pts, world_pts = [], []
            for k in range(0, min(len(gp), len(lp)) - 1, 2):
                ux = bbox[0] + lp[k] * (bbox[2] - bbox[0])
                uy = bbox[1] + lp[k + 1] * (bbox[3] - bbox[1])
                p = fitz.Point(ux, uy) * m
                page_pts.append((p.x, p.y))
                world_pts.append(to_crs.transform(gp[k + 1], gp[k]))  # lon, lat
            transform, res = _fit_affine(page_pts, world_pts)
            r = fitz.Rect(*bbox) * m
            out.append(Viewport(i, (r.x0, r.y0, r.x1, r.y1), epsg,
                                crs.axis_info[0].unit_name, transform, res,
                                bbox_mode))
        return out
    finally:
        doc.close()
