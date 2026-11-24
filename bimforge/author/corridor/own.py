"""A shared-use path on its own corridor (P.6, V1.2 part C, phase 3).

`path.own` lists stretches where the path leaves the road and runs on a
corridor of its own in the same build: its own horizontal (`run`, in the
road's form, from the hand-over point derived here), its own profile on its
own stationing from 0+00, its own section (the paved width, courses and
shoulders, one way by `cross_slope`, V1.1's side slopes both sides), walls
and earthwork. It hands over at road station `from` and rejoins at `to`,
each where the beside section leaves natural ground between road and path,
and its plan footprint never crosses the road's, so earthwork is counted
once.

Own section coordinates: u left of the own alignment's travel, v up from
its profile (the paved inner edge's elevation) in the plane square to its
3D tangent. The own alignment is the paved centreline; the inner edge is on
the side the road was (`inward` = -Path.sign), the cross slope falling away
from it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from types import SimpleNamespace

from bimforge.author.alignment import Alignment, parse_bearing, parse_dms, sta

#: the run rejoins the path's centreline within these
REJOIN_FT = 0.1
REJOIN_DEG = 0.1
#: a tangent's bearing meets the heading it comes in on within this, deg:
#: plans write bearings to the second, so rounding leaves at most half one
JOIN_TOL_DEG = 1.0 / 3600.0
#: the beside section turns into the road's own over this at a hand-over
#: and a rejoin, feet: the own stretch's earthwork starts there
HANDOVER_FT = 0.01
#: a curve's length is its radius times its delta within this, feet, or
#: ARC_TOL_RATIO of its radius where that is more (a delta to the second on
#: a long radius): the alignment stations by the length and turns by the delta
ARC_TOL_FT = 0.01
ARC_TOL_RATIO = 5e-6
#: HDM 1003.1(10): the least radius, and the radius under which a path
#: would need superelevation (its cross slope stays at most 2 %), by speed
MIN_RADIUS_FT = {20: 90.0, 25: 160.0, 30: 260.0}
NO_SUPER_RADIUS_FT = {20: 100.0, 25: 180.0, 30: 320.0}
#: the keys each `path.own` entry takes
KEYS = {"from", "to", "run", "profile", "gaps"}
_EPS = 1e-9


@dataclass(frozen=True)
class Own:
    """One own stretch."""
    index: int                 # from 1, by start station
    entry: int                 # its place in the path.own list, from 0: the
                               # i its messages name (path.own[i])
    start: float               # the hand-over, road station
    end: float                 # the rejoin, road station
    alignment: object          # its own, the paved centreline, from 0+00
    profile: object            # the paved inner edge, own stations
    gaps: tuple = ()           # path.PathGap on own stations: its structures
    walls: tuple = ()          # its automatic walls, own stations (Task 20)

    @property
    def length(self) -> float:
        return self.alignment.s_end - self.alignment.s_start


def _turn(d: float) -> float:
    """An azimuth difference folded into [-180, 180) degrees."""
    return (d + 180.0) % 360.0 - 180.0


def centre_point(c, p, s: float) -> tuple:
    """(northing, easting, azimuth): the path's centreline beside the road
    at road station s, heading the road's way."""
    from bimforge.author.corridor.section import grade_edge  # section imports path
    u = grade_edge(c, s, p.side)[0] + p.sign * (p.separation_at(s) + 0.5 * p.width)
    n, e, az = p.alignment.point_az(s)
    ln, le = p.alignment.left_normal(s)
    return n + u * ln, e + u * le, az


