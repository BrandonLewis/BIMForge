"""estimate_model5d: a BidSheet.ai get_estimate_model document -> IfcTask /
IfcCostItem / IfcLaborResource, read back with schedule_read."""
import json
from decimal import Decimal

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

import ifcopenshell.api.root  # noqa: E402
import ifcopenshell.guid  # noqa: E402

from bimforge.bim import cli  # noqa: E402
from bimforge.bim.estimate_model5d import (  # noqa: E402
    apportion_cents, embed_estimate_model,
)
from bimforge.bim.schedule_read import (  # noqa: E402
    read_costs, read_schedule, task_elements,
)

NAME = "BidSheet.ai estimate 76"
UNASSIGNED = ifcopenshell.guid.compress("7c9e6679-7425-40de-944b-e07fc1f90ae7".replace("-", ""))


def _ifc():
    f = ifcopenshell.file(schema="IFC4X3_ADD2")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="p")
    site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite",
                                               name="site")
    ftg = ifcopenshell.api.root.create_entity(f, ifc_class="IfcFooting",
                                              name="F-1")
    wall = ifcopenshell.api.root.create_entity(f, ifc_class="IfcWall",
                                               name="W-1")
    return f, site, ftg, wall


def _model_json(ftg_gid, wall_gid):
    crew = {"id": 5, "name": "Concrete crew", "headcount": "4.00",
            "members": [{"classification": "Carpenter", "count": "3"},
                        {"classification": "Laborer", "count": "1"}]}
    return {
        "estimate": {"id": 76, "name": "Sample Bridge"},
        "items": [
            {"id": 1, "item_number": "10", "item_code": "51-CONC",
             "schedule": "A", "description": "Structural concrete",
             "unit": "CY", "quantity": "20.0000", "unit_price": "1.00",
             "total": "20.01", "pricing_source": "detailed"},
            {"id": 2, "item_number": "20", "item_code": "",
             "schedule": "A", "description": "Mobilization", "unit": "LS",
             "quantity": "1", "unit_price": "500.00", "total": "500.00",
             "pricing_source": "detailed"},
            {"id": 3, "item_number": "30", "item_code": "99-UNUSED",
             "schedule": "A", "description": "Unpriced item", "unit": "EA",
             "quantity": "1", "unit_price": None, "total": None,
             "pricing_source": None},
        ],
        "elements": [
            {"id": 101, "global_id": ftg_gid, "global_id_assigned": True,
             "name": "F-1", "element_type": "footing",
             "ifc_class": "IfcFooting", "source": "modelled", "quantities": []},
            {"id": 102, "global_id": wall_gid, "global_id_assigned": True,
             "name": "W-1", "element_type": "wall", "ifc_class": "IfcWall",
             "source": "modelled", "quantities": []},
            {"id": 103, "global_id": UNASSIGNED, "global_id_assigned": False,
             "name": "Abutment 1", "element_type": "wall",
             "ifc_class": "IfcWall", "source": "parametric",
             "quantities": []},
        ],
        "activities": [
            {"id": 1, "key": "a1", "name": "Form & pour footing",
             "kind": "labor", "home_item_id": 1, "cost_code": "03-300",
             "crew": crew, "duration_days": "5", "manhours": "20",
             "cost": "10.004", "cost_split": {"labor": "10.004"},
             # BidSheet.ai: end_date exclusive (start + 5 working days),
             # finish_date the inclusive last working day
             "start_date": "2026-08-10", "end_date": "2026-08-15",
             "finish_date": "2026-08-14",
             "element_ids": [101, 103], "spread": {"basis": "",
                                                   "scope": "all",
                                                   "items": []}},
            {"id": 2, "key": "a2", "name": "Form & pour wall",
             "kind": "labor", "home_item_id": 1, "cost_code": "03-300",
             "crew": crew, "duration_days": "5", "manhours": "20",
             "cost": "10.004", "cost_split": {"labor": "10.004"},
             # an older model: no finish_date, and an exclusive end_date
             # on a Monday — the finish steps back over the weekend
             "start_date": "2026-08-17", "end_date": "2026-08-24",
             "element_ids": [102], "spread": {"basis": "", "scope": "all",
                                              "items": []}},
            {"id": 3, "key": "a3", "name": "Mobilize", "kind": "priced",
             "home_item_id": 2, "cost_code": "01-500", "crew": None,
             "duration_days": None, "manhours": "0", "cost": "500",
             "cost_split": {"other": "500"}, "start_date": None,
             "end_date": None, "element_ids": [101],
             "spread": {"basis": "cost", "scope": "all", "items": [1, 2]}},
        ],
        "shares": [
            {"activity_id": 1, "activity_key": "a1", "item_id": 1,
             "element_id": 101, "fraction": "1", "cost": "10.004",
             "manhours": "20", "reason": "home"},
            {"activity_id": 2, "activity_key": "a2", "item_id": 1,
             "element_id": 102, "fraction": "1", "cost": "10.004",
             "manhours": "20", "reason": "home"},
            {"activity_id": 3, "activity_key": "a3", "item_id": 2,
             "element_id": None, "fraction": "1", "cost": "500",
             "manhours": "0", "reason": "spread"},
        ],
    }


