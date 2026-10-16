import math
from pathlib import Path

import pytest

from bimforge.author import paycodes as pc_mod
from bimforge.author.emit_dxf import emit_dxf
from bimforge.author.emit_ifc import emit_ifc
from bimforge.author.families import concrete_barrier_732sw as cb
from bimforge.author.families.registry import get, load_spec
from bimforge.author.gate import run_post, run_pre
from bimforge.author.project import ProjectContext

PROJECT = {"name": "t", "epsg": 2226, "base": [0.0, 0.0],
           "guid_ns": "6f0e5a1a-0000-4000-8000-000000000000"}
SPEC = (Path(__file__).resolve().parents[1] / "examples"
        / "concrete-barrier-732sw.spec.yaml")


def _ctx():
    return ProjectContext.from_spec(PROJECT)


def test_registry_exposes_family():
    assert get("concrete-barrier-732sw") is cb.build


def test_missing_runs_fails_loud():
    with pytest.raises((KeyError, ValueError)):
        cb.build({}, _ctx())


def test_mod_item_reaches_end_block():
    # a Mod section dim (sidewalk width) must flow into the end-block loft
    # (merged row -> endblock_solid), not only the running prism.
    def eb_cf(m):
        return next(e.quantities["volume_cf"] for e in m.elements
                    if "end block (approach) [start]" in e.name)
    base = cb.build({"runs": [{"name": "NB", "straight_length_ft": 120.0,
                    "handrail": False}]}, _ctx())
    mod = cb.build({"runs": [{"name": "NB", "straight_length_ft": 120.0,
                   "handrail": False, "sw_width_ft": 8.0}]}, _ctx())
    assert eb_cf(mod) > eb_cf(base)


def test_one_concrete_solid_carries_lf_once():
    # default end blocks ON: running prism is shortened; still exactly one
    # element ends with "732sw barrier" (blocks end with "end block (kind)").
    model = cb.build({"runs": [{"name": "NB", "straight_length_ft": 120.0,
                                "handrail": False}]}, _ctx())
    solids = [e for e in model.elements if e.name.endswith("732sw barrier")]
    assert len(solids) == 1
    assert math.isclose(solids[0].quantities["length_ft"], 120.0 - 12.0)
    assert solids[0].quantities["volume_cf"] > 0.0
    # with both end blocks suppressed the full length is the running prism:
    bare = cb.build({"runs": [{"name": "NB", "straight_length_ft": 120.0,
                               "handrail": False, "approach_end_block": False,
                               "departure_end_block": False}]}, _ctx())
    solid = [e for e in bare.elements if e.name.endswith("732sw barrier")][0]
    assert math.isclose(solid.quantities["length_ft"], 120.0)


def test_handrail_false_omits_rail_true_adds_one_railing():
    off = cb.build({"runs": [{"name": "NB", "straight_length_ft": 24.0,
                              "handrail": False}]}, _ctx())
    assert not any("top rail" in e.name for e in off.elements)
    on = cb.build({"runs": [{"name": "NB", "straight_length_ft": 24.0,
                             "handrail": True}]}, _ctx())
    tops = [e for e in on.elements if e.name.endswith("top rail")]
    assert len(tops) == 1
    assert tops[0].geometry is not None
    # the rail must be SEATED on the barrier top, 6" in from the outside face
    from bimforge.author.barrier_section import BarrierSection
    from bimforge.author.families.concrete_barrier_732sw import SECTION_DEFAULTS
    section = BarrierSection("type_732sw", "std", {"barriers": {"type_732sw": {
        "shape": "type_732sw", "variants": {"std": SECTION_DEFAULTS}}}})
    rail_x = min(x for x, _z in section.outline) + 0.5
    xs = [p[0] for p in tops[0].geometry.profile]
    zs = [p[1] for p in tops[0].geometry.profile]
    assert (min(xs) + max(xs)) / 2 == pytest.approx(rail_x)   # x0 = outside face + 6"
    assert min(zs) > section.top_z                            # rail sits ABOVE the barrier top


