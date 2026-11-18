"""Carry a returned IFC's own additions onto a rebuilt one (#83)."""
import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

import ifcopenshell.api.root as root  # noqa: E402
import ifcopenshell.api.sequence as sq  # noqa: E402

from bimforge.bim.carry_forward import carry_forward  # noqa: E402
from bimforge.bim.schedule4d import embed_schedule  # noqa: E402
from bimforge.bim.tests.test_stable_ids import (  # noqa: E402
    OTHER, _linked, _linked_file, _one, _wall_file,
)


def _stamp(f, action="ADDED"):
    org = f.createIfcOrganization(Name="downstream")
    app = f.createIfcApplication(org, "1.0", "ProjectCommand", "ProjectCommand")
    who = f.createIfcPersonAndOrganization(f.createIfcPerson(FamilyName="p"), org)
    return f.createIfcOwnerHistory(who, app, None, action, 1794783608, None,
                                   None, 1794783608)


def _returned(action="ADDED"):
    """Our schedule file with a downstream tool's additions: its own copy of
    the Deck task tied to ours, progress on the copy, the copy building one
    of our walls, and an approval on a wall."""
    f = _linked_file()
    oh = _stamp(f, action)
    ws = root.create_entity(f, ifc_class="IfcWorkSchedule", name="Update")
    ws.GlobalId, ws.OwnerHistory, ws.Purpose = "1PCschedule00000000000", oh, \
        "Contractor update"
    copy = root.create_entity(f, ifc_class="IfcTask", name="Deck")
    copy.GlobalId, copy.OwnerHistory = "1PCtaskDeck00000000000", oh
    tt = sq.add_task_time(f, copy)
    tt.ActualStart, tt.Completion = "2026-07-11T00:00:00", 0.4
    deck = _one(f, "IfcTask", lambda e: e.Name == "Deck" and e != copy)
    f.createIfcRelDefinesByObject("1PCdefines000000000000", oh, None, None,
                                  [copy], deck)
    f.createIfcRelAssignsToControl("1PCcontrols00000000000", oh, None, None,
                                   [copy], None, ws)
    wall = _one(f, "IfcWall", lambda e: e.Name == "wall 0")
    f.createIfcRelAssignsToProduct("1PCbuilds0000000000000", oh, None, None,
                                   [copy], None, wall)
    asker, giver = (f.createIfcOrganization(Name=n) for n in ("Sub", "Owner"))
    approval = f.createIfcApproval("03-01", "Shear key", "shop drawing",
                                   "2026-10-20T00:00:00", "approved as noted",
                                   None, None, asker, giver)
    f.createIfcRelAssociatesApproval("1PCapproval00000000000", oh, "Shear key",
                                     None, [wall], approval)
    return f


def _rebuilt(sched=None, gid=None):
    f = _wall_file(*([gid] if gid else []))
    embed_schedule(f, sched or _linked())
    return f


def _by(f, gid):
    return f.by_guid(gid)


def test_every_addition_is_carried_with_its_ids_and_repointed():
    returned, rebuilt = _returned(), _rebuilt()
    report = carry_forward(returned, rebuilt)
    assert report.carried == 6 and report.applications == ["ProjectCommand"]
    assert not (report.vanished or report.dropped or report.modified)
    copy = _by(rebuilt, "1PCtaskDeck00000000000")
    assert copy.TaskTime.Completion == pytest.approx(0.4)
    link = _by(rebuilt, "1PCdefines000000000000")
    deck = _one(rebuilt, "IfcTask", lambda e: e.Name == "Deck" and e != copy)
    assert link.RelatingObject == deck and link.RelatedObjects == (copy,)
    wall = _one(rebuilt, "IfcWall", lambda e: e.Name == "wall 0")
    assert _by(rebuilt, "1PCbuilds0000000000000").RelatingProduct == wall
    appr = _by(rebuilt, "1PCapproval00000000000")
    assert appr.RelatedObjects == (wall,)
    assert appr.RelatingApproval.Identifier == "03-01"
    assert appr.RelatingApproval.GivingApproval.Name == "Owner"
    assert appr.OwnerHistory.OwningApplication.ApplicationIdentifier == \
        "ProjectCommand"


def test_carrying_twice_adds_nothing_new():
    returned, rebuilt = _returned(), _rebuilt()
    carry_forward(returned, rebuilt)
    n = len(list(rebuilt))
    again = carry_forward(returned, rebuilt)
    assert again.carried == 0 and again.already_present == 6
    assert len(list(rebuilt)) == n


