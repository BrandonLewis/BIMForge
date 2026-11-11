# ESTIMATE Schedule Keyed by Bid Item Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `est-bim estimate-model` writes its ESTIMATE cost schedule as bid item → `"<item>.<cost code>"` → per-share leaves with one ADD-composed cost value, so ProjectCommand pairs it with the TENDER schedule by Identification. Every BIMForge reader keeps working and gives the same totals.

**Architecture:** The pay-item Identification moves to one helper, `estimate5d.pay_item_id`, which both writers call. `cost_categories` gains a single cost-value evaluator (`value_of`) that understands ADD composites; every reader goes through it. `schedule_read` gains small nest helpers (`_nest_parent`, `_top_item`, `_cost_key`, `_cost_code`, `cost_schedules_for`), which `read_costs` and `web/contract._shares` share. `read_costs` keys and the share `code` stay as they are. The old key rides on the bid item as `BidSheet_EstimateItem.CostKey`.

**Tech Stack:** Python 3.11+, ifcopenshell 0.8/0.9 (`ifcopenshell.api.cost`, `.unit`), pytest.

**Spec:** `docs/superpowers/specs/2026-11-09-estimate-schedule-by-bid-item-design.md`

**Run tests with:** `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider <paths>`. pytest-xdist is not installed, so don't pass `-n`.

---

## File map

| File | Change |
|---|---|
| `bimforge/bim/cost_categories.py` | `value_of`, composite-aware `categories_of` / `total_of`, `write_cost_values(..., composed=True)`, `remove_cost_values` |
| `bimforge/bim/estimate5d.py` | `pay_item_id` (with "Item #" normalisation); `_item_key` calls it |
| `bimforge/bim/cost5d.py` | `ensure_currency`, called from `add_declared_cost_schedule` |
| `bimforge/bim/schedule_read.py` | nest helpers, `cost_schedules_for`; `read_costs` uses them and `total_of` |
| `bimforge/web/contract.py` | `_shares` walks to the top-level item, uses `total_of`, adds `cost_code` |
| `bimforge/bim/estimate_model5d.py` | the re-keyed schedule, indirects, composite leaves, `CostKey`, marker `WorkSchedule`, second-ESTIMATE warning, `remove_cost_values` |
| `bimforge/bim/tests/test_cost_values.py` | new: evaluator, composed writer, removal |
| `bimforge/bim/tests/test_estimate5d.py` | `pay_item_id` tests |
| `bimforge/bim/tests/test_cost5d.py` | currency test |
| `bimforge/bim/tests/test_estimate_model5d.py` | updated structure tests, new shape tests, the TENDER-pairing test |
| `bimforge/web/tests/test_contract.py` | `cost_code` assertion |
| `CHANGELOG.md`, `ROADMAP.md` | entries |

---

### Task 0: Baseline

- [ ] **Step 1: Confirm the worktree and a green baseline**

Run: `git -C C:/Users/brand/PycharmProjects/BIMForge/.claude/worktrees/feat-estimate5d-internal-schedule status -sb`
Expected: `## feat/estimate5d-internal-schedule...`, clean.

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/bim/tests/test_estimate_model5d.py bimforge/bim/tests/test_cost_read.py bimforge/bim/tests/test_estimate5d.py bimforge/bim/tests/test_cost5d.py bimforge/web/tests/test_contract.py`
Expected: all pass. Do not start if they don't; report.

---

### Task 1: One cost-value evaluator (composites read at their components' sum)

**Files:**
- Modify: `bimforge/bim/cost_categories.py:139-158` (`_applied`, `categories_of`, `total_of`)
- Test: `bimforge/bim/tests/test_cost_values.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `bimforge/bim/tests/test_cost_values.py`:

```python
"""cost_categories: one evaluator for IfcCostValue, composites included."""
import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

import ifcopenshell.api.cost as cost  # noqa: E402
import ifcopenshell.api.root as root  # noqa: E402

from bimforge.bim.cost_categories import (  # noqa: E402
    categories_of, total_of, value_of,
)


def _item():
    f = ifcopenshell.file(schema="IFC4X3_ADD2")
    root.create_entity(f, ifc_class="IfcProject", name="p")
    cs = cost.add_cost_schedule(f, name="s")
    return f, cost.add_cost_item(f, cost_schedule=cs)


def _composite(f, ci, parts):
    top = cost.add_cost_value(f, parent=ci)
    cost.edit_cost_value(f, top, attributes={"ArithmeticOperator": "ADD"})
    for cat, amount in parts:
        cv = cost.add_cost_value(f, parent=top)
        attrs = {"AppliedValue": amount, "Name": cat or "Unallocated"}
        if cat:
            attrs["Category"] = cat
        cost.edit_cost_value(f, cv, attributes=attrs)
    return top


def test_a_composite_reads_at_its_components_sum():
    f, ci = _item()
    top = _composite(f, ci, [("Labor", 7.0), ("Material", 2.5), (None, 0.5)])
    assert top.AppliedValue is None
    assert value_of(top) == pytest.approx(10.0)
    assert total_of(ci) == pytest.approx(10.0)
    assert categories_of(ci) == {"Labor": 7.0, "Material": 2.5}


def test_sibling_values_read_as_before():
    f, ci = _item()
    for cat, amount in (("Labor", 4.0), (None, 1.0)):
        cv = cost.add_cost_value(f, parent=ci)
        attrs = {"AppliedValue": amount}
        if cat:
            attrs["Category"] = cat
        cost.edit_cost_value(f, cv, attributes=attrs)
    assert total_of(ci) == pytest.approx(5.0)
    assert categories_of(ci) == {"Labor": 4.0}


def test_a_non_add_composite_is_not_guessed_at():
    f, ci = _item()
    top = _composite(f, ci, [("Labor", 7.0)])
    top.ArithmeticOperator = "MULTIPLY"
    assert value_of(top) == 0.0
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/bim/tests/test_cost_values.py`
Expected: ImportError, `cannot import name 'value_of'`.

- [ ] **Step 3: Implement**

In `bimforge/bim/cost_categories.py`, replace `_applied`, `categories_of` and `total_of` (lines 139-158) with:

