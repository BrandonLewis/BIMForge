import pytest

from bimforge.bim.schedule_model import (
    CanonicalSchedule, Dependency, ScheduleTask, resolve_bid_item_codes,
)


def _sched():
    return CanonicalSchedule(
        name="OH Bridge BL V.07",
        start_date="2026-07-10",
        work_weekdays=[0, 1, 2, 3, 4],
        holidays=["2026-09-07"],
        tasks=[
            ScheduleTask(id="t1", name="Substructure Summary", wbs="1.1"),
            ScheduleTask(id="t2", name="AB.1010  Finegrade for Abutment",
                         wbs="1.1.1", start="2026-07-10", finish="2026-07-14"),
            ScheduleTask(id="t3", name="AB.1020  Construct Abutment Piles",
                         wbs="1.1.2", start="2026-07-15", finish="2026-08-12",
                         dependencies=[Dependency(predecessor="t2")]),
            ScheduleTask(id="t4", name="Deck pour", wbs="1.2",
                         start="2026-08-13", finish="2026-09-01",
                         dependencies=[Dependency(predecessor="t3",
                                                  type="SS", lag_days=2.0)]),
        ],
    )


def test_round_trip_preserves_everything():
    sched = _sched()
    sched.tasks[1].bid_item_codes = ["190101"]
    again = CanonicalSchedule.from_json(sched.to_json())
    assert again == sched
    assert again.tasks[2].dependencies[0].predecessor == "t2"
    assert again.tasks[3].dependencies[0].type == "SS"
    assert again.tasks[3].dependencies[0].lag_days == 2.0


def test_to_dict_omits_empty_resources_and_activity_codes():
    # Old-shape canonical JSON (pre-R8, no resources/activity_codes keys)
    # must round-trip to the identical dict — the fields are omitted when
    # empty, not serialized as [].
    old = {
        "name": "x", "start_date": None,
        "work_weekdays": [0, 1, 2, 3, 4], "holidays": [],
        "tasks": [{"id": "t1", "name": "a", "wbs": "1", "start": None,
                   "finish": None, "duration_days": None,
                   "is_milestone": False, "dependencies": [],
                   "bid_item_codes": [], "match_name_re": None,
                   "match_ifc_class": None}],
    }
    assert CanonicalSchedule.from_dict(old).to_dict() == old
    d = _sched().to_dict()
    for t in d["tasks"]:
        assert "resources" not in t
        assert "activity_codes" not in t


def test_resources_and_activity_codes_round_trip():
    sched = _sched()
    sched.tasks[1].resources = ["Pile Crew", "Concrete Crew"]
    sched.tasks[1].activity_codes = ["Subcontractor: SUB-A"]
    d = sched.to_dict()
    assert d["tasks"][1]["resources"] == ["Pile Crew", "Concrete Crew"]
    assert d["tasks"][1]["activity_codes"] == ["Subcontractor: SUB-A"]
    again = CanonicalSchedule.from_json(sched.to_json())
    assert again == sched
    assert again.tasks[1].resources == ["Pile Crew", "Concrete Crew"]
    assert again.tasks[1].activity_codes == ["Subcontractor: SUB-A"]
    assert again.tasks[0].resources == []
    assert again.tasks[0].activity_codes == []


def test_validate_passes_on_good_schedule():
    _sched().validate()


def test_validate_rejects_duplicate_ids():
    sched = _sched()
    sched.tasks[1].id = "t1"
    with pytest.raises(ValueError, match="duplicate task id"):
        sched.validate()


def test_validate_rejects_finish_before_start():
    sched = _sched()
    sched.tasks[2].finish = "2026-07-01"
    with pytest.raises(ValueError, match="finish before start"):
        sched.validate()


def test_validate_rejects_unknown_predecessor_and_bad_type():
    sched = _sched()
    sched.tasks[3].dependencies[0].predecessor = "nope"
    with pytest.raises(ValueError, match="unknown predecessor"):
        sched.validate()
    sched = _sched()
    sched.tasks[3].dependencies[0].type = "XX"
    with pytest.raises(ValueError, match="dependency type"):
        sched.validate()


