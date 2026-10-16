"""est-bim label-crops: centred crops, a contact sheet, an anchors skeleton."""
from __future__ import annotations

import json

import pytest
import yaml

fitz = pytest.importorskip("fitz")

from bimforge.bim import cli  # noqa: E402
from bimforge.bim.tests._pdf_fixtures import write_label_sheet  # noqa: E402

TIES = ["--tie", "100,200=5000,1000", "--tie", "1100,200=5000,2000"]


def _manifest(tmp_path, pdf):
    m = tmp_path / "c.json"
    assert cli.main(["contours", "--pdf", pdf, "--sheet", "1", *TIES,
                     "--layer", "C=ocg:Topo|CONT_MJR", "--min-length", "2",
                     "--json", str(m)]) == 0
    return m


def _dark_share(png):
    pix = fitz.Pixmap(str(png))
    s, n = pix.samples, pix.n
    return sum(1 for i in range(0, len(s), n) if s[i] < 100) / (pix.width * pix.height)


def _label_crops(tmp_path, pdf, manifest, *extra):
    out, sk = tmp_path / "crops", tmp_path / "anchors.yaml"
    rc = cli.main(["label-crops", "--contours", str(manifest), "--pdf", pdf,
                   "--sheet", "1", "--out-dir", str(out), "--anchors", str(sk),
                   *extra])
    return rc, out, sk


def test_label_crops_writes_crops_a_contact_sheet_and_a_skeleton(tmp_path, capsys):
    pdf = write_label_sheet(tmp_path / "s.pdf")
    rc, out, sk = _label_crops(tmp_path, pdf, _manifest(tmp_path, pdf),
                               "--spots", "ocg:Topo|E_SPOT")
    assert rc == 0
    y = yaml.safe_load(sk.read_text(encoding="utf-8"))
    assert y["sheet"] == 1 and y["vertical_datum"] is None
    assert [c["source"] for c in y["contours"]] == ["mask", "mask"]
    assert [round(c["page"][1]) for c in y["contours"]] == [200, 300]
    assert all(c["elev"] is None for c in y["contours"] + y["spots"])
    assert all(isinstance(c["nearest_line"], int) and c["dist_ft"] < 1.0
               for c in y["contours"])
    assert len(y["spots"]) == 1
    names = {p.name for p in out.iterdir()}
    assert {"L001.png", "L002.png", "S001.png", "contact-sheet.pdf",
            "contact-sheet-01.png"} <= names
    assert _dark_share(out / "L001.png") > 0.0          # the glyph is in frame
    assert "2 label candidate(s)" in capsys.readouterr().out
    assert "REQUIRED" in sk.read_text(encoding="utf-8")   # the header says so

    # spec §4: the contact sheet rings each crop's centre and captions it
    # "id · source · line N" — build the expected caption from the skeleton
    # itself rather than hard-coding a line id.
    sheet_doc = fitz.open(str(out / "contact-sheet.pdf"))
    text = sheet_doc[0].get_text()
    first = y["contours"][0]
    for part in ("L001", first["source"], f"line {first['nearest_line']}"):
        assert part in text
    assert "S001" in text and "spot" in text
    drawings = sheet_doc[0].get_drawings()
    assert any(d.get("color") == (1.0, 0.0, 0.0) for d in drawings), \
        "expected a red-stroked ring drawing on the contact sheet"
    # the tiles are stored compressed (uncompressed: 16 MB on a real sheet)
    xrefs = [img[0] for img in sheet_doc.get_page_images(0)]
    assert xrefs and all("FlateDecode" in sheet_doc.xref_get_key(x, "Filter")[1]
                         for x in xrefs)
    sheet_doc.close()


