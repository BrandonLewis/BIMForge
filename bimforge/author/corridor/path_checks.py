"""The shared-use path's checks and station table (P.6, V1.2 part C).

outputs.path_checks lists every advisory deviation from HDM Index 1003.1
("should"s, and phase 2's USFS equestrian guidance), one row per stretch;
outputs.path lists the path at every section station. Nothing here is an
error: the path's errors are params' and path.validate's.

Stretches are found every SAMPLE_FT along the path and each end refined by
bisection to 1e-6 ft. The path's grade is along its own length: its
profile's rise per road station over (1 - kappa u), u its paved centre's
offset.
"""
from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass

CHECK_HEADER = "check,from,to,value,limit,reference"
PATH_HEADER = ("station,side,separation_ft,offset_ft,hinge_elev_ft,path_elev_ft,"
               "difference_ft,grade_pct,strip,barrier,note")
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
    """Strictly inside a road structure gap and not in a path gap: the path
    is on the road's deck."""
    return (not c.path.in_gap(s)
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


def profile_grade_rows(grade_at, s0: float, s1: float, skip, label: str = "") -> list:
    """Grades over 5 % (1003.1(14)) and over 2 % for more than 500 ft
    (1003.1(14), "should be limited to 2 percent": for information) on
    [s0, s1], where skip(s) is false; `grade_at(s)` the grade along the
    path's own length. `label` prefixes the check (an own stretch's)."""
    out = []

    def steep(limit):
        return lambda s: not skip(s) and abs(grade_at(s)) > limit + 1e-12

    for a, b in spans(s0, s1, steep(MAX_GRADE)):
        top = max(abs(grade_at(s)) for s in _within(a, b))
        out.append(CheckRow(f"{label}grade>5%", a, b, 100.0 * top, 100.0 * MAX_GRADE,
                            "HDM 1003.1(14)"))
    for a, b in spans(s0, s1, steep(SUSTAINED_GRADE)):
        if b - a > SUSTAINED_FT + _EPS:
            out.append(CheckRow(f"{label}sustained grade>2%", a, b, b - a,
                                SUSTAINED_FT, "HDM 1003.1(14)"))
    return out


def grade_rows(c) -> list:
    """The path's grade rows beside the road, off the decks it is on."""
    p = c.path
    return profile_grade_rows(lambda s: path_grade(c, s), p.s_start, p.s_end,
                              lambda s: on_deck(c, s))


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
        for x, y in spans(a, b, lambda s: not p.in_gap(s)
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


def _beside(profile, s0: float, s1: float, i: int, after: bool) -> tuple:
    """(grade %, length): the grade beside curve i of `profile`, after its
    EVC or before its BVC, through constant-grade curves to the next grade
    change or the end of [s0, s1]."""
    # a steep run stops at the next vertical curve (a grade change), even
    # where the grade after it is as steep: conservative, it may under-count
    curves = profile.curves
    if after:
        g, start, end = curves[i]["g_out_pct"], curves[i]["evc_station"], s1
        for cv in curves[i + 1:]:
            if abs(cv["g_out_pct"] - cv["g_in_pct"]) > 1e-12:
                end = cv["bvc_station"]
                break
        return g, max(0.0, min(end, s1) - start)
    g, start, end = curves[i]["g_in_pct"], s0, curves[i]["bvc_station"]
    for cv in reversed(curves[:i]):
        if abs(cv["g_out_pct"] - cv["g_in_pct"]) > 1e-12:
            start = cv["evc_station"]
            break
    return g, max(0.0, end - max(start, s0))


def crest_speed(profile, s0: float, s1: float, design_speed: int, i: int) -> int:
    """30 mph for curve i where a grade beside it is steeper than 4 % for
    more than 500 ft (a downgrade one way of travel or the other, Table
    1003.1); else the design speed."""
    if design_speed == 30:
        return 30
    for g, run in (_beside(profile, s0, s1, i, False), _beside(profile, s0, s1, i, True)):
        if abs(g) > 100.0 * STEEP_DOWNGRADE + 1e-9 and run > STEEP_RUN_FT + _EPS:
            return 30
    return 20


def profile_crest_rows(profile, s0: float, s1: float, design_speed: int,
                       label: str = "") -> list:
    """Crest vertical curves of `profile` short of stopping sight distance
    (1003.1(11), (12))."""
    out = []
    for i, cv in enumerate(profile.curves):
        a_pct = cv["g_in_pct"] - cv["g_out_pct"]
        if a_pct <= 1e-12:
            continue                                     # a sag, or no curve
        speed = crest_speed(profile, s0, s1, design_speed, i)
        need = crest_length(a_pct, SSD_FT[speed])
        if cv["length_ft"] < need - _EPS:
            out.append(CheckRow(f"{label}crest VC short of SSD at {speed} mph",
                                cv["bvc_station"], cv["evc_station"],
                                cv["length_ft"], need, "HDM 1003.1(11), (12)"))
    return out


def crest_rows(c) -> list:
    p = c.path
    return profile_crest_rows(p.profile, p.s_start, p.s_end, p.design_speed)


def _shielded(rails, side: str, s: float) -> bool:
    return any(r.side == side and r.start - 1e-6 <= s <= r.end + 1e-6 for r in rails)


def barrier_rows(c, rails) -> list:
    """A separation under 10 ft with no road guardrail (`rails`,
    guardrail.RailRun) on the path's side: a barrier is needed
    (1003.1(7)). Off the decks."""
    from bimforge.author.corridor.path import BARRIER_SEPARATION_FT
    p = c.path

    def needs(s):
        return (not on_deck(c, s) and not p.in_gap(s)
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
        for x, y in spans(a, b, lambda s: p.separation_at(s) < MIN_SEPARATION_FT - _EPS):
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
    the path's stations, off the decks."""
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
    for limit, check in ((EQ_SUSTAINED, "equestrian grade>10% for over 200ft"),
                         (EQ_PITCH, "equestrian grade>15% for over 200ft")):
        for x, y in spans(a, b, lambda s, limit=limit: not on_deck(c, s)
                          and abs(path_grade(c, s)) > limit + 1e-12):
            if y - x > EQ_RUN_FT + _EPS:
                top = max(abs(path_grade(c, s)) for s in _within(x, y))
                out.append(CheckRow(check, x, y, 100.0 * top, 100.0 * limit,
                                    "USFS-EDG Table 4-3; HDM 208.7"))
    return out


def _off_path_gaps(p, a: float, b: float) -> list:
    """[(s0, s1)]: the stretches of [a, b] outside every path gap."""
    out = [(a, b)]
    for g in p.gaps:
        out = [piece for x, y in out
               for piece in ((x, min(y, g.start)), (max(x, g.end), y))
               if piece[1] - piece[0] > _EPS]
    return out


def deck_width_rows(c) -> list:
    """For each road structure gap the path crosses on the deck, the width
    the deck must carry there: from the road's edge of shoulder, the deck
    separation, the paved width, the buffer, the tread and its clear strip,
    out to the tread's outer clear edge; the rail the tread side needs
    (54 in by default) is in the check's name. Where a path gap lies over
    the deck, the path is on its own structure and the deck carries none of
    it. The bridge family sizes the deck from it."""
    p = c.path
    eq = p.equestrian
    if eq is None:
        return []
    width = p.deck_separation + p.width + eq.buffer + eq.width + eq.clear
    out = []
    for g in c.gaps:
        if g.kind != "structure":
            continue
        a, b = max(g.start, p.s_start), min(g.end, p.s_end)
        if b - a <= _EPS:
            continue
        for x, y in _off_path_gaps(p, a, b):
            out.append(CheckRow(f"deck width to carry (tread rail {eq.rail_height:.2f} ft)",
                                x, y, width, None, "USFS-EDG Ch. 5; CSP-TH 18.2.1"))
    return out


def wall_rows(wall_rows_) -> list:
    """Each wall in the strip, with its side and height (walls.WallRow)."""
    return [CheckRow(f"strip wall {r.side} {r.kind}", r.start, r.end, r.max_height,
                     None, "HDM 1003.1(7)")
            for r in wall_rows_ if r.location == "strip"]


def checks(c, rails, walls_) -> list:
    """Every advisory row for corridor `c`'s path, by start station."""
    found = (grade_rows(c) + deck_rows(c) + crest_rows(c) + barrier_rows(c, rails)
             + approach_rows(c) + path_gap_rows(c) + equestrian_rows(c)
             + deck_width_rows(c) + wall_rows(walls_))
    return sorted(found, key=lambda r: (r.start, r.check))


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
    if ps.strip in ("wall-road", "wall-path", "ground"):
        return ps.strip
    return "level" if math.isinf(ps.ratio) else f"{ps.ratio:.2f}"


def path_csv(c, secs: list, rails) -> str:
    """outputs.path: one row per section of `secs` that carries the path,
    and one per corridor station on a deck the path crosses."""
    from bimforge.author.corridor.path import BARRIER_SEPARATION_FT, on_approach
    p = c.path
    prof = p.road_profile
    rows = []
    for sec in secs:
        ps = sec.path
        if ps is None:
            continue
        s, sf = sec.s, ps.surface
        hinge = prof.elev(s) + (sf.edge[1] - c.depth()) * sf.cg
        pz, g = p.profile.elev(s), path_grade(c, s)
        under = sf.separation < BARRIER_SEPARATION_FT - _EPS
        barrier = ("rail" if under and _shielded(rails, p.side, s)
                   else "yes" if under else "no")
        note = ";".join(x for x, on in (("approach", on_approach(c, s)),
                                        ("grade>5%", abs(g) > MAX_GRADE + 1e-12)) if on)
        rows.append((s, ",".join([
            f"{s:.2f}", p.side, f"{sf.separation:.2f}", f"{centre_u(c, s):.2f}",
            f"{hinge:.3f}", f"{pz:.3f}", f"{pz - hinge:.3f}", f"{100.0 * g:.2f}",
            _strip_label(ps), barrier, note])))
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
            if not p.covers(s) or p.in_gap(s, 1e-6):
                continue
            pz = p.profile.elev(s)
            rows.append((s, ",".join([
                f"{s:.2f}", p.side, f"{p.separation_at(s):.2f}",
                f"{centre_u(c, s):.2f}", "", f"{pz:.3f}", "",
                f"{100.0 * prof.grade(s):.2f}", "deck", "deck", "deck"])))
    return "\n".join([PATH_HEADER] + [r for _s, r in sorted(rows)]) + "\n"
