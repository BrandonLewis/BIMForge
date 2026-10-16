"""terrain/reconcile: the neighbour graph, the range check, and the findings.

Everything here runs on the base install (numpy); scipy only speeds the
neighbour search and is exercised both ways.
"""
import math
import sys

import numpy as np
import pytest

from bimforge.terrain.contours import build_adjacency
from bimforge.terrain.reconcile import (NeighbourGraph, neighbour_graph, _crossing,
                                        reconcile, CHECKS, Contact, Finding,
                                        build_findings)


def poly(pts, src="sheet A", lay="EG"):
    return (np.asarray(pts, dtype=float), src, lay)


def hline(y, x0=0.0, x1=100.0, n=11):
    xs = np.linspace(x0, x1, n)
    return np.column_stack([xs, np.full(n, float(y))])


def ray(deg, r=10.0):
    a = math.radians(deg)
    return (r * math.cos(a), r * math.sin(a))


# ---------------------------------------------------------- neighbour graph
def _sparse_middle():
    # dense outer lines, a two-vertex middle line: the 79 - 96 - 78 case
    return [poly(hline(0.0, n=101)), poly([(0.0, 10.0), (100.0, 10.0)]),
            poly(hline(20.0, n=101))]


def test_neighbour_graph_cannot_skip_a_sparse_line():
    polys = _sparse_middle()
    # the shipped vertex vote reaches past the sparse middle line ...
    assert (0, 2) in build_adjacency(polys)
    # ... the facing vote cannot: any line crossing the connector is nearer
    g = neighbour_graph(polys)
    assert g.faces == {(0, 1), (1, 2)}
    assert not g.same and not g.joints and not g.contacts


def test_neighbour_graph_equal_spacing_keeps_every_neighbour():
    g = neighbour_graph([poly(hline(10.0 * k)) for k in range(4)])
    assert g.faces == {(0, 1), (1, 2), (2, 3)}


def test_neighbour_graph_numpy_fallback_matches(monkeypatch):
    monkeypatch.setitem(sys.modules, "scipy", None)
    monkeypatch.setitem(sys.modules, "scipy.spatial", None)
    assert neighbour_graph(_sparse_middle()).faces == {(0, 1), (1, 2)}


def test_end_to_end_pieces_are_a_joint_not_a_hop():
    a = poly([(0.0, 0.0), (50.0, 0.0)])
    b = poly([(50.0, 0.0), (100.0, 0.0)])
    c = poly(hline(10.0))
    g = neighbour_graph([a, b, c])
    assert g.joints == {(0, 1)}
    assert (0, 1) not in g.faces
    assert {(0, 2), (1, 2)} <= g.faces
    assert not g.contacts


def test_a_piece_lying_on_a_line_is_the_same_contour():
    a = poly(hline(0.0, n=101))
    b = poly([(20.0, 0.1), (60.0, 0.1)])            # same layer, 0.1 ft off
    g = neighbour_graph([a, b, poly(hline(10.0))])
    assert g.same == {(0, 1)}
    assert (0, 1) not in g.faces and not g.contacts
    assert (0, 0) in g.adjacency()[1]          # one contour: no hop between


def test_crossing_lines_are_a_contact_not_neighbours():
    g = neighbour_graph([poly(hline(0.0)), poly([(50.0, -20.0), (50.0, 20.0)])])
    (c,) = g.contacts
    assert c.kind == "cross" and c.pair == (0, 1)
    assert c.xy == pytest.approx((50.0, 0.0))
    assert not g.faces


def test_a_vertex_that_only_touches_is_a_touch_not_a_cross():
    # b's middle vertex lands exactly on a (a's own vertex grid included:
    # hline(0.0, n=11) has a vertex at x=50 too) but b never reaches past
    # y=0 -- it dips to the line and returns, it does not cross through.
    a = poly(hline(0.0, n=11))
    b = poly([(0.0, 10.0), (50.0, 0.0), (100.0, 10.0)])
    g = neighbour_graph([a, b])
    (c,) = g.contacts
    assert c.kind == "touch" and c.pair == (0, 1)
    assert not g.faces


