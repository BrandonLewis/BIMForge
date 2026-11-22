"""Guardrail for the road corridor (V1.1): MGS where a steep fill is
guarded and at each bridge rail end, laid out by its length of need.

A guarded station is a 2:1 fill (section.Side.guarded); consecutive guarded
stations on a side are one span. Each span is extended by its length of
need for each direction of travel (TSSM length-of-need calculator, a
parallel rail with in-line terminals): X = (LH - L - Y) / (LH / LR), LH the
20 ft clear-zone edge (HDM Index 309.1), L the rail face's offset (L2 from
the edge of traveled way for the lane beside the rail, from the centreline
for the opposing lane, TSSM Figure 5b), Y = 0, LR the runout length by
design speed, each X rounded up to whole 12.5 ft rail elements. On a
two-lane road a right-side rail's own lane runs up-station, so its X
extends the span's start and the opposing lane's its end; a left-side rail
is the mirror. Where an X is 0 (the rail face beyond LH for that direction)
the end is a Type SFT-M anchor (TSSM 3.6(10)(b)), not a terminal.

With `bridge_rail`, each bridge rail end (a structure gap's end) is a hazard
too: a run from it, starting on a Type AGT transition, extended outward by
the X of the traffic heading toward the bridge (TSSM 3.6(2)).

A run stops on a Type AGT transition at a structure gap and ties into a
wall, also with a Type AGT (TSSM 3.6(10)(c); counted in `agts`, its end
marked WALL). Runs 200 ft or less apart join (TSSM 3.6(11): avoid such
gaps), never across a wall or a structure gap. A wall over a guarded span
is refused. Between its length-of-need points a run is whole elements and
150 ft at least (TSSM 3.6(1)), the extra split evenly between its ends, or
all at one end when the other is fixed (an AGT, a wall, or the alignment's
end); a run held at both ends short of 150 ft is kept and flagged
(`below_minimum`), and the family warns. The length of need is measured to
a point 12.5 ft in from a terminal's nose (TSSM 3.6(1)), so a run's
stations are its noses: 12.5 ft (GATING_FT) is added at each free
terminal end. A free terminal's nose 200 ft or less from a wall runs on
and ties into it (TSSM 3.6(11); no terminal at the wall barrier's end). A
run reaching the alignment's end stops there, its terminal at the end with
no room for its gating and its length of need cut short: it is flagged
(`short_end`), and the family warns. `side_runs` clips each guarded span
to the corridor runs, so a span across a structure gap shields both sides.

The rail face stands at the shoulder edge; the body is the W-beam band,
31 in to the top of rail (A77N3), swept along the alignment. Posts are
counted at 6'-3" from the run's start, not modelled: every post is a 6 ft
post (A77N3 Detail A), the 10:1 widening behind the rail running the whole
run, its length-of-need stretches included.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from bimforge.author.alignment import sta
from bimforge.author.corridor.params import RUNOUT_FT

#: the clear-zone edge on a conventional highway, feet (HDM Index 309.1)
CLEAR_ZONE_FT = 20.0
#: one W-beam rail element, feet
ELEMENT_FT = 12.5
#: the shortest length of need, feet (TSSM 3.6(1))
MIN_RUN_FT = 150.0
#: a terminal's nose to its length-of-need point, feet (TSSM 3.6(1))
GATING_FT = 12.5
#: runs this close or closer join, feet (TSSM 3.6(11))
JOIN_GAP_FT = 200.0
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
#: end treatments: an in-line terminal, a Type AGT transition at a structure
#: gap, a Type AGT tied into a wall, a Type SFT-M anchor
TERMINAL, AGT, WALL, SFT_M = "TERMINAL", "AGT", "WALL", "SFT-M"
HEADER = ("side,start,end,length_ft,start_treatment,end_treatment,posts,"
          "below_minimum,short_end")
_EPS = 1e-9


@dataclass(frozen=True)
class RailRun:
    side: str
    start: float           # the rail's ends: a terminal's nose, else the
    end: float             # transition, tie-in or anchor
    start_end: str         # TERMINAL, AGT, WALL or SFT_M
    end_end: str
    #: the guarded spans [(s0, s1)] the run shields
    guarded: tuple = ()
    #: held at both ends short of MIN_RUN_FT of need
    below_minimum: bool = False
    #: a terminal held at the alignment's end: no gating, and its length of
    #: need would run on past the alignment
    short_end: bool = False

    @property
    def length(self) -> float:
        return self.end - self.start

    @property
    def posts(self) -> int:
        """6 ft posts every POST_SPACING_FT from the start (A77N3 Detail A)."""
        return math.floor(self.length / POST_SPACING_FT + _EPS) + 1

    @property
    def terminals(self) -> int:
        return [self.start_end, self.end_end].count(TERMINAL)

    @property
    def agts(self) -> int:
        """Type AGT transitions: at a structure gap or tied into a wall."""
        return sum(1 for e in (self.start_end, self.end_end) if e in (AGT, WALL))

    @property
    def anchors(self) -> int:
        """Type SFT-M anchors."""
        return [self.start_end, self.end_end].count(SFT_M)


@dataclass
class _Core:
    """A run between its length-of-need points (or fixed ends), before its
    whole elements, minimum and gating. `lo` and `hi` are its bay's limits
    (station, treatment): the corridor run's ends or the walls beside it."""
    start: float
    end: float
    s_kind: str
    e_kind: str
    s_fixed: bool
    e_fixed: bool
    lo: tuple
    hi: tuple
    guarded: tuple = field(default=())


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
    minimum is the run's, not each X's (`_finish`)."""
    x = (lh - offset - y) / (lh / RUNOUT_FT[speed_mph])
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


def _bay(a: float, b: float, lower: tuple, upper: tuple, walls) -> tuple:
    """The limits (station, treatment) either side of [a, b]: the nearest
    wall ends, else the corridor run's ends."""
    lo = max([lower] + [(e, WALL) for _s, e in walls if e <= a + _EPS],
             key=lambda t: t[0])
    hi = min([upper] + [(s, WALL) for s, _e in walls if s >= b - _EPS],
             key=lambda t: t[0])
    return lo, hi


