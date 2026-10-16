"""Geometric calibration evidence: station ticks, grid lines, scale bars.

All three detectors are pure-vector — they read only the extracted segment
geometry, never the text layer, so they survive the flattened lettering that
is the NORM on signed bid sets (the v1 Pioneer finding). Each detected
family yields *hypothesis* candidates: the page spacing is measured exactly,
but the world spacing is unknown, so every member of
``SPACING_HYPOTHESES_FT`` ({1, 5, 10, 20, 25, 50, 100} ft) produces one
ft/pt candidate. Hypotheses are cheap and mostly wrong — the calibration
consensus (>=2 independent source types within 0.5%) is what turns them
into an accepted scale. Vision proposes, vectors confirm; here vectors
propose too.

Detected structures:

* **Station ticks** (``detect_station_ticks``) — short segments
  perpendicular to (and touching/near) a long carrier line, evenly spaced.
  Carriers may be dashed (a centerline is many short collinear strokes), so
  carriers are recovered by collinear clustering, not single-segment length.
  Tick candidates are grouped by stroke length (station ticks are drawn
  identical) and the largest arithmetic progression wins — noise ticks that
  happen to touch the carrier do not break the family (the Pioneer sheet 4
  "P" line carries exactly this: twelve 5.04 pt ticks at 90.00 pt among a
  band of unrelated linework).
* **Grid lines** (``detect_grid_lines``) — families of >=4 long parallel
  carriers with uniform perpendicular spacing (profile grids, section rules).
* **Graphic scale bars** (``detect_scale_bars``) — compact collinear runs of
  alternating filled blocks/strokes: 2-4 uniform subdivisions, optionally
  with a distinct half-length subdivision at one end (the classic bar
  scale). The subdivision length is the spacing candidate.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from bimforge.bim.plansheet.vectors import Segment

__all__ = [
    "SPACING_HYPOTHESES_FT", "FT_PER_PT_PLAUSIBLE",
    "Carrier", "TickFamily", "GridFamily", "ScaleBar",
    "find_carriers", "detect_station_ticks", "detect_grid_lines",
    "detect_scale_bars",
]

#: world spacings (ft) hypothesized for a detected uniform page spacing
SPACING_HYPOTHESES_FT = (1.0, 5.0, 10.0, 20.0, 25.0, 50.0, 100.0)
#: plausible ft/pt range for a plan sheet (1"=3.6' .. 1 pt = 5')
FT_PER_PT_PLAUSIBLE = (0.005, 5.0)

# carrier recovery
_ANGLE_BUCKET_DEG = 1.0
_OFFSET_TOL_PT = 1.5
_MIN_CARRIER_SPAN_PT = 100.0
_MIN_CARRIER_COVERAGE = 0.3      # summed stroke length / span (dashed lines ok)
_MIN_CARRIER_SEG_PT = 3.0

# tick gates
_TICK_LEN_PT = (1.5, 30.0)
_TICK_PERP_TOL_DEG = 25.0
_TICK_TOUCH_PT = 4.0
_TICK_LEN_CLUSTER_REL = 0.25
_TICK_DEDUPE_PT = 1.0
_MIN_TICKS = 4                   # >=4 ticks = >=3 uniform gaps
_AP_REL_TOL = 0.02               # gap agreement within 2%
#: minimum credible tick/grid spacing. Flattened lettering explodes into
#: thousands of ~2 pt strokes that would otherwise chain into fake
#: 1-3 pt-spacing "families"; no real station tick or grid rule is spaced
#: that tight on a plottable sheet.
_MIN_SPACING_PT = 6.0
#: a real evenly-spaced family is *tight*; reject sloppier chains
_MAX_FAMILY_SPREAD_PCT = 1.0

# grid gates
_MIN_GRID_LINES = 4

# scale-bar gates
_BAR_SEG_PT = (4.0, 150.0)
_BAR_GAP_PT = 1.0                # blocks touch end-to-end
_BAR_SUBDIVS = (2, 4)            # uniform subdivision count range
_BAR_LEN_REL_TOL = 0.05
_HALF_REL_TOL = 0.12             # half block within 12% of len/2


@dataclass(frozen=True)
class Carrier:
    """A (possibly dashed) straight line: point + unit direction + span."""

    ox: float
    oy: float
    dx: float
    dy: float
    t0: float                    # span along direction, page points
    t1: float
    coverage: float              # summed stroke length / span
    n_segments: int

    @property
    def span(self) -> float:
        return self.t1 - self.t0

    def point_at(self, t: float) -> tuple[float, float]:
        return (self.ox + t * self.dx, self.oy + t * self.dy)

    def project(self, x: float, y: float) -> tuple[float, float]:
        """(along-carrier t, signed perpendicular distance)."""
        px, py = x - self.ox, y - self.oy
        t = px * self.dx + py * self.dy
        d = px * -self.dy + py * self.dx
        return t, d


@dataclass(frozen=True)
class TickFamily:
    """Evenly spaced ticks on one carrier."""

    carrier: Carrier
    positions_t: tuple[float, ...]     # along-carrier tick positions (pt)
    spacing_pt: float
    count: int
    spread_pct: float                  # (max gap - min gap) / spacing * 100
    tick_len_pt: float

    def crossing_points(self) -> list[tuple[float, float]]:
        """Unrotated page point of each tick's carrier crossing."""
        return [self.carrier.point_at(t) for t in self.positions_t]

    def describe(self) -> str:
        return (f"{self.count} ticks ({self.tick_len_pt:.2f} pt) @ "
                f"{self.spacing_pt:.2f} pt spacing, spread {self.spread_pct:.2f}%")


