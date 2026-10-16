"""estimate5d: quantity-backed ESTIMATE cost schedule (spec 2026-08-12)."""
import ifcopenshell
import ifcopenshell.api.classification
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.unit
import pytest

from bimforge.bim import estimate5d

M_TO_LF = 3.28083989501


def _pile_ifc(codes=("PILE-200W-FRN",)):
    """One IfcPile, Length 12_500 native mm (= 12.5 m), Count 1, one
    classification reference per entry in `codes`."""
    f = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="p")
    ifcopenshell.api.unit.assign_unit(f)   # default: MILLIMETRES
    pile = ifcopenshell.api.root.create_entity(f, ifc_class="IfcPile",
                                               name="P-1")
    qto = ifcopenshell.api.pset.add_qto(f, product=pile,
                                        name="Qto_PileBaseQuantities")
    ifcopenshell.api.pset.edit_qto(f, qto=qto,
                                   properties={"Length": 12_500.0, "Count": 1})
    system = ifcopenshell.api.classification.add_classification(
        f, classification="BidSchedule")
    for code in codes:
        ifcopenshell.api.classification.add_reference(
            f, products=[pile], identification=code, name=code,
            classification=system)
    return f


PILE_MAP = {"project_ref": "B9", "codes": {
    "PILE-200W-FRN": {"measure": "Length", "unit": "LF",
                      "item_number": "0055"}}}
PILE_COSTS = {"PILE-200W-FRN": {"cost": 500.0, "labor_hours": None,
                                "unit_price": 10.0, "unit": "LF"}}


def _children(parent):
    return [o for rel in (parent.IsNestedBy or []) for o in rel.RelatedObjects
            if o.is_a("IfcCostItem")]


def test_embed_authors_estimate_schedule_with_shared_qto_entity():
    model = _pile_ifc()
    report = estimate5d.embed_estimate(model, PILE_MAP, PILE_COSTS)
    (cs,) = model.by_type("IfcCostSchedule")
    assert cs.PredefinedType == "ESTIMATE"
    assert cs.Name == "B9 estimate"          # "<project_ref> estimate"
    parents = [ci for rel in (cs.Controls or [])
               for ci in rel.RelatedObjects if ci.is_a("IfcCostItem")]
    (parent,) = parents
    assert parent.Identification == "PILE-200W-FRN"
    # the parent is VALUELESS — consumers sum the children
    assert not (parent.CostValues or [])
    (child,) = _children(parent)
    # THE headline property: the child's CostQuantities entry IS the pile's
    # own Qto member — one entity, shared by reference, not a copy.
    pile = model.by_type("IfcPile")[0]
    member = [q for rel in pile.IsDefinedBy
              if rel.is_a("IfcRelDefinesByProperties")
              and rel.RelatingPropertyDefinition.is_a("IfcElementQuantity")
              for q in rel.RelatingPropertyDefinition.Quantities
              if q.Name == "Length"]
    assert len(member) == 1
    assert child.CostQuantities[0].id() == member[0].id()
    # editing the element's quantity IS editing the cost item's quantity
    member[0].LengthValue = 13_000.0
    assert child.CostQuantities[0].LengthValue == 13_000.0
    # the element is control-linked (assign_cost_item_quantity authors it)
    assert any(r.is_a("IfcRelAssignsToControl")
               for r in (pile.HasAssignments or []))
    assert report.parents == 1 and report.children == 1


def test_rate_is_converted_to_per_raw_model_unit():
    # $10/LF on a native-mm Length of 12_500 (12.5 m = 41.0105 LF):
    # AppliedValue x raw quantity must equal unit_price x pay quantity.
    model = _pile_ifc()
    report = estimate5d.embed_estimate(model, PILE_MAP, PILE_COSTS)
    (cs,) = model.by_type("IfcCostSchedule")
    (parent,) = [ci for rel in (cs.Controls or [])
                 for ci in rel.RelatedObjects if ci.is_a("IfcCostItem")]
    (child,) = _children(parent)
    applied = child.CostValues[0].AppliedValue.wrappedValue
    expected_total = 10.0 * 12.5 * M_TO_LF          # 410.105
    assert applied * 12_500.0 == pytest.approx(expected_total, rel=1e-9)
    assert report.extended_total == pytest.approx(expected_total, rel=1e-9)
    # variance vs the BM lump 500.0: (410.105 - 500) / 500
    v = report.by_code["PILE-200W-FRN"]
    assert v["extended"] == pytest.approx(expected_total, rel=1e-9)
    assert v["bm_cost"] == 500.0
    assert v["variance_pct"] == pytest.approx(
        (expected_total - 500.0) / 500.0 * 100.0, rel=1e-6)


