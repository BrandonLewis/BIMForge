"""est-bim validate: open + schema-validate an IFC, report per-class counts.

The thin CLI form of the check the dxf-to-bim SKILL used to embed as an
inline python block (R12 item 3).
"""
from __future__ import annotations

import pytest

pytest.importorskip("ezdxf")
pytest.importorskip("shapely")
pytest.importorskip("ifcopenshell")
pytest.importorskip("yaml")

from bimforge.bim import cli  # noqa: E402


@pytest.fixture(scope="module")
def sample_ifc(tmp_path_factory):
    """Tiny IFC via the shipped sample DXF + example layer map."""
    tmp = tmp_path_factory.mktemp("validate")
    assert cli.main(["sample", "--dir", str(tmp), "--with-configs"]) == 0
    ifc = tmp / "model.ifc"
    assert cli.main([
        "dxf2bim", "--dxf", str(tmp / "sample_plan.dxf"),
        "--config", str(tmp / "layer_map.example.yaml"),
        "--out", str(ifc),
    ]) == 0
    return ifc


def test_valid_ifc_exits_zero_with_counts(sample_ifc, capsys):
    assert cli.main(["validate", str(sample_ifc)]) == 0
    out = capsys.readouterr().out
    # per-class counts (the sample model's known contents)
    import re
    assert re.search(r"IfcColumn +4", out)
    assert "IfcSlab" in out
    assert "IfcWall" in out
    # total element count and the schema verdict
    assert re.search(r"TOTAL +8", out)
    assert "schema issues: 0" in out


def test_nonexistent_file_exits_one(tmp_path, capsys):
    missing = tmp_path / "nope.ifc"
    assert cli.main(["validate", str(missing)]) == 1
    err = capsys.readouterr().err
    assert "error" in err and "nope.ifc" in err


def test_unparseable_file_exits_one(tmp_path, capsys):
    bad = tmp_path / "garbage.ifc"
    bad.write_text("this is not an IFC file", encoding="utf-8")
    assert cli.main(["validate", str(bad)]) == 1
    err = capsys.readouterr().err
    assert "error" in err


def test_unhosted_earthworks_cut_fails_with_a_hint(tmp_path, capsys):
    # #364: an IfcEarthworksCut that voids no host is invalid IFC; say so in
    # plain words and name the class pay-item excavation should carry
    import ifcopenshell
    import ifcopenshell.api.root
    f = ifcopenshell.file(schema="IFC4X3_ADD2")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="p")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcEarthworksCut",
                                        name="Cut 1")
    path = tmp_path / "cut.ifc"
    f.write(str(path))
    assert cli.main(["validate", str(path)]) == 1
    err = capsys.readouterr().err
    assert "Cut 1" in err
    assert "IfcRelVoidsElement" in err and "IfcEarthworksElement" in err


def test_ifc2x3_file_validates_without_crashing(tmp_path, capsys):
    # #369 review: the #364 cut check called by_type("IfcEarthworksCut") on
    # every schema but IFC4, and IFC2X3 has no such entity — RuntimeError.
    # Guard on the schema's own declarations, not on its name.
    import ifcopenshell
    # empty: the api's create_entity and the raw IfcProject both demand an
    # owner history on 2X3, and the crash needs no content to reproduce
    f = ifcopenshell.file(schema="IFC2X3")
    path = tmp_path / "old.ifc"
    f.write(str(path))
    rc = cli.main(["validate", str(path)])
    out = capsys.readouterr().out
    assert "TOTAL" in out and "schema issues:" in out
    assert rc in (0, 1)
