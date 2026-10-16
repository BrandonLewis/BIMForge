"""Registry resolution, spec validation, demo-box build->gate->emit, --check-only."""
import shutil
import uuid
from pathlib import Path

import pytest

from bimforge.author.families import registry
from bimforge.author.families.demo_box import build as demo_build
from bimforge.author.project import ProjectContext

EXAMPLES = Path(registry.__file__).resolve().parents[1] / "examples"


def test_available_and_get():
    fams = registry.available()
    assert {"demo-box", "pipe-supports", "standard-plan",
            "headwall-926"} <= set(fams)
    assert registry.get("demo-box") is demo_build
    with pytest.raises(KeyError, match="unknown family"):
        registry.get("flying-buttress")


def test_demo_box_builds_and_checks():
    ctx = ProjectContext(name="d", guid_ns=uuid.UUID(int=9))
    m = demo_build({"count": 2, "size_ft": 4.0, "depth_ft": 2.0,
                    "spacing_ft": 20.0}, ctx)
    assert len(m.elements) == 2
    assert m.elements[0].quantities["volume_cf"] == pytest.approx(32.0)
    with pytest.raises(ValueError, match="missing"):
        demo_build({"count": 2}, ctx)
    from bimforge.author.gate import run_pre
    bad = demo_build({"count": 2, "size_ft": 4.0, "depth_ft": 2.0,
                      "spacing_ft": 2.0}, ctx)          # overlapping
    rep = run_pre(bad)
    assert any("overlap" in f for f in rep.failures)


def test_load_spec_validation(tmp_path):
    spec = tmp_path / "s.yaml"
    spec.write_text("family: demo-box\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing spec keys"):
        registry.load_spec(spec)
    spec.write_text(
        "family: demo-box\nparams: {a: 1}\npaycodes: p.yaml\n"
        "outputs: {nonsense: x}\nproject: {name: x}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown outputs"):
        registry.load_spec(spec)
    spec.write_text(
        "family: demo-box\nparams: {a: 1}\npaycodes: p.yaml\n"
        "outputs: {ifc: null}\nproject: {name: x}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="names no files"):
        registry.load_spec(spec)


def _stage_example(tmp_path) -> Path:
    for f in ("demo-box.spec.yaml", "demo-box.paycodes.yaml"):
        shutil.copy(EXAMPLES / f, tmp_path / f)
    return tmp_path / "demo-box.spec.yaml"


def test_check_only_writes_nothing(tmp_path):
    spec = _stage_example(tmp_path)
    rc = registry.build_from_spec(spec, check_only=True)
    assert rc == 0
    assert not (tmp_path / "out").exists()


def test_build_happy_path_and_round_trip(tmp_path):
    pytest.importorskip("ifcopenshell")
    spec = _stage_example(tmp_path)
    rc = registry.build_from_spec(spec)
    assert rc == 0
    out = tmp_path / "out"
    assert (out / "demo-box.ifc").exists()
    assert (out / "demo-box.dxf").exists()
    import yaml
    from bimforge.bim.ifc_takeoff import build_takeoff
    tmap = yaml.safe_load((out / "demo-box-takeoff-map.yaml").read_text(
        encoding="utf-8"))
    takeoff, _warnings = build_takeoff(str(out / "demo-box.ifc"), tmap)
    rows = {r["cost_code"]: r for r in takeoff["rows"]}
    assert rows["DEMO-FTG"]["quantity"] == pytest.approx(2.3704, abs=2e-3)
    assert rows["DEMO-FTG"]["unit"] == "CY"


def test_gate_failure_blocks_writes(tmp_path):
    import yaml
    spec_path = _stage_example(tmp_path)
    doc = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    doc["params"]["stated_cy"] = 99.0        # stated-quantity gate must trip
    spec_path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    rc = registry.build_from_spec(spec_path)
    assert rc == 1
    assert not (tmp_path / "out").exists()


def test_emitter_failure_cleans_partial_outputs(tmp_path):
    """An emitter raising mid-loop (unwritable second path) must not orphan
    the outputs already written — refuse-partial holds for I/O failures."""
    pytest.importorskip("ifcopenshell")
    import yaml
    spec_path = _stage_example(tmp_path)
    doc = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    (tmp_path / "f").write_text("a file, not a directory", encoding="utf-8")
    doc["outputs"]["ifc"] = "f/demo-box.ifc"      # parent is a FILE -> OSError
    spec_path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(OSError):
        registry.build_from_spec(spec_path)
    assert not (tmp_path / "out" / "demo-box.dxf").exists()


def test_cli_build_unknown_family_one_liner(tmp_path, capsys):
    """est-bim build with an unknown family prints the error one-liner (no
    traceback) and exits 1 — the sibling _run_* CLI convention."""
    from bimforge.bim.cli import main
    spec = tmp_path / "s.yaml"
    spec.write_text(
        "family: flying-buttress\nparams: {a: 1}\npaycodes: p.yaml\n"
        "outputs: {ifc: x.ifc}\n"
        "project: {name: x, guid_ns: '3b7a5c2e-0000-4000-8000-000000000001'}\n",
        encoding="utf-8")
    rc = main(["build", str(spec)])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "unknown family" in err
    assert "Traceback" not in err


def test_tables_file_is_resolved_and_inlined(tmp_path):
    from bimforge.author.families.registry import load_spec
    (tmp_path / "t.yaml").write_text(
        "type_1_case_1:\n  table:\n    8: {W_ft: 6.0}\n", encoding="utf-8")
    (tmp_path / "pc.yaml").write_text(
        "rules: [{match: x, group: g}]\n"
        "groups: {g: {measure: GrossVolume}}\n"
        "codes: {C: {group: g, measure: GrossVolume, unit: CY}}\n",
        encoding="utf-8")
    (tmp_path / "s.yaml").write_text(
        "family: standard-plan\n"
        "params: {tables_file: ./t.yaml, walls: []}\n"
        "paycodes: ./pc.yaml\n"
        "outputs: {dxf: out.dxf}\n"
        "project: {name: n, epsg: 2226, base: [0,0,0], guid_ns: x}\n",
        encoding="utf-8")
    spec = load_spec(tmp_path / "s.yaml")
    assert spec["params"]["tables"]["type_1_case_1"]["table"][8]["W_ft"] == 6.0
    assert "tables_file" not in spec["params"]


def test_tables_file_missing_raises_with_spec_name(tmp_path):
    import pytest
    from bimforge.author.families.registry import load_spec
    (tmp_path / "pc.yaml").write_text(
        "rules: [{match: x, group: g}]\n"
        "groups: {g: {measure: GrossVolume}}\n"
        "codes: {C: {group: g, measure: GrossVolume, unit: CY}}\n",
        encoding="utf-8")
    (tmp_path / "s.yaml").write_text(
        "family: standard-plan\n"
        "params: {tables_file: ./nope.yaml, walls: []}\n"
        "paycodes: ./pc.yaml\n"
        "outputs: {dxf: out.dxf}\n"
        "project: {name: n, epsg: 2226, base: [0,0,0], guid_ns: x}\n",
        encoding="utf-8")
    with pytest.raises(ValueError, match="tables_file"):
        load_spec(tmp_path / "s.yaml")
