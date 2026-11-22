"""Guardrail for the road corridor (V1.1): MGS where a steep fill is
guarded, laid out by its length of need.

A guarded station is a 2:1 fill (section.Side.guarded); consecutive guarded
stations on a side are one span. Each span is extended by its length of
need for each direction of travel (TSSM length-of-need calculator, a
parallel rail with in-line terminals): X = (LH - L) / (LH / LR), LH the
20 ft clear-zone edge (HDM Index 309.1), L the rail face's offset (from the
edge of traveled way for the lane beside the rail, from the centreline for
the opposing lane), LR the runout length by design speed, each X rounded up
to whole 12.5 ft rail elements. The extended run stops on a Type AGT
transition at a structure gap and ties into a wall; runs closer than a
terminal's length join; a run with a terminal is whole elements and 150 ft
at least (TSSM 3.6(1)), the extra at its terminal ends.

The rail face stands at the shoulder edge; the body is the W-beam band,
31 in to the top of rail (A77N3), swept along the alignment. Posts are
counted at 6'-3", not modelled: 6 ft posts where the run shields a guarded
span (behind the widening, A77N3 Detail A), 8 ft W6 posts elsewhere (no
widening, A77N3 Detail B).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from bimforge.author.corridor.params import RUNOUT_FT

#: the clear-zone edge on a conventional highway, feet (HDM Index 309.1)
CLEAR_ZONE_FT = 20.0
#: one W-beam rail element, feet
ELEMENT_FT = 12.5
#: the shortest guardrail installation, feet (TSSM 3.6(1))
MIN_RUN_FT = 150.0
#: an in-line terminal's length: runs closer than this join, feet
TERMINAL_FT = 50.0
#: MGS post spacing, 6'-3" (A77N3)
POST_SPACING_FT = 6.25
#: top of rail above the shoulder edge, 31 in (A77N3)
RAIL_TOP_FT = 31.0 / 12.0
#: the W-beam's height, 12 1/4 in, and depth, 3 1/4 in
W_BEAM_HEIGHT_FT = 12.25 / 12.0
W_BEAM_DEPTH_FT = 3.25 / 12.0
#: how far the shoulder edge may move under one run's constant rail, feet
EDGE_TOL_FT = 0.01
#: the IfcRailingType name (the dictionary class road-corridor-guardrail)
TYPE_NAME = "Midwest guardrail system"
TERMINAL, AGT, WALL = "TERMINAL", "AGT", "WALL"
HEADER = ("side,start,end,length_ft,start_treatment,end_treatment,posts,"
          "posts_6ft,posts_8ft")
_EPS = 1e-9


@dataclass(frozen=True)
class RailRun:
    side: str
    start: float
    end: float
    start_end: str          # TERMINAL, AGT or WALL
    end_end: str
    #: the guarded spans [(s0, s1)] the run shields: 6 ft posts there
    guarded: tuple = ()

    @property
    def length(self) -> float:
        return self.end - self.start

    @property
    def posts(self) -> int:
        return math.floor(self.length / POST_SPACING_FT + _EPS) + 1

    @property
    def posts_6ft(self) -> int:
        """Posts (every POST_SPACING_FT from the start) within a guarded
        span: 6 ft posts behind the widening (A77N3 Detail A)."""
        return sum(1 for i in range(self.posts)
                   if any(a - _EPS <= self.start + i * POST_SPACING_FT <= b + _EPS
                          for a, b in self.guarded))

    @property
    def posts_8ft(self) -> int:
        """The other posts: 8 ft W6 posts with no widening behind them
        (A77N3 Detail B)."""
        return self.posts - self.posts_6ft

    @property
    def terminals(self) -> int:
        return [self.start_end, self.end_end].count(TERMINAL)

    @property
    def agts(self) -> int:
        return [self.start_end, self.end_end].count(AGT)


def round_up(x: float, step: float = ELEMENT_FT) -> float:
    """`x` up to whole rail elements."""
    return math.ceil(x / step - _EPS) * step


def need(offset: float, speed_mph: int, lh: float = CLEAR_ZONE_FT,
         y: float = 0.0) -> float:
    """The length of need X = (LH - L - Y) / (LH / LR) for a rail face
    `offset` ft out (L), rounded up to whole elements; 0 beyond LH.

    By hand, 12 ft lanes and the face at a 5 ft shoulder's edge: own lane
    L2 = 5, at 45 mph (20 - 5) / (20 / 195) = 15 x 9.75 = 146.25 ft, 11.7
    elements, so 12: 150 ft; at 50 mph 15 x 11.5 = 172.5, so 14: 175 ft.
    Opposing lane L = 12 + 5 = 17 from the centreline: (20 - 17) x 9.75 =
    29.25 and 3 x 11.5 = 34.5, both 3 elements: 37.5 ft. The 150 ft
    minimum is the run's, not each X's (`_whole`)."""
    x =(lh - offset - y) / (lh / RUNOUT_FT[speed_mph])
    return round_up(x) if x > 0.0 else 0.0


def spans(stations: list, flags: list) -> list:
    """[(first, last)]: the runs of consecutive stations whose flag is set."""
    out, start = [], None
    for s, flag in zip(stations, flags):
        if flag and start is None:
            start = s
        if flag:
            last = s
        if not flag and start is not None:
            out.append((start, last))
            start = None
    if start is not None:
        out.append((start, last))
    return out


def _clamped(side: str, start: float, end: float, lo: tuple, hi: tuple,
             guarded: tuple) -> RailRun:
    """A run cut back to its limits (station, treatment) at either end."""
    s_kind = e_kind = TERMINAL
    if start <= lo[0] + _EPS:
        start, s_kind = lo
    if end >= hi[0] - _EPS:
        end, e_kind = hi
    return RailRun(side, start, end, s_kind, e_kind, guarded)


def lay_out(side: str, guarded: list, l2: float, lc: float, speed_mph: int,
            lower: tuple, upper: tuple, walls=()) -> list:
    """The rail runs on `side` for its `guarded` spans [(s0, s1)], the rail
    face `l2` ft from the edge of traveled way and `lc` ft from the
    centreline. `lower` and `upper` are the corridor run's ends, (station,
    AGT at a structure gap or TERMINAL at the alignment's end); `walls`
    [(start, end)] are the side's walls, which a run ties into."""
    near = need(l2, speed_mph)            # the lane beside the rail
    far = need(lc, speed_mph)             # the opposing lane
    up, down = (near, far) if side == "R" else (far, near)
    runs = []
    for a, b in guarded:
        lo = max([lower] + [(e, WALL) for _s, e in walls if e <= a + _EPS],
                 key=lambda t: t[0])
        hi = min([upper] + [(s, WALL) for s, _e in walls if s >= b - _EPS],
                 key=lambda t: t[0])
        runs.append((_clamped(side, a - up, b + down, lo, hi, ((a, b),)), lo, hi))
    merged = []
    for run, lo, hi in runs:
        if merged:
            prev, plo, _phi = merged[-1]
            if (prev.end_end == TERMINAL and run.start_end == TERMINAL
                    and run.start - prev.end < TERMINAL_FT):
                merged[-1] = (RailRun(side, prev.start, max(prev.end, run.end),
                                      prev.start_end, run.end_end,
                                      prev.guarded + run.guarded), plo, hi)
                continue
        merged.append((run, lo, hi))
    return [_whole(run, lo, hi) for run, lo, hi in merged]


