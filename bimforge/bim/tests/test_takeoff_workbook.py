"""bimforge.bim.takeoff_workbook + the est-bim takeoff-workbook verb (#367).

A footing Prism authored over bimforge.author (two pay codes, L/W/H
quantities) plus an unclassified proxy -> emit_ifc -> the workbook. The
column order is the contract; CY / Forming SF / CF box / delta / Pay qty are
formulas on the right columns; Qty / L / W / H are the model's numbers in
blue; Summary SUMIFS by cost code; a rebuild is byte-identical.
"""
import hashlib
import json
import uuid
import zipfile

import numpy as np
import pytest

pytest.importorskip("ifcopenshell")
openpyxl = pytest.importorskip("openpyxl")

from bimforge.author.emit_ifc import emit_ifc
from bimforge.author.model import Element, StructureModel
from bimforge.author.primitives import Prism
from bimforge.author.project import ProjectContext
from bimforge.bim import cli
from bimforge.bim.takeoff_workbook import (ELEMENT_HEADERS, build_workbook,
                                           forming_default, load_official,
                                           planar_face_count)
from bimforge.bim.tests.test_ifc_mesh import CUBE_F, CUBE_V

TAKEOFF_LAYOUT = ["Qty", "#_surfaces", "L (ft)", "W (ft)", "H (ft)", "CY",
                  "Forming SF"]
MAP = {"codes": {
    "FTG-CONC": {"measure": "GrossVolume", "unit": "CY", "item_number": "0020",
                 "description": "Structure Concrete, Footing"},
    "FTG-FORM": {"measure": "GrossArea", "unit": "SF", "item_number": "0010"},
}}
OFFICIAL = [{"item_number": "0020", "estimated_quantity": 3.5,
             "description": "STRUCTURE CONCRETE (FOOTING)"},
            {"item_number": "0010", "quantity": "160"}]


def _emit_footing(tmp_path, name="m.ifc"):
    """A 10 x 4 x 2 ft footing on two pay codes plus a reference proxy."""
    ctx = ProjectContext(
        name="Workbook Fixture", epsg=2226,
        base_e=6_594_000.0, base_n=1_943_000.0, base_h=200.0,
        guid_ns=uuid.UUID("5a0e2c4d-9b17-4f36-8d25-3c1a7e9b0f42"))
    m = StructureModel("fixture", ctx)
    ftg = Prism("Abut 1 footing", [(0, 0), (10, 0), (10, 4), (0, 4)],
                z_bot=0.0, z_top=2.0, ifc="IfcFooting")
    m.add(Element.from_geometry(ftg.name, ftg, ifc_class="IfcFooting",
                                classifications=["FTG-CONC", "FTG-FORM"],
                                description="Spread footing, Abutment 1"))
    ref = Prism("Survey marker", [(20, 0), (21, 0), (21, 1), (20, 1)],
                z_bot=0.0, z_top=1.0)
    m.add(Element.from_geometry(ref.name, ref))      # [] = reference geometry
    out = tmp_path / name
    emit_ifc(m, str(out))
    return out


def _build(tmp_path, out_name="takeoff.xlsx", official=None):
    ifc = _emit_footing(tmp_path)
    out = tmp_path / out_name
    info = build_workbook([str(ifc)], MAP, str(out), official=official)
    return ifc, out, info


def _col(header):
    return openpyxl.utils.get_column_letter(ELEMENT_HEADERS.index(header) + 1)


# ------------------------------------------------------------------ contract
def test_header_order_is_the_takeoff_layout(tmp_path):
    _ifc, out, info = _build(tmp_path)
    ws = openpyxl.load_workbook(out)["Elements"]
    header = [c.value for c in ws[1]]
    assert header == ELEMENT_HEADERS
    # the estimator's fixed layout comes right after the identity columns
    assert header[9:16] == TAKEOFF_LAYOUT
    assert header[16:] == ["CF (model)", "CF (L×W×H×Qty)", "Δ box vs model",
                           "Area SF", "Weight LB", "Top SF", "Soffit SF",
                           "Side SF", "Form sides (1/0)", "Form soffit (1/0)",
                           "Pay qty", "GUID", "Model file",
                           "Pay measure", "Pay measure (model)"]
    assert ws.freeze_panes == "C2"
    # one row per element per pay code: footing x2 + reference x1
    assert info == {"elements": 3, "summary": 2, "models": 1}
    assert [ws[f"F{r}"].value for r in (2, 3, 4)] == [
        "FTG-CONC", "FTG-FORM", "(reference)"]


