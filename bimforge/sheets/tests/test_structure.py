"""Structure sheet: frame an existing takeoff DXF without touching modelspace."""
import pytest

pytest.importorskip("bimforge.cad")
ezdxf = pytest.importorskip("ezdxf")
yaml = pytest.importorskip("yaml")

from bimforge.sheets.model import SheetMeta
from bimforge.sheets.structure import frame_structure_sheet

LAYER_MAP = {"units": {"dxf_length_unit": "ft"},
             "layers": {"S-DECK": {"feature": "area"}}}
META = SheetMeta(project="Job X", sheet_title="HEADWALL TYPE 1", grade="approximate")


def _takeoff_dxf(path):
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 2
    doc.layers.add("S-DECK")
    doc.modelspace().add_lwpolyline([(0, 0), (40, 0), (40, 30), (0, 30)],
                                    close=True, dxfattribs={"layer": "S-DECK"})
    doc.saveas(path)
    return path


def test_frames_without_touching_modelspace(tmp_path):
    src = _takeoff_dxf(tmp_path / "hw.dxf")
    before = src.read_bytes()
    lm = tmp_path / "layer_map.yaml"
    lm.write_text(yaml.safe_dump(LAYER_MAP), encoding="utf-8")
    out = frame_structure_sheet(src, lm, META, tmp_path / "hw.sheet.dxf")
    assert src.read_bytes() == before                       # source untouched
    doc = ezdxf.readfile(out)
    names = {lay.name for lay in doc.layouts}
    assert any("HEADWALL" in n for n in names)
    msp_types = sorted(e.dxftype() for e in doc.modelspace())
    assert msp_types == ["LWPOLYLINE"]                      # geometry unchanged


def test_unmapped_layer_rejected(tmp_path):
    src = _takeoff_dxf(tmp_path / "hw.dxf")
    lm = tmp_path / "layer_map.yaml"
    lm.write_text(yaml.safe_dump({"units": {"dxf_length_unit": "ft"},
                                  "layers": {"S-WALL": {}}}), encoding="utf-8")
    with pytest.raises(ValueError, match="not in the layer map"):
        frame_structure_sheet(src, lm, META, tmp_path / "out.dxf")


def test_hatch_and_polyline_extents_covered(tmp_path):
    doc = ezdxf.new("R2018")
    doc.layers.add("S-DECK")
    doc.layers.add("A-HATCH")
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (10, 0), (10, 10)], close=True,
                       dxfattribs={"layer": "S-DECK"})
    h = msp.add_hatch(dxfattribs={"layer": "A-HATCH"})
    h.paths.add_polyline_path([(100, 100), (160, 100), (160, 140), (100, 140)],
                              is_closed=True)
    src = tmp_path / "mix.dxf"
    doc.saveas(src)
    lm = tmp_path / "lm.yaml"
    lm.write_text(yaml.safe_dump({"units": {"dxf_length_unit": "ft"},
                                  "layers": {"S-DECK": {}, "A-HATCH": {}}}),
                  encoding="utf-8")
    out = frame_structure_sheet(src, lm, META, tmp_path / "mix.sheet.dxf")
    doc2 = ezdxf.readfile(out)
    lay = [l for l in doc2.layouts if "HEADWALL" in l.name][0]
    vp = [e for e in lay if e.dxftype() == "VIEWPORT" and e is not lay.main_viewport()][0]
    # viewport must frame the hatch too (center pulled toward (80, 70))
    assert vp.dxf.view_center_point[0] > 50


def test_hatch_only_dxf_accepted(tmp_path):
    doc = ezdxf.new("R2018")
    doc.layers.add("A-HATCH")
    h = doc.modelspace().add_hatch(dxfattribs={"layer": "A-HATCH"})
    h.paths.add_polyline_path([(0, 0), (10, 0), (10, 10), (0, 10)], is_closed=True)
    src = tmp_path / "h.dxf"
    doc.saveas(src)
    lm = tmp_path / "lm.yaml"
    lm.write_text(yaml.safe_dump({"layers": {"A-HATCH": {}}}), encoding="utf-8")
    out = frame_structure_sheet(src, lm, META, tmp_path / "h.sheet.dxf")
    assert out.exists()


def test_lowercase_layer_accepted(tmp_path):
    doc = ezdxf.new("R2018")
    doc.layers.add("s-deck")
    doc.modelspace().add_lwpolyline([(0, 0), (5, 0), (5, 5)], close=True,
                                    dxfattribs={"layer": "s-deck"})
    src = tmp_path / "lc.dxf"
    doc.saveas(src)
    lm = tmp_path / "lm.yaml"
    lm.write_text(yaml.safe_dump({"layers": {"S-DECK": {}}}), encoding="utf-8")
    out = frame_structure_sheet(src, lm, META, tmp_path / "lc.sheet.dxf")
    assert out.exists()


def test_framing_preserves_inserts(tmp_path):
    doc = ezdxf.new("R2018")
    doc.layers.add("S-COL")
    blk = doc.blocks.new("EST-PT")
    blk.add_circle((0, 0), 0.5)
    msp = doc.modelspace()
    msp.add_blockref("EST-PT", (5, 5), dxfattribs={"layer": "S-COL"})
    src = tmp_path / "cols.dxf"
    doc.saveas(src)
    lm = tmp_path / "lm.yaml"
    lm.write_text(yaml.safe_dump({"layers": {"S-COL": {"feature": "count"}}}), encoding="utf-8")
    out = frame_structure_sheet(src, lm, META, tmp_path / "cols.sheet.dxf")
    doc2 = ezdxf.readfile(out)
    inserts = [e for e in doc2.modelspace() if e.dxftype() == "INSERT"]
    assert len(inserts) == 1 and inserts[0].dxf.insert[0] == 5