```python
def value_of(cv) -> float:
    """A cost value's amount: its AppliedValue, else, for an ADD composite
    (ArithmeticOperator ADD over Components, how estimate_model5d writes a
    leaf), the sum of its components. Another operator is not guessed at."""
    v = getattr(cv, "AppliedValue", None)
    if v is not None:
        return float(getattr(v, "wrappedValue", v))
    if getattr(cv, "ArithmeticOperator", None) == "ADD":
        return sum(value_of(c) for c in getattr(cv, "Components", None) or ())
    return 0.0


def _parts(cv):
    """The values that carry money: an ADD composite's components (down
    through nested composites), else the value itself."""
    if getattr(cv, "AppliedValue", None) is None \
            and getattr(cv, "ArithmeticOperator", None) == "ADD":
        for c in getattr(cv, "Components", None) or ():
            yield from _parts(c)
    else:
        yield cv


def categories_of(cost_item) -> dict[str, float]:
    """{Category: amount} of a cost item's categorised values, a
    composite's components included (a value with no Category is left
    out; `total_of` has everything)."""
    out: dict[str, float] = {}
    for cv in cost_item.CostValues or []:
        for part in _parts(cv):
            cat = getattr(part, "Category", None)
            if cat:
                out[cat] = out.get(cat, 0.0) + value_of(part)
    return out


def total_of(cost_item) -> float:
    return sum(value_of(cv) for cv in cost_item.CostValues or [])
```

- [ ] **Step 4: Run them to see them pass, plus the existing readers**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/bim/tests/test_cost_values.py bimforge/bim/tests/test_cost_read.py bimforge/web/tests/test_contract.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add bimforge/bim/cost_categories.py bimforge/bim/tests/test_cost_values.py
git commit -m "feat(cost): one cost-value evaluator; an ADD composite reads at its components' sum"
```

---

### Task 2: Composed writer and removal

**Files:**
- Modify: `bimforge/bim/cost_categories.py:90-125` (`write_cost_values`), and add `remove_cost_values` after it
- Test: `bimforge/bim/tests/test_cost_values.py`

- [ ] **Step 1: Write the failing tests**

Append to `bimforge/bim/tests/test_cost_values.py`:

```python
from bimforge.bim.cost_categories import (  # noqa: E402
    remove_cost_values, write_cost_values,
)


def test_composed_writes_one_add_value_with_a_component_per_kind():
    f, ci = _item()
    (top,) = write_cost_values(f, ci, 10.0, {"Labor": 6.0, "Material": 3.0},
                               composed=True)
    assert list(ci.CostValues) == [top]
    assert top.ArithmeticOperator == "ADD" and top.AppliedValue is None
    parts = {(c.Category, c.Name): c.AppliedValue.wrappedValue
             for c in top.Components}
    assert parts == {("Labor", "Labor"): 6.0, ("Material", "Material"): 3.0,
                     (None, "Unallocated"): 1.0}
    assert total_of(ci) == pytest.approx(10.0)


def test_composed_without_a_split_is_one_unallocated_component():
    f, ci = _item()
    (top,) = write_cost_values(f, ci, 4.25, None, composed=True)
    (only,) = top.Components
    assert only.Category is None and only.Name == "Unallocated"
    assert only.AppliedValue.wrappedValue == 4.25


def test_remove_cost_values_leaves_no_orphan_components():
    f, ci = _item()
    write_cost_values(f, ci, 10.0, {"Labor": 6.0}, composed=True)
    assert len(f.by_type("IfcCostValue")) == 3
    remove_cost_values(f, ci)
    assert not f.by_type("IfcCostValue")
    assert not (ci.CostValues or ())
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/bim/tests/test_cost_values.py`
Expected: ImportError, `cannot import name 'remove_cost_values'`.

- [ ] **Step 3: Implement**

Replace `write_cost_values` in `bimforge/bim/cost_categories.py` with:

```python
def write_cost_values(model, cost_item, total, by_category: dict | None, *,
                      composed: bool = False):
    """One IfcCostValue per category of `by_category` ({Category: amount},
    `split_amount`'s result) on `cost_item`, else one value of `total`.

    Categorising a cost never changes it: the kinds may add up to less than
    `total`, and the balance is then written as one more value with no
    Category (it reads back in `cost`, not in `categories`); kinds that add
    up to more than `total` are refused.

    `composed` writes ONE value on the item instead, ArithmeticOperator ADD
    with no AppliedValue of its own, whose Components are those values (an
    uncategorised cost is one `Unallocated` component): the shape
    ProjectCommand reads on an ESTIMATE leaf. Returns the values written on
    the item."""
    from ifcopenshell.api import cost
    parts = {c: Decimal(str(a)) for c, a in (by_category or {}).items() if a}
    total = Decimal(str(total))
    if not parts and not composed:
        cv = cost.add_cost_value(model, parent=cost_item)
        cost.edit_cost_value(model, cv, attributes={"AppliedValue": float(total)})
        return [cv]
    allotted = sum(parts.values(), Decimal(0))
    if allotted > total + SPLIT_TOL:
        raise ValueError(f"cost split {allotted} exceeds the cost {total}")
    holder = cost_item
    if composed:
        holder = cost.add_cost_value(model, parent=cost_item)
        cost.edit_cost_value(model, holder,
                             attributes={"ArithmeticOperator": "ADD"})
    values = []
    for cat in CATEGORIES:
        if cat not in parts:
            continue
        cv = cost.add_cost_value(model, parent=holder)
        cost.edit_cost_value(model, cv, attributes={
            "AppliedValue": float(parts[cat]), "Category": cat,
            "Name": cat})
        values.append(cv)
    balance = total - allotted
    if balance > SPLIT_TOL or (composed and not values):
        cv = cost.add_cost_value(model, parent=holder)
        cost.edit_cost_value(model, cv, attributes={
            "AppliedValue": float(balance), "Name": "Unallocated"})
        values.append(cv)
    return [holder] if composed else values


def remove_cost_values(model, cost_item) -> None:
    """Remove every value on `cost_item`, a composite's components too
    (ifcopenshell's remove_cost_value leaves them behind as orphans)."""
    from ifcopenshell.api import cost

    def tree(cv):                      # parents before their components
        out = [cv]
        for c in getattr(cv, "Components", None) or ():
            out.extend(tree(c))
        return out

    for cv in list(cost_item.CostValues or []):
        parts = tree(cv)[1:]
        cost.remove_cost_value(model, cost_item, cv)
        for part in parts:
            if not model.get_inverse(part):
                model.remove(part)
```

- [ ] **Step 4: Run them to see them pass**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/bim/tests/test_cost_values.py bimforge/bim/tests/test_cost_read.py bimforge/bim/tests/test_cost5d.py`
Expected: all pass. Sibling mode is unchanged.

- [ ] **Step 5: Commit**

```bash
git add bimforge/bim/cost_categories.py bimforge/bim/tests/test_cost_values.py
git commit -m "feat(cost): composed (ADD) cost values and a removal that takes their components"
```

---

### Task 3: `pay_item_id`, shared by both writers

