import math

import pytest
from bimforge.author.primitives import bar_stations
from bimforge.author.wingwall_rebar import type_e_bars, warped_bars


def bar_stations_ft(length, sp_ft):           # local test helper
    return bar_stations(0.0, length, sp_ft)


# stepped wingwall: 3 steps x 6 ft, heights 8.5/5.0/2.0; foot_t=1.0
HW = {"name": "WWE", "kind": "stepped", "stem_t_ft": 0.8333, "toe_ft": 1.0,
      "heel_ft": 4.0, "foot_t_ft": 1.0,
      "steps": [{"length_ft": 6.0, "h_ft": 8.5},
                {"length_ft": 6.0, "h_ft": 5.0},
                {"length_ft": 6.0, "h_ft": 2.0}]}
ROW = {"k_bar": "#5@12", "L_bar": "#6", "L_each_wall": 2}


def test_type_e_k_bars_count_and_length():
    bars = type_e_bars(HW, ROW, cover_in=2.0)
    k = [b for b in bars if b.mark == "k"]
    # 3 steps, each 6 ft at 12 in (1 ft) spacing -> 7 stations/step -> 21 k bars
    assert len(k) == 21
    # a step-1 bar: length = h(8.5) + foot_t(1.0) embed + hook(12*db #5=0.625)
    step1 = [b for b in k if b.host.endswith("step 1")]
    assert len(step1) == 7
    assert step1[0].length == pytest.approx(8.5 + 1.0 + 12 * (0.625 / 12.0), abs=1e-6)
    hook = 12 * (0.625 / 12.0)
    step2 = [b for b in k if b.host.endswith("step 2")]
    step3 = [b for b in k if b.host.endswith("step 3")]
    assert step2[0].length == pytest.approx(5.0 + 1.0 + hook, abs=1e-6)
    assert step3[0].length == pytest.approx(2.0 + 1.0 + hook, abs=1e-6)


def test_type_e_L_bars():
    bars = type_e_bars(HW, ROW, cover_in=2.0)
    L = [b for b in bars if b.mark == "L"]
    assert len(L) == 2                       # L_each_wall
    # length = wall length (18) + 2 hooks (#6: 12*0.75/12)
    assert L[0].length == pytest.approx(18.0 + 2 * 12 * (0.75 / 12.0), abs=1e-6)
    assert L[0].size == 6


def test_type_e_total_weight():
    bars = type_e_bars(HW, ROW, cover_in=2.0)
    total = sum(b.weight for b in bars)
    assert total == pytest.approx(sum(b.length * b.plf for b in bars), abs=1e-9)
    assert total > 0
    assert all(b.size == 5 for b in bars if b.mark == "k")
    assert all(b.size == 6 for b in bars if b.mark == "L")
    assert bars[0].plf == pytest.approx(1.043)   # #5 plf


WHW = {"name": "WWW", "kind": "warped", "wall_h_ft": 8.0, "length_ft": 18.0,
       "min_h_ft": 1.0, "stem_t_ft": 0.8333, "toe_ft": 1.0, "heel_ft": 4.0,
       "foot_t_ft": 1.0, "face_slope": "1.5:1"}
WALL_ROW = {"front": "#4@12", "rear": "#4@8"}
BEAM_REGION = {"h_max": 20, "A_ft": 1.0, "B_ft": 0.75, "total": "6-#7"}


def test_warped_front_face_uses_slope_length():
    bars = warped_bars(WHW, WALL_ROW, BEAM_REGION, cover_in=2.0)
    front = [b for b in bars if b.mark == "front"]
    # front @12 over L=18 -> 19 stations
    assert len(front) == 19
    s = 1.5                                   # face slope 1.5:1
    F, hook = 1.0, 12 * (0.5 / 12.0)          # #4 db=0.5 in
    # culvert-end station (x~0): h≈h_max=8.5 -> along-face h*sqrt(1+s^2)
    tallest = max(front, key=lambda b: b.length)
    assert tallest.length == pytest.approx(
        8.5 * math.sqrt(1 + s * s) + F + hook, abs=0.05)


def test_warped_rear_face_is_near_vertical():
    bars = warped_bars(WHW, WALL_ROW, BEAM_REGION, cover_in=2.0)
    rear = [b for b in bars if b.mark == "rear"]
    assert len(rear) == len(bar_stations_ft(18.0, 8.0 / 12.0))  # @8 over 18
    F, hook = 1.0, 12 * (0.5 / 12.0)
    tallest = max(rear, key=lambda b: b.length)
    assert tallest.length == pytest.approx(8.5 + F + hook, abs=0.05)  # no slope factor


def test_warped_beam_bars():
    bars = warped_bars(WHW, WALL_ROW, BEAM_REGION, cover_in=2.0)
    beam = [b for b in bars if b.mark == "beam"]
    assert len(beam) == 6                     # TOTAL 6-#7
    assert beam[0].size == 7
    hook = 12 * (0.875 / 12.0)                 # #7 db=0.875
    assert beam[0].length == pytest.approx(18.0 + 2 * hook, abs=1e-6)


def test_minor_bars_full_detailing():
    # dowels (#4 x 5'-0 @12) + spacers (#4 @12) over the wall length L=18
    from bimforge.author.wingwall_rebar import minor_bars
    bars = minor_bars(HW, cover_in=2.0)       # HW = stepped, L=18 (3x6)
    dowels = [b for b in bars if b.mark == "dowel"]
    assert len(dowels) == 19                  # @12 over 18 -> 19
    assert dowels[0].length == pytest.approx(5.0)   # 5'-0 dowel
    spacers = [b for b in bars if b.mark == "spacer"]
    assert len(spacers) == 19
    assert spacers[0].length == pytest.approx(HW["stem_t_ft"])


def test_wingwall_bars_dispatch_stepped():
    from bimforge.author.wingwall_steel import WingwallSteel
    from bimforge.author.wingwall_rebar import wingwall_bars
    steel = WingwallSteel({"type_e": {"10": {"k_bar": "#5@12", "L_bar": "#6",
                                             "L_each_wall": 2}}})
    # HW stepped max step height is 8.5 -> rounds up to "10"
    bars = wingwall_bars(HW, steel, cover_in=2.0)
    assert any(b.mark == "k" for b in bars)
    assert any(b.mark == "dowel" for b in bars)     # minor bars included


def test_wingwall_bars_dispatch_warped():
    from bimforge.author.wingwall_steel import WingwallSteel
    from bimforge.author.wingwall_rebar import wingwall_bars
    steel = WingwallSteel({"warped": {
        "wall": {"8": {"slopes": {"1.5:1": {"front": "#4@12", "rear": "#4@8"}}}},
        "beam": {"by_l": {"20": [{"h_max": 20, "total": "6-#7"}]}}}})
    bars = wingwall_bars(WHW, steel, cover_in=2.0)   # WHW warped, face_slope 1.5:1, L=18
    assert any(b.mark == "front" for b in bars)
    assert any(b.mark == "beam" for b in bars)
    assert any(b.mark == "spacer" for b in bars)     # minor bars included
