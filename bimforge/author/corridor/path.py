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
        "deck_separation_ft", "rail_height_ft", "gaps", "equestrian"}
#: the keys `path.equestrian` takes
EQ_KEYS = {"width", "buffer", "clear_ft", "cross_slope", "courses", "fence",
           "fence_height_ft", "rail_height_ft"}
_EPS = 1e-9
#: how far outside an approach validate looks, feet: separation is linear
#: between its rows, so a violation just outside is a violation at the edge
_NEAR = 1e-6
#: section_v's rounds before it gives up, and the least 1 - kappa u it takes
SECTION_V_ROUNDS = 50
MIN_CURVE_SCALE = 1e-6


@dataclass(frozen=True)
class PathGap:
    """A stretch where the path is on a structure of its own (`path.gaps`),
    road stations; the structure is its own family's."""
    start: float
    end: float


@dataclass(frozen=True)
class Equestrian:
    """An unpaved equestrian tread beside the paved path, away from the road,
    a buffer between them (USFS-EDG Ch. 3): one shared-use corridor with
    separate treads. Its figures are guidance: defaults and advisories."""
    width: float           # the tread, feet (Table 4-2: 8-12 two-way)
    buffer: float          # paved edge to tread edge, feet
    clear: float           # graded clear each side, feet (Table 4-1)
    cross_slope: float     # negative: down away from the road (Table 4-4)
    courses: tuple         # params.Course: its surfacing, top down
    fence: bool            # an open rail fence on the tread side of the buffer
    fence_height: float
    rail_height: float     # on walls along the tread, feet (54 in)

    def depth(self) -> float:
        return sum(x.thickness for x in self.courses)


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
    gaps: tuple = ()               # PathGap, by start station
    equestrian: object = None      # Equestrian, or None

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

    def in_gap(self, s: float, margin: float = 0.0) -> bool:
        """Whether station s is inside a path gap grown by `margin` each
        way (strictly: a gap's end grown by the margin is outside it)."""
        return any(g.start - margin + _EPS < s < g.end + margin - _EPS
                   for g in self.gaps)

    def waived(self, s: float) -> bool:
        """A road structure gap's end at s inside a path gap grown by the
        path's transition foot, the span validate's separation check skips:
        the deck carries no path there, so it is not met and no approach
        leads to it. A station exactly a foot outside has a built path
        section, so it is not waived."""
        return self.in_gap(s, PATH_TRANSITION_FT)


def _separation(value, s0: float, s1: float) -> tuple:
    where = "path.separation"
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError(f"{where}: needs [station, ft] rows")
    rows = tuple((_on_alignment(s, where, s0, s1), _num(v, where))
                 for s, v in (_row(r, 2, where, "[station, ft]") for r in value))
    _ascending([s for s, _v in rows], where)
    return rows


def _path_gaps(value, s0: float, s1: float, where: str = "path.gaps") -> tuple:
    """Path gaps on [s0, s1]: road stations."""
    out = []
    for i, g in enumerate(value or []):
        at = f"{where}[{i}]"
        if not isinstance(g, dict):
            raise ValueError(f"{at}: a mapping ({{from, to, kind: structure}})")
        kind = str(g.get("kind", "")).lower()
        if kind != "structure":
            raise ValueError(f"{at}: kind {g.get('kind')!r} is not 'structure': a "
                             f"path gap is the path's own structure")
        a = _num(g.get("from"), f"{at}.from", positive=False)
        b = _num(g.get("to"), f"{at}.to", positive=False)
        if not b > a:
            raise ValueError(f"{at}: 'to' must be past 'from'")
        if a < s0 - _EPS or b > s1 + _EPS:
            raise ValueError(f"{at}: {sta(a)} to {sta(b)} is outside the path's "
                             f"stations ({sta(s0)} to {sta(s1)})")
        out.append(PathGap(a, b))
    out.sort(key=lambda g: g.start)
    for p, q in zip(out, out[1:]):
        if q.start < p.end + _EPS:
            raise ValueError(f"{where}: {sta(p.start)} to {sta(p.end)} overlaps "
                             f"{sta(q.start)} to {sta(q.end)}")
    return tuple(out)


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


