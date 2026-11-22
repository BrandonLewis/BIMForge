"""Automatic walls for the road corridor (V1.1, `walls: auto`).

A side whose slope does not fit at a station (no daylight within the limit,
or a daylight past the footprint: section.needs_wall) takes a wall there.
Consecutive failing stations of one kind on a side are one wall, extended a
foot at a time while the section a foot beyond still fails, so each end's
1 ft lead-in (params.WALL_TRANSITION_FT) runs to a slope that fits. Each
wall is then a wall gap (params.Gap, `auto` its kind), standing at the hinge
(section._side): a fill wall with a barrier on top and no slope in front, a
cut wall beside its 10 ft shoulder (params.Corridor.width).

`rows` reads each wall's exposed height off the sections: the shoulder
edge's height above the ground at a fill wall, the ground's above the edge
at a cut wall. A fill wall over `max_wall_height_ft` is kept and flagged,
and its stretch is a structure candidate (`structures`): a short bridge or
a culvert the designer may put there instead, with a structure gap.
"""
from __future__ import annotations

from dataclasses import dataclass

from bimforge.author.alignment import sta
from bimforge.author.corridor.params import SIDES, WALL_TRANSITION_FT, Gap
from bimforge.author.corridor.section import needs_wall

WALL_HEADER = "side,kind,start,end,offset_ft,min_height_ft,max_height_ft,barrier,too_tall"
STRUCTURE_HEADER = "side,start,end,max_fill_ft,low_point_station"
_EPS = 1e-9


@dataclass(frozen=True)
class WallRow:
    side: str
    kind: str              # "fill" or "cut"
    start: float
    end: float
    offset: float          # the largest hinge offset, feet from the centreline
    min_height: float      # exposed height, feet
    max_height: float
    too_tall: bool         # a fill wall over max_wall_height_ft

    @property
    def barrier(self) -> bool:
        """A fill wall carries a barrier on top (no guardrail there)."""
        return self.kind == "fill"


@dataclass(frozen=True)
class StructureRow:
    side: str              # "L", "R" or "both"
    start: float
    end: float
    max_fill: float        # the tallest wall it replaces, feet
    low_point: float       # the station where the ground is lowest


def find(c, stations: list, ground_dz) -> list:
    """Wall gaps (params.Gap, `auto` the wall's kind) for one run's
    `stations` of corridor `c`, by start station."""
    out = []
    for side in SIDES:
        kinds = [needs_wall(c, s, side, ground_dz) for s in stations]
        i = 0
        while i < len(stations):
            kind = kinds[i]
            if kind is None:
                i += 1
                continue
            j = i
            while j + 1 < len(stations) and kinds[j + 1] == kind:
                j += 1
            start = _reach(c, side, ground_dz, kind, stations[i],
                           stations[i - 1] if i > 0 else None, -1.0)
            end = _reach(c, side, ground_dz, kind, stations[j],
                         stations[j + 1] if j + 1 < len(stations) else None, 1.0)
            out.append(Gap(start, end, "wall", side, None, auto=kind))
            i = j + 1
    return sorted(out, key=lambda g: (g.start, g.side))


def _reach(c, side: str, ground_dz, kind: str, s: float, neighbour, step: float) -> float:
    """The wall's end, moved from station `s` toward `neighbour` (the next
    station, which does not need this wall; None at the run's end, where
    the wall ends at `s`) a foot at a time while the section a foot beyond
    still needs it. It stops a foot short of `neighbour` at the latest, so
    the lead-in ends on a section that fits."""
    if neighbour is None:
        return s
    while True:
        t = s + step * WALL_TRANSITION_FT
        if (neighbour - t) * step <= _EPS:
            return s
        if needs_wall(c, t, side, ground_dz) != kind:
            return s
        s = t


def rows(c, secs: list, ground_dz) -> list:
    """One WallRow per automatic wall of `c`, its heights read off the
    sections `secs` (section.Section) on its stations, by start station."""
    out = []
    for g in c.gaps:
        if g.auto is None:
            continue
        on = [sec for sec in secs if g.start - _EPS <= sec.s <= g.end + _EPS]
        if not on:
            raise ValueError(f"the {g.side} {g.auto} wall from {sta(g.start)} "
                             f"to {sta(g.end)} has no section on it to read "
                             f"its height from")
        heights = []
        for sec in on:
            u, v = sec.grade[g.side][-1]
            dz = ground_dz(sec.s, u, v)
            heights.append(-dz if g.auto == "fill" else dz)
        top = max(heights)
        out.append(WallRow(g.side, g.auto, g.start, g.end,
                           max(abs(sec.subgrade[g.side][-1][0]) for sec in on),
                           min(heights), top,
                           g.auto == "fill" and top > c.max_wall_height + _EPS))
    return sorted(out, key=lambda r: (r.start, r.side))


def structures(rows: list, stations: list, ground_elev) -> list:
    """The structure candidates: each too-tall wall's stretch, walls on the
    two sides that overlap merged into one ("both"), with the tallest fill
    and the station of `stations` where `ground_elev(s)` (the ground at the
    centreline) is lowest."""
    groups = []
    for r in sorted((r for r in rows if r.too_tall), key=lambda r: r.start):
        if groups and r.start <= groups[-1][1] + _EPS:
            a, b, top, sides = groups[-1]
            groups[-1] = (a, max(b, r.end), max(top, r.max_height), sides | {r.side})
        else:
            groups.append((r.start, r.end, r.max_height, {r.side}))
    out = []
    for a, b, top, sides in groups:
        inside = [s for s in stations if a - _EPS <= s <= b + _EPS] or [a, b]
        out.append(StructureRow("both" if len(sides) > 1 else next(iter(sides)),
                                a, b, top, min(inside, key=ground_elev)))
    return out


def walls_csv(rows: list) -> str:
    return "\n".join([WALL_HEADER] + [
        f"{r.side},{r.kind},{r.start:.2f},{r.end:.2f},{r.offset:.2f},"
        f"{r.min_height:.2f},{r.max_height:.2f},"
        f"{'yes' if r.barrier else 'no'},{'yes' if r.too_tall else 'no'}"
        for r in rows]) + "\n"


def structures_csv(rows: list) -> str:
    return "\n".join([STRUCTURE_HEADER] + [
        f"{r.side},{r.start:.2f},{r.end:.2f},{r.max_fill:.2f},{r.low_point:.2f}"
        for r in rows]) + "\n"
