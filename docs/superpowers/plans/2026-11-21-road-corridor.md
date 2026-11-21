# Road Corridor Family (P.6) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `road-corridor` family that builds a road from an alignment, a profile, a typical section and the ground, and writes it as IFC4X3 road elements (IfcRoad > ROADSEGMENT > CARRIAGEWAY/SHOULDER, IfcCourse, IfcEarthworksCut/Fill) with standard quantity sets and a mass-haul table.

**Architecture:** A new package `bimforge/author/corridor/` with small units: `params` (validation, by-station reads), `section` (cross-section resolver, no geometry), `frame` (section coordinates to survey points), `loft` (a closed solid through one ring per station, written as IfcSectionedSolidHorizontal on IFC4X3), `ground` (plane or 3DEP), `earthwork` (cut/fill prismatoids) and `masshaul`. `families/road_corridor.py` drives them. Two small kernel additions: `Element.standard_qto` (written by `emit_ifc` beside `Qto_BaseQuantities`) and `StructureModel.mass_haul` (written by the registry as `outputs.masshaul`).

**Tech Stack:** Python 3.11+, ifcopenshell, numpy (ground sampling), pytest.

**Spec:** `docs/superpowers/specs/2026-11-21-road-corridor-design.md`.

**Conventions to keep:**
- Section coordinates: `u` positive to the LEFT of travel, `v` up from the profile grade line. Cross slopes negative down, outward from the crown.
- Survey points are `(northing, easting, elevation)`; `bimforge.author.sweep.to_model(origin, n, e, z)` is the only conversion to the model frame.
- Run tests from the worktree root: `python -m pytest <path> -q`.
- Commit messages end with the two attribution lines from the session (Co-Authored-By and Claude-Session).

---

## File structure

| File | Responsibility |
|---|---|
| Create `bimforge/author/corridor/__init__.py` | Package docstring only |
| Create `bimforge/author/corridor/params.py` | Parse/validate params; widths, cross slopes, walls by station; runs; station list |
| Create `bimforge/author/corridor/section.py` | `resolve()`: grade, course rings, subgrade, side slopes to daylight; `Section.earthwork_line()` |
| Create `bimforge/author/corridor/frame.py` | `survey_point()`, `densify()` |
| Create `bimforge/author/corridor/loft.py` | `StationLoft` |
| Create `bimforge/author/corridor/ground.py` | `PlaneGround`, `GridGround`, `footprint()`, `from_params()` |
| Create `bimforge/author/corridor/earthwork.py` | `strip()`: cut/fill prismatoids between two sections |
| Create `bimforge/author/corridor/masshaul.py` | `HaulRow`, `mass_haul()`, `to_csv()` |
| Create `bimforge/author/families/road_corridor.py` | The family `build()` |
| Modify `bimforge/author/model.py` | `Element.standard_qto`, `StructureModel.mass_haul` |
| Modify `bimforge/author/emit_ifc.py` | Write `standard_qto` sets |
| Modify `bimforge/author/families/registry.py` | Register the family; `masshaul` output key |
| Create `bimforge/author/examples/road-corridor.spec.yaml`, `road-corridor.paycodes.yaml` | The shipped example (joins conformance automatically) |
| Modify `bimforge/author/tests/fixtures/example_globalids.json` | Record the new example |
| Create tests under `bimforge/author/tests/`: `test_corridor_params.py`, `test_corridor_section.py`, `test_corridor_loft.py`, `test_corridor_ground.py`, `test_corridor_earthwork.py`, `test_corridor_masshaul.py`, `test_road_corridor.py` | Unit and integration tests |
| Modify `bimforge/author/tests/test_emit.py` | `standard_qto` tests |
| Modify `CHANGELOG.md` | Unreleased > Added |

---

### Task 1: `Element.standard_qto`, written by `emit_ifc`

**Files:**
- Modify: `bimforge/author/model.py` (Element dataclass, after `psets`)
- Modify: `bimforge/author/emit_ifc.py` (after the `Qto_BaseQuantities` block, around line 2316; helper beside `_QTY_ATTR`, around line 302)
- Test: `bimforge/author/tests/test_emit.py`

- [ ] **Step 1: Write the failing tests** (append to `bimforge/author/tests/test_emit.py`)

```python
def test_standard_qto_is_written_beside_the_base_set(tmp_path):
    import ifcopenshell
    import ifcopenshell.util.element

    m = _fixture_model()
    m.element("PS-1 footing").standard_qto = {"Qto_FootingBaseQuantities": {
        "Length": ("length", 4.0), "Width": ("length", 4.0),
        "GrossVolume": ("volume", 32.0)}}
    out = tmp_path / "std.ifc"
    emit_ifc(m, str(out), PC)
    f = ifcopenshell.open(str(out))
    el = next(e for e in f.by_type("IfcFooting") if e.Name == "PS-1 footing")
    qtos = ifcopenshell.util.element.get_psets(el, qtos_only=True)
    k = m.ctx.ft_to_m
    assert {"Qto_BaseQuantities", "Qto_FootingBaseQuantities"} <= set(qtos)
    std = qtos["Qto_FootingBaseQuantities"]
    assert std["Length"] == pytest.approx(4.0 * k)
    assert std["GrossVolume"] == pytest.approx(32.0 * k ** 3)


def test_standard_qto_refuses_an_unknown_measure(tmp_path):
    m = _fixture_model()
    m.element("PS-1 footing").standard_qto = {
        "Qto_FootingBaseQuantities": {"Length": ("furlong", 1.0)}}
    with pytest.raises(ValueError, match="furlong"):
        emit_ifc(m, str(tmp_path / "bad.ifc"), PC)
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_emit.py -q -k standard_qto`
Expected: FAIL. The emitted file has no `Qto_FootingBaseQuantities`, and the second test raises no error.

- [ ] **Step 3: Add the field** in `bimforge/author/model.py`, directly after the `psets` field of `Element`:

```python
    #: The class's standard quantity set (roadmap M.17), {set name:
    #: {quantity name: (measure, value)}}, measure one of "length", "area",
    #: "volume", values in the feet domain: emit_ifc writes each as an
    #: IfcElementQuantity beside Qto_BaseQuantities, which consumers read
    #: until M.17 retires it ({"Qto_CourseBaseQuantities": {"Thickness":
    #: ("length", 0.4)}}).
    standard_qto: dict = field(default_factory=dict)
```

- [ ] **Step 4: Write the sets** in `bimforge/author/emit_ifc.py`. Beside `_QTY_ATTR` (around line 302) add:

```python
#: Element.standard_qto measure -> (IfcQuantity entity, power of ft_to_m)
_STANDARD_MEASURES = {"length": ("IfcQuantityLength", 1),
                      "area": ("IfcQuantityArea", 2),
                      "volume": ("IfcQuantityVolume", 3)}


def _standard_quantity(f, name: str, measure: str, value: float,
                       ft_to_m: float):
    """One quantity of an Element.standard_qto set, converted to metres."""
    if measure not in _STANDARD_MEASURES:
        raise ValueError(f"standard quantity {name}: measure {measure!r} is "
                         f"not one of {sorted(_STANDARD_MEASURES)}")
    ent, power = _STANDARD_MEASURES[measure]
    q = f.create_entity(ent, Name=name)
    setattr(q, _QTY_ATTR[ent], float(value) * ft_to_m ** power)
    return q
```

Then directly after the `if el.quantities:` block that writes `Qto_BaseQuantities` (it ends with `qto.Quantities = tuple(quantities)`), at the same indentation as that `if`:

```python
            # the class's standard set (roadmap M.17), beside the base set
            for qset, values in (el.standard_qto or {}).items():
                sq = run("pset.add_qto", f, product=product, name=qset)
                sq.Quantities = tuple(
                    _standard_quantity(f, qname, measure, value, ctx.ft_to_m)
                    for qname, (measure, value) in values.items())
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_emit.py -q`
Expected: PASS (all tests in the file).

- [ ] **Step 6: Make sure no shipped example changed**

Run: `python -m pytest bimforge/author/tests/test_example_globalids.py bimforge/author/tests/test_ifc4_golden.py -q`
Expected: PASS. No shipped family sets `standard_qto`, so nothing is added to their files.

- [ ] **Step 7: Commit**

```bash
git add bimforge/author/model.py bimforge/author/emit_ifc.py bimforge/author/tests/test_emit.py
git commit -m "Element.standard_qto: a class's standard quantity set, written beside Qto_BaseQuantities (M.17)"
```

---

### Task 2: corridor params

**Files:**
- Create: `bimforge/author/corridor/__init__.py`
- Create: `bimforge/author/corridor/params.py`
- Test: `bimforge/author/tests/test_corridor_params.py`

- [ ] **Step 1: Create the package**

`bimforge/author/corridor/__init__.py`:

```python
"""The road corridor (roadmap P.6): typical sections resolved by station,
lofted into pavement courses and cut and fill to daylight.

Spec: docs/superpowers/specs/2026-11-21-road-corridor-design.md. The family
that drives it is bimforge.author.families.road_corridor.
"""
```

- [ ] **Step 2: Write the failing tests** in `bimforge/author/tests/test_corridor_params.py`

```python
"""road-corridor params: validation and by-station reads (P.6)."""
import copy

import pytest

from bimforge.author.corridor.params import NORMAL_CROWN, parse

BASE = {"section": {
    "components": [{"name": "lane", "kind": "carriageway", "width": 12.0},
                   {"name": "shoulder", "kind": "shoulder", "width": 5.0,
                    "slope": -0.05}],
    "courses": [{"name": "HMA", "type": "PAVEMENT", "thickness": 0.4},
                {"name": "AB", "type": "CORE", "thickness": 1.0}],
    "side_slopes": {"cut": {"ratio": 2.0, "ditch": {"width": 4.0, "depth": 1.5}},
                    "fill": {"ratio": 2.0}, "daylight_limit_ft": 150}}}


def params(**over):
    p = copy.deepcopy(BASE)
    p.update(over)
    return p


def test_defaults_are_a_normal_crown_and_25_ft_sections():
    c = parse(params(), 1000.0, 2000.0)
    assert c.cross_slope("L", 1500.0) == NORMAL_CROWN == c.cross_slope("R", 1500.0)
    assert (c.interval, c.band, c.shrink, c.swell) == (25.0, 100.0, 0.0, 0.0)
    assert c.depth() == pytest.approx(1.4)


def test_superelevation_interpolates_each_side():
    c = parse(params(superelevation=[[1000, -0.02, -0.02], [1400, 0.06, -0.06]]),
              1000.0, 2000.0)
    assert c.cross_slope("L", 1200.0) == pytest.approx(0.02)
    assert c.cross_slope("R", 1200.0) == pytest.approx(-0.04)
    assert c.cross_slope("L", 1900.0) == pytest.approx(0.06)


def test_a_width_table_tapers_one_side():
    c = parse(params(widths=[{"component": "shoulder", "side": "R",
                              "at": [[1200, 5.0], [1300, 10.0]]}]), 1000.0, 2000.0)
    shoulder = c.components[1]
    assert c.width(shoulder, "R", 1250.0) == pytest.approx(7.5)
    assert c.width(shoulder, "L", 1250.0) == 5.0
    assert c.max_half_width() == 22.0


def test_structure_gaps_split_the_runs():
    c = parse(params(gaps=[{"from": 1400, "to": 1500, "kind": "structure"}]),
              1000.0, 2000.0)
    assert c.runs() == [(1000.0, 1400.0), (1500.0, 2000.0)]


def test_stations_take_every_interval_band_table_and_wall_end():
    c = parse(params(gaps=[{"from": 1110, "to": 1130, "kind": "wall", "side": "L",
                            "offset": 30}],
                     stations={"interval": 50, "band": 100}), 1000.0, 2000.0)
    assert c.stations(1000.0, 1200.0, extra=[1075.5]) == [
        1000.0, 1050.0, 1075.5, 1100.0, 1109.0, 1110.0, 1130.0, 1131.0,
        1150.0, 1200.0]
    assert c.wall("L", 1120.0).offset == 30.0
    assert c.wall("R", 1120.0) is None


@pytest.mark.parametrize("over, match", [
    ({"gaps": [{"from": 1100, "to": 1300, "kind": "structure"},
               {"from": 1200, "to": 1400, "kind": "structure"}]}, "overlaps"),
    ({"gaps": [{"from": 1900, "to": 2100, "kind": "structure"}]}, "off the alignment"),
    ({"gaps": [{"from": 1100, "to": 1200, "kind": "wall", "offset": 30}]}, "side L or R"),
    ({"superelevation": [[900, -0.02, -0.02]]}, "off the alignment"),
    ({"superelevation": [[1000, -0.02]]}, r"\[station, left, right\]"),
    ({"widths": [{"component": "shoulder", "side": "R",
                  "at": [[1200, 5.0], [1300, 0.0]]}]}, "must be positive"),
    ({"widths": [{"component": "verge", "side": "R", "at": [[1200, 5.0]]}]},
     "no component named"),
    ({"mass_haul": {"shrink": 1.0}}, "below 1"),
    ({"stations": {"interval": 0}}, "must be positive"),
])
def test_bad_params_are_refused(over, match):
    with pytest.raises(ValueError, match=match):
        parse(params(**over), 1000.0, 2000.0)


def test_a_course_needs_a_course_type():
    p = params()
    p["section"]["courses"][0]["type"] = "BASE"
    with pytest.raises(ValueError, match="BASE"):
        parse(p, 1000.0, 2000.0)


def test_a_corridor_needs_components_and_courses():
    p = params()
    p["section"]["courses"] = []
    with pytest.raises(ValueError, match="at least one course"):
        parse(p, 1000.0, 2000.0)
```

