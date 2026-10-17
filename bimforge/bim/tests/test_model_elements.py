"""model_elements: IFC elements -> BidSheet.ai upsert_modelled_elements entries."""
import json

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

import ifcopenshell.api.classification  # noqa: E402
import ifcopenshell.api.pset  # noqa: E402
import ifcopenshell.api.root  # noqa: E402
import ifcopenshell.api.unit  # noqa: E402

from bimforge.bim import cli  # noqa: E402
from bimforge.bim.model_elements import (  # noqa: E402
    CY_M3, SF_M2, item_index, plan_modelled_elements,
)


def _file(schema="IFC4", metres=True):
    f = ifcopenshell.file(schema=schema)
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="p")
    if metres:
        m = ifcopenshell.api.unit.add_si_unit(f, unit_type="LENGTHUNIT")
        ifcopenshell.api.unit.assign_unit(f, units=[m])
    else:
        ifcopenshell.api.unit.assign_unit(f)          # default: millimetres
    return f


def _element(f, cls, name, qto, values, codes=()):
    el = ifcopenshell.api.root.create_entity(f, ifc_class=cls, name=name)
    if qto:
        q = ifcopenshell.api.pset.add_qto(f, product=el, name=qto)
        ifcopenshell.api.pset.edit_qto(f, qto=q, properties=values)
    if codes:
        system = (f.by_type("IfcClassification") or [
            ifcopenshell.api.classification.add_classification(
                f, classification="BidSchedule")])[0]
        for code in codes:
            ifcopenshell.api.classification.add_reference(
                f, products=[el], identification=code, name=code,
                classification=system)
    return el


def _by_name(plan):
    return {e["name"]: e for e in plan["elements"]}


def test_footing_net_volume_converts_m3_to_cy_with_unit_and_source():
    f = _file()
    ftg = _element(f, "IfcFooting", "F-1", "Qto_FootingBaseQuantities",
                   {"NetVolume": 10.0, "GrossVolume": 11.0})
    plan = plan_modelled_elements(f)
    (entry,) = plan["elements"]
    assert entry["global_id"] == ftg.GlobalId
    assert entry["ifc_class"] == "IfcFooting"
    assert entry["element_type"] == "footing"
    q = entry["quantities"]
    assert set(q) == {"concrete_cy"}          # no form area is ever guessed
    # NetVolume wins over GrossVolume; 10 m3 = 13.0795 CY
    assert q["concrete_cy"]["value"] == pytest.approx(10.0 / CY_M3, abs=1e-4)
    assert q["concrete_cy"]["value"] == pytest.approx(13.0795, abs=1e-4)
    assert q["concrete_cy"]["unit"] == "CY"
    assert q["concrete_cy"]["source"] == "Qto_FootingBaseQuantities.NetVolume"
    assert "structure_id" not in entry and "pay_items" not in entry


def _imperial(f, *names):
    """Conversion-based units with EXACT factors. ifcopenshell's own table
    rounds some (its cubic yard is 0.7636 m3, the yard 0.914 m); a correct
    exporter writes the exact ones, and the reader takes whatever the file
    says."""
    exact = {"foot": 0.3048, "square foot": 0.09290304,
             "cubic foot": 0.3048 ** 3, "cubic yard": 0.764554857984}
    units = []
    for name in names:
        u = ifcopenshell.api.unit.add_conversion_based_unit(f, name=name)
        u.ConversionFactor.ValueComponent = f.create_entity(
            u.ConversionFactor.ValueComponent.is_a(), exact[name])
        units.append(u)
    return units


def _units_file(units):
    f = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="p")
    ifcopenshell.api.unit.assign_unit(f, units=units(f))
    return f


def test_mm_length_with_m2_m3_reads_volume_in_its_own_unit():
    # ifcopenshell's default assignment -- and a Revit metric export -- is
    # mm length but m2 / m3: 10 is 10 m3, never 10 mm-cubed-from-length
    f = _file(metres=False)
    _element(f, "IfcFooting", "F-1", "Qto_FootingBaseQuantities",
             {"NetVolume": 10.0})
    plan = plan_modelled_elements(f)
    (entry,) = plan["elements"]
    assert entry["quantities"]["concrete_cy"]["value"] == \
        pytest.approx(13.0795, abs=1e-4)
    assert plan["warnings"] == []