def _embed(**kw):
    f, site, ftg, wall = _ifc()
    summary = embed_estimate_model(f, _model_json(ftg.GlobalId, wall.GlobalId),
                                   **kw)
    return f, summary, ftg, wall


def _parents(f):
    (cs,) = f.by_type("IfcCostSchedule")
    return cs, {ci.Identification: ci for rel in cs.Controls or []
                for ci in rel.RelatedObjects if ci.is_a("IfcCostItem")}


def _kids(ci):
    return [o for rel in ci.IsNestedBy or [] for o in rel.RelatedObjects
            if o.is_a("IfcCostItem")]


def _value(ci):
    return sum(cv.AppliedValue.wrappedValue for cv in ci.CostValues or [])


def test_apportion_cents_sums_to_the_rounded_exact_total():
    got = apportion_cents([Decimal("10.004"), Decimal("10.004")])
    assert got == [Decimal("10.00"), Decimal("10.01")]
    assert sum(got) == Decimal("20.01")
    many = [Decimal("0.3333")] * 3
    assert sum(apportion_cents(many)) == Decimal("1.00")


def test_one_task_per_activity_with_dates():
    f, summary, _, _ = _embed()
    (ws,) = f.by_type("IfcWorkSchedule")
    assert ws.Name == NAME
    sched = read_schedule(f)
    tasks = {t.id: t for t in sched.tasks}
    assert set(tasks) == {"a1", "a2", "a3"}
    assert tasks["a1"].name == "Form & pour footing"
    assert (tasks["a1"].start, tasks["a1"].finish) == ("2026-08-10",
                                                       "2026-08-14")
    assert tasks["a1"].duration_days == 5      # agrees with the span
    # no finish_date: the working day before the exclusive end_date
    assert (tasks["a2"].start, tasks["a2"].finish) == ("2026-08-17",
                                                       "2026-08-21")
    assert tasks["a2"].duration_days == 5
    assert any("a2" in w and "finish_date" in w for w in summary["warnings"])
    assert not any("a1" in w and "finish_date" in w
                   for w in summary["warnings"])
    assert tasks["a3"].start is None and tasks["a3"].finish is None
    # the home item's number rides as an owner bid item
    assert tasks["a1"].bid_items == ["10"]
    ident = {t.Identification for t in f.by_type("IfcTask")}
    assert ident == {"a1", "a2", "a3"}
    assert summary["tasks"] == 3 and summary["tasks_timed"] == 2


def test_tasks_link_elements_by_global_id_and_spread_links_none():
    f, summary, ftg, wall = _embed()
    links = task_elements(f, NAME)
    assert [l["global_id"] for l in links["a1"]] == [ftg.GlobalId]  # noqa: E741
    assert [l["global_id"] for l in links["a2"]] == [wall.GlobalId]  # noqa: E741
    assert links["a3"] == []             # spread: no elements, even listed
    assert summary["task_element_links"] == 2
    assert summary["unmatched_links"] == [{"activity": "a1",
                                           "element_id": 103}]