def test_parent_gets_one_child_per_element():
    model = _pile_ifc()
    # a second pile with the same code — children must partition, one each
    p2 = ifcopenshell.api.root.create_entity(model, ifc_class="IfcPile",
                                             name="P-2")
    qto = ifcopenshell.api.pset.add_qto(model, product=p2,
                                        name="Qto_PileBaseQuantities")
    ifcopenshell.api.pset.edit_qto(model, qto=qto,
                                   properties={"Length": 6_250.0})
    system = model.by_type("IfcClassification")[0]
    ifcopenshell.api.classification.add_reference(
        model, products=[p2], identification="PILE-200W-FRN",
        name="", classification=system)
    report = estimate5d.embed_estimate(model, PILE_MAP, PILE_COSTS)
    (cs,) = model.by_type("IfcCostSchedule")
    (parent,) = [ci for rel in (cs.Controls or [])
                 for ci in rel.RelatedObjects if ci.is_a("IfcCostItem")]
    kids = _children(parent)
    assert len(kids) == 2
    # each quantity entity appears in exactly one child
    qids = [q.id() for k in kids for q in (k.CostQuantities or [])]
    assert len(qids) == len(set(qids)) == 2
    assert report.children == 2
    assert report.extended_total == pytest.approx(
        10.0 * (12.5 + 6.25) * M_TO_LF, rel=1e-9)


KG_TO_CWT = 0.0220462262185

PLURAL_MAP = {"project_ref": "B9", "codes": {
    "49-3020": {"measures": [
        {"measure": "Length", "unit": "LF", "item_number": "0055",
         "description": "Furnish CISS"},
        {"measure": "Count", "unit": "EA", "item_number": "0056",
         "description": "Drive CISS"}]}}}
PLURAL_COSTS = {"49-3020": {"cost": 1300.0, "labor_hours": None,
                            "unit_price": {"0055": 12.5, "0056": 800.0},
                            "unit": {"0055": "LF", "0056": "EA"}}}


def test_plural_measures_two_parents_same_elements():
    model = _pile_ifc(codes=("49-3020",))
    report = estimate5d.embed_estimate(model, PLURAL_MAP, PLURAL_COSTS)
    (cs,) = model.by_type("IfcCostSchedule")
    parents = [ci for rel in (cs.Controls or [])
               for ci in rel.RelatedObjects if ci.is_a("IfcCostItem")]
    assert len(parents) == 2                      # one per bid item
    by_name = {p.Name: _children(p)[0] for p in parents}
    lf_child = by_name["Furnish CISS"]
    ea_child = by_name["Drive CISS"]
    assert lf_child.CostQuantities[0].is_a("IfcQuantityLength")
    assert ea_child.CostQuantities[0].is_a("IfcQuantityCount")
    # extended: 12.5 $/LF x 41.0105 LF + 800 $/EA x 1 EA, aggregated per CODE
    expected = 12.5 * 12.5 * M_TO_LF + 800.0
    assert report.extended_total == pytest.approx(expected, rel=1e-9)
    assert report.by_code["49-3020"]["extended"] == pytest.approx(
        expected, rel=1e-9)
    assert report.by_code["49-3020"]["bm_cost"] == 1300.0


def test_plural_code_with_bare_number_rate_is_an_error():
    model = _pile_ifc(codes=("49-3020",))
    bad = {"49-3020": {"cost": 1.0, "unit_price": 12.5}}
    with pytest.raises(ValueError, match=r"keyed by item_number"):
        estimate5d.embed_estimate(model, PLURAL_MAP, bad)


def test_unit_cross_check_mismatch_is_an_error():
    model = _pile_ifc()
    bad = {"PILE-200W-FRN": {"cost": 1.0, "unit_price": 10.0, "unit": "CY"}}
    with pytest.raises(ValueError, match=r"contradicts"):
        estimate5d.embed_estimate(model, PILE_MAP, bad)