def test_a_task_the_source_dropped_drops_the_link_and_is_reported():
    sched = _linked()
    sched.tasks[1].id = "a2"            # Deck has a new id: its GlobalId goes
    sched.tasks[2].dependencies[0].predecessor = "a2"
    report = carry_forward(_returned(), _rebuilt(sched))
    assert [d["global_id"] for d in report.dropped] == ["1PCdefines000000000000"]
    assert report.dropped[0]["missing"][0]["name"] == "Deck"
    assert report.carried == 5           # the rest still comes across


def test_an_element_no_longer_in_the_model_drops_its_approval():
    rebuilt = _rebuilt()
    wall = _one(rebuilt, "IfcWall", lambda e: e.Name == "wall 0")
    rebuilt.remove(wall)
    report = carry_forward(_returned(), rebuilt)
    assert {d["global_id"] for d in report.dropped} == {
        "1PCapproval00000000000", "1PCbuilds0000000000000"}


def test_uncovered_tasks_and_elements_are_reported():
    report = carry_forward(_returned(), _rebuilt())
    assert {t["name"] for t in report.uncovered_tasks} == {"Structure", "Walls"}
    assert {e["name"] for e in report.uncovered_elements} == {"wall 1", "wall 2"}


def test_without_a_downstream_schedule_nothing_is_uncovered():
    returned = _linked_file()
    oh = _stamp(returned)
    wall = _one(returned, "IfcWall", lambda e: e.Name == "wall 0")
    approval = returned.createIfcApproval("1", "x", None, None, "ok", None,
                                          None, None, None)
    returned.createIfcRelAssociatesApproval("1PCapproval00000000000", oh, None,
                                            None, [wall], approval)
    report = carry_forward(returned, _rebuilt())
    assert report.carried == 1
    assert not (report.uncovered_tasks or report.uncovered_elements)


def test_a_modified_task_of_ours_is_rebuilt_and_reported():
    returned = _returned()
    deck = _one(returned, "IfcTask",
                lambda e: e.Name == "Deck" and e.OwnerHistory is None)
    deck.TaskTime.ScheduleFinish = "2026-08-01T00:00:00"
    rebuilt = _rebuilt()
    report = carry_forward(returned, rebuilt)
    assert [m["global_id"] for m in report.modified] == [deck.GlobalId]
    assert rebuilt.by_guid(deck.GlobalId).TaskTime.ScheduleFinish \
        != "2026-08-01T00:00:00"


def test_a_rewritten_update_is_carried_as_it_is():
    # a downstream tool may replace what it added itself (stamped MODIFIED):
    # it is still its own, so it is carried, stamp and all, and not reported
    returned, rebuilt = _returned("MODIFIED"), _rebuilt()
    report = carry_forward(returned, rebuilt)
    assert report.carried == 6
    assert not (report.vanished or report.dropped or report.modified)
    copy = _by(rebuilt, "1PCtaskDeck00000000000")
    assert copy.OwnerHistory.ChangeAction == "MODIFIED"


def test_a_kept_update_retyped_baseline_is_carried_beside_the_current_one():
    # its last update kept to compare against: retyped BASELINE, re-keyed,
    # and still tied to our task, as the current update is
    returned = _returned("MODIFIED")
    oh = returned.by_guid("1PCtaskDeck00000000000").OwnerHistory
    kept = root.create_entity(returned, ifc_class="IfcWorkSchedule",
                              name="Update (kept)")
    kept.GlobalId, kept.OwnerHistory, kept.PredefinedType = \
        "1PCkeptSchedule0000000", oh, "BASELINE"
    copy = root.create_entity(returned, ifc_class="IfcTask", name="Deck")
    copy.GlobalId, copy.OwnerHistory = "1PCkeptDeck00000000000", oh
    deck = _one(returned, "IfcTask",
                lambda e: e.Name == "Deck" and e.OwnerHistory is None)
    returned.createIfcRelDefinesByObject("1PCkeptDefines00000000", oh, None,
                                         None, [copy], deck)
    returned.createIfcRelAssignsToControl("1PCkeptControls0000000", oh, None,
                                          None, [copy], None, kept)
    rebuilt = _rebuilt()
    report = carry_forward(returned, rebuilt)
    assert report.carried == 10
    assert not (report.vanished or report.dropped or report.modified)
    assert _by(rebuilt, "1PCkeptSchedule0000000").PredefinedType == "BASELINE"
    ours = _one(rebuilt, "IfcTask",
                lambda e: e.Name == "Deck" and e.OwnerHistory is None)
    for gid in ("1PCdefines000000000000", "1PCkeptDefines00000000"):
        assert _by(rebuilt, gid).RelatingObject == ours


def test_another_project_is_refused():
    with pytest.raises(ValueError, match="another project"):
        carry_forward(_returned(), _rebuilt(gid=OTHER))