@dataclass(frozen=True)
class GridFamily:
    """>=4 parallel long lines at uniform perpendicular spacing."""

    angle_deg: float
    offsets: tuple[float, ...]
    spacing_pt: float
    count: int
    spread_pct: float

    def describe(self) -> str:
        return (f"{self.count} parallel lines (angle {self.angle_deg:.1f} deg) @ "
                f"{self.spacing_pt:.2f} pt spacing, spread {self.spread_pct:.2f}%")


@dataclass(frozen=True)
class ScaleBar:
    """A graphic bar scale: uniform subdivisions, optional leading half block."""

    x: float                       # bar start, unrotated page points
    y: float
    subdiv_pt: float
    n_subdivs: int
    has_half: bool

    def describe(self) -> str:
        half = " + half block" if self.has_half else ""
        return (f"bar scale at ({self.x:.1f}, {self.y:.1f}): {self.n_subdivs} "
                f"subdivisions of {self.subdiv_pt:.2f} pt{half}")


def _in_bbox(seg: Segment, bbox) -> bool:
    return bbox is None or seg.in_bbox(bbox)


def _angle_deg(seg: Segment) -> float:
    dx, dy = seg.direction
    return math.degrees(math.atan2(dy, dx)) % 180.0


def find_carriers(
    segments: list[Segment],
    bbox: tuple[float, float, float, float] | None = None,
    *,
    min_span_pt: float = _MIN_CARRIER_SPAN_PT,
    min_coverage: float = _MIN_CARRIER_COVERAGE,
) -> list[Carrier]:
    """Recover straight carrier lines by collinear clustering.

    Handles dashed carriers (centerlines): segments are grouped by direction
    (1 deg buckets) and perpendicular offset (1.5 pt clusters); a cluster
    whose along-direction span is long enough and whose summed stroke length
    covers enough of that span is a carrier.
    """
    buckets: dict[int, list[Segment]] = {}
    for s in segments:
        if s.length < _MIN_CARRIER_SEG_PT or not _in_bbox(s, bbox):
            continue
        b = int(_angle_deg(s) / _ANGLE_BUCKET_DEG)
        buckets.setdefault(b, []).append(s)
    # merge the wrap-around bucket (179.x deg == 0 deg)
    nb = int(180.0 / _ANGLE_BUCKET_DEG)
    if 0 in buckets and (nb - 1) in buckets:
        buckets[0] = buckets[0] + buckets.pop(nb - 1)

    carriers: list[Carrier] = []
    for segs in buckets.values():
        # refined bucket direction: length-weighted mean of the unit vectors
        # (sign-aligned to the longest member). The bucket CENTER angle can be
        # 0.5 deg off, which would smear the perpendicular offset by ~11 pt
        # over a 1300 pt border line and break collinear clustering.
        ref = max(segs, key=lambda s: s.length).direction
        vx = vy = 0.0
        for s in segs:
            dx, dy = s.direction
            sign = 1.0 if dx * ref[0] + dy * ref[1] >= 0 else -1.0
            vx += sign * dx * s.length
            vy += sign * dy * s.length
        n = math.hypot(vx, vy)
        if n <= 0.0:
            continue
        dx, dy = vx / n, vy / n
        # offset = perpendicular coordinate of the midpoint
        items = []
        for s in segs:
            mx, my = (s.x1 + s.x2) / 2.0, (s.y1 + s.y2) / 2.0
            rho = mx * -dy + my * dx
            items.append((rho, s))
        items.sort(key=lambda it: it[0])
        # sweep-cluster rho within tolerance
        cluster: list[tuple[float, Segment]] = []
        for it in items + [(float("inf"), None)]:
            if cluster and it[0] - cluster[-1][0] > _OFFSET_TOL_PT:
                carrier = _cluster_to_carrier(cluster, dx, dy,
                                              min_span_pt, min_coverage)
                if carrier:
                    carriers.append(carrier)
                cluster = []
            if it[1] is not None:
                cluster.append(it)
    return carriers


