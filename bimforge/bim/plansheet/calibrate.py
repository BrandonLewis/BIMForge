"""Sheet calibration: derive/load the page→world transform per view zone.

Produces the spec's ``sheet-calibration.yaml``: per zone a ``ft_per_pt``
scale, the /Rotate-derived rotation, the method that produced it and its
evidence/residual.

v2 — calibration that survives flattened text. Signed sets flatten all
lettering to vector outlines (the v1 Pioneer finding), so evidence is pooled
from every source the sheet offers and a zone's scale is AUTO-ACCEPTED only
when **>=2 independent source types agree within 0.5%**:

* **Geometric** (pure vector, immune to flattening; ``detect.py``) —
  station ticks, grid lines, graphic scale bars. Page spacings are measured
  exactly; the world spacing is hypothesized from {1, 5, 10, 20, 25, 50,
  100} ft, one candidate each.
* **Live text dimensions** (``dimension_strings``, the v1 method) — lettered
  feet-inches strings paired with nearby parallel long segments. Only on
  sheets that still carry a text layer.
* **Vision hints** (``hints.py``) — the agent reads the rendered lettering
  and writes hints.yaml; dimension and station-label hints are validated
  against vector geometry before they count. All hints together are ONE
  source type. Scale-note hints carry half weight and can never make a zone
  eligible by themselves — title blocks lie (half-size plots, proven live).

No consensus -> ``CalibrationInsufficient`` carrying a machine-readable
evidence report of every candidate and cluster, so the operating agent
knows exactly what hint to supply next (the CLI exits 2 with the JSON).
A hint disagreeing >2% with the consensus is reported as *contradicted*,
never silently dropped.

Still v1-scoped: zones are explicit (``--zone``), rotation comes from
/Rotate only (axis-aligned views), and the ``alignment:`` block is passed
through verbatim. ``--ft-per-pt``/``--scale`` remain as manual overrides
(method: manual, warned as single-source).
"""
from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass, field
from typing import Optional

import yaml

from bimforge.bim.plansheet.vectors import SheetVectors, rotate_to_visual

__all__ = [
    "CalibrationError", "CalibrationInsufficient", "Zone", "Calibration",
    "DIM_RE", "parse_dimension", "parse_scale",
    "Candidate", "gather_candidates", "consensus",
    "calibrate_zone_from_dimensions", "build_calibration",
    "load_calibration", "save_calibration",
]

# Lettered feet-inches dimension: 45'-0"  3'-0"  1'-6 1/2"  (unicode quotes too)
DIM_RE = re.compile(
    r"(\d+)\s*['’]\s*[-–]\s*(\d+)(?:\s+(\d+)\s*/\s*(\d+))?\s*[\"”]"
)

# Pairing gates (page points / degrees) for dimension_strings calibration.
MIN_DIM_SEG_PT = 8.0        # a dimension line is a *long* straight segment
GATE_PT = 30.0              # max text-center -> segment distance
STATION_GATE_PT = 40.0      # max station-label -> tick-crossing distance
ANGLE_TOL_DEG = 20.0        # text runs parallel to its dimension line
CLUSTER_REL_TOL = 0.02      # candidates within 2% agree (v1 dimension_strings)
_FT_PER_PT_PLAUSIBLE = (1e-4, 1e3)

# v2 consensus gates
CONSENSUS_REL_TOL = 0.005   # >=2 independent source types within 0.5%
CONTRADICTION_REL_TOL = 0.02  # hints >2% off the consensus are flagged
SCALE_NOTE_WEIGHT = 0.5
# A rival cluster whose value is within this of EXACTLY 2x or 1/2x the winner
# is a harmonic conflict: the classic inch/half-inch (or half-size-plot) scale
# ambiguity that geometry alone cannot resolve. Detected and refused. (#249)
HARMONIC_RATIO_REL_TOL = 0.03


class CalibrationError(ValueError):
    """No usable calibration evidence."""


class CalibrationInsufficient(CalibrationError):
    """Evidence exists but no >=2 independent source types agree.

    Carries the per-zone evidence reports (machine-readable dicts listing
    every candidate and cluster) so the operating agent knows what hint to
    supply; the CLI serializes them as JSON and exits 2.
    """

    def __init__(self, message: str, reports: list[dict]):
        super().__init__(message)
        self.reports = reports


