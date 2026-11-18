"""Every IFC bimforge writes passes the schema, its WHERE rules and its
global rules (#94, C.7).

The examples are built as a user builds them, on IFC4X3 and on IFC4; the 4D
and 5D writers then embed into a built example, federate merges two, and a
schedule rebuild carries a downstream tool's update forward. A finding here
is a file a third-party tool may refuse, so the gate is strict: no statement.

With BIMFORGE_CONFORMANCE_OUT set, each file checked is also written there
as <name>.ifc (<name>-ifc4.ifc on IFC4), for buildingSMART's normative rules
(scripts/bsi_rules.py).
"""
from __future__ import annotations

import dataclasses
import os
from importlib.resources import files
from pathlib import Path

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
yaml = pytest.importorskip("yaml")

import ifcopenshell.guid  # noqa: E402

from bimforge.author.gate import schema_issues  # noqa: E402

EXAMPLES = sorted(e.name[:-len(".spec.yaml")]
                  for e in (files("bimforge.author") / "examples").iterdir()
                  if e.name.endswith(".spec.yaml"))
X3, IFC4 = "IFC4X3_ADD2", "IFC4"
#: every writer is checked on both schemas it writes: IFC4X3 by default,
#: IFC4 a project's opt-out for viewers that cannot read 4X3
SCHEMAS = (X3, IFC4)


def _label(name: str, schema: str) -> str:
    """The name the file is written under for the normative rules."""
    return name if schema == X3 else f"{name}-ifc4"


def _schema_of(schema: str) -> str:
    """What ifcopenshell reports as file.schema for `schema`."""
    return "IFC4X3" if schema == X3 else schema


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> dict:
    """{(example, schema): path of its IFC}, built from a copy of the
    examples, the IFC4 copy with `project: schema: IFC4`."""
    from bimforge.author.families.registry import build_from_spec
    out = {}
    for schema in SCHEMAS:
        tmp = tmp_path_factory.mktemp(f"conformance-{schema}")
        for entry in (files("bimforge.author") / "examples").iterdir():
            if entry.name.endswith(".yaml"):
                (tmp / entry.name).write_text(entry.read_text("utf-8"), "utf-8")
        for name in EXAMPLES:
            spec = tmp / f"{name}.spec.yaml"
            doc = yaml.safe_load(spec.read_text("utf-8"))
            if schema != X3:
                doc.setdefault("project", {})["schema"] = schema
                spec.write_text(yaml.safe_dump(doc, sort_keys=False), "utf-8")
            assert build_from_spec(str(spec)) == 0, (name, schema)
            out[name, schema] = tmp / doc["outputs"]["ifc"]
    return out


def _clean(f, name):
    """No schema finding. `name` writes f for the normative rules; None for
    a hand-built fixture, whose own shortcuts they would report."""
    issues = schema_issues(f)
    assert not issues, "\n".join(issues[:20])
    if name and (out := os.environ.get("BIMFORGE_CONFORMANCE_OUT")):
        Path(out).mkdir(parents=True, exist_ok=True)
        f.write(str(Path(out) / f"{name}.ifc"))


@pytest.mark.parametrize("schema", SCHEMAS)
@pytest.mark.parametrize("name", EXAMPLES)
def test_every_example_builds_conformant(built, name, schema):
    f = ifcopenshell.open(str(built[name, schema]))
    assert f.schema == _schema_of(schema)
    _clean(f, _label(name, schema))


def _schedule():
    from bimforge.bim.schedule_model import CanonicalSchedule, ScheduleTask
    return CanonicalSchedule(
        name="BL", start_date="2026-07-10", work_weekdays=[0, 1, 2, 3, 4],
        tasks=[ScheduleTask(id="s", name="Structure", wbs="1"),
               ScheduleTask(id="a", name="Build", wbs="1.1",
                            start="2026-07-10", finish="2026-07-24",
                            match_ifc_class="IfcElement",
                            bid_item_codes=["A"])])


@pytest.mark.parametrize("schema", SCHEMAS)
def test_4d_and_cost5d_on_a_built_bridge_are_conformant(built, schema):
    from bimforge.bim import cost5d
    from bimforge.bim.schedule4d import embed_schedule
    f = ifcopenshell.open(str(built["bridge-standard", schema]))
    report = embed_schedule(f, _schedule())
    assert report.assigned_elements
    cost5d.embed_cost_and_resources(
        f, _schedule(), {"A": {"cost": 1000.0, "labor_hours": 40.0}})
    _clean(f, _label("bridge-standard-4d-cost5d", schema))


@pytest.mark.parametrize("schema", SCHEMAS)
def test_estimate_model_on_a_built_bridge_is_conformant(built, schema):
    from bimforge.bim.estimate_model5d import embed_estimate_model
    from bimforge.bim.tests.test_estimate_model5d import _model_json
    f = ifcopenshell.open(str(built["bridge-standard", schema]))
    a, b = f.by_type("IfcElement")[:2]
    embed_estimate_model(f, _model_json(a.GlobalId, b.GlobalId))
    _clean(f, _label("bridge-standard-estimate-model", schema))


