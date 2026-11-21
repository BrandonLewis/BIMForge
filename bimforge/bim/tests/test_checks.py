"""A measurement check recorded in the model, in ProjectCommand's shape
(M.5)."""
import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

import ifcopenshell.api.pset  # noqa: E402
import ifcopenshell.api.root  # noqa: E402
import ifcopenshell.api.unit  # noqa: E402

from bimforge.bim.alignment_station import US_SURVEY_FT_M  # noqa: E402
from bimforge.bim.carry_forward import carry_forward  # noqa: E402
from bimforge.bim.checks import read_checks, record_check  # noqa: E402
from bimforge.bim.stable_ids import foreign  # noqa: E402

PROJECT = "0PRJcheck0000000000000"
WALL = "0WALLcheck000000000000"
DIMS = "BIMForge_Dimensions"


def _model(height_ft=8.0, schema="IFC4", volume=2.0):
    """A metre file with one wall: its DesignHeight a length, its Batter a
    ratio, its GrossVolume a quantity."""
    f = ifcopenshell.file(schema=schema)
    p = ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject",
                                            name="p")
    p.GlobalId = PROJECT
    m = ifcopenshell.api.unit.add_si_unit(f, unit_type="LENGTHUNIT")
    ifcopenshell.api.unit.assign_unit(f, units=[m])
    wall = ifcopenshell.api.root.create_entity(f, ifc_class="IfcWall",
                                               name="stem")
    wall.GlobalId = WALL
    dims = ifcopenshell.api.pset.add_pset(f, product=wall, name=DIMS)
    dims.HasProperties = [
        f.createIfcPropertySingleValue(
            "DesignHeight", None,
            f.createIfcPositiveLengthMeasure(height_ft * US_SURVEY_FT_M)),
        f.createIfcPropertySingleValue("Batter", None,
                                       f.createIfcRatioMeasure(0.02))]
    qto = ifcopenshell.api.pset.add_qto(f, product=wall,
                                        name="Qto_BaseQuantities")
    ifcopenshell.api.pset.edit_qto(f, qto=qto,
                                   properties={"GrossVolume": volume})
    return f


def _record(f, **kw):
    args = {"sheet": "S-3", "sheet_value": 8.0, "unit": "FT",
            "revision": "Add. 2", "by": "B. Lewis", "day": "2026-11-21",
            "file_sha256": "ab" * 32}
    args.update(kw)
    return record_check(f, WALL, DIMS, "DesignHeight", **args)


def test_a_check_is_written_in_projectcommands_shape():
    f = _model()
    rec = _record(f)
    assert rec["status"] == "agrees" and not rec["replaced"]
    (approval,) = f.by_type("IfcApproval")
    assert approval.Identifier == f"{WALL}/{DIMS}/DesignHeight"
    assert (approval.Name, approval.Status, approval.Level,
            approval.Qualifier) == ("Check: DesignHeight", "agrees",
                                    "measurement", "within 1%")
    assert approval.TimeOfApproval == "2026-11-21T00:00:00"
    assert approval.GivingApproval.FamilyName == "B. Lewis"
    (link,) = f.by_type("IfcResourceApprovalRelationship")
    assert link.Name == "Checked" and link.RelatingApproval == approval
    (objective,) = link.RelatedResourceObjects
    assert (objective.Name, objective.ObjectiveQualifier,
            objective.UserDefinedQualifier) == (
        "Check: DesignHeight", "USERDEFINED", "measurement")
    sheet, model, tol = objective.BenchmarkValues
    # a positive length property is written as IfcLengthMeasure: the one
    # ProjectCommand reads, in the file's metres
    assert sheet.DataValue.is_a() == model.DataValue.is_a() == \
        "IfcLengthMeasure"
    assert sheet.DataValue.wrappedValue == pytest.approx(8 * US_SURVEY_FT_M)
    assert (sheet.Name, sheet.ValueSource, sheet.ConstraintSource) == (
        "SheetValue", "S-3", "Add. 2")
    assert (model.Name, model.ValueSource) == ("ModelValue", "stated")
    assert model.ConstraintSource == "sha256:" + "ab" * 32
    assert (tol.Name, tol.Benchmark, tol.ValueSource,
            tol.DataValue.wrappedValue) == (
        "Tolerance", "LESSTHANOREQUALTO", "relative", 0.01)
    path = model.ReferencePath
    assert (path.TypeIdentifier, path.InstanceName) == ("IfcPropertySet",
                                                        DIMS)
    assert (path.InnerReference.TypeIdentifier,
            path.InnerReference.AttributeIdentifier,
            path.InnerReference.InstanceName) == (
        "IfcPropertySingleValue", "HasProperties", "DesignHeight")
    (c,) = f.by_type("IfcRelAssociatesConstraint")
    assert c.RelatingConstraint == objective and c.RelatedObjects[0].GlobalId \
        == WALL
    (doc_rel,) = f.by_type("IfcRelAssociatesDocument")
    assert (doc_rel.RelatingDocument.Identification,
            doc_rel.RelatingDocument.Revision) == ("S-3", "Add. 2")
    for rel in (c, doc_rel, *f.by_type("IfcRelAssociatesApproval")):
        assert foreign(rel)
        assert rel.OwnerHistory.ChangeAction == "ADDED"
        assert rel.OwnerHistory.OwningApplication.ApplicationIdentifier == \
            "Bonsai"