def test_formulas_reference_the_right_columns(tmp_path):
    _ifc, out, _ = _build(tmp_path)
    ws = openpyxl.load_workbook(out)["Elements"]
    # A..I identity, J Qty, K #_surfaces, L/M/N L/W/H, O CY, P Forming SF,
    # Q CF model, R CF box, S delta, T Area, U LB, V top, W soffit, X side,
    # Y/Z form flags, AA Pay qty
    assert _col("CY") == "O" and _col("Pay qty") == "AA"
    assert ws["O2"].value == '=IF(ISNUMBER(Q2),Q2/27,"")'
    assert ws["P2"].value == '=IF(ISNUMBER(X2),X2*Y2+W2*Z2,"")'
    assert ws["R2"].value == (
        '=IF(AND(ISNUMBER(L2),ISNUMBER(M2),ISNUMBER(N2)),L2*M2*N2*J2,"")')
    assert ws["S2"].value == (
        '=IF(AND(ISNUMBER(R2),ISNUMBER(Q2),Q2<>0),R2/Q2-1,"")')
    assert ws["AA2"].value == "=O2"            # GrossVolume / CY
    assert ws["AA3"].value == "=T3"            # GrossArea / SF
    assert ws["AA4"].value in (None, "")       # reference geometry pays nothing
    for cell in ("O2", "P2", "R2", "S2", "AA2"):
        assert str(ws[cell].value).startswith("="), cell


def test_inputs_are_the_models_numbers_in_blue(tmp_path):
    _ifc, out, _ = _build(tmp_path)
    ws = openpyxl.load_workbook(out)["Elements"]
    assert ws["J2"].value == 1
    assert ws["K2"].value == 6                       # a box: 6 planar faces
    assert ws["L2"].value == pytest.approx(10.0, rel=1e-9)
    assert ws["M2"].value == pytest.approx(4.0, rel=1e-9)
    assert ws["N2"].value == pytest.approx(2.0, rel=1e-9)
    assert ws["Q2"].value == pytest.approx(80.0, rel=1e-9)   # CF (model)
    assert ws["T2"].value == pytest.approx(40.0, rel=1e-9)   # Area SF
    assert ws["V2"].value == pytest.approx(40.0, rel=1e-6)   # top
    assert ws["W2"].value == pytest.approx(40.0, rel=1e-6)   # soffit
    assert ws["X2"].value == pytest.approx(56.0, rel=1e-6)   # 2*(10*2 + 4*2)
    assert (ws["Y2"].value, ws["Z2"].value) == (1, 0)        # footing: sides
    assert (ws["Y4"].value, ws["Z4"].value) == (0, 0)        # proxy: none
    for cell in ("J2", "L2", "M2", "N2", "Y2", "Z2"):
        assert ws[cell].font.color.rgb.endswith("0000FF"), cell
    for cell in ("A1", "B2", "O2", "Q2", "AB2"):
        assert ws[cell].font.name == "Arial", cell
    assert ws["L2"].number_format == "0.000"
    assert ws["O2"].number_format == "#,##0.00"
    assert ws["S2"].number_format == "0.0%"
    assert ws["D2"].value == "IfcFooting"
    assert ws["C2"].value == "Spread footing, Abutment 1"
    assert ws["G2"].value == "0020" and ws["I2"].value == "CY"
    assert ws["AB2"].value == ws["AB3"].value       # same GUID, two pay codes
    assert len(ws["AB2"].value) == 22


def test_summary_sumifs_by_cost_code(tmp_path):
    official = load_official_from(tmp_path)
    _ifc, out, _ = _build(tmp_path, official=official)
    sm = openpyxl.load_workbook(out)["Summary"]
    assert [c.value for c in sm[1]] == ["Item #", "Cost code", "Bid item",
                                        "Pay unit", "Modelled qty",
                                        "Official qty", "Variance",
                                        "Variance %", "Elements"]
    # ordered by item number: 0010 (FTG-FORM) then 0020 (FTG-CONC)
    assert [sm[f"B{r}"].value for r in (2, 3)] == ["FTG-FORM", "FTG-CONC"]
    assert sm["E3"].value == (
        "=SUMIFS(Elements!$AA$2:$AA$4,Elements!$F$2:$F$4,B3)")
    assert sm["I3"].value == "=COUNTIFS(Elements!$F$2:$F$4,B3)"
    assert sm["G3"].value == '=IF(ISNUMBER(F3),E3-F3,"")'
    assert sm["H3"].value == '=IF(AND(ISNUMBER(F3),F3<>0),G3/F3,"")'
    assert sm["F3"].value == 3.5                      # estimated_quantity
    assert sm["F2"].value == 160.0                    # quantity, as text
    assert sm["C3"].value == "STRUCTURE CONCRETE (FOOTING)"   # official wins
    assert sm["D3"].value == "CY"
    assert sm["F3"].font.color.rgb.endswith("0000FF")
    assert sm.freeze_panes == "A2"