def test_feet_with_cubic_yards():
    f = _units_file(lambda f: _imperial(f, "foot", "cubic yard"))
    _element(f, "IfcFooting", "F-1", "Qto_FootingBaseQuantities",
             {"NetVolume": 1.0})
    (entry,) = plan_modelled_elements(f)["elements"]
    assert entry["quantities"]["concrete_cy"]["value"] == 1.0


def test_pure_feet_square_feet_cubic_feet():
    f = _units_file(lambda f: _imperial(f, "foot", "square foot",
                                        "cubic foot"))
    _element(f, "IfcWall", "W-1", "Qto_WallBaseQuantities",
             {"NetVolume": 27.0, "NetSideArea": 100.0})
    (entry,) = plan_modelled_elements(
        f, form_area="NetSideArea")["elements"]
    assert entry["quantities"]["concrete_cy"]["value"] == 1.0
    assert entry["quantities"]["form_contact_sf"]["value"] == 100.0


def test_a_quantity_with_its_own_unit_overrides_the_project_unit():
    f = _file()                                   # project: metres, m3
    ftg = _element(f, "IfcFooting", "F-1", "Qto_FootingBaseQuantities",
                   {"NetVolume": 27.0})
    (cf,) = _imperial(f, "cubic foot")
    (q,) = [q for rel in ftg.IsDefinedBy
            for q in rel.RelatingPropertyDefinition.Quantities]
    q.Unit = cf                                   # 27 ft3, whatever the project
    (entry,) = plan_modelled_elements(f)["elements"]
    assert entry["quantities"]["concrete_cy"]["value"] == 1.0


def test_undeclared_volume_falls_back_to_length_cubed_and_warns_on_zero():
    f = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="p")
    mm = ifcopenshell.api.unit.add_si_unit(f, unit_type="LENGTHUNIT",
                                           prefix="MILLI")
    ifcopenshell.api.unit.assign_unit(f, units=[mm])   # no VOLUMEUNIT
    _element(f, "IfcFooting", "F-1", "Qto_FootingBaseQuantities",
             {"NetVolume": 100.0})                       # 100 mm3
    plan = plan_modelled_elements(f)
    (entry,) = plan["elements"]
    assert entry["quantities"]["concrete_cy"]["value"] == 0.0
    assert any("rounds to 0" in w and "F-1" in w for w in plan["warnings"])


def test_earthworks_cut_and_fill_map_to_excavation_and_backfill():
    f = _file(schema="IFC4X3_ADD2")
    _element(f, "IfcEarthworksCut", "Cut", "Qto_EarthworksCutBaseQuantities",
             {"UndisturbedVolume": 76.4554857984, "LooseVolume": 99.0})
    _element(f, "IfcEarthworksFill", "Fill",
             "Qto_EarthworksFillBaseQuantities",
             {"CompactedVolume": 7.64554857984, "LooseVolume": 9.0})
    els = _by_name(plan_modelled_elements(f))
    cut, fill = els["Cut"], els["Fill"]
    assert cut["element_type"] == "excavation"
    assert fill["element_type"] == "backfill"
    assert set(cut["quantities"]) == {"excavation_cy"}
    assert set(fill["quantities"]) == {"backfill_cy"}
    # the in-place volume, never the loose (swelled) one
    assert cut["quantities"]["excavation_cy"] == {
        "value": 100.0, "unit": "CY",
        "source": "Qto_EarthworksCutBaseQuantities.UndisturbedVolume"}
    assert fill["quantities"]["backfill_cy"] == {
        "value": 10.0, "unit": "CY",
        "source": "Qto_EarthworksFillBaseQuantities.CompactedVolume"}


