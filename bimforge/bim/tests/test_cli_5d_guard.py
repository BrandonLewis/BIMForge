"""est-bim's 4D/5D subcommands need nothing from the estimating layer.

The schedule readers (GanttWarrior / P6 XER / MSPDI) used to live in
estimating_tools.schedule.importers and the schedule/cost5d handlers imported
them behind a guard that printed "install estimating-core and retry". They now
live in bimforge.bim.schedule_io (bimforge package split, step 1), so with
estimating_tools made to look uninstalled every subcommand still gets as far as
its input files.
"""
import json
import sys

import pytest

pytest.importorskip("ifcopenshell")

from bimforge.bim import cli


class _BlockEstimatingTools:
    """meta_path finder that makes estimating_tools look uninstalled."""

    def find_spec(self, name, path=None, target=None):
        if name == "estimating_tools" or name.startswith("estimating_tools."):
            raise ModuleNotFoundError(f"blocked for test: {name}")
        return None


@pytest.fixture
def no_estimating_tools(monkeypatch):
    # Drop cached modules so any import actually hits the finder; monkeypatch
    # restores the originals (same objects) on teardown.
    for name in list(sys.modules):
        if name == "estimating_tools" or name.startswith("estimating_tools."):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(
        sys, "meta_path", [_BlockEstimatingTools()] + sys.meta_path)


@pytest.mark.parametrize("argv", [
    ["schedule", "--ifc", "x.ifc", "--schedule", "s.xer"],
    ["cost5d", "--ifc", "x.ifc", "--schedule", "s.xer", "--costs", "c.json"],
    ["estimate5d", "--ifc", "x.ifc", "--map", "m.yaml", "--costs", "c.json"],
])
def test_4d_5d_commands_reach_their_inputs_without_estimating_core(
        no_estimating_tools, capsys, argv):
    rc = cli.main(argv)
    err = capsys.readouterr().err
    assert rc == 1                       # the files don't exist: a plain error
    assert "error:" in err
    assert "estimating-core" not in err
    assert not [m for m in sys.modules if m.startswith("estimating_tools")]


def test_schedule_loader_is_bimforges_own(no_estimating_tools, tmp_path):
    from bimforge.bim.schedule_io import load_schedule

    gw = {"name": "S", "start_date": "2026-08-10",
          "default_work_weekdays": [0, 1, 2, 3, 4],
          "tasks": [{"id": "t1", "name": "Pour", "wbs": "1",
                     "start_date": "2026-08-10", "end_date": "2026-08-14",
                     "bid_item_codes": ["A"], "dependencies": []}]}
    p = tmp_path / "s.gw.json"
    p.write_text(json.dumps(gw), encoding="utf-8")
    sched = load_schedule(p)
    assert [t.bid_item_codes for t in sched.tasks] == [["A"]]
    assert not [m for m in sys.modules if m.startswith("estimating_tools")]


def test_cost5d_embed_needs_no_estimating_core(no_estimating_tools):
    import ifcopenshell
    import ifcopenshell.api.root as root

    from bimforge.bim.cost5d import embed_cost_and_resources
    from bimforge.bim.schedule4d import embed_schedule
    from bimforge.bim.schedule_model import CanonicalSchedule, ScheduleTask
    from bimforge.bim.schedule_read import read_costs

    sched = CanonicalSchedule(name="S", tasks=[ScheduleTask(
        id="t1", name="Pour", start="2026-08-10", finish="2026-08-14",
        bid_item_codes=["A"])])
    f = ifcopenshell.file(schema="IFC4X3_ADD2")
    root.create_entity(f, ifc_class="IfcProject")
    embed_schedule(f, sched)
    embed_cost_and_resources(f, sched, {"A": {"cost": 100.0,
                                              "labor_hours": 8.0}})
    assert read_costs(f)["costs"] == {"A": {"cost": 100.0, "labor_hours": 8.0}}
    assert not [m for m in sys.modules if m.startswith("estimating_tools")]
