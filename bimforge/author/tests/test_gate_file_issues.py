"""The gate's file-only checks run on an open file (C.11): the build and
est-bim validate hold a file to the same functions."""
import ifcopenshell
import ifcopenshell.api.root
import pytest

from bimforge.author import gate


def _project(schema="IFC4X3_ADD2"):
    f = ifcopenshell.file(schema=schema)
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="p")
    return f


def test_spatial_issues_names_a_storey_with_no_building():
    f = _project("IFC4")
    site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name="s")
    storey = ifcopenshell.api.root.create_entity(
        f, ifc_class="IfcBuildingStorey", name="L1")
    f.createIfcRelAggregates(ifcopenshell.guid.new(), None, None, None,
                             f.by_type("IfcProject")[0], [site])
    f.createIfcRelAggregates(ifcopenshell.guid.new(), None, None, None,
                             site, [storey])
    issues = gate.spatial_issues(f)
    assert any("storey 'L1'" in i and "IfcBuilding" in i for i in issues)


def bad_formula(f, name="W"):
    """A wall whose GrossVolume is not its Formula over its own set."""
    wall = ifcopenshell.api.root.create_entity(f, ifc_class="IfcWall", name=name)
    qs = [f.createIfcQuantityLength("Length", None, None, 2.0),
          f.createIfcQuantityLength("Width", None, None, 3.0),
          f.createIfcQuantityLength("Height", None, None, 4.0),
          f.createIfcQuantityVolume("GrossVolume", None, None, 99.0,
                                    "Length * Width * Height")]
    qset = f.createIfcElementQuantity(ifcopenshell.guid.new(), None,
                                      "Qto_BaseQuantities", None, None, qs)
    f.createIfcRelDefinesByProperties(ifcopenshell.guid.new(), None, None,
                                      None, [wall], qset)
    return wall


def bad_representation(f, name="S"):
    """A slab whose Body says SweptSolid over an IfcFacetedBrep (#329)."""
    slab = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSlab", name=name)
    origin = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)))
    ctx = f.createIfcGeometricRepresentationContext(None, "Model", 3, 1e-5,
                                                    origin, None)
    brep = f.createIfcFacetedBrep(f.createIfcClosedShell([]))
    rep = f.createIfcShapeRepresentation(ctx, "Body", "SweptSolid", [brep])
    slab.Representation = f.createIfcProductDefinitionShape(None, None, [rep])
    return slab


def test_formula_issues_names_a_formula_that_does_not_hold():
    f = _project()
    bad_formula(f)
    issues = gate.formula_issues(f)
    assert len(issues) == 1 and "GrossVolume" in issues[0]


def test_unhosted_cut_issues_names_the_cut():
    f = _project()
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcEarthworksCut",
                                        name="Cut 1")
    (issue,) = gate.unhosted_cut_issues(f)
    assert "Cut 1" in issue and "IfcRelVoidsElement" in issue


def test_unhosted_cut_issues_is_empty_on_ifc2x3():
    assert gate.unhosted_cut_issues(ifcopenshell.file(schema="IFC2X3")) == []


def test_representation_issues_on_a_clean_file_is_empty():
    assert gate.representation_issues(_project()) == []


def test_representation_issues_names_a_type_that_does_not_admit_its_items():
    f = _project()
    bad_representation(f)
    (issue,) = gate.representation_issues(f)
    assert issue.startswith("S:") and "SweptSolid" in issue
    assert "IfcFacetedBrep" in issue


def test_schema_statements_split_attributes_from_rules():
    f = _project()
    f.createIfcCartesianPoint()          # Coordinates is required
    w = ifcopenshell.api.root.create_entity(f, ifc_class="IfcWall", name="W1")
    w.PredefinedType = "USERDEFINED"     # with no ObjectType: a WHERE rule
    kinds = gate.schema_statements(f)
    assert {k for k, line in kinds if "Coordinates" in line} == {"schema"}
    assert {k for k, line in kinds if "CorrectPredefinedType" in line} == {"rule"}
    assert [k for k, _ in gate.schema_statements(f, rules=False)] == ["schema"]
    assert gate.schema_issues(f) == [line for _, line in kinds]


@pytest.mark.parametrize("check, fn", [
    ("_ifc_spatial_chain_check", "spatial_issues"),
    ("_ifc_formula_check", "formula_issues"),
    ("_ifc_representation_type_check", "representation_issues"),
])
def test_the_gate_wrappers_return_the_file_functions_findings(
        tmp_path, check, fn):
    f = _project()
    bad_formula(f)
    bad_representation(f)
    path = tmp_path / "m.ifc"
    f.write(str(path))
    found = getattr(gate, fn)(ifcopenshell.open(str(path)))
    assert found                         # something to compare, not [] == []
    assert getattr(gate, check)(None, str(path)) == found
