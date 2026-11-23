# Modified standards (M.8, M.9) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every typed element says the route it was built by (standard, modified by value / part / section, bespoke) and, when modified, each changed value with its standard and its actual value, found from what the spec already says.

**Architecture:** A new module `bimforge/author/modified.py` holds the vocabulary (`ROUTES`, `Difference`), the table diff, the route assignment and the gate check. `load_spec` keeps the packaged tables before the project file merges over them and stores the differences on the spec. Families say which table paths each element read (`Element.table_reads`); `build_from_spec` assigns routes. The barrier template sets its own route from a run's Mod keys or `profile`. `emit_ifc` writes `BIMForge_Route` (Route, BasedOn, one `IfcComplexProperty` per difference) after the GlobalId sweep, keyed like `BIMForge_Dimensions`. `model-elements` sends it.

**Tech Stack:** Python 3.11+, ifcopenshell, pytest. Spec: `docs/superpowers/specs/2026-11-22-modified-standards-design.md`.

**Conventions:** run tests with `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider <path>` from the repo root. Most files are CRLF in the working tree; edit them with a Python script using `open(..., newline="")`, or with the Edit tool when the file is LF (`file <path>` tells you). Commit messages end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. Lengths in the author domain are feet.

---

### Task 1: The vocabulary and the table diff

**Files:**
- Create: `bimforge/author/modified.py`
- Test: `bimforge/author/tests/test_modified.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Modified standards (M.8, M.9): the table diff and the routes."""
from bimforge.author.modified import (
    Difference, ROUTES, difference_measure, path_text, table_differences)


def test_equal_tables_differ_in_nothing():
    t = {"type_1_case_1": {"table": {8: {"W_ft": 6.5833, "batter": "0.5:12"}}}}
    assert table_differences(t, {"type_1_case_1": {"table": {
        8: {"W_ft": 6.5833, "batter": "0.5:12"}}}}) == []


def test_a_changed_field_is_one_difference():
    std = {"t": {"table": {8: {"W_ft": 6.5833, "C_ft": 2.3333}}}}
    got = {"t": {"table": {8: {"W_ft": 7.0, "C_ft": 2.3333}}}}
    assert table_differences(std, got) == [
        Difference(("t", "table", 8, "W_ft"), 6.5833, 7.0)]


def test_numbers_within_1e9_are_the_same_and_int_equals_float():
    assert table_differences({"a": 1}, {"a": 1.0 + 1e-12}) == []


def test_text_is_compared_exactly():
    assert table_differences({"b": "0.5:12"}, {"b": "NONE"}) == [
        Difference(("b",), "0.5:12", "NONE")]


def test_an_added_row_has_no_standard():
    std = {"t": {"table": {8: {"W_ft": 6.5}}}}
    got = {"t": {"table": {8: {"W_ft": 6.5}, 9: {"W_ft": 7.0, "C_ft": 2.5}}}}
    assert table_differences(std, got) == [
        Difference(("t", "table", 9, "W_ft"), None, 7.0),
        Difference(("t", "table", 9, "C_ft"), None, 2.5)]


def test_a_string_key_is_not_an_int_key():
    # "8" is a new row, not row 8: the merge adds it, so the diff says so
    assert table_differences({"t": {8: {"W": 1}}}, {"t": {8: {"W": 1}, "8": {"W": 2}}}) \
        == [Difference(("t", "8", "W"), None, 2)]


def test_path_text_and_routes():
    assert path_text(("type_1_case_1", "table", 8, "W_ft")) == \
        "type_1_case_1.table.8.W_ft"
    assert ROUTES == ("standard", "modified-by-value", "modified-by-part",
                      "modified-by-section", "bespoke")


def test_difference_measure_names_the_unit():
    assert difference_measure("ToeWidth") == ("IfcLengthMeasure", 1.0)
    assert difference_measure("Batter") == ("IfcRatioMeasure", None)
    assert difference_measure("W_ft") == ("IfcLengthMeasure", 1.0)
    assert difference_measure("chamfer_in") == ("IfcLengthMeasure", 1.0 / 12.0)
    assert difference_measure("deck_slope_pct") == ("IfcReal", None)
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/author/tests/test_modified.py`
Expected: FAIL, `ModuleNotFoundError: No module named 'bimforge.author.modified'`

- [ ] **Step 3: Write the module**

```python
"""Modified standards (roadmap M.8, M.9).

A modified standard, the plans' "(MOD)", is its standard class plus
recorded differences: never a new class. Every typed element carries the
route it was built by and, when modified, each value it changed, with the
standard's and its own. The differences come from what a spec already
says: a project's tables over the packaged ones (`table_differences`, kept
by `load_spec`), a barrier run's Mod dimensions (`barrier_template`).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

#: The routes an element is built by: from the standard's values; the
#: standard's shape with values changed; with a part added, removed or
#: replaced (nothing produces it yet); the standard's class with its own
#: section; authored outright.
ROUTES = ("standard", "modified-by-value", "modified-by-part",
          "modified-by-section", "bespoke")

#: The property set every routed element carries (Route, BasedOn and one
#: IfcComplexProperty per difference, UsageName DIFFERENCE).
ROUTE_PSET = "BIMForge_Route"
DIFFERENCE = "Difference"


@dataclass(frozen=True)
class Difference:
    """One packaged value the project changed: where it is in the tables,
    the pack's value (None: a row or field the project added) and the
    project's."""
    path: tuple
    standard: object
    actual: object


def _same(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-9)
    return a == b


def _added(value, path: tuple) -> list:
    if isinstance(value, dict):
        return [d for k, v in value.items() for d in _added(v, path + (k,))]
    return [Difference(path, None, value)]


def table_differences(standard: dict, merged: dict, path: tuple = ()) -> list:
    """Every leaf of `merged` that differs from `standard` (numbers within
    1e-9, anything else exactly), and every leaf `standard` does not have,
    in `merged`'s order. A key is matched as written: "8" is not 8."""
    out: list = []
    for key, value in merged.items():
        here = path + (key,)
        if key not in standard:
            out.extend(_added(value, here))
            continue
        base = standard[key]
        if isinstance(value, dict) and isinstance(base, dict):
            out.extend(table_differences(base, value, here))
        elif not _same(base, value):
            out.append(Difference(here, base, value))
    return out


def path_text(path: tuple) -> str:
    """`("type_1_case_1", "table", 8, "W_ft")` -> "type_1_case_1.table.8.W_ft"."""
    return ".".join(str(p) for p in path)


def difference_measure(name: str) -> tuple:
    """(IFC measure, feet per unit or None when not a length) of a
    difference named `name`: a dictionary dimension's own measure, else by
    the field's suffix (`_ft` feet, `_in` inches), else an IfcReal."""
    from bimforge.author import family_dictionary as fd
    try:
        ifc_type, scales = fd.measure(name)
    except KeyError:
        if name.endswith("_ft"):
            return ("IfcLengthMeasure", 1.0)
        if name.endswith("_in"):
            return ("IfcLengthMeasure", 1.0 / 12.0)
        return ("IfcReal", None)
    return (ifc_type, 1.0 if scales else None)
```