def parse_dimension(text: str) -> list[float]:
    """All feet-inches dimension values (decimal feet) lettered in a string."""
    out = []
    for m in DIM_RE.finditer(text):
        ft = int(m.group(1))
        inches = float(m.group(2))
        if m.group(3) and m.group(4) and int(m.group(4)) != 0:
            inches += int(m.group(3)) / int(m.group(4))
        out.append(ft + inches / 12.0)
    return out


def parse_scale(text: str) -> float:
    """Lettered scale -> ft per point (72 pt per inch).

    Accepts '1/4in=1ft', '1in=40ft', and the lettered title-block forms
    '1/8" = 1'-0"' / '3/16" = 1'-0"' (unicode quotes too).
    """
    m = re.fullmatch(
        r"\s*(\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)?)\s*(?:in|[\"”])\s*=\s*"
        r"(\d+(?:\.\d+)?)\s*(?:ft|['’])(?:\s*[-–]\s*(\d+(?:\.\d+)?)\s*(?:in|[\"”]))?\s*",
        text)
    if not m:
        raise CalibrationError(
            f"cannot parse scale {text!r} (expected e.g. '1/4in=1ft', "
            "'1in=40ft' or '1/8\" = 1'-0\"')")
    frac = m.group(1)
    if "/" in frac:
        num, den = frac.split("/")
        inches = float(num) / float(den)
    else:
        inches = float(frac)
    feet = float(m.group(2))
    if m.group(3):
        feet += float(m.group(3)) / 12.0
    if inches <= 0 or feet <= 0:
        raise CalibrationError(f"non-positive scale {text!r}")
    return feet / (inches * 72.0)


@dataclass
class Zone:
    """One view zone's page→world transform (bbox in unrotated page points)."""

    name: str
    bbox_pt: tuple[float, float, float, float]
    ft_per_pt: float
    rotation_deg: int = 0
    world: str = "local_ft"           # local_ft | station_offset | state_plane
    method: str = "manual"            # dimension_strings | manual
    evidence: str = ""
    residual_ft: Optional[float] = None
    anchor: Optional[dict] = None     # {"page": [x, y], "world": [wx, wy]}
    # unrotated page dims, needed to apply rotation_deg; carried in the yaml
    page_size_pt: tuple[float, float] = (0.0, 0.0)

    def _visual_bbox(self) -> tuple[float, float, float, float]:
        w, h = self.page_size_pt
        x0, y0, x1, y1 = self.bbox_pt
        pts = [rotate_to_visual(x, y, self.rotation_deg, w, h)
               for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))

    def to_world(self, x: float, y: float) -> tuple[float, float]:
        """Unrotated page point -> world feet (+x right, +y up on the visual sheet)."""
        w, h = self.page_size_pt
        vx, vy = rotate_to_visual(x, y, self.rotation_deg, w, h)
        s = self.ft_per_pt
        if self.anchor:
            ax, ay = self.anchor["page"]
            awx, awy = self.anchor["world"]
            avx, avy = rotate_to_visual(ax, ay, self.rotation_deg, w, h)
            return (awx + (vx - avx) * s, awy - (vy - avy) * s)
        bx0, _by0, _bx1, by1 = self._visual_bbox()
        return ((vx - bx0) * s, (by1 - vy) * s)

    def contains(self, x: float, y: float) -> bool:
        x0, y0, x1, y1 = self.bbox_pt
        return x0 <= x <= x1 and y0 <= y <= y1


@dataclass
class Calibration:
    """One sheet's calibration: zones + optional alignment passthrough."""

    sheet: int                        # 1-based sheet / PDF page number
    page_index: int                   # 0-based
    zones: list[Zone] = field(default_factory=list)
    alignment: Optional[dict] = None  # passed through verbatim (v1)
    warnings: list[str] = field(default_factory=list)
    evidence_reports: list[dict] = field(default_factory=list)  # per zone (v2)

    def zone(self, name: Optional[str] = None) -> Zone:
        if not self.zones:
            raise CalibrationError("calibration has no zones")
        if name is None:
            return self.zones[0]
        for z in self.zones:
            if z.name == name:
                return z
        raise CalibrationError(
            f"no zone named {name!r} (have: {[z.name for z in self.zones]})")


