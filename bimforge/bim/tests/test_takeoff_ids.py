"""The takeoff contract as IDS: the committed documents are the generated
ones, every producer in the tree conforms, and each rule fails on the breach
it names."""
from __future__ import annotations

from importlib.resources import files

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
yaml = pytest.importorskip("yaml")

from bimforge.bim import takeoff_ids  # noqa: E402
from bimforge.bim.ifc_takeoff import MEASURE_DIM, quantity_sets  # noqa: E402


def test_committed_documents_are_the_generated_ones():
    for name, text in takeoff_ids.documents().items():
        committed = (files("bimforge.bim") / "contract" / name).read_text(
            encoding="utf-8")
        assert committed == text, (
            f"{name} is stale: run python -m bimforge.bim.takeoff_ids")


def test_every_measure_the_reader_knows_has_a_datatype_rule():
    assert set(MEASURE_DIM.values()) == set(takeoff_ids.DIM_DATATYPE)
    assert set(takeoff_ids.SUMMABLE) <= set(MEASURE_DIM)


def test_element_classes_cover_both_schemas():
    classes = takeoff_ids.element_classes()
    assert {"IFCWALL", "IFCREINFORCINGBAR", "IFCEARTHWORKSCUT",
            "IFCWALLSTANDARDCASE"} <= set(classes)
    assert "IFCELEMENT" not in classes          # abstract


# -- conformance, through ifctester ------------------------------------------
ids = pytest.importorskip("ifctester.ids")
pytest.importorskip("ezdxf")
pytest.importorskip("shapely")

from bimforge.bim.dxf2bim import UNIT_TO_M, build_ifc, extract_features  # noqa: E402
from bimforge.bim.sample import write_sample_dxf  # noqa: E402


def _check(model, name: str) -> dict[str, list]:
    """{specification name: failed entities} for one committed document."""
    path = files("bimforge.bim") / "contract" / name
    spec = ids.open(str(path), validate=True)     # also checks it against the XSD
    spec.validate(model)
    return {s.name: list(s.failed_entities) for s in spec.specifications}


@pytest.fixture(scope="module")
def sample_ifc(tmp_path_factory) -> str:
    tmp = tmp_path_factory.mktemp("ids")
    layer_map = yaml.safe_load((files("bimforge.bim") / "examples"
                                / "layer_map.example.yaml").read_text("utf-8"))
    scale = UNIT_TO_M[layer_map["units"]["dxf_length_unit"]]
    features = extract_features(write_sample_dxf(str(tmp / "plan.dxf")),
                                layer_map["layers"], scale)
    build_ifc(features, layer_map, str(tmp / "model.ifc"))
    return str(tmp / "model.ifc")


@pytest.fixture
def model(sample_ifc):
    return ifcopenshell.open(sample_ifc)        # a fresh copy to break


def test_dxf2bim_output_conforms(model):
    for name in takeoff_ids.DOCUMENTS:
        failed = _check(model, name)
        assert failed and not any(failed.values()), failed


def test_family_output_conforms(tmp_path):
    from bimforge.author.families.registry import build_from_spec
    examples = files("bimforge.author") / "examples"
    for name in ("demo-box.spec.yaml", "demo-box.paycodes.yaml"):
        (tmp_path / name).write_text((examples / name).read_text("utf-8"), "utf-8")
    spec = yaml.safe_load((tmp_path / "demo-box.spec.yaml").read_text("utf-8"))
    assert build_from_spec(str(tmp_path / "demo-box.spec.yaml")) == 0
    built = ifcopenshell.open(str(tmp_path / spec["outputs"]["ifc"]))
    for name in takeoff_ids.DOCUMENTS:
        failed = _check(built, name)
        assert failed and not any(failed.values()), failed


def test_a_classified_element_without_quantities_fails(model):
    wall = model.by_type("IfcWall")[0]
    for qto in quantity_sets(wall):
        qto.Quantities = [model.create_entity(
            "IfcQuantityLength", Name="Thickness", LengthValue=0.2)]
    failed = _check(model, "takeoff.ids")
    assert failed["Classified elements carry a quantity to measure"] == [wall]


def test_a_quantity_of_the_wrong_dimension_fails(model):
    slab = model.by_type("IfcSlab")[0]
    qto = quantity_sets(slab)[0]
    qto.Quantities = [q for q in qto.Quantities if q.Name != "GrossArea"] + [
        model.create_entity("IfcQuantityLength", Name="GrossArea", LengthValue=3.0)]
    failed = _check(model, "takeoff.ids")
    assert failed["Quantities are stored as their own dimension"] == [slab]


def test_a_reference_without_a_code_fails(model):
    ref = model.by_type("IfcClassificationReference")[0]
    ref.Identification = None
    failed = _check(model, "takeoff.ids")
    assert failed["Classification references carry a code"] == [ref]


def test_an_unclassified_measured_element_fails_coverage_only(model):
    wall = model.by_type("IfcWall")[0]
    for rel in list(wall.HasAssociations):
        if rel.is_a("IfcRelAssociatesClassification"):
            model.remove(rel)
    assert _check(model, "takeoff-coverage.ids") == {
        "Measured elements are classified": [wall]}
    assert not any(_check(model, "takeoff.ids").values())
