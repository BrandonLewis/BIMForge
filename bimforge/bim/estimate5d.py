"""Quantity-backed ESTIMATE cost schedule (spec 2026-08-12).

Authors a bid-time estimate snapshot into an IFC: one IfcCostSchedule
(PredefinedType=ESTIMATE, named "<name> estimate") with a parent IfcCostItem
per bid item (map entry) and one nested child per contributing element. Each
child's CostQuantities references the element's OWN Qto quantity entity —
`ifcopenshell.api.cost.assign_cost_item_quantity` appends the same entity
instance, not a copy, and control-links the element — so the priced quantity
IS the model quantity. The parent carries no cost value; consumers sum a
valueless parent's children (children partition the quantities, so the sum is
honest).

Money semantics: with CostQuantities present, an item's total is
AppliedValue x sum(quantities). The referenced quantities are the file's RAW
declared-unit values (the reader-side scaling of issue #109 never rewrites
the file), so each child's AppliedValue is the bid unit rate converted to
per-one-raw-quantity-unit:

    AppliedValue = unit_price x CONVERT[dim][pay_unit] x _unit_scales(model)[dim]

No UnitBasis is authored (uneven consumer support); this line is the basis.

The BUDGET schedule cost5d authors is untouched — the two coexist. Removal
safety on re-run: every item's CostQuantities is cleared BEFORE teardown so
removing cost items can never cascade into the elements' own Qto members.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import ifcopenshell.api.control as ctl
import ifcopenshell.api.cost as cost

from bimforge.bim.cost5d import _classification, _code_reference
from bimforge.bim.ifc_takeoff import (
    DEFAULT_UNIT, MEASURE_DIM, classifications_of, convert, normalize_map,
    quantities_of, _unit_scales)


@dataclass
class EstimateEmbedReport:
    schedule_name: str
    parents: int = 0
    children: int = 0
    extended_total: float = 0.0
    # {code: {"extended", "bm_cost", "variance_pct"}} — bm_cost/variance_pct
    # None (never fabricated zeros) when the lump cost is absent. Plural
    # codes aggregate their entries here: the lump cost is per code.
    by_code: dict = field(default_factory=dict)
    codes_without_rate: list = field(default_factory=list)
    codes_without_measure: list = field(default_factory=list)
    codes_without_elements: list = field(default_factory=list)
    elements_missing_measure: list = field(default_factory=list)  # (el, code, measure)


def _rate_for(code: str, entry: dict, costs: dict, *, plural: bool,
              pay_unit: str):
    """The bid unit price for a map entry, or None when the code carries no
    unit_price. Raises ValueError on: a plural code with a bare-number
    unit_price, a dict unit_price missing the entry's item_number, and a
    costs.json unit that contradicts the map's pay unit ($/CY silently
    applied to an LF entry is exactly the mistake the cross-check catches).
    """
    rec = costs.get(code) or {}
    up = rec.get("unit_price")
    if up is None:
        return None
    item = str(entry.get("item_number", "") or "")
    if isinstance(up, dict):
        if not item or item not in up:
            raise ValueError(
                f"code {code}: unit_price is keyed by item_number "
                f"({sorted(up)}) but this entry's item_number is "
                f"{item or '(unset)'}")
        price = up[item]
    else:
        if plural:
            raise ValueError(
                f"code {code}: plural 'measures' entries need unit_price "
                f"keyed by item_number, got a bare number")
        price = up
    # The unit is an optional CROSS-CHECK, not a requirement: a dict unit
    # lacking this entry's item_number deliberately no-ops and the map's pay
    # unit is trusted (contrast unit_price above, where the missing key
    # raises — a price is required, corroboration is not).
    cu = rec.get("unit")
    if isinstance(cu, dict):
        cu = cu.get(item)
    if cu and cu.upper() != pay_unit.upper():
        raise ValueError(
            f"code {code}: costs.json unit '{cu}' contradicts the map's "
            f"pay unit '{pay_unit}'")
    return float(price)


def _walk_items(cs):
    """Every IfcCostItem in the schedule, parents and nested children."""
    stack = [ci for rel in (cs.Controls or [])
             for ci in rel.RelatedObjects if ci.is_a("IfcCostItem")]
    out = []
    while stack:
        ci = stack.pop()
        out.append(ci)
        for nest in (ci.IsNestedBy or []):
            stack.extend(o for o in nest.RelatedObjects
                         if o.is_a("IfcCostItem"))
    return out


def _remove_named(model, cost_name: str) -> None:
    for cs in list(model.by_type("IfcCostSchedule")):
        if cs.Name != cost_name:
            continue
        items = _walk_items(cs)
        for ci in items:
            # Belt-and-braces only: file.remove never follows a removed
            # entity's forward attributes, so this detach is inert today —
            # the LOAD-BEARING safety here is the unassign_control loop
            # below (without it, removal leaves schema-invalid rels whose
            # RelatingControl dangles). Kept in case a future
            # remove_cost_item learns to cascade CostQuantities: those
            # entities belong to the ELEMENTS, never to this schedule.
            ci.CostQuantities = None
            for arel in list(getattr(ci, "Controls", None) or []):
                ctl.unassign_control(model, relating_control=ci,
                                     related_objects=list(arel.RelatedObjects))
            for assoc in list(getattr(ci, "HasAssociations", None) or []):
                if not assoc.is_a("IfcRelAssociatesClassification"):
                    continue
                others = [o for o in assoc.RelatedObjects if o != ci]
                if others:
                    # a shared rel (e.g. the element's own BidSchedule
                    # association) — detach this item only, never the rel
                    assoc.RelatedObjects = others
                    continue
                ref = assoc.RelatingClassification
                model.remove(assoc)
                if ref and not model.get_inverse(ref):
                    model.remove(ref)
            for cv in list(ci.CostValues or []):
                cost.remove_cost_value(model, ci, cv)
        cost.remove_cost_schedule(model, cs)


def embed_estimate(model, tmap: dict, costs: dict, *,
                   schedule_name: str | None = None) -> EstimateEmbedReport:
    """Author the ESTIMATE schedule onto the open IFC in place."""
    codes_cfg, _defaults, entries_by_code = normalize_map(tmap)
    name = schedule_name or tmap.get("project_ref") or "Estimate"
    cost_name = f"{name} estimate"
    _remove_named(model, cost_name)
    scales = _unit_scales(model)

    # elements per code (dedupe: the same code twice on one element counts once)
    elements_by_code: dict[str, list] = {}
    for el in model.by_type("IfcElement"):
        seen: set[str] = set()
        for c in classifications_of(el):
            if c["code"] and c["code"] not in seen:
                seen.add(c["code"])
                elements_by_code.setdefault(c["code"], []).append(el)

    cs = cost.add_cost_schedule(model, name=cost_name,
                                predefined_type="ESTIMATE")
    classif = _classification(model)
    report = EstimateEmbedReport(schedule_name=cost_name)

    for code, cfg in codes_cfg.items():
        cfg = cfg or {}
        entries = entries_by_code.get(code)
        plural = entries is not None
        code_extended = 0.0
        code_authored = False
        for entry in (entries or [cfg]):
            measure = entry.get("measure")
            if not measure:
                # pricing needs ONE deterministic measure; the takeoff's
                # natural-preference fallback would let elements pick
                # different measures under one rate — skip loudly instead
                report.codes_without_measure.append(code)
                continue
            dim = MEASURE_DIM[measure]
            pay_unit = entry.get("unit") or DEFAULT_UNIT[dim]
            price = _rate_for(code, entry, costs, plural=plural,
                              pay_unit=pay_unit)
            if price is None:
                report.codes_without_rate.append(code)
                continue
            elements = elements_by_code.get(code, [])
            eligible = []
            for el in elements:
                qtys = quantities_of(el)          # NATIVE — matches the rate
                if measure not in qtys:
                    report.elements_missing_measure.append(
                        (el.Name or el.is_a(), code, measure))
                    continue
                eligible.append((el, qtys[measure]))
            if not eligible:
                report.codes_without_elements.append(code)
                continue
            # convert() validates pay_unit against the measure's dimension
            rate = convert(price, dim, pay_unit) * scales[dim]
            desc = entry.get("description") or ""
            if not desc:
                for c in classifications_of(eligible[0][0]):
                    if c["code"] == code and c["name"]:
                        desc = c["name"]
                        break
            parent = cost.add_cost_item(model, cost_schedule=cs)
            cost.edit_cost_item(model, parent, attributes={
                "Name": desc or code, "Identification": code})
            children = 0
            entry_extended = 0.0
            for el, raw_qty in eligible:
                child = cost.add_cost_item(model, cost_item=parent)
                cost.edit_cost_item(model, child, attributes={
                    "Name": el.Name or f"{el.is_a()}-{el.GlobalId[:6]}"})
                cost.assign_cost_item_quantity(model, cost_item=child,
                                               products=[el],
                                               prop_name=measure)
                if not (child.CostQuantities or ()):
                    # The measure passed eligibility off an INHERITED type
                    # Qto (quantities_of reads the type; assign walks only
                    # the occurrence's IsDefinedBy) — pricing this child
                    # would leave a rate with no quantities, which consumers
                    # read as a lump total. Unwind it: unassign first
                    # (remove_cost_item skips rels it is RelatingControl of,
                    # which would dangle), then reroute the element.
                    for arel in list(child.Controls or []):
                        ctl.unassign_control(
                            model, relating_control=child,
                            related_objects=list(arel.RelatedObjects))
                    cost.remove_cost_item(model, cost_item=child)
                    report.elements_missing_measure.append(
                        (el.Name or el.is_a(), code, measure))
                    continue
                cv = cost.add_cost_value(model, parent=child)
                cost.edit_cost_value(model, cv,
                                     attributes={"AppliedValue": rate})
                children += 1
                entry_extended += rate * raw_qty
            if not children:
                # every eligible element was type-level — a childless parent
                # would read as a zero bid item; remove it and report the
                # code exactly like one with no contributing elements
                cost.remove_cost_item(model, cost_item=parent)
                report.codes_without_elements.append(code)
                continue
            _code_reference(model, parent, code, classif)
            report.parents += 1
            report.children += children
            code_extended += entry_extended
            code_authored = True
        if code_authored:
            bm = (costs.get(code) or {}).get("cost")
            report.by_code[code] = {
                "extended": code_extended,
                "bm_cost": bm,
                "variance_pct": ((code_extended - bm) / bm * 100.0
                                 if bm else None)}
            report.extended_total += code_extended
    return report
