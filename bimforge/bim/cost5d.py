"""Embed cost + labor resources into a 4D IFC (5D spec, slice 3).

Given a schedule already embedded by `bim/schedule4d.py` (IfcTasks whose
Identification is the task's wbs-or-id) and a cost record, author one
IfcCostSchedule with **one IfcCostItem per (task, cost code)** — its distributed
cost as an IfcCostValue, classified with the cost code (IfcRelAssociatesClassification)
and linked to the task via IfcRelAssignsToControl — plus one IfcLaborResource
per loaded task carrying IfcResourceTime hours + a StandardWork IfcQuantityTime,
assigned to the task via IfcRelAssignsToResource.

Per-(task, code) cost items keep the cost code on the item (groupable in cost
accounting) and never blend a multi-code task into one uncoded figure; the crew
stays per task (a crew executes the task, its hours summed across the task's
codes). Idempotent by name: the cost schedule is "<name> cost"; each crew is
"<name>: <task>". A re-run removes those (and their classification links) first.
Pure ifcopenshell.api; the distribution is `bimforge.bim.costload`.

Issue #335: each cost item also carries `Pset_BimforgeCostItem` (TaskId, and
the item's own LaborHours — the crew sums hours across a task's codes, so
per-code hours are otherwise lost), and tasks are found inside the work
schedule of the same name by the id `schedule_read.task_id` reads, so
`schedule_read.read_costs` returns the same task identities as
`read_schedule`.
"""
from __future__ import annotations

from dataclasses import dataclass

import ifcopenshell.api.classification as cl
import ifcopenshell.api.control as ctl
import ifcopenshell.api.cost as cost
import ifcopenshell.api.pset as pset_api
import ifcopenshell.api.resource as res
import ifcopenshell.guid

from bimforge.bim.costload import distribute_to_task_codes, load_schedule_costs
from bimforge.bim.schedule_read import _schedule_tasks, task_id

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bimforge.bim.schedule_model import CanonicalSchedule

# The IfcClassification the per-code cost items are referenced under. The codes
# themselves are the project's cost/bid-item codes (the same spine the elements
# carry); this names the source system for the cost side.
CLASSIFICATION_NAME = "Estimate cost codes"

# per cost item: the canonical task id and the (task, code) labor hours
COST_ITEM_PSET = "Pset_BimforgeCostItem"


@dataclass
class CostEmbedReport:
    schedule_name: str
    cost_items: int = 0
    resources: int = 0
    total_cost: float = 0.0
    total_labor_hours: float = 0.0
    tasks_without_entity: list = None    # schedule task ids with no IfcTask match

    def __post_init__(self):
        if self.tasks_without_entity is None:
            self.tasks_without_entity = []


def _iso_hours(hours: float) -> str:
    """ISO-8601 duration for a labor-hour count, never scientific notation."""
    s = f"{hours:.4f}".rstrip("0").rstrip(".")
    return f"PT{s}H"


def _remove_named(model, cost_name: str, crew_prefix: str) -> None:
    for cs in list(model.by_type("IfcCostSchedule")):
        if cs.Name != cost_name:
            continue
        # remove_cost_schedule cascades the items but leaves orphaned: the
        # IfcRelAssignsToControl (task link), the IfcRelAssociatesClassification
        # (code link), and the nested IfcCostValue — all of which accumulate and
        # invalidate the file on re-run. Drop them explicitly first.
        for rel in (cs.Controls or []):
            for ci in list(rel.RelatedObjects):
                if not ci.is_a("IfcCostItem"):
                    continue
                for arel in list(getattr(ci, "Controls", None) or []):
                    ctl.unassign_control(model, relating_control=ci,
                                         related_objects=list(arel.RelatedObjects))
                for assoc in list(getattr(ci, "HasAssociations", None) or []):
                    if not assoc.is_a("IfcRelAssociatesClassification"):
                        continue
                    others = [o for o in assoc.RelatedObjects if o != ci]
                    if others:
                        # a shared rel (e.g. an element's own BidSchedule
                        # association) — detach this item only, never the rel
                        assoc.RelatedObjects = others
                        continue
                    ref = assoc.RelatingClassification
                    model.remove(assoc)
                    # drop the reference too if nothing else points at it
                    if ref and not model.get_inverse(ref):
                        model.remove(ref)
                for cv in list(ci.CostValues or []):
                    cost.remove_cost_value(model, ci, cv)
                for drel in list(getattr(ci, "IsDefinedBy", None) or []):
                    if drel.is_a("IfcRelDefinesByProperties"):
                        pset_api.remove_pset(
                            model, product=ci,
                            pset=drel.RelatingPropertyDefinition)
        cost.remove_cost_schedule(model, cs)
    for r in list(model.by_type("IfcConstructionResource")):
        if r.Name and r.Name.startswith(crew_prefix):
            res.remove_resource(model, r)


def _classification(model):
    for c in model.by_type("IfcClassification"):
        if c.Name == CLASSIFICATION_NAME:
            return c
    return cl.add_classification(model, CLASSIFICATION_NAME)


