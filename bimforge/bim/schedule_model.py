"""CanonicalSchedule — the 4D staging interchange (4D staging spec, slice 1).

One schedule shape regardless of source format (GanttWarrior JSON, P6 XER,
MSPDI — `bimforge.bim.schedule_io` normalizes each, and
`schedule_read.read_schedule` reads one back out of a 4D IFC): a project
calendar (work weekdays + holidays), optional named task calendars with
recurring blackouts, and tasks carrying WBS, schedule dates, typed
dependencies, and the `bid_item_codes` that join a task to IFC elements
through the classification-code spine (see docs/ifc-takeoff-contract.md —
the same key, pointed the other way). Pure stdlib.

bimforge owns 4D in both directions (issue #335): `schedule4d.embed_schedule`
writes this shape into an IfcWorkSchedule and `schedule_read.read_schedule`
is its inverse. `estimating_tools.schedule.model` re-exports this module.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date

DEP_TYPES = ("FS", "SS", "FF", "SF")

_MONTH_DAY = re.compile(r"^(\d{2})-(\d{2})$")


def parse_month_day(value: str) -> tuple[int, int]:
    """A blackout bound "MM-DD" -> (month, day); ValueError when malformed.

    Validated against a leap year, so "02-29" is a legal bound.
    """
    m = _MONTH_DAY.match(str(value))
    if not m:
        raise ValueError(f"blackout bound must be MM-DD, got {value!r}")
    month, day = int(m.group(1)), int(m.group(2))
    date(2000, month, day)          # raises ValueError on 13-01, 04-31, ...
    return month, day


@dataclass
class Calendar:
    """A named task calendar (issue #335).

    `blackouts` are yearly-recurring closed windows, each
    `{"from": "MM-DD", "to": "MM-DD"}` inclusive. A window whose `to` is
    earlier than its `from` wraps the year end (`10-02`..`05-31` is the
    closed season around an in-water window of Jun 1 - Oct 1).
    """
    work_weekdays: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])
    holidays: list[str] = field(default_factory=list)
    blackouts: list[dict] = field(default_factory=list)


@dataclass
class Dependency:
    predecessor: str                 # ScheduleTask.id
    type: str = "FS"
    lag_days: float = 0.0


@dataclass
class ScheduleTask:
    id: str
    name: str
    wbs: str = ""
    start: str | None = None         # ISO YYYY-MM-DD (schedule dates)
    finish: str | None = None
    duration_days: float | None = None
    is_milestone: bool = False
    dependencies: list[Dependency] = field(default_factory=list)
    # R8 scope filter — predecessors that intentionally point OUTSIDE this
    # schedule (the GC ties a filtered sub-scope must not lose: they carry
    # the float/GC-delay exposure). Same Dependency shape; `validate()`
    # checks their types but skips existence/cycle checks. Serialized only
    # when non-empty, so pre-R8 canonical JSON round-trips unchanged.
    external_dependencies: list[Dependency] = field(default_factory=list)
    bid_item_codes: list[str] = field(default_factory=list)
    # R8 sub-scope filter keys — source-schedule metadata the scope filter
    # selects on. `resources` are assigned resource NAMES (MSPDI Resources/
    # Assignments); `activity_codes` are P6 activity-code labels rendered
    # "<type>: <name>" (XER ACTVTYPE/ACTVCODE/TASKACTV). Both serialize only
    # when non-empty, so pre-R8 canonical JSON round-trips unchanged.
    resources: list[str] = field(default_factory=list)
    activity_codes: list[str] = field(default_factory=list)
    # slice 5 — assign IFC elements to this task by element-Name regex and/or
    # IFC class, for models that carry no classification codes (parametric
    # builders, Revit/Tekla exports). Any of the three matchers assigns.
    match_name_re: str | None = None
    match_ifc_class: str | None = None
    # issue #335 — what a 4D IFC carries beyond dates and links. All
    # optional and serialized only when set, so earlier canonical JSON
    # round-trips unchanged.
    global_id: str | None = None     # the IfcTask GlobalId, for write-back
    task_type: str | None = None     # IfcTask PredefinedType: CONSTRUCTION, ...
    # owner bid item NUMBERS ("67") — distinct from bid_item_codes, which
    # join to element classification codes; covers tasks with no elements
    bid_items: list[str] = field(default_factory=list)
    notes: str = ""                  # IfcTask.Description: duration basis etc.
    calendar: str | None = None      # a CanonicalSchedule.calendars key;
                                     # None = the project calendar


@dataclass
class CanonicalSchedule:
    name: str
    start_date: str | None = None
    work_weekdays: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])
    holidays: list[str] = field(default_factory=list)
    tasks: list[ScheduleTask] = field(default_factory=list)
    calendars: dict[str, Calendar] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        # omit-when-empty: keep pre-R8 (and pre-#335) canonical JSON
        # byte-identical
        for t in d["tasks"]:
            for key in ("resources", "activity_codes", "external_dependencies",
                        "global_id", "task_type", "bid_items", "notes",
                        "calendar"):
                if not t[key]:
                    del t[key]
        if not d["calendars"]:
            del d["calendars"]
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict) -> "CanonicalSchedule":
        tasks = []
        for t in data.get("tasks") or []:
            deps = [Dependency(**d) for d in t.get("dependencies") or []]
            kwargs = {**t, "dependencies": deps}
            # absent (pre-R8 JSON) or null -> []
            kwargs["external_dependencies"] = [
                Dependency(**d) for d in t.get("external_dependencies") or []]
            kwargs["resources"] = list(t.get("resources") or [])
            kwargs["activity_codes"] = list(t.get("activity_codes") or [])
            kwargs["bid_items"] = [str(b) for b in t.get("bid_items") or []]
            kwargs["notes"] = t.get("notes") or ""
            tasks.append(ScheduleTask(**kwargs))
        calendars = {
            str(k): Calendar(
                work_weekdays=list(c.get("work_weekdays", [0, 1, 2, 3, 4])),
                holidays=list(c.get("holidays") or []),
                blackouts=[dict(b) for b in c.get("blackouts") or []])
            for k, c in (data.get("calendars") or {}).items()}
        return cls(
            name=data.get("name", ""),
            start_date=data.get("start_date"),
            work_weekdays=list(data.get("work_weekdays", [0, 1, 2, 3, 4])),
            holidays=list(data.get("holidays", [])),
            tasks=tasks,
            calendars=calendars,
        )

    @classmethod
    def from_json(cls, text: str) -> "CanonicalSchedule":
        return cls.from_dict(json.loads(text))

    # -- structure -----------------------------------------------------------
    def summary_ids(self) -> set[str]:
        """Tasks that are WBS parents of other tasks (roll-ups, not work).

        A WBS is a summary iff it is a dotted ancestor of some other WBS.
        Collect every ancestor by walking each WBS's own segments — O(n·depth)
        — rather than testing every prefix against every WBS (O(n²) on the
        thousand-task P6/MSPDI schedules slice 4 imports). Segment walking
        also avoids the ``1.1`` / ``1.11`` false-prefix bug.
        """
        ancestors: set[str] = set()
        for t in self.tasks:
            if not t.wbs:
                continue
            parts = t.wbs.split(".")
            for i in range(1, len(parts)):
                ancestors.add(".".join(parts[:i]))
        return {t.id for t in self.tasks if t.wbs and t.wbs in ancestors}

    # -- validation ----------------------------------------------------------
    def validate(self) -> None:
        """Raise ValueError on structural problems, before any consumer runs.

        Duplicate ids, finish-before-start, unknown/invalid dependencies,
        dependency cycles (the IFC embed would otherwise author a
        nonsensical IfcRelSequence graph), unknown task calendars, and
        malformed blackouts.
        """
        for cname, cal in self.calendars.items():
            for b in cal.blackouts:
                if not isinstance(b, dict) or set(b) != {"from", "to"}:
                    raise ValueError(f"calendar {cname!r}: a blackout is "
                                     f'{{"from": "MM-DD", "to": "MM-DD"}}, '
                                     f"got {b!r}")
                try:
                    parse_month_day(b["from"])
                    parse_month_day(b["to"])
                except ValueError as exc:
                    raise ValueError(f"calendar {cname!r}: {exc}") from None
        ids = [t.id for t in self.tasks]
        seen: set[str] = set()
        for tid in ids:
            if tid in seen:
                raise ValueError(f"duplicate task id: {tid}")
            seen.add(tid)
        for t in self.tasks:
            if t.start and t.finish and _d(t.finish) < _d(t.start):
                raise ValueError(f"task {t.id} ({t.wbs}): finish before start "
                                 f"({t.finish} < {t.start})")
            for dep in t.dependencies:
                if dep.type not in DEP_TYPES:
                    raise ValueError(f"task {t.id}: dependency type must be one "
                                     f"of {DEP_TYPES}, got {dep.type!r}")
                if dep.predecessor not in seen:
                    raise ValueError(f"task {t.id}: unknown predecessor "
                                     f"{dep.predecessor!r}")
            if t.calendar is not None and t.calendar not in self.calendars:
                raise ValueError(f"task {t.id}: unknown calendar "
                                 f"{t.calendar!r} (have: "
                                 f"{sorted(self.calendars) or 'none'})")
            # external deps deliberately point outside the schedule (R8 scope
            # filter) — validate the type, skip existence/cycle checks
            for dep in t.external_dependencies:
                if dep.type not in DEP_TYPES:
                    raise ValueError(f"task {t.id}: external dependency type "
                                     f"must be one of {DEP_TYPES}, "
                                     f"got {dep.type!r}")
        self._check_cycles()

    def _check_cycles(self) -> None:
        preds = {t.id: [d.predecessor for d in t.dependencies] for t in self.tasks}
        WHITE, GREY, BLACK = 0, 1, 2
        state = dict.fromkeys(preds, WHITE)

        def visit(tid: str, trail: list[str]) -> None:
            state[tid] = GREY
            for p in preds[tid]:
                if state[p] == GREY:
                    raise ValueError(
                        "dependency cycle: " + " -> ".join(trail + [tid, p]))
                if state[p] == WHITE:
                    visit(p, trail + [tid])
            state[tid] = BLACK

        for tid in preds:
            if state[tid] == WHITE:
                visit(tid, [])


def _d(iso: str) -> date:
    return date.fromisoformat(iso[:10])


# ---------------------------------------------------------------------------
# task -> bid item code resolution (spec decision 2; the BM-estimate join
# proposal is skill-layer judgment, not done here)
# ---------------------------------------------------------------------------

@dataclass
class MapReport:
    mapped: list[str] = field(default_factory=list)      # task ids with codes
    unmapped: list[str] = field(default_factory=list)    # LEAF ids without
    summaries: list[str] = field(default_factory=list)   # roll-ups (exempt)


def resolve_bid_item_codes(sched: CanonicalSchedule, *,
                           task_map: dict | None = None,
                           name_code_re: str | None = None) -> MapReport:
    """Fill each task's join to IFC elements; report the outcome, drop nothing.

    Precedence per task: explicit task_map entry (keyed by task id, then by
    WBS — REPLACES anything present), else codes extracted from the task
    name by `name_code_re` (first capture group per match, or the whole
    match) APPENDED to importer-carried codes. Order-preserving dedupe.

    A task_map value may be a list of bid item codes (`["510120", …]`) or a
    dict of matchers for code-less models (slice 5):
    `{"codes": [...], "name_re": "^RW\\d", "ifc_class": "IfcPile"}` — any key
    optional; the dict form sets `match_name_re` / `match_ifc_class` too.

    Summary (WBS-parent) tasks are reported separately, never "unmapped" —
    work maps at the leaves. A leaf is "mapped" if it has any matcher (code,
    name regex, or IFC class).
    """
    task_map = task_map or {}
    pattern = re.compile(name_code_re) if name_code_re else None
    report = MapReport()
    summaries = sched.summary_ids()
    for t in sched.tasks:
        explicit = task_map.get(t.id, task_map.get(t.wbs))
        if isinstance(explicit, dict):
            t.bid_item_codes = list(explicit.get("codes") or [])
            t.match_name_re = explicit.get("name_re")
            t.match_ifc_class = explicit.get("ifc_class")
        elif explicit is not None:
            # explicit map REPLACES anything present: a bare code list also
            # clears any pre-existing name/class selectors (precedence above).
            t.bid_item_codes = list(explicit)
            t.match_name_re = None
            t.match_ifc_class = None
        elif pattern:
            found = [m.group(1) if m.groups() else m.group(0)
                     for m in pattern.finditer(t.name)]
            t.bid_item_codes = list(t.bid_item_codes) + found
        t.bid_item_codes = list(dict.fromkeys(t.bid_item_codes))
        if t.id in summaries:
            report.summaries.append(t.id)
        elif t.bid_item_codes or t.match_name_re or t.match_ifc_class:
            report.mapped.append(t.id)
        else:
            report.unmapped.append(t.id)
    return report
