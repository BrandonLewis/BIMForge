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

Issue #335: each cost item also carries `Bimforge_CostItem` (TaskId, and
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
import ifcopenshell.api.project as project_api
import ifcopenshell.api.pset as pset_api
import ifcopenshell.api.resource as res
import ifcopenshell.guid

from bimforge.bim.cost_categories import (normalize_split, split_amount,
                                          split_of, write_cost_values)
from bimforge.bim.costload import distribute_to_task_codes, load_schedule_costs
from bimforge.bim.schedule_read import _schedule_tasks, task_id
from bimforge.bim import stable_ids

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bimforge.bim.schedule_model import CanonicalSchedule

# The IfcClassification the per-code cost items are referenced under. The codes
# themselves are the project's cost/bid-item codes (the same spine the elements
# carry); this names the source system for the cost side.
CLASSIFICATION_NAME = "Estimate cost codes"

# per cost item: the canonical task id and the (task, code) labor hours
# Not "Pset_": that prefix is reserved for buildingSMART's standard sets.
# Models written by 0.1.88 or earlier carry "Pset_BimforgeCostItem", which
# schedule_read still reads.
COST_ITEM_PSET = "Bimforge_CostItem"


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
        remove_declared_cost_schedule(model, cs)
    for r in list(model.by_type("IfcConstructionResource")):
        if r.Name and r.Name.startswith(crew_prefix):
            res.remove_resource(model, r)


#: the currency a file that declares none is given
DEFAULT_CURRENCY = "USD"


def ensure_currency(model, currency: str | None = None):
    """The project's IfcMonetaryUnit, added to its IfcUnitAssignment when it
    has none, so cost values carry a currency: `currency`, else
    DEFAULT_CURRENCY. A file that already declares one keeps it (one
    monetary unit per file); asking for a different one raises ValueError,
    since the values already written are in the file's. A project with no
    unit assignment is left alone (it declares no units at all)."""
    import ifcopenshell.api.unit as unit
    projects = model.by_type("IfcProject")
    units = projects[0].UnitsInContext if projects else None
    if units is None:
        return None
    money = check_currency(model, currency)
    if money is None:
        money = unit.add_monetary_unit(model,
                                       currency=currency or DEFAULT_CURRENCY)
        unit.assign_unit(model, units=[money])
    return money


def check_currency(model, currency: str | None):
    """The file's declared IfcMonetaryUnit (None when it has none), after
    refusing a `currency` that differs from it — so a writer can refuse
    before it touches the model."""
    projects = model.by_type("IfcProject")
    units = projects[0].UnitsInContext if projects else None
    for u in (units.Units if units else ()) or ():
        if u.is_a("IfcMonetaryUnit"):
            if currency and u.Currency != currency:
                raise ValueError(
                    f"the IFC's currency is {u.Currency}, not {currency}: "
                    f"its cost values are in {u.Currency}, so write this one "
                    f"in {u.Currency} too (or omit the currency)")
            return u
    return None


def _hour(model):
    """The file's 'hour' IfcConversionBasedUnit, made once."""
    import ifcopenshell.api.unit as unit
    for u in model.by_type("IfcConversionBasedUnit"):
        if u.UnitType == "TIMEUNIT" and (u.Name or "").lower() == "hour":
            return u
    return unit.add_conversion_based_unit(model, name="hour")


def hours_unit(model):
    """The unit a StandardWork IfcQuantityTime written in hours must name,
    or None when the project's TIMEUNIT already is the hour.

    IFC's SI time unit is the second, so a TimeValue of 400 in a file with
    no TIMEUNIT read as 400 s. A project whose unit assignment has no
    TIMEUNIT is given the hour (once); one that declares another time unit
    keeps it — an embed never re-declares a third-party file's units — and
    so does a file with no unit assignment: both get the hour on the
    quantity's own Unit instead, which overrides the project's."""
    import ifcopenshell.api.unit as unit
    import ifcopenshell.util.unit as uu
    projects = model.by_type("IfcProject")
    units = projects[0].UnitsInContext if projects else None
    declared = [u for u in (units.Units if units else ())
                if getattr(u, "UnitType", None) == "TIMEUNIT"]
    if units is not None and not declared:
        unit.assign_unit(model, units=[_hour(model)])
        return None
    if declared and abs(uu.calculate_unit_scale(model, "TIMEUNIT")
                        - 3600.0) < 1e-9:
        return None
    return _hour(model)


#: the Status of a schedule bimforge writes before it is agreed: a BUDGET or
#: ESTIMATE, and a TENDER at bid (IfcCostSchedule.Status is a label; IFC's
#: own examples are PLANNED, APPROVED, AGREED, ISSUED, STARTED)
PLANNED = "PLANNED"