def test_cli_schedule_carries_a_returned_file(tmp_path, capsys):
    import json

    from bimforge.bim.cli import main
    site, sched, back = (str(tmp_path / n) for n in
                         ("site.ifc", "bl.json", "back.ifc"))
    _wall_file().write(site)
    (tmp_path / "bl.json").write_text(_linked().to_json(), encoding="utf-8")
    _returned().write(back)
    out = str(tmp_path / "site.4d.ifc")
    assert main(["schedule", "--ifc", site, "--schedule", sched, "--out", out,
                 "--returned", back]) == 0
    assert "Carried 6 addition(s) from ProjectCommand" in capsys.readouterr().out
    f = ifcopenshell.open(out)
    assert f.by_guid("1PCapproval00000000000").RelatingApproval.Identifier == "03-01"
    report = json.loads((tmp_path / "site.4d.carry.json").read_text())
    assert report["carried"] == 6 and not report["modified"]

def test_our_schedule_is_planned_and_dated_from_the_source():
    from bimforge.bim.schedule_read import read_schedule
    f = _rebuilt()
    (ws,) = f.by_type("IfcWorkSchedule")
    assert ws.PredefinedType == "PLANNED"
    assert ws.CreationDate == "2026-07-10T00:00:00"     # its start_date
    sched = _linked()
    sched.schedule_type = "BASELINE"
    g = _wall_file()
    embed_schedule(g, sched)
    assert read_schedule(g).schedule_type == "BASELINE"


def test_an_unknown_schedule_type_is_refused():
    sched = _linked()
    sched.schedule_type = "LATEST"
    with pytest.raises(ValueError, match="schedule_type"):
        embed_schedule(_wall_file(), sched)

def test_a_sweep_after_the_carry_moves_no_id():
    """The downstream copy shares our task pset through its own rel; our
    pset's key must not count that owner, or the next sweep re-keys it."""
    from bimforge.bim import stable_ids
    returned = _returned()
    oh = returned.by_guid("1PCtaskDeck00000000000").OwnerHistory
    copy = returned.by_guid("1PCtaskDeck00000000000")
    deck = returned.by_guid("1PCdefines000000000000").RelatingObject
    (pset,) = [r.RelatingPropertyDefinition for r in deck.IsDefinedBy]
    returned.createIfcRelDefinesByProperties("1PCsharesPset000000000", oh, None,
                                             None, [copy], pset)
    rebuilt = _rebuilt()
    carry_forward(returned, rebuilt)
    before = {e.GlobalId for e in rebuilt.by_type("IfcRoot")}
    stable_ids.key_relationships(rebuilt)
    assert {e.GlobalId for e in rebuilt.by_type("IfcRoot")} == before
    assert rebuilt.by_guid(pset.GlobalId).Name == pset.Name

def test_typed_values_are_copied_each_as_written():
    """Two lags and two pset values: each IfcDuration and IfcLabel keeps
    its own value (typed values all have id 0, so a cache would merge them)."""
    import ifcopenshell.api.pset as pset_api
    returned = _returned()
    oh = returned.by_guid("1PCtaskDeck00000000000").OwnerHistory
    copy = returned.by_guid("1PCtaskDeck00000000000")
    other = root.create_entity(returned, ifc_class="IfcTask", name="Extra")
    other.GlobalId, other.OwnerHistory = "1PCtaskExtra0000000000", oh
    for gid, days, succ in (("1PCseq1000000000000000", "P1D", other),
                            ("1PCseq2000000000000000", "P7D", copy)):
        lag = returned.createIfcLagTime(
            None, None, None, returned.create_entity("IfcDuration", days),
            "ELAPSEDTIME")
        src = copy if succ is other else other
        returned.createIfcRelSequence(gid, oh, None, None, src, succ, lag,
                                      "FINISH_START", None)
    ps = pset_api.add_pset(returned, product=other, name="PC_Note")
    pset_api.edit_pset(returned, pset=ps, properties={"A": "first", "B": "second"})
    ps.GlobalId, ps.OwnerHistory = "1PCpset000000000000000", oh
    (rel,) = ps.DefinesOccurrence
    rel.GlobalId, rel.OwnerHistory = "1PCdefinesPset00000000", oh
    rebuilt = _rebuilt()
    carry_forward(returned, rebuilt)
    lags = {g: rebuilt.by_guid(g).TimeLag.LagValue.wrappedValue
            for g in ("1PCseq1000000000000000", "1PCseq2000000000000000")}
    assert lags == {"1PCseq1000000000000000": "P1D",
                    "1PCseq2000000000000000": "P7D"}
    values = {p.Name: p.NominalValue.wrappedValue
              for p in rebuilt.by_guid("1PCpset000000000000000").HasProperties}
    assert values == {"A": "first", "B": "second"}
