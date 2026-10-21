"""Read embedded 4D schedule data back out of an IFC (4D staging spec, slice 3).

The inverse of `schedule4d.embed_schedule`, but read-only and dependency-light:
plain ifcopenshell entity access, no `ifcopenshell.api.sequence` (so the KML
writer can import this without pulling the sequence API's optional deps). Used
to stamp each element's KML `TimeSpan` from its task's ScheduleStart, and
(issue #335) to read a whole 4D/5D model back: `read_schedule` returns the
CanonicalSchedule, `task_elements` the task -> element links, and
`read_costs` the per-task costs and labor cost5d embedded — all keyed by the
same task ids — so a consumer never parses IFC itself.
"""
from __future__ import annotations

import re
from datetime import date, timedelta


def element_start_dates(model) -> dict[int, str]:
    """Map each scheduled element's entity id → earliest task ScheduleStart.

    Walks `IfcRelAssignsToProcess` (task → products, authored by slice 2)
    and `IfcRelAssignsToProduct` (product ← task, the output form), reads
    the task's `IfcTaskTime.ScheduleStart`, and keeps the earliest
    date (`YYYY-MM-DD`) per element when several tasks touch it. Elements no
    task schedules simply don't appear — the caller leaves them untimed
    (always visible).
    """
    starts: dict[int, str] = {}

    def stamp(task, objs):
        if not (task and task.is_a("IfcTask") and task.TaskTime):
            return
        raw = getattr(task.TaskTime, "ScheduleStart", None)
        if not raw:
            return
        day = str(raw)[:10]          # "2026-07-10T09:00:00" → "2026-07-10"
        for obj in objs:
            eid = obj.id()
            if eid not in starts or day < starts[eid]:
                starts[eid] = day

    for rel in model.by_type("IfcRelAssignsToProcess"):
        stamp(rel.RelatingProcess, rel.RelatedObjects or [])
    # outputs too (#335): models post-processed for Bonsai playback link
    # task -> element with IfcRelAssignsToProduct instead
    for rel in model.by_type("IfcRelAssignsToProduct"):
        if rel.RelatingProduct is not None:
            for task in rel.RelatedObjects or []:
                stamp(task, [rel.RelatingProduct])
    return starts


# ---------------------------------------------------------------------------
# read_schedule / task_elements — the inverse of schedule4d.embed_schedule
# (issue #335). Same discipline as above: plain entity access only.
# ---------------------------------------------------------------------------

# kept in step with schedule4d (not imported: that module pulls the
# sequence API this one deliberately avoids)
_SEQ_DEP = {"FINISH_START": "FS", "START_START": "SS",
            "FINISH_FINISH": "FF", "START_FINISH": "SF"}
# The current names, then the "Pset_"-prefixed ones models written by 0.1.88
# or earlier carry ("Pset_" is reserved for buildingSMART's standard sets).
_TASK_PSETS = ("Bimforge_Task", "Pset_BimforgeTask")
_BID_ITEM_CLASSIFICATION = "Owner bid items"
_CALENDAR_SEP = ": "
_BLACKOUT_PREFIX = "blackout "

# Task types under which a task builds its elements, so it may claim their
# quantities. DEMOLITION / DISMANTLE / REMOVAL / ... tasks never do.
CONSTRUCTIVE_TYPES = frozenset({"CONSTRUCTION", "INSTALLATION", "NOTDEFINED"})

_ISO_DUR = re.compile(
    r"^P(?:(?P<w>[\d.]+)W)?(?:(?P<d>[\d.]+)D)?"
    r"(?:T(?:(?P<h>[\d.]+)H)?(?:(?P<m>[\d.]+)M)?(?:(?P<s>[\d.]+)S)?)?$")


def _days(value, hours_per_day: float = 8.0) -> float | None:
    """An IfcDuration string as WORK days; None when unreadable.

    Weeks count five work days and time parts count `hours_per_day`, since
    embed writes work-time durations (DurationType WORKTIME).
    """
    m = _ISO_DUR.match(str(value or "").strip())
    if not m or not any(m.groupdict().values()):
        return None
    g = {k: float(v) if v else 0.0 for k, v in m.groupdict().items()}
    return (g["w"] * 5 + g["d"]
            + (g["h"] + g["m"] / 60 + g["s"] / 3600) / hours_per_day)


