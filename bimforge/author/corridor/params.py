"""road-corridor parameters (roadmap P.6): a spec's typical section, width
transitions, superelevation, gaps, stationing and mass-haul factors,
validated once and read by station.

Sides are "L" and "R" of travel. A cross slope is measured outward from the
crown, negative down. Offsets and stations are feet.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

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
#: the shoulder beside a wall in cut, feet (HDM Index 309.1(3)(b))
CUT_WALL_SHOULDER_FT = 10.0
#: guardrail runout length LR by design speed, feet (TSSM length-of-need
#: calculator, "Tables")
RUNOUT_FT = {45: 195.0, 50: 230.0}
#: MGS rail face to back of post: the 3 1/4 in W-beam, the 6 x 8 in block
#: holding the rail 8 in off the post, and a W6 post (2025 Standard Plans
#: A77N2, A77N3), feet
RAIL_DEPTH_FT = 1.44
#: back of post to the hinge, 30 in at least (A77N3 Detail A), feet
HINGE_BEHIND_POST_FT = 2.5
#: the widening behind the rail falls 1 in 10 (TSSM 3.6(5))
WIDENING_SLOPE = 0.1
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
class Steep:
    """Fill steeper than `Slopes.fill_ratio` over a height, behind guardrail."""
    ratio: float                   # horizontal per vertical, e.g. 2.0
    above_height: float            # fill at the hinge over this takes it, feet


@dataclass(frozen=True)
class Rock:
    """Rock under the soil in cut: its face, a bench at its surface."""
    depth: tuple                   # ((station, depth below ground), ...)
    ratio: float                   # the rock face, horizontal per vertical
    bench: float                   # the level bench's width, feet

    def depth_at(self, s: float) -> float:
        return interp(list(self.depth), s)


@dataclass(frozen=True)
class Guard:
    """The guardrail a steep fill takes (TSSM 3.6, A77N3)."""
    speed_mph: int                 # a RUNOUT_FT key
    rail_depth: float              # rail face to back of post, feet

    @property
    def widening(self) -> float:
        """Horizontal, from the shoulder edge (the rail face) to the hinge,
        falling at 10:1, feet."""
        return self.rail_depth + HINGE_BEHIND_POST_FT


@dataclass(frozen=True)
class Slopes:
    cut_ratio: float               # horizontal per vertical
    fill_ratio: float
    ditch: Ditch | None
    daylight_limit: float          # horizontal feet from the hinge
    steep: Steep | None = None     # V1.1: 2:1 behind guardrail over a height
    rock: Rock | None = None       # V1.1: rock in cut, with a bench
    footprint: dict | None = None  # V1.1: side -> farthest daylight, feet


@dataclass(frozen=True)
class Gap:
    start: float
    end: float
    kind: str                      # "structure" or "wall"
    side: str | None = None        # a wall's side
    offset: float | None = None    # a listed wall's face, feet from the
                                   # centreline; None: at the hinge
    auto: str | None = None        # an automatic wall's kind: "fill", "cut"


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
    #: V1.1: walls wherever a slope cannot fit (`walls: auto`)
    auto_walls: bool = False
    #: a fill wall taller than this is a structure candidate, feet
    max_wall_height: float = 30.0
    #: the guardrail a steep fill takes; None without a steep rule or a
    #: `guardrail:` block
    guard: Guard | None = None

    def width(self, comp: Component, side: str, s: float) -> float:
        """The component's width; through an automatic cut wall the
        outermost shoulder is CUT_WALL_SHOULDER_FT, reached linearly over
        the WALL_TRANSITION_FT lead-in at each end (HDM 309.1(3)(b))."""
        table = self.widths.get((comp.name, side))
        w = interp(table, s) if table else comp.width
        if not self.auto_walls or comp.name != self._widened():
            return w
        for g in self.gaps:
            if g.auto != "cut" or g.side != side:
                continue
            a, b = g.start - WALL_TRANSITION_FT, g.end + WALL_TRANSITION_FT
            if not a - _EPS <= s <= b + _EPS:
                continue
            full = max(w, CUT_WALL_SHOULDER_FT)
            if s < g.start:
                return w + (full - w) * (s - a) / WALL_TRANSITION_FT
            if s > g.end:
                return w + (full - w) * (b - s) / WALL_TRANSITION_FT
            return full
        return w

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

    def etw(self, side: str, s: float) -> float:
        """The edge of traveled way: the outer edge of the outermost
        carriageway component, feet from the crown."""
        out = edge = 0.0
        for comp in self.components:
            out += self.width(comp, side, s)
            if comp.kind == "carriageway":
                edge = out
        return edge

    def max_half_width(self) -> float:
        """The widest a side's components get anywhere in their width
        tables, feet; a cut wall's 10 ft shoulder is not counted."""
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

    def _widened(self) -> str | None:
        """The component a cut wall widens: the outermost shoulder."""
        names = [comp.name for comp in self.components if comp.kind == "shoulder"]
        return names[-1] if names else None

    def with_walls(self, walls) -> "Corridor":
        """This corridor with automatic wall gaps (`walls: auto`) added. A
        wall whose stations, its 1 ft lead-ins included, touch a listed wall
        gap on its side is refused, as is a cut wall with no shoulder to
        widen beside it."""
        walls = tuple(walls)
        for w in walls:
            for g in self.gaps:
                if (g.kind == "wall" and g.auto is None and g.side == w.side
                        and w.start - 2 * WALL_TRANSITION_FT < g.end + _EPS
                        and g.start - _EPS < w.end + 2 * WALL_TRANSITION_FT):
                    raise ValueError(
                        f"walls: auto puts a {w.auto} wall on the {w.side} side "
                        f"from {sta(w.start)} to {sta(w.end)}, against the "
                        f"listed wall gap {sta(g.start)} to {sta(g.end)}; list "
                        f"the wall or let walls: auto place it, not both")
            if w.auto == "cut" and self._widened() is None:
                raise ValueError(
                    f"walls: auto puts a cut wall on the {w.side} side from "
                    f"{sta(w.start)} to {sta(w.end)}; the 10 ft shoulder beside "
                    f"it needs a shoulder component to widen")
        # two automatic walls on a side need both lead-ins between them,
        # each ending on a slope that fits; closer, the side has neither a
        # wall nor a slope there, and a cut wall's widening reaches under
        # its neighbour
        autos = sorted((g for g in self.gaps + walls if g.auto is not None),
                       key=lambda g: (g.side, g.start))
        for p, q in zip(autos, autos[1:]):
            if p.side == q.side and q.start - p.end < 2 * WALL_TRANSITION_FT - _EPS:
                raise ValueError(
                    f"walls: auto puts a {p.auto} wall on the {p.side} side from "
                    f"{sta(p.start)} to {sta(p.end)} and a {q.auto} wall from "
                    f"{sta(q.start)} to {sta(q.end)}, under "
                    f"{2 * WALL_TRANSITION_FT:g} ft apart: no slope fits between "
                    f"them; list a wall or a structure gap there")
        return replace(self, gaps=tuple(sorted(self.gaps + walls,
                                               key=lambda g: (g.start, g.side or ""))))