def calibrate_zone_from_dimensions(
    sv: SheetVectors,
    name: str,
    bbox: tuple[float, float, float, float],
    *,
    min_seg_pt: float = MIN_DIM_SEG_PT,
    gate_pt: float = GATE_PT,
    angle_tol_deg: float = ANGLE_TOL_DEG,
    cluster_rel_tol: float = CLUSTER_REL_TOL,
) -> tuple[Zone, list[str]]:
    """Derive a zone's ft/pt from lettered dimension strings.

    Pairs every feet-inches string in the zone with each nearby long straight
    segment running parallel to the text (within ``gate_pt`` of the text
    center, within ``angle_tol_deg`` of its direction), forming ft/pt
    candidates; clusters the candidates at ``cluster_rel_tol`` and takes the
    dominant cluster's median. Returns (zone, warnings). Raises
    ``CalibrationError`` when no candidate pairs exist.
    """
    cos_tol = math.cos(math.radians(angle_tol_deg))
    dims = []                        # (feet, x, y, dir)
    for t in sv.texts:
        if not t.in_bbox(bbox):
            continue
        for feet in parse_dimension(t.text):
            if feet > 0:
                dims.append((feet, t.x, t.y, t.dir))
    segs = [s for s in sv.segments if s.in_bbox(bbox) and s.length >= min_seg_pt]

    candidates = []                  # (ft_per_pt, feet, seg_len)
    for feet, tx, ty, tdir in dims:
        for s in segs:
            if _point_segment_dist(tx, ty, s) > gate_pt:
                continue
            dx, dy = s.direction
            if (tdir[0] or tdir[1]) and abs(dx * tdir[0] + dy * tdir[1]) < cos_tol:
                continue
            cand = feet / s.length
            if _FT_PER_PT_PLAUSIBLE[0] <= cand <= _FT_PER_PT_PLAUSIBLE[1]:
                candidates.append((cand, feet, s.length))

    if not candidates:
        raise CalibrationError(
            f"zone {name!r}: no dimension-string evidence — found "
            f"{len(dims)} feet-inches strings and {len(segs)} candidate segments, "
            "but no string/segment pair within the gates. Supply --ft-per-pt or "
            "--scale, or adjust the zone bbox.")

    cluster = _dominant_cluster([c[0] for c in candidates], cluster_rel_tol)
    ft_per_pt = statistics.median(cluster)
    members = [c for c in candidates if c[0] in set(cluster)]
    residual = max(abs(feet - seg_len * ft_per_pt) for _v, feet, seg_len in members)
    spread = (max(cluster) - min(cluster)) / ft_per_pt * 100.0 if len(cluster) > 1 else 0.0
    n_strings = len({(feet, x, y) for feet, x, y, _d in dims})
    evidence = (f"{len(cluster)}/{len(candidates)} dim-line pairs from "
                f"{n_strings} dimension strings; ft/pt spread {spread:.2f}%")

    warnings = []
    if len(cluster) < 2:
        warnings.append(
            f"zone {name!r}: only ONE evidence pair supports ft_per_pt="
            f"{ft_per_pt:.6f} — the spec requires >=2 agreeing sources to fully "
            "trust a zone; verify against a known dimension before relying on it.")

    zone = Zone(name=name, bbox_pt=tuple(bbox), ft_per_pt=ft_per_pt,
                rotation_deg=sv.rotation, method="dimension_strings",
                evidence=evidence, residual_ft=round(residual, 4),
                page_size_pt=(sv.width, sv.height))
    return zone, warnings


def _point_segment_dist(px: float, py: float, seg) -> float:
    ax, ay, bx, by = seg.x1, seg.y1, seg.x2, seg.y2
    dx, dy = bx - ax, by - ay
    d2 = dx * dx + dy * dy
    if d2 <= 0.0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / d2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _dominant_cluster(values: list[float], rel_tol: float) -> list[float]:
    """Largest group of values mutually within rel_tol of the group seed."""
    best: list[float] = []
    for seed in values:
        group = [v for v in values if abs(v - seed) <= rel_tol * seed]
        if len(group) > len(best) or (
                len(group) == len(best) and group and best
                and (max(group) - min(group)) < (max(best) - min(best))):
            best = group
    return sorted(best)