def test_validate_rejects_dependency_cycles():
    sched = _sched()
    sched.tasks[1].dependencies = [Dependency(predecessor="t4")]
    with pytest.raises(ValueError, match="cycle"):
        sched.validate()


def test_summary_detection_by_wbs_prefix():
    sched = _sched()
    assert sched.summary_ids() == {"t1"}       # 1.1 has children 1.1.1/1.1.2


def test_summary_detection_multi_level_and_no_false_prefix():
    # 1.1 is a parent of 1.1.1; 1.11 must NOT count as a child of 1.1.
    sched = CanonicalSchedule(name="x", tasks=[
        ScheduleTask(id="a", name="root", wbs="1"),
        ScheduleTask(id="b", name="mid", wbs="1.1"),
        ScheduleTask(id="c", name="leaf", wbs="1.1.1"),
        ScheduleTask(id="d", name="sibling", wbs="1.11"),
    ])
    assert sched.summary_ids() == {"a", "b"}    # not "d" (1.11), not "c"


def test_from_dict_tolerates_null_tasks_and_dependencies():
    # A producer may serialize omitted collections as null; don't crash.
    sched = CanonicalSchedule.from_dict({"name": "empty", "tasks": None})
    assert sched.tasks == []
    sched = CanonicalSchedule.from_dict({"name": "x", "tasks": [
        {"id": "t1", "name": "solo", "wbs": "1", "dependencies": None}]})
    assert sched.tasks[0].dependencies == []


def test_resolve_precedence_explicit_map_then_regex():
    sched = _sched()
    report = resolve_bid_item_codes(
        sched,
        task_map={"t2": ["190101"], "1.1.2": ["490505", "490506"]},
        name_code_re=r"\b([A-Z]{2,}\.\d{4})\b")
    by_id = {t.id: t for t in sched.tasks}
    assert by_id["t2"].bid_item_codes == ["190101"]        # map by id wins
    assert by_id["t3"].bid_item_codes == ["490505", "490506"]  # map by wbs
    assert by_id["t4"].bid_item_codes == []                # regex no match
    assert set(report.mapped) == {"t2", "t3"}
    assert report.unmapped == ["t4"]                       # leaf, no codes
    assert report.summaries == ["t1"]                      # never "unmapped"


def test_resolve_regex_extracts_and_keeps_existing_codes():
    sched = _sched()
    sched.tasks[3].bid_item_codes = ["510120"]             # importer-carried
    report = resolve_bid_item_codes(sched, name_code_re=r"\b([A-Z]{2,}\.\d{4})\b")
    by_id = {t.id: t for t in sched.tasks}
    assert by_id["t2"].bid_item_codes == ["AB.1010"]       # regex capture
    assert by_id["t4"].bid_item_codes == ["510120"]        # kept, still mapped
    assert "t4" in report.mapped and not report.unmapped


def test_resolve_dict_task_map_sets_selectors():
    sched = _sched()
    report = resolve_bid_item_codes(sched, task_map={
        "t2": {"name_re": r"^RW\d|retaining wall"},
        "t3": {"ifc_class": "IfcPile", "codes": ["490505"]},
        "t4": {"codes": ["510120"]},
    })
    by_id = {t.id: t for t in sched.tasks}
    assert by_id["t2"].match_name_re == r"^RW\d|retaining wall"
    assert by_id["t2"].bid_item_codes == []
    assert by_id["t3"].match_ifc_class == "IfcPile"
    assert by_id["t3"].bid_item_codes == ["490505"]
    assert by_id["t4"].bid_item_codes == ["510120"]
    # a task with only a selector (no code) still counts as mapped, not unmapped
    assert set(report.mapped) == {"t2", "t3", "t4"}
    assert report.unmapped == []


def test_resolve_explicit_code_list_replaces_selectors():
    # docstring precedence: an explicit map entry REPLACES anything present —
    # a bare code list must also clear any pre-existing name/class selectors.
    sched = _sched()
    sched.tasks[1].match_name_re = r"^RW"
    sched.tasks[1].match_ifc_class = "IfcWall"
    resolve_bid_item_codes(sched, task_map={"t2": ["190101"]})
    by_id = {t.id: t for t in sched.tasks}
    assert by_id["t2"].bid_item_codes == ["190101"]
    assert by_id["t2"].match_name_re is None
    assert by_id["t2"].match_ifc_class is None


