"""est-bim validate's result (C.11): one verdict from what ships."""
import builtins
import json

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
pytest.importorskip("ezdxf")
pytest.importorskip("shapely")

import ifcopenshell.api.root  # noqa: E402

from bimforge.bim import cli  # noqa: E402
from bimforge.bim.validate import FAILING, validate  # noqa: E402


@pytest.fixture(scope="module")
def sample_ifc(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("validate-lib")
    assert cli.main(["sample", "--dir", str(tmp), "--with-configs"]) == 0
    ifc = tmp / "model.ifc"
    assert cli.main(["dxf2bim", "--dxf", str(tmp / "sample_plan.dxf"),
                     "--config", str(tmp / "layer_map.example.yaml"),
                     "--out", str(ifc)]) == 0
    return ifc


def _write(f, tmp_path, name="m.ifc"):
    path = tmp_path / name
    f.write(str(path))
    return path


def test_a_clean_file(sample_ifc):
    pytest.importorskip("ifctester.ids")
    r = validate(sample_ifc)
    assert r["contract"] == "bimforge-validate/1"
    assert r["verdict"] == "clean" and r["failing"] == 0
    for name in FAILING:
        assert r["sections"][name]["status"] == "pass", (name, r["sections"][name])
    assert r["sections"]["coverage"]["status"] == "advisory"
    assert set(r["versions"]) >= {"bimforge", "ifcopenshell", "ifctester"}
    assert r["schema"] and len(r["sha256"]) == 64
    rs = r["not_run"]["normative_rules"]["rule_set"]
    assert rs.startswith("buildingSMART/ifc-gherkin-rules@") and len(rs.split("@")[1]) == 40
    json.dumps(r)                       # serialisable as it stands


def test_a_where_rule_break_fails_rules_only(tmp_path):
    f = ifcopenshell.file(schema="IFC4X3_ADD2")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="p")
    w = ifcopenshell.api.root.create_entity(f, ifc_class="IfcWall", name="W1")
    w.PredefinedType = "USERDEFINED"
    r = validate(_write(f, tmp_path))
    assert r["verdict"] == "issues"
    assert r["sections"]["rules"]["status"] == "fail"
    assert any("CorrectPredefinedType" in x["check"] + x["message"]
               for x in r["sections"]["rules"]["findings"])
    assert r["sections"]["schema"]["status"] == "pass"


def test_a_storey_with_no_building_fails_structure(tmp_path):
    f = ifcopenshell.file(schema="IFC4")
    p = ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="p")
    site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name="s")
    st = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuildingStorey", name="L1")
    f.createIfcRelAggregates(ifcopenshell.guid.new(), None, None, None, p, [site])
    f.createIfcRelAggregates(ifcopenshell.guid.new(), None, None, None, site, [st])
    r = validate(_write(f, tmp_path))
    assert r["sections"]["structure"]["status"] == "fail"
    assert r["verdict"] == "issues"


def test_no_rules_is_incomplete(sample_ifc):
    r = validate(sample_ifc, rules=False)
    assert r["sections"]["rules"] == {"status": "not run", "reason": "--no-rules"}
    assert r["verdict"] == "incomplete"


def test_without_ifctester_the_ids_sections_do_not_run(sample_ifc, monkeypatch):
    real = builtins.__import__

    def no_ifctester(name, *a, **k):
        if name == "ifctester" or name.startswith("ifctester."):
            raise ImportError(name)
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_ifctester)
    r = validate(sample_ifc)
    for name in ("takeoff", "coverage"):
        assert r["sections"][name] == {"status": "not run",
                                       "reason": "pip install bimforge[ids]"}
    assert r["verdict"] == "incomplete"


def test_a_takeoff_failure_fails_and_a_coverage_finding_does_not(sample_ifc, tmp_path):
    pytest.importorskip("ifctester.ids")
    f = ifcopenshell.open(str(sample_ifc))
    wall = f.by_type("IfcWall")[0]
    for rel in list(wall.HasAssociations):
        if rel.is_a("IfcRelAssociatesClassification"):
            f.remove(rel)
    r = validate(_write(f, tmp_path, "uncls.ifc"))
    assert r["sections"]["coverage"]["findings"]
    assert r["sections"]["takeoff"]["status"] == "pass"
    assert r["verdict"] == "clean"
    ref = f.by_type("IfcClassificationReference")[0]
    ref.Identification = None
    r = validate(_write(f, tmp_path, "nocode.ifc"))
    assert r["sections"]["takeoff"]["status"] == "fail"
    assert any("Classification references carry a code" in x["check"]
               for x in r["sections"]["takeoff"]["findings"])


def test_extra_ids_add_to_takeoff(sample_ifc, tmp_path):
    pytest.importorskip("ifctester.ids")
    from importlib.resources import files
    doc = files("bimforge.bim") / "contract" / "takeoff-coverage.ids"
    extra = tmp_path / "extra.ids"
    extra.write_text(doc.read_text("utf-8"), "utf-8")
    f = ifcopenshell.open(str(sample_ifc))
    wall = f.by_type("IfcWall")[0]
    for rel in list(wall.HasAssociations):
        if rel.is_a("IfcRelAssociatesClassification"):
            f.remove(rel)
    r = validate(_write(f, tmp_path), extra_ids=[extra])
    assert r["sections"]["takeoff"]["status"] == "fail"
    assert any(x["check"].startswith("extra.ids:")
               for x in r["sections"]["takeoff"]["findings"])


def test_an_unreadable_file_raises(tmp_path):
    bad = tmp_path / "garbage.ifc"
    bad.write_text("not an IFC", "utf-8")
    with pytest.raises(ValueError, match="garbage.ifc"):
        validate(bad)