def load_official_from(tmp_path):
    p = tmp_path / "bid_items.json"
    p.write_text(json.dumps(OFFICIAL), encoding="utf-8")
    return load_official(str(p))


def test_official_quantity_blank_without_the_file(tmp_path):
    _ifc, out, _ = _build(tmp_path)
    sm = openpyxl.load_workbook(out)["Summary"]
    assert sm["F2"].value is None and sm["F3"].value is None
    assert sm["C3"].value == "Structure Concrete, Footing"   # map description


def test_docprops_modified_is_pinned(tmp_path):
    # openpyxl's save stamps `modified` with wall-clock time, so two rebuilds
    # a second apart differed despite the pinned property.
    _ifc, out, _ = _build(tmp_path)
    with zipfile.ZipFile(out) as z:
        core = z.read("docProps/core.xml").decode("utf-8")
    assert "2026-08-15T12:00:00Z</dcterms:modified>" in core


def test_rebuild_is_byte_identical(tmp_path):
    ifc, a, _ = _build(tmp_path, "a.xlsx")
    b = tmp_path / "b.xlsx"
    build_workbook([str(ifc)], MAP, str(b))
    assert a.read_bytes() == b.read_bytes()
    src = openpyxl.load_workbook(a)["Sources"]
    assert [c.value for c in src[1]] == ["Model", "File", "SHA-256"]
    assert src["A2"].value == "m"
    assert src["B2"].value == str(ifc)
    assert src["C2"].value == hashlib.sha256(ifc.read_bytes()).hexdigest()
    lg = openpyxl.load_workbook(a)["Legend"]
    assert "Blue cells are inputs" in lg["A2"].value


def test_unmapped_code_is_a_review_note(tmp_path):
    ifc = _emit_footing(tmp_path)
    notes = []
    build_workbook([str(ifc)], {"codes": {"FTG-CONC": MAP["codes"]["FTG-CONC"]}},
                   str(tmp_path / "t.xlsx"), log=notes.append)
    assert any("FTG-FORM" in n and "no takeoff-map entry" in n for n in notes)
    sm = openpyxl.load_workbook(tmp_path / "t.xlsx")["Summary"]
    assert "FTG-FORM" in [sm[f"B{r}"].value for r in (2, 3)]   # still listed


def test_bad_pay_unit_for_the_measure_fails_loud(tmp_path):
    ifc = _emit_footing(tmp_path)
    bad = {"codes": {"FTG-CONC": {"measure": "GrossVolume", "unit": "SF"}}}
    with pytest.raises(ValueError, match="not a volume unit"):
        build_workbook([str(ifc)], bad, str(tmp_path / "t.xlsx"))


@pytest.mark.parametrize("measure,unit,expected", [
    ("NetVolume", "CF", "=AE2"),
    ("NetVolume", "CY", "=AE2/27"),
    ("NetArea", "SF", "=AE2"),
    ("Perimeter", "LF", "=AE2*J2"),
    ("Width", "LF", "=M2*J2"),
    ("Height", "LF", "=N2*J2"),
    ("NetWeight", "LB", "=AE2"),
])
def test_pay_quantity_uses_the_named_measure(tmp_path, monkeypatch, measure, unit, expected):
    from bimforge.bim import takeoff_workbook as tw

    values = {"NetVolume": 27 * tw.M_PER_FT ** 3,
              "NetArea": 12 * tw.M_PER_FT ** 2,
              "Perimeter": 28 * tw.M_PER_FT,
              "Width": 4 * tw.M_PER_FT, "Height": 2 * tw.M_PER_FT,
              "NetWeight": 10 * tw.KG_PER_LB}
    model = tmp_path / "fixture.ifc"
    model.write_text("fixture")
    element = tw.ElementRow(
        structure="Bridge", model_file=str(model), element="Footing", guid="test",
        ifc_class="IfcFooting", predefined_type=None, description="", part="",
        codes=["PAY"], length_ft=10, width_ft=4, height_ft=2,
        volume_cf=80, area_sf=40, weight_lb=30, quantities=values)
    monkeypatch.setattr(tw, "read_elements", lambda _: [element])
    out = tmp_path / "takeoff.xlsx"
    build_workbook([str(model)], {"codes": {"PAY": {"measure": measure, "unit": unit}}}, str(out))
    ws = openpyxl.load_workbook(out)["Elements"]
    assert ws["AA2"].value == expected
    assert ws["AD2"].value == measure
    assert ws["AE2"].value == pytest.approx({"NetVolume": 27, "NetArea": 12,
        "Perimeter": 28, "Width": 4, "Height": 2, "NetWeight": 10}[measure])