- [ ] **Step 4: Run the tests**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/author/tests/test_modified.py`
Expected: 8 passed. (If `fd.measure("ToeWidth")` is a TEXT or other tuple, check `family_dictionary.MEASURES`; ToeWidth is a length.)

- [ ] **Step 5: Commit**

```bash
git add bimforge/author/modified.py bimforge/author/tests/test_modified.py
git commit -m "modified: the routes and the table diff (M.8, M.9)"
```

---

### Task 2: `load_spec` keeps the packaged tables and reports the differences

**Files:**
- Modify: `bimforge/author/families/registry.py` (`load_spec`, around L224-240; new `DEFAULT_TABLES_PACKS`, `_pack_label`; gate validation near L262)
- Test: `bimforge/caltrans/tests/test_pack.py` (append)

- [ ] **Step 1: Write the failing tests** (append to `test_pack.py`; it already has `_spec(tmp_path, params_yaml)` writing a standard-plan spec, check its signature first and reuse it)

```python
def test_a_project_file_over_the_default_pack_is_diffed(tmp_path):
    from bimforge.author.families.registry import load_spec
    from bimforge.author.modified import Difference
    (tmp_path / "t.yaml").write_text(
        "type_1_case_1: {table: {8: {W_ft: 7.0}}}\n", "utf-8")
    pack = caltrans.load_table("b3-retaining-wall")
    (tmp_path / "full.yaml").write_text(yaml.safe_dump(
        {**pack, "type_1_case_1": {**pack["type_1_case_1"], "table": {
            **pack["type_1_case_1"]["table"],
            8: {**pack["type_1_case_1"]["table"][8], "W_ft": 7.0}}}}), "utf-8")
    spec = load_spec(_spec(tmp_path, "{tables_file: ./full.yaml, walls: []}"))
    assert spec["_tables_standard"] == "caltrans/2025/b3-retaining-wall"
    assert spec["_tables_differences"] == [Difference(
        ("type_1_case_1", "table", 8, "W_ft"),
        pack["type_1_case_1"]["table"][8]["W_ft"], 7.0)]


def test_a_named_pack_is_the_standard(tmp_path):
    from bimforge.author.families.registry import load_spec
    (tmp_path / "t.yaml").write_text(
        "type_1_case_1: {table: {8: {W_ft: 7.0}}}\n", "utf-8")
    spec = load_spec(_spec(tmp_path, (
        "{tables_pack: caltrans/b3-retaining-wall, tables_file: ./t.yaml, "
        "walls: []}")))
    assert [d.path for d in spec["_tables_differences"]] == [
        ("type_1_case_1", "table", 8, "W_ft")]
    # the baseline was copied: the pack's own row is untouched
    assert caltrans.load_table("b3-retaining-wall")["type_1_case_1"][
        "table"][8]["W_ft"] != 7.0


def test_the_pack_alone_differs_in_nothing(tmp_path):
    from bimforge.author.families.registry import load_spec
    spec = load_spec(_spec(tmp_path,
                           "{tables_pack: caltrans/b3-retaining-wall, walls: []}"))
    assert spec["_tables_differences"] == []


def test_gate_modified_must_be_a_mode(tmp_path):
    from bimforge.author.families.registry import load_spec
    path = _spec(tmp_path, "{tables_pack: caltrans/b3-retaining-wall, walls: []}")
    text = path.read_text("utf-8") + "gate: {modified: loud}\n"
    path.write_text(text, "utf-8")
    with pytest.raises(ValueError, match="gate.modified"):
        load_spec(path)
```

(`import yaml` at the top of the test file if it is not there.)

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/caltrans/tests/test_pack.py -k "diffed or standard or nothing or gate_modified"`
Expected: FAIL with `KeyError: '_tables_standard'` (and no ValueError for the gate).

- [ ] **Step 3: Implement**

At module level in `registry.py`, after `TABLE_PACKS`:

```python
# The packaged tables a family is the standard of: a spec that names no
# `tables_pack` is compared with these (M.9), so a project's `tables_file`
# that copies them reports nothing and one that changes a value says so.
DEFAULT_TABLES_PACKS = {"standard-plan": "caltrans/b3-retaining-wall"}


def _pack_label(ref) -> str:
    """`caltrans/b3-retaining-wall` -> `caltrans/2025/b3-retaining-wall`:
    the ref with the edition it resolved to."""
    pack, _, rest = str(ref).partition("/")
    if "/" not in rest:
        edition = getattr(importlib.import_module(TABLE_PACKS[pack]),
                          "EDITION", None)
        if edition:
            rest = f"{edition}/{rest}"
    return f"{pack}/{rest}"
```

Replace the `if tf or tp:` block in `load_spec` with (add `import copy` at the top):

```python
    if tf or tp:
        # packaged tables first, in the order named; the project's own file
        # last, so its rows (a field-varied schedule, say) land on top
        tables: dict = {}
        refs = [tp] if isinstance(tp, str) else list(tp or [])
        for ref in refs:
            _merge_tables(tables, _load_tables_pack(path.name, ref))
        # the standard the project's file is compared with (M.9): the packs
        # it named, else its family's own
        standard_refs = refs or ([DEFAULT_TABLES_PACKS[spec["family"]]]
                                 if spec["family"] in DEFAULT_TABLES_PACKS
                                 else [])
        baseline: dict = copy.deepcopy(tables)
        if not refs:
            for ref in standard_refs:
                _merge_tables(baseline, _load_tables_pack(path.name, ref))
        if tf:
            tf_path = (base / tf).resolve()
            if not tf_path.exists():
                raise ValueError(f"{path.name}: tables_file {tf!r} not found "
                                 f"at {tf_path}")
            _merge_tables(tables, yaml.safe_load(
                tf_path.read_text(encoding="utf-8")) or {})
        params["tables"] = tables
        spec["params"] = params
        if standard_refs:
            from bimforge.author.modified import table_differences
            spec["_tables_standard"] = " + ".join(
                _pack_label(r) for r in standard_refs)
            spec["_tables_differences"] = (
                table_differences(baseline, tables) if tf else [])
```

Beside the `gate.unread_params` validation:

```python
    from bimforge.author.modified import MODIFIED_MODES
    modified = (spec.get("gate") or {}).get("modified")
    if modified is not None and str(modified).lower() not in MODIFIED_MODES:
        raise ValueError(f"{path.name}: gate.modified {modified!r} must be "
                         f"one of {MODIFIED_MODES}")
```

And in `modified.py`: `MODIFIED_MODES = ("warn", "error", "off")`.

- [ ] **Step 4: Run the tests, then the whole of `test_pack.py` and `test_registry.py`**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/caltrans/tests/test_pack.py bimforge/author/tests/test_registry.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add bimforge/author/families/registry.py bimforge/author/modified.py bimforge/caltrans/tests/test_pack.py
git commit -m "load_spec keeps the packaged tables and lists what the project changed (M.9)"
```

---

### Task 3: The element's route fields, and the B3 wall's table reads

**Files:**
- Modify: `bimforge/author/model.py` (`Element`, after `dimensions`)
- Modify: `bimforge/author/alignment.py` (`WallSection.__init__`, `_lookup`)
- Modify: `bimforge/author/families/standard_plan.py` (`build`, new `_table_reads`)
- Modify: `bimforge/author/modified.py` (`FIELD_DIMENSIONS`)
- Test: `bimforge/author/tests/test_standard_plan_routes.py` (new)

- [ ] **Step 1: Write the failing tests**

```python
"""The B3 wall says which table values each element read (M.8)."""
from bimforge import caltrans
from bimforge.author.alignment import WallSection


def _tables():
    return caltrans.load_table("b3-retaining-wall")


def test_a_type_1_section_names_its_row():
    ws = WallSection(1, 8.0, _tables())
    row = ("type_1_case_1", "table", 8)
    assert ws.sources["W"] == [row + ("W_ft",)]
    assert ws.sources["T"] == [row + ("T_ft",)]
    assert ws.sources["batter"] == [row + ("batter",)]


def test_a_type_5_toe_is_read_from_the_batter():
    ws = WallSection(5, 8.0, _tables())
    tab = _tables()["type_5_case_1"]["table"]
    key = next(k for k in sorted(tab, key=float) if 8.0 <= float(k) + 0.5)
    row = ("type_5_case_1", "table", key)
    assert ws.sources["T"] == [("type_5_case_1", "stem_top_thickness_ft")]
    assert ws.sources["C"] == [row + ("batter",)]
    assert ws.sources["B"] == [row + ("W_ft",), row + ("batter",)]


def test_the_stem_and_footing_read_their_own_fields():
    from bimforge.author.families.standard_plan import _table_reads
    ws = WallSection(1, 8.0, _tables())
    row = ("type_1_case_1", "table", 8)
    stem = _table_reads("retaining-wall-b3-type-1", ws, ("T", "batter"))
    foot = _table_reads("retaining-wall-b3-type-1-footing", ws,
                        ("W", "C", "B", "F"))
    assert stem == {row + ("T_ft",): "StemThickness",
                    row + ("batter",): "Batter"}
    assert foot == {row + ("W_ft",): "W_ft", row + ("C_ft",): "ToeWidth",
                    row + ("B_ft",): "HeelWidth", row + ("F_ft",): "F_ft"}
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/author/tests/test_standard_plan_routes.py`
Expected: FAIL, `AttributeError: 'WallSection' object has no attribute 'sources'`

- [ ] **Step 3: Implement**

`model.py`, in `Element` after `dimensions`:

```python
    #: The route the element was built by (roadmap M.8), one of
    #: `modified.ROUTES`; `build_from_spec` gives every typed element one.
    #: None = no route written (an untyped element), unless `based_on`
    #: is set, which makes it "bespoke".
    route: str | None = None
    #: The class a modified or bespoke element is based on, by dictionary
    #: Code; None = its `family_class`.
    based_on: str | None = None
    #: What it changed from its standard (M.8): [{"name", "standard",
    #: "actual", "source"}], a dimension Code or the table field as name,
    #: values in the author domain (feet, a ratio, text); "standard" None
    #: for a row the project added.
    differences: list = field(default_factory=list)
    #: The packaged table values it was built from (M.9), {table path:
    #: name}: `modified.assign_routes` turns the ones the project changed
    #: into `differences`.
    table_reads: dict = field(default_factory=dict)
```

`alignment.py`: split `_lookup` and record sources.

```python
    @staticmethod
    def _lookup_key(table: dict, H: float):
        """The key of the nearest tabulated design H at or above the
        requested one (see `_lookup`)."""
        pairs = sorted((float(k), k) for k in table)
        for fk, k in pairs:
            if H <= fk + 0.5:
                return k
        raise ValueError(
            f"design H {H} ft exceeds the tabulated range {pairs[-1][0]} ft")

    @staticmethod
    def _lookup(table: dict, H: float) -> dict:
        """...existing docstring..."""
        return table[WallSection._lookup_key(table, H)]
```

In `__init__`, each branch looks up the key once and fills `self.sources` ({section attribute: [table paths it was read from]}):

```python
        if wt in ("1", "1a"):
            tkey = "type_1_case_1" if wt == "1" else "type_1a_case_1"
            tt = tables[tkey]
            k = self._lookup_key(tt["table"], H)
            t, row = tt["table"][k], (tkey, "table", k)
            self.W, self.C, self.B = t["W_ft"], t["C_ft"], t["B_ft"]
            src = {"W": [row + ("W_ft",)], "C": [row + ("C_ft",)],
                   "B": [row + ("B_ft",)]}
            if wt == "1":
                self.T, self.F = t["T_ft"], t["F_ft"]
                self.batter = parse_batter(t["batter"])
                src |= {"T": [row + ("T_ft",)], "F": [row + ("F_ft",)],
                        "batter": [row + ("batter",)]}
            else:                        # 1a: constant vertical stem, no batter
                self.T = tt["stem_thickness_ft"]
                self.F = tt["footing_thickness_ft"]
                self.batter = 0.0
                src |= {"T": [(tkey, "stem_thickness_ft")],
                        "F": [(tkey, "footing_thickness_ft")]}
            self.front = "vertical"
        elif wt == "5":
            tkey = "type_5_case_1"
            tt = tables[tkey]
            k = self._lookup_key(tt["table"], H)
            t, row = tt["table"][k], (tkey, "table", k)
            ... (unchanged assignments) ...
            src = {"T": [(tkey, "stem_top_thickness_ft")],
                   "F": [(tkey, "footing_thickness_ft")],
                   "W": [row + ("W_ft",)], "batter": [row + ("batter",)],
                   "C": [row + ("batter",)],
                   "B": [row + ("W_ft",), row + ("batter",)]}
        elif wt in ("6a", "6b"):
            tkey = f"type_{wt}_case_1"
            tt = tables[tkey]
            k = self._lookup_key(tt["table"], H)
            t, row = tt["table"][k], (tkey, "table", k)
            ... (unchanged assignments) ...
            src = {"T": [(tkey, "stem_thickness_ft")],
                   "F": [(tkey, "footing_thickness_ft")],
                   "W": [row + ("W_ft",)], "C": [(tkey, "toe_ft")],
                   "B": [row + ("W_ft",), (tkey, "toe_ft")]}
        else:
            raise ValueError(f"unsupported wall type {wall_type!r}")
        #: {section attribute: [table paths it was read from]} (M.9)
        self.sources = src
