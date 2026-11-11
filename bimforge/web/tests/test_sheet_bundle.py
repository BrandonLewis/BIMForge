"""bimforge.web.sheet_bundle / glb / changes: the sheet bundle the IFC
Navigator add-in loads, its GLB geometry, and the change-set it hands back."""
from __future__ import annotations

import json
import struct

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
np = pytest.importorskip("numpy")

import ifcopenshell.util.element as ue  # noqa: E402

from bimforge.bim.ifc_mesh import mesh_volume  # noqa: E402
from bimforge.web import (apply_changes, build_sheet_bundle, validate_changes,  # noqa: E402
                          validate_manifest, write_sheet_bundle)
from bimforge.web.changes import coerce  # noqa: E402
from bimforge.web.glb import read_glb, to_y_up, write_glb  # noqa: E402
from bimforge.web.sheet_bundle import CONTRACT  # noqa: E402
from bimforge.web.tests.test_contract import _ifc  # noqa: E402

M_PER_FT = 1200.0 / 3937.0


@pytest.fixture(scope="module")
def ifc(tmp_path_factory):
    out = _ifc(tmp_path_factory.mktemp("sheet"), with_4d=False, with_5d=False)
    import ifcopenshell.api
    f = ifcopenshell.open(str(out))
    # a few single-value properties to round-trip
    wall = next(w for w in f.by_type("IfcWall") if w.Name == "Abut 1 wall")
    ps = ifcopenshell.api.run("pset.add_pset", f, product=wall, name="Pset_WallCommon")
    ifcopenshell.api.run("pset.edit_pset", f, pset=ps, properties={
        "FireRating": "2HR", "IsExternal": True, "ThermalTransmittance": 0.5})
    f.write(str(out))
    return out


def test_bundle_tables_and_manifest(ifc):
    b = build_sheet_bundle(ifc)
    m = b["manifest"]
    validate_manifest(m)
    assert m["contract"] == CONTRACT
    assert m["model"]["schema"] == "IFC4X3"
    assert m["units"]["length"] == "m"
    assert m["geometry"]["up"] == "Y" and len(m["geometry"]["offset_m"]) == 3
    # every chunk entry has its tables, and the counts add up
    assert sum(c["elements"] for c in m["chunks"]) == m["model"]["counts"]["elements"]
    assert set(b["chunks"]) == {c["id"] for c in m["chunks"]}
    all_rows = [r for c in b["chunks"].values() for r in c["elements"]]
    guids = [r["global_id"] for r in all_rows]
    assert len(guids) == len(set(guids)) == m["model"]["counts"]["elements"]
    wall = next(r for r in all_rows if r["name"] == "Abut 1 wall")
    assert wall["ifc_class"] == "IfcWall" and wall["type"] == "Stem wall"
    assert wall["type_global_id"] and wall["codes"] == ["W-CONC"]
    # the posts are parts of the rail run, and say so
    post = next(r for r in all_rows if r["name"] == "Rail post 1")
    rail = next(r for r in all_rows if r["name"] == "Rail run")
    assert post["whole"] == rail["global_id"] and post["predefined_type"] == "POST"
    # properties carry their IFC value type
    props = [p for c in b["chunks"].values() for p in c["properties"]
             if p["global_id"] == wall["global_id"] and p["pset"] == "Pset_WallCommon"]
    by_name = {p["property"]: p for p in props}
    assert by_name["FireRating"]["value"] == "2HR" and by_name["FireRating"]["value_type"] == "IfcLabel"
    assert by_name["IsExternal"]["value"] is True and by_name["IsExternal"]["value_type"] == "IfcBoolean"
    assert by_name["ThermalTransmittance"]["value_type"] == "IfcThermalTransmittanceMeasure"
    assert "Pset_WallCommon" in m["psets"]
    # quantities are SI and come from the model's Qto sets
    qtos = {q["quantity"]: q["value"] for c in b["chunks"].values() for q in c["quantities"]
            if q["global_id"] == wall["global_id"]}
    assert qtos["GrossVolume"] == pytest.approx(3 * 20 * 12 * M_PER_FT ** 3, rel=1e-6)


