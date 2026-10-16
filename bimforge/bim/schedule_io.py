"""Schedule-format importers → CanonicalSchedule (4D staging spec).

GanttWarrior JSON, Primavera P6 XER, MS Project MSPDI and a serialized
CanonicalSchedule all land here. Nothing downstream knows what format a
schedule arrived in — `load_schedule` dispatches on the file, importers
normalize, and every importer validates before returning.

Lives in bimforge (moved from ``estimating_tools.schedule.importers``, which
re-exports it) so ``est-bim schedule`` / ``est-bim cost5d`` need nothing from
the estimating layer: bimforge owns the schedule domain end to end — model,
readers, 4D/5D embed and read-back.
"""
from __future__ import annotations

import json
from pathlib import Path

from bimforge.bim.schedule_model import (
    CanonicalSchedule, Dependency, ScheduleTask,
)


def from_ganttwarrior(doc: dict) -> CanonicalSchedule:
    """A GanttWarrior export dict → validated CanonicalSchedule.

    Field map: name/start_date verbatim; default_work_weekdays →
    work_weekdays; holidays verbatim; per task id/name/wbs verbatim,
    start_date→start, end_date→finish, duration_days, is_milestone,
    bid_item_codes (order preserved, duplicates removed), and
    dependencies {predecessor_id, dependency_type, lag_days} →
    Dependency(predecessor, type, lag_days). Presentation/tracking fields
    (status, color, progress, assigned_to, work_days, time_blocks, …) are
    deliberately dropped — the canonical model carries schedule structure,
    not Gantt UI state.

    `bid_item_codes` is structure, not presentation (#302). It is the join key
    every downstream surface needs, and dropping it failed silently: `est-bim
    schedule` assigned no IFC elements (no code → no IfcRelAssignsToProcess) and
    `cost5d`/`costload` reported every task unpriced even with the codes in
    `costs.json`. GanttWarrior 0.2 writes them; a pre-0.2 export has no such key
    and still loads, with `[]`.
    """
    if not isinstance(doc, dict) or "tasks" not in doc:
        raise ValueError("does not look like a GanttWarrior export "
                         "(no 'tasks' key) — wrong file?")
    tasks = []
    for t in doc.get("tasks") or []:
        deps = [Dependency(predecessor=d.get("predecessor_id", ""),
                           type=d.get("dependency_type", "FS"),
                           lag_days=float(d.get("lag_days", 0) or 0))
                for d in t.get("dependencies", []) or []]
        tasks.append(ScheduleTask(
            id=str(t.get("id", "")),
            name=t.get("name", ""),
            wbs=str(t.get("wbs", "")),
            start=t.get("start_date"),
            finish=t.get("end_date"),
            duration_days=t.get("duration_days"),
            is_milestone=bool(t.get("is_milestone", False)),
            # dict.fromkeys, not set(): element assignment walks the codes in
            # order, so a stable order keeps the IFC join reproducible.
            bid_item_codes=list(dict.fromkeys(
                str(c) for c in t.get("bid_item_codes") or [])),
            dependencies=deps,
        ))
    sched = CanonicalSchedule(
        name=doc.get("name", ""),
        start_date=doc.get("start_date"),
        work_weekdays=list(doc.get("default_work_weekdays", [0, 1, 2, 3, 4])),
        holidays=list(doc.get("holidays", [])),
        tasks=tasks,
    )
    sched.validate()
    return sched


# ---------------------------------------------------------------------------
# Primavera P6 .xer
# ---------------------------------------------------------------------------

# P6 predecessor-type -> CanonicalSchedule dependency type
_XER_PRED = {"PR_FS": "FS", "PR_SS": "SS", "PR_FF": "FF", "PR_SF": "SF"}
_XER_WORKDAY_HR = 8.0        # lag_hr_cnt -> days; P6 lag is calendar-hours


# The XER reader lives in `bimforge.bim.xer` (shared with the estimating
# layer's dump/bridge Excel profiles, #204): one reader, one parse.
from bimforge.bim.xer import parse_tables as _parse_xer_tables
from bimforge.bim.xer import xer_date as _xer_date