def _num(value, where: str, positive: bool = True) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{where}: expected a number, got {value!r}") from None
    if not math.isfinite(x):
        raise ValueError(f"{where}: expected a finite number, got {x:g}")
    if positive and not x > 0.0:
        raise ValueError(f"{where}: must be positive, got {x:g}")
    return x


def _on_alignment(s, where: str, s_start: float, s_end: float) -> float:
    s = _num(s, where, positive=False)
    if not s_start - _EPS <= s <= s_end + _EPS:
        raise ValueError(f"{where}: station {sta(s)} is off the alignment "
                         f"({sta(s_start)} to {sta(s_end)})")
    return s


def _name(c: dict, where: str) -> str:
    if not isinstance(c, dict) or not str(c.get("name") or "").strip():
        raise ValueError(f"{where}.name: a name is required")
    return str(c["name"])


def _row(r, n: int, where: str, form: str) -> list:
    if not isinstance(r, (list, tuple)) or len(r) != n:
        raise ValueError(f"{where}: rows are {form}, got {r!r}")
    return list(r)


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
            _name(c, where), kind, _num(c.get("width"), f"{where}.width"),
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
        out.append(Course(_name(c, where), ctype,
                          _num(c.get("thickness"), f"{where}.thickness")))
    if not out:
        raise ValueError("section.courses: a corridor needs at least one course")
    return out