def test_missing_net_quantity_cannot_silently_use_gross(tmp_path):
    ifc = _emit_footing(tmp_path)
    with pytest.raises(ValueError, match="lacks mapped measure NetVolume"):
        build_workbook([str(ifc)], {"codes": {"FTG-CONC": {
            "measure": "NetVolume", "unit": "CY"}}}, str(tmp_path / "net.xlsx"))


@pytest.mark.parametrize("unit,count_as,expected", [("LS", None, 1.0), ("EA", 3, 3.0)])
def test_count_override_is_applied_once_per_pay_code(tmp_path, unit, count_as, expected):
    ifc = _emit_footing(tmp_path)
    cfg = {"measure": "Count", "unit": unit}
    if count_as is not None:
        cfg["count_as"] = count_as
    out = tmp_path / "count.xlsx"
    build_workbook([str(ifc), str(ifc)], {"codes": {"FTG-CONC": cfg}}, str(out))
    ws = openpyxl.load_workbook(out)["Elements"]
    paid_rows = [r for r in range(2, ws.max_row + 1) if ws[f"F{r}"].value == "FTG-CONC"]
    assert len(paid_rows) == 2
    for row in paid_rows:
        assert ws[f"AA{row}"].value == f'=IF(COUNTIF($F$2:F{row},F{row})=1,{expected!r},0)'


# ------------------------------------------------------------------- helpers
def test_planar_face_count_and_forming_defaults():
    v = np.asarray(CUBE_V, dtype=float).reshape(-1, 3)
    f = np.asarray(CUBE_F, dtype=np.int64).reshape(-1, 3)
    assert planar_face_count(v, f) == 6
    assert planar_face_count(v + [6_592_000.0, 1_943_000.0, 0.0], f) == 6
    assert forming_default("IfcFooting") == (1, 0)
    assert forming_default("IfcSlab") == (1, 1)
    assert forming_default("IfcSlab", "PRECAST") == (0, 0)
    assert forming_default("IfcCovering") == (0, 0)
    assert forming_default("IfcPile") == (0, 0)             # unlisted: none


def test_load_official_shapes(tmp_path):
    p = tmp_path / "o.json"
    p.write_text(json.dumps({"bid_items": OFFICIAL}), encoding="utf-8")
    got = load_official(str(p))
    assert got["0020"]["quantity"] == 3.5 and got["0010"]["quantity"] == 160.0
    p.write_text(json.dumps({"nope": 1}), encoding="utf-8")
    with pytest.raises(ValueError, match="expected a list"):
        load_official(str(p))
    assert load_official(None) == {}


# ----------------------------------------------------------------------- CLI
def test_cli_takeoff_workbook(tmp_path, capsys):
    ifc = _emit_footing(tmp_path)
    import yaml
    mp = tmp_path / "map.yaml"
    mp.write_text(yaml.safe_dump(MAP), encoding="utf-8")
    off = tmp_path / "bid_items.json"
    off.write_text(json.dumps(OFFICIAL), encoding="utf-8")
    out = tmp_path / "wb.xlsx"
    rc = cli.main(["takeoff-workbook", "--ifc", str(ifc), "--ifc", str(ifc),
                   "--map", str(mp), "--official", str(off), "--out", str(out)])
    assert rc == 0
    printed = capsys.readouterr().out
    assert "6 element rows, 2 summary rows, 2 model(s)" in printed
    assert out.is_file()
    src = openpyxl.load_workbook(out)["Sources"]
    assert src.max_row == 3


def test_cli_takeoff_workbook_missing_ifc_is_an_error(tmp_path, capsys):
    mp = tmp_path / "map.yaml"
    mp.write_text("codes: {}\n", encoding="utf-8")
    rc = cli.main(["takeoff-workbook", "--ifc", str(tmp_path / "nope.ifc"),
                   "--map", str(mp), "--out", str(tmp_path / "wb.xlsx")])
    assert rc == 1
    assert "error:" in capsys.readouterr().err
