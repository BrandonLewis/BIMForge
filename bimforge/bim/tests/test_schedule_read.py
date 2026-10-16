"""Read 4D back out of an IFC (issue #335): read_schedule, task_elements,
takeoff_by_task — the inverse of schedule4d.embed_schedule."""
import json
import os

import pytest

ezdxf = pytest.importorskip("ezdxf")
shapely = pytest.importorskip("shapely")
ifcopenshell = pytest.importorskip("ifcopenshell")
pytest.importorskip("pyproj")
yaml = pytest.importorskip("yaml")

from importlib.resources import files  # noqa: E402

import ifcopenshell.api.sequence as sq  # noqa: E402
import ifcopenshell.validate  # noqa: E402

from bimforge.bim.dxf2bim import UNIT_TO_M, build_ifc, extract_features  # noqa: E402
from bimforge.bim.ifc_takeoff import build_takeoff, takeoff_by_task  # noqa: E402
from bimforge.bim.sample import write_sample_dxf  # noqa: E402
from bimforge.bim.schedule4d import blackout_spans, embed_schedule  # noqa: E402
from bimforge.bim.schedule_model import (  # noqa: E402
    Calendar, CanonicalSchedule, Dependency, ScheduleTask,
)
from bimforge.bim.schedule_read import (  # noqa: E402
    element_start_dates, read_schedule, task_elements,
)


def _example(name):
    return yaml.safe_load(
        (files("bimforge.bim") / "examples" / name).read_text())


@pytest.fixture(scope="module")
def sample_ifc(tmp_path_factory):
    # sample codes: A-SLAB 03 30 00, A-WALL EF_25_10, 4x COL 05 12 00,
    # curb 32 16 13, hatch EF_25_30
    tmp = tmp_path_factory.mktemp("sched_read")
    dxf = write_sample_dxf(str(tmp / "s.dxf"))
    lm = _example("layer_map.example.yaml")
    feats = extract_features(dxf, lm["layers"],
                             UNIT_TO_M[lm["units"]["dxf_length_unit"]])
    ifc = str(tmp / "m.ifc")
    build_ifc(feats, lm, ifc)
    return ifc


def _full_schedule():
    """A schedule using every #335 field."""
    return CanonicalSchedule(
        name="Bridge BL V.02", start_date="2026-06-01",
        work_weekdays=[0, 1, 2, 3], holidays=["2026-07-03", "2026-09-07"],
        calendars={
            "in-water": Calendar(work_weekdays=[0, 1, 2, 3, 4],
                                 holidays=["2026-07-03"],
                                 blackouts=[{"from": "10-02", "to": "05-31"}]),
            "nesting": Calendar(blackouts=[{"from": "02-15", "to": "02-29"},
                                           {"from": "08-01", "to": "08-01"}]),
        },
        tasks=[
            ScheduleTask(id="10", name="Bridge", wbs="1"),
            ScheduleTask(id="20", name="Mobilization", wbs="1.1",
                         start="2026-06-01", finish="2026-06-05",
                         duration_days=5.0, bid_items=["1"],
                         notes="LS per spec 9-1.03"),
            ScheduleTask(id="30", name="Remove existing bridge", wbs="1.2",
                         start="2026-06-08", finish="2026-06-19",
                         duration_days=10.0, task_type="DEMOLITION",
                         bid_items=["4"], calendar="in-water",
                         dependencies=[Dependency("20")]),
            ScheduleTask(id="40", name="Deck pour", wbs="1.3",
                         start="2026-06-22", finish="2026-06-26",
                         duration_days=4.5, task_type="CONSTRUCTION",
                         bid_items=["67", "87"], bid_item_codes=["03 30 00"],
                         notes="JUDGEMENT ~4 piles/day",
                         dependencies=[Dependency("30", "SS", 2.0)]),
            ScheduleTask(id="50", name="Bird survey", wbs="1.4",
                         is_milestone=True, start="2026-06-29",
                         finish="2026-06-29", task_type="ENVIRONMENTAL",
                         calendar="nesting",
                         dependencies=[Dependency("40", "FF", 1.5)]),
        ],
    )


