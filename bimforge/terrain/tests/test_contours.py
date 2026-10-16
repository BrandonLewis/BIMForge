"""terrain/contours: contour-TIN source — tiered elevations, held-out-spot
scorecard (Work Tools/contour_surface.py port).

Delaunay-dependent tests importorskip scipy; everything else runs on the
base install (numpy only) — merge/assign/adjacency/propagate are the pure
cores the R5b design says stay offline-testable without the extra.
"""
import json
import math
import sys

import numpy as np
import pytest

from bimforge.terrain.contours import (
    ContourTIN, TinFile, assign_lettered, build_adjacency, build_tin,
    check_index_labels, find_misreads, flat_triangle_share, load_tin_npz,
    merge_fragments, propagate, sample_tin, save_tin_npz, score_against_spots,
    score_stats, tin_provenance)


def poly(pts, src="sheet A", lay="EG"):
    """A polyline record as the module defines it: (points Nx2, source, layer)."""
    return (np.asarray(pts, dtype=float), src, lay)


def hline(y, x0=0.0, x1=100.0, n=11):
    """A horizontal contour at constant northing ``y``."""
    xs = np.linspace(x0, x1, n)
    return np.column_stack([xs, np.full(n, float(y))])


# ---------------------------------------------------------- merge_fragments
def test_merge_fragments_joins_across_label_gap():
    a = poly([(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)])
    b = poly([(28.0, 0.0), (38.0, 0.0), (48.0, 0.0)])
    out = merge_fragments([a, b], gap_ft=10.0, angle_deg=15.0)
    assert len(out) == 1
    assert len(out[0][0]) == 6
    assert out[0][1:] == ("sheet A", "EG")  # record metadata survives