```

`modified.py`:

```python
#: A packaged table field that is a dictionary dimension, by the dimension's
#: Code: a difference in it is named by the Code when the element's class
#: declares that dimension, else by the field.
FIELD_DIMENSIONS = {"C_ft": "ToeWidth", "toe_ft": "ToeWidth",
                    "B_ft": "HeelWidth", "T_ft": "StemThickness",
                    "stem_thickness_ft": "StemThickness",
                    "stem_top_thickness_ft": "StemThickness",
                    "batter": "Batter"}
```

`standard_plan.py`:

```python
from bimforge.author.modified import FIELD_DIMENSIONS

#: The section attributes each element of a slice is built from (M.9)
_STEM_PARTS = ("T", "batter")
_FOOTING_PARTS = ("W", "C", "B", "F")


def _table_reads(cls, ws, parts) -> dict:
    """{table path: name} of the values `parts` of `ws` were read from: a
    field named by the dimension `cls` declares for it, else by itself."""
    declared = set(fd.dimensions(cls))
    reads = {}
    for part in parts:
        for p in ws.sources.get(part, ()):
            code = FIELD_DIMENSIONS.get(p[-1])
            reads[p] = code if code in declared else str(p[-1])
    return reads
```

In `build`, pass `table_reads=_table_reads(foot_cls, ws, _FOOTING_PARTS)` to the footing's `Element.from_geometry(...)` and `table_reads=_table_reads(stem_cls, ws, _STEM_PARTS)` to the stem's. (Check `Element.from_geometry` passes unknown kwargs through to `Element`; it does for `dimensions`, so it will for these.)

- [ ] **Step 4: Run the tests and the B3 suites**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/author/tests/test_standard_plan_routes.py bimforge/author/tests -k "standard_plan or wall or b3 or culvert_headwall"`
Expected: all pass (the D90 headwall reads `WallSection` too and must not break).

- [ ] **Step 5: Commit**

```bash
git add bimforge/author/model.py bimforge/author/alignment.py bimforge/author/families/standard_plan.py bimforge/author/modified.py bimforge/author/tests/test_standard_plan_routes.py
git commit -m "The B3 wall's elements say which table values they read (M.8, M.9)"
```

---

### Task 4: Routes assigned at build, and the `modified` gate

**Files:**
- Modify: `bimforge/author/modified.py` (`assign_routes`, `modified_lines`, `modified_check`)
- Modify: `bimforge/author/families/registry.py` (`build_from_spec`)
- Test: `bimforge/author/tests/test_modified.py` (append), `bimforge/author/tests/test_standard_plan_routes.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `test_modified.py`:

```python
from bimforge.author.model import Element


def _el(name, cls="retaining-wall-b3-type-1-footing", reads=None, **kw):
    return Element(name, "IfcFooting", family_class=cls,
                   table_reads=reads or {}, **kw)


class _Model:
    def __init__(self, *els):
        self.elements = list(els)


def test_assign_routes_gives_each_typed_element_its_route():
    from bimforge.author.modified import assign_routes
    w = ("type_1_case_1", "table", 8, "W_ft")
    b = ("type_1_case_1", "table", 8, "batter")
    hit = _el("f8", reads={w: "W_ft"})
    stem = _el("s8", cls="retaining-wall-b3-type-1", reads={b: "Batter"})
    plain = Element("loose", "IfcBuildingElementProxy")
    kept = _el("barrier", route="modified-by-section")
    m = _Model(hit, stem, plain, kept)
    assign_routes(m, [Difference(w, 6.5833, 7.0)], "caltrans/2025/b3-retaining-wall")
    assert hit.route == "modified-by-value"
    assert hit.differences == [{"name": "W_ft", "standard": 6.5833,
                                "actual": 7.0, "source":
                                "caltrans/2025/b3-retaining-wall "
                                "type_1_case_1.table.8.W_ft"}]
    assert stem.route == "standard" and stem.differences == []
    assert plain.route is None
    assert kept.route == "modified-by-section"


def test_a_batter_difference_is_a_ratio():
    from bimforge.author.modified import assign_routes
    b = ("type_1_case_1", "table", 8, "batter")
    stem = _el("s8", cls="retaining-wall-b3-type-1", reads={b: "Batter"})
    assign_routes(_Model(stem), [Difference(b, "0.5:12", "NONE")], "pack")
    assert stem.differences[0]["standard"] == 0.5 / 12
    assert stem.differences[0]["actual"] == 0.0


def test_modified_lines_group_alike_elements():
    from bimforge.author.modified import modified_check, modified_lines
    d = [{"name": "W_ft", "standard": 6.5833, "actual": 7.0, "source": "s"}]
    m = _Model(_el("a", route="modified-by-value", differences=d),
               _el("b", route="modified-by-value", differences=list(d)),
               _el("c", route="standard"))
    lines = modified_lines(m)
    assert lines == ["2 elements (a, ...) modified-by-value of "
                     "retaining-wall-b3-type-1-footing: W_ft 6.5833 -> 7.0"]
    assert modified_check(m)(m) == lines
    assert modified_check(_Model(_el("c", route="standard")))(None) == []
```

Append to `test_standard_plan_routes.py` (a build through the registry; copy the minimal B3 spec writer from `bimforge/caltrans/tests/test_pack.py:_spec`, or import it):

```python
def test_a_changed_row_modifies_only_the_elements_that_read_it(tmp_path, capsys):
    import yaml
    from bimforge.author.families.registry import build_from_spec
    from bimforge.caltrans.tests.test_pack import _spec  # the B3 spec writer
    pack = caltrans.load_table("b3-retaining-wall")
    pack["type_1_case_1"]["table"][8]["W_ft"] = 7.0
    (tmp_path / "t.yaml").write_text(yaml.safe_dump(pack), "utf-8")
    # one Type 1 wall, design H 8 ft over its length; see the shipped
    # caltrans-b3-retaining-wall.spec.yaml for a full `walls:` entry
    path = _spec(tmp_path, WALL_8FT_PARAMS)
    assert build_from_spec(str(path), check_only=True) == 0
    err = capsys.readouterr().err
    assert "type_1_case_1.table.8.W_ft 6.5833 -> 7.0" in err
    assert "modified-by-value of retaining-wall-b3-type-1-footing: W_ft" in err
    assert "of retaining-wall-b3-type-1:" not in err      # stems are standard