def _built():
    spec = load_spec(SPEC)
    ctx = ProjectContext.from_spec(spec["project"])
    pc = pc_mod.load(spec["paycodes"])
    model = get(spec["family"])(spec["params"], ctx)
    pc_mod.apply(model, pc)
    return model, pc


def test_barrier_lf_pay_item_covers_full_run_length():
    # the shortened running prism must not shrink the LF pay item: the end
    # blocks carry length_ft so CONC-BARRIER-732SW sums to the full run (120').
    model, pc = _built()
    assert model.total("CONC-BARRIER-732SW", "length_ft") == pytest.approx(120.0)


def test_takeoff_has_barrier_and_handrail_codes():
    model, pc = _built()
    assert run_pre(model, pc).passed, run_pre(model, pc).format()
    used = set(model.codes_used())
    assert {"CONC-BARRIER-732SW", "B732SW-CONC", "B732SW-REBAR"} <= used
    assert {"TUBULAR-HANDRAIL"} <= used


def test_emit_nonempty_and_post_gate(tmp_path):
    pytest.importorskip("ifcopenshell")
    model, pc = _built()
    ifc = tmp_path / "b.ifc"
    dxf = tmp_path / "b.dxf"
    emit_ifc(model, str(ifc), pc, allow_local=True)
    emit_dxf(model, str(dxf))
    assert run_post(model, {"ifc": str(ifc), "dxf": str(dxf)}, pc).passed
    assert ifc.stat().st_size > 0 and dxf.stat().st_size > 0
    import ifcopenshell
    f = ifcopenshell.open(str(ifc))
    assert f.by_type("IfcWall")
    assert f.by_type("IfcRailing")
    assert f.by_type("IfcReinforcingBar")


def test_end_blocks_default_on_emits_two_blocks_and_hardware():
    model = cb.build({"runs": [{"name": "NB", "straight_length_ft": 120.0,
                                "handrail": False}]}, _ctx())
    blocks = [e for e in model.elements if "barrier end block" in e.name]
    assert len(blocks) == 2                              # approach + departure
    assert any("(approach)" in e.name for e in blocks)
    assert any("(departure)" in e.name for e in blocks)
    assert any("transition HSS" in e.name for e in model.elements)
    assert any("transition HS bolts" in e.name for e in model.elements)
    # running prism shortened by 6' at each end:
    run = [e for e in model.elements if e.name.endswith("732sw barrier")][0]
    assert run.quantities["length_ft"] == pytest.approx(120.0 - 12.0)


def test_end_block_flag_false_suppresses_only_that_end():
    model = cb.build({"runs": [{"name": "NB", "straight_length_ft": 120.0,
                                "handrail": False,
                                "approach_end_block": False}]}, _ctx())
    blocks = [e for e in model.elements if "barrier end block" in e.name]
    assert len(blocks) == 1 and "(departure)" in blocks[0].name
    assert not any("(approach)" in e.name for e in model.elements)
    # only the departure hardware remains (1 HSS + 1 bolt group):
    assert len([e for e in model.elements if "transition HSS" in e.name]) == 1
    run = [e for e in model.elements if e.name.endswith("732sw barrier")][0]
    assert run.quantities["length_ft"] == pytest.approx(120.0 - 6.0)


def test_handrail_spans_full_length_over_end_blocks():
    # default end blocks ON shorten the running prism to 108', but the tubular
    # handrail must still span the full 120' run (per B11-59A it continues over
    # the end blocks). Guards against passing run_len instead of length.
    model = cb.build({"runs": [{"name": "NB", "straight_length_ft": 120.0,
                                "handrail": True}]}, _ctx())
    tops = [e for e in model.elements if e.name.endswith("top rail")]
    assert len(tops) == 1
    top = tops[0]
    assert top.quantities["length_ft"] == pytest.approx(120.0)   # NOT 108