def _embed(ifc_path, sched, out_name, **kw):
    model = ifcopenshell.open(ifc_path)
    report = embed_schedule(model, sched, **kw)
    out = os.path.join(os.path.dirname(ifc_path), out_name)
    model.write(out)
    return out, report


def test_round_trip_every_new_field(sample_ifc):
    src = _full_schedule()
    path, report = _embed(sample_ifc, src, "full.4d.ifc")
    assert report.calendars == 2 and report.bid_item_links == 4
    got = read_schedule(ifcopenshell.open(path))

    want = src.to_dict()
    have = got.to_dict()
    # GlobalId is always filled on read; the embed-time joins are not read
    for t in have["tasks"]:
        assert len(t.pop("global_id")) == 22
    for t in want["tasks"]:
        t["bid_item_codes"] = []
    assert have == want


def test_round_trip_survives_json(sample_ifc):
    path, _ = _embed(sample_ifc, _full_schedule(), "json.4d.ifc")
    got = read_schedule(ifcopenshell.open(path))
    assert CanonicalSchedule.from_json(got.to_json()).to_dict() == got.to_dict()


def test_embedded_file_is_valid_ifc(sample_ifc):
    path, _ = _embed(sample_ifc, _full_schedule(), "valid.4d.ifc")
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(ifcopenshell.open(path), logger)
    assert not logger.statements, logger.statements[:5]


def test_global_id_writes_back_to_the_same_task(sample_ifc):
    path, _ = _embed(sample_ifc, _full_schedule(), "gid1.4d.ifc")
    first = read_schedule(ifcopenshell.open(path))
    # a consumer re-plans and writes back over the same entities
    first.tasks[2].start, first.tasks[2].finish = "2026-06-09", "2026-06-22"
    again, _ = _embed(path, first, "gid2.4d.ifc")
    second = read_schedule(ifcopenshell.open(again))
    assert [t.global_id for t in second.tasks] == \
        [t.global_id for t in first.tasks]
    assert second.tasks[2].start == "2026-06-09"
    # the replaced schedule left nothing behind
    m = ifcopenshell.open(again)
    assert len(m.by_type("IfcWorkSchedule")) == 1
    assert len(m.by_type("IfcWorkCalendar")) == 3
    assert {r.Identification for r in m.by_type("IfcClassificationReference")
            if r.ReferencedSource.Name == "Owner bid items"} == \
        {"1", "4", "67", "87"}
    assert all(r.RelatedObjects
               for r in m.by_type("IfcRelAssociatesClassification"))


def test_bad_global_id_is_refused(sample_ifc):
    sched = _full_schedule()
    sched.tasks[1].global_id = "not-a-guid"
    with pytest.raises(ValueError, match="not an IFC GlobalId"):
        embed_schedule(ifcopenshell.open(sample_ifc), sched)


def test_unknown_calendar_is_refused():
    sched = _full_schedule()
    sched.tasks[1].calendar = "winter"
    with pytest.raises(ValueError, match="unknown calendar 'winter'"):
        sched.validate()


@pytest.mark.parametrize("bad", [{"from": "13-01", "to": "01-01"},
                                 {"from": "04-31", "to": "05-01"},
                                 {"from": "6-1", "to": "10-01"},
                                 {"from": "06-01"}])
def test_malformed_blackout_is_refused(bad):
    sched = _full_schedule()
    sched.calendars["in-water"].blackouts = [bad]
    with pytest.raises(ValueError, match="in-water"):
        sched.validate()


