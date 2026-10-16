from datetime import date
from bimforge.bim.schedule_model import CanonicalSchedule, ScheduleTask
from bimforge.bim import costload


def _sched(**kw):
    base = dict(name="S", work_weekdays=[0, 1, 2, 3, 4], holidays=[])
    base.update(kw)
    return CanonicalSchedule(**base)


def test_workdays_skips_weekends_and_holidays():
    sched = _sched(holidays=["2026-08-13"])  # a Thursday
    # Mon 2026-08-10 .. Fri 2026-08-14 inclusive
    t = ScheduleTask(id="1", name="Pour", start="2026-08-10", finish="2026-08-14")
    days = costload._workdays(sched, t)
    assert days == [date(2026, 8, 10), date(2026, 8, 11),
                    date(2026, 8, 12), date(2026, 8, 14)]  # Thu holiday dropped


def test_workdays_empty_when_no_dates():
    sched = _sched()
    assert costload._workdays(sched, ScheduleTask(id="1", name="x")) == []


def test_distribute_duration_weighted_across_tasks():
    # code "A" maps to two tasks: 4 work-days and 1 work-day (total 5).
    sched = _sched(tasks=[
        ScheduleTask(id="t4", name="big", start="2026-08-10", finish="2026-08-13",
                     bid_item_codes=["A"]),                       # Mon-Thu = 4 wd
        ScheduleTask(id="t1", name="small", start="2026-08-14", finish="2026-08-14",
                     bid_item_codes=["A"]),                       # Fri = 1 wd
    ])
    costs = {"A": {"cost": 5000.0, "labor_hours": 500.0}}
    loads, cov = costload.distribute_to_tasks(sched, costs)
    # cost split 4:1; hours split 4:1
    assert round(loads["t4"]["cost"], 2) == 4000.0
    assert round(loads["t1"]["cost"], 2) == 1000.0
    assert round(loads["t4"]["labor_hours"], 2) == 400.0
    assert round(loads["t1"]["labor_hours"], 2) == 100.0
    assert cov.unloaded_cost == {} and cov.no_hours_items == [] and cov.unpriced_tasks == []


def test_distribute_reports_coverage_both_ways():
    sched = _sched(tasks=[
        ScheduleTask(id="t1", name="lump", start="2026-08-10", finish="2026-08-10",
                     bid_item_codes=["A"]),          # A has cost, no hours
        ScheduleTask(id="t2", name="orphan", start="2026-08-11", finish="2026-08-11",
                     bid_item_codes=["Z"]),          # Z not priced
    ])
    costs = {"A": {"cost": 1000.0, "labor_hours": None},
             "B": {"cost": 700.0, "labor_hours": 40.0}}  # B mapped to no task
    loads, cov = costload.distribute_to_tasks(sched, costs)
    assert loads["t1"]["cost"] == 1000.0 and loads["t1"]["labor_hours"] == 0.0
    assert cov.no_hours_items == ["A"]
    assert cov.unloaded_cost == {"B": 700.0}
    assert cov.unpriced_tasks == ["t2"]


def test_load_schedule_costs_buckets_and_peak():
    # one code, one task Mon-Fri (5 wd), $10k, 400 hr, 8 hr/day
    sched = _sched(tasks=[ScheduleTask(id="t1", name="Pour", start="2026-08-10",
                                       finish="2026-08-14", bid_item_codes=["A"])])
    costs = {"A": {"cost": 10000.0, "labor_hours": 400.0}}
    loaded = costload.load_schedule_costs(sched, costs, work_hours_per_day=8.0)
    assert round(loaded.total_cost, 2) == 10000.0
    assert round(loaded.total_labor_hours, 2) == 400.0
    # 400 hr / 5 days = 80 hr/day / 8 = 10 workers/day, flat -> peak 10
    assert round(loaded.peak_workers, 2) == 10.0
    # single ISO week 2026-W33
    assert [p.period for p in loaded.by_week] == ["2026-W33"]
    wk = loaded.by_week[0]
    assert round(wk.cost, 2) == 10000.0 and round(wk.cumulative_cost, 2) == 10000.0
    assert round(wk.labor_hours, 2) == 400.0 and round(wk.peak_workers, 2) == 10.0
    assert loaded.by_task["t1"]["cost"] == 10000.0
    assert loaded.peak_period == "2026-W33"


def test_load_schedule_costs_rejects_bad_hours_per_day():
    import pytest
    with pytest.raises(ValueError):
        costload.load_schedule_costs(_sched(), {}, work_hours_per_day=0)


def test_validate_costs_rejects_malformed_shapes():
    import pytest
    costload.validate_costs({"A": {"cost": 1.0, "labor_hours": None}})  # ok
    costload.validate_costs({"A": {"cost": 1.0, "labor_hours": 5}})     # ok
    for bad in ([1, 2, 3],                          # not a dict
                {"A": 5},                           # value not a dict
                {"A": {"labor_hours": 5}},          # missing cost
                {"A": {"cost": "free"}},            # cost not a number
                {"A": {"cost": True}},              # bool is not a number
                {"A": {"cost": 1.0, "labor_hours": "lots"}}):  # hours not number/null
        with pytest.raises(ValueError):
            costload.validate_costs(bad)


