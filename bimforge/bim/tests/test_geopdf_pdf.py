"""GeoPDF viewport reader against real (synthetic) PDFs — needs pymupdf.

The pure PDF-object parser and the scale gates (no pymupdf) live in
``test_geopdf.py``.
"""
from __future__ import annotations

import pytest

fitz = pytest.importorskip("fitz")

from bimforge.bim.plansheet.geopdf import anisotropy_ok, is_foot_crs, read_viewports  # noqa: E402
from bimforge.bim.tests._pdf_fixtures import write_geopdf, write_raw_vp  # noqa: E402

ORIGIN = (6_700_000.0, 1_950_000.0)
#: MuPDF stores PDF reals as 32-bit floats: /GPTS keep ~7 significant digits
#: (~4e-6 degree), so a GeoPDF fit is good to about a foot, never better.
GPTS_TOL_FT = 1.0


def test_maps_page_points_to_world(tmp_path):
    vp, = read_viewports(write_geopdf(tmp_path / "a.pdf"), 0)
    assert vp.crs_epsg == 2226 and vp.unit == "US survey foot"
    # user-space (600, 400) is unrotated y-down (600, 792 - 400)
    assert vp.to_world(600.0, 392.0) == pytest.approx(
        (ORIGIN[0] + 3000.0, ORIGIN[1] + 2000.0), abs=GPTS_TOL_FT)
    assert vp.anisotropy_pct < 0.05
    assert max(vp.residuals_ft) < GPTS_TOL_FT
    assert vp.bbox_pt == pytest.approx((100.0, 92.0, 1100.0, 692.0))


def test_indirect_viewport_reads_like_inline(tmp_path):
    a, = read_viewports(write_geopdf(tmp_path / "a.pdf"), 0)
    b, = read_viewports(write_geopdf(tmp_path / "b.pdf", indirect=True), 0)
    assert b.transform == pytest.approx(a.transform)


def test_page_without_viewport_or_non_geo(tmp_path):
    doc = fitz.open()
    doc.new_page()
    doc.save(str(tmp_path / "plain.pdf"))
    assert read_viewports(str(tmp_path / "plain.pdf"), 0) == []
    rl = write_geopdf(tmp_path / "rl.pdf", subtype="RL")
    assert read_viewports(rl, 0) == []


def test_wrong_bbox_on_rotated_page_trips_the_gate_and_page_mode_repairs(tmp_path):
    pdf = write_geopdf(tmp_path / "rot.pdf", page=(1584.0, 2448.0), rotate=270,
                       bbox=(0.0, 0.0, 1584.0, 1584.0),
                       true_bbox=(0.0, 0.0, 1584.0, 2448.0))
    bad, = read_viewports(pdf, 0)
    assert bad.anisotropy_pct > 30.0 and not anisotropy_ok(bad)
    assert max(bad.residuals_ft) < GPTS_TOL_FT    # residuals do NOT reveal it
    good, = read_viewports(pdf, 0, bbox_mode="page")
    assert anisotropy_ok(good)
    assert good.bbox_mode == "page"
    assert good.to_world(792.0, 1224.0) == pytest.approx(
        (ORIGIN[0] + 3960.0, ORIGIN[1] + 6120.0), abs=GPTS_TOL_FT)


def test_page_mode_uses_raw_mediabox_when_origin_is_offset(tmp_path):
    # MediaBox [100 50 1324 842] — an exporter whose page origin isn't (0,0).
    mb = (100.0, 50.0, 1324.0, 842.0)
    pdf = write_geopdf(tmp_path / "off.pdf", mediabox=mb,
                       bbox=(0.0, 0.0, 1224.0, 792.0),   # wrong: ignores the offset
                       true_bbox=mb)
    vp, = read_viewports(pdf, 0, bbox_mode="page")
    assert vp.bbox_mode == "page"
    # unrotated y-down (600, 392) is user-space (700, 450) inside the offset
    # MediaBox: world = origin + 5 ft/pt * (700, 450)
    assert vp.to_world(600.0, 392.0) == pytest.approx(
        (ORIGIN[0] + 3500.0, ORIGIN[1] + 2250.0), abs=GPTS_TOL_FT)


def test_metre_crs_is_read_but_flagged(tmp_path):
    pdf = write_geopdf(tmp_path / "utm.pdf", epsg=26910, ft_per_pt=0.2,
                       origin=(600_000.0, 4_270_000.0))
    vp, = read_viewports(pdf, 0)
    assert vp.unit == "metre" and not is_foot_crs(vp)


# ------------------------------------------------------- malformed viewports
def test_vp_scalar_is_not_an_array_or_dict(tmp_path):
    pdf = write_raw_vp(tmp_path / "badvp.pdf", "5")
    with pytest.raises(ValueError, match="/VP is not an array or dictionary"):
        read_viewports(pdf, 0)


def _vp_array(bbox="[0 0 100 100]",
             gpts="[38.0 -122.0 38.0 -121.9 37.9 -121.9 37.9 -122.0]",
             lpts="[0 0 1 0 1 1 0 1]"):
    return (f"[<</Type/Viewport/BBox {bbox}/Measure<</Type/Measure"
           f"/Subtype/GEO/LPTS{lpts}/GPTS{gpts}"
           f"/GCS<</Type/PROJCS/EPSG 2226>>>>>>]")


def test_null_bbox_raises(tmp_path):
    pdf = write_raw_vp(tmp_path / "nullbbox.pdf", _vp_array(bbox="null"))
    with pytest.raises(ValueError, match=r"/BBox is not a numeric array"):
        read_viewports(pdf, 0)


def test_non_array_bbox_raises(tmp_path):
    pdf = write_raw_vp(tmp_path / "strbbox.pdf", _vp_array(bbox="(nope)"))
    with pytest.raises(ValueError, match=r"/BBox is not a numeric array"):
        read_viewports(pdf, 0)


def test_non_numeric_gpts_entry_raises(tmp_path):
    pdf = write_raw_vp(tmp_path / "badgpts.pdf",
                       _vp_array(gpts="[38.0 (bad) 38.0 -121.9 37.9 -121.9 "
                                      "37.9 -122.0]"))
    with pytest.raises(ValueError, match=r"/GPTS is not a numeric array"):
        read_viewports(pdf, 0)


def test_non_array_lpts_raises(tmp_path):
    pdf = write_raw_vp(tmp_path / "badlpts.pdf",
                       _vp_array(lpts="<</not/an/array true>>"))
    with pytest.raises(ValueError, match=r"/LPTS is not a numeric array"):
        read_viewports(pdf, 0)