def test_a_bend_that_crosses_through_is_still_a_cross():
    # p bends exactly at the point where it touches q's line -- unlike the
    # V-touch above, p's path genuinely continues to the far side (up and
    # to the right of x=50), so this is a real crossing, not a touch.
    p = poly([(0.0, 0.0), (50.0, 0.0), (100.0, 50.0)])
    q = poly([(50.0, -20.0), (50.0, 20.0)])
    g = neighbour_graph([p, q])
    (c,) = g.contacts
    assert c.kind == "cross" and c.pair == (0, 1)
    assert not g.faces


def test_a_bend_through_a_sharp_q_vertex_is_still_a_cross():
    # q turns sharply (its own two rays are only 30 degrees apart, at 150
    # and 180); p passes through q's vertex bending from inside that
    # narrow gap (165) to well outside it (30) -- a genuine crossing, and
    # unaffected by which line is listed first.
    p = poly([ray(165.0), (0.0, 0.0), ray(30.0)])
    q = poly([ray(180.0), (0.0, 0.0), ray(150.0)])
    g = neighbour_graph([p, q])
    assert [c.kind for c in g.contacts] == ["cross"]
    assert not g.faces
    g_swapped = neighbour_graph([q, p])
    assert [c.kind for c in g_swapped.contacts] == ["cross"]
    assert not g_swapped.faces


def test_a_v_touching_a_sharp_q_vertex_from_outside_is_not_a_cross():
    # p's two arms (30 and -30 degrees) both stay in the wide arc outside
    # q's narrow (150, 180) gap -- p touches q's vertex but never crosses
    # through it, from either side. (Whether this momentary touch clears
    # neighbour_graph's separate touch-length threshold is a different,
    # pre-existing question; what this guards is that it is never "cross".)
    p = poly([ray(30.0), (0.0, 0.0), ray(-30.0)])
    q = poly([ray(180.0), (0.0, 0.0), ray(150.0)])
    g = neighbour_graph([p, q])
    assert not any(c.kind == "cross" for c in g.contacts)
    g_swapped = neighbour_graph([q, p])
    assert not any(c.kind == "cross" for c in g_swapped.contacts)


def test_crossing_case_list_agrees_regardless_of_argument_order_and_direction():
    # _crossing(p, q) and _crossing(q, p) must always agree -- neighbour_graph
    # only ever calls it one way (the lower line index first), so any
    # order-dependence would make the "cross" finding depend on which
    # index a contour happened to get. Nor may the verdict depend on which
    # way a polyline runs: bridge / merge_fragments can reverse one.
    hl = hline(0.0, n=11)                        # a vertex at x=50
    dup = np.vstack([hl[:6], hl[5:6], hl[6:]])   # ... and a duplicate of it
    vertical = np.array([(50.0, -20.0), (50.0, 20.0)])
    diamond_at_5 = np.array([(5.0, 0.0), (7.0, -2.0), (9.0, 0.0), (7.0, 2.0),
                             (5.0, 0.0)])        # closed, its seam at (5, 0)
    cases = [
        ("straight crossing, a vertex of both lines", hl, vertical, True),
        ("V touch: vertex on q, turns back", hl,
         np.array([(0.0, 10.0), (50.0, 0.0), (100.0, 10.0)]), False),
        ("p bends through q's vertex",
         np.array([(0.0, 0.0), (50.0, 0.0), (100.0, 50.0)]), vertical, True),
        ("sharp q vertex, p bends through the gap",
         np.array([ray(165.0), (0.0, 0.0), ray(30.0)]),
         np.array([ray(180.0), (0.0, 0.0), ray(150.0)]), True),
        ("sharp q vertex, p is a V from outside",
         np.array([ray(30.0), (0.0, 0.0), ray(-30.0)]),
         np.array([ray(180.0), (0.0, 0.0), ray(150.0)]), False),
        ("collinear overlap (the same line twice)", hl, hl.copy(), False),
        ("a plain mid-segment crossing, no vertex involved",
         hl, np.array([(33.0, -20.0), (33.0, 20.0)]), True),
        ("a T: one line ends on the other's interior",
         np.array([(40.0, 0.0), (50.0, 0.0)]), vertical, False),
        ("a crossing at a duplicated vertex", dup, vertical, True),
        ("a crossing through a 0.0005 ft segment ending on p",
         np.array([(0.0, 0.0), (10.0, 0.0)]),
         np.array([(5.0, -5.0), (5.0, -0.0005), (5.0, 0.0), (5.0, 5.0)]), True),
        ("a V-touch from below whose 0.0005 ft segment ends on p",
         np.array([(0.0, 1.0), (10.0, -1.0)]),
         np.array([(3.0, -5.0), (5.0, -0.0005), (5.0, 0.0), (7.0, -5.0)]), False),
        ("a crossing at a closed contour's seam vertex",
         np.array([(0.0, 0.0), (6.0, 0.0)]), diamond_at_5, True),
        ("a closed contour's seam vertex touching p from one side",
         np.array([(4.0, 0.0), (10.0, 0.0)]),
         np.array([(5.0, 0.0), (7.0, 2.0), (5.0, 4.0), (3.0, 2.0), (5.0, 0.0)]),
         False),
    ]
    for name, p, q, expect_cross in cases:
        for pp, pd in ((p, "p"), (p[::-1], "reversed p")):
            for qq, qd in ((q, "q"), (q[::-1], "reversed q")):
                for args, order in (((pp, qq), f"({pd}, {qd})"),
                                    ((qq, pp), f"({qd}, {pd})")):
                    got = _crossing(*args) is not None
                    assert got == expect_cross, (
                        f"{name}: _crossing{order} gave cross={got}, "
                        f"expected {expect_cross}")


