"""Stable GlobalIds for what the embedders write (#74): a re-embed, or the
same embed on a rebuilt file, writes the same ids again."""
import uuid

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

import ifcopenshell.api.root as root  # noqa: E402
import ifcopenshell.guid  # noqa: E402

from bimforge.bim import cost5d, estimate5d, stable_ids  # noqa: E402
from bimforge.bim.estimate_model5d import embed_estimate_model  # noqa: E402
from bimforge.bim.schedule4d import embed_schedule  # noqa: E402
from bimforge.bim.schedule_model import (  # noqa: E402
    CanonicalSchedule, Dependency, ScheduleTask,
)
from bimforge.bim.tests.test_estimate5d import (  # noqa: E402
    PILE_COSTS, PILE_MAP, _pile_ifc,
)
from bimforge.bim.tests.test_estimate_model5d import (  # noqa: E402
    _ifc as _model_ifc, _model_json,
)

PROJECT = ifcopenshell.guid.compress(uuid.UUID(int=1).hex)
OTHER = ifcopenshell.guid.compress(uuid.UUID(int=2).hex)
KEYED = ("IfcWorkSchedule", "IfcWorkCalendar", "IfcTask", "IfcCostSchedule",
         "IfcCostItem", "IfcLaborResource")


def _pin(f, gid=PROJECT):
    f.by_type("IfcProject")[0].GlobalId = gid
    return f


def _file(gid=PROJECT):
    f = ifcopenshell.file(schema="IFC4")
    root.create_entity(f, ifc_class="IfcProject", name="p")
    return _pin(f, gid)


def _ids(f):
    """{(class, path): GlobalId} for every keyed entity in `f`."""
    out = {}
    for cls in KEYED:
        for ent in f.by_type(cls):
            label = (getattr(ent, "Identification", None) or "") + "|" + (ent.Name or "")
            key = (cls, label)
            n = 1
            while key in out:
                n += 1
                key = (cls, f"{label}#{n}")
            out[key] = ent.GlobalId
    return out


def _sched(task_ids=("s", "a", "b")):
    return CanonicalSchedule(
        name="BL", start_date="2026-07-10", work_weekdays=[0, 1, 2, 3, 4],
        holidays=["2026-09-07"],
        tasks=[ScheduleTask(id=task_ids[0], name="Structure", wbs="1"),
               ScheduleTask(id=task_ids[1], name="Deck", wbs="1.1",
                            start="2026-07-10", finish="2026-07-14",
                            bid_item_codes=["A"]),
               ScheduleTask(id=task_ids[2], name="Walls", wbs="1.2",
                            start="2026-07-15", finish="2026-07-20",
                            bid_item_codes=["B"])])


def _scheduled(gid=PROJECT, sched=None):
    f = _file(gid)
    embed_schedule(f, sched or _sched())
    return f


def test_the_namespace_is_the_project_global_id():
    f = _file()
    assert stable_ids.namespace(f) == uuid.UUID(int=1)
    assert stable_ids.stable_id(f, "task/BL/a") == ifcopenshell.guid.compress(
        uuid.uuid5(uuid.UUID(int=1), "task/BL/a").hex)


def test_a_file_without_a_project_is_refused():
    with pytest.raises(ValueError, match="IfcProject"):
        stable_ids.namespace(ifcopenshell.file(schema="IFC4"))


def test_schedule_ids_repeat_across_files_and_re_embeds():
    a, b = _scheduled(), _scheduled()
    ids = _ids(a)
    assert {c for c, _ in ids} == {"IfcWorkSchedule", "IfcWorkCalendar",
                                   "IfcTask"}
    assert ids == _ids(b)
    embed_schedule(a, _sched())             # replaced by name
    assert _ids(a) == ids


def test_a_changed_task_id_changes_that_task_only():
    before = _ids(_scheduled())
    after = _ids(_scheduled(sched=_sched(("s", "a", "b2"))))
    changed = {k for k in before if before[k] != after.get(k)}
    assert changed == {("IfcTask", "1.2|Walls")}


def test_another_project_gets_other_ids():
    a, b = _ids(_scheduled()), _ids(_scheduled(OTHER))
    assert a.keys() == b.keys()
    assert not set(a.values()) & set(b.values())


def test_an_explicit_task_global_id_still_wins():
    gid = ifcopenshell.guid.compress(uuid.UUID(int=99).hex)
    sched = _sched()
    sched.tasks[1].global_id = gid
    f = _scheduled(sched=sched)
    (deck,) = [t for t in f.by_type("IfcTask") if t.Name == "Deck"]
    assert deck.GlobalId == gid


