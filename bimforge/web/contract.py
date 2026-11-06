"""The web bundle: everything a BIMForge page shows, as one JSON document.

`build_bundle(ifc_path, ...)` reads an IFC the way the CLI readers do (the
takeoff roll-up, `schedule_read`, `schedule_state`) and returns::

    {"contract": "bimforge-web/1",
     "model": {"file", "schema", "project", "site", "generator", "counts"},
     "elements": {GlobalId: {"name", "ifc_class", "predefined_type", "type",
                             "whole", "parts", "container", "codes",
                             "qto": {Qto name: SI value},
                             "appear", "vanish", "tasks"}},
     "takeoff": {"rows": [CanonicalTakeoff row + per-element "quantity" in
                          the row's unit, "official_quantity", "variance",
                          "unit_price", "bid_total" (the priced bid list,
                          else the estimate the IFC carries)],
                 "warnings": [...], "unclassified": [GlobalId, ...]},
     "schedule": CanonicalSchedule.to_dict() + {"task_elements":
                 {task id: [GlobalId, ...]}} | null,
     "costs": schedule_read.read_costs(...) + {"shares": [{"task",
              "element", "item_number", "code", "cost", "labor_hours",
              "categories": {Labor | Material | Equipment | Subcontract |
                             Other: amount}}]} | null}

`costs.shares` is what the pay follows: every priced cost item of the 5D
schedule, with the task it is spent in, the element it builds (when the
estimate ties it to one; a cost5d-only model has task-level shares) and
the bid item it is allocated to. The dashboard earns each element's pay
quantity over its tasks in proportion to those shares, so pay follows the
labour, the tasks and the materials that build the element, not a date.

Dates are ISO days. Element quantities are the IFC's SI values by Qto name;
takeoff quantities are in the pay unit the takeoff map names (or the
natural unit). The bundle carries no timestamp, so a rebuild of an
unchanged model is byte-identical (the same contract every BIMForge
output keeps).
"""
from __future__ import annotations

import json
from pathlib import Path

CONTRACT = "bimforge-web/1"


def _generator() -> str:
    try:
        from importlib.metadata import version
        return f"bimforge {version('bimforge')}"
    except Exception:                                   # not installed
        return "bimforge"


def _predefined(el) -> str | None:
    import ifcopenshell.util.element as ue
    try:
        pdt = ue.get_predefined_type(el)
    except Exception:
        pdt = getattr(el, "PredefinedType", None)
    return None if pdt in (None, "NOTDEFINED") else pdt


def _type_name(el) -> str | None:
    import ifcopenshell.util.element as ue
    t = ue.get_type(el)
    return (t.Name or None) if t is not None else None


def _whole(el) -> str | None:
    for rel in getattr(el, "Decomposes", None) or ():
        if rel.is_a("IfcRelAggregates") and rel.RelatingObject.is_a("IfcElement"):
            return rel.RelatingObject.GlobalId
    return None


def _parts(el) -> list[str]:
    return [o.GlobalId for rel in getattr(el, "IsDecomposedBy", None) or ()
            if rel.is_a("IfcRelAggregates")
            for o in rel.RelatedObjects or () if o.is_a("IfcElement")]


def _container(el) -> str | None:
    for rel in getattr(el, "ContainedInStructure", None) or ():
        return rel.RelatingStructure.Name or rel.RelatingStructure.GlobalId
    whole = None
    for rel in getattr(el, "Decomposes", None) or ():
        if rel.is_a("IfcRelAggregates"):
            whole = rel.RelatingObject
    return _container(whole) if whole is not None and whole.is_a("IfcElement") \
        else None


def _elements(model, spans) -> dict:
    from bimforge.bim.ifc_takeoff import (_unit_scales, classifications_of,
                                          quantities_of)
    scales = _unit_scales(model)
    out = {}
    for el in sorted(model.by_type("IfcElement"), key=lambda e: e.GlobalId):
        sp = spans.get(el.GlobalId)
        qto = quantities_of(el, scales)
        out[el.GlobalId] = {
            "name": el.Name or f"{el.is_a()}-{el.GlobalId[:6]}",
            "ifc_class": el.is_a(),
            "predefined_type": _predefined(el),
            "type": _type_name(el),
            "whole": _whole(el),
            "parts": _parts(el),
            "container": _container(el),
            "codes": sorted({c["code"] for c in classifications_of(el)
                             if c.get("code")}),
            "qto": {k: round(float(v), 9) for k, v in sorted(qto.items())},
            "appear": sp.appear if sp else None,
            "vanish": sp.vanish if sp else None,
            "tasks": list(sp.tasks) if sp else [],
        }
    return out


def _bid_items(model) -> dict:
    """{item_number: {"unit_price", "total", "quantity", "unit", "code"}}
    from the estimate an IFC carries (estimate_model5d's
    BidSheet_EstimateItem on each bid item's cost item). {} without one."""
    import ifcopenshell.util.element as ue
    out = {}
    for ci in model.by_type("IfcCostItem"):
        ps = ue.get_psets(ci).get("BidSheet_EstimateItem")
        if not ps or ps.get("ItemNumber") in (None, ""):
            continue
        out[str(ps["ItemNumber"])] = {
            "unit_price": ps.get("UnitPrice"), "total": ps.get("Total"),
            "quantity": ps.get("Quantity"), "unit": ps.get("Unit"),
            "code": ps.get("ItemCode")}
    return out