def _whole(run: RailRun, lo: tuple, hi: tuple) -> RailRun:
    """`run` made whole elements and MIN_RUN_FT at least: the extra split
    evenly between its two ends where both are free terminals, all at the
    free one where the other is fixed (an AGT, a wall, or a terminal at the
    alignment's end); then cut back to its limits."""
    free = (run.start_end == TERMINAL and run.start > lo[0] + _EPS,
            run.end_end == TERMINAL and run.end < hi[0] - _EPS)
    extra = max(MIN_RUN_FT, round_up(run.length)) - run.length
    if extra <= _EPS or not any(free):
        return run
    start, end = run.start, run.end
    if all(free):
        start, end = start - extra / 2.0, end + extra / 2.0
    elif free[0]:
        start -= extra
    else:
        end += extra
    return _clamped(run.side, start, end, lo, hi, run.guarded)


def band(side: str, face_u: float) -> list:
    """The W-beam band's (x, z) section for SweptSection: from the rail face
    at offset `face_u` (u, left positive) outward, top of rail RAIL_TOP_FT
    above the shoulder edge."""
    sign = 1.0 if side == "L" else -1.0
    x0, x1 = face_u, face_u + sign * W_BEAM_DEPTH_FT
    z0, z1 = RAIL_TOP_FT - W_BEAM_HEIGHT_FT, RAIL_TOP_FT
    return [(x0, z0), (x1, z0), (x1, z1), (x0, z1)]


def to_csv(runs: list) -> str:
    return "\n".join([HEADER] + [
        f"{r.side},{r.start:.2f},{r.end:.2f},{r.length:.2f},"
        f"{r.start_end},{r.end_end},{r.posts},{r.posts_6ft},{r.posts_8ft}"
        for r in runs]) + "\n"