def _code_reference(model, item, code: str, classif) -> None:
    """Classify a cost item with its bid-item code under `classif`.

    Deliberately NOT `classification.add_reference`: that API finds any
    existing IfcClassificationReference by Identification alone (ignoring
    the classification system) and would splice the cost item into the
    ELEMENT's own BidSchedule rel — the very rel teardown must never touch.
    A dedicated reference per cost item keeps the two spines separate.
    Shared with estimate5d.
    """
    ref = model.create_entity("IfcClassificationReference",
                              Identification=code, Name=code,
                              ReferencedSource=classif)
    model.create_entity("IfcRelAssociatesClassification",
                        GlobalId=ifcopenshell.guid.new(),
                        RelatedObjects=[item], RelatingClassification=ref)


def embed_cost_and_resources(model, sched: CanonicalSchedule, costs: dict, *,
                             schedule_name: str | None = None,
                             work_hours_per_day: float = 8.0) -> CostEmbedReport:
    """Author cost + labor onto the open IFC in place; return a CostEmbedReport."""
    name = schedule_name or sched.name or "Schedule"
    loaded = load_schedule_costs(sched, costs,
                                 work_hours_per_day=work_hours_per_day)
    task_codes = distribute_to_task_codes(sched, costs)
    cost_name, crew_prefix = f"{name} cost", f"{name}: "
    _remove_named(model, cost_name, crew_prefix)

    # IfcTask inside the 4D schedule of the same name, by canonical id (the
    # one read_schedule returns), then by Identification (schedule4d set it
    # to wbs or id). Only a model with no same-named schedule falls back to
    # every task in the file, so one schedule's costs never land on another's
    in_schedule, scoped = {}, None
    for ws in model.by_type("IfcWorkSchedule"):
        if ws.Name == name:
            scoped = [t for t, _ in _schedule_tasks(ws)]
            in_schedule = {task_id(t): t for t in scoped}
            break
    task_ent = {t.Identification: t for t in
                (scoped if scoped is not None else model.by_type("IfcTask"))}
    by_id = {t.id: t for t in sched.tasks}

    cs = cost.add_cost_schedule(model, name=cost_name, predefined_type="BUDGET")
    classif = _classification(model)
    report = CostEmbedReport(schedule_name=name)
    missing: set = set()

    def _entity(tid):
        st = by_id.get(tid)
        if tid in in_schedule:
            return st, in_schedule[tid]
        ident = (st.wbs or st.id) if st else tid
        return st, task_ent.get(ident)

    # one classified cost item per (task, cost code)
    for (tid, code), e in task_codes.items():
        if e["cost"] <= 0:
            continue
        st, ent = _entity(tid)
        if ent is None:
            missing.add(tid)
            continue
        ci = cost.add_cost_item(model, cost_schedule=cs)
        cost.edit_cost_item(model, ci, attributes={
            "Name": f"{st.name if st else tid}: {code}", "Identification": code})
        cv = cost.add_cost_value(model, parent=ci)
        cost.edit_cost_value(model, cv, attributes={"AppliedValue": e["cost"]})
        ctl.assign_control(model, relating_control=ci, related_objects=[ent])
        _code_reference(model, ci, code, classif)
        ps = pset_api.add_pset(model, product=ci, name=COST_ITEM_PSET)
        # LaborHours only when the code's hours are known: a null in the
        # costs record means unknown, which must not read back as zero
        known = (costs.get(code) or {}).get("labor_hours") is not None
        pset_api.edit_pset(model, pset=ps, properties={
            "TaskId": tid,
            **({"LaborHours": float(e["labor_hours"])} if known else {})})
        report.cost_items += 1

    # one labor crew per task (hours summed across the task's codes)
    for tid, load in loaded.by_task.items():
        if load["labor_hours"] <= 0:
            continue
        st, ent = _entity(tid)
        if ent is None:
            missing.add(tid)
            continue
        crew = res.add_resource(model, ifc_class="IfcLaborResource",
                                name=f"{name}: {st.name if st else tid}")
        rt = res.add_resource_time(model, resource=crew)
        res.edit_resource_time(model, rt, attributes={
            "ScheduleWork": _iso_hours(load["labor_hours"])})
        # Name the base quantity `StandardWork` — the standard slot in
        # Qto_LaborResourceBaseQuantities — so Bonsai/Synchro surface the
        # crew-hours in the resource quantity panel (a custom name reads as zero
        # there). ScheduleWork above carries the same hours as usage.
        q = res.add_resource_quantity(model, resource=crew,
                                      ifc_class="IfcQuantityTime")
        res.edit_resource_quantity(model, q, attributes={
            "Name": "StandardWork", "TimeValue": float(load["labor_hours"])})
        res.assign_resource(model, relating_resource=crew, related_object=ent)
        report.resources += 1

    report.tasks_without_entity = sorted(missing)
    report.total_cost = loaded.total_cost
    report.total_labor_hours = loaded.total_labor_hours
    return report