def test_merge_fragments_gap_gate_and_off_by_default():
    polys = [poly([(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]),
             poly([(28.0, 0.0), (38.0, 0.0), (48.0, 0.0)])]
    # gap_ft <= 0 is the documented off switch: identity, no copies.
    assert merge_fragments(polys, 0.0, 15.0) is polys
    # an 8 ft jump does not close under a 5 ft gap
    assert len(merge_fragments(polys, 5.0, 15.0)) == 2


def test_merge_fragments_refuses_sharp_turn():
    a = poly([(0.0, 0.0), (20.0, 0.0)])
    b = poly([(26.0, 6.0), (26.0, 26.0)])  # within gap but heads off at 90 deg
    out = merge_fragments([a, b], gap_ft=10.0, angle_deg=15.0)
    assert len(out) == 2


def test_merge_fragments_never_joins_across_source_or_layer():
    a = poly([(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)], lay="EG")
    b = poly([(28.0, 0.0), (38.0, 0.0), (48.0, 0.0)], lay="PG")
    out = merge_fragments([a, b], gap_ft=10.0, angle_deg=15.0)
    assert len(out) == 2


def test_merge_fragments_refuses_a_join_across_another_line():
    # Two pieces of one contour, but a line on another layer runs through the
    # gap: joining would draw a contour across it. On a real sheet a 15 ft
    # merge turned 4 raw crossings into 121 this way.
    a = poly([(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)])
    b = poly([(28.0, 0.0), (38.0, 0.0), (48.0, 0.0)])
    c = poly([(24.0, -5.0), (24.0, 5.0)], lay="PG")
    stats = {}
    out = merge_fragments([a, b, c], gap_ft=10.0, angle_deg=15.0, stats=stats)
    assert stats == {"refused": 1}
    assert sorted(len(p) for p, _, _ in out) == [2, 3, 3]


def test_merge_fragments_refuses_a_join_that_grazes_another_line():
    a = poly([(0.0, 0.0), (20.0, 0.0)])
    b = poly([(28.0, 0.0), (48.0, 0.0)])
    c = poly([(22.0, 0.3), (26.0, 0.3)], lay="PG")     # 0.3 ft off the join
    stats = {}
    assert len(merge_fragments([a, b, c], 10.0, 15.0, stats=stats)) == 3
    assert stats["refused"] == 1
    # a tighter contact distance lets the join through
    assert len(merge_fragments([a, b, c], 10.0, 15.0, contact_ft=0.2)) == 2


def test_merge_fragments_counts_nothing_when_off():
    stats = {}
    polys = [poly(hline(0.0))]
    assert merge_fragments(polys, 0.0, 15.0, stats=stats) is polys
    assert stats == {"refused": 0}


def test_merge_fragments_refuses_when_a_third_lines_endpoint_sits_on_the_join():
    # c's endpoint coincides exactly with the join point (20, 0). That must
    # not be mistaken for c being one of the two lines actually being
    # joined -- only a's and b's segments adjacent to the join are exempt.
    a = poly([(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)])
    b = poly([(28.0, 0.0), (38.0, 0.0), (48.0, 0.0)])
    c = poly([(20.0, 0.0), (20.0, -5.0)], lay="PG")
    stats = {}
    out = merge_fragments([a, b, c], gap_ft=10.0, angle_deg=15.0, stats=stats)
    assert stats == {"refused": 1}
    assert sorted(len(p) for p, _, _ in out) == [2, 3, 3]


def test_merge_fragments_refuses_a_join_that_crosses_another_join():
    # both contours are broken where they cross: each join alone clears
    # every input segment by 4 ft, but the two joins cross at (24, 0). The
    # first contour's join is made; the second's is refused.
    a1 = poly([(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)])
    a2 = poly([(28.0, 0.0), (38.0, 0.0), (48.0, 0.0)])
    b1 = poly([(24.0, -24.0), (24.0, -14.0), (24.0, -4.0)], lay="PG")
    b2 = poly([(24.0, 4.0), (24.0, 14.0), (24.0, 24.0)], lay="PG")
    stats = {}
    out = merge_fragments([a1, a2, b1, b2], gap_ft=10.0, angle_deg=15.0,
                          stats=stats)
    assert stats == {"refused": 1}
    assert sorted(len(p) for p, _, _ in out) == [3, 3, 6]


def test_merge_fragments_refuses_a_join_lying_exactly_on_a_third_line():
    # c's one segment IS the join (20, 0) - (28, 0). Only a's and b's own
    # segments are exempt from the check; a third line's identical segment
    # is not.
    a = poly([(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)])
    b = poly([(28.0, 0.0), (38.0, 0.0), (48.0, 0.0)])
    c = poly([(20.0, 0.0), (28.0, 0.0)], lay="PG")
    stats = {}
    out = merge_fragments([a, b, c], gap_ft=10.0, angle_deg=15.0, stats=stats)
    assert stats == {"refused": 1}
    assert sorted(len(p) for p, _, _ in out) == [2, 3, 3]


# ---------------------------------------------------------- assign_lettered
def test_assign_lettered_nearest_within_gate():
    polys = [poly(hline(0.0)), poly(hline(10.0))]
    labels = [{"elev": 100.0, "xy": (50.0, 1.0)},
              {"elev": 110.0, "xy": (50.0, 9.0)}]
    elev, rows = assign_lettered(polys, labels, max_dist=6.0)
    assert elev == {0: 100.0, 1: 110.0}
    assert all(r["accepted"] for r in rows)
    assert rows[0]["line"] == 0
    assert rows[0]["dist_ft"] == pytest.approx(1.0)
    assert rows[0]["margin_ft"] == pytest.approx(8.0)


def test_assign_lettered_measures_to_segments_not_vertices():
    # Sparse linework: line 0 is one 100 ft two-vertex run, line 1 a short
    # stub whose vertices sit near the label. By vertex distance the label
    # (1 ft off line 0's run) would go to the stub (2.8 ft); by segment
    # distance it is 1 ft from line 0 and 2 ft from the stub.
    polys = [poly([(0.0, 0.0), (100.0, 0.0)]),
             poly([(48.0, 3.0), (52.0, 3.0)])]
    elev, rows = assign_lettered(
        polys, [{"elev": 100.0, "xy": (50.0, 1.0), "id": "L001"}], 6.0)
    assert elev == {0: 100.0}
    assert rows[0]["line"] == 0 and rows[0]["id"] == "L001"
    assert rows[0]["dist_ft"] == pytest.approx(1.0)
    assert rows[0]["margin_ft"] == pytest.approx(1.0)


def test_assign_lettered_accepts_a_label_mid_run_on_a_two_vertex_line():
    # 50 ft from either vertex, 0.5 ft from the line itself: accepted.
    elev, rows = assign_lettered([poly([(0.0, 0.0), (100.0, 0.0)])],
                                 [{"elev": 7.0, "xy": (50.0, 0.5)}], 6.0)
    assert elev == {0: 7.0} and rows[0]["id"] is None
    assert rows[0]["dist_ft"] == pytest.approx(0.5)


def test_assign_lettered_single_vertex_polyline_still_has_a_distance():
    elev, rows = assign_lettered([poly([(0.0, 0.0)]), poly(hline(10.0))],
                                 [{"elev": 1.0, "xy": (0.0, 1.0)}], 6.0)
    assert elev == {0: 1.0}
    assert rows[0]["dist_ft"] == pytest.approx(1.0)
    assert rows[0]["margin_ft"] == pytest.approx(8.0)


def test_assign_lettered_far_label_reported_never_silently_dropped():
    polys = [poly(hline(0.0))]
    labels = [{"elev": 100.0, "xy": (50.0, 30.0)}]
    elev, rows = assign_lettered(polys, labels, max_dist=6.0)
    assert elev == {}
    assert len(rows) == 1 and rows[0]["accepted"] is False


def test_assign_lettered_conflicting_label_rejected():
    polys = [poly(hline(0.0))]
    labels = [{"elev": 100.0, "xy": (30.0, 1.0)},
              {"elev": 102.0, "xy": (70.0, 1.0)}]
    elev, rows = assign_lettered(polys, labels, max_dist=6.0)
    assert elev == {0: 100.0}
    assert rows[1]["accepted"] is False
    assert rows[1]["conflict"] == 100.0


# ---------------------------------------------------------- build_adjacency
def test_build_adjacency_neighbours_only():
    polys = [poly(hline(0.0)), poly(hline(10.0)), poly(hline(20.0))]
    adj = build_adjacency(polys)
    assert (0, 1) in adj and (1, 2) in adj
    assert (0, 2) not in adj  # a contour lies between them


def test_build_adjacency_min_votes_gate():
    polys = [poly(hline(0.0)), poly(hline(10.0))]
    assert build_adjacency(polys, min_votes=1000) == set()


def test_build_adjacency_single_contour_is_empty():
    assert build_adjacency([poly(hline(0.0))]) == set()


# ----------------------------------------------------------------- propagate
def test_propagate_infers_middle_contour():
    # Parallel contours on a 10-ft interval; the second one is unlabelled and
    # sits on a hop-path between lettered 100 and 120.
    polys = [poly(hline(0.0)), poly(hline(10.0)),
             poly(hline(20.0)), poly(hline(30.0))]
    elev = {0: 100.0, 2: 120.0, 3: 130.0}
    added, rows = propagate(polys, elev, interval=10.0)
    assert added == {1: 110.0}
    (row,) = rows
    assert row["line"] == 1
    assert row["accepted"] is True
    assert row["tier"] == "inferred"
    assert row["between"] == (100.0, 120.0)
    # the lettered dict is the caller's; propagate must not mutate it
    assert elev == {0: 100.0, 2: 120.0, 3: 130.0}


def test_propagate_checks_against_the_local_bracket_not_a_sheet_plane():
    # Two slopes facing opposite ways (#235): west rises 100 -> 130 going
    # north, east falls 190 -> 160. No single plane fits both — a sheet-wide
    # trend sits at ~115 across the west slope and rejected its 110 and 120
    # — but each unlabelled contour sits exactly where the two lettered
    # contours bracketing it say it should.
    west = [poly(hline(y)) for y in (0.0, 10.0, 20.0, 30.0)]
    east = [poly(hline(y, 1000.0, 1100.0)) for y in (0.0, 10.0, 20.0, 30.0)]
    elev = {0: 100.0, 3: 130.0, 4: 190.0, 7: 160.0}
    added, rows = propagate(west + east, elev, interval=10.0)
    assert added == {1: 110.0, 2: 120.0, 5: 180.0, 6: 170.0}
    by_line = {r["line"]: r for r in rows}
    assert by_line[1]["between"] == (100.0, 130.0)
    assert by_line[1]["trend"] == pytest.approx(110.0)


def test_propagate_snap_tol_rejects_not_guesses():
    # The unlabelled contour sits at y=4 between lettered 100 (y=0) and 120
    # (y=20): hop counting alone would happily call it 110, but
    # interpolating between those two lettered contours says 104 — beyond
    # snap_tol, so it must be REJECTED, not guessed (an off-by-one-interval
    # contour is a silent error over its whole length).
    polys = [poly(hline(0.0)), poly(hline(4.0)), poly(hline(20.0))]
    elev = {0: 100.0, 2: 120.0}
    added, rows = propagate(polys, elev, interval=10.0)
    assert added == {}
    (row,) = rows
    assert row["accepted"] is False
    assert row["tier"] is None
    assert row["reason"] == "snap-tol"
    # snap_tol is the caller's dial: open it wide and the hop count stands
    added_loose, _ = propagate(polys, elev, interval=10.0, snap_tol=7.0)
    assert added_loose == {1: 110.0}


def test_propagate_honours_layer_roles():
    # Eleven parallel contours on a 1 ft interval, lettered 20 and 30. The
    # role filters the range itself: an index-role line must land on a
    # multiple of the index interval and an intermediate-role line must not,
    # so the index line whose only value is 23, and the intermediate line
    # whose only value is 25, have empty ranges — conflict. A line with no
    # role is not filtered.
    polys = [poly(hline(10.0 * k)) for k in range(11)]
    elev = {0: 20.0, 10: 30.0}
    roles = {3: "index", 5: "intermediate", 2: "intermediate", 10: "index"}
    added, rows = propagate(polys, elev, interval=1.0, roles=roles,
                            index_interval=5.0)
    assert added == {k: 20.0 + k for k in (1, 2, 4, 6, 7, 8, 9)}
    by_line = {r["line"]: r for r in rows}
    assert by_line[3]["reason"] == by_line[5]["reason"] == "conflict"
    assert by_line[3]["range"] == (23.0, 23.0) and not by_line[3]["accepted"]
    # no index interval, no role filter
    added, _ = propagate(polys, elev, interval=1.0, roles=roles)
    assert sorted(added) == [1, 2, 3, 4, 5, 6, 7, 8, 9]


def test_propagate_beyond_the_outermost_label_is_ambiguous():
    # A contour past the last lettered one can be the next interval or the
    # same one again across a crest: ambiguous, never guessed.
    polys = [poly(hline(0.0)), poly(hline(10.0)), poly(hline(20.0))]
    added, rows = propagate(polys, {0: 100.0, 1: 110.0}, interval=10.0)
    assert added == {}
    (row,) = rows
    assert row["line"] == 2 and row["accepted"] is False
    assert row["reason"] == "ambiguous"
    assert row["values"] == [100.0, 110.0, 120.0]


def test_propagate_unreached_is_no_hop_path():
    polys = [poly(hline(0.0)), poly(hline(10.0)),
             poly(hline(0.0, 1000.0, 1100.0))]
    added, rows = propagate(polys, {0: 100.0}, interval=10.0)
    by_line = {r["line"]: r for r in rows}
    assert by_line[2]["reason"] == "no-hop-path" and by_line[2]["range"] is None


def test_propagate_rejects_a_pin_whose_bracket_hop_counts_disagree():
    # Seven parallel lines, lettered only at the ends (20 and 25, 5 apart
    # over 6 hops -- a dropped intermediate elsewhere on a real sheet looks
    # just like this locally). Line 1 is one hop from the 20 and five hops
    # from the 25; the intermediate role rules out the repeated 20, pinning
    # it to 21 -- but the only bracket pair's hops (1, 5) sum to 6, one more
    # than the 5 ft span, so 25 - 21 = 4 does not match the 5-hop side. The
    # interpolated trend (~20.83) is well within snap_tol, so only the new
    # hop-count gate catches this.
    polys = [poly(hline(10.0 * k)) for k in range(7)]
    added, rows = propagate(polys, {0: 20.0, 6: 25.0}, interval=1.0,
                            roles={1: "intermediate"}, index_interval=5.0)
    by_line = {r["line"]: r for r in rows}
    row = by_line[1]
    assert row["hops"] == (1, 5)
    assert row["reason"] == "hop-count"
    assert not row["accepted"]
    assert 21.0 not in added.values()


def test_propagate_pinned_without_a_bracket_is_not_assigned():
    # The index role pins the neighbour of a lettered 25 to 25 (a crest or
    # trough between them), but no lettered value lies on the other side of
    # it, so the local check has nothing to interpolate: reported, not used.
    polys = [poly(hline(0.0)), poly(hline(10.0))]
    added, rows = propagate(polys, {0: 25.0}, interval=1.0,
                            roles={1: "index"}, index_interval=5.0)
    assert added == {}
    (row,) = rows
    assert (row["reason"], row["elev"]) == ("no-bracket", 25.0)


def test_propagate_uses_a_given_reconciliation(monkeypatch):
    from bimforge.terrain import reconcile as rmod
    polys = [poly(hline(0.0)), poly(hline(10.0)), poly(hline(20.0))]
    elev = {0: 100.0, 2: 120.0}
    rec = rmod.reconcile(polys, rmod.neighbour_graph(polys), elev, 10.0)

    def boom(*a, **k):
        raise AssertionError("propagate rebuilt the graph")

    monkeypatch.setattr(rmod, "neighbour_graph", boom)
    added, _ = propagate(polys, elev, 10.0, reconciliation=rec)
    assert added == {1: 110.0}


def test_propagate_no_adjacency_returns_empty():
    added, rows = propagate([poly(hline(0.0))], {0: 100.0}, interval=10.0)
    assert added == {} and rows == []


# ------------------------------------------------------------- label checks
def test_check_index_labels_drops_values_off_the_index_interval():
    kept, rows = check_index_labels({0: 100.0, 1: 112.0, 2: 115.0},
                                    index_lines={1, 2}, index_interval=5.0)
    assert kept == {0: 100.0, 2: 115.0}
    assert [(r["line"], r["check"]) for r in rows] == [(1, "index-multiple")]


def test_check_index_labels_is_off_without_an_index_interval():
    elev = {0: 101.0}
    assert check_index_labels(elev, {0}, None) == (elev, [])


def test_find_misreads_flags_one_value_its_neighbours_contradict():
    polys = [poly(hline(y)) for y in (0.0, 20.0, 40.0, 60.0, 80.0)]
    elev = {0: 100.0, 1: 110.0, 2: 150.0, 3: 130.0, 4: 140.0}   # 2 misread
    rows = find_misreads(polys, elev, 10.0)
    assert [(r["line"], r["check"]) for r in rows] == [(2, "likely-misread")]


def test_find_misreads_detail_carries_the_label_match_margin():
    polys = [poly(hline(y)) for y in (0.0, 20.0, 40.0, 60.0, 80.0)]
    elev = {0: 100.0, 1: 110.0, 2: 150.0, 3: 130.0, 4: 140.0}
    (row,) = find_misreads(polys, elev, 10.0, margins={2: 0.27})
    assert row["check"] == "likely-misread"
    assert "0.27 ft margin" in row["detail"]


# Seven parallel lines y = 0, 20, ... 120 (a hop chain); lines 1 and 5 are
# unlabelled. Line 3 = 170 disagrees with its 1-hop neighbours 120 and 140,
# which agree with each other (2 hops, 20 ft) — the flag rule fires. But the
# other lettered pairs contradict their own hop counts: of (0,2) (0,4) (0,6)
# (2,4) (2,6) (4,6) only (2,4) agrees, 1/6. Hand-checked: lines 0, 2, 4, 6
# each escape the rule (0 and 6: their disagreeing neighbours disagree with
# each other; 2 and 4: a 2-hop neighbour agrees).
_UNFAITHFUL = {0: 200.0, 2: 120.0, 3: 170.0, 4: 140.0, 6: 200.0}


def _chain(n=7):
    return [poly(hline(20.0 * k)) for k in range(n)]


def test_find_misreads_keeps_a_value_the_hop_graph_cannot_judge():
    rows = find_misreads(_chain(), _UNFAITHFUL, 10.0)
    assert [(r["line"], r["check"]) for r in rows] == [(3, "unverified-misread")]
    assert "agree for only 1/6" in rows[0]["detail"]
    assert rows[0]["detail"].endswith("— kept")


def test_find_misreads_min_agreement_zero_is_the_ungated_rule():
    rows = find_misreads(_chain(), _UNFAITHFUL, 10.0, min_agreement=0.0)
    assert [(r["line"], r["check"]) for r in rows] == [(3, "likely-misread")]


def test_find_misreads_spares_a_correct_label_beside_a_ridge():
    # 100/110/120/110/100 over a hop chain: a ridge at line 2. Hand check,
    # line 0 (100): lines 3 (110, 3 hops) and 4 (100, 4 hops) disagree with
    # it and agree with each other (1 hop, 10 ft) — the bare rule would flag
    # it — but lines 1 and 2 agree with it within two hops (close_ok), which
    # is what spares it. Line 1 likewise (0 and 2 agree at 1 hop); line 2
    # agrees with everything; 3 and 4 mirror 1 and 0.
    polys = [poly(hline(y)) for y in (0.0, 20.0, 40.0, 60.0, 80.0)]
    elev = {0: 100.0, 1: 110.0, 2: 120.0, 3: 110.0, 4: 100.0}
    assert find_misreads(polys, elev, 10.0) == []


def test_find_misreads_is_quiet_on_a_consistent_set():
    polys = [poly(hline(y)) for y in (0.0, 20.0, 40.0, 60.0)]
    assert find_misreads(polys, {0: 100.0, 1: 110.0, 2: 120.0, 3: 130.0},
                         10.0) == []


def test_find_misreads_needs_three_labels_and_an_interval():
    polys = [poly(hline(y)) for y in (0.0, 20.0)]
    assert find_misreads(polys, {0: 100.0, 1: 150.0}, 10.0) == []
    assert find_misreads([poly(hline(y)) for y in (0.0, 20.0, 40.0)],
                         {0: 1.0, 1: 2.0, 2: 9.0}, None) == []


# ------------------------------------------------------------------ build_tin
def test_build_tin_without_scipy_raises_actionable(monkeypatch):
    monkeypatch.setitem(sys.modules, "scipy", None)
    monkeypatch.setitem(sys.modules, "scipy.spatial", None)
    pts = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    with pytest.raises(RuntimeError, match=r"bimforge\[terrain\]"):
        build_tin(pts, max_edge=10.0)


def _plane_points(z_fn, lo=0.0, hi=10.0, step=2.0):
    xs = np.arange(lo, hi + step / 2, step)
    pts = [(x, y, z_fn(x, y)) for x in xs for y in xs]
    return np.asarray(pts, dtype=float)


def test_build_tin_and_sample_recover_planar_z():
    pytest.importorskip("scipy")
    P = _plane_points(lambda x, y: 2.0 * x + 3.0 * y + 5.0)
    tin = build_tin(P, max_edge=5.0)
    assert isinstance(tin, ContourTIN)
    assert tin.dropped == 0
    q = np.array([[3.3, 4.7], [1.1, 8.9], [9.0, 0.5]])
    z = sample_tin(tin, q)
    for (x, y), got in zip(q, z):
        assert got == pytest.approx(2.0 * x + 3.0 * y + 5.0, abs=1e-9)
    # outside the hull the surface refuses to answer
    assert np.isnan(sample_tin(tin, np.array([[50.0, 50.0]]))[0])


def test_build_tin_max_edge_drops_void_spanning_triangles():
    pytest.importorskip("scipy")
    near = _plane_points(lambda x, y: 1.0, lo=0.0, hi=4.0, step=2.0)
    far = _plane_points(lambda x, y: 1.0, lo=20.0, hi=24.0, step=2.0)
    tin = build_tin(np.vstack([near, far]), max_edge=6.0)
    assert tin.dropped > 0
    # a query over the void samples NaN even though Delaunay's hull covers it
    assert np.isnan(sample_tin(tin, np.array([[12.0, 2.0]]))[0])


# ------------------------------------------------------------------ scorecard
def test_score_stats_known_residuals():
    st = score_stats([0.3, -0.4, None, 0.0])
    assert st["n"] == 3
    assert st["mean"] == pytest.approx(-0.1 / 3)
    assert st["mae"] == pytest.approx(0.7 / 3)
    assert st["rmse"] == pytest.approx(math.sqrt(0.25 / 3))
    assert st["max_abs"] == pytest.approx(0.4)


def test_score_stats_empty_is_honest():
    st = score_stats([])
    assert st == {"n": 0, "mean": None, "mae": None, "rmse": None,
                  "max_abs": None}


def test_score_against_spots_residuals_and_rmse():
    pytest.importorskip("scipy")
    tin = build_tin(_plane_points(lambda x, y: x), max_edge=5.0)
    spots = [{"elev": 3.5, "xy": (3.0, 3.0)},    # TIN says 3.0 -> err -0.5
             {"elev": 4.5, "xy": (5.0, 5.0)},    # TIN says 5.0 -> err +0.5
             {"elev": 99.0, "xy": (100.0, 100.0)}]  # outside the TIN
    got = score_against_spots(tin, spots)
    rows = got["rows"]
    assert rows[0]["err"] == pytest.approx(-0.5)
    assert rows[1]["err"] == pytest.approx(0.5)
    assert rows[2]["tin"] is None and rows[2]["err"] is None
    st = got["stats"]
    assert st["n"] == 2
    assert st["mean"] == pytest.approx(0.0)
    assert st["rmse"] == pytest.approx(0.5)


def test_score_against_spots_no_spots():
    # No spots is a legal (if regrettable) state — an empty scorecard, not
    # a crash; the TIN is never consulted.
    got = score_against_spots(None, [])
    assert got["rows"] == []
    assert got["stats"]["n"] == 0


# ------------------------------------------------------------- tin_provenance
def test_tin_provenance_carries_tiers_and_scorecard():
    prov = tin_provenance({"lettered": 12, "inferred": 3}, rmse=0.41,
                          spacing_note="contour vertices thinned to 8 ft")
    assert prov["Source"] == "plan-sheet contours"
    assert prov["SurveyGrade"] is False
    assert prov["SpotRMSE"] == pytest.approx(0.41)
    assert "lettered 12" in prov["ElevationTiers"]
    assert "inferred 3" in prov["ElevationTiers"]
    assert prov["MeshSpacing"] == "contour vertices thinned to 8 ft"


def test_tin_provenance_unscored_says_so():
    prov = tin_provenance({"lettered": 2, "inferred": 0}, rmse=None,
                          spacing_note="")
    assert prov["SpotRMSE"] == "unscored (no spot scored)"


def test_build_adjacency_dense_contours_beyond_k_still_vote():
    # Two dense clustered contours (>48 vertices each) far apart: every
    # vertex's 48 nearest neighbours are its own contour, so the capped
    # KD-tree query alone casts no votes — the per-vertex fallback must
    # still find the nearest other contour (Copilot, PR #125).
    pytest.importorskip("scipy")
    rng = [i * 0.001 for i in range(60)]
    a = poly([(x, 0.0) for x in rng])
    b = poly([(x, 10.0) for x in rng])
    adj = build_adjacency([a, b], min_votes=2)
    assert (0, 1) in adj


# ------------------------------------------------------- flat share + TinFile
def test_flat_triangle_share_is_area_weighted():
    pts = np.array([[0, 0, 10], [10, 0, 10], [20, 5, 10], [10, 20, 11]], float)
    simp = np.array([[0, 1, 2], [0, 2, 3]])
    # triangle 0 (area 25) has all three vertices on contour 0; triangle 1
    # (area 175) spans two contours -> 25 / 200
    assert flat_triangle_share(pts, simp, [0, 0, 0, 1]) == pytest.approx(0.125)


def test_flat_triangle_share_empty_tin_is_zero():
    assert flat_triangle_share(np.zeros((0, 3)), np.zeros((0, 3), int), []) == 0.0


def _lines():
    return [{"points": np.array([[0.0, 0.0], [10.0, 0.0]]), "elev": 100.0,
             "tier": "lettered", "role": "index", "source": "sheet 1 / EXIST"},
            {"points": np.array([[0.0, 20.0], [5.0, 20.0], [10.0, 20.0]]),
             "elev": 110.0, "tier": "inferred", "role": None,
             "source": "sheet 1 / EXIST"}]


def test_tin_npz_round_trip(tmp_path):
    pts = np.array([[0, 0, 100], [10, 0, 100], [5, 20, 110]], float)
    out = save_tin_npz(tmp_path / "t", pts, [[0, 1, 2]], {"surface": "existing"},
                       _lines(), [0, 0, 1])
    assert out.endswith(".npz")
    t = load_tin_npz(out)
    assert isinstance(t, TinFile)
    assert t.info["npz_version"] == 2 and t.info["surface"] == "existing"
    assert t.info["sources"] == ["sheet 1 / EXIST", "sheet 1 / EXIST"]
    assert [(ln["elev"], ln["tier"], ln["role"]) for ln in t.lines] == [
        (100.0, "lettered", "index"), (110.0, "inferred", None)]
    np.testing.assert_allclose(t.lines[1]["points"], _lines()[1]["points"])
    assert t.point_line.tolist() == [0, 0, 1]


def test_load_tin_npz_reads_a_v1_file(tmp_path):
    p = tmp_path / "v1.npz"
    np.savez_compressed(p, points=np.zeros((3, 3)), simplices=np.array([[0, 1, 2]]),
                        info=json.dumps({"tiers": {"lettered": 1}}))
    t = load_tin_npz(p)
    assert t.lines == [] and t.point_line is None
    assert t.info["tiers"] == {"lettered": 1}
