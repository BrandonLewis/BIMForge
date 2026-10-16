import pytest

from bimforge.author.barrier_732sw_rebar import barrier_732sw_bars
from bimforge.author.primitives import BAR_PROPS

GROUPS = [
    {"mark": "long-barrier", "size": 5, "kind": "long", "count": 12},
    {"mark": "long-deck", "size": 5, "kind": "long", "count": 2},
    {"mark": "vert-face", "size": 6, "kind": "vert", "spacing_in": 8.0,
     "length_ft": 3.43},
    {"mark": "sw-transverse", "size": 5, "kind": "vert", "spacing_in": 12.0,
     "length_ft": 6.1667},
]


def test_longitudinal_weight_matches_hand_calc():
    bars = barrier_732sw_bars(24.0, GROUPS)
    longs = [b for b in bars if b.mark.startswith("long")]
    # 14 continuous #5 bars, each 24 ft, at #5 plf
    expect = 14 * 24.0 * BAR_PROPS[5][2]
    assert sum(b.weight for b in longs) == pytest.approx(expect, rel=1e-6)


def test_vertical_count_follows_spacing():
    bars = barrier_732sw_bars(24.0, GROUPS)
    face = [b for b in bars if b.mark == "vert-face"]
    # 24 ft at 8" spacing -> floor(24/(8/12)) + 1 = 37 bars
    assert len(face) == 37
    assert all(b.size == 6 for b in face)
    # the vert bar's developed length_ft must be honored (not run length / axis-swapped)
    assert face[0].length == pytest.approx(3.43)
    assert face[0].weight == pytest.approx(3.43 * BAR_PROPS[6][2])


def test_every_group_present_and_nonzero():
    bars = barrier_732sw_bars(24.0, GROUPS)
    marks = {b.mark for b in bars}
    assert marks == {"long-barrier", "long-deck", "vert-face", "sw-transverse"}
    assert sum(b.weight for b in bars) > 0.0


def test_unknown_kind_fails_loud():
    with pytest.raises(ValueError, match="unknown bar kind"):
        barrier_732sw_bars(24.0, [{"mark": "x", "size": 5, "kind": "bogus"}])