def test_wall_subtype_reads_as_wall_and_pile_carries_length():
    f = _file()
    _element(f, "IfcWallStandardCase", "W-1", "Qto_WallBaseQuantities",
             {"NetVolume": 1.0, "NetSideArea": 20.0})
    _element(f, "IfcPile", "P-1", "Qto_PileBaseQuantities",
             {"Length": 30.48, "NetVolume": 2.0})
    els = _by_name(plan_modelled_elements(f))
    assert els["W-1"]["element_type"] == "wall"
    # a wall's side area is one face, not the formed area: not sent
    assert set(els["W-1"]["quantities"]) == {"concrete_cy"}
    assert els["P-1"]["element_type"] == "pile"
    assert els["P-1"]["quantities"]["pile_lf"] == {
        "value": 100.0, "unit": "LF", "source": "Qto_PileBaseQuantities.Length"}


def test_form_area_only_when_named_and_only_for_concrete():
    f = _file(schema="IFC4X3_ADD2")
    _element(f, "IfcWall", "W-1", "Qto_WallBaseQuantities",
             {"NetVolume": 1.0, "NetSideArea": 9.290304})
    _element(f, "IfcEarthworksCut", "Cut", "Qto_EarthworksCutBaseQuantities",
             {"UndisturbedVolume": 1.0})
    plan = plan_modelled_elements(f, form_area="Qto_WallBaseQuantities.NetSideArea")
    els = _by_name(plan)
    assert els["W-1"]["quantities"]["form_contact_sf"] == {
        "value": pytest.approx(9.290304 / SF_M2), "unit": "SFCA",
        "source": "Qto_WallBaseQuantities.NetSideArea"}
    assert "form_contact_sf" not in els["Cut"]["quantities"]


def test_pay_items_by_classification_code():
    f = _file()
    _element(f, "IfcFooting", "F-1", "Qto_FootingBaseQuantities",
             {"NetVolume": 1.0}, codes=["51-CONC"])
    _element(f, "IfcFooting", "F-2", "Qto_FootingBaseQuantities",
             {"NetVolume": 1.0}, codes=["99-NONE"])
    plan = plan_modelled_elements(f, {"51-CONC": 701})
    els = _by_name(plan)
    assert els["F-1"]["pay_items"] == {"concrete_cy": 701}
    assert "pay_items" not in els["F-2"]
    assert any("99-NONE" in w for w in plan["warnings"])


def test_pay_items_from_model_items_match_the_item_unit():
    # furnish (LF) and drive (EA) off one pile: LF pays pile_lf, EA pays
    # nothing measurable here and is warned, never forced onto a key
    f = _file()
    _element(f, "IfcPile", "P-1", "Qto_PileBaseQuantities",
             {"Length": 10.0, "NetVolume": 1.0}, codes=["FRN", "DRV"])
    model = {"items": [
        {"id": 11, "item_number": "55", "item_code": "FRN", "unit": "LF"},
        {"id": 12, "item_number": "56", "item_code": "DRV", "unit": "EA"}]}
    plan = plan_modelled_elements(f, model)
    (entry,) = plan["elements"]
    assert entry["pay_items"] == {"pile_lf": 11}
    assert any("DRV" in w and "EA" in w for w in plan["warnings"])


def test_ambiguous_item_code_maps_to_no_item_unless_scheduled():
    f = _file()
    _element(f, "IfcFooting", "F-1", "Qto_FootingBaseQuantities",
             {"NetVolume": 1.0}, codes=["51"])
    model = {"items": [
        {"id": 1, "item_number": "10", "item_code": "51", "unit": "CY",
         "schedule": "A"},
        {"id": 2, "item_number": "10", "item_code": "51", "unit": "CY",
         "schedule": "B"}]}
    plan = plan_modelled_elements(f, model)
    assert "pay_items" not in plan["elements"][0]
    assert any("51" in w and "several" in w for w in plan["warnings"])
    assert item_index(model) == {}            # neither the code nor "10"
    plan = plan_modelled_elements(f, model, schedule="B")
    assert plan["elements"][0]["pay_items"] == {"concrete_cy": 2}