def _cluster_to_carrier(cluster, dx, dy, min_span_pt, min_coverage):
    segs = [s for _rho, s in cluster]
    rho = sum(r for r, _s in cluster) / len(cluster)
    ox, oy = -dy * rho, dx * rho          # foot of the perpendicular from origin
    ts: list[float] = []
    total = 0.0
    for s in segs:
        for x, y in ((s.x1, s.y1), (s.x2, s.y2)):
            ts.append((x - ox) * dx + (y - oy) * dy)
        total += s.length
    t0, t1 = min(ts), max(ts)
    span = t1 - t0
    if span < min_span_pt or total < min_coverage * span:
        return None
    return Carrier(ox=ox, oy=oy, dx=dx, dy=dy, t0=t0, t1=t1,
                   coverage=total / span, n_segments=len(segs))


def _best_arithmetic_chain(positions: list[float], rel_tol: float = _AP_REL_TOL):
    """Largest subset of sorted positions forming an even spacing.

    Tries every successive gap as the base spacing and greedily extends,
    allowing skipped members (a gap of ~k*spacing counts as k steps). Returns
    (members, spacing, spread_pct) or None.
    """
    pos = sorted(positions)
    if len(pos) < _MIN_TICKS:
        return None
    best = None
    gaps = {round(b - a, 4) for a, b in zip(pos, pos[1:])
            if b - a >= _MIN_SPACING_PT}
    for g in sorted(gaps):
        # anchor at each possible start
        for start in range(len(pos)):
            chain = [pos[start]]
            step_gaps: list[float] = []
            last = pos[start]
            for p in pos[start + 1:]:
                gap = p - last
                k = round(gap / g)
                if 1 <= k <= 3 and abs(gap - k * g) <= rel_tol * g * k:
                    chain.append(p)
                    step_gaps.append(gap / k)
                    last = p
            if len(chain) >= _MIN_TICKS:
                spacing = sum(step_gaps) / len(step_gaps)
                spread = ((max(step_gaps) - min(step_gaps)) / spacing * 100.0
                          if len(step_gaps) > 1 else 0.0)
                if spread > _MAX_FAMILY_SPREAD_PCT:
                    continue
                cand = (chain, spacing, spread)
                if best is None or len(chain) > len(best[0]) or (
                        len(chain) == len(best[0]) and spread < best[2]):
                    best = cand
    return best