def _steel_gram_ifc():
    """IfcPlate, GrossWeight 96_000 native GRAMS (= 96 kg), code STL-FAB."""
    f = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="p")
    ifcopenshell.api.unit.assign_unit(f)   # mm defaults
    gram = f.create_entity("IfcSIUnit", UnitType="MASSUNIT", Name="GRAM")
    ua = f.by_type("IfcUnitAssignment")[0]
    ua.Units = tuple(ua.Units) + (gram,)
    plate = ifcopenshell.api.root.create_entity(f, ifc_class="IfcPlate",
                                                name="Saddle-1")
    qto = ifcopenshell.api.pset.add_qto(f, product=plate,
                                        name="Qto_PlateBaseQuantities")
    ifcopenshell.api.pset.edit_qto(f, qto=qto,
                                   properties={"GrossWeight": 96_000.0})
    system = ifcopenshell.api.classification.add_classification(
        f, classification="BidSchedule")
    ifcopenshell.api.classification.add_reference(
        f, products=[plate], identification="STL-FAB", name="Fab steel",
        classification=system)
    return f


def test_mass_rate_honors_declared_gram_unit():
    # $50/CWT on 96 kg (= 2.11644 CWT) authored as 96_000 g
    model = _steel_gram_ifc()
    tmap = {"codes": {"STL-FAB": {"measure": "GrossWeight", "unit": "CWT",
                                  "item_number": "0090"}}}
    costs = {"STL-FAB": {"cost": 100.0, "unit_price": 50.0, "unit": "CWT"}}
    report = estimate5d.embed_estimate(model, tmap, costs)
    expected = 50.0 * 96.0 * KG_TO_CWT            # 105.822
    assert report.extended_total == pytest.approx(expected, rel=1e-9)
    (cs,) = model.by_type("IfcCostSchedule")
    (parent,) = [ci for rel in (cs.Controls or [])
                 for ci in rel.RelatedObjects if ci.is_a("IfcCostItem")]
    (child,) = _children(parent)
    applied = child.CostValues[0].AppliedValue.wrappedValue
    assert applied * 96_000.0 == pytest.approx(expected, rel=1e-9)


def test_skips_are_reported_never_silent():
    model = _pile_ifc()
    tmap = {"project_ref": "B9", "codes": {
        "PILE-200W-FRN": {"measure": "Length", "unit": "LF",
                          "item_number": "0055"},
        "NO-RATE": {"measure": "Count", "unit": "EA"},
        "NO-MEASURE": {"unit": "EA"},
        "GHOST": {"measure": "Count", "unit": "EA"}}}
    costs = {"PILE-200W-FRN": {"cost": 500.0, "unit_price": 10.0},
             "NO-MEASURE": {"cost": 1.0, "unit_price": 5.0},
             "GHOST": {"cost": 1.0, "unit_price": 5.0}}
    report = estimate5d.embed_estimate(model, tmap, costs)
    assert report.codes_without_rate == ["NO-RATE"]
    assert report.codes_without_measure == ["NO-MEASURE"]
    assert report.codes_without_elements == ["GHOST"]
    assert list(report.by_code) == ["PILE-200W-FRN"]   # only the authored code


def test_element_lacking_the_measure_is_skipped_and_reported():
    model = _pile_ifc()
    # a second element with the code but NO Length quantity
    p2 = ifcopenshell.api.root.create_entity(model, ifc_class="IfcPile",
                                             name="P-noqty")
    system = model.by_type("IfcClassification")[0]
    ifcopenshell.api.classification.add_reference(
        model, products=[p2], identification="PILE-200W-FRN", name="",
        classification=system)
    report = estimate5d.embed_estimate(model, PILE_MAP, PILE_COSTS)
    assert report.children == 1
    assert ("P-noqty", "PILE-200W-FRN", "Length") \
        in report.elements_missing_measure


def test_type_level_qto_element_is_skipped_not_mispriced():
    # The pile's Length lives ONLY on its TYPE: quantities_of() inherits type
    # Qtos (get_psets should_inherit), but assign_cost_item_quantity walks the
    # occurrence's IsDefinedBy only — pricing it would author a child whose
    # AppliedValue has NO CostQuantities, which consumers read as a lump
    # total: a silent money error the report never shows.
    import ifcopenshell.api.type as tp
    f = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="p")
    ifcopenshell.api.unit.assign_unit(f)
    pile = ifcopenshell.api.root.create_entity(f, ifc_class="IfcPile",
                                               name="P-1")
    ptype = ifcopenshell.api.root.create_entity(f, ifc_class="IfcPileType",
                                                name="PT-200W")
    tp.assign_type(f, related_objects=[pile], relating_type=ptype)
    qto = ifcopenshell.api.pset.add_qto(f, product=ptype,
                                        name="Qto_PileBaseQuantities")
    ifcopenshell.api.pset.edit_qto(f, qto=qto,
                                   properties={"Length": 12_500.0})
    system = ifcopenshell.api.classification.add_classification(
        f, classification="BidSchedule")
    ifcopenshell.api.classification.add_reference(
        f, products=[pile], identification="PILE-200W-FRN", name="",
        classification=system)
    report = estimate5d.embed_estimate(f, PILE_MAP, PILE_COSTS)
    # never a priced item with empty CostQuantities anywhere in the file
    for ci in f.by_type("IfcCostItem"):
        if ci.CostValues:
            assert ci.CostQuantities
    assert report.children == 0 and report.parents == 0
    assert ("P-1", "PILE-200W-FRN", "Length") in report.elements_missing_measure
    assert report.codes_without_elements == ["PILE-200W-FRN"]
    assert "PILE-200W-FRN" not in report.by_code
    assert report.extended_total == 0.0


