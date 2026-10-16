"""QC cross-check: measured geometry vs the engineer's own lettering.

The bid-day credibility feature (spec section 3): every PDF-measured entity
is compared against the lettered dimensions near it, and the report says so
either way::

    S-DECK[0]  vector 45.00 ft   lettered 45'-0" (45.00)   d 0.00%  OK
    S-FTG[1]   vector 31.71 ft   lettered 32'-0" (32.00)   d 0.91%  REVIEW

Lettered values come from live text spans when the sheet has a text layer,
and from vision hints (``kind: dimension``, matched by proximity) when the
lettering is flattened — same rule as calibration: vision proposes, the
vector measurement is what gets checked. Rows over the tolerance are
REVIEW and set ``"confidence": "review"`` in the provenance sidecar;
entities with no lettered evidence nearby are listed UNVERIFIED, never
silently omitted.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from bimforge.bim.plansheet.calibrate import Calibration, parse_dimension
from bimforge.bim.plansheet.vectors import SheetVectors

__all__ = [
    "Lettered", "CheckRow", "DEFAULT_QC_TOL_PCT",
    "collect_lettered", "cross_check", "render_report",
]

DEFAULT_QC_TOL_PCT = 0.5      # d% above this -> REVIEW
DEFAULT_GATE_FT = 20.0        # lettered value must sit this close to the entity
MATCH_CAP_PCT = 10.0          # beyond this the lettering belongs to something else
_EDGE_CLUSTER_REL = 0.02


@dataclass(frozen=True)
class Lettered:
    """One lettered dimension value positioned in world feet."""

    zone: str
    feet: float
    x: float                  # world feet
    y: float
    text: str
    source: str               # "text" | "hint"


@dataclass
class CheckRow:
    entity: str               # "S-DECK[0]"
    zone: str
    vector_ft: Optional[float]
    lettered_ft: Optional[float]
    lettered_text: str
    delta_pct: Optional[float]
    status: str               # OK | REVIEW | UNVERIFIED


def collect_lettered(sv: SheetVectors, calib: Calibration,
                     hints=None) -> list[Lettered]:
    """Every feet-inches value the sheet letters, positioned in world feet.

    Live text spans first (sheets that kept a text layer); vision hints of
    ``kind: dimension`` for flattened sheets. Values land in every zone whose
    bbox contains them.
    """
    out: list[Lettered] = []
    for zone in calib.zones:
        for t in sv.texts:
            if not t.in_bbox(zone.bbox_pt):
                continue
            for feet in parse_dimension(t.text):
                if feet <= 0:  # "0'-0\"" would divide-by-zero in cross_check
                    continue
                wx, wy = zone.to_world(t.x, t.y)
                out.append(Lettered(zone=zone.name, feet=feet, x=wx, y=wy,
                                    text=t.text.strip(), source="text"))
        for h in (hints or []):
            if h.kind != "dimension":
                continue
            if h.zone is not None and h.zone != zone.name:
                continue
            if h.zone is None and not h.in_bbox(zone.bbox_pt):
                continue
            for feet in parse_dimension(h.text):
                if feet <= 0:
                    continue
                wx, wy = zone.to_world(h.x, h.y)
                out.append(Lettered(zone=zone.name, feet=feet, x=wx, y=wy,
                                    text=h.text, source="hint"))
    return out


def _principal_dims(points: list[tuple[float, float]], closed: bool) -> list[float]:
    """Candidate check dimensions of a measured polyline (world feet).

    Closed: clustered edge lengths plus the axis-aligned extents (a
    rectangle yields exactly its length and width). Open: the total length
    plus clustered edge lengths when there are several edges.
    """
    if len(points) < 2:
        return []
    pairs = list(zip(points, points[1:] + ([points[0]] if closed else [])))
    edges = [math.dist(a, b) for a, b in pairs if math.dist(a, b) > 0]
    dims: list[float] = []
    if closed:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        dims.extend([max(xs) - min(xs), max(ys) - min(ys)])
    else:
        dims.append(sum(edges))
    # clustered edge lengths
    for e in sorted(edges, reverse=True):
        grp = [v for v in edges if abs(v - e) <= _EDGE_CLUSTER_REL * e]
        mean = sum(grp) / len(grp)
        if not any(abs(mean - d) <= _EDGE_CLUSTER_REL * d for d in dims):
            dims.append(mean)
    return dims


def _entity_gate_dist(points, lx, ly, closed: bool = False) -> float:
    """Distance from a lettered value to the entity's nearest edge.

    Dimension text sits beside the middle of the edge it dimensions, so
    vertex distance alone would under-match long edges. The closing edge
    exists only for closed polylines — synthesizing it for open ones would
    shrink the gate and adopt unrelated lettering.
    """
    if len(points) == 1:
        px, py = points[0]
        return math.hypot(px - lx, py - ly)
    best = math.inf
    pairs = list(zip(points, points[1:]))
    if closed and len(points) > 2:
        pairs.append((points[-1], points[0]))
    for (ax, ay), (bx, by) in pairs:
        dx, dy = bx - ax, by - ay
        d2 = dx * dx + dy * dy
        if d2 <= 0:
            d = math.hypot(lx - ax, ly - ay)
        else:
            t = max(0.0, min(1.0, ((lx - ax) * dx + (ly - ay) * dy) / d2))
            d = math.hypot(lx - (ax + t * dx), ly - (ay + t * dy))
        best = min(best, d)
    return best


def cross_check(
    entities: list[dict],
    lettered: list[Lettered],
    *,
    tol_pct: float = DEFAULT_QC_TOL_PCT,
    gate_ft: float = DEFAULT_GATE_FT,
) -> list[CheckRow]:
    """Compare each measured entity against nearby lettered dimensions.

    ``entities`` are provenance-sidecar rows (mutated in place: each gains a
    ``confidence`` of ok / review / unverified and a ``crosscheck`` list).
    Every entity yields at least one row — UNVERIFIED when nothing lettered
    sits within ``gate_ft`` of it.
    """
    rows: list[CheckRow] = []
    for e in entities:
        name = f"{e['layer']}[{e['index']}]"
        zone = e.get("zone", "")
        points = [(p[0], p[1]) for p in e.get("points", [])]
        dims = ([] if e.get("feature") == "count"
                else _principal_dims(points, bool(e.get("closed"))))
        near = [l for l in lettered
                if l.zone == zone and points
                and _entity_gate_dist(points, l.x, l.y,
                                      closed=bool(e.get("closed"))) <= gate_ft]
        erows: list[CheckRow] = []
        used_dims: set[int] = set()
        for l in near:
            best = None
            for i, d in enumerate(dims):
                dev = abs(d - l.feet) / l.feet * 100.0
                if dev <= MATCH_CAP_PCT and (best is None or dev < best[0]):
                    best = (dev, i, d)
            if best is None:
                continue
            dev, i, d = best
            used_dims.add(i)
            erows.append(CheckRow(
                entity=name, zone=zone, vector_ft=round(d, 3),
                lettered_ft=l.feet, lettered_text=l.text,
                delta_pct=round(dev, 3),
                status="OK" if dev <= tol_pct else "REVIEW"))
        # collapse duplicate (vector, lettered) pairs (a dim lettered twice)
        seen = set()
        erows = [r for r in erows
                 if (key := (r.vector_ft, r.lettered_ft)) not in seen
                 and not seen.add(key)]
        if not erows:
            erows = [CheckRow(
                entity=name, zone=zone,
                vector_ft=(round(dims[0], 3) if dims else None),
                lettered_ft=None, lettered_text="",
                delta_pct=None, status="UNVERIFIED")]
        rows.extend(erows)
        conf = ("review" if any(r.status == "REVIEW" for r in erows)
                else "unverified" if all(r.status == "UNVERIFIED" for r in erows)
                else "ok")
        e["confidence"] = conf
        e["crosscheck"] = [{
            "vector_ft": r.vector_ft, "lettered_ft": r.lettered_ft,
            "lettered_text": r.lettered_text, "delta_pct": r.delta_pct,
            "status": r.status} for r in erows]
    return rows


def _fmt_ft(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:.2f} ft"


def render_report(rows: list[CheckRow], *,
                  tol_pct: float = DEFAULT_QC_TOL_PCT,
                  title: str = "PDF measurement cross-check") -> str:
    """The QC report as markdown (the spec's table)."""
    lines = [
        f"# {title}",
        "",
        f"Vector-measured dimensions vs lettered dimensions; Δ > {tol_pct}% "
        "→ REVIEW. UNVERIFIED entities had no lettered evidence within the "
        "match gate — verify them another way before trusting.",
        "",
        "| entity | zone | vector | lettered | Δ% | status |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lettered = (f"{r.lettered_text} ({r.lettered_ft:.2f})"
                    if r.lettered_ft is not None else "—")
        delta = "—" if r.delta_pct is None else f"{r.delta_pct:.2f}%"
        lines.append(f"| {r.entity} | {r.zone} | {_fmt_ft(r.vector_ft)} | "
                     f"{lettered} | {delta} | {r.status} |")
    n_rev = sum(1 for r in rows if r.status == "REVIEW")
    n_unv = sum(1 for r in rows if r.status == "UNVERIFIED")
    n_ok = sum(1 for r in rows if r.status == "OK")
    lines += ["", f"OK {n_ok} · REVIEW {n_rev} · UNVERIFIED {n_unv}", ""]
    return "\n".join(lines)