@pytest.mark.parametrize("d", [1e-9, 1e-6, 1e-5, 5e-4, 1e-2])
@pytest.mark.parametrize("origin", [(0.0, 0.0), (2008473.0, 6692677.0)])
def test_a_short_segment_at_the_touch_point_never_changes_the_verdict(d, origin):
    # however short the segment next to (or straddling) the touching point,
    # and at plan-sheet coordinates too, the verdict is the geometry's
    o = np.asarray(origin)
    cases = [
        ([(0, 0), (10, 0)], [(5, -5), (5, -d), (5, 0), (5, 5)], True),
        ([(0, 0), (10, 0)], [(5, -5), (5, -d / 2), (5, d / 2), (5, 5)], True),
        ([(0, 1), (10, -1)], [(3, -5), (5, -d), (5, 0), (7, -5)], False),
        ([(0, 0), (10, 0)], [(3, -5), (5, -d), (5, 0), (7, -5)], False),
    ]
    for p, q, expect_cross in cases:
        p, q = np.asarray(p, float) + o, np.asarray(q, float) + o
        for pp in (p, p[::-1]):
            for qq in (q, q[::-1]):
                assert (_crossing(pp, qq) is not None) == expect_cross
                assert (_crossing(qq, pp) is not None) == expect_cross


def test_a_steep_crossing_between_samples_is_a_cross_not_faces():
    # every 1 ft sample of either line lands >= 0.5 ft from the other, so
    # there is no contact vote -- the pair must still be crossing-tested
    # before it may face
    p = poly([(0.0, 0.0), (100.0, 0.0)])
    q = poly([(50.5, -50.5), (50.5, 49.5)])
    g = neighbour_graph([p, q])
    assert not g.faces
    (c,) = g.contacts
    assert c.kind == "cross" and c.pair == (0, 1) and c.length_ft == 0.0
    assert c.xy == pytest.approx((50.5, 0.0))


def test_converging_contours_touch_and_are_not_neighbours():
    a = poly(hline(0.0, n=101))
    b = poly([(0.0, 10.0), (40.0, 0.3), (60.0, 0.3), (100.0, 10.0)])
    g = neighbour_graph([a, b])
    (c,) = g.contacts
    assert c.kind == "touch" and c.pair == (0, 1)
    assert c.length_ft >= 2.0
    assert 40.0 <= c.xy[0] <= 60.0
    assert not g.faces and not g.same


def test_a_touch_across_layers_is_not_the_same_contour():
    a = poly(hline(0.0, n=101), lay="MJR")
    b = poly(hline(0.2, n=101), lay="MNR")          # on top of it, other layer
    g = neighbour_graph([a, b])
    assert not g.same and [c.kind for c in g.contacts] == ["touch"]


def test_neighbour_graph_records_its_parameters_and_handles_one_line():
    g = neighbour_graph([poly(hline(0.0))], contact_ft=0.25)
    assert isinstance(g, NeighbourGraph) and g.n == 1
    assert g.params == {"sample_ft": 1.0, "contact_ft": 0.25,
                        "min_facing_ft": 4.0}
    assert not (g.faces or g.same or g.joints or g.contacts)


