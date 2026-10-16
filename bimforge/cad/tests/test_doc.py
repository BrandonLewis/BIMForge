"""Tests for bimforge.cad.doc / layers / viewport / titleblock (ezdxf-backed)."""
from __future__ import annotations

import os

import pytest

ezdxf = pytest.importorskip("ezdxf")

from ezdxf import units  # noqa: E402

from bimforge.cad.doc import new_doc  # noqa: E402
from bimforge.cad.layers import DEFAULT_LAYERS, LayerDef, add_layers  # noqa: E402
from bimforge.cad.titleblock import SHEET_SIZES, TitleBlockFields, apply_title_block  # noqa: E402
from bimforge.cad.viewport import add_fitted_viewport, bbox  # noqa: E402


# --- doc.new_doc -----------------------------------------------------------
def test_new_doc_header_setup():
    doc = new_doc(ltscale=40.0, text_size=3.5)
    assert doc.header["$INSUNITS"] == units.FT
    assert doc.header["$LTSCALE"] == 40.0
    assert doc.header["$MEASUREMENT"] == 0
    assert doc.header["$TEXTSIZE"] == 3.5


def test_new_doc_standard_style_font():
    doc = new_doc()
    assert doc.styles.get("STANDARD").dxf.font == "romans.shx"


def test_new_doc_creates_dimstyle_and_layers():
    doc = new_doc()
    assert "CIVIL" in doc.dimstyles
    names = {layer.dxf.name for layer in doc.layers}
    assert "S-CONC-OTLN" in names
    assert "C-ROAD-CNTR" in names


def test_new_doc_can_skip_layers_and_dimstyle():
    doc = new_doc(layers=None, add_dimstyle=False)
    assert "CIVIL" not in doc.dimstyles
    names = {layer.dxf.name for layer in doc.layers}
    assert "S-CONC-OTLN" not in names


def test_new_doc_modelspace_usable():
    doc = new_doc()
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (10, 0), (10, 10)], dxfattribs={"layer": "S-CONC-OTLN"})
    assert len(list(msp)) == 1


# --- layers ----------------------------------------------------------------
def test_default_layers_have_unique_names():
    names = [ld.name for ld in DEFAULT_LAYERS]
    assert len(names) == len(set(names))


def test_add_layers_is_idempotent():
    doc = ezdxf.new("R2018", setup=True)
    add_layers(doc, DEFAULT_LAYERS)
    before = len(list(doc.layers))
    add_layers(doc, DEFAULT_LAYERS)  # second call adds nothing
    assert len(list(doc.layers)) == before


def test_add_layers_applies_color_and_linetype():
    doc = ezdxf.new("R2018", setup=True)
    add_layers(doc, (LayerDef("T-DASH", 5, "DASHED", 25),))
    layer = doc.layers.get("T-DASH")
    assert layer.dxf.color == 5
    assert layer.dxf.linetype == "DASHED"
    assert layer.dxf.lineweight == 25


# --- viewport --------------------------------------------------------------
def test_bbox():
    assert bbox([(0, 0), (10, 20), (5, -5)]) == (0, -5, 10, 20)


def test_bbox_with_margin():
    assert bbox([(0, 0), (10, 10)], margin=2) == (-2, -2, 12, 12)


def test_bbox_empty_raises():
    with pytest.raises(ValueError):
        bbox([])


def test_add_fitted_viewport_centers_and_fits():
    doc = new_doc()
    lay = doc.layouts.new("SHEET")
    vp = add_fitted_viewport(lay, (6462000.0, 2157000.0, 6462100.0, 2157200.0))
    assert vp.dxf.view_center_point[0] == pytest.approx(6462050.0)
    assert vp.dxf.view_center_point[1] == pytest.approx(2157100.0)
    # world height (200) * margin(1.05) dominates the width term here
    assert vp.dxf.view_height == pytest.approx(210.0)


def test_add_fitted_viewport_explicit_scale():
    doc = new_doc()
    lay = doc.layouts.new("SHEET")
    # 1" = 30' -> scale 1/30, window height 19" -> view_height 570'
    vp = add_fitted_viewport(lay, (0.0, 0.0, 100.0, 100.0), scale=1 / 30,
                             size=(27.0, 19.0))
    assert vp.dxf.view_height == pytest.approx(570.0)


def test_add_fitted_viewport_rejects_bad_scale():
    doc = new_doc()
    lay = doc.layouts.new("SHEET")
    with pytest.raises(ValueError):
        add_fitted_viewport(lay, (0.0, 0.0, 1.0, 1.0), scale=0.0)


# --- titleblock ------------------------------------------------------------
def test_title_block_fields_as_attribs_uppercases():
    flds = TitleBlockFields(project="PRJ-001", sheet_title="LAYOUT")
    attrs = flds.as_attribs()
    assert attrs["PROJECT"] == "PRJ-001"
    assert attrs["SHEET_TITLE"] == "LAYOUT"
    assert attrs["COUNTY"] == ""


def test_sheet_sizes_registered():
    assert set(SHEET_SIZES) == {"11x17", "ARCH_D"}
    assert SHEET_SIZES["ARCH_D"].paper_in == (36, 24)


def test_apply_title_block_rejects_unknown_size():
    doc = new_doc()
    with pytest.raises(ValueError):
        apply_title_block(doc, "A4", TitleBlockFields(), "SHEET")


def test_title_block_library_is_bundled():
    from bimforge.cad.titleblock import TITLE_BLOCK_LIBRARY
    assert os.path.exists(TITLE_BLOCK_LIBRARY), "generic-title-blocks.dxf must ship with the package"


@pytest.mark.parametrize("size, block", [
    ("ARCH_D", "border_ARCH D TITLE"),
    ("11x17", "border_11X17 TITLE"),
])
def test_apply_title_block_stamps_border(size, block):
    doc = new_doc()
    flds = TitleBlockFields(project="PRJ-002", sheet_title="PLAN", drafter="ARR")
    lay = apply_title_block(doc, size, flds, f"SHEET_{size}")
    assert block in doc.blocks
    inserts = [e for e in lay if e.dxftype() == "INSERT"]
    assert len(inserts) == 1
    assert inserts[0].dxf.name == block
