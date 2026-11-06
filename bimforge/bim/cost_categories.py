"""The labour / material / equipment split of a cost, written and read the
way IFC categorises money.

IFC puts no price on an element, a task or an IfcMaterial. Money lives in
an IfcCostItem under an IfcCostSchedule, as a LIST of IfcCostValue: each
value carries an AppliedValue, an optional UnitBasis (a rate per unit) and a
`Category`, "specification of the type of cost used" (IfcAppliedValue). The
cost item's total is the sum of its values, and the item is tied to what
it costs by IfcRelAssignsToControl (the task it is spent in, the element it
builds, the resource it pays for). So a cost split by kind is one cost item
with one IfcCostValue per kind, each named by its Category: that is what
this module writes and reads, and what the 4D/5D dashboard earns against.

Categories are the estimate's: Labor, Material, Equipment, Subcontract,
Other. An input split uses the estimate's keys (``labor``, ``material``,
``equipment``, ``subcontract`` or ``sub``, ``other``, ``overhead``); unknown
keys are refused so a typo is never silently "Other".
"""
from __future__ import annotations

from decimal import Decimal

CATEGORIES = ("Labor", "Material", "Equipment", "Subcontract", "Other")

#: estimate split key -> IfcCostValue.Category
SPLIT_KEYS = {"labor": "Labor", "labour": "Labor", "material": "Material",
              "materials": "Material", "equipment": "Equipment",
              "subcontract": "Subcontract", "sub": "Subcontract",
              "other": "Other", "overhead": "Other"}


def split_of(record: dict) -> dict:
    """The split a costs record carries: its top-level kind keys (``labor``,
    ``material``, ...) and, as `read_costs` returns them, a ``categories``
    mapping ({"Labor": 60, "Material": 40}); both forms add up. Kinds and
    categories are matched without regard to case."""
    out: dict = {}
    for key, value in (record or {}).items():
        if str(key).lower() in SPLIT_KEYS:
            out[key] = value
    for key, value in ((record or {}).get("categories") or {}).items():
        if str(key).lower() in SPLIT_KEYS:
            out[key] = value
    return out


def normalize_split(split) -> dict[str, Decimal]:
    """{Category: amount} from an estimate split ({labor: "10.00", ...}) or
    the reader's categories ({"Labor": 60.0, ...}); zero and missing kinds
    dropped; {} for no split. Raises on a key that is no kind of cost."""
    out: dict[str, Decimal] = {}
    for key, value in (split or {}).items():
        cat = SPLIT_KEYS.get(str(key).lower())
        if cat is None:
            raise ValueError(f"cost split: unknown kind {key!r} (one of "
                             f"{sorted(set(SPLIT_KEYS))})")
        if value in (None, ""):
            continue
        amount = Decimal(str(value))
        if amount:
            out[cat] = out.get(cat, Decimal(0)) + amount
    return out


def split_amount(total, split, *, scale_from=None) -> dict[str, Decimal]:
    """Share `total` out by the kinds of `split`, to the cent, summing to
    `total` exactly (the last cent goes to the largest kind).

    `split` is a normalized split; `scale_from` is the amount the split
    adds up to when it describes a larger whole (an activity's split for
    one element's share of it). Without a split, {} (one uncategorised
    value)."""
    from bimforge.bim.estimate_model5d import apportion_cents
    if not split:
        return {}
    total = Decimal(str(total))
    basis = Decimal(str(scale_from)) if scale_from is not None else \
        sum(split.values(), Decimal(0))
    if not basis:
        return {}
    cats = [c for c in CATEGORIES if c in split]
    exact = [total * split[c] / basis for c in cats]
    return dict(zip(cats, apportion_cents(exact)))


#: a split and its cost agree to the cent
SPLIT_TOL = Decimal("0.005")


def write_cost_values(model, cost_item, total, by_category: dict | None):
    """One IfcCostValue per category of `by_category` ({Category: amount},
    `split_amount`'s result) on `cost_item`, else one value of `total`.

    Categorising a cost never changes it: the kinds may add up to less than
    `total`, and the balance is then written as one more value with no
    Category (it reads back in `cost`, not in `categories`); kinds that add
    up to more than `total` are refused. Returns the values written."""
    from ifcopenshell.api import cost
    values = []
    parts = {c: Decimal(str(a)) for c, a in (by_category or {}).items() if a}
    total = Decimal(str(total))
    if not parts:
        cv = cost.add_cost_value(model, parent=cost_item)
        cost.edit_cost_value(model, cv, attributes={"AppliedValue": float(total)})
        return [cv]
    allotted = sum(parts.values(), Decimal(0))
    if allotted > total + SPLIT_TOL:
        raise ValueError(f"cost split {allotted} exceeds the cost {total}")
    for cat in CATEGORIES:
        if cat not in parts:
            continue
        cv = cost.add_cost_value(model, parent=cost_item)
        cost.edit_cost_value(model, cv, attributes={
            "AppliedValue": float(parts[cat]), "Category": cat,
            "Name": cat})
        values.append(cv)
    balance = total - allotted
    if balance > SPLIT_TOL:
        cv = cost.add_cost_value(model, parent=cost_item)
        cost.edit_cost_value(model, cv, attributes={
            "AppliedValue": float(balance), "Name": "Unallocated"})
        values.append(cv)
    return values


def check_split(record: dict, where: str = "") -> None:
    """Raise ValueError when a costs record's kinds add up to more than its
    cost (`validate_costs` calls this at the file boundary)."""
    split = normalize_split(split_of(record))
    if not split:
        return
    cost = Decimal(str(record.get("cost", 0)))
    allotted = sum(split.values(), Decimal(0))
    if allotted > cost + SPLIT_TOL:
        raise ValueError(f"{where}: the kinds of cost add up to {allotted}, "
                         f"more than the cost {cost}")


def _applied(cv) -> float:
    v = getattr(cv, "AppliedValue", None)
    if v is None:
        return 0.0
    return float(getattr(v, "wrappedValue", v))


def categories_of(cost_item) -> dict[str, float]:
    """{Category: amount} of a cost item's categorised values (a value
    with no Category is left out; `total_of` has everything)."""
    out: dict[str, float] = {}
    for cv in cost_item.CostValues or []:
        cat = getattr(cv, "Category", None)
        if cat:
            out[cat] = out.get(cat, 0.0) + _applied(cv)
    return out


def total_of(cost_item) -> float:
    return sum(_applied(cv) for cv in cost_item.CostValues or [])


def add_categories(into: dict[str, float], cats: dict[str, float]) -> None:
    for c, a in cats.items():
        into[c] = into.get(c, 0.0) + a