def from_xer(text: str) -> CanonicalSchedule:
    """A Primavera P6 XER export → validated CanonicalSchedule.

    Every activity becomes a task keyed by its P6 ``task_code``; each WBS
    node with descendants becomes a summary task (id ``W<wbs_id>``) so the
    hierarchy nests. WBS numbers are synthesized by ``seq_num`` order
    (``1``, ``1.1``, …); activities sit at ``<wbs>.<n>``. Dependencies keep
    only internal predecessors (those outside the export are dropped, not
    errored). Lag is ``lag_hr_cnt`` / 8 work-hours → days — approximate, but
    task Start/Finish dates (which drive the animation) are exact.
    P6 activity-code assignments (ACTVTYPE/ACTVCODE/TASKACTV) land on
    ``task.activity_codes`` as ``"<type>: <name>"`` labels.
    """
    tables = _parse_xer_tables(text)
    task_rows = tables.get("TASK")
    if not task_rows:
        raise ValueError("no TASK table in the XER — not a P6 activity export?")
    wbs = {w["wbs_id"]: w for w in tables.get("PROJWBS", [])}
    proj = (tables.get("PROJECT") or [{}])[0]

    # dotted WBS number per node (skip the project root, proj_node_flag=Y)
    children: dict[str, list[str]] = {}
    roots: list[str] = []
    for wid, w in wbs.items():
        if w.get("proj_node_flag") == "Y":
            continue
        parent = w.get("parent_wbs_id")
        if parent in wbs and wbs[parent].get("proj_node_flag") != "Y":
            children.setdefault(parent, []).append(wid)
        else:
            roots.append(wid)
    number: dict[str, str] = {}

    def _seq(wid: str) -> int:
        return int(wbs[wid].get("seq_num") or 0)

    def _walk(ids: list[str], prefix: str) -> None:
        for i, wid in enumerate(sorted(ids, key=_seq), 1):
            number[wid] = f"{i}" if not prefix else f"{prefix}.{i}"
            _walk(children.get(wid, []), number[wid])

    _walk(roots, "")

    code_of = {t["task_id"]: t["task_code"] for t in task_rows}

    # P6 activity codes: ACTVTYPE (the code type, e.g. "Subcontractor") →
    # ACTVCODE (the value, e.g. "SUB-A") → TASKACTV (task assignment).
    # Rendered "<type>: <name>" per assignment, in TASKACTV row order.
    actv_type = {r.get("actv_code_type_id"): (r.get("actv_code_type") or "")
                 for r in tables.get("ACTVTYPE", [])}
    actv_label: dict[str, str] = {}
    for r in tables.get("ACTVCODE", []):
        tname = actv_type.get(r.get("actv_code_type_id"), "")
        cname = r.get("actv_code_name") or r.get("short_name") or ""
        actv_label[r.get("actv_code_id", "")] = (
            f"{tname}: {cname}" if tname else cname)
    actv_of: dict[str, list[str]] = {}
    for r in tables.get("TASKACTV", []):
        label = actv_label.get(r.get("actv_code_id"))
        tid = r.get("task_id")
        if label and tid in code_of:
            actv_of.setdefault(code_of[tid], []).append(label)

    preds: dict[str, list[Dependency]] = {}
    for rel in tables.get("TASKPRED", []):
        tid, pid = rel.get("task_id"), rel.get("pred_task_id")
        if tid not in code_of or pid not in code_of:
            continue          # predecessor outside the export — drop it
        lag = float(rel.get("lag_hr_cnt") or 0) / _XER_WORKDAY_HR
        preds.setdefault(code_of[tid], []).append(Dependency(
            predecessor=code_of[pid],
            type=_XER_PRED.get(rel.get("pred_type"), "FS"),
            lag_days=round(lag, 4)))

    # a summary task per WBS node (all of them, so intermediate nodes with no
    # direct activities still nest their children and register as summaries)
    tasks: list[ScheduleTask] = [
        ScheduleTask(id=f"W{wid}", name=wbs[wid].get("wbs_name", ""), wbs=num)
        for wid, num in number.items()]
    per_node_count: dict[str, int] = {}
    for t in task_rows:
        wid = t.get("wbs_id")
        base = number.get(wid)
        per_node_count[wid] = per_node_count.get(wid, 0) + 1
        # activities under a known WBS nest at <wbs>.<n>; an activity whose
        # WBS is the project root (or absent) has no WBS and sits at the root
        wbs_num = f"{base}.{per_node_count[wid]}" if base else ""
        start = (_xer_date(t.get("act_start_date"))
                 or _xer_date(t.get("early_start_date"))
                 or _xer_date(t.get("target_start_date")))
        finish = (_xer_date(t.get("act_end_date"))
                  or _xer_date(t.get("early_end_date"))
                  or _xer_date(t.get("target_end_date")))
        is_ms = t.get("task_type") in ("TT_Mile", "TT_FinMile")
        if is_ms:                        # milestones carry a single date
            start = start or finish
            finish = finish or start
        dur = float(t.get("target_drtn_hr_cnt") or 0) / _XER_WORKDAY_HR
        tasks.append(ScheduleTask(
            id=t["task_code"], name=t.get("task_name", ""), wbs=wbs_num,
            start=start, finish=finish, duration_days=round(dur, 4) or None,
            is_milestone=is_ms, dependencies=preds.get(t["task_code"], []),
            activity_codes=list(actv_of.get(t["task_code"], []))))

    sched = CanonicalSchedule(
        name=proj.get("proj_short_name") or "P6 schedule",
        start_date=_xer_date(proj.get("plan_start_date")),
        tasks=tasks)
    sched.validate()
    return sched