def test_a_quantity_is_named_by_its_set_and_name():
    f = _model(volume=2.0)
    rec = record_check(f, WALL, "Qto_BaseQuantities", "GrossVolume",
                       sheet="S-3", sheet_value=2.0, unit="M3")
    assert rec["status"] == "agrees" and rec["measure"] == "IfcVolumeMeasure"
    (approval,) = f.by_type("IfcApproval")
    assert approval.Identifier == f"{WALL}/Qto_BaseQuantities/GrossVolume"
    model = read_checks(f)[0]
    assert model["model_value"] == pytest.approx(2.0)
    (_, metric, _) = f.by_type("IfcObjective")[0].BenchmarkValues
    assert (metric.ReferencePath.TypeIdentifier,
            metric.ReferencePath.InnerReference.TypeIdentifier,
            metric.ReferencePath.InnerReference.AttributeIdentifier) == (
        "IfcElementQuantity", "IfcPhysicalQuantity", "Quantities")


def test_a_value_past_the_tolerance_differs_and_a_measured_one_is_used():
    f = _model()
    assert _record(f, sheet_value=8.5)["status"] == "differs"
    rec = _record(f, sheet_value=8.5, measured=8.49)
    assert rec["status"] == "agrees" and rec["value_source"] == "measured"
    assert rec["model_value"] == pytest.approx(8.49 * US_SURVEY_FT_M)


def test_the_model_value_names_the_build_and_the_file():
    from bimforge.bim import model_identity
    f = _model()
    bid = model_identity.write(f, {"spec": 1}, "spec.yaml")
    _record(f)
    assert read_checks(f)[0]["model_origin"] == \
        f"build:{bid}; sha256:" + "ab" * 32


def test_recording_again_replaces_the_check_under_its_ids():
    f = _model()
    _record(f)
    ids = sorted(r.GlobalId for r in f.by_type("IfcRelAssociatesApproval")
                 + f.by_type("IfcRelAssociatesConstraint"))
    rec = _record(f, sheet_value=9.0)
    assert rec["replaced"] and rec["status"] == "differs"
    assert len(f.by_type("IfcApproval")) == 1
    assert len(f.by_type("IfcObjective")) == 1
    assert len(f.by_type("IfcMetric")) == 3
    assert len(f.by_type("IfcRelAssociatesDocument")) == 1
    assert sorted(r.GlobalId for r in f.by_type("IfcRelAssociatesApproval")
                  + f.by_type("IfcRelAssociatesConstraint")) == ids
    (approval_rel,) = f.by_type("IfcRelAssociatesApproval")
    assert approval_rel.OwnerHistory.ChangeAction == "MODIFIED"
    assert not [r for r in f.by_type("IfcReference")
                if not f.get_inverse(r)]
    # one application however many times it records (IfcApplication UR1)
    assert len(f.by_type("IfcApplication")) == 1


def test_a_check_projectcommand_recorded_is_replaced_under_its_ids():
    from bimforge.bim.tests.test_carry_forward import _measurement_check
    f = _model()
    _measurement_check(f, f.by_guid(WALL))
    _record(f)
    assert {r.GlobalId for r in f.by_type("IfcRelAssociatesApproval")} == {
        "1PCcheck00000000000000"}
    assert {r.GlobalId for r in f.by_type("IfcRelAssociatesConstraint")} == {
        "1PCconstraint000000000"}
    (check,) = read_checks(f)
    assert check["sheet_value"] == pytest.approx(8 * US_SURVEY_FT_M)
    assert check["by"] == "B. Lewis"


@pytest.mark.parametrize("what, message", [
    (("BIMForge_Dimensions", "Batter"), "length, area or volume"),
    (("BIMForge_Dimensions", "Toe"), "has no BIMForge_Dimensions.Toe"),
])
def test_what_cannot_be_checked_is_refused(what, message):
    f = _model()
    with pytest.raises(ValueError, match=message):
        record_check(f, WALL, *what, sheet="S-3", sheet_value=1.0,
                     unit="FT")


def test_a_wrong_unit_is_refused():
    with pytest.raises(ValueError, match="not a length unit"):
        _record(_model(), unit="CY")


def test_a_check_comes_across_a_rebuild_as_recorded():
    """A rebuild with a changed height carries the check as it was
    written: the reader calls it lapsed, nothing drops it."""
    returned = _model(8.0)
    _record(returned)
    rebuilt = _model(9.0)
    report = carry_forward(returned, rebuilt)
    assert report.links == 1 and not (report.dropped or report.vanished)
    (check,) = read_checks(rebuilt)
    assert check["status"] == "agrees"
    assert check["model_value"] == pytest.approx(8 * US_SURVEY_FT_M)
    assert check["sheet"] == "S-3"


def test_ifc4x3_is_written_too():
    f = _model(schema="IFC4X3")
    assert _record(f)["status"] == "agrees"
    assert read_checks(f)[0]["revision"] == "Add. 2"


def test_cli_records_and_lists_a_check(tmp_path, capsys):
    from bimforge.bim.cli import main
    path = tmp_path / "m.ifc"
    _model().write(str(path))
    out = tmp_path / "checked.ifc"
    assert main(["check", "--ifc", str(path), "--element", WALL, "--what",
                 f"{DIMS}.DesignHeight", "--sheet", "S-3", "--sheet-value",
                 "96", "--unit", "IN", "--by", "B. Lewis", "--out",
                 str(out)]) == 0
    assert "agrees" in capsys.readouterr().out
    assert main(["check", "--ifc", str(out), "--list"]) == 0
    listed = capsys.readouterr().out
    assert f"{WALL}/{DIMS}/DesignHeight: agrees" in listed
    assert "B. Lewis" in listed
    assert main(["check", "--ifc", str(path), "--element", WALL, "--what",
                 "DesignHeight", "--sheet", "S-3", "--sheet-value", "8",
                 "--unit", "FT", "--out", str(out)]) == 1
