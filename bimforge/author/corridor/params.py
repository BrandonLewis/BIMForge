"""road-corridor parameters (roadmap P.6): a spec's typical section, width
transitions, superelevation, gaps, stationing and mass-haul factors,
validated once and read by station.

Sides are "L" and "R" of travel. A cross slope is measured outward from the
crown, negative down. Offsets and stations are feet.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from bimforge.author.alignment import sta

#: component kind -> IfcRoadPartTypeEnum
PART_TYPES = {"carriageway": "CARRIAGEWAY", "shoulder": "SHOULDER",
              "median": "CENTRALRESERVE"}
#: the IfcCourseTypeEnum values a course may take
COURSE_TYPES = ("ARMOUR", "BALLASTBED", "CORE", "FILTER", "PAVEMENT",
                "PROTECTION")
SIDES = ("L", "R")
#: both sides' cross slope with no superelevation table
NORMAL_CROWN = -0.02
#: sections are cut this far outside each wall gap, so the side slope turns
#: into the wall within it, feet
WALL_TRANSITION_FT = 1.0
_EPS = 1e-9


def interp(table: list, s: float) -> float:
    """Linear in station between [(station, value)] rows; the end value
    holds outside them."""
    if s <= table[0][0]:
        return table[0][1]
    for (s0, v0), (s1, v1) in zip(table, table[1:]):
        if s <= s1:
            return v0 + (v1 - v0) * (s - s0) / (s1 - s0)
    return table[-1][1]


@dataclass(frozen=True)
class Component:
    name: str
    kind: str                      # a PART_TYPES key
    width: float
    slope: float | None = None     # its own cross slope; None: the side's


@dataclass(frozen=True)
class Course:
    name: str
    type: str                      # a COURSE_TYPES value
    thickness: float


@dataclass(frozen=True)
class Ditch:
    width: float
    depth: float


@dataclass(frozen=True)
class Slopes:
    cut_ratio: float               # horizontal per vertical
    fill_ratio: float
    ditch: Ditch | None
    daylight_limit: float          # horizontal feet from the hinge


@dataclass(frozen=True)
class Gap:
    start: float
    end: float
    kind: str                      # "structure" or "wall"
    side: str | None = None        # a wall's side
    offset: float | None = None    # a wall's face, feet from the centreline


@dataclass(frozen=True)
class Corridor:
    s_start: float
    s_end: float
    components: tuple
    courses: tuple
    slopes: Slopes
    widths: dict                   # (component name, side) -> [(s, width)]
    superelevation: tuple          # ((s, left, right), ...)
    gaps: tuple                    # by start station
    interval: float
    band: float
    shrink: float
    swell: float

    def width(self, comp: Component, side: str, s: float) -> float:
        table = self.widths.get((comp.name, side))
        return interp(table, s) if table else comp.width

    def cross_slope(self, side: str, s: float) -> float:
        if not self.superelevation:
            return NORMAL_CROWN
        col = 1 if side == "L" else 2
        return interp([(r[0], r[col]) for r in self.superelevation], s)

    def depth(self) -> float:
        """Every course's thickness: finished grade to subgrade."""
        return sum(c.thickness for c in self.courses)

    def wall(self, side: str, s: float) -> Gap | None:
        for g in self.gaps:
            if (g.kind == "wall" and g.side == side
                    and g.start - _EPS <= s <= g.end + _EPS):
                return g
        return None

    def max_half_width(self) -> float:
        """The widest a side's components get anywhere, feet."""
        return max(sum(max([comp.width] + [w for _s, w in
                                            self.widths.get((comp.name, side), ())])
                       for comp in self.components)
                   for side in SIDES)

    def runs(self) -> list:
        """[(s0, s1)]: the alignment less its structure gaps."""
        out, s = [], self.s_start
        for g in self.gaps:
            if g.kind != "structure":
                continue
            if g.start - s > _EPS:
                out.append((s, g.start))
            s = g.end
        if self.s_end - s > _EPS:
            out.append((s, self.s_end))
        return out

    def stations(self, s0: float, s1: float, extra=()) -> list:
        """Where to cut sections on [s0, s1]: every `interval` and `band`
        from the alignment's start, every table and gap station, 1 ft
        outside each wall gap, and `extra` (the geometry's own points)."""
        cuts = {s0, s1}
        for step in (self.interval, self.band):
            k = math.ceil((s0 - self.s_start) / step - _EPS)
            while self.s_start + k * step < s1 - _EPS:
                cuts.add(self.s_start + k * step)
                k += 1
        cuts.update(s for table in self.widths.values() for s, _w in table)
        cuts.update(r[0] for r in self.superelevation)
        for g in self.gaps:
            cuts.update((g.start, g.end))
            if g.kind == "wall":
                cuts.update((g.start - WALL_TRANSITION_FT,
                             g.end + WALL_TRANSITION_FT))
        cuts.update(extra)
        out = []
        for s in sorted(x for x in cuts if s0 - _EPS <= x <= s1 + _EPS):
            if not out or s - out[-1] > 1e-6:
                out.append(min(max(s, s0), s1))
        out[-1] = s1
        return out