def _pset(obj, *names: str) -> dict | None:
    """The first of `names` the object carries, as {property: value}."""
    for name in names:
        got = _one_pset(obj, name)
        if got is not None:
            return got
    return None


def _one_pset(obj, name: str) -> dict | None:
    for rel in getattr(obj, "IsDefinedBy", None) or []:
        if not rel.is_a("IfcRelDefinesByProperties"):
            continue
        ps = rel.RelatingPropertyDefinition
        if ps.is_a("IfcPropertySet") and ps.Name == name:
            return {p.Name: (p.NominalValue.wrappedValue if p.NominalValue
                             else None)
                    for p in ps.HasProperties or []
                    if p.is_a("IfcPropertySingleValue")}
    return None


def task_id(task) -> str:
    """The canonical id of an IfcTask: what read_schedule and task_elements
    key on. The embed's TaskId property, else Identification, else Name."""
    ps = _pset(task, *_TASK_PSETS) or {}
    return str(ps.get("TaskId") or task.Identification or task.Name
               or task.GlobalId)


def _work_schedule(model, name: str | None):
    wss = list(model.by_type("IfcWorkSchedule"))
    if name is not None:
        hits = [w for w in wss if w.Name == name]
        if len(hits) == 1:
            return hits[0]
        if not hits:
            raise ValueError(f"no IfcWorkSchedule named {name!r} (have: "
                             f"{sorted(w.Name or '' for w in wss) or 'none'})")
        raise ValueError(f"{len(hits)} IfcWorkSchedules are named {name!r}")
    if len(wss) == 1:
        return wss[0]
    if not wss:
        raise ValueError("the IFC has no IfcWorkSchedule (is it a 4D model?)")
    raise ValueError(f"the IFC has {len(wss)} IfcWorkSchedules — pass a name "
                     f"(have: {sorted(w.Name or '' for w in wss)})")


def _children(obj) -> list:
    return [o for rel in getattr(obj, "IsNestedBy", None) or []
            for o in rel.RelatedObjects or [] if o.is_a("IfcTask")]


def _schedule_tasks(ws) -> list[tuple[object, object]]:
    """(task, parent task or None) in depth-first nesting order."""
    roots = [o for rel in ws.Controls or [] for o in rel.RelatedObjects or []
             if o.is_a("IfcTask")]
    out, seen = [], set()

    def walk(task, parent):
        if task.id() in seen:
            return
        seen.add(task.id())
        out.append((task, parent))
        for child in _children(task):
            walk(child, task)

    for root in roots:
        walk(root, None)
    return out


_NUMERIC_WBS = re.compile(r"^\d+(\.\d+)*$")


def _wbs_map(pairs) -> dict[int, str]:
    """entity id -> WBS: the embed's Wbs property, else from the tree.

    A file without the property (embedded before #335, or by another tool)
    keeps the Identifications when every one already reads as its node's
    WBS (numeric, and under its parent's), and otherwise numbers the whole
    nesting tree "1", "1.2", ... — never a mix, which could repeat a WBS.
    """
    positional: dict[int, str] = {}
    count: dict[int | None, int] = {}
    as_is = True
    for task, parent in pairs:
        pkey = parent.id() if parent is not None else None
        count[pkey] = count.get(pkey, 0) + 1
        head = positional.get(pkey) if pkey is not None else None
        positional[task.id()] = (f"{head}.{count[pkey]}" if head
                                 else str(count[pkey]))
        if _pset(task, *_TASK_PSETS) is None:
            ident = task.Identification or ""
            want_head = parent.Identification if parent is not None else None
            got_head = ident.rsplit(".", 1)[0] if "." in ident else None
            if not (_NUMERIC_WBS.match(ident) and got_head == want_head):
                as_is = False
    out = {}
    for task, _ in pairs:
        ps = _pset(task, *_TASK_PSETS)
        if ps is not None:
            out[task.id()] = str(ps.get("Wbs") or "")
        else:
            out[task.id()] = (task.Identification if as_is
                              else positional[task.id()])
    return out