def detect_station_ticks(
    segments: list[Segment],
    bbox: tuple[float, float, float, float] | None = None,
    *,
    carriers: list[Carrier] | None = None,
) -> list[TickFamily]:
    """Find evenly spaced tick marks on long carrier lines."""
    if carriers is None:
        carriers = find_carriers(segments, bbox)
    shorts = [s for s in segments
              if _TICK_LEN_PT[0] <= s.length <= _TICK_LEN_PT[1]
              and _in_bbox(s, bbox)]
    cos_perp = math.cos(math.radians(90.0 - _TICK_PERP_TOL_DEG))
    out: list[TickFamily] = []
    for car in carriers:
        # ticks: perpendicular-ish short segments touching the carrier
        cands: list[tuple[float, float]] = []      # (t, tick length)
        for s in shorts:
            dx, dy = s.direction
            if abs(dx * car.dx + dy * car.dy) > cos_perp:
                continue                            # not perpendicular enough
            mx, my = (s.x1 + s.x2) / 2.0, (s.y1 + s.y2) / 2.0
            t, d = car.project(mx, my)
            if abs(d) > _TICK_TOUCH_PT + s.length / 2.0:
                continue
            if not (car.t0 - 20.0 <= t <= car.t1 + 20.0):
                continue
            cands.append((t, s.length))
        if len(cands) < _MIN_TICKS:
            continue
        # group by tick stroke length (station ticks are drawn identical)
        cands.sort(key=lambda c: c[1])
        groups: list[list[tuple[float, float]]] = []
        for c in cands:
            if groups and c[1] <= groups[-1][0][1] * (1 + _TICK_LEN_CLUSTER_REL):
                groups[-1].append(c)
            else:
                groups.append([c])
        for grp in groups:
            if len(grp) < _MIN_TICKS:
                continue
            # dedupe overdrawn ticks at the same position
            ts = sorted(t for t, _l in grp)
            dedup = [ts[0]]
            for t in ts[1:]:
                if t - dedup[-1] > _TICK_DEDUPE_PT:
                    dedup.append(t)
            chain = _best_arithmetic_chain(dedup)
            if not chain:
                continue
            members, spacing, spread = chain
            out.append(TickFamily(
                carrier=car, positions_t=tuple(members), spacing_pt=spacing,
                count=len(members), spread_pct=spread,
                tick_len_pt=sum(l for _t, l in grp) / len(grp)))
    # strongest families first
    out.sort(key=lambda f: (-f.count, f.spread_pct))
    return out


def detect_grid_lines(
    segments: list[Segment],
    bbox: tuple[float, float, float, float] | None = None,
    *,
    carriers: list[Carrier] | None = None,
    min_lines: int = _MIN_GRID_LINES,
) -> list[GridFamily]:
    """Find families of parallel long lines at uniform spacing."""
    if carriers is None:
        carriers = find_carriers(segments, bbox)
    by_angle: dict[int, list[Carrier]] = {}
    for car in carriers:
        ang = math.degrees(math.atan2(car.dy, car.dx)) % 180.0
        by_angle.setdefault(int(ang / 2.0), []).append(car)
    out: list[GridFamily] = []
    for b, cars in by_angle.items():
        if len(cars) < min_lines:
            continue
        offsets = sorted(car.ox * -car.dy + car.oy * car.dx for car in cars)
        chain = _best_arithmetic_chain(offsets)
        if not chain or len(chain[0]) < min_lines:
            continue
        members, spacing, spread = chain
        out.append(GridFamily(
            angle_deg=(b + 0.5) * 2.0, offsets=tuple(members),
            spacing_pt=spacing, count=len(members), spread_pct=spread))
    out.sort(key=lambda f: (-f.count, f.spread_pct))
    return out


