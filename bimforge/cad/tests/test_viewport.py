"""Tests for bimforge.cad.viewport — bbox() and add_fitted_viewport()."""
from __future__ import annotations

import pytest

ezdxf = pytest.importorskip("ezdxf")

from bimforge.cad.doc import new_doc  # noqa: E402
from bimforge.cad.viewport import ARCH_D_WINDOW, add_fitted_viewport, bbox  # noqa: E402


# --- bbox --------------------------------------------------------------------
def test_bbox_known_geometry():
    pts = [(6462000.0, 2157000.0), (6462160.0, 2157000.0),
           (6462160.0, 2157012.0), (6462000.0, 2157012.0)]
    assert bbox(pts) == (6462000.0, 2157000.0, 6462160.0, 2157012.0)


def test_bbox_margin_expands_every_side():
    assert bbox([(0.0, 0.0), (10.0, 20.0)], margin=5.0) == (-5.0, -5.0, 15.0, 25.0)


def test_bbox_single_point():
    assert bbox([(3.0, 4.0)]) == (3.0, 4.0, 3.0, 4.0)


def test_bbox_empty_raises():
    with pytest.raises(ValueError):
        bbox([])


# --- add_fitted_viewport -----------------------------------------------------
def _doc_with_geometry():
    doc = new_doc()
    msp = doc.modelspace()
    footprint = [(5000.0, 5000.0), (5160.0, 5000.0),
                 (5160.0, 5012.0), (5000.0, 5012.0)]
    msp.add_lwpolyline(footprint, close=True,
                       dxfattribs={"layer": "S-CONC-OTLN"})
    return doc, footprint


def test_add_fitted_viewport_creates_viewport_in_paperspace():
    doc, footprint = _doc_with_geometry()
    lay = doc.layouts.new("SHEET")
    vp = add_fitted_viewport(lay, bbox(footprint, margin=10.0))
    assert vp.dxftype() == "VIEWPORT"
    assert vp in list(lay)
    assert vp.dxf.layer == "S-ANNO-SYMB"


def test_add_fitted_viewport_frames_modelspace_content():
    doc, footprint = _doc_with_geometry()
    lay = doc.layouts.new("SHEET")
    ext = bbox(footprint)  # (5000, 5000, 5160, 5012)
    vp = add_fitted_viewport(lay, ext)
    # Centred on the geometry...
    assert vp.dxf.view_center_point[0] == pytest.approx(5080.0)
    assert vp.dxf.view_center_point[1] == pytest.approx(5006.0)
    # ...and tall/wide enough to show all of it (with positive height).
    view_h = vp.dxf.view_height
    assert view_h > 0
    paper_w, paper_h = ARCH_D_WINDOW["size"]
    view_w = view_h * (paper_w / paper_h)
    assert view_h >= (ext[3] - ext[1])   # world height fits
    assert view_w >= (ext[2] - ext[0])   # world width fits
    # Paper window matches the ARCH D default.
    assert (vp.dxf.center[0], vp.dxf.center[1]) == ARCH_D_WINDOW["center"]
    assert (vp.dxf.width, vp.dxf.height) == ARCH_D_WINDOW["size"]


def test_add_fitted_viewport_fixed_scale():
    doc, footprint = _doc_with_geometry()
    lay = doc.layouts.new("SHEET")
    # 1" = 30' with the 27x19 window -> view_height = 19 * 30 = 570 ft.
    vp = add_fitted_viewport(lay, bbox(footprint), scale=1 / 30)
    assert vp.dxf.view_height == pytest.approx(570.0)


def test_add_fitted_viewport_rejects_nonpositive_scale():
    doc, _ = _doc_with_geometry()
    lay = doc.layouts.new("SHEET")
    for bad in (0.0, -1.0):
        with pytest.raises(ValueError):
            add_fitted_viewport(lay, (0.0, 0.0, 1.0, 1.0), scale=bad)
