"""The takeoff's sum, checked against the model and recorded (roadmap M.5).

That a takeoff's rows add up to the model's elements is arithmetic, so the
tool checks it on every takeoff and records the result in the takeoff as
its top-level `check` (a CanonicalTakeoff reader ignores the key):

    {"kind": "takeoff-sum", "result": "pass" | "fail",
     "build_id": the model's BIMForge_Model BuildId, when it has one,
     "checked_by": "bimforge <version>",
     "rows": [{"cost_code", "item_number", "schedule", "unit", "quantity",
               "basis": "sum" | "stated", "elements_sum", "agrees"}],
     "elements": how many row elements were checked,
     "missing": [GlobalId] in a row, not in the model,
     "changed": [GlobalId] in the model with another value than the row's,
     "repeated": [GlobalId] twice in one row,
     "not_in_any_row": [GlobalId] classified, with quantities, in no row}

A row's `basis` is "sum" when its quantity is its elements' sum in its unit,
to the takeoff's 4 places, and "stated" for a lump sum or a `count_as` row,
whose quantity is the map's. The same function re-checks a takeoff written
earlier against a rebuilt model: GlobalIds are stable (C.2a), so a value
that moved or an element that is gone fails the rows it backs.

Pure: reads the model, writes nothing.
"""
from __future__ import annotations

import math

from bimforge.bim.ifc_takeoff import (
    MEASURE_DIM, _unit_scales, classifications_of, convert, quantities_of)

#: how far a row's quantity may be from its elements' sum: the takeoff
#: rounds both to 4 places, so the last place may differ by summing order
SUM_TOLERANCE = 1e-4

#: how far an element's value in the model may be from the row's (SI)
VALUE_TOLERANCE = 1e-9


def _bases(takeoff: dict) -> list[str]:
    """Each row's basis, from the takeoff's own `check` when it has one for
    the same rows; otherwise "stated" for a lump sum, else "sum"."""
    rows = takeoff.get("rows") or []
    prior = (takeoff.get("check") or {}).get("rows") or []
    if len(prior) == len(rows) and all(
            p.get("cost_code") == r.get("cost_code")
            for p, r in zip(prior, rows)):
        return [p.get("basis") or "sum" for p in prior]
    return ["stated" if str(r.get("unit", "")).upper() == "LS" else "sum"
            for r in rows]


def _element(model, gid):
    try:
        return model.by_guid(gid)
    except RuntimeError:
        return None


def check_takeoff(model, takeoff: dict, bases: list[str] | None = None
                  ) -> dict:
    """The `check` record of `takeoff` against `model` (module docstring).
    `bases` gives each row's basis; None reads it from the takeoff."""
    from bimforge.bim import model_identity

    scales = _unit_scales(model)
    rows = takeoff.get("rows") or []
    bases = bases if bases is not None else _bases(takeoff)
    qtys_cache: dict[str, dict | None] = {}

    def qtys(gid):
        if gid not in qtys_cache:
            el = _element(model, gid)
            qtys_cache[gid] = None if el is None else quantities_of(el, scales)
        return qtys_cache[gid]

    missing, changed, repeated = [], [], []
    in_rows: set[str] = set()
    checked = 0
    out_rows = []
    for row, basis in zip(rows, bases):
        unit = row.get("unit") or ""
        total, ok, seen = 0.0, True, set()
        for e in row.get("elements") or []:
            gid, measure = e.get("global_id"), e.get("measure")
            if not gid or not measure:
                continue
            checked += 1
            in_rows.add(gid)
            if gid in seen:
                repeated.append(gid)
                ok = False
            seen.add(gid)
            q = qtys(gid)
            if q is None:
                missing.append(gid)
                ok = False
                continue
            value = q.get(measure)
            recorded = e.get("value_si")
            if value is None or recorded is None or not math.isclose(
                    value, recorded, rel_tol=VALUE_TOLERANCE,
                    abs_tol=VALUE_TOLERANCE):
                changed.append(gid)
                ok = False
                if value is None:
                    continue
            try:
                total += convert(value, MEASURE_DIM[measure], unit)
            except (KeyError, ValueError):
                ok = False
        elements_sum = round(total, 4)
        if basis != "stated" and abs(elements_sum - (row.get("quantity")
                                                      or 0.0)) > SUM_TOLERANCE:
            ok = False
        out_rows.append({
            "cost_code": row.get("cost_code"),
            "item_number": row.get("item_number"),
            "schedule": row.get("schedule"),
            "unit": unit,
            "quantity": row.get("quantity"),
            "basis": basis,
            "elements_sum": elements_sum,
            "agrees": ok,
        })

    not_in_any_row = sorted(
        el.GlobalId for el in model.by_type("IfcElement")
        if el.GlobalId not in in_rows
        and any(c["code"] for c in classifications_of(el))
        and quantities_of(el, scales))

    record = {"kind": "takeoff-sum"}
    ident = model_identity.read(model) or {}
    if ident.get("BuildId"):
        record["build_id"] = ident["BuildId"]
    record["checked_by"] = f"bimforge {model_identity.version()}"
    fail = (missing or changed or repeated or not_in_any_row
            or not all(r["agrees"] for r in out_rows))
    record["result"] = "fail" if fail else "pass"
    record.update({"rows": out_rows, "elements": checked,
                   "missing": sorted(set(missing)),
                   "changed": sorted(set(changed)),
                   "repeated": sorted(set(repeated)),
                   "not_in_any_row": not_in_any_row})
    return record


def failures(record: dict) -> list[str]:
    """The record's failures as review lines; empty when it passes."""
    out = [f"takeoff check: row {r['cost_code']}"
           f"{' item ' + r['item_number'] if r['item_number'] else ''} "
           f"states {r['quantity']} {r['unit']} but its elements sum to "
           f"{r['elements_sum']}"
           for r in record["rows"] if not r["agrees"]]
    for key, what in (("missing", "in the takeoff but not in the model"),
                      ("changed", "changed in the model since the takeoff"),
                      ("repeated", "listed twice in one row"),
                      ("not_in_any_row",
                       "classified, with quantities, but in no row")):
        if record[key]:
            out.append(f"takeoff check: {len(record[key])} element(s) "
                       f"{what}: {', '.join(record[key][:5])}"
                       f"{' ...' if len(record[key]) > 5 else ''}")
    return out