def _num(value, where: str, positive: bool = True) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{where}: expected a number, got {value!r}") from None
    if positive and not x > 0.0:
        raise ValueError(f"{where}: must be positive, got {x:g}")
    return x


def _on_alignment(s, where: str, s_start: float, s_end: float) -> float:
    s = _num(s, where, positive=False)
    if not s_start - _EPS <= s <= s_end + _EPS:
        raise ValueError(f"{where}: station {sta(s)} is off the alignment "
                         f"({sta(s_start)} to {sta(s_end)})")
    return s


def _ascending(stations: list, where: str) -> None:
    if any(b <= a for a, b in zip(stations, stations[1:])):
        raise ValueError(f"{where}: stations must be strictly ascending")


def _components(sec: dict) -> list:
    out = []
    for i, c in enumerate(sec.get("components") or []):
        where = f"section.components[{i}]"
        kind = str(c.get("kind", "")).lower()
        if kind not in PART_TYPES:
            raise ValueError(f"{where}: kind {c.get('kind')!r} is not one of "
                             f"{sorted(PART_TYPES)}")
        slope = c.get("slope")
        out.append(Component(
            str(c["name"]), kind, _num(c.get("width"), f"{where}.width"),
            None if slope is None else _num(slope, f"{where}.slope",
                                            positive=False)))
    if not out:
        raise ValueError("section.components: a corridor needs at least one "
                         "component")
    names = [c.name for c in out]
    if len(set(names)) != len(names):
        raise ValueError("section.components: names must be distinct")
    return out


def _courses(sec: dict) -> list:
    out = []
    for i, c in enumerate(sec.get("courses") or []):
        where = f"section.courses[{i}]"
        ctype = str(c.get("type", "")).upper()
        if ctype not in COURSE_TYPES:
            raise ValueError(f"{where}: type {c.get('type')!r} is not one of "
                             f"{COURSE_TYPES}")
        out.append(Course(str(c["name"]), ctype,
                          _num(c.get("thickness"), f"{where}.thickness")))
    if not out:
        raise ValueError("section.courses: a corridor needs at least one course")
    return out


def _slopes(sec: dict) -> Slopes:
    ss = sec.get("side_slopes") or {}
    cut, fill = ss.get("cut") or {}, ss.get("fill") or {}
    ditch = None
    if cut.get("ditch"):
        d = cut["ditch"]
        width = _num(d.get("width"), "side_slopes.cut.ditch.width", positive=False)
        if width < 0.0:
            raise ValueError("side_slopes.cut.ditch.width: must not be negative")
        ditch = Ditch(width, _num(d.get("depth"), "side_slopes.cut.ditch.depth"))
    return Slopes(_num(cut.get("ratio", 2.0), "side_slopes.cut.ratio"),
                  _num(fill.get("ratio", 2.0), "side_slopes.fill.ratio"),
                  ditch,
                  _num(ss.get("daylight_limit_ft", 150.0),
                       "side_slopes.daylight_limit_ft"))


