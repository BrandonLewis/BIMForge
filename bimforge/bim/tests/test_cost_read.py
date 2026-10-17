"""Read 5D back out of an IFC (issue #335 §7): read_costs is the inverse of
cost5d.embed_cost_and_resources, keyed by read_schedule's task ids."""
import json

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

import ifcopenshell.api.root as root  # noqa: E402

from bimforge.bim import cost5d  # noqa: E402
from bimforge.bim.schedule4d import embed_schedule  # noqa: E402
from bimforge.bim.schedule_model import (  # noqa: E402
    CanonicalSchedule, ScheduleTask,
)
from bimforge.bim.schedule_read import read_costs, read_schedule  # noqa: E402
from bimforge.bim.costload import (  # noqa: E402
    distribute_to_task_codes, load_schedule_costs,
)

COSTS = {"A": {"cost": 10000.0, "labor_hours": 400.0},
         "B": {"cost": 2500.0, "labor_hours": None},
         "C": {"cost": 900.0, "labor_hours": 30.0},
         "Z": {"cost": 50.0, "labor_hours": 1.0}}      # no task: unloaded


def _sched(name="S"):
    return CanonicalSchedule(name=name, tasks=[
        ScheduleTask(id="t1", name="Pour", wbs="1", start="2026-08-10",
                     finish="2026-08-14", bid_item_codes=["A", "B"]),
        ScheduleTask(id="t2", name="Strip", wbs="2", start="2026-08-17",
                     finish="2026-08-26", bid_item_codes=["A"]),
        ScheduleTask(id="t3", name="Cure", wbs="3", start="2026-08-17",
                     finish="2026-08-18", bid_item_codes=["C"]),
    ])


def _model(*names):
    f = ifcopenshell.file(schema="IFC4X3_ADD2")
    root.create_entity(f, ifc_class="IfcProject")
    for n in names or ("S",):
        embed_schedule(f, _sched(n))
        cost5d.embed_cost_and_resources(f, _sched(n), COSTS,
                                        schedule_name=n)
    return f


def test_round_trip_per_task_and_per_code():
    got = read_costs(_model())
    want = distribute_to_task_codes(_sched(), COSTS)
    assert set(got["tasks"]) == {"t1", "t2", "t3"}
    for (tid, code), e in want.items():
        rec = got["tasks"][tid]["costs"][code]
        assert rec["cost"] == pytest.approx(e["cost"])
        if COSTS[code]["labor_hours"] is None:
            assert rec["labor_hours"] is None
        else:
            assert rec["labor_hours"] == pytest.approx(e["labor_hours"])
    # the code totals are the costs record back, less what no task carried
    assert set(got["costs"]) == {"A", "B", "C"}
    for code in "ABC":
        assert got["costs"][code]["cost"] == pytest.approx(COSTS[code]["cost"])
    assert got["costs"]["A"]["labor_hours"] == pytest.approx(400.0)
    assert got["costs"]["C"]["labor_hours"] == pytest.approx(30.0)
    # unknown hours stay unknown, never zero
    assert got["costs"]["B"]["labor_hours"] is None
    assert got["tasks"]["t1"]["costs"]["B"]["labor_hours"] is None
    # task crews: hours summed across the task's codes
    loaded = load_schedule_costs(_sched(), COSTS)
    for tid, load in loaded.by_task.items():
        assert got["tasks"][tid]["cost"] == pytest.approx(load["cost"])
        assert got["tasks"][tid]["labor_hours"] == \
            pytest.approx(load["labor_hours"])
    assert got["warnings"] == []


def test_read_costs_feeds_load_schedule_costs_and_matches_read_schedule():
    m = _model()
    got = read_costs(m)
    sched = read_schedule(m)
    assert set(got["tasks"]) <= {t.id for t in sched.tasks}
    # a consumer starting from the 5D model re-loads the same totals
    for t in sched.tasks:
        t.bid_item_codes = sorted(got["tasks"].get(t.id, {}).get("costs", {}))
    reloaded = load_schedule_costs(sched, got["costs"])
    assert reloaded.total_cost == pytest.approx(13400.0)
    assert json.loads(json.dumps(got)) == got