def _slopes(sec: dict, s_start: float, s_end: float) -> Slopes:
    ss = sec.get("side_slopes") or {}
    cut, fill = ss.get("cut") or {}, ss.get("fill") or {}
    ditch = None
    if cut.get("ditch"):
        d = cut["ditch"]
        width = _num(d.get("width"), "side_slopes.cut.ditch.width", positive=False)
        if width < 0.0:
            raise ValueError("side_slopes.cut.ditch.width: must not be negative")
        ditch = Ditch(width, _num(d.get("depth"), "side_slopes.cut.ditch.depth"))
    cut_ratio = _num(cut.get("ratio", 2.0), "side_slopes.cut.ratio")
    fill_ratio = _num(fill.get("ratio", 2.0), "side_slopes.fill.ratio")
    steep = None
    if fill.get("steep") is not None:
        st = fill["steep"]
        if not isinstance(st, dict):
            raise ValueError("side_slopes.fill.steep: a mapping "
                             "({ratio, above_height_ft})")
        steep = Steep(_num(st.get("ratio"), "side_slopes.fill.steep.ratio"),
                      _num(st.get("above_height_ft"),
                           "side_slopes.fill.steep.above_height_ft"))
        if not steep.ratio < fill_ratio:
            raise ValueError(f"side_slopes.fill.steep.ratio: {steep.ratio:g} is "
                             f"not steeper than fill.ratio {fill_ratio:g}")
    rock = None
    if cut.get("rock") is not None:
        rk = cut["rock"]
        if not isinstance(rk, dict):
            raise ValueError("side_slopes.cut.rock: a mapping "
                             "({depth_ft, ratio, bench_ft})")
        rock = Rock(_depth_rows(rk.get("depth_ft"), s_start, s_end),
                    _num(rk.get("ratio"), "side_slopes.cut.rock.ratio"),
                    _num(rk.get("bench_ft"), "side_slopes.cut.rock.bench_ft"))
        if not rock.ratio < cut_ratio:
            raise ValueError(f"side_slopes.cut.rock.ratio: {rock.ratio:g} is "
                             f"not steeper than cut.ratio {cut_ratio:g}")
    footprint = None
    if ss.get("footprint_ft") is not None:
        fp = ss["footprint_ft"]
        if not isinstance(fp, dict) or not set(fp) <= set(SIDES):
            raise ValueError("side_slopes.footprint_ft: a mapping of L and R "
                             "offsets from the centreline, feet")
        footprint = {side: _num(fp[side], f"side_slopes.footprint_ft.{side}")
                     for side in SIDES if side in fp}
    return Slopes(cut_ratio, fill_ratio, ditch,
                  _num(ss.get("daylight_limit_ft", 150.0),
                       "side_slopes.daylight_limit_ft"),
                  steep=steep, rock=rock, footprint=footprint)


def _depth_rows(value, s_start: float, s_end: float) -> tuple:
    """Rock depth: one number, or [station, depth] rows on the alignment
    (read as widths are: linear, the end values holding)."""
    where = "side_slopes.cut.rock.depth_ft"
    if isinstance(value, (list, tuple)):
        rows = tuple((_on_alignment(s, where, s_start, s_end), _num(d, where))
                     for s, d in (_row(r, 2, where, "[station, depth]")
                                  for r in value))
        if not rows:
            raise ValueError(f"{where}: needs [station, depth] rows")
        _ascending([s for s, _d in rows], where)
        return rows
    return ((float(s_start), _num(value, where)),)


