"""bimforge.bim.schedule_state: the 4D state on a day."""
from __future__ import annotations

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
import ifcopenshell.api  # noqa: E402

from bimforge.bim.schedule_state import (  # noqa: E402
    Span, element_spans, event_days, shift_day, standing, state)


def _model():
    f = ifcopenshell.file(schema="IFC4X3_ADD2")
    run = ifcopenshell.api.run
    run("root.create_entity", f, ifc_class="IfcProject")
    el = {n: run("root.create_entity", f, ifc_class="IfcWall", name=n)
          for n in ("old deck", "sheet pile", "new deck", "existing grade",
                    "crane mat")}
    ws = run("sequence.add_work_schedule", f, name="baseline")

    def task(name, kind, start, objs, output=False):
        t = run("sequence.add_task", f, work_schedule=ws, name=name)
        t.PredefinedType = kind
        tt = run("sequence.add_task_time", f, task=t)
        run("sequence.edit_task_time", f, task_time=tt,
            attributes={"ScheduleStart": f"{start}T08:00:00"})
        for o in objs:
            if output:
                run("sequence.assign_product", f, relating_product=el[o],
                    related_object=t)
            else:
                run("sequence.assign_process", f, relating_process=t,
                    related_object=el[o])
        return t

    task("Stage 1 shoring", "CONSTRUCTION", "2027-06-10", ["sheet pile"])
    task("Stage 1 demo deck", "DEMOLITION", "2027-06-18", ["old deck"],
         output=True)
    task("Stage 1 deck", "CONSTRUCTION", "2027-09-15", ["new deck"],
         output=True)
    task("Crane mats in", "INSTALLATION", "2027-08-24", ["crane mat"])
    task("Crane mats out", "REMOVAL", "2027-08-26", ["crane mat"],
         output=True)
    task("Pull sheets", "DISMANTLE", "2028-05-01", ["sheet pile"],
         output=True)
    t = task("Inspect", "OPERATION", "2027-07-01", ["new deck"])  # moves nothing
    assert t.PredefinedType == "OPERATION"
    return f, {n: e.GlobalId for n, e in el.items()}


def test_spans_read_both_link_directions_and_types():
    f, g = _model()
    sp = element_spans(f)
    assert sp[g["sheet pile"]] == Span("2027-06-10", "2028-05-01",
                                       ("Stage 1 shoring", "Pull sheets"))
    assert sp[g["old deck"]].appear is None
    assert sp[g["old deck"]].vanish == "2027-06-18"
    assert sp[g["new deck"]].appear == "2027-09-15"   # OPERATION ignored
    assert g["existing grade"] not in sp                 # untouched


def test_state_on_a_day():
    f, g = _model()
    sp = element_spans(f)

    def up(day):
        return {n for n, gid in g.items() if standing(sp.get(gid), day)}

    assert up("2027-06-09") == {"old deck", "existing grade"}
    # stage 1 before the deck demo: shoring in, old deck still there
    assert up("2027-06-15") == {"old deck", "sheet pile", "existing grade"}
    assert up("2027-06-18") == {"sheet pile", "existing grade"}   # demo day
    assert up("2027-08-25") == {"sheet pile", "existing grade", "crane mat"}
    assert up("2027-09-15") == {"sheet pile", "existing grade", "new deck"}
    assert up("2028-05-01") == {"existing grade", "new deck"}
    assert state(sp[g["new deck"]], "2027-06-15") == "not yet built"
    assert state(sp[g["old deck"]], "2027-07-01") == "removed"
    assert state(None, "2027-07-01") == "standing"


def test_event_days_and_shift():
    f, _ = _model()
    assert event_days(element_spans(f)) == [
        "2027-06-10", "2027-06-18", "2027-08-24", "2027-08-26", "2027-09-15",
        "2028-05-01"]
    assert shift_day("2027-06-28", 7) == "2027-07-05"
    assert shift_day("2028-03-01", -1) == "2028-02-29"