- [ ] **Step 3: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_corridor_params.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'bimforge.author.corridor.params'`.

- [ ] **Step 4: Write `bimforge/author/corridor/params.py`**

```python
"""road-corridor parameters (roadmap P.6): a spec's typical section, width
transitions, superelevation, gaps, stationing and mass-haul factors,
validated once and read by station.

Sides are "L" and "R" of travel. A cross slope is measured outward from the
crown, negative down. Offsets and stations are feet.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from bimforge.author.alignment import sta

#: component kind -> IfcRoadPartTypeEnum
PART_TYPES = {"carriageway": "CARRIAGEWAY", "shoulder": "SHOULDER",
              "median": "CENTRALRESERVE"}
#: the IfcCourseTypeEnum values a course may take
COURSE_TYPES = ("ARMOUR", "BALLASTBED", "CORE", "FILTER", "PAVEMENT",
                "PROTECTION")
SIDES = ("L", "R")
#: both sides' cross slope with no superelevation table
NORMAL_CROWN = -0.02
#: sections are cut this far outside each wall gap, so the side slope turns
#: into the wall within it, feet
WALL_TRANSITION_FT = 1.0
_EPS = 1e-9


def interp(table: list, s: float) -> float:
    """Linear in station between [(station, value)] rows; the end value
    holds outside them."""
    if s <= table[0][0]:
        return table[0][1]
    for (s0, v0), (s1, v1) in zip(table, table[1:]):
        if s <= s1:
            return v0 + (v1 - v0) * (s - s0) / (s1 - s0)
    return table[-1][1]


@dataclass(frozen=True)
class Component:
    name: str
    kind: str                      # a PART_TYPES key
    width: float
    slope: float | None = None     # its own cross slope; None: the side's


@dataclass(frozen=True)
class Course:
    name: str
    type: str                      # a COURSE_TYPES value
    thickness: float


@dataclass(frozen=True)
class Ditch:
    width: float
    depth: float


@dataclass(frozen=True)
class Slopes:
    cut_ratio: float               # horizontal per vertical
    fill_ratio: float
    ditch: Ditch | None
    daylight_limit: float          # horizontal feet from the hinge


@dataclass(frozen=True)
class Gap:
    start: float
    end: float
    kind: str                      # "structure" or "wall"
    side: str | None = None        # a wall's side
    offset: float | None = None    # a wall's face, feet from the centreline


@dataclass(frozen=True)
class Corridor:
    s_start: float
    s_end: float
    components: tuple
    courses: tuple
    slopes: Slopes
    widths: dict                   # (component name, side) -> [(s, width)]
    superelevation: tuple          # ((s, left, right), ...)
    gaps: tuple                    # by start station
    interval: float
    band: float
    shrink: float
    swell: float

    def width(self, comp: Component, side: str, s: float) -> float:
        table = self.widths.get((comp.name, side))
        return interp(table, s) if table else comp.width

    def cross_slope(self, side: str, s: float) -> float:
        if not self.superelevation:
            return NORMAL_CROWN
        col = 1 if side == "L" else 2
        return interp([(r[0], r[col]) for r in self.superelevation], s)

    def depth(self) -> float:
        """Every course's thickness: finished grade to subgrade."""
        return sum(c.thickness for c in self.courses)

    def wall(self, side: str, s: float) -> Gap | None:
        for g in self.gaps:
            if (g.kind == "wall" and g.side == side
                    and g.start - _EPS <= s <= g.end + _EPS):
                return g
        return None

    def max_half_width(self) -> float:
        """The widest a side's components get anywhere, feet."""
        return max(sum(max([comp.width] + [w for _s, w in
                                            self.widths.get((comp.name, side), ())])
                       for comp in self.components)
                   for side in SIDES)

    def runs(self) -> list:
        """[(s0, s1)]: the alignment less its structure gaps."""
        out, s = [], self.s_start
        for g in self.gaps:
            if g.kind != "structure":
                continue
            if g.start - s > _EPS:
                out.append((s, g.start))
            s = g.end
        if self.s_end - s > _EPS:
            out.append((s, self.s_end))
        return out

    def stations(self, s0: float, s1: float, extra=()) -> list:
        """Where to cut sections on [s0, s1]: every `interval` and `band`
        from the alignment's start, every table and gap station, 1 ft
        outside each wall gap, and `extra` (the geometry's own points)."""
        cuts = {s0, s1}
        for step in (self.interval, self.band):
            k = math.ceil((s0 - self.s_start) / step - _EPS)
            while self.s_start + k * step < s1 - _EPS:
                cuts.add(self.s_start + k * step)
                k += 1
        cuts.update(s for table in self.widths.values() for s, _w in table)
        cuts.update(r[0] for r in self.superelevation)
        for g in self.gaps:
            cuts.update((g.start, g.end))
            if g.kind == "wall":
                cuts.update((g.start - WALL_TRANSITION_FT,
                             g.end + WALL_TRANSITION_FT))
        cuts.update(extra)
        out = []
        for s in sorted(x for x in cuts if s0 - _EPS <= x <= s1 + _EPS):
            if not out or s - out[-1] > 1e-6:
                out.append(min(max(s, s0), s1))
        out[-1] = s1
        return out


def _num(value, where: str, positive: bool = True) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{where}: expected a number, got {value!r}") from None
    if positive and not x > 0.0:
        raise ValueError(f"{where}: must be positive, got {x:g}")
    return x


def _on_alignment(s, where: str, s_start: float, s_end: float) -> float:
    s = _num(s, where, positive=False)
    if not s_start - _EPS <= s <= s_end + _EPS:
        raise ValueError(f"{where}: station {sta(s)} is off the alignment "
                         f"({sta(s_start)} to {sta(s_end)})")
    return s


def _ascending(stations: list, where: str) -> None:
    if any(b <= a for a, b in zip(stations, stations[1:])):
        raise ValueError(f"{where}: stations must be strictly ascending")


def _components(sec: dict) -> list:
    out = []
    for i, c in enumerate(sec.get("components") or []):
        where = f"section.components[{i}]"
        kind = str(c.get("kind", "")).lower()
        if kind not in PART_TYPES:
            raise ValueError(f"{where}: kind {c.get('kind')!r} is not one of "
                             f"{sorted(PART_TYPES)}")
        slope = c.get("slope")
        out.append(Component(
            str(c["name"]), kind, _num(c.get("width"), f"{where}.width"),
            None if slope is None else _num(slope, f"{where}.slope",
                                            positive=False)))
    if not out:
        raise ValueError("section.components: a corridor needs at least one "
                         "component")
    names = [c.name for c in out]
    if len(set(names)) != len(names):
        raise ValueError("section.components: names must be distinct")
    return out


def _courses(sec: dict) -> list:
    out = []
    for i, c in enumerate(sec.get("courses") or []):
        where = f"section.courses[{i}]"
        ctype = str(c.get("type", "")).upper()
        if ctype not in COURSE_TYPES:
            raise ValueError(f"{where}: type {c.get('type')!r} is not one of "
                             f"{COURSE_TYPES}")
        out.append(Course(str(c["name"]), ctype,
                          _num(c.get("thickness"), f"{where}.thickness")))
    if not out:
        raise ValueError("section.courses: a corridor needs at least one course")
    return out


def _slopes(sec: dict) -> Slopes:
    ss = sec.get("side_slopes") or {}
    cut, fill = ss.get("cut") or {}, ss.get("fill") or {}
    ditch = None
    if cut.get("ditch"):
        d = cut["ditch"]
        width = _num(d.get("width"), "side_slopes.cut.ditch.width", positive=False)
        if width < 0.0:
            raise ValueError("side_slopes.cut.ditch.width: must not be negative")
        ditch = Ditch(width, _num(d.get("depth"), "side_slopes.cut.ditch.depth"))
    return Slopes(_num(cut.get("ratio", 2.0), "side_slopes.cut.ratio"),
                  _num(fill.get("ratio", 2.0), "side_slopes.fill.ratio"),
                  ditch,
                  _num(ss.get("daylight_limit_ft", 150.0),
                       "side_slopes.daylight_limit_ft"))


def _widths(params: dict, names: list, s_start: float, s_end: float) -> dict:
    out = {}
    for i, w in enumerate(params.get("widths") or []):
        where = f"widths[{i}]"
        if w.get("component") not in names:
            raise ValueError(f"{where}: no component named {w.get('component')!r}")
        side = str(w.get("side", "")).upper()
        if side not in SIDES:
            raise ValueError(f"{where}: side must be L or R")
        rows = [(_on_alignment(s, where, s_start, s_end),
                 _num(v, f"{where} width", positive=False))
                for s, v in w.get("at") or []]
        if not rows:
            raise ValueError(f"{where}: 'at' needs [station, width] rows")
        _ascending([s for s, _v in rows], where)
        for s, v in rows:
            if v <= 0.0:
                raise ValueError(f"{where}: width {v:g} at station {sta(s)} "
                                 f"must be positive")
        if (w["component"], side) in out:
            raise ValueError(f"{where}: a second table for {w['component']} {side}")
        out[w["component"], side] = rows
    return out


def _superelevation(params: dict, s_start: float, s_end: float) -> list:
    out = []
    for i, r in enumerate(params.get("superelevation") or []):
        where = f"superelevation[{i}]"
        if len(r) != 3:
            raise ValueError(f"{where}: rows are [station, left, right]")
        out.append((_on_alignment(r[0], where, s_start, s_end),
                    _num(r[1], where, positive=False),
                    _num(r[2], where, positive=False)))
    _ascending([r[0] for r in out], "superelevation")
    return out


def _gaps(params: dict, s_start: float, s_end: float) -> list:
    out = []
    for i, g in enumerate(params.get("gaps") or []):
        where = f"gaps[{i}]"
        a = _on_alignment(g.get("from"), where, s_start, s_end)
        b = _on_alignment(g.get("to"), where, s_start, s_end)
        if b <= a:
            raise ValueError(f"{where}: 'to' must be past 'from'")
        kind = str(g.get("kind", "")).lower()
        if kind == "structure":
            out.append(Gap(a, b, kind))
        elif kind == "wall":
            side = str(g.get("side", "")).upper()
            if side not in SIDES:
                raise ValueError(f"{where}: a wall gap needs side L or R")
            out.append(Gap(a, b, kind, side, _num(g.get("offset"), f"{where}.offset")))
        else:
            raise ValueError(f"{where}: kind {g.get('kind')!r} is not "
                             f"'structure' or 'wall'")
    out.sort(key=lambda g: g.start)
    for p, q in zip(out, out[1:]):
        if q.start < p.end - _EPS:
            raise ValueError(f"gaps: {sta(p.start)} to {sta(p.end)} overlaps "
                             f"{sta(q.start)} to {sta(q.end)}")
    return out


