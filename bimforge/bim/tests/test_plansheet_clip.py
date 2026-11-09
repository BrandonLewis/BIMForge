"""extract_sheet honours the PDF's clip paths (#17).

Line work outside the active clip is in the content stream but never plots,
so a harvest that ignores the clip returns phantom contours and labels.
"""
import pytest

fitz = pytest.importorskip("fitz")

from bimforge.bim.plansheet.vectors import extract_sheet  # noqa: E402

# PDF user space is y-up on a 600 x 600 page, so page y = 600 - pdf y.
# Clip A: pdf (100,100)-(300,300) -> page (100,300)-(300,500).
# Clip B, nested in A: pdf (150,150)-(200,200) -> page (150,400)-(200,450).
STREAM = (
    b"q 100 100 200 200 re W n "
    b"0 0 m 500 500 l S "                    # diagonal crossing clip A
    b"400 550 m 450 560 l S "                # wholly outside clip A: a phantom
    b"q 150 150 50 50 re W n "
    b"0 200 m 600 200 l S "                  # horizontal crossing clip B
    b"Q Q "
    b"10 590 m 60 590 l S"                   # after both Q: unclipped
)


@pytest.fixture
def clipped_pdf(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=600, height=600)
    xref = doc.get_new_xref()
    doc.update_object(xref, "<<>>")
    doc.update_stream(xref, STREAM)
    doc.xref_set_key(page.xref, "Contents", f"{xref} 0 R")
    path = tmp_path / "clipped.pdf"
    doc.save(str(path))
    doc.close()
    return path


def _ends(sv):
    return sorted((round(s.x1, 3), round(s.y1, 3), round(s.x2, 3), round(s.y2, 3))
                  for s in sv.segments)


def test_segments_are_cut_to_the_active_clip(clipped_pdf):
    sv = extract_sheet(clipped_pdf, 0, min_path_pt=0.0)
    assert _ends(sv) == sorted([
        (100.0, 500.0, 300.0, 300.0),        # the diagonal, inside clip A only
        (150.0, 400.0, 200.0, 400.0),        # the horizontal, inside clip B only
        (10.0, 10.0, 60.0, 10.0),            # outside every clip: untouched
    ])
    assert sv.clip_cut == 2
    assert sv.clip_dropped == 1


def test_clip_can_be_ignored(clipped_pdf):
    sv = extract_sheet(clipped_pdf, 0, min_path_pt=0.0, honor_clip=False)
    assert len(sv.segments) == 4
    assert (sv.clip_cut, sv.clip_dropped) == (0, 0)
    assert (0.0, 600.0, 500.0, 100.0) in _ends(sv)


def test_a_rotated_sheet_clips_in_the_same_frame(clipped_pdf, tmp_path):
    doc = fitz.open(str(clipped_pdf))
    doc[0].set_rotation(90)
    rotated = tmp_path / "rotated.pdf"
    doc.save(str(rotated))
    doc.close()
    assert _ends(extract_sheet(rotated, 0, min_path_pt=0.0)) == \
        _ends(extract_sheet(clipped_pdf, 0, min_path_pt=0.0))


def test_contours_reports_what_the_clip_removed(clipped_pdf, capsys):
    from bimforge.bim.cli import main
    assert main(["contours", "--pdf", str(clipped_pdf), "--sheet", "1",
                 "--profile", "--min-path-pt", "0"]) == 0
    assert "1 stroke(s) outside them dropped, 2 cut" in capsys.readouterr().err
