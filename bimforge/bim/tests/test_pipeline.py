"""End-to-end tests: sample DXF -> IFC (typed + Qto + classification) ->
CanonicalTakeoff -> loads into the takeoff module's model."""
from __future__ import annotations

import json
from importlib.resources import files

import pytest

ezdxf = pytest.importorskip("ezdxf")
shapely = pytest.importorskip("shapely")
ifcopenshell = pytest.importorskip("ifcopenshell")
yaml = pytest.importorskip("yaml")

from bimforge.bim.dxf2bim import UNIT_TO_M, build_ifc, extract_features  # noqa: E402
from bimforge.bim.ifc_takeoff import (  # noqa: E402
    build_takeoff, classification_of, quantities_of,
)
from bimforge.bim.sample import write_sample_dxf  # noqa: E402


def _example(name: str) -> dict:
    text = (files("bimforge.bim") / "examples" / name).read_text(encoding="utf-8")
    return yaml.safe_load(text)


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory):
    """Run the whole pipeline once: sample DXF -> model.ifc -> takeoff dict."""
    tmp = tmp_path_factory.mktemp("bim")
    dxf_path = write_sample_dxf(str(tmp / "sample_plan.dxf"))

    layer_map = _example("layer_map.example.yaml")
    scale = UNIT_TO_M[layer_map["units"]["dxf_length_unit"]]
    features = extract_features(dxf_path, layer_map["layers"], scale)
    ifc_path = str(tmp / "model.ifc")
    build_ifc(features, layer_map, ifc_path)

    takeoff_map = _example("takeoff_map.example.yaml")
    takeoff_map["organization_id"] = 1
    takeoff, warnings = build_takeoff(ifc_path, takeoff_map)
    return {
        "features": features,
        "model": ifcopenshell.open(ifc_path),
        "ifc_path": ifc_path,
        "takeoff": takeoff,
        "warnings": warnings,
    }


def test_sample_dxf_extracts_all_layers(pipeline):
    layers = {f.layer for f in pipeline["features"]}
    assert layers == {"A-SLAB", "A-WALL", "C-CURB", "A-HATCH", "E-COL"}
    # 1 slab + 1 wall + 1 curb + 1 hatch + 4 columns
    assert len(pipeline["features"]) == 8


def test_ifc_has_expected_typed_elements(pipeline):
    model = pipeline["model"]
    assert len(model.by_type("IfcSlab")) == 1
    assert len(model.by_type("IfcWall")) == 1
    assert len(model.by_type("IfcCovering")) == 1
    assert len(model.by_type("IfcColumn")) == 4
    assert len(model.by_type("IfcBuildingElementProxy")) == 1
    assert len(model.by_type("IfcElement")) == 8


def test_ifc_elements_have_object_placement(pipeline):
    """IfcProduct.PlacementForShapeRepresentation (express rule): a product
    with a shape representation must have an ObjectPlacement. The sample
    layer_map sets no base_elevation for any layer (all default to 0.0/falsy),
    so this specifically covers the zero-elevation identity-placement path."""
    model = pipeline["model"]
    for element in model.by_type("IfcElement"):
        assert element.ObjectPlacement is not None
        assert element.ObjectPlacement.is_a("IfcLocalPlacement")


def test_ifc_elements_carry_qto_quantities(pipeline):
    model = pipeline["model"]
    slab = model.by_type("IfcSlab")[0]
    q = quantities_of(slab)
    assert q["GrossArea"] == pytest.approx(60.0, rel=1e-6)      # 10m x 6m
    assert q["GrossVolume"] == pytest.approx(12.0, rel=1e-6)    # x 0.2m thick
    assert q["Perimeter"] == pytest.approx(32.0, rel=1e-6)

    wall = model.by_type("IfcWall")[0]
    q = quantities_of(wall)
    assert q["Length"] == pytest.approx(16.0, rel=1e-6)         # 10m + 6m L-run
    assert q["GrossVolume"] == pytest.approx(9.6, rel=1e-6)     # 16 x 0.2 x 3.0

    for col in model.by_type("IfcColumn"):
        assert quantities_of(col)["Count"] == 1.0


def test_ifc_elements_carry_classification(pipeline):
    model = pipeline["model"]
    slab_cls = classification_of(model.by_type("IfcSlab")[0])
    assert slab_cls == {"system": "MasterFormat", "code": "03 30 00",
                        "name": "Cast-in-Place Concrete"}
    wall_cls = classification_of(model.by_type("IfcWall")[0])
    assert wall_cls["code"] == "EF_25_10"