# ---------------------------------------------------------------------------
# v2: pooled evidence candidates + >=2-independent-source consensus
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Candidate:
    """One ft/pt proposal from one evidence source.

    ``source`` is the independence unit for the >=2-source rule: "ticks",
    "grid", "scale_bar", "text_dims" or "hints" (ALL hints together are one
    source type — they share the failure mode of a misread). ``qualifying``
    is False for candidates that may support a cluster but never make it
    eligible on their own source type (scale notes: title blocks lie).

    ``measured`` separates *measured* evidence — a lettered world value tied
    to an exactly-measured vector length (text dims, hint dimensions,
    station-label pairs) — from *hypothesis* evidence (a tick/grid/bar
    spacing whose world value is guessed from the standard set). Hypothesis
    sources agree with each other by construction whenever two detected
    spacings sit in a small rational ratio, so a cluster is never accepted
    on hypotheses alone: eligibility requires >=2 qualifying source types
    AND at least one measured member (vision/text proposes the world value,
    vectors confirm — neither alone).

    ``length_pt``/``world_ft`` feed the accepted zone's ``residual_ft``.
    """

    source: str
    kind: str
    ft_per_pt: float
    weight: float = 1.0
    qualifying: bool = True
    measured: bool = False
    detail: str = ""
    length_pt: Optional[float] = None
    world_ft: Optional[float] = None

    def as_dict(self) -> dict:
        d = {"source": self.source, "kind": self.kind,
             "ft_per_pt": round(self.ft_per_pt, 8), "weight": self.weight,
             "qualifying": self.qualifying, "measured": self.measured,
             "detail": self.detail}
        if self.length_pt is not None:
            d["length_pt"] = round(self.length_pt, 3)
        if self.world_ft is not None:
            d["world_ft"] = self.world_ft
        return d


def _text_dim_candidates(sv: SheetVectors, bbox) -> list[Candidate]:
    """v1 dimension_strings pairs as consensus candidates (live text only)."""
    cos_tol = math.cos(math.radians(ANGLE_TOL_DEG))
    segs = [s for s in sv.segments
            if s.in_bbox(bbox) and s.length >= MIN_DIM_SEG_PT]
    out: list[Candidate] = []
    for t in sv.texts:
        if not t.in_bbox(bbox):
            continue
        for feet in parse_dimension(t.text):
            if feet <= 0:
                continue
            for s in segs:
                if _point_segment_dist(t.x, t.y, s) > GATE_PT:
                    continue
                dx, dy = s.direction
                if (t.dir[0] or t.dir[1]) and \
                        abs(dx * t.dir[0] + dy * t.dir[1]) < cos_tol:
                    continue
                v = feet / s.length
                if _FT_PER_PT_PLAUSIBLE[0] <= v <= _FT_PER_PT_PLAUSIBLE[1]:
                    out.append(Candidate(
                        source="text_dims", kind="dimension_string",
                        ft_per_pt=v, measured=True,
                        length_pt=s.length, world_ft=feet,
                        detail=f"{t.text.strip()!r} vs {s.length:.2f} pt segment"))
    return out


def _geometric_candidates(sv: SheetVectors, bbox) -> tuple[list[Candidate], list]:
    """Tick/grid/scale-bar hypothesis candidates; also returns tick families."""
    from bimforge.bim.plansheet import detect

    segs = [s for s in sv.segments if s.in_bbox(bbox)]
    carriers = detect.find_carriers(segs)
    tick_fams = detect.detect_station_ticks(segs, carriers=carriers)
    grids = detect.detect_grid_lines(segs, carriers=carriers)
    bars = detect.detect_scale_bars(segs)

    out: list[Candidate] = []
    for f in tick_fams:
        for ft, v in detect.spacing_candidates(f.spacing_pt):
            out.append(Candidate(
                source="ticks", kind=f"tick_family@{ft:g}ft", ft_per_pt=v,
                length_pt=f.spacing_pt, world_ft=ft,
                detail=f"{f.describe()} = {ft:g} ft hypothesis"))
    for g in grids:
        for ft, v in detect.spacing_candidates(g.spacing_pt):
            out.append(Candidate(
                source="grid", kind=f"grid@{ft:g}ft", ft_per_pt=v,
                length_pt=g.spacing_pt, world_ft=ft,
                detail=f"{g.describe()} = {ft:g} ft hypothesis"))
    for b in bars:
        for ft, v in detect.spacing_candidates(b.subdiv_pt):
            out.append(Candidate(
                source="scale_bar", kind=f"scale_bar@{ft:g}ft", ft_per_pt=v,
                length_pt=b.subdiv_pt, world_ft=ft,
                detail=f"{b.describe()} = {ft:g} ft hypothesis"))
    return out, tick_fams


#: pairwise ft/pt values of one family's station labels must agree this well
_STATION_CONSISTENCY_REL = 0.01


