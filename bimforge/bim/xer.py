"""Primavera P6 .xer reader — the tab-delimited ``%T``/``%F``/``%R`` dump.

The format half of what used to be ``estimating_tools.schedule.xer`` (#204):
parse the tables, build WBS name-paths, convert P6 duration/float hours to
work-days, classify summary rows. Pure stdlib, so a consumer with only
bimforge can read a P6 export; the Excel output profiles (``dump``,
``bridge``) stay in ``estimating_tools.schedule.xer``, which re-exports
everything here.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

# P6 task_type codes that are summary / level-of-effort rows
_SUMMARY_TYPES = {"TT_WBS", "TT_LOE"}
_XER_WORKDAY_HR = 8.0
_DATE_SOURCES = ("target", "early", "actual")


def _require_positive_hpd(hours_per_day: float) -> None:
    if hours_per_day <= 0:
        raise ValueError("hours_per_day must be > 0")


# ---------------------------------------------------------------------------
# reader
# ---------------------------------------------------------------------------

def parse_tables(text: str) -> dict[str, list[dict]]:
    """The XER's tab-delimited ``%T``/``%F``/``%R`` blocks → ``{table: [row]}``.

    Rows are padded/truncated to the field count so a short row yields ``""``
    for the missing trailing fields (rather than absent keys) and a long row
    drops its extras — both P6 export quirks.
    """
    tables: dict[str, list[dict]] = {}
    fields: list[str] = []
    cur: list[dict] | None = None
    for line in text.splitlines():
        row = line.split("\t")
        tag = row[0]
        if tag == "%T":
            cur = []
            tables[row[1]] = cur
        elif tag == "%F":
            fields = row[1:]
        elif tag == "%R" and cur is not None:
            vals = row[1:]
            n = len(fields)
            if len(vals) < n:
                vals = vals + [""] * (n - len(vals))
            elif len(vals) > n:
                vals = vals[:n]
            cur.append(dict(zip(fields, vals)))
    return tables


def read_tables(path) -> dict[str, list[dict]]:
    """Read an .xer file (cp1252, the XER encoding) and parse its tables."""
    return parse_tables(Path(path).read_text(encoding="cp1252",
                                             errors="replace"))


def xer_date(s: str | None) -> str | None:
    """P6 datetime ("2026-07-14 17:00") → date-only "2026-07-14"; ""/None → None."""
    return s[:10] if s else None


def xer_date_obj(s: str | None) -> date | None:
    """P6 datetime → a ``datetime.date`` (so a workbook stores a real date the
    ``mm/dd/yy`` number format can render); unparseable/empty → None."""
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def hours_to_workdays(hours, hours_per_day: float = _XER_WORKDAY_HR, *,
                      whole: bool = False):
    """P6 duration/float hours → work-days; ``None`` when unparseable/empty.

    ``whole=True`` rounds to a whole day (the bridge deliverable's convention);
    otherwise rounds to 2 decimals (the readable dump's convention).
    """
    try:
        days = float(hours) / hours_per_day
    except (ValueError, TypeError):
        return None
    return int(round(days)) if whole else round(days, 2)


def wbs_paths(tables: dict[str, list[dict]], sep: str = " > ") -> dict[str, str]:
    """``{wbs_id: "root<sep>child<sep>…"}`` from the PROJWBS table."""
    wbs = {w["wbs_id"]: w for w in tables.get("PROJWBS", [])}
    cache: dict[str, str] = {}

    def path(wid: str) -> str:
        if wid in cache:
            return cache[wid]
        r = wbs.get(wid)
        if not r:
            return ""
        cache[wid] = wid          # cycle guard
        name = r.get("wbs_name", "")
        parent = r.get("parent_wbs_id", "")
        if parent and parent in wbs:
            p = path(parent)
            full = f"{p}{sep}{name}" if p else name
        else:
            full = name
        cache[wid] = full
        return full

    return {wid: path(wid) for wid in wbs}


def is_summary(task: dict) -> bool:
    """A summary / LOE / roll-up row: by task_type, ``.SUM`` code, or name."""
    if task.get("task_type") in _SUMMARY_TYPES:
        return True
    code = task.get("task_code", "")
    if code.endswith(".SUM"):
        return True
    return task.get("task_name", "").strip().lower().endswith("summary")