def _day(value) -> str | None:
    return str(value)[:10] if value else None


def _calendar_of(task):
    for rel in getattr(task, "HasAssignments", None) or []:
        if rel.is_a("IfcRelAssignsToControl") and rel.RelatingControl \
                and rel.RelatingControl.is_a("IfcWorkCalendar"):
            return rel.RelatingControl
    return None


def _bid_items_of(task) -> list[str]:
    items = []
    for rel in getattr(task, "HasAssociations", None) or []:
        if not rel.is_a("IfcRelAssociatesClassification"):
            continue
        ref = rel.RelatingClassification
        src = getattr(ref, "ReferencedSource", None)
        if src and src.is_a("IfcClassification") \
                and src.Name == _BID_ITEM_CLASSIFICATION and ref.Identification:
            items.append(str(ref.Identification))
    return list(dict.fromkeys(items))


def _merge_days(days: set[tuple[int, int]]) -> list[dict]:
    """Blacked-out (month, day)s -> cyclic MM-DD windows (for unnamed
    patterns another tool wrote)."""
    year = [(m, d) for m in range(1, 13)
            for d in range(1, (31, 29, 31, 30, 31, 30,
                               31, 31, 30, 31, 30, 31)[m - 1] + 1)]
    flags = [md in days for md in year]
    if all(flags):
        return [{"from": "01-01", "to": "12-31"}]
    if not any(flags):
        return []
    start = flags.index(False)              # rotate so a run never straddles
    order = list(range(start, len(year))) + list(range(start))
    runs, cur = [], None
    for i in order:
        if flags[i]:
            cur = [i, i] if cur is None else [cur[0], i]
        elif cur is not None:
            runs.append(cur)
            cur = None
    if cur is not None:
        runs.append(cur)
    fmt = lambda i: f"{year[i][0]:02d}-{year[i][1]:02d}"  # noqa: E731
    return [{"from": fmt(a), "to": fmt(b)} for a, b in runs]


def _first_attr(ent, *names):
    info = ent.get_info(recursive=False, include_identifier=False)
    return next((info[n] for n in names if n in info), None)


def _read_calendar(cal) -> dict:
    """An IfcWorkCalendar -> {work_weekdays, holidays, blackouts}."""
    weekdays: list[int] = []
    for wt in cal.WorkingTimes or []:
        rp = wt.RecurrencePattern
        if rp and rp.RecurrenceType == "WEEKLY":
            weekdays += [int(d) - 1 for d in rp.WeekdayComponent or []]
    holidays: list[str] = []
    named: list[dict] = []
    loose: set[tuple[int, int]] = set()
    for et in cal.ExceptionTimes or []:
        rp = et.RecurrencePattern
        if rp is None:
            # IFC4 Start/Finish; IFC4X3 renamed them StartDate/FinishDate
            first = _first_attr(et, "Start", "StartDate")
            start = _day(first)
            finish = _day(_first_attr(et, "Finish", "FinishDate") or first)
            if start:
                d0, d1 = date.fromisoformat(start), date.fromisoformat(finish)
                while d0 <= d1 and len(holidays) < 10000:
                    holidays.append(d0.isoformat())
                    d0 += timedelta(days=1)
            continue
        if rp.RecurrenceType != "YEARLY_BY_DAY_OF_MONTH":
            continue
        name = et.Name or ""
        if name.startswith(_BLACKOUT_PREFIX) and ".." in name:
            frm, to = name[len(_BLACKOUT_PREFIX):].split("..", 1)
            window = {"from": frm, "to": to}
            if window not in named:
                named.append(window)
            continue
        for m in rp.MonthComponent or []:
            for d in rp.DayComponent or []:
                loose.add((int(m), int(d)))
    return {"work_weekdays": sorted(set(weekdays)),
            "holidays": sorted(set(holidays)),
            "blackouts": named + _merge_days(loose)}