# ---------------------------------------------------------------- reconcile
def chain_graph(n, same=()):
    """Lines 0..n-1, each facing the next (a hand-built graph: no geometry)."""
    return NeighbourGraph(n=n, faces={(k, k + 1) for k in range(n - 1)} - set(same),
                          same=set(same))


def test_two_agreeing_labels_pin_the_line_between():
    polys = [poly(hline(10.0 * k)) for k in range(4)]
    rec = reconcile(polys, neighbour_graph(polys), {0: 100.0, 2: 120.0, 3: 130.0},
                    10.0)
    assert rec.pinned == {1: 110.0}
    lr = rec.lines[1]
    assert (lr.status, lr.lo, lr.hi, lr.values) == ("pinned", 110.0, 110.0, [110.0])
    assert rec.lines[0].status == "lettered" and not rec.label_conflicts


def test_reuse_gives_the_same_ranges_as_a_fresh_reconcile():
    # the CLI's recheck sets one label aside at a time over the same graph
    polys = [poly(hline(10.0 * k)) for k in range(8)]
    g = neighbour_graph(polys)
    elev = {0: 100.0, 3: 130.0, 5: 170.0, 7: 170.0}      # 130 / 170 conflict
    spot = [{"elev": 112.0, "xy": (50.0, 11.0)}]
    rec = reconcile(polys, g, elev, 10.0, spot_pins=spot)
    assert rec.label_conflicts
    for k in elev:
        e = {a: z for a, z in elev.items() if a != k}
        fresh = reconcile(polys, g, e, 10.0, spot_pins=spot)
        again = reconcile(polys, g, e, 10.0, reuse=rec)
        assert again.lines == fresh.lines
        assert again.pinned == fresh.pinned
        assert again.label_conflicts == fresh.label_conflicts


def test_reuse_refuses_a_label_it_has_no_hops_for():
    polys = [poly(hline(10.0 * k)) for k in range(4)]
    g = neighbour_graph(polys)
    rec = reconcile(polys, g, {0: 100.0}, 10.0)
    with pytest.raises(ValueError, match="reuse"):
        reconcile(polys, g, {0: 100.0, 3: 130.0}, 10.0, reuse=rec)
    with pytest.raises(ValueError, match="reuse"):
        reconcile(polys, g, {0: 100.0}, 5.0, reuse=rec)


def test_reconciliations_still_compare_by_value():
    # the hop-table cache stays out of == (a numpy array would make it raise)
    polys = [poly(hline(10.0 * k)) for k in range(4)]
    g = neighbour_graph(polys)
    assert (reconcile(polys, g, {0: 100.0}, 10.0)
            == reconcile(polys, g, {0: 100.0}, 10.0))


def test_crossing_does_not_depend_on_the_chunk_size(monkeypatch):
    import bimforge.terrain.reconcile as R
    rng = np.random.default_rng(5)
    pairs = [(rng.uniform(0, 100, (40, 2)), rng.uniform(0, 100, (30, 2)))
             for _ in range(20)]
    pairs.append((np.array([[0.0, 0.0], [100.0, 100.0]]),
                  rng.uniform(0, 100, (60, 2))))          # one long segment
    want = [R._crossing(p, q) for p, q in pairs]
    assert any(w is not None for w in want)
    monkeypatch.setattr(R, "_PAIR_CHUNK", 1)
    assert [R._crossing(p, q) for p, q in pairs] == want


