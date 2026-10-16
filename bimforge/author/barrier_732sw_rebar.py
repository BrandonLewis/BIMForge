"""Type 732SW reinforcement: weight-only straight bars for the LB pay quantity
and the BBS. Two kinds -- continuous LONGITUDINAL bars (one straight bar per
count, length = run length) and transverse VERTICAL/mat bars at a spacing
(length = a documented developed length). Weight = length x plf (BAR_PROPS),
matching the barrier_rebar / wingwall_rebar precedent; 3D bent solids and exact
hook/lap lengths are a follow-on (estimate-level, per estimator direction 2026-08-25).
"""
from __future__ import annotations

from bimforge.author.primitives import RebarBuilder, bar_stations


def barrier_732sw_bars(run_length_ft: float, groups: list,
                       cover_in: float = 2.0) -> list:
    """Straight weight-only bars for one 732SW run of `run_length_ft` ft.

    `groups` is a list of dicts:
      {mark, size, kind: "long"}                      -> `count` continuous bars
      {mark, size, kind: "vert", spacing_in, length_ft} -> bars every spacing
    """
    out: list = []
    for g in groups:
        rb = RebarBuilder(size=int(g["size"]), cover_in=cover_in,
                          spacing_in=float(g.get("spacing_in", 12.0)))
        mark, host = g["mark"], f"732sw {g['mark']}"
        kind = g["kind"]
        if kind == "long":
            for _ in range(int(g["count"])):
                rb.bar(mark, host, [(0.0, 0.0, 0.0),
                                    (0.0, 0.0, float(run_length_ft))], "straight")
        elif kind == "vert":
            length = float(g["length_ft"])
            sp_ft = float(g["spacing_in"]) / 12.0
            for _ in bar_stations(0.0, float(run_length_ft), sp_ft):
                rb.bar(mark, host, [(0.0, 0.0, 0.0),
                                    (0.0, length, 0.0)], "straight")
        else:
            raise ValueError(f"unknown bar kind {kind!r} for mark {mark!r}")
        out += rb.bars
    return out