def _widths(params: dict, names: list, s_start: float, s_end: float) -> dict:
    out = {}
    for i, w in enumerate(params.get("widths") or []):
        where = f"widths[{i}]"
        if w.get("component") not in names:
            raise ValueError(f"{where}: no component named {w.get('component')!r}")
        side = str(w.get("side", "")).upper()
        if side not in SIDES:
            raise ValueError(f"{where}: side must be L or R")
        rows = [(_on_alignment(s, where, s_start, s_end),
                 _num(v, f"{where} width", positive=False))
                for s, v in w.get("at") or []]
        if not rows:
            raise ValueError(f"{where}: 'at' needs [station, width] rows")
        _ascending([s for s, _v in rows], where)
        for s, v in rows:
            if v <= 0.0:
                raise ValueError(f"{where}: width {v:g} at station {sta(s)} "
                                 f"must be positive")
        if (w["component"], side) in out:
            raise ValueError(f"{where}: a second table for {w['component']} {side}")
        out[w["component"], side] = rows
    return out


def _superelevation(params: dict, s_start: float, s_end: float) -> list:
    out = []
    for i, r in enumerate(params.get("superelevation") or []):
        where = f"superelevation[{i}]"
        if len(r) != 3:
            raise ValueError(f"{where}: rows are [station, left, right]")
        out.append((_on_alignment(r[0], where, s_start, s_end),
                    _num(r[1], where, positive=False),
                    _num(r[2], where, positive=False)))
    _ascending([r[0] for r in out], "superelevation")
    return out


def _gaps(params: dict, s_start: float, s_end: float) -> list:
    out = []
    for i, g in enumerate(params.get("gaps") or []):
        where = f"gaps[{i}]"
        a = _on_alignment(g.get("from"), where, s_start, s_end)
        b = _on_alignment(g.get("to"), where, s_start, s_end)
        if b <= a:
            raise ValueError(f"{where}: 'to' must be past 'from'")
        kind = str(g.get("kind", "")).lower()
        if kind == "structure":
            out.append(Gap(a, b, kind))
        elif kind == "wall":
            side = str(g.get("side", "")).upper()
            if side not in SIDES:
                raise ValueError(f"{where}: a wall gap needs side L or R")
            out.append(Gap(a, b, kind, side, _num(g.get("offset"), f"{where}.offset")))
        else:
            raise ValueError(f"{where}: kind {g.get('kind')!r} is not "
                             f"'structure' or 'wall'")
    out.sort(key=lambda g: g.start)
    for p, q in zip(out, out[1:]):
        if q.start < p.end - _EPS:
            raise ValueError(f"gaps: {sta(p.start)} to {sta(p.end)} overlaps "
                             f"{sta(q.start)} to {sta(q.end)}")
    return out


def parse(params: dict, s_start: float, s_end: float) -> Corridor:
    """The corridor `params` describe on an alignment from `s_start` to
    `s_end`; ValueError names the first field that is wrong."""
    sec = params.get("section") or {}
    comps = _components(sec)
    st = params.get("stations") or {}
    mh = params.get("mass_haul") or {}
    shrink = _num(mh.get("shrink", 0.0), "mass_haul.shrink", positive=False)
    swell = _num(mh.get("swell", 0.0), "mass_haul.swell", positive=False)
    if not 0.0 <= shrink < 1.0:
        raise ValueError("mass_haul.shrink: must be at least 0 and below 1")
    if swell < 0.0:
        raise ValueError("mass_haul.swell: must not be negative")
    return Corridor(
        s_start=float(s_start), s_end=float(s_end),
        components=tuple(comps), courses=tuple(_courses(sec)),
        slopes=_slopes(sec),
        widths=_widths(params, [c.name for c in comps], s_start, s_end),
        superelevation=tuple(_superelevation(params, s_start, s_end)),
        gaps=tuple(_gaps(params, s_start, s_end)),
        interval=_num(st.get("interval", 25.0), "stations.interval"),
        band=_num(st.get("band", 100.0), "stations.band"),
        shrink=shrink, swell=swell)
