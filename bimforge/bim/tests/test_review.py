"""plansheet/review: the review directory. File outputs need numpy only;
the crop tests (Task 11) importorskip fitz."""
from __future__ import annotations

import csv
import json

import numpy as np
import pytest

from bimforge.bim.plansheet.review import (LINE_COLUMNS, REVIEW_MARKER, affine_of,
                                           check_review_dir, clear_stale,
                                           contact_sheet,
                                           line_rows, render_crops,
                                           world_to_page, write_review)
from bimforge.terrain.reconcile import build_findings, neighbour_graph, reconcile


def _case():
    polys = [(np.column_stack([np.linspace(0, 100, 11), np.full(11, 10.0 * k)]),
              "sheet 1", "EXIST") for k in range(5)]
    g = neighbour_graph(polys)
    elev = {0: 25.0, 4: 20.0}                 # 25 and 20 with one line missing
    rec = reconcile(polys, g, elev, 1.0)
    return polys, g, elev, rec, build_findings(polys, g, elev, rec)


def test_write_review_writes_md_json_and_csv(tmp_path):
    polys, g, elev, rec, fs = _case()
    paths = write_review(tmp_path, fs, line_rows(polys, g, rec, elev))
    md = paths["review"].read_text(encoding="utf-8")
    assert "## F01 · conflict" in md
    assert "4(20) – 3 – 2 – 1 – 0(25)" in md
    data = json.loads(paths["findings"].read_text(encoding="utf-8"))
    assert [f["kind"] for f in data["findings"]] == ["conflict"]
    with open(paths["lines"], newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert list(rows[0]) == LINE_COLUMNS
    assert [r["status"] for r in rows] == ["lettered", "conflict", "conflict",
                                           "conflict", "lettered"]
    assert rows[2]["faces"] == "2" and rows[0]["values"] == "25"
    assert rows[0]["sheet"] == "sheet 1" and rows[0]["layer"] == "EXIST"


def test_write_review_says_when_there_is_nothing_to_look_at(tmp_path):
    md = write_review(tmp_path, [], [])["review"].read_text(encoding="utf-8")
    assert "No findings" in md


def test_clear_stale_touches_only_review_outputs(tmp_path):
    (tmp_path / REVIEW_MARKER).write_text("")            # a previous run's directory
    for name in ("F01.png", "F12.png", "contact-sheet.pdf", "contact-sheet-01.png",
                 "review.md", "findings.json", "lines.csv",
                 "keep.png", "L001.png", "notes.md"):
        (tmp_path / name).write_text("x")
    assert clear_stale(tmp_path) == 7
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        REVIEW_MARKER, "L001.png", "keep.png", "notes.md"]


def test_clear_stale_refuses_a_directory_it_did_not_write(tmp_path):
    (tmp_path / "review.md").write_text("my own notes")
    with pytest.raises(ValueError, match="not a review directory"):
        check_review_dir(tmp_path)
    with pytest.raises(ValueError, match="not a review directory"):
        clear_stale(tmp_path)
    assert (tmp_path / "review.md").read_text() == "my own notes"


def test_clear_stale_marks_a_new_directory(tmp_path):
    rd = tmp_path / "review"
    check_review_dir(rd)                     # not there yet: fine
    assert clear_stale(rd) == 0
    assert (rd / REVIEW_MARKER).is_file()
    (rd / "review.md").write_text("x")
    assert clear_stale(rd) == 1              # a marked directory is cleared


def test_check_review_dir_refuses_a_file(tmp_path):
    f = tmp_path / "review"
    f.write_text("x")
    with pytest.raises(ValueError, match="not a directory"):
        check_review_dir(f)
    assert f.read_text() == "x"


# ---------------------------------------------------------------- crops
def test_affine_of_and_world_to_page_round_trip():
    coef = (0.33, -0.25, 6692691.3, -0.25, -0.33, 2008717.4)

    def p2w(x, y):
        return (coef[0] * x + coef[1] * y + coef[2], coef[3] * x + coef[4] * y + coef[5])

    assert affine_of(p2w) == pytest.approx(coef)
    assert world_to_page(coef)(*p2w(387.8, 569.5)) == pytest.approx((387.8, 569.5))


def test_world_to_page_refuses_a_singular_placement():
    with pytest.raises(ValueError, match="singular"):
        world_to_page((1.0, 2.0, 0.0, 2.0, 4.0, 0.0))