def _task_type(task) -> str | None:
    t = task.PredefinedType
    if t == "USERDEFINED":
        return task.ObjectType or "USERDEFINED"
    if not t or t == "NOTDEFINED":
        return None
    return str(t)


def read_schedule(model, name: str | None = None):
    """Read an IfcWorkSchedule back into a CanonicalSchedule (issue #335).

    Picks the schedule named `name`, or the only one in the file. Task ids
    and WBS come from the embed's Bimforge_Task (or 0.1.88-and-earlier Pset_BimforgeTask), or else from
    Identification and the nesting tree; dates, duration, milestone, type,
    notes, calendar, owner bid items and GlobalId from the IfcTask;
    dependencies from IfcRelSequence (a predecessor outside the schedule
    becomes an external dependency). A model written before #335, or by
    another tool, reads with the newer fields empty — never an error.
    Element links are `task_elements`; bid_item_codes are an embed-time
    join and stay empty. The task map's selectors and filters
    (match_name_re / match_ifc_class / filter_name_re / filter_ifc_class)
    read back from Bimforge_Task (#365).
    """
    from bimforge.bim.schedule_model import (
        Calendar, CanonicalSchedule, Dependency, ScheduleTask)

    ws = _work_schedule(model, name)
    sname = ws.Name or ""
    project_name = f"{sname} calendar"
    project_cal = next((c for c in model.by_type("IfcWorkCalendar")
                        if c.Name == project_name), None)

    pairs = _schedule_tasks(ws)
    ids = {task.id(): task_id(task) for task, _ in pairs}
    wbs_of = _wbs_map(pairs)
    calendars: dict[str, Calendar] = {}
    tasks = []
    for task, _parent in pairs:
        tt = task.TaskTime
        duration = _days(getattr(tt, "ScheduleDuration", None)) if tt else None

        deps, external = [], []
        for rel in getattr(task, "IsSuccessorFrom", None) or []:
            pred = rel.RelatingProcess
            if pred is None:
                continue
            lag = 0.0
            lag_time = getattr(rel, "TimeLag", None)
            if lag_time is not None and lag_time.LagValue is not None \
                    and lag_time.LagValue.is_a("IfcDuration"):
                lag = _days(lag_time.LagValue.wrappedValue) or 0.0
            dep = Dependency(predecessor=ids.get(pred.id()) or task_id(pred),
                             type=_SEQ_DEP.get(rel.SequenceType, "FS"),
                             lag_days=lag)
            (deps if pred.id() in ids else external).append(dep)

        cal_key = None
        cal = _calendar_of(task)
        if cal is not None and cal != project_cal:
            cname = cal.Name or cal.GlobalId
            prefix = project_name + _CALENDAR_SEP
            cal_key = cname[len(prefix):] if cname.startswith(prefix) else cname
            if cal_key not in calendars:
                calendars[cal_key] = Calendar(**_read_calendar(cal))

        ps = _pset(task, *_TASK_PSETS) or {}
        tasks.append(ScheduleTask(
            id=ids[task.id()], name=task.Name or "", wbs=wbs_of[task.id()],
            match_name_re=ps.get("MatchNameRe") or None,
            match_ifc_class=ps.get("MatchIfcClass") or None,
            filter_name_re=ps.get("FilterNameRe") or None,
            filter_ifc_class=ps.get("FilterIfcClass") or None,
            start=_day(getattr(tt, "ScheduleStart", None)) if tt else None,
            finish=_day(getattr(tt, "ScheduleFinish", None)) if tt else None,
            duration_days=duration,
            is_milestone=bool(task.IsMilestone),
            dependencies=deps, external_dependencies=external,
            global_id=task.GlobalId, task_type=_task_type(task),
            bid_items=_bid_items_of(task), notes=task.Description or "",
            calendar=cal_key))

    # a named calendar no task uses still belongs to the schedule
    prefix = project_name + _CALENDAR_SEP
    for cal in model.by_type("IfcWorkCalendar"):
        cname = cal.Name or ""
        if cname.startswith(prefix) and cname[len(prefix):] not in calendars:
            calendars[cname[len(prefix):]] = Calendar(**_read_calendar(cal))

    # no calendar at all reads as the model default; an authored calendar
    # with no work days stays empty (embed writes no weekly pattern for it)
    project = (_read_calendar(project_cal) if project_cal is not None
               else {"work_weekdays": [0, 1, 2, 3, 4], "holidays": []})
    return CanonicalSchedule(
        name=sname, start_date=_day(ws.StartTime),
        work_weekdays=project["work_weekdays"],
        holidays=project["holidays"], tasks=tasks,
        calendars=dict(sorted(calendars.items())))