def test_two_keys_on_one_id_fail_loud():
    f = _file()
    a = root.create_entity(f, ifc_class="IfcTask", name="a")
    b = root.create_entity(f, ifc_class="IfcTask", name="b")
    stable_ids.assign(f, a, "task/x/1")
    stable_ids.assign(f, a, "task/x/1")     # its own id again is fine
    with pytest.raises(ValueError, match="already used by IfcTask 'a'"):
        stable_ids.assign(f, b, "task/x/1")


def _costed(gid=PROJECT):
    f = _scheduled(gid)
    costs = {"A": {"cost": 1000.0, "labor_hours": 40.0},
             "B": {"cost": 500.0, "labor_hours": 10.0}}
    cost5d.embed_cost_and_resources(f, _sched(), costs, work_hours_per_day=8.0)
    return f, costs


def test_cost5d_ids_repeat_across_files_and_re_embeds():
    (a, costs), (b, _) = _costed(), _costed()
    ids = _ids(a)
    assert {"IfcCostSchedule", "IfcCostItem", "IfcLaborResource"} <= {
        c for c, _ in ids}
    assert ids == _ids(b)
    cost5d.embed_cost_and_resources(a, _sched(), costs, work_hours_per_day=8.0)
    assert _ids(a) == ids


def test_estimate5d_ids_repeat_across_files_and_re_embeds():
    a, b = _pin(_pile_ifc()), _pin(_pile_ifc())
    estimate5d.embed_estimate(a, PILE_MAP, PILE_COSTS)
    estimate5d.embed_estimate(b, PILE_MAP, PILE_COSTS)
    ids = _ids(a)
    assert len([c for c, _ in ids if c == "IfcCostItem"]) == 2  # item + leaf
    assert ids == _ids(b)
    estimate5d.embed_estimate(a, PILE_MAP, PILE_COSTS)
    assert _ids(a) == ids


def _modelled():
    f, _site, ftg, wall = _model_ifc()
    _pin(f)
    embed_estimate_model(f, _model_json(ftg.GlobalId, wall.GlobalId))
    return f, ftg, wall


def test_estimate_model_ids_repeat_across_files_and_re_embeds():
    (a, ftg, wall), (b, _, _) = _modelled(), _modelled()
    ids = _ids(a)
    assert {"IfcWorkSchedule", "IfcTask", "IfcCostSchedule", "IfcCostItem",
            "IfcLaborResource"} <= {c for c, _ in ids}
    assert ids == _ids(b)
    embed_estimate_model(a, _model_json(ftg.GlobalId, wall.GlobalId))
    assert _ids(a) == ids


def test_cost_item_keys_number_repeated_siblings():
    f = _file()
    cs = cost5d.add_declared_cost_schedule(f, name="E", predefined_type="ESTIMATE")
    import ifcopenshell.api.cost as cost
    p = cost.add_cost_item(f, cost_schedule=cs)
    p.Identification = "1"
    kids = [cost.add_cost_item(f, cost_item=p) for _ in range(2)]
    for k in kids:
        k.Name = "leaf"
    assert stable_ids.key_cost_items(f, cs) == 3
    assert p.GlobalId == stable_ids.stable_id(f, "cost-item/E/1")
    assert [k.GlobalId for k in kids] == [
        stable_ids.stable_id(f, "cost-item/E/1/leaf#1"),
        stable_ids.stable_id(f, "cost-item/E/1/leaf#2")]


def _dxf_ids(tmp_path, tag, guid_ns="3f2b8c1e-7d4a-4e6b-9a15-0c8d2e7f4b91",
             move=False):
    pytest.importorskip("ezdxf")
    pytest.importorskip("shapely")
    yaml = pytest.importorskip("yaml")
    from importlib.resources import files

    import ezdxf

    from bimforge.bim.dxf2bim import UNIT_TO_M, build_ifc, extract_features
    from bimforge.bim.sample import write_sample_dxf

    dxf = write_sample_dxf(str(tmp_path / f"{tag}.dxf"))
    if move:                      # edit the drawing in place: same handles
        doc = ezdxf.readfile(dxf)
        e = next(iter(doc.modelspace().query("LWPOLYLINE")))
        e.set_points([(x + 1000.0, y) for x, y, *_ in e.get_points()])
        doc.saveas(dxf)
    lm = yaml.safe_load((files("bimforge.bim") / "examples"
                         / "layer_map.example.yaml").read_text())
    if guid_ns:
        lm["project"]["guid_ns"] = guid_ns
    else:
        lm["project"].pop("guid_ns", None)
    feats = extract_features(dxf, lm["layers"],
                             UNIT_TO_M[lm["units"]["dxf_length_unit"]])
    out = str(tmp_path / f"{tag}.ifc")
    build_ifc(feats, lm, out)
    f = ifcopenshell.open(out)
    return {(e.is_a(), e.Name): e.GlobalId
            for cls in ("IfcProject", "IfcSpatialElement", "IfcElement")
            for e in f.by_type(cls)}