@pytest.mark.parametrize("chunk", [None, 7, 1])
def test_segment_pairs_match_a_full_box_scan(monkeypatch, chunk):
    import bimforge.terrain.reconcile as R
    if chunk:
        monkeypatch.setattr(R, "_PAIR_CHUNK", chunk)
    rng = np.random.default_rng(3)
    cases = [
        (rng.uniform(0, 100, (60, 2)), rng.uniform(0, 100, (40, 2))),   # tangled
        (np.column_stack([np.full(50, 5.0), np.linspace(0, 100, 50)]),  # vertical
         np.column_stack([rng.uniform(0, 10, 30), np.linspace(0, 100, 30)])),
        (np.array([[0.0, 0.0], [100.0, 100.0]]), rng.uniform(0, 100, (50, 2))),
        (rng.uniform(0, 100, (50, 2)), np.array([[0.0, 0.0], [100.0, 100.0]])),
        (hline(0.0), hline(10.0)),                                       # apart
    ]
    for p, q in cases:
        chunks = list(R._segment_pairs(p, q))
        ii = np.concatenate([c[0] for c in chunks] or [np.zeros(0, dtype=int)])
        jj = np.concatenate([c[1] for c in chunks] or [np.zeros(0, dtype=int)])
        plo = np.minimum(p[:-1], p[1:]) - R._VERTEX_FT
        phi = np.maximum(p[:-1], p[1:]) + R._VERTEX_FT
        qlo, qhi = np.minimum(q[:-1], q[1:]), np.maximum(q[:-1], q[1:])
        full = np.argwhere(((plo[:, None] <= qhi[None]) & (qlo[None] <= phi[:, None]))
                           .all(axis=-1))
        assert np.array_equal(np.column_stack([ii, jj]).reshape(-1, 2), full)


def test_reconciliation_lists_its_unreached_lines():
    g = NeighbourGraph(n=4, faces={(0, 1)}, same=set())
    rec = reconcile(None, g, {0: 20.0}, 1.0)
    assert rec.unreached == [2, 3]
    assert rec.counts()["unreached"] == 2


def test_one_label_leaves_up_or_down_open():
    # one hop from a lone 20 the line may step up, step down, or repeat 20
    # across a crest or trough; the intermediate pen rules out the repeat
    rec = reconcile(None, chain_graph(2), {0: 20.0}, 1.0)
    assert rec.lines[1].status == "ambiguous"
    assert rec.lines[1].values == [19.0, 20.0, 21.0]
    rec = reconcile(None, chain_graph(2), {0: 20.0}, 1.0,
                    roles={1: "intermediate"}, index_interval=5.0)
    assert rec.lines[1].values == [19.0, 21.0]


def test_the_index_role_pins_a_neighbour_of_a_lettered_index_line():
    roles = {1: "index", 2: "intermediate"}
    rec = reconcile(None, chain_graph(3), {0: 25.0}, 1.0, roles=roles,
                    index_interval=5.0)
    assert rec.pinned == {1: 25.0}
    assert rec.lines[2].values == [23.0, 24.0, 26.0, 27.0]
    # no index interval, no role filter
    assert reconcile(None, chain_graph(3), {0: 25.0}, 1.0,
                     roles=roles).lines[1].values == [24.0, 25.0, 26.0]


def test_a_missing_intermediate_is_a_conflict_naming_both_labels():
    # 25 and 20 need four intermediates between them; only three exist
    rec = reconcile(None, chain_graph(5), {0: 25.0, 4: 20.0}, 1.0)
    assert sorted(c["line"] for c in rec.label_conflicts) == [0, 4]
    c0 = next(c for c in rec.label_conflicts if c["line"] == 0)
    assert (c0["lo"], c0["hi"]) == (16.0, 24.0)
    assert c0["hi_from"] == (4, 4)
    assert rec.path(4, 0) == [4, 3, 2, 1, 0]
    assert [rec.lines[k].status for k in (1, 2, 3)] == ["conflict"] * 3
    assert rec.counts() == {"pinned": 0, "ambiguous": 0, "conflict": 3,
                            "unreached": 0, "label_conflicts": 2,
                            "off_interval": 0}


def test_a_same_pair_shares_its_value_at_no_hop_cost():
    g = NeighbourGraph(n=3, faces={(0, 1)}, same={(1, 2)})
    rec = reconcile(None, g, {0: 100.0}, 10.0)
    assert rec.lines[2].values == rec.lines[1].values == [90.0, 100.0, 110.0]


def test_an_off_interval_label_constrains_nothing():
    rec = reconcile(None, chain_graph(2), {0: 100.5}, 1.0)
    assert rec.off_interval == [0]
    assert rec.lines[1].status == "unreached"


def test_reconcile_needs_an_interval():
    with pytest.raises(ValueError, match="interval"):
        reconcile(None, chain_graph(2), {0: 1.0}, 0.0)