def _equestrian(value, shoulder_width: float):
    if value is None:
        return None
    where = "path.equestrian"
    if not isinstance(value, dict):
        raise ValueError(f"{where}: a mapping ({{width, buffer, clear_ft, courses, "
                         f"...}})")
    unknown = sorted(set(value) - EQ_KEYS)
    if unknown:
        raise ValueError(f"{where}: unknown keys {unknown}")
    # no positive floor of its own: a zero or negative buffer is narrower
    # than the shoulder, and says so
    buffer = _num(value.get("buffer", 6.0), f"{where}.buffer", positive=False)
    if buffer < shoulder_width - _EPS:
        raise ValueError(f"{where}.buffer: {buffer:g} ft is narrower than "
                         f"path.shoulder.width ({shoulder_width:g} ft): no room for "
                         f"the paved path's graded shoulder (HDM 1003.1(1))")
    fence = value.get("fence", False)
    if not isinstance(fence, bool):
        raise ValueError(f"{where}.fence: true or false, got {fence!r}")
    cs = _num(value.get("cross_slope", -0.02), f"{where}.cross_slope", positive=False)
    width = _num(value.get("width", 8.0), f"{where}.width")
    clear = _num(value.get("clear_ft", 3.0), f"{where}.clear_ft")
    for key, x, steps in (
            ("width", width, "down the tread's courses"),
            ("clear_ft", clear, "down the tread's courses"),
            ("buffer", buffer, "one out from the paved courses and one down the "
                               "tread's")):
        # the top line steps STEP_FT in from each edge of the tread's
        # courses, and out from the paved courses' outer edge (_top):
        # narrower, it folds back on itself
        if x <= 2.0 * STEP_FT + _EPS:
            raise ValueError(f"{where}.{key}: {x:g} ft is no wider than two "
                             f"{STEP_FT:g} ft steps, {steps}")
    return Equestrian(
        width=width, buffer=buffer, clear=clear,
        cross_slope=-abs(cs),      # always falling away from the road, as the path's
        courses=tuple(_courses(value.get("courses"), f"{where}.courses")),
        fence=fence,
        fence_height=_num(value.get("fence_height_ft", 4.5), f"{where}.fence_height_ft"),
        rail_height=_num(value.get("rail_height_ft", 4.5), f"{where}.rail_height_ft"))


def _deck_separation(value) -> float:
    """`deck_separation_ft`: the least separation anywhere the path is
    built (validate), and at a deck the inner shoulder is it less STEP_FT
    (surface), which must be wider than the step down the paved courses'
    inner edge (_top)."""
    where = "path.deck_separation_ft"
    sep = _num(value, where)
    if sep <= 2.0 * STEP_FT + _EPS:
        raise ValueError(f"{where}: {sep:g} ft is no wider than two {STEP_FT:g} ft "
                         f"steps, the inner shoulder's and the one down the paved "
                         f"courses' inner edge")
    return sep


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
    if sw <= STEP_FT + _EPS:
        # the top line steps STEP_FT out from the paved courses' outer edge
        # before o, and q lies the inner shoulder in from the step down
        # their inner edge (_top): no wider, either folds back on itself
        raise ValueError(f"path.shoulder.width: {sw:g} ft is no wider than the "
                         f"{STEP_FT:g} ft step down the paved courses' edge")
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
        deck_separation=_deck_separation(pp.get("deck_separation_ft", 1.5)),
        rail_height=_num(pp.get("rail_height_ft", 3.5), "path.rail_height_ft"),
        road_profile=profile, alignment=alignment,
        gaps=_path_gaps(pp.get("gaps"), s0, s1),
        equestrian=_equestrian(pp.get("equestrian"), sw))


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
    for g in p.gaps:
        out += [g.start - PATH_TRANSITION_FT, g.start, g.end, g.end + PATH_TRANSITION_FT]
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
        if p.covers(g.start) and not p.waived(g.start):
            out.append((g.start - p.approach, g.start, g.start))
        if p.covers(g.end) and not p.waived(g.end):
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


