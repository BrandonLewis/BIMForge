"""A shared-use path beside the road corridor (P.6, V1.2 part C): parsed
from `params.path`, placed on the road's section by station, and checked
against the Caltrans Class I bikeway standards (HDM Index 1003.1).

Spec: docs/superpowers/specs/2026-11-22-road-corridor-path-design.md.

While it is beside the road the path is the outer part of one side of the
road's section: its paved inner edge `separation` ft out from the road's
outer edge of shoulder, at the elevation its own profile gives on road
stations. Section coordinates are section.py's: u left of travel, v up from
the road's profile grade line in the plane square to the road's 3D tangent.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from bimforge.author.alignment import Profile, sta
from bimforge.author.corridor.params import (COURSE_TYPES, SIDES, WALL_TRANSITION_FT,
                                             Course, _ascending, _name, _num,
                                             _on_alignment, _row, interp)

#: the least separation from the road's edge of shoulder to the path's
#: paved edge, outside an approach, feet (HDM 1003.1(7))
MIN_SEPARATION_FT = 5.0
#: under this separation a barrier is needed (1003.1(7)), feet
BARRIER_SEPARATION_FT = 10.0
#: the path's cross slope, magnitude (1003.1(16), DIB 82)
CROSS_SLOPE = (0.01, 0.02)
#: the graded shoulders' slope, magnitude (1003.1(16))
SHOULDER_SLOPE = (0.02, 0.05)
#: the design speeds Table 1003.1 gives, mph
DESIGN_SPEEDS = (20, 30)
#: a profile meets a deck, or another profile, within this, feet
MEET_TOL_FT = 0.01
#: the path's section turns into the road's own over this at the path's
#: ends, as a V1 section turns into a wall gap, feet
PATH_TRANSITION_FT = 1.0
#: the earthwork's step down a course's edge, as section.GUARD_STEP_FT: a
#: vertical face would put two columns on one plan edge, feet
STEP_FT = 0.01
#: points on the ground between the road's slope and the path's, where
#: natural ground is left between them
GROUND_SAMPLES = 8
#: the keys `params.path` takes
KEYS = {"side", "stations", "separation", "width", "cross_slope", "shoulder",
        "courses", "profile", "design_speed_mph", "strip", "approach_ft",
        "deck_separation_ft", "rail_height_ft"}
_EPS = 1e-9
#: how far outside an approach validate looks, feet: separation is linear
#: between its rows, so a violation just outside is a violation at the edge
_NEAR = 1e-6


@dataclass(frozen=True)
class Path:
    """The path beside the road (`params.path`), and the road's alignment
    and profile it is placed against."""
    side: str                      # "L" or "R" of travel
    s_start: float                 # its stations, road stations
    s_end: float
    separation: tuple              # ((station, ft), ...): the road's outer
                                   # edge of shoulder to the paved inner edge
    width: float                   # paved, feet
    cross_slope: float             # negative: parse takes the magnitude, falling
                                   # away from the road, whatever sign is given
    shoulder_width: float          # each graded shoulder, feet
    shoulder_slope: float          # negative: down away from the paved path
    courses: tuple                 # params.Course, top down, under the paved width
    profile: Profile               # the paved inner edge's elevation, road stations
    design_speed: int              # 20 or 30 mph (Table 1003.1)
    strip_ratio: float             # the steepest slope between road and path
    approach: float                # ft from a structure gap's end
    deck_separation: float         # the deck's barrier between traffic and path
    rail_height: float             # the path's rail on a wall, feet
    road_profile: Profile          # the road's
    alignment: object              # the road's

    @property
    def sign(self) -> float:
        """+1 on the left, -1 on the right: u = edge u + sign x distance out."""
        return 1.0 if self.side == "L" else -1.0

    def separation_at(self, s: float) -> float:
        return interp(list(self.separation), s)

    def depth(self) -> float:
        """The courses' thickness, normal to the path's grade."""
        return sum(x.thickness for x in self.courses)

    def covers(self, s: float) -> bool:
        return self.s_start - _EPS <= s <= self.s_end + _EPS


def _separation(value, s0: float, s1: float) -> tuple:
    where = "path.separation"
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError(f"{where}: needs [station, ft] rows")
    rows = tuple((_on_alignment(s, where, s0, s1), _num(v, where))
                 for s, v in (_row(r, 2, where, "[station, ft]") for r in value))
    _ascending([s for s, _v in rows], where)
    return rows


def _courses(value, where: str = "path.courses") -> list:
    out = []
    if value is not None and not isinstance(value, (list, tuple)):
        raise ValueError(f"{where}: a list of {{name, type, thickness}}, got {value!r}")
    for i, x in enumerate(value or []):
        at = f"{where}[{i}]"
        if not isinstance(x, dict):
            raise ValueError(f"{at}: a mapping ({{name, type, thickness}}), got {x!r}")
        ctype = str(x.get("type", "")).upper()
        if ctype not in COURSE_TYPES:
            raise ValueError(f"{at}: type {x.get('type')!r} is not one of "
                             f"{COURSE_TYPES}")
        out.append(Course(_name(x, at), ctype,
                          _num(x.get("thickness"), f"{at}.thickness")))
    if not out:
        raise ValueError(f"{where}: needs at least one course")
    return out


def _profile(value, where: str, s0: float, s1: float) -> Profile:
    """A profile in params.profile's form (`{curves: [...]}`): each curve
    whole (its EVC where its length and grades put it, within MEET_TOL_FT),
    the tangents between them continuous, covering stations s0 to s1."""
    if (not isinstance(value, dict) or not isinstance(value.get("curves"), list)
            or not value["curves"]):
        raise ValueError(f"{where}: a profile is {{curves: [...]}}, as params.profile")
    keys = ("bvc_station", "bvc_elev", "g_in_pct", "g_out_pct", "length_ft",
            "evc_station", "evc_elev")
    curves = []
    for i, cv in enumerate(value["curves"]):
        at = f"{where}.curves[{i}]"
        if not isinstance(cv, dict):
            raise ValueError(f"{at}: a mapping ({', '.join(keys)})")
        row = {k: _num(cv.get(k), f"{at}.{k}", positive=(k == "length_ft"))
               for k in keys}
        if abs(row["bvc_station"] + row["length_ft"] - row["evc_station"]) > MEET_TOL_FT:
            raise ValueError(f"{at}: evc_station {sta(row['evc_station'])} is not "
                             f"bvc_station + length_ft")
        g1, g2 = row["g_in_pct"] / 100.0, row["g_out_pct"] / 100.0
        length = row["length_ft"]
        z = row["bvc_elev"] + g1 * length + 0.5 * (g2 - g1) * length
        if abs(z - row["evc_elev"]) > MEET_TOL_FT:
            raise ValueError(f"{at}: evc_elev {row['evc_elev']:g} is not the "
                             f"curve's {z:.4f}")
        curves.append(row)
    for i, (a, b) in enumerate(zip(curves, curves[1:])):
        at = f"{where}.curves[{i + 1}]"
        if b["bvc_station"] < a["evc_station"] - _EPS:
            raise ValueError(f"{at}: starts at {sta(b['bvc_station'])}, inside the "
                             f"curve before it")
        if abs(a["g_out_pct"] - b["g_in_pct"]) > 1e-9:
            raise ValueError(f"{at}: g_in_pct {b['g_in_pct']:g} is not the grade "
                             f"before it, {a['g_out_pct']:g}")
        z = a["evc_elev"] + a["g_out_pct"] / 100.0 * (b["bvc_station"] - a["evc_station"])
        if abs(z - b["bvc_elev"]) > MEET_TOL_FT:
            raise ValueError(f"{at}: bvc_elev {b['bvc_elev']:g} is off the tangent "
                             f"before it ({z:.4f})")
    first, last = curves[0]["bvc_station"], curves[-1]["evc_station"]
    if first > s0 + _EPS or last < s1 - _EPS:
        raise ValueError(f"{where}: covers {sta(first)} to {sta(last)}, not the "
                         f"path's {sta(s0)} to {sta(s1)}")
    return Profile(curves)


def parse_path(pp, c, alignment, profile) -> Path:
    """The path `pp` (`params.path`) describes beside corridor `c`
    (params.Corridor), placed against the road's `alignment` and `profile`;
    ValueError names the first field that is wrong."""
    if not isinstance(pp, dict):
        raise ValueError("path: a mapping ({side, separation, width, courses, "
                         "profile, ...})")
    unknown = sorted(set(pp) - KEYS)
    if unknown:
        raise ValueError(f"path: unknown keys {unknown}")
    if alignment is None or profile is None:
        raise ValueError("path: needs the road's alignment and profile "
                         "(params.parse(..., alignment=, profile=))")
    side = str(pp.get("side", "")).upper()
    if side not in SIDES:
        raise ValueError(f"path.side: {pp.get('side')!r} is not L or R")
    s0, s1 = c.s_start, c.s_end
    if pp.get("stations") is not None:
        st = _row(pp["stations"], 2, "path.stations", "[from, to]")
        s0 = _on_alignment(st[0], "path.stations", c.s_start, c.s_end)
        s1 = _on_alignment(st[1], "path.stations", c.s_start, c.s_end)
        if not s1 > s0:
            raise ValueError(f"path.stations: 'to' {sta(s1)} must be past 'from' "
                             f"{sta(s0)}")
    separation = _separation(pp.get("separation"), c.s_start, c.s_end)
    width = _num(pp.get("width"), "path.width")
    cs = _num(pp.get("cross_slope", -0.02), "path.cross_slope", positive=False)
    if not CROSS_SLOPE[0] - _EPS <= abs(cs) <= CROSS_SLOPE[1] + _EPS:
        raise ValueError(f"path.cross_slope: {cs:g} is outside 1-2 % "
                         f"(HDM 1003.1(16), DIB 82)")
    cs = -abs(cs)                  # always falling away from the road
    sh = pp.get("shoulder") or {}
    if not isinstance(sh, dict):
        raise ValueError("path.shoulder: a mapping ({width, slope})")
    sw = _num(sh.get("width", 2.0), "path.shoulder.width")
    ss = _num(sh.get("slope", -0.05), "path.shoulder.slope", positive=False)
    if ss >= 0.0:
        raise ValueError(f"path.shoulder.slope: {ss:g} does not slope away from "
                         f"the path; give it negative (HDM 1003.1(16))")
    if not SHOULDER_SLOPE[0] - _EPS <= -ss <= SHOULDER_SLOPE[1] + _EPS:
        raise ValueError(f"path.shoulder.slope: {ss:g} is outside 2-5 % "
                         f"(HDM 1003.1(16))")
    speed = _num(pp.get("design_speed_mph", 20), "path.design_speed_mph")
    if speed not in DESIGN_SPEEDS:
        raise ValueError(f"path.design_speed_mph: {speed:g} is not 20 or 30 "
                         f"(HDM Table 1003.1)")
    strip = pp.get("strip") or {}
    if not isinstance(strip, dict):
        raise ValueError("path.strip: a mapping ({max_ratio})")
    courses = _courses(pp.get("courses"))
    return Path(
        side=side, s_start=float(s0), s_end=float(s1), separation=separation,
        width=width, cross_slope=cs, shoulder_width=sw, shoulder_slope=ss,
        courses=tuple(courses),
        profile=_profile(pp.get("profile"), "path.profile", s0, s1),
        design_speed=int(speed),
        strip_ratio=_num(strip.get("max_ratio", 2.0), "path.strip.max_ratio"),
        approach=_num(pp.get("approach_ft", 100.0), "path.approach_ft"),
        deck_separation=_num(pp.get("deck_separation_ft", 1.5),
                             "path.deck_separation_ft"),
        rail_height=_num(pp.get("rail_height_ft", 3.5), "path.rail_height_ft"),
        road_profile=profile, alignment=alignment)


def stations_extra(c) -> list:
    """The stations a corridor with a path cuts sections at, beside V1.1's:
    the path's ends and a foot outside them (where its section turns into
    the road's own), its separation rows, its vertical curves' BVC, PVI and
    EVC, and enough inside each curve to hold its chords to
    sweep.VC_SAGITTA_FT (frame.densify does this for the road's profile
    only)."""
    from bimforge.author.sweep import VC_SAGITTA_FT
    p = c.path
    out = [p.s_start, p.s_end]
    out += [x for x in (p.s_start - PATH_TRANSITION_FT, p.s_end + PATH_TRANSITION_FT)
            if c.s_start + _EPS < x < c.s_end - _EPS]
    out += [s for s, _v in p.separation]
    for cv in p.profile.curves:
        a, length = cv["bvc_station"], cv["length_ft"]
        out += [a, a + 0.5 * length, cv["evc_station"]]
        dg = abs(cv["g_out_pct"] - cv["g_in_pct"]) / 100.0
        if dg > 1e-12:
            n = math.ceil(length / math.sqrt(8.0 * VC_SAGITTA_FT * length / dg) - _EPS)
            out += [a + length * i / n for i in range(1, n)]
    return out


def approaches(c) -> list:
    """[(a, b, end)]: the stretches within approach_ft of a structure gap's
    end on the path's stations, where the separation may narrow to the
    deck's (HDM 1003.1(7)); `end` is the gap end each leads to."""
    p = c.path
    out = []
    for g in c.gaps:
        if g.kind != "structure":
            continue
        if p.covers(g.start):
            out.append((g.start - p.approach, g.start, g.start))
        if p.covers(g.end):
            out.append((g.end, g.end + p.approach, g.end))
    return out