def test_gate_modified_error_fails_the_build(tmp_path):
    ...same setup, spec text + "gate: {modified: error}\n"...
    assert build_from_spec(str(path), check_only=True) == 1
```

`WALL_8FT_PARAMS`: write it as a module constant, a params mapping in flow YAML with `tables_file: ./t.yaml`, an `alignment` and one Type 1 wall with `design_h_segments: [{H_ft: 8, ...}]`, taken from the shipped B3 example spec (read `bimforge/author/examples/caltrans-b3-retaining-wall.spec.yaml` and keep only the first wall). If `_spec` cannot carry an alignment, write the spec file inline in the test instead, with the example's `paycodes`, `project` and `outputs` keys.

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/author/tests/test_modified.py bimforge/author/tests/test_standard_plan_routes.py`
Expected: FAIL, `ImportError: cannot import name 'assign_routes'`

- [ ] **Step 3: Implement** (in `modified.py`)

```python
def _value(name: str, value):
    """A difference's value in the author domain: a ratio dimension given
    as text ("0.5:12", "NONE") is its ratio; anything else as written."""
    if isinstance(value, str) and difference_measure(name)[0] in (
            "IfcRatioMeasure", "IfcPositiveRatioMeasure"):
        from bimforge.author.alignment import parse_batter
        return parse_batter(value)
    return value


def assign_routes(model, differences: list, source: str) -> None:
    """Give every typed element (a `family_class`) a route: the one the
    family set (a barrier's), else "modified-by-value" with the
    `differences` it read (`Element.table_reads`), else "standard"."""
    by_path = {d.path: d for d in differences}
    for el in model.elements:
        if el.family_class is None or el.route is not None:
            continue
        hit = [(by_path[p], name) for p, name in el.table_reads.items()
               if p in by_path]
        if not hit:
            el.route = "standard"
            continue
        el.route = "modified-by-value"
        el.differences = [
            {"name": name,
             "standard": None if d.standard is None else _value(name, d.standard),
             "actual": _value(name, d.actual),
             "source": f"{source} {path_text(d.path)}".strip()}
            for d, name in hit]


def _fmt(v) -> str:
    return "(added)" if v is None else (f"{v:g}" if isinstance(v, float) else str(v))


def modified_lines(model) -> list:
    """One line per kind of modified element: how many, the first's name,
    its route and class, and what it changed."""
    groups: dict = {}
    for el in model.elements:
        if not el.route or not el.route.startswith("modified"):
            continue
        what = (", ".join(f"{d['name']} {_fmt(d['standard'])} -> "
                          f"{_fmt(d['actual'])}" for d in el.differences)
                or "its own section")
        key = (el.route, el.based_on or el.family_class, what)
        groups.setdefault(key, []).append(el.name)
    lines = []
    for (route, cls, what), names in groups.items():
        who = (f"{len(names)} elements ({names[0]}, ...)" if len(names) > 1
               else names[0])
        lines.append(f"{who} {route} of {cls}: {what}")
    return lines


def modified_check(model):
    """`gate: {modified: error}`: a pre-emit check failing on every
    modified element."""
    def check_modified(_model) -> list:
        return modified_lines(model)
    return check_modified
```

