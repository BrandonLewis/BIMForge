"""est-bim validate's result (C.11): one verdict from what ships."""
import builtins
import json

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
pytest.importorskip("ezdxf")
pytest.importorskip("shapely")

import ifcopenshell.api.root  # noqa: E402

from bimforge.bim import cli  # noqa: E402
from bimforge.bim.validate import (  # noqa: E402
    FAILING, BadIds, UnreadableFile, validate)


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
    with pytest.raises(UnreadableFile, match="garbage.ifc"):
        validate(bad)


REQUIRED_BRIDGE = """<?xml version="1.0" encoding="UTF-8"?>
<ids:ids xmlns:ids="http://standards.buildingsmart.org/IDS"
 xmlns:xs="http://www.w3.org/2001/XMLSchema"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
 xsi:schemaLocation="http://standards.buildingsmart.org/IDS http://standards.buildingsmart.org/IDS/1.0/ids.xsd">
  <ids:info><ids:title>req</ids:title></ids:info>
  <ids:specifications>
    <ids:specification name="There is a bridge" ifcVersion="IFC4 IFC4X3_ADD2">
      <ids:applicability minOccurs="{min}" maxOccurs="{max}">
        <ids:entity><ids:name><ids:simpleValue>{entity}</ids:simpleValue></ids:name></ids:entity>
      </ids:applicability>
    </ids:specification>
  </ids:specifications>
</ids:ids>
"""


def _ids(tmp_path, name, **kw):
    doc = tmp_path / name
    doc.write_text(REQUIRED_BRIDGE.format(**kw), "utf-8")
    return doc


def test_a_required_specification_nothing_applies_to_fails(sample_ifc, tmp_path):
    # ifctester fails the spec with no failed entity: still a finding
    pytest.importorskip("ifctester.ids")
    doc = _ids(tmp_path, "req.ids", min=1, max="unbounded", entity="IFCBRIDGE")
    r = validate(sample_ifc, extra_ids=[doc])
    assert r["verdict"] == "issues"
    (x,) = r["sections"]["takeoff"]["findings"]
    assert x["check"] == "req.ids: There is a bridge" and "instance" not in x
    assert "no applicable entity" in x["message"]


def test_a_prohibited_specification_names_what_it_applies_to(sample_ifc, tmp_path):
    pytest.importorskip("ifctester.ids")
    doc = _ids(tmp_path, "no-walls.ids", min=0, max=0, entity="IFCWALL")
    r = validate(sample_ifc, extra_ids=[doc])
    (x,) = r["sections"]["takeoff"]["findings"]
    assert "IfcWall" in x["instance"] and "prohibited" in x["message"]


def test_an_ids_document_that_does_not_parse_raises_before_any_check(
        sample_ifc, tmp_path, monkeypatch):
    pytest.importorskip("ifctester.ids")
    bad = tmp_path / "bad.ids"
    bad.write_text("<not-ids/>", "utf-8")
    from bimforge.author import gate

    def never(*a, **k):
        raise AssertionError("a check ran before the --ids documents parsed")

    monkeypatch.setattr(gate, "schema_statements", never)
    with pytest.raises(BadIds, match="bad.ids"):
        validate(sample_ifc, extra_ids=[bad])
    with pytest.raises(BadIds, match="nope.ids"):
        validate(sample_ifc, extra_ids=[tmp_path / "nope.ids"])


def test_a_wrong_attribute_fails_schema_not_rules(tmp_path):
    f = ifcopenshell.file(schema="IFC4X3_ADD2")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="p")
    f.createIfcCartesianPoint()          # Coordinates is required
    r = validate(_write(f, tmp_path))
    assert r["sections"]["schema"]["status"] == "fail"
    assert any("Coordinates" in x["message"]
               for x in r["sections"]["schema"]["findings"])
    assert r["sections"]["rules"]["status"] == "pass"


def test_an_alignment_ending_with_a_non_zero_segment_fails_alignment(tmp_path):
    import ifcopenshell.api.alignment as alapi

    from bimforge.bim.add_alignment import add_alignments
    from bimforge.bim.tests.test_add_alignment import ZIGZAG, _model
    f = _model()
    add_alignments(f, [ZIGZAG])
    (al,) = f.by_type("IfcAlignment")
    last = alapi.get_layout_segments(alapi.get_horizontal_layout(al))[-1]
    last.DesignParameters.SegmentLength = 1.0
    r = validate(_write(f, tmp_path))
    assert r["sections"]["alignment"]["status"] == "fail"
    assert any("ends with a segment of length 1.0" in x["message"]
               for x in r["sections"]["alignment"]["findings"])