def test_curved_run_end_blocks_and_lf():
    run = {"name": "NB", "handrail": False,
           "path": [{"kind": "straight", "length": 20.0},
                    {"kind": "arc", "radius": 250.0, "delta": 20.0, "turn": "R"},
                    {"kind": "straight", "length": 20.0}],
           "approach_end_block": True, "departure_end_block": True}
    m = cb.build({"runs": [run]}, _ctx())
    total = 20.0 + 250.0 * math.radians(20.0) + 20.0
    lf = sum(e.quantities.get("length_ft", 0.0)
             for e in m.elements if e.name.endswith("732sw barrier")
             or "barrier end block" in e.name)
    assert lf == pytest.approx(total)
    blocks = [e for e in m.elements if "barrier end block" in e.name]
    assert len(blocks) == 2 and all(e.quantities["volume_cf"] > 0.0 for e in blocks)


def test_curved_732sw_run_with_default_handrail_is_rejected():
    # curved handrail GEOMETRY is deferred (#149); a curved run with the
    # handrail on must fail loud rather than lay a straight rail off the arc.
    run = {"name": "NB",           # handrail defaults on -> must raise
           "path": [{"kind": "straight", "length": 20.0},
                    {"kind": "arc", "radius": 250.0, "delta": 20.0, "turn": "R"},
                    {"kind": "straight", "length": 20.0}],
           "approach_end_block": True, "departure_end_block": True}
    with pytest.raises(ValueError, match="handrail"):
        cb.build({"runs": [run]}, _ctx())


def test_run_too_short_for_requested_blocks_fails_loud():
    with pytest.raises(ValueError, match="too short"):
        cb.build({"runs": [{"name": "NB", "straight_length_ft": 10.0}]},
                 _ctx())


def test_end_block_concrete_and_rebar_named_for_existing_codes():
    model = cb.build({"runs": [{"name": "NB", "straight_length_ft": 120.0,
                                "handrail": False}]}, _ctx())
    # blocks carry "732sw barrier" so the concrete rule catches them;
    # block bars carry "732sw reinforcing" so the rebar rule catches them.
    blocks = [e for e in model.elements if "barrier end block" in e.name]
    assert all("732sw barrier" in e.name for e in blocks)
    assert all(e.quantities.get("volume_cf", 0.0) > 0.0 for e in blocks)
    eb_bars = [e for e in model.elements
               if "endblock" in e.name and "732sw reinforcing" in e.name]
    assert eb_bars and all(e.quantities["weight_lb"] > 0.0 for e in eb_bars)


def test_transition_paycodes_present_and_roll_up():
    model, pc = _built()
    assert run_pre(model, pc).passed, run_pre(model, pc).format()
    used = set(model.codes_used())
    assert {"B732SW-TRANSITION-STEEL", "B732SW-HS-BOLTS"} <= used
    # transition steel: every HSS (both approach ends + departure) must be
    # captured -> total equals the sum over ALL transition-HSS elements.
    hss_els = [e for e in model.elements if "transition HSS" in e.name]
    assert len(hss_els) == 3                                  # 2 approach + 1 departure
    assert model.total("B732SW-TRANSITION-STEEL", "weight_lb") == pytest.approx(
        sum(e.quantities["weight_lb"] for e in hss_els))
    # HS bolts: exact count proves BOTH ends fold in (6 approach + 1 departure);
    # a floor of >=6 would pass on approach alone.
    assert model.total("B732SW-HS-BOLTS", "count") == 7
    # end-block loft CF is included in the barrier concrete total -- assert the
    # EXACT sum so a broken fold-in (blocks dropping out) fails, not a floor.
    conc = model.total("B732SW-CONC", "volume_cf")
    blocks_cf = sum(e.quantities.get("volume_cf", 0.0)
                    for e in model.elements if "barrier end block" in e.name)
    running = [e for e in model.elements
               if e.name.endswith("732sw barrier")][0]
    assert blocks_cf > 0.0
    assert conc == pytest.approx(running.quantities["volume_cf"] + blocks_cf)