def test_chunking_by_container_and_none(ifc):
    by_container = build_sheet_bundle(ifc, geometry=False)
    one = build_sheet_bundle(ifc, chunk_by="none", geometry=False)
    assert one["manifest"]["chunks"][0]["id"] == "all"
    assert len(one["chunks"]["all"]["elements"]) == one["manifest"]["model"]["counts"]["elements"]
    assert by_container["manifest"]["geometry"] is None
    for entry in by_container["manifest"]["chunks"]:
        assert entry["files"]["geometry"] is None
    with pytest.raises(ValueError):
        build_sheet_bundle(ifc, chunk_by="storey")


def test_written_bundle_is_deterministic_and_geometry_matches_qto(ifc, tmp_path):
    b = build_sheet_bundle(ifc)
    out1 = write_sheet_bundle(b, tmp_path / "a").parent
    out2 = write_sheet_bundle(build_sheet_bundle(ifc), tmp_path / "b").parent
    for rel in sorted(p.relative_to(out1) for p in out1.rglob("*") if p.is_file()):
        assert (out1 / rel).read_bytes() == (out2 / rel).read_bytes(), rel
    manifest = json.loads((out1 / "manifest.json").read_text(encoding="utf-8"))
    validate_manifest(manifest)
    offset = np.asarray(manifest["geometry"]["offset_m"])
    chunk = next(c for c in manifest["chunks"] if c["files"]["geometry"])
    doc, blob = read_glb(out1 / chunk["files"]["geometry"])
    tables = json.loads((out1 / chunk["files"]["data"]).read_text(encoding="utf-8"))
    names = {n["name"] for n in doc["nodes"]}
    assert names <= {r["global_id"] for r in tables["elements"]}
    qto = {(q["global_id"], q["quantity"]): q["value"] for q in tables["quantities"]}
    # decode one node's mesh and check its volume against the model's Qto
    wall_gid = next(r["global_id"] for r in tables["elements"] if r["name"] == "Abut 1 wall")
    node = next(n for n in doc["nodes"] if n["name"] == wall_gid)
    prim = doc["meshes"][node["mesh"]]["primitives"][0]
    pa, ia = doc["accessors"][prim["attributes"]["POSITION"]], doc["accessors"][prim["indices"]]
    pv, iv = doc["bufferViews"][pa["bufferView"]], doc["bufferViews"][ia["bufferView"]]
    verts = np.frombuffer(blob, dtype="<f4", count=pa["count"] * 3, offset=pv["byteOffset"]).reshape(-1, 3)
    faces = np.frombuffer(blob, dtype="<u4", count=ia["count"], offset=iv["byteOffset"]).reshape(-1, 3)
    assert mesh_volume(verts.astype(float), faces) == pytest.approx(qto[(wall_gid, "GrossVolume")], rel=1e-5)
    # Y-up: the wall stands 12 ft tall along glTF Y, and sits back near the origin after the offset
    back = np.stack([verts[:, 0], -verts[:, 2], verts[:, 1]], axis=1) + offset
    assert back[:, 2].max() - back[:, 2].min() == pytest.approx(12 * M_PER_FT, rel=1e-5)
    assert np.all(np.abs(verts) < 1e4)       # offset took the georeferencing out
    assert node["extras"] == {"ifc_class": "IfcWall"}
    assert pa["min"] == [float(x) for x in verts.min(axis=0)]


def test_glb_writer_layout(tmp_path):
    tri = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    info = write_glb([("A", tri, [(0, 1, 2)], None), ("empty", [], [], None)], tmp_path / "t.glb",
                     extras={"chunk": "x"})
    assert info == {"nodes": 1, "bytes": (tmp_path / "t.glb").stat().st_size, "triangles": 1}
    data = (tmp_path / "t.glb").read_bytes()
    assert data[:4] == b"glTF" and struct.unpack_from("<I", data, 8)[0] == len(data)
    doc, blob = read_glb(tmp_path / "t.glb")
    assert doc["scenes"][0]["extras"] == {"chunk": "x"} and doc["nodes"] == [{"name": "A", "mesh": 0}]
    assert len(blob) % 4 == 0 and doc["buffers"][0]["byteLength"] == len(blob)
    assert np.allclose(to_y_up([(1, 2, 3)]), [[1, 3, -2]])


