"""The shared-use path's checks and station table (P.6, V1.2 part C).

outputs.path_checks lists every advisory deviation from HDM Index 1003.1
("should"s, and phase 2's USFS equestrian guidance), one row per stretch;
outputs.path lists the path at every section station. Nothing here is an
error: the path's errors are params' and path.validate's.

Stretches are found every SAMPLE_FT along the path and each end refined by
bisection to 1e-6 ft. The path's grade is along its own length: its
profile's rise per road station over (1 - kappa u), u its paved centre's
offset; on an own stretch it is the own profile's grade (own stations run
along the paved centreline).

Runs of grade (sustained, the 30 mph crest rule, the equestrian 200 ft) are
read along the path as it is built: the path beside the road up to an own
stretch's hand-over, the stretch's own profile, the path beside the road
again from its rejoin, joined end to end by length (`Chain`). A row for a
run on more than one piece is written on each system it lies on (the road's
stations, or `own <n> ` and the stretch's own) with the whole run's length.
"""
from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass

CHECK_HEADER = "check,from,to,value,limit,reference"
PATH_HEADER = ("station,side,separation_ft,offset_ft,hinge_elev_ft,path_elev_ft,"
               "difference_ft,grade_pct,strip,barrier,note")
#: outputs.path lists a strip flatter than this (horizontal per vertical,
#: under 1 %) as `level`: too flat to drain, so not a slope to read; the
#: rise itself stays in difference_ft
LEVEL_RATIO = 100.0
#: 1003.1(14)
MAX_GRADE = 0.05
SUSTAINED_GRADE = 0.02
SUSTAINED_FT = 500.0
#: stopping sight distance by design speed, feet (1003.1(11))
SSD_FT = {20: 125.0, 30: 230.0}
#: a downgrade steeper than this for longer than STEEP_RUN_FT takes 30 mph
#: (Table 1003.1)
STEEP_DOWNGRADE = 0.04
STEEP_RUN_FT = 500.0
#: the checks' sampling step along the path, feet
SAMPLE_FT = 1.0
#: USFS-EDG's guidance for the tread
EQ_BUFFER_FT = 6.0                 # Ch. 3
EQ_WIDTH_FT = 8.0                  # Table 4-2, two-way
EQ_CLEAR_FT = 3.0                  # Table 4-1
EQ_CROSS_SLOPE = (0.02, 0.05)      # Table 4-4
EQ_SUSTAINED = 0.10                # Table 4-3; HDM 208.7 at crossings
EQ_PITCH = 0.15                    # Table 4-3
EQ_RUN_FT = 200.0
DECK_CHECK = "deck grade>5% (or a separate path structure)"
_EPS = 1e-9


@dataclass(frozen=True)
class CheckRow:
    check: str
    start: float
    end: float
    value: float
    limit: float | None          # None where the row only lists (a wall)
    reference: str


def _edge(pred, off: float, on: float) -> float:
    """Where pred starts to hold between `off` (false) and `on` (true), on
    the `on` side, to 1e-6 ft."""
    for _ in range(60):
        if abs(on - off) < 1e-7:
            break
        mid = 0.5 * (off + on)
        if pred(mid):
            on = mid
        else:
            off = mid
    return on


