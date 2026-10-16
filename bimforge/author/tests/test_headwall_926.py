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