def test_a_formula_that_does_not_hold_fails_structure(tmp_path):
    from bimforge.author.tests.test_gate_file_issues import bad_formula
    f = ifcopenshell.file(schema="IFC4X3_ADD2")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="p")
    bad_formula(f)
    r = validate(_write(f, tmp_path))
    assert r["sections"]["structure"]["status"] == "fail"
    assert any(x["check"] == "formula" and "GrossVolume" in x["message"]
               for x in r["sections"]["structure"]["findings"])


def test_a_check_that_raises_is_a_finding_not_a_traceback(sample_ifc, monkeypatch):
    from bimforge.author import gate

    def boom(f, *args):
        raise RuntimeError("hostile file")

    monkeypatch.setattr(gate, "spatial_issues", boom)
    r = validate(sample_ifc)
    assert r["sections"]["structure"]["status"] == "fail"
    raised = {"check": "spatial tree raised",
              "message": "RuntimeError: hostile file"}
    assert raised in r["sections"]["structure"]["findings"]
    assert r["verdict"] == "issues"


def _ifc2x3_project(path):
    """The smallest IFC2X3 file every other section passes: a project with
    its owner history, units and a model context."""
    f = ifcopenshell.file(schema="IFC2X3")
    org = f.createIfcOrganization(None, "o")
    owner = f.createIfcOwnerHistory(
        f.createIfcPersonAndOrganization(f.createIfcPerson(None, None, "x"), org),
        f.createIfcApplication(org, "1", "bimforge", "bimforge"),
        None, "ADDED", None, None, None, 0)
    origin = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)))
    ctx = f.createIfcGeometricRepresentationContext(None, "Model", 3, 1e-5,
                                                    origin, None)
    units = f.createIfcUnitAssignment(
        [f.createIfcSIUnit(None, "LENGTHUNIT", None, "METRE")])
    f.createIfcProject(ifcopenshell.guid.new(), owner, "p", None, None, None,
                       None, [ctx], units)
    f.write(str(path))
    return path


def test_a_schema_outside_the_takeoff_contract_is_not_run(tmp_path):
    pytest.importorskip("ifctester.ids")
    r = validate(_ifc2x3_project(tmp_path / "old.ifc"))
    for name in ("takeoff", "coverage"):
        assert r["sections"][name]["status"] == "not run"
        assert "IFC4" in r["sections"][name]["reason"]
        assert "IFC2X3" in r["sections"][name]["reason"]
    for name in ("schema", "rules", "alignment", "structure"):
        assert r["sections"][name]["status"] == "pass", r["sections"][name]
    assert r["verdict"] == "incomplete"


def test_a_schema_outside_the_contract_names_the_skipped_ids(tmp_path):
    pytest.importorskip("ifctester.ids")
    doc = _ids(tmp_path, "mine.ids", min=1, max="unbounded", entity="IFCWALL")
    r = validate(_ifc2x3_project(tmp_path / "old.ifc"), extra_ids=[doc])
    assert "mine.ids" in r["sections"]["takeoff"]["reason"]
    assert "mine.ids" not in r["sections"]["coverage"]["reason"]


def _hide(monkeypatch, hidden):
    """Make `import X` fail for every name `hidden(name)` is true of."""
    real = builtins.__import__

    def imp(name, *a, **k):
        if hidden(name):
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", imp)


def test_without_pytest_the_rules_do_not_run_and_schema_still_does(
        sample_ifc, monkeypatch):
    # ifcopenshell's rule executor imports _pytest; it is not a bimforge
    # dependency outside the ids extra, so the rules must read as not run
    # hidden only around the call: pytest's own reporting imports _pytest
    with monkeypatch.context() as m:
        _hide(m, lambda n: n == "_pytest" or n.startswith("_pytest.")
              or n == "pytest" or n.startswith("pytest."))
        r = validate(sample_ifc)
    assert r["sections"]["schema"] == {"status": "pass", "findings": []}
    assert r["sections"]["rules"]["status"] == "not run"
    assert "pytest" in r["sections"]["rules"]["reason"]
    assert "bimforge[ids]" in r["sections"]["rules"]["reason"]
    assert r["verdict"] == "incomplete"