**Files:**
- Modify: `bimforge/bim/estimate5d.py:144-146` (`_item_key`), with `import re` at the top
- Test: `bimforge/bim/tests/test_estimate5d.py`

- [ ] **Step 1: Write the failing tests**

Append to `bimforge/bim/tests/test_estimate5d.py`:

```python
@pytest.mark.parametrize("number,code,want", [
    ("31", "X", "31"), ("Item # 2", "X", "2"), ("item no. 7", "X", "7"),
    ("ITEM 12A", "X", "12A"), ("0055", "X", "0055"), ("", "MOB", "MOB"),
    (None, "MOB", "MOB"), ("Itemized 3", "X", "Itemized 3")])
def test_pay_item_id_is_the_bare_item_number_else_the_code(number, code, want):
    from bimforge.bim.estimate5d import pay_item_id
    assert pay_item_id(number, code) == want


def test_the_tender_pay_item_is_the_bare_number():
    f = _pile_ifc()
    tmap = {"codes": {"PILE-200W-FRN": {**PILE_MAP["codes"]["PILE-200W-FRN"],
                                        "item_number": "Item # 55"}}}
    estimate5d.embed_estimate(f, tmap, PILE_COSTS)
    (cs,) = [c for c in f.by_type("IfcCostSchedule")]
    tops = {ci.Identification for rel in cs.Controls or []
            for ci in rel.RelatedObjects if ci.is_a("IfcCostItem")}
    assert tops == {"55"}
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/bim/tests/test_estimate5d.py -k "pay_item_id or bare_number"`
Expected: ImportError on `pay_item_id`, and `{"Item # 55"} != {"55"}`.

- [ ] **Step 3: Implement**

In `bimforge/bim/estimate5d.py`, add `import re` with the other imports, and replace `_item_key` with:

```python
_ITEM_PREFIX = re.compile(r"^\s*item\b\s*(?:no\.?|number|#)?\s*[#:]?\s*",
                          re.IGNORECASE)


def pay_item_id(item_number, code) -> str:
    """The pay item's Identification: the bare item number ("Item # 2" is
    "2"), else the code. The TENDER (here) and ESTIMATE (estimate_model5d)
    schedules both take it from this one rule, since ProjectCommand pairs
    them by exact Identification."""
    number = _ITEM_PREFIX.sub("", str(item_number or "")).strip()
    return number or str(code)


def _item_key(code: str, entry: dict) -> str:
    """The pay item an entry prices: pay_item_id of its item_number."""
    return pay_item_id(entry.get("item_number"), code)
```

- [ ] **Step 4: Run the estimate5d suite**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/bim/tests/test_estimate5d.py bimforge/bim/tests/test_cli_estimate5d.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add bimforge/bim/estimate5d.py bimforge/bim/tests/test_estimate5d.py
git commit -m "feat(estimate5d): pay_item_id, the bare item number both schedules key by"
```

---

### Task 4: The file declares its currency

**Files:**
- Modify: `bimforge/bim/cost5d.py:121-147` (`add_declared_cost_schedule`); add `ensure_currency` above it
- Test: `bimforge/bim/tests/test_cost5d.py`

- [ ] **Step 1: Write the failing test**

Append to `bimforge/bim/tests/test_cost5d.py`:

```python
def test_a_declared_cost_schedule_gives_the_file_one_currency():
    import ifcopenshell.api.unit as unit
    from bimforge.bim.cost5d import add_declared_cost_schedule
    f = ifcopenshell.file(schema="IFC4X3_ADD2")
    project = ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject",
                                                  name="p")
    unit.assign_unit(f)
    add_declared_cost_schedule(f, name="a", predefined_type="TENDER")
    add_declared_cost_schedule(f, name="b", predefined_type="ESTIMATE")
    money = [u for u in project.UnitsInContext.Units
             if u.is_a("IfcMonetaryUnit")]
    assert [m.Currency for m in money] == ["USD"]


def test_a_file_without_units_is_left_alone():
    from bimforge.bim.cost5d import add_declared_cost_schedule
    f = ifcopenshell.file(schema="IFC4X3_ADD2")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="p")
    add_declared_cost_schedule(f, name="a", predefined_type="TENDER")
    assert not f.by_type("IfcUnitAssignment")
```

If `test_cost5d.py` lacks `import ifcopenshell.api.root`, add it beside its other imports.

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/bim/tests/test_cost5d.py -k currency`
Expected: FAIL, `[] == ["USD"]`.

- [ ] **Step 3: Implement**

In `bimforge/bim/cost5d.py`, add above `add_declared_cost_schedule`:

```python
def ensure_currency(model, currency: str = "USD"):
    """The project's IfcMonetaryUnit, added to its IfcUnitAssignment when it
    has none, so cost values carry a currency. A project with no unit
    assignment is left alone (it declares no units at all)."""
    import ifcopenshell.api.unit as unit
    projects = model.by_type("IfcProject")
    units = projects[0].UnitsInContext if projects else None
    if units is None:
        return None
    for u in units.Units or ():
        if u.is_a("IfcMonetaryUnit"):
            return u
    money = unit.add_monetary_unit(model, currency=currency)
    unit.assign_unit(model, units=[money])
    return money
```

In `add_declared_cost_schedule`, call `ensure_currency(model)` as its first line, and add this sentence to its docstring: "The file's currency is declared on the way (`ensure_currency`)."

- [ ] **Step 4: Run the 5D suites**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/bim/tests/test_cost5d.py bimforge/bim/tests/test_estimate5d.py bimforge/bim/tests/test_estimate_model5d.py bimforge/bim/tests/test_cost_read.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add bimforge/bim/cost5d.py bimforge/bim/tests/test_cost5d.py
git commit -m "feat(cost5d): a cost schedule declares the file's currency (IfcMonetaryUnit USD)"
```

---

### Task 5: Reader helpers and `read_costs`

**Files:**
- Modify: `bimforge/bim/schedule_read.py`: add the helpers after `_leaf_cost_items` (line ~533); in `read_costs` (536-…) change the lookup, key, value and record; update the import at line 17
- Test: `bimforge/bim/tests/test_cost_read.py`

The behaviour on today's files must not change. The new code paths are tested in Task 6 against the new writer. This task adds only a lookup test that needs no new writer.

- [ ] **Step 1: Write the failing test**

Append to `bimforge/bim/tests/test_cost_read.py`:

```python
def test_a_renamed_estimate_schedule_is_found_through_its_marker():
    import ifcopenshell.api.pset as pset
    from bimforge.bim.schedule_read import cost_schedules_for
    f = _ifc()      # this file's helper: one IfcProject, no schedules
    sched = _sched()
    embed_schedule(f, sched)
    cost5d.embed_cost_and_resources(f, sched, COSTS)
    (cs,) = f.by_type("IfcCostSchedule")
    cs.Name = "Renamed in another tool"
    assert cost_schedules_for(f, sched.name) == []
    ps = pset.add_pset(f, product=cs, name="BidSheet_EstimateModel")
    pset.edit_pset(f, pset=ps, properties={"WorkSchedule": sched.name})
    assert cost_schedules_for(f, sched.name) == [cs]
    assert read_costs(f, sched.name)["costs"]["A"]["cost"] == \
        pytest.approx(10000.0)