def _check_curvature(c, step: float = 25.0) -> None:
    """The path's outer shoulder must stay inside the centre of curvature
    of the road's plan curve, checked along its stations."""
    from bimforge.author.corridor.section import grade_edge  # section imports path
    p = c.path
    n = max(int(math.ceil((p.s_end - p.s_start) / step)), 1)
    ats = [p.s_start + (p.s_end - p.s_start) * i / n for i in range(n + 1)]
    for s in ats:
        if _on_deck(c, s):
            continue
        k = p.alignment.curvature(s)
        if k == 0.0:
            continue
        u = (grade_edge(c, s, p.side)[0]
             + p.sign * (p.separation_at(s) + p.width + p.shoulder_width))
        if 1.0 - k * u <= MIN_CURVE_SCALE:
            raise ValueError(
                f"path: at {sta(s)} its outer shoulder, {abs(u):.1f} ft from the "
                f"centreline, is at or beyond the centre of curvature of the "
                f"road's plan curve (radius {1.0 / abs(k):.1f} ft)")


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
        if not p.covers(s) or _on_deck(c, s) or p.in_gap(s, PATH_TRANSITION_FT):
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
    _check_curvature(c)
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


@dataclass(frozen=True)
class Surface:
    """The path's finished surface at a station, in section coordinates."""
    edge: tuple            # the road's outer edge of shoulder
    q: tuple               # the road-side edge of the path's inner shoulder
    inner: tuple           # the paved inner edge, `separation` out from edge
    outer: tuple           # the paved outer edge
    o: tuple               # the outer edge of the outer shoulder
    separation: float
    cos_theta: float       # the plane's normal against the path's tangent
    depth: float           # the courses' depth in the plane: sum t / cos theta
    cg: float              # cos of the road's grade: v to elevation
    tread: tuple | None = None     # the tread's (inner edge, outer edge)
    fence: tuple | None = None     # where the fence stands on the buffer
    tread_depth: float = 0.0       # the tread courses' depth in the plane
    tread_cos_theta: float = 1.0   # cos theta at the tread's centre


def section_v(p, s: float, u: float, z_at, toward: float = 0.0) -> float:
    """v of the point at offset u in station s's section plane whose
    elevation is z_at(station), read at the station where the point lies:
    the plane leans back v sin(gamma) along the road (frame.survey_point),
    (1 - kappa u) to a foot of the road's on a curve. `p` must carry
    `road_profile` and `alignment`. Fixed point, iterated until the step is
    under 1e-12 (the map contracts by about |g_z' sg / (cg scale)|, well
    under 1 at road grades); ValueError names the station if it does not
    settle, or if the point is at or past the centre of curvature. At a
    PC or PT kappa is the `toward` side's (Alignment.curvature), taken for
    the whole plane: an idealisation, since a point the plane leans onto
    may lie on the other side of the PC (its station is s - v sg / scale),
    which shifts it by about g (v sg) kappa u, 1e-4 ft at 3 %, v = -0.5 ft
    and kappa u = 0.07."""
    prof = p.road_profile
    g = prof.grade(s)
    root = math.sqrt(1.0 + g * g)
    cg, sg = 1.0 / root, g / root
    k = p.alignment.curvature(s, toward)
    scale = 1.0 - k * u
    if scale <= MIN_CURVE_SCALE:
        raise ValueError(
            f"path: at {sta(s)} the point {u:.2f} ft out is at or beyond the "
            f"centre of curvature of a plan curve of radius "
            f"{1.0 / abs(k):.1f} ft (curvature factor {scale:.3g})")
    z0 = prof.elev(s)
    v = (z_at(s) - z0) / cg
    for _ in range(SECTION_V_ROUNDS):
        nxt = (z_at(s - v * sg / scale) - z0) / cg
        done = abs(nxt - v) < 1e-12
        v = nxt
        if done:
            return v
    raise ValueError(f"path: the section point {u:.2f} ft out at {sta(s)} does "
                     f"not settle in {SECTION_V_ROUNDS} rounds")


def _centre(c, s: float, toward: float = 0.0, at: tuple | None = None) -> tuple:
    """(u, v) of the paved path's centre at finished grade, station s; with
    `at` (du, dz), of the point du out from the paved inner edge and dz
    above the path's profile (the tread's centre: _tread_centre)."""
    from bimforge.author.corridor.section import grade_edge  # section imports path
    p = c.path
    du, dz = at if at is not None else (0.5 * p.width, 0.5 * p.width * p.cross_slope)
    u = grade_edge(c, s, p.side)[0] + p.sign * (p.separation_at(s) + du)
    return u, section_v(p, s, u, lambda st: p.profile.elev(st) + dz, toward)