def test_distribute_to_task_codes_keeps_per_code_detail():
    # code A spans two tasks (split 1:1); each task also has its own code.
    sched = _sched(tasks=[
        ScheduleTask(id="t1", name="T1", start="2026-08-10", finish="2026-08-14",
                     bid_item_codes=["A", "B"]),          # 5 wd
        ScheduleTask(id="t2", name="T2", start="2026-08-17", finish="2026-08-21",
                     bid_item_codes=["A", "C"]),          # 5 wd
    ])
    costs = {"A": {"cost": 10000.0, "labor_hours": 400.0},
             "B": {"cost": 5000.0, "labor_hours": None},
             "C": {"cost": 3000.0, "labor_hours": 100.0}}
    tc = costload.distribute_to_task_codes(sched, costs)
    # A splits 5000/5000 across its two tasks; B/C stay whole on their task
    assert round(tc[("t1", "A")]["cost"], 2) == 5000.0
    assert round(tc[("t2", "A")]["cost"], 2) == 5000.0
    assert round(tc[("t1", "B")]["cost"], 2) == 5000.0
    assert tc[("t1", "B")]["labor_hours"] == 0.0        # None -> 0
    assert round(tc[("t2", "C")]["cost"], 2) == 3000.0
    # summing per-code back to per-task matches distribute_to_tasks
    loads, _ = costload.distribute_to_tasks(sched, costs)
    assert round(sum(v["cost"] for (t, _c), v in tc.items() if t == "t1"), 2) \
        == round(loads["t1"]["cost"], 2)


def test_load_schedule_iso_week_year_boundary_and_multibucket_cumulative():
    # Mon 2025-12-29 .. Fri 2026-01-02: all ISO week 2026-W01, months split
    sched = _sched(tasks=[ScheduleTask(id="t1", name="span", start="2025-12-29",
                                       finish="2026-01-02", bid_item_codes=["A"])])
    costs = {"A": {"cost": 5000.0, "labor_hours": 200.0}}  # 5 wd -> $1000/day, 40 hr/day
    loaded = costload.load_schedule_costs(sched, costs, work_hours_per_day=8.0)
    # 2025-12-29 belongs to ISO week-year 2026, NOT 2025-W52
    assert [p.period for p in loaded.by_week] == ["2026-W01"]
    # months split 3 days (Dec) / 2 days (Jan)
    assert [p.period for p in loaded.by_month] == ["2025-12", "2026-01"]
    assert round(loaded.by_month[0].cost, 2) == 3000.0
    assert round(loaded.by_month[1].cost, 2) == 2000.0
    # cumulative is monotonic and the last bucket equals the total
    assert round(loaded.by_month[0].cumulative_cost, 2) == 3000.0
    assert round(loaded.by_month[1].cumulative_cost, 2) == 5000.0
    assert round(loaded.by_month[1].cumulative_cost, 2) == round(loaded.total_cost, 2)
    # avg workers in Dec bucket: 120 hr / (3 days * 8) = 5
    assert round(loaded.by_month[0].avg_workers, 2) == 5.0


def test_load_schedule_peak_exceeds_avg_on_overlap():
    # t1 spans the week; t2 spikes Wednesday -> that day carries two crews
    sched = _sched(tasks=[
        ScheduleTask(id="t1", name="base", start="2026-08-10", finish="2026-08-14",
                     bid_item_codes=["A"]),                 # Mon-Fri, 400 hr
        ScheduleTask(id="t2", name="spike", start="2026-08-12", finish="2026-08-12",
                     bid_item_codes=["B"]),                 # Wed only, 80 hr
    ])
    costs = {"A": {"cost": 1000.0, "labor_hours": 400.0},
             "B": {"cost": 100.0, "labor_hours": 80.0}}
    loaded = costload.load_schedule_costs(sched, costs, work_hours_per_day=8.0)
    wk = loaded.by_week[0]                                  # single week 2026-W33
    # t1 spreads 400 hr over 5 wd = 80/day; t2 spreads 80 hr over 1 wd = 80 on Wed.
    # Wed = 80 + 80 = 160 hr -> 20 workers; other days 80 hr -> 10 workers.
    # Week total = 480 hr, avg = 480 / (5 * 8) = 12.
    assert round(wk.peak_workers, 2) == 20.0
    assert round(wk.avg_workers, 2) == 12.0
    assert round(loaded.peak_workers, 2) == 20.0
    assert loaded.peak_period == "2026-W33"


def test_load_schedule_empty_is_zeros_not_error():
    loaded = costload.load_schedule_costs(_sched(), {}, work_hours_per_day=8.0)
    assert loaded.total_cost == 0.0 and loaded.total_labor_hours == 0.0
    assert loaded.by_week == [] and loaded.by_month == []
    assert loaded.peak_workers == 0.0 and loaded.peak_period == ""


def test_validate_costs_accepts_unit_price_shapes():
    costload.validate_costs({"A": {"cost": 1.0, "labor_hours": None,
                                   "unit_price": 145.0, "unit": "CY"}})
    costload.validate_costs({"B": {"cost": 1.0, "labor_hours": 2.0,
                                   "unit_price": {"0055": 12.5, "0056": 800.0},
                                   "unit": {"0055": "LF", "0056": "EA"}}})
    costload.validate_costs({"C": {"cost": 1.0, "labor_hours": None}})   # both optional


def test_validate_costs_rejects_bad_unit_price():
    import pytest
    with pytest.raises(ValueError, match=r"unit_price"):
        costload.validate_costs({"A": {"cost": 1.0, "unit_price": "145"}})
    with pytest.raises(ValueError, match=r"unit_price"):
        costload.validate_costs({"A": {"cost": 1.0, "unit_price": {"0055": "x"}}})
    with pytest.raises(ValueError, match=r"unit_price"):
        costload.validate_costs({"A": {"cost": 1.0, "unit_price": True}})


def test_validate_costs_rejects_bad_unit():
    import pytest
    with pytest.raises(ValueError, match=r"'unit'"):
        costload.validate_costs({"A": {"cost": 1.0, "unit": 7}})
    with pytest.raises(ValueError, match=r"'unit'"):
        costload.validate_costs({"A": {"cost": 1.0, "unit": {"0055": 7}}})
