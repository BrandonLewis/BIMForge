"""Cost- & resource-load a CanonicalSchedule (5D spec).

Duration-weights each bid item's cost and labor-hours across its mapped tasks,
uniform per work-day and calendar-aware, into a LoadedSchedule: per-day totals
rolled to ISO-week and month buckets, a cumulative S-curve, peak crew, per-task
aggregates (for the IFC embed), and both-ways coverage reports. Pure stdlib;
consumers are `est-schedule costload` (render) and `est-bim cost5d` (embed).
`estimating_tools.schedule.costload` re-exports this module beside the
estimate-side derivation (`derive_costs`, `tie_out`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from bimforge.bim.schedule_model import CanonicalSchedule, ScheduleTask


def _d(iso: str) -> date:
    return date.fromisoformat(iso[:10])


def validate_costs(costs) -> None:
    """Raise ValueError if `costs` is not shaped
    `{code: {"cost": number, "labor_hours": number | null,
    "unit_price"?: number | {item#: number}, "unit"?: string | {item#: string}}}`.

    The CLIs call this at the file boundary so a malformed cost record produces
    a clean one-line error instead of a KeyError/TypeError traceback out of the
    distribution math.
    """
    if not isinstance(costs, dict):
        raise ValueError("costs must be a JSON object "
                         "{code: {cost, labor_hours, unit_price?, unit?}}")

    def _num(x):
        return isinstance(x, (int, float)) and not isinstance(x, bool)

    for code, rec in costs.items():
        if not isinstance(rec, dict) or "cost" not in rec:
            raise ValueError(f"costs['{code}'] must be an object with a 'cost'")
        if not isinstance(rec["cost"], (int, float)) or isinstance(rec["cost"], bool):
            raise ValueError(f"costs['{code}']['cost'] must be a number")
        hours = rec.get("labor_hours")
        if hours is not None and (not isinstance(hours, (int, float))
                                  or isinstance(hours, bool)):
            raise ValueError(
                f"costs['{code}']['labor_hours'] must be a number or null")
        up = rec.get("unit_price")
        if up is not None:
            ok = _num(up) or (isinstance(up, dict) and up
                              and all(_num(v) for v in up.values()))
            if not ok:
                raise ValueError(
                    f"costs['{code}']['unit_price'] must be a number or an "
                    f"object of item_number -> number")
        cu = rec.get("unit")
        if cu is not None:
            ok = isinstance(cu, str) or (isinstance(cu, dict) and cu
                                         and all(isinstance(v, str)
                                                 for v in cu.values()))
            if not ok:
                raise ValueError(
                    f"costs['{code}']['unit'] must be a string or an "
                    f"object of item_number -> string")


def _workdays(sched: CanonicalSchedule, task: ScheduleTask) -> list[date]:
    """Calendar work-days in [start, finish] inclusive, honoring the schedule's
    work_weekdays (0=Mon..6=Sun) and holidays. Empty when the task has no dates."""
    if not task.start or not task.finish:
        return []
    start, finish = _d(task.start), _d(task.finish)
    if finish < start:
        return []
    work = set(sched.work_weekdays)
    holidays = {_d(h) for h in sched.holidays}
    out: list[date] = []
    cur = start
    while cur <= finish:
        if cur.weekday() in work and cur not in holidays:
            out.append(cur)
        cur += timedelta(days=1)
    return out


@dataclass
class Coverage:
    unloaded_cost: dict[str, float] = field(default_factory=dict)  # priced, no live task
    no_hours_items: list[str] = field(default_factory=list)        # cost but labor None
    unpriced_tasks: list[str] = field(default_factory=list)        # task codes not priced


def distribute_to_tasks(sched: CanonicalSchedule, costs: dict[str, dict]):
    """Return ({task_id: {"cost", "labor_hours"}}, Coverage).

    Duration-weighted, uniform per work-day: a code's cost/hours split across
    its mapped tasks in proportion to each task's work-day count. Per task with
    W of the code's T total work-days, share = amount * W / T. A task carrying
    several codes sums each code's share. labor_hours contributes 0 when the
    code's hours are None (still counted as cost). See spec decision 2/5.
    """
    wd = {t.id: _workdays(sched, t) for t in sched.tasks}
    loads = {t.id: {"cost": 0.0, "labor_hours": 0.0} for t in sched.tasks}
    cov = Coverage()

    priced = set(costs)
    for t in sched.tasks:
        if t.bid_item_codes and not (set(t.bid_item_codes) & priced):
            cov.unpriced_tasks.append(t.id)

    for code, rec in costs.items():
        tasks_for = [t for t in sched.tasks if code in t.bid_item_codes]
        total_wd = sum(len(wd[t.id]) for t in tasks_for)
        if total_wd == 0:
            cov.unloaded_cost[code] = cov.unloaded_cost.get(code, 0.0) + float(rec["cost"])
            continue
        hours = rec.get("labor_hours")
        if hours is None:
            cov.no_hours_items.append(code)
        for t in tasks_for:
            w = len(wd[t.id])
            if not w:
                continue
            loads[t.id]["cost"] += float(rec["cost"]) * w / total_wd
            if hours is not None:
                loads[t.id]["labor_hours"] += float(hours) * w / total_wd
    cov.no_hours_items.sort()
    cov.unpriced_tasks.sort()
    return loads, cov


def distribute_to_task_codes(sched: CanonicalSchedule, costs: dict[str, dict]):
    """Return {(task_id, code): {"cost", "labor_hours"}} — the per-(task, code)
    breakdown before `distribute_to_tasks` sums it across a task's codes.

    Same duration-weighted split (share = amount * task_workdays / code_total),
    kept per code so the IFC embed can author one classified IfcCostItem per
    (task, cost code) rather than blending a multi-code task into one figure.
    Codes mapped to no live task (zero total work-days) are omitted — they are
    the `unloaded_cost` `distribute_to_tasks` already reports.
    """
    wd = {t.id: _workdays(sched, t) for t in sched.tasks}
    out: dict[tuple[str, str], dict] = {}
    for code, rec in costs.items():
        tasks_for = [t for t in sched.tasks if code in t.bid_item_codes]
        total_wd = sum(len(wd[t.id]) for t in tasks_for)
        if total_wd == 0:
            continue
        hours = rec.get("labor_hours")
        for t in tasks_for:
            w = len(wd[t.id])
            if not w:
                continue
            e = out.setdefault((t.id, code), {"cost": 0.0, "labor_hours": 0.0})
            e["cost"] += float(rec["cost"]) * w / total_wd
            if hours is not None:
                e["labor_hours"] += float(hours) * w / total_wd
    return out


@dataclass
class PeriodLoad:
    period: str          # ISO week "2026-W33" or month "2026-08"
    start: str           # ISO date of first active work-day in the bucket
    end: str             # ISO date of last active work-day in the bucket
    cost: float
    cumulative_cost: float
    labor_hours: float
    avg_workers: float   # labor_hours / (active_work_days * work_hours_per_day)
    peak_workers: float  # max daily workers within the bucket


@dataclass
class LoadedSchedule:
    name: str
    work_hours_per_day: float
    total_cost: float
    total_labor_hours: float
    peak_workers: float
    peak_period: str                      # ISO week of the peak-crew day
    by_week: list[PeriodLoad] = field(default_factory=list)
    by_month: list[PeriodLoad] = field(default_factory=list)
    by_task: dict = field(default_factory=dict)      # {task_id: {"cost","labor_hours"}}
    unloaded_cost: dict = field(default_factory=dict)
    no_hours_items: list = field(default_factory=list)
    unpriced_tasks: list = field(default_factory=list)


def _week_key(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _month_key(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


def _bucketize(day_cost, day_hours, keyfn, hpd) -> list[PeriodLoad]:
    keys = sorted({keyfn(d) for d in set(day_cost) | set(day_hours)})
    days_by_key: dict[str, list[date]] = {}
    for d in set(day_cost) | set(day_hours):
        days_by_key.setdefault(keyfn(d), []).append(d)
    out: list[PeriodLoad] = []
    cum = 0.0
    for k in keys:
        days = sorted(days_by_key[k])
        cost = sum(day_cost.get(d, 0.0) for d in days)
        hours = sum(day_hours.get(d, 0.0) for d in days)
        cum += cost
        active = len(days)
        avg = hours / (active * hpd) if active else 0.0
        peak = max((day_hours.get(d, 0.0) / hpd for d in days), default=0.0)
        out.append(PeriodLoad(period=k, start=days[0].isoformat(),
                              end=days[-1].isoformat(), cost=cost,
                              cumulative_cost=cum, labor_hours=hours,
                              avg_workers=avg, peak_workers=peak))
    return out


def load_schedule_costs(sched: CanonicalSchedule, costs: dict[str, dict], *,
                        work_hours_per_day: float = 8.0) -> LoadedSchedule:
    if work_hours_per_day <= 0:
        raise ValueError("work_hours_per_day must be > 0")
    loads, cov = distribute_to_tasks(sched, costs)

    # per-day accumulation: a task's per-day rate is its total / its work-days.
    day_cost: dict[date, float] = {}
    day_hours: dict[date, float] = {}
    for t in sched.tasks:
        days = _workdays(sched, t)
        if not days:
            continue
        c = loads[t.id]["cost"] / len(days)
        h = loads[t.id]["labor_hours"] / len(days)
        for d in days:
            day_cost[d] = day_cost.get(d, 0.0) + c
            day_hours[d] = day_hours.get(d, 0.0) + h

    peak_workers, peak_period = 0.0, ""
    for d in sorted(day_hours):
        w = day_hours[d] / work_hours_per_day
        if w > peak_workers:
            peak_workers, peak_period = w, _week_key(d)

    return LoadedSchedule(
        name=sched.name,
        work_hours_per_day=work_hours_per_day,
        total_cost=sum(day_cost.values()),
        total_labor_hours=sum(day_hours.values()),
        peak_workers=peak_workers,
        peak_period=peak_period,
        by_week=_bucketize(day_cost, day_hours, _week_key, work_hours_per_day),
        by_month=_bucketize(day_cost, day_hours, _month_key, work_hours_per_day),
        by_task=loads,
        unloaded_cost=cov.unloaded_cost,
        no_hours_items=cov.no_hours_items,
        unpriced_tasks=cov.unpriced_tasks,
    )