def _tread_centre(p) -> tuple:
    """(du, dz) of the tread's centre at its finished grade: out from the
    paved inner edge, and above the path's profile (surface's levels)."""
    eq = p.equestrian
    zb = p.cross_slope * p.width + p.shoulder_slope * eq.buffer
    return p.width + eq.buffer + 0.5 * eq.width, zb + 0.5 * eq.cross_slope * eq.width


def cos_theta(c, s: float, h: float = 0.01, toward: float = 0.0,
              at: tuple | None = None) -> float:
    """cos of the angle between station s's section plane's normal (the
    road's 3D tangent, frame.tangent3) and the paved centre's 3D tangent
    there: its grade against the road's, its drift as the separation
    changes, and its twist on a graded curve, all in one. The path's
    tangent is the chord of its centre over s +/- h. With `at` (_centre's)
    it is another line's along the path, the tread's centre: its grade
    along its own length is the profile's over its own (1 - kappa u). The chord's error is
    of order (h / R)^2 / 6 in direction, so about 1e-8 rad at R = 40 ft
    and h = 0.01, against 1e-6 at h = 0.5; round-off (coordinates near
    1e6 ft) is about 1e-10 / h. cos theta is within 1e-8 of an h = 1e-4
    chord on R = 60 ft at 8 % and -6 %.

    theta steps where the road's curvature does (a PC, a PT): the path's
    grade along its own length is its profile's over (1 - kappa u). With
    `toward` +1 or -1 the tangent is the one on that side, the one-sided
    difference (-3 P(s) + 4 P(s + h) - P(s + 2 h)) / 2h toward it (its
    error O(h^2), as the chord's; its round-off about 4e-10 / h), so a
    chord across the step does not average the two sides."""
    from bimforge.author.corridor.frame import survey_point, tangent3
    p = c.path
    al, prof = p.alignment, p.road_profile

    def point(x):
        return survey_point(al, prof, x, *_centre(c, x, toward, at))

    if toward:
        # the stencil reads s to s + 2h on `toward`'s side: no segment end
        # may lie inside it, or it reads across the step it is there to
        # keep out of (the alignment's segments are far longer than 2h)
        if any(0.0 < toward * (b - s) <= 2.0 * h + 1e-9
               for b in al.seg_breaks(s - 2.0 * h - 1.0, s + 2.0 * h + 1.0)):
            raise ValueError(f"path: at {sta(s)} the one-sided tangent's "
                             f"{2.0 * h:g} ft reaches past a segment end")
        p0, p1, p2 = (point(s + toward * i * h) for i in (0, 1, 2))
        d = [toward * (4.0 * y - 3.0 * x - z) for x, y, z in zip(p0, p1, p2)]
    else:
        a, b = point(s - h), point(s + h)
        d = [y - x for x, y in zip(a, b)]
    t3 = tangent3(al, prof, s)
    return sum(x * y for x, y in zip(t3, d)) / math.sqrt(sum(x * x for x in d))