(`_fmt(6.5833)` is "6.5833" and `_fmt(7.0)` is "7", so the expected line in the test reads `W_ft 6.5833 -> 7`. Fix the test's expected strings to "-> 7" accordingly, in both test files.)

In `registry.build_from_spec`, right after `model = builder(params, ctx)`:

```python
    from bimforge.author import modified as mod
    diffs = spec.get("_tables_differences") or []
    for d in diffs:
        print(f"tables: {mod.path_text(d.path)} {mod._fmt(d.standard)} -> "
              f"{mod._fmt(d.actual)} (standard: {spec['_tables_standard']})",
              file=sys.stderr)
    mod.assign_routes(model, diffs, spec.get("_tables_standard", ""))
    modified = str(gate_cfg.get("modified", "warn")).lower()
```

Change the `extra_pre` line to:

```python
    extra_pre = [unread_params_check(params, ignore)] if unread == "error" else []
    if modified == "error":
        extra_pre.append(mod.modified_check(model))
```

And after the `if unread == "warn":` block:

```python
    if modified == "warn":
        for line in mod.modified_lines(model):
            print(f"modified: {line}", file=sys.stderr)
```

Make `_fmt` public as `fmt_value` if a reviewer objects to the private import; use it in both places.

- [ ] **Step 4: Run the tests and the registry suite**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/author/tests/test_modified.py bimforge/author/tests/test_standard_plan_routes.py bimforge/author/tests/test_registry.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add bimforge/author/modified.py bimforge/author/families/registry.py bimforge/author/tests/test_modified.py bimforge/author/tests/test_standard_plan_routes.py
git commit -m "Every typed element gets its route at build; gate: {modified: warn|error|off} (M.8, M.9)"
```

---

### Task 5: `BIMForge_Route` in the IFC

**Files:**
- Modify: `bimforge/author/emit_ifc.py` (the element loop near L2247-2256; new `_routes` after `_dimensions`; call after L2559)
- Test: `bimforge/author/tests/test_emit_routes.py` (new)

- [ ] **Step 1: Write the failing tests**

Build a tiny model the way existing emit tests do (find one with `grep -rn "family_class=" bimforge/author/tests | head`, e.g. a test of `_dimensions`, and copy its model/emit fixture). Then:

```python
def _route_pset(product):
    import ifcopenshell.util.element as ue
    for rel in product.IsDefinedBy:
        p = rel.RelatingPropertyDefinition
        if p.is_a("IfcPropertySet") and p.Name == "BIMForge_Route":
            return p
    return None


def test_a_standard_element_says_so(emitted_footing):
    f, product = emitted_footing(route="standard")
    p = _route_pset(product)
    vals = {q.Name: q.NominalValue.wrappedValue for q in p.HasProperties}
    assert vals == {"Route": "standard",
                    "BasedOn": "retaining-wall-b3-type-1-footing"}


def test_a_difference_is_a_complex_property_in_metres(emitted_footing):
    f, product = emitted_footing(route="modified-by-value", differences=[
        {"name": "ToeWidth", "standard": 2.3333, "actual": 2.0,
         "source": "caltrans/2025/b3-retaining-wall type_1_case_1.table.8.C_ft"},
        {"name": "W_ft", "standard": None, "actual": 7.0, "source": "s"}])
    p = _route_pset(product)
    cx = {q.Name: q for q in p.HasProperties if q.is_a("IfcComplexProperty")}
    toe = {q.Name: q.NominalValue for q in cx["ToeWidth"].HasProperties}
    assert cx["ToeWidth"].UsageName == "Difference"
    assert toe["Standard"].is_a("IfcLengthMeasure")
    assert abs(toe["Standard"].wrappedValue - 2.3333 * 0.3048006096) < 1e-6
    assert toe["Source"].wrappedValue.endswith("table.8.C_ft")
    assert "Standard" not in {q.Name for q in cx["W_ft"].HasProperties}


def test_bespoke_based_on_classifies_and_routes(emitted_footing):
    from bimforge.bim.ifc_takeoff import family_class_of
    f, product = emitted_footing(family_class=None,
                                 based_on="retaining-wall-b3-type-1-footing")
    vals = {q.Name: q.NominalValue.wrappedValue
            for q in _route_pset(product).HasProperties}
    assert vals["Route"] == "bespoke"
    assert family_class_of(product)["code"] == "retaining-wall-b3-type-1-footing"


def test_an_unrouted_element_has_no_route_set(emitted_footing):
    f, product = emitted_footing(route=None)
    assert _route_pset(product) is None
```

`emitted_footing` is a fixture returning a function `(**element_overrides) -> (ifc_file, product)`: it builds a `StructureModel` with one `Element.from_geometry` footing (`family_class="retaining-wall-b3-type-1-footing"`, its required dimensions `{"DesignHeight": 8.0, "ToeWidth": 2.3333, "HeelWidth": 4.25}`, overrides applied), emits it with the same call the copied test uses, opens the file and returns the IfcFooting. The foot-to-metre factor in the assert follows the project's foot; if the fixture's project is in international feet use 0.3048.

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/author/tests/test_emit_routes.py`
Expected: FAIL, `_route_pset` returns None for the standard element.

- [ ] **Step 3: Implement**

In the element loop (beside `dimensioned`), declare `routed: list = []` next to `dimensioned: list = []` and:

```python
            family = el.family_class or el.based_on or (
                "reinforcing-bar" if el.bar_size is not None
                and product.is_a("IfcReinforcingBar") else None)
            ...
            if el.route or el.based_on:
                routed.append((product, el))
```

New function after `_dimensions`:

```python
def _routes(run, f, ctx, routed: list) -> None:
    """Write each routed element's BIMForge_Route (M.8): its Route (a
    `modified.ROUTES` value; "bespoke" when only `based_on` is set), the
    class it is BasedOn, and each difference as an IfcComplexProperty
    (UsageName "Difference") of Standard, Actual and Source, a length in
    the file's metres. After the sweep, keyed as BIMForge_Dimensions is."""
    from bimforge.author import modified as mod
    for product, el in routed:
        route = el.route or "bespoke"
        if route not in mod.ROUTES:
            raise ValueError(f"{el.name}: route {route!r} must be one of "
                             f"{mod.ROUTES}")
        props = {"Route": f.create_entity("IfcLabel", route)}
        based = el.based_on or el.family_class
        if based:
            props["BasedOn"] = f.create_entity("IfcLabel", based)
        pset = run("pset.add_pset", f, product=product, name=mod.ROUTE_PSET)
        run("pset.edit_pset", f, pset=pset, properties=props)
        extra = [_difference_property(f, ctx, d) for d in el.differences]
        if extra:
            pset.HasProperties = list(pset.HasProperties) + extra
        pset.GlobalId = ctx.guid(f"pset/{product.GlobalId}/{mod.ROUTE_PSET}")
        for rel in pset.DefinesOccurrence or ():
            rel.GlobalId = ctx.guid(f"rel/IfcRelDefinesByProperties/{pset.GlobalId}")


def _difference_property(f, ctx, d: dict):
    from bimforge.author import modified as mod
    ifc_type, per_ft = mod.difference_measure(d["name"])

    def single(name, value):
        if isinstance(value, str):
            nv = f.create_entity("IfcLabel", value)
        else:
            v = float(value) * (per_ft * ctx.ft_to_m if per_ft else 1.0)
            nv = f.create_entity(ifc_type, round(v, 9))
        return f.create_entity("IfcPropertySingleValue", Name=name,
                               NominalValue=nv)

    parts = []
    if d.get("standard") is not None:
        parts.append(single("Standard", d["standard"]))
    parts.append(single("Actual", d["actual"]))
    if d.get("source"):
        parts.append(f.create_entity("IfcPropertySingleValue", Name="Source",
                                     NominalValue=f.create_entity(
                                         "IfcLabel", d["source"])))
    return f.create_entity("IfcComplexProperty", Name=d["name"],
                           UsageName=mod.DIFFERENCE, HasProperties=parts)
```

Call `_routes(run, f, ctx, routed)` on the line after `_dimensions(run, f, ctx, dimensioned)`.

- [ ] **Step 4: Run the tests, the emit suites, and the GlobalId and pack identity tests**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/author/tests/test_emit_routes.py bimforge/author/tests -k "emit or globalid or dimension" bimforge/caltrans/tests/test_pack.py`
Expected: all pass. If `test_example_globalids` compares the full set of GlobalIds per example, it now sees the new `BIMForge_Route` sets: re-record with the command its module docstring gives, and check the diff adds only `pset/.../BIMForge_Route` and its rels (no existing id moves).

- [ ] **Step 5: Commit**

```bash
git add bimforge/author/emit_ifc.py bimforge/author/tests/test_emit_routes.py
git commit -m "emit_ifc writes BIMForge_Route: the route, the class it is based on, each difference (M.8)"
```

---

### Task 6: The barriers' Mod and profile routes

**Files:**
- Modify: `bimforge/author/barrier_template.py` (`BarrierTemplate`: `standard_dims`; `end_run(..., run)`; new `run_route`; the three `end_run` callers at L193, L253, L468)
- Modify: `bimforge/author/type_842_profile.py` (public `STANDARD_DIMS`)
- Modify: `bimforge/author/families/concrete_barrier_842.py`, `concrete_barrier_732sw.py` (`_TEMPLATE`)
- Test: `bimforge/author/tests/test_barrier_routes.py` (new)

- [ ] **Step 1: Write the failing tests**

```python
"""A barrier run's Mod dimensions and profile are its route (M.8)."""
from bimforge.author.barrier_template import run_route
from bimforge.author.families import concrete_barrier_732sw, concrete_barrier_842


def test_a_standard_842_run():
    assert run_route(concrete_barrier_842.template(),
                     {"straight_length_ft": 40}) == ("standard", [])


def test_an_842_with_a_taller_stem_is_modified_by_value():
    route, diffs = run_route(concrete_barrier_842.template(),
                             {"straight_length_ft": 40, "stem_h_ft": 4.0})
    assert route == "modified-by-value"
    assert diffs == [{"name": "stem_h_ft", "standard": 3.5, "actual": 4.0,
                      "source": diffs[0]["source"]}]
    assert diffs[0]["source"].endswith("stem_h_ft")


def test_a_run_given_at_the_standard_value_is_standard():
    assert run_route(concrete_barrier_842.template(),
                     {"stem_h_ft": 3.5})[0] == "standard"


def test_a_profile_is_modified_by_section():
    ring = [[0, 0], [1.75, 0], [1.2, 3.5], [0, 3.5]]
    assert run_route(concrete_barrier_842.template(),
                     {"profile": ring}) == ("modified-by-section", [])


def test_a_732sw_sidewalk_width_mod():
    route, diffs = run_route(concrete_barrier_732sw.template(),
                             {"sw_width_ft": 8.0})
    assert route == "modified-by-value"
    assert diffs[0]["name"] == "sw_width_ft" and diffs[0]["actual"] == 8.0
```

And one build test: build the shipped 842 example spec (find it with `ls bimforge/author/examples | grep 842`) with one run given `stem_h_ft: 4.0`; assert the run whole and its IfcWall bodies have `route == "modified-by-value"` and the run's other parts (rebar) have none. Build the model with the family builder directly (`concrete_barrier_842.build(params, ctx)` as its existing tests do) rather than through `build_from_spec`.

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/author/tests/test_barrier_routes.py`
Expected: FAIL, `ImportError: cannot import name 'run_route'`

- [ ] **Step 3: Implement**

`type_842_profile.py`, after the constants:

```python
#: The standard section's value of each dimension a run may Mod (M.8)
STANDARD_DIMS = {"stem_h_ft": _H, "top_slope_x_ft": _X_TOPSLOPE,
                 "base_w_ft": _X_BASE_DECK, "back_x_ft": _X_BACK_UPPER,
                 "step_x_ft": _X_BACK_LOWER,
                 "step_from_top_ft": _STEP_FROM_TOP, "chamfer_in": 0.0}
```

(Check that `_MOD_KEYS` in `concrete_barrier_842.py` and these keys are the same set; add a test asserting `set(STANDARD_DIMS) == set(concrete_barrier_842._MOD_KEYS)`.)

`BarrierTemplate`, a new field:

```python
    #: The standard section's dimensions a run may Mod, {key: value} (M.8):
    #: a run giving one at another value is "modified-by-value", a run with
    #: its own `profile` "modified-by-section". None = no route set here.
    standard_dims: Optional[dict] = None
```

In each `_TEMPLATE`: `standard_dims=STANDARD_DIMS` (842, imported from `type_842_profile`) and `standard_dims=SECTION_DEFAULTS` (732SW).

`barrier_template.py`:

```python
def run_route(tmpl: BarrierTemplate, run: dict) -> tuple:
    """(route, differences) of one run (M.8): its own `profile` is a
    section of its own; a Mod dimension at another value than the
    standard's is a modified value; else standard. (None, []) for a
    family with no `standard_dims`."""
    if tmpl.standard_dims is None:
        return None, []
    if "profile" in run:
        return "modified-by-section", []
    where = standard_plan(tmpl) or tmpl.family_id
    diffs = [{"name": k, "standard": float(std), "actual": float(run[k]),
              "source": f"{where} {k}"}
             for k, std in tmpl.standard_dims.items()
             if k in run and not math.isclose(float(run[k]), float(std),
                                              rel_tol=0.0, abs_tol=1e-9)]
    return ("modified-by-value" if diffs else "standard"), diffs
```

`end_run(tmpl, model, start, run=None)`: after the existing loop,

```python
    route, diffs = run_route(tmpl, run) if run is not None else (None, [])
    if route:
        cls = _family_class(tmpl)
        for el in [whole] + model.elements[start:]:
            if el.family_class == cls:
                el.route, el.differences = route, list(diffs)
```

Pass `run` at the three callers (`end_run(tmpl, model, start, run)`; check each caller has `run` in scope; the curved and on-alignment builders take it as a parameter). Add `import math` if missing.

- [ ] **Step 4: Run the tests and the barrier suites**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/author/tests/test_barrier_routes.py bimforge/author/tests -k "barrier or 842 or 732"`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add bimforge/author/barrier_template.py bimforge/author/type_842_profile.py bimforge/author/families/concrete_barrier_842.py bimforge/author/families/concrete_barrier_732sw.py bimforge/author/tests/test_barrier_routes.py
git commit -m "A barrier run's Mod dimensions and profile are its route (M.8)"
```

---

### Task 7: `model-elements` sends the route

**Files:**
- Modify: `bimforge/bim/model_elements.py` (`described`; module docstring's key list near L84)
- Test: `bimforge/bim/tests/test_model_elements.py` (append)

- [ ] **Step 1: Write the failing test**

Build a B3 model with one changed row (reuse Task 4's spec writer: `build_from_spec` on a spec whose `outputs.ifc` is in `tmp_path`), then:

```python
def test_model_elements_sends_the_route_and_differences(tmp_path):
    import ifcopenshell
    from bimforge.bim.model_elements import plan_modelled_elements
    ifc_path = _build_modified_b3(tmp_path)        # W_ft of row 8 -> 7.0
    out = plan_modelled_elements(ifcopenshell.open(str(ifc_path)))
    foot = next(e for e in out["elements"]
                if e.get("family_class") == "retaining-wall-b3-type-1-footing")
    stem = next(e for e in out["elements"]
                if e.get("family_class") == "retaining-wall-b3-type-1")
    assert foot["route"] == "modified-by-value"
    assert foot["based_on"] == "retaining-wall-b3-type-1-footing"
    assert foot["differences"] == [{
        "name": "W_ft", "standard": 6.5833, "actual": 7.0, "unit": "FT",
        "source": "caltrans/2025/b3-retaining-wall type_1_case_1.table.8.W_ft"}]
    assert stem["route"] == "standard" and "differences" not in stem
```

(Check how `plan_modelled_elements` is called in this file's other tests, the keyword for items and what `out["elements"]` is called; match them.)

- [ ] **Step 2: Run it to see it fail**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/bim/tests/test_model_elements.py -k route`
Expected: FAIL, `KeyError: 'route'`

- [ ] **Step 3: Implement**

In `model_elements.py`:

```python
def _route_of(pset, ft: float) -> dict:
    """What a BIMForge_Route set says (M.8): route, based_on, and each
    difference's name, standard, actual (a length in the project's feet),
    unit and source."""
    out: dict = {}
    diffs = []
    for prop in pset.HasProperties:
        if prop.is_a("IfcPropertySingleValue") and prop.NominalValue is not None:
            key = {"Route": "route", "BasedOn": "based_on"}.get(prop.Name)
            if key:
                out[key] = prop.NominalValue.wrappedValue
        elif prop.is_a("IfcComplexProperty") and prop.UsageName == DIFFERENCE:
            d: dict = {"name": prop.Name}
            for part in prop.HasProperties:
                nv = getattr(part, "NominalValue", None)
                if nv is None:
                    continue
                if part.Name == "Source":
                    d["source"] = nv.wrappedValue
                    continue
                key = {"Standard": "standard", "Actual": "actual"}.get(part.Name)
                if key is None:
                    continue
                if nv.is_a() in ("IfcLabel", "IfcText"):
                    d[key] = nv.wrappedValue
                    continue
                unit = PARAMETER_UNITS.get(nv.is_a())
                value = float(nv.wrappedValue) * (ft if unit and unit[1] else 1.0)
                if not math.isfinite(value):
                    continue
                d[key] = round(value, 6)
                if unit:
                    d["unit"] = unit[0]
            diffs.append({k: d[k] for k in ("name", "standard", "actual",
                                            "unit", "source") if k in d})
    if diffs:
        out["differences"] = diffs
    return out
```

In `described`, inside the pset loop before the `!= DIMENSIONS` skip:

```python
        if pset is not None and pset.is_a("IfcPropertySet") \
                and pset.Name == ROUTE_PSET:
            out.update(_route_of(pset, ft))
            continue
```

Import `from bimforge.author.modified import DIFFERENCE, ROUTE_PSET` at the top of `described` (with the `DIMENSIONS` import). Add to the module docstring's key list:

```
- `route`, `based_on`, `differences` (M.8): the route the element was built
  by (standard, modified-by-value, modified-by-part, modified-by-section,
  bespoke), the class it is based on, and each value it changed:
  [{"name", "standard" (absent for an added row), "actual", "unit" (FT or
  RATIO, absent for text and other numbers), "source"}].
```

- [ ] **Step 4: Run the model-elements suite**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/bim/tests/test_model_elements.py`
Expected: all pass. Existing expected dicts for typed elements now also carry `route` and `based_on`: update those expectations (route "standard").

- [ ] **Step 5: Commit**

```bash
git add bimforge/bim/model_elements.py bimforge/bim/tests/test_model_elements.py
git commit -m "model-elements sends each element's route and differences (M.6, M.8)"
```

---

### Task 8: Docs, the whole suite, lint

**Files:**
- Modify: `ROADMAP.md` (M.8, M.9 rows), `README.md` (the `ignore: [tables]` line, L46), `CHANGELOG.md` (Unreleased), `bimforge/author/params_tracking.py` (docstring L16-17 if it ties `ignore` to modified elements)

- [ ] **Step 1: Correct the M.9 row's gate sentence and set both statuses**

M.9's last sentence becomes: "No check held an element to its packaged table, and `gate: {ignore: [...]}` only silences the unread-params check, so the gate gains `modified: warn | error | off` (default warn), listing each modified element's differences." Status cells: M.8 "B3 wall and 842/732SW barriers in #N; the other table families (D80, D84, D89, D90 headwall, B9) next"; M.9 "B3 in #N; the other table families next". (#N is filled in at PR time.)

- [ ] **Step 2: README line 46**

Keep `ignore: [tables]` as the way to silence a table-driven family's unread rows, and add one sentence: a project's tables that change a packaged value make the elements that read it `modified-by-value`, listed by `gate: {modified: warn}` (the default), failed by `error`.

- [ ] **Step 3: CHANGELOG (Unreleased, `### Added`)**

```markdown
- **Modified standards are recorded (M.8, M.9).** Every typed element
  carries `BIMForge_Route`: its `Route` (standard, modified-by-value,
  modified-by-part, modified-by-section or bespoke), the class it is
  `BasedOn` (its classification stays the standard's, so a Type 842 (MOD)
  is found as a Type 842), and each value it changed as an
  IfcComplexProperty (UsageName `Difference`) of `Standard`, `Actual` and
  `Source`. The differences come from what the spec says: a project's
  `tables_file` is compared with the packaged tables it names, or its
  family's own (the B3 wall's `caltrans/b3-retaining-wall`), and the build
  log lists every changed value; a barrier run's Mod dimensions (842,
  732SW) are modified by value, its own `profile` modified by section. A
  bespoke `bimforge.author` element may say what it is `based_on`.
  `gate: {modified: warn | error | off}` (default warn) lists, fails on,
  or ignores modified elements. `model-elements` sends `route`,
  `based_on` and `differences`. The shipped B3 examples' tables differ
  from the 2025 pack in 13 values, so their elements are modified by value.
```

And a line under the Unreleased "**For ProjectCommand and BidSheet.ai:**" paragraph (create one if it is not there): "`BIMForge_Route` holds `IfcComplexProperty` differences, the first complex properties BIMForge writes; a reader of property sets that expects single values must skip or read them."

- [ ] **Step 4: Run the whole suite**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider` (about 6 minutes)
Expected: all pass (2599+ passed, 11 skipped). Any expectation that pins a typed element's property sets now sees `BIMForge_Route`: update it to include the set, never drop the check.

- [ ] **Step 5: Lint against main**

Run: `ruff check bimforge` and compare with `git stash`-free main: `git show origin/main:<file> | ruff check --stdin-filename <file> -` for each changed file. Only I001, RUF100, F811 findings pre-existing on main are acceptable.

- [ ] **Step 6: Validate a modified B3 model**

Build the B3 example (`est-bim build bimforge/author/examples/caltrans-b3-retaining-wall.spec.yaml`, or `build_from_spec`), then `est-bim validate <ifc>`: 0 schema issues. The buildingSMART rules job runs in CI on the PR.

- [ ] **Step 7: Commit, push, open the PR**

```bash
git add ROADMAP.md README.md CHANGELOG.md bimforge/author/params_tracking.py
git commit -m "Docs: modified standards (M.8, M.9)"
git push -u origin feat/m8-m9-modified-standards
gh pr create --title "Modified standards recorded (M.8, M.9)" --body "..."
```

Fill #N in the ROADMAP rows with the PR number and push again.