def parse(params: dict, s_start: float, s_end: float) -> Corridor:
    """The corridor `params` describe on an alignment from `s_start` to
    `s_end`; ValueError names the first field that is wrong."""
    sec = params.get("section") or {}
    comps = _components(sec)
    st = params.get("stations") or {}
    mh = params.get("mass_haul") or {}
    shrink = _num(mh.get("shrink", 0.0), "mass_haul.shrink", positive=False)
    swell = _num(mh.get("swell", 0.0), "mass_haul.swell", positive=False)
    if not 0.0 <= shrink < 1.0:
        raise ValueError("mass_haul.shrink: must be at least 0 and below 1")
    if swell < 0.0:
        raise ValueError("mass_haul.swell: must not be negative")
    return Corridor(
        s_start=float(s_start), s_end=float(s_end),
        components=tuple(comps), courses=tuple(_courses(sec)),
        slopes=_slopes(sec),
        widths=_widths(params, [c.name for c in comps], s_start, s_end),
        superelevation=tuple(_superelevation(params, s_start, s_end)),
        gaps=tuple(_gaps(params, s_start, s_end)),
        interval=_num(st.get("interval", 25.0), "stations.interval"),
        band=_num(st.get("band", 100.0), "stations.band"),
        shrink=shrink, swell=swell)
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_corridor_params.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add bimforge/author/corridor/__init__.py bimforge/author/corridor/params.py bimforge/author/tests/test_corridor_params.py
git commit -m "road corridor: params, validated and read by station (P.6)"
```

---

### Task 3: the section resolver

**Files:**
- Create: `bimforge/author/corridor/section.py`
- Test: `bimforge/author/tests/test_corridor_section.py`

Hand-worked numbers used below (lane 12 ft, shoulder 5 ft at -0.05, courses 0.4 + 1.0 ft, normal crown -0.02):
- Left grade: (0, 0), (12, -0.24), (17, -0.49). Hinge: (17, -1.89).
- Fill onto level ground at v = -5 (2:1): daylight at u = 17 + 2 × 3.11 = 23.22.
- Cut into level ground at v = +3, ditch 4 ft wide and 1.5 ft deep, 2:1: (20, -3.39), (24, -3.39), then up at 1:2 to v = 3, which is h = 12.78, so u = 36.78.

- [ ] **Step 1: Write the failing tests** in `bimforge/author/tests/test_corridor_section.py`

```python
"""road-corridor section resolver: hand-worked sections (P.6)."""
import copy

import pytest

from bimforge.author.corridor.params import parse
from bimforge.author.corridor.section import SIDE_SAMPLES, resolve

BASE = {"section": {
    "components": [{"name": "lane", "kind": "carriageway", "width": 12.0},
                   {"name": "shoulder", "kind": "shoulder", "width": 5.0,
                    "slope": -0.05}],
    "courses": [{"name": "HMA", "type": "PAVEMENT", "thickness": 0.4},
                {"name": "AB", "type": "CORE", "thickness": 1.0}],
    "side_slopes": {"cut": {"ratio": 2.0, "ditch": {"width": 4.0, "depth": 1.5}},
                    "fill": {"ratio": 2.0}, "daylight_limit_ft": 150}}}


def corridor(**over):
    p = copy.deepcopy(BASE)
    p.update(over)
    return parse(p, 0.0, 2000.0)


def level(h):
    """Level ground h ft above the profile grade line."""
    return lambda s, u, v: h - v


def flat(points):
    return [c for p in points for c in p]


def test_normal_crown_grade_and_hinges():
    sec = resolve(corridor(), 500.0, level(-5.0))
    assert flat(sec.grade["L"]) == pytest.approx(flat([(0, 0), (12, -0.24), (17, -0.49)]))
    assert flat(sec.grade["R"]) == pytest.approx(flat([(0, 0), (-12, -0.24), (-17, -0.49)]))
    assert flat(sec.subgrade["L"][-1:]) == pytest.approx([17.0, -1.89])


def test_full_super_tilts_the_lanes_and_keeps_the_shoulder_slope():
    sec = resolve(corridor(superelevation=[[0, 0.06, -0.06], [2000, 0.06, -0.06]]),
                  500.0, level(-5.0))
    assert flat(sec.grade["L"]) == pytest.approx(flat([(0, 0), (12, 0.72), (17, 0.47)]))
    assert flat(sec.grade["R"]) == pytest.approx(flat([(0, 0), (-12, -0.72), (-17, -0.97)]))


def test_course_rings_split_by_component_and_side():
    sec = resolve(corridor(), 500.0, level(-5.0))
    assert flat(sec.courses[0, 0, "L"]) == pytest.approx(
        flat([(0, 0), (12, -0.24), (12, -0.64), (0, -0.4)]))
    assert flat(sec.courses[1, 1, "R"]) == pytest.approx(
        flat([(-12, -0.64), (-17, -0.89), (-17, -1.89), (-12, -1.64)]))


def test_fill_daylights_at_the_fill_ratio():
    sec = resolve(corridor(), 500.0, level(-5.0))
    side = sec.sides["L"]
    assert side.kind == "fill"
    assert flat(side.line) == pytest.approx(flat([(17, -1.89), (23.22, -5.0)]))
    assert flat(sec.sides["R"].line[-1:]) == pytest.approx([-23.22, -5.0])


def test_cut_runs_through_the_ditch_then_up_the_backslope():
    sec = resolve(corridor(), 500.0, level(3.0))
    side = sec.sides["L"]
    assert side.kind == "cut"
    assert flat(side.line) == pytest.approx(
        flat([(17, -1.89), (20, -3.39), (24, -3.39), (36.78, 3.0)]))


def test_a_width_taper_moves_the_hinge():
    sec = resolve(corridor(widths=[{"component": "shoulder", "side": "R",
                                    "at": [[1200, 5.0], [1300, 10.0]]}]),
                  1250.0, level(-5.0))
    assert flat(sec.grade["R"][-1:]) == pytest.approx([-19.5, -0.615])


def test_a_wall_gap_runs_level_at_subgrade_to_the_wall():
    sec = resolve(corridor(gaps=[{"from": 400, "to": 600, "kind": "wall",
                                  "side": "L", "offset": 30.0}]), 500.0, level(-5.0))
    assert sec.sides["L"].kind == "wall"
    assert flat(sec.sides["L"].line) == pytest.approx(flat([(17, -1.89), (30, -1.89)]))
    assert sec.sides["R"].kind == "fill"


def test_a_wall_inside_the_hinge_is_refused():
    c = corridor(gaps=[{"from": 400, "to": 600, "kind": "wall", "side": "L",
                        "offset": 10.0}])
    with pytest.raises(ValueError, match="inside the hinge"):
        resolve(c, 500.0, level(-5.0))


def test_a_slope_that_finds_no_ground_names_the_station_and_side():
    with pytest.raises(ValueError, match=r"5\+00.*L fill slope finds no ground within 150"):
        resolve(corridor(), 500.0, level(-500.0))


def test_the_earthwork_line_has_one_count_in_cut_and_in_fill():
    c = corridor()
    a, b = resolve(c, 500.0, level(-5.0)), resolve(c, 525.0, level(3.0))
    n = 2 * SIDE_SAMPLES - 1 + 2 * len(c.components)
    assert len(a.earthwork_line()) == len(b.earthwork_line()) == n
    line = a.earthwork_line()
    assert line[0] == pytest.approx((23.22, -5.0))
    assert line[-1] == pytest.approx((-23.22, -5.0))
    assert a.width() == pytest.approx(46.44)
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_corridor_section.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'bimforge.author.corridor.section'`.

- [ ] **Step 3: Write `bimforge/author/corridor/section.py`**

```python
"""The road corridor's cross-section at a station (roadmap P.6): finished
grade, course rings, subgrade and side slopes to daylight, in section
coordinates (u left of travel, v up from the profile grade line).

No geometry and no IFC. The ground comes in as `ground_dz(s, u, v)`: how far
the ground lies above the section point (u, v) at station s, so a test can
hand in level ground and the family hands in the real thing.
"""
from __future__ import annotations

from dataclasses import dataclass

from bimforge.author.alignment import sta
from bimforge.author.corridor.params import SIDES

#: points on each side's slope line, hinge and daylight included: fixed, so
#: every station's earthwork line has the same count and lofts point to point
SIDE_SAMPLES = 12
#: the daylight search's step along a slope, horizontal feet
_SCAN_FT = 1.0


@dataclass(frozen=True)
class Side:
    kind: str           # "cut", "fill" or "wall"
    line: list          # [(u, v)] from the hinge out to daylight or the wall


@dataclass(frozen=True)
class Section:
    s: float
    grade: dict         # side -> [(u, v)], crown outward, one per component edge
    courses: dict       # (course index, component index, side) -> 4-point ring
    subgrade: dict      # side -> [(u, v)], crown outward; its last is the hinge
    sides: dict         # side -> Side

    def earthwork_line(self) -> list:
        """Left daylight to right daylight across the subgrade, with the same
        number of points at every station."""
        left = list(reversed(_samples(self.sides["L"].line)))
        under_left = list(reversed(self.subgrade["L"][:-1]))
        under_right = self.subgrade["R"][1:]
        right = _samples(self.sides["R"].line)[1:]
        return left + under_left + under_right + right

    def width(self) -> float:
        """Daylight to daylight, feet."""
        return abs(self.sides["L"].line[-1][0] - self.sides["R"].line[-1][0])


def _samples(line: list) -> list:
    """`line` with its last segment cut evenly to SIDE_SAMPLES points."""
    extra = SIDE_SAMPLES - len(line)
    (u0, v0), (u1, v1) = line[-2], line[-1]
    mid = [(u0 + (u1 - u0) * i / (extra + 1), v0 + (v1 - v0) * i / (extra + 1))
           for i in range(1, extra + 1)]
    return list(line[:-1]) + mid + [line[-1]]


def _daylight(s, start, sign, rise, ground_dz, reach, cut):
    """Where the line from `start`, `sign` outward and `rise` ft up per ft
    out, meets the ground within `reach` horizontal ft; None if it does
    not."""
    su, sv = start

    def hit(h):
        dz = ground_dz(s, su + sign * h, sv + rise * h)
        return dz <= 0.0 if cut else dz >= 0.0

    if hit(0.0):
        return start
    if reach <= 0.0:
        return None
    lo, h = 0.0, min(_SCAN_FT, reach)
    while not hit(h):
        if h >= reach:
            return None
        lo, h = h, min(h + _SCAN_FT, reach)
    hi = h
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if hit(mid):
            hi = mid
        else:
            lo = mid
    return (su + sign * hi, sv + rise * hi)


def _side(c, s: float, side: str, sign: float, hinge: tuple, ground_dz) -> Side:
    hu, hv = hinge
    wall = c.wall(side, s)
    if wall is not None:
        if wall.offset < abs(hu):
            raise ValueError(
                f"station {sta(s)}: the {side} wall at offset {wall.offset:g} ft "
                f"is inside the hinge at {abs(hu):g} ft")
        return Side("wall", [hinge, (sign * wall.offset, hv)])
    sl = c.slopes
    if ground_dz(s, hu, hv) > 0.0:
        kind, pts = "cut", [hinge]
        if sl.ditch is not None:
            p1 = (hu + sign * sl.cut_ratio * sl.ditch.depth, hv - sl.ditch.depth)
            pts += [p1, (p1[0] + sign * sl.ditch.width, p1[1])]
        rise = 1.0 / sl.cut_ratio
    else:
        kind, pts, rise = "fill", [hinge], -1.0 / sl.fill_ratio
    used = abs(pts[-1][0] - hu)
    day = _daylight(s, pts[-1], sign, rise, ground_dz,
                    sl.daylight_limit - used, cut=(kind == "cut"))
    if day is None:
        raise ValueError(
            f"station {sta(s)}: the {side} {kind} slope finds no ground within "
            f"{sl.daylight_limit:g} ft of the hinge")
    return Side(kind, pts + [day])