def _clamp(k: _Core) -> None:
    """Cut `k` back to its bay. At the alignment's end (a TERMINAL limit)
    an end keeps its own treatment; at a wall or structure gap it takes
    the limit's."""
    if k.start < k.lo[0] + _EPS:
        k.start, k.s_fixed = k.lo[0], True
        if k.lo[1] != TERMINAL:
            k.s_kind = k.lo[1]
    if k.end > k.hi[0] - _EPS:
        k.end, k.e_fixed = k.hi[0], True
        if k.hi[1] != TERMINAL:
            k.e_kind = k.hi[1]


def _finish(side: str, core: _Core) -> RailRun:
    """`core` made whole elements and MIN_RUN_FT at least between its
    length-of-need points (the extra split evenly between its free ends, or
    all at the free one; what a free end loses to its limit goes to the
    other), then 12.5 ft of gating added at each free terminal."""
    k = _Core(**core.__dict__)
    target = max(MIN_RUN_FT, round_up(k.end - k.start))
    extra = target - (k.end - k.start)
    if extra > _EPS and not (k.s_fixed and k.e_fixed):
        if not k.s_fixed and not k.e_fixed:
            k.start, k.end = k.start - extra / 2.0, k.end + extra / 2.0
        elif not k.s_fixed:
            k.start -= extra
        else:
            k.end += extra
        _clamp(k)
        short = target - (k.end - k.start)
        if short > _EPS and not (k.s_fixed and k.e_fixed):
            if not k.s_fixed:
                k.start -= short
            else:
                k.end += short
            _clamp(k)
    below = k.end - k.start < MIN_RUN_FT - _EPS
    if k.s_kind == TERMINAL and not k.s_fixed:
        k.start -= GATING_FT
    if k.e_kind == TERMINAL and not k.e_fixed:
        k.end += GATING_FT
    _clamp(k)
    # a TERMINAL end now fixed is held at the alignment's end, its length of
    # need or its gating cut short
    short = ((k.s_kind == TERMINAL and k.s_fixed)
             or (k.e_kind == TERMINAL and k.e_fixed))
    # a free nose 200 ft or less from a wall ties into it
    if (k.s_kind == TERMINAL and not k.s_fixed and k.lo[1] == WALL
            and k.start - k.lo[0] <= JOIN_GAP_FT + _EPS):
        k.start, k.s_kind = k.lo
    if (k.e_kind == TERMINAL and not k.e_fixed and k.hi[1] == WALL
            and k.hi[0] - k.end <= JOIN_GAP_FT + _EPS):
        k.end, k.e_kind = k.hi
    return RailRun(side, k.start, k.end, k.s_kind, k.e_kind, k.guarded, below,
                   short)


