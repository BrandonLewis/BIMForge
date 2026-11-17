"""Every IFC bimforge writes passes the schema, its WHERE rules and its
global rules (#94).

The examples are built as a user builds them; the 4D and 5D writers then
embed into a built example, and federate merges two. A finding here is a
file a third-party tool may refuse, so the gate is strict: no statement.
"""
from __future__ import annotations

from importlib.resources import files

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
yaml = pytest.importorskip("yaml")

from bimforge.author.gate import schema_issues  # noqa: E402

EXAMPLES = sorted(e.name[:-len(".spec.yaml")]
                  for e in (files("bimforge.author") / "examples").iterdir()
                  if e.name.endswith(".spec.yaml"))


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> dict:
    """{example: path of its IFC}, built from a copy of the examples."""
    from bimforge.author.families.registry import build_from_spec
    tmp = tmp_path_factory.mktemp("conformance")
    for entry in (files("bimforge.author") / "examples").iterdir():
        if entry.name.endswith(".yaml"):
            (tmp / entry.name).write_text(entry.read_text("utf-8"), "utf-8")
    out = {}
    for name in EXAMPLES:
        spec = tmp / f"{name}.spec.yaml"
        assert build_from_spec(str(spec)) == 0, name
        out[name] = tmp / yaml.safe_load(spec.read_text("utf-8"))["outputs"]["ifc"]
    return out


def _clean(f):
    issues = schema_issues(f)
    assert not issues, "\n".join(issues[:20])


@pytest.mark.parametrize("name", EXAMPLES)
def test_every_example_builds_conformant(built, name):
    _clean(ifcopenshell.open(str(built[name])))


def _schedule():
    from bimforge.bim.schedule_model import CanonicalSchedule, ScheduleTask
    return CanonicalSchedule(
        name="BL", start_date="2026-07-10", work_weekdays=[0, 1, 2, 3, 4],
        tasks=[ScheduleTask(id="s", name="Structure", wbs="1"),
               ScheduleTask(id="a", name="Build", wbs="1.1",
                            start="2026-07-10", finish="2026-07-24",
                            match_ifc_class="IfcElement",
                            bid_item_codes=["A"])])


def test_4d_and_cost5d_on_a_built_bridge_are_conformant(built):
    from bimforge.bim import cost5d
    from bimforge.bim.schedule4d import embed_schedule
    f = ifcopenshell.open(str(built["bridge-standard"]))
    report = embed_schedule(f, _schedule())
    assert report.assigned_elements
    cost5d.embed_cost_and_resources(
        f, _schedule(), {"A": {"cost": 1000.0, "labor_hours": 40.0}})
    _clean(f)


def test_estimate_model_on_a_built_bridge_is_conformant(built):
    from bimforge.bim.estimate_model5d import embed_estimate_model
    from bimforge.bim.tests.test_estimate_model5d import _model_json
    f = ifcopenshell.open(str(built["bridge-standard"]))
    a, b = f.by_type("IfcElement")[:2]
    embed_estimate_model(f, _model_json(a.GlobalId, b.GlobalId))
    _clean(f)


def test_estimate5d_is_conformant():
    from bimforge.bim import estimate5d
    from bimforge.bim.tests.test_estimate5d import (
        PILE_COSTS, PILE_MAP, _pile_ifc,
    )
    f = _pile_ifc()
    estimate5d.embed_estimate(f, PILE_MAP, PILE_COSTS)
    _clean(f)


def test_dxf2bim_sample_is_conformant(tmp_path):
    pytest.importorskip("ezdxf")
    pytest.importorskip("shapely")
    from bimforge.bim import cli
    assert cli.main(["sample", "--dir", str(tmp_path), "--with-configs"]) == 0
    out = tmp_path / "model.ifc"
    assert cli.main(["dxf2bim", "--dxf", str(tmp_path / "sample_plan.dxf"),
                     "--config", str(tmp_path / "layer_map.example.yaml"),
                     "--out", str(out)]) == 0
    _clean(ifcopenshell.open(str(out)))


def test_federating_two_examples_is_conformant(built, tmp_path):
    from bimforge.author.federate import federate
    from bimforge.author.tests.test_federate import _ctx
    out = tmp_path / "federated.ifc"
    federate([(str(built["caltrans-pipe-headwall"]), "Headwall"),
              (str(built["caltrans-d90-headwall"]), "Guardrail")],
             str(out), _ctx(), georef_check=False)
    _clean(ifcopenshell.open(str(out)))