def test_blackout_spans_split_into_rectangles():
    full = list(range(1, 32))
    assert blackout_spans("06-01", "10-01") == [
        ([6, 7, 8, 9], full), ([10], [1])]
    assert blackout_spans("10-02", "05-31") == [
        ([10], list(range(2, 32))), ([11, 12, 1, 2, 3, 4, 5], full)]
    assert blackout_spans("03-10", "03-12") == [([3], [10, 11, 12])]
    # wraps all the way round, through its own month twice
    assert blackout_spans("03-10", "03-09") == [
        ([3], list(range(10, 32))),
        ([4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2], full),
        ([3], list(range(1, 10)))]


def test_unnamed_blackout_patterns_merge_into_windows(sample_ifc):
    """Another tool's yearly exceptions carry no window name: the reader
    rebuilds windows from the days, joining across the year end."""
    path, _ = _embed(sample_ifc, _full_schedule(), "unnamed.4d.ifc")
    m = ifcopenshell.open(path)
    for wt in m.by_type("IfcWorkTime"):
        wt.Name = None
    got = read_schedule(m)
    assert got.calendars["in-water"].blackouts == [
        {"from": "10-02", "to": "05-31"}]
    assert got.calendars["nesting"].blackouts == [
        {"from": "02-15", "to": "02-29"}, {"from": "08-01", "to": "08-01"}]


def _pre_335(ifc_path):
    """A 4D model as embed_schedule wrote it before #335: no task pset, no
    calendars beyond the project one, no types/items/notes."""
    sched = CanonicalSchedule(
        name="Old BL", tasks=[
            ScheduleTask(id="s", name="Structure", wbs="1"),
            ScheduleTask(id="deck", name="Place deck", wbs="1.1",
                         start="2026-07-10", finish="2026-07-14",
                         bid_item_codes=["03 30 00"]),
            ScheduleTask(id="walls", name="Build walls", wbs="1.2",
                         start="2026-07-15", finish="2026-07-25",
                         bid_item_codes=["EF_25_10"],
                         dependencies=[Dependency("deck", "FS", 2.0)]),
            ScheduleTask(id="cols", name="Set columns",
                         start="2026-07-26", finish="2026-07-28",
                         bid_item_codes=["05 12 00"]),
        ])
    path, _ = _embed(ifc_path, sched, "old.4d.ifc")
    m = ifcopenshell.open(path)
    for rel in list(m.by_type("IfcRelDefinesByProperties")):
        if rel.RelatingPropertyDefinition.Name == "Pset_BimforgeTask":
            m.remove(rel.RelatingPropertyDefinition)
            m.remove(rel)
    return m


def test_model_from_before_335_reads_with_new_fields_empty(sample_ifc):
    got = read_schedule(_pre_335(sample_ifc))
    # Identification was wbs-or-id, so that is the id a consumer sees; the
    # code-less "cols" root is not a WBS, so the whole tree is numbered
    assert [(t.id, t.wbs) for t in got.tasks] == [
        ("cols", "1"), ("1", "2"), ("1.1", "2.1"), ("1.2", "2.2")]
    walls = got.tasks[3]
    assert walls.dependencies == [Dependency("1.1", "FS", 2.0)]
    assert got.calendars == {}
    for t in got.tasks:
        assert t.task_type is None and t.bid_items == [] and t.notes == ""
        assert t.calendar is None and t.global_id
    assert got.work_weekdays == [0, 1, 2, 3, 4]


def test_schedule_selection(sample_ifc):
    path, _ = _embed(sample_ifc, _full_schedule(), "two.4d.ifc")
    m = ifcopenshell.open(path)
    other = _full_schedule()
    other.name = "Bridge BL V.03"
    embed_schedule(m, other)
    with pytest.raises(ValueError, match="2 IfcWorkSchedules"):
        read_schedule(m)
    assert read_schedule(m, "Bridge BL V.03").name == "Bridge BL V.03"
    with pytest.raises(ValueError, match="no IfcWorkSchedule named 'X'"):
        read_schedule(m, "X")
    with pytest.raises(ValueError, match="no IfcWorkSchedule"):
        read_schedule(ifcopenshell.open(sample_ifc))