def test_another_failure_of_the_rules_pass_is_a_rules_finding(tmp_path,
                                                             monkeypatch):
    from bimforge.author import gate
    real = gate.schema_statements

    def rules_crash(f, rules=True):
        if rules:
            raise RuntimeError("rule executor broke")
        return real(f, rules=False)

    monkeypatch.setattr(gate, "schema_statements", rules_crash)
    f = ifcopenshell.file(schema="IFC4X3_ADD2")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="p")
    f.createIfcCartesianPoint()          # an attribute finding to keep
    r = validate(_write(f, tmp_path))
    assert r["sections"]["rules"] == {"status": "fail", "findings": [
        {"check": "rules raised", "message": "RuntimeError: rule executor broke"}]}
    assert r["sections"]["schema"]["status"] == "fail"
    assert any("Coordinates" in x["message"]
               for x in r["sections"]["schema"]["findings"])


def test_without_ifctester_the_reason_names_the_skipped_ids(sample_ifc, tmp_path,
                                                           monkeypatch):
    real = builtins.__import__

    def no_ifctester(name, *a, **k):
        if name == "ifctester" or name.startswith("ifctester."):
            raise ImportError(name)
        return real(name, *a, **k)

    doc = _ids(tmp_path, "mine.ids", min=1, max="unbounded", entity="IFCWALL")
    monkeypatch.setattr(builtins, "__import__", no_ifctester)
    r = validate(sample_ifc, extra_ids=[doc])
    assert "mine.ids" in r["sections"]["takeoff"]["reason"]
    assert r["verdict"] == "incomplete"


def _bridge_with_a_rule_break(tmp_path):
    """IFC4X3 with a facility (as every family writes) and a wall breaking
    IfcWall.CorrectPredefinedType: USERDEFINED with no ObjectType."""
    import ifcopenshell.api.aggregate
    import ifcopenshell.api.spatial
    f = ifcopenshell.file(schema="IFC4X3_ADD2")
    p = ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="p")
    site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name="s")
    bridge = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBridge", name="b")
    ifcopenshell.api.aggregate.assign_object(f, products=[site], relating_object=p)
    ifcopenshell.api.aggregate.assign_object(f, products=[bridge],
                                             relating_object=site)
    w = ifcopenshell.api.root.create_entity(f, ifc_class="IfcWall", name="W1")
    w.PredefinedType = "USERDEFINED"
    ifcopenshell.api.spatial.assign_container(f, products=[w],
                                              relating_structure=bridge)
    return _write(f, tmp_path, "bridge.ifc")


def test_a_rule_break_in_a_facility_file_is_counted_once(tmp_path):
    r = validate(_bridge_with_a_rule_break(tmp_path))
    rules = r["sections"]["rules"]["findings"]
    assert any("CorrectPredefinedType" in x["message"] for x in rules)
    assert r["sections"]["structure"] == {"status": "pass", "findings": []}
    assert r["failing"] == len(rules)


def test_without_pytest_a_facility_file_has_a_passing_structure(
        tmp_path, monkeypatch):
    path = _bridge_with_a_rule_break(tmp_path)
    with monkeypatch.context() as m:
        _hide(m, lambda n: n.split(".")[0] in ("_pytest", "pytest"))
        r = validate(path)
    assert r["sections"]["structure"] == {"status": "pass", "findings": []}
    assert r["sections"]["rules"]["status"] == "not run"
    assert r["verdict"] == "incomplete"


def _unevaluated(monkeypatch):
    """A validator that could not evaluate one rule (info level) and
    found nothing wrong."""
    import ifcopenshell.validate

    def fake(f, logger, express_rules=False):
        if express_rules:
            logger.set_state("type", "entity_rule")
            logger.info("maximum recursion depth exceeded")

    monkeypatch.setattr(ifcopenshell.validate, "validate", fake)


def test_a_rule_that_could_not_be_evaluated_is_not_a_pass(sample_ifc,
                                                         monkeypatch):
    pytest.importorskip("ifctester.ids")
    _unevaluated(monkeypatch)
    r = validate(sample_ifc)
    assert r["sections"]["rules"] == {"status": "pass", "findings": [],
                                      "unevaluated": 1}
    assert r["verdict"] == "incomplete"


def test_every_rule_evaluated_says_so(sample_ifc):
    pytest.importorskip("ifctester.ids")
    r = validate(sample_ifc)
    assert r["sections"]["rules"]["unevaluated"] == 0
    assert r["verdict"] == "clean"
