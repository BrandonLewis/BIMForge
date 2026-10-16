"""End-to-end: the worked two-span box-girder example (spec 4.8) through
run_pre -> emit_ifc + emit_dxf -> run_post, plus the whole `est-bim build`
pipeline via `build_from_spec`.

The model is built by loading the SHIPPED spec (`load_spec` + the registry
builder) rather than by re-declaring params here: the fixture under test is
the file CI ships, and a hand-copied params dict would drift from it.
"""
from pathlib import Path

import pytest
import yaml

pytest.importorskip("ifcopenshell")

from bimforge.author import paycodes as pc_mod
from bimforge.author.emit_dxf import emit_dxf
from bimforge.author.emit_ifc import emit_ifc
from bimforge.author.families.registry import build_from_spec, get, load_spec
from bimforge.author.gate import MESH_TOLERANCE, run_post, run_pre
from bimforge.author.project import ProjectContext

SPEC = (Path(__file__).resolve().parents[1] / "examples"
        / "bridge-standard.spec.yaml")


def _built():
    """(model, paycodes) for the shipped worked example."""
    spec = load_spec(SPEC)
    ctx = ProjectContext.from_spec(spec["project"])
    pc = pc_mod.load(spec["paycodes"])
    model = get(spec["family"])(spec["params"], ctx)
    pc_mod.apply(model, pc)
    return model, pc


def test_pre_gate_passes():
    model, pc = _built()
    rep = run_pre(model, pc)
    assert rep.passed, rep.format()
    names = [e.name for e in model.elements]
    assert sum("superstructure" in n for n in names) == 2
    assert sum("diaphragm" in n for n in names) == 2
    assert sorted(model.codes_used()) == [
        "STRUCT-CONC-BR-DECK", "STRUCT-CONC-BR-SUB"]


def test_emit_and_post_gate(tmp_path):
    model, pc = _built()
    assert run_pre(model, pc).passed
    ifc = tmp_path / "bridge.ifc"
    dxf = tmp_path / "bridge.dxf"
    emit_ifc(model, str(ifc), pc)
    emit_dxf(model, str(dxf))
    rep = run_post(model, {"ifc": str(ifc), "dxf": str(dxf)}, pc)
    assert rep.passed, rep.format()
    assert ifc.exists() and dxf.exists()      # pass -> outputs kept


def test_build_from_spec_writes_every_output(tmp_path):
    """The real pipeline, outputs redirected into tmp_path.

    The spec is re-emitted with an ABSOLUTE paycodes path because
    `load_spec` resolves relative paths from the spec's own directory.
    """
    doc = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    doc["paycodes"] = str((SPEC.parent / doc["paycodes"]).resolve())
    doc["outputs"] = {"dxf": str(tmp_path / "br.dxf"),
                      "ifc": str(tmp_path / "br.ifc"),
                      "takeoff_map": str(tmp_path / "br-takeoff-map.yaml")}
    copy = tmp_path / "bridge-standard.spec.yaml"
    copy.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    assert build_from_spec(copy) == 0
    for name in ("br.dxf", "br.ifc", "br-takeoff-map.yaml"):
        assert (tmp_path / name).exists()
    tmap = yaml.safe_load((tmp_path / "br-takeoff-map.yaml").read_text(
        encoding="utf-8"))
    assert sorted(tmap["codes"]) == ["STRUCT-CONC-BR-DECK",
                                     "STRUCT-CONC-BR-SUB"]


def test_mesh_matches_the_declared_volume_with_room_to_spare(tmp_path,
                                                             capsys):
    """Record the slack every element actually has against the 0.50%
    MESH_TOLERANCE — the number the sabotage test below relies on.

    The two spans and the diaphragms are FACE-DECLARED (a nonzero end skew
    lands on a curve, where the Pappus closed form does not hold, so the
    engine declares its own facet volume): for them this measures the
    emitter's fidelity, and the residual is float noise. The rectangular
    substructure declares L x W x H, so its residual is the emitter's
    fidelity too. Nothing here is a loose closed-form-vs-facet band.
    """
    from bimforge.bim.ifc_mesh import mesh_leg
    model, pc = _built()
    for name in ("span 1 superstructure", "span 2 superstructure"):
        assert model.element(name).geometry._face_declared
    ifc = tmp_path / "bridge.ifc"
    emit_ifc(model, str(ifc), pc)
    got: dict[str, float] = {}
    for info in mesh_leg(str(ifc)).values():
        got[info["name"]] = got.get(info["name"], 0.0) + info["mesh"][
            "volume_m3"]
    m3 = model.ctx.ft_to_m ** 3
    worst = 0.0
    with capsys.disabled():
        for el in model.elements:
            want = el.quantities.get("volume_cf")
            if not want:
                continue
            assert el.name in got, f"{el.name} has no IFC mesh to check"
            err = abs(got[el.name] - want * m3) / (want * m3)
            worst = max(worst, err)
            print(f"mesh vs declared  {el.name:<28} {err:.3e}")
        print(f"worst element {worst:.3e} vs MESH_TOLERANCE "
              f"{MESH_TOLERANCE:.3e}")
    assert worst < MESH_TOLERANCE


def test_post_gate_deletes_outputs_when_a_span_volume_is_wrong(tmp_path):
    """Proves the post-emit mesh check is NOT vacuously skipping the swept
    deck: it matches "span 1 superstructure" by name and measures it well
    inside the 0.50% band on the honest model, so inflating the declared
    volume 20% must fail the gate AND delete both outputs."""
    model, pc = _built()
    ifc = tmp_path / "bad.ifc"
    dxf = tmp_path / "bad.dxf"
    emit_ifc(model, str(ifc), pc)
    emit_dxf(model, str(dxf))
    model.element("span 1 superstructure").quantities["volume_cf"] *= 1.2
    rep = run_post(model, {"ifc": str(ifc), "dxf": str(dxf)}, pc)
    assert not rep.passed
    assert any("IFC mesh volume" in f for f in rep.failures), rep.format()
    assert any("span 1 superstructure" in f for f in rep.failures)
    assert not ifc.exists() and not dxf.exists()