# ---------------------------------------------------------------------------
# MS Project MSPDI (.xml — via MPXJ from a binary .mpp)
# ---------------------------------------------------------------------------

_MSP_NS = {"p": "http://schemas.microsoft.com/project"}
_MSP_LINK = {"0": "FF", "1": "FS", "2": "SF", "3": "SS"}
# LinkLag is tenths of a minute; /10 -> minutes, /60 -> hours, /8 -> work-days
_MSP_LAG_PER_DAY = 10 * 60 * _XER_WORKDAY_HR


def from_mspdi(data) -> CanonicalSchedule:
    """An MS Project MSPDI XML export → validated CanonicalSchedule.

    Tasks are keyed by MSPDI ``UID`` (stable predecessor anchor); ``Name``
    is display only. ``OutlineNumber`` is the dotted WBS verbatim, so
    hierarchy and summary detection come for free. The project summary task
    (UID 0) is dropped. Lag: ``LinkLag`` tenths-of-minutes at 8 h/day →
    days (approximate; Start/Finish drive the animation). Resource
    assignments (Resources/Assignments) land on ``task.resources`` as the
    assigned resource NAMES, in document order.

    Accepts ``bytes`` (preferred — ElementTree honors the XML prolog's
    encoding, and MSPDI exports are frequently UTF-16 on Windows) or
    ``str``. Raises if the document isn't MSPDI rather than returning an
    empty schedule.
    """
    import xml.etree.ElementTree as ET

    root = ET.fromstring(data)

    def _txt(el, tag):
        found = el.find(f"p:{tag}", _MSP_NS)
        return found.text if found is not None else None

    tasks_el = root.find("p:Tasks", _MSP_NS)
    if tasks_el is None or tasks_el.find("p:Task", _MSP_NS) is None:
        raise ValueError("no <Tasks> in the MS Project namespace — not an "
                         "MSPDI export? (convert a .mpp with MPXJ first)")

    # Resources UID→Name joined through Assignments TaskUID → resource NAMES
    # per task, in Assignments document order. Nameless resources are skipped.
    res_name = {_txt(r, "UID"): _txt(r, "Name")
                for r in root.findall("p:Resources/p:Resource", _MSP_NS)}
    assigns: dict[str, list[str]] = {}
    for a in root.findall("p:Assignments/p:Assignment", _MSP_NS):
        name = res_name.get(_txt(a, "ResourceUID"))
        if name:
            assigns.setdefault(_txt(a, "TaskUID"), []).append(name)

    tasks: list[ScheduleTask] = []
    for te in (tasks_el.findall("p:Task", _MSP_NS) if tasks_el is not None else []):
        uid = _txt(te, "UID")
        if uid is None or uid == "0":       # project summary row
            continue
        deps = []
        for link in te.findall("p:PredecessorLink", _MSP_NS):
            puid = _txt(link, "PredecessorUID")
            if not puid:
                continue
            lag = float(_txt(link, "LinkLag") or 0) / _MSP_LAG_PER_DAY
            deps.append(Dependency(
                predecessor=puid,
                type=_MSP_LINK.get(_txt(link, "Type") or "1", "FS"),
                lag_days=round(lag, 4)))
        start = (_txt(te, "Start") or "")[:10] or None
        finish = (_txt(te, "Finish") or "")[:10] or None
        tasks.append(ScheduleTask(
            id=uid, name=_txt(te, "Name") or "", wbs=_txt(te, "OutlineNumber") or "",
            start=start, finish=finish, is_milestone=_txt(te, "Milestone") == "1",
            dependencies=deps, resources=list(assigns.get(uid, []))))

    # drop predecessors outside the imported set (external links)
    known = {t.id for t in tasks}
    for t in tasks:
        t.dependencies = [d for d in t.dependencies if d.predecessor in known]

    sched = CanonicalSchedule(
        name=_txt(root, "Name") or "MS Project schedule",
        start_date=(_txt(root, "StartDate") or "")[:10] or None,
        tasks=tasks)
    sched.validate()
    return sched


