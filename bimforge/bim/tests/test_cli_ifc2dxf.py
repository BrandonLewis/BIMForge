import json
import os
from pathlib import Path

from bimforge.bim import cli
from bimforge.bim.tests.test_ifc2dxf import _foreign_ifc


def test_cli_ifc2dxf_writes_dxf_and_sidecar(tmp_path, capsys):
    ifc = _foreign_ifc(tmp_path / "m.ifc")
    out = tmp_path / "m.plan.dxf"
    rc = cli.main(["ifc2dxf", "--ifc", str(ifc), "--out", str(out)])
    assert rc == 0
    assert out.is_file()
    sidecar = str(out) + ".sidecar.json"
    assert os.path.isfile(sidecar)
    assert json.loads(Path(sidecar).read_text(encoding="utf-8"))["elements"] == 2
    printed = capsys.readouterr().out
    assert "UNGEOREFERENCED" in printed
    assert "layer_map.yaml" in printed  # the next-step hint


def test_cli_ifc2dxf_zero_geometry_is_nonzero_exit(tmp_path, capsys):
    ifc = _foreign_ifc(tmp_path / "m.ifc")
    rc = cli.main(["ifc2dxf", "--ifc", str(ifc), "--include", "IfcBeam"])
    assert rc == 1
    assert "error:" in capsys.readouterr().err


def test_cli_ifc2dxf_sidecar_records_filters(tmp_path):
    ifc = _foreign_ifc(tmp_path / "m.ifc")
    out = tmp_path / "m.plan.dxf"
    rc = cli.main(["ifc2dxf", "--ifc", str(ifc), "--out", str(out),
                   "--include", "IfcSlab", "--simplify-ft", "0.05"])
    assert rc == 0
    payload = json.loads(
        Path(str(out) + ".sidecar.json").read_text(encoding="utf-8"))
    assert payload["params"] == {"include": ["IfcSlab"], "exclude": None,
                                 "simplify_ft": 0.05}


def test_cli_ifc2dxf_sidecar_override_path(tmp_path):
    ifc = _foreign_ifc(tmp_path / "m.ifc")
    out = tmp_path / "m.plan.dxf"
    custom_sidecar = tmp_path / "custom.qc.json"
    rc = cli.main(["ifc2dxf", "--ifc", str(ifc), "--out", str(out),
                   "--sidecar", str(custom_sidecar)])
    assert rc == 0
    assert custom_sidecar.is_file()
    default_sidecar = Path(str(out) + ".sidecar.json")
    assert not default_sidecar.exists()


def test_cli_ifc2dxf_skipped_row_stderr_format(monkeypatch, tmp_path, capsys):
    # Pin the exact stderr line format for a skipped row without needing to
    # author a real IFC element that triggers a skip (fiddly to construct
    # deterministically) -- monkeypatch ifc_to_dxf's result instead, since
    # the CLI's skip-loop only reads row['ifc_class']/row['global_id']/
    # row['reason'] off whatever ifc_to_dxf returns.
    from bimforge.bim.ifc2dxf import Ifc2DxfResult

    ifc = _foreign_ifc(tmp_path / "m.ifc")
    out = tmp_path / "m.plan.dxf"

    def fake_ifc_to_dxf(ifc_path, out_path=None, **kwargs):
        res = Ifc2DxfResult(out=str(out), georef={"status": "ungeoreferenced",
                                                   "unit": "ft"})
        res.elements = 1
        res.entities = [{"layer": "IFCSLAB-FLOOR", "global_id": "keep",
                         "name": None, "ifc_class": "IfcSlab",
                         "predefined_type": "FLOOR", "area": 1.0, "rings": 1,
                         "vertices": 4, "z_min": 0.0, "z_max": 1.0}]
        res.skipped = [{"ifc_class": "IfcBeam", "global_id": "ABC123",
                        "reason": "no plan-view area"}]
        res.params = {"include": None, "exclude": None, "simplify_ft": 0.0}
        return res

    monkeypatch.setattr(
        "bimforge.bim.ifc2dxf.ifc_to_dxf", fake_ifc_to_dxf)
    rc = cli.main(["ifc2dxf", "--ifc", str(ifc), "--out", str(out)])
    assert rc == 0
    err = capsys.readouterr().err
    assert "  skipped IfcBeam ABC123: no plan-view area\n" in err
