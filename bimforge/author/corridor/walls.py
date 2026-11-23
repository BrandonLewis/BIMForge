"""Automatic walls for the road corridor (V1.1, `walls: auto`).

A side whose slope does not fit at a station (no daylight within the limit,
or a daylight past the footprint: section.needs_wall) takes a wall there.
Consecutive failing stations of one kind on a side are one wall, extended a
foot at a time while the section a foot beyond still fails, so each end's
1 ft lead-in (params.WALL_TRANSITION_FT) runs to a slope that fits. Each
wall is then a wall gap (params.Gap, `auto` its kind), standing at the hinge
(section._side): a fill wall with a barrier on top and no slope in front, a
cut wall beside its 10 ft shoulder (params.Corridor.width).

`rows` reads each wall's exposed height at its face at finished grade, at
its sections' stations and at least every 5 ft between: the shoulder edge's
height above the ground at a fill wall (grade minus ground), the ground's
above the edge at a cut wall (ground minus grade). The barrier on a fill
wall and the wall's footing and embedment are not in it; the wall family
adds them. A fill wall over `max_wall_height_ft` is kept and flagged,
and its stretch is a structure candidate (`structures`): a short bridge or
a culvert the designer may put there instead, with a structure gap.

V1.2 C: on the path's side, where the path is, the path's outer slope takes
a `path-fill` or `path-cut` wall at o, and the strip between road and path
a strip wall (`strip-road` at the road's hinge, `strip-path` at q), found
apart, so a station may have both. A strip wall's height is its face down
to the level strip at its foot; a too-tall fill or strip wall is a
structure candidate carrying the road or the path (`carries`).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from bimforge.author.alignment import sta
from bimforge.author.corridor.params import SIDES, WALL_TRANSITION_FT, Gap
from bimforge.author.corridor.section import grade_edge, needs_wall

#: outputs.walls: heights are exposed at the face, at finished grade, with
#: no barrier, footing or embedment (the module docstring); `location` is
#: "outer", or "strip" between the road and its path (V1.2 C)
WALL_HEADER = ("side,kind,start,end,offset_ft,min_height_ft,max_height_ft,"
               "barrier,too_tall,location")
STRUCTURE_HEADER = "side,start,end,max_fill_ft,low_point_station,carries"
#: the longest step between the stations a wall's height is read at, feet
HEIGHT_STEP_FT = 5.0
_EPS = 1e-9


@dataclass(frozen=True)
class WallRow:
    side: str
    kind: str              # "fill" or "cut"; in the strip "wall-road" or
                           # "wall-path" (V1.2 C)
    start: float
    end: float
    offset: float          # the wall's face, feet from the centreline
    min_height: float      # exposed at the face at finished grade, feet
                           # (no barrier, footing or embedment)
    max_height: float
    too_tall: bool         # a fill or strip wall over max_wall_height_ft
    location: str = "outer"        # or "strip"
    carries: str = "road"          # or "path"

    @property
    def barrier(self) -> bool:
        """Whether the wall carries the road's barrier on top: a road fill
        wall, or a strip wall at the road's hinge (`wall-road`). Only the
        road's barrier: the path's rail on a `wall-path` or on a wall on
        the path's outer side is not one."""
        return (self.kind == "fill" and self.carries == "road") or self.kind == "wall-road"


@dataclass(frozen=True)
class StructureRow:
    side: str              # "L", "R" or "both"
    start: float
    end: float
    max_fill: float        # the tallest wall it replaces, feet
    low_point: float       # the station where the ground is lowest
    carries: str = "road"  # what the structure would carry: "road" or "path"


def find(c, stations: list, ground_dz, rail=None) -> list:
    """Wall gaps (params.Gap, `auto` the wall's token) for one run's
    `stations` of corridor `c`, by start station. Each side is searched for
    outer walls and, on the path's side (V1.2 C), for strip walls apart, so
    a station may have one of each. `rail(s, side)`, when given, says
    whether a guardrail's widening stands on `side` at s (the family's
    second pass), so a slope it pushes past the footprint takes a wall
    too."""
    out = []
    for side in SIDES:
        edge = _path_edge(c, side)
        for location in ("outer", "strip"):
            if location == "strip" and (c.path is None or c.path.side != side):
                continue

            def need(s, sd, location=location):
                return needs_wall(c, s, sd, ground_dz,
                                  rail is not None and rail(s, sd), location)

            kinds = [need(s, side) for s in stations]
            i = 0
            while i < len(stations):
                kind = kinds[i]
                if kind is None:
                    i += 1
                    continue
                j = i
                while j + 1 < len(stations) and kinds[j + 1] == kind:
                    j += 1
                start = _reach(side, need, kind, stations[i],
                               stations[i - 1] if i > 0 else None, -1.0, edge)
                end = _reach(side, need, kind, stations[j],
                             stations[j + 1] if j + 1 < len(stations) else None, 1.0,
                             edge)
                out.append(Gap(start, end, "wall", side, None, auto=kind))
                i = j + 1
    return sorted(out, key=lambda g: (g.start, g.side))