def test_cost_items_per_item_and_share_sum_to_item_total():
    f, summary, ftg, wall = _embed()
    cs, parents = _parents(f)
    assert cs.PredefinedType == "ESTIMATE" and cs.Name == f"{NAME} cost"
    assert set(parents) == {"51-CONC", "20"}   # item code, else number
    conc = parents["51-CONC"]
    assert conc.Name == "Structural concrete"
    assert not (conc.CostValues or [])         # valueless: sum the children
    kids = _kids(conc)
    values = sorted(round(_value(k), 2) for k in kids)
    assert values == [10.00, 10.01]
    assert round(sum(values), 2) == 20.01      # not 20.00
    assert summary["cost_items"] == 2 and summary["share_items"] == 3
    # an item with no shares gets no (valueless, unlinked) cost item
    assert summary["items_without_shares"] == [3]
    assert "99-UNUSED" not in parents
    assert Decimal(summary["allocated_total"]) == Decimal("520.01")
    # each share's item links its task and its element
    by_name = {k.Name: k for k in kids}
    ftg_kid = by_name["Form & pour footing: F-1"]
    related = [o for rel in ftg_kid.Controls for o in rel.RelatedObjects]
    assert {o.is_a() for o in related} == {"IfcTask", "IfcFooting"}
    assert ftg in related


def test_one_labor_resource_per_crew_with_headcount():
    f, summary, _, _ = _embed()
    (crew,) = f.by_type("IfcLaborResource")
    assert crew.Name == f"{NAME}: crew Concrete crew"
    assert "3 x Carpenter" in crew.Description
    import ifcopenshell.util.element as ue
    ps = ue.get_psets(crew)["BidSheet_Crew"]
    assert ps["Headcount"] == 4.0 and ps["CrewId"] == 5
    tasks = {t.Identification for rel in crew.ResourceOf or []
             for t in rel.RelatedObjects}
    assert tasks == {"a1", "a2"}
    assert summary["labor_resources"] == 1


def test_elements_absent_from_the_ifc_are_reported_not_invented():
    f, summary, _, _ = _embed()
    assert summary["unmatched_elements"] == [{
        "id": 103, "global_id": UNASSIGNED, "name": "Abutment 1",
        "global_id_assigned": False}]
    assert not f.by_type("IfcBuildingElementProxy")
    assert summary["placeholders_created"] == 0


def test_placeholders_opt_in_carry_the_global_id():
    f, summary, _, _ = _embed(placeholders=True)
    (proxy,) = f.by_type("IfcBuildingElementProxy")
    assert proxy.GlobalId == UNASSIGNED and proxy.Name == "Abutment 1"
    assert proxy.ContainedInStructure[0].RelatingStructure.is_a("IfcSite")
    assert summary["unmatched_elements"] == []
    assert summary["placeholders_created"] == 1
    links = task_elements(f, NAME)
    assert UNASSIGNED in [l["global_id"] for l in links["a1"]]  # noqa: E741


def test_round_trip_through_read_costs():
    f, _, _, _ = _embed()
    got = read_costs(f, NAME)
    assert got["warnings"] == []
    assert got["tasks"]["a1"]["costs"]["51-CONC"]["cost"] == \
        pytest.approx(10.00)
    assert got["tasks"]["a2"]["costs"]["51-CONC"]["cost"] == \
        pytest.approx(10.01)
    assert got["tasks"]["a1"]["costs"]["51-CONC"]["labor_hours"] == \
        pytest.approx(20.0)
    assert got["tasks"]["a3"]["costs"]["20"]["cost"] == pytest.approx(500.0)
    assert got["costs"]["51-CONC"]["cost"] == pytest.approx(20.01)
    assert got["costs"]["51-CONC"]["labor_hours"] == pytest.approx(40.0)
    # task totals: the crew is shared, so each task's hours are its own
    # activity's (20 each), never the crew's (none) or a sum across tasks
    assert got["tasks"]["a1"]["labor_hours"] == pytest.approx(20.0)
    assert got["tasks"]["a2"]["labor_hours"] == pytest.approx(20.0)
    assert got["tasks"]["a3"]["labor_hours"] == pytest.approx(0.0)
    # the read-back task ids are read_schedule's
    assert set(got["tasks"]) <= {t.id for t in read_schedule(f, NAME).tasks}


def test_rerun_replaces_by_name(tmp_path):
    f, _, ftg, wall = _embed()
    counts = lambda: {c: len(f.by_type(c)) for c in (  # noqa: E731
        "IfcTask", "IfcCostItem", "IfcCostValue", "IfcLaborResource",
        "IfcRelAssociatesClassification", "IfcRelAssignsToControl",
        "IfcRelAssignsToProcess", "IfcRelAssignsToResource",
        "IfcPropertySet", "IfcClassificationReference")}
    before = counts()
    embed_estimate_model(f, _model_json(ftg.GlobalId, wall.GlobalId))
    assert counts() == before
    out = tmp_path / "o.ifc"
    f.write(str(out))
    assert read_costs(ifcopenshell.open(str(out)), NAME)["warnings"] == []


