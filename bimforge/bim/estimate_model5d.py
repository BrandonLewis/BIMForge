"""Embed a BidSheet.ai estimate model into an IFC (the export half of the
IFC round trip, BidSheet.ai #1486 slice 6).

`embed_estimate_model` takes the document BidSheet.ai's `get_estimate_model`
MCP tool returns — `estimate`, `items`, `elements`, `activities`, `shares` —
and writes it into an IFC as:

- **one IfcWorkSchedule** ("BidSheet.ai estimate <id>" unless named), authored
  by `schedule4d.embed_schedule`: one IfcTask per activity, Identification
  and TaskId `a<id>`, the home item's number as an owner bid item. Task
  times: ScheduleStart is the activity's `start_date`; ScheduleFinish is its
  INCLUSIVE `finish_date` (BidSheet.ai's `end_date` is exclusive, start +
  duration — a model without `finish_date` falls back to the working day
  before `end_date` on a Mon-Fri week, with a warning); ScheduleDuration is
  the Mon-Fri working days of that span, so the three agree on the
  calendar the schedule carries. Each task is assigned
  (IfcRelAssignsToProcess) to the activity's linked elements found in the
  IFC by GlobalId; a spread activity (it pays across items, not for
  elements) is assigned none.
- **one IfcCostSchedule** (PredefinedType ESTIMATE, "<schedule> cost"): a
  valueless parent IfcCostItem per estimate item that carries allocation
  shares (Name = the description; unit, quantity and prices in
  BidSheet_EstimateItem), classified under cost5d's cost-code system, and a
  child per share. The parent's Identification is the item code (else its
  number), made unique — "<code> [<schedule>]", else "<code> [item <id>]" —
  when several items share it, so `read_costs` never merges two items; the
  raw code stays in the pset and the classification. Shares carry EXACT
  amounts; the children's cents are the running sum rounded half-up,
  differenced, so they sum to the item's allocated total (the exact sum,
  rounded once) — two $10.004 shares write $10.00 + $10.01 = $20.01. Each
  child is control-linked to its activity's IfcTask and to its element, and
  carries Bimforge_CostItem (TaskId, LaborHours), so
  `schedule_read.read_costs` reads it back per task and item. Items with no
  shares get no cost item (a valueless leaf would read as an unlinked
  cost); they are listed in the summary.
- **one IfcLaborResource per distinct crew** ("<schedule>: crew <name>"),
  its headcount and members in BidSheet_Crew, assigned to every task the
  crew works. Hours stay on the cost items (a crew shared by several tasks
  has no single hour figure).

Elements the model names but the IFC lacks — parametric elements whose
GlobalId is BidSheet.ai's deterministic one (`global_id_assigned` false), or
modelled elements since deleted from the file — are reported in the
summary, never invented. With `placeholders=True` each becomes an
IfcBuildingElementProxy carrying that GlobalId and name (no geometry), so
links land on it and a later `upsert_modelled_elements` matches the same
row.

Re-runs replace only what this tool wrote: the work schedule and cost
schedule carry the `BidSheet_EstimateModel` marker set, the crews their
BidSheet_Crew set. A same-named schedule WITHOUT the marker (a stage-model
4D schedule, a cost5d BUDGET) is refused with an error, never replaced.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

import ifcopenshell
import ifcopenshell.api.control as ctl
import ifcopenshell.api.cost as cost
import ifcopenshell.api.pset as pset_api
import ifcopenshell.api.resource as res
import ifcopenshell.api.root as root
import ifcopenshell.api.sequence as sq
import ifcopenshell.api.spatial as spatial

from bimforge.bim.cost5d import COST_ITEM_PSET, _classification, _code_reference
from bimforge.bim.estimate5d import _walk_items
from bimforge.bim.schedule4d import embed_schedule
from bimforge.bim.schedule_model import CanonicalSchedule, ScheduleTask
from bimforge.bim.schedule_read import _pset, _schedule_tasks, task_id

CENT = Decimal("0.01")
MARKER_PSET = "BidSheet_EstimateModel"
ITEM_PSET = "BidSheet_EstimateItem"
CREW_PSET = "BidSheet_Crew"
ACTIVITY_PSET = "BidSheet_Activity"
ELEMENT_PSET = "BidSheet_Element"


def _dec(value) -> Decimal:
    return Decimal(str(value)) if value not in (None, "") else Decimal(0)


def _cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def apportion_cents(amounts: list[Decimal]) -> list[Decimal]:
    """Round exact amounts to cents so they sum to their exact total rounded
    half-up: each is its running sum's rounding less the previous one's."""
    out, running, prev = [], Decimal(0), Decimal(0)
    for amount in amounts:
        running += amount
        now = _cents(running)
        out.append(now - prev)
        prev = now
    return out


def _workdays(start: date, finish: date) -> int:
    """Mon-Fri days from start to finish, both included."""
    n, d = 0, start
    while d <= finish:
        n += d.weekday() < 5
        d += timedelta(days=1)
    return n


def task_dates(activity: dict) -> tuple[str | None, str | None,
                                         float | None, bool]:
    """(start, inclusive finish, duration in work days, fell back) for an
    activity. `finish_date` is BidSheet.ai's inclusive last working day;
    without it the working day before the exclusive `end_date` (Mon-Fri)
    stands in, and `fell back` is True. With both dates the duration is
    the span's Mon-Fri days; else BidSheet.ai's `duration_days`."""
    start = activity.get("start_date")
    finish = activity.get("finish_date")
    fell_back = False
    if not finish and activity.get("end_date"):
        d = date.fromisoformat(activity["end_date"][:10]) - timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        if start and d < date.fromisoformat(start[:10]):
            d = date.fromisoformat(start[:10])      # a zero-length activity
        finish, fell_back = d.isoformat(), True
    duration = activity.get("duration_days")
    duration = float(duration) if duration not in (None, "") else None
    if start and finish:
        s, f = date.fromisoformat(start[:10]), date.fromisoformat(finish[:10])
        duration = float(_workdays(s, f) or (f - s).days + 1)
    return start, finish, duration, fell_back


def _schedule_name(model_json: dict, name: str | None) -> str:
    if name:
        return name
    est = model_json.get("estimate") or {}
    return f"BidSheet.ai estimate {est.get('id', '')}".strip()


def _marked(obj) -> bool:
    return _pset(obj, MARKER_PSET) is not None


def _check_names(model, name: str) -> None:
    """Refuse to replace a same-named schedule this tool did not write."""
    for cls, target in (("IfcWorkSchedule", name),
                        ("IfcCostSchedule", f"{name} cost")):
        for obj in model.by_type(cls):
            if obj.Name == target and not _marked(obj):
                raise ValueError(
                    f"the IFC already has an {cls} named {target!r} that "
                    f"est-bim estimate-model did not write (a stage-model "
                    f"4D or cost5d schedule?) — refusing to replace it; "
                    f"pass --schedule-name to write under another name")


def _remove_prior(model, name: str) -> None:
    """Drop what a previous run wrote — and only that: the marked cost
    schedule (nested items, their links, classification refs, values and
    psets), the marked work schedule's own sets, and the crews carrying
    BidSheet_Crew. The marked work schedule itself is replaced by
    embed_schedule (`_check_names` has made sure it is the only one)."""
    cost_name = f"{name} cost"
    for cs in list(model.by_type("IfcCostSchedule")):
        if cs.Name != cost_name or not _marked(cs):
            continue
        for ci in _walk_items(cs):
            for arel in list(getattr(ci, "Controls", None) or []):
                ctl.unassign_control(model, relating_control=ci,
                                     related_objects=list(arel.RelatedObjects))
            for assoc in list(getattr(ci, "HasAssociations", None) or []):
                if not assoc.is_a("IfcRelAssociatesClassification"):
                    continue
                others = [o for o in assoc.RelatedObjects if o != ci]
                if others:
                    assoc.RelatedObjects = others
                    continue
                ref = assoc.RelatingClassification
                model.remove(assoc)
                if ref and not model.get_inverse(ref):
                    model.remove(ref)
            for cv in list(ci.CostValues or []):
                cost.remove_cost_value(model, ci, cv)
            _remove_psets(model, ci)
        _remove_psets(model, cs)
        cost.remove_cost_schedule(model, cs)
    for ws in model.by_type("IfcWorkSchedule"):
        if ws.Name == name and _marked(ws):
            _remove_psets(model, ws)
    prefix = f"{name}: crew "
    for r in list(model.by_type("IfcLaborResource")):
        if (r.Name or "").startswith(prefix) and _pset(r, CREW_PSET) is not None:
            _remove_psets(model, r)
            res.remove_resource(model, r)


def _remove_psets(model, obj) -> None:
    for drel in list(getattr(obj, "IsDefinedBy", None) or []):
        if drel.is_a("IfcRelDefinesByProperties"):
            pset_api.remove_pset(model, product=obj,
                                 pset=drel.RelatingPropertyDefinition)


def _set_pset(model, obj, name: str, props: dict) -> None:
    props = {k: v for k, v in props.items() if v is not None and v != ""}
    if props:
        ps = pset_api.add_pset(model, product=obj, name=name)
        pset_api.edit_pset(model, pset=ps, properties=props)


def _by_guid(model, gid: str | None):
    if not gid:
        return None
    try:
        return model.by_guid(gid)
    except RuntimeError:
        return None


def _container(model):
    for cls in ("IfcBuildingStorey", "IfcBuilding", "IfcFacility", "IfcSite"):
        try:
            hits = model.by_type(cls)
        except RuntimeError:          # a class this schema lacks
            continue
        if hits:
            return hits[0]
    return None


def _placeholder(model, el: dict, container):
    proxy = root.create_entity(model, ifc_class="IfcBuildingElementProxy",
                               name=(el.get("name") or "")[:255] or None)
    proxy.GlobalId = el["global_id"]
    proxy.ObjectType = el.get("element_type") or None
    if container is not None:
        spatial.assign_container(model, products=[proxy],
                                 relating_structure=container)
    _set_pset(model, proxy, ELEMENT_PSET, {
        "ElementId": el.get("id"), "Source": el.get("source"),
        "Placeholder": True})
    return proxy


def _is_spread(activity: dict) -> bool:
    return bool((activity.get("spread") or {}).get("basis"))


def _crew_key(crew: dict):
    return crew.get("id") if crew.get("id") is not None else crew.get("name")


def _item_code(it: dict) -> str:
    return str(it.get("item_code") or it.get("item_number") or it["id"])


def item_identifications(items: list[dict]) -> dict:
    """{item id: unique cost-item Identification}: the item's code, made
    unique by its schedule label, else its id, when items share it."""
    codes = Counter(_item_code(it) for it in items)
    qualified = Counter(f"{_item_code(it)} [{it.get('schedule')}]"
                        for it in items if it.get("schedule"))
    out = {}
    for it in items:
        code = _item_code(it)
        if codes[code] == 1:
            out[it["id"]] = code
            continue
        by_schedule = f"{code} [{it.get('schedule')}]"
        if it.get("schedule") and qualified[by_schedule] == 1:
            out[it["id"]] = by_schedule
        else:
            out[it["id"]] = f"{code} [item {it['id']}]"
    return out


def embed_estimate_model(ifc, model_json: dict, out_path: str | None = None, *,
                         schedule_name: str | None = None,
                         placeholders: bool = False) -> dict:
    """Write `model_json` (a `get_estimate_model` document) into the IFC.

    `ifc` is a path or an open model (mutated in place); `out_path`, when
    given, is where the result is written. Returns the summary dict.
    Raises ValueError when a same-named schedule this tool did not write
    is in the way.
    """
    model = ifcopenshell.open(ifc) if isinstance(ifc, str) else ifc
    name = _schedule_name(model_json, schedule_name)
    items = model_json.get("items") or []
    elements = model_json.get("elements") or []
    activities = model_json.get("activities") or []
    shares = model_json.get("shares") or []
    warnings: list[str] = []
    est_id = (model_json.get("estimate") or {}).get("id")

    _check_names(model, name)
    _remove_prior(model, name)

    # -- elements: match by GlobalId, optionally place the missing ---------
    by_element: dict = {}
    unmatched = []
    container = _container(model) if placeholders else None
    created = 0
    for el in elements:
        ent = _by_guid(model, el.get("global_id"))
        if ent is not None and not ent.is_a("IfcProduct"):
            warnings.append(f"element {el.get('id')}: GlobalId "
                            f"{el.get('global_id')} names a {ent.is_a()} in "
                            f"the IFC, not a product — left unmatched")
            ent = None
        elif ent is None and placeholders and el.get("global_id"):
            ent = _placeholder(model, el, container)
            created += 1
        if ent is None:
            unmatched.append({"id": el.get("id"),
                              "global_id": el.get("global_id"),
                              "name": el.get("name"),
                              "global_id_assigned":
                                  el.get("global_id_assigned")})
            continue
        by_element[el.get("id")] = ent

    # -- tasks: one per activity, via schedule4d ---------------------------
    item_by_id = {it.get("id"): it for it in items}
    tasks, seen, fallbacks = [], set(), []
    for act in activities:
        key = act.get("key") or f"a{act.get('id')}"
        if key in seen:
            warnings.append(f"activity {key} listed twice — kept the first")
            continue
        seen.add(key)
        home = item_by_id.get(act.get("home_item_id")) or {}
        start, finish, duration, fell_back = task_dates(act)
        if fell_back:
            fallbacks.append(key)
        tasks.append(ScheduleTask(
            id=key, name=act.get("name") or key, start=start, finish=finish,
            duration_days=duration,
            bid_items=[str(home["item_number"])] if home.get("item_number")
            else []))
    if fallbacks:
        warnings.append(
            f"{len(fallbacks)} activit(ies) ({', '.join(fallbacks)}) have no "
            f"finish_date — finish is the Mon-Fri working day before their "
            f"exclusive end_date (refresh get_estimate_model for BidSheet.ai's "
            f"own calendar)")
    starts = sorted(t.start for t in tasks if t.start)
    sched = CanonicalSchedule(name=name, start_date=starts[0] if starts
                              else None, tasks=tasks)
    s_report = embed_schedule(model, sched, schedule_name=name)
    ws = next(w for w in model.by_type("IfcWorkSchedule") if w.Name == name)
    _set_pset(model, ws, MARKER_PSET, {"EstimateId": est_id,
                                       "Writer": "est-bim estimate-model"})
    task_ent = {task_id(t): t for t, _ in _schedule_tasks(ws)}

    acts = {}
    links, dangling = 0, []
    for act in activities:
        key = act.get("key") or f"a{act.get('id')}"
        if key in acts:
            continue
        acts[key] = act
        ent = task_ent[key]
        _set_pset(model, ent, ACTIVITY_PSET, {
            "ActivityId": act.get("id"), "Kind": act.get("kind"),
            "CostCode": act.get("cost_code"),
            "HomeItemId": act.get("home_item_id"),
            "Manhours": float(_dec(act.get("manhours"))),
            "Cost": act.get("cost")})
        if _is_spread(act):
            continue
        for eid in act.get("element_ids") or []:
            target = by_element.get(eid)
            if target is None:
                dangling.append({"activity": key, "element_id": eid})
                continue
            sq.assign_process(model, relating_process=ent,
                              related_object=target)
            links += 1
    act_by_id = {a.get("id"): k for k, a in acts.items()}

    # -- cost schedule: parent per item, child per share -------------------
    cs = cost.add_cost_schedule(model, name=f"{name} cost",
                                predefined_type="ESTIMATE")
    _set_pset(model, cs, MARKER_PSET, {"EstimateId": est_id,
                                       "Writer": "est-bim estimate-model"})
    classif = _classification(model)
    by_item = defaultdict(list)
    for share in shares:
        by_item[share.get("item_id")].append(share)
    unknown_items = sorted(str(i) for i in by_item if i not in item_by_id)
    if unknown_items:
        warnings.append(f"shares name item(s) {', '.join(unknown_items)} "
                        f"the model's items do not list — left out")
    idents = item_identifications(items)
    elem_by_id = {e.get("id"): e for e in elements}
    parents = children = 0
    grand = Decimal(0)
    no_shares = []
    for it in items:
        item_shares = by_item.get(it.get("id"), [])
        if not item_shares:
            no_shares.append(it.get("id"))
            continue
        code = _item_code(it)
        ident = idents[it["id"]]
        exact = [_dec(s.get("cost")) for s in item_shares]
        allocated = _cents(sum(exact, Decimal(0)))
        parent = cost.add_cost_item(model, cost_schedule=cs)
        cost.edit_cost_item(model, parent, attributes={
            "Name": it.get("description") or code, "Identification": ident})
        _code_reference(model, parent, code, classif)
        _set_pset(model, parent, ITEM_PSET, {
            "ItemId": it.get("id"), "ItemNumber": it.get("item_number"),
            "ItemCode": it.get("item_code"), "Schedule": it.get("schedule"),
            "Unit": it.get("unit"),
            "Quantity": _float(it.get("quantity")),
            "UnitPrice": _float(it.get("unit_price")),
            "Total": _float(it.get("total")),
            "AllocatedTotal": float(allocated),
            "PricingSource": it.get("pricing_source")})
        parents += 1
        grand += allocated
        for share, cents in zip(item_shares, apportion_cents(exact)):
            akey = share.get("activity_key") or act_by_id.get(
                share.get("activity_id")) or f"a{share.get('activity_id')}"
            act = acts.get(akey) or {}
            el = elem_by_id.get(share.get("element_id"))
            label = act.get("name") or akey
            if el is not None:
                label = f"{label}: {el.get('name') or el.get('global_id')}"
            child = cost.add_cost_item(model, cost_item=parent)
            cost.edit_cost_item(model, child, attributes={
                "Name": label, "Identification": ident})
            cv = cost.add_cost_value(model, parent=child)
            cost.edit_cost_value(model, cv,
                                 attributes={"AppliedValue": float(cents)})
            related = [t for t in (task_ent.get(akey),) if t is not None]
            target = by_element.get(share.get("element_id"))
            if target is not None:
                related.append(target)
            if related:
                ctl.assign_control(model, relating_control=child,
                                   related_objects=related)
            _set_pset(model, child, COST_ITEM_PSET, {
                "TaskId": akey if akey in task_ent else None,
                "LaborHours": float(_dec(share.get("manhours"))),
                "ActivityId": share.get("activity_id"),
                "ItemId": share.get("item_id"),
                "ElementId": share.get("element_id"),
                "ElementGlobalId": el.get("global_id") if el else None,
                "Fraction": share.get("fraction"),
                "ExactCost": share.get("cost"),
                "Reason": share.get("reason")})
            children += 1

    # -- crews: one labor resource per distinct crew -----------------------
    crews: dict = {}
    for key, act in acts.items():
        crew = act.get("crew")
        if crew:
            crews.setdefault(_crew_key(crew), (crew, []))[1].append(key)
    for crew, keys in crews.values():
        members = "; ".join(
            f"{m.get('count')} x {m.get('classification')}"
            for m in crew.get("members") or [])
        r = res.add_resource(model, ifc_class="IfcLaborResource",
                             name=f"{name}: crew {crew.get('name') or crew.get('id')}")
        if members:
            r.Description = members
        # always written: it is also what marks the crew as this tool's
        ps = pset_api.add_pset(model, product=r, name=CREW_PSET)
        pset_api.edit_pset(model, pset=ps, properties={
            "Writer": "est-bim estimate-model",
            **{k: v for k, v in {"CrewId": crew.get("id"),
                                 "Headcount": _float(crew.get("headcount")),
                                 "Members": members}.items()
               if v not in (None, "")}})
        for key in keys:
            res.assign_resource(model, relating_resource=r,
                                related_object=task_ent[key])

    if out_path:
        model.write(out_path)
    return {
        "schedule_name": name,
        "tasks": s_report.tasks,
        "tasks_timed": s_report.tasks_timed,
        "task_element_links": links,
        "cost_items": parents,
        "share_items": children,
        "items_without_shares": no_shares,
        "labor_resources": len(crews),
        "allocated_total": str(grand),
        "placeholders_created": created,
        "unmatched_elements": unmatched,
        "unmatched_links": dangling,
        "warnings": warnings,
    }


def _float(value):
    return float(value) if value not in (None, "") else None