def test_label_crops_removes_only_its_own_stale_outputs(tmp_path, capsys):
    pdf = write_label_sheet(tmp_path / "s.pdf")
    out = tmp_path / "crops"
    out.mkdir()
    for stale in ("L009.png", "S007.png", "contact-sheet-05.png"):
        (out / stale).write_bytes(b"stale")
    (out / "notes.txt").write_text("keep me", encoding="utf-8")

    rc, out, _ = _label_crops(tmp_path, pdf, _manifest(tmp_path, pdf),
                              "--spots", "ocg:Topo|E_SPOT")
    assert rc == 0
    names = {p.name for p in out.iterdir()}
    assert "L009.png" not in names
    assert "S007.png" not in names
    assert "contact-sheet-05.png" not in names
    assert "notes.txt" in names
    assert {"L001.png", "L002.png", "S001.png"} <= names
    assert "removed 3 stale output(s)" in capsys.readouterr().err


def test_label_crops_centres_crops_on_a_rotated_sheet(tmp_path):
    pdf = write_label_sheet(tmp_path / "r.pdf", rotate=90)
    rc, out, _ = _label_crops(tmp_path, pdf, _manifest(tmp_path, pdf))
    assert rc == 0
    assert _dark_share(out / "L001.png") > 0.0


def _ring_centres(pdf_path):
    """Centres of the red rings on the contact sheet's first page, in order."""
    doc = fitz.open(str(pdf_path))
    try:
        rings = [d["rect"] for d in doc[0].get_drawings()
                 if d.get("color") == (1.0, 0.0, 0.0)]
        return [((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2) for r in rings]
    finally:
        doc.close()


@pytest.mark.parametrize("rotate", [90, 270])
def test_label_crops_tiles_a_rotated_sheet_past_its_short_side(tmp_path, rotate):
    # The spot marker sits at unrotated x 900 — past the 792 pt short side
    # that becomes the visual width once the page is turned.
    pdf = write_label_sheet(tmp_path / "r.pdf", rotate=rotate)
    rc, out, sk = _label_crops(tmp_path, pdf, _manifest(tmp_path, pdf),
                               "--spots", "ocg:Topo|E_SPOT")
    assert rc == 0
    y = yaml.safe_load(sk.read_text(encoding="utf-8"))
    assert [round(s["page"][0]) for s in y["spots"]] == [900]
    assert _dark_share(out / "S001.png") > 0.0
    # tiles are L001, L002, S001: the third ring is the spot's tile centre,
    # and the marker's cross is under it (a tile is its crop, centred)
    cx, cy = _ring_centres(out / "contact-sheet.pdf")[2]
    doc = fitz.open(str(out / "contact-sheet.pdf"))
    try:
        pix = doc[0].get_pixmap(dpi=300, clip=fitz.Rect(cx - 3, cy - 3,
                                                        cx + 3, cy + 3))
    finally:
        doc.close()
    s, n = pix.samples, pix.n
    assert any(s[i] < 100 for i in range(0, len(s), n))


def test_label_crops_stale_clearing_is_a_digits_only_name_match(tmp_path, capsys):
    pdf = write_label_sheet(tmp_path / "s.pdf")
    out = tmp_path / "crops"
    out.mkdir()
    for stale in ("L1000.png", "S0042.png", "contact-sheet-100.png"):
        (out / stale).write_bytes(b"stale")
    for keep in ("Legend.png", "L01.png", "Site.png", "L001a.png"):
        (out / keep).write_bytes(b"keep")
    rc, out, _ = _label_crops(tmp_path, pdf, _manifest(tmp_path, pdf))
    assert rc == 0
    names = {p.name for p in out.iterdir()}
    assert not {"L1000.png", "S0042.png", "contact-sheet-100.png"} & names
    assert {"Legend.png", "L01.png", "Site.png", "L001a.png"} <= names
    assert "removed 3 stale output(s)" in capsys.readouterr().err


@pytest.mark.parametrize("where", ["out-dir", "anchors"])
def test_label_crops_unwritable_output_is_exit_1(tmp_path, capsys, where):
    pdf = write_label_sheet(tmp_path / "s.pdf")
    m = _manifest(tmp_path, pdf)
    capsys.readouterr()                  # drop the contours run's log
    blocker = tmp_path / "a-file"
    blocker.write_text("not a directory", encoding="utf-8")
    out = blocker / "crops" if where == "out-dir" else tmp_path / "crops"
    sk = blocker / "a.yaml" if where == "anchors" else tmp_path / "a.yaml"
    rc = cli.main(["label-crops", "--contours", str(m), "--pdf", pdf,
                   "--sheet", "1", "--out-dir", str(out), "--anchors", str(sk)])
    assert rc == 1
    assert capsys.readouterr().err.startswith("error: ")


@pytest.mark.parametrize("rotate", [0, 90])
def test_sheet_to_surface_chain_needs_no_ties(tmp_path, capsys, rotate):
    """contours (v2) -> label-crops -> a filled skeleton -> contour-surface,
    placed by the manifest's own georef (no --tie on the surface run)."""
    pytest.importorskip("scipy")
    import numpy as np

    from bimforge.terrain.contours import load_tin_npz
    pdf = write_label_sheet(tmp_path / "s.pdf", rotate=rotate)
    man = _manifest(tmp_path, pdf)
    rc, _, sk = _label_crops(tmp_path, pdf, man, "--spots", "ocg:Topo|E_SPOT")
    assert rc == 0
    y = yaml.safe_load(sk.read_text(encoding="utf-8"))
    # the fixture's contours run along page y = 200 / 300 / 400; what a
    # reader would letter on each
    known = {200: 120.0, 300: 110.0, 400: 100.0}
    for c in y["contours"]:
        c["elev"] = known[round(c["page"][1], -2)]
    for s in y["spots"]:
        s["elev"] = 95.0
    y.update({"vertical_datum": "NGVD29", "interval_ft": 10.0})
    sk.write_text(yaml.safe_dump(y, sort_keys=False), encoding="utf-8")
    capsys.readouterr()

    tin = tmp_path / "t.npz"
    assert cli.main(["contour-surface", "--contours", str(man),
                     "--anchors", str(sk), "--out", str(tin)]) == 0
    err = capsys.readouterr().err
    n = len(y["contours"])
    assert n == 2 and f"lettered: {n}/{n} labels matched" in err
    assert "placed by the manifest sheet 1 georef" in err
    t = load_tin_npz(tin)
    assert t.info["tiers"]["lettered"] == n
    assert t.info["vertical_datum"] == "NGVD29"
    assert sorted(ln["elev"] for ln in t.lines) == [110.0, 120.0]
    with np.load(tin, allow_pickle=False) as d:
        assert {"line_points", "line_offsets", "line_elev", "line_tier",
                "line_role", "point_line"} <= set(d.files)


def test_label_crops_refuses_a_v1_manifest(tmp_path, capsys):
    pdf = write_label_sheet(tmp_path / "s.pdf")
    v1 = tmp_path / "v1.json"
    v1.write_text(json.dumps({"sheet": 1, "layers": {}}), encoding="utf-8")
    rc, _, _ = _label_crops(tmp_path, pdf, v1)
    assert rc == 1 and "v2" in capsys.readouterr().err


def test_label_crops_rejects_unknown_sources(tmp_path, capsys):
    pdf = write_label_sheet(tmp_path / "s.pdf")
    rc, _, _ = _label_crops(tmp_path, pdf, _manifest(tmp_path, pdf),
                            "--sources", "mask,ocr")
    assert rc == 1 and "--sources" in capsys.readouterr().err


def test_label_crops_sheet_mismatch_is_exit_1(tmp_path, capsys):
    pdf = write_label_sheet(tmp_path / "s.pdf")
    m = _manifest(tmp_path, pdf)
    out, sk = tmp_path / "o", tmp_path / "a.yaml"
    rc = cli.main(["label-crops", "--contours", str(m), "--pdf", pdf,
                   "--sheet", "2", "--out-dir", str(out), "--anchors", str(sk)])
    assert rc == 1 and "sheet" in capsys.readouterr().err