def resolve(c, s: float, ground_dz) -> Section:
    """The section of corridor `c` at station `s` (params.Corridor)."""
    depth = c.depth()
    grade, subgrade, courses, sides = {}, {}, {}, {}
    for side in SIDES:
        sign = 1.0 if side == "L" else -1.0
        u = v = 0.0
        pts = [(0.0, 0.0)]
        for comp in c.components:
            w = c.width(comp, side, s)
            slope = (comp.slope if comp.slope is not None
                     else c.cross_slope(side, s))
            u += sign * w
            v += w * slope
            pts.append((u, v))
        grade[side] = pts
        subgrade[side] = [(pu, pv - depth) for pu, pv in pts]
        above = 0.0
        for k, course in enumerate(c.courses):
            t = course.thickness
            for j in range(len(c.components)):
                (u0, v0), (u1, v1) = pts[j], pts[j + 1]
                courses[k, j, side] = [(u0, v0 - above), (u1, v1 - above),
                                       (u1, v1 - above - t), (u0, v0 - above - t)]
            above += t
        sides[side] = _side(c, s, side, sign, subgrade[side][-1], ground_dz)
    return Section(s, grade, courses, subgrade, sides)
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_corridor_section.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bimforge/author/corridor/section.py bimforge/author/tests/test_corridor_section.py
git commit -m "road corridor: the section resolver, grade to daylight (P.6)"
```

---

### Task 4: the frame and `StationLoft`

**Files:**
- Create: `bimforge/author/corridor/frame.py`
- Create: `bimforge/author/corridor/loft.py`
- Test: `bimforge/author/tests/test_corridor_loft.py`

- [ ] **Step 1: Write the failing tests** in `bimforge/author/tests/test_corridor_loft.py`

```python
"""StationLoft and the corridor frame (P.6)."""
import pytest

from bimforge.author.alignment import Alignment, Profile
from bimforge.author.corridor.frame import densify, survey_point
from bimforge.author.corridor.loft import StationLoft
from bimforge.author.primitives import exact_of
from bimforge.author.sweep import MAX_ARC_STEP_RAD

POB = {"station": 0.0, "northing": 0.0, "easting": 0.0}
RECT = [(5.0, 0.0), (-5.0, 0.0), (-5.0, -1.0), (5.0, -1.0)]


def line(length=100.0):
    return Alignment(POB, [{"kind": "tangent", "bearing": "N 0-0-0 E",
                            "length": length}], name="T")


def curve():
    """10 ft tangent, a 100 ft right curve of radius 500, 10 ft tangent."""
    return Alignment(POB, [
        {"kind": "tangent", "bearing": "N 0-0-0 E", "length": 10.0},
        {"kind": "curve", "delta": "11-27-33", "radius": 500.0, "turn": "R",
         "length": 100.0},
        {"kind": "tangent", "bearing": "N 11-27-33 E", "length": 10.0}], name="C")


def level(elev=100.0, length=120.0, grade_pct=0.0):
    return Profile([{"bvc_station": 0.0, "bvc_elev": elev, "g_in_pct": grade_pct,
                     "g_out_pct": grade_pct, "length_ft": length,
                     "evc_station": length,
                     "evc_elev": elev + grade_pct / 100.0 * length}])


def test_a_section_point_sits_left_and_below_on_a_level_tangent():
    assert survey_point(line(), level(), 50.0, 5.0, -1.0) == pytest.approx(
        (50.0, -5.0, 99.0))


def test_densify_keeps_chords_on_the_curve():
    al = curve()
    got = densify(al, level(), [0.0, 10.0, 110.0, 120.0])
    steps = [b - a for a, b in zip(got, got[1:])]
    assert got[0] == 0.0 and got[-1] == 120.0
    assert max(steps[1:-1]) <= MAX_ARC_STEP_RAD * 500.0 + 1e-9
    assert len(got) > 4


def test_a_straight_loft_is_its_prism():
    lf = StationLoft("slab", line(), level(), None, [0.0, 50.0, 100.0], [RECT] * 3)
    assert lf.volume_cf == pytest.approx(1000.0, rel=1e-9)
    assert lf.average_end_area_cf == pytest.approx(1000.0, rel=1e-9)
    assert lf.mean_width_ft == pytest.approx(10.0)
    assert lf.length_ft == 100.0


def test_a_curved_loft_agrees_with_its_curvature_corrected_end_areas():
    al, prof = curve(), level()
    ring = [(12.0, 0.0), (2.0, 0.0), (2.0, -1.0), (12.0, -1.0)]   # left of the line
    ss = densify(al, prof, [0.0, 10.0, 110.0, 120.0])
    lf = StationLoft("outer", al, prof, None, ss, [ring] * len(ss))
    assert lf.volume_cf > 1210.0            # the outside of a right curve is longer
    assert lf.volume_cf == pytest.approx(lf.average_end_area_cf, rel=1e-3)


def test_grade_lengthens_the_loft():
    lf = StationLoft("slab", line(), level(grade_pct=6.0), None, [0.0, 100.0], [RECT] * 2)
    assert lf.average_end_area_cf == pytest.approx(1000.0 * (1 + 0.06 ** 2) ** 0.5)
    assert lf.volume_cf == pytest.approx(lf.average_end_area_cf, rel=1e-6)


def test_its_exact_form_is_one_section_per_station():
    ss = [0.0, 50.0, 100.0]
    lf = StationLoft("slab", line(), level(), None, ss, [RECT] * 3, ifc="IfcCourse")
    d = lf.body_solids()[0]
    ex = exact_of(d)
    assert ex is not None and ex["kind"] == "sectioned"
    assert [sec["s"] for sec in ex["sections"]] == ss
    d["verts"][0] = (d["verts"][0][0] + 1.0,) + tuple(d["verts"][0][1:])
    assert exact_of(d) is None              # an edited mesh is written as itself


@pytest.mark.parametrize("stations, rings, match", [
    ([0.0], [RECT], "one ring per station"),
    ([0.0, 0.0], [RECT, RECT], "strictly ascending"),
    ([0.0, 10.0], [RECT, RECT[:3]], "same vertex count"),
])
def test_bad_lofts_are_refused(stations, rings, match):
    with pytest.raises(ValueError, match=match):
        StationLoft("x", line(), level(), None, stations, rings)
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_corridor_loft.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'bimforge.author.corridor.frame'`.

- [ ] **Step 3: Write `bimforge/author/corridor/frame.py`**

```python
"""Section coordinates to survey points for the road corridor (P.6).

(u, v): u left of travel, v up from the profile grade line, in the plane
square to the alignment's 3D tangent. That is the sweep engine's "normal"
frame (SweptSection._xf), and the plane IFC4.3 puts an
IfcSectionedSolidHorizontal's sections in. The corridor places its courses,
its earthwork and its ground samples through `survey_point`, so all three
agree on where a section point is.
"""
from __future__ import annotations

import math

from bimforge.author.sweep import MAX_ARC_STEP_RAD, VC_SAGITTA_FT


def survey_point(alignment, profile, s: float, u: float, v: float) -> tuple:
    """(northing, easting, elevation) of section point (u, v) at station s."""
    n0, e0, az = alignment.point_az(s)
    ln, le = alignment.left_normal(s)
    a = math.radians(az)
    tn, te = math.cos(a), math.sin(a)
    gam = math.atan(profile.grade(s))
    sg, cg = math.sin(gam), math.cos(gam)
    return (n0 + u * ln - v * sg * tn, e0 + u * le - v * sg * te,
            profile.elev(s) + v * cg)


def densify(alignment, profile, stations: list) -> list:
    """`stations` with more between them where a plan curve or a vertical
    curve needs them, by the sweep engine's own step rules (SweptSection.
    _bays). `stations` must hold the alignment's segment breaks and the
    profile's BVC/EVC stations already."""
    out = []
    for a, b in zip(stations, stations[1:]):
        ds = b - a
        n = 1
        k = abs(alignment.curvature((a + b) / 2.0))
        if k > 0.0:
            n = max(n, math.ceil(k * ds / MAX_ARC_STEP_RAD))
        eps = 1e-9 * ds
        dg = abs(profile.grade(b - eps) - profile.grade(a + eps))
        if dg > 1e-12:
            n = max(n, math.ceil(ds / math.sqrt(8.0 * VC_SAGITTA_FT * ds / dg)))
        out.extend(a + ds * i / n for i in range(n))
    out.append(stations[-1])
    return out
```

- [ ] **Step 4: Write `bimforge/author/corridor/loft.py`**

```python
"""StationLoft: a closed solid through one (u, v) ring per station along an
alignment (roadmap P.6), the road corridor's course body.

The sweep engine's SweptSection sweeps ONE section; a corridor's changes
with width transitions and superelevation, so each station brings its own
ring, with the same vertex count at every station. Rings sit in the
corridor frame (corridor.frame), the plane IFC4.3 places an
IfcSectionedSolidHorizontal's sections in, so on IFC4X3 the loft is written
as that solid (one profile per station) and as its mesh everywhere else.
The stations are the caller's: densify them (frame.densify) so the mesh's
chords stay on the curve the IFC solid follows.
"""
from __future__ import annotations

import math

from bimforge.author.alignment import poly_area
from bimforge.author.corridor.frame import survey_point
from bimforge.author.primitives import (_outward_tris, _wound, clean_ring,
                                        ear_clip, face_volume)
from bimforge.author.sweep import ring_centroid, to_model


class StationLoft:
    """Rings `rings[i]` at `stations[i]`, lofted point to point and capped."""

    def __init__(self, name: str, alignment, profile, origin, stations: list,
                 rings: list, ifc: str = "IfcBuildingElementProxy",
                 layer: str | None = None) -> None:
        if profile is None:
            raise ValueError(f"{name}: a station loft needs a vertical profile")
        if len(stations) < 2 or len(stations) != len(rings):
            raise ValueError(f"{name}: needs one ring per station, at least two")
        if any(b <= a for a, b in zip(stations, stations[1:])):
            raise ValueError(f"{name}: stations must be strictly ascending")
        counts = {len(r) for r in rings}
        if len(counts) != 1 or min(counts) < 3:
            raise ValueError(f"{name}: every ring needs the same vertex count, "
                             f"at least three")
        self.name, self.ifc, self.layer = name, ifc, layer
        #: what model_alignments finds the loft's IfcAlignment by
        self.alignment, self.profile, self.origin = alignment, profile, origin
        self.stations = [float(s) for s in stations]
        self.rings = [_wound([(float(u), float(v)) for u, v in r], ccw=True)
                      for r in rings]
        self.s0, self.s1 = self.stations[0], self.stations[-1]
        self._verts = None

    # ------------------------------------------------------------- geometry
    def _world(self, i: int) -> list:
        s = self.stations[i]
        return [to_model(self.origin,
                         *survey_point(self.alignment, self.profile, s, u, v))
                for u, v in self.rings[i]]

    def _faces(self) -> list:
        world = [self._world(i) for i in range(len(self.stations))]
        faces = []
        for i0, i1, i2 in ear_clip(self.rings[0]):
            faces.append([world[0][i2], world[0][i1], world[0][i0]])
        for i0, i1, i2 in ear_clip(self.rings[-1]):
            faces.append([world[-1][i0], world[-1][i1], world[-1][i2]])
        m = len(self.rings[0])
        for wa, wb in zip(world, world[1:]):
            for j in range(m):
                k = (j + 1) % m
                a, b, c, d = wa[j], wa[k], wb[k], wb[j]
                # the 4-fan through the quad's centroid, as SweptSection
                # lofts: a twisted quad's flux is the mean of its diagonals
                mid = tuple((a[x] + b[x] + c[x] + d[x]) / 4.0 for x in range(3))
                faces += [[a, b, mid], [b, c, mid], [c, d, mid], [d, a, mid]]
        return faces

    def _plan_ring(self) -> list:
        """The footprint: the left edge out, the right edge back."""
        left, right = [], []
        for s, ring in zip(self.stations, self.rings):
            for pick, out in ((max, left), (min, right)):
                u, v = pick(ring, key=lambda p: p[0])
                x, y, _z = to_model(self.origin, *survey_point(
                    self.alignment, self.profile, s, u, v))
                out.append((x, y))
        return left + right[::-1]

    def ifc_sections(self) -> list[dict]:
        """[{"s", "outer", "voids"}]: the IFC cross-sections, one per station,
        (u, v) in the section plane as emit_ifc._sectioned_solid reads them."""
        return [{"s": s, "outer": list(ring), "voids": []}
                for s, ring in zip(self.stations, self.rings)]

    def body_solids(self) -> list[dict]:
        verts: list = []
        index: dict = {}

        def vid(p):
            key = (round(p[0], 9), round(p[1], 9), round(p[2], 9))
            if key not in index:
                index[key] = len(verts)
                verts.append((float(p[0]), float(p[1]), float(p[2])))
            return index[key]

        tris = []
        for ring in self._faces():
            r = clean_ring(ring)
            if not r:
                continue
            for b, c in zip(r[1:], r[2:]):
                tris.append((vid(r[0]), vid(b), vid(c)))
        self._verts = list(verts)
        return [{"kind": "mesh", "units": "ft", "verts": verts,
                 "tris": _outward_tris(verts, tris), "plan": [self._plan_ring()],
                 "exact": {"kind": "sectioned", "sweep": self,
                           "alignment": self.alignment, "vprofile": self.profile,
                           "origin": self.origin,
                           "sections": self.ifc_sections()}}]

    def mesh_is_exact(self, verts) -> bool:
        """Whether `verts` are still this loft's own mesh (primitives.exact_of):
        anything that edits them is written as the mesh it made."""
        return self._verts is not None and [tuple(p) for p in verts] == self._verts

    # ----------------------------------------------------------- quantities
    @property
    def length_ft(self) -> float:
        return self.s1 - self.s0

    @property
    def volume_cf(self) -> float:
        return abs(face_volume(self._faces()))

    @property
    def mean_width_ft(self) -> float:
        return sum(max(u for u, _v in r) - min(u for u, _v in r)
                   for r in self.rings) / len(self.rings)

    @property
    def average_end_area_cf(self) -> float:
        """The volume by average end areas, each bay lengthened by the plan
        curvature at the rings' centroid (Pappus) and by the grade: a figure
        independent of the mesh, for the gate to hold the mesh to."""
        out = 0.0
        for i in range(len(self.stations) - 1):
            a, b = self.stations[i], self.stations[i + 1]
            mid = 0.5 * (a + b)
            k = self.alignment.curvature(mid)
            g = self.profile.grade(mid)
            area = 0.5 * (poly_area(self.rings[i]) + poly_area(self.rings[i + 1]))
            ubar = 0.5 * (ring_centroid(self.rings[i])[0]
                          + ring_centroid(self.rings[i + 1])[0])
            out += area * (b - a) * (1.0 - k * ubar) * math.sqrt(1.0 + g * g)
        return out
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_corridor_loft.py -q`
Expected: PASS.

If `test_a_curved_loft_agrees_with_its_curvature_corrected_end_areas` fails with the two figures about 2.8% apart, the curvature sign is the other way round from `SweptSection._closed_cf`. Check what `Alignment.curvature` returns on a right curve, and make the factor `(1.0 + k * ubar)` if it is positive there. The test's `> 1210` assertion settles which side is outside.

- [ ] **Step 6: Commit**

```bash
git add bimforge/author/corridor/frame.py bimforge/author/corridor/loft.py bimforge/author/tests/test_corridor_loft.py
git commit -m "road corridor: StationLoft, one ring per station, exact on IFC4X3 (P.6)"
```

---

### Task 5: the ground

**Files:**
- Create: `bimforge/author/corridor/ground.py`
- Test: `bimforge/author/tests/test_corridor_ground.py`

- [ ] **Step 1: Write the failing tests** in `bimforge/author/tests/test_corridor_ground.py`

```python
"""road-corridor ground: a plane, and 3DEP through a stubbed fetch (P.6)."""
import uuid