def test_dxf2bim_ids_repeat_for_one_drawing_and_layer_map(tmp_path):
    a = _dxf_ids(tmp_path, "a")
    assert ("IfcProject", "Sample Takeoff") in a and len(a) > 4
    assert a == _dxf_ids(tmp_path, "b")


def test_dxf2bim_ids_hold_when_an_entity_moves(tmp_path):
    assert _dxf_ids(tmp_path, "a") == _dxf_ids(tmp_path, "m", move=True)


def test_dxf2bim_without_guid_ns_warns_and_ids_are_random(tmp_path, capsys):
    a = _dxf_ids(tmp_path, "a", guid_ns=None)
    assert "guid_ns is not set" in capsys.readouterr().err
    b = _dxf_ids(tmp_path, "b", guid_ns=None)
    assert not set(a.values()) & set(b.values())

# --- relationships and property sets (#80) ---

def _roots(f):
    """{GlobalId: class} for every IfcRoot in `f`."""
    return {e.GlobalId: e.is_a() for e in f.by_type("IfcRoot")}


def _wall_file(gid=PROJECT):
    f = _file(gid)
    for i in range(3):
        w = root.create_entity(f, ifc_class="IfcWall", name=f"wall {i}")
        w.GlobalId = ifcopenshell.guid.compress(uuid.UUID(int=100 + i).hex)
    return f


def _linked(lag=1.0, pred="a"):
    sched = _sched()
    sched.tasks[1].match_ifc_class = "IfcWall"
    sched.tasks[2].match_name_re = "wall [01]"
    sched.tasks[2].dependencies = [Dependency(predecessor=pred, lag_days=lag)]
    return sched


def _linked_file(**kw):
    f = _wall_file()
    embed_schedule(f, _linked(**kw))
    return f


def _one(f, cls, test=lambda e: True):
    (e,) = [e for e in f.by_type(cls) if test(e)]
    return e


def test_every_schedule_root_repeats_rels_and_psets_included():
    a, b = _linked_file(), _linked_file()
    kinds = set(_roots(a).values())
    assert {"IfcRelAssignsToProduct", "IfcRelSequence", "IfcPropertySet",
            "IfcRelDefinesByProperties", "IfcRelNests",
            "IfcRelAssignsToControl"} <= kinds
    assert _roots(a) == _roots(b)
    embed_schedule(a, _linked())            # replaced by name
    assert _roots(a) == _roots(b)


def test_the_sweep_is_idempotent():
    f = _linked_file()
    before = _roots(f)
    stable_ids.key_relationships(f)
    assert _roots(f) == before


def test_a_later_assignment_keeps_the_relationship_id():
    import ifcopenshell.api.sequence as sq
    f = _linked_file()
    wall = _one(f, "IfcWall", lambda e: e.Name == "wall 0")
    (rel,) = wall.ReferencedBy
    gid = rel.GlobalId
    extra = root.create_entity(f, ifc_class="IfcTask", name="Extra")
    stable_ids.assign(f, extra, "task/BL/extra")
    sq.assign_product(f, relating_product=wall, related_object=extra)
    stable_ids.key_relationships(f)
    assert wall.ReferencedBy == (rel,) and len(rel.RelatedObjects) == 3
    assert rel.GlobalId == gid


def test_a_sequence_keeps_its_id_through_a_lag_change_not_a_new_predecessor():
    seq = lambda f: _one(f, "IfcRelSequence").GlobalId  # noqa: E731
    base = seq(_linked_file())
    assert seq(_linked_file(lag=3.0)) == base
    assert seq(_linked_file(pred="s")) != base