def _takeoff(model, tmap: dict | None, official: dict | None) -> dict:
    from bimforge.bim.ifc_takeoff import (MEASURE_DIM, _build_takeoff,
                                          classifications_of, convert)
    takeoff, warnings = _build_takeoff(model, tmap or {})
    bid = _bid_items(model)
    rows = []
    for row in takeoff["rows"]:
        r = dict(row)
        dim = None
        els = []
        for e in row["elements"]:
            e = dict(e)
            measure = e.get("measure")
            dim = MEASURE_DIM.get(measure) if measure else None
            v = e.get("value_si")
            e["quantity"] = (round(convert(v, dim, r["unit"]), 4)
                             if v is not None and dim else None)
            if dim == "count" and e["quantity"] is None:
                e["quantity"] = float(e.get("count") or 0)
            els.append(e)
        # the row's pay quantity is the authority (a lump sum is 1 LS over
        # any number of elements, `count_as` states the count): the
        # elements' quantities are scaled to add up to it
        have = sum(e["quantity"] or 0.0 for e in els)
        if have > 0 and abs(have - (r["quantity"] or 0.0)) > 1e-9:
            k = (r["quantity"] or 0.0) / have
            for e in els:
                if e["quantity"] is not None:
                    e["quantity"] = round(e["quantity"] * k, 9)
        r["elements"] = els
        off = (official or {}).get(r.get("item_number") or "")
        r["official_quantity"] = (float(off["quantity"])
                                  if off and off.get("quantity") is not None
                                  else None)
        if r["official_quantity"] not in (None, 0.0):
            r["variance"] = round(r["quantity"] - r["official_quantity"], 4)
            r["variance_pct"] = round(100.0 * r["variance"]
                                      / r["official_quantity"], 2)
        else:
            r["variance"] = (round(r["quantity"] - r["official_quantity"], 4)
                             if r["official_quantity"] is not None else None)
            r["variance_pct"] = None
        if off and not r.get("description"):
            r["description"] = off.get("description") or r.get("description")
        # the pay: the priced bid list first, else the estimate in the IFC
        est = bid.get(r.get("item_number") or "") or next(
            (v for v in bid.values() if v.get("code") == r["cost_code"]), None)
        price = (off or {}).get("unit_price")
        if price is None and est:
            price = est.get("unit_price")
        r["unit_price"] = float(price) if price is not None else None
        # the bid total: the list's own amount; else its quantity at the
        # price in force; else the estimate's amount (only when the list
        # priced nothing); else the modelled quantity at that price
        total = (off or {}).get("total")
        if total is None and r["unit_price"] is not None \
                and r["official_quantity"] is not None:
            total = r["official_quantity"] * r["unit_price"]
        if total is None and est and est.get("total") is not None \
                and (off or {}).get("unit_price") is None:
            total = est["total"]
        if total is None and r["unit_price"] is not None:
            total = r["quantity"] * r["unit_price"]
        r["bid_total"] = round(float(total), 2) if total is not None else None
        rows.append(r)
    unclassified = [el.GlobalId for el in model.by_type("IfcElement")
                    if not [c for c in classifications_of(el) if c.get("code")]
                    and (el.Representation is not None
                         or _has_quantities(el))]
    return {"rows": rows, "warnings": list(warnings),
            "unclassified": sorted(unclassified)}


def _has_quantities(el) -> bool:
    from bimforge.bim.ifc_takeoff import quantity_sets
    return bool(quantity_sets(el))


def _schedule(model, name: str | None):
    from bimforge.bim.schedule_read import read_schedule, task_elements
    if not model.by_type("IfcWorkSchedule"):
        return None
    sched = read_schedule(model, name)
    links = task_elements(model, sched.name or None)
    d = sched.to_dict()
    d["task_elements"] = {tid: sorted({l["global_id"] for l in ls})   # noqa: E741
                          for tid, ls in sorted(links.items())}
    return d