def _guard(gp, steep: bool) -> Guard | None:
    """The `guardrail:` block; a steep rule brings one at its defaults."""
    if gp is not None and not isinstance(gp, dict):
        raise ValueError("guardrail: a mapping ({design_speed_mph: 45})")
    if gp is None and not steep:
        return None
    gp = gp or {}
    speed = _num(gp.get("design_speed_mph", 45), "guardrail.design_speed_mph")
    if speed not in RUNOUT_FT:
        raise ValueError(f"guardrail.design_speed_mph: {speed:g} mph is not in "
                         f"the runout table ({', '.join(str(k) for k in RUNOUT_FT)} mph)")
    return Guard(int(speed), _num(gp.get("rail_depth_ft", RAIL_DEPTH_FT),
                                  "guardrail.rail_depth_ft"))


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
                for s, v in (_row(r, 2, where, "[station, width]")
                             for r in w.get("at") or [])]
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
        r = _row(r, 3, where, "[station, left, right]")
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
    for i, p in enumerate(out):
        for q in out[i + 1:]:
            # walls on opposite sides may share stations; nothing else may
            if (q.start < p.end - _EPS
                    and (p.kind == "structure" or q.kind == "structure"
                         or p.side == q.side)):
                raise ValueError(f"gaps: {sta(p.start)} to {sta(p.end)} "
                                 f"overlaps {sta(q.start)} to {sta(q.end)}")
    return out


def parse(params: dict, s_start: float, s_end: float) -> Corridor:
    """The corridor `params` describe on an alignment from `s_start` to
    `s_end`; ValueError names the first field that is wrong."""
    if not float(s_end) > float(s_start):
        raise ValueError(f"alignment: ends at {sta(s_end)}, not past its "
                         f"start {sta(s_start)}")
    sec = params.get("section") or {}
    crown = sec.get("crown", "centerline")
    if crown != "centerline":
        raise ValueError(f"section.crown: {crown!r} is not supported; the "
                         f"crown is the centerline (crown: centerline)")
    comps = _components(sec)
    st = params.get("stations") or {}
    mh = params.get("mass_haul") or {}
    shrink = _num(mh.get("shrink", 0.0), "mass_haul.shrink", positive=False)
    swell = _num(mh.get("swell", 0.0), "mass_haul.swell", positive=False)
    if not 0.0 <= shrink < 1.0:
        raise ValueError("mass_haul.shrink: must be at least 0 and below 1")
    if swell < 0.0:
        raise ValueError("mass_haul.swell: must not be negative")
    slopes = _slopes(sec, s_start, s_end)
    walls = params.get("walls")
    if walls is not None and walls != "auto":
        raise ValueError(f"walls: {walls!r} is not 'auto'; a wall at stations "
                         f"you choose is a gap (gaps: [{{kind: wall, side, "
                         f"offset, from, to}}])")
    return Corridor(
        s_start=float(s_start), s_end=float(s_end),
        components=tuple(comps), courses=tuple(_courses(sec)),
        slopes=slopes,
        widths=_widths(params, [c.name for c in comps], s_start, s_end),
        superelevation=tuple(_superelevation(params, s_start, s_end)),
        gaps=tuple(_gaps(params, s_start, s_end)),
        interval=_num(st.get("interval", 25.0), "stations.interval"),
        band=_num(st.get("band", 100.0), "stations.band"),
        shrink=shrink, swell=swell,
        auto_walls=walls == "auto",
        max_wall_height=_num(params.get("max_wall_height_ft", 30.0),
                             "max_wall_height_ft"),
        guard=_guard(params.get("guardrail"), slopes.steep is not None))
