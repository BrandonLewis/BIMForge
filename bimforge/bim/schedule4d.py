"""Embed a CanonicalSchedule into an IFC as 4D data (4D staging spec, slice 2).

Authors one `IfcWorkSchedule` (idempotent by name), an `IfcTask` tree from
the WBS (`IfcRelNests`), `IfcTaskTime` schedule dates, an `IfcWorkCalendar`
from the canonical work-week + holidays, `IfcRelSequence` from dependencies
(with lag), and `IfcRelAssignsToProcess` linking each task to the elements
whose classification code is in the task's `bid_item_codes` — the same
classification-code spine `ifc_takeoff` reads (docs/ifc-takeoff-contract.md),
pointed the other way. Construction semantics only: elements appear at task
start and persist; the KML/KMZ TimeSpan writer (slice 3) reads these dates.

Issue #335 adds what a re-planning consumer needs back out: each task's
`Pset_BimforgeTask` (canonical TaskId + Wbs, since Identification carries the
wbs-or-id that cost5d and Bonsai key on), PredefinedType (task_type),
Description (notes), a ScheduleDuration, owner bid items as classification
references under `BID_ITEM_CLASSIFICATION`, and one IfcWorkCalendar per named
task calendar — its blackouts as yearly ExceptionTimes — assigned to its tasks
with IfcRelAssignsToControl. `schedule_read.read_schedule` is the inverse.

Deterministic authoring via `ifcopenshell.api.sequence`; no MCP, no network.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

import ifcopenshell.api.control as ctl
import ifcopenshell.api.pset as pset_api
import ifcopenshell.api.sequence as sq
import ifcopenshell.guid

from bimforge.bim.ifc_takeoff import classifications_of
from bimforge.bim.schedule_model import parse_month_day

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bimforge.bim.schedule_model import CanonicalSchedule

# CanonicalSchedule dependency codes -> IfcRelSequence.SequenceType
SEQ_TYPE = {"FS": "FINISH_START", "SS": "START_START",
            "FF": "FINISH_FINISH", "SF": "START_FINISH"}

# The IfcClassification a task's owner bid item numbers are referenced under
# (ScheduleTask.bid_items). Separate from the elements' pay-code system and
# cost5d's "Estimate cost codes", so no reader confuses the three.
BID_ITEM_CLASSIFICATION = "Owner bid items"

# The canonical task id and WBS. IfcTask.Identification keeps the wbs-or-id
# it always carried (cost5d and Bonsai key on it), so the id needs a home.
TASK_PSET = "Pset_BimforgeTask"

# Named task calendars are "<schedule> calendar: <key>"; the project calendar
# is "<schedule> calendar".
CALENDAR_SEP = ": "

# A blackout's yearly ExceptionTimes carry this name, so a reader rebuilds
# the window exactly rather than re-merging the days.
BLACKOUT_PREFIX = "blackout "

_MONTH_DAYS = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)   # leap year


@dataclass
class EmbedReport:
    schedule_name: str
    tasks: int = 0
    tasks_timed: int = 0
    sequences: int = 0
    assignments: int = 0                 # task->element assign_process calls
    calendars: int = 0                   # named task calendars authored
    bid_item_links: int = 0              # task->owner bid item references
    assigned_elements: int = 0           # distinct elements assigned
    codes_without_elements: list = field(default_factory=list)
    selectors_without_elements: list = field(default_factory=list)
    unscheduled_elements: list = field(default_factory=list)

    @property
    def unscheduled_element_count(self) -> int:
        return len(self.unscheduled_elements)


def _iso_date(value: str | None):
    return date.fromisoformat(value[:10]) if value else None


def _all_tasks(ws) -> list:
    """Every IfcTask under a work schedule: its roots and their nested tree."""
    out, stack = [], [o for rel in ws.Controls or []
                      for o in rel.RelatedObjects if o.is_a("IfcTask")]
    while stack:
        task = stack.pop()
        out.append(task)
        for rel in getattr(task, "IsNestedBy", None) or []:
            stack.extend(o for o in rel.RelatedObjects if o.is_a("IfcTask"))
    return out


def _detach_bid_items(model, task) -> None:
    """Unlink a task from its owner bid item references before it is removed.

    `sequence.remove_task` leaves classification associations alone, which
    would strand an IfcRelAssociatesClassification with no objects (an
    invalid file) on every re-run.
    """
    for assoc in list(getattr(task, "HasAssociations", None) or []):
        if not assoc.is_a("IfcRelAssociatesClassification"):
            continue
        ref = assoc.RelatingClassification
        src = getattr(ref, "ReferencedSource", None)
        if not (src and src.is_a("IfcClassification")
                and src.Name == BID_ITEM_CLASSIFICATION):
            continue
        others = [o for o in assoc.RelatedObjects if o != task]
        if others:
            assoc.RelatedObjects = others
            continue
        model.remove(assoc)
        if not model.get_inverse(ref):
            model.remove(ref)


def _remove_schedule_named(model, name: str) -> None:
    """Drop an existing schedule (and its tasks) so re-runs replace by name."""
    for ws in list(model.by_type("IfcWorkSchedule")):
        if ws.Name != name:
            continue
        for task in _all_tasks(ws):
            _detach_bid_items(model, task)
        for rel in ws.Controls or []:
            for task in list(rel.RelatedObjects):
                if task.is_a("IfcTask"):
                    sq.remove_task(model, task)
        sq.remove_work_schedule(model, ws)
    # this run authors "<name> calendar" and "<name> calendar: <key>"; drop
    # prior ones so re-runs don't leave orphan calendars (the schedule/tasks
    # above are already gone).
    project = f"{name} calendar"
    for cal in list(model.by_type("IfcWorkCalendar")):
        if cal.Name == project or (cal.Name or "").startswith(
                project + CALENDAR_SEP):
            sq.remove_work_calendar(model, cal)


def blackout_spans(frm: str, to: str) -> list[tuple[list[int], list[int]]]:
    """A yearly MM-DD..MM-DD window as (months, days) products, in order.

    IFC's YEARLY_BY_DAY_OF_MONTH pattern selects every day whose month is in
    MonthComponent AND whose day is in DayComponent, so one pattern can only
    hold a rectangle. A window is at most three: the partial first month,
    the whole months between, and the partial last month. A `to` before
    `frm` wraps the year end; `to` the day before `frm` is the whole year.
    """
    (m1, d1), (m2, d2) = parse_month_day(frm), parse_month_day(to)
    if (m2, d2) < (m1, d1):
        # wraps; m1 == m2 lists that month twice (its tail, then its head)
        months = list(range(m1, 13)) + list(range(1, m2 + 1))
    else:
        months = list(range(m1, m2 + 1))
    spans: list[tuple[list[int], list[int]]] = []
    full: list[int] = []
    last = len(months) - 1
    for i, m in enumerate(months):
        lo = d1 if i == 0 else 1
        hi = d2 if i == last else _MONTH_DAYS[m - 1]
        if lo == 1 and hi == _MONTH_DAYS[m - 1]:
            full.append(m)
            continue
        if full:
            spans.append((full, list(range(1, 32))))
            full = []
        spans.append(([m], list(range(lo, hi + 1))))
    if full:
        spans.append((full, list(range(1, 32))))
    return spans


def _add_calendar(model, cal_spec, name: str):
    """One IfcWorkCalendar: weekly work days, holidays, yearly blackouts.

    `cal_spec` is the CanonicalSchedule itself (the project calendar) or one
    of its named `Calendar`s — both carry work_weekdays and holidays.
    """
    cal = sq.add_work_calendar(model, name=name)
    if cal_spec.work_weekdays:
        wt = sq.add_work_time(model, cal, time_type="WorkingTimes")
        rp = sq.assign_recurrence_pattern(model, wt, recurrence_type="WEEKLY")
        # canonical weekdays are 0=Mon..6=Sun; IFC WeekdayComponent is 1=Mon..7=Sun
        sq.edit_recurrence_pattern(model, rp, attributes={
            "WeekdayComponent": [d + 1 for d in sorted(set(cal_spec.work_weekdays))]})
    for hol in cal_spec.holidays:
        d = _iso_date(hol)
        if d:
            et = sq.add_work_time(model, cal, time_type="ExceptionTimes")
            sq.edit_work_time(model, et, attributes={"Start": d, "Finish": d})
    for b in getattr(cal_spec, "blackouts", None) or []:
        label = f"{BLACKOUT_PREFIX}{b['from']}..{b['to']}"
        for months, days in blackout_spans(b["from"], b["to"]):
            et = sq.add_work_time(model, cal, time_type="ExceptionTimes")
            et.Name = label
            rp = sq.assign_recurrence_pattern(
                model, et, recurrence_type="YEARLY_BY_DAY_OF_MONTH")
            sq.edit_recurrence_pattern(model, rp, attributes={
                "MonthComponent": months, "DayComponent": days})
    return cal


def _task_type(model, value: str | None) -> tuple[str, str | None]:
    """(PredefinedType, ObjectType) for a canonical task_type.

    A type IfcTaskTypeEnum doesn't list is written USERDEFINED with the
    type in ObjectType, as IFC prescribes, and reads back unchanged.
    """
    if not value:
        return "NOTDEFINED", None
    allowed = _task_type_enum(model)
    v = value.upper()
    if v in allowed and v != "USERDEFINED":
        return v, None
    return "USERDEFINED", value


def _task_type_enum(model) -> set[str]:
    import ifcopenshell.ifcopenshell_wrapper as w
    schema = w.schema_by_name(model.schema_identifier)
    return set(schema.declaration_by_name("IfcTaskTypeEnum").enumeration_items())


def _bid_item_refs(model, sched: CanonicalSchedule, task_by_id: dict) -> int:
    """Associate each task with a reference per owner bid item; return links.

    One reference and one IfcRelAssociatesClassification per item number,
    shared by every task that pays it. Built directly rather than through
    `classification.add_reference`, which matches an existing reference by
    Identification alone and would splice tasks into an element's own pay-
    code association (see cost5d._code_reference).
    """
    tasks_by_item: dict[str, list] = defaultdict(list)
    for t in sched.tasks:
        for item in dict.fromkeys(t.bid_items):
            tasks_by_item[str(item)].append(task_by_id[t.id])
    if not tasks_by_item:
        return 0
    classif = next((c for c in model.by_type("IfcClassification")
                    if c.Name == BID_ITEM_CLASSIFICATION), None)
    if classif is None:
        classif = model.create_entity("IfcClassification",
                                      Name=BID_ITEM_CLASSIFICATION)
    links = 0
    for item, tasks in tasks_by_item.items():
        ref = model.create_entity("IfcClassificationReference",
                                  Identification=item, Name=item,
                                  ReferencedSource=classif)
        model.create_entity("IfcRelAssociatesClassification",
                            GlobalId=ifcopenshell.guid.new(),
                            RelatedObjects=tasks, RelatingClassification=ref)
        links += len(tasks)
    return links


def _set_global_id(model, ent, gid: str, tid: str) -> None:
    """Give an IfcTask the GlobalId a consumer read earlier (write-back)."""
    try:
        ok = len(gid) == 22 and ifcopenshell.guid.compress(
            ifcopenshell.guid.expand(gid)) == gid
    except Exception:          # noqa: BLE001 — any decode failure is "bad"
        ok = False
    if not ok:
        raise ValueError(f"task {tid}: global_id {gid!r} is not an IFC GlobalId")
    try:
        clash = model.by_guid(gid)
    except RuntimeError:
        clash = None
    if clash is not None and clash != ent:
        raise ValueError(f"task {tid}: global_id {gid} is already used by "
                         f"{clash.is_a()} '{getattr(clash, 'Name', '')}'")
    ent.GlobalId = gid


def embed_schedule(model, sched: CanonicalSchedule, *,
                   schedule_name: str | None = None) -> EmbedReport:
    """Author `sched` into the open IFC `model` in place; return an EmbedReport.

    The model is mutated (caller writes it). Re-running with the same name
    replaces the prior schedule. Nothing is dropped silently: task codes
    that match no element, and elements no task claims, are both
    reported.
    """
    sched.validate()
    name = schedule_name or sched.name or "Schedule"
    _remove_schedule_named(model, name)
    ws = sq.add_work_schedule(model, name=name,
                              start_time=_iso_date(sched.start_date))
    _add_calendar(model, sched, f"{name} calendar")

    # classification-code -> elements (code join), plus the full element set
    # for the name-regex / IFC-class matchers (slice 5)
    code_index: dict[str, list] = defaultdict(list)
    all_elements = list(model.by_type("IfcElement"))
    for el in all_elements:
        # every classification participates (issue #106): a furnish-and-drive
        # pile belongs to BOTH codes' tasks; same-code duplicates count once
        seen: set[str] = set()
        for cls in classifications_of(el):
            if cls["code"] and cls["code"] not in seen:
                seen.add(cls["code"])
                code_index[cls["code"]].append(el)

    # precompile task name regexes up front — a bad pattern fails loud
    import re
    name_res: dict[str, "re.Pattern"] = {}
    for t in sched.tasks:
        if t.match_name_re:
            try:
                name_res[t.id] = re.compile(t.match_name_re)
            except re.error as exc:
                raise ValueError(f"task {t.id}: invalid name_re "
                                 f"{t.match_name_re!r}: {exc}")

    report = EmbedReport(schedule_name=name)

    # tasks, parents before children (shallower WBS first)
    def depth(t):
        return len(t.wbs.split(".")) if t.wbs else 0

    task_by_id: dict[str, object] = {}
    task_by_wbs: dict[str, object] = {}
    for t in sorted(sched.tasks, key=depth):
        parent = None
        if t.wbs and "." in t.wbs:
            parent = task_by_wbs.get(t.wbs.rsplit(".", 1)[0])
        predefined, object_type = _task_type(model, t.task_type)
        ent = sq.add_task(model, work_schedule=(None if parent else ws),
                          parent_task=parent, name=t.name,
                          description=t.notes or None,
                          identification=t.wbs or t.id,
                          predefined_type=predefined)
        if object_type:
            ent.ObjectType = object_type
        if t.global_id:
            _set_global_id(model, ent, t.global_id, t.id)
        ps = pset_api.add_pset(model, product=ent, name=TASK_PSET)
        pset_api.edit_pset(model, pset=ps, properties={
            "TaskId": t.id, **({"Wbs": t.wbs} if t.wbs else {})})
        task_by_id[t.id] = ent
        if t.wbs:
            task_by_wbs[t.wbs] = ent
        report.tasks += 1
        if t.is_milestone:
            sq.edit_task(model, ent, attributes={"IsMilestone": True})

    # named task calendars, each assigned to the tasks that work to it
    for key, cal_spec in sched.calendars.items():
        cal = _add_calendar(model, cal_spec, f"{name} calendar{CALENDAR_SEP}{key}")
        users = [task_by_id[t.id] for t in sched.tasks if t.calendar == key]
        if users:
            ctl.assign_control(model, relating_control=cal,
                               related_objects=users)
        report.calendars += 1
    report.bid_item_links = _bid_item_refs(model, sched, task_by_id)

    # sequences (dependencies) — predecessor -> this task, with lag
    for t in sched.tasks:
        for dep in t.dependencies:
            rel = sq.assign_sequence(
                model, relating_process=task_by_id[dep.predecessor],
                related_process=task_by_id[t.id],
                sequence_type=SEQ_TYPE[dep.type])
            report.sequences += 1
            if dep.lag_days:
                # ISO-8601 duration; :g keeps a fractional day (P1.5D) and
                # drops the trailing .0 on whole days (P2D) — never truncate.
                sq.assign_lag_time(model, rel,
                                   lag_value=f"P{dep.lag_days:g}D",
                                   duration_type="WORKTIME")

    # task times: write ScheduleStart/Finish as raw IfcDateTime attributes,
    # NOT via sq.edit_task_time. That api wrapper cascades — it recomputes a
    # task's start from its predecessors' finish (keeping only the duration),
    # which silently overwrites the source schedule's own computed dates once
    # any IfcRelSequence exists. The source (P6/gw/MSP) already resolved the
    # CPM; we embed those dates verbatim.
    for t in sched.tasks:
        start, finish = _iso_date(t.start), _iso_date(t.finish)
        if not (start or finish or t.duration_days is not None):
            continue
        ent = task_by_id[t.id]
        tt = ent.TaskTime or sq.add_task_time(model, ent)
        if start:
            tt.ScheduleStart = f"{start.isoformat()}T00:00:00"
        if finish:
            tt.ScheduleFinish = f"{finish.isoformat()}T00:00:00"
        if t.duration_days is not None:
            # work days, as the lag is (:g keeps P1.5D, drops P2.0D)
            tt.ScheduleDuration = f"P{t.duration_days:g}D"
            tt.DurationType = "WORKTIME"
        if start and finish:
            report.tasks_timed += 1

    # product assignment: code join OR name-regex OR IFC class (slice 5)
    assigned: set = set()
    missing_codes: set = set()
    missing_selectors: list = []
    for t in sched.tasks:
        els: list = []
        for code in t.bid_item_codes:
            hit = code_index.get(code)
            if hit:
                els += hit
            else:
                missing_codes.add(code)
        rx = name_res.get(t.id)
        klass = t.match_ifc_class or None
        # a selector matches when EITHER the name regex OR the IFC class hits
        # (docstring: "any of the three matchers assigns"). is_a(str) is
        # subtype-aware and case-insensitive, so IfcWall catches
        # IfcWallStandardCase et al. — an exact entity check would miss them.
        if rx or klass:
            selector_hits = [
                el for el in all_elements
                if (rx and el.Name and rx.search(el.Name))
                or (klass and el.is_a(klass))]
            els += selector_hits
            if not selector_hits:
                parts = ([f"name_re={t.match_name_re!r}"] if rx else []) + \
                        ([f"ifc_class={t.match_ifc_class!r}"] if klass else [])
                missing_selectors.append(f"{t.name or t.id}: {', '.join(parts)}")
        seen: set = set()
        for el in els:                       # dedupe within the task
            if el.id() in seen:
                continue
            seen.add(el.id())
            sq.assign_process(model, relating_process=task_by_id[t.id],
                              related_object=el)
            report.assignments += 1
            assigned.add(el.id())
    report.assigned_elements = len(assigned)
    report.codes_without_elements = sorted(missing_codes)
    report.selectors_without_elements = missing_selectors
    # every element no task claims (code-less models schedule by name/class,
    # so "unscheduled" spans all elements, not only classified ones)
    report.unscheduled_elements = sorted(
        (el.Name or el.is_a()) for el in all_elements if el.id() not in assigned)
    return report
