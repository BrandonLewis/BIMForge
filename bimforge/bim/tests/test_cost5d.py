import ifcopenshell
import ifcopenshell.api.root as root
import ifcopenshell.api.sequence as sq
from bimforge.bim.schedule_model import CanonicalSchedule, ScheduleTask
from bimforge.bim import cost5d


def _ifc_with_task(ident):
    f = ifcopenshell.file(schema="IFC4")
    root.create_entity(f, ifc_class="IfcProject")
    ws = sq.add_work_schedule(f, name="S")
    sq.add_task(f, work_schedule=ws, name="Pour", identification=ident)
    return f


def _sched():
    return CanonicalSchedule(name="S", work_weekdays=[0, 1, 2, 3, 4], holidays=[],
        tasks=[ScheduleTask(id="t1", name="Pour", wbs="1", start="2026-08-10",
                            finish="2026-08-14", bid_item_codes=["A"])])


def test_embed_authors_cost_and_labor_linked_to_task():
    model = _ifc_with_task("1")   # embed_schedule set identification = wbs "1"
    costs = {"A": {"cost": 10000.0, "labor_hours": 400.0}}
    report = cost5d.embed_cost_and_resources(model, _sched(), costs,
                                             work_hours_per_day=8.0)
    assert model.by_type("IfcCostSchedule")
    ci = model.by_type("IfcCostItem")
    assert len(ci) == 1
    assert round(ci[0].CostValues[0].AppliedValue.wrappedValue, 2) == 10000.0
    # the cost item carries the cost code: Identification = code, and it is
    # classified via IfcRelAssociatesClassification so it is groupable by code.
    assert ci[0].Identification == "A"
    codes = [a.RelatingClassification.Identification
             for a in (ci[0].HasAssociations or [])
             if a.is_a("IfcRelAssociatesClassification")]
    assert codes == ["A"]
    lr = model.by_type("IfcLaborResource")
    assert len(lr) == 1
    # hours land in the standard StandardWork base quantity (so Bonsai/Synchro
    # surface them in the resource quantity panel), and in ScheduleWork usage.
    bq = lr[0].BaseQuantity
    assert bq is not None and bq.Name == "StandardWork" and bq.TimeValue == 400.0
    assert lr[0].Usage.ScheduleWork == "PT400H"
    task = model.by_type("IfcTask")[0]
    rels = {a.is_a() for a in (task.HasAssignments or [])}
    assert "IfcRelAssignsToControl" in rels    # cost item -> task
    assert "IfcRelAssignsToResource" in rels    # labor -> task
    assert report.cost_items == 1 and report.resources == 1


def test_embed_is_idempotent_by_name():
    model = _ifc_with_task("1")
    costs = {"A": {"cost": 10000.0, "labor_hours": 400.0}}
    for _ in range(3):
        cost5d.embed_cost_and_resources(model, _sched(), costs)
    assert len(model.by_type("IfcCostSchedule")) == 1
    assert len(model.by_type("IfcCostItem")) == 1
    assert len(model.by_type("IfcCostValue")) == 1
    assert len(model.by_type("IfcLaborResource")) == 1
    # classification does not accumulate on re-run either: one classification,
    # one reference for code A, and the cost item classified exactly once.
    assert len(model.by_type("IfcClassification")) == 1
    assert len(model.by_type("IfcClassificationReference")) == 1
    _ci = model.by_type("IfcCostItem")[0]
    assert len([a for a in (_ci.HasAssociations or [])
                if a.is_a("IfcRelAssociatesClassification")]) == 1
    # no orphaned cost-item->task assignment rels
    dangling = [r for r in model.by_type("IfcRelAssignsToControl")
                if r.RelatingControl is None]
    assert dangling == []
    # the surviving cost item still carries the right value and task link
    ci = model.by_type("IfcCostItem")[0]
    assert round(ci.CostValues[0].AppliedValue.wrappedValue, 2) == 10000.0


def test_multi_code_task_splits_into_classified_cost_items():
    # a task carrying two cost codes yields ONE cost item per code, each
    # classified — never a single blended figure (so cost is groupable by code).
    model = _ifc_with_task("1")
    sched = CanonicalSchedule(name="S", work_weekdays=[0, 1, 2, 3, 4], holidays=[],
        tasks=[ScheduleTask(id="t1", name="Curb & flatwork", wbs="1",
                            start="2026-08-10", finish="2026-08-14",
                            bid_item_codes=["32 16 13", "EF_25_30"])])
    costs = {"32 16 13": {"cost": 21000.0, "labor_hours": 180.0},
             "EF_25_30": {"cost": 15000.0, "labor_hours": None}}  # lump-sum, no hours
    report = cost5d.embed_cost_and_resources(model, sched, costs)
    items = {ci.Identification: ci.CostValues[0].AppliedValue.wrappedValue
             for ci in model.by_type("IfcCostItem")}
    assert items == {"32 16 13": 21000.0, "EF_25_30": 15000.0}   # no blending
    assert report.cost_items == 2
    # one crew for the task, hours only from the code that had them (180)
    lr = model.by_type("IfcLaborResource")
    assert len(lr) == 1 and lr[0].BaseQuantity.TimeValue == 180.0


def test_rerun_never_strips_element_classifications():
    # An ELEMENT sharing a code with the estimate: classification.add_reference
    # matches existing references by Identification alone (ignoring the
    # system), so classifying the cost item must never splice it into — nor
    # teardown remove — the element's own BidSchedule rel.
    import ifcopenshell.api.classification as cl
    model = _ifc_with_task("1")
    pile = root.create_entity(model, ifc_class="IfcPile", name="P-1")
    system = cl.add_classification(model, classification="BidSchedule")
    cl.add_reference(model, products=[pile], identification="A", name="A",
                     classification=system)
    costs = {"A": {"cost": 10000.0, "labor_hours": 400.0}}
    for _ in range(2):
        cost5d.embed_cost_and_resources(model, _sched(), costs)
    # the pile still carries exactly its one BidSchedule reference
    refs = [a.RelatingClassification for a in (pile.HasAssociations or [])
            if a.is_a("IfcRelAssociatesClassification")]
    assert [(r.Identification, r.ReferencedSource.Name) for r in refs] \
        == [("A", "BidSchedule")]
    # and the cost item is still classified with the code
    ci = model.by_type("IfcCostItem")
    assert len(ci) == 1
    codes = [a.RelatingClassification.Identification
             for a in (ci[0].HasAssociations or [])
             if a.is_a("IfcRelAssociatesClassification")]
    assert codes == ["A"]
    # entity counts do not accumulate across the two runs
    assert len(model.by_type("IfcCostSchedule")) == 1
    assert len(model.by_type("IfcCostValue")) == 1
    assert len(model.by_type("IfcLaborResource")) == 1


def test_iso_hours_never_scientific():
    from bimforge.bim.cost5d import _iso_hours
    assert _iso_hours(400.0) == "PT400H"
    assert _iso_hours(2.5) == "PT2.5H"
    assert _iso_hours(1234567.0) == "PT1234567H"