def _run(value, at: str) -> list:
    """The own horizontal in the road's form: each element a tangent
    (bearing, length) or a curve (delta, radius, turn, length) whose length
    is its arc."""
    from bimforge.author.corridor.params import _num
    if not isinstance(value, list) or not value:
        raise ValueError(f"{at}: the path's own horizontal, [tangent or curve, ...] "
                         f"in the road's form, from the hand-over")
    for j, x in enumerate(value):
        here = f"{at}[{j}]"
        if not isinstance(x, dict):
            raise ValueError(f"{here}: a mapping ({{kind: tangent, bearing, length}} "
                             f"or {{kind: curve, delta, radius, turn, length}}), "
                             f"got {x!r}")
        kind = x.get("kind")
        if kind not in ("tangent", "curve"):
            raise ValueError(f"{here}.kind: {kind!r} is not tangent or curve")
        length = _num(x.get("length"), f"{here}.length")
        if kind == "tangent":
            try:
                parse_bearing(x["bearing"])
            except (KeyError, AttributeError, TypeError, ValueError):
                raise ValueError(f"{here}.bearing: a bearing as 'N 1-2-3 E', got "
                                 f"{x.get('bearing')!r}") from None
            continue
        radius = _num(x.get("radius"), f"{here}.radius")
        try:
            delta = parse_dms(x["delta"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"{here}.delta: an angle as '20-0-0', got "
                             f"{x.get('delta')!r}") from None
        if not 0.0 < delta < 360.0:
            raise ValueError(f"{here}.delta: {x['delta']!r} is not between 0 and "
                             f"360 deg")
        if x.get("turn", "R") not in ("L", "R"):
            raise ValueError(f"{here}.turn: {x.get('turn')!r} is not L or R")
        arc = radius * math.radians(delta)
        if abs(arc - length) > max(ARC_TOL_FT, ARC_TOL_RATIO * radius):
            raise ValueError(f"{here}.length: {length:g} ft is not the curve's "
                             f"{arc:.4f} ft (radius x delta)")
    return value


def _bearing(az: float) -> str:
    """A quadrant bearing for azimuth `az`, in decimal degrees to 1e-12 (no
    minus sign, which parse_bearing would split on)."""
    az %= 360.0                    # 360.0 itself for a tiny negative: N 0 E
    for top, ns, ew, x in ((90.0, "N", "E", az), (180.0, "S", "E", 180.0 - az),
                           (270.0, "S", "W", az - 180.0), (360.0, "N", "W", 360.0 - az)):
        if az < top:
            return f"{ns} {x:.12f} {ew}"
    return f"N {0.0:.12f} E"


def _snapped(run: list, az: float, name: str, at: str) -> list:
    """`run` (checked by _run) with each tangent's bearing set to the
    heading it comes in on: the road's `az` at the hand-over for a first
    tangent (parse_own holds it to REJOIN_DEG), and after that the heading
    the element before it ends on, which a bearing must be within
    JOIN_TOL_DEG of. The own alignment is then tangent-continuous, as a
    swept run must be; the spec's run is left as given."""
    out, s = [], 0.0
    for j, x in enumerate(run):
        if x["kind"] == "tangent":
            d = _turn(parse_bearing(x["bearing"]) - az)
            if j and abs(d) > JOIN_TOL_DEG + _EPS:
                raise ValueError(f"{at}: {name}: {abs(d):.6f} deg kink at station "
                                 f"{sta(s)} (more than {JOIN_TOL_DEG * 3600.0:g} "
                                 f"arc-second): a swept run must be "
                                 f"tangent-continuous")
            x = dict(x, bearing=_bearing(az))
        else:
            az += (1.0 if x.get("turn", "R") == "R" else -1.0) * parse_dms(x["delta"])
        out.append(x)
        s += x["length"]
    return out


def parse_own(value, p, c) -> tuple:
    """The own stretches `value` (`path.own`) describes for path `p` beside
    corridor `c`, by start station; ValueError names the first field that
    is wrong."""
    from bimforge.author.corridor.params import _num
    from bimforge.author.corridor.path import (MEET_TOL_FT, PATH_TRANSITION_FT,
                                               _path_gaps, _profile)
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("path.own: a list of {from, to, run, profile, gaps}")
    rows = []
    for i, o in enumerate(value):
        at = f"path.own[{i}]"
        if not isinstance(o, dict):
            raise ValueError(f"{at}: a mapping ({{from, to, run, profile, gaps}})")
        unknown = sorted(set(o) - KEYS)
        if unknown:
            raise ValueError(f"{at}: unknown keys {unknown}")
        a = _num(o.get("from"), f"{at}.from", positive=False)
        b = _num(o.get("to"), f"{at}.to", positive=False)
        if not b > a:
            raise ValueError(f"{at}: 'to' must be past 'from'")
        if not (p.covers(a) and p.covers(b)):
            raise ValueError(f"{at}: {sta(a)} to {sta(b)} is outside the path's "
                             f"stations ({sta(p.s_start)} to {sta(p.s_end)})")
        for s, which in ((a, "hand-over"), (b, "rejoin")):
            deck = next((g for g in c.gaps if g.kind == "structure"
                         and g.start + _EPS < s < g.end - _EPS), None)
            if deck is not None:
                raise ValueError(f"{at}: the {which} at {sta(s)} is on the road's "
                                 f"structure gap {sta(deck.start)} to "
                                 f"{sta(deck.end)}: no beside section stands there "
                                 f"to hand over from")
        rows.append((a, i, b, o))
    out = []
    # numbered, and the alignments named, by start station
    for k, (a, i, b, o) in enumerate(sorted(rows, key=lambda r: (r[0], r[1]))):
        at = f"path.own[{i}]"
        run = _run(o.get("run"), f"{at}.run")
        n, e, az = centre_point(c, p, a)
        if run[0]["kind"] == "tangent":
            got = parse_bearing(run[0]["bearing"])
            if abs(_turn(got - az)) > REJOIN_DEG + _EPS:
                raise ValueError(f"{at}.run[0]: bearing {run[0]['bearing']} is not the "
                                 f"road's heading at the hand-over {sta(a)} "
                                 f"({az:.4f} deg): the run starts the road's way")
        name = f"{p.alignment.name} path {k + 1}"
        al = Alignment({"station": 0.0, "northing": n, "easting": e, "azimuth": az},
                       _snapped(run, az, name, f"{at}.run"), name=name)
        en, ee = al.end_point
        eaz = al.point_az(al.s_end)[2]
        tn, te, taz = centre_point(c, p, b)
        miss, turn = math.hypot(en - tn, ee - te), abs(_turn(eaz - taz))
        if miss > REJOIN_FT + _EPS or turn > REJOIN_DEG + _EPS:
            raise ValueError(
                f"{at}: its run ends at N {en:.2f} E {ee:.2f} heading {eaz:.4f} deg, "
                f"not on the path's centreline at {sta(b)} (N {tn:.2f} E {te:.2f}, "
                f"heading {taz:.4f} deg): {miss:.2f} ft and {turn:.4f} deg off (at "
                f"most {REJOIN_FT:g} ft and {REJOIN_DEG:g} deg)")
        prof = _profile(o.get("profile"), f"{at}.profile", 0.0, al.s_end)
        for st, rs, which in ((0.0, a, "hand-over"), (al.s_end, b, "rejoin")):
            got, want = prof.elev(st), p.profile.elev(rs)
            if abs(got - want) > MEET_TOL_FT + _EPS:
                raise ValueError(
                    f"{at}.profile: at the {which} ({sta(st)}, road {sta(rs)}) it is "
                    f"at {got:.4f} ft and path.profile at {want:.4f} ft, "
                    f"{abs(got - want):.4f} ft off (more than {MEET_TOL_FT:g} ft)")
        out.append(Own(k + 1, i, a, b, al, prof,
                       _path_gaps(o.get("gaps"), 0.0, al.s_end, f"{at}.gaps",
                                  "its own stations")))
    for x, y in zip(out, out[1:]):
        if y.start < x.end + _EPS:
            raise ValueError(f"path.own: {sta(x.start)} to {sta(x.end)} overlaps "
                             f"{sta(y.start)} to {sta(y.end)}")
    for x in out:
        for g in p.gaps:
            # a path gap's transition foot back to the beside section must
            # be clear of the stretch too: no beside section stands in it
            if (g.start - PATH_TRANSITION_FT < x.end - _EPS
                    and g.end + PATH_TRANSITION_FT > x.start + _EPS):
                raise ValueError(
                    f"path.own: {sta(x.start)} to {sta(x.end)} overlaps the path gap "
                    f"{sta(g.start)} to {sta(g.end)} or its {PATH_TRANSITION_FT:g} ft "
                    f"transition; a path bridge on an own stretch is one of its own "
                    f"gaps (own[].gaps)")
    return tuple(out)


@dataclass(frozen=True)
class OwnSurface:
    """The path's finished surface on an own stretch at an own station:
    path.Surface's fields, in own section coordinates. The section is
    square to the own alignment's 3D tangent, and the paved courses are
    centred on it, so their cos theta is 1 and they are their thickness
    deep; the tread's centre, off the alignment, has its own."""
    q: tuple                        # the inner shoulder's edge
    inner: tuple                    # the paved inner edge, on the own profile
    outer: tuple                    # the paved outer edge
    o: tuple                        # the outer shoulder's edge, or the clear
                                    # strip's past a tread
    cos_theta: float
    depth: float                    # the courses' depth in the plane
    cg: float                       # cos of the own grade
    inward: float                   # +1: the inner edge left of the own alignment
    tread: tuple | None = None      # the tread's (inner edge, outer edge)
    fence: tuple | None = None
    tread_depth: float = 0.0        # the tread courses' depth in the plane
    tread_cos_theta: float = 1.0    # cos theta at the tread's centre


def _frame(own):
    """The own alignment and profile in the form path.section_v reads
    (`road_profile`, `alignment`): the plane is square to the own tangent."""
    return SimpleNamespace(road_profile=own.profile, alignment=own.alignment)


def own_surface(p, own, t: float, toward: float = 0.0) -> OwnSurface:
    """The path's finished surface at own station t: the paved width
    centred on the own alignment, its inner edge at the own profile on the
    side the road was, falling away at `cross_slope`, a graded shoulder
    each side at `shoulder.slope` falling away from it; with a tread the
    outer shoulder gives way to the buffer, tread and clear strip, as
    beside the road (path.surface). Each point is solved in the plane
    (path.section_v): dz above the own profile where it lies, so on a grade
    v is not dz but dz cos(gamma) and less. The tread's courses are their
    thickness over its cos theta deep (path.chord_cos: on a graded curve
    its centre rises faster or slower than the alignment). At a PC or PT,
    `toward` +1 or -1 solves it on that side."""
    from bimforge.author.corridor.frame import survey_point
    from bimforge.author.corridor.path import chord_cos, section_v
    al, prof, fr = own.alignment, own.profile, _frame(own)
    g = prof.grade(t)
    cg = 1.0 / math.sqrt(1.0 + g * g)
    inward, w, sw = -p.sign, p.width, p.shoulder_width
    cs, ss = p.cross_slope, p.shoulder_slope

    def at(du, dz, x=t):
        """du ft outward from the paved inner edge, dz ft above it, at own
        station x."""
        u = inward * (0.5 * w - du)
        return (u, section_v(fr, x, u, lambda st: prof.elev(st) + dz, toward))

    o, tread, fence, tread_depth, tread_cos = (at(w + sw, cs * w + ss * sw),
                                               None, None, 0.0, 1.0)
    eq = p.equestrian
    if eq is not None:
        zb = cs * w + ss * eq.buffer
        zt = zb + eq.cross_slope * eq.width
        tread = (at(w + eq.buffer, zb), at(w + eq.buffer + eq.width, zt))
        o = at(w + eq.buffer + eq.width + eq.clear, zt + ss * eq.clear)
        back = max(eq.buffer - eq.clear, 0.0)
        fence = at(w + back, cs * w + ss * back)
        mid = (w + eq.buffer + 0.5 * eq.width, zb + 0.5 * eq.cross_slope * eq.width)
        tread_cos = chord_cos(al, prof, t,
                              lambda x: survey_point(al, prof, x, *at(*mid, x=x)),
                              toward=toward)
        tread_depth = eq.depth() / tread_cos
    return OwnSurface(q=at(-sw, ss * sw), inner=at(0.0, 0.0), outer=at(w, cs * w),
                      o=o, cos_theta=1.0, depth=p.depth(), cg=cg, inward=inward,
                      tread=tread, fence=fence, tread_depth=tread_depth,
                      tread_cos_theta=tread_cos)


def own_corridor(c, own):
    """The params.Corridor an own stretch's slopes are read and its walls
    found on: the road's slopes on own stations 0 to its length, the rock
    depth read linearly from the road's at the hand-over to its at the
    rejoin, its own gaps as structure gaps and its walls, no widths,
    superelevation, path or guardrail."""
    from bimforge.author.corridor.params import Gap
    sl = c.slopes
    if sl.rock is not None:
        sl = replace(sl, rock=replace(sl.rock, depth=(
            (0.0, sl.rock.depth_at(own.start)),
            (own.length, sl.rock.depth_at(own.end)))))
    gaps = tuple(Gap(g.start, g.end, "structure") for g in own.gaps) + tuple(own.walls)
    return replace(c, s_start=0.0, s_end=own.length, slopes=sl, widths={},
                   superelevation=(), path=None, guard=None, own=True,
                   gaps=tuple(sorted(gaps, key=lambda g: (g.start, g.side or ""))))


@dataclass(frozen=True)
class OwnSection:
    """An own stretch's section at an own station: earthwork.strip reads
    its earthwork_line, as a section.Section's."""
    s: float                        # own station
    surface: OwnSurface
    sides: dict                     # "L"/"R" -> section.Side, out from q or o
    top: list                       # q to o (path._top)
    courses: dict                   # course index -> 4-point ring
    tread_courses: dict | None
    count: int                      # each side's points on the earthwork line

    def earthwork_line(self, per_component=1) -> list:
        """Left daylight to right daylight, the same count at every
        station: the left side's slope, the top, the right side's.
        `per_component` is section.Section's; an own section has no
        components to divide."""
        from bimforge.author.corridor.section import _samples
        top = self.top if self.surface.inward > 0 else self.top[::-1]
        left = list(reversed(_samples(self.sides["L"].line, self.count)))
        right = _samples(self.sides["R"].line, self.count)
        return left + top[1:-1] + right

    def width(self) -> float:
        """Daylight to daylight, feet."""
        line = self.earthwork_line()
        return abs(line[0][0] - line[-1][0])


def _start(sf: OwnSurface, side: str) -> tuple:
    """(the point `side`'s slope starts at, its outward sign): q on the
    inner side, o on the outer."""
    if (side == "L") == (sf.inward > 0):
        return sf.q, sf.inward
    return sf.o, -sf.inward


def _named(own, exc):
    """`exc` (NoDaylight, or a ground's ValueError) naming the own stretch
    it was read on: its stations are its own."""
    from bimforge.author.corridor.section import NoDaylight
    msg = f"path.own[{own.entry}] ({own.alignment.name}, own stations): {exc}"
    return NoDaylight(msg, exc.kind) if isinstance(exc, NoDaylight) else ValueError(msg)


def own_section(c, oc, own, t: float, ground_dz) -> OwnSection:
    """The own stretch's section at own station t on its corridor `oc`
    (own_corridor): the path's top, q to o, and V1.1's side slope out from
    each (no MGS widening), or a wall where `oc` has one. NoDaylight, naming
    the stretch, where a slope does not fit and no wall stands."""
    from bimforge.author.corridor.path import _top, course_rings, tread_rings
    from bimforge.author.corridor.section import Side, _slope, side_samples
    from bimforge.author.corridor.section import _named as on_side
    p = c.path
    sf = own_surface(p, own, t)
    sides = {}
    for side in ("L", "R"):
        start, sign = _start(sf, side)
        if oc.wall(side, t) is not None:
            # an automatic wall at q or o: its line is the point twice, so
            # the side keeps its point count
            sides[side] = Side("wall", [start, start])
            continue
        try:
            sides[side] = _slope(oc, t, side, sign, start,
                                 on_side(ground_dz, side), widen=False)
        except ValueError as exc:
            raise _named(own, exc) from None
    eq = p.equestrian
    return OwnSection(t, sf, sides, _top(c, sf), course_rings(p, sf),
                      tread_rings(eq, sf) if eq is not None else None,
                      side_samples(oc))


def own_needs_wall(c, oc, own, t: float, side: str, ground_dz) -> str | None:
    """The wall `side` of the own section needs at own station t:
    "path-fill" or "path-cut", None where its slope fits or a wall gap
    already stands."""
    from bimforge.author.corridor.section import NoDaylight, _slope
    from bimforge.author.corridor.section import _named as on_side
    if oc.wall(side, t) is not None:
        return None
    start, sign = _start(own_surface(c.path, own, t), side)
    try:
        _slope(oc, t, side, sign, start, on_side(ground_dz, side), widen=False)
    except NoDaylight as exc:
        return f"path-{exc.kind}"
    except ValueError as exc:
        raise _named(own, exc) from None
    return None


def own_runs(oc, own) -> list:
    """Each own run's stations (the stretch less its own gaps), with the own
    alignment's and profile's points, densified as the road's are."""
    from bimforge.author.corridor.frame import densify, geometry_stations
    al, prof = own.alignment, own.profile
    return [densify(al, prof, oc.stations(a, b, geometry_stations(al, prof, a, b)))
            for a, b in oc.runs()]


def find_walls(c, oc, own, ground_dz) -> tuple:
    """(own, oc) with the automatic walls its section needs, `path-fill` or
    `path-cut` at q or o (walls.find on its stations, own_needs_wall the
    need), added as params.Corridor.with_walls adds them. For `walls:
    auto`: the caller asks only where c.auto_walls is set."""
    from bimforge.author.corridor import walls
    found = [g for ss in own_runs(oc, own) for g in walls.find(
        oc, ss, ground_dz,
        need=lambda t, side, loc: (own_needs_wall(c, oc, own, t, side, ground_dz)
                                   if loc == "outer" else None))]
    if not found:
        return own, oc
    oc = oc.with_walls(found)
    own = replace(own, walls=tuple(g for g in oc.gaps if g.auto is not None))
    return own, own_corridor(c, own)


def kind_changes(c, own, a: OwnSection, b: OwnSection, ground_dz) -> list:
    """Own stations strictly between own sections `a` and `b` where a side
    turns from cut to fill or back (section.kind_changes): where the ground
    meets the point its slope starts at, q or o, the point _slope reads
    its kind at. The station returned is the fill side of the turn, within
    section._TURN_FT."""
    from bimforge.author.corridor.params import SIDES
    from bimforge.author.corridor.section import _TURN_FT
    out = []
    for side in SIDES:
        if {a.sides[side].kind, b.sides[side].kind} != {"cut", "fill"}:
            continue

        def above(t):
            start, _sign = _start(own_surface(c.path, own, t), side)
            return ground_dz(t, *start) > 0.0

        lo, hi = a.s, b.s                 # `above` differs at the two ends
        cut_lo = above(lo)
        while hi - lo > _TURN_FT:
            mid = 0.5 * (lo + hi)
            if above(mid) == cut_lo:
                lo = mid
            else:
                hi = mid
        t = hi if cut_lo else lo          # the end where the side is fill
        if a.s < t < b.s:
            out.append(t)
    return sorted(set(out))


def own_sections(c, oc, own, ground_dz) -> list:
    """Each own run's sections (OwnSection), by station, with a section
    where a side turns between cut and fill (kind_changes), as the road's
    first pass cuts one: unless a station is already within TURN_GAP_FT or
    it falls in an automatic wall's lead-in (section.in_lead_in)."""
    from bimforge.author.corridor.frame import merge_stations
    from bimforge.author.corridor.section import TURN_GAP_FT, in_lead_in
    out = []
    for ss in own_runs(oc, own):
        secs = [own_section(c, oc, own, t, ground_dz) for t in ss]
        turns = [t for a, b in zip(secs, secs[1:])
                 for t in kind_changes(c, own, a, b, ground_dz)
                 if min(t - a.s, b.s - t) > TURN_GAP_FT and not in_lead_in(oc, t)]
        if turns:
            known = {sec.s: sec for sec in secs}
            secs = [known.get(t) or own_section(c, oc, own, t, ground_dz)
                    for t in merge_stations(ss, turns)]
        out.append(secs)
    return out


def wall_rows(c, oc, own, ground_dz, secs=()) -> list:
    """walls.WallRow for each of the own stretch's walls, on own stations:
    its exposed height at q or o (the ground below it at a fill wall, above
    it at a cut wall), read at the own sections `secs` on it and at least
    every HEIGHT_STEP_FT between its ends (walls.rows), location "own
    <index>", carrying the path. A fill wall over max_wall_height_ft is
    too tall."""
    from bimforge.author.corridor.walls import HEIGHT_STEP_FT, WallRow
    out = []
    for g in own.walls:
        n = max(1, math.ceil((g.end - g.start) / HEIGHT_STEP_FT - _EPS))
        at = {g.start + (g.end - g.start) * i / n for i in range(n + 1)}
        at.update(sec.s for sec in secs if g.start - _EPS <= sec.s <= g.end + _EPS)
        heights, offsets = [], []
        for t in sorted(at):
            start, _sign = _start(own_surface(c.path, own, t), g.side)
            dz = ground_dz(t, *start)
            heights.append(-dz if g.auto == "path-fill" else dz)
            offsets.append(abs(start[0]))
        kind, top = ("fill" if g.auto == "path-fill" else "cut"), max(heights)
        out.append(WallRow(g.side, kind, g.start, g.end, max(offsets), min(heights),
                           top, kind == "fill" and top > c.max_wall_height + _EPS,
                           location=f"own {own.index}", carries="path"))
    return sorted(out, key=lambda r: (r.start, r.side))


def check_handover(own, at_from, at_to) -> None:
    """The beside sections (section.Section) at the hand-over and the
    rejoin must leave natural ground between road and path (path._strip's
    "ground"), so the two footprints are already apart there."""
    for sec, which in ((at_from, "hand-over"), (at_to, "rejoin")):
        strip = sec.path.strip if sec.path is not None else "no path"
        if strip != "ground":
            raise ValueError(
                f"path.own[{own.entry}]: the {which} at {sta(sec.s)} does not "
                f"leave natural ground between the road and the path (the strip is "
                f"{strip}): the footprints would meet there; move the {which} or "
                f"widen the separation")


def plan(survey, ground_z, secs) -> list:
    """[(station, left end, right end)] in plan, (easting, northing): each
    of `secs`' earthwork lines' ends where the earthwork's corner stands on
    the ground, along its section ray (earthwork._ground_v), so a wall's
    end is its foot and not its top. `survey(s, u, v)` places a section
    point; `ground_z(n, e)` is the ground."""
    from bimforge.author.corridor.earthwork import _ground_v
    out = []
    for sec in secs:
        line = sec.earthwork_line()
        ends = []
        for u, v in (line[0], line[-1]):
            n, e, _z = survey(sec.s, u, _ground_v(survey, ground_z, sec.s, u, v,
                                                  f"station {sta(sec.s)}"))
            ends.append((e, n))
        out.append((sec.s, ends[0], ends[1]))
    return out


def _side(a, b, p) -> float:
    """p's signed distance from the line a to b, left positive."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length < 1e-12:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    return (dx * (p[1] - a[1]) - dy * (p[0] - a[0])) / length


def _within(a, b, p, tol) -> bool:
    return (min(a[0], b[0]) - tol <= p[0] <= max(a[0], b[0]) + tol
            and min(a[1], b[1]) - tol <= p[1] <= max(a[1], b[1]) + tol)


def _crosses(p, q, a, b, tol: float = 1e-6) -> bool:
    """Whether segments pq and ab cross or touch (to `tol` ft)."""
    d1, d2 = _side(a, b, p), _side(a, b, q)
    d3, d4 = _side(p, q, a), _side(p, q, b)
    if (((d1 > tol and d2 < -tol) or (d1 < -tol and d2 > tol))
            and ((d3 > tol and d4 < -tol) or (d3 < -tol and d4 > tol))):
        return True
    return any(abs(d) <= tol and _within(x, y, z, tol)
               for d, x, y, z in ((d1, a, b, p), (d2, a, b, q),
                                  (d3, p, q, a), (d4, p, q, b)))


def _box(pts) -> tuple:
    xs, ys = [x for x, _y in pts], [y for _x, y in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _apart(m, n, tol: float = 1e-6) -> bool:
    """Whether boxes m and n (_box) are more than `tol` apart."""
    return (m[0] > n[2] + tol or n[0] > m[2] + tol
            or m[1] > n[3] + tol or n[1] > m[3] + tol)


def _segments(footprint: list) -> list:
    """[(station, a, b)]: a footprint's cross-sections, then its two edges,
    each edge segment named by its first station."""
    out = [(s, left, right) for s, left, right in footprint]
    for (s, l0, r0), (_s1, l1, r1) in zip(footprint, footprint[1:]):
        out += [(s, l0, l1), (s, r0, r1)]
    return out


def _quads(footprint: list) -> list:
    """[(station, ring)]: the footprint between each two cross-sections,
    named by its first station."""
    return [(s, [l0, l1, r1, r0])
            for (s, l0, r0), (_s1, l1, r1) in zip(footprint, footprint[1:])]


def _inside(ring, p) -> bool:
    """Whether p is inside the ring (even-odd); on its edge is _crosses'."""
    x, y, got = p[0], p[1], False
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            got = not got
    return got


def check_footprints(own, road: list, path: list) -> None:
    """The own stretch's plan footprint `path` must not cross the road's
    `road` (each plan()'s rows), nor lie on it without crossing (the one
    inside the other), so the earthwork is counted once."""
    road_segs = [(s, a, b, _box((a, b))) for s, a, b in _segments(road)]
    for t, p, q in _segments(path):
        box = _box((p, q))
        for s, a, b, near in road_segs:
            if not _apart(box, near) and _crosses(p, q, a, b):
                raise ValueError(
                    f"path.own[{own.entry}]: its footprint at path station "
                    f"{sta(t)} crosses the road's at {sta(s)}: the earthwork would "
                    f"be counted twice; keep the run off the road's footprint")
    # no edge crosses: one is inside the other only if a corner is
    for inner, outer, path_in in ((path, road, True), (road, path, False)):
        quads = [(s, ring, _box(ring)) for s, ring in _quads(outer)]
        for t, *ends in inner:
            for p in ends:
                for s, ring, near in quads:
                    if not _apart(_box((p,)), near) and _inside(ring, p):
                        at_path, at_road = (t, s) if path_in else (s, t)
                        raise ValueError(
                            f"path.own[{own.entry}]: its footprint at path station "
                            f"{sta(at_path)} lies on the road's at {sta(at_road)}: "
                            f"the earthwork would be counted twice; keep the run "
                            f"off the road's footprint")
