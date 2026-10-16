"""Anchors files: the visually-read contour labels and spot elevations.

A flattened plan set letters its contours as outlined glyphs, so the values
are read by eye and transcribed into an anchors YAML — the audit trail:

    sheet: 94                 # the manifest whose georef places page: records
    vertical_datum: NGVD29    # REQUIRED — the sheet's benchmark datum
    interval_ft: 1.0
    index_interval_ft: 5.0    # optional; enables the index-multiple check
    contours: [{elev, page: [x, y] | xy: [e, n], id?, ...}]
    spots:    [{elev, page | xy, id?}]

``page`` is unrotated page points, y down. ``elev: null`` marks a candidate
nobody has read yet (an ``est-bim label-crops`` skeleton): it is skipped and
counted, never guessed. A record's ``id`` (``L012``, ``S004`` in a skeleton)
rides through to the placed record so a flagged label can be traced back to
its crop. Malformed input raises ``ValueError`` naming the record.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = ["Anchors", "load_anchors", "place_anchors", "manifest_page_to_world"]


@dataclass
class Anchors:
    sheet: int | None
    vertical_datum: str
    interval_ft: float | None
    index_interval_ft: float | None
    contours: list = field(default_factory=list)   # [{"elev", "xy", "id"}]
    spots: list = field(default_factory=list)
    unread: int = 0


def _sheet(v):
    """``sheet:`` as a page number: ``94`` and ``"94"`` both give 94."""
    if v is None:
        return None
    if isinstance(v, bool):
        raise ValueError(f"anchors sheet: must be a page number (got {v!r})")
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"anchors sheet: must be a page number (got {v!r})") from None
    if not f.is_integer():
        raise ValueError(f"anchors sheet: must be a page number (got {v!r})")
    return int(f)


def _number(v, what):
    """A finite float, or ValueError naming ``what``."""
    if isinstance(v, bool):
        raise ValueError(f"{what} must be a number (got {v!r})")
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a number (got {v!r})") from None
    if not math.isfinite(f):
        raise ValueError(f"{what} must be a finite number (got {v!r})")
    return f


def _pair(v, what):
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        raise ValueError(f"{what} must be 2 numbers [a, b] (got {v!r})")
    return _number(v[0], what), _number(v[1], what)


def load_anchors(path) -> dict:
    """The raw anchors mapping (``{}`` for an empty file); ``sheet`` as an int."""
    import yaml
    from pathlib import Path
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"anchors file {path}: not valid YAML ({exc})") from None
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"anchors file {path}: expected a mapping (sheet, "
                         f"vertical_datum, contours, spots), got a "
                         f"{type(raw).__name__}")
    if "sheet" in raw:
        raw["sheet"] = _sheet(raw["sheet"])
    return raw


def place_anchors(raw: dict, *, extra_spots=(), page_to_world=None) -> Anchors:
    """Validate an anchors mapping and place every read record in world feet."""
    if not isinstance(raw, dict):
        raise ValueError(f"anchors: expected a mapping (sheet, vertical_datum, "
                         f"contours, spots), got a {type(raw).__name__}")
    vd = raw.get("vertical_datum")
    if not vd:
        raise ValueError("anchors file needs vertical_datum: (the sheet's "
                         "benchmark datum, e.g. NGVD29)")
    sheet = _sheet(raw.get("sheet"))
    unread = 0

    def place(rec, where):
        nonlocal unread
        if not isinstance(rec, dict):
            raise ValueError(f"anchors {where}: expected a record "
                             f"{{elev, page | xy}}, got {rec!r}")
        if rec.get("elev") is None:
            unread += 1
            return None
        elev = _number(rec["elev"], f"anchors {where}: elev")
        if "xy" in rec:
            e, n = _pair(rec["xy"], f"anchors {where}: xy")
        elif "page" in rec:
            x, y = _pair(rec["page"], f"anchors {where}: page")
            if page_to_world is None:
                raise ValueError(
                    "anchor records give page coordinates but nothing places "
                    "them — pass --tie, or use a v2 manifest (its georef "
                    "places page points; with several manifests the anchors "
                    "file's sheet: picks one)"
                    + (f" — no v2 manifest is for sheet {sheet}"
                       if sheet is not None else ""))
            e, n = page_to_world(x, y)
        else:
            raise ValueError(f"anchor record needs xy or page: {rec!r}")
        rid = rec.get("id")
        return {"elev": elev, "xy": (float(e), float(n)),
                "id": None if rid is None else str(rid)}

    def records(key):
        v = raw.get(key)
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError(f"anchors {key}: must be a list of records "
                             f"(got {v!r})")
        return v

    contours = [p for p in (place(r, f"contours[{k}]")
                            for k, r in enumerate(records("contours"))) if p]
    spots = [p for p in (place(r, f"spots[{k}]")
                         for k, r in enumerate(records("spots"))) if p]
    spots += [p for p in (place(r, f"--spots record {k}")
                          for k, r in enumerate(extra_spots)) if p]

    def interval(key):
        v = raw.get(key)
        if v is None:
            return None
        f = _number(v, f"anchors {key}")
        if f <= 0:
            raise ValueError(f"anchors {key}: must be > 0 (got {v!r})")
        return f

    return Anchors(sheet, str(vd), interval("interval_ft"),
                   interval("index_interval_ft"), contours, spots, unread)


def manifest_page_to_world(manifest: dict):
    """Page -> world callable from a v2 manifest's ``georef.transform``.

    ``None`` for a v1 manifest (no transform recorded).
    """
    t = (manifest.get("georef") or {}).get("transform")
    if not t or len(t) != 6:
        return None
    a, b, c, d, e, f = (float(v) for v in t)
    return lambda x, y: (a * x + b * y + c, d * x + e * y + f)
