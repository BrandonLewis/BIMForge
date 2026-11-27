"""Every IFC bimforge writes passes `est-bim validate`'s failing sections:
the schema, its WHERE rules and its global rules (#94, C.7), buildingSMART's
alignment checks (C.12), the gate's structure checks and the takeoff
contract (C.11).

The examples, and the conformance specs (conformance_specs/: the families no
example builds, and options the examples leave off), are built as a user
builds them, on IFC4X3 and on IFC4; every registered family is among
them. The 4D and 5D writers then embed into a built example, federate
merges two, and a schedule rebuild carries a downstream tool's update
forward. A finding here
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
# validate's takeoff section: without it no file here could be clean
pytest.importorskip("ifctester.ids")

import ifcopenshell.guid  # noqa: E402

from bimforge.author.gate import alignment_issues  # noqa: E402

EXAMPLES = sorted(e.name[:-len(".spec.yaml")]
                  for e in (files("bimforge.author") / "examples").iterdir()
                  if e.name.endswith(".spec.yaml"))
#: specs for the families no example builds, and options the examples
#: leave off; `conformance: schemas:` names the schemas one is built on
CONFORMANCE_SPECS = Path(__file__).with_name("conformance_specs")
VARIANTS = sorted(p.name[:-len(".spec.yaml")]
                  for p in CONFORMANCE_SPECS.glob("*.spec.yaml"))
X3, IFC4 = "IFC4X3_ADD2", "IFC4"
#: every writer is checked on both schemas it writes: IFC4X3 by default,
#: IFC4 a project's opt-out for viewers that cannot read 4X3
SCHEMAS = (X3, IFC4)


def test_no_conformance_spec_shadows_an_example():
    """The suite copies the examples and the conformance specs into one
    directory: a shared name would build one in place of the other."""
    assert not set(EXAMPLES) & set(VARIANTS)
    example_files = {e.name for e in (files("bimforge.author") / "examples")
                     .iterdir()}
    assert not example_files & {p.name for p in CONFORMANCE_SPECS.iterdir()}


def _family_of(spec_path) -> str:
    return yaml.safe_load(Path(spec_path).read_text("utf-8"))["family"]


def test_every_shipped_family_is_built_by_the_suite():
    """Every family the package ships (not a third party's, installed by
    entry point) is built by an example or a conformance spec."""
    from bimforge.author.families.registry import _shipped
    examples = files("bimforge.author") / "examples"
    built_families = {_family_of(examples / f"{n}.spec.yaml") for n in EXAMPLES}
    built_families |= {_family_of(CONFORMANCE_SPECS / f"{n}.spec.yaml")
                       for n in VARIANTS}
    missing = sorted(set(_shipped()) - built_families)
    assert not missing, (f"families no example or conformance spec builds: "
                         f"{missing}; add one under {CONFORMANCE_SPECS.name}/")


def _label(name: str, schema: str) -> str:
    """The name the file is written under for the normative rules."""
    return name if schema == X3 else f"{name}-ifc4"


def _schema_of(schema: str) -> str:
    """What ifcopenshell reports as file.schema for `schema`."""
    return "IFC4X3" if schema == X3 else schema


def _schemas_of(doc: dict, name: str) -> tuple:
    """The schemas spec `name` is built on: its `conformance: schemas:`
    (read by this suite only; load_spec ignores the key), else every one.
    A list that names nothing, or a schema the suite does not build, is the
    spec's error: it would build on nothing while counting as built."""
    schemas = (doc.get("conformance") or {}).get("schemas", SCHEMAS)
    if not schemas:
        raise ValueError(f"{name}: conformance.schemas names no schema")
    bad = [s for s in schemas if s not in SCHEMAS]
    if bad:
        raise ValueError(f"{name}: conformance.schemas {bad} not among "
                         f"{list(SCHEMAS)}")
    return tuple(schemas)


def test_a_spec_names_the_schemas_it_is_built_on(tmp_path):
    """A variant IFC4 cannot write names IFC4X3 alone; one that names none
    is built on both; and the key does not stop the spec building."""
    from bimforge.author.families.registry import build_from_spec
    examples = files("bimforge.author") / "examples"
    for entry in examples.iterdir():
        if entry.name.startswith("demo-box."):
            (tmp_path / entry.name).write_text(entry.read_text("utf-8"),
                                               "utf-8")
    spec = tmp_path / "demo-box.spec.yaml"
    doc = yaml.safe_load(spec.read_text("utf-8"))
    assert _schemas_of(doc, "demo-box") == SCHEMAS
    doc["conformance"] = {"schemas": [X3]}
    assert _schemas_of(doc, "demo-box") == (X3,)
    spec.write_text(yaml.safe_dump(doc, sort_keys=False), "utf-8")
    assert build_from_spec(str(spec), check_only=True) == 0