```

Before writing it, check the name of the file's own IFC helper: run `grep -n "^def _" bimforge/bim/tests/test_cost_read.py`. If it isn't `_ifc`, use the helper `test_round_trip_per_task_and_per_code` uses to build its model.

- [ ] **Step 2: Run it to see it fail**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/bim/tests/test_cost_read.py -k marker`
Expected: ImportError on `cost_schedules_for`.

- [ ] **Step 3: Implement the helpers**

In `bimforge/bim/schedule_read.py`, change line 17 to:

```python
from bimforge.bim.cost_categories import add_categories, categories_of, total_of
```

Add after `_leaf_cost_items`:

```python
def _nest_parent(ci):
    """The cost item `ci` is nested under, else None."""
    return next((rel.RelatingObject for rel in getattr(ci, "Nests", None) or []
                 if rel.RelatingObject.is_a("IfcCostItem")), None)


def _top_item(ci):
    """The top-level cost item above `ci` (`ci` itself when it is one)."""
    while (parent := _nest_parent(ci)) is not None:
        ci = parent
    return ci


def _cost_key(ci) -> str:
    """read_costs' key for a leaf: its bid item's CostKey (estimate_model5d
    keeps the pre-0.1.112 key there, since the item's Identification is now
    the pay item id), else the top-level item's Identification (a cost5d
    item is its own top; an older estimate-model parent carried the key)."""
    top = _top_item(ci)
    ps = _pset(top, "BidSheet_EstimateItem") or {}
    return str(ps.get("CostKey") or top.Identification or ci.Identification
               or ci.Name or ci.GlobalId)


def _cost_code(ci) -> str | None:
    """The code node's Identification ("10.03-300"): the leaf's parent when
    that parent is itself nested, else None (cost5d, older files)."""
    parent = _nest_parent(ci)
    if parent is None or _nest_parent(parent) is None:
        return None
    return parent.Identification


def cost_schedules_for(model, sname: str) -> list:
    """The cost schedules of work schedule `sname`: those named
    "<sname> cost", else the ESTIMATE ones whose BidSheet_EstimateModel
    marker names it (a schedule renamed in another tool)."""
    named = [c for c in model.by_type("IfcCostSchedule")
             if c.Name == f"{sname} cost"]
    if named:
        return named
    return [c for c in model.by_type("IfcCostSchedule")
            if (_pset(c, "BidSheet_EstimateModel") or {}).get("WorkSchedule")
            == sname]
```

- [ ] **Step 4: Use them in `read_costs`**

In `read_costs`, replace

```python
    css = [c for c in model.by_type("IfcCostSchedule") if c.Name == cost_name]
```

with

```python
    css = cost_schedules_for(model, sname)
```

Keep both `raise ValueError` messages as they are. In the leaf loop, replace

```python
        code = ci.Identification or ci.Name or ci.GlobalId
        value = sum(_number(cv.AppliedValue) or 0.0
                    for cv in ci.CostValues or [])
```

with

```python
        code = _cost_key(ci)
        value = total_of(ci)               # an ADD composite included
```

and replace

```python
        rec = entry(tid)["costs"].setdefault(code, {"cost": 0.0,
                                                    "labor_hours": None,
                                                    "categories": {}})
```

with

```python
        rec = entry(tid)["costs"].setdefault(code, {"cost": 0.0,
                                                    "labor_hours": None,
                                                    "categories": {}})
        cost_code = _cost_code(ci)
        if cost_code and "cost_code" not in rec:
            rec["cost_code"] = cost_code    # estimate-model: "<item>.<code>"
```

Add this paragraph to the `read_costs` docstring after the "A parent cost item that nests others…" paragraph:

```
    An estimate-model leaf (0.1.112+) is keyed by its bid item's CostKey,
    the key earlier versions used, and its record also carries
    `cost_code`, the "<item>.<code>" node it sits under. The cost schedule
    is "<name> cost", else the ESTIMATE schedule whose
    BidSheet_EstimateModel marker names the work schedule.
```

- [ ] **Step 5: Run the readers' suites**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/bim/tests/test_cost_read.py bimforge/bim/tests/test_estimate_model5d.py bimforge/bim/tests/test_cli_5d_guard.py bimforge/bim/tests/test_costload.py bimforge/web/tests/test_contract.py`
Expected: all pass. The writer hasn't changed yet, so keys are as before.

- [ ] **Step 6: Commit**

```bash
git add bimforge/bim/schedule_read.py bimforge/bim/tests/test_cost_read.py
git commit -m "feat(schedule_read): nest helpers; read_costs evaluates composites, keys by the bid item's CostKey, finds a renamed ESTIMATE schedule"
```

---

### Task 6: Re-key the ESTIMATE writer

**Files:**
- Modify: `bimforge/bim/estimate_model5d.py`: the imports (60-78), `item_identifications` (262-283), `_remove_prior` (191-192), the cost-schedule block (395-471), the summary (501-515), the module docstring (20-35)
- Test: `bimforge/bim/tests/test_estimate_model5d.py`

- [ ] **Step 1: Update the existing tests to the new shape, and add the new ones**

In `bimforge/bim/tests/test_estimate_model5d.py`, add `from bimforge.bim.cost_categories import total_of` to the imports, and replace `_value` with:

```python
def _value(ci):
    return total_of(ci)


def _leaves(ci):
    kids = _kids(ci)
    return [leaf for k in kids for leaf in (_leaves(k) if _kids(k) else [k])]


def _psets(obj):
    import ifcopenshell.util.element as ue
    return ue.get_psets(obj)
```

Replace `test_cost_items_per_item_and_share_sum_to_item_total` with:

```python
def test_cost_items_per_item_and_share_sum_to_item_total():
    f, summary, ftg, wall = _embed()
    cs, parents = _parents(f)
    assert cs.PredefinedType == "ESTIMATE" and cs.Name == f"{NAME} cost"
    assert set(parents) == {"10", "20"}        # the pay item ids
    conc = parents["10"]
    assert conc.Name == "Structural concrete"
    assert not (conc.CostValues or [])         # valueless: sum the leaves
    (node,) = _kids(conc)                      # a1 and a2 share 03-300
    assert node.Identification == "10.03-300"
    assert not (node.CostValues or [])
    leaves = _leaves(conc)
    values = sorted(round(_value(k), 2) for k in leaves)
    assert values == [10.00, 10.01]
    assert round(sum(values), 2) == 20.01      # not 20.00
    assert summary["cost_items"] == 2 and summary["share_items"] == 3
    assert summary["code_items"] == 2
    assert summary["items_without_shares"] == [3]
    assert "30" not in parents
    assert Decimal(summary["allocated_total"]) == Decimal("520.01")
    by_name = {k.Name: k for k in leaves}
    ftg_kid = by_name["Form & pour footing: F-1"]
    related = [o for rel in ftg_kid.Controls for o in rel.RelatedObjects]
    assert {o.is_a() for o in related} == {"IfcTask", "IfcFooting"}
    assert ftg in related
    # the pre-0.1.112 key read_costs still uses
    assert _psets(conc)["BidSheet_EstimateItem"]["CostKey"] == "51-CONC"
    assert _psets(parents["20"])["BidSheet_EstimateItem"]["CostKey"] == "20"
```

In `test_round_trip_through_read_costs`, add at the end:

```python
    assert got["tasks"]["a1"]["costs"]["51-CONC"]["cost_code"] == "10.03-300"
    assert got["tasks"]["a3"]["costs"]["20"]["cost_code"] == "20.01-500"
    assert got["tasks"]["a1"]["costs"]["51-CONC"]["categories"] == {
        "Labor": pytest.approx(10.00)}
```

Replace the first assertions of `test_items_sharing_a_code_get_distinct_identifications` (from `_, parents = _parents(f)` through the `for` loop) with:

```python
    _, parents = _parents(f)
    assert set(parents) == {"10", "20"}             # pay ids stay distinct
    keys = {_psets(ci)["BidSheet_EstimateItem"]["CostKey"]
            for ci in parents.values()}
    assert keys == {"51-CONC [A]", "51-CONC [B]"}
    for ci in parents.values():
        assert _psets(ci)["BidSheet_EstimateItem"]["ItemCode"] == "51-CONC"
```

Keep its `read_costs` assertions unchanged. Then append the new tests:

```python
def test_the_schedule_is_projectcommand_s_shape():
    f, _, _, _ = _embed()
    cs, parents = _parents(f)
    every = [ci for ci in f.by_type("IfcCostItem")]
    idents = [ci.Identification for ci in every if ci.Identification]
    assert len(idents) == len(set(idents))          # unique
    for top in parents.values():
        assert not (top.CostValues or ())
        for node in _kids(top):
            assert not (node.CostValues or ())
    for leaf in [l for top in parents.values() for l in _leaves(top)]:  # noqa: E741
        assert leaf.Identification is None
        (cv,) = leaf.CostValues                     # exactly one value
        assert cv.ArithmeticOperator == "ADD" and cv.AppliedValue is None
        assert not (leaf.CostQuantities or ())      # totals, not rates
    marker = _psets(cs)["BidSheet_EstimateModel"]
    assert marker["WorkSchedule"] == NAME


def test_a_share_with_no_bid_item_is_a_top_level_indirect():
    f, site, ftg, wall = _ifc()
    model = _model_json(ftg.GlobalId, wall.GlobalId)
    model["shares"][2]["item_id"] = None            # a3 Mobilize, 01-500
    summary = embed_estimate_model(f, model)
    _, parents = _parents(f)
    assert set(parents) == {"10", "01-500"}
    mob = parents["01-500"]
    (leaf,) = _kids(mob)                            # no code node under it
    assert _value(leaf) == pytest.approx(500.0)
    assert summary["indirect_items"] == 1
    assert not any("left out" in w for w in summary["warnings"])
    got = read_costs(f, NAME)
    assert got["tasks"]["a3"]["costs"]["01-500"]["cost"] == \
        pytest.approx(500.0)
    assert Decimal(summary["allocated_total"]) == Decimal("520.01")


def test_a_share_naming_an_unknown_item_is_still_dropped():
    f, site, ftg, wall = _ifc()
    model = _model_json(ftg.GlobalId, wall.GlobalId)
    model["shares"][2]["item_id"] = 999
    summary = embed_estimate_model(f, model)
    assert any("999" in w and "left out" in w for w in summary["warnings"])


def test_another_estimate_schedule_in_the_file_is_warned_about():
    import ifcopenshell.api.cost as cost
    f, site, ftg, wall = _ifc()
    cost.add_cost_schedule(f, name="Someone else's", predefined_type="ESTIMATE")
    summary = embed_estimate_model(f, _model_json(ftg.GlobalId, wall.GlobalId))
    assert any("ESTIMATE" in w and "Someone else's" in w
               for w in summary["warnings"])
    _f, clean, _ftg, _wall = _embed()
    assert not any("ESTIMATE schedule" in w for w in clean["warnings"])


def test_the_file_declares_one_currency_after_a_rerun():
    import ifcopenshell.api.unit as unit
    f, site, ftg, wall = _ifc()
    unit.assign_unit(f)
    doc = _model_json(ftg.GlobalId, wall.GlobalId)
    embed_estimate_model(f, doc)
    embed_estimate_model(f, doc)
    (project,) = f.by_type("IfcProject")
    assert [u.Currency for u in project.UnitsInContext.Units
            if u.is_a("IfcMonetaryUnit")] == ["USD"]
    estimates = [c for c in f.by_type("IfcCostSchedule")
                 if c.PredefinedType == "ESTIMATE"]
    assert len(estimates) == 1
    declares = [r for r in f.by_type("IfcRelDeclares")
                if estimates[0] in r.RelatedDefinitions]
    assert len(declares) == 1
```

- [ ] **Step 2: Run them to see the new expectations fail**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/bim/tests/test_estimate_model5d.py`
Expected: FAILs in the updated and new tests (for example `{"51-CONC", "20"} != {"10", "20"}`, KeyError `code_items`). The other tests pass.

- [ ] **Step 3: Implement the writer**

In `bimforge/bim/estimate_model5d.py`:

(a) Imports. Change the `cost_categories` import and the `estimate5d` import to:

```python
from bimforge.bim.cost_categories import (normalize_split, remove_cost_values,
                                          split_amount, write_cost_values)