def _path_edge(c, side: str):
    """edge(a, t): the path's first or last station between stations a and
    t (V1.2 C) when the path is on `side` and one of them is on its
    stations and the other not; else None. None for a side without the
    path."""
    p = c.path
    if p is None or p.side != side:
        return None

    def edge(a: float, t: float):
        if c.path_at(a) == c.path_at(t):
            return None
        lo, hi = min(a, t), max(a, t)
        return next((x for x in (p.s_start, p.s_end)
                     if lo - _EPS <= x <= hi + _EPS), None)
    return edge


def _reach(side: str, need_at, kind: str, s: float, neighbour, step: float,
           edge=None) -> float:
    """The wall's end, moved from station `s` toward `neighbour` (the next
    station, which does not need this wall; None at the run's end, where
    the wall ends at `s`) a foot at a time while the section a foot beyond
    still needs it, so its lead-in ends on a section that fits: the foot
    beyond, or `neighbour` when the foot beyond would pass it. ValueError
    where the foot beyond needs the other kind of wall, or the lead-in has
    no room before a section that does not fit.

    V1.2 C: the path's first and last stations (`edge`, _path_edge) are a
    break in the section: a road wall running into the path's stretch,
    where the path's side needs a wall of its own, ends there, and a path
    or strip wall begins there, each on its own side of it. A road cut
    wall ends its lead-in short of it, so the shoulder it widens
    (params.Corridor.width) is back to its width there and the path is
    placed from the unwidened edge from its first station."""
    if neighbour is None:
        return s
    first, t = s, s
    while True:
        t = s + step * WALL_TRANSITION_FT
        b = edge(s, t) if edge is not None else None
        if b is not None and (neighbour - b) * step >= -_EPS:
            need = need_at(t, side)
            if need is not None and need != kind:
                if kind != "cut":
                    return b
                e = b - step * WALL_TRANSITION_FT
                if (e - first) * step >= -_EPS:
                    return e
                raise ValueError(
                    f"walls: auto: the {side} cut wall ending at {sta(first)} "
                    f"has no room for its {WALL_TRANSITION_FT:g} ft lead-in "
                    f"before the path's stations at {sta(b)}; list a wall or "
                    f"a structure gap there")
        if (t - neighbour) * step > _EPS:
            # a foot on passes the neighbour: end the wall a foot short of
            # it, unless that is back inside the failing stations
            e = neighbour - step * WALL_TRANSITION_FT
            if (e - first) * step >= -_EPS:
                return e
            break
        need = need_at(t, side)
        if need is None:
            return s
        if need != kind:
            raise ValueError(
                f"walls: auto: the {side} side needs a "
                f"{kind if step > 0 else need} wall at {sta(min(s, t))} and a "
                f"{need if step > 0 else kind} wall at {sta(max(s, t))}, under "
                f"{2 * WALL_TRANSITION_FT:g} ft apart: no slope fits between "
                f"them; list a wall or a structure gap there")
        s = t
    if need_at(t, side) is not None:
        raise ValueError(
            f"walls: auto: the {side} {kind} wall ending at {sta(s)} has no "
            f"room for its {WALL_TRANSITION_FT:g} ft lead-in: the slope fits "
            f"at {sta(neighbour)} but not at {sta(t)}; list a wall or a "
            f"structure gap there")
    return s


