"""est-sheets control / layout / structure end to end on tmp dirs."""
import json

import pytest

pytest.importorskip("bimforge.cad")
ezdxf = pytest.importorskip("ezdxf")
yaml = pytest.importorskip("yaml")

from bimforge.sheets.cli import main

CSV = ("point_id,description,northing_ft,easting_ft,elevation_ft\n"
       "CP1,CONTROL,1000.0,5000.0,100.0\n")
ALIGN = {"name": "P", "grade": "approximate",
         "points": [{"station": 10000.0, "northing": 1000.0, "easting": 5000.0},
                    {"station": 10200.0, "northing": 1200.0, "easting": 5000.0}]}


def test_control_subcommand(tmp_path):
    csv = tmp_path / "pts.csv"
    csv.write_text(CSV, encoding="utf-8")
    rc = main(["control", str(csv), "--project", "Job X", "--grade", "survey",
               "--title", "GEOMETRIC CONTROL", "--out-dir", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "geometric-control.dxf").exists()
    assert (tmp_path / "qc-geometric-control.md").exists()


def test_layout_subcommand(tmp_path):
    a = tmp_path / "align.yaml"
    a.write_text(yaml.safe_dump(ALIGN), encoding="utf-8")
    rc = main(["layout", str(a), "--project", "Job X",
               "--title", "SITE LAYOUT", "--out-dir", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "site-layout.dxf").exists()
    assert (tmp_path / "qc-site-layout.md").exists()


def test_structure_subcommand(tmp_path):
    doc = ezdxf.new("R2018")
    doc.layers.add("S-DECK")
    doc.modelspace().add_lwpolyline([(0, 0), (10, 0), (10, 10)], close=True,
                                    dxfattribs={"layer": "S-DECK"})
    src = tmp_path / "hw.dxf"
    doc.saveas(src)
    lm = tmp_path / "layer_map.yaml"
    lm.write_text(yaml.safe_dump({"layers": {"S-DECK": {}}}), encoding="utf-8")
    rc = main(["structure", str(src), "--layer-map", str(lm), "--project", "Job X",
               "--grade", "approximate", "--title", "HEADWALL 1",
               "--out-dir", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "headwall-1.sheet.dxf").exists()
    assert (tmp_path / "qc-headwall-1.md").exists()


def test_bad_inputs_fail_cleanly(tmp_path):
    rc = main(["control", str(tmp_path / "missing.csv"), "--project", "J",
               "--grade", "survey", "--title", "T", "--out-dir", str(tmp_path)])
    assert rc == 1


def test_bad_scale_fails_cleanly(tmp_path):
    csv = tmp_path / "pts.csv"
    csv.write_text(CSV, encoding="utf-8")
    rc = main(["control", str(csv), "--project", "J", "--grade", "survey",
               "--title", "T", "--out-dir", str(tmp_path), "--scale", "banana"])
    assert rc == 1


def test_layout_grade_from_yaml_flag_overrides(tmp_path):
    a = tmp_path / "align.yaml"
    a.write_text(yaml.safe_dump(ALIGN), encoding="utf-8")   # ALIGN has grade approximate
    rc = main(["layout", str(a), "--project", "J", "--title", "L2",
               "--out-dir", str(tmp_path), "--grade", "survey"])
    assert rc == 0
    doc = ezdxf.readfile(tmp_path / "l2.dxf")
    for layout in doc.layouts:
        for e in layout:
            if e.dxftype() == "MTEXT":
                assert "NOT FOR CONSTRUCTION LAYOUT" not in e.text


def test_title_with_dxf_invalid_chars(tmp_path):
    csv = tmp_path / "pts.csv"
    csv.write_text(CSV, encoding="utf-8")
    rc = main(["control", str(csv), "--project", "J", "--grade", "survey",
               "--title", '24" RCP HEADWALL', "--out-dir", str(tmp_path),
               "--no-pdf"])
    assert rc == 0
    assert (tmp_path / "24-rcp-headwall.dxf").exists()


def test_structure_with_preexisting_layout_still_renders_pdf(tmp_path):
    pytest.importorskip("matplotlib")
    doc = ezdxf.new("R2018")
    doc.layers.add("S-DECK")
    doc.modelspace().add_lwpolyline([(0, 0), (10, 0), (10, 10)], close=True,
                                    dxfattribs={"layer": "S-DECK"})
    doc.layouts.new("DETAILS")
    src = tmp_path / "hw.dxf"
    doc.saveas(src)
    lm = tmp_path / "lm.yaml"
    lm.write_text(yaml.safe_dump({"layers": {"S-DECK": {}}}), encoding="utf-8")
    rc = main(["structure", str(src), "--layer-map", str(lm), "--project", "J",
               "--grade", "approximate", "--title", "HEADWALL 3",
               "--out-dir", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "headwall-3.pdf").exists()


def test_structure_rejects_corrupt_dxf(tmp_path):
    src = tmp_path / "garbage.dxf"
    # Sniffs as DXF (starts with a (0, SECTION) tag) but is malformed past
    # that point, so ezdxf.readfile raises DXFStructureError rather than the
    # plain "not a DXF file" OSError a non-DXF blob would trigger.
    src.write_text("0\nSECTION\n2\nHEADER\n garbage not valid dxf content\n",
                   encoding="utf-8")
    lm = tmp_path / "layer_map.yaml"
    lm.write_text(yaml.safe_dump({"layers": {"S-DECK": {}}}), encoding="utf-8")
    rc = main(["structure", str(src), "--layer-map", str(lm), "--project", "J",
               "--grade", "approximate", "--title", "T", "--out-dir", str(tmp_path)])
    assert rc == 1


def test_layout_malformed_structures_fails_cleanly(tmp_path):
    a = tmp_path / "align.yaml"
    a.write_text(yaml.safe_dump(ALIGN), encoding="utf-8")
    s = tmp_path / "structures.json"
    s.write_text('[{"station": 1}]', encoding="utf-8")
    rc = main(["layout", str(a), "--project", "J", "--title", "L3",
               "--out-dir", str(tmp_path), "--structures", str(s)])
    assert rc == 1


def test_structure_unmapped_layer_fails_cleanly(tmp_path):
    doc = ezdxf.new("R2018")
    doc.layers.add("S-MYSTERY")
    doc.modelspace().add_lwpolyline([(0, 0), (5, 0), (5, 5)], close=True,
                                    dxfattribs={"layer": "S-MYSTERY"})
    src = tmp_path / "m.dxf"
    doc.saveas(src)
    lm = tmp_path / "lm.yaml"
    lm.write_text(yaml.safe_dump({"layers": {"S-DECK": {}}}), encoding="utf-8")
    rc = main(["structure", str(src), "--layer-map", str(lm), "--project", "J",
               "--grade", "approximate", "--title", "M", "--out-dir", str(tmp_path)])
    assert rc == 1