import pytest

from bimforge.author.alignment import Alignment
from bimforge.author.corridor.ground import PlaneGround, footprint, from_params
from bimforge.author.project import ProjectContext


def line():
    return Alignment({"station": 0.0, "northing": 0.0, "easting": 0.0},
                     [{"kind": "tangent", "bearing": "N 0-0-0 E", "length": 100.0}],
                     name="T")


def test_a_plane_through_a_point():
    g = PlaneGround(100.0, n0=10.0, e0=20.0, slope_n=0.02, slope_e=-0.01)
    assert g.z(60.0, 120.0) == pytest.approx(100.0)


def test_a_plane_from_params_passes_through_the_point_of_beginning():
    g = from_params({"source": "plane", "elevation": 95.0, "slope_e": 0.1},
                    line(), None, 50.0, None)
    assert g.z(0.0, 10.0) == pytest.approx(96.0)


def test_the_footprint_is_the_line_plus_its_reach():
    assert footprint(line(), 50.0) == pytest.approx((-50.0, -50.0, 50.0, 150.0))


@pytest.mark.parametrize("gp, ctx, match", [
    ({"source": "3dep"}, ProjectContext(name="g", epsg=2226, guid_ns=uuid.UUID(int=5)),
     "cache"),
    ({"source": "3dep", "cache": "x"}, ProjectContext(name="g", guid_ns=uuid.UUID(int=5)),
     "epsg"),
    ({"source": "lidar"}, None, "plane or 3dep"),
])
def test_bad_ground_is_refused(gp, ctx, match):
    with pytest.raises(ValueError, match=match):
        from_params(gp, line(), ctx, 50.0, None)


def test_3dep_fetches_the_footprint_and_adds_the_terrain(monkeypatch, tmp_path):
    import numpy as np

    import bimforge.terrain as T
    from bimforge.terrain.grid import TerrainGrid
    calls = {}

    def fake_fetch(bbox_m, spacing_m, crs_epsg, cache_path, refresh=False, log=print):
        calls["fetch"] = (bbox_m, spacing_m, crs_epsg, str(cache_path))
        return TerrainGrid(z=np.full((20, 20), 30.48), bbox_m=bbox_m,
                           spacing_m=spacing_m, crs_epsg=crs_epsg)

    def fake_attach(model, bbox_m, **kw):
        calls["attach"] = (model, bbox_m, kw)

    monkeypatch.setattr(T, "fetch_3dep_dem", fake_fetch)
    monkeypatch.setattr(T, "attach_terrain", fake_attach)
    ctx = ProjectContext(name="g", epsg=2226, guid_ns=uuid.UUID(int=5))
    stem = str(tmp_path / "ml")
    g = from_params({"source": "3dep", "cache": stem, "margin_ft": 10.0},
                    line(), ctx, 40.0, "MODEL")
    k = ctx.ft_to_m
    bbox, spacing, epsg, cache = calls["fetch"]
    assert bbox == pytest.approx((-50 * k, -50 * k, 50 * k, 150 * k))
    assert (spacing, epsg, cache) == (1.0, 2226, stem + "-3DEP-DEM.tif")
    model, abox, kw = calls["attach"]
    assert model == "MODEL" and abox == bbox
    assert kw["cache_stem"] == stem and kw["vshift_m"] == 0.0
    assert kw["unit_scale"] == pytest.approx(1.0 / k)
    assert g.z(50.0, 0.0) == pytest.approx(30.48 / k)
    with pytest.raises(ValueError, match="does not cover"):
        g.z(5000.0, 0.0)
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_corridor_ground.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'bimforge.author.corridor.ground'`.

- [ ] **Step 3: Check the bbox units** before writing the 3DEP path:

Run: `grep -n "bbox_m" bimforge/terrain/fetch.py | head -20`
Expected: `fetch_3dep_dem` treats `bbox_m` as metres in the CRS and `grid_to_mesh` scales by `unit_scale` (metres to feet). The code below converts survey feet to metres with `ctx.ft_to_m`. If `fetch_3dep_dem` instead expects CRS-native units (US feet for EPSG:2226), drop the `* k` from `bbox_m` and the `* self.ft_to_m` in `GridGround.z`, and change the test's expected bbox to match.

- [ ] **Step 4: Write `bimforge/author/corridor/ground.py`**

```python
"""The ground a road corridor is measured against (roadmap P.6).

`plane`: a plane through the alignment's point of beginning, for tests and
the shipped example, so CI never touches the network. `3dep`: the USGS 3DEP
1 m DEM over the corridor's footprint, cached under a path stem as
bimforge.terrain caches it (rebuilds are offline), with the TERRAIN element
added from the same cache. A ground answers `z(northing, easting)` in the
project's vertical datum, feet.
"""
from __future__ import annotations

import math
from pathlib import Path


class PlaneGround:
    """z = elevation + slope_n (n - n0) + slope_e (e - e0)."""

    def __init__(self, elevation: float, n0: float = 0.0, e0: float = 0.0,
                 slope_n: float = 0.0, slope_e: float = 0.0) -> None:
        self.elevation, self.n0, self.e0 = float(elevation), float(n0), float(e0)
        self.slope_n, self.slope_e = float(slope_n), float(slope_e)

    def z(self, n: float, e: float) -> float:
        return (self.elevation + self.slope_n * (n - self.n0)
                + self.slope_e * (e - self.e0))


class GridGround:
    """A bimforge.terrain TerrainGrid (metres, NAVD88), read in feet in the
    project datum."""

    def __init__(self, grid, ft_to_m: float, vshift_m: float = 0.0) -> None:
        self.grid, self.ft_to_m, self.vshift_m = grid, float(ft_to_m), float(vshift_m)

    def z(self, n: float, e: float) -> float:
        from bimforge.terrain.diff import sample_grid
        zm = float(sample_grid(self.grid.z, self.grid.bbox_m,
                               e * self.ft_to_m, n * self.ft_to_m)[0])
        if math.isnan(zm):
            raise ValueError(f"ground: no ground at N {n:.1f} E {e:.1f}: the "
                             f"DEM does not cover it")
        return (zm - self.vshift_m) / self.ft_to_m


def footprint(alignment, reach: float) -> tuple:
    """(e_min, n_min, e_max, n_max), survey feet: the alignment, sampled
    every 10 ft or closer, grown by `reach` each way."""
    run = alignment.s_end - alignment.s_start
    n = max(1, math.ceil(run / 10.0))
    pts = [alignment.point_az(alignment.s_start + run * i / n)[:2]
           for i in range(n + 1)]
    ns, es = [p[0] for p in pts], [p[1] for p in pts]
    return (min(es) - reach, min(ns) - reach, max(es) + reach, max(ns) + reach)


def from_params(gp: dict, alignment, ctx, reach: float, model, log=print):
    """The ground `gp` (the spec's `ground:`) names. `reach` is how far from
    the line the corridor can reach, feet; a 3DEP ground adds the TERRAIN
    element to `model`."""
    source = str((gp or {}).get("source", "")).lower()
    if source == "plane":
        n0, e0, _az = alignment.point_az(alignment.s_start)
        return PlaneGround(float(gp["elevation"]), n0=n0, e0=e0,
                           slope_n=float(gp.get("slope_n", 0.0)),
                           slope_e=float(gp.get("slope_e", 0.0)))
    if source == "3dep":
        import bimforge.terrain as terrain
        if not gp.get("cache"):
            raise ValueError("ground: source 3dep needs `cache`, the path stem "
                             "its downloads are kept under")
        if ctx is None or ctx.epsg is None:
            raise ValueError("ground: source 3dep needs project.epsg")
        k = ctx.ft_to_m
        spacing = float(gp.get("spacing_m", 1.0))
        vshift = float(gp.get("vshift_m", 0.0))
        e0, n0, e1, n1 = footprint(alignment, reach + float(gp.get("margin_ft", 200.0)))
        bbox_m = (e0 * k, n0 * k, e1 * k, n1 * k)
        stem = str(gp["cache"])
        grid = terrain.fetch_3dep_dem(bbox_m, spacing, ctx.epsg,
                                      Path(stem + "-3DEP-DEM.tif"), log=log)
        terrain.attach_terrain(model, bbox_m, crs_epsg=ctx.epsg, cache_stem=stem,
                               unit_scale=1.0 / k, spacing_m=spacing,
                               vshift_m=vshift, log=log)
        return GridGround(grid, k, vshift)
    raise ValueError(f"ground: source {gp.get('source') if gp else None!r} is "
                     f"not plane or 3dep")
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_corridor_ground.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add bimforge/author/corridor/ground.py bimforge/author/tests/test_corridor_ground.py
git commit -m "road corridor: plane and 3DEP ground (P.6)"
```

---

### Task 6: earthwork

**Files:**
- Create: `bimforge/author/corridor/earthwork.py`
- Test: `bimforge/author/tests/test_corridor_earthwork.py`

Hand-worked: one 10 ft lane at slope 0, one 1 ft course, a level profile at 100, level ground at 95, 2:1 fill. Subgrade at 99, so the fill is 4 ft deep. Each side's slope reaches 8 ft out. Section area = 20 × 4 + 2 × (½ × 8 × 4) = 112 sf, so 100 ft of road is 11,200 cf.

- [ ] **Step 1: Write the failing tests** in `bimforge/author/tests/test_corridor_earthwork.py`

```python
"""road-corridor earthwork: prismatoids between two sections (P.6)."""
import pytest