def surface(c, s: float, toward: float = 0.0) -> Surface:
    """The path's finished surface at station s: the paved inner edge
    `separation` ft out from the road's outer edge of shoulder (so it moves
    out where the road widens) at the path's profile, the paved width at
    `cross_slope`, a shoulder each side at `shoulder.slope` falling away
    from the paved path. The inner shoulder is no wider than the
    separation less STEP_FT, so near a deck q stays off the road. At a PC
    or PT, `toward` +1 or -1 solves it on that side (section_v, cos_theta):
    the courses' depth steps there, so a band ending at one and the band
    starting at it read it each on its own side. With a tread the outer
    shoulder gives way to the buffer at `shoulder.slope`, the tread at its
    `cross_slope` and the clear strip at `shoulder.slope` again, o at the
    clear strip's end; the tread has no profile of its own, its elevation
    the path's through the cross slopes. The fence stands on the buffer
    `clear_ft` in from the tread (at the paved edge where the buffer is
    narrower)."""
    from bimforge.author.corridor.section import grade_edge  # section imports path
    p = c.path
    edge = grade_edge(c, s, p.side)
    sep = p.separation_at(s)
    g = p.road_profile.grade(s)
    cg = 1.0 / math.sqrt(1.0 + g * g)
    ui = edge[0] + p.sign * sep
    vi = section_v(p, s, ui, p.profile.elev, toward)

    def at(du, dz):
        # solved in its own plane offset, at the path's profile + dz
        u = ui + p.sign * du
        return (u, section_v(p, s, u, lambda st: p.profile.elev(st) + dz, toward))

    w, sw = p.width, p.shoulder_width
    inner_sw = min(sw, max(sep - STEP_FT, 0.0))
    cos_t = cos_theta(c, s, toward=toward)
    eq = p.equestrian
    o = at(w + sw, p.cross_slope * w + p.shoulder_slope * sw)
    tread = fence = None
    tread_depth, tread_cos = 0.0, 1.0
    if eq is not None:
        zb = p.cross_slope * w + p.shoulder_slope * eq.buffer
        zt = zb + eq.cross_slope * eq.width
        tread = (at(w + eq.buffer, zb), at(w + eq.buffer + eq.width, zt))
        o = at(w + eq.buffer + eq.width + eq.clear, zt + p.shoulder_slope * eq.clear)
        back = max(eq.buffer - eq.clear, 0.0)
        fence = at(w + back, p.cross_slope * w + p.shoulder_slope * back)
        # its thickness normal to its own grade, as the paved courses'
        tread_cos = cos_theta(c, s, toward=toward, at=_tread_centre(p))
        tread_depth = eq.depth() / tread_cos
    return Surface(edge=edge, q=at(-inner_sw, p.shoulder_slope * inner_sw),
                   inner=(ui, vi), outer=at(w, p.cross_slope * w), o=o,
                   separation=sep, cos_theta=cos_t,
                   depth=p.depth() / cos_t, cg=cg,
                   tread=tread, fence=fence, tread_depth=tread_depth,
                   tread_cos_theta=tread_cos)


def course_rings(p, sf: Surface) -> dict:
    """{course index: 4-point ring}: the path's courses under its paved
    width, top down, each thickness / cos theta deep in the section plane
    (its thickness held normal to the path's grade). `p` is the Path, with
    its `courses`; `sf` comes from `surface`, which needs `p.road_profile`
    and `p.alignment`."""
    (ui, vi), (uo, vo) = sf.inner, sf.outer
    out, above = {}, 0.0
    for k, course in enumerate(p.courses):
        d = course.thickness / sf.cos_theta
        out[k] = [(ui, vi - above), (uo, vo - above), (uo, vo - above - d),
                  (ui, vi - above - d)]
        above += d
    return out


def tread_rings(eq, sf: Surface) -> dict:
    """{course index: 4-point ring}: the tread's courses under its width,
    top down, each thickness / cos theta deep, as the paved courses are
    (course_rings), theta the tread's own (Surface.tread_cos_theta). `eq`
    is the Equestrian; `sf` a surface with a tread."""
    (ui, vi), (uo, vo) = sf.tread
    out, above = {}, 0.0
    for k, course in enumerate(eq.courses):
        d = course.thickness / sf.tread_cos_theta
        out[k] = [(ui, vi - above), (uo, vo - above), (uo, vo - above - d),
                  (ui, vi - above - d)]
        above += d
    return out


#: the path's earthwork top, q to o: q, a step down the courses' inner edge,
#: under the courses, up their outer edge, o
TOP_POINTS = 6
#: the tread's four more points on the path's top: a step down its courses'
#: inner edge, under them, up their outer edge, onto the clear strip
TREAD_POINTS = 4


def top_points(c) -> int:
    """The path's top's points, q to o: TOP_POINTS, and TREAD_POINTS more
    with a tread."""
    return TOP_POINTS + (TREAD_POINTS if c.path.equestrian is not None else 0)


