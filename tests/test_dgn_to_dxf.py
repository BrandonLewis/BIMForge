import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "dgn_to_dxf", Path(__file__).resolve().parents[1] / "scripts" / "dgn_to_dxf.py")
dgn_to_dxf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dgn_to_dxf)


def test_oda_command_shape():
    # stage 2: ODAFileConverter batch DWG -> DXF (ACAD2018).
    cmd = dgn_to_dxf.oda_command(
        exe="C:/ODA/ODAFileConverter.exe", in_dir="a/dwg", out_dir="a/dxf")
    assert cmd == ["C:/ODA/ODAFileConverter.exe", "a/dwg", "a/dxf",
                   "ACAD2018", "DXF", "0", "1", "*.DWG"]


def test_oda_command_filter_override():
    cmd = dgn_to_dxf.oda_command(
        exe="x", in_dir="i", out_dir="o", dwg_filter="2025__b03*.DWG")
    assert cmd[-1] == "2025__b03*.DWG"


def test_exdgnimport_command():
    # stage 1: one DGN -> DWG import.
    cmd = dgn_to_dxf.exdgnimport_command(
        exe="C:/ODA/ExDgnImport.exe", src_dgn="a/x.dgn", dst_dwg="t/x.dwg")
    assert cmd == ["C:/ODA/ExDgnImport.exe", "a/x.dgn", "t/x.dwg"]