def test_takeoff_rows_and_units(pipeline):
    takeoff = pipeline["takeoff"]
    rows = {r["cost_code"]: r for r in takeoff["rows"]}
    assert set(rows) == {"03 30 00", "05 12 00", "32 16 13", "EF_25_10", "EF_25_30"}

    assert rows["03 30 00"]["unit"] == "CY"
    assert rows["03 30 00"]["quantity"] == pytest.approx(12.0 * 1.30795061931, abs=1e-3)
    assert rows["05 12 00"]["unit"] == "EA"
    assert rows["05 12 00"]["quantity"] == 4
    assert rows["32 16 13"]["unit"] == "LF"
    assert rows["32 16 13"]["quantity"] == pytest.approx(10.0 * 3.28083989501, abs=1e-3)
    assert rows["EF_25_10"]["quantity"] == pytest.approx(9.6 * 1.30795061931, abs=1e-3)
    assert rows["EF_25_30"]["unit"] == "SF"
    assert rows["EF_25_30"]["quantity"] == pytest.approx(6.0 * 10.76391041671, abs=1e-3)

    for r in takeoff["rows"]:
        assert r["kind"] == "quantity"
        assert r["item_number"]
        assert r["schedule"] == "A"
    # every element is classified in the sample, so nothing falls back
    assert not any("no map entry" in w for w in pipeline["warnings"])


def test_takeoff_rows_carry_element_breakdowns(pipeline):
    """Each row's `elements` mirror the IFC elements behind the summed quantity:
    a BM section_type per element and dimensions in FEET from the Qto values."""
    rows = {r["cost_code"]: r for r in pipeline["takeoff"]["rows"]}
    M_TO_FT = 3.28083989501

    slab = rows["03 30 00"]["elements"]
    assert len(slab) == 1 and slab[0]["section_type"] == "decks"
    assert slab[0]["count"] == 1
    # area feature: Width holds the slab thickness (0.2 m); no Length/Height Qto
    assert slab[0]["width_ft"] == pytest.approx(0.2 * M_TO_FT, abs=1e-3)
    assert slab[0]["length_ft"] is None and slab[0]["height_ft"] is None

    wall = rows["EF_25_10"]["elements"]
    assert len(wall) == 1 and wall[0]["section_type"] == "walls"
    assert wall[0]["length_ft"] == pytest.approx(16.0 * M_TO_FT, abs=1e-3)
    assert wall[0]["width_ft"] == pytest.approx(0.2 * M_TO_FT, abs=1e-3)
    assert wall[0]["height_ft"] == pytest.approx(3.0 * M_TO_FT, abs=1e-3)

    cols = rows["05 12 00"]["elements"]
    assert len(cols) == 4
    assert all(c["section_type"] == "column" and c["count"] == 1 for c in cols)


def test_takeoff_loads_into_canonical_takeoff_model(pipeline):
    """CRITICAL contract check: the bim output IS the takeoff module's shape.

    Consumer-side: skipped in a standalone bimforge checkout (the estimating
    layer is not installed there); the monorepo always runs it."""
    pytest.importorskip("estimating_tools")
    from estimating_tools.takeoff.model import CanonicalTakeoff
    from estimating_tools.takeoff.push import plan_takeoff_push

    loaded = CanonicalTakeoff.from_json(json.dumps(pipeline["takeoff"]))
    assert loaded.organization_id == 1
    assert loaded.project_ref == "sample-job"
    assert len(loaded.rows) == 5
    assert all(row.kind == "quantity" for row in loaded.rows)
    assert all(row.elements for row in loaded.rows)

    # default target: estimate structures. Only structural SOLIDS become
    # sections (issue #215): the fixture's two GrossVolume rows plan sections;
    # its Count / Length / GrossArea rows ride the advisory check as pay-only.
    # The structure id falls back to the takeoff's project_ref.
    plan = plan_takeoff_push(loaded)
    assert len(plan.structure_plans) == 2
    assert all(sp["structure_id"] == "sample-job" for sp in plan.structure_plans)
    assert len(plan.advisory_quantity_check) == 5   # every quantity row, still
    assert not plan.unresolved and not plan.unsupported

    # legacy target (forbidden on live bids; BM #984) still plans creates
    legacy = plan_takeoff_push(loaded, existing_bid_items=[],
                               target="bid-item-quantities")
    assert len(legacy.quantity_creates) == 5
    assert not legacy.unresolved and not legacy.unsupported
    assert "OFFICIAL" in legacy.WARNING