def test_item_index_falls_back_to_unique_item_number():
    idx = item_index({"items": [
        {"id": 1, "item_number": "10", "item_code": "", "unit": "CY"},
        {"id": 2, "item_number": "20", "item_code": "10", "unit": "CY"}]})
    # "10" is item 2's code; the number "10" never steals it
    assert idx["10"]["id"] == 2
    assert idx["20"]["id"] == 2
    with pytest.raises(ValueError):
        item_index({"X": "seven"})


def test_element_without_volume_is_sent_empty_to_clear_stale_values():
    # a re-export that lost the Qto must clear what an earlier import
    # stored, so the element goes with quantities {} -- never skipped
    f = _file()
    slab = _element(f, "IfcSlab", "S-1", "Qto_SlabBaseQuantities",
                    {"NetArea": 50.0}, codes=["51"])
    _element(f, "IfcColumn", "C-1", None, {})
    plan = plan_modelled_elements(f, {"51": 4})
    els = _by_name(plan)
    assert els["S-1"]["quantities"] == {} and els["C-1"]["quantities"] == {}
    assert "pay_items" not in els["S-1"]           # nothing to pay
    assert plan["skipped"] == []
    assert {w["global_id"] for w in plan["without_quantities"]} == {
        slab.GlobalId, els["C-1"]["global_id"]}
    assert any("no quantities" in w for w in plan["warnings"])


class _Quantity:
    """A stand-in IfcQuantityVolume: ifcopenshell itself refuses to hold a
    NaN, but a reader or a future parser could still hand one over."""
    Unit = None

    def __init__(self, name, value):
        self.Name, self.value = name, value

    def is_a(self, cls=None):
        return "IfcQuantityVolume" if cls is None else             cls in ("IfcQuantityVolume", "IfcPhysicalSimpleQuantity")

    def __getitem__(self, i):
        assert i == 3
        return self.value


class _Qto:
    Name = "Qto_FootingBaseQuantities"

    def __init__(self, value):
        self.Quantities = [_Quantity("NetVolume", value)]


def test_non_finite_quantity_skips_the_element(monkeypatch):
    from bimforge.bim import model_elements
    f = _file()
    bad = {_element(f, "IfcFooting", "F-1", None, {}).id(): float("nan"),
           _element(f, "IfcFooting", "F-2", None, {}).id(): float("inf")}
    monkeypatch.setattr(model_elements, "quantity_sets",
                        lambda el: [_Qto(bad[el.id()])])
    plan = plan_modelled_elements(f)
    assert plan["elements"] == []
    assert len(plan["skipped"]) == 2
    assert all("non-finite" in s["reason"] for s in plan["skipped"])


def test_invalid_and_duplicate_global_ids_are_skipped_first_kept():
    f = _file()
    a = _element(f, "IfcFooting", "A", "Qto_FootingBaseQuantities",
                 {"NetVolume": 1.0})
    b = _element(f, "IfcFooting", "B", "Qto_FootingBaseQuantities",
                 {"NetVolume": 1.0})
    c = _element(f, "IfcFooting", "C", "Qto_FootingBaseQuantities",
                 {"NetVolume": 1.0})
    b.GlobalId = a.GlobalId                       # a broken export
    c.GlobalId = "4" + a.GlobalId[1:]             # first char above 3
    plan = plan_modelled_elements(f)
    assert [e["name"] for e in plan["elements"]] == ["A"]
    reasons = {s["name"]: s["reason"] for s in plan["skipped"]}
    assert "repeats 'A'" in reasons["B"] and "first" in reasons["B"]
    assert "not a 22-character IFC GlobalId" in reasons["C"]


def test_blank_name_falls_back_to_class_and_global_id_tail():
    f = _file()
    el = _element(f, "IfcFooting", "   ", "Qto_FootingBaseQuantities",
                  {"NetVolume": 1.0})
    (entry,) = plan_modelled_elements(f)["elements"]
    assert entry["name"] == f"IfcFooting-{el.GlobalId[-6:]}"


