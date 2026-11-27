"""est-bim validate: accept a file (C.11), one verdict, per-class counts.

The CLI form of bimforge.bim.validate (the check the dxf-to-bim SKILL used to
embed as an inline python block, R12 item 3): exit 0 clean, 1 issues or
incomplete, 2 unreadable.
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
    pytest.importorskip("ifctester.ids")
    assert cli.main(["validate", str(sample_ifc)]) == 0
    out = capsys.readouterr().out
    # per-class counts (the sample model's known contents)
    import re
    assert re.search(r"IfcColumn +4", out)
    assert "IfcSlab" in out
    assert "IfcWall" in out
    # total element count and the verdict
    assert re.search(r"TOTAL +8", out)
    assert "verdict: clean" in out


def test_nonexistent_file_exits_two(tmp_path, capsys):
    missing = tmp_path / "nope.ifc"
    assert cli.main(["validate", str(missing)]) == 2
    err = capsys.readouterr().err
    assert "error" in err and "nope.ifc" in err


def test_unparseable_file_exits_two(tmp_path, capsys):
    bad = tmp_path / "garbage.ifc"
    bad.write_text("this is not an IFC file", encoding="utf-8")
    assert cli.main(["validate", str(bad)]) == 2
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
    out = capsys.readouterr().out       # under the structure section
    assert "Cut 1" in out
    assert "IfcRelVoidsElement" in out and "IfcEarthworksElement" in out


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
    assert "TOTAL" in out and "verdict:" in out
    assert rc in (0, 1)


def _rule_break(tmp_path):
    """A file every attribute of which is valid but that breaks a WHERE rule
    (IfcWall.CorrectPredefinedType: USERDEFINED needs an ObjectType)."""
    import ifcopenshell
    import ifcopenshell.api.root
    f = ifcopenshell.file(schema="IFC4X3_ADD2")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="p")
    w = ifcopenshell.api.root.create_entity(f, ifc_class="IfcWall", name="W1")
    w.PredefinedType = "USERDEFINED"
    path = tmp_path / "rule.ifc"
    f.write(str(path))
    return path


def test_a_where_rule_break_fails(tmp_path, capsys):
    # #94: the schema's rules are checked, not only its attribute types
    assert cli.main(["validate", str(_rule_break(tmp_path))]) == 1
    assert "CorrectPredefinedType" in capsys.readouterr().out


def test_no_rules_checks_attributes_only(tmp_path, capsys):
    # the rules did not run: the verdict is incomplete, never clean
    assert cli.main(["validate", "--no-rules",
                     str(_rule_break(tmp_path))]) == 1
    assert "rules: not run" in capsys.readouterr().out


def test_json_writes_the_result(sample_ifc, tmp_path):
    import json
    pytest.importorskip("ifctester.ids")
    out = tmp_path / "r.json"
    rc = cli.main(["validate", str(sample_ifc), "--json", str(out)])
    r = json.loads(out.read_text("utf-8"))
    assert r["contract"] == "bimforge-validate/1"
    assert r["verdict"] == "clean" and rc == 0


def test_json_dash_prints_only_the_result(sample_ifc, capsys):
    import json
    cli.main(["validate", str(sample_ifc), "--json", "-"])
    assert json.loads(capsys.readouterr().out)["file"] == sample_ifc.name


def test_a_missing_ids_document_exits_two(sample_ifc, tmp_path, capsys):
    assert cli.main(["validate", str(sample_ifc), "--ids",
                     str(tmp_path / "nope.ids")]) == 2
    assert "nope.ids" in capsys.readouterr().err


def test_an_unreadable_file_with_json_says_unreadable(tmp_path):
    import json
    bad = tmp_path / "garbage.ifc"
    bad.write_text("not an IFC", "utf-8")
    out = tmp_path / "r.json"
    assert cli.main(["validate", str(bad), "--json", str(out)]) == 2
    assert json.loads(out.read_text("utf-8"))["verdict"] == "unreadable"


def test_the_summary_is_sections_then_counts_then_verdict(sample_ifc, capsys):
    cli.main(["validate", str(sample_ifc)])
    lines = capsys.readouterr().out.splitlines()
    at = {key: next(i for i, line in enumerate(lines) if line.startswith(key))
          for key in ("schema:", "coverage:", "CLASS", "TOTAL", "verdict:")}
    order = [at[k] for k in ("schema:", "coverage:", "CLASS", "TOTAL", "verdict:")]
    assert order == sorted(order)


def test_a_missing_file_with_json_names_the_file_not_the_path(tmp_path):
    import json
    out = tmp_path / "r.json"
    assert cli.main(["validate", str(tmp_path / "nope.ifc"),
                     "--json", str(out)]) == 2
    r = json.loads(out.read_text("utf-8"))
    assert r["file"] == "nope.ifc" and r["verdict"] == "unreadable"


def test_a_bad_ids_document_exits_two_with_no_verdict(sample_ifc, tmp_path,
                                                      capsys):
    pytest.importorskip("ifctester.ids")
    bad = tmp_path / "bad.ids"
    bad.write_text("<not-ids/>", "utf-8")
    out = tmp_path / "r.json"
    assert cli.main(["validate", str(sample_ifc), "--ids", str(bad),
                     "--json", str(out)]) == 2
    assert "bad.ids" in capsys.readouterr().err
    assert not out.exists()          # the file was not judged: no verdict


def test_a_check_that_raises_a_value_error_is_not_unreadable(
        sample_ifc, monkeypatch, capsys):
    from bimforge.author import gate

    def boom(f):
        raise ValueError("a check's own failure")

    monkeypatch.setattr(gate, "formula_issues", boom)
    assert cli.main(["validate", str(sample_ifc)]) == 1
    out = capsys.readouterr().out
    assert "structure: fail" in out and "formula raised" in out


def test_without_ifctester_the_command_exits_one(sample_ifc, monkeypatch, capsys):
    import builtins
    real = builtins.__import__

    def no_ifctester(name, *a, **k):
        if name == "ifctester" or name.startswith("ifctester."):
            raise ImportError(name)
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_ifctester)
    assert cli.main(["validate", str(sample_ifc)]) == 1
    out = capsys.readouterr().out
    assert "takeoff: not run (pip install bimforge[ids])" in out
    assert "verdict: incomplete" in out


def test_the_rules_line_counts_the_rules_not_evaluated(sample_ifc, monkeypatch,
                                                       capsys):
    # a rule the executor could not evaluate is not a pass: the summary says
    # how many, beside the rules' status
    pytest.importorskip("ifctester.ids")
    from bimforge.bim.tests.test_validate import _unevaluated
    _unevaluated(monkeypatch)
    assert cli.main(["validate", str(sample_ifc)]) == 1
    out = capsys.readouterr().out
    assert "rules: pass (1 unevaluated)" in out.splitlines()
    assert "verdict: incomplete" in out


def test_the_rules_line_is_bare_when_every_rule_was_evaluated(sample_ifc,
                                                              capsys):
    pytest.importorskip("ifctester.ids")
    assert cli.main(["validate", str(sample_ifc)]) == 0
    assert "rules: pass" in capsys.readouterr().out.splitlines()
