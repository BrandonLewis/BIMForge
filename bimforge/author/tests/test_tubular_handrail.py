import math

from bimforge.author.families import tubular_handrail as th
from bimforge.author.families.registry import get
from bimforge.author.project import ProjectContext

PROJECT = {"name": "t", "epsg": 2226, "base": [0.0, 0.0],
           "guid_ns": "6f0e5a1a-0000-4000-8000-000000000000"}


def _ctx():
    return ProjectContext.from_spec(PROJECT)


def test_registry_exposes_family():
    assert get("tubular-handrail") is th.build


def test_build_two_runs_makes_two_top_rails():
    params = {"runs": [
        {"name": "NB", "straight_length_ft": 24.0, "base_z_ft": 2.0},
        {"name": "SB", "straight_length_ft": 12.0, "base_z_ft": 2.0},
    ]}
    model = th.build(params, _ctx())
    names = [e.name for e in model.elements]
    assert sum(n.endswith("top rail") for n in names) == 2
    top_nb = next(e for e in model.elements if e.name == "NB top rail")
    assert math.isclose(top_nb.quantities["length_ft"], 24.0)


def test_missing_runs_fails_loud():
    import pytest
    with pytest.raises((KeyError, ValueError)):
        th.build({}, _ctx())


def test_alignment_bound_run_rejected():
    import pytest
    with pytest.raises(ValueError, match="follow-on"):
        th.build({"runs": [{"name": "curved"}]}, _ctx())


def test_run_override_anchorage_false_reaches_primitive():
    model = th.build({"runs": [{"name": "NB", "straight_length_ft": 24.0,
                                "anchorage": False}]}, _ctx())
    names = [e.name for e in model.elements]
    assert not any("mortar" in n for n in names)   # anchorage=False honoured
    assert not any("dowel" in n for n in names)


def test_scalar_end_posts_not_split_into_characters():
    # YAML `end_posts: start` (scalar) must mean one end, not 5 characters.
    model = th.build({"runs": [{"name": "NB", "straight_length_ft": 24.0,
                                "end_posts": "start"}]}, _ctx())
    names = [e.name for e in model.elements]
    assert any(n == "NB end return start" for n in names)
    assert not any(n.endswith("end return end") for n in names)
    # the char-split bug would have raised on 's'/'t'/'a'/... -- if it silently
    # produced fewer/garbled returns this catches it.
    assert sum("end return" in n for n in names) == 1


def test_scalar_joint_not_iterated_as_characters():
    # YAML `joints: 12.0` (scalar) must mean one joint station, not TypeError.
    model = th.build({"runs": [{"name": "NB", "straight_length_ft": 24.0,
                                "joints": 12.0}]}, _ctx())
    sleeves = [e for e in model.elements if "splice sleeve" in e.name]
    assert len(sleeves) == 1


# --------------------------------------------------------------------- e2e
from pathlib import Path

import pytest

from bimforge.author import paycodes as pc_mod
from bimforge.author.emit_dxf import emit_dxf
from bimforge.author.emit_ifc import emit_ifc
from bimforge.author.families.registry import load_spec
from bimforge.author.gate import run_post, run_pre

SPEC = (Path(__file__).resolve().parents[1] / "examples"
        / "tubular-handrail.spec.yaml")


def _built():
    spec = load_spec(SPEC)
    ctx = ProjectContext.from_spec(spec["project"])
    pc = pc_mod.load(spec["paycodes"])
    model = get(spec["family"])(spec["params"], ctx)
    pc_mod.apply(model, pc)
    return model, pc


def test_codes_used_are_the_five_handrail_codes():
    model, pc = _built()
    assert run_pre(model, pc).passed, run_pre(model, pc).format()
    assert sorted(model.codes_used()) == [
        "HANDRAIL-MORTAR", "HANDRAIL-REBAR", "HANDRAIL-STL",
        "HANDRAIL-STL-TOP", "TUBULAR-HANDRAIL"]


def test_lf_equals_payment_length_once():
    model, pc = _built()
    tops = [e for e in model.elements if e.name.endswith("top rail")]
    assert len(tops) == 1
    assert math.isclose(tops[0].quantities["length_ft"], 120.0)


def test_emit_nonempty_ifc_dxf_and_post_gate(tmp_path):
    pytest.importorskip("ifcopenshell")
    model, pc = _built()
    assert run_pre(model, pc).passed
    ifc = tmp_path / "h.ifc"
    dxf = tmp_path / "h.dxf"
    emit_ifc(model, str(ifc), pc, allow_local=True)
    emit_dxf(model, str(dxf))
    assert run_post(model, {"ifc": str(ifc), "dxf": str(dxf)}, pc).passed
    assert ifc.stat().st_size > 0 and dxf.stat().st_size > 0
    import ifcopenshell
    f = ifcopenshell.open(str(ifc))
    assert f.by_type("IfcRailing")            # the payment top rail
    assert f.by_type("IfcMember")             # posts / lower rail / sleeves / end returns
    assert f.by_type("IfcPlate")              # rail caps
    assert f.by_type("IfcReinforcingBar")     # post-pocket dowels
    assert f.by_type("IfcBuildingElementProxy")  # pocket mortar