@dataclass(frozen=True)
class PathSection:
    """The path's part of a section (section.Section.path)."""
    strip: str             # "ground", "slope", "guarded", "wall-road", "wall-path"
    ratio: float | None    # the strip's slope ratio (from the widening's hinge
                           # where guarded); None on natural ground, at a
                           # wall, or where the strip is level (no ratio)
    surface: Surface
    courses: dict          # course index -> 4-point ring under the paved width
    tread_courses: dict | None = None   # the same under the tread, or None


def strip_count(c) -> int:
    """The strip's points on the earthwork line: room for the road's slope
    and the path's inner slope (section.side_samples each) and the ground
    between them."""
    from bimforge.author.corridor.section import side_samples
    return 2 * side_samples(c) + GROUND_SAMPLES


def side_count(c) -> int:
    """The path side's points on every section's earthwork line: the strip,
    the path's top (its first point the strip's last) and its outer slope
    (its first the top's last). A station without the path pads the road's
    own side to it."""
    from bimforge.author.corridor.section import side_samples
    return strip_count(c) + top_points(c) - 1 + side_samples(c) - 1


def _fixed(points: list, n: int, s: float, seg: int | None = None) -> list:
    """`points` padded to `n` by cutting segment `seg` (the last where None)
    evenly, as section._samples cuts a slope's last segment: the line is
    unchanged, and which segment takes the padding depends only on the
    strip's mode, so vertex k means the same from station to station.
    ValueError, naming station s, when there are more than `n`."""
    pts = list(points)
    if len(pts) > n:
        raise ValueError(f"station {sta(s)}: the path's strip has {len(pts)} "
                         f"points, more than its {n}")
    k = len(pts) - 2 if seg is None else seg
    extra = n - len(pts)
    (u0, v0), (u1, v1) = pts[k], pts[k + 1]
    mid = [(u0 + (u1 - u0) * i / (extra + 1), v0 + (v1 - v0) * i / (extra + 1))
           for i in range(1, extra + 1)]
    return pts[:k + 1] + mid + pts[k + 1:]


def _ratio(a: tuple, b: tuple, cg: float) -> float | None:
    """The slope a to b, horizontal per vertical; None where it is level
    (no ratio: as flat as a slope gets)."""
    dz = abs(a[1] - b[1]) * cg
    return None if dz < 1e-9 else abs(a[0] - b[0]) / dz


def _steeper(ratio: float | None, limit: float) -> bool:
    """Whether a slope of `ratio` (None: level) is steeper than `limit`."""
    return ratio is not None and ratio < limit - _EPS


def _no_fit(c, s: float, a: tuple, q: tuple, cg: float) -> str:
    p = c.path
    dz = (a[1] - q[1]) * cg
    return (f"station {sta(s)}: the {p.side} strip between the road and the path "
            f"does not fit at {p.strip_ratio:g}:1 or flatter: the road "
            f"{abs(dz):.2f} ft {'above' if dz > 0 else 'below'} the path's "
            f"shoulder edge, {abs(q[0] - a[0]):.2f} ft from it; set walls: auto "
            f"for a wall there")


def _widening(c, s: float, hinge: tuple, room: float) -> list:
    """The road's guardrail widening (section._widening) on the path's
    side, held inside the strip: its hinge no farther out than STEP_FT
    short of q. Where the strip has no room for it (q within GUARD_STEP_FT
    + STEP_FT of the hinge: the path at the deck, beside its barrier) it
    collapses onto `hinge` and the strip runs straight on to q: the first
    point would stand at q's own offset, at finished grade, and the strip
    would fold back down to q, a fold the earthwork's columns cannot
    close."""
    from bimforge.author.corridor.params import WIDENING_SLOPE
    from bimforge.author.corridor.section import GUARD_STEP_FT, grade_edge
    p = c.path
    if room < GUARD_STEP_FT + STEP_FT - _EPS:
        return [hinge, hinge]
    eu, ev = grade_edge(c, s, p.side)
    far = max(min(c.guard.widening, room - STEP_FT), GUARD_STEP_FT)
    return [(eu + p.sign * w, ev - WIDENING_SLOPE * w) for w in (GUARD_STEP_FT, far)]