# ---------------------------------------------------------------------------
# task -> element links, inputs and outputs
# ---------------------------------------------------------------------------

def _staged(ifc_path, out_name="staged.4d.ifc"):
    """Columns split across two piling stages, a removal task linked to the
    deck it tears out, and a deck pour."""
    sched = CanonicalSchedule(
        name="Staged", tasks=[
            ScheduleTask(id="P1", name="Piling stage 1",
                         start="2026-07-01", finish="2026-07-03"),
            ScheduleTask(id="P2", name="Piling stage 2",
                         start="2026-07-06", finish="2026-07-08"),
            ScheduleTask(id="RM", name="Remove deck", task_type="REMOVAL",
                         start="2026-06-01", finish="2026-06-05",
                         bid_item_codes=["03 30 00"]),
            ScheduleTask(id="DK", name="Pour deck",
                         task_type="CONSTRUCTION",
                         start="2026-07-10", finish="2026-07-14",
                         bid_item_codes=["03 30 00"]),
            ScheduleTask(id="WL", name="Walls", task_type="INSTALLATION",
                         start="2026-07-15", finish="2026-07-17",
                         bid_item_codes=["EF_25_10"]),
        ])
    m = ifcopenshell.open(ifc_path)
    embed_schedule(m, sched)
    tasks = {t.Name: t for t in m.by_type("IfcTask")}
    cols = sorted(m.by_type("IfcColumn"), key=lambda e: e.GlobalId)
    for el in cols[:2]:
        sq.assign_process(m, relating_process=tasks["Piling stage 1"],
                          related_object=el)
    for el in cols[2:]:
        sq.assign_process(m, relating_process=tasks["Piling stage 2"],
                          related_object=el)
    out = os.path.join(os.path.dirname(ifc_path), out_name)
    m.write(out)
    return out, cols


def _to_outputs(path, out_name):
    """Post-process every input link into an output link (Bonsai playback)."""
    m = ifcopenshell.open(path)
    for rel in list(m.by_type("IfcRelAssignsToProcess")):
        task = rel.RelatingProcess
        for el in rel.RelatedObjects:
            sq.assign_product(m, relating_product=el, related_object=task)
        m.remove(rel)
    out = os.path.join(os.path.dirname(path), out_name)
    m.write(out)
    return out


def _undirected(links):
    return {tid: sorted(l["global_id"] for l in ls)  # noqa: E741
            for tid, ls in links.items()}


def test_task_elements_reads_inputs_and_outputs_alike(sample_ifc):
    path, cols = _staged(sample_ifc)
    outs = _to_outputs(path, "staged.out.ifc")
    m_in, m_out = ifcopenshell.open(path), ifcopenshell.open(outs)
    links_in, links_out = task_elements(m_in), task_elements(m_out)
    assert _undirected(links_in) == _undirected(links_out)
    assert {l["direction"] for ls in links_in.values() for l in ls} == \
        {"input"}
    assert {l["direction"] for ls in links_out.values() for l in ls} == \
        {"output"}
    assert sorted(l["global_id"] for l in links_in["P1"]) == \
        sorted(c.GlobalId for c in cols[:2])
    # the same tasks read back from both
    assert read_schedule(m_in).to_dict() == read_schedule(m_out).to_dict()
    # and the KML/KMZ start dates follow output links too
    assert sorted(element_start_dates(m_in).values()) == \
        sorted(element_start_dates(m_out).values())


def test_task_elements_limited_to_one_schedule(sample_ifc):
    path, _ = _staged(sample_ifc, "staged2.4d.ifc")
    m = ifcopenshell.open(path)
    embed_schedule(m, _full_schedule())
    assert set(task_elements(m, "Staged")) == {"P1", "P2", "RM", "DK", "WL"}
    assert set(task_elements(m)) >= {"P1", "10", "40"}