...
from bimforge.bim.estimate5d import _walk_items, pay_item_id
```

(b) Make `item_identifications` take a key and add `pay_identifications`. Replace lines 262-283 with:

```python
def _item_code(it: dict) -> str:
    return str(it.get("item_code") or it.get("item_number") or it["id"])


def _pay_id(it: dict) -> str:
    return pay_item_id(it.get("item_number"), _item_code(it))


def _unique(items: list[dict], key) -> dict:
    """{item id: key(item)}, made unique by the item's schedule label, else
    its id, when items share a key."""
    keys = Counter(key(it) for it in items)
    qualified = Counter(f"{key(it)} [{it.get('schedule')}]"
                        for it in items if it.get("schedule"))
    out = {}
    for it in items:
        k = key(it)
        if keys[k] == 1:
            out[it["id"]] = k
            continue
        by_schedule = f"{k} [{it.get('schedule')}]"
        if it.get("schedule") and qualified[by_schedule] == 1:
            out[it["id"]] = by_schedule
        else:
            out[it["id"]] = f"{k} [item {it['id']}]"
    return out


def item_identifications(items: list[dict]) -> dict:
    """{item id: read_costs key}: the item's code, made unique (the
    Identification before 0.1.112, kept as BidSheet_EstimateItem.CostKey)."""
    return _unique(items, _item_code)


def pay_identifications(items: list[dict]) -> dict:
    """{item id: the bid item's Identification}: pay_item_id, the rule the
    TENDER schedule uses, made unique the same way (a duplicate is a data
    error ProjectCommand reports)."""
    return _unique(items, _pay_id)
```

(c) In `_remove_prior`, replace

```python
            for cv in list(ci.CostValues or []):
                cost.remove_cost_value(model, ci, cv)
```

with

```python
            remove_cost_values(model, ci)
```

(d) Replace the whole cost-schedule block, from `# -- cost schedule: parent per item, child per share` down to and including `children += 1`, with:

```python
    # -- cost schedule: bid item > "<item>.<code>" > leaf per share --------
    cs = add_declared_cost_schedule(model, name=f"{name} cost",
                                    predefined_type="ESTIMATE")
    _set_pset(model, cs, MARKER_PSET, {"EstimateId": est_id,
                                       "Writer": "est-bim estimate-model",
                                       "WorkSchedule": name})
    others = sorted(c.Name or "(unnamed)" for c in model.by_type("IfcCostSchedule")
                    if c != cs and c.PredefinedType == "ESTIMATE")
    if others:
        warnings.append(f"the IFC has another ESTIMATE schedule "
                        f"({', '.join(others)}): ProjectCommand reads only "
                        f"one per file")
    classif = _classification(model)
    by_item = defaultdict(list)
    for share in shares:
        by_item[share.get("item_id")].append(share)
    unknown_items = sorted(str(i) for i in by_item
                           if i is not None and i not in item_by_id)
    if unknown_items:
        warnings.append(f"shares name item(s) {', '.join(unknown_items)} "
                        f"the model's items do not list — left out")
    keys = item_identifications(items)
    pay_ids = pay_identifications(items)
    elem_by_id = {e.get("id"): e for e in elements}
    parents = children = code_items = indirect_items = 0
    grand = Decimal(0)
    no_shares = []

    def activity_of(share):
        return share.get("activity_key") or act_by_id.get(
            share.get("activity_id")) or f"a{share.get('activity_id')}"

    def leaf(parent, share, cents):
        nonlocal children
        akey = activity_of(share)
        act = acts.get(akey) or {}
        el = elem_by_id.get(share.get("element_id"))
        label = act.get("name") or akey
        if el is not None:
            label = f"{label}: {el.get('name') or el.get('global_id')}"
        child = cost.add_cost_item(model, cost_item=parent)
        cost.edit_cost_item(model, child, attributes={"Name": label})
        # the share's money by kind, in the activity's own proportions
        # (labour / material / equipment / subcontract / other): one ADD
        # value whose components are the kinds. No CostQuantities: these
        # are extended totals, and IFC reads a value over quantities as a
        # rate
        split = normalize_split(act.get("cost_split"))
        write_cost_values(model, child, cents, split_amount(
            cents, split, scale_from=sum(split.values(), Decimal(0))),
            composed=True)
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

    def code_of(share):
        return (acts.get(activity_of(share)) or {}).get("cost_code") \
            or activity_of(share)

    for it in items:
        item_shares = by_item.get(it.get("id"), [])
        if not item_shares:
            no_shares.append(it.get("id"))
            continue
        code = _item_code(it)
        pay = pay_ids[it["id"]]
        exact = [_dec(s.get("cost")) for s in item_shares]
        allocated = _cents(sum(exact, Decimal(0)))
        parent = cost.add_cost_item(model, cost_schedule=cs)
        cost.edit_cost_item(model, parent, attributes={
            "Name": it.get("description") or code, "Identification": pay})
        _code_reference(model, parent, code, classif)
        _set_pset(model, parent, ITEM_PSET, {
            "ItemId": it.get("id"), "ItemNumber": it.get("item_number"),
            "ItemCode": it.get("item_code"), "Schedule": it.get("schedule"),
            "CostKey": keys[it["id"]],
            "Unit": it.get("unit"),
            "Quantity": _float(it.get("quantity")),
            "UnitPrice": _float(it.get("unit_price")),
            "Total": _float(it.get("total")),
            "AllocatedTotal": float(allocated),
            "PricingSource": it.get("pricing_source")})
        parents += 1
        grand += allocated
        nodes: dict = {}
        for share, cents in zip(item_shares, apportion_cents(exact)):
            ccode = code_of(share)
            node = nodes.get(ccode)
            if node is None:
                node = nodes[ccode] = cost.add_cost_item(model,
                                                         cost_item=parent)
                cost.edit_cost_item(model, node, attributes={
                    "Name": ccode, "Identification": f"{pay}.{ccode}"})
                code_items += 1
            leaf(node, share, cents)

    # shares that name no bid item: a top-level item per cost code, which
    # ProjectCommand shows as "not in bid" (mobilization the contract
    # does not pay as an item)
    indirect = defaultdict(list)
    for share in by_item.get(None, []):
        indirect[code_of(share)].append(share)
    taken = set(pay_ids.values())
    for ccode, group in indirect.items():
        if ccode in taken:
            warnings.append(f"indirect cost code {ccode!r} is also a pay "
                            f"item id — ProjectCommand will pair it with "
                            f"that item")
        act = acts.get(activity_of(group[0])) or {}
        exact = [_dec(s.get("cost")) for s in group]
        top = cost.add_cost_item(model, cost_schedule=cs)
        cost.edit_cost_item(model, top, attributes={
            "Name": act.get("name") or ccode, "Identification": ccode})
        _code_reference(model, top, ccode, classif)
        grand += _cents(sum(exact, Decimal(0)))
        for share, cents in zip(group, apportion_cents(exact)):
            leaf(top, share, cents)
        indirect_items += 1
```

