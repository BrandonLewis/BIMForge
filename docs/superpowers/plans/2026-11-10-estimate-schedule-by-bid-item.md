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
| `bimforge/bim/estimate5d.py` | `pay_item_id` (with "Item #" normalisation); `_item_key` calls it; residue trimmed to the cost, no-element items as totals, the read-back gate (#49) |
| `bimforge/bim/costload.py` | costs.json reserved `items` key: validated, skipped by the loaders |
| `bimforge/bim/cli.py` | estimate5d prints no-element items and trimmed codes |
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

Run: `git -C <worktree> status -sb`
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

### Tasks 9–11: the TENDER total is the bid (#49)

Issue #49 lists two ways `est-bim estimate5d`'s TENDER schedule fails to total the bid:
1. A lump-sum item that no element carries, such as mobilization, never appears in the schedule.
2. An item's children drift from its `cost` by float residue (4 items came out $0.23 over on $115,140.31).

Decisions:
- **Items with no elements** come from a reserved `"items"` key in costs.json: `{"items": {"<item_number>": {"cost": 7670.0, "description": "Mobilization"}}}`.
  - Each becomes a top-level leaf, with Identification `pay_item_id(number, number)` and one IfcCostValue (AppliedValue = cost, Name "Total", no Category, so ProjectCommand doesn't see a "TOTAL" category) and no CostQuantities.
  - Codes are never named "items", and the cost5d/costload readers skip the key.
- **Children sum to the cost** only when the drift is residue: |extended − cost| ≤ max($0.01, 0.01% of cost).
  - The code's rates are then scaled by cost/extended, which is the same as rate = cost / Σ(q/basis).
  - A real variance (the model quantity isn't the bid quantity) is not hidden. It is reported as today.
- **The gate** reads the schedule back the way a consumer does (AppliedValue × q / UnitBasis, a total where there are no CostQuantities). That figure must equal the report's `extended_total` (which includes the no-element items) to $0.01, or `embed_estimate` raises and the CLI writes nothing.
- The "Item #" prefix note in #49 is handled by Task 3's `pay_item_id`.

### Task 9: costs.json `items`, validated and ignored by the cost loaders

**Files:**
- Modify: `bimforge/bim/costload.py` (`validate_costs`, `distribute_to_tasks`, `distribute_to_task_codes`)
- Test: `bimforge/bim/tests/test_costload.py`

- [ ] **Step 1: Write the failing tests**

Append to `bimforge/bim/tests/test_costload.py` (add `import pytest` at the top if it is missing):

```python
LUMPS = {"1": {"cost": 7670.0, "description": "Mobilization"}}


def test_costs_items_are_validated():
    ok = {"A": {"cost": 1.0, "labor_hours": None}, "items": LUMPS}
    costload.validate_costs(ok)
    assert costload.code_costs(ok) == {"A": ok["A"]}
    for bad in ({"items": []}, {"items": {"1": {"description": "x"}}},
                {"items": {"1": {"cost": "7670"}}},
                {"items": {"1": {"cost": 1.0, "description": 3}}}):
        with pytest.raises(ValueError, match="items"):
            costload.validate_costs(bad)


def test_the_distribution_ignores_costs_items():
    sched = _sched(tasks=[
        ScheduleTask(id="t1", name="x", start="2026-08-10",
                     finish="2026-08-10", bid_item_codes=["A"])])
    costs = {"A": {"cost": 1000.0, "labor_hours": None}}
    want = costload.distribute_to_tasks(sched, costs)
    assert costload.distribute_to_tasks(sched, {**costs, "items": LUMPS}) \
        == want
    assert costload.distribute_to_task_codes(
        sched, {**costs, "items": LUMPS}) == \
        costload.distribute_to_task_codes(sched, costs)
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/bim/tests/test_costload.py -k items`
Expected: FAIL. `costs['items'] must be an object with a 'cost'`, and `AttributeError: code_costs`.

- [ ] **Step 3: Implement**

In `bimforge/bim/costload.py`, add above `validate_costs`:

```python
#: costs.json's reserved key for bid items no element carries (estimate5d
#: writes each as a total): {"items": {"<item_number>": {cost, description?}}}
ITEMS_KEY = "items"


def code_costs(costs: dict) -> dict:
    """costs.json's per-code records, without the reserved `items` key."""
    return {k: v for k, v in costs.items() if k != ITEMS_KEY}


def _validate_items(items) -> None:
    if not isinstance(items, dict):
        raise ValueError("costs['items'] must map item numbers to "
                         "{cost, description?}")
    for number, rec in items.items():
        c = rec.get("cost") if isinstance(rec, dict) else None
        if not isinstance(c, (int, float)) or isinstance(c, bool):
            raise ValueError(f"costs['items']['{number}'] must be an object "
                             f"with a numeric 'cost'")
        desc = rec.get("description")
        if desc is not None and not isinstance(desc, str):
            raise ValueError(f"costs['items']['{number}']['description'] "
                             f"must be a string")
```

In `validate_costs`:
- Add this line to the docstring after the shape: "plus an optional reserved `"items"` key (`ITEMS_KEY`) for bid items no element carries."
- Replace `for code, rec in costs.items():` with:

```python
    if ITEMS_KEY in costs:
        _validate_items(costs[ITEMS_KEY])
    for code, rec in code_costs(costs).items():
```

In both `distribute_to_tasks` and `distribute_to_task_codes`, make the first line of the body (after the docstring) `costs = code_costs(costs)`.

- [ ] **Step 4: Run the cost suites**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/bim/tests/test_costload.py bimforge/bim/tests/test_cost5d.py bimforge/bim/tests/test_cli_5d_guard.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add bimforge/bim/costload.py bimforge/bim/tests/test_costload.py
git commit -m "feat(costload): costs.json 'items' for bid items no element carries (validated; the loaders skip it)"
```

---

### Task 10: The children sum to the item's cost

**Files:**
- Modify: `bimforge/bim/estimate5d.py` (`EstimateEmbedReport`, the per-code loop in `embed_estimate`)
- Test: `bimforge/bim/tests/test_estimate5d.py`

- [ ] **Step 1: Write the failing tests**

Append to `bimforge/bim/tests/test_estimate5d.py`:

```python
def _two_piles():
    model = _pile_ifc()
    p2 = ifcopenshell.api.root.create_entity(model, ifc_class="IfcPile",
                                             name="P-2")
    qto = ifcopenshell.api.pset.add_qto(model, product=p2,
                                        name="Qto_PileBaseQuantities")
    ifcopenshell.api.pset.edit_qto(model, qto=qto,
                                   properties={"Length": 6_250.0})
    ifcopenshell.api.classification.add_reference(
        model, products=[p2], identification="PILE-200W-FRN", name="",
        classification=model.by_type("IfcClassification")[0])
    return model


def _money(child):
    cv = child.CostValues[0]
    q = child.CostQuantities[0]
    return (cv.AppliedValue.wrappedValue * q[3]
            / cv.UnitBasis.ValueComponent.wrappedValue)


def test_residue_is_trimmed_so_the_children_sum_to_the_cost():
    # $10/LF x 18.75 m = $615.1575; the bid's cost is the rounded $615.16
    model = _two_piles()
    costs = {"PILE-200W-FRN": {**PILE_COSTS["PILE-200W-FRN"], "cost": 615.16}}
    report = estimate5d.embed_estimate(model, PILE_MAP, costs)
    kids = _children(_parents(model)[0])
    assert sum(_money(k) for k in kids) == pytest.approx(615.16, abs=1e-9)
    assert report.by_code["PILE-200W-FRN"]["extended"] == \
        pytest.approx(615.16, abs=1e-9)
    assert report.extended_total == pytest.approx(615.16, abs=1e-9)
    assert report.snapped_to_cost["PILE-200W-FRN"] == \
        pytest.approx(10.0 * 18.75 * M_TO_LF - 615.16, abs=1e-9)


def test_a_real_variance_is_reported_not_trimmed():
    model = _pile_ifc()
    report = estimate5d.embed_estimate(model, PILE_MAP, PILE_COSTS)  # 500
    (child,) = _children(_parents(model)[0])
    assert _money(child) == pytest.approx(10.0 * 12.5 * M_TO_LF, rel=1e-9)
    assert report.snapped_to_cost == {}
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/bim/tests/test_estimate5d.py -k "residue or real_variance"`
Expected: FAIL. `615.1575 != 615.16`, and `AttributeError: snapped_to_cost`.

- [ ] **Step 3: Implement**

In `estimate5d.py`, add below `EACH = "EACH"`:

```python
#: a code's extension within this of its cost is float / unit-conversion
#: residue, trimmed so its children sum to the cost exactly (#49); a larger
#: gap is a real variance (model quantity is not the bid quantity), reported
RESIDUE_REL = 1e-4


def _is_residue(extended: float, cost: float) -> bool:
    return abs(extended - cost) <= max(0.01, RESIDUE_REL * abs(cost))
```

In `EstimateEmbedReport`, after `zero_count_lump_sums`, add:

```python
    # {code: extended - cost}: residue trimmed off the code's rates so its
    # children sum to its cost exactly
    snapped_to_cost: dict = field(default_factory=dict)
```

In `embed_estimate`'s per-code loop:
- Add `code_values = []` beside `code_extended = 0.0`.
- In the `for cv, rate, raw_qty, _ in priced:` loop, append `code_values.append(cv)` after the `edit_cost_value` call.
- Replace the `if code_authored:` block with:

```python
        if code_authored:
            bm = (costs.get(code) or {}).get("cost")
            if bm and code_extended and _is_residue(code_extended, bm):
                k = bm / code_extended      # rate = cost / sum(q / basis)
                for cv in code_values:
                    cost.edit_cost_value(model, cv, attributes={
                        "AppliedValue": cv.AppliedValue.wrappedValue * k})
                report.snapped_to_cost[code] = code_extended - bm
                code_extended = float(bm)
            report.by_code[code] = {
                "extended": code_extended,
                "bm_cost": bm,
                "variance_pct": ((code_extended - bm) / bm * 100.0
                                 if bm else None)}
            report.extended_total += code_extended
```

In the module docstring, add this paragraph after the "Money semantics" paragraph (before "THE GOVERNING CODE"):

```
When a code's extension is within float / unit-conversion residue of its
costs.json `cost` (`RESIDUE_REL`, at least $0.01), its rates are scaled by
cost / extension, so its children sum to the cost exactly (#49; reported in
`snapped_to_cost`). A larger gap is a real variance and stays in `by_code`.
```

- [ ] **Step 4: Run the estimate5d suites**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/bim/tests/test_estimate5d.py bimforge/bim/tests/test_cli_estimate5d.py`
Expected: all pass. Tests with `cost: 0.0` aren't trimmed (`bm` is falsy).

- [ ] **Step 5: Commit**

```bash
git add bimforge/bim/estimate5d.py bimforge/bim/tests/test_estimate5d.py
git commit -m "fix(estimate5d): trim float residue so an item's children sum to its cost (#49)"
```

---

### Task 11: No-element items as totals, and the $0.01 gate

**Files:**
- Modify: `bimforge/bim/estimate5d.py` (`EstimateEmbedReport`, the end of `embed_estimate`, the module docstring), `bimforge/bim/cli.py` (`_run_estimate5d` output)
- Test: `bimforge/bim/tests/test_estimate5d.py`, `bimforge/bim/tests/test_cli_estimate5d.py`

- [ ] **Step 1: Write the failing tests**

Append to `bimforge/bim/tests/test_estimate5d.py`:

```python
def test_an_item_with_no_elements_is_a_total_leaf():
    model = _pile_ifc()
    costs = {**PILE_COSTS,
             "items": {"Item # 1": {"cost": 7670.0,
                                    "description": "Mobilization"}}}
    report = estimate5d.embed_estimate(model, PILE_MAP, costs)
    tops = {ci.Identification: ci for ci in _parents(model)}
    assert set(tops) == {"0055", "1"}
    mob = tops["1"]
    assert mob.Name == "Mobilization"
    assert not _children(mob) and not (mob.CostQuantities or ())
    (cv,) = mob.CostValues
    assert cv.AppliedValue.wrappedValue == 7670.0 and cv.Category is None
    assert report.items_without_elements == {"1": 7670.0}
    assert report.extended_total == pytest.approx(
        7670.0 + 10.0 * 12.5 * M_TO_LF, rel=1e-9)
    assert report.parents == 2


def test_an_items_entry_that_elements_already_price_is_refused():
    model = _pile_ifc()
    with pytest.raises(ValueError, match="0055"):
        estimate5d.embed_estimate(model, PILE_MAP, {
            **PILE_COSTS, "items": {"0055": {"cost": 1.0}}})


def test_the_schedule_must_read_back_at_the_priced_total(monkeypatch):
    model = _pile_ifc()
    real = estimate5d._leaf_money
    monkeypatch.setattr(estimate5d, "_leaf_money",
                        lambda ci: real(ci) + 0.02)
    with pytest.raises(ValueError, match="not written"):
        estimate5d.embed_estimate(model, PILE_MAP, PILE_COSTS)


def test_a_rerun_with_items_leaves_one_of_each():
    model = _pile_ifc()
    costs = {**PILE_COSTS, "items": {"1": {"cost": 7670.0}}}
    for _ in range(2):
        estimate5d.embed_estimate(model, PILE_MAP, costs)
    assert sorted(ci.Identification for ci in _parents(model)) == \
        ["0055", "1"]
    assert len(model.by_type("IfcCostSchedule")) == 1
```

In `bimforge/bim/tests/test_cli_estimate5d.py`, add a test that copies the file's first passing CLI test, with `"items": {"1": {"cost": 7670.0, "description": "Mobilization"}}` added to the costs.json it writes. It should assert that the exit code is 0 and that stdout contains `item 1: $7,670.00, no elements`. Read the file's first test for its fixture and invocation pattern (`capsys` and `main([...])` or a subprocess, whichever it uses).

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/bim/tests/test_estimate5d.py bimforge/bim/tests/test_cli_estimate5d.py -k "no_elements or already_price or read_back or rerun_with_items or items"`
Expected: FAIL. The `"items"` key is read as a code without a unit_price (skipped), there is no `items_without_elements`, and there is no `_leaf_money`.

- [ ] **Step 3: Implement**

In `estimate5d.py`, extend the `bimforge.bim.costload` usage with an import below the existing imports:

```python
from bimforge.bim.costload import ITEMS_KEY, code_costs
```

In `EstimateEmbedReport`, after `snapped_to_cost`, add:

```python
    # {pay item: cost}: costs.json "items" no element carries (mobilization),
    # each written as a top-level total with no CostQuantities
    items_without_elements: dict = field(default_factory=dict)
```

Add above `embed_estimate`:

```python
def _leaf_money(ci) -> float:
    """What a consumer reads off a leaf: AppliedValue x quantity / UnitBasis
    per value, or the AppliedValue itself when there are no CostQuantities."""
    qty = sum(float(q[3]) for q in ci.CostQuantities or ())
    total = 0.0
    for cv in ci.CostValues or ():
        v = float(cv.AppliedValue.wrappedValue) if cv.AppliedValue else 0.0
        if ci.CostQuantities:
            basis = cv.UnitBasis.ValueComponent.wrappedValue \
                if cv.UnitBasis is not None else 1.0
            v = v * qty / basis
        total += v
    return total
```

At the top of `embed_estimate`, after `codes_cfg, _defaults, entries_by_code = normalize_map(tmap)`, add:

```python
    lumps = costs.get(ITEMS_KEY) or {}
    costs = code_costs(costs)
```

Replace the final `report.parents = len(parents)` / `return report` with:

```python
    # bid items no element carries (mobilization): a top-level total each,
    # so the schedule totals the bid (#49)
    for number, rec in lumps.items():
        item = pay_item_id(number, number)
        if item in parents:
            raise ValueError(f"costs.json items: {item} is a pay item the "
                             f"map's elements already price")
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
    written = sum(_leaf_money(ci) for ci in _walk_items(cs)
                  if not any(rel.RelatedObjects
                             for rel in (ci.IsNestedBy or [])))
    if abs(written - report.extended_total) > 0.01:
        raise ValueError(f"the {schedule_type} schedule reads "
                         f"${written:,.2f} but prices "
                         f"${report.extended_total:,.2f}: not written")
    return report
```

(`pay_item_id` is Task 3's helper, in this module.) A covered parent has no children of its own, but the governing-code loop only adds control links and classification to existing priced parents. Every top-level item is therefore either a parent with children or a lump leaf, and the leaf filter is exact.

In the module docstring, add after the paragraph Task 10 added:

```
A bid item no element carries (mobilization) is listed in costs.json under
"items" ({"<item_number>": {"cost", "description"?}}) and written as a
top-level leaf with one total IfcCostValue and no CostQuantities. Before
returning, the schedule is read back the way a consumer sums it; if that
differs from the priced total by more than $0.01, embed_estimate raises.
```

In `bimforge/bim/cli.py` `_run_estimate5d`, after the `covered_by_item` print loop, add:

```python
    for item, amount in sorted(report.items_without_elements.items()):
        print(f"  item {item}: ${amount:,.2f}, no elements (costs.json items)")
    for code, drift in sorted(report.snapped_to_cost.items()):
        print(f"  {code}: rates trimmed by ${drift:+,.4f} so its children "
              f"sum to its cost")
```

In the `estimate5d` subparser, change the `--costs` help to: `"costs.json with unit_price (and optional unit) per code, and optional \"items\" for bid items no element carries"`.

- [ ] **Step 4: Run the 5D suites**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/bim/tests/test_estimate5d.py bimforge/bim/tests/test_cli_estimate5d.py bimforge/bim/tests/test_estimate_model5d.py bimforge/bim/tests/test_costload.py`
Expected: all pass. If an existing test trips the gate, don't loosen the gate. Report the test and the two totals: that is a real mismatch between the file and the report.

- [ ] **Step 5: Commit**

```bash
git add bimforge/bim/estimate5d.py bimforge/bim/cli.py bimforge/bim/tests/test_estimate5d.py bimforge/bim/tests/test_cli_estimate5d.py
git commit -m "feat(estimate5d): bid items no element carries are total leaves; the schedule must read back at its priced total (#49)"
```

---

### Task 12: Validate the IFC and run everything

- [ ] **Step 1: Write a validation script to the scratchpad**

Create `<scratchpad>/validate_estimate.py` (a temporary directory outside the repo):

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

### Task 13: CHANGELOG and ROADMAP

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
- **costs.json `"items"`** for bid items no element carries (mobilization):
  `est-bim estimate5d` writes each as a top-level total in the TENDER schedule (#49).
```

Add a `### Fixed` subsection under `## Unreleased` (create it if absent):

```markdown
- **The TENDER schedule totals the bid** (#49): a code whose extension is within
  float residue of its `cost` has its rates trimmed so its children sum to the
  cost exactly, and `estimate5d` refuses to write a schedule that does not read
  back at its priced total to $0.01.
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
| C.1a | TENDER totals the bid: no-element items, children sum to the cost, $0.01 gate (#49). | This PR |
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

### Task 14: Push and open the PR

- [ ] **Step 1:** `git push`
- [ ] **Step 2:** Open the PR against `main` titled "estimate-model: ESTIMATE schedule keyed by pay item (ProjectCommand pairing)". The body has a summary, the spec link, a test plan (the full suite count from Task 12, and the validation result), and a note that the estimating plugin needs no shim: `read_costs` keys are unchanged, and a 0.1.108 reader of the new file would read composite leaves as $0, so the plugin floor moves to 0.1.112 when it adopts this. It says `Closes #49`. End the body with the attribution line.