@pytest.mark.parametrize("schemas, match", [
    ([], "names no schema"),
    (["IFC4X3"], r"\['IFC4X3'\] not among"),
])
def test_a_spec_naming_no_schema_the_suite_builds_is_refused(schemas, match):
    with pytest.raises(ValueError,
                       match=f"demo-box: conformance.schemas {match}"):
        _schemas_of({"conformance": {"schemas": schemas}}, "demo-box")


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> dict:
    """{(name, schema): path of its IFC}: every example, and every
    conformance spec on the schemas it names, built as a user builds them,
    the IFC4 copy with `project: schema: IFC4`. A spec this interpreter
    cannot build (a terrain: block without bimforge[terrain]) maps to the
    reason, a str: its cases skip, the others still run."""
    from bimforge.author.families.registry import build_from_spec
    from bimforge.terrain.testing import missing_terrain_deps, offline
    no_terrain = missing_terrain_deps()
    out = {}
    for schema in SCHEMAS:
        tmp = tmp_path_factory.mktemp(f"conformance-{schema}")
        for entry in (files("bimforge.author") / "examples").iterdir():
            if entry.name.endswith(".yaml"):
                (tmp / entry.name).write_text(entry.read_text("utf-8"), "utf-8")
        for entry in CONFORMANCE_SPECS.iterdir():
            if entry.is_file():
                (tmp / entry.name).write_bytes(entry.read_bytes())
        for name in EXAMPLES + VARIANTS:
            spec = tmp / f"{name}.spec.yaml"
            doc = yaml.safe_load(spec.read_text("utf-8"))
            if schema not in _schemas_of(doc, name):
                continue
            if doc.get("terrain") and no_terrain:
                out[name, schema] = (f"{name}: its terrain: block needs "
                                     f"{', '.join(no_terrain)} "
                                     f"(pip install bimforge[terrain])")
                continue
            if schema != X3:
                doc.setdefault("project", {})["schema"] = schema
                spec.write_text(yaml.safe_dump(doc, sort_keys=False), "utf-8")
            with pytest.MonkeyPatch.context() as mp:
                if doc.get("terrain"):
                    offline(mp)     # 3DEP answered locally: a flat DEM
                assert build_from_spec(str(spec)) == 0, (name, schema)
            out[name, schema] = tmp / doc["outputs"]["ifc"]
    return out


def _clean(f, name):
    """validate's verdict on f is clean: no finding in a failing section,
    every check in them run and every rule evaluated. `name` writes f for
    the normative rules; None for a hand-built fixture, whose own shortcuts
    they would report."""
    import tempfile

    from bimforge.bim.validate import FAILING, validate
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "f.ifc"
        f.write(str(path))
        r = validate(path)
    secs = r["sections"]
    # the gate's lines carry their own check name
    found = [f"{s}: {x['message']}"
             + (f" [{x['instance']}]" if "instance" in x else "")
             for s in FAILING if secs[s]["status"] == "fail"
             for x in secs[s]["findings"]]
    found += [f"{s}: not run ({secs[s]['reason']})" for s in FAILING
              if secs[s]["status"] == "not run"]
    if secs["rules"].get("unevaluated"):
        found.append(f"rules: {secs['rules']['unevaluated']} unevaluated")
    assert r["verdict"] == "clean", (f"verdict {r['verdict']}:\n"
                                     + "\n".join(found[:20]))
    if name and (out := os.environ.get("BIMFORGE_CONFORMANCE_OUT")):
        Path(out).mkdir(parents=True, exist_ok=True)
        f.write(str(Path(out) / f"{name}.ifc"))


@pytest.mark.parametrize("schema", SCHEMAS)
@pytest.mark.parametrize("name", EXAMPLES + VARIANTS)
def test_every_spec_builds_conformant(built, name, schema):
    """Each example and conformance spec, built on each schema it names,
    is a file validate calls clean."""
    if (name, schema) not in built:
        pytest.skip(f"{name} names the schemas it is built on")
    if isinstance(built[name, schema], str):
        pytest.skip(built[name, schema])
    f = ifcopenshell.open(str(built[name, schema]))
    assert f.schema == _schema_of(schema)
    _clean(f, _label(name, schema))


@pytest.mark.parametrize("schema", SCHEMAS)
@pytest.mark.parametrize("name", ["headwall-926-rack-guardrail",
                                  "pipe-supports"])
def test_the_variants_options_are_inside_the_takeoff_contract(built, name,
                                                              schema):
    """The options these specs add (the 926 rack and guardrail, the pipe
    supports' steel) are classified, so the failing takeoff section holds
    their quantities: the advisory coverage section names nothing but the
    pipe supports' casing, reference geometry the family leaves unpaid on
    purpose (named so no pay rule matches it)."""
    from bimforge.bim.validate import validate
    r = validate(built[name, schema])
    unpaid = [x.get("instance", x["check"])
              for x in r["sections"]["coverage"]["findings"]
              if "(REFERENCE)" not in x.get("instance", "")]
    assert unpaid == []


def test_the_alignment_checks_have_an_alignment_to_check(built):
    """The bridge carries the examples' alignment, so the alignment checks
    in `_clean` are not passing on files that have none."""
    f = ifcopenshell.open(str(built["bridge-standard", X3]))
    assert f.by_type("IfcAlignment")
    assert not alignment_issues(f)


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
    # a pile with no body: held to every failing section, not written for
    # the normative rules (a file with no geometry is not one they judge)
    _clean(f, None)


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