from bimforge.author.alignment import Alignment, Profile
from bimforge.author.corridor import earthwork
from bimforge.author.corridor.frame import survey_point
from bimforge.author.corridor.ground import PlaneGround
from bimforge.author.corridor.params import parse
from bimforge.author.corridor.section import resolve

AL = Alignment({"station": 0.0, "northing": 0.0, "easting": 0.0},
               [{"kind": "tangent", "bearing": "N 0-0-0 E", "length": 100.0}], name="T")
PROF = Profile([{"bvc_station": 0.0, "bvc_elev": 100.0, "g_in_pct": 0.0,
                 "g_out_pct": 0.0, "length_ft": 100.0, "evc_station": 100.0,
                 "evc_elev": 100.0}])
C = parse({"section": {
    "components": [{"name": "lane", "kind": "carriageway", "width": 10.0, "slope": 0.0}],
    "courses": [{"name": "AB", "type": "CORE", "thickness": 1.0}],
    "side_slopes": {"cut": {"ratio": 2.0}, "fill": {"ratio": 2.0}}}}, 0.0, 100.0)


def survey(s, u, v):
    return survey_point(AL, PROF, s, u, v)


def sections(ground):
    def dz(s, u, v):
        n, e, z = survey(s, u, v)
        return ground.z(n, e) - z
    return resolve(C, 0.0, dz), resolve(C, 100.0, dz)


def test_fill_on_level_ground_is_the_prism_formula():
    ground = PlaneGround(95.0)
    cut, fill, cut_depth, fill_depth = earthwork.strip("t", *sections(ground),
                                                       survey, ground.z, None)
    assert cut == []
    assert sum(p.volume_cf for p in fill) == pytest.approx(11200.0, rel=1e-9)
    assert fill_depth == pytest.approx(4.0)
    assert all(p.ifc == "IfcEarthworksFill" for p in fill)


def test_cut_less_fill_is_the_signed_section_area_on_a_side_hill():
    ground = PlaneGround(99.0, slope_e=0.2)     # rises to the east, the right side
    a, b = sections(ground)
    cut, fill, _cd, _fd = earthwork.strip("t", a, b, survey, ground.z, None)
    assert cut and fill
    d = []
    for u, v in a.earthwork_line():
        n, e, z = survey(0.0, u, v)
        d.append((u, ground.z(n, e) - z))
    area = sum(0.5 * (d0 + d1) * abs(u0 - u1) for (u0, d0), (u1, d1) in zip(d, d[1:]))
    net = sum(p.volume_cf for p in cut) - sum(p.volume_cf for p in fill)
    assert net == pytest.approx(100.0 * area, rel=1e-9)


def test_sections_with_different_counts_are_refused():
    ground = PlaneGround(95.0)
    a, b = sections(ground)
    b.subgrade["R"].append(b.subgrade["R"][-1])
    with pytest.raises(ValueError, match="point counts"):
        earthwork.strip("t", a, b, survey, ground.z, None)
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_corridor_earthwork.py -q`
Expected: FAIL with `ImportError: cannot import name 'earthwork'`.

- [ ] **Step 3: Write `bimforge/author/corridor/earthwork.py`**

```python
"""Cut and fill between two corridor sections (roadmap P.6).

The strip between two stations' earthwork lines is cut into triangles, two
per quad. Each triangle is split where the ground crosses the design line,
with depth interpolated linearly along its edges. Each piece becomes a
vertical triangular Prismatoid between the design line and the ground: cut
where the ground is above, fill where it is below. Every face is planar, so
the mesh volume is exact for the surfaces it carries (the private trail
family's lesson: a warped quad top is not a plane, and the STEP true-volume
check then disagrees by several percent).
"""
from __future__ import annotations

from bimforge.author.primitives import Prismatoid
from bimforge.author.sweep import to_model

LAYER = "C-ROAD"
IFC = {"cut": "IfcEarthworksCut", "fill": "IfcEarthworksFill"}
_TINY = 1e-6


def _signed_area(pts: list) -> float:
    x0, y0 = pts[0][0], pts[0][1]
    return 0.5 * sum((p[0] - x0) * (q[1] - y0) - (q[0] - x0) * (p[1] - y0)
                     for p, q in zip(pts, pts[1:] + pts[:1]))


def _clip(tri: list, sign: float) -> list:
    """The part of `tri`, vertices (n, e, z, ground), where sign x (ground -
    z) >= 0, split at the crossing by linear interpolation."""
    out = []
    for p, q in zip(tri, tri[1:] + tri[:1]):
        dp, dq = sign * (p[3] - p[2]), sign * (q[3] - q[2])
        if dp >= 0.0:
            out.append(p)
        if (dp > 0.0 > dq) or (dq > 0.0 > dp):
            t = dp / (dp - dq)
            out.append(tuple(a + t * (b - a) for a, b in zip(p, q)))
    return out if len(out) >= 3 else []


def _column(name: str, kind: str, tri: list, origin):
    """The vertical prismatoid between the design line and the ground over
    one triangle, or None when it has no plan area or no depth."""
    design = [to_model(origin, n, e, z) for n, e, z, _g in tri]
    earth = [to_model(origin, n, e, g) for n, e, _z, g in tri]
    bottom, top = (design, earth) if kind == "cut" else (earth, design)
    if max(t[2] - b[2] for b, t in zip(bottom, top)) < _TINY:
        return None
    area = _signed_area(bottom)
    if abs(area) < _TINY:
        return None
    if area < 0.0:
        bottom, top = bottom[::-1], top[::-1]
    return Prismatoid(name, bottom, top, ifc=IFC[kind], layer=LAYER)


def strip(tag: str, a, b, survey, ground_z, origin) -> tuple:
    """(cut prismatoids, fill prismatoids, max cut depth, max fill depth)
    between sections `a` and `b` (section.Section). `survey(s, u, v)` places
    a section point (frame.survey_point); `ground_z(n, e)` is the ground."""
    la, lb = a.earthwork_line(), b.earthwork_line()
    if len(la) != len(lb):
        raise ValueError(f"{tag}: earthwork lines at {a.s:g} and {b.s:g} have "
                         f"different point counts ({len(la)}, {len(lb)})")

    def corner(sec, p):
        n, e, z = survey(sec.s, *p)
        return (n, e, z, ground_z(n, e))

    ca, cb = [corner(a, p) for p in la], [corner(b, p) for p in lb]
    out = {"cut": [], "fill": []}
    depth = {"cut": 0.0, "fill": 0.0}
    for i in range(len(la) - 1):
        for t, tri in enumerate(((ca[i], cb[i], cb[i + 1]),
                                 (ca[i], cb[i + 1], ca[i + 1]))):
            for kind, sign in (("cut", 1.0), ("fill", -1.0)):
                poly = _clip(list(tri), sign)
                for f, piece in enumerate((poly[0], poly[k], poly[k + 1])
                                          for k in range(1, len(poly) - 1)):
                    col = _column(f"{kind} {tag} {i}.{t}.{f}", kind, list(piece),
                                  origin)
                    if col is None:
                        continue
                    out[kind].append(col)
                    depth[kind] = max(depth[kind],
                                      max(abs(q[3] - q[2]) for q in piece))
    return out["cut"], out["fill"], depth["cut"], depth["fill"]
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_corridor_earthwork.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bimforge/author/corridor/earthwork.py bimforge/author/tests/test_corridor_earthwork.py
git commit -m "road corridor: cut and fill prismatoids, split where ground crosses grade (P.6)"
```

---

### Task 7: mass haul

**Files:**
- Create: `bimforge/author/corridor/masshaul.py`
- Test: `bimforge/author/tests/test_corridor_masshaul.py`

- [ ] **Step 1: Write the failing tests** in `bimforge/author/tests/test_corridor_masshaul.py`

```python
"""road-corridor mass haul (P.6)."""
import pytest

from bimforge.author.corridor.masshaul import HEADER, mass_haul, to_csv

BANDS = [(0.0, 100.0, 2700.0, 0.0), (100.0, 200.0, 0.0, 2160.0)]


def test_the_ordinate_adds_cut_less_the_bank_volume_fill_takes():
    rows = mass_haul(BANDS, shrink=0.2)
    assert [r.cumulative_cy for r in rows] == pytest.approx([100.0, 0.0])
    assert rows[1].fill_cy == pytest.approx(80.0)
    assert rows[1].adjusted_fill_cy == pytest.approx(100.0)
    assert (rows[1].start, rows[1].station) == (100.0, 200.0)


def test_the_csv_has_a_row_per_band():
    lines = to_csv(mass_haul(BANDS, shrink=0.2)).strip().splitlines()
    assert lines[0] == HEADER == "start,station,cut_cy,fill_cy,adjusted_fill_cy,cumulative_cy"
    assert lines[1] == "0.00,100.00,100.000,0.000,0.000,100.000"
    assert len(lines) == 3
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_corridor_masshaul.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'bimforge.author.corridor.masshaul'`.

- [ ] **Step 3: Write `bimforge/author/corridor/masshaul.py`**

```python
"""Mass haul for the road corridor (roadmap P.6), band by band.

Cut is bank volume. Fill is compacted volume, and takes fill / (1 - shrink)
of bank to make; the ordinate adds cut less that. Loose volumes (the swell)
are the family's, on the earthwork's quantity sets.
"""
from __future__ import annotations

from dataclasses import dataclass

CF_PER_CY = 27.0
HEADER = "start,station,cut_cy,fill_cy,adjusted_fill_cy,cumulative_cy"


@dataclass(frozen=True)
class HaulRow:
    start: float
    station: float
    cut_cy: float
    fill_cy: float
    adjusted_fill_cy: float
    cumulative_cy: float


def mass_haul(bands: list, shrink: float) -> list[HaulRow]:
    """One row per (start, end, cut cf, fill cf) band, in order."""
    rows, total = [], 0.0
    for s0, s1, cut_cf, fill_cf in bands:
        cut, fill = cut_cf / CF_PER_CY, fill_cf / CF_PER_CY
        adjusted = fill / (1.0 - shrink)
        total += cut - adjusted
        rows.append(HaulRow(s0, s1, cut, fill, adjusted, total))
    return rows


def to_csv(rows: list) -> str:
    return "\n".join([HEADER] + [
        f"{r.start:.2f},{r.station:.2f},{r.cut_cy:.3f},{r.fill_cy:.3f},"
        f"{r.adjusted_fill_cy:.3f},{r.cumulative_cy:.3f}" for r in rows]) + "\n"
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_corridor_masshaul.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bimforge/author/corridor/masshaul.py bimforge/author/tests/test_corridor_masshaul.py
git commit -m "road corridor: mass haul with shrink (P.6)"
```

---

### Task 8: the family, its registration and the mass-haul output

**Files:**
- Create: `bimforge/author/families/road_corridor.py`
- Modify: `bimforge/author/model.py` (`StructureModel`, after `ifc_sweeps`)
- Modify: `bimforge/author/families/registry.py` (`_shipped()`, `OUTPUT_KEYS`, `build_from_spec`)
- Test: `bimforge/author/tests/test_road_corridor.py`

- [ ] **Step 1: Write the failing tests** in `bimforge/author/tests/test_road_corridor.py`

```python
"""road-corridor: the family, built directly and through est-bim build (P.6)."""
import copy
import uuid

import pytest

from bimforge.author.project import ProjectContext

N0, E0 = 1943000.0, 6594000.0
PARAMS = {
    "alignment": {"name": "ML", "pob": {"station": 1000.0, "northing": N0, "easting": E0},
                  "run": [{"kind": "tangent", "bearing": "N 0-0-0 E", "length": 200.0},
                          {"kind": "curve", "delta": "11-27-33", "radius": 500.0,
                           "turn": "R", "length": 100.0},
                          {"kind": "tangent", "bearing": "N 11-27-33 E", "length": 200.0}]},
    "profile": {"curves": [{"bvc_station": 1000.0, "bvc_elev": 300.0, "g_in_pct": 1.0,
                            "g_out_pct": 1.0, "length_ft": 500.0,
                            "evc_station": 1500.0, "evc_elev": 305.0}]},
    "ground": {"source": "plane", "elevation": 300.0, "slope_e": 0.05},
    "section": {
        "components": [{"name": "lane", "kind": "carriageway", "width": 12.0},
                       {"name": "shoulder", "kind": "shoulder", "width": 5.0,
                        "slope": -0.05}],
        "courses": [{"name": "HMA", "type": "PAVEMENT", "thickness": 0.4},
                    {"name": "AB", "type": "CORE", "thickness": 1.0}],
        "side_slopes": {"cut": {"ratio": 2.0, "ditch": {"width": 4.0, "depth": 1.5}},
                        "fill": {"ratio": 2.0}, "daylight_limit_ft": 150}},
    "superelevation": [[1000, -0.02, -0.02], [1150, -0.02, -0.02],
                       [1200, 0.04, -0.04], [1300, 0.04, -0.04], [1350, -0.02, -0.02]],
    "gaps": [{"from": 1350, "to": 1400, "kind": "structure"},
             {"from": 1050, "to": 1100, "kind": "wall", "side": "L", "offset": 30.0}],
    "stations": {"interval": 25, "band": 100},
    "mass_haul": {"shrink": 0.1, "swell": 0.2},
}
CTX = ProjectContext(name="rc", epsg=2226, base_e=E0, base_n=N0, base_h=300.0,
                     guid_ns=uuid.UUID(int=9))