def ifc_datetime(value: str | None, what: str) -> str | None:
    """An IfcDateTime for a 'YYYY-MM-DD' (or ISO date-time) `value`, at
    midnight; None for None. A value that is not a date raises ValueError
    naming `what`."""
    from datetime import date
    if value is None:
        return None
    try:
        day = date.fromisoformat(str(value)[:10])
    except ValueError:
        raise ValueError(f"{what} must be a date (YYYY-MM-DD), got "
                         f"{value!r}") from None
    return f"{day.isoformat()}T00:00:00"


def add_declared_cost_schedule(model, *, name: str, predefined_type: str,
                               status: str | None = None,
                               currency: str | None = None,
                               submitted_on: str | None = None):
    """An IfcCostSchedule declared to the IfcProject (IfcRelDeclares).

    A control that sits outside the project's decomposition and declarations
    is not part of the project: viewers and ProjectCommand only find a cost
    schedule through the project, so every schedule bimforge writes is
    declared. `status` is the schedule's Status (PLANNED, APPROVED, ...).
    The file's currency is declared on the way (`ensure_currency`).

    `submitted_on` (an IfcDateTime) is the SubmittedOn and UpdateDate; with
    none both stay unset. ifcopenshell stamps UpdateDate with the write
    time, which a reader takes as the schedule's date and which changes the
    file on every run (the rule #36 set for StartTime), so it is cleared."""
    ensure_currency(model, currency)
    cs = cost.add_cost_schedule(model, name=name,
                                predefined_type=predefined_type)
    stable_ids.assign(model, cs, f"cost-schedule/{name}")
    cs.UpdateDate = submitted_on
    if submitted_on:
        cs.SubmittedOn = submitted_on
    if status:
        cs.Status = status
    projects = model.by_type("IfcProject")
    if projects:
        project_api.assign_declaration(model, definitions=[cs],
                                       relating_context=projects[0])
    return cs


def remove_declared_cost_schedule(model, cs) -> None:
    """remove_cost_schedule, first dropping the schedule's IfcRelDeclares
    (ifcopenshell leaves it behind, pointing at nothing)."""
    for rel in list(getattr(cs, "HasContext", None) or []):
        project_api.unassign_declaration(model, definitions=[cs],
                                         relating_context=rel.RelatingContext)
    cost.remove_cost_schedule(model, cs)


def _classification(model):
    for c in model.by_type("IfcClassification"):
        if c.Name == CLASSIFICATION_NAME:
            return c
    c = cl.add_classification(model, CLASSIFICATION_NAME)
    # its association to the project touches nothing key_relationships
    # sweeps, so it is keyed here (#80)
    for rel in c.ClassificationForObjects or ():
        stable_ids.assign(model, rel, f"rel/{rel.is_a()}/IfcClassification:{c.Name}")
    return c


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
                             work_hours_per_day: float = 8.0,
                             currency: str | None = None) -> CostEmbedReport:
    """Author cost + labor onto the open IFC in place; return a CostEmbedReport.

    `currency` is the cost values' (ensure_currency: the file's, else USD)."""
    name = schedule_name or sched.name or "Schedule"
    loaded = load_schedule_costs(sched, costs,
                                 work_hours_per_day=work_hours_per_day)
    task_codes = distribute_to_task_codes(sched, costs)
    cost_name, crew_prefix = f"{name} cost", f"{name}: "
    check_currency(model, currency)
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

    cs = add_declared_cost_schedule(model, name=cost_name,
                                    predefined_type="BUDGET", status=PLANNED,
                                    currency=currency)
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
        # one item per (task, code): two tasks may share a code
        stable_ids.assign(model, ci, f"cost-item/{cost_name}/{tid}/{code}")
        # the code's split by kind (top-level kinds, or the reader's
        # `categories`), scaled to this task's part of the code; a balance
        # the kinds do not cover stays uncategorised, so the total holds
        split = normalize_split(split_of(costs.get(code) or {}))
        write_cost_values(model, ci, e["cost"], split_amount(
            e["cost"], split, scale_from=(costs.get(code) or {}).get("cost")))
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

    # one labor crew per task (hours summed across the task's codes); the
    # StandardWork TimeValue is hours, and the file says so (hours_unit)
    hour = None
    if any(load["labor_hours"] > 0 for load in loaded.by_task.values()):
        hour = hours_unit(model)
    for tid, load in loaded.by_task.items():
        if load["labor_hours"] <= 0:
            continue
        st, ent = _entity(tid)
        if ent is None:
            missing.add(tid)
            continue
        crew = res.add_resource(model, ifc_class="IfcLaborResource",
                                name=f"{name}: {st.name if st else tid}")
        stable_ids.assign(model, crew, f"crew/{name}/{tid}")
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
        if hour is not None:
            q.Unit = hour
        res.assign_resource(model, relating_resource=crew, related_object=ent)
        report.resources += 1

    report.tasks_without_entity = sorted(missing)
    report.total_cost = loaded.total_cost
    report.total_labor_hours = loaded.total_labor_hours
    stable_ids.key_relationships(model)
    return report