def test_resolve_dedupes_preserving_order():
    sched = _sched()
    sched.tasks[1].name = "AB.1010 then AB.1010 again AB.1020"
    resolve_bid_item_codes(sched, name_code_re=r"\b([A-Z]{2,}\.\d{4})\b")
    assert sched.tasks[1].bid_item_codes == ["AB.1010", "AB.1020"]


def test_pre_335_json_round_trips_without_new_keys():
    """#335's fields serialize only when set: earlier JSON is unchanged."""
    d = _sched().to_dict()
    assert "calendars" not in d
    for t in d["tasks"]:
        assert not {"global_id", "task_type", "bid_items", "notes",
                    "calendar"} & set(t)
    assert CanonicalSchedule.from_dict(d).to_dict() == d


def test_new_fields_round_trip_through_json():
    from bimforge.bim.schedule_model import Calendar

    s = _sched()
    s.calendars = {"fish": Calendar(blackouts=[{"from": "10-02",
                                                "to": "05-31"}])}
    t = s.tasks[1]
    t.global_id, t.task_type, t.bid_items = "2O2Fr$t4X7Zf8NOew3FLOH", \
        "DEMOLITION", ["67"]
    t.notes, t.calendar = "JUDGEMENT ~4 piles/day", "fish"
    s.validate()
    back = CanonicalSchedule.from_json(s.to_json())
    assert back == s


def test_estimating_tools_reexports_the_same_model():
    model = pytest.importorskip("estimating_tools.schedule.model")
    from bimforge.bim import schedule_model

    for name in ("CanonicalSchedule", "ScheduleTask", "Dependency",
                 "Calendar", "resolve_bid_item_codes", "MapReport"):
        assert getattr(model, name) is getattr(schedule_model, name)


def test_resolve_dict_task_map_sets_filters_and_bare_list_clears_them():
    # #365: filter_re / filter_ifc_class narrow the code join (AND); they
    # ride ScheduleTask.filter_name_re / filter_ifc_class
    sched = _sched()
    resolve_bid_item_codes(sched, task_map={
        "t2": {"codes": ["190101"], "filter_re": r"^RW\d", "filter_ifc_class": "IfcWall"},
        "t3": {"codes": ["490505"], "filter_ifc_class": "IfcPile"},
    })
    by_id = {t.id: t for t in sched.tasks}
    assert by_id["t2"].bid_item_codes == ["190101"]
    assert by_id["t2"].filter_name_re == r"^RW\d"
    assert by_id["t2"].filter_ifc_class == "IfcWall"
    assert by_id["t2"].match_name_re is None and by_id["t2"].match_ifc_class is None
    assert by_id["t3"].filter_name_re is None
    assert by_id["t3"].filter_ifc_class == "IfcPile"
    resolve_bid_item_codes(sched, task_map={"t2": ["190101"]})
    assert by_id["t2"].filter_name_re is None and by_id["t2"].filter_ifc_class is None


def test_resolve_filter_without_codes_is_a_loud_error():
    # a filter narrows the code join; with nothing to narrow it is a typo
    sched = _sched()
    with pytest.raises(ValueError, match="filter"):
        resolve_bid_item_codes(sched, task_map={"t2": {"filter_re": "^RW"}})


def test_filters_serialize_only_when_set_and_round_trip():
    sched = _sched()
    d = sched.to_dict()
    for t in d["tasks"]:
        assert "filter_name_re" not in t and "filter_ifc_class" not in t
    sched.tasks[1].filter_name_re = r"^RW\d"
    sched.tasks[1].filter_ifc_class = "IfcWall"
    again = CanonicalSchedule.from_json(sched.to_json())
    assert again == sched
    assert again.tasks[1].filter_name_re == r"^RW\d"
    assert again.tasks[1].filter_ifc_class == "IfcWall"
    assert again.tasks[0].filter_name_re is None
