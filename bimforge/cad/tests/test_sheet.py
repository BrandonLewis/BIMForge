"""compose_sheet: title block + fitted viewport in one call."""
import pytest

ezdxf = pytest.importorskip("ezdxf")

from bimforge.cad.doc import new_doc
from bimforge.cad.sheet import compose_sheet
from bimforge.cad.titleblock import TitleBlockFields


def test_compose_sheet_creates_layout_with_viewport():
    doc = new_doc()
    doc.modelspace().add_lwpolyline([(0, 0), (100, 0), (100, 50)], close=True,
                                    dxfattribs={"layer": "S-CONC-OTLN"})
    lay = compose_sheet(doc, size="ARCH_D",
                        fields=TitleBlockFields(sheet_title="PLAN"),
                        layout_name="PLAN 1",
                        extents=(0, 0, 100, 50), scale=1 / 30)
    assert lay.name == "PLAN 1"
    # `page_setup` (called by `apply_title_block`) creates its own "main"
    # background VIEWPORT (dxf.id == 1, ezdxf's `Layout.main_viewport()`);
    # exclude it to isolate the one `compose_sheet` adds via
    # `add_fitted_viewport`.
    main = lay.main_viewport()
    vports = [e for e in lay if e.dxftype() == "VIEWPORT" and e is not main]
    assert len(vports) == 1
    assert vports[0].dxf.view_height == pytest.approx(19.0 * 30)


def test_compose_sheet_autofit_when_no_scale():
    doc = new_doc()
    lay = compose_sheet(doc, size="11x17", fields=TitleBlockFields(),
                        layout_name="S1", extents=(0, 0, 10, 10))
    main = lay.main_viewport()
    vports = [e for e in lay if e.dxftype() == "VIEWPORT" and e is not main]
    assert len(vports) == 1
    vp = vports[0]
    cx, cy, _ = vp.dxf.view_center_point
    assert (cx, cy) == pytest.approx((5.0, 5.0))
    # 10x10 extents padded 5%, width-constrained by the 11x17 window's
    # 9.5x13.0 aspect ratio: (10 * 1.05) * (13.0 / 9.5)
    assert vp.dxf.view_height == pytest.approx(10 * 1.05 * 13.0 / 9.5)


def test_partial_window_override_merges_size_default(tmp_path):
    doc = new_doc()
    lay = compose_sheet(doc, size="11x17", fields=TitleBlockFields(),
                        layout_name="S2", extents=(0, 0, 10, 10),
                        window={"center": (5.0, 8.0)})
    main = lay.main_viewport()
    vp = [e for e in lay if e.dxftype() == "VIEWPORT" and e is not main][0]
    assert (vp.dxf.width, vp.dxf.height) == (9.5, 13.0)   # 11x17 size kept
    assert vp.dxf.center[0] == pytest.approx(5.0)


def test_compose_sheet_unknown_size():
    doc = new_doc()
    with pytest.raises(ValueError, match="unknown sheet size"):
        compose_sheet(doc, size="A0", fields=TitleBlockFields(),
                      layout_name="X", extents=(0, 0, 1, 1))