# ---------------------------------------------------------------------------
# quantities per task
# ---------------------------------------------------------------------------

def _tmap():
    return {"codes": {
        "05 12 00": {"measure": "Count", "unit": "EA", "item_number": "12"},
        "03 30 00": {"unit": "CY", "item_number": "30"},
        "EF_25_10": {"unit": "CY", "item_number": "31"},
    }}


@pytest.mark.parametrize("outputs", [False, True])
def test_takeoff_by_task_splits_each_row(sample_ifc, outputs):
    path, cols = _staged(sample_ifc, f"tbt{outputs}.4d.ifc")
    if outputs:
        path = _to_outputs(path, "tbt.out.ifc")
    takeoff, warnings = takeoff_by_task(path, _tmap())
    rows = {r["cost_code"]: r for r in takeoff["rows"]}

    # every pile on exactly one stage task
    assert rows["05 12 00"]["tasks"] == {"P1": 2.0, "P2": 2.0}
    # the removal task never claims the deck it removes
    deck = rows["03 30 00"]
    assert set(deck["tasks"]) == {"DK"}
    assert deck["tasks"]["DK"] == pytest.approx(deck["quantity"])
    assert rows["EF_25_10"]["tasks"].keys() == {"WL"}
    # unlinked quantity is reported, never dropped
    assert rows["32 16 13"]["tasks"] == {}
    assert rows["32 16 13"]["unassigned"] == rows["32 16 13"]["quantity"]
    for r in takeoff["rows"]:
        assert sum(r["tasks"].values()) + r["unassigned"] == \
            pytest.approx(r["quantity"], abs=1e-4)
    # otherwise the same takeoff
    plain, _ = build_takeoff(path, _tmap())
    for r in takeoff["rows"]:
        r.pop("tasks"), r.pop("unassigned")
    assert takeoff == plain
    assert not [w for w in warnings if "construction tasks" in w]


def test_two_constructive_tasks_earliest_claims_with_warning(sample_ifc):
    path, cols = _staged(sample_ifc, "dup.4d.ifc")
    m = ifcopenshell.open(path)
    p2 = next(t for t in m.by_type("IfcTask") if t.Name == "Piling stage 2")
    sq.assign_process(m, relating_process=p2, related_object=cols[0])
    out = path.replace(".4d.ifc", ".dup2.ifc")
    m.write(out)
    takeoff, warnings = takeoff_by_task(out, _tmap())
    row = next(r for r in takeoff["rows"] if r["cost_code"] == "05 12 00")
    assert row["tasks"] == {"P1": 2.0, "P2": 2.0}
    assert [w for w in warnings
            if cols[0].GlobalId in w and "claimed by the earliest-starting, P1"
            in w]


def test_takeoff_by_task_with_a_replanned_schedule(sample_ifc):
    """A consumer's re-plan (same ids, new dates) decides the claim."""
    path, cols = _staged(sample_ifc, "replan.4d.ifc")
    m = ifcopenshell.open(path)
    p2 = next(t for t in m.by_type("IfcTask") if t.Name == "Piling stage 2")
    sq.assign_process(m, relating_process=p2, related_object=cols[0])
    out = path.replace(".4d.ifc", ".r2.ifc")
    m.write(out)
    plan = read_schedule(ifcopenshell.open(out))
    p1 = next(t for t in plan.tasks if t.id == "P1")
    p1.start, p1.finish = "2026-08-01", "2026-08-03"   # now after stage 2
    takeoff, _ = takeoff_by_task(out, _tmap(), schedule=plan)
    row = next(r for r in takeoff["rows"] if r["cost_code"] == "05 12 00")
    assert row["tasks"] == {"P1": 1.0, "P2": 3.0}


