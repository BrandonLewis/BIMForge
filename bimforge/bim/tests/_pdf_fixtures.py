"""Synthetic PDF fixtures for the plan-sheet tests (authored in-test with fitz).

Import only from tests that already did ``pytest.importorskip("fitz")``.
"""
from __future__ import annotations

import fitz  # pymupdf


def write_ocg_sheet(path) -> str:
    """A sheet with two OCG-tagged grey polylines and one untagged black line.

    ``Topo|CONT_MNR`` at y=100 and ``Grading|C-TOPO-MAJR-N`` at y=200 are
    3-point polylines (2 segments each); the untagged line is 1 segment.
    """
    doc = fitz.open()
    page = doc.new_page(width=1224, height=792)
    minor = doc.add_ocg("Topo|CONT_MNR", on=True)
    major = doc.add_ocg("Grading|C-TOPO-MAJR-N", on=True)
    for oc, y in ((minor, 100.0), (major, 200.0)):
        points = [(100.0, y), (300.0, y + 20.0), (500.0, y)]
        for i in range(len(points) - 1):
            page.draw_line(points[i], points[i + 1], color=(0.75, 0.75, 0.75),
                           width=0.72, oc=oc)
    page.draw_line((100.0, 400.0), (500.0, 400.0), color=(0.0, 0.0, 0.0),
                   width=0.5)
    doc.save(str(path))
    return str(path)


def write_geopdf(path, *, page=(1224.0, 792.0), rotate=0,
                 bbox=(100.0, 100.0, 1100.0, 700.0), true_bbox=None,
                 mediabox=None,
                 lpts=(0.1, 0.1, 0.9, 0.1, 0.9, 0.9, 0.1, 0.9),
                 ft_per_pt=5.0, origin=(6_700_000.0, 1_950_000.0),
                 epsg=2226, indirect=False, subtype="GEO") -> str:
    """A one-page GeoPDF whose world coordinates are known exactly.

    World (CRS units) = ``origin + ft_per_pt * (x, y)`` for a PDF user-space
    point (x, y). ``bbox`` is what the /VP declares; ``true_bbox`` (default
    ``bbox``) is the region the reference points really describe — pass a
    different one to reproduce an exporter that wrote the wrong /BBox.
    ``mediabox`` (default: the page rect, i.e. ``[0, 0, *page]`` —
    unchanged behaviour) sets the page's raw ``/MediaBox``, to reproduce an
    exporter whose MediaBox origin is not ``(0, 0)``.
    """
    from pyproj import CRS, Transformer

    tb = true_bbox or bbox
    crs = CRS.from_epsg(epsg)
    inv = Transformer.from_crs(crs, crs.geodetic_crs, always_xy=True)
    gpts = []
    for k in range(0, len(lpts), 2):
        ux = tb[0] + lpts[k] * (tb[2] - tb[0])
        uy = tb[1] + lpts[k + 1] * (tb[3] - tb[1])
        lon, lat = inv.transform(origin[0] + ft_per_pt * ux,
                                 origin[1] + ft_per_pt * uy)
        gpts += [lat, lon]

    def fmt(xs):
        return " ".join(f"{v:.10f}" for v in xs)

    vp = (f"<</Type/Viewport/BBox[{fmt(bbox)}]/Measure<</Type/Measure"
          f"/Subtype/{subtype}/LPTS[{fmt(lpts)}]/GPTS[{fmt(gpts)}]"
          f"/GCS<</Type/PROJCS/EPSG {epsg}>>>>>>")
    doc = fitz.open()
    pg = doc.new_page(width=page[0], height=page[1])
    if mediabox is not None:
        pg.set_mediabox(fitz.Rect(*mediabox))
    if indirect:
        xref = doc.get_new_xref()
        doc.update_object(xref, vp)
        doc.xref_set_key(pg.xref, "VP", f"[{xref} 0 R]")
    else:
        doc.xref_set_key(pg.xref, "VP", f"[{vp}]")
    if rotate:
        pg.set_rotation(rotate)
    doc.save(str(path))
    return str(path)


def write_raw_vp(path, vp_text, *, page=(1224.0, 792.0)) -> str:
    """A one-page PDF whose ``/VP`` key is set to ``vp_text`` verbatim.

    For malformed-``/VP`` tests: pass a bare scalar (``"5"``) or a full
    array literal (``"[<<...>>]"``) that ``read_viewports`` should reject.
    """
    doc = fitz.open()
    pg = doc.new_page(width=page[0], height=page[1])
    doc.xref_set_key(pg.xref, "VP", vp_text)
    doc.save(str(path))
    return str(path)


def write_label_sheet(path, *, rotate=0) -> str:
    """Three contours on an OCG; two white label masks over them (each with a
    glyph), one mask over nothing, and a spot marker. Unrotated coordinates:
    contours y = 200/300/400 from x = 100 to 1100; masks centred (490, 300),
    (710, 200) and (300, 500); spot marker at (900, 600)."""
    doc = fitz.open()
    page = doc.new_page(width=1224, height=792)
    cont = doc.add_ocg("Topo|CONT_MJR", on=True)
    ann = doc.add_ocg("S-BRDG-ANNO", on=True)
    spot = doc.add_ocg("Topo|E_SPOT", on=True)
    for y in (200.0, 300.0, 400.0):
        sh = page.new_shape()
        sh.draw_line((100.0, y), (1100.0, y))
        sh.finish(color=(0.5, 0.5, 0.5), width=0.72, closePath=False, oc=cont)
        sh.commit()
    for x, y in ((490.0, 300.0), (710.0, 200.0), (300.0, 500.0)):
        sh = page.new_shape()
        sh.draw_rect(fitz.Rect(x - 10, y - 8, x + 10, y + 8))
        sh.finish(fill=(1, 1, 1), color=None, oc=ann)
        sh.commit()
        sh = page.new_shape()
        sh.draw_line((x - 6, y - 4), (x - 6, y + 4))
        sh.draw_line((x - 6, y - 4), (x + 2, y - 4))
        sh.finish(color=(0, 0, 0), width=0.6, closePath=False, oc=ann)
        sh.commit()
    sh = page.new_shape()
    sh.draw_line((896.0, 596.0), (904.0, 604.0))
    sh.draw_line((896.0, 604.0), (904.0, 596.0))
    sh.finish(color=(0, 0, 0), width=0.5, closePath=False, oc=spot)
    sh.commit()
    if rotate:
        page.set_rotation(rotate)
    doc.save(str(path))
    return str(path)


def write_image_page(path, rects, *, page=(1224.0, 792.0), rotate=0) -> str:
    """One page with a grey image stretched into each rect (x0, y0, x1, y1).

    ``rects`` are in the page's own (unrotated) MediaBox space, matching what
    ``page.get_image_info()`` reports; ``rotate`` sets ``/Rotate`` so the
    visual ``page.rect`` differs from the MediaBox on 90/270.
    """
    doc = fitz.open()
    pg = doc.new_page(width=page[0], height=page[1])
    pix = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 40, 4), False)
    pix.clear_with(200)
    for r in rects:
        pg.insert_image(fitz.Rect(*r), pixmap=pix, keep_proportion=False)
    if rotate:
        pg.set_rotation(rotate)
    doc.save(str(path))
    return str(path)
