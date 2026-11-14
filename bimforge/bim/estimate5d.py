"""Quantity-backed TENDER cost schedule: the owner's bill of quantities.

Authors the bid as an IFC cost schedule: one IfcCostSchedule (PredefinedType
TENDER, Status PLANNED; with `stage="awarded"` PRICEDBILLOFQUANTITIES /
APPROVED) named "<name> bid" and declared to the IfcProject, with one parent
IfcCostItem per BID ITEM and one nested child per contributing element.

The parent's Identification is the bare item number of the map entry's
`item_number` (`pay_item_id`: "Item # 2" is "2"; the code when an entry has
none), so every code a bid item takes off lands under ONE pay
item, and an internal ESTIMATE schedule can pair its parents with these by
Identification alone. Each child's CostQuantities references the element's
OWN Qto quantity entity — `ifcopenshell.api.cost.assign_cost_item_quantity`
appends the same entity instance, not a copy, and control-links the element
— so the priced quantity IS the model quantity. The parent carries no cost
value; consumers sum a valueless parent's children (children partition the
quantities, so the sum is honest).

Money semantics: with CostQuantities present, an item's total is
AppliedValue x quantity / UnitBasis. The referenced quantities are the file's
RAW declared-unit values (the reader-side scaling of issue #109 never
rewrites the file), so each child's AppliedValue is the bid unit rate per
one raw quantity unit, and its UnitBasis says so: an IfcMeasureWithUnit of 1
in the quantity's own Unit, else the project's declared unit for the
dimension, else EACH for a count. When the project declares no unit for the
dimension (an area in a file that declares only millimetres), it is 1 of a
unit made the raw unit's size: the prefixed IfcSIUnit when one fits (MILLI
SQUARE_METRE for mm2), else an IfcConversionBasedUnit ("raw area unit
(0.09290304 m2)" for ft2). Every basis is therefore 1 raw unit, and a
consumer's naive AppliedValue x quantity / ValueComponent is the money:

    AppliedValue = unit_price x CONVERT[dim][pay_unit] x scale

where `scale` takes that raw quantity to SI (`ifc_takeoff.quantity_scale` /
`_unit_scales`). A Count row's AppliedValue is further multiplied by
pay / counted — the takeoff's pay quantity (`ifc_takeoff.count_quantity`: 1
for LS, else `count_as` when set) over the elements' summed Count — so the
children of a lump sum sum to the capped price (#366). Elements whose Count
sums to 0 cannot carry a lump sum; the code is reported in
`zero_count_lump_sums` and extends $0.

When a code's extension is within float / unit-conversion residue of its
costs.json `cost` (`RESIDUE_REL`, at least $0.01), its non-count rates are
scaled so its children sum to the cost exactly (#49; reported in
`snapped_to_cost`). A Count / LS entry is exact by construction and never
moves; a code that is all count is never snapped. A larger gap is a real
variance and stays in `by_code`.

A bid item no element carries (mobilization) is listed in costs.json under
"items" ({"<item_number>": {"cost", "description"?}}) and written as a
top-level leaf with one total IfcCostValue and no CostQuantities. Before
returning, the schedule is read back the way a consumer sums it; if that
differs from the priced total by more than $0.01, embed_estimate raises.
The read-back is unit-aware (each quantity and each basis taken to SI), so
it also reads a basis that is not 1 raw unit correctly.

THE GOVERNING CODE. A bid item is priced on one pay quantity, and the other
codes it takes off are incidental to it: a fence item that pays by the
frame's steel weight takes off its footings, fabric and gates too, and they
carry no rate. A code without a unit_price whose item_number names a priced item
has its elements assigned (IfcRelAssignsToControl) to that item's parent —
covered, at $0, with no CostQuantities, so the price stays on the steel —
and is reported in `covered_by_item`, not `codes_without_rate`.

The BUDGET schedule cost5d authors is untouched — the two coexist. Removal
safety on re-run: every item's CostQuantities is cleared BEFORE teardown so
removing cost items can never cascade into the elements' own Qto members.
A file written by bimforge <= 0.1.110 carries this schedule as ESTIMATE,
"<name> estimate"; a re-run removes that one too.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import ifcopenshell.api.control as ctl
import ifcopenshell.api.cost as cost
import ifcopenshell.api.unit as unit_api
import ifcopenshell.util.unit as unit_util

from bimforge.bim.cost5d import (_classification, _code_reference,
                                 add_declared_cost_schedule,
                                 remove_declared_cost_schedule)
from bimforge.bim.costload import (ITEMS_KEY, code_costs, pay_item_id,
                                   validate_costs)
from bimforge.bim.ifc_takeoff import (
    DEFAULT_UNIT, MEASURE_DIM, classifications_of, convert, count_quantity,
    QUANTITY_DIM, normalize_map, quantities_of, quantity_entities,
    quantity_scale, resolve_measure, _declared, _unit_scales)

#: stage -> (IfcCostScheduleTypeEnum, Status)
STAGES = {"tender": ("TENDER", "PLANNED"),
          "awarded": ("PRICEDBILLOFQUANTITIES", "APPROVED")}

_UNIT_TYPE = {"length": "LENGTHUNIT", "area": "AREAUNIT",
              "volume": "VOLUMEUNIT", "mass": "MASSUNIT"}
_MEASURE_TYPE = {"length": "IfcLengthMeasure", "area": "IfcAreaMeasure",
                 "volume": "IfcVolumeMeasure", "mass": "IfcMassMeasure",
                 "count": "IfcCountMeasure"}
_SI_PREFIX = {"mass": "KILO"}      # SI mass is the gram; quantity_scale is kg
#: per dimension: the power of an SI prefix in the unit's size, the size of
#: the unprefixed SI unit (the gram is 0.001 kg), and the symbol for sizes
_SI_POWER = {"length": (1, 1.0, "m"), "area": (2, 1.0, "m2"),
             "volume": (3, 1.0, "m3"), "mass": (1, 0.001, "kg")}
_EXPONENTS = {"length": (1, 0), "area": (2, 0), "volume": (3, 0),
              "mass": (0, 1)}                  # (length, mass)
#: the name of a unit _UnitBasis makes for a raw size no SI prefix fits
RAW_UNIT = "raw {dim} unit ({size:.12g} {symbol})"
EACH = "EACH"
#: a code's extension within this of its cost is float / unit-conversion
#: residue, trimmed so its children sum to the cost exactly (#49); a larger
#: gap is a real variance (model quantity is not the bid quantity), reported
RESIDUE_REL = 1e-5
LEGACY_MARKER = "BidSheet_EstimateModel"   # estimate_model5d's schedules


def _is_residue(extended: float, cost: float) -> bool:
    # rounded, so a gap of exactly a cent reads the same either way round
    return round(abs(extended - cost), 6) <= max(0.01, RESIDUE_REL * abs(cost))


@dataclass
class EstimateEmbedReport:
    schedule_name: str
    schedule_type: str = "TENDER"
    parents: int = 0             # pay items
    children: int = 0
    extended_total: float = 0.0
    # {code: {"extended", "bm_cost", "variance_pct"}} — bm_cost/variance_pct
    # None (never fabricated zeros) when the lump cost is absent. Plural
    # codes aggregate their entries here: the lump cost is per code.
    by_code: dict = field(default_factory=dict)
    # {code: item}: unrated codes covered at $0 by their item's priced code
    covered_by_item: dict = field(default_factory=dict)
    codes_without_rate: list = field(default_factory=list)
    codes_without_measure: list = field(default_factory=list)
    codes_without_elements: list = field(default_factory=list)
    elements_missing_measure: list = field(default_factory=list)  # (el, code, measure)
    # (code, pay quantity): a lump sum / count_as over elements whose Count
    # sums to 0 — nothing to spread the price over, so it extends $0
    zero_count_lump_sums: list = field(default_factory=list)
    # {code: {"drift": extended - cost, "scale_pct", "cost"}}: residue
    # trimmed off the code's non-count rates (scaled by scale_pct) so its
    # children sum to its cost exactly
    snapped_to_cost: dict = field(default_factory=dict)
    # {pay item: cost}: costs.json "items" no element carries (mobilization),
    # each written as a top-level total with no CostQuantities
    items_without_elements: dict = field(default_factory=dict)


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


def _item_key(code: str, entry: dict) -> str:
    """The pay item an entry prices: pay_item_id of its item_number."""
    return pay_item_id(entry.get("item_number"), code)


class _UnitBasis:
    """One IfcMeasureWithUnit per distinct basis: 1 raw unit of a quantity."""

    def __init__(self, model):
        self.model = model
        self.made: dict = {}

    def _once(self, key, make):
        if key not in self.made:
            self.made[key] = make()
        return self.made[key]

    def _si(self, dim: str, prefix=None):
        return self._once(("si", dim, prefix), lambda: unit_api.add_si_unit(
            self.model, unit_type=_UNIT_TYPE[dim], prefix=prefix))

    def _raw_unit(self, dim: str, size: float):
        """A unit `size` SI (kg for mass) big: a prefixed IfcSIUnit when one
        fits, else an IfcConversionBasedUnit of `size` SI base units."""
        power, base, symbol = _SI_POWER[dim]
        for prefix, mult in [(None, 1.0), *unit_util.prefixes.items()]:
            if math.isclose(mult ** power * base, size, rel_tol=1e-9):
                return self._si(dim, prefix)
        m = self.model
        length, mass = _EXPONENTS[dim]
        return m.create_entity(
            "IfcConversionBasedUnit",
            Dimensions=m.create_entity("IfcDimensionalExponents",
                                       length, mass, 0, 0, 0, 0, 0),
            UnitType=_UNIT_TYPE[dim],
            Name=RAW_UNIT.format(dim=dim, size=size, symbol=symbol),
            ConversionFactor=m.create_entity(
                "IfcMeasureWithUnit",
                ValueComponent=m.create_entity(_MEASURE_TYPE[dim], size),
                UnitComponent=self._si(dim, _SI_PREFIX.get(dim))))

    def __call__(self, q_ent, dim: str, q_scale: float):
        m = self.model
        unit, value = getattr(q_ent, "Unit", None), 1.0
        if unit is None:
            if dim == "count":
                unit = self._once(("unit", EACH), lambda: unit_api.add_context_dependent_unit(
                    m, unit_type="USERDEFINED", name=EACH))
            elif _declared(m, _UNIT_TYPE[dim]):
                unit = unit_util.get_project_unit(m, _UNIT_TYPE[dim])
            else:
                # no project unit: a unit the raw unit's size, so the basis
                # is still 1 raw unit
                unit = self._once(("raw", dim, q_scale),
                                  lambda: self._raw_unit(dim, q_scale))
        if dim == "count":
            value = int(value)      # IfcCountMeasure is INTEGER in IFC4X3
        return self._once(("basis", dim, unit.id(), value), lambda: m.create_entity(
            "IfcMeasureWithUnit",
            ValueComponent=m.create_entity(_MEASURE_TYPE[dim], value),
            UnitComponent=unit))


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


def _has_pset(obj, name: str) -> bool:
    return any(r.is_a("IfcRelDefinesByProperties")
               and r.RelatingPropertyDefinition.Name == name
               for r in (getattr(obj, "IsDefinedBy", None) or []))


def _remove_basis(model, basis) -> None:
    """A UnitBasis no cost value uses any more, and a unit made for it that
    nothing else uses (a project's assigned units are always referenced)."""
    if model.get_inverse(basis):
        return
    unit = basis.UnitComponent
    model.remove(basis)
    if model.get_inverse(unit):
        return
    if (unit.is_a("IfcConversionBasedUnit")
            and unit.Name.startswith(RAW_UNIT[:4])):
        factor, dims = unit.ConversionFactor, unit.Dimensions
        model.remove(unit)
        if not model.get_inverse(dims):
            model.remove(dims)
        _remove_basis(model, factor)        # and its SI unit, if unused
    elif unit.is_a("IfcSIUnit") or (unit.is_a("IfcContextDependentUnit")
                                    and unit.Name == EACH):
        # an SI unit's Dimensions is derived; EACH's is its own entity
        dims = unit.Dimensions if unit.is_a("IfcContextDependentUnit") else None
        model.remove(unit)
        if dims is not None and not model.get_inverse(dims):
            model.remove(dims)


def _remove_named(model, cost_name: str, legacy_name: str) -> None:
    for cs in list(model.by_type("IfcCostSchedule")):
        legacy = (cs.Name == legacy_name and cs.PredefinedType == "ESTIMATE"
                  and not _has_pset(cs, LEGACY_MARKER))
        if cs.Name != cost_name and not legacy:
            continue
        bases = {}
        for ci in _walk_items(cs):
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
                if cv.UnitBasis is not None:
                    bases[cv.UnitBasis.id()] = cv.UnitBasis
                cost.remove_cost_value(model, ci, cv)
        remove_declared_cost_schedule(model, cs)
        for basis in bases.values():
            _remove_basis(model, basis)


def _size(unit, dim) -> float:
    """One `unit` in SI base (kg for mass), as `quantity_scale` sizes a
    quantity's own unit; 1 for EACH or any context-dependent unit."""
    if unit is None or unit.is_a("IfcContextDependentUnit"):
        return 1.0
    scale = unit_util.get_unit_scale(unit)
    return scale / 1000.0 if dim == "mass" else scale


def _leaf_money(ci, scales: dict) -> float:
    """What a leaf is worth, per IFC: AppliedValue x the quantity in the
    basis's unit / the basis value, i.e. AppliedValue x q x size(q's unit) /
    (basis value x size(basis unit)) per value; the AppliedValue itself when
    there are no CostQuantities. `scales` is `_unit_scales(model)`."""
    quantities = ci.CostQuantities or ()
    dims = {QUANTITY_DIM.get(q.is_a()) for q in quantities}
    dim = dims.pop() if len(dims) == 1 else None
    q_si = sum(float(q[3]) * quantity_scale(q, scales, QUANTITY_DIM.get(
        q.is_a())) for q in quantities)
    total = 0.0
    for cv in ci.CostValues or ():
        v = float(cv.AppliedValue.wrappedValue) if cv.AppliedValue else 0.0
        if quantities:
            b = cv.UnitBasis
            basis = 1.0 if b is None else (
                float(b.ValueComponent.wrappedValue)
                * _size(b.UnitComponent, dim))
            v = v * q_si / basis
        total += v
    return total


def embed_estimate(model, tmap: dict, costs: dict, *,
                   schedule_name: str | None = None,
                   stage: str = "tender") -> EstimateEmbedReport:
    """Author the TENDER (bill of quantities) schedule onto the open IFC in
    place. `stage` is "tender" (at bid) or "awarded".

    A bad stage or costs.json items raise before the model is touched. On
    any later ValueError (a rate, or the read-back gate), the in-memory
    model holds a partial schedule: callers must discard it (the CLI writes
    nothing)."""
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {sorted(STAGES)}, got {stage!r}")
    schedule_type, status = STAGES[stage]
    codes_cfg, _defaults, entries_by_code = normalize_map(tmap)
    lumps = costs.get(ITEMS_KEY) or {}
    costs = code_costs(costs)
    # elements per code (dedupe: the same code twice on one element counts once)
    elements_by_code: dict[str, list] = {}
    for el in model.by_type("IfcElement"):
        seen: set[str] = set()
        for c in classifications_of(el):
            if c["code"] and c["code"] not in seen:
                seen.add(c["code"])
                elements_by_code.setdefault(c["code"], []).append(el)

    if lumps:
        # before anything is written: an items entry is a bid item no
        # element carries, so no map entry may make the same pay item
        validate_costs({ITEMS_KEY: lumps})
        made: dict = {}                     # pay item -> map codes making it
        for code, cfg in codes_cfg.items():
            if code not in elements_by_code:
                continue                    # no element here: no parent made
            for entry in (entries_by_code.get(code) or [cfg or {}]):
                made.setdefault(_item_key(code, entry), set()).add(code)
        for number in lumps:
            item = pay_item_id(number, number)
            if item in made:
                raise ValueError(
                    f"costs.json items: '{number}' is pay item {item}, which "
                    f"map code(s) {', '.join(sorted(made[item]))} make")
    name = schedule_name or tmap.get("project_ref") or "Estimate"
    cost_name = f"{name} bid"
    _remove_named(model, cost_name, legacy_name=f"{name} estimate")
    scales = _unit_scales(model)
    basis_of = _UnitBasis(model)

    cs = add_declared_cost_schedule(model, name=cost_name,
                                    predefined_type=schedule_type,
                                    status=status)
    classif = _classification(model)
    report = EstimateEmbedReport(schedule_name=cost_name,
                                 schedule_type=schedule_type)
    parents: dict = {}                      # pay item -> parent IfcCostItem
    unrated: list[tuple[str, str]] = []     # (code, pay item)

    def _parent(item: str, desc: str):
        if item not in parents:
            p = cost.add_cost_item(model, cost_schedule=cs)
            cost.edit_cost_item(model, p, attributes={
                "Name": desc, "Identification": item})
            parents[item] = p
        return parents[item]

    for code, cfg in codes_cfg.items():
        cfg = cfg or {}
        entries = entries_by_code.get(code)
        plural = entries is not None
        code_extended = 0.0
        code_values = []                    # (cost value, dim, money)
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
                unrated.append((code, _item_key(code, entry)))
                continue
            elements = elements_by_code.get(code, [])
            eligible = []
            for el in elements:
                qtys = quantities_of(el)          # NATIVE — matches the rate
                # the takeoff's aliases (#363): a map's plain Weight reads
                # an element's GrossWeight, and the other way round
                found = resolve_measure(qtys, measure)
                if found is None:
                    report.elements_missing_measure.append(
                        (el.Name or el.is_a(), code, measure))
                    continue
                # the raw value's own scale: its quantity's Unit when it
                # names one, else the project unit of the dimension
                q_ent = quantity_entities(el).get(found)
                eligible.append((el, found, qtys[found], q_ent,
                                 quantity_scale(q_ent, scales, dim)))
            if not eligible:
                report.codes_without_elements.append(code)
                continue
            # convert() validates pay_unit against the measure's dimension;
            # the rate per raw unit is then per child (its quantity's scale)
            per_si = convert(price, dim, pay_unit)
            desc = entry.get("description") or ""
            if not desc:
                for c in classifications_of(eligible[0][0]):
                    if c["code"] == code and c["name"]:
                        desc = c["name"]
                        break
            parent = _parent(_item_key(code, entry), desc or code)
            priced = []   # (cost value, rate per raw unit, raw qty, scale)
            for el, found, raw_qty, q_ent, q_scale in eligible:
                rate = per_si * q_scale
                child = cost.add_cost_item(model, cost_item=parent)
                cost.edit_cost_item(model, child, attributes={
                    "Name": el.Name or f"{el.is_a()}-{el.GlobalId[:6]}"})
                cost.assign_cost_item_quantity(model, cost_item=child,
                                               products=[el],
                                               prop_name=found)
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
                cv.UnitBasis = basis_of(q_ent, dim, q_scale)
                priced.append((cv, rate, raw_qty, q_scale))
            # A Count row pays the takeoff's quantity (#366): 1 for a lump
            # sum, `count_as` when the map states one. The parent stays
            # valueless (consumers sum the children) and each child keeps
            # its own element's quantity, so its rate scales by
            # pay / counted — the children then sum to the capped price.
            factor = 1.0
            if dim == "count" and priced:
                counted = convert(sum(raw * qs for _, _, raw, qs in priced),
                                  dim, pay_unit)
                pay = count_quantity(entry, pay_unit, counted)
                if counted:
                    factor = pay / counted
                elif pay:
                    report.zero_count_lump_sums.append((code, pay))
            entry_extended = 0.0
            for cv, rate, raw_qty, _ in priced:
                cost.edit_cost_value(model, cv,
                                     attributes={"AppliedValue": rate * factor})
                code_values.append((cv, dim, rate * factor * raw_qty))
                entry_extended += rate * factor * raw_qty
            if not priced:
                # every eligible element was type-level: nothing to price
                report.codes_without_elements.append(code)
                continue
            _code_reference(model, parent, code, classif)
            report.children += len(priced)
            code_extended += entry_extended
            code_authored = True
        if code_authored:
            bm = (costs.get(code) or {}).get("cost")
            # a Count / LS entry is exact by construction: only the
            # measured entries take the residue
            fixed = sum(v for _, d, v in code_values if d == "count")
            scaled = code_extended - fixed
            if bm and scaled != 0 and _is_residue(scaled, bm - fixed):
                k = (bm - fixed) / scaled
                for cv, d, _ in code_values:
                    if d != "count":
                        cost.edit_cost_value(model, cv, attributes={
                            "AppliedValue": cv.AppliedValue.wrappedValue * k})
                report.snapped_to_cost[code] = {
                    "drift": code_extended - bm,
                    "scale_pct": (k - 1.0) * 100.0, "cost": float(bm)}
                code_extended = float(bm)
            report.by_code[code] = {
                "extended": code_extended,
                "bm_cost": bm,
                "variance_pct": ((code_extended - bm) / bm * 100.0
                                 if bm else None)}
            report.extended_total += code_extended

    # a childless pay item (every element type-level) would read as a zero
    # bid item: remove it; its codes are already in codes_without_elements
    for item, p in list(parents.items()):
        if not any(rel.RelatedObjects for rel in (p.IsNestedBy or [])):
            cost.remove_cost_item(model, cost_item=p)
            del parents[item]

    # the governing code: an unrated code under a priced item is covered by
    # it at $0 (its elements control-linked to the pay item, no quantities)
    for code, item in unrated:
        parent = parents.get(item) if item != code else None
        if parent is None:
            report.codes_without_rate.append(code)
            continue
        linked = {o.id() for rel in (parent.Controls or [])
                  for o in rel.RelatedObjects}
        els = [el for el in elements_by_code.get(code, [])
               if el.id() not in linked]
        if els:
            ctl.assign_control(model, relating_control=parent,
                               related_objects=els)
        _code_reference(model, parent, code, classif)
        report.covered_by_item[code] = item

    # bid items no element carries (mobilization): a top-level total each,
    # so the schedule totals the bid (#49)
    for number, rec in lumps.items():
        item = pay_item_id(number, number)
        amount = float(rec["cost"])
        lump = cost.add_cost_item(model, cost_schedule=cs)
        cost.edit_cost_item(model, lump, attributes={
            "Name": rec.get("description") or item, "Identification": item})
        cv = cost.add_cost_value(model, parent=lump)
        cost.edit_cost_value(model, cv, attributes={"AppliedValue": amount,
                                                    "Name": "Total"})
        parents[item] = lump
        report.items_without_elements[item] = amount
        report.extended_total += amount
    report.parents = len(parents)

    # the gate: the schedule reads back, as a consumer sums it, at what it
    # prices, to the cent, or it is not written
    written = sum(_leaf_money(ci, scales) for ci in _walk_items(cs)
                  if not any(rel.RelatedObjects
                             for rel in (ci.IsNestedBy or [])))
    if abs(written - report.extended_total) > 0.01:
        raise ValueError(f"the {schedule_type} schedule reads "
                         f"${written:,.2f} but prices "
                         f"${report.extended_total:,.2f}: not written")
    return report