def test_cli_schedule_read(sample_ifc, tmp_path, capsys):
    from bimforge.bim.cli import main

    path, _ = _staged(sample_ifc, "cli.4d.ifc")
    tmap = tmp_path / "map.yaml"
    tmap.write_text(yaml.safe_dump(_tmap()))
    out, tko = tmp_path / "s.json", tmp_path / "t.json"
    rc = main(["schedule-read", "--ifc", path, "--out", str(out),
               "--takeoff-map", str(tmap), "--takeoff-out", str(tko)])
    assert rc == 0
    sched = CanonicalSchedule.from_json(out.read_text())
    assert [t.id for t in sched.tasks] == ["P1", "P2", "RM", "DK", "WL"]
    rows = json.loads(tko.read_text())["rows"]
    assert all("tasks" in r and "unassigned" in r for r in rows)
    assert "5 tasks" in capsys.readouterr().out

    assert main(["schedule-read", "--ifc", path, "--out", str(out),
                 "--schedule", "nope"]) == 1
    assert main(["schedule-read", "--ifc", path, "--out", str(out),
                 "--takeoff-out", str(tko)]) == 2


def test_apportion_never_leaves_negative_unassigned():
    from bimforge.bim.ifc_takeoff import _apportion

    tasks, un = _apportion(0.0001, [("a", 0.00006), ("b", 0.00006)])
    assert un == 0.0 and sum(tasks.values()) == pytest.approx(0.0001)
    assert sorted(tasks.values()) == [0.0, 0.0001]
    tasks, un = _apportion(10.0, [("a", 3.33333), ("b", 3.33333)])
    # 6.66666 claimed rounds to 6.6667: one share takes the spare unit
    assert tasks == {"a": 3.3334, "b": 3.3333} and un == 3.3333
    tasks, un = _apportion(1.0, [("a", 1 / 3), ("b", 1 / 3), ("c", 1 / 3)])
    assert un == 0.0 and round(sum(tasks.values()), 4) == 1.0


def test_renamed_replan_in_a_multi_schedule_file_matches_by_global_id(
        sample_ifc):
    """Two schedules reuse ids P1/P2; a renamed re-plan of one must not
    borrow the other's elements."""
    path, cols = _staged(sample_ifc, "multi.4d.ifc")
    m = ifcopenshell.open(path)
    twin = read_schedule(m)
    twin.name = "Staged copy"
    for t in twin.tasks:
        t.global_id = None
    embed_schedule(m, twin)      # same ids, links only through codes
    copy_p1 = next(t for t in m.by_type("IfcTask")
                   if t.Name == "Piling stage 1"
                   and t.TaskTime and t != _task_named(m, "Staged", "P1"))
    for el in cols[2:]:
        sq.assign_process(m, relating_process=copy_p1, related_object=el)
    out = path.replace(".4d.ifc", ".m2.ifc")
    m.write(out)

    plan = read_schedule(ifcopenshell.open(out), "Staged")
    plan.name = "Staged re-plan"
    takeoff, _ = takeoff_by_task(out, _tmap(), schedule=plan)
    row = next(r for r in takeoff["rows"] if r["cost_code"] == "05 12 00")
    assert row["tasks"] == {"P1": 2.0, "P2": 2.0}

    for t in plan.tasks:
        t.global_id = None
    with pytest.raises(ValueError, match="ambiguous"):
        takeoff_by_task(out, _tmap(), schedule=plan)


def _task_named(model, schedule, tid):
    from bimforge.bim.schedule_read import _schedule_tasks, _work_schedule, \
        task_id
    return next(t for t, _ in _schedule_tasks(_work_schedule(model, schedule))
                if task_id(t) == tid)


def test_project_calendar_with_no_work_days_round_trips(sample_ifc):
    sched = _full_schedule()
    sched.work_weekdays = []
    path, _ = _embed(sample_ifc, sched, "nowork.4d.ifc")
    assert read_schedule(ifcopenshell.open(path)).work_weekdays == []