(e) In the returned summary, after `"share_items": children,` add:

```python
        "code_items": code_items,
        "indirect_items": indirect_items,
```

(f) Rewrite the module docstring's cost-schedule bullet (lines 20-35) to:

```
- **one IfcCostSchedule** (PredefinedType ESTIMATE, "<schedule> cost"),
  ProjectCommand's shape: a valueless top-level IfcCostItem per estimate
  item that carries allocation shares, its Identification the pay item id
  the TENDER schedule uses (`estimate5d.pay_item_id`: the bare item number,
  else the code; made unique by schedule label, else item id, when items
  share it), its Name the description, unit, quantity, prices and CostKey
  (read_costs' key: the code-based Identification before 0.1.112) in
  BidSheet_EstimateItem, classified under cost5d's cost-code system.
  Beneath it a valueless "<item>.<cost code>" item per activity cost code
  (the activity key when it has none), and beneath that a leaf per share
  with no Identification and ONE ADD IfcCostValue whose components are
  the share's money by kind. A share that names no item is filed under a
  top-level item keyed by its cost code alone (an indirect). Shares carry
  EXACT amounts; the leaves' cents are the running sum rounded half-up,
  differenced, so they sum to the item's allocated total (the exact sum,
  rounded once) — two $10.004 shares write $10.00 + $10.01 = $20.01. Each
  leaf is control-linked to its activity's IfcTask and to its element
  (never CostQuantities: the values are totals, not rates), and carries
  Bimforge_CostItem (TaskId, LaborHours), so `schedule_read.read_costs`
  reads it back per task and item. Items with no shares get no cost item;
  they are listed in the summary.
```

- [ ] **Step 4: Run the estimate-model suite**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/bim/tests/test_estimate_model5d.py`
Expected: all pass, including `test_rerun_replaces_by_name`. Its unchanged counts include `IfcCostValue`, so leftover components would fail it.

- [ ] **Step 5: Commit**

```bash
git add bimforge/bim/estimate_model5d.py bimforge/bim/tests/test_estimate_model5d.py
git commit -m "feat(estimate-model): ESTIMATE schedule keyed by pay item, cost codes nested, ADD-composed leaves, top-level indirects"
```

---

### Task 7: Contract view shares

**Files:**
- Modify: `bimforge/web/contract.py:225-279` (`_shares`)
- Test: `bimforge/web/tests/test_contract.py:275-305`

- [ ] **Step 1: Write the failing assertions**

In `test_estimate_shares_name_the_element_item_and_price`, after `assert by_el[ftg.GlobalId]["labor_hours"] == pytest.approx(20.0)` add:

```python
    assert by_el[ftg.GlobalId]["code"] == "51-CONC"          # dashboard join
    assert by_el[ftg.GlobalId]["cost_code"] == "10.03-300"
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/web/tests/test_contract.py -k estimate_shares_name`
Expected: FAIL. `item_number` is None, because the immediate parent is now the code node, which has no `BidSheet_EstimateItem`.

- [ ] **Step 3: Implement**

In `_shares`, replace the imports and the schedule lookup with:

```python
    import ifcopenshell.util.element as ue
    from bimforge.bim.cost_categories import categories_of, total_of
    from bimforge.bim.schedule_read import (_COST_ITEM_PSETS, _cost_code,
                                            _leaf_cost_items, _number,
                                            _pset, _top_item,
                                            cost_schedules_for, task_id)
    css = cost_schedules_for(model, schedule_name)
```

Replace

```python
        parent = next((rel.RelatingObject for rel in ci.Nests or []
                       if rel.RelatingObject.is_a("IfcCostItem")), None)
```

with

```python
        top = _top_item(ci)                # the bid item, above any code node
        parent = top if top is not ci else None
```

Replace the `out.append({...})` call with:

```python
        share = {
            "task": task_id(task),
            "element": element.GlobalId if element is not None else None,
            "item_number": (str(item["ItemNumber"])
                            if item.get("ItemNumber") not in (None, "")
                            else None),
            "code": code or ci.Identification or ci.Name,
            "cost": round(total_of(ci), 2),
            "labor_hours": _number(ps.get("LaborHours")),
            "categories": {c: round(a, 2)
                           for c, a in sorted(categories_of(ci).items())},
        }
        cost_code = _cost_code(ci)
        if cost_code:
            share["cost_code"] = cost_code
        out.append(share)
```

Update the docstring to: "…the bid item (the top-level item's BidSheet_EstimateItem ItemNumber) and the code it is classified under (the bid item's), the `cost_code` node it sits under (estimate-model), its cost and labour hours."

- [ ] **Step 4: Run the contract suite**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/web/tests`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add bimforge/web/contract.py bimforge/web/tests/test_contract.py
git commit -m "feat(web): shares read the bid item above the code node, evaluate composites, carry cost_code"
```

---

### Task 8: The two schedules pair by Identification

**Files:**
- Test: `bimforge/bim/tests/test_estimate_model5d.py`

- [ ] **Step 1: Write the test**

Append to `bimforge/bim/tests/test_estimate_model5d.py`:

```python
def test_estimate_and_tender_pair_by_identification():
    """The same bid through estimate5d (TENDER) and estimate-model
    (ESTIMATE): their top-level Identifications are equal, though the
    takeoff map spells the number "Item # 7" and BidSheet.ai "7"."""
    from bimforge.bim import estimate5d
    from bimforge.bim.tests.test_estimate5d import _pile_ifc
    f = _pile_ifc(schema="IFC4X3_ADD2")
    (pile,) = f.by_type("IfcPile")
    estimate5d.embed_estimate(
        f, {"codes": {"PILE-200W-FRN": {"measure": "Length", "unit": "LF",
                                        "item_number": "Item # 7"}}},
        {"PILE-200W-FRN": {"cost": 0, "unit_price": 10.0, "unit": "LF"}})
    embed_estimate_model(f, {
        "estimate": {"id": 9},
        "items": [{"id": 1, "item_number": "7", "item_code": "PILE-200W-FRN",
                   "description": "Piles", "unit": "LF", "quantity": "41",
                   "unit_price": "10", "total": "410"}],
        "elements": [{"id": 11, "global_id": pile.GlobalId,
                      "global_id_assigned": True, "name": "P-1"}],
        "activities": [{"id": 1, "key": "a1", "name": "Drive piles",
                        "home_item_id": 1, "cost_code": "31-620",
                        "cost": "410",
                        "cost_split": {"labor": "300", "equipment": "110"},
                        "start_date": "2026-08-10",
                        "finish_date": "2026-08-14",
                        "element_ids": [11], "spread": {}}],
        "shares": [{"activity_id": 1, "activity_key": "a1", "item_id": 1,
                    "element_id": 11, "fraction": "1", "cost": "410",
                    "manhours": "16"}]})

    def tops(kind):
        (cs,) = [c for c in f.by_type("IfcCostSchedule")
                 if c.PredefinedType == kind]
        return {ci.Identification for rel in cs.Controls or []
                for ci in rel.RelatedObjects if ci.is_a("IfcCostItem")}

    assert tops("TENDER") == tops("ESTIMATE") == {"7"}