def test_cli_estimate_model(tmp_path, capsys):
    f, site, ftg, wall = _ifc()
    src = tmp_path / "in.ifc"
    f.write(str(src))
    model = tmp_path / "model.json"
    model.write_text(json.dumps(_model_json(ftg.GlobalId, wall.GlobalId)),
                     encoding="utf-8")
    out = tmp_path / "out.ifc"
    rc = cli.main(["estimate-model", str(src), str(model), str(out)])
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["share_items"] == 3
    back = ifcopenshell.open(str(out))
    assert {t.id for t in read_schedule(back).tasks} == {"a1", "a2", "a3"}


def test_items_sharing_a_code_get_distinct_identifications():
    f, site, ftg, wall = _ifc()
    model = _model_json(ftg.GlobalId, wall.GlobalId)
    model["items"][1]["item_code"] = "51-CONC"      # schedule A again
    model["items"][1]["schedule"] = "B"
    embed_estimate_model(f, model)
    _, parents = _parents(f)
    assert set(parents) == {"51-CONC [A]", "51-CONC [B]"}
    import ifcopenshell.util.element as ue
    for ident, ci in parents.items():
        assert ue.get_psets(ci)["BidSheet_EstimateItem"]["ItemCode"] ==             "51-CONC"
    got = read_costs(f, NAME)
    assert got["costs"]["51-CONC [A]"]["cost"] == pytest.approx(20.01)
    assert got["costs"]["51-CONC [B]"]["cost"] == pytest.approx(500.0)


def test_same_schedule_same_code_falls_back_to_the_item_id():
    from bimforge.bim.estimate_model5d import item_identifications
    got = item_identifications([
        {"id": 1, "item_code": "X", "schedule": "A"},
        {"id": 2, "item_code": "X", "schedule": "A"},
        {"id": 3, "item_code": "Y", "schedule": "A"}])
    assert got == {1: "X [item 1]", 2: "X [item 2]", 3: "Y"}


def test_an_unmarked_same_named_schedule_is_refused_not_replaced():
    from bimforge.bim.schedule4d import embed_schedule
    from bimforge.bim.schedule_model import CanonicalSchedule, ScheduleTask
    f, site, ftg, wall = _ifc()
    embed_schedule(f, CanonicalSchedule(name=NAME, tasks=[
        ScheduleTask(id="t1", name="Stage 1")]))
    with pytest.raises(ValueError, match="did not write"):
        embed_estimate_model(f, _model_json(ftg.GlobalId, wall.GlobalId))
    assert [t.Name for t in f.by_type("IfcTask")] == ["Stage 1"]

    f, site, ftg, wall = _ifc()
    import ifcopenshell.api.cost as cost
    cost.add_cost_schedule(f, name=f"{NAME} cost", predefined_type="BUDGET")
    with pytest.raises(ValueError, match="IfcCostSchedule"):
        embed_estimate_model(f, _model_json(ftg.GlobalId, wall.GlobalId))
    assert len(f.by_type("IfcCostSchedule")) == 1


def test_rerun_leaves_other_tools_schedules_alone():
    from bimforge.bim import cost5d
    from bimforge.bim.schedule4d import embed_schedule
    from bimforge.bim.schedule_model import CanonicalSchedule, ScheduleTask
    f, summary, ftg, wall = _embed()
    stage = CanonicalSchedule(name="Staging", tasks=[
        ScheduleTask(id="s1", name="Stage 1", start="2026-08-03",
                     finish="2026-08-07", bid_item_codes=["X"])])
    embed_schedule(f, stage)
    cost5d.embed_cost_and_resources(
        f, stage, {"X": {"cost": 10.0, "labor_hours": 8.0}})
    embed_estimate_model(f, _model_json(ftg.GlobalId, wall.GlobalId))
    names = sorted(w.Name for w in f.by_type("IfcWorkSchedule"))
    assert names == [NAME, "Staging"]
    assert sorted(c.Name for c in f.by_type("IfcCostSchedule")) == [
        f"{NAME} cost", "Staging cost"]
    assert read_costs(f, "Staging")["costs"]["X"]["cost"] ==         pytest.approx(10.0)
    # cost5d's crew ("Staging: Stage 1") survives; ours is replaced, not doubled
    crews = sorted(r.Name for r in f.by_type("IfcLaborResource"))
    assert crews == [f"{NAME}: crew Concrete crew", "Staging: Stage 1"]