def spans(a: float, b: float, pred) -> list:
    """[(s0, s1)]: the stretches of [a, b] where pred(s) holds."""
    n = max(1, math.ceil((b - a) / SAMPLE_FT - _EPS))
    ss = [a + (b - a) * i / n for i in range(n + 1)]
    flags = [bool(pred(s)) for s in ss]
    out, i = [], 0
    while i < len(ss):
        if not flags[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(ss) and flags[j + 1]:
            j += 1
        s0 = ss[i] if i == 0 else _edge(pred, ss[i - 1], ss[i])
        s1 = ss[j] if j == len(ss) - 1 else _edge(pred, ss[j + 1], ss[j])
        out.append((s0, s1))
        i = j + 1
    return out


def _within(a: float, b: float) -> list:
    n = max(1, math.ceil((b - a) / SAMPLE_FT - _EPS))
    return [a + (b - a) * i / n for i in range(n + 1)]


def on_deck(c, s: float) -> bool:
    """Strictly inside a road structure gap, not in a path gap and not in an
    own stretch: the path is on the road's deck. (path._on_deck is the
    structure gap alone; Corridor.path_at is whether a section carries the
    path, also false off its stations and within a path gap's transition.)"""
    return (not c.path.in_gap(s) and not c.path.in_own(s)
            and any(g.kind == "structure" and g.start + _EPS < s < g.end - _EPS
                    for g in c.gaps))


def centre_u(c, s: float) -> float:
    from bimforge.author.corridor.section import grade_edge
    p = c.path
    return grade_edge(c, s, p.side)[0] + p.sign * (p.separation_at(s) + 0.5 * p.width)


def path_grade(c, s: float) -> float:
    """The path's grade at road station s, along its own length."""
    p = c.path
    return p.profile.grade(s) / (1.0 - p.alignment.curvature(s) * centre_u(c, s))


@dataclass(frozen=True)
class Piece:
    """A stretch of the path on one station system: beside the road
    (own=None, road stations) or an own stretch (its own stations). `off`
    takes a station to its place along the chain."""
    own: object
    lo: float
    hi: float
    off: float

    @property
    def x0(self) -> float:
        return self.lo + self.off

    @property
    def x1(self) -> float:
        return self.hi + self.off

    @property
    def label(self) -> str:
        return "" if self.own is None else f"own {self.own.index} "


@dataclass(frozen=True)
class Curve:
    """A vertical curve of the path as built, along the chain."""
    xb: float
    xe: float
    g_in: float            # %: read from the chain where the curve is carried
    g_out: float           # across a hand-over or a rejoin
    length: float
    label: str
    bvc: float             # its stations on its own system
    evc: float


class Chain:
    """The path along its length: beside the road, each own stretch on its
    own profile, beside the road again, end to end (an own stretch counts its
    own length, the road's stations count beside it)."""

    def __init__(self, c) -> None:
        self.c = c
        p = c.path
        pieces, x, s = [], p.s_start, p.s_start
        for o in p.own:
            if o.start - s > _EPS:
                pieces.append(Piece(None, s, o.start, x - s if pieces else 0.0))
                x = pieces[-1].x1
            pieces.append(Piece(o, 0.0, o.length, x))
            x = pieces[-1].x1
            s = o.end
        if p.s_end - s > _EPS or not pieces:
            pieces.append(Piece(None, s, p.s_end, x - s if pieces else 0.0))
        self.pieces = pieces
        self.lo, self.hi = p.s_start, pieces[-1].x1

    def locate(self, x: float) -> tuple:
        """(piece, station on its system) at position x."""
        for pc in self.pieces:
            if x <= pc.x1 + _EPS:
                return pc, x - pc.off
        return self.pieces[-1], x - self.pieces[-1].off

    def grade(self, x: float) -> float:
        """The path's grade along its own length."""
        pc, s = self.locate(x)
        return path_grade(self.c, s) if pc.own is None else pc.own.profile.grade(s)

    def pct(self, x: float) -> float:
        """The profile's grade, in %, where the path is at x."""
        pc, s = self.locate(x)
        prof = self.c.path.profile if pc.own is None else pc.own.profile
        return 100.0 * prof.grade(s)

    def skip(self, x: float) -> bool:
        """On a road deck the path is on: not its own grade to check."""
        pc, s = self.locate(x)
        return pc.own is None and on_deck(self.c, s)

    def parts(self, a: float, b: float) -> list:
        """[(piece, from, to, x_from, x_to)]: [a, b] cut at the pieces' ends,
        each part on its piece's stations."""
        if len(self.pieces) == 1:
            pc = self.pieces[0]
            return [(pc, a - pc.off, b - pc.off, a, b)]
        out = []
        for pc in self.pieces:
            xa, xb = max(a, pc.x0), min(b, pc.x1)
            if xb - xa > _EPS:
                out.append((pc, xa - pc.off, xb - pc.off, xa, xb))
        return out

    @staticmethod
    def note(ref: str, parts: list, pc, run: float) -> str:
        """`ref` as is for a run on one piece; for one across several, a
        note that the row is a piece of it (its rows' values are the run's
        whole, so they do not add up)."""
        others = [q.label.strip() or "road" for q, *_rest in parts if q is not pc]
        if not others:
            return ref
        return f"{ref}; run {run:.2f} ft continues on {' and '.join(others)}"

    def curves(self) -> list:
        """The vertical curves that change the grade, by position: the
        path's beside the road, and each stretch's own. One of the path's
        profile inside a stretch's span is not the path's (it is on the
        stretch's profile there); one across a hand-over or a rejoin is kept
        from its end beside the road, carried its length along the chain,
        and its far grade read from the chain there. Such a curve and the
        stretch's first (or last) curve can list the same change of grade,
        and a side run ignores a curve that overlaps another: accepted, both
        err on listing more."""
        beside = [pc for pc in self.pieces if pc.own is None]
        out = []
        for cv in self.c.path.profile.curves:
            if abs(cv["g_out_pct"] - cv["g_in_pct"]) <= 1e-12:
                continue
            b, e, ln = cv["bvc_station"], cv["evc_station"], cv["length_ft"]
            whole = [pc for pc in beside if pc.lo - _EPS <= b and e <= pc.hi + _EPS]
            if whole:
                off = whole[0].off
                out.append(Curve(b + off, e + off, cv["g_in_pct"], cv["g_out_pct"],
                                 ln, "", b, e))
                continue
            at_b = [pc for pc in beside if pc.lo - _EPS <= b < pc.hi - _EPS]
            at_e = [pc for pc in beside if pc.lo + _EPS < e <= pc.hi + _EPS]
            if at_b:                                   # leaves the road's profile
                xb = b + at_b[0].off
                out.append(Curve(xb, xb + ln, cv["g_in_pct"], self.pct(xb + ln),
                                 ln, "", b, e))
            elif at_e:                                 # joins it again
                xe = e + at_e[0].off
                out.append(Curve(xe - ln, xe, self.pct(xe - ln), cv["g_out_pct"],
                                 ln, "", b, e))
        for pc in self.pieces:
            if pc.own is None:
                continue
            for cv in pc.own.profile.curves:
                if abs(cv["g_out_pct"] - cv["g_in_pct"]) > 1e-12:
                    out.append(Curve(cv["bvc_station"] + pc.off, cv["evc_station"] + pc.off,
                                     cv["g_in_pct"], cv["g_out_pct"], cv["length_ft"],
                                     pc.label, cv["bvc_station"], cv["evc_station"]))
        return sorted(out, key=lambda v: (v.xb, v.xe))


def grade_rows(c, ch=None) -> list:
    """Grades over 5 % (1003.1(14)) and over 2 % for more than 500 ft
    (1003.1(14), "should be limited to 2 percent": for information) on the
    path, off the decks it is on. A run is cut where it passes from the
    road's stations to an own stretch's (or back): a row for each piece,
    each with the run's whole length."""
    ch = ch or Chain(c)

    def steep(limit):
        return lambda x: not ch.skip(x) and abs(ch.grade(x)) > limit + 1e-12

    out = []
    for a, b in spans(ch.lo, ch.hi, steep(MAX_GRADE)):
        for pc, la, lb, xa, xb in ch.parts(a, b):
            top = max(abs(ch.grade(x)) for x in _within(xa, xb))
            out.append(CheckRow(f"{pc.label}grade>5%", la, lb, 100.0 * top,
                                100.0 * MAX_GRADE,
                                ch.note("HDM 1003.1(14)", ch.parts(a, b), pc, b - a)))
    for a, b in spans(ch.lo, ch.hi, steep(SUSTAINED_GRADE)):
        if b - a > SUSTAINED_FT + _EPS:
            parts = ch.parts(a, b)
            for pc, la, lb, _xa, _xb in parts:
                out.append(CheckRow(f"{pc.label}sustained grade>2%", la, lb, b - a,
                                    SUSTAINED_FT,
                                    ch.note("HDM 1003.1(14)", parts, pc, b - a)))
    return out


def deck_rows(c) -> list:
    """A deck the path is on graded over 5 % (1003.1(14), "should"); a path
    gap's stretch is the path structure's, not the deck's."""
    p = c.path
    out = []
    for g in c.gaps:
        if g.kind != "structure":
            continue
        a, b = max(g.start, p.s_start), min(g.end, p.s_end)
        if b - a <= _EPS:
            continue
        for x, y in spans(a, b, lambda s: not p.in_gap(s) and not p.in_own(s)
                          and abs(p.road_profile.grade(s)) > MAX_GRADE + 1e-12):
            top = max(abs(p.road_profile.grade(s)) for s in _within(x, y))
            out.append(CheckRow(DECK_CHECK, x, y, 100.0 * top, 100.0 * MAX_GRADE,
                                "HDM 1003.1(14)"))
    return out


def crest_length(a_pct: float, ssd: float) -> float:
    """The crest vertical curve that gives a path its stopping sight
    distance (1003.1(12)): L = A S^2 / 1600 where S < L, else 2S - 1600/A;
    0 where that is negative (no curve needed)."""
    long = a_pct * ssd * ssd / 1600.0
    if long > ssd:
        return long
    return max(0.0, 2.0 * ssd - 1600.0 / a_pct)


def crest_speed(ch, curves: list, i: int, design_speed: int) -> int:
    """30 mph for curve i of `curves` (`Chain.curves`) where a grade beside
    it is steeper than 4 % for more than 500 ft (a downgrade one way of
    travel or the other, Table 1003.1); else the design speed. A run goes
    from the curve to the next one that changes the grade, or the path's
    end, across a hand-over or a rejoin: the path's grade carries on. A run
    ignores curves that overlap this one (see Chain.curves): accepted."""
    if design_speed == 30:
        return 30
    v = curves[i]
    # a steep run stops at the next vertical curve (a grade change), even
    # where the grade after it is as steep: conservative, it may under-count
    before = [w.xe for w in curves[:i] if w.xe <= v.xb + _EPS]
    after = [w.xb for w in curves[i + 1:] if w.xb >= v.xe - _EPS]
    for g, run in ((v.g_in, max(0.0, v.xb - max(before[-1] if before else ch.lo, ch.lo))),
                   (v.g_out, max(0.0, min(after[0] if after else ch.hi, ch.hi) - v.xe))):
        if abs(g) > 100.0 * STEEP_DOWNGRADE + 1e-9 and run > STEEP_RUN_FT + _EPS:
            return 30
    return 20


def crest_rows(c, ch=None) -> list:
    """Crest vertical curves of the path short of stopping sight distance
    (1003.1(11), (12)): those of its profile beside the road, and each own
    stretch's, on its own stations (`own <n> `)."""
    ch = ch or Chain(c)
    curves = ch.curves()
    out = []
    for i, v in enumerate(curves):
        a_pct = v.g_in - v.g_out
        if a_pct <= 1e-12:
            continue                                     # a sag, or no curve
        speed = crest_speed(ch, curves, i, c.path.design_speed)
        need = crest_length(a_pct, SSD_FT[speed])
        if v.length < need - _EPS:
            out.append(CheckRow(f"{v.label}crest VC short of SSD at {speed} mph",
                                v.bvc, v.evc, v.length, need, "HDM 1003.1(11), (12)"))
    return out


def _shielded(rails, side: str, s: float) -> bool:
    return any(r.side == side and r.start - 1e-6 <= s <= r.end + 1e-6 for r in rails)


def shields(rails, walls_=()) -> list:
    """What stands between the road and its path, each with side, start
    and end: the road's guardrail runs (guardrail.RailRun) and the strip
    walls at the road's hinge (walls.WallRow `wall-road`), whose barrier
    is the road's, as V1.1's automatic fill wall carries one. The rail on
    a `wall-path` is the path's, not a barrier from the road."""
    return list(rails) + [w for w in walls_
                          if w.kind == "wall-road" and w.location == "strip"]


def barrier_rows(c, rails) -> list:
    """A separation under 10 ft with no barrier (`rails`: `shields`) on the
    path's side: a barrier is needed (1003.1(7)). Off the decks."""
    from bimforge.author.corridor.path import BARRIER_SEPARATION_FT
    p = c.path

    def needs(s):
        return (not on_deck(c, s) and not p.in_gap(s) and not p.in_own(s)
                and p.separation_at(s) < BARRIER_SEPARATION_FT - _EPS
                and not _shielded(rails, p.side, s))

    return [CheckRow("barrier needed (separation<10ft)", a, b,
                     min(p.separation_at(s) for s in _within(a, b)),
                     BARRIER_SEPARATION_FT, "HDM 1003.1(7)")
            for a, b in spans(p.s_start, p.s_end, needs)]


def approach_rows(c) -> list:
    """A separation under 5 ft on an approach: a deviation from 1003.1(7)'s
    minimum."""
    from bimforge.author.corridor.path import MIN_SEPARATION_FT, approaches
    p = c.path
    out = []
    for a, b, _e in approaches(c):
        a, b = max(a, p.s_start), min(b, p.s_end)
        for x, y in spans(a, b, lambda s: not p.in_own(s)
                          and p.separation_at(s) < MIN_SEPARATION_FT - _EPS):
            out.append(CheckRow("separation<5ft on an approach", x, y,
                                min(p.separation_at(s) for s in _within(x, y)),
                                MIN_SEPARATION_FT, "HDM 1003.1(7)"))
    return out


def path_gap_rows(c) -> list:
    """Each path gap over a road structure gap: the road's deck carries no
    path there; its width is the bridge family's."""
    out = []
    for pg in c.path.gaps:
        for g in c.gaps:
            if g.kind != "structure":
                continue
            a, b = max(pg.start, g.start), min(pg.end, g.end)
            if b - a > _EPS:
                out.append(CheckRow("path gap over a road structure gap", a, b, b - a,
                                    None, "the deck carries no path there"))
    return out


def equestrian_rows(c) -> list:
    """The tread's advisory rows (USFS-EDG: guidance, never errors), over
    the path's stations, off the decks. The tread runs on each own stretch
    too: its grade rows are `own <n> ` on its own stations, a run across a
    hand-over or rejoin a row for each piece."""
    p = c.path
    eq = p.equestrian
    if eq is None:
        return []
    a, b = p.s_start, p.s_end
    out = []
    for check, value, limit, ref in (
            ("equestrian buffer<6ft", eq.buffer, EQ_BUFFER_FT, "USFS-EDG Ch. 3"),
            ("equestrian tread width<8ft", eq.width, EQ_WIDTH_FT, "USFS-EDG Table 4-2"),
            ("equestrian clear<3ft", eq.clear, EQ_CLEAR_FT, "USFS-EDG Table 4-1")):
        if value < limit - _EPS:
            out.append(CheckRow(check, a, b, value, limit, ref))
    cs = abs(eq.cross_slope)
    lo, hi = EQ_CROSS_SLOPE
    if not lo - _EPS <= cs <= hi + _EPS:
        out.append(CheckRow("equestrian cross slope outside 2-5%", a, b, 100.0 * cs,
                            100.0 * (lo if cs < lo else hi), "USFS-EDG Table 4-4"))
    ch = Chain(c)
    for limit, check in ((EQ_SUSTAINED, "equestrian grade>10% for over 200ft"),
                         (EQ_PITCH, "equestrian grade>15% for over 200ft")):
        for x, y in spans(ch.lo, ch.hi, lambda s, limit=limit: not ch.skip(s)
                          and abs(ch.grade(s)) > limit + 1e-12):
            if y - x > EQ_RUN_FT + _EPS:
                parts = ch.parts(x, y)
                for pc, la, lb, xa, xb in parts:
                    top = max(abs(ch.grade(s)) for s in _within(xa, xb))
                    out.append(CheckRow(f"{pc.label}{check}", la, lb, 100.0 * top,
                                        100.0 * limit,
                                        ch.note("USFS-EDG Table 4-3; HDM 208.7",
                                                parts, pc, y - x)))
    return out


def _off_path_gaps(p, a: float, b: float) -> list:
    """[(s0, s1)]: the stretches of [a, b] outside every path gap and own
    stretch (the path is not on the road's deck there)."""
    out = [(a, b)]
    for g in list(p.gaps) + list(p.own):
        out = [piece for x, y in out
               for piece in ((x, min(y, g.start)), (max(x, g.end), y))
               if piece[1] - piece[0] > _EPS]
    return out


def deck_width_rows(c) -> list:
    """For each road structure gap the path crosses on the deck, the width
    the deck must carry there: from the road's edge of shoulder, the widest
    separation on it, the paved width, the buffer, the tread and its clear
    strip, out to the tread's outer clear edge; the rail the tread side
    needs (54 in by default) is in the check's name. Where a path gap lies
    over the deck, the path is on its own structure and the deck carries
    none of it; where one covers a gap's end the approach is waived, so the
    separation on the deck may be wider than deck_separation_ft. It is
    linear between its rows, so its widest is at a stretch's end or a row.
    The bridge family sizes the deck from it."""
    p = c.path
    eq = p.equestrian
    if eq is None:
        return []
    rest = p.width + eq.buffer + eq.width + eq.clear
    out = []
    for g in c.gaps:
        if g.kind != "structure":
            continue
        a, b = max(g.start, p.s_start), min(g.end, p.s_end)
        if b - a <= _EPS:
            continue
        for x, y in _off_path_gaps(p, a, b):
            sep = max([p.separation_at(x), p.separation_at(y)]
                      + [v for st, v in p.separation if x < st < y])
            out.append(CheckRow(f"deck width to carry (tread rail {eq.rail_height:.2f} ft)",
                                x, y, sep + rest, None, "USFS-EDG Ch. 5; CSP-TH 18.2.1"))
    return out


def wall_rows(wall_rows_) -> list:
    """Each wall in the strip, with its side and height (walls.WallRow)."""
    return [CheckRow(f"strip wall {r.side} {r.kind}", r.start, r.end, r.max_height,
                     None, "HDM 1003.1(7)")
            for r in wall_rows_ if r.location == "strip"]


def own_rows(c) -> list:
    """The radius rows of each own stretch, on its own stations (its grade
    and crest rows are the chain's)."""
    from bimforge.author.corridor.own import radius_rows
    return [r for o in c.path.own for r in radius_rows(o, c.path.design_speed)]


def _order(row) -> tuple:
    """Road rows by station first, then each own stretch's rows by its own
    stations (an own station repeats the road's numbers)."""
    word = row.check.split(" ", 2)
    n = int(word[1]) if word[0] == "own" and word[1].isdigit() else 0
    return (n, row.start, row.check)


def checks(c, rails, walls_) -> list:
    """Every advisory row for corridor `c`'s path, by start station, then
    its own stretches' rows (`own <n> ...`) by their own stations."""
    found = (grade_rows(c) + deck_rows(c) + crest_rows(c) + barrier_rows(c, shields(rails, walls_))
             + approach_rows(c) + path_gap_rows(c) + equestrian_rows(c)
             + deck_width_rows(c) + wall_rows(walls_) + own_rows(c))
    return sorted(found, key=_order)


def checks_csv(rows: list) -> str:
    """The rows as CSV; a field with a comma (a reference) is quoted."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(CHECK_HEADER.split(","))
    for r in rows:
        w.writerow([r.check, f"{r.start:.2f}", f"{r.end:.2f}", f"{r.value:.2f}",
                    "" if r.limit is None else format(r.limit, ".2f"), r.reference])
    return out.getvalue()


def _strip_label(ps) -> str:
    """The strip column: its kind at a wall or on natural ground, else its
    slope ratio, or `level` where it has none (path._ratio's None) or is
    flatter than LEVEL_RATIO - too flat to drain, so not a slope to read."""
    if ps.strip in ("wall-road", "wall-path", "ground"):
        return ps.strip
    if ps.ratio is None or ps.ratio > LEVEL_RATIO:
        return "level"
    return f"{ps.ratio:.2f}"


def _own_ends(p, s: float) -> list:
    """[(note, True)] for an own stretch's hand-over or rejoin at s."""
    return [(f"own {o.index} {end}", True) for o in p.own
            for at, end in ((o.start, "hand-over"), (o.end, "rejoin"))
            if abs(s - at) <= _EPS]


def path_csv(c, secs: list, rails, walls_=()) -> str:
    """outputs.path: one row per section of `secs` that carries the path,
    and one per corridor station on a deck the path crosses. The table is
    on road stations, so it has none inside an own stretch: the hand-over
    and the rejoin rows note it ("own <n> hand-over" / "own <n> rejoin"),
    and without a section row there one is written as a path gap's is.
    The barrier is `rail` where one of `shields(rails, walls_)` stands."""
    from bimforge.author.corridor.path import BARRIER_SEPARATION_FT, on_approach
    p = c.path
    prof = p.road_profile
    guard = shields(rails, walls_)
    rows = []
    for sec in secs:
        ps = sec.path
        if ps is None:
            continue
        s, sf = sec.s, ps.surface
        hinge = prof.elev(s) + (sf.edge[1] - c.depth()) * sf.cg
        pz, g = p.profile.elev(s), path_grade(c, s)
        under = sf.separation < BARRIER_SEPARATION_FT - _EPS
        barrier = ("rail" if under and _shielded(guard, p.side, s)
                   else "yes" if under else "no")
        note = ";".join(x for x, on in (("approach", on_approach(c, s)),
                                        ("grade>5%", abs(g) > MAX_GRADE + 1e-12),
                                        *_own_ends(p, s)) if on)
        rows.append((s, ",".join([
            f"{s:.2f}", p.side, f"{sf.separation:.2f}", f"{centre_u(c, s):.2f}",
            f"{hinge:.3f}", f"{pz:.3f}", f"{pz - hinge:.3f}", f"{100.0 * g:.2f}",
            _strip_label(ps), barrier, note])))
    for o in p.own:
        for s, end in ((o.start, "hand-over"), (o.end, "rejoin")):
            if any(abs(s - x) <= _EPS for x, _r in rows):
                continue
            # one row per station holds here only because own.py refuses an
            # end on a road structure gap (deck) or in or near a path gap
            pz = p.profile.elev(s)
            rows.append((s, f"{s:.2f},{p.side},{p.separation_at(s):.2f},"
                            f"{centre_u(c, s):.2f},,{pz:.3f},,"
                            f"{100.0 * path_grade(c, s):.2f},own {o.index},,"
                            f"own {o.index} {end}"))
    for pg in p.gaps:
        for s in c.stations(pg.start, pg.end):
            pz = p.profile.elev(s)
            rows.append((s, f"{s:.2f},{p.side},{p.separation_at(s):.2f},"
                            f"{centre_u(c, s):.2f},,{pz:.3f},,"
                            f"{100.0 * path_grade(c, s):.2f},path gap,,path gap"))
    for gap in c.gaps:
        if gap.kind != "structure":
            continue
        for s in c.stations(gap.start, gap.end)[1:-1]:
            if not p.covers(s) or p.in_gap(s, 1e-6) or p.in_own(s):
                continue
            pz = p.profile.elev(s)
            rows.append((s, ",".join([
                f"{s:.2f}", p.side, f"{p.separation_at(s):.2f}",
                f"{centre_u(c, s):.2f}", "", f"{pz:.3f}", "",
                f"{100.0 * prof.grade(s):.2f}", "deck", "deck", "deck"])))
    return "\n".join([PATH_HEADER] + [r for _s, r in sorted(rows)]) + "\n"