def test_cli_end_to_end(tmp_path):
    from bimforge.bim import cli

    assert cli.main(["sample", "--dir", str(tmp_path), "--with-configs"]) == 0
    dxf = tmp_path / "sample_plan.dxf"
    layer_map = tmp_path / "layer_map.example.yaml"
    takeoff_map = tmp_path / "takeoff_map.example.yaml"
    assert dxf.is_file() and layer_map.is_file() and takeoff_map.is_file()

    ifc = tmp_path / "model.ifc"
    assert cli.main(["dxf2bim", "--dxf", str(dxf), "--config", str(layer_map),
                     "--out", str(ifc)]) == 0
    assert ifc.is_file()

    out = tmp_path / "takeoff.json"
    csv_out = tmp_path / "takeoff.csv"
    assert cli.main(["takeoff", "--ifc", str(ifc), "--map", str(takeoff_map),
                     "--out", str(out), "--csv", str(csv_out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["project_ref"] == "sample-job"
    assert len(data["rows"]) == 5
    assert csv_out.read_text(encoding="utf-8").count("\n") == 6  # header + 5 rows


# ----------------------------------------------------------------------------
# measures: plural — one classification code paying multiple bid items (EP-10)
# ----------------------------------------------------------------------------

def _multi_measure_map():
    return {
        "organization_id": 1,
        "defaults": {"schedule": "A"},
        "codes": {
            "32 16 13": {"measures": [
                {"measure": "Length", "unit": "LF", "item_number": "0030"},
                {"measure": "GrossVolume", "unit": "CY", "item_number": "0031",
                 "description": "Curb concrete", "schedule": "B"},
            ]},
        },
    }


@pytest.fixture(scope="module")
def multi_measure(pipeline, tmp_path_factory):
    # Reuse the pipeline's IFC; only the map differs.
    ifc_path = pipeline["ifc_path"]
    return build_takeoff(ifc_path, _multi_measure_map())


def test_measures_plural_emits_one_row_per_entry(multi_measure):
    takeoff, _ = multi_measure
    curb_rows = [r for r in takeoff["rows"] if r["cost_code"] == "32 16 13"]
    assert len(curb_rows) == 2
    by_item = {r["item_number"]: r for r in curb_rows}
    lf, cy = by_item["0030"], by_item["0031"]
    assert lf["unit"] == "LF"
    assert lf["quantity"] == pytest.approx(10.0 * 3.28083989501, abs=1e-3)
    assert cy["unit"] == "CY"
    # linear ribbon volume: 10.0 m x 0.3 m wide x 0.15 m high
    assert cy["quantity"] == pytest.approx(10.0 * 0.3 * 0.15 * 1.30795061931,
                                           abs=1e-3)
    # per-entry overrides land; unset fields inherit
    assert cy["description"] == "Curb concrete"
    assert cy["schedule"] == "B"
    assert lf["schedule"] == "A"                  # defaults.schedule
    # both rows describe the same element set
    assert len(lf["elements"]) == len(cy["elements"]) == 1
    assert lf["elements"][0]["section_type"] == cy["elements"][0]["section_type"]


def test_measures_entry_without_matching_quantity_warns_and_emits_no_row(pipeline):
    ifc_path = pipeline["ifc_path"]
    tmap = {"codes": {"32 16 13": {"measures": [
        {"measure": "Count", "unit": "EA", "item_number": "0032"}]}}}
    takeoff, warnings = build_takeoff(ifc_path, tmap)
    assert not [r for r in takeoff["rows"] if r["cost_code"] == "32 16 13"]
    assert any("lacks Count" in w and "32 16 13" in w for w in warnings)


def test_measure_and_measures_together_is_an_error(pipeline):
    ifc_path = pipeline["ifc_path"]
    tmap = {"codes": {"32 16 13": {"measure": "Length",
                                   "measures": [{"measure": "Length"}]}}}
    with pytest.raises(ValueError, match="either 'measure' or 'measures'"):
        build_takeoff(ifc_path, tmap)


def test_empty_or_invalid_measures_is_an_error(pipeline):
    ifc_path = pipeline["ifc_path"]
    with pytest.raises(ValueError, match="non-empty list"):
        build_takeoff(ifc_path, {"codes": {"32 16 13": {"measures": []}}})
    with pytest.raises(ValueError, match="must set 'measure'"):
        build_takeoff(ifc_path, {"codes": {"32 16 13": {"measures": [{"unit": "LF"}]}}})
    with pytest.raises(ValueError, match="unknown measure"):
        build_takeoff(ifc_path, {"codes": {"32 16 13": {"measures": [
            {"measure": "Girth"}]}}})


def test_singular_map_behavior_is_unchanged(pipeline, multi_measure):
    # The example (singular) map's curb row still matches the plural map's
    # Length entry — back-compat is byte-level on quantities.
    singular = {r["cost_code"]: r for r in pipeline["takeoff"]["rows"]}
    takeoff, _ = multi_measure
    lf = [r for r in takeoff["rows"]
          if r["cost_code"] == "32 16 13" and r["unit"] == "LF"][0]
    assert singular["32 16 13"]["quantity"] == lf["quantity"]


def test_non_mapping_code_entry_is_a_clean_error(pipeline):
    ifc_path = pipeline["ifc_path"]
    with pytest.raises(ValueError, match="must be a mapping"):
        build_takeoff(ifc_path, {"codes": {"32 16 13": "GrossVolume"}})
    with pytest.raises(ValueError, match="'codes' must be a mapping"):
        build_takeoff(ifc_path, {"codes": ["32 16 13"]})
    # a null entry (bare "code:" line in YAML) means "no overrides" — allowed
    takeoff, _ = build_takeoff(ifc_path, {"codes": {"32 16 13": None}})
    assert [r for r in takeoff["rows"] if r["cost_code"] == "32 16 13"]