def test_unit_dict_missing_item_number_trusts_the_map():
    # unit is an optional CROSS-CHECK: a dict unit that lacks this entry's
    # item_number silently defers to the map's pay unit (contrast unit_price,
    # where the missing key raises — a price is required, corroboration not).
    model = _pile_ifc(codes=("49-3020",))
    costs = {"49-3020": {"cost": 1300.0,
                         "unit_price": {"0055": 12.5, "0056": 800.0},
                         "unit": {"0055": "LF"}}}          # no "0056" key
    report = estimate5d.embed_estimate(model, PLURAL_MAP, costs)
    expected = 12.5 * 12.5 * M_TO_LF + 800.0
    assert report.extended_total == pytest.approx(expected, rel=1e-9)


def test_rerun_is_idempotent_and_never_touches_element_qtos():
    model = _pile_ifc()
    for _ in range(3):
        estimate5d.embed_estimate(model, PILE_MAP, PILE_COSTS)
    assert len(model.by_type("IfcCostSchedule")) == 1
    assert len(model.by_type("IfcCostItem")) == 2      # parent + child
    assert len(model.by_type("IfcCostValue")) == 1     # child rate only
    # the pile's OWN quantity survived teardown untouched
    pile = model.by_type("IfcPile")[0]
    member = [q for rel in pile.IsDefinedBy
              if rel.is_a("IfcRelDefinesByProperties")
              and rel.RelatingPropertyDefinition.is_a("IfcElementQuantity")
              for q in rel.RelatingPropertyDefinition.Quantities]
    assert {q.Name for q in member} == {"Length", "Count"}
    assert [q.LengthValue for q in member if q.Name == "Length"] == [12_500.0]
    # no orphaned rels/classification accumulate (schedule->parent is itself
    # an IfcRelAssignsToControl per schema — cs.Controls above reads it)
    assert len(model.by_type("IfcRelAssignsToControl")) == 2  # cs->parent + child->pile
    assert len([r for r in model.by_type("IfcClassificationReference")
                if r.Identification == "PILE-200W-FRN"]) == 2  # element's + item's


def test_coexists_with_cost5d_budget_schedule():
    import ifcopenshell.api.sequence as sq
    from bimforge.bim import cost5d
    from bimforge.bim.schedule_model import (CanonicalSchedule,
                                                 ScheduleTask)
    model = _pile_ifc()
    ws = sq.add_work_schedule(model, name="S")
    sq.add_task(model, work_schedule=ws, name="Drive", identification="1")
    sched = CanonicalSchedule(
        name="S", work_weekdays=[0, 1, 2, 3, 4], holidays=[],
        tasks=[ScheduleTask(id="t1", name="Drive", wbs="1",
                            start="2026-08-10", finish="2026-08-14",
                            bid_item_codes=["PILE-200W-FRN"])])
    cost5d.embed_cost_and_resources(model, sched, PILE_COSTS)
    budget_items = len(model.by_type("IfcCostItem"))
    estimate5d.embed_estimate(model, PILE_MAP, PILE_COSTS)
    kinds = {cs.PredefinedType for cs in model.by_type("IfcCostSchedule")}
    assert kinds == {"BUDGET", "ESTIMATE"}
    # estimate5d added exactly its parent+child; BUDGET items untouched
    assert len(model.by_type("IfcCostItem")) == budget_items + 2
    # and a re-run of estimate5d must not disturb the BUDGET schedule
    estimate5d.embed_estimate(model, PILE_MAP, PILE_COSTS)
    assert len(model.by_type("IfcCostItem")) == budget_items + 2
    assert {cs.PredefinedType for cs in model.by_type("IfcCostSchedule")} \
        == {"BUDGET", "ESTIMATE"}
