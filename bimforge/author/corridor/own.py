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
from dataclasses import dataclass

from bimforge.author.alignment import Alignment, parse_bearing, parse_dms, sta

#: the run rejoins the path's centreline within these
REJOIN_FT = 0.1
REJOIN_DEG = 0.1
#: the beside section turns into the road's own over this at a hand-over
#: and a rejoin, feet: the own stretch's earthwork starts there
HANDOVER_FT = 0.01
#: a curve's length is its radius times its delta within this, feet: the
#: alignment stations by the length and turns by the delta
ARC_TOL_FT = 0.01
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
        if abs(arc - length) > ARC_TOL_FT:
            raise ValueError(f"{here}.length: {length:g} ft is not the curve's "
                             f"{arc:.4f} ft (radius x delta)")
    return value


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
        al = Alignment({"station": 0.0, "northing": n, "easting": e, "azimuth": az},
                       run, name=f"{p.alignment.name} path {k + 1}")
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
        out.append(Own(k + 1, a, b, al, prof,
                       _path_gaps(o.get("gaps"), 0.0, al.s_end, f"{at}.gaps")))
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
