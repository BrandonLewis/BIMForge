"""Tests for bimforge.cad.titleblock — applying the bundled border to paperspace."""
from __future__ import annotations

import pytest

ezdxf = pytest.importorskip("ezdxf")

from bimforge.cad.doc import new_doc  # noqa: E402
from bimforge.cad.titleblock import (  # noqa: E402
    SHEET_SIZES,
    TITLE_BLOCK_LIBRARY,
    TitleBlockFields,
    apply_title_block,
)

FIELDS = TitleBlockFields(
    project="PRJ-002",
    sheet_title="BOX CULVERT - PLAN",
    city="ANYTOWN",
    county="EXAMPLE",
    date="2026-07-07",
    scale="AS SHOWN",
    drafter="ARR",
)


def _attrib_texts(layout):
    """All ATTRIB text values on INSERTs in ``layout``."""
    texts = []
    for e in layout:
        if e.dxftype() == "INSERT":
            texts.extend(a.dxf.text for a in e.attribs)
    return texts


def test_apply_title_block_succeeds_with_bundled_template():
    doc = new_doc()
    lay = apply_title_block(doc, "ARCH_D", FIELDS, "SHEET-01",
                            library=TITLE_BLOCK_LIBRARY)
    assert lay.name == "SHEET-01"
    assert "SHEET-01" in doc.layouts
    # The layout carries entities afterward (at minimum the border INSERT).
    entities = list(lay)
    assert len(entities) >= 1
    assert any(e.dxftype() == "INSERT" for e in entities)
    assert SHEET_SIZES["ARCH_D"].block in doc.blocks


def test_apply_title_block_default_library_is_bundled_template():
    doc = new_doc()
    lay = apply_title_block(doc, "11x17", FIELDS, "SHEET-02")
    assert any(e.dxftype() == "INSERT" for e in lay)
    assert SHEET_SIZES["11x17"].block in doc.blocks


@pytest.mark.parametrize("size", ["ARCH_D", "11x17"])
def test_title_block_fields_land_in_drawing(size):
    doc = new_doc()
    lay = apply_title_block(doc, size, FIELDS, f"SHEET_{size}")
    texts = _attrib_texts(lay)
    assert texts, "border INSERT should carry text attributes"
    for value in ("PRJ-002", "ANYTOWN", "EXAMPLE", "2026-07-07", "ARR"):
        assert value in texts, f"{value!r} not stamped into the {size} title block"


def test_apply_title_block_sets_paper_size():
    doc = new_doc()
    lay = apply_title_block(doc, "ARCH_D", FIELDS, "SHEET-PAPER")
    # ARCH D is 36x24 inches (landscape); ezdxf stores paper size in mm.
    w = lay.dxf_layout.dxf.paper_width
    h = lay.dxf_layout.dxf.paper_height
    assert sorted((w, h)) == pytest.approx([24 * 25.4, 36 * 25.4])