@pytest.fixture(scope="module")
def model():
    from bimforge.author.families.road_corridor import build
    return build(copy.deepcopy(PARAMS), CTX)


def courses(m):
    return [e for e in m.elements if e.ifc_class == "IfcCourse"]


def test_one_course_element_per_course_component_and_band(model):
    # bands: 10+00 to 11+00, 11+00 to 12+00, 12+00 to 13+00, 13+00 to 13+50, 14+00 to 15+00
    assert len(courses(model)) == 5 * 2 * 2
    assert {e.predefined_type for e in courses(model)} == {"PAVEMENT", "CORE"}
    assert {e.spatial_part.predefined_type for e in courses(model)} == {"CARRIAGEWAY", "SHOULDER"}


def test_nothing_is_built_inside_the_structure_gap(model):
    for el in courses(model):
        for lf in el.geometry:
            assert lf.s1 <= 1350.0 + 1e-6 or lf.s0 >= 1400.0 - 1e-6, el.name
    for el in model.elements:
        if "BIMForge_MassHaul" in el.psets:
            ps = el.psets["BIMForge_MassHaul"]
            assert ps["EndStation"] <= 1350.0 + 1e-6 or ps["StartStation"] >= 1400.0 - 1e-6


def test_every_course_meets_its_stated_volume(model):
    from bimforge.author.gate import check_stated_quantities
    assert model.stated_quantities
    assert check_stated_quantities(model) == []


def test_mass_haul_rows_follow_the_bands(model):
    rows = model.mass_haul
    assert [(r.start, r.station) for r in rows] == [
        (1000.0, 1100.0), (1100.0, 1200.0), (1200.0, 1300.0), (1300.0, 1350.0),
        (1400.0, 1500.0)]
    last = [e for e in model.elements if e.name.endswith("15+00.00")
            and "BIMForge_MassHaul" in e.psets]
    assert last
    assert last[0].psets["BIMForge_MassHaul"]["CumulativeCY"] == pytest.approx(
        rows[-1].cumulative_cy, abs=1e-3)


def test_each_element_carries_its_standard_set(model):
    sets = {e.ifc_class: set(e.standard_qto) for e in model.elements}
    assert sets["IfcCourse"] == {"Qto_CourseBaseQuantities"}
    assert sets.get("IfcEarthworksCut", {"Qto_EarthworksCutBaseQuantities"}) == {
        "Qto_EarthworksCutBaseQuantities"}
    assert sets.get("IfcEarthworksFill", {"Qto_EarthworksFillBaseQuantities"}) == {
        "Qto_EarthworksFillBaseQuantities"}
    assert "IfcEarthworksCut" in sets or "IfcEarthworksFill" in sets


def test_a_slope_that_finds_no_ground_is_refused():
    from bimforge.author.families.road_corridor import build
    p = copy.deepcopy(PARAMS)
    p["ground"]["elevation"] = 0.0
    with pytest.raises(ValueError, match="finds no ground"):
        build(p, CTX)


PAYCODES = """\
rules:
  - {match: "(?i)^(HMA|AB) ", group: rc_pave}
  - {match: "(?i)^(Cut|Fill) ", group: rc_earth}
groups:
  rc_pave: {measure: GrossVolume}
  rc_earth: {measure: GrossVolume}
codes:
  RC-PAVE: {group: rc_pave, measure: GrossVolume, unit: CY, item_number: "0001",
            description: "Pavement courses"}
  RC-EARTH: {group: rc_earth, measure: GrossVolume, unit: CY, item_number: "0002",
             description: "Earthwork"}
"""


def _built(tmp_path, schema):
    import ifcopenshell
    import yaml

    from bimforge.author.families.registry import build_from_spec
    (tmp_path / "rc.paycodes.yaml").write_text(PAYCODES, "utf-8")
    spec = {"family": "road-corridor", "params": copy.deepcopy(PARAMS),
            "paycodes": "./rc.paycodes.yaml",
            "outputs": {"ifc": "out/rc.ifc", "masshaul": "out/rc.masshaul.csv"},
            "project": {"name": "Corridor fixture", "epsg": 2226,
                        "base": [E0, N0, 300.0], "guid_ns": str(uuid.UUID(int=9)),
                        "schema": schema, "facility": {"kind": "road"}}}
    if schema == "IFC4":
        del spec["project"]["facility"]
    path = tmp_path / "rc.spec.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False), "utf-8")
    assert build_from_spec(str(path)) == 0
    return ifcopenshell.open(str(tmp_path / "out" / "rc.ifc")), tmp_path / "out"


def test_the_ifc4x3_file_is_a_road(tmp_path):
    import ifcopenshell.util.element as E

    from bimforge.author.gate import alignment_issues, schema_issues
    f, out = _built(tmp_path, "IFC4X3_ADD2")
    assert not schema_issues(f) + alignment_issues(f)
    assert len(f.by_type("IfcRoad")) == 1
    parts = f.by_type("IfcRoadPart")
    assert sum(p.PredefinedType == "ROADSEGMENT" for p in parts) == 2
    assert {p.PredefinedType for p in parts} >= {"ROADSEGMENT", "CARRIAGEWAY", "SHOULDER"}
    for course in f.by_type("IfcCourse"):
        typ = E.get_type(course)
        assert typ is not None and typ.is_a("IfcCourseType")
        assert typ.PredefinedType in ("PAVEMENT", "CORE")
        assert "Qto_CourseBaseQuantities" in E.get_psets(course, qtos_only=True)
        items = course.Representation.Representations[0].Items
        assert all(i.is_a("IfcSectionedSolidHorizontal") for i in items)
    text = (out / "rc.masshaul.csv").read_text("utf-8")
    assert text.startswith("start,station,")


def test_the_ifc4_file_passes_the_schema(tmp_path):
    from bimforge.author.gate import schema_issues
    f, _out = _built(tmp_path, "IFC4")
    assert not schema_issues(f)
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_road_corridor.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'bimforge.author.families.road_corridor'`.

- [ ] **Step 3: Add `StructureModel.mass_haul`** in `bimforge/author/model.py`, directly after the `ifc_sweeps` field:

```python
    #: A road corridor's mass-haul table (corridor.masshaul.HaulRow per
    #: station band), written to `outputs.masshaul` as a CSV; [] otherwise.
    mass_haul: list = field(default_factory=list)
```

- [ ] **Step 4: Write `bimforge/author/families/road_corridor.py`**

```python
"""road-corridor -- a road from an alignment, a profile, a typical section
and the ground (roadmap P.6): pavement courses lofted along the alignment,
cut and fill out to daylight, and the mass haul, in IFC4.3's road terms
(IfcRoad > ROADSEGMENT > CARRIAGEWAY / SHOULDER / CENTRALRESERVE, IfcCourse
typed by IfcCourseType, IfcEarthworksCut and IfcEarthworksFill).

Spec: docs/superpowers/specs/2026-11-21-road-corridor-design.md.
"""
from __future__ import annotations

import math
import sys

REQUIRED = ("alignment", "profile", "ground", "section")
LAYER = "C-ROAD"
#: how far a course's mesh volume may stray from its average end area
AEA_TOL = 0.005


def bands(stations: list, s_start: float, band: float) -> list:
    """[(i0, i1)]: the index range of `stations` in each station band. The
    band boundaries are stations already (params.Corridor.stations)."""
    out = []
    for i in range(len(stations) - 1):
        k = math.floor((stations[i] - s_start) / band + 1e-9)
        if out and out[-1][0] == k:
            out[-1][2] = i + 1
        else:
            out.append([k, i, i + 1])
    return [(i0, i1) for _k, i0, i1 in out]


def _parts(r: int) -> tuple:
    """Run r's ROADSEGMENT, and its lateral parts by component kind."""
    from bimforge.author.corridor.params import PART_TYPES
    seg = {"name": f"Segment {r}", "predefined_type": "ROADSEGMENT",
           "usage_type": "LONGITUDINAL"}
    return seg, {kind: {"name": f"Segment {r} {kind}", "predefined_type": pt,
                        "usage_type": "LATERAL", "parent": seg}
                 for kind, pt in PART_TYPES.items()}


def build(params: dict, ctx) -> "StructureModel":
    from bimforge.author.alignment import Alignment, Profile, sta
    from bimforge.author.corridor import earthwork, masshaul
    from bimforge.author.corridor.frame import densify, survey_point
    from bimforge.author.corridor.ground import from_params
    from bimforge.author.corridor.loft import StationLoft
    from bimforge.author.corridor.params import SIDES, parse
    from bimforge.author.corridor.section import resolve
    from bimforge.author.model import Element, StructureModel

    missing = [k for k in REQUIRED if params.get(k) is None]
    if missing:
        raise ValueError(f"road-corridor params missing {missing}")
    al_p = params["alignment"]
    al = Alignment(al_p["pob"], al_p["run"], name=al_p.get("name", "ML"))
    prof = Profile(params["profile"]["curves"])
    c = parse(params, al.s_start, al.s_end)
    model = StructureModel("road-corridor", ctx)
    ground = from_params(params["ground"], al, ctx,
                         c.max_half_width() + c.slopes.daylight_limit, model,
                         log=lambda m: print(m, file=sys.stderr))

    def survey(s, u, v):
        return survey_point(al, prof, s, u, v)

    def ground_dz(s, u, v):
        n, e, z = survey(s, u, v)
        return ground.z(n, e) - z

    hauls, haul_elements = [], []
    for r, (s0, s1) in enumerate(c.runs(), start=1):
        segment, parts = _parts(r)
        extra = list(al.seg_breaks(s0, s1)) + list(prof.breaks(s0, s1))
        stations = densify(al, prof, c.stations(s0, s1, extra))
        secs = [resolve(c, s, ground_dz) for s in stations]
        for i0, i1 in bands(stations, al.s_start, c.band):
            b0, b1 = stations[i0], stations[i1]
            ss, bs = stations[i0:i1 + 1], secs[i0:i1 + 1]
            tag = f"STA {sta(b0)} to {sta(b1)}"
            for k, course in enumerate(c.courses):
                for j, comp in enumerate(c.components):
                    name = f"{course.name} {comp.name} {tag}"
                    lofts = [StationLoft(f"{name} {side}", al, prof, ctx, ss,
                                         [sec.courses[k, j, side] for sec in bs],
                                         ifc="IfcCourse", layer=LAYER)
                             for side in SIDES]
                    vol = sum(lf.volume_cf for lf in lofts)
                    aea = sum(lf.average_end_area_cf for lf in lofts)
                    model.add(Element(
                        name, ifc_class="IfcCourse", geometry=lofts,
                        predefined_type=course.type, type_name=course.name,
                        material=course.name, layer=LAYER, body="solids",
                        spatial_part=parts[comp.kind],
                        quantities={"length_ft": b1 - b0, "volume_cf": vol},
                        standard_qto={"Qto_CourseBaseQuantities": {
                            "Length": ("length", b1 - b0),
                            "Width": ("length", sum(lf.mean_width_ft for lf in lofts)),
                            "Thickness": ("length", course.thickness),
                            "Volume": ("volume", vol)}}))
                    model.stated_quantities.append(
                        (f"{name}: mesh volume vs average end area", vol, aea,
                         AEA_TOL * max(aea, 1.0)))
            cut, fill, cut_d, fill_d = [], [], 0.0, 0.0
            for a, b in zip(bs, bs[1:]):
                cp, fp, cd, fd = earthwork.strip(f"{tag} {sta(a.s)}", a, b,
                                                 survey, ground.z, ctx)
                cut += cp
                fill += fp
                cut_d, fill_d = max(cut_d, cd), max(fill_d, fd)
            width = sum(sec.width() for sec in bs) / len(bs)
            cut_cf = sum(p.volume_cf for p in cut)
            fill_cf = sum(p.volume_cf for p in fill)
            els = []
            if cut:
                els.append(model.add(Element(
                    f"Cut {tag}", ifc_class="IfcEarthworksCut", geometry=cut,
                    predefined_type="CUT", layer=LAYER, body="solids",
                    spatial_part=segment,
                    quantities={"length_ft": b1 - b0, "volume_cf": cut_cf},
                    standard_qto={"Qto_EarthworksCutBaseQuantities": {
                        "Length": ("length", b1 - b0), "Width": ("length", width),
                        "Depth": ("length", cut_d),
                        "UndisturbedVolume": ("volume", cut_cf),
                        "LooseVolume": ("volume", cut_cf * (1.0 + c.swell))}})))
            if fill:
                bank = fill_cf / (1.0 - c.shrink)
                els.append(model.add(Element(
                    f"Fill {tag}", ifc_class="IfcEarthworksFill", geometry=fill,
                    predefined_type="EMBANKMENT", layer=LAYER, body="solids",
                    spatial_part=segment,
                    quantities={"length_ft": b1 - b0, "volume_cf": fill_cf},
                    standard_qto={"Qto_EarthworksFillBaseQuantities": {
                        "Length": ("length", b1 - b0), "Width": ("length", width),
                        "Depth": ("length", fill_d),
                        "CompactedVolume": ("volume", fill_cf),
                        "LooseVolume": ("volume", bank * (1.0 + c.swell))}})))
            hauls.append((b0, b1, cut_cf, fill_cf))
            haul_elements.append(els)
    model.mass_haul = masshaul.mass_haul(hauls, c.shrink)
    for els, row in zip(haul_elements, model.mass_haul):
        for el in els:
            el.psets["BIMForge_MassHaul"] = {
                "StartStation": row.start, "EndStation": row.station,
                "CumulativeCY": round(row.cumulative_cy, 3)}
    return model
