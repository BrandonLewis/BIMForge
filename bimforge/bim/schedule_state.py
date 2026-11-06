"""What stands on a given day: the 4D state an IFC's embedded schedule gives.

Every IfcTask linked to an element (as an input, IfcRelAssignsToProcess,
which `est-bim schedule` writes, or an output, IfcRelAssignsToProduct, which
Bonsai playback reads) moves it by the task's type:

* CONSTRUCTION / INSTALLATION / NOTDEFINED (and no type): the element
  APPEARS at the task's ScheduleStart;
* DEMOLITION / DISMANTLE / DISPOSAL / REMOVAL: it DISAPPEARS at the start.

An element no task touches stands for the whole schedule (existing ground,
existing utilities, the bridge being removed until its removal task).
"Standing on day D" is the state at the end of D: built if its appear date
is on or before D, gone if its disappear date is.

Kept to ifcopenshell and the standard library; the IfcSection Blender
add-on (https://github.com/BrandonLewis/ifcsection) carries its own copy.

Examples:
    import ifcopenshell
    from bimforge.bim.schedule_state import element_spans, standing
    f = ifcopenshell.open("model.4d.ifc")
    spans = element_spans(f)
    up = [gid for gid, sp in spans.items() if standing(sp, "2027-06-15")]
"""
from __future__ import annotations

from typing import NamedTuple

APPEAR = frozenset({"CONSTRUCTION", "INSTALLATION", "NOTDEFINED"})
VANISH = frozenset({"DEMOLITION", "DISMANTLE", "DISPOSAL", "REMOVAL"})


class Span(NamedTuple):
    """One element's life in the schedule: ISO days, None = unbounded."""
    appear: str | None
    vanish: str | None
    tasks: tuple[str, ...]            # names of the tasks that move it


def _type(task) -> str:
    t = task.PredefinedType
    if t == "USERDEFINED":
        return (task.ObjectType or "USERDEFINED").upper()
    return str(t or "NOTDEFINED").upper()


def _start(task) -> str | None:
    tt = getattr(task, "TaskTime", None)
    raw = getattr(tt, "ScheduleStart", None) if tt else None
    return str(raw)[:10] if raw else None


def _links(task):
    for rel in getattr(task, "OperatesOn", None) or ():
        if rel.is_a("IfcRelAssignsToProcess"):
            yield from rel.RelatedObjects or ()
    for rel in getattr(task, "HasAssignments", None) or ():
        if rel.is_a("IfcRelAssignsToProduct") and rel.RelatingProduct:
            yield rel.RelatingProduct


def element_spans(f, tasks=None) -> dict[str, Span]:
    """GlobalId -> Span for every element some dated task moves.

    Several tasks on one element: it appears at the EARLIEST appearing task
    and vanishes at the earliest vanishing one. A task of another type
    (OPERATION, LOGISTIC, ...) or with no start date moves nothing.
    `tasks` limits the reading to those IfcTasks (one schedule's); None
    reads every task in the file.
    """
    appear: dict[str, str] = {}
    vanish: dict[str, str] = {}
    names: dict[str, list[str]] = {}
    for task in (f.by_type("IfcTask") if tasks is None else tasks):
        day, kind = _start(task), _type(task)
        if day is None or kind not in APPEAR | VANISH:
            continue
        side = appear if kind in APPEAR else vanish
        for obj in _links(task):
            if not obj.is_a("IfcProduct"):
                continue
            gid = obj.GlobalId
            if gid not in side or day < side[gid]:
                side[gid] = day
            names.setdefault(gid, [])
            if task.Name and task.Name not in names[gid]:
                names[gid].append(task.Name)
    return {gid: Span(appear.get(gid), vanish.get(gid), tuple(names[gid]))
            for gid in names}


def standing(span: Span | None, day: str) -> bool:
    """True when the element stands at the end of `day` (an ISO date)."""
    if span is None:
        return True
    if span.appear is not None and span.appear > day:
        return False
    return span.vanish is None or span.vanish > day


def state(span: Span | None, day: str) -> str:
    """'standing', 'not yet built' or 'removed' at the end of `day`."""
    if span is not None and span.appear is not None and span.appear > day:
        return "not yet built"
    if span is not None and span.vanish is not None and span.vanish <= day:
        return "removed"
    return "standing"


def event_days(spans: dict[str, Span]) -> list[str]:
    """Every day on which something appears or vanishes, sorted."""
    return sorted({d for sp in spans.values() for d in (sp.appear, sp.vanish)
                   if d is not None})


def shift_day(day: str, days: int) -> str:
    """`day` (ISO) moved by `days` calendar days."""
    from datetime import date, timedelta
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()
