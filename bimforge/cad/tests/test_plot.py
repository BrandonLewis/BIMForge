"""Layout rendering to PDF/PNG via the ezdxf drawing add-on."""
import pytest

ezdxf = pytest.importorskip("ezdxf")
pytest.importorskip("matplotlib")

from bimforge.cad.doc import new_doc
from bimforge.cad.plot import render_layout
from bimforge.cad.titleblock import TitleBlockFields, apply_title_block
from bimforge.cad.viewport import add_fitted_viewport, bbox


def _sheet_doc():
    doc = new_doc()
    msp = doc.modelspace()
    pts = [(0, 0), (40, 0), (40, 30), (0, 30), (0, 0)]
    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "S-CONC-OTLN"})
    # A filled triangle on "C-ANNO-TEXT" (ACI 2 / yellow, see bimforge.cad.layers)
    # inside the polyline's extents, for the mono-plot color-policy tests
    # below: literal yellow ink is illegible on white paper, so mono plots
    # must map it to black.
    msp.add_solid([(15, 10), (25, 10), (20, 20)], dxfattribs={"layer": "C-ANNO-TEXT"})
    lay = apply_title_block(doc, "ARCH_D", TitleBlockFields(sheet_title="TEST"), "TEST SHEET")
    add_fitted_viewport(lay, bbox(pts, margin=5.0))
    return doc


def test_render_pdf_and_png(tmp_path):
    doc = _sheet_doc()
    pdf = render_layout(doc, "TEST SHEET", tmp_path / "sheet.pdf")
    png = render_layout(doc, "TEST SHEET", tmp_path / "sheet.png", dpi=100)
    assert pdf.stat().st_size > 1000
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert pdf.read_bytes()[:5] == b"%PDF-"


def test_unknown_layout_raises(tmp_path):
    doc = new_doc()
    with pytest.raises(KeyError):
        render_layout(doc, "NOPE", tmp_path / "x.pdf")


def test_render_true_paper_size(tmp_path):
    """ARCH D is 36x24in; at dpi=50 the PNG should be ~1800x1200px."""
    doc = _sheet_doc()
    png = render_layout(doc, "TEST SHEET", tmp_path / "size.png", dpi=50)
    import struct

    data = png.read_bytes()
    # PNG IHDR: width/height are the first two 4-byte big-endian ints after
    # the 8-byte signature + 4-byte length + 4-byte "IHDR" chunk type.
    width, height = struct.unpack(">II", data[16:24])
    # matplotlib rounds inches*dpi to pixels, which can be off by one.
    assert abs(width - 1800) <= 1
    assert abs(height - 1200) <= 1


def test_render_11x17_portrait(tmp_path):
    doc = new_doc()
    lay = apply_title_block(doc, "11x17", TitleBlockFields(sheet_title="P"), "P SHEET")
    add_fitted_viewport(lay, (0.0, 0.0, 10.0, 10.0),
                        center=(5.5, 8.5), size=(9.5, 13.0))
    png = render_layout(doc, "P SHEET", tmp_path / "p.png", dpi=50)
    import struct

    w, h = struct.unpack(">II", png.read_bytes()[16:24])
    assert h > w  # portrait


def test_bad_suffix_rejected(tmp_path):
    doc = _sheet_doc()
    with pytest.raises(ValueError, match="must end in .pdf or .png"):
        render_layout(doc, "TEST SHEET", tmp_path / "sheet")


def _has_dark_ink(img) -> bool:
    """True if any pixel's darkest channel is below the 100/255 threshold."""
    rgb = img[..., :3]
    return bool((rgb.min(axis=-1) < 100 / 255).any())


def _has_saturated_yellow(img) -> bool:
    """True if any pixel is a bright, low-blue (saturated) yellow."""
    r, g, b = img[..., 0], img[..., 1], img[..., 2]
    return bool(((r > 200 / 255) & (g > 200 / 255) & (b < 100 / 255)).any())


def test_mono_plot_maps_yellow_layer_to_black(tmp_path):
    """Default mono=True renders the ACI-2 (yellow) layer as black ink;
    mono=False renders it literally as yellow, per standard CTB practice."""
    import matplotlib.image as mpimg

    doc = _sheet_doc()
    mono_png = render_layout(doc, "TEST SHEET", tmp_path / "mono.png", dpi=50)
    color_png = render_layout(
        doc, "TEST SHEET", tmp_path / "color.png", dpi=50, mono=False
    )

    def _read_normalized(png):
        img = mpimg.imread(str(png))
        if img.dtype.kind in "ui":
            img = img.astype("float64") / 255.0
        return img

    mono_img = _read_normalized(mono_png)
    color_img = _read_normalized(color_png)

    assert _has_dark_ink(mono_img)
    assert not _has_saturated_yellow(mono_img)
    assert _has_saturated_yellow(color_img)