def _station_family_matches(zone_hints, tick_fams):
    """Match station-label hints to tick families, family by family.

    Returns ``[(family, [(station_ft, t, hint), ...]), ...]`` for families
    that explain the labels CONSISTENTLY: every label matches a distinct
    crossing, and all pairwise Δstation/Δt values agree within 1%. Matching
    nearest-crossing across all families would be a trap — a dense noise
    family has a crossing near *any* point on the carrier, so each family
    must explain the labels on its own or not at all.
    """
    from bimforge.bim.plansheet.hints import parse_station

    labels = []
    for h in zone_hints:
        if h.kind != "station_label":
            continue
        sta = parse_station(h.text)
        if sta is not None:
            labels.append((sta, h))
    if len(labels) < 2:
        return []

    out = []
    for fam in tick_fams:
        matches = []
        used_t: set[float] = set()
        for sta, h in labels:
            best = None               # (dist, t)
            for t, (cx, cy) in zip(fam.positions_t, fam.crossing_points()):
                if t in used_t:
                    continue
                d = math.hypot(h.x - cx, h.y - cy)
                if d <= STATION_GATE_PT and (best is None or d < best[0]):
                    best = (d, t)
            if best is not None:
                used_t.add(best[1])
                matches.append((sta, best[1], h))
        if len(matches) < 2:
            continue
        vs = []
        ok = True
        for i in range(len(matches)):
            for j in range(i + 1, len(matches)):
                sa, ta, _ = matches[i]
                sb, tb, _ = matches[j]
                if sa == sb or ta == tb:
                    ok = False
                    break
                vs.append(abs(sb - sa) / abs(tb - ta))
            if not ok:
                break
        if not ok or not vs:
            continue
        vs.sort()
        med = vs[len(vs) // 2]
        if any(abs(v - med) > _STATION_CONSISTENCY_REL * med for v in vs):
            continue                  # this family cannot explain the labels
        out.append((fam, matches))
    return out


def _hint_candidates(zone_hints, sv: SheetVectors, bbox,
                     tick_fams) -> tuple[list[Candidate], Optional[dict]]:
    """Vector-validated candidates from vision hints (one source type).

    Returns (candidates, anchor) where anchor is a ready-to-use zone anchor
    ({"page": [x, y], "world": [station_ft, 0.0]}) from the best station-
    label/tick-family match, or None.
    """
    from bimforge.bim.plansheet.hints import nearest_distance

    segs = [s for s in sv.segments
            if s.in_bbox(bbox) and s.length >= MIN_DIM_SEG_PT]
    out: list[Candidate] = []
    for h in zone_hints:
        if h.kind == "dimension":
            for feet in parse_dimension(h.text):
                if feet <= 0:
                    continue
                for s in segs:
                    if nearest_distance(h.x, h.y, s) > GATE_PT:
                        continue
                    v = feet / s.length
                    if _FT_PER_PT_PLAUSIBLE[0] <= v <= _FT_PER_PT_PLAUSIBLE[1]:
                        out.append(Candidate(
                            source="hints", kind="hint:dimension",
                            ft_per_pt=v, measured=True,
                            length_pt=s.length, world_ft=feet,
                            detail=(f"hint {h.text!r} near ({h.x:.1f}, {h.y:.1f})"
                                    f" vs {s.length:.2f} pt segment")))
        elif h.kind == "scale_note":
            v = parse_scale(h.text)
            out.append(Candidate(
                source="hints", kind="hint:scale_note", ft_per_pt=v,
                weight=SCALE_NOTE_WEIGHT, qualifying=False,
                detail=(f"lettered scale {h.text!r} — half weight, never "
                        "auto-accepts alone (title blocks lie on half-size plots)")))

    anchor = None
    fam_matches = _station_family_matches(zone_hints, tick_fams)
    for fam, matches in fam_matches:
        for i in range(len(matches)):
            for j in range(i + 1, len(matches)):
                sa, ta, ha = matches[i]
                sb, tb, hb = matches[j]
                v = abs(sb - sa) / abs(tb - ta)
                if _FT_PER_PT_PLAUSIBLE[0] <= v <= _FT_PER_PT_PLAUSIBLE[1]:
                    out.append(Candidate(
                        source="hints", kind="hint:station_pair", ft_per_pt=v,
                        measured=True,
                        length_pt=abs(tb - ta), world_ft=abs(sb - sa),
                        detail=(f"stations {ha.text!r} and {hb.text!r} anchored "
                                f"to '{fam.describe()}' crossings "
                                f"{abs(tb - ta):.2f} pt apart")))
        if anchor is None:
            sta0, t0, _h0 = matches[0]
            cx, cy = fam.carrier.point_at(t0)
            anchor = {"page": [round(cx, 3), round(cy, 3)],
                      "world": [sta0, 0.0]}
    return out, anchor


def gather_candidates(
    sv: SheetVectors,
    bbox: tuple[float, float, float, float],
    zone_hints=None,
) -> tuple[list[Candidate], Optional[dict]]:
    """Pool candidates from every source.

    Returns (candidates, station_anchor) — the anchor is a zone anchor dict
    from the best station-label/tick-family match, when hints provide one.
    """
    cands = _text_dim_candidates(sv, bbox)
    geo, tick_fams = _geometric_candidates(sv, bbox)
    cands.extend(geo)
    anchor = None
    if zone_hints:
        hc, anchor = _hint_candidates(zone_hints, sv, bbox, tick_fams)
        cands.extend(hc)
    return cands, anchor


def consensus(
    candidates: list[Candidate],
    rel_tol: float = CONSENSUS_REL_TOL,
) -> tuple[Optional[float], list[dict]]:
    """Cluster candidates; accept the best cluster backed by >=2 source types.

    Returns (accepted ft_per_pt or None, cluster report dicts). A cluster is
    *eligible* when its QUALIFYING members span >=2 distinct source types
    (scale notes never qualify) AND it contains at least one MEASURED
    member — tick/grid/bar spacing hypotheses can never accept a scale
    among themselves (two spacings in a rational ratio "agree" trivially).
    The winner is the eligible cluster with the highest summed weight
    (tie: tightest spread); its value is the weighted median of members.
    """
    clusters: list[dict] = []
    seen: set[frozenset] = set()
    for seed in candidates:
        members = [c for c in candidates
                   if abs(c.ft_per_pt - seed.ft_per_pt) <= rel_tol * seed.ft_per_pt]
        key = frozenset(id(c) for c in members)
        if key in seen:
            continue
        seen.add(key)
        vals = sorted(c.ft_per_pt for c in members)
        qual_sources = sorted({c.source for c in members if c.qualifying})
        has_measured = any(c.measured for c in members)
        value = _weighted_median(members)
        spread = ((vals[-1] - vals[0]) / value * 100.0) if len(vals) > 1 else 0.0
        clusters.append({
            "ft_per_pt": round(value, 8),
            "members": [c.as_dict() for c in members],
            "sources": sorted({c.source for c in members}),
            "qualifying_sources": qual_sources,
            "measured": has_measured,
            "weight": round(sum(c.weight for c in members), 2),
            "spread_pct": round(spread, 3),
            "eligible": len(qual_sources) >= 2 and has_measured,
            "_members": members,
        })
    clusters.sort(key=lambda c: (-c["weight"], c["spread_pct"]))
    winner = next((c for c in clusters if c["eligible"]), None)
    if winner is None:
        return None, clusters
    sibling = _harmonic_sibling(winner, clusters)
    if sibling is not None:
        # Harmonic ambiguity: a populated, measured rival sits at exactly
        # 2x/1/2x the winner. Both fit the geometry (a half-inch segment read as
        # the note's inch doubles the scale and quadruples areas), so refuse to
        # auto-accept and force disambiguation from an independent measured
        # source. Record the conflict on both clusters for the evidence report.
        winner["harmonic_conflict"] = round(sibling["ft_per_pt"], 8)
        sibling["harmonic_conflict"] = round(winner["ft_per_pt"], 8)
        return None, clusters
    return winner["ft_per_pt"], clusters


def _harmonic_sibling(winner: dict, clusters: list[dict]) -> Optional[dict]:
    """The populated, measured cluster (if any) sitting at exactly 2x or 1/2x
    the winner's ft/pt — the harmonic-ambiguity signal. Hypothesis-only rivals
    (tick/grid major-vs-minor spacings routinely differ by 2x) are ignored: a
    conflict needs a MEASURED world value tied to a segment on the rival side,
    the same bar that makes a cluster eligible in the first place. (#249)"""
    v = winner["ft_per_pt"]
    if v <= 0:
        return None
    for other in clusters:
        if other is winner:
            continue
        if not (other["measured"] and len(other["_members"]) >= 2):
            continue
        ratio = other["ft_per_pt"] / v
        if (abs(ratio / 2.0 - 1.0) <= HARMONIC_RATIO_REL_TOL
                or abs(ratio * 2.0 - 1.0) <= HARMONIC_RATIO_REL_TOL):
            return other
    return None


def _weighted_median(members: list[Candidate]) -> float:
    items = sorted(members, key=lambda c: c.ft_per_pt)
    half = sum(c.weight for c in items) / 2.0
    acc = 0.0
    for c in items:
        acc += c.weight
        if acc >= half:
            return c.ft_per_pt
    return items[-1].ft_per_pt


def _zone_report(zname, bbox, cands, clusters, accepted) -> dict:
    report = {
        "zone": zname,
        "bbox_pt": [round(v, 3) for v in bbox],
        "accepted": accepted,
        "candidates": [c.as_dict() for c in cands],
        "clusters": [{k: v for k, v in c.items() if k != "_members"}
                     for c in clusters],
    }
    if accepted is None:
        conflicted = sorted(
            (c["ft_per_pt"] for c in clusters
             if c.get("harmonic_conflict") is not None))
        if conflicted:
            report["note"] = (
                "HARMONIC AMBIGUITY: two populated, measured clusters sit at "
                f"exactly a 2x / half ratio ({conflicted}). A half-inch segment "
                "read as the scale note's inch doubles ft/pt (and quadruples "
                "areas), and the tick/bar clusters then corroborate the wrong "
                "value — so consensus refuses to auto-accept. Disambiguate with "
                "an INDEPENDENT MEASURED source: a PDF /Annots station chain "
                "(consecutive labels are 100 ft apart) settles it directly, or "
                "supply a hint dimension whose ft/pt matches exactly one of the "
                "two, or --ft-per-pt from a known length.")
        else:
            srcs = sorted({c.source for c in cands})
            report["note"] = (
                "no cluster with a measured member is backed by >=2 independent "
                "qualifying source types "
                f"(sources seen: {srcs or 'none'}). Render the sheet (est-bim "
                "calibrate --render), read the flattened lettering, and supply "
                "hints.yaml (kind=dimension near a lettered dimension line is the "
                "strongest); geometric candidates above show which ft/pt values a "
                "hint would confirm.")
    return report


def _accept_zone(sv, zname, bbox, value, clusters, cands,
                 station_anchor, warnings) -> Zone:
    cluster = next(c for c in clusters if c["eligible"]
                   and c["ft_per_pt"] == value)
    members = cluster["_members"]
    measured = [c for c in members if c.length_pt and c.world_ft]
    residual = max((abs(c.world_ft - c.length_pt * value) for c in measured),
                   default=None)
    srcs = cluster["qualifying_sources"]
    n_by_src = {s: sum(1 for c in members if c.source == s) for s in
                sorted({c.source for c in members})}
    evidence = (f"consensus of {len(members)} candidates from "
                + " + ".join(f"{s}({n_by_src[s]})" for s in n_by_src)
                + f"; spread {cluster['spread_pct']:.3f}%")
    zone = Zone(name=zname, bbox_pt=tuple(bbox), ft_per_pt=value,
                rotation_deg=sv.rotation,
                method="consensus:" + "+".join(srcs),
                evidence=evidence,
                residual_ft=(round(residual, 4) if residual is not None else None),
                page_size_pt=(sv.width, sv.height))

    # contradicted hints: >2% off the consensus — reported, never dropped
    for c in cands:
        if c.source == "hints" and \
                abs(c.ft_per_pt - value) > CONTRADICTION_REL_TOL * value:
            warnings.append(
                f"zone {zname!r}: CONTRADICTED hint {c.detail} -> "
                f"{c.ft_per_pt:.6f} ft/pt disagrees "
                f"{abs(c.ft_per_pt - value) / value * 100:.1f}% with the "
                f"consensus {value:.6f}")

    # station-label anchor: the label/tick-family match pins world x along
    # the carrier (station feet at the tick crossing)
    if station_anchor is not None:
        zone.anchor = station_anchor
        zone.world = "station_offset"
    return zone


def build_calibration(
    sv: SheetVectors,
    sheet: int,
    *,
    zones: Optional[list[tuple[str, tuple[float, float, float, float]]]] = None,
    ft_per_pt: Optional[float] = None,
    scale: Optional[str] = None,
    alignment: Optional[dict] = None,
    hints=None,
) -> Calibration:
    """Calibrate a sheet by pooled-evidence consensus, or a manual override.

    ``zones`` is a list of (name, bbox_pt); default is one full-page zone.
    ``hints`` is a list of ``hints.Hint`` (see ``hints.load_hints``).
    ``ft_per_pt``/``scale`` short-circuit evidence gathering (method: manual).

    Every zone must reach the >=2-independent-source consensus; otherwise
    ``CalibrationInsufficient`` is raised carrying the per-zone evidence
    reports (the CLI serializes them and exits 2). Reports for *all* zones —
    accepted or not — are attached to the returned ``Calibration`` as
    ``evidence_reports``.
    """
    if ft_per_pt is not None and scale is not None:
        raise CalibrationError("give either --ft-per-pt or --scale, not both")
    if scale is not None:
        ft_per_pt = parse_scale(scale)

    zone_specs = zones or [("full", (0.0, 0.0, sv.width, sv.height))]
    calib = Calibration(sheet=sheet, page_index=sv.page_index, alignment=alignment)

    from bimforge.bim.plansheet.hints import hints_for_zone

    failed: list[str] = []
    for zname, bbox in zone_specs:
        if ft_per_pt is not None:
            calib.zones.append(Zone(
                name=zname, bbox_pt=tuple(bbox), ft_per_pt=float(ft_per_pt),
                rotation_deg=sv.rotation, method="manual",
                evidence="manual override (no sheet evidence)",
                residual_ft=None, page_size_pt=(sv.width, sv.height)))
            calib.warnings.append(
                f"zone {zname!r}: manual scale override — a single evidence source; "
                "the spec requires >=2 to fully trust a zone. Cross-check one "
                "lettered dimension against `est-bim vectors` output.")
            continue
        zone_hints = hints_for_zone(hints, zname, bbox) if hints else []
        cands, station_anchor = gather_candidates(sv, bbox, zone_hints)
        value, clusters = consensus(cands)
        if value is None:
            calib.evidence_reports.append(
                _zone_report(zname, bbox, cands, clusters, None))
            failed.append(zname)
            continue
        zone = _accept_zone(sv, zname, bbox, value, clusters, cands,
                            station_anchor, calib.warnings)
        calib.zones.append(zone)
        calib.evidence_reports.append(_zone_report(
            zname, bbox, cands, clusters,
            {"ft_per_pt": zone.ft_per_pt, "method": zone.method,
             "evidence": zone.evidence, "residual_ft": zone.residual_ft}))

    if failed:
        raise CalibrationInsufficient(
            f"zones {failed} found no >=2-source consensus — see the evidence "
            "report for every candidate (exit 2); supply hints.yaml or a "
            "manual --ft-per-pt/--scale.",
            calib.evidence_reports)

    if alignment is not None:
        for z in calib.zones:
            if z.method != "manual":
                if z.world == "local_ft":
                    z.world = "station_offset"
    return calib


# ---------------------------------------------------------------------------
# YAML round-trip (the spec's sheet-calibration.yaml)
# ---------------------------------------------------------------------------
def save_calibration(calib: Calibration, path) -> None:
    data: dict = {
        "sheet": calib.sheet,
        "page_index": calib.page_index,
        "zones": [],
    }
    for z in calib.zones:
        zd: dict = {
            "name": z.name,
            "bbox_pt": [round(v, 3) for v in z.bbox_pt],
            "world": z.world,
            "ft_per_pt": float(z.ft_per_pt),
            "rotation_deg": z.rotation_deg,
            "method": z.method,
            "evidence": z.evidence,
            "page_size_pt": [round(v, 3) for v in z.page_size_pt],
        }
        if z.residual_ft is not None:
            zd["residual_ft"] = float(z.residual_ft)
        if z.anchor:
            zd["anchor"] = z.anchor
        data["zones"].append(zd)
    if calib.alignment is not None:
        data["alignment"] = calib.alignment
    if calib.warnings:
        data["warnings"] = list(calib.warnings)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False)


def load_calibration(path) -> Calibration:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    calib = Calibration(
        sheet=int(data.get("sheet", 0)),
        page_index=int(data.get("page_index", 0)),
        alignment=data.get("alignment"),
        warnings=list(data.get("warnings", [])),
    )
    for zd in data.get("zones", []):
        calib.zones.append(Zone(
            name=zd["name"],
            bbox_pt=tuple(float(v) for v in zd["bbox_pt"]),
            ft_per_pt=float(zd["ft_per_pt"]),
            rotation_deg=int(zd.get("rotation_deg", 0)),
            world=zd.get("world", "local_ft"),
            method=zd.get("method", "manual"),
            evidence=zd.get("evidence", ""),
            residual_ft=(float(zd["residual_ft"]) if zd.get("residual_ft") is not None
                         else None),
            anchor=zd.get("anchor"),
            page_size_pt=tuple(float(v) for v in zd.get("page_size_pt", (0.0, 0.0))),
        ))
    if not calib.zones:
        raise CalibrationError(f"{path}: calibration file has no zones")
    return calib