@pytest.mark.parametrize("rotate", [0, 90])
def test_render_crops_draws_the_finding_on_its_vector(tmp_path, rotate):
    fitz = pytest.importorskip("fitz")
    from bimforge.bim.tests._pdf_fixtures import write_label_sheet
    from bimforge.terrain.reconcile import Finding
    pdf = write_label_sheet(tmp_path / "s.pdf", rotate=rotate)
    coef = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)            # page points are world feet
    polys = [(np.array([[100.0, y], [1100.0, y]]), "sheet 1", "C")
             for y in (200.0, 300.0, 400.0)]
    f = Finding("F01", "cross", [1], [], (600.0, 300.0))
    made = render_crops(pdf, coef, polys, [f], tmp_path / "rv",
                        sheet_of=lambda _f: 1, elev={}, crop_ft=80.0, dpi=144)
    pix = fitz.Pixmap(str(made["F01"]))
    s, n = pix.samples, pix.n
    red = sum(1 for i in range(0, len(s), n)
              if s[i] > 200 and s[i + 1] < 80 and s[i + 2] < 80)
    grey = sum(1 for i in range(0, len(s), n)
               if 100 < s[i] < 160 and abs(s[i] - s[i + 1]) < 12
               and abs(s[i + 1] - s[i + 2]) < 12)
    assert red > 0
    assert grey <= 0.2 * red      # the red overlay lies on the grey contour it traces


def test_render_crops_leaves_out_another_sheets_lines(tmp_path):
    fitz = pytest.importorskip("fitz")
    from bimforge.bim.tests._pdf_fixtures import write_label_sheet
    from bimforge.terrain.reconcile import Finding
    pdf = write_label_sheet(tmp_path / "s.pdf")
    coef = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
    # line 1 is on sheet 2: through sheet 1's placement it would land 10 pt
    # from the finding's own line, inside its crop, drawn orange
    polys = [(np.array([[100.0, 300.0], [1100.0, 300.0]]), "sheet 1", "C"),
             (np.array([[100.0, 310.0], [1100.0, 310.0]]), "sheet 2", "C")]
    f = Finding("F01", "cross", [0], [], (600.0, 300.0))

    def orange(made):
        pix = fitz.Pixmap(str(made["F01"]))
        s, n = pix.samples, pix.n
        return sum(1 for i in range(0, len(s), n)
                   if s[i] > 200 and 100 < s[i + 1] < 180 and s[i + 2] < 60)

    kw = dict(sheet_of=lambda _f: 1, elev={}, crop_ft=80.0, dpi=144)
    assert orange(render_crops(pdf, coef, polys, [f], tmp_path / "a", **kw)) > 0
    assert orange(render_crops(pdf, coef, polys, [f], tmp_path / "b",
                               line_sheet=[1, 2], **kw)) == 0


def test_render_crops_refuses_a_sheet_past_the_end_of_the_pdf(tmp_path):
    pytest.importorskip("fitz")
    from bimforge.bim.tests._pdf_fixtures import write_label_sheet
    from bimforge.terrain.reconcile import Finding
    pdf = write_label_sheet(tmp_path / "s.pdf")
    polys = [(np.array([[100.0, 300.0], [1100.0, 300.0]]), "sheet 9", "C")]
    f = Finding("F01", "cross", [0], [], (600.0, 300.0))
    with pytest.raises(ValueError, match="page"):
        render_crops(pdf, (1.0, 0.0, 0.0, 0.0, 1.0, 0.0), polys, [f],
                     tmp_path / "rv", sheet_of=lambda _f: 9, elev={},
                     crop_ft=80.0, dpi=72)


def test_render_crops_closes_scratch_when_page_copy_setup_fails(tmp_path, monkeypatch):
    fitz = pytest.importorskip("fitz")
    from bimforge.bim.tests._pdf_fixtures import write_label_sheet
    from bimforge.terrain.reconcile import Finding
    pdf = write_label_sheet(tmp_path / "s.pdf")
    f = Finding("F01", "cross", [0], [], (600.0, 300.0))
    polys = [(np.array([[100.0, 300.0], [1100.0, 300.0]]), "sheet 1", "C")]
    closed = []
    orig_insert = fitz.Document.insert_pdf
    orig_close = fitz.Document.close

    def boom(self, *args, **kwargs):
        if self.page_count == 0:
            raise RuntimeError("boom")
        return orig_insert(self, *args, **kwargs)

    def track_close(self, *args, **kwargs):
        closed.append(self.page_count)
        return orig_close(self, *args, **kwargs)

    monkeypatch.setattr(fitz.Document, "insert_pdf", boom)
    monkeypatch.setattr(fitz.Document, "close", track_close)
    with pytest.raises(RuntimeError, match="boom"):
        render_crops(pdf, (1.0, 0.0, 0.0, 0.0, 1.0, 0.0), polys, [f], tmp_path / "rv",
                     sheet_of=lambda _f: 1, elev={}, crop_ft=80.0, dpi=72)
    assert sorted(closed) == [0, 1]