def test_only_typed_or_classified_elements_by_default():
    f = _file()
    _element(f, "IfcBuildingElementProxy", "loose", None, {})
    _element(f, "IfcBuildingElementProxy", "curb", None, {}, codes=["51"])
    _element(f, "IfcBeam", "girder", None, {}, codes=["51"])
    _element(f, "IfcReinforcingBar", "bar", None, {}, codes=["52"])
    _element(f, "IfcGeographicElement", "ground", None, {})
    _element(f, "IfcBuildingElementProxy", "Terrain mesh", None, {})
    plan = plan_modelled_elements(f)
    assert [e["name"] for e in plan["elements"]] == ["curb"]
    reasons = {s["name"]: s["reason"] for s in plan["skipped"]}
    assert set(reasons) == {"loose", "girder", "bar", "ground",
                            "Terrain mesh"}
    assert "IfcBuildingElementProxy" in reasons["loose"]
    assert "IfcBeam" in reasons["girder"]
    assert "never sent" in reasons["bar"] and "never sent" in reasons["ground"]
    # opt in: the rest goes as generic; rebar and terrain still never do
    sent = _by_name(plan_modelled_elements(f, all_elements=True))
    assert set(sent) == {"loose", "curb", "girder"}
    assert sent["girder"]["element_type"] == "generic"


def test_an_assembly_and_its_parts_are_never_both_sent():
    import ifcopenshell.api.aggregate
    f = _file()
    asm = _element(f, "IfcElementAssembly", "Abutment", None, {},
                   codes=["51"])
    parts = [_element(f, "IfcFooting", f"F-{i}", "Qto_FootingBaseQuantities",
                      {"NetVolume": 1.0}) for i in (1, 2)]
    ifcopenshell.api.aggregate.assign_object(f, products=parts,
                                             relating_object=asm)
    plan = plan_modelled_elements(f)
    assert sorted(e["name"] for e in plan["elements"]) == ["F-1", "F-2"]
    (s,) = plan["skipped"]
    assert s["name"] == "Abutment" and "parts" in s["reason"]


def test_openings_are_not_elements():
    f = _file()
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcOpeningElement",
                                        name="hole")
    plan = plan_modelled_elements(f)
    assert plan["elements"] == [] and plan["skipped"] == []


def test_structure_ids_per_code_and_default():
    f = _file()
    _element(f, "IfcFooting", "F-1", "Qto_FootingBaseQuantities",
             {"NetVolume": 1.0}, codes=["A"])
    _element(f, "IfcFooting", "F-2", "Qto_FootingBaseQuantities",
             {"NetVolume": 1.0}, codes=["B"])
    els = _by_name(plan_modelled_elements(f, structure_id="BR-1",
                                          structure_ids={"A": "ABUT-1"}))
    assert els["F-1"]["structure_id"] == "ABUT-1"
    assert els["F-2"]["structure_id"] == "BR-1"


def test_cli_model_elements_writes_the_payload(tmp_path, capsys):
    f = _file()
    _element(f, "IfcFooting", "F-1", "Qto_FootingBaseQuantities",
             {"NetVolume": 1.0}, codes=["51"])
    ifc = tmp_path / "m.ifc"
    f.write(str(ifc))
    items = tmp_path / "items.json"
    items.write_text(json.dumps({"51": 9}), encoding="utf-8")
    out = tmp_path / "upsert.json"
    rc = cli.main(["model-elements", str(ifc), "--items", str(items),
                   "--estimate-id", "76", "--complete", "--out", str(out)])
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["estimate_id"] == 76 and payload["complete"] is True
    (entry,) = payload["elements"]
    assert entry["pay_items"] == {"concrete_cy": 9}
    # stdout mode: the JSON alone
    rc = cli.main(["model-elements", str(ifc)])
    assert rc == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["elements"][0]["global_id"] == entry["global_id"]


def test_cli_model_elements_reports_an_unreadable_ifc(tmp_path, capsys):
    bad = tmp_path / "bad.ifc"
    bad.write_text("not an ifc file", encoding="utf-8")
    assert cli.main(["model-elements", str(bad)]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: ") and "Traceback" not in err