def _height(c, g, s: float, ground_dz) -> tuple:
    """(exposed height at the face, the face's offset) of wall gap `g` at
    station s: a road wall's at its shoulder edge (V1.1); a wall on the
    path's outer side at o; a strip wall from its top (the road's edge of
    shoulder, or q) down to the level strip at its foot. ValueError for a
    token that is none of these."""
    if g.auto not in _KIND:
        raise ValueError(f"walls: an automatic wall's token {g.auto!r} is not "
                         f"one of {', '.join(_KIND)}")
    if g.auto in ("fill", "cut"):
        u, v = grade_edge(c, s, g.side)
        dz = ground_dz(s, u, v)
        return (-dz if g.auto == "fill" else dz), abs(u)
    from bimforge.author.corridor.path import surface
    sf = surface(c, s)
    if g.auto == "strip-road":
        return (sf.edge[1] - sf.q[1]) * sf.cg, abs(sf.edge[0])
    if g.auto == "strip-path":
        hinge_v = sf.edge[1] - c.depth()
        return (sf.q[1] - hinge_v) * sf.cg, abs(sf.q[0])
    if g.auto in ("path-fill", "path-cut"):
        dz = ground_dz(s, *sf.o)
        return (-dz if g.auto == "path-fill" else dz), abs(sf.o[0])
    raise AssertionError(g.auto)          # _KIND holds no other token


#: a wall's token -> its walls-table kind
_KIND = {"fill": "fill", "cut": "cut", "path-fill": "fill", "path-cut": "cut",
         "strip-road": "wall-road", "strip-path": "wall-path"}


def rows(c, secs: list, ground_dz) -> list:
    """One WallRow per automatic wall of `c`, by start station. Its exposed
    height at the face, at finished grade (no barrier, footing or
    embedment), and its offset are read at the stations of the sections
    `secs` (section.Section) on it and at least every HEIGHT_STEP_FT
    between its ends, so a peak in the ground between sections is not
    missed. A fill wall or a strip wall over max_wall_height_ft is too
    tall."""
    out = []
    for g in c.gaps:
        if g.auto is None:
            continue
        n = max(1, math.ceil((g.end - g.start) / HEIGHT_STEP_FT - _EPS))
        at = {g.start + (g.end - g.start) * i / n for i in range(n + 1)}
        at.update(sec.s for sec in secs if g.start - _EPS <= sec.s <= g.end + _EPS)
        heights, offsets = zip(*(_height(c, g, s, ground_dz) for s in sorted(at)))
        top, kind = max(heights), _KIND[g.auto]
        out.append(WallRow(g.side, kind, g.start, g.end, max(offsets),
                           min(heights), top,
                           kind != "cut" and top > c.max_wall_height + _EPS,
                           location="strip" if g.strip else "outer",
                           carries=g.carries))
    return sorted(out, key=lambda r: (r.start, r.side))


def structures(rows: list, stations: list, ground_elev) -> list:
    """The structure candidates: each too-tall wall's stretch, walls on the
    two sides that overlap and carry the same thing merged into one
    ("both"), with the tallest wall and the station of `stations` where
    `ground_elev(s)` (the ground at the centreline) is lowest."""
    groups = []
    for r in sorted((r for r in rows if r.too_tall), key=lambda r: (r.carries, r.start)):
        g = groups[-1] if groups else None
        if g is not None and g[4] == r.carries and r.start <= g[1] + _EPS:
            groups[-1] = (g[0], max(g[1], r.end), max(g[2], r.max_height),
                          g[3] | {r.side}, g[4])
        else:
            groups.append((r.start, r.end, r.max_height, {r.side}, r.carries))
    out = []
    for a, b, top, sides, carries in sorted(groups, key=lambda g: (g[0], g[4])):
        inside = [s for s in stations if a - _EPS <= s <= b + _EPS] or [a, b]
        out.append(StructureRow("both" if len(sides) > 1 else next(iter(sides)),
                                a, b, top, min(inside, key=ground_elev), carries))
    return out


def walls_csv(rows: list) -> str:
    return "\n".join([WALL_HEADER] + [
        f"{r.side},{r.kind},{r.start:.2f},{r.end:.2f},{r.offset:.2f},"
        f"{r.min_height:.2f},{r.max_height:.2f},"
        f"{'yes' if r.barrier else 'no'},{'yes' if r.too_tall else 'no'},"
        f"{r.location}"
        for r in rows]) + "\n"


def structures_csv(rows: list) -> str:
    return "\n".join([STRUCTURE_HEADER] + [
        f"{r.side},{r.start:.2f},{r.end:.2f},{r.max_fill:.2f},{r.low_point:.2f},"
        f"{r.carries}"
        for r in rows]) + "\n"