```

- [ ] **Step 2: Run it**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/bim/tests/test_estimate_model5d.py -k pair`
Expected: PASS, since Tasks 3 and 6 already deliver this. If the TENDER schedule's PredefinedType is not "TENDER" in this fixture (estimate5d takes a stage), read `estimate5d.STAGES` and pass the stage that gives TENDER.

- [ ] **Step 3: Commit**

```bash
git add bimforge/bim/tests/test_estimate_model5d.py
git commit -m "test(estimate): TENDER and ESTIMATE pair by Identification"
```

---

### Task 9: Validate the IFC and run everything

- [ ] **Step 1: Write a validation script to the scratchpad**

Create `C:/Users/brand/AppData/Local/Temp/claude/C--Users-brand-PycharmProjects-BIMForge/142cb442-5e01-493e-aa8d-bba5db785a25/scratchpad/validate_estimate.py`:

```python
import sys
import ifcopenshell
import ifcopenshell.api.unit as unit
import ifcopenshell.validate as validate

from bimforge.bim.estimate_model5d import embed_estimate_model
from bimforge.bim.tests.test_estimate_model5d import _ifc, _model_json

f, site, ftg, wall = _ifc()
unit.assign_unit(f)
embed_estimate_model(f, _model_json(ftg.GlobalId, wall.GlobalId))
out = sys.argv[1]
f.write(out)
logger = validate.json_logger()
validate.validate(ifcopenshell.open(out), logger, express_rules=True)
errors = [s for s in logger.statements if s.get("level") == "error"]
print(len(errors), "errors")
for e in errors[:20]:
    print(e)
```

- [ ] **Step 2: Run it**

Run: `PYTHONPATH=. C:/Python314/python.exe <scratchpad>/validate_estimate.py <scratchpad>/estimate.ifc`
Expected: `0 errors`. If ifcopenshell's `validate` has no `express_rules` keyword, drop it and run `C:/Python314/python.exe -m ifcopenshell.validate --rules <scratchpad>/estimate.ifc` instead.

- [ ] **Step 3: Full suite**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge tests`
Expected: all pass (on main the count was 2137 passed, 9 skipped, plus this plan's new tests).

---

### Task 10: CHANGELOG and ROADMAP

**Files:**
- Modify: `CHANGELOG.md` (the `## Unreleased` section)
- Modify: `ROADMAP.md`

- [ ] **Step 1: CHANGELOG**

Under `## Unreleased` → `### Changed`, add:

```markdown
- **`est-bim estimate-model` writes ProjectCommand's ESTIMATE shape.** Each bid
  item's Identification is now its pay item id, the one the TENDER schedule
  (`est-bim estimate5d`) writes, so the two pair by Identification. Beneath it,
  one `"<item>.<cost code>"` item per cost code, and one leaf per share with a
  single ADD-composed IfcCostValue (its components are the money by kind) and
  no CostQuantities. `read_costs` keys and the dashboard's share `code` are
  unchanged; the old key rides on the bid item as `BidSheet_EstimateItem.CostKey`.
- **Pay item ids are the bare item number** in both schedules
  (`estimate5d.pay_item_id`): "Item # 2" is written "2".
```

Under `### Added`, add:

```markdown
- **Top-level indirects:** an estimate share naming no bid item is filed under
  a top-level cost item keyed by its cost code. Before, it was dropped with a warning.
- **Composite cost values are read everywhere** (`cost_categories.value_of`):
  `read_costs`, the categories and the web contract sum an ADD value's
  components.
- **`cost_code`** in `read_costs` per-task records and contract shares of
  estimate-model files.
- **The file's currency:** every cost schedule BIMForge writes declares an
  IfcMonetaryUnit (USD) in the project's units when it has none.
- An ESTIMATE schedule renamed in another tool is still found (its
  `BidSheet_EstimateModel.WorkSchedule`), and a second ESTIMATE schedule in the
  file is warned about.
```

- [ ] **Step 2: ROADMAP**

Append to `ROADMAP.md`:

```markdown
## 5D and IFC compliance

Goal: every schedule BIMForge writes reads correctly in any IFC tool and pairs
in ProjectCommand. The audit is `docs/superpowers/specs/2026-11-09-ifc-compliance-audit.md`.

| ID | Item | State |
|---|---|---|
| C.1 | TENDER schedule from the takeoff (`est-bim estimate5d`). | Done in #39 (0.1.111) |
| C.2 | ESTIMATE schedule keyed by pay item, cost codes nested, ADD-composed leaves, one cost evaluator, currency. Spec `docs/superpowers/specs/2026-11-09-estimate-schedule-by-bid-item-design.md`. | This PR |
| C.3 | Audit Phase 0: the remaining bugs (0.2 to 0.10). | Next |
| C.4 | Audit Phase 1: additive units, types and statuses (#37). | Next |
| C.5 | Audit Phase 2: relationship semantics (task outputs as IfcRelAssignsToProduct, resources via assign_process). | Next, coordinated with ProjectCommand |
| C.6 | Audit Phase 3: renames out of the reserved `Qto_`/`Pset_` prefixes, behind GlobalId stability. | Later; the estimating plugin shims first |
```

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md ROADMAP.md
git commit -m "docs: changelog and roadmap for the ESTIMATE re-key"
```

---

### Task 11: Push and open the PR

- [ ] **Step 1:** `git push`
- [ ] **Step 2:** Open the PR against `main` titled "estimate-model: ESTIMATE schedule keyed by pay item (ProjectCommand pairing)". The body has a summary, the spec link, a test plan (the full suite count from Task 9, and the validation result), and a note that the estimating plugin needs no shim: `read_costs` keys are unchanged, and a 0.1.108 reader of the new file would read composite leaves as $0, so the plugin floor moves to 0.1.112 when it adopts this. End the body with the attribution line.