def detect_scale_bars(
    segments: list[Segment],
    bbox: tuple[float, float, float, float] | None = None,
) -> list[ScaleBar]:
    """Find graphic bar scales: collinear runs of uniform touching blocks."""
    # collect collinear groups of bar-sized strokes
    lines: dict[tuple[int, int], list[tuple[float, float, Segment]]] = {}
    for s in segments:
        if not (_BAR_SEG_PT[0] <= s.length <= _BAR_SEG_PT[1]) or not _in_bbox(s, bbox):
            continue
        dx, dy = s.direction
        ang = _angle_deg(s)
        rho = s.x1 * -math.sin(math.radians(ang)) + s.y1 * math.cos(math.radians(ang))
        key = (int(ang / _ANGLE_BUCKET_DEG), int(rho / _OFFSET_TOL_PT))
        ux, uy = math.cos(math.radians(ang)), math.sin(math.radians(ang))
        ta = s.x1 * ux + s.y1 * uy
        tb = s.x2 * ux + s.y2 * uy
        lines.setdefault(key, []).append((min(ta, tb), max(ta, tb), s))

    out: list[ScaleBar] = []
    for key, iv in lines.items():
        if len(iv) < 2:
            continue
        iv.sort(key=lambda t: (t[0], t[1]))
        # merge exact duplicates (block outlines: top+bottom edges collapse
        # into separate keys; overdrawn strokes into the same one)
        merged: list[tuple[float, float, Segment]] = []
        for t0, t1, s in iv:
            if merged and abs(t0 - merged[-1][0]) < 0.3 and abs(t1 - merged[-1][1]) < 0.3:
                continue
            merged.append((t0, t1, s))
        # runs of touching blocks
        run: list[tuple[float, float, Segment]] = []
        for item in merged + [(float("inf"), float("inf"), None)]:
            if run and item[0] - run[-1][1] > _BAR_GAP_PT:
                bar = _run_to_bar(run)
                if bar:
                    out.append(bar)
                run = []
            if item[2] is not None:
                run.append(item)
    # a filled bar's top and bottom edges both reproduce the bar: dedupe
    dedup: list[ScaleBar] = []
    for bar in sorted(out, key=lambda b: (b.n_subdivs, b.subdiv_pt)):
        if any(d.n_subdivs == bar.n_subdivs and d.has_half == bar.has_half
               and abs(d.subdiv_pt - bar.subdiv_pt) <= 0.02 * d.subdiv_pt
               and math.hypot(d.x - bar.x, d.y - bar.y) < 4.0 * d.subdiv_pt
               for d in dedup):
            continue
        dedup.append(bar)
    return dedup


def _run_to_bar(run) -> ScaleBar | None:
    lens = [t1 - t0 for t0, t1, _s in run]
    if len(lens) < 2:
        return None
    full = max(lens)
    fulls = [l for l in lens if abs(l - full) <= _BAR_LEN_REL_TOL * full]
    halves = [l for l in lens if abs(l - full / 2.0) <= _HALF_REL_TOL * full / 2.0]
    if len(fulls) + len(halves) != len(lens):
        return None                          # stray block lengths: not a bar
    if not (_BAR_SUBDIVS[0] <= len(fulls) <= _BAR_SUBDIVS[1]):
        return None
    if len(halves) > 1:
        return None                          # at most one half block, at one end
    if len(fulls) == 2 and not halves:
        return None                          # two bare blocks: too easy to fake
                                             # (flattened glyphs do it constantly)
    if halves:
        half_len = halves[0]
        if abs(lens[0] - half_len) > 1e-9 and abs(lens[-1] - half_len) > 1e-9:
            return None                      # half block must sit at an end
    seg0 = run[0][2]
    return ScaleBar(x=min(seg0.x1, seg0.x2), y=min(seg0.y1, seg0.y2),
                    subdiv_pt=sum(fulls) / len(fulls), n_subdivs=len(fulls),
                    has_half=bool(halves))


def spacing_candidates(spacing_pt: float) -> list[tuple[float, float]]:
    """(hypothesis_ft, ft_per_pt) for every plausible world spacing."""
    out = []
    for ft in SPACING_HYPOTHESES_FT:
        v = ft / spacing_pt
        if FT_PER_PT_PLAUSIBLE[0] <= v <= FT_PER_PT_PLAUSIBLE[1]:
            out.append((ft, v))
    return out