def task_elements(model, name: str | None = None) -> dict[str, list[dict]]:
    """Map task id -> the elements it is linked to (issue #335).

    Reads both directions a 4D model uses: inputs (`IfcRelAssignsToProcess`,
    what embed_schedule writes) and outputs (`IfcRelAssignsToProduct`, what
    Bonsai playback wants and post-processors convert to). Each link is
    `{"global_id", "name", "direction": "input" | "output"}`, in file order,
    with the same element+direction listed once. `name` limits the map to
    one IfcWorkSchedule's tasks (as read_schedule picks it); None reads
    every IfcTask. Ids are `task_id`, the ones read_schedule returns.
    """
    if name is not None:
        tasks = [t for t, _ in _schedule_tasks(_work_schedule(model, name))]
    else:
        tasks = list(model.by_type("IfcTask"))
    out: dict[str, list[dict]] = {}
    for task in tasks:
        links = out.setdefault(task_id(task), [])
        have = {(l["global_id"], l["direction"]) for l in links}  # noqa: E741
        links += [l for l in _links_of(task)  # noqa: E741
                  if (l["global_id"], l["direction"]) not in have]
    return out


def _links_of(task) -> list[dict]:
    """One IfcTask's element links, inputs then outputs, each listed once."""
    links, seen = [], set()

    def add(obj, direction):
        if not obj.is_a("IfcProduct"):
            return
        key = (obj.GlobalId, direction)
        if key in seen:
            return
        seen.add(key)
        links.append({"global_id": obj.GlobalId,
                      "name": obj.Name or obj.is_a(),
                      "direction": direction})

    for rel in getattr(task, "OperatesOn", None) or []:
        if rel.is_a("IfcRelAssignsToProcess"):
            for obj in rel.RelatedObjects or []:
                add(obj, "input")
    for rel in getattr(task, "HasAssignments", None) or []:
        if rel.is_a("IfcRelAssignsToProduct") and rel.RelatingProduct:
            add(rel.RelatingProduct, "output")
    return links


def schedule_links(model, schedule) -> dict[str, list[dict]]:
    """task_elements for a CanonicalSchedule, which may be a consumer's re-plan.

    When the IFC holds a work schedule of the same name, its tasks are read
    by id. Otherwise (a renamed re-plan) each task is found by its
    `global_id`, so a task id repeated in another of the file's schedules
    can never borrow that schedule's elements. A task with no global_id
    falls back to its id only when the file holds a single work schedule;
    with several, which one it means is ambiguous and this raises.
    """
    names = [ws.Name for ws in model.by_type("IfcWorkSchedule")]
    if schedule.name in names:
        return task_elements(model, schedule.name)
    out: dict[str, list[dict]] = {}
    by_id = None
    for t in schedule.tasks:
        ent = None
        if t.global_id:
            try:
                ent = model.by_guid(t.global_id)
            except RuntimeError:
                ent = None
            if ent is not None and not ent.is_a("IfcTask"):
                ent = None
        if ent is not None:
            out[t.id] = _links_of(ent)
            continue
        if len(names) > 1:
            raise ValueError(
                f"schedule {schedule.name!r} is not in the IFC and task "
                f"{t.id} matches no IfcTask by global_id; with {len(names)} "
                f"work schedules its links are ambiguous")
        if by_id is None:
            by_id = task_elements(model, names[0]) if names else {}
        out[t.id] = list(by_id.get(t.id, []))
    return out


