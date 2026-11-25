"""Mass haul for the road corridor (roadmap P.6), band by band.

Cut is bank volume. Fill is compacted volume, and takes fill / (1 - shrink)
of bank to make; the ordinate adds cut less that. Loose volumes (the swell)
are the family's, on the earthwork's quantity sets.
"""
from __future__ import annotations

from dataclasses import dataclass

CF_PER_CY = 27.0
HEADER = "start,station,cut_cy,fill_cy,adjusted_fill_cy,cumulative_cy"


@dataclass(frozen=True)
class HaulRow:
    start: float
    station: float
    cut_cy: float
    fill_cy: float
    adjusted_fill_cy: float
    cumulative_cy: float


def mass_haul(bands: list, shrink: float) -> list[HaulRow]:
    """One row per (start, end, cut cf, fill cf) band, in order."""
    if not 0.0 <= shrink < 1.0:
        raise ValueError("shrink: must be at least 0 and below 1")
    rows, total = [], 0.0
    for s0, s1, cut_cf, fill_cf in bands:
        cut, fill = cut_cf / CF_PER_CY, fill_cf / CF_PER_CY
        adjusted = fill / (1.0 - shrink)
        total += cut - adjusted
        rows.append(HaulRow(s0, s1, cut, fill, adjusted, total))
    return rows


def to_csv(rows: list) -> str:
    return "\n".join([HEADER] + [
        f"{r.start:.2f},{r.station:.2f},{r.cut_cy:.3f},{r.fill_cy:.3f},"
        f"{r.adjusted_fill_cy:.3f},{r.cumulative_cy:.3f}" for r in rows]) + "\n"