# ----------------------------------------------------------------- findings
def test_a_conflict_cluster_is_one_finding_with_its_paths():
    polys = [poly(hline(10.0 * k)) for k in range(5)]
    g, elev = chain_graph(5), {0: 25.0, 4: 20.0}
    rec = reconcile(polys, g, elev, 1.0)
    (f,) = build_findings(polys, g, elev, rec, line_ids={0: ["L001"]})
    assert (f.id, f.kind, f.lines) == ("F01", "conflict", [0, 1, 2, 3, 4])
    assert f.labels == [{"id": "L001", "elev": 25.0, "line": 0},
                        {"id": None, "elev": 20.0, "line": 4}]
    assert f.check == CHECKS["conflict"]
    assert "4(20) – 3 – 2 – 1 – 0(25): 4 hops → ≤ 24" in f.paths[0]
    assert f.xy == pytest.approx((50.0, 20.0))


def test_a_conflict_names_the_one_label_whose_removal_reconciles_it():
    polys = [poly(hline(20.0 * k)) for k in range(5)]
    g = chain_graph(5)
    elev = {0: 100.0, 1: 110.0, 2: 150.0, 3: 130.0, 4: 140.0}   # 150 misread
    rec = reconcile(polys, g, elev, 10.0)
    (f,) = build_findings(polys, g, elev, rec,
                          recheck=lambda e: reconcile(polys, g, e, 10.0))
    assert [lab["elev"] for lab in f.labels] == [100.0, 110.0, 150.0, 130.0]
    assert ("everything here reconciles without the 150 label on line 2 — "
            "check that reading first") in f.detail


def test_contacts_close_together_are_one_finding():
    g = NeighbourGraph(n=4, contacts=[
        Contact((0, 1), "cross", 1.0, (0.0, 0.0)),
        Contact((1, 2), "cross", 1.0, (10.0, 0.0)),
        Contact((2, 3), "touch", 5.0, (500.0, 0.0))])
    polys = [poly(hline(0.0)) for _ in range(4)]
    fs = build_findings(polys, g, {}, None)
    assert [(f.id, f.kind, f.lines) for f in fs] == [
        ("F01", "cross", [0, 1, 2]), ("F02", "touch", [2, 3])]
    assert fs[0].detail == "lines 0 and 1 cross; lines 1 and 2 cross"
    assert fs[1].detail == "lines 2 and 3 touch over 5 ft"
    assert fs[0].xy == pytest.approx((5.0, 0.0))


def test_label_findings_come_from_the_label_checks():
    polys = [poly(hline(0.0)), poly(hline(10.0))]
    g = chain_graph(2)
    labels = [{"elev": 100.0, "xy": (50.0, 30.0), "id": "L009"}]
    label_rows = [{"id": "L009", "elev": 100.0, "dist_ft": 20.0, "line": 1,
                   "margin_ft": 10.0, "accepted": False}]
    index_rows = [{"line": 0, "elev": 102.0, "check": "index-multiple", "id": None,
                   "detail": "102 is not a multiple of the 5 ft index interval"}]
    elev = {1: 100.5}
    rec = reconcile(polys, g, elev, 1.0)
    fs = build_findings(polys, g, elev, rec, labels=labels,
                        label_rows=label_rows, index_rows=index_rows)
    assert [f.kind for f in fs] == ["label-unmatched", "label-not-index",
                                    "label-off-interval"]
    assert [f.id for f in fs] == ["F01", "F02", "F03"]
    assert fs[0].xy == (50.0, 30.0) and "20.0 ft away" in fs[0].detail
    assert fs[0].labels == [{"id": "L009", "elev": 100.0, "line": 1}]
    assert fs[2].detail == ("lettered 100.5 is not a multiple of the 1 ft "
                            "contour interval")


def test_a_consistent_sheet_has_no_findings():
    polys = [poly(hline(10.0 * k)) for k in range(4)]
    g = neighbour_graph(polys)
    elev = {0: 100.0, 2: 120.0, 3: 130.0}
    assert build_findings(polys, g, elev, reconcile(polys, g, elev, 10.0)) == []


def test_finding_as_dict_is_plain_json():
    import json
    f = Finding("F01", "cross", [0, 1], [], (1.0, 2.0), "d", "c")
    d = json.loads(json.dumps(f.as_dict()))
    assert d["xy"] == [1.0, 2.0] and d["page"] is None and d["kind"] == "cross"