def lay_out(side: str, guarded: list, l2: float, lc: float, speed_mph: int,
            lower: tuple, upper: tuple, walls=(), bridge_rail: bool = False) -> list:
    """The rail runs on `side` within one corridor run, for its `guarded`
    spans [(s0, s1)], the rail face `l2` ft from the edge of traveled way
    and `lc` ft from the centreline. `lower` and `upper` are the corridor
    run's ends, (station, AGT at a structure gap or TERMINAL at the
    alignment's end); `walls` [(start, end)] are the side's walls, which a
    run ties into. With `bridge_rail`, each AGT end also takes a run for
    the bridge rail end, merged with the rest by the same join rules."""
    near = need(l2, speed_mph)            # the lane beside the rail
    far = need(lc, speed_mph)             # the opposing lane
    # X for traffic travelling up-station (it extends a span's start) and
    # down-station (its end)
    up, down = (near, far) if side == "R" else (far, near)
    for a, b in guarded:
        for ws, we in walls:
            if ws < b - _EPS and we > a + _EPS:
                raise ValueError(
                    f"guardrail: the wall {sta(ws)} to {sta(we)} on side {side} "
                    f"overlaps the guarded span {sta(a)} to {sta(b)}")
    cores = []
    for a, b in guarded:
        lo, hi = _bay(a, b, lower, upper, walls)
        cores.append(_Core(a - up, b + down, TERMINAL if up > 0.0 else SFT_M,
                           TERMINAL if down > 0.0 else SFT_M, False, False,
                           lo, hi, ((a, b),)))
    if bridge_rail and lower[1] == AGT and down > 0.0:
        # down-station traffic heads toward the bridge rail end at `lower`
        lo, hi = _bay(lower[0], lower[0], lower, upper, walls)
        cores.append(_Core(lower[0], lower[0] + down, AGT, TERMINAL, True,
                           False, lo, hi))
    if bridge_rail and upper[1] == AGT and up > 0.0:
        lo, hi = _bay(upper[0], upper[0], lower, upper, walls)
        cores.append(_Core(upper[0] - up, upper[0], TERMINAL, AGT, False,
                           True, lo, hi))
    for k in cores:
        _clamp(k)
    cores.sort(key=lambda k: (k.start, k.end))
    while True:
        runs = [_finish(side, k) for k in cores]
        for i in range(len(cores) - 1):
            p, n = cores[i], cores[i + 1]
            pr, nr = runs[i], runs[i + 1]
            between = any(ws > pr.end - _EPS and we < nr.start + _EPS
                          for ws, we in walls)
            if (p.lo == n.lo and p.hi == n.hi and not between
                    and nr.start - pr.end <= JOIN_GAP_FT + _EPS):
                first = p if p.start <= n.start else n
                last = p if p.end >= n.end else n
                cores[i:i + 2] = [_Core(
                    first.start, last.end, first.s_kind, last.e_kind,
                    first.s_fixed, last.e_fixed, p.lo, p.hi,
                    tuple(sorted(p.guarded + n.guarded)))]
                break
        else:
            return runs


def side_runs(side: str, guarded: list, l2: float, lc: float, speed_mph: int,
              runs: list, s_start: float, s_end: float, walls=()) -> list:
    """Every rail run on `side` along the alignment `s_start` to `s_end`:
    `runs` [(s0, s1)] are the corridor's runs (params.Corridor.runs()), an
    end that is not the alignment's being a structure gap's (AGT, with
    bridge rail); `guarded` spans and `walls` [(start, end)] are the
    side's, over the whole alignment. A guarded span is clipped to each
    corridor run it crosses."""
    out = []
    for s0, s1 in runs:
        lower = (s0, TERMINAL if abs(s0 - s_start) < _EPS else AGT)
        upper = (s1, TERMINAL if abs(s1 - s_end) < _EPS else AGT)
        out += lay_out(
            side, [(max(a, s0), min(b, s1)) for a, b in guarded
                   if max(a, s0) <= min(b, s1) + _EPS],
            l2, lc, speed_mph, lower, upper,
            [(ws, we) for ws, we in walls if we > s0 - _EPS and ws < s1 + _EPS],
            bridge_rail=True)
    return out


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
        f"{r.start_end},{r.end_end},{r.posts},"
        f"{'yes' if r.below_minimum else 'no'},{'yes' if r.short_end else 'no'}"
        for r in runs]) + "\n"
