from collections import Counter

import pytest

from bimforge.author.alignment import poly_area
from bimforge.author.barrier_842_endblock import (
    ENDBLOCK_842_LEN, endblock_bars, endblock_solid, nose_section)
from bimforge.author.type_842_profile import type_842_profile


def _watertight_and_oriented(sol):
    d = sol.body_solids()[0]
    tris = [tuple(t) for t in d["tris"]]
    edges = Counter()
    for a, b, c in tris:
        for e in ((a, b), (b, c), (c, a)):
            edges[e] += 1
    assert edges and all(n == 1 for n in edges.values())
    assert all((b, a) in edges for (a, b) in edges)


def test_endblock_len_is_nine_ten():
    assert ENDBLOCK_842_LEN == pytest.approx(9.0 + 10.0 / 12.0)


def test_nose_section_is_the_vertical_face_section():
    nose = nose_section({}, base_kind="deck")
    assert nose == type_842_profile({}, base_kind="deck", face="vertical")


def test_loft_volume_equals_trapezoidal_average():
    sol = endblock_solid("EB", {}, base_kind="deck",
                         y_inboard=ENDBLOCK_842_LEN, y_nose=0.0)
    a_run = poly_area(type_842_profile({}, base_kind="deck", face="sloping"))
    a_nose = poly_area(nose_section({}, base_kind="deck"))
    # trapezoidal (mean-of-end-areas) rule; equals the true prismatoid/Simpson
    # volume here ONLY because the taper varies x at fixed z (section area is
    # linear in the sweep parameter), so fan=True must hit it exactly while the
    # single-diagonal fan=False split is ~2.9% off.
    expect = 0.5 * (a_run + a_nose) * ENDBLOCK_842_LEN
    assert sol.volume_cf == pytest.approx(expect, rel=1e-6)


def test_loft_mesh_is_watertight_and_oriented():
    sol = endblock_solid("EB", {}, base_kind="deck",
                         y_inboard=ENDBLOCK_842_LEN, y_nose=0.0)
    _watertight_and_oriented(sol)


def test_wall_endblock_loft_is_watertight():
    # 5-gon running <-> 5-gon vertical nose (the topology-preserving fix)
    sol = endblock_solid("EB", {}, base_kind="wall",
                         y_inboard=ENDBLOCK_842_LEN, y_nose=0.0)
    _watertight_and_oriented(sol)
    assert sol.volume_cf > 0.0


def test_trench_endblock_loft_is_watertight():
    # 6-gon running <-> 6-gon vertical nose
    sol = endblock_solid("EB", {}, base_kind="trench",
                         y_inboard=ENDBLOCK_842_LEN, y_nose=0.0)
    _watertight_and_oriented(sol)
    assert sol.volume_cf > 0.0


def test_endblock_bars_approach_heavier_than_departure():
    ap = endblock_bars(ENDBLOCK_842_LEN, approach=True)
    dp = endblock_bars(ENDBLOCK_842_LEN, approach=False)
    assert sum(b.weight for b in ap) > sum(b.weight for b in dp) > 0.0
