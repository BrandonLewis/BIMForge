"""Vision-hints handshake: the agent reads what fitz can't.

Signed bid sets are routinely flattened — every letter is vector outlines,
so the PDF carries no text spans (the v1 Pioneer finding: zero spans on all
21 pages). est-bim stays a deterministic CLI with no vision; the agent
operating the skill DOES have vision. The handshake is a hints file: the
agent renders the sheet (``est-bim calibrate --render``), reads the
flattened lettering, and writes what it says and roughly where. The code
then validates every hint against the vector geometry — a dimension hint
only becomes evidence when a real vector segment of the matching length
lies near it, exactly like v1's live-text ``dimension_strings`` method.
Vision proposes, vectors confirm; neither source is trusted alone.

hints.yaml schema::

    frame: visual            # optional: visual (default) | unrotated
    zone_hints:
      - zone: plan           # optional zone name; omitted = every zone
                             #   whose bbox contains the point
        kind: dimension      # dimension | scale_note | station_label
        text: "45'-0\""
        near_pt: [437.0, 771.9]   # page points; in the *visual* (as-rendered)
                                  #   frame by default — rendered pixel
                                  #   coords x the printed pt-per-pixel

Hint kinds:

* ``dimension`` — a lettered feet-inches string; pairs with nearby long
  segments (the dimension line) to yield ft/pt candidates. Full weight.
* ``scale_note`` — a lettered scale ("1/8\" = 1'-0\""). HALF weight, and it
  can never make a zone eligible for auto-acceptance on its own: title
  blocks lie (half-size plots — proven live on the Pioneer set).
* ``station_label`` — lettered stationing ("106+00", "BB 105+97.90"). Pairs
  of labels anchored to vector crossings on a shared carrier yield ft/pt
  candidates (delta station / delta distance); the first label near a
  detected tick also anchors the zone's world coordinates along the carrier.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Optional

import yaml

from bimforge.bim.plansheet.vectors import (
    SheetVectors, visual_to_unrotated,
)

__all__ = [
    "Hint", "HintsError", "load_hints", "parse_station",
    "STATION_RE",
]

VALID_KINDS = ("dimension", "scale_note", "station_label")

#: lettered stationing: 106+00, 105+97.90, optionally prefixed (BB 105+97.90)
STATION_RE = re.compile(r"(\d+)\s*\+\s*(\d+(?:\.\d+)?)")


class HintsError(ValueError):
    """Malformed hints file."""


@dataclass(frozen=True)
class Hint:
    """One agent-supplied reading of the flattened lettering."""

    kind: str                     # dimension | scale_note | station_label
    text: str
    x: float                      # unrotated page points (converted on load)
    y: float
    zone: Optional[str] = None    # zone name; None = any zone containing (x, y)

    def in_bbox(self, bbox: tuple[float, float, float, float]) -> bool:
        x0, y0, x1, y1 = bbox
        return x0 <= self.x <= x1 and y0 <= self.y <= y1


def parse_station(text: str) -> Optional[float]:
    """Lettered station -> feet ('106+00' -> 10600.0); None when absent."""
    m = STATION_RE.search(text)
    if not m:
        return None
    return float(m.group(1)) * 100.0 + float(m.group(2))


def load_hints(path, sv: SheetVectors) -> list[Hint]:
    """Load and validate hints.yaml; convert locations to unrotated points.

    ``frame: visual`` (the default) means ``near_pt`` values are as-rendered
    page points — what an agent measures off a ``--render`` PNG (pixel
    coordinates times the printed pt-per-pixel factor). ``frame: unrotated``
    takes raw PDF content coordinates.
    """
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise HintsError(f"{path}: expected a mapping at the top level")
    frame = data.get("frame", "visual")
    if frame not in ("visual", "unrotated"):
        raise HintsError(f"{path}: frame must be 'visual' or 'unrotated', "
                         f"got {frame!r}")
    entries = data.get("zone_hints")
    if not isinstance(entries, list) or not entries:
        raise HintsError(f"{path}: expected a non-empty 'zone_hints:' list")

    hints: list[Hint] = []
    for i, e in enumerate(entries):
        where = f"{path}: zone_hints[{i}]"
        if not isinstance(e, dict):
            raise HintsError(f"{where}: expected a mapping")
        kind = e.get("kind")
        if kind not in VALID_KINDS:
            raise HintsError(f"{where}: kind must be one of {VALID_KINDS}, "
                             f"got {kind!r}")
        text = e.get("text")
        if not isinstance(text, str) or not text.strip():
            raise HintsError(f"{where}: 'text' (the lettering as read) is required")
        near = e.get("near_pt")
        if (not isinstance(near, (list, tuple)) or len(near) != 2
                or not all(isinstance(v, (int, float)) for v in near)):
            raise HintsError(f"{where}: near_pt must be [x, y] page points")
        x, y = float(near[0]), float(near[1])
        if frame == "visual":
            x, y = visual_to_unrotated(x, y, sv.rotation, sv.width, sv.height)
        zone = e.get("zone")
        if zone is not None and not isinstance(zone, str):
            raise HintsError(f"{where}: zone must be a name or omitted")
        # validate the text parses for its kind, so typos fail loudly here
        # rather than silently contributing nothing
        if kind == "dimension":
            from bimforge.bim.plansheet.calibrate import parse_dimension
            if not parse_dimension(text):
                raise HintsError(
                    f"{where}: no feet-inches dimension found in {text!r} "
                    "(expected e.g. \"45'-0\\\"\")")
        elif kind == "scale_note":
            from bimforge.bim.plansheet.calibrate import parse_scale
            parse_scale(text)                     # raises CalibrationError
        elif kind == "station_label":
            if parse_station(text) is None:
                raise HintsError(
                    f"{where}: no station found in {text!r} (expected e.g. "
                    "'106+00' or 'BB 105+97.90')")
        hints.append(Hint(kind=kind, text=text.strip(), x=x, y=y, zone=zone))
    return hints


def hints_for_zone(hints: list[Hint], name: str,
                   bbox: tuple[float, float, float, float]) -> list[Hint]:
    """Hints addressed to a zone by name, or falling inside its bbox."""
    out = []
    for h in hints:
        if h.zone is not None:
            if h.zone == name:
                out.append(h)
        elif h.in_bbox(bbox):
            out.append(h)
    return out


def nearest_distance(x: float, y: float, seg) -> float:
    """Point -> segment distance (page points)."""
    ax, ay, bx, by = seg.x1, seg.y1, seg.x2, seg.y2
    dx, dy = bx - ax, by - ay
    d2 = dx * dx + dy * dy
    if d2 <= 0.0:
        return math.hypot(x - ax, y - ay)
    t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / d2))
    return math.hypot(x - (ax + t * dx), y - (ay + t * dy))
