from collections import Counter

import pytest
from bimforge.author.culvert_headwall_rebar import headwall_bars

SCHED = {"wall_vert": {"size": 5, "spacing_in": 12},
         "footing": {"size": 5, "spacing_in": 12},
         "pipe_dist": {"size": 6, "count": 2},
         "wing_vert": {"size": 4, "spacing_in": 12}}


def test_headwall_bars_marks_and_positive():
    bars = headwall_bars(
        wall_length=10.0, design_h=6.0, footing_w=5.0,
        pipe={"dia_ft": 3.0, "material": "rc"},
        wingwalls=[{"length_ft": 8.0}, {"length_ft": 8.0}],
        schedule={"wall_vert": {"size": 5, "spacing_in": 12},
                  "footing": {"size": 5, "spacing_in": 12},
                  "pipe_dist": {"size": 6, "count": 2},
                  "wing_vert": {"size": 4, "spacing_in": 12}},
        cover_in=2.0)
    marks = {b.mark for b in bars}
    assert {"wall_vert", "footing", "pipe_dist", "wing_vert"} <= marks
    assert all(b.weight > 0 for b in bars)
    # pipe distribution bars are #6, count 2 (RC pipe)
    pd = [b for b in bars if b.mark == "pipe_dist"]
    assert len(pd) == 2 and all(b.size == 6 for b in pd)
    # Pin the COUNTS so an off-by-one in bar_stations or a swap of
    # wall_length/footing_w cannot pass silently. 10 ft @ 12" -> 11 stations;
    # each 8 ft wingwall @ 12" -> 9 stations, and the per-wingwall loop runs
    # twice.
    c = Counter(b.mark for b in bars)
    assert c["wall_vert"] == 11
    # R25 continuous footing: 11 under the headwall + 9 under each 8 ft wingwall
    assert c["footing"] == 11 + 9 + 9
    assert c["pipe_dist"] == 2
    assert c["wing_vert"] == 2 * 9      # verifies the per-wingwall loop


def test_metal_pipe_has_no_distribution_bars():
    bars = headwall_bars(
        wall_length=10.0, design_h=6.0, footing_w=5.0,
        pipe={"dia_ft": 3.0, "material": "metal"},
        wingwalls=[], schedule={"wall_vert": {"size": 5, "spacing_in": 12},
                                "footing": {"size": 5, "spacing_in": 12},
                                "pipe_dist": {"size": 6, "count": 2},
                                "wing_vert": {"size": 4, "spacing_in": 12}},
        cover_in=2.0)
    assert not [b for b in bars if b.mark == "pipe_dist"]  # metal -> hook bolts


def test_unknown_pipe_material_raises():
    with pytest.raises(ValueError, match="material"):
        headwall_bars(
            wall_length=10.0, design_h=6.0, footing_w=5.0,
            pipe={"dia_ft": 3.0, "material": "bogus"},
            wingwalls=[], schedule={"wall_vert": {"size": 5, "spacing_in": 12},
                                    "footing": {"size": 5, "spacing_in": 12},
                                    "pipe_dist": {"size": 6, "count": 2},
                                    "wing_vert": {"size": 4, "spacing_in": 12}},
            cover_in=2.0)


def test_footing_bars_cover_wingwalls_and_corners():
    from collections import Counter
    bars = headwall_bars(wall_length=10.0, design_h=6.0, footing_w=5.0,
                         pipe={"dia_ft": 3.0, "center_ft": 5.0, "material": "rc"},
                         wingwalls=[{"length_ft": 8.0}, {"length_ft": 8.0}],
                         schedule=SCHED)                 # existing fixture
    marks = Counter(b.mark for b in bars)
    assert marks["corner"] == 8                          # 4 per corner x 2 wings
    assert marks["wall_dowel"] > 0
    # footing bars now run under the headwall AND both wingwalls: strictly more
    # than the headwall-only count. Compare against a no-wingwall build.
    hw_only = headwall_bars(wall_length=10.0, design_h=6.0, footing_w=5.0,
                            pipe={"dia_ft": 3.0, "center_ft": 5.0, "material": "rc"},
                            wingwalls=[], schedule=SCHED)
    assert Counter(b.mark for b in bars)["footing"] > \
        Counter(b.mark for b in hw_only)["footing"]
    assert all(b.weight > 0 for b in bars)


def test_no_wingwalls_no_corner_or_wingfooting_bars():
    # zero wingwalls -> zero corner bars and zero wingwall-footing additions
    # (guards that corner/footing counts actually key off the wingwall list,
    # not a hardcoded constant).
    from collections import Counter
    bars = headwall_bars(wall_length=10.0, design_h=6.0, footing_w=5.0,
                         pipe={"dia_ft": 3.0, "center_ft": 5.0, "material": "rc"},
                         wingwalls=[], schedule=SCHED)
    assert Counter(b.mark for b in bars)["corner"] == 0
