"""The road corridor's cross-section at a station (roadmap P.6): finished
grade, course rings, subgrade and side slopes to daylight, in section
coordinates (u left of travel, v up from the profile grade line).

No geometry and no IFC. The ground comes in as `ground_dz(s, u, v)`: how far
the ground lies above the section point (u, v) at station s, so a test can
hand in level ground and the family hands in the real thing.
"""
from __future__ import annotations

from dataclasses import dataclass

from bimforge.author.alignment import sta
from bimforge.author.corridor.params import SIDES, WIDENING_SLOPE

#: points on each side's slope line, hinge and daylight included: fixed, so
#: every station's earthwork line has the same count and lofts point to point
SIDE_SAMPLES = 12
#: the daylight search's step along a slope, horizontal feet
_SCAN_FT = 1.0
#: how far a daylight point may sit off the ground, feet
_ON_GROUND_FT = 0.01


#: a guarded side's widening starts this far outside the shoulder edge, so
#: the earthwork's face up the courses' outer edge is a slope and not a
#: vertical step (a step puts two columns on one plan edge, and the merged
#: earthwork skin is then two bodies touching along it), feet
GUARD_STEP_FT = 0.01


class NoDaylight(ValueError):
    """A side slope that does not fit: no ground within the daylight limit,
    or a daylight past the side's footprint. `kind` is the side's kind at
    its hinge, "cut" or "fill": the wall `walls: auto` puts there."""

    def __init__(self, message: str, kind: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class Side:
    kind: str           # "cut", "fill" or "wall"
    line: list          # [(u, v)] from the hinge out to daylight or the wall
    guarded: bool = False          # V1.1: a steep fill behind guardrail
    #: V1.1: the side's nominal slope ratio: cut_ratio on any cut side (even
    #: a side-hill cut whose ditch edge runs down at the fill ratio), the
    #: fill or steep ratio on a fill side; None on a wall
    ratio: float | None = None


@dataclass(frozen=True)
class Section:
    s: float
    grade: dict         # side -> [(u, v)], crown outward, one per component edge
    courses: dict       # (course index, component index, side) -> 4-point ring
    subgrade: dict      # side -> [(u, v)], crown outward; its last is the hinge
    sides: dict         # side -> Side

    def earthwork_line(self, per_component=1) -> list:
        """Left daylight to right daylight across the subgrade, with the same
        number of points at every station.

        `per_component` cuts each component's subgrade segment, both sides,
        into that many equal parts (an int for all, or one count per
        component), so the ground is read across a wide lane and not only
        at its edges. The points lie on the subgrade, so the geometry is
        unchanged; the caller must pass the same counts at every station."""
        n = len(self.subgrade["L"]) - 1
        if len(self.subgrade["R"]) - 1 != n:
            raise ValueError(f"station {sta(self.s)}: the subgrade has "
                             f"{n} components left, {len(self.subgrade['R']) - 1} right")
        counts = ([per_component] * n if isinstance(per_component, int)
                  else list(per_component))
        if len(counts) != n:
            raise ValueError(f"per_component: {len(counts)} counts for {n} "
                             f"components; give one count per component")
        if any(not isinstance(k, int) or k < 1 for k in counts):
            raise ValueError(f"per_component: each count must be an int of "
                             f"at least 1, not {counts}")
        sub = {side: _divided(self.subgrade[side], counts) for side in SIDES}
        left = list(reversed(_samples(self.sides["L"].line)))
        under_left = list(reversed(sub["L"][:-1]))
        under_right = sub["R"][1:]
        right = _samples(self.sides["R"].line)[1:]
        return left + under_left + under_right + right

    def width(self) -> float:
        """Daylight to daylight, feet."""
        return abs(self.sides["L"].line[-1][0] - self.sides["R"].line[-1][0])


def _divided(pts: list, counts: list) -> list:
    """`pts` with segment j cut evenly into counts[j] parts."""
    out = []
    for ((u0, v0), (u1, v1)), k in zip(zip(pts, pts[1:]), counts):
        out.append((u0, v0))
        out += [(u0 + (u1 - u0) * i / k, v0 + (v1 - v0) * i / k)
                for i in range(1, k)]
    return out + [pts[-1]]


def _samples(line: list) -> list:
    """`line` with its last segment cut evenly to SIDE_SAMPLES points."""
    extra = SIDE_SAMPLES - len(line)
    (u0, v0), (u1, v1) = line[-2], line[-1]
    mid = [(u0 + (u1 - u0) * i / (extra + 1), v0 + (v1 - v0) * i / (extra + 1))
           for i in range(1, extra + 1)]
    return list(line[:-1]) + mid + [line[-1]]


def _daylight(s, start, sign, rise, ground_dz, reach, cut):
    """Where the line from `start`, `sign` outward and `rise` ft up per ft
    out, meets the ground within `reach` horizontal ft; None if it does
    not."""
    su, sv = start

    def hit(h):
        dz = ground_dz(s, su + sign * h, sv + rise * h)
        return dz <= 0.0 if cut else dz >= 0.0

    if hit(0.0):
        return start
    if reach <= 0.0:
        return None
    lo, h = 0.0, min(_SCAN_FT, reach)
    while not hit(h):
        if h >= reach:
            return None
        lo, h = h, min(h + _SCAN_FT, reach)
    hi = h
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if hit(mid):
            hi = mid
        else:
            lo = mid
    return (su + sign * hi, sv + rise * hi)


def _side(c, s: float, side: str, sign: float, hinge: tuple, ground_dz,
          rail: bool = False) -> Side:
    hu, hv = hinge
    # each side reads its own wall, so walls on both sides at one station
    # each end their own side
    wall = c.wall(side, s)
    if wall is not None:
        if wall.offset is None:
            # an automatic wall (walls: auto) stands at the hinge: a fill
            # wall with no slope in front, a cut wall beside its 10 ft
            # shoulder (params.Corridor.width). Its line is the hinge
            # twice, so the side keeps its point count (_samples)
            return Side("wall", [hinge, hinge])
        if wall.offset < abs(hu):
            raise ValueError(
                f"station {sta(s)}: the {side} wall at offset {wall.offset:g} ft "
                f"is inside the hinge at {abs(hu):g} ft")
        return Side("wall", [hinge, (sign * wall.offset, hv)])
    return _slope(c, s, side, sign, hinge, ground_dz, rail)


def _slope(c, s: float, side: str, sign: float, hinge: tuple, ground_dz,
           rail: bool = False) -> Side:
    """The side's slope from `hinge` out to daylight: cut (the ditch, V1.1's
    rock face and bench, then the backslope) or fill (V1.1: the steep ratio
    behind the rail's widening where the fill at the hinge is over the
    steep rule's height). NoDaylight when it finds no ground within the
    limit or daylights past the footprint.

    With `rail` (a guardrail runs past station s on this side) the 10:1
    widening stands behind the rail whatever the side is: a 4:1 fill runs
    from the widening's hinge, and a cut's ditch moves out behind it. The
    side's kind and its guarded flag are read at the subgrade hinge as
    without it, so the rail does not move the spans it was laid for.

    A corridor with guardrail gives every slope the widening's two points:
    where no rail runs and the fill is not guarded they collapse onto the
    hinge, so a side keeps one vertex for each point of its configuration
    and a ditch lofts to the ditch moved out behind the widening, not onto
    the widening."""
    hu, hv = hinge
    sl = c.slopes
    fill_ratio, guarded = sl.fill_ratio, False
    # the widening's points, or the hinge twice where it has none
    collapsed = [hinge, hinge] if c.guard is not None else []
    if ground_dz(s, hu, hv) > 0.0:
        kind, pts = "cut", [hinge]
        pts += _widening(c, s, side, sign) if rail else collapsed
        if sl.ditch is not None:
            # the flowline is the ditch depth under the subgrade hinge,
            # rail or no rail, so the base drains to it and it does not step
            # at a rail's ends; the foreslope runs down to it from the hinge,
            # or under a rail from the widening's hinge
            du, dv = pts[-1]
            flow = hv - sl.ditch.depth
            p1 = (du + sign * sl.cut_ratio * (dv - flow), flow)
            pts += [p1, (p1[0] + sign * sl.ditch.width, p1[1])]
        if sl.rock is not None:
            pts += _rock(c, s, side, sign, pts[-1], ground_dz,
                         sl.daylight_limit - abs(pts[-1][0] - hu))
    else:
        kind, pts = "fill", [hinge]
        # the fill height is read at the subgrade hinge, the courses' depth
        # below the finished shoulder, not at the widening's hinge: the
        # trigger is that much more conservative than TSSM's embankment
        # height, measured from the shoulder
        if sl.steep is not None and -ground_dz(s, hu, hv) > sl.steep.above_height:
            fill_ratio, guarded = sl.steep.ratio, True
        pts += _widening(c, s, side, sign) if guarded or rail else collapsed
    # up the backslope while the ground is above the slope's start; on a side
    # hill the ditch's outer edge can stand above the ground, and the side
    # then runs down at the fill ratio from there
    up = ground_dz(s, *pts[-1]) > 0.0
    rise = 1.0 / sl.cut_ratio if up else -1.0 / fill_ratio
    used = abs(pts[-1][0] - hu)
    day = _daylight(s, pts[-1], sign, rise, ground_dz,
                    sl.daylight_limit - used, cut=up)
    if day is None:
        raise NoDaylight(
            f"station {sta(s)}: the {side} {kind} slope finds no ground within "
            f"{sl.daylight_limit:g} ft of the hinge", kind)
    off = ground_dz(s, *day)
    if abs(off) > _ON_GROUND_FT:
        raise ValueError(
            f"station {sta(s)}: the {side} {kind} slope ends {abs(off):.2f} ft "
            f"off the ground at offset {abs(day[0]):.2f} ft (is the ground "
            f"continuous there?)")
    fp = (sl.footprint or {}).get(side)
    if fp is not None and abs(day[0]) > fp + 1e-9:
        raise NoDaylight(
            f"station {sta(s)}: the {side} {kind} slope daylights "
            f"{abs(day[0]):.2f} ft out, past the {side} footprint of {fp:g} ft",
            kind)
    return Side(kind, pts + [day], guarded,
                sl.cut_ratio if kind == "cut" else fill_ratio)


def _widening(c, s: float, side: str, sign: float) -> list:
    """A guarded side's two points past the hinge: GUARD_STEP_FT out from
    the shoulder edge, then the hinge `Guard.widening` behind the rail face
    (at the shoulder edge), both on the 10:1 (TSSM 3.6, A77N3 Detail A)."""
    eu, ev = grade_edge(c, s, side)
    return [(eu + sign * w, ev - WIDENING_SLOPE * w)
            for w in (GUARD_STEP_FT, c.guard.widening)]


def _rock(c, s: float, side: str, sign: float, toe: tuple, ground_dz,
          reach: float) -> list:
    """The rock face's top and the bench's end, out from the toe of the cut
    (the ditch's outer edge, or the hinge without a ditch): the face at
    `rock.ratio` up to the rock surface (`rock.depth_at(s)` under the
    ground), then the bench level `rock.bench` ft. A toe not in rock gives
    the toe twice: the face and bench collapse onto it, so a rock cut has
    one vertex count at every station and its last segment, the one
    `_samples` divides, is always the soil slope.

    Rock depth is measured vertically below the ground at each point along
    the face, so the face's top (the bench's inner end) sits on the
    soil/rock interface and the face only ever stands in rock. The bench
    and the soil slope take no such reading: on ground rising outward the
    first part of the soil slope can cut rock (conservative); on ground
    falling faster than depth / bench across the bench, its outer end can
    stand above the ground, and the side then runs down at the fill ratio
    from there, as a side-hill cut does (NoDaylight where the ground keeps
    falling faster than that)."""
    rock = c.slopes.rock
    depth = rock.depth_at(s)

    def in_rock(s_, u, v):
        return ground_dz(s_, u, v) - depth

    if in_rock(s, *toe) <= 0.0:
        return [toe, toe]
    top = _daylight(s, toe, sign, 1.0 / rock.ratio, in_rock, reach, cut=True)
    if top is None:
        raise NoDaylight(
            f"station {sta(s)}: the {side} cut's rock face finds no rock "
            f"surface within {c.slopes.daylight_limit:g} ft of the hinge", "cut")
    return [top, (top[0] + sign * rock.bench, top[1])]


def _grade(c, s: float, side: str) -> list:
    """Finished grade on `side` at station s, crown outward, one point per
    component edge."""
    sign = 1.0 if side == "L" else -1.0
    u = v = 0.0
    pts = [(0.0, 0.0)]
    for comp in c.components:
        w = c.width(comp, side, s)
        slope = (comp.slope if comp.slope is not None
                 else c.cross_slope(side, s))
        u += sign * w
        v += w * slope
        pts.append((u, v))
    return pts


def grade_edge(c, s: float, side: str) -> tuple:
    """(u, v) of the finished grade's outer edge, the shoulder edge, on
    `side` at station s: where a guardrail's face stands."""
    return _grade(c, s, side)[-1]


def needs_wall(c, s: float, side: str, ground_dz, rail: bool = False) -> str | None:
    """The wall `side` needs at station s, "cut" or "fill", when its slope
    does not fit (no daylight within the limit, or past the footprint);
    None when it fits, or where a wall gap already stands. With `rail`, the
    slope behind a guardrail's widening (_slope)."""
    if c.wall(side, s) is not None:
        return None
    sign = 1.0 if side == "L" else -1.0
    u, v = grade_edge(c, s, side)
    try:
        _slope(c, s, side, sign, (u, v - c.depth()), _named(ground_dz, side),
               rail)
    except NoDaylight as exc:
        return exc.kind
    return None


#: how close the station a side turns at is found, feet
_TURN_FT = 1e-9


def kind_changes(c, a: Section, b: Section, ground_dz) -> list:
    """Stations strictly between sections `a` and `b` where a side turns
    from cut to fill or back: where its hinge meets the ground.

    A side's earthwork line is lofted point to point between stations, so
    across a turn the ditch and backslope at one station run onto the fill
    slope at the next: long twisted slivers whose ground crossing is a comb.
    Cut a section where it turns and the side there is a point on the
    ground (the hinge, as fill), so each strip either side is all one kind
    fanning from that point. The station returned is the fill side of the
    turn, within _TURN_FT."""
    depth = c.depth()
    out = []
    for side in SIDES:
        kinds = {a.sides[side].kind, b.sides[side].kind}
        if kinds != {"cut", "fill"}:
            continue

        def above(s):
            u, v = _grade(c, s, side)[-1]
            return ground_dz(s, u, v - depth) > 0.0

        lo, hi = a.s, b.s                 # `above` differs at the two ends
        cut_lo = above(lo)
        while hi - lo > _TURN_FT:
            mid = 0.5 * (lo + hi)
            if above(mid) == cut_lo:
                lo = mid
            else:
                hi = mid
        s = hi if cut_lo else lo          # the end where the side is fill
        if a.s < s < b.s:
            out.append(s)
    return sorted(set(out))


def _named(ground_dz, side: str):
    """`ground_dz`, its errors (a DEM with no ground there) naming the
    station and side they were read for."""
    def dz(s, u, v):
        try:
            return ground_dz(s, u, v)
        except ValueError as exc:
            raise ValueError(f"station {sta(s)}, {side} side, offset "
                             f"{abs(u):.2f} ft: {exc}") from None
    return dz


def resolve(c, s: float, ground_dz, rail=()) -> Section:
    """The section of corridor `c` at station `s` (params.Corridor). `rail`
    names the sides a guardrail runs past at s: each takes the widening
    behind it (_slope)."""
    depth = c.depth()
    grade, subgrade, courses, sides = {}, {}, {}, {}
    for side in SIDES:
        sign = 1.0 if side == "L" else -1.0
        pts = _grade(c, s, side)
        grade[side] = pts
        subgrade[side] = [(pu, pv - depth) for pu, pv in pts]
        above = 0.0
        for k, course in enumerate(c.courses):
            t = course.thickness
            for j in range(len(c.components)):
                (u0, v0), (u1, v1) = pts[j], pts[j + 1]
                courses[k, j, side] = [(u0, v0 - above), (u1, v1 - above),
                                       (u1, v1 - above - t), (u0, v0 - above - t)]
            above += t
        sides[side] = _side(c, s, side, sign, subgrade[side][-1],
                            _named(ground_dz, side), side in rail)
    return Section(s, grade, courses, subgrade, sides)
