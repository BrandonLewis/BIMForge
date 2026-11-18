import importlib.util
from pathlib import Path

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
import ifcopenshell.api.pset  # noqa: E402
import ifcopenshell.api.root  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "ifc_inventory", Path(__file__).resolve().parents[1] / "scripts" / "ifc_inventory.py")
ifc_inventory = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ifc_inventory)


def _file(path, schema, task=False):
    f = ifcopenshell.file(schema=schema)
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="p")
    wall = ifcopenshell.api.root.create_entity(f, ifc_class="IfcWall", name="w")
    ps = ifcopenshell.api.pset.add_pset(f, product=wall, name="Pset_WallCommon")
    ifcopenshell.api.pset.edit_pset(f, pset=ps, properties={"IsExternal": True})
    if task:
        ifcopenshell.api.root.create_entity(f, ifc_class="IfcTask", name="t")
    f.write(str(path))


def test_a_derived_file_is_credited_only_with_what_it_adds(tmp_path):
    _file(tmp_path / "bridge-standard.ifc", "IFC4X3_ADD2")
    _file(tmp_path / "bridge-standard-4d-cost5d.ifc", "IFC4X3_ADD2", task=True)
    _file(tmp_path / "bridge-standard-ifc4.ifc", "IFC4")
    inv = ifc_inventory.inventory(tmp_path)
    assert inv["entity|IfcTask"] == {"IFC4X3": ["schedule + cost5d"]}
    assert inv["entity|IfcWall"] == {"IFC4": ["build"], "IFC4X3": ["build"]}
    assert inv["pset|Pset_WallCommon|IsExternal"] == {
        "IFC4": ["build"], "IFC4X3": ["build"]}
    assert inv["applies|pset|Pset_WallCommon|IfcWall"]["IFC4X3"] == ["build"]


def test_the_rendered_page_lists_sets_with_their_members(tmp_path):
    _file(tmp_path / "demo-box.ifc", "IFC4X3_ADD2")
    md = ifc_inventory.render(ifc_inventory.inventory(tmp_path))
    assert "| IfcWall | build | IFC4X3 |" in md
    assert "| Pset_WallCommon | IsExternal | IfcWall | build | IFC4X3 |" in md
