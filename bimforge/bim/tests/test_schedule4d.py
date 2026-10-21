"""est-bim schedule: embed a CanonicalSchedule into an IFC (4D staging slice 2)."""
import os

import pytest

ezdxf = pytest.importorskip("ezdxf")
shapely = pytest.importorskip("shapely")
ifcopenshell = pytest.importorskip("ifcopenshell")
pytest.importorskip("pyproj")
yaml = pytest.importorskip("yaml")

from importlib.resources import files  # noqa: E402

from bimforge.bim.dxf2bim import UNIT_TO_M, build_ifc, extract_features  # noqa: E402
from bimforge.bim.sample import write_sample_dxf  # noqa: E402
from bimforge.bim.schedule4d import embed_schedule  # noqa: E402
from bimforge.bim.schedule_model import (  # noqa: E402
    CanonicalSchedule, Dependency, ScheduleTask,
)


def _example(name):
    return yaml.safe_load(
        (files("bimforge.bim") / "examples" / name).read_text())


@pytest.fixture(scope="module")
def sample_ifc(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("sched4d")
    dxf = write_sample_dxf(str(tmp / "s.dxf"))
    lm = _example("layer_map.example.yaml")
    feats = extract_features(dxf, lm["layers"], UNIT_TO_M[lm["units"]["dxf_length_unit"]])
    ifc = str(tmp / "m.ifc")
    build_ifc(feats, lm, ifc)
    return ifc


def _schedule():
    # sample codes: A-SLAB 03 30 00, A-WALL EF_25_10, E-COL 05 12 00
    return CanonicalSchedule(
        name="Sample BL V.01", start_date="2026-07-10",
        work_weekdays=[0, 1, 2, 3, 4], holidays=["2026-09-07"],
        tasks=[
            ScheduleTask(id="s", name="Structure", wbs="1"),
            ScheduleTask(id="deck", name="Place deck", wbs="1.1",
                         start="2026-07-10", finish="2026-07-14",
                         bid_item_codes=["03 30 00"]),
            ScheduleTask(id="walls", name="Build walls", wbs="1.2",
                         start="2026-07-15", finish="2026-07-25",
                         bid_item_codes=["EF_25_10"],
                         dependencies=[Dependency(predecessor="deck",
                                                  type="FS", lag_days=2.0)]),
            ScheduleTask(id="cols", name="Set columns", wbs="1.3",
                         start="2026-07-26", finish="2026-07-28",
                         is_milestone=True, bid_item_codes=["05 12 00"]),
            ScheduleTask(id="ghost", name="Paint (no geometry)", wbs="1.4",
                         start="2026-07-29", finish="2026-07-30",
                         bid_item_codes=["09 90 00"]),   # code with no element
        ],
    )


def _embed(ifc_path, sched, out_name="m4d.ifc", **kw):
    model = ifcopenshell.open(ifc_path)
    report = embed_schedule(model, sched, **kw)
    out = os.path.join(os.path.dirname(ifc_path), out_name)
    model.write(out)
    return ifcopenshell.open(out), report


def test_embed_authors_schedule_tasks_and_times(sample_ifc):
    g, report = _embed(sample_ifc, _schedule())
    ws = g.by_type("IfcWorkSchedule")
    assert len(ws) == 1 and ws[0].Name == "Sample BL V.01"
    tasks = {t.Name: t for t in g.by_type("IfcTask")}
    assert set(tasks) >= {"Structure", "Place deck", "Build walls",
                          "Set columns"}
    assert tasks["Place deck"].TaskTime.ScheduleStart.startswith("2026-07-10")
    assert tasks["Set columns"].IsMilestone is True
    assert report.tasks == 5 and report.tasks_timed == 4   # summary has no time


def test_embed_nests_tasks_by_wbs(sample_ifc):
    g, _ = _embed(sample_ifc, _schedule())
    structure = [t for t in g.by_type("IfcTask") if t.Name == "Structure"][0]
    nested = []
    for rel in structure.IsNestedBy or []:
        nested += [o.Name for o in rel.RelatedObjects]
    assert {"Place deck", "Build walls", "Set columns"} <= set(nested)


def test_embed_sequences_with_type_and_lag(sample_ifc):
    g, report = _embed(sample_ifc, _schedule())
    seqs = g.by_type("IfcRelSequence")
    assert len(seqs) == 1
    seq = seqs[0]
    assert seq.SequenceType == "FINISH_START"
    assert seq.RelatingProcess.Name == "Place deck"
    assert seq.RelatedProcess.Name == "Build walls"
    assert seq.TimeLag is not None and "2" in seq.TimeLag.LagValue.wrappedValue
    assert report.sequences == 1


def test_embed_assigns_elements_by_code(sample_ifc):
    g, report = _embed(sample_ifc, _schedule())
    links = {}
    for rel in g.by_type("IfcRelAssignsToProcess"):
        links[rel.RelatingProcess.Name] = sorted(o.is_a() for o in rel.RelatedObjects)
    assert links["Place deck"] == ["IfcSlab"]
    assert links["Build walls"] == ["IfcWall"]
    assert links["Set columns"] == ["IfcColumn", "IfcColumn", "IfcColumn", "IfcColumn"]
    assert report.assigned_elements == 6          # 1 slab + 1 wall + 4 cols


def test_embed_reports_unmapped_both_ways(sample_ifc):
    g, report = _embed(sample_ifc, _schedule())
    # a task code with no geometry in the model
    assert "09 90 00" in report.codes_without_elements
    # curb (32 16 13) and hatch (EF_25_30) are in the IFC but no task claims them
    assert report.unscheduled_element_count == 2   # C-CURB + A-HATCH
    assert all(isinstance(n, str) and n for n in report.unscheduled_elements)
    # the reported names are exactly the un-assigned classified elements
    assigned = set()
    for rel in g.by_type("IfcRelAssignsToProcess"):
        assigned |= {o.Name or o.is_a() for o in rel.RelatedObjects}
    assert not (set(report.unscheduled_elements) & assigned)


def test_embed_fractional_lag_is_not_truncated(sample_ifc):
    sched = _schedule()
    sched.tasks[2].dependencies[0].lag_days = 1.5     # deck -> walls
    g, _ = _embed(sched=sched, ifc_path=sample_ifc, out_name="frac.ifc")
    seq = g.by_type("IfcRelSequence")[0]
    assert seq.TimeLag.LagValue.wrappedValue == "P1.5D"


def test_embed_authors_calendar(sample_ifc):
    g, _ = _embed(sample_ifc, _schedule())
    cals = g.by_type("IfcWorkCalendar")
    assert len(cals) == 1
    # a weekly working-time recurrence carries the Mon-Fri weekdays (IFC 1..7)
    rp = g.by_type("IfcRecurrencePattern")
    assert rp and sorted(rp[0].WeekdayComponent) == [1, 2, 3, 4, 5]


def test_embed_is_idempotent_by_name(sample_ifc):
    model = ifcopenshell.open(sample_ifc)
    embed_schedule(model, _schedule())
    embed_schedule(model, _schedule())            # same name again
    assert len(model.by_type("IfcWorkSchedule")) == 1
    # tasks not doubled
    assert len([t for t in model.by_type("IfcTask") if t.Name == "Place deck"]) == 1
    # calendar not orphaned/duplicated on re-run
    assert len(model.by_type("IfcWorkCalendar")) == 1


def test_embed_assigns_by_ifc_class_and_name_regex(sample_ifc):
    # The sample IFC's elements DO carry codes, but here we join by class /
    # name instead — the slice-5 path for code-less models.
    sched = CanonicalSchedule(name="Sel", tasks=[
        ScheduleTask(id="piles", name="Set columns", wbs="1",
                     start="2026-07-10", finish="2026-07-12",
                     match_ifc_class="IfcColumn"),
        ScheduleTask(id="deck", name="Place deck", wbs="2",
                     start="2026-07-13", finish="2026-07-15",
                     match_name_re=r"A-SLAB"),
        ScheduleTask(id="ghost", name="Nothing", wbs="3",
                     start="2026-07-16", finish="2026-07-17",
                     match_ifc_class="IfcPile"),   # no piles in the sample
    ])
    g, report = _embed(sample_ifc, sched, out_name="sel.ifc")
    links = {}
    for rel in g.by_type("IfcRelAssignsToProcess"):
        links[rel.RelatingProcess.Name] = sorted(o.is_a() for o in rel.RelatedObjects)
    assert links["Set columns"] == ["IfcColumn"] * 4
    assert links["Place deck"] == ["IfcSlab"]        # A-SLAB element name
    assert report.assigned_elements == 5
    # the class selector that matched nothing is reported
    assert any("IfcPile" in s for s in report.selectors_without_elements)


def test_embed_ifc_class_selector_matches_subtypes(sample_ifc):
    # Selecting IfcWall must also catch subtypes like IfcWallStandardCase
    # (Revit/Tekla exports emit the *StandardCase variants). Exact-entity
    # matching would silently miss them.
    model = ifcopenshell.open(sample_ifc)
    model.create_entity("IfcWallStandardCase",
                        GlobalId=ifcopenshell.guid.new(), Name="RW-STD-1")
    sched = CanonicalSchedule(name="Subtype", tasks=[
        ScheduleTask(id="w", name="Build walls", wbs="1",
                     start="2026-07-10", finish="2026-07-12",
                     match_ifc_class="IfcWall")])
    report = embed_schedule(model, sched)
    links = {}
    for rel in model.by_type("IfcRelAssignsToProcess"):
        links[rel.RelatingProcess.Name] = sorted(o.is_a() for o in rel.RelatedObjects)
    # both the plain IfcWall and the IfcWallStandardCase subtype are assigned
    assert links["Build walls"] == ["IfcWall", "IfcWallStandardCase"]
    assert report.assigned_elements == 2


def test_embed_does_not_cascade_dates_over_dependencies(sample_ifc):
    # A task with a predecessor and a gap after it must keep its OWN start
    # (the source schedule's CPM), not be rescheduled to predecessor-finish+1.
    sched = CanonicalSchedule(name="NoCascade", tasks=[
        ScheduleTask(id="a", name="A", wbs="1",
                     start="2026-07-01", finish="2026-07-10"),
        ScheduleTask(id="b", name="B", wbs="2",
                     start="2026-09-01", finish="2026-09-10",   # 7-week gap
                     dependencies=[Dependency(predecessor="a")]),
    ])
    g, _ = _embed(sample_ifc, sched, out_name="nocascade.ifc")
    b = [t for t in g.by_type("IfcTask") if t.Name == "B"][0]
    assert b.TaskTime.ScheduleStart.startswith("2026-09-01")   # not 2026-07-11


def test_embed_invalid_name_regex_is_clean_error(sample_ifc):
    sched = CanonicalSchedule(name="Bad", tasks=[
        ScheduleTask(id="x", name="X", wbs="1", start="2026-07-10",
                     finish="2026-07-11", match_name_re="([")])
    model = ifcopenshell.open(sample_ifc)
    with pytest.raises(ValueError, match="invalid name_re"):
        embed_schedule(model, sched)


def test_cli_schedule_end_to_end(sample_ifc, tmp_path, capsys):
    import json

    from bimforge.bim.cli import main

    gw = {
        "name": "CLI BL", "start_date": "2026-07-10",
        "default_work_weekdays": [0, 1, 2, 3, 4], "holidays": [],
        "tasks": [
            {"id": "d", "name": "SLAB.0010 Place deck", "wbs": "1",
             "start_date": "2026-07-10", "end_date": "2026-07-14",
             "duration_days": 3.0, "is_milestone": False, "dependencies": []},
        ],
    }
    sched_path = tmp_path / "cli.gw.json"
    sched_path.write_text(json.dumps(gw), encoding="utf-8")
    task_map = tmp_path / "map.json"
    task_map.write_text(json.dumps({"d": ["03 30 00"]}), encoding="utf-8")
    out = tmp_path / "out.4d.ifc"
    rc = main(["schedule", "--ifc", sample_ifc, "--schedule", str(sched_path),
               "--task-map", str(task_map), "--out", str(out)])
    assert rc == 0
    printed = capsys.readouterr().out
    assert "1 tasks" in printed and "1 elements assigned" in printed
    g = ifcopenshell.open(str(out))
    assert [w.Name for w in g.by_type("IfcWorkSchedule")] == ["CLI BL"]
    links = {r.RelatingProcess.Name: [o.is_a() for o in r.RelatedObjects]
             for r in g.by_type("IfcRelAssignsToProcess")}
    assert links["SLAB.0010 Place deck"] == ["IfcSlab"]


def test_cli_schedule_bad_task_map_is_clean_error(sample_ifc, tmp_path, capsys):
    import json

    from bimforge.bim.cli import main

    sched_path = tmp_path / "cli.gw.json"
    sched_path.write_text(json.dumps({"tasks": []}), encoding="utf-8")
    bad = tmp_path / "map.json"
    bad.write_text(json.dumps(["03 30 00"]), encoding="utf-8")   # not an object
    rc = main(["schedule", "--ifc", sample_ifc, "--schedule", str(sched_path),
               "--task-map", str(bad)])
    assert rc == 1
    assert "must be a JSON object" in capsys.readouterr().err


def test_cli_schedule_ifcopenshell_error_is_clean_error(tmp_path, capsys, monkeypatch):
    import json

    import ifcopenshell

    from bimforge.bim.cli import main

    sched_path = tmp_path / "cli.gw.json"
    sched_path.write_text(json.dumps({"tasks": []}), encoding="utf-8")
    ifc = tmp_path / "any.ifc"
    ifc.write_text("", encoding="utf-8")

    def boom(*a, **k):
        raise ifcopenshell.Error("invalid IFC")

    monkeypatch.setattr(ifcopenshell, "open", boom)
    rc = main(["schedule", "--ifc", str(ifc), "--schedule", str(sched_path)])
    assert rc == 1
    assert "error: invalid IFC" in capsys.readouterr().err   # not a traceback


def test_multi_classified_element_links_to_every_codes_task(tmp_path):
    # issue #106, 4D surface: a furnish-and-drive pile carries two codes;
    # each code's task must claim it — dropping the second silently starves
    # that task (and everything cost5d spreads across it).
    import ifcopenshell.api.classification
    import ifcopenshell.api.root
    import ifcopenshell.api.unit

    f = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="p")
    ifcopenshell.api.unit.assign_unit(f)
    pile = ifcopenshell.api.root.create_entity(f, ifc_class="IfcPile",
                                               name="P-1")
    system = ifcopenshell.api.classification.add_classification(
        f, classification="BidSchedule")
    for code in ("PILE-200W-FRN", "PILE-200W-DRV"):
        ifcopenshell.api.classification.add_reference(
            f, products=[pile], identification=code, name=code,
            classification=system)

    sched = CanonicalSchedule(name="Piling", tasks=[
        ScheduleTask(id="frn", name="Furnish piles", wbs="1",
                     start="2026-07-10", finish="2026-07-12",
                     bid_item_codes=["PILE-200W-FRN"]),
        ScheduleTask(id="drv", name="Drive piles", wbs="2",
                     start="2026-07-13", finish="2026-07-15",
                     bid_item_codes=["PILE-200W-DRV"])])
    report = embed_schedule(f, sched)
    links = {rel.RelatingProcess.Name: [o.Name for o in rel.RelatedObjects]
             for rel in f.by_type("IfcRelAssignsToProcess")}
    assert links == {"Furnish piles": ["P-1"], "Drive piles": ["P-1"]}
    assert report.codes_without_elements == []