@pytest.mark.parametrize("schema", SCHEMAS)
def test_estimate5d_is_conformant(schema):
    from bimforge.bim import estimate5d
    from bimforge.bim.tests.test_estimate5d import (
        PILE_COSTS, PILE_MAP, _pile_ifc,
    )
    f = _pile_ifc(schema=schema)
    estimate5d.embed_estimate(f, PILE_MAP, PILE_COSTS)
    _clean(f, None)     # a bare pile: no context, no container


@pytest.mark.parametrize("schema", SCHEMAS)
def test_dxf2bim_sample_is_conformant(tmp_path, schema):
    pytest.importorskip("ezdxf")
    pytest.importorskip("shapely")
    from bimforge.bim import cli
    assert cli.main(["sample", "--dir", str(tmp_path), "--with-configs"]) == 0
    config = tmp_path / "layer_map.example.yaml"
    if schema != X3:
        doc = yaml.safe_load(config.read_text("utf-8"))
        doc.setdefault("project", {})["schema"] = schema
        config.write_text(yaml.safe_dump(doc, sort_keys=False), "utf-8")
    out = tmp_path / "model.ifc"
    assert cli.main(["dxf2bim", "--dxf", str(tmp_path / "sample_plan.dxf"),
                     "--config", str(config), "--out", str(out)]) == 0
    f = ifcopenshell.open(str(out))
    assert f.schema == _schema_of(schema)
    _clean(f, _label("dxf2bim-sample", schema))


@pytest.mark.parametrize("schema", SCHEMAS)
def test_federating_two_examples_is_conformant(built, tmp_path, schema):
    from bimforge.author.federate import federate
    from bimforge.author.tests.test_federate import _ctx
    out = tmp_path / "federated.ifc"
    federate([(str(built["caltrans-pipe-headwall", schema]), "Headwall"),
              (str(built["caltrans-d90-headwall", schema]), "Guardrail")],
             str(out), dataclasses.replace(_ctx(), schema=schema),
             georef_check=False)
    f = ifcopenshell.open(str(out))
    assert f.schema == _schema_of(schema)
    _clean(f, _label("federated-headwalls", schema))


def _downstream_update(f) -> None:
    """What a downstream tool returns on top of our schedule (#83): its own
    update, a copy of our Build task tied to ours and carrying progress, and
    an approval on one of our elements, all stamped with its application."""
    import ifcopenshell.api.sequence as sq
    from bimforge.bim.tests.test_carry_forward import _stamp
    oh = _stamp(f, "MODIFIED")
    ours = next(t for t in f.by_type("IfcTask") if t.Name == "Build")
    ws = sq.add_work_schedule(f, name="Update")
    ws.Purpose, ws.CreationDate = "Contractor update", "2026-07-15T00:00:00"
    copy = sq.add_task(f, work_schedule=ws, name="Build")
    tt = sq.add_task_time(f, copy)
    tt.ScheduleStart, tt.ScheduleFinish = (ours.TaskTime.ScheduleStart,
                                           "2026-07-28T17:00:00")
    tt.ActualStart, tt.Completion = ours.TaskTime.ScheduleStart, 0.4
    tie = f.createIfcRelDefinesByObject(ifcopenshell.guid.new(), oh, None,
                                        None, [copy], ours)
    approval = f.createIfcApproval("03-01", "Shop drawing", None,
                                   "2026-07-14T00:00:00", "approved as noted",
                                   None, None, None, None)
    f.createIfcRelAssociatesApproval(ifcopenshell.guid.new(), oh, None, None,
                                     [f.by_type("IfcElement")[0]], approval)
    # the api leaves what it made unstamped: stamp it as the tool would
    made = [ws, copy, tie] + [rel for rel in f.get_inverse(copy)
                              if rel.is_a("IfcRelationship")]
    for ent in made:
        ent.OwnerHistory = oh


@pytest.mark.parametrize("schema", SCHEMAS)
def test_a_carried_forward_rebuild_is_conformant(built, schema):
    """`est-bim schedule --returned`: the rebuild with a downstream tool's
    update and approval carried onto it."""
    from bimforge.bim.carry_forward import carry_forward
    from bimforge.bim.schedule4d import embed_schedule
    path = str(built["bridge-standard", schema])
    returned = ifcopenshell.open(path)
    embed_schedule(returned, _schedule())
    _downstream_update(returned)
    rebuilt = ifcopenshell.open(path)
    embed_schedule(rebuilt, _schedule())
    report = carry_forward(returned, rebuilt)
    assert report.carried and not (report.dropped or report.vanished
                                   or report.modified)
    assert any(w.Purpose == "Contractor update"
               for w in rebuilt.by_type("IfcWorkSchedule"))
    _clean(rebuilt, _label("bridge-standard-carried", schema))