def test_contact_sheet_captions_each_tile(tmp_path):
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    doc.new_page(width=50, height=50).get_pixmap(dpi=36).save(str(tmp_path / "F01.png"))
    doc.close()
    pdf = contact_sheet([("F01", "F01 · cross · lines 1, 2")], tmp_path)
    assert "F01 · cross · lines 1, 2" in fitz.open(str(pdf))[0].get_text()
    assert (tmp_path / "contact-sheet-01.png").exists()
    assert contact_sheet([], tmp_path) is None


def test_label_point_finds_the_point_inside_the_box_nearest_centre():
    fitz = pytest.importorskip("fitz")
    from bimforge.bim.plansheet.review import _label_point
    pl = np.array([[0.0, 0.0], [2000.0, 0.0]])          # a long horizontal line
    box = fitz.Rect(1900.0, -20.0, 2000.0, 20.0)         # the crop near one end
    pt = _label_point(pl, box, (1950.0, 0.0))
    assert pt is not None
    assert box.contains(fitz.Point(*pt))


def test_label_point_returns_none_when_the_path_never_enters_the_box():
    fitz = pytest.importorskip("fitz")
    from bimforge.bim.plansheet.review import _label_point
    pl = np.array([[0.0, 0.0], [0.0, 100.0], [100.0, 100.0]])   # an L around a corner
    box = fitz.Rect(60.0, 0.0, 100.0, 40.0)              # overlaps the bbox, not the path
    assert _label_point(pl, box, (80.0, 20.0)) is None


def test_crop_box_identity_affine_is_the_world_square():
    from bimforge.bim.plansheet.review import _crop_box
    w2p = world_to_page((1.0, 0.0, 0.0, 0.0, 1.0, 0.0))
    x0, y0, x1, y1 = _crop_box(w2p, (500.0, 500.0), 80.0)
    assert (x1 - x0, y1 - y0) == pytest.approx((80.0, 80.0))


def test_crop_box_nonuniform_affine_scales_axes_independently():
    from bimforge.bim.plansheet.review import _crop_box
    # page y spans half as many points as page x for the same world feet
    w2p = world_to_page((1.0, 0.0, 0.0, 0.0, 2.0, 0.0))
    x0, y0, x1, y1 = _crop_box(w2p, (500.0, 500.0), 80.0)
    assert (x1 - x0, y1 - y0) == pytest.approx((80.0, 40.0))


def test_lines_csv_formats_lo_hi_like_values():
    # #245: lo/hi used to write as raw floats ("21.0") while values used :g
    polys, g, elev, rec, _fs = _case()
    rows = line_rows(polys, g, rec, elev)
    ranged = [r for r in rows if r["lo"] != ""]
    assert ranged, "the middle lines should carry a lo/hi range"
    assert all(not str(r["lo"]).endswith(".0")
               and not str(r["hi"]).endswith(".0") for r in ranged)


def test_clip_polyline_keeps_only_the_in_box_run():
    import types
    from bimforge.bim.plansheet.review import _clip_polyline
    box = types.SimpleNamespace(x0=0.0, y0=0.0, x1=10.0, y1=10.0)
    pl = np.array([[-5.0, 5.0], [5.0, 5.0], [15.0, 5.0]])   # crosses in and out
    runs = _clip_polyline(pl, box)
    assert len(runs) == 1
    r = np.asarray(runs[0])
    assert r[:, 0].min() >= -1e-9 and r[:, 0].max() <= 10.0 + 1e-9


def test_clip_polyline_drops_a_bbox_overlap_that_never_enters():
    import types
    from bimforge.bim.plansheet.review import _clip_polyline
    box = types.SimpleNamespace(x0=0.0, y0=0.0, x1=10.0, y1=10.0)
    # an L whose bounding box overlaps the box but whose path stays outside it
    pl = np.array([[-5.0, 20.0], [20.0, 20.0], [20.0, -5.0]])
    assert _clip_polyline(pl, box) == []


def test_ellipsize_trims_to_width():
    from bimforge.bim.plansheet.review import _ellipsize
    measure = len                                    # one unit per char
    assert _ellipsize("short", 100, measure) == "short"
    out = _ellipsize("a very long caption that overflows", 10, measure)
    assert measure(out) <= 10 and out.endswith("…")
