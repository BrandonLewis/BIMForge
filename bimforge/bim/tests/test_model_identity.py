"""BIMForge_Model: the model's own identity on its IfcProject (M.6)."""
from __future__ import annotations

import re
from importlib.resources import files

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
yaml = pytest.importorskip("yaml")

from bimforge.bim import model_identity  # noqa: E402

EXAMPLE = "demo-box"


def _copy_examples(tmp):
    for entry in (files("bimforge.author") / "examples").iterdir():
        if entry.name.endswith(".yaml"):
            (tmp / entry.name).write_text(entry.read_text("utf-8"), "utf-8")
    return tmp / f"{EXAMPLE}.spec.yaml"


def _build(spec):
    from bimforge.author.families.registry import build_from_spec
    assert build_from_spec(str(spec)) == 0
    doc = yaml.safe_load(spec.read_text("utf-8"))
    return ifcopenshell.open(str(spec.parent / doc["outputs"]["ifc"]))


def _edit(spec, fn):
    doc = yaml.safe_load(spec.read_text("utf-8"))
    fn(doc)
    spec.write_text(yaml.safe_dump(doc, sort_keys=False), "utf-8")


@pytest.fixture
def spec(tmp_path):
    return _copy_examples(tmp_path)


def test_a_built_model_names_itself(spec):
    f = _build(spec)
    got = model_identity.read(f)
    assert re.fullmatch(r"[0-9a-f]{64}", got["BuildId"])
    assert got["BimforgeVersion"] == model_identity.version()
    assert got["Schema"] == "IFC4X3_ADD2"
    assert got["Source"] == f"{EXAMPLE}.spec.yaml"


def test_the_set_is_keyed_under_the_project(spec):
    from bimforge.bim import stable_ids
    f = _build(spec)
    project = f.by_type("IfcProject")[0]
    (pset,) = [p for p in f.by_type("IfcPropertySet")
               if p.Name == model_identity.PSET]
    assert pset.GlobalId == stable_ids.stable_id(
        f, f"pset/{project.GlobalId}/{model_identity.PSET}")
    (rel,) = pset.DefinesOccurrence
    assert rel.RelatedObjects == (project,)
    assert rel.GlobalId == stable_ids.stable_id(
        f, f"rel/IfcRelDefinesByProperties/{pset.GlobalId}")


def test_the_same_source_gets_the_same_id(spec, tmp_path):
    first = model_identity.read(_build(spec))["BuildId"]
    # written elsewhere, the spec's comments and layout changed: one source
    other = tmp_path / "elsewhere"
    other.mkdir()
    again = _copy_examples(other)
    _edit(again, lambda d: d["outputs"].update(ifc="renamed.ifc"))
    again.write_text("# a comment\n" + again.read_text("utf-8"), "utf-8")
    assert model_identity.read(_build(again))["BuildId"] == first


def test_a_changed_source_or_schema_changes_the_id(spec):
    first = model_identity.read(_build(spec))["BuildId"]
    _edit(spec, lambda d: d.setdefault("project", {}).update(schema="IFC4"))
    ifc4 = model_identity.read(_build(spec))
    assert ifc4["Schema"] == "IFC4" and ifc4["BuildId"] != first
    paycodes = spec.parent / yaml.safe_load(spec.read_text("utf-8"))["paycodes"]
    doc = yaml.safe_load(paycodes.read_text("utf-8"))
    doc["project_ref"] = f"{doc.get('project_ref')}-changed"
    paycodes.write_text(yaml.safe_dump(doc), "utf-8")
    assert model_identity.read(_build(spec))["BuildId"] not in (first, ifc4["BuildId"])


def test_an_embed_leaves_the_identity_alone(spec):
    from bimforge.bim.schedule4d import embed_schedule
    from bimforge.bim.tests.test_conformance import _schedule
    f = _build(spec)
    before = model_identity.read(f)
    embed_schedule(f, _schedule())
    assert model_identity.read(f) == before


def test_a_model_emitted_without_a_source_is_named_by_its_file(tmp_path):
    from bimforge.author.emit_ifc import emit_ifc
    from bimforge.author.tests.test_emit import _terrain_model
    a, b = tmp_path / "a.ifc", tmp_path / "b.ifc"
    emit_ifc(_terrain_model(), str(a))
    emit_ifc(_terrain_model(), str(b))
    ida = model_identity.read(ifcopenshell.open(str(a)))
    assert "Source" not in ida
    assert ida == model_identity.read(ifcopenshell.open(str(b)))


def test_write_replaces_the_set(spec):
    f = _build(spec)
    bid = model_identity.write(f, {"other": 1}, "other.yaml")
    assert model_identity.read(f) == {
        "BuildId": bid, "BimforgeVersion": model_identity.version(),
        "Schema": "IFC4X3_ADD2", "Source": "other.yaml"}
    assert len([p for p in f.by_type("IfcPropertySet")
                if p.Name == model_identity.PSET]) == 1


def test_dxf2bim_names_its_model_by_the_drawing(tmp_path):
    pytest.importorskip("ezdxf")
    pytest.importorskip("shapely")
    from bimforge.bim import cli
    assert cli.main(["sample", "--dir", str(tmp_path), "--with-configs"]) == 0
    ids = []
    for out in ("a.ifc", "b.ifc"):
        assert cli.main(["dxf2bim", "--dxf", str(tmp_path / "sample_plan.dxf"),
                         "--config", str(tmp_path / "layer_map.example.yaml"),
                         "--out", str(tmp_path / out)]) == 0
        ids.append(model_identity.read(ifcopenshell.open(str(tmp_path / out))))
    assert ids[0]["Source"] == "sample_plan.dxf"
    assert re.fullmatch(r"[0-9a-f]{64}", ids[0]["BuildId"])
    assert ids[0] == ids[1]


def test_a_federation_names_its_sources(spec, tmp_path):
    import dataclasses

    from bimforge.author.federate import federate
    from bimforge.author.tests.test_federate import _ctx
    built = _build(spec)
    src = spec.parent / yaml.safe_load(spec.read_text("utf-8"))["outputs"]["ifc"]
    first = model_identity.read(built)["BuildId"]
    out = tmp_path / "federated.ifc"
    federate([(str(src), "Box")], str(out),
             dataclasses.replace(_ctx(), schema="IFC4X3_ADD2"),
             georef_check=False)
    f = ifcopenshell.open(str(out))
    got = model_identity.read(f)
    assert got["Source"] == src.name
    assert got["BuildId"] == model_identity.build_id(
        {"federate": [["Box", first]], "merge_facilities": False},
        "IFC4X3_ADD2")
    assert len([p for p in f.by_type("IfcPropertySet")
                if p.Name == model_identity.PSET]) == 1