def test_a_pset_keys_on_its_owner_and_name():
    f = _linked_file()
    deck = _one(f, "IfcTask", lambda e: e.Name == "Deck")
    (pset,) = [r.RelatingPropertyDefinition for r in deck.IsDefinedBy]
    assert pset.GlobalId == stable_ids.stable_id(
        f, f"pset/{deck.GlobalId}/{pset.Name}")


def test_two_relationships_of_one_type_on_one_entity_are_numbered():
    def build():
        f = _file()
        cs = root.create_entity(f, ifc_class="IfcWorkSchedule", name="W")
        stable_ids.assign(f, cs, "work-schedule/W")
        tasks = []
        for i in range(2):
            t = root.create_entity(f, ifc_class="IfcTask", name=f"t{i}")
            stable_ids.assign(f, t, f"task/W/{i}")
            tasks.append(t)
        for t in tasks:
            # one rel per task, as a writer that never merges would
            f.createIfcRelAssignsToControl(
                ifcopenshell.guid.new(), None, None, None, [t], None, cs)
        stable_ids.key_relationships(f)
        return f
    a, b = build(), build()
    ids = sorted(r.GlobalId for r in a.by_type("IfcRelAssignsToControl"))
    assert len(set(ids)) == 2
    assert ids == sorted(r.GlobalId for r in b.by_type("IfcRelAssignsToControl"))


def test_another_project_gets_other_relationship_ids():
    a, b = _linked_file(), _wall_file(OTHER)
    embed_schedule(b, _linked())
    rels = lambda f: {g for g, c in _roots(f).items()  # noqa: E731
                      if c.startswith("IfcRel")}
    assert not rels(a) & rels(b)


def test_cost5d_roots_all_repeat():
    def build():
        f = _wall_file()
        embed_schedule(f, _linked())
        cost5d.embed_cost_and_resources(
            f, _linked(), {"A": {"cost": 1000.0, "labor_hours": 40.0},
                           "B": {"cost": 500.0, "labor_hours": 10.0}},
            work_hours_per_day=8.0)
        return f
    assert _roots(build()) == _roots(build())


def _pin_all(f):
    """Pin every authored IfcRoot, as an authored model's ids are: the
    fixtures here make random ones."""
    for i, e in enumerate(f.by_type("IfcRoot")):
        e.GlobalId = ifcopenshell.guid.compress(uuid.UUID(int=1000 + i).hex)
    return _pin(f)


def test_estimate5d_roots_all_repeat():
    a, b = _pin_all(_pile_ifc()), _pin_all(_pile_ifc())
    for f in (a, b):
        estimate5d.embed_estimate(f, PILE_MAP, PILE_COSTS)
    assert _roots(a) == _roots(b)


def test_estimate_model_roots_all_repeat():
    def build():
        f, _site, ftg, wall = _model_ifc()
        _pin_all(f)
        embed_estimate_model(f, _model_json(ftg.GlobalId, wall.GlobalId))
        return f
    a, b = build(), build()
    assert {"IfcRelAssignsToProduct", "IfcRelAssignsToResource",
            "IfcPropertySet"} & set(_roots(a).values())
    assert _roots(a) == _roots(b)

def test_a_downstream_tools_own_relationships_keep_their_ids():
    """Entities another application stamped are its own: the sweep leaves
    their ids, so a returned file's additions carry through a rebuild."""
    import ifcopenshell.api.sequence as sq
    f = _linked_file()
    person = f.createIfcPerson(FamilyName="planner")
    org = f.createIfcOrganization(Name="downstream")
    app = f.createIfcApplication(org, "1.0", "ProjectCommand", "ProjectCommand")
    oh = f.createIfcOwnerHistory(
        f.createIfcPersonAndOrganization(person, org), app, None, "ADDED",
        None, None, None, 0)
    copy = root.create_entity(f, ifc_class="IfcTask", name="Deck (copy)")
    deck = _one(f, "IfcTask", lambda e: e.Name == "Deck")
    link = f.createIfcRelDefinesByObject(
        "1PCdownstreamLinkId000", oh, None, None, [copy], deck)
    wall = _one(f, "IfcWall", lambda e: e.Name == "wall 2")
    rel = sq.assign_product(f, relating_product=wall, related_object=copy)
    rel.OwnerHistory, rel.GlobalId = oh, "1PCdownstreamAssignId0"
    stable_ids.key_relationships(f)
    assert (link.GlobalId, rel.GlobalId) == (
        "1PCdownstreamLinkId000", "1PCdownstreamAssignId0")