```

- [ ] **Step 5: Register the family and the output** in `bimforge/author/families/registry.py`:

In `_shipped()`, add `road_corridor` to the import list (alphabetical: after `pipe_supports`) and the entry `"road-corridor": road_corridor.build,` after `"approach-slab": approach_slab.build,`.

Change `OUTPUT_KEYS`:

```python
OUTPUT_KEYS = ("dxf", "ifc", "takeoff_map", "qto", "step", "bbs", "masshaul")
```

In `build_from_spec`, inside the `try:` after the `step` block:

```python
        if outs.get("masshaul") and model.mass_haul:
            from bimforge.author.corridor.masshaul import to_csv
            p = Path(outs["masshaul"])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(to_csv(model.mass_haul), encoding="utf-8")
            print(f"mass haul written to {p}", file=sys.stderr)
            written["masshaul"] = str(p)
```

Add `masshaul: CAD/x.masshaul.csv` to the `outputs:` line of the module docstring.

- [ ] **Step 6: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_road_corridor.py -q`
Expected: PASS.

If `test_the_ifc4x3_file_is_a_road` fails because a course's items are `IfcFacetedBrep`, `exact_of` refused the exact form. Check that `StationLoft.mesh_is_exact` gets the same `verts` list `body_solids` built (emit may round or copy them). If it fails on `IfcCourseType`, read how `emit_ifc` derives a type class from `type_name` (search for `IfcRelDefinesByType`) and make sure `IfcCourse` maps to `IfcCourseType`.

- [ ] **Step 7: Run the whole author suite** to catch registry fallout

Run: `python -m pytest bimforge/author -q`
Expected: PASS. `test_registry.py` and `test_example_globalids.py` don't see a new example yet.

- [ ] **Step 8: Commit**

```bash
git add bimforge/author/families/road_corridor.py bimforge/author/model.py bimforge/author/families/registry.py bimforge/author/tests/test_road_corridor.py
git commit -m "road-corridor family: courses, cut and fill, mass haul, under IfcRoad (P.6)"
```

---

### Task 9: the shipped example

**Files:**
- Create: `bimforge/author/examples/road-corridor.spec.yaml`
- Create: `bimforge/author/examples/road-corridor.paycodes.yaml`
- Modify: `bimforge/author/tests/fixtures/example_globalids.json`

- [ ] **Step 1: Write `bimforge/author/examples/road-corridor.spec.yaml`**

```yaml
# Worked road-corridor run (P.6): a two-lane road on a tangent, a 1000 ft
# right curve and a second tangent, over a sloping plane of ground, with a
# superelevation run through the curve, a shoulder that widens, a gap for a
# bridge and a gap for a wall on the left. --check-only writes nothing (CI
# fixture). Fictitious alignment and stationing: nothing here is a real
# project.
family: road-corridor
params:
  alignment:
    name: "ML"
    pob: {station: 1000.0, northing: 1943000.0, easting: 6594000.0}
    run:
      - {kind: tangent, bearing: "N 0-0-0 E", length: 600.0}
      - {kind: curve, delta: "20-0-0", radius: 1000.0, turn: R, length: 349.07}
      - {kind: tangent, bearing: "N 20-0-0 E", length: 600.0}
  profile:                              # one sag VC over the whole road
    curves:
      - bvc_station: 1000.0
        bvc_elev: 298.0
        g_in_pct: 3.0
        g_out_pct: 4.4
        length_ft: 1549.07
        evc_station: 2549.07
        evc_elev: 355.3156
  ground: {source: plane, elevation: 300.0, slope_n: 0.03, slope_e: 0.04}
  section:
    crown: centerline
    components:                         # outward from the crown, both sides
      - {name: lane, kind: carriageway, width: 12.0}
      - {name: shoulder, kind: shoulder, width: 5.0, slope: -0.05}
    courses:                            # top down
      - {name: HMA, type: PAVEMENT, thickness: 0.40}
      - {name: AB, type: CORE, thickness: 1.00}
    side_slopes:
      cut: {ratio: 2.0, ditch: {width: 4.0, depth: 1.5}}
      fill: {ratio: 2.0}
      daylight_limit_ft: 150
  widths:                               # the right shoulder widens to 10 ft
    - {component: shoulder, side: R, at: [[1200, 5.0], [1300, 10.0]]}
  superelevation:                       # [station, left, right]; - slopes down away
    - [1000.0, -0.02, -0.02]
    - [1500.0, -0.02, -0.02]
    - [1600.0, 0.04, -0.04]
    - [1949.07, 0.04, -0.04]
    - [2049.07, -0.02, -0.02]
    - [2549.07, -0.02, -0.02]
  gaps:
    - {from: 1700, to: 1800, kind: structure}           # a bridge
    - {from: 2200, to: 2300, kind: wall, side: L, offset: 40.0}
  stations: {interval: 25, band: 100}
  mass_haul: {shrink: 0.10, swell: 0.20}
paycodes: ./road-corridor.paycodes.yaml
outputs:
  dxf: out/road-corridor.dxf
  ifc: out/road-corridor.ifc
  takeoff_map: out/road-corridor-takeoff-map.yaml
  masshaul: out/road-corridor.masshaul.csv
project:
  name: "Fixture Road (example)"
  epsg: 2226
  base: [6594000.0, 1943000.0, 300.0]
  guid_ns: "3b7a5c2e-0000-4000-8000-0000000000c6"
  facility: {kind: road}
```

`crown: centerline` is in the spec format but the family has one crown, so it reads nothing from it. If the build runs with `gate.unread_params: warn`, drop the key from the example rather than add code for it.

- [ ] **Step 2: Write `bimforge/author/examples/road-corridor.paycodes.yaml`**

```yaml
# Road corridor: pavement courses and earthwork (CY).
rules:
  - match: "(?i)^HMA "
    group: rc_hma
  - match: "(?i)^AB "
    group: rc_ab
  - match: "(?i)^Cut "
    group: rc_cut
  - match: "(?i)^Fill "
    group: rc_fill
groups:
  rc_hma: {measure: GrossVolume}
  rc_ab: {measure: GrossVolume}
  rc_cut: {measure: GrossVolume}
  rc_fill: {measure: GrossVolume}
codes:
  PAVE-HMA:
    group: rc_hma
    measure: GrossVolume
    unit: CY
    item_number: "390132"
    description: "Hot mix asphalt"
  PAVE-AB:
    group: rc_ab
    measure: GrossVolume
    unit: CY
    item_number: "260203"
    description: "Class 2 aggregate base"
  EARTH-CUT:
    group: rc_cut
    measure: GrossVolume
    unit: CY
    item_number: "190101"
    description: "Roadway excavation"
  EARTH-FILL:
    group: rc_fill
    measure: GrossVolume
    unit: CY
    item_number: "198010"
    description: "Imported borrow"
```

- [ ] **Step 3: Build it**

Run: `est-bim build bimforge/author/examples/road-corridor.spec.yaml --check-only`
Expected: the gate's pre report passes and the run prints `--check-only: nothing written`. If a side slope finds no ground, the profile has run too far above or below the ground plane at the station the error names. Fix the example's profile or ground, not the daylight limit.

- [ ] **Step 4: Run the conformance suite on it**

Run: `python -m pytest bimforge/bim/tests/test_conformance.py -q -k road-corridor`
Expected: PASS on both IFC4X3 and IFC4 (the example joins by its file name).

- [ ] **Step 5: Record its GlobalIds**

Run `python -m pytest bimforge/author/tests/test_example_globalids.py -q`. Expected: `test_every_example_is_recorded` FAILS (road-corridor is not recorded). Then record it:

```bash
python - <<'PY'
import json, shutil, tempfile
from pathlib import Path
import ifcopenshell
src = Path("bimforge/author/examples")
tmp = Path(tempfile.mkdtemp())
for p in src.glob("road-corridor.*.yaml"):
    shutil.copy(p, tmp / p.name)
from bimforge.author.families.registry import build_from_spec
assert build_from_spec(str(tmp / "road-corridor.spec.yaml")) == 0
f = ifcopenshell.open(str(tmp / "out" / "road-corridor.ifc"))
fx = Path("bimforge/author/tests/fixtures/example_globalids.json")
d = json.loads(fx.read_text("utf-8"))
d["road-corridor"] = {
    "elements": {e.Name: e.GlobalId for e in f.by_type("IfcElement")},
    "roots": {e.GlobalId: e.is_a() for e in f.by_type("IfcRoot")}}
fx.write_text(json.dumps(d, indent=1, sort_keys=True) + "\n", "utf-8")
PY
git diff --stat bimforge/author/tests/fixtures/example_globalids.json
```

Expected: the diff only adds a `road-corridor` block. If it reorders existing blocks, the file was not written with `sort_keys=True`. Revert it and rewrite with the original key order.

Run: `python -m pytest bimforge/author/tests/test_example_globalids.py -q`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add bimforge/author/examples/road-corridor.spec.yaml bimforge/author/examples/road-corridor.paycodes.yaml bimforge/author/tests/fixtures/example_globalids.json
git commit -m "road-corridor example: curve, superelevation, widening, bridge and wall gaps (P.6)"
```

---

### Task 10: changelog

**Files:**
- Modify: `CHANGELOG.md` (the Unreleased section's `### Added`)

- [ ] **Step 1: Add the entry** under Unreleased > Added:

```markdown
- The `road-corridor` family (P.6): a road from an alignment, a profile, a typical section and the ground. Pavement courses are `IfcCourse` elements typed by `IfcCourseType`, written as `IfcSectionedSolidHorizontal` along the alignment on IFC4X3, under `IfcRoad` > ROADSEGMENT > CARRIAGEWAY / SHOULDER. Cut and fill run to daylight as `IfcEarthworksCut` / `IfcEarthworksFill`, with superelevation, width transitions, gaps for bridges and walls, and a mass-haul table (`outputs.masshaul`). Ground is a plane or 3DEP.
- `Element.standard_qto`: a class's standard quantity set (`Qto_CourseBaseQuantities`, ...), written beside `Qto_BaseQuantities` (M.17's first step).
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "Changelog: the road-corridor family (P.6)"
```

The roadmap row P.6 is updated to "Done in #<PR>" when the PR is opened.