def test_change_set_round_trip(ifc, tmp_path):
    b = build_sheet_bundle(ifc, geometry=False)
    rows = [r for c in b["chunks"].values() for r in c["elements"]]
    wall = next(r for r in rows if r["name"] == "Abut 1 wall")
    footing = next(r for r in rows if r["name"] == "Abut 2 footing")
    changes = {"contract": "bimforge-changes/1", "source": {"file": ifc.name, "schema": "IFC4X3"},
               "operations": [
                   {"op": "set_property", "global_id": wall["global_id"], "pset": "Pset_WallCommon",
                    "property": "FireRating", "value": "4HR", "value_type": "IfcLabel"},
                   {"op": "set_property", "global_id": wall["global_id"], "pset": "Pset_WallCommon",
                    "property": "IsExternal", "value": "FALSE", "value_type": "IfcBoolean"},
                   {"op": "remove_property", "global_id": wall["global_id"], "pset": "Pset_WallCommon",
                    "property": "ThermalTransmittance"},
                   {"op": "set_property", "global_id": footing["global_id"], "pset": "Pset_FootingCommon",
                    "property": "LoadBearing", "value": True, "value_type": None},
                   {"op": "set_property", "global_id": footing["global_id"], "pset": "ARR_Takeoff",
                    "property": "Width", "value": "10", "value_type": "IfcLengthMeasure"},
                   {"op": "set_property", "global_id": wall["type_global_id"], "pset": "Pset_WallCommon",
                    "property": "Reference", "value": "Std Plan B", "value_type": "IfcIdentifier"},
                   {"op": "set_name", "global_id": footing["global_id"], "value": "Abut 2 footing (rev)"},
               ]}
    out = tmp_path / "edited.ifc"
    report = apply_changes(ifc, changes, out)
    assert report == {"applied": 7, "objects": 3, "added_psets": 3, "removed": 1, "renamed": 1}
    f = ifcopenshell.open(str(out))
    w = f.by_guid(wall["global_id"])
    ps = ue.get_psets(w, should_inherit=False, verbose=True)["Pset_WallCommon"]
    assert ps["FireRating"]["value"] == "4HR" and ps["IsExternal"]["value"] is False
    assert ps["IsExternal"]["value_type"] == "IfcBoolean" and "ThermalTransmittance" not in ps
    ft = f.by_guid(footing["global_id"])
    assert ft.Name == "Abut 2 footing (rev)"
    fps = ue.get_psets(ft, should_inherit=False, verbose=True)
    assert fps["Pset_FootingCommon"]["LoadBearing"]["value"] is True
    assert fps["ARR_Takeoff"]["Width"] == {"id": fps["ARR_Takeoff"]["Width"]["id"], "class": "IfcPropertySingleValue",
                                           "value": 10.0, "value_type": "IfcLengthMeasure"}
    assert ue.get_psets(f.by_guid(wall["type_global_id"]))["Pset_WallCommon"]["Reference"] == "Std Plan B"
    # the edited file re-bundles, and the sheet shows the new values
    b2 = build_sheet_bundle(out, geometry=False)
    props = {(p["global_id"], p["pset"], p["property"]): p["value"]
             for c in b2["chunks"].values() for p in c["properties"]}
    assert props[(wall["global_id"], "Pset_WallCommon", "FireRating")] == "4HR"
    assert props[(footing["global_id"], "ARR_Takeoff", "Width")] == 10.0
    # the original is untouched
    original = ifcopenshell.open(str(ifc))
    assert ue.get_psets(original.by_guid(wall["global_id"]))["Pset_WallCommon"]["FireRating"] == "2HR"