def _shares(model, schedule_name: str) -> list[dict]:
    """Every priced cost item of the 5D schedule "<name> cost": the task it
    is spent in, the element it builds (null when the item controls no
    element), the bid item (parent's BidSheet_EstimateItem ItemNumber) and
    the code it is classified under, its cost and labour hours."""
    import ifcopenshell.util.element as ue
    from bimforge.bim.cost_categories import categories_of
    from bimforge.bim.schedule_read import (_COST_ITEM_PSETS,
                                            _leaf_cost_items, _number,
                                            _pset, task_id)
    css = [c for c in model.by_type("IfcCostSchedule")
           if c.Name == f"{schedule_name} cost"]
    if not css:
        return []
    out = []
    for ci in _leaf_cost_items(css[0]):
        task = element = None
        for rel in getattr(ci, "Controls", None) or []:
            for o in rel.RelatedObjects or []:
                if o.is_a("IfcTask"):
                    task = o
                elif o.is_a("IfcElement"):
                    element = o
        if task is None:
            continue
        parent = next((rel.RelatingObject for rel in ci.Nests or []
                       if rel.RelatingObject.is_a("IfcCostItem")), None)
        item = (ue.get_psets(parent).get("BidSheet_EstimateItem")
                if parent is not None else None) or {}
        code = None
        for rel in getattr(ci, "HasAssociations", None) or []:
            if rel.is_a("IfcRelAssociatesClassification"):
                ref = rel.RelatingClassification
                code = getattr(ref, "Identification", None) or code
        if code is None and parent is not None:
            for rel in getattr(parent, "HasAssociations", None) or []:
                if rel.is_a("IfcRelAssociatesClassification"):
                    code = getattr(rel.RelatingClassification,
                                   "Identification", None) or code
        ps = _pset(ci, *_COST_ITEM_PSETS) or {}
        out.append({
            "task": task_id(task),
            "element": element.GlobalId if element is not None else None,
            "item_number": (str(item["ItemNumber"])
                            if item.get("ItemNumber") not in (None, "")
                            else None),
            "code": code or ci.Identification or ci.Name,
            "cost": round(sum(_number(cv.AppliedValue) or 0.0
                              for cv in ci.CostValues or []), 2),
            "labor_hours": _number(ps.get("LaborHours")),
            "categories": {c: round(a, 2)
                           for c, a in sorted(categories_of(ci).items())},
        })
    return out


def _costs(model, name: str | None):
    from bimforge.bim.schedule_read import read_costs
    if not model.by_type("IfcCostSchedule"):
        return None
    try:
        costs = read_costs(model, name)
    except ValueError as exc:        # a cost schedule that is not the 4D one
        return {"schedule": name, "costs": {}, "tasks": {}, "shares": [],
                "warnings": [str(exc)]}
    costs["shares"] = _shares(model, costs.get("schedule") or name or "")
    return costs


def build_bundle(ifc_path, tmap: dict | None = None,
                 official: dict | None = None,
                 schedule_name: str | None = None) -> dict:
    """The bundle for one IFC. `tmap` is a takeoff map (`est-bim takeoff
    --map`), `official` the bid items `takeoff_workbook.load_official`
    returns, `schedule_name` the IfcWorkSchedule to read (None: the only
    one). A model with no schedule has `schedule: null`; with no cost
    schedule, `costs: null`."""
    import ifcopenshell
    from bimforge.bim.schedule_state import element_spans

    path = Path(ifc_path)
    model = ifcopenshell.open(str(path))
    # the 4D state, from the SELECTED schedule's tasks (another schedule on
    # the same elements must not move them here)
    tasks = None
    if model.by_type("IfcWorkSchedule"):
        from bimforge.bim.schedule_read import _schedule_tasks, _work_schedule
        tasks = [t for t, _ in _schedule_tasks(_work_schedule(model,
                                                              schedule_name))]
    spans = element_spans(model, tasks)
    project = next(iter(model.by_type("IfcProject")), None)
    site = next(iter(model.by_type("IfcSite")), None)
    elements = _elements(model, spans)
    schedule = _schedule(model, schedule_name)
    bundle = {
        "contract": CONTRACT,
        "model": {
            "file": path.name,
            "schema": model.schema,
            "project": (project.Name if project else None),
            "site": (site.Name if site else None),
            "generator": _generator(),
            "counts": {"elements": len(elements),
                       "scheduled": sum(1 for e in elements.values()
                                        if e["appear"] or e["vanish"])},
        },
        "elements": elements,
        "takeoff": _takeoff(model, tmap, official),
        "schedule": schedule,
        "costs": _costs(model, (schedule or {}).get("name") or schedule_name),
    }
    validate_bundle(bundle)
    return bundle


def validate_bundle(bundle: dict) -> None:
    """Raise ValueError unless `bundle` is a bundle of this contract."""
    if not isinstance(bundle, dict) or bundle.get("contract") != CONTRACT:
        raise ValueError(f"not a {CONTRACT} bundle: contract="
                         f"{(bundle or {}).get('contract')!r}")
    for key in ("model", "elements", "takeoff"):
        if key not in bundle:
            raise ValueError(f"bundle lacks {key!r}")
    for key in ("schedule", "costs"):
        if key not in bundle:
            raise ValueError(f"bundle lacks {key!r} (null when absent)")
    for row in bundle["takeoff"].get("rows", []):
        for e in row.get("elements", []):
            if e.get("global_id") not in bundle["elements"]:
                raise ValueError(f"takeoff row {row.get('cost_code')!r} names "
                                 f"an element the bundle lacks: "
                                 f"{e.get('global_id')!r}")


def dump_bundle(bundle: dict) -> str:
    """The bundle as deterministic JSON (sorted keys, 2-space indent)."""
    return json.dumps(bundle, indent=2, sort_keys=True, ensure_ascii=False)