def _looks_ganttwarrior(doc: dict) -> bool:
    """True iff the JSON carries GanttWarrior-specific keys."""
    if not isinstance(doc, dict):
        return False
    if "default_work_weekdays" in doc:
        return True
    for t in doc.get("tasks") or []:
        if not isinstance(t, dict):
            continue
        if "start_date" in t or "end_date" in t:
            return True
        for d in t.get("dependencies") or []:
            if isinstance(d, dict) and ("predecessor_id" in d
                                        or "dependency_type" in d):
                return True
    return False


def _looks_canonical(doc: dict) -> bool:
    """True iff the JSON carries CanonicalSchedule-specific task/calendar keys.

    Recognizes a serialized CanonicalSchedule (see `CanonicalSchedule.to_json`)
    so a round-tripped schedule — or one hand-authored in the canonical shape,
    as the 5D cost-load surfaces consume — loads without a GanttWarrior wrapper.
    """
    if not isinstance(doc, dict):
        return False
    if "work_weekdays" in doc:
        return True
    for t in doc.get("tasks") or []:
        if not isinstance(t, dict):
            continue
        # `duration_days` is deliberately NOT a marker: GanttWarrior tasks carry
        # it too, so it can't discriminate the two shapes. The canonical-only
        # keys below can.
        if any(k in t for k in ("start", "finish", "bid_item_codes",
                                "match_name_re", "match_ifc_class")):
            return True
        for d in t.get("dependencies") or []:
            if isinstance(d, dict) and ("predecessor" in d or "type" in d):
                return True
    return False


def load_schedule(path) -> CanonicalSchedule:
    """Load any supported schedule file into a CanonicalSchedule.

    Dispatch by extension: `.gw.json` → GanttWarrior; `.json` → a serialized
    CanonicalSchedule when it carries canonical keys (`start`/`finish`/
    `bid_item_codes`/`work_weekdays`, and no GanttWarrior markers), else
    GanttWarrior; `.xer` → Primavera P6 (read as cp1252, the XER encoding);
    `.xml` / `.mspdi` → MS Project MSPDI.
    """
    p = Path(path)
    name = p.name.lower()
    if name.endswith(".gw.json"):
        return from_ganttwarrior(json.loads(p.read_text(encoding="utf-8")))
    if name.endswith(".json"):
        doc = json.loads(p.read_text(encoding="utf-8"))
        if _looks_canonical(doc) and not _looks_ganttwarrior(doc):
            sched = CanonicalSchedule.from_dict(doc)
            sched.validate()
            return sched
        return from_ganttwarrior(doc)
    if name.endswith(".xer"):
        return from_xer(p.read_text(encoding="cp1252"))
    if name.endswith(".mspdi") or name.endswith(".xml"):
        # bytes so ElementTree honors the prolog encoding (often UTF-16)
        return from_mspdi(p.read_bytes())
    raise ValueError(f"unsupported schedule format: {p.name} "
                     f"(supported: .gw.json/.json GanttWarrior, .xer P6, "
                     f".xml/.mspdi MS Project)")