def test_finding_as_dict_turns_non_finite_xy_into_none():
    import json
    f = Finding("F01", "conflict", [0], [], (math.nan, math.nan))
    d = f.as_dict()
    assert d["xy"] is None
    json.dumps(d, allow_nan=False)      # must not raise: no NaN token anywhere


def test_label_unmatched_says_there_are_no_contour_lines():
    labels = [{"elev": 100.0, "xy": (10.0, 20.0), "id": "L001"}]
    label_rows = [{"id": "L001", "elev": 100.0, "dist_ft": None, "line": None,
                   "margin_ft": None, "accepted": False}]
    (f,) = build_findings([], NeighbourGraph(n=0), {}, None, labels=labels,
                          label_rows=label_rows)
    assert f.lines == []
    assert "there are no contour lines" in f.detail


def test_label_unmatched_says_the_line_already_carries_a_value():
    labels = [{"elev": 100.0, "xy": (5.0, 6.0), "id": "L002"}]
    label_rows = [{"id": "L002", "elev": 100.0, "dist_ft": 0.0, "line": 1,
                   "margin_ft": 0.0, "accepted": False, "conflict": 102.0}]
    (f,) = build_findings([], NeighbourGraph(n=2), {}, None, labels=labels,
                          label_rows=label_rows)
    assert f.lines == [1]
    assert "line 1 already carries 102" in f.detail


# ------------------------------------------------------- synthetic benchmark
def _terrain(x, y):
    z = 20 + 0.03 * x + 0.008 * y
    z -= 7 * np.exp(-((y - 0.25 * x - 350) / 70) ** 2)              # a valley
    z += 14 * np.exp(-((x - 720) ** 2 + (y - 200) ** 2) / 140 ** 2)  # a hill
    z += 6 * np.exp(-((x - 250) ** 2 + (y - 620) ** 2) / 90 ** 2)    # a knoll
    z += 1.5 * np.sin(x / 90) * np.cos(y / 120)                      # roughness
    return z