def test_schedules_stay_apart():
    m = _model("S", "T")
    with pytest.raises(ValueError, match="2 IfcWorkSchedules"):
        read_costs(m)
    for n in ("S", "T"):
        got = read_costs(m, n)
        assert got["schedule"] == n
        assert got["costs"]["A"]["cost"] == pytest.approx(10000.0)


def test_cost_never_lands_on_another_schedules_task():
    """A task missing from the same-named 4D schedule is reported missing,
    not matched by Identification to another schedule's task."""
    f = ifcopenshell.file(schema="IFC4X3_ADD2")
    root.create_entity(f, ifc_class="IfcProject")
    embed_schedule(f, _sched("S"))
    other = _sched("T")
    other.tasks.append(ScheduleTask(id="t4", name="Backfill", wbs="4",
                                    start="2026-08-27", finish="2026-08-28",
                                    bid_item_codes=["C"]))
    embed_schedule(f, other)
    costed = _sched("S")
    costed.tasks.append(other.tasks[-1])
    rep = cost5d.embed_cost_and_resources(f, costed, COSTS, schedule_name="S")
    assert rep.tasks_without_entity == ["t4"]
    assert not [c for c in f.by_type("IfcCostItem") if c.Name == "Backfill: C"]


def test_no_cost_schedule_is_a_clear_error():
    f = ifcopenshell.file(schema="IFC4X3_ADD2")
    root.create_entity(f, ifc_class="IfcProject")
    embed_schedule(f, _sched())
    with pytest.raises(ValueError, match="no IfcCostSchedule named 'S cost'"):
        read_costs(f)


def test_model_from_before_335_splits_crew_hours_by_cost():
    m = _model()
    for rel in list(m.by_type("IfcRelDefinesByProperties")):
        pd = rel.RelatingPropertyDefinition
        if pd.Name in ("Bimforge_CostItem", "Bimforge_Task"):
            m.remove(pd)
            m.remove(rel)
    got = read_costs(m)
    # tasks now read by Identification (= wbs)
    assert set(got["tasks"]) == {"1", "2", "3"}
    # single-code tasks keep their crew's hours exactly
    want = distribute_to_task_codes(_sched(), COSTS)
    assert got["tasks"]["3"]["costs"]["C"]["labor_hours"] == \
        pytest.approx(want[("t3", "C")]["labor_hours"])
    # the two-code task's crew is shared out by cost, with a warning
    t1 = got["tasks"]["1"]["costs"]
    crew = want[("t1", "A")]["labor_hours"]
    share = t1["A"]["cost"] / (t1["A"]["cost"] + t1["B"]["cost"])
    assert t1["A"]["labor_hours"] == pytest.approx(crew * share)
    assert [w for w in got["warnings"] if w.startswith("task 1:")]
    assert got["costs"]["A"]["cost"] == pytest.approx(10000.0)


def test_cli_costs_out(tmp_path):
    from bimforge.bim.cli import main

    path = tmp_path / "m.5d.ifc"
    _model().write(str(path))
    out, costs = tmp_path / "s.json", tmp_path / "c.json"
    assert main(["schedule-read", "--ifc", str(path), "--out", str(out),
                 "--costs-out", str(costs)]) == 0
    got = json.loads(costs.read_text())
    assert got["costs"]["A"]["cost"] == pytest.approx(10000.0)


def test_models_with_the_old_pset_names_still_read():
    """0.1.88 and earlier wrote Pset_BimforgeTask / Pset_BimforgeCostItem
    ("Pset_" is reserved for buildingSMART's sets); renamed to Bimforge_*,
    the old names must keep reading identically."""
    new = _model()
    old = _model()
    renamed = 0
    for pd in old.by_type("IfcPropertySet"):
        if pd.Name in ("Bimforge_Task", "Bimforge_CostItem"):
            pd.Name = "Pset_" + pd.Name.replace("_", "")
            renamed += 1
    assert renamed
    assert read_costs(old) == read_costs(new)
    def tasks(m):           # GlobalIds differ between the two builds
        return [{k: v for k, v in t.items() if k != "global_id"}
                for t in read_schedule(m).to_dict()["tasks"]]
    assert tasks(old) == tasks(new)
    assert [t["wbs"] for t in tasks(old)] == ["1", "2", "3"]
