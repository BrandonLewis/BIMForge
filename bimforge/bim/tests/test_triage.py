"""Sheet triage: raster vs vector by placed-image coverage; GeoPDF presence."""
from __future__ import annotations

import pytest

from bimforge.bim.plansheet.triage import classify


def test_classify_thresholds():
    assert classify(0.60, 1224.0) == "raster"
    assert classify(0.59, 1224.0) == "vector"
    assert classify(1.00, 792.0) == "vector"          # letter/report page


fitz = pytest.importorskip("fitz")
from bimforge.bim.plansheet.triage import image_coverage, sheet_triage  # noqa: E402
from bimforge.bim.tests._pdf_fixtures import (  # noqa: E402
    write_geopdf, write_image_page, write_ocg_sheet, write_raw_vp,
)

STRIPS = [(0.0, k * 26.4, 1224.0, (k + 1) * 26.4) for k in range(30)]


def _coverage(pdf):
    doc = fitz.open(pdf)
    try:
        return image_coverage(doc[0])
    finally:
        doc.close()


def test_strip_tiled_scan_is_raster(tmp_path):
    pdf = write_image_page(tmp_path / "s.pdf", STRIPS + [STRIPS[0]])  # + a duplicate
    assert _coverage(pdf) >= 0.99
    assert sheet_triage(pdf, 0).kind == "raster"


def test_half_covered_page_is_vector(tmp_path):
    pdf = write_image_page(tmp_path / "h.pdf", [(0.0, 0.0, 612.0, 792.0)])
    assert _coverage(pdf) == pytest.approx(0.5, abs=0.01)
    assert sheet_triage(pdf, 0).kind == "vector"


def test_letter_size_full_image_is_not_a_plan_sheet(tmp_path):
    pdf = write_image_page(tmp_path / "l.pdf", [(0.0, 0.0, 612.0, 792.0)],
                           page=(612.0, 792.0))
    t = sheet_triage(pdf, 0)
    assert t.image_coverage >= 0.99 and t.kind == "vector"


def test_vector_sheet_has_no_coverage_and_no_viewport(tmp_path):
    t = sheet_triage(write_ocg_sheet(tmp_path / "v.pdf"), 0)
    assert (t.kind, t.image_coverage, t.viewports) == ("vector", 0.0, [])


def test_reports_geopdf_viewports(tmp_path):
    t = sheet_triage(write_geopdf(tmp_path / "g.pdf"), 0)
    assert len(t.viewports) == 1 and t.viewports[0].crs_epsg == 2226


def test_rotated_page_coverage_uses_the_visual_frame(tmp_path):
    # 1584x2448 portrait page, /Rotate 270 -> visual page.rect is 2448x1584.
    # The image covers 90% of the page in the UNROTATED (MediaBox) frame.
    pdf = write_image_page(tmp_path / "r.pdf", [(0.0, 0.0, 1584.0, 2200.0)],
                           page=(1584.0, 2448.0), rotate=270)
    assert _coverage(pdf) == pytest.approx(0.9, abs=0.02)
    assert sheet_triage(pdf, 0).kind == "raster"


def test_bad_page_index_raises(tmp_path):
    with pytest.raises(ValueError):
        sheet_triage(write_ocg_sheet(tmp_path / "v.pdf"), 5)


def test_malformed_vp_is_reported_not_raised(tmp_path):
    # a malformed /VP (here, a bare scalar) must not blow up triage — it
    # gets surfaced in viewport_error so callers like _pick_viewport /
    # _print_contours_profile can report it instead of crashing.
    pdf = write_raw_vp(tmp_path / "badvp.pdf", "5")
    t = sheet_triage(pdf, 0)
    assert t.viewports == []
    assert "/VP is not an array or dictionary" in t.viewport_error