def _synthetic_sheet(seed, drop_frac, label_frac=0.5, step=10.0):
    """1 ft contours of a known surface drawn like CAD linework: 2 ft vertex
    spacing simplified to 0.5 ft, index labels about every 250 ft in a 10 ft
    gap, and ``drop_frac`` of the intermediates missing from the extraction."""
    contourpy = pytest.importorskip("contourpy")
    geom = pytest.importorskip("shapely.geometry")
    from bimforge.terrain.contours import merge_fragments
    rng = np.random.default_rng(seed)
    xs, ys = np.arange(0, 1000 + step, step), np.arange(0, 800 + step, step)
    Z = _terrain(*np.meshgrid(xs, ys))
    gen = contourpy.contour_generator(xs, ys, Z)
    polys, labels = [], []

    def emit(pts):
        if len(pts) >= 2:
            s = geom.LineString(pts).simplify(0.5)
            polys.append((np.asarray(s.coords, float), "synth", "C"))

    for lev in range(int(np.ceil(Z.min())), int(np.floor(Z.max())) + 1):
        for ln in gen.lines(lev):
            if len(ln) < 3:
                continue
            ls = geom.LineString(ln)
            n = max(2, int(ls.length / 2.0))
            ln = np.array([ls.interpolate(t, normalized=True).coords[0]
                           for t in np.linspace(0, 1, n)])
            if lev % 5:
                if rng.random() >= drop_frac:        # an extraction miss otherwise
                    emit(ln)
                continue
            ks = [k for k in range(len(ln) // 8, len(ln), 125)
                  if rng.random() < label_frac and 20 < k < len(ln) - 20]
            start = 0
            for k in ks:
                labels.append({"elev": float(lev), "xy": tuple(ln[k])})
                emit(ln[start:k - 2])
                start = k + 3
            emit(ln[start:])
    polys = merge_fragments(polys, 15.0, 15.0)
    truth = {i: float(np.round(np.median(_terrain(p[:, 0], p[:, 1]))))
             for i, (p, _, _) in enumerate(polys)}
    return polys, labels, truth


@pytest.mark.parametrize("drop", [0.0, 0.05, 0.10])
def test_synthetic_benchmark_assigns_nothing_wrong(drop):
    pytest.importorskip("scipy")
    from bimforge.terrain.contours import assign_lettered, propagate
    pinned_right = pinned_wrong = assigned = assigned_wrong = 0
    for seed in range(6):
        polys, labels, truth = _synthetic_sheet(seed, drop)
        elev, _ = assign_lettered(polys, labels, 6.0)
        roles = {i: "index" if truth[i] % 5 == 0 else "intermediate" for i in truth}
        g = neighbour_graph(polys)
        rec = reconcile(polys, g, elev, 1.0, roles=roles, index_interval=5.0)
        pinned_right += sum(abs(z - truth[i]) < 1e-6 for i, z in rec.pinned.items())
        pinned_wrong += sum(abs(z - truth[i]) >= 1e-6 for i, z in rec.pinned.items())
        added, _ = propagate(polys, elev, 1.0, roles=roles, index_interval=5.0,
                             reconciliation=rec)
        assigned += len(added)
        assigned_wrong += sum(abs(z - truth[i]) >= 1e-6 for i, z in added.items())
    assert assigned_wrong == 0, f"{assigned_wrong} of {assigned} assigned are wrong"
    if drop == 0.0:
        assert pinned_wrong == 0 and pinned_right >= 148, (pinned_right, pinned_wrong)


# ----------------------------------------------------------------- spot pins
def test_a_spot_pins_its_nearest_line_to_the_values_around_it():
    polys = [poly(hline(10.0 * k)) for k in range(3)]
    rec = reconcile(polys, neighbour_graph(polys), {}, 1.0,
                    spot_pins=[{"elev": 24.3, "xy": (50.0, 12.0)}])
    assert rec.pins == [{"elev": 24.3, "xy": (50.0, 12.0), "line": 1}]
    assert rec.lines[1].values == [24.0, 25.0]
    assert rec.lines[0].values == [23.0, 24.0, 25.0, 26.0]


def test_a_spot_pin_narrows_the_ranges_one_label_leaves_open():
    # one lettered 20 leaves every line up-or-down; a 24.3 spot past the far
    # end pins the whole run -- ranges only: propagate still assigns none of
    # them, having no lettered line on the far side (final review I-3)
    polys = [poly(hline(10.0 * k)) for k in range(5)]
    g = neighbour_graph(polys)
    assert reconcile(polys, g, {0: 20.0}, 1.0).pinned == {}
    rec = reconcile(polys, g, {0: 20.0}, 1.0,
                    spot_pins=[{"elev": 24.3, "xy": (50.0, 41.0)}])
    assert rec.pinned == {1: 21.0, 2: 22.0, 3: 23.0, 4: 24.0}


def test_a_label_can_conflict_with_a_spot():
    polys = [poly(hline(0.0)), poly(hline(10.0))]
    g = neighbour_graph(polys)
    rec = reconcile(polys, g, {0: 20.0}, 1.0,
                    spot_pins=[{"elev": 30.2, "xy": (50.0, 11.0)}])
    (c,) = rec.label_conflicts
    assert c["line"] == 0 and c["lo_from"][0] == ("spot", 0)
    (f,) = build_findings(polys, g, {0: 20.0}, rec)
    assert "spot 30.2 – 1 – 0(20): 1 hop → ≥ 28.2" in f.paths[0]


def test_a_spot_equidistant_from_two_lines_pins_neither():
    # 5 ft from hline(0) and 5 ft from hline(10): the argmin tie-break used to
    # pin the lower-index line arbitrarily (#245) — now it pins neither.
    polys = [poly(hline(0.0)), poly(hline(10.0))]
    rec = reconcile(polys, neighbour_graph(polys), {}, 1.0,
                    spot_pins=[{"elev": 24.3, "xy": (50.0, 5.0)}])
    assert rec.pins == []
    assert rec.spot_ties == [{"elev": 24.3, "xy": (50.0, 5.0),
                              "lines": [0, 1], "dist_ft": 5.0}]


def test_an_equidistant_spot_becomes_a_finding():
    polys = [poly(hline(0.0)), poly(hline(10.0))]
    g = neighbour_graph(polys)
    rec = reconcile(polys, g, {}, 1.0,
                    spot_pins=[{"elev": 24.3, "xy": (50.0, 5.0)}])
    (f,) = build_findings(polys, g, {}, rec)
    assert (f.kind, f.lines, f.xy) == ("spot-tie", [0, 1], (50.0, 5.0))
    assert f.check == CHECKS["spot-tie"]
    assert "it was not used as a pin" in f.detail
