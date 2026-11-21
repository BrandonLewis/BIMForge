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
from bimforge.author.corridor.params import SIDES

#: points on each side's slope line, hinge and daylight included: fixed, so
#: every station's earthwork line has the same count and lofts point to point
SIDE_SAMPLES = 12
#: the daylight search's step along a slope, horizontal feet
_SCAN_FT = 1.0


@dataclass(frozen=True)
class Side:
    kind: str           # "cut", "fill" or "wall"
    line: list          # [(u, v)] from the hinge out to daylight or the wall


@dataclass(frozen=True)
class Section:
    s: float
    grade: dict         # side -> [(u, v)], crown outward, one per component edge
    courses: dict       # (course index, component index, side) -> 4-point ring
    subgrade: dict      # side -> [(u, v)], crown outward; its last is the hinge
    sides: dict         # side -> Side

    def earthwork_line(self) -> list:
        """Left daylight to right daylight across the subgrade, with the same
        number of points at every station."""
        left = list(reversed(_samples(self.sides["L"].line)))
        under_left = list(reversed(self.subgrade["L"][:-1]))
        under_right = self.subgrade["R"][1:]
        right = _samples(self.sides["R"].line)[1:]
        return left + under_left + under_right + right

    def width(self) -> float:
        """Daylight to daylight, feet."""
        return abs(self.sides["L"].line[-1][0] - self.sides["R"].line[-1][0])


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


def _side(c, s: float, side: str, sign: float, hinge: tuple, ground_dz) -> Side:
    hu, hv = hinge
    # each side reads its own wall, so walls on both sides at one station
    # each end their own side
    wall = c.wall(side, s)
    if wall is not None:
        if wall.offset < abs(hu):
            raise ValueError(
                f"station {sta(s)}: the {side} wall at offset {wall.offset:g} ft "
                f"is inside the hinge at {abs(hu):g} ft")
        return Side("wall", [hinge, (sign * wall.offset, hv)])
    sl = c.slopes
    if ground_dz(s, hu, hv) > 0.0:
        kind, pts = "cut", [hinge]
        if sl.ditch is not None:
            p1 = (hu + sign * sl.cut_ratio * sl.ditch.depth, hv - sl.ditch.depth)
            pts += [p1, (p1[0] + sign * sl.ditch.width, p1[1])]
        rise = 1.0 / sl.cut_ratio
    else:
        kind, pts, rise = "fill", [hinge], -1.0 / sl.fill_ratio
    used = abs(pts[-1][0] - hu)
    day = _daylight(s, pts[-1], sign, rise, ground_dz,
                    sl.daylight_limit - used, cut=(kind == "cut"))
    if day is None:
        raise ValueError(
            f"station {sta(s)}: the {side} {kind} slope finds no ground within "
            f"{sl.daylight_limit:g} ft of the hinge")
    return Side(kind, pts + [day])


def resolve(c, s: float, ground_dz) -> Section:
    """The section of corridor `c` at station `s` (params.Corridor)."""
    depth = c.depth()
    grade, subgrade, courses, sides = {}, {}, {}, {}
    for side in SIDES:
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
        sides[side] = _side(c, s, side, sign, subgrade[side][-1], ground_dz)
    return Section(s, grade, courses, subgrade, sides)