def on_approach(c, s: float) -> bool:
    """Whether station s is on an approach (edges included)."""
    return any(a - _EPS <= s <= b + _EPS for a, b, _e in approaches(c))


def deck_elevation(c, s: float) -> float:
    """The deck at the path's paved edge at station s: the road's edge of
    shoulder, then the road's cross slope there (superelevation included)
    over the separation."""
    from bimforge.author.corridor.section import grade_edge
    p = c.path
    prof = p.road_profile
    g = prof.grade(s)
    _u, v = grade_edge(c, s, p.side)
    return (prof.elev(s) + v / math.sqrt(1.0 + g * g)
            + c.cross_slope(p.side, s) * p.separation_at(s))


def _on_deck(c, s: float) -> bool:
    return any(g.kind == "structure" and g.start + _EPS < s < g.end - _EPS
               for g in c.gaps)


def validate(c) -> None:
    """The path's checks that need the whole corridor `c`; ValueError names
    the field and the station."""
    p = c.path
    for g in c.gaps:
        if (g.kind == "wall" and g.auto is None and g.side == p.side
                and g.start < p.s_end + 2 * WALL_TRANSITION_FT + _EPS
                and g.end > p.s_start - 2 * WALL_TRANSITION_FT - _EPS):
            raise ValueError(
                f"gaps: a listed wall gap on the {g.side} side, {sta(g.start)} to "
                f"{sta(g.end)}, overlaps the path's stations ({sta(p.s_start)} to "
                f"{sta(p.s_end)}): its offset would be ambiguous; use walls: auto")
    zones = approaches(c)
    at = {s for s, _v in p.separation} | {p.s_start, p.s_end}
    for a, b, _e in zones:
        at |= {a, b, a - _NEAR, b + _NEAR}
    for g in c.gaps:
        if g.kind == "structure":
            at |= {g.start, g.end}
    for s in sorted(at):
        if not p.covers(s) or _on_deck(c, s):
            continue
        sep = p.separation_at(s)
        if sep < p.deck_separation - _EPS:
            raise ValueError(f"path.separation: {sep:.2f} ft at {sta(s)} is under "
                             f"deck_separation_ft {p.deck_separation:g}")
        if (sep < MIN_SEPARATION_FT - _EPS
                and not any(a - _EPS <= s <= b + _EPS for a, b, _e in zones)):
            before = [za for za, _zb, _ze in zones if 0.0 < za - s <= 2 * _NEAR]
            where = (f"just before the approach that starts at {sta(before[0])}"
                     if before else f"at {sta(s)}")
            raise ValueError(
                f"path.separation: {sep:.2f} ft {where} is under the "
                f"{MIN_SEPARATION_FT:g} ft minimum (HDM 1003.1(7)) outside an "
                f"approach to a structure gap")
    for e in sorted({e for _a, _b, e in zones}):
        sep = p.separation_at(e)
        if abs(sep - p.deck_separation) > MEET_TOL_FT + _EPS:
            raise ValueError(
                f"path.separation: {sep:.2f} ft at the structure gap's end "
                f"{sta(e)} is not deck_separation_ft {p.deck_separation:g}: the "
                f"path meets the deck there")
        got, deck = p.profile.elev(e), deck_elevation(c, e)
        if abs(got - deck) > MEET_TOL_FT + _EPS:
            raise ValueError(
                f"path.profile: at the structure gap's end {sta(e)} the path is at "
                f"{got:.4f} ft and the deck at its paved edge {deck:.4f} ft, "
                f"{abs(got - deck):.4f} ft off (more than {MEET_TOL_FT:g} ft)")