def _on_ground(c, s: float, a: tuple, b: tuple, ground_dz) -> list:
    """GROUND_SAMPLES points evenly between a and b, each moved up or down
    onto the ground."""
    g = c.path.road_profile.grade(s)
    cg = 1.0 / math.sqrt(1.0 + g * g)
    out = []
    for i in range(1, GROUND_SAMPLES + 1):
        t = i / (GROUND_SAMPLES + 1)
        u, v = a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
        for _ in range(3):
            v += ground_dz(s, u, v) / cg
        out.append((u, v))
    return out


def _natural(c, s: float, hinge: tuple, q: tuple, room: float, ground_dz,
             rail: bool) -> tuple | None:
    """The strip as two slopes with natural ground between, or None: the
    road's slope from the hinge (V1.1's rules, with the rail's widening
    where one runs) and the path's inner slope from q toward the road (the
    same rules mirrored, no widening), each held to the strip's width and
    no footprint, both daylighting, the road's no farther from the hinge
    than the path's."""
    from dataclasses import replace

    from bimforge.author.corridor.section import (NoDaylight, _samples, _slope,
                                                  side_samples)
    p = c.path
    free = replace(c, slopes=replace(c.slopes, footprint=None, daylight_limit=room))
    try:
        road = _slope(free, s, p.side, p.sign, hinge, ground_dz, rail)
        back = _slope(free, s, p.side, -p.sign, q, ground_dz, widen=False)
    except NoDaylight:
        return None
    dr, dp = road.line[-1], back.line[-1]
    if abs(dr[0] - hinge[0]) > abs(dp[0] - hinge[0]) + _EPS:
        return None                                   # the slopes cross
    # each slope padded to side_samples as V1.1 pads a side, and the ground
    # between: exactly strip_count points
    n = side_samples(c)
    pts = (_samples(road.line, n) + _on_ground(c, s, dr, dp, ground_dz)
           + _samples(back.line, n)[::-1])
    return pts, "ground", None, road.guarded


def _strip(c, s: float, sf: Surface, hinge: tuple, ground_dz,
           rail: bool = False) -> tuple:
    """(points from the hinge to q, mode, ratio, guarded): the strip at
    station s, resolved in the spec's order: a wall gap standing here,
    natural ground between, a slope (guarded below a higher road where
    steeper than fill.ratio; on an approach whatever its slope, as the
    deck's barrier layout stands there), else NoDaylight with the wall it
    needs, "strip-road" or "strip-path". With `rail` the road's guardrail
    widening is taken out of the strip as well."""
    from bimforge.author.corridor.section import NoDaylight
    p = c.path
    sign, q = p.sign, sf.q
    hu, hv = hinge
    wall = c.wall(p.side, s, strip=True)
    if wall is not None:
        if wall.auto == "strip-road":
            # V1.1's automatic fill wall at the hinge, its barrier on top;
            # the strip level at q from its foot
            return [hinge, (hu + sign * STEP_FT, q[1]), q], "wall-road", None, False
        # the wall at q retaining the path, its rail on top; the strip
        # level at the hinge's elevation from the road to its foot
        return [hinge, (q[0] - sign * STEP_FT, hv), q], "wall-path", None, False
    room = abs(q[0] - hu)
    natural = _natural(c, s, hinge, q, room, ground_dz, rail)
    if natural is not None:
        return natural
    approach = on_approach(c, s)
    higher = hv > q[1]
    # the wall a strip too steep needs stands on its higher side
    kind = "strip-road" if higher else "strip-path"
    ratio = _ratio(hinge, q, sf.cg)
    guarded = (higher and not approach and c.guard is not None
               and _steeper(ratio, c.slopes.fill_ratio))
    if guarded or (rail and c.guard is not None):
        # a rail's widening stands behind it whichever side is higher, as
        # V1.1's does on a cut (section._slope); the rest runs on to q
        w = _widening(c, s, hinge, room)
        rest = _ratio(w[-1], q, sf.cg)
        if not approach and _steeper(rest, p.strip_ratio):
            raise NoDaylight(_no_fit(c, s, w[-1], q, sf.cg), kind)
        return [hinge] + w + [q], "guarded" if guarded else "slope", rest, guarded
    if not approach and _steeper(ratio, p.strip_ratio):
        raise NoDaylight(_no_fit(c, s, hinge, q, sf.cg), kind)
    collapsed = [hinge, hinge] if c.guard is not None else []
    return [hinge] + collapsed + [q], "slope", ratio, False