def _links(g):
    links = {}
    for rel in g.by_type("IfcRelAssignsToProcess"):
        links[rel.RelatingProcess.Name] = sorted(o.Name for o in rel.RelatedObjects)
    return links


def test_embed_filters_narrow_the_code_join(sample_ifc):
    # #365: codes join slab + wall + 4 columns (6); filter_re keeps the two
    # "A-" elements, filter_ifc_class keeps the columns, and both together
    # AND. A name_re selector still ORs in unfiltered.
    codes = ["03 30 00", "EF_25_10", "05 12 00"]
    sched = CanonicalSchedule(name="Filt", tasks=[
        ScheduleTask(id="a", name="Arch", wbs="1", start="2026-07-10",
                     finish="2026-07-12", bid_item_codes=codes,
                     filter_name_re=r"^A-"),
        ScheduleTask(id="c", name="Cols", wbs="2", start="2026-07-13",
                     finish="2026-07-15", bid_item_codes=codes,
                     filter_ifc_class="IfcColumn"),
        ScheduleTask(id="both", name="Both", wbs="3", start="2026-07-16",
                     finish="2026-07-17", bid_item_codes=codes,
                     filter_name_re=r"^A-", filter_ifc_class="IfcSlab"),
        ScheduleTask(id="or", name="Or", wbs="4", start="2026-07-18",
                     finish="2026-07-19", bid_item_codes=["05 12 00"],
                     filter_ifc_class="IfcWall", match_name_re=r"A-SLAB"),
    ])
    g, report = _embed(sample_ifc, sched, out_name="filt.ifc")
    links = _links(g)
    assert links["Arch"] == ["A-SLAB-34", "A-WALL-35"]
    assert links["Cols"] == ["COL"] * 4
    assert links["Both"] == ["A-SLAB-34"]
    assert links["Or"] == ["A-SLAB-34"]           # filter dropped the columns
    assert report.codes_without_elements == []


def test_embed_filter_that_empties_the_join_is_reported(sample_ifc):
    sched = CanonicalSchedule(name="Empty", tasks=[
        ScheduleTask(id="z", name="Zip", wbs="1", start="2026-07-10",
                     finish="2026-07-12", bid_item_codes=["05 12 00"],
                     filter_name_re=r"^ZZZ")])
    g, report = _embed(sample_ifc, sched, out_name="empty.ifc")
    assert "Zip" not in _links(g)
    assert report.assigned_elements == 0
    assert any("filter_re" in s and "Zip" in s
               for s in report.selectors_without_elements)


def test_embed_invalid_filter_regex_is_clean_error(sample_ifc):
    sched = CanonicalSchedule(name="Bad", tasks=[
        ScheduleTask(id="b", name="Bad", wbs="1", start="2026-07-10",
                     finish="2026-07-11", bid_item_codes=["05 12 00"],
                     filter_name_re="([")])
    with pytest.raises(ValueError, match="invalid filter_re"):
        embed_schedule(ifcopenshell.open(sample_ifc), sched)