def test_change_set_is_all_or_nothing(ifc, tmp_path):
    b = build_sheet_bundle(ifc, geometry=False)
    wall = next(r for c in b["chunks"].values() for r in c["elements"] if r["name"] == "Abut 1 wall")
    bad = {"contract": "bimforge-changes/1", "operations": [
        {"op": "set_property", "global_id": wall["global_id"], "pset": "Pset_WallCommon",
         "property": "FireRating", "value": "4HR", "value_type": "IfcLabel"},
        {"op": "set_property", "global_id": "0000000000000000000000", "pset": "P", "property": "X", "value": 1},
        {"op": "set_property", "global_id": wall["global_id"], "pset": "P", "property": "N",
         "value": "abc", "value_type": "IfcLengthMeasure"},
        {"op": "set_property", "global_id": wall["global_id"], "pset": "P", "property": "N",
         "value": 1, "value_type": "IfcNoSuchType"},
        {"op": "explode", "global_id": wall["global_id"]},
    ]}
    model = ifcopenshell.open(str(ifc))
    problems = validate_changes(model, bad)
    assert len(problems) == 4
    assert any("0000000000000000000000" in p for p in problems)
    assert any("'abc' is not a IfcLengthMeasure" in p for p in problems)
    assert any("IfcNoSuchType" in p for p in problems)
    assert any("unknown op 'explode'" in p for p in problems)
    out = tmp_path / "never.ifc"
    with pytest.raises(ValueError, match="change-set refused"):
        apply_changes(ifc, bad, out)
    assert not out.exists()
    assert validate_changes(model, {"contract": "other/1"}) == ["not a bimforge-changes/1 change-set: contract='other/1'"]


def test_coerce_from_spreadsheet_text():
    assert coerce("yes", "IfcBoolean") is True and coerce(0, "IfcLogical") is False
    assert coerce("3", "IfcInteger") == 3 and coerce(2.0, "IfcCountMeasure") == 2
    assert coerce("1.5", "IfcLengthMeasure") == 1.5 and coerce(2, "IfcReal") == 2.0
    assert coerce(12, "IfcLabel") == "12" and coerce(None, "IfcLabel") is None
    assert coerce("x", None) == "x"
    for value, vt in (("maybe", "IfcBoolean"), ("2.5", "IfcInteger"), ("tall", "IfcLengthMeasure")):
        with pytest.raises(ValueError):
            coerce(value, vt)


def test_cli_sheet_bundle_and_apply_changes(ifc, tmp_path, capsys):
    from bimforge.bim.cli import main
    out = tmp_path / "bundle"
    assert main(["sheet-bundle", str(ifc), "-o", str(out), "--no-geometry"]) == 0
    assert (out / "manifest.json").exists()
    assert "no geometry" in capsys.readouterr().out
    b = build_sheet_bundle(ifc, geometry=False)
    wall = next(r for c in b["chunks"].values() for r in c["elements"] if r["name"] == "Abut 1 wall")
    cs = tmp_path / "changes.json"
    cs.write_text(json.dumps({"contract": "bimforge-changes/1", "operations": [
        {"op": "set_name", "global_id": wall["global_id"], "value": "Renamed"}]}), encoding="utf-8")
    edited = tmp_path / "edited.ifc"
    assert main(["apply-changes", str(ifc), str(cs), "-o", str(edited)]) == 0
    assert "1 operation(s) applied to 1 object(s)" in capsys.readouterr().out
    assert ifcopenshell.open(str(edited)).by_guid(wall["global_id"]).Name == "Renamed"
    cs.write_text(json.dumps({"contract": "bimforge-changes/1", "operations": [
        {"op": "set_name", "global_id": "nope", "value": "x"}]}), encoding="utf-8")
    assert main(["apply-changes", str(ifc), str(cs), "-o", str(tmp_path / "no.ifc")]) == 1
    assert "change-set refused" in capsys.readouterr().err
    assert not (tmp_path / "no.ifc").exists()