# ---------------------------------------------------------------------------
# read_costs — the inverse of cost5d.embed_cost_and_resources (#335 §7)
# ---------------------------------------------------------------------------

_COST_ITEM_PSETS = ("Bimforge_CostItem",         # kept in step with cost5d
                    "Pset_BimforgeCostItem")
# estimate_model5d's per-activity set (its first cut named it with Pset_)
_ACTIVITY_PSETS = ("BidSheet_Activity", "Pset_BidSheetActivity")


def _number(value) -> float | None:
    if value is None:
        return None
    value = getattr(value, "wrappedValue", value)
    return float(value) if isinstance(value, (int, float)) else None


def _crew_hours(crew) -> float | None:
    """A labor resource's hours: ScheduleWork usage, else StandardWork."""
    usage = getattr(crew, "Usage", None)
    hours = _days(getattr(usage, "ScheduleWork", None), hours_per_day=1.0) \
        if usage is not None else None
    if hours is not None:
        return hours
    bq = getattr(crew, "BaseQuantity", None)
    return _number(getattr(bq, "TimeValue", None)) if bq is not None else None


def _leaf_cost_items(cs) -> list:
    """A cost schedule's priced cost items, in file order: its top-level
    items, with a parent that nests cost items replaced by its leaves.
    cost5d writes a flat list; estimate_model5d nests a valueless parent
    per bid item over its children, whose sum the parent is."""
    out = []

    def walk(ci):
        kids = [o for rel in getattr(ci, "IsNestedBy", None) or []
                for o in rel.RelatedObjects or [] if o.is_a("IfcCostItem")]
        if not kids:
            out.append(ci)
        for kid in kids:
            walk(kid)

    for rel in cs.Controls or []:
        for o in rel.RelatedObjects or []:
            if o.is_a("IfcCostItem"):
                walk(o)
    return out


