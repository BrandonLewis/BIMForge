"""headwall-926: hand-computed concrete, options, taper shape check."""
import math
import uuid

import pytest

from bimforge.author.families.headwall_926 import build
from bimforge.author.gate import run_pre
from bimforge.author.project import ProjectContext

CTX = ProjectContext(name="f", guid_ns=uuid.UUID(int=8))

# Neutral fixture in the 9-26 shape (values are round, not any bid's).
PARAMS = {
    "pipe_dia_ft": 3.0, "wall_t_ft": 0.67, "hw_int_w_ft": 5.5,
    "hw_height_ft": 5.75, "foot_len_ft": 6.83, "foot_splay_ft": 1.0,
    "wing_len_ft": 6.16, "cut_depth_ft": 2.0,
    "el_top_hw": 130.26, "el_invert": 127.18,
}


def test_concrete_hand_figures():
    m = build(PARAMS, CTX)
    hw_w = 5.5 + 2 * 0.67                       # 6.84
    hw = m.element("headwall")
    want = hw_w * 0.67 * 5.75 - math.pi * 1.5 ** 2 * 0.67
    assert hw.quantities["volume_cf"] == pytest.approx(want, rel=1e-6)
    foot = m.element("headwall footing")
    trap_area = (hw_w + hw_w + 2.0) / 2.0 * 6.83
    assert foot.quantities["volume_cf"] == pytest.approx(trap_area * 0.67,
                                                         rel=1e-6)
    cut = m.element("cutoff wall")
    assert cut.quantities["volume_cf"] == pytest.approx(hw_w * 0.67 * 2.0,
                                                        rel=1e-6)
    # wingwall: triangular taper -> half the full-height slab volume
    wing = m.element("left wingwall")
    assert wing.quantities["volume_cf"] == pytest.approx(
        wing.quantities["length_ft"] * 0.67 * 5.75 / 2.0, rel=1e-2)
    assert len(m.openings) == 1
    assert run_pre(m).passed


def test_elevations_are_model_z_relative_to_base_h():
    # The model frame is z = elevation - base_h (ProjectContext.local): with
    # the base at elevation 100, a top of headwall at 130.26 is model z
    # 30.26, and the pipe opening's centre sits at invert + r - 100.
    ctx = ProjectContext(name="f", guid_ns=uuid.UUID(int=8), base_h=100.0)
    m = build({**PARAMS, "guardrail": {}}, ctx)
    hw = m.element("headwall").geometry
    assert hw.z_top == pytest.approx(30.26)
    assert hw.z_bot == pytest.approx(30.26 - 5.75)
    (_host, opening), = m.openings
    assert opening.geometry["cz"] == pytest.approx(27.18 + 1.5)
    assert m.element("guardrail").z_ft == pytest.approx(30.26)
    assert run_pre(m).passed


def test_trash_rack_sits_over_the_opening():
    # The rack's bars are centred on the pipe: their z is from the top of
    # footing, so the element sits at the top of footing, not at z 0.
    ctx = ProjectContext(name="f", guid_ns=uuid.UUID(int=8), base_h=100.0)
    m = build({**PARAMS, "rack": {"bars": 7}}, ctx)
    rack = m.element("trash rack")
    (_host, opening), = m.openings
    for (_x, _y, z_in, *_size) in rack.geometry["boxes"]:
        assert rack.z_ft + z_in / 12.0 == pytest.approx(opening.geometry["cz"])
    assert run_pre(m).passed


def test_options_are_off_by_default_and_add_steel():
    m = build(PARAMS, CTX)
    names = [e.name for e in m.elements]
    assert "trash rack" not in names and "guardrail" not in names
    m2 = build({**PARAMS, "rack": {"bars": 7}, "guardrail": {}}, CTX)
    rack = m2.element("trash rack")
    assert rack.quantities["count"] == 7
    assert rack.weight_lb > 0
    rail = m2.element("guardrail")
    assert rail.quantities["count"] >= 2
    assert run_pre(m2).passed


def test_missing_params():
    with pytest.raises(ValueError, match="missing"):
        build({"pipe_dia_ft": 3.0}, CTX)
