"""Canonical sheet-production data: control points (PNEZDS+ CSV, the Pioneer
schema), a chord alignment with station interpolation, and sheet metadata.

Pure: stdlib only. Coordinates are ground/published State Plane feet, x=E,
y=N (the Work-repo rule: the DXF stays in ground coords; only KML converts).
grade is first-class: 'survey' (tied to published control) vs 'approximate'
(georeferenced from imagery/plans — NOT for construction layout)."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

REQUIRED_COLS = ("point_id", "description", "northing_ft", "easting_ft")
OPTIONAL_COLS = ("elevation_ft", "station", "offset_ft", "side",
                 "latitude", "longitude")
VALID_GRADES = ("survey", "approximate")


@dataclass
class ControlPoint:
    point_id: str
    description: str
    northing_ft: float
    easting_ft: float
    elevation_ft: float | None = None
    station: str | None = None
    offset_ft: float | None = None
    side: str | None = None
    latitude: float | None = None
    longitude: float | None = None


def load_control_csv(path) -> list:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        cols = set(reader.fieldnames or [])
        missing = [c for c in REQUIRED_COLS if c not in cols]
        if missing:
            raise ValueError(f"control CSV missing required columns: {missing}")
        pts = []
        for row in reader:
            def _f(key):
                v = (row.get(key) or "").strip()
                return float(v) if v else None
            pts.append(ControlPoint(
                point_id=row["point_id"].strip(),
                description=(row.get("description") or "").strip(),
                northing_ft=float(row["northing_ft"]),
                easting_ft=float(row["easting_ft"]),
                elevation_ft=_f("elevation_ft"),
                station=(row.get("station") or "").strip() or None,
                offset_ft=_f("offset_ft"),
                side=(row.get("side") or "").strip() or None,
                latitude=_f("latitude"),
                longitude=_f("longitude"),
            ))
    return pts


def save_control_csv(points: list, path) -> None:
    cols = list(REQUIRED_COLS) + list(OPTIONAL_COLS)
    with Path(path).open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for p in points:
            w.writerow({c: ("" if getattr(p, c) is None else getattr(p, c))
                        for c in cols})


@dataclass
class Alignment:
    """Chord alignment: monotonically increasing stations with N/E at each.
    Curves are annotation-only in v1 (no COGO engine — roadmap decision).

    NOT the authoring alignment: exact tangent/curve traverses with radial
    station-offset resolution live in `bimforge.author.alignment.Alignment`.
    The two are intentionally different models (chords for sheet annotation;
    COGO for parametric authoring) — do not merge them."""
    name: str
    points: list  # [{station: float, northing: float, easting: float}]

    def __post_init__(self):
        stas = [p["station"] for p in self.points]
        if len(stas) < 2 or any(b <= a for a, b in zip(stas, stas[1:])):
            raise ValueError("alignment needs >=2 points with increasing stations")

    def at_station(self, sta: float) -> tuple:
        pts = self.points
        if not pts[0]["station"] <= sta <= pts[-1]["station"]:
            raise ValueError(f"station {sta} is outside the alignment "
                             f"({pts[0]['station']}..{pts[-1]['station']})")
        for a, b in zip(pts, pts[1:]):
            if a["station"] <= sta <= b["station"]:
                t = (sta - a["station"]) / (b["station"] - a["station"])
                return (a["northing"] + t * (b["northing"] - a["northing"]),
                        a["easting"] + t * (b["easting"] - a["easting"]))
        raise AssertionError("unreachable")

    def ticks(self, interval: float) -> list:
        """[(station, northing, easting)] at multiples of interval, inclusive
        of the start station, exclusive of any station past the end."""
        if interval <= 0:
            raise ValueError(f"tick interval must be positive, got {interval}")
        start = self.points[0]["station"]
        end = self.points[-1]["station"]
        out = []
        i = 0
        while True:
            sta = start + i * interval
            if sta > end:
                break
            n, e = self.at_station(sta)
            out.append((sta, n, e))
            i += 1
        return out


@dataclass
class SheetMeta:
    """What every sheet needs to say about itself (title block + QC header)."""
    project: str
    sheet_title: str
    grade: str                      # survey | approximate
    crs_epsg: int | None = None
    basis_note: str = ""            # basis of bearings/coordinates prose
    combined_factor: float | None = None
    bid_number: str | None = None
    date: str = ""
    drafter: str = ""
    scale_text: str = ""            # e.g. 1"=30'
    extra_fields: dict = field(default_factory=dict)  # TitleBlockFields overrides

    def __post_init__(self):
        if self.grade not in VALID_GRADES:
            raise ValueError(
                f"invalid grade {self.grade!r} (expected one of {list(VALID_GRADES)})")

    @property
    def not_for_layout(self) -> bool:
        return self.grade == "approximate"


NOT_FOR_LAYOUT_NOTE = ("GEOREFERENCED-APPROXIMATE COORDINATES — FIELD "
                       "NAVIGATION AND TAKEOFF ONLY. NOT FOR CONSTRUCTION LAYOUT.")

_SCALE_RE = re.compile(r"""^\s*1\s*(?:"|in)\s*=\s*(\d+(?:\.\d+)?)\s*(?:'|ft)\s*$""")


def scale_from_engineering(text: str) -> float:
    """'1"=30'' / '1in=30ft' -> 1/30 (paper-inch per world-foot)."""
    m = _SCALE_RE.match(text)
    if not m:
        raise ValueError(f"unrecognized scale {text!r} (expected like '1in=30ft')")
    return 1.0 / float(m.group(1))