def read_costs(model, name: str | None = None) -> dict:
    """Read 5D back out of an IFC (issue #335 §7).

    `name` is the 4D schedule's name, as read_schedule takes it (None = the
    file's only IfcWorkSchedule); the cost schedule is "<name> cost" and the
    crews "<name>: <task>", as cost5d writes them. Returns::

        {"schedule": name,
         "costs": {code: {"cost", "labor_hours"}},      # load_schedule_costs
         "tasks": {task_id: {"costs": {code: {"cost", "labor_hours"}},
                             "cost": total, "labor_hours": task hours}},
         "warnings": [...]}

    A task's `labor_hours` is its BidSheet_Activity Manhours when the
    task carries one (estimate_model5d, whose crews are shared across
    tasks), else the hours of its own crews (cost5d).

    Task ids are `task_id`'s, the ones read_schedule returns, so a consumer
    can start from a 5D model. `costs` sums the per-task records — the shape
    `load_schedule_costs` and `est-bim cost5d --costs` accept. A code whose
    hours are unknown everywhere has `labor_hours: null`.

    A parent cost item that nests others is read through its leaves
    (`estimate_model5d` nests share items under each bid item), so an
    item's children are never counted twice.

    Per-code hours come from each cost item's Bimforge_CostItem (0.1.88 and earlier: Pset_BimforgeCostItem). A model
    embedded before #335 has only the per-task crew: a single-code task's
    hours go to its code, and a multi-code task's are split by cost, with a
    warning, since the embed did not keep the split.
    """
    ws = _work_schedule(model, name)
    sname = ws.Name or ""
    cost_name = f"{sname} cost"
    css = [c for c in model.by_type("IfcCostSchedule") if c.Name == cost_name]
    if not css:
        raise ValueError(f"no IfcCostSchedule named {cost_name!r} — is this "
                         f"the 5D IFC (est-bim cost5d)?")
    if len(css) > 1:
        raise ValueError(f"{len(css)} IfcCostSchedules are named {cost_name!r}")

    in_schedule = {t.id() for t, _ in _schedule_tasks(ws)}
    warnings: list[str] = []
    tasks: dict[str, dict] = {}
    need_split: dict[str, list[str]] = {}

    def entry(tid):
        return tasks.setdefault(tid, {"costs": {}, "cost": 0.0,
                                      "labor_hours": None})

    for ci in _leaf_cost_items(css[0]):
        code = ci.Identification or ci.Name or ci.GlobalId
        value = sum(_number(cv.AppliedValue) or 0.0
                    for cv in ci.CostValues or [])
        linked = [o for rel in getattr(ci, "Controls", None) or []
                  for o in rel.RelatedObjects or [] if o.is_a("IfcTask")]
        ps = _pset(ci, *_COST_ITEM_PSETS)
        if not linked:
            warnings.append(f"cost item {code!r} (${value:,.2f}) is linked "
                            f"to no task — left out")
            continue
        task = linked[0]
        if task.id() not in in_schedule:
            warnings.append(f"cost item {code!r} is linked to a task outside "
                            f"schedule {sname!r} — left out")
            continue
        tid = task_id(task)
        rec = entry(tid)["costs"].setdefault(code, {"cost": 0.0,
                                                    "labor_hours": None})
        rec["cost"] += value
        tasks[tid]["cost"] += value
        if ps is None:              # embedded before #335: no per-code hours
            need_split.setdefault(tid, []).append(code)
            continue
        hours = _number(ps.get("LaborHours"))      # absent = unknown (null)
        if hours is not None:
            rec["labor_hours"] = (rec["labor_hours"] or 0.0) + hours

    crew_prefix = f"{sname}: "
    for task, _ in _schedule_tasks(ws):
        # estimate_model5d: the task's own total, since its crew is shared
        # by several tasks and carries no hours of its own. Older exports
        # (cost5d, one crew per task) fall through to the crew's hours.
        act = _pset(task, *_ACTIVITY_PSETS) or {}
        manhours = _number(act.get("Manhours"))
        if manhours is not None:
            entry(task_id(task))["labor_hours"] = manhours
            continue
        for rel in getattr(task, "HasAssignments", None) or []:
            crew = rel.RelatingResource if rel.is_a(
                "IfcRelAssignsToResource") else None
            if crew is None or not crew.is_a("IfcLaborResource") \
                    or not (crew.Name or "").startswith(crew_prefix):
                continue
            hours = _crew_hours(crew)
            if hours is None:
                continue
            e = entry(task_id(task))
            e["labor_hours"] = (e["labor_hours"] or 0.0) + hours

    # pre-#335 cost items: no per-code hours, so share out the crew's
    for tid, codes in need_split.items():
        e = tasks[tid]
        crew = e["labor_hours"]
        if crew is None:
            continue
        known = sum(e["costs"][c]["labor_hours"] or 0.0 for c in e["costs"]
                    if c not in codes)
        left = max(crew - known, 0.0)
        if len(codes) == 1:
            e["costs"][codes[0]]["labor_hours"] = left
            continue
        basis = sum(e["costs"][c]["cost"] for c in codes)
        for c in codes:
            share = e["costs"][c]["cost"] / basis if basis else 1 / len(codes)
            e["costs"][c]["labor_hours"] = left * share
        warnings.append(f"task {tid}: {left:g} crew hours split across codes "
                        f"{', '.join(codes)} by cost — the model predates "
                        f"per-code hours")

    costs: dict[str, dict] = {}
    for e in tasks.values():
        for code, rec in e["costs"].items():
            agg = costs.setdefault(code, {"cost": 0.0, "labor_hours": None})
            agg["cost"] += rec["cost"]
            if rec["labor_hours"] is not None:
                agg["labor_hours"] = (agg["labor_hours"] or 0.0) \
                    + rec["labor_hours"]
    return {"schedule": sname, "costs": dict(sorted(costs.items())),
            "tasks": tasks, "warnings": warnings}