def _top(c, sf: Surface) -> list:
    """The path's earthwork top, q to o (top_points): the inner shoulder at
    finished grade, a STEP_FT step down the courses' inner edge, under the
    courses, up their outer edge, the outer shoulder; with a tread the
    buffer, the same step down, under and up the tread's courses, and the
    clear strip. k is the shoulder slope over a step: the buffer and the
    clear strip fall at it too, so a step back toward the path rises by it."""
    p = c.path
    k = p.shoulder_slope * STEP_FT / sf.cg
    (ui, vi), (uo, vo) = sf.inner, sf.outer
    top = [sf.q, (ui - p.sign * STEP_FT, vi + k), (ui, vi - sf.depth),
           (uo, vo - sf.depth), (uo + p.sign * STEP_FT, vo + k)]
    if sf.tread is None:
        return top + [sf.o]
    (ti, tv), (to, tov) = sf.tread
    return top + [(ti - p.sign * STEP_FT, tv - k), (ti, tv - sf.tread_depth),
                  (to, tov - sf.tread_depth), (to + p.sign * STEP_FT, tov + k), sf.o]


#: the automatic walls that stand on the path's outer side, at o
OUTER_WALLS = ("path-fill", "path-cut")


def outer_wall(c, s: float):
    """The wall gap on the path's outer side at station s, or None. Only a
    `path-fill` or `path-cut` wall stands there: a listed wall gap is
    refused over the path's stations (validate), and a road `fill` or `cut`
    wall on the path's side (one ending on the path's first or last
    station, where the path's own wall may start) is the road's, whose
    side there is the strip."""
    p = c.path
    return next((g for g in c.gaps
                 if g.kind == "wall" and g.side == p.side and g.auto in OUTER_WALLS
                 and g.start - _EPS <= s <= g.end + _EPS), None)


def _outer(c, s: float, sf: Surface, ground_dz) -> list:
    """The path's outer slope from o by V1.1's rules, with no MGS widening,
    or [o, o] at a wall on the path's outer side (outer_wall)."""
    from bimforge.author.corridor.section import _slope
    p = c.path
    if outer_wall(c, s) is not None:
        return [sf.o, sf.o]
    return _slope(c, s, p.side, p.sign, sf.o, ground_dz, widen=False).line


def side(c, s: float, hinge: tuple, ground_dz, rail: bool = False) -> tuple:
    """(section.Side, PathSection): the path's side of corridor `c`'s
    section at station s, out from the road's subgrade `hinge`. The Side's
    kind is "path"; it is guarded where the strip is, so the road's rail
    is laid there; its line has side_count(c) points."""
    from bimforge.author.corridor.section import Side, _samples, side_samples
    sf = surface(c, s)
    pts, mode, ratio, guarded = _strip(c, s, sf, hinge, ground_dz, rail)
    # a wall at q pads the level run to its foot, not the wall's face;
    # every other mode pads its last segment, the run on to q
    seg = 0 if mode == "wall-path" else None
    line = (_fixed(pts, strip_count(c), s, seg) + _top(c, sf)[1:]
            + _samples(_outer(c, s, sf, ground_dz), side_samples(c))[1:])
    eq = c.path.equestrian
    return (Side("path", line, guarded, ratio),
            PathSection(mode, ratio, sf, course_rings(c.path, sf),
                        tread_rings(eq, sf) if eq is not None else None))


def needs_wall(c, s: float, hinge: tuple, ground_dz, rail: bool = False,
               location: str = "outer") -> str | None:
    """section.needs_wall on the path's side where the path is: the strip's
    wall ("strip-road", "strip-path") or the outer side's ("path-fill",
    "path-cut"), None where it fits or a wall gap already stands."""
    from bimforge.author.corridor.section import NoDaylight
    p = c.path
    strip = location == "strip"
    if (c.wall(p.side, s, strip=True) if strip else outer_wall(c, s)) is not None:
        return None
    sf = surface(c, s)
    try:
        if strip:
            _strip(c, s, sf, hinge, ground_dz, rail)
        else:
            _outer(c, s, sf, ground_dz)
    except NoDaylight as exc:
        return exc.kind if strip else f"path-{exc.kind}"
    return None
