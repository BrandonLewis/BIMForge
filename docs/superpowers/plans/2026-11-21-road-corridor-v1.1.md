# Road Corridor V1.1 (Slope Rules, Walls, Guardrail, Dimensions) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hold a road corridor's side slopes to Caltrans practice on steep ground (4:1 fill, 2:1 behind guardrail over a fill height, soil over rock with a bench in cut, a wall wherever no slope fits), write each guardrail run as an `IfcRailing` GUARDRAIL with its length of need and end treatments, list every automatic wall and every stretch a structure should take, and give courses, earthwork and guardrail the `BIMForge_Dimensions` and quantity `Formula`s that the gate recomputes.

**Architecture:** Every V1.1 key is optional and parsed in `corridor/params.py`; with none of them the corridor builds V1's bodies, quantities and GlobalIds (Task 1 pins this). The section resolver (`corridor/section.py`) gains the steep-fill rule with the guarded widening, the rock bench, the footprint check, a wall at the hinge, and `needs_wall()`, a probe that says which wall a side needs. A new `corridor/walls.py` turns failing stations into wall gaps (runs ending where the slope fits again) and writes the wall and structure-candidate tables. A new `corridor/guardrail.py` lays out guardrail runs by the TSSM length-of-need formula. A new `corridor/dimensions.py` holds the dictionary class codes and the Formulas. The family (`families/road_corridor.py`) finds the walls first, then builds as V1 did, then adds the rails (a kernel `SweptSection` W-beam band) and the tables. The kernel gains `StructureModel.tables` (CSV outputs, written by the registry), a Formula on `Element.standard_qto` quantities, text and optional dictionary dimensions, and a gate formula grammar that reads the element's `BIMForge_Dimensions` and takes one difference (`EndStation - StartStation`).

**Tech Stack:** Python 3.11+, ifcopenshell, pytest.

**Spec:** `docs/superpowers/specs/2026-11-21-road-corridor-v1.1-slopes-guardrail-design.md` (the authority). V1: `docs/superpowers/specs/2026-11-21-road-corridor-design.md` and `docs/superpowers/plans/2026-11-21-road-corridor.md`.

**Conventions to keep:**
- Section coordinates: `u` positive to the LEFT of travel, `v` up from the profile grade line. Cross slopes negative down, outward from the crown. A ratio is horizontal per vertical (4.0 is 4:1).
- Survey points are `(northing, easting, elevation)`; `bimforge.author.sweep.to_model(origin, n, e, z)` is the only conversion to the model frame.
- The model is in US survey feet; the IFC is in metres. `emit_ifc` converts every length, area and volume, and every `BIMForge_Dimensions` length; families never convert.
- Every new key is optional. A spec without them builds V1's geometry, quantities and GlobalIds exactly (`test_road_corridor_v1.py`, Task 1). V1.1 *adds* to every corridor element a class reference, `BIMForge_Dimensions` and a `Length` Formula, all written after `emit_ifc`'s GlobalId sweep, so nothing V1 wrote is renumbered.
- A side's line has a fixed vertex count for its configuration (with rock, the bench collapses when the cut does not reach rock), and every side is padded to `SIDE_SAMPLES`, so `Section.earthwork_line()` has the same count at every station whatever the side is: slope, guarded slope, rock cut or wall.
- `Element.standard_qto` is written only on the class it is for (`emit_ifc`'s `own_class`); `Qto_BaseQuantities` stays the authoritative set consumers read.
- A station is a length along the alignment: `StartStation`/`EndStation` are `IfcLengthMeasure` with `StartStationText`/`EndStationText` (`IfcLabel`) twins.
- A Formula is written only where the family has checked it holds within `gate.FORMULA_TOLERANCE`; the post gate recomputes every one.
- Run tests from the worktree root: `python -m pytest <path> -q`.
- Every commit message ends, after a blank line, with:
  ```
  Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
  ```

---

## File structure

| File | Responsibility |
|---|---|
| Create `bimforge/author/tests/fixtures/road-corridor-v1/` (`road-corridor.spec.yaml`, `road-corridor.paycodes.yaml`, `globalids.json`, `volumes.json`, `masshaul.csv`) | The V1 example and what it built, frozen before V1.1 changes the example |
| Create `bimforge/author/tests/test_road_corridor_v1.py` | V1 builds unchanged: GlobalIds, volumes, mass haul |
| Modify `bimforge/author/corridor/params.py` | `Steep`, `Rock`, `Guard`; `Slopes.steep/rock/footprint`; `Gap.auto`; `Corridor.auto_walls/max_wall_height/guard`, `with_walls()`, `etw()`, the cut-wall shoulder widening in `width()` |
| Modify `bimforge/author/corridor/section.py` | `NoDaylight`, `Side.guarded/ratio`, the steep fill and its widening, the rock bench, the footprint, a wall at the hinge, `grade_edge()`, `needs_wall()` |
| Create `bimforge/author/corridor/walls.py` | `find()` (wall gaps from failing stations), `rows()`, `structures()`, their CSVs |
| Create `bimforge/author/corridor/guardrail.py` | Length of need, `lay_out()` runs, the W-beam `band()`, the CSV |
| Create `bimforge/author/corridor/dimensions.py` | Dictionary class codes, `stations()`, the Formulas |
| Modify `bimforge/author/corridor/earthwork.py` | `plan_area_sf()` |
| Modify `bimforge/author/families/road_corridor.py` | Walls first, then the V1 build, rails, tables, dimensions and Formulas |
| Modify `bimforge/author/model.py` | `StructureModel.tables`; `standard_qto` may carry a Formula |
| Modify `bimforge/author/emit_ifc.py` | A standard quantity's Formula; text and optional dimensions |
| Modify `bimforge/author/gate.py` | Formula grammar: one difference, names from the element's `BIMForge_Dimensions` |
| Modify `bimforge/author/family_dictionary.py` | Text dimensions (`IfcLabel`), `required_dimensions()` |
| Modify `bimforge/author/dictionary/bimforge-families.bsdd.json` | Four corridor classes, twelve properties |
| Modify `bimforge/bim/model_elements.py` | Station texts in `BIMForge_Dimensions` are skipped, not warned about |
| Modify `bimforge/author/families/registry.py` | `walls`, `structures`, `guardrail` outputs and their errors |
| Modify `bimforge/author/examples/road-corridor.spec.yaml`, `road-corridor.paycodes.yaml` | Guarded fill, rock cut, an automatic wall, guardrail |
| Modify `bimforge/author/tests/fixtures/example_globalids.json`, `docs/ifc-inventory.json`, `docs/ifc-inventory.md`, `scripts/bsi_baseline.yaml` (only if a new finding is accepted) | Re-recorded for the example |
| Create tests `test_corridor_walls.py`, `test_corridor_guardrail.py`; modify `test_corridor_params.py`, `test_corridor_section.py`, `test_corridor_earthwork.py`, `test_road_corridor.py`, `test_emit.py`, `test_dictionary.py`, `test_registry.py` | Unit and integration tests |
| Modify `CHANGELOG.md` | Unreleased > Added |

---

### Task 1: Pin the V1 build

The example changes in Task 12, so freeze it now, with what it builds, and test that the frozen copy keeps building the same thing through every later task.

**Files:**
- Create: `bimforge/author/tests/fixtures/road-corridor-v1/road-corridor.spec.yaml`, `road-corridor.paycodes.yaml`, `globalids.json`, `volumes.json`, `masshaul.csv`
- Create: `bimforge/author/tests/test_road_corridor_v1.py`

- [ ] **Step 1: Record the fixture** (from the worktree root):

```bash
python - <<'PY'
import contextlib, io, json, shutil, tempfile
from pathlib import Path
import ifcopenshell
import ifcopenshell.util.element as E
from bimforge.author.families.registry import build_from_spec
fx = Path("bimforge/author/tests/fixtures/road-corridor-v1")
fx.mkdir(parents=True, exist_ok=False)
for name in ("road-corridor.spec.yaml", "road-corridor.paycodes.yaml"):
    shutil.copy(Path("bimforge/author/examples") / name, fx / name)
recorded = json.loads(Path("bimforge/author/tests/fixtures/example_globalids.json")
                      .read_text("utf-8"))["road-corridor"]
(fx / "globalids.json").write_text(json.dumps(recorded, indent=1, sort_keys=True) + "\n",
                                   "utf-8")
tmp = Path(tempfile.mkdtemp())
for p in fx.glob("*.yaml"):
    shutil.copy(p, tmp / p.name)
with contextlib.redirect_stderr(io.StringIO()):
    assert build_from_spec(str(tmp / "road-corridor.spec.yaml")) == 0
f = ifcopenshell.open(str(tmp / "out" / "road-corridor.ifc"))
vols = {}
for el in f.by_type("IfcElement"):
    base = E.get_psets(el, qtos_only=True).get("Qto_BaseQuantities", {})
    if "GrossVolume" in base:
        vols[el.Name] = base["GrossVolume"]
(fx / "volumes.json").write_text(json.dumps(vols, indent=1, sort_keys=True) + "\n", "utf-8")
shutil.copy(tmp / "out" / "road-corridor.masshaul.csv", fx / "masshaul.csv")
print(len(recorded["elements"]), "elements,", len(vols), "volumes")
PY
```

Expected: `79 elements,` followed by the number of elements with a GrossVolume. `globalids.json` is the `road-corridor` block of `example_globalids.json` exactly.

- [ ] **Step 2: Write the test** `bimforge/author/tests/test_road_corridor_v1.py`

```python
"""The V1 road corridor builds as it did before V1.1 (P.6).

fixtures/road-corridor-v1/ holds the shipped example as V1 shipped it, its
spec and paycodes copied before V1.1 changed the example, and what it built
then: every element's and root's GlobalId, every element's
Qto_BaseQuantities GrossVolume, and the mass-haul CSV. V1.1's keys are all
optional: without them the corridor builds the same bodies, the same
quantities and the same GlobalIds. V1.1 may ADD roots (the dimension sets
and the class references, written after the GlobalId sweep); it may not
move or drop one, and it adds no element.
"""
from __future__ import annotations

import contextlib
import io
import json
import shutil
from pathlib import Path

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

FIXTURE = Path(__file__).parent / "fixtures" / "road-corridor-v1"
SPEC = "road-corridor.spec.yaml"


def _recorded(name: str):
    return json.loads((FIXTURE / name).read_text("utf-8"))


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    from bimforge.author.families.registry import build_from_spec
    tmp = tmp_path_factory.mktemp("v1")
    for name in (SPEC, "road-corridor.paycodes.yaml"):
        shutil.copy(FIXTURE / name, tmp / name)
    with contextlib.redirect_stderr(io.StringIO()):
        assert build_from_spec(str(tmp / SPEC)) == 0
    return ifcopenshell.open(str(tmp / "out" / "road-corridor.ifc")), tmp / "out"


def test_every_v1_element_keeps_its_globalid(built):
    f, _out = built
    was = _recorded("globalids.json")["elements"]
    now = {el.Name: el.GlobalId for el in f.by_type("IfcElement")}
    assert {n: now.get(n) for n in was} == was
    assert set(now) == set(was)                  # and no element is added


def test_every_v1_root_keeps_its_globalid(built):
    f, _out = built
    moved = {}
    for gid, cls in _recorded("globalids.json")["roots"].items():
        try:
            ent = f.by_guid(gid)
        except RuntimeError:
            moved[gid] = (cls, None)
            continue
        if ent.is_a() != cls:
            moved[gid] = (cls, ent.is_a())
    assert not moved, f"{len(moved)} V1 root(s) moved or dropped: {moved}"


def test_every_v1_volume_is_unchanged(built):
    import ifcopenshell.util.element as E
    f, _out = built
    was = _recorded("volumes.json")
    now = {}
    for el in f.by_type("IfcElement"):
        base = E.get_psets(el, qtos_only=True).get("Qto_BaseQuantities", {})
        if "GrossVolume" in base:
            now[el.Name] = base["GrossVolume"]
    assert set(now) == set(was)
    for name, v in was.items():
        assert now[name] == pytest.approx(v, rel=1e-9), name


def test_the_v1_mass_haul_is_unchanged(built):
    _f, out = built
    assert (out / "road-corridor.masshaul.csv").read_text("utf-8") == (
        FIXTURE / "masshaul.csv").read_text("utf-8")
```

- [ ] **Step 3: Run it**

Run: `python -m pytest bimforge/author/tests/test_road_corridor_v1.py -q`
Expected: 4 passed. It pins today's output, so it passes before any V1.1 code exists. To see it bite, change `shrink: 0.10` to `shrink: 0.11` in the fixture spec and rerun: `test_the_v1_mass_haul_is_unchanged` FAILS. Put `0.10` back.

- [ ] **Step 4: Commit**

```bash
git add bimforge/author/tests/fixtures/road-corridor-v1 bimforge/author/tests/test_road_corridor_v1.py
git commit -F - <<'EOF'
road corridor: pin the V1 build before V1.1 (P.6)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

### Task 2: Params for the V1.1 keys

**Files:**
- Modify: `bimforge/author/corridor/params.py`
- Test: `bimforge/author/tests/test_corridor_params.py`

Where the keys sit (the spec's format block is abbreviated): `side_slopes` stays under `section` as in V1, with `fill.steep`, `cut.rock` and `footprint_ft` inside it; `walls`, `max_wall_height_ft` and `guardrail` are top-level params beside `gaps`.

- [ ] **Step 1: Write the failing tests** (append to `bimforge/author/tests/test_corridor_params.py`)

```python
from bimforge.author.corridor.params import (CUT_WALL_SHOULDER_FT, Gap, Guard,
                                             Rock, Steep)

STEEP_FILL = {"ratio": 4.0, "steep": {"ratio": 2.0, "above_height_ft": 10.0}}
ROCK_CUT = {"ratio": 2.0, "ditch": {"width": 4.0, "depth": 1.5},
            "rock": {"depth_ft": 8.0, "ratio": 0.5, "bench_ft": 6.0}}


def slopes(**ss):
    """BASE with side_slopes keys replaced."""
    p = copy.deepcopy(BASE)
    p["section"]["side_slopes"].update(copy.deepcopy(ss))
    return p


def test_without_the_v11_keys_a_corridor_is_v1():
    c = parse(params(), 1000.0, 2000.0)
    assert (c.slopes.steep, c.slopes.rock, c.slopes.footprint) == (None, None, None)
    assert (c.auto_walls, c.max_wall_height, c.guard) == (False, 30.0, None)


def test_a_steep_rule_brings_a_guardrail_at_its_defaults():
    c = parse(slopes(fill=STEEP_FILL), 1000.0, 2000.0)
    assert c.slopes.fill_ratio == 4.0
    assert c.slopes.steep == Steep(ratio=2.0, above_height=10.0)
    assert c.guard == Guard(speed_mph=45, rail_depth=1.44)
    # the hinge 30 in behind the back of post: 1.44 + 2.5 = 3.94 ft from
    # the rail face
    assert c.guard.widening == pytest.approx(3.94)


def test_a_guardrail_block_sets_its_speed_and_depth():
    p = slopes(fill=STEEP_FILL)
    p["guardrail"] = {"design_speed_mph": 50, "rail_depth_ft": 1.77}
    assert parse(p, 1000.0, 2000.0).guard == Guard(speed_mph=50, rail_depth=1.77)


def test_rock_depth_is_one_value_or_rows_by_station():
    c = parse(slopes(cut=ROCK_CUT), 1000.0, 2000.0)
    assert c.slopes.rock == Rock(depth=((1000.0, 8.0),), ratio=0.5, bench=6.0)
    assert c.slopes.rock.depth_at(1500.0) == 8.0
    rows = copy.deepcopy(ROCK_CUT)
    rows["rock"]["depth_ft"] = [[1200, 8.0], [1600, 12.0]]
    rock = parse(slopes(cut=rows), 1000.0, 2000.0).slopes.rock
    # 14+00 is halfway from 12+00 (8 ft) to 16+00 (12 ft): 10 ft; the end
    # values hold outside the rows
    assert (rock.depth_at(1400.0), rock.depth_at(1100.0),
            rock.depth_at(1900.0)) == (10.0, 8.0, 12.0)


def test_walls_auto_the_footprint_and_the_wall_height():
    p = slopes(footprint_ft={"L": 120, "R": 100})
    p.update(walls="auto", max_wall_height_ft=25)
    c = parse(p, 1000.0, 2000.0)
    assert c.slopes.footprint == {"L": 120.0, "R": 100.0}
    assert (c.auto_walls, c.max_wall_height) == (True, 25.0)


def test_a_cut_wall_widens_its_shoulder_to_10_ft_over_a_1_ft_lead_in():
    c = parse(params(walls="auto"), 1000.0, 2000.0).with_walls(
        [Gap(1400.0, 1600.0, "wall", "L", None, auto="cut")])
    lane, shoulder = c.components
    assert CUT_WALL_SHOULDER_FT == 10.0
    assert c.wall("L", 1500.0).auto == "cut"
    assert c.wall("L", 1500.0).offset is None
    # 10 ft through the wall; halfway through each 1 ft lead-in, 7.5 ft
    # (5 + (10 - 5) x 0.5); 1 ft outside each end, the 5 ft shoulder again
    assert [c.width(shoulder, "L", s)
            for s in (1399.0, 1399.5, 1400.0, 1500.0, 1600.0, 1600.5, 1601.0)
            ] == pytest.approx([5.0, 7.5, 10.0, 10.0, 10.0, 7.5, 5.0])
    assert c.width(shoulder, "R", 1500.0) == 5.0
    assert c.width(lane, "L", 1500.0) == 12.0
    assert c.etw("L", 1500.0) == 12.0
    # the wall's ends and 1 ft outside them are stations, as a listed wall's
    assert c.stations(1350.0, 1650.0) == [
        1350.0, 1375.0, 1399.0, 1400.0, 1425.0, 1450.0, 1475.0, 1500.0,
        1525.0, 1550.0, 1575.0, 1600.0, 1601.0, 1625.0, 1650.0]


def test_a_fill_wall_leaves_the_shoulder_alone():
    c = parse(params(walls="auto"), 1000.0, 2000.0).with_walls(
        [Gap(1400.0, 1600.0, "wall", "R", None, auto="fill")])
    assert c.width(c.components[1], "R", 1500.0) == 5.0


def test_an_automatic_wall_against_a_listed_one_is_refused():
    c = parse(params(walls="auto", gaps=[{"from": 1100, "to": 1300, "kind": "wall",
                                          "side": "L", "offset": 30}]), 1000.0, 2000.0)
    # 13+00.50's lead-in, 12+99.50, is inside the listed wall
    with pytest.raises(ValueError, match=r"walls: auto puts a fill wall on the L "
                       r"side from 13\+00\.50 to 14\+00\.00, against the listed "
                       r"wall gap 11\+00\.00 to 13\+00\.00"):
        c.with_walls([Gap(1300.5, 1400.0, "wall", "L", None, auto="fill")])
    c.with_walls([Gap(1300.5, 1400.0, "wall", "R", None, auto="fill")])  # the other side


def test_a_cut_wall_needs_a_shoulder_to_widen():
    p = params(walls="auto")
    p["section"]["components"] = [{"name": "lane", "kind": "carriageway", "width": 12.0}]
    c = parse(p, 1000.0, 2000.0)
    with pytest.raises(ValueError, match="needs a shoulder component"):
        c.with_walls([Gap(1400.0, 1600.0, "wall", "L", None, auto="cut")])


@pytest.mark.parametrize("p, match", [
    (slopes(fill={"ratio": 4.0, "steep": {"ratio": 4.0, "above_height_ft": 10.0}}),
     r"steep\.ratio: 4 is not steeper than fill\.ratio 4"),
    (slopes(fill={"ratio": 4.0, "steep": {"ratio": 2.0, "above_height_ft": 0.0}}),
     r"steep\.above_height_ft: must be positive"),
    (slopes(fill={"ratio": 4.0, "steep": {"ratio": 2.0,
                                          "above_height_ft": float("inf")}}),
     r"steep\.above_height_ft: expected a finite number"),
    (slopes(cut={**ROCK_CUT, "rock": {"depth_ft": 8.0, "ratio": 2.0, "bench_ft": 6.0}}),
     r"rock\.ratio: 2 is not steeper than cut\.ratio 2"),
    (slopes(cut={**ROCK_CUT, "rock": {"depth_ft": -1.0, "ratio": 0.5, "bench_ft": 6.0}}),
     r"rock\.depth_ft: must be positive"),
    (slopes(cut={**ROCK_CUT, "rock": {"depth_ft": 8.0, "ratio": 0.5, "bench_ft": 0.0}}),
     r"rock\.bench_ft: must be positive"),
    (slopes(cut={**ROCK_CUT, "rock": {"depth_ft": [[3000, 8.0]], "ratio": 0.5,
                                      "bench_ft": 6.0}}), "off the alignment"),
    (slopes(cut={**ROCK_CUT, "rock": {"depth_ft": [[1500, 8.0], [1200, 9.0]],
                                      "ratio": 0.5, "bench_ft": 6.0}}),
     "strictly ascending"),
    (slopes(footprint_ft={"L": 0.0}), r"footprint_ft\.L: must be positive"),
    (slopes(footprint_ft={"X": 10.0}), r"footprint_ft: a mapping of L and R"),
    (params(max_wall_height_ft=float("nan")), r"max_wall_height_ft: expected a finite"),
    (params(max_wall_height_ft=0), r"max_wall_height_ft: must be positive"),
    (params(walls="yes"), r"walls: 'yes' is not 'auto'"),
    (params(walls=[{"from": 1100, "to": 1200}]), r"walls: .* is not 'auto'"),
    (params(guardrail={"design_speed_mph": 55}),
     r"design_speed_mph: 55 mph is not in the runout table \(45, 50 mph\)"),
    (params(guardrail={"rail_depth_ft": 0}), r"rail_depth_ft: must be positive"),
])
def test_bad_v11_params_are_refused(p, match):
    with pytest.raises(ValueError, match=match):
        parse(p, 1000.0, 2000.0)
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_corridor_params.py -q`
Expected: collection ERROR, `ImportError: cannot import name 'CUT_WALL_SHOULDER_FT'`.

- [ ] **Step 3: Implement** in `bimforge/author/corridor/params.py`.

Change the imports at the top to:

```python
import math
from dataclasses import dataclass, replace

from bimforge.author.alignment import sta
```

After `WALL_TRANSITION_FT = 1.0` add:

```python
#: the shoulder beside a wall in cut, feet (HDM Index 309.1(3)(b))
CUT_WALL_SHOULDER_FT = 10.0
#: guardrail runout length LR by design speed, feet (TSSM length-of-need
#: calculator, "Tables")
RUNOUT_FT = {45: 195.0, 50: 230.0}
#: MGS rail face to back of post: the 3 1/4 in W-beam, the 6 x 8 in block
#: holding the rail 8 in off the post, and a W6 post (2025 Standard Plans
#: A77N2, A77N3), feet
RAIL_DEPTH_FT = 1.44
#: back of post to the hinge, 30 in at least (A77N3 Detail A), feet
HINGE_BEHIND_POST_FT = 2.5
#: the widening behind the rail falls 1 in 10 (TSSM 3.6(5))
WIDENING_SLOPE = 0.1
```

Replace the `Slopes` dataclass with these four:

```python
@dataclass(frozen=True)
class Steep:
    """Fill steeper than `Slopes.fill_ratio` over a height, behind guardrail."""
    ratio: float                   # horizontal per vertical, e.g. 2.0
    above_height: float            # fill at the hinge over this takes it, feet


@dataclass(frozen=True)
class Rock:
    """Rock under the soil in cut: its face, a bench at its surface."""
    depth: tuple                   # ((station, depth below ground), ...)
    ratio: float                   # the rock face, horizontal per vertical
    bench: float                   # the level bench's width, feet

    def depth_at(self, s: float) -> float:
        return interp(list(self.depth), s)


@dataclass(frozen=True)
class Guard:
    """The guardrail a steep fill takes (TSSM 3.6, A77N3)."""
    speed_mph: int                 # a RUNOUT_FT key
    rail_depth: float              # rail face to back of post, feet

    @property
    def widening(self) -> float:
        """Rail face to the hinge behind the post, feet."""
        return self.rail_depth + HINGE_BEHIND_POST_FT


@dataclass(frozen=True)
class Slopes:
    cut_ratio: float               # horizontal per vertical
    fill_ratio: float
    ditch: Ditch | None
    daylight_limit: float          # horizontal feet from the hinge
    steep: Steep | None = None     # V1.1: 2:1 behind guardrail over a height
    rock: Rock | None = None       # V1.1: rock in cut, with a bench
    footprint: dict | None = None  # V1.1: side -> farthest daylight, feet
```

Replace the `Gap` dataclass with:

```python
@dataclass(frozen=True)
class Gap:
    start: float
    end: float
    kind: str                      # "structure" or "wall"
    side: str | None = None        # a wall's side
    offset: float | None = None    # a listed wall's face, feet from the
                                   # centreline; None: at the hinge
    auto: str | None = None        # an automatic wall's kind: "fill", "cut"
```

Replace the whole `Corridor` class with:

```python
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
    #: V1.1: walls wherever a slope cannot fit (`walls: auto`)
    auto_walls: bool = False
    #: a fill wall taller than this is a structure candidate, feet
    max_wall_height: float = 30.0
    #: the guardrail a steep fill takes; None without a steep rule or a
    #: `guardrail:` block
    guard: Guard | None = None

    def width(self, comp: Component, side: str, s: float) -> float:
        """The component's width; through an automatic cut wall the
        outermost shoulder is CUT_WALL_SHOULDER_FT, reached linearly over
        the WALL_TRANSITION_FT lead-in at each end (HDM 309.1(3)(b))."""
        table = self.widths.get((comp.name, side))
        w = interp(table, s) if table else comp.width
        if not self.auto_walls or comp.name != self._widened():
            return w
        for g in self.gaps:
            if g.auto != "cut" or g.side != side:
                continue
            a, b = g.start - WALL_TRANSITION_FT, g.end + WALL_TRANSITION_FT
            if not a - _EPS <= s <= b + _EPS:
                continue
            full = max(w, CUT_WALL_SHOULDER_FT)
            if s < g.start:
                return w + (full - w) * (s - a) / WALL_TRANSITION_FT
            if s > g.end:
                return w + (full - w) * (b - s) / WALL_TRANSITION_FT
            return full
        return w

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

    def etw(self, side: str, s: float) -> float:
        """The edge of traveled way: the outer edge of the outermost
        carriageway component, feet from the crown."""
        out = edge = 0.0
        for comp in self.components:
            out += self.width(comp, side, s)
            if comp.kind == "carriageway":
                edge = out
        return edge

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

    def _widened(self) -> str | None:
        """The component a cut wall widens: the outermost shoulder."""
        names = [comp.name for comp in self.components if comp.kind == "shoulder"]
        return names[-1] if names else None

    def with_walls(self, walls) -> "Corridor":
        """This corridor with automatic wall gaps (`walls: auto`) added. A
        wall whose stations, its 1 ft lead-ins included, touch a listed wall
        gap on its side is refused, as is a cut wall with no shoulder to
        widen beside it."""
        walls = tuple(walls)
        for w in walls:
            for g in self.gaps:
                if (g.kind == "wall" and g.auto is None and g.side == w.side
                        and w.start - WALL_TRANSITION_FT < g.end + _EPS
                        and g.start - _EPS < w.end + WALL_TRANSITION_FT):
                    raise ValueError(
                        f"walls: auto puts a {w.auto} wall on the {w.side} side "
                        f"from {sta(w.start)} to {sta(w.end)}, against the "
                        f"listed wall gap {sta(g.start)} to {sta(g.end)}; list "
                        f"the wall or let walls: auto place it, not both")
            if w.auto == "cut" and self._widened() is None:
                raise ValueError(
                    f"walls: auto puts a cut wall on the {w.side} side from "
                    f"{sta(w.start)} to {sta(w.end)}; the 10 ft shoulder beside "
                    f"it needs a shoulder component to widen")
        return replace(self, gaps=tuple(sorted(self.gaps + walls,
                                               key=lambda g: (g.start, g.side or ""))))
```

Replace `_slopes` with:

```python
def _slopes(sec: dict, s_start: float, s_end: float) -> Slopes:
    ss = sec.get("side_slopes") or {}
    cut, fill = ss.get("cut") or {}, ss.get("fill") or {}
    ditch = None
    if cut.get("ditch"):
        d = cut["ditch"]
        width = _num(d.get("width"), "side_slopes.cut.ditch.width", positive=False)
        if width < 0.0:
            raise ValueError("side_slopes.cut.ditch.width: must not be negative")
        ditch = Ditch(width, _num(d.get("depth"), "side_slopes.cut.ditch.depth"))
    cut_ratio = _num(cut.get("ratio", 2.0), "side_slopes.cut.ratio")
    fill_ratio = _num(fill.get("ratio", 2.0), "side_slopes.fill.ratio")
    steep = None
    if fill.get("steep") is not None:
        st = fill["steep"]
        steep = Steep(_num(st.get("ratio"), "side_slopes.fill.steep.ratio"),
                      _num(st.get("above_height_ft"),
                           "side_slopes.fill.steep.above_height_ft"))
        if not steep.ratio < fill_ratio:
            raise ValueError(f"side_slopes.fill.steep.ratio: {steep.ratio:g} is "
                             f"not steeper than fill.ratio {fill_ratio:g}")
    rock = None
    if cut.get("rock") is not None:
        rk = cut["rock"]
        rock = Rock(_depth_rows(rk.get("depth_ft"), s_start, s_end),
                    _num(rk.get("ratio"), "side_slopes.cut.rock.ratio"),
                    _num(rk.get("bench_ft"), "side_slopes.cut.rock.bench_ft"))
        if not rock.ratio < cut_ratio:
            raise ValueError(f"side_slopes.cut.rock.ratio: {rock.ratio:g} is "
                             f"not steeper than cut.ratio {cut_ratio:g}")
    footprint = None
    if ss.get("footprint_ft") is not None:
        fp = ss["footprint_ft"]
        if not isinstance(fp, dict) or not set(fp) <= set(SIDES):
            raise ValueError("side_slopes.footprint_ft: a mapping of L and R "
                             "offsets from the centreline, feet")
        footprint = {side: _num(fp[side], f"side_slopes.footprint_ft.{side}")
                     for side in SIDES if side in fp}
    return Slopes(cut_ratio, fill_ratio, ditch,
                  _num(ss.get("daylight_limit_ft", 150.0),
                       "side_slopes.daylight_limit_ft"),
                  steep=steep, rock=rock, footprint=footprint)


def _depth_rows(value, s_start: float, s_end: float) -> tuple:
    """Rock depth: one number, or [station, depth] rows on the alignment
    (read as widths are: linear, the end values holding)."""
    where = "side_slopes.cut.rock.depth_ft"
    if isinstance(value, (list, tuple)):
        rows = tuple((_on_alignment(s, where, s_start, s_end), _num(d, where))
                     for s, d in (_row(r, 2, where, "[station, depth]")
                                  for r in value))
        if not rows:
            raise ValueError(f"{where}: needs [station, depth] rows")
        _ascending([s for s, _d in rows], where)
        return rows
    return ((float(s_start), _num(value, where)),)


def _guard(gp, steep: bool) -> Guard | None:
    """The `guardrail:` block; a steep rule brings one at its defaults."""
    if gp is None and not steep:
        return None
    gp = gp or {}
    if not isinstance(gp, dict):
        raise ValueError("guardrail: a mapping ({design_speed_mph: 45})")
    speed = _num(gp.get("design_speed_mph", 45), "guardrail.design_speed_mph")
    if speed not in RUNOUT_FT:
        raise ValueError(f"guardrail.design_speed_mph: {speed:g} mph is not in "
                         f"the runout table ({', '.join(str(k) for k in RUNOUT_FT)} mph)")
    return Guard(int(speed), _num(gp.get("rail_depth_ft", RAIL_DEPTH_FT),
                                  "guardrail.rail_depth_ft"))
```

In `parse`, replace the final `return Corridor(...)` with:

```python
    slopes = _slopes(sec, s_start, s_end)
    walls = params.get("walls")
    if walls is not None and walls != "auto":
        raise ValueError(f"walls: {walls!r} is not 'auto'; a wall at stations "
                         f"you choose is a gap (gaps: [{{kind: wall, side, "
                         f"offset, from, to}}])")
    return Corridor(
        s_start=float(s_start), s_end=float(s_end),
        components=tuple(comps), courses=tuple(_courses(sec)),
        slopes=slopes,
        widths=_widths(params, [c.name for c in comps], s_start, s_end),
        superelevation=tuple(_superelevation(params, s_start, s_end)),
        gaps=tuple(_gaps(params, s_start, s_end)),
        interval=_num(st.get("interval", 25.0), "stations.interval"),
        band=_num(st.get("band", 100.0), "stations.band"),
        shrink=shrink, swell=swell,
        auto_walls=walls == "auto",
        max_wall_height=_num(params.get("max_wall_height_ft", 30.0),
                             "max_wall_height_ft"),
        guard=_guard(params.get("guardrail"), slopes.steep is not None))
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_corridor_params.py bimforge/author/tests/test_corridor_section.py bimforge/author/tests/test_road_corridor_v1.py -q`
Expected: PASS (the section tests and the V1 pin show V1 is untouched).

- [ ] **Step 5: Commit**

```bash
git add bimforge/author/corridor/params.py bimforge/author/tests/test_corridor_params.py
git commit -F - <<'EOF'
road corridor params: steep fill, rock, footprint, walls auto, guardrail (P.6 V1.1)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

### Task 3: Section resolver: the steep fill rule, the guarded widening, the footprint

**Files:**
- Modify: `bimforge/author/corridor/section.py`
- Test: `bimforge/author/tests/test_corridor_section.py`

- [ ] **Step 1: Write the failing tests** (append to `bimforge/author/tests/test_corridor_section.py`)

```python
from bimforge.author.corridor.section import (GUARD_STEP_FT, NoDaylight,
                                              grade_edge, needs_wall)

STEEP_FILL = {"ratio": 4.0, "steep": {"ratio": 2.0, "above_height_ft": 10.0}}


def sloped(fill=None, cut=None, footprint=None, **over):
    """A corridor on BASE with its side slopes changed."""
    p = copy.deepcopy(BASE)
    ss = p["section"]["side_slopes"]
    if fill is not None:
        ss["fill"] = copy.deepcopy(fill)
    if cut is not None:
        ss["cut"] = copy.deepcopy(cut)
    if footprint is not None:
        ss["footprint_ft"] = dict(footprint)
    p.update(over)
    return parse(p, 0.0, 2000.0)


def test_the_shoulder_edge_is_the_grade_s_outer_point():
    assert grade_edge(corridor(), 500.0, "R") == pytest.approx((-17.0, -0.49))


def test_fill_under_the_height_limit_takes_4_to_1():
    # 3.11 ft of fill at the hinge (17, -1.89) over ground at -5: not over
    # 10 ft, so 4:1, falling 3.11 ft in 4 x 3.11 = 12.44 ft: (29.44, -5)
    sec = resolve(sloped(fill=STEEP_FILL), 500.0, level(-5.0))
    side = sec.sides["L"]
    assert (side.kind, side.guarded, side.ratio) == ("fill", False, 4.0)
    assert flat(side.line) == pytest.approx(flat([(17, -1.89), (29.44, -5.0)]))


def test_fill_over_the_height_limit_takes_2_to_1_behind_the_rail_s_widening():
    # 13.11 ft of fill at the hinge over ground at -15: over 10, so 2:1 and
    # guarded. The rail face is at the shoulder edge (17, -0.49); the
    # widening falls 1 in 10 to the hinge 1.44 + 2.5 = 3.94 ft out:
    # (20.94, -0.49 - 0.394) = (20.94, -0.884). Its first point is 0.01 ft
    # out, on the widening: (17.01, -0.491). From the widening's hinge 2:1
    # falls 14.116 ft in 28.232 ft: daylight (49.172, -15)
    sec = resolve(sloped(fill=STEEP_FILL), 500.0, level(-15.0))
    side = sec.sides["L"]
    assert (side.kind, side.guarded, side.ratio) == ("fill", True, 2.0)
    assert GUARD_STEP_FT == 0.01
    assert flat(side.line) == pytest.approx(flat(
        [(17, -1.89), (17.01, -0.491), (20.94, -0.884), (49.172, -15.0)]))
    assert flat(sec.sides["R"].line[-1:]) == pytest.approx([-49.172, -15.0])
    assert len(sec.earthwork_line()) == 2 * SIDE_SAMPLES - 1 + 2 * 2


def test_without_a_steep_rule_fill_keeps_its_one_ratio():
    # V1: 2:1 from the hinge, 13.11 ft in 26.22 ft: (43.22, -15)
    side = resolve(corridor(), 500.0, level(-15.0)).sides["L"]
    assert (side.kind, side.guarded, side.ratio) == ("fill", False, 2.0)
    assert flat(side.line) == pytest.approx(flat([(17, -1.89), (43.22, -15.0)]))


def test_a_daylight_past_the_footprint_is_refused():
    # the 2:1 daylights at 43.22 ft, past a 40 ft footprint on the left
    with pytest.raises(NoDaylight, match=r"5\+00\.00: the L fill slope daylights "
                       r"43\.22 ft out, past the L footprint of 40 ft") as exc:
        resolve(sloped(footprint={"L": 40.0}), 500.0, level(-15.0))
    assert exc.value.kind == "fill"
    assert isinstance(exc.value, ValueError)
    # inside it, the same section builds
    resolve(sloped(footprint={"L": 44.0}), 500.0, level(-15.0))


def test_needs_wall_says_which_wall_a_side_needs():
    c = corridor()
    assert needs_wall(c, 500.0, "L", level(-5.0)) is None
    assert needs_wall(c, 500.0, "L", level(-500.0)) == "fill"
    # 500 ft of cut: the backslope from the ditch's edge (24, -3.39) needs
    # 2 x 503.39 ft, past the 143 ft left of the daylight limit
    assert needs_wall(c, 500.0, "L", level(500.0)) == "cut"
    # where a wall is listed, the side is that wall: it needs none
    walled = corridor(gaps=[{"from": 400, "to": 600, "kind": "wall", "side": "L",
                             "offset": 30.0}])
    assert needs_wall(walled, 500.0, "L", level(-500.0)) is None
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_corridor_section.py -q`
Expected: collection ERROR, `ImportError: cannot import name 'GUARD_STEP_FT'`.

- [ ] **Step 3: Implement** in `bimforge/author/corridor/section.py`.

Change the params import to:

```python
from bimforge.author.corridor.params import SIDES, WIDENING_SLOPE
```

Replace the `Side` dataclass with:

```python
#: a guarded side's widening starts this far outside the shoulder edge, so
#: the earthwork's face up the courses' outer edge is a slope and not a
#: vertical step (a step puts two columns on one plan edge, and the merged
#: earthwork skin is then two bodies touching along it), feet
GUARD_STEP_FT = 0.01


class NoDaylight(ValueError):
    """A side slope that does not fit: no ground within the daylight limit,
    or a daylight past the side's footprint. `kind` is the side's kind at
    its hinge, "cut" or "fill": the wall `walls: auto` puts there."""

    def __init__(self, message: str, kind: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class Side:
    kind: str           # "cut", "fill" or "wall"
    line: list          # [(u, v)] from the hinge out to daylight or the wall
    guarded: bool = False          # V1.1: a steep fill behind guardrail
    ratio: float | None = None     # V1.1: the slope it runs at; None on a wall
```

Replace the whole `_side` function with:

```python
def _side(c, s: float, side: str, sign: float, hinge: tuple, ground_dz) -> Side:
    hu, hv = hinge
    # each side reads its own wall, so walls on both sides at one station
    # each end their own side
    wall = c.wall(side, s)
    if wall is not None:
        if wall.offset < abs(hu):
            raise ValueError(
                f"station {sta(s)}: the {side} wall at offset {wall.offset:g} ft "
                f"is inside the hinge at {abs(hu):g} ft")
        return Side("wall", [hinge, (sign * wall.offset, hv)])
    return _slope(c, s, side, sign, hinge, ground_dz)


def _slope(c, s: float, side: str, sign: float, hinge: tuple, ground_dz) -> Side:
    """The side's slope from `hinge` out to daylight: cut (the ditch, then
    the backslope) or fill (V1.1: 2:1 behind the rail's widening where the
    fill at the hinge is over the steep rule's height). NoDaylight when it
    finds no ground within the limit or daylights past the footprint."""
    hu, hv = hinge
    sl = c.slopes
    fill_ratio, guarded = sl.fill_ratio, False
    if ground_dz(s, hu, hv) > 0.0:
        kind, pts = "cut", [hinge]
        if sl.ditch is not None:
            p1 = (hu + sign * sl.cut_ratio * sl.ditch.depth, hv - sl.ditch.depth)
            pts += [p1, (p1[0] + sign * sl.ditch.width, p1[1])]
    else:
        kind, pts = "fill", [hinge]
        if sl.steep is not None and -ground_dz(s, hu, hv) > sl.steep.above_height:
            fill_ratio, guarded = sl.steep.ratio, True
            pts += _widening(c, s, side, sign)
    # up the backslope while the ground is above the slope's start; on a side
    # hill the ditch's outer edge can stand above the ground, and the side
    # then runs down at the fill ratio from there
    up = ground_dz(s, *pts[-1]) > 0.0
    rise = 1.0 / sl.cut_ratio if up else -1.0 / fill_ratio
    used = abs(pts[-1][0] - hu)
    day = _daylight(s, pts[-1], sign, rise, ground_dz,
                    sl.daylight_limit - used, cut=up)
    if day is None:
        raise NoDaylight(
            f"station {sta(s)}: the {side} {kind} slope finds no ground within "
            f"{sl.daylight_limit:g} ft of the hinge", kind)
    off = ground_dz(s, *day)
    if abs(off) > _ON_GROUND_FT:
        raise ValueError(
            f"station {sta(s)}: the {side} {kind} slope ends {abs(off):.2f} ft "
            f"off the ground at offset {abs(day[0]):.2f} ft (is the ground "
            f"continuous there?)")
    fp = (sl.footprint or {}).get(side)
    if fp is not None and abs(day[0]) > fp + 1e-9:
        raise NoDaylight(
            f"station {sta(s)}: the {side} {kind} slope daylights "
            f"{abs(day[0]):.2f} ft out, past the {side} footprint of {fp:g} ft",
            kind)
    return Side(kind, pts + [day], guarded,
                sl.cut_ratio if kind == "cut" else fill_ratio)


def _widening(c, s: float, side: str, sign: float) -> list:
    """A guarded side's two points past the hinge: GUARD_STEP_FT out from
    the shoulder edge, then the hinge `Guard.widening` behind the rail face
    (at the shoulder edge), both on the 10:1 (TSSM 3.6, A77N3 Detail A)."""
    eu, ev = grade_edge(c, s, side)
    return [(eu + sign * w, ev - WIDENING_SLOPE * w)
            for w in (GUARD_STEP_FT, c.guard.widening)]
```

After the `_grade` function add:

```python
def grade_edge(c, s: float, side: str) -> tuple:
    """(u, v) of the finished grade's outer edge, the shoulder edge, on
    `side` at station s: where a guardrail's face stands."""
    return _grade(c, s, side)[-1]


def needs_wall(c, s: float, side: str, ground_dz) -> str | None:
    """The wall `side` needs at station s, "cut" or "fill", when its slope
    does not fit (no daylight within the limit, or past the footprint);
    None when it fits, or where a wall gap already stands."""
    if c.wall(side, s) is not None:
        return None
    sign = 1.0 if side == "L" else -1.0
    u, v = grade_edge(c, s, side)
    try:
        _slope(c, s, side, sign, (u, v - c.depth()), _named(ground_dz, side))
    except NoDaylight as exc:
        return exc.kind
    return None
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_corridor_section.py bimforge/author/tests/test_road_corridor_v1.py -q`
Expected: PASS. The V1 section tests are unchanged: without a steep rule `fill_ratio` is V1's, and a side-hill cut still runs down at it.

- [ ] **Step 5: Commit**

```bash
git add bimforge/author/corridor/section.py bimforge/author/tests/test_corridor_section.py
git commit -F - <<'EOF'
road corridor section: 4:1 fill, 2:1 behind the rail's widening, the footprint (P.6 V1.1)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---
### Task 4: Section resolver: the rock cut and its bench

**Files:**
- Modify: `bimforge/author/corridor/section.py`
- Test: `bimforge/author/tests/test_corridor_section.py`

A cut side with `rock` always has the same vertices: hinge, the ditch's two points (when there is a ditch), the rock face's top, the bench's end, daylight. Where the cut does not reach rock the rock face and the bench collapse onto the toe of the cut (the ditch's outer edge), so the padded segment `_samples` divides is the soil slope at every station.

- [ ] **Step 1: Write the failing tests** (append to `bimforge/author/tests/test_corridor_section.py`)

```python
ROCK_CUT = {"ratio": 2.0, "ditch": {"width": 4.0, "depth": 1.5},
            "rock": {"depth_ft": 8.0, "ratio": 0.5, "bench_ft": 6.0}}


def test_a_cut_into_rock_benches_then_runs_soil_to_daylight():
    # ground 15 ft above the PGL, rock 8 ft under it, at v = 7. The ditch's
    # outer edge (24, -3.39) is 18.39 ft under ground, 10.39 ft into rock.
    # The rock face rises 2 per ft (0.5:1): 10.39 ft in 5.195 ft, to
    # (29.195, 7). The bench runs 6 ft level: (35.195, 7). The soil, 8 ft
    # deep, rises 1 in 2: 16 ft out, daylight (51.195, 15)
    sec = resolve(sloped(cut=ROCK_CUT), 500.0, level(15.0))
    side = sec.sides["L"]
    assert (side.kind, side.ratio) == ("cut", 2.0)
    assert flat(side.line) == pytest.approx(flat(
        [(17, -1.89), (20, -3.39), (24, -3.39), (29.195, 7.0), (35.195, 7.0),
         (51.195, 15.0)]))
    assert flat(sec.sides["R"].line[-1:]) == pytest.approx([-51.195, 15.0])


def test_a_cut_that_never_reaches_rock_collapses_its_bench_onto_the_toe():
    # ground 3 ft above: the ditch's edge is 6.39 ft under, inside the 8 ft
    # of soil. The rock face and the bench are points at the edge, and the
    # soil runs to V1's daylight: 6.39 ft up at 1 in 2, (36.78, 3)
    sec = resolve(sloped(cut=ROCK_CUT), 500.0, level(3.0))
    assert flat(sec.sides["L"].line) == pytest.approx(flat(
        [(17, -1.89), (20, -3.39), (24, -3.39), (24, -3.39), (24, -3.39),
         (36.78, 3.0)]))
    deep = resolve(sloped(cut=ROCK_CUT), 500.0, level(15.0))
    assert len(sec.earthwork_line()) == len(deep.earthwork_line())


def test_rock_depth_follows_its_rows():
    # [0, 8] to [2000, 12]: 10 ft at 10+00, rock at v = 15 - 10 = 5. The
    # rock face rises 8.39 ft from the ditch's edge in 4.195 ft: (28.195, 5);
    # the bench to (34.195, 5); 10 ft of soil at 1 in 2: (54.195, 15)
    cut = copy.deepcopy(ROCK_CUT)
    cut["rock"]["depth_ft"] = [[0, 8.0], [2000, 12.0]]
    sec = resolve(sloped(cut=cut), 1000.0, level(15.0))
    assert flat(sec.sides["L"].line) == pytest.approx(flat(
        [(17, -1.89), (20, -3.39), (24, -3.39), (28.195, 5.0), (34.195, 5.0),
         (54.195, 15.0)]))


def test_a_side_hill_rock_cut_whose_ditch_edge_is_above_ground_runs_fill_down():
    # as V1's side hill: the ditch edge (24, -3.39) is above the ground, so
    # not in rock; the bench collapses onto it and the side runs down 2:1
    sec = resolve(sloped(cut=ROCK_CUT), 500.0, side_hill)
    assert flat(sec.sides["L"].line) == pytest.approx(flat(
        [(17, -1.89), (20, -3.39), (24, -3.39), (24, -3.39), (24, -3.39),
         (26, -4.39)]))
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_corridor_section.py -q -k rock`
Expected: FAIL. The cut lines are V1's: no rock face, no bench (`(24, -3.39), (36.78, 3.0)` for the deep cut ends at V1's daylight).

- [ ] **Step 3: Implement** in `bimforge/author/corridor/section.py`. In `_slope`, replace:

```python
        if sl.ditch is not None:
            p1 = (hu + sign * sl.cut_ratio * sl.ditch.depth, hv - sl.ditch.depth)
            pts += [p1, (p1[0] + sign * sl.ditch.width, p1[1])]
    else:
```

with:

```python
        if sl.ditch is not None:
            p1 = (hu + sign * sl.cut_ratio * sl.ditch.depth, hv - sl.ditch.depth)
            pts += [p1, (p1[0] + sign * sl.ditch.width, p1[1])]
        if sl.rock is not None:
            pts += _rock(c, s, side, sign, pts[-1], ground_dz,
                         sl.daylight_limit - abs(pts[-1][0] - hu))
    else:
```

and after `_widening` add:

```python
def _rock(c, s: float, side: str, sign: float, toe: tuple, ground_dz,
          reach: float) -> list:
    """The rock face's top and the bench's end, out from the toe of the cut:
    the face at `rock.ratio` up to the rock surface (`rock.depth_at(s)`
    under the ground), then the bench level `rock.bench` ft. A toe that is
    not in rock gives the toe twice: the face and bench collapse onto it,
    so a rock cut has one vertex count at every station."""
    rock = c.slopes.rock
    depth = rock.depth_at(s)

    def in_rock(s_, u, v):
        return ground_dz(s_, u, v) - depth

    if in_rock(s, *toe) <= 0.0:
        return [toe, toe]
    top = _daylight(s, toe, sign, 1.0 / rock.ratio, in_rock, reach, cut=True)
    if top is None:
        raise NoDaylight(
            f"station {sta(s)}: the {side} cut's rock face finds no rock "
            f"surface within {c.slopes.daylight_limit:g} ft of the hinge", "cut")
    return [top, (top[0] + sign * rock.bench, top[1])]
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_corridor_section.py bimforge/author/tests/test_road_corridor_v1.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bimforge/author/corridor/section.py bimforge/author/tests/test_corridor_section.py
git commit -F - <<'EOF'
road corridor section: soil over rock in cut, with a bench (P.6 V1.1)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

### Task 5: Automatic walls: the wall at the hinge, runs, heights, structure candidates

**Files:**
- Modify: `bimforge/author/corridor/section.py`
- Create: `bimforge/author/corridor/walls.py`
- Test: `bimforge/author/tests/test_corridor_section.py`, create `bimforge/author/tests/test_corridor_walls.py`

- [ ] **Step 1: Write the failing section tests** (append to `bimforge/author/tests/test_corridor_section.py`)

```python
from bimforge.author.corridor.params import Gap


def test_an_automatic_fill_wall_stands_at_the_hinge():
    c = corridor(walls="auto").with_walls(
        [Gap(400.0, 600.0, "wall", "L", None, auto="fill")])

    def ground(s, u, v):                  # no ground left, 5 ft down right
        return (-500.0 if u > 0.0 else -5.0) - v
    sec = resolve(c, 500.0, ground)
    assert sec.sides["L"].kind == "wall"
    assert flat(sec.sides["L"].line) == pytest.approx(flat([(17, -1.89), (17, -1.89)]))
    assert flat(sec.sides["R"].line[-1:]) == pytest.approx([-23.22, -5.0])


def test_an_automatic_cut_wall_stands_at_the_edge_of_a_10_ft_shoulder():
    # the left shoulder is 10 ft through the wall: grade (12, -0.24) then
    # (22, -0.74); the hinge 1.4 ft under, (22, -2.14), is the wall's foot.
    # The right cuts 43.39 ft up from its ditch edge at 1 in 2: (-110.78, 40)
    c = corridor(walls="auto").with_walls(
        [Gap(400.0, 600.0, "wall", "L", None, auto="cut")])
    sec = resolve(c, 500.0, level(40.0))
    assert flat(sec.grade["L"]) == pytest.approx(flat([(0, 0), (12, -0.24), (22, -0.74)]))
    assert flat(sec.courses[0, 1, "L"]) == pytest.approx(
        flat([(12, -0.24), (22, -0.74), (22, -1.14), (12, -0.64)]))
    assert flat(sec.sides["L"].line) == pytest.approx(flat([(22, -2.14), (22, -2.14)]))
    assert flat(sec.sides["R"].line[-1:]) == pytest.approx([-110.78, 40.0])


def test_one_earthwork_line_count_for_every_kind_of_side():
    n = 2 * SIDE_SAMPLES - 1 + 2 * 2
    rocky = sloped(cut=ROCK_CUT, fill=STEEP_FILL)
    walled = corridor(walls="auto").with_walls(
        [Gap(400.0, 600.0, "wall", "L", None, auto="fill")])
    secs = [resolve(corridor(), 500.0, level(-5.0)),      # fill 2:1
            resolve(rocky, 500.0, level(-5.0)),           # fill 4:1
            resolve(rocky, 500.0, level(-15.0)),          # fill 2:1, guarded
            resolve(rocky, 500.0, level(15.0)),           # cut into rock
            resolve(rocky, 500.0, level(3.0)),            # cut short of rock
            resolve(walled, 500.0, lambda s, u, v: (-500.0 if u > 0.0 else -5.0) - v)]
    assert {len(sec.earthwork_line()) for sec in secs} == {n}
```

- [ ] **Step 2: Write the failing walls tests** in `bimforge/author/tests/test_corridor_walls.py`

```python
"""road-corridor automatic walls (V1.1): runs, heights, structure candidates."""
import copy

import pytest

from bimforge.author.corridor import walls
from bimforge.author.corridor.params import Gap, parse
from bimforge.author.corridor.section import resolve

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
    return lambda s, u, v: h - v


def test_failing_stations_make_a_wall_that_ends_where_the_slope_fits_again():
    # the left fill finds no ground within 150 ft from 4+49.5 to 5+20.5:
    # 4+50, 4+75 and 5+00 fail; 4+25 and 5+25 fit. Back from 4+50, 4+49
    # fits, so the wall starts at 4+50. On from 5+00, 5+01 to 5+20 fail and
    # 5+21 fits, so it ends at 5+20. The right side fits throughout
    def dz(s, u, v):
        deep = u > 0.0 and 449.5 <= s <= 520.5
        return (-500.0 if deep else -5.0) - v
    found = walls.find(corridor(walls="auto"),
                       [400.0, 425.0, 450.0, 475.0, 500.0, 525.0, 550.0], dz)
    assert found == [Gap(450.0, 520.0, "wall", "L", None, auto="fill")]


def test_a_wall_from_the_first_station_starts_there():
    # no ground from 4+40 to 5+10.5: 4+50 (the run's first station), 4+75
    # and 5+00 fail; on from 5+00, 5+11 fits, so the wall is 4+50 to 5+10
    def dz(s, u, v):
        return (-500.0 if u > 0.0 and 440.0 <= s <= 510.5 else -5.0) - v
    found = walls.find(corridor(walls="auto"), [450.0, 475.0, 500.0, 525.0], dz)
    assert found == [Gap(450.0, 510.0, "wall", "L", None, auto="fill")]


def test_a_cut_that_finds_no_ground_is_a_cut_wall():
    # 500 ft of cut on the left at both stations, 3 ft on the right
    def dz(s, u, v):
        return (500.0 if u > 0.0 else 3.0) - v
    assert walls.find(corridor(walls="auto"), [400.0, 425.0], dz) == [
        Gap(400.0, 425.0, "wall", "L", None, auto="cut")]


def test_a_fill_wall_s_heights_are_read_off_its_sections():
    # the ground falls 0.01 per ft along the road from 30 ft under the PGL
    # at 5+00. The wall's face is the shoulder edge (17, -0.49): at 4+50
    # the ground is at -29.5, 29.01 ft of wall; at 5+50, -30.5: 30.01 ft.
    # Over 25 ft it is too tall: a structure candidate. 4+25 and 5+75 lie
    # outside the wall and are not read
    def dz(s, u, v):
        return (-30.0 - 0.01 * (s - 500.0)) - v
    c = corridor(walls="auto", max_wall_height_ft=25).with_walls(
        [Gap(450.0, 550.0, "wall", "L", None, auto="fill")])
    secs = [resolve(c, s, dz) for s in (425.0, 450.0, 500.0, 550.0, 575.0)]
    (row,) = walls.rows(c, secs, dz)
    assert (row.side, row.kind, row.start, row.end) == ("L", "fill", 450.0, 550.0)
    assert row.offset == pytest.approx(17.0)
    assert (row.min_height, row.max_height) == pytest.approx((29.01, 30.01))
    assert row.barrier and row.too_tall


def test_a_cut_wall_is_as_tall_as_the_ground_over_its_shoulder_edge():
    # 40 ft of ground over the PGL; the 10 ft shoulder's edge is at
    # (22, -0.74): 40.74 ft of wall, no barrier, never a structure
    c = corridor(walls="auto").with_walls(
        [Gap(450.0, 550.0, "wall", "L", None, auto="cut")])
    secs = [resolve(c, s, level(40.0)) for s in (450.0, 500.0, 550.0)]
    (row,) = walls.rows(c, secs, level(40.0))
    assert (row.kind, row.offset) == ("cut", pytest.approx(22.0))
    assert (row.min_height, row.max_height) == pytest.approx((40.74, 40.74))
    assert not row.barrier and not row.too_tall


def test_too_tall_walls_side_by_side_are_one_structure_candidate():
    rows = [walls.WallRow("L", "fill", 450.0, 550.0, 17.0, 29.0, 31.0, True),
            walls.WallRow("R", "fill", 500.0, 600.0, 17.0, 26.0, 28.0, True),
            walls.WallRow("L", "fill", 700.0, 750.0, 17.0, 31.0, 32.5, True),
            walls.WallRow("R", "fill", 800.0, 850.0, 17.0, 10.0, 12.0, False)]
    stations = [450.0 + 25.0 * i for i in range(17)]           # 4+50 to 8+50

    def ground(s):
        # lowest at 5+20; of the stations, 5+25 is nearest (0.0025 ft up);
        # on 7+00 to 7+50 the ground falls toward 5+20, lowest at 7+00
        return 270.0 + 0.0001 * (s - 520.0) ** 2
    assert walls.structures(rows, stations, ground) == [
        walls.StructureRow("both", 450.0, 600.0, 31.0, 525.0),
        walls.StructureRow("L", 700.0, 750.0, 32.5, 700.0)]


def test_the_wall_and_structure_tables():
    rows = [walls.WallRow("R", "fill", 1000.0, 1111.0, 17.0, 15.66, 21.21, True)]
    assert walls.walls_csv(rows) == (
        walls.WALL_HEADER + "\n" "R,fill,1000.00,1111.00,17.00,15.66,21.21,yes,yes\n")
    assert walls.walls_csv([]) == walls.WALL_HEADER + "\n"
    assert walls.structures_csv([walls.StructureRow("R", 1000.0, 1111.0, 21.21, 1000.0)]) == (
        walls.STRUCTURE_HEADER + "\n" "R,1000.00,1111.00,21.21,1000.00\n")
```

- [ ] **Step 3: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_corridor_section.py bimforge/author/tests/test_corridor_walls.py -q`
Expected: the walls file fails to collect (`ImportError: cannot import name 'walls'`); the section wall tests FAIL with `TypeError: '<' not supported between instances of 'NoneType' and 'float'` (an automatic wall has no offset).

- [ ] **Step 4: Implement the wall at the hinge.** In `_side` (`bimforge/author/corridor/section.py`), replace:

```python
    if wall is not None:
        if wall.offset < abs(hu):
```

with:

```python
    if wall is not None:
        if wall.offset is None:
            # an automatic wall (walls: auto) stands at the hinge: a fill
            # wall with no slope in front, a cut wall beside its 10 ft
            # shoulder (params.Corridor.width)
            return Side("wall", [hinge, hinge])
        if wall.offset < abs(hu):
```

- [ ] **Step 5: Write** `bimforge/author/corridor/walls.py`

```python
"""Automatic walls for the road corridor (V1.1, `walls: auto`).

A side whose slope does not fit at a station (no daylight within the limit,
or a daylight past the footprint: section.needs_wall) takes a wall there.
Consecutive failing stations of one kind on a side are one wall, extended a
foot at a time while the section a foot beyond still fails, so each end's
1 ft lead-in (params.WALL_TRANSITION_FT) is a slope that fits. Each wall is
then a wall gap, standing at the hinge (section._side): a fill wall with a
barrier on top and no slope in front, a cut wall beside its 10 ft shoulder.

`rows` reads each wall's exposed height off the sections: the shoulder
edge's height above the ground at a fill wall, the ground's above the edge
at a cut wall. A fill wall over `max_wall_height_ft` is kept and flagged,
and its stretch is a structure candidate (`structures`): a short bridge or
a culvert the designer may put there instead, with a structure gap.
"""
from __future__ import annotations

from dataclasses import dataclass

from bimforge.author.corridor.params import SIDES, WALL_TRANSITION_FT, Gap
from bimforge.author.corridor.section import needs_wall

WALL_HEADER = "side,kind,start,end,offset_ft,min_height_ft,max_height_ft,barrier,too_tall"
STRUCTURE_HEADER = "side,start,end,max_fill_ft,low_point_station"
_EPS = 1e-9


@dataclass(frozen=True)
class WallRow:
    side: str
    kind: str              # "fill" or "cut"
    start: float
    end: float
    offset: float          # the hinge, feet from the centreline
    min_height: float      # exposed height, feet
    max_height: float
    too_tall: bool         # a fill wall over max_wall_height_ft

    @property
    def barrier(self) -> bool:
        """A fill wall carries a barrier on top (no guardrail there)."""
        return self.kind == "fill"


@dataclass(frozen=True)
class StructureRow:
    side: str              # "L", "R" or "both"
    start: float
    end: float
    max_fill: float        # the tallest wall it replaces, feet
    low_point: float       # the station where the ground is lowest


def find(c, stations: list, ground_dz) -> list:
    """Wall gaps (params.Gap, auto = the wall's kind) for one run's
    `stations` of corridor `c`."""
    out = []
    for side in SIDES:
        kinds = [needs_wall(c, s, side, ground_dz) for s in stations]
        i = 0
        while i < len(stations):
            kind = kinds[i]
            if kind is None:
                i += 1
                continue
            j = i
            while j + 1 < len(stations) and kinds[j + 1] == kind:
                j += 1
            start = _reach(c, side, ground_dz, kind, stations[i],
                           stations[i - 1] if i > 0 else None, -1.0)
            end = _reach(c, side, ground_dz, kind, stations[j],
                         stations[j + 1] if j + 1 < len(stations) else None, 1.0)
            out.append(Gap(start, end, "wall", side, None, auto=kind))
            i = j + 1
    return sorted(out, key=lambda g: (g.start, g.side))


def _reach(c, side: str, ground_dz, kind: str, s: float, neighbour, step: float) -> float:
    """The wall's end, moved from station `s` toward `neighbour` (a station
    whose slope fits; None at the run's end) a foot at a time while the
    section a foot beyond still needs this wall."""
    if neighbour is None:
        return s
    while True:
        t = s + step * WALL_TRANSITION_FT
        if (neighbour - t) * step <= _EPS:
            return s
        if needs_wall(c, t, side, ground_dz) != kind:
            return s
        s = t


def rows(c, secs: list, ground_dz) -> list:
    """One WallRow per automatic wall of `c`, its heights read off the
    sections `secs` (section.Section) at its stations."""
    out = []
    for g in c.gaps:
        if g.auto is None:
            continue
        on = [sec for sec in secs if g.start - _EPS <= sec.s <= g.end + _EPS]
        heights = []
        for sec in on:
            u, v = sec.grade[g.side][-1]
            dz = ground_dz(sec.s, u, v)
            heights.append(-dz if g.auto == "fill" else dz)
        top = max(heights)
        out.append(WallRow(g.side, g.auto, g.start, g.end,
                           max(abs(sec.subgrade[g.side][-1][0]) for sec in on),
                           min(heights), top,
                           g.auto == "fill" and top > c.max_wall_height))
    return sorted(out, key=lambda r: (r.start, r.side))


def structures(rows: list, stations: list, ground_elev) -> list:
    """The structure candidates: each too-tall wall's stretch, walls on the
    two sides that overlap merged into one ("both"), with the tallest fill
    and the station of `stations` where `ground_elev(s)` (the ground at the
    centreline) is lowest."""
    groups = []
    for r in sorted((r for r in rows if r.too_tall), key=lambda r: r.start):
        if groups and r.start <= groups[-1][1] + _EPS:
            a, b, top, sides = groups[-1]
            groups[-1] = (a, max(b, r.end), max(top, r.max_height), sides | {r.side})
        else:
            groups.append((r.start, r.end, r.max_height, {r.side}))
    out = []
    for a, b, top, sides in groups:
        inside = [s for s in stations if a - _EPS <= s <= b + _EPS]
        out.append(StructureRow("both" if len(sides) > 1 else next(iter(sides)),
                                a, b, top, min(inside, key=ground_elev)))
    return out


def walls_csv(rows: list) -> str:
    return "\n".join([WALL_HEADER] + [
        f"{r.side},{r.kind},{r.start:.2f},{r.end:.2f},{r.offset:.2f},"
        f"{r.min_height:.2f},{r.max_height:.2f},"
        f"{'yes' if r.barrier else 'no'},{'yes' if r.too_tall else 'no'}"
        for r in rows]) + "\n"


def structures_csv(rows: list) -> str:
    return "\n".join([STRUCTURE_HEADER] + [
        f"{r.side},{r.start:.2f},{r.end:.2f},{r.max_fill:.2f},{r.low_point:.2f}"
        for r in rows]) + "\n"
```

- [ ] **Step 6: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_corridor_section.py bimforge/author/tests/test_corridor_walls.py bimforge/author/tests/test_road_corridor_v1.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add bimforge/author/corridor/section.py bimforge/author/corridor/walls.py bimforge/author/tests/test_corridor_section.py bimforge/author/tests/test_corridor_walls.py
git commit -F - <<'EOF'
road corridor: automatic walls where a slope cannot fit, and structure candidates (P.6 V1.1)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

### Task 6: The family finds its walls and writes the wall and structure tables

**Files:**
- Modify: `bimforge/author/model.py` (`StructureModel`, after `mass_haul`)
- Modify: `bimforge/author/families/road_corridor.py` (`build`)
- Test: `bimforge/author/tests/test_road_corridor.py`

- [ ] **Step 1: Write the failing tests** (append to `bimforge/author/tests/test_road_corridor.py`)

```python
#: a level road on a plane that rises 1 in 20 along the road (north) and
#: falls 1 in 10 to its right (east): 18 to 20 ft of fill at 10+00, cut by
#: 14+00. 4:1 fill, 2:1 behind guardrail over 10 ft of it; rock 8 ft down
#: in cut; a wall wherever a slope would reach past 60 ft
STEEP = {
    "alignment": {"name": "ML", "pob": {"station": 1000.0, "northing": N0, "easting": E0},
                  "run": [{"kind": "tangent", "bearing": "N 0-0-0 E", "length": 600.0}]},
    "profile": {"curves": [{"bvc_station": 1000.0, "bvc_elev": 320.0, "g_in_pct": 0.0,
                            "g_out_pct": 0.0, "length_ft": 600.0,
                            "evc_station": 1600.0, "evc_elev": 320.0}]},
    "ground": {"source": "plane", "elevation": 300.0, "slope_n": 0.05, "slope_e": -0.1},
    "section": {
        "components": [{"name": "lane", "kind": "carriageway", "width": 12.0},
                       {"name": "shoulder", "kind": "shoulder", "width": 5.0,
                        "slope": -0.05}],
        "courses": [{"name": "HMA", "type": "PAVEMENT", "thickness": 0.4},
                    {"name": "AB", "type": "CORE", "thickness": 1.0}],
        "side_slopes": {
            "cut": {"ratio": 2.0, "ditch": {"width": 4.0, "depth": 1.5},
                    "rock": {"depth_ft": 8.0, "ratio": 0.5, "bench_ft": 6.0}},
            "fill": {"ratio": 4.0, "steep": {"ratio": 2.0, "above_height_ft": 10.0}},
            "daylight_limit_ft": 150, "footprint_ft": {"L": 60, "R": 60}}},
    "walls": "auto",
    "max_wall_height_ft": 20,
    "guardrail": {"design_speed_mph": 45},
    "stations": {"interval": 25, "band": 100},
}


@pytest.fixture(scope="module")
def steep():
    from bimforge.author.families.road_corridor import build
    return build(copy.deepcopy(STEEP), CTX)


def test_the_steep_road_finds_its_walls(steep):
    from bimforge.author.corridor.walls import STRUCTURE_HEADER, WALL_HEADER
    # Right of the road (x ft east, d = s - 1000) the ground is
    # 300 + 0.05 d - 0.1 x. The hinge (17 east, 320 - 0.49 - 1.4 = 318.11)
    # has 19.81 - 0.05 d ft of fill under it: over 10 ft to d = 196.2, so
    # 2:1 from the widening's hinge (20.94 east, 319.51 - 0.394 = 319.116):
    # 329.586 - 0.5 x meets the ground at x = 73.965 - 0.125 d, past the
    # 60 ft footprint to d = 111.7. So a wall from 10+00 (the run's first
    # station) to 11+11 (11+12 fits: x = 59.965). From d = 196.2 the fill is
    # 4:1, 322.36 - 0.25 x, meeting the ground at x = (22.36 - 0.05 d) / 0.15,
    # past 60 ft to d = 267.2: 12+00 to 12+50 fail; back from 12+00, 11+99 to
    # 11+97 fail (4:1) and 11+96 fits (10.01 ft of fill, 2:1, x = 49.47), so
    # the wall starts at 11+97; on from 12+50 it ends at 12+67 (12+68 fits).
    # Each wall's face is the shoulder edge (17 east, 319.51), 21.21 - 0.05 d
    # ft above the ground: 21.21 at 10+00, 15.66 at 11+11; 11.36 at 11+97,
    # 7.86 at 12+67. The first is over 20 ft: a structure candidate, its
    # ground lowest at 10+00 (the ground rises along the road). The left
    # side fits throughout (its 2:1 daylights by 49.31 ft, its 4:1 by
    # 45.57 ft, its rock cut by 55.6 ft)
    assert steep.tables["walls"] == (
        WALL_HEADER + "\n"
        "R,fill,1000.00,1111.00,17.00,15.66,21.21,yes,yes\n"
        "R,fill,1197.00,1267.00,17.00,7.86,11.36,yes,no\n")
    assert steep.tables["structures"] == (
        STRUCTURE_HEADER + "\n" "R,1000.00,1111.00,21.21,1000.00\n")


def test_the_steep_road_s_earthwork_is_closed(steep):
    from bimforge.author.primitives import _signed_volume
    earth = [e for e in steep.elements if e.ifc_class.startswith("IfcEarthworks")]
    assert {e.ifc_class for e in earth} == {"IfcEarthworksCut", "IfcEarthworksFill"}
    for el in earth:
        got = 0.0
        for g in el.geometry:
            (d,) = g.body_solids()
            assert _manifold(d["tris"]), el.name
            v = d["verts"]
            got += _signed_volume([(v[a], v[b], v[c]) for a, b, c in d["tris"]])
        assert got == pytest.approx(el.quantities["volume_cf"], rel=1e-9)
        assert len(el.geometry) < 10, el.name


def test_without_walls_auto_a_slope_past_the_footprint_is_an_error():
    from bimforge.author.families.road_corridor import build
    p = copy.deepcopy(STEEP)
    del p["walls"]
    # at 10+00 the right 2:1 daylights 73.965 ft out
    with pytest.raises(ValueError, match=r"10\+00\.00: the R fill slope daylights "
                       r"73\.9\d ft out, past the R footprint of 60 ft"):
        build(p, CTX)


def test_a_v1_corridor_makes_no_tables(model):
    assert model.tables == {}
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_road_corridor.py -q -k "steep or no_tables or footprint"`
Expected: FAIL. The steep build raises `NoDaylight: station 10+00.00: the R fill slope daylights 73.97 ft out, past the R footprint of 60 ft` (the family does not place walls yet), and `StructureModel` has no attribute `tables`.

- [ ] **Step 3: Add the field** in `bimforge/author/model.py`, directly after `mass_haul` in `StructureModel`:

```python
    #: Tables a family writes as CSV outputs, {output key: CSV text}: a
    #: road corridor's "walls" and "structures" (walls: auto) and
    #: "guardrail" (a steep fill rule or a guardrail: block). The registry
    #: writes each to outputs.<key>, and refuses that output when the key is
    #: missing.
    tables: dict = field(default_factory=dict)
```

- [ ] **Step 4: Rewrite `build`** in `bimforge/author/families/road_corridor.py`. Replace the whole function with:

```python
def build(params: dict, ctx) -> "StructureModel":
    from bimforge.author.alignment import Alignment, Profile, sta
    from bimforge.author.corridor import earthwork, masshaul
    from bimforge.author.corridor import walls as auto_walls
    from bimforge.author.corridor.frame import densify, survey_point
    from bimforge.author.corridor.ground import from_params
    from bimforge.author.corridor.loft import StationLoft
    from bimforge.author.corridor.params import SIDES, parse
    from bimforge.author.corridor.section import kind_changes, resolve
    from bimforge.author.model import Element, StructureModel

    missing = [k for k in REQUIRED if params.get(k) is None]
    if missing:
        raise ValueError(f"road-corridor params missing {missing}")
    al_p = params["alignment"]
    al = Alignment(al_p["pob"], al_p["run"], name=al_p.get("name", "ML"))
    prof = Profile(params["profile"]["curves"])
    c = parse(params, al.s_start, al.s_end)
    model = StructureModel("road-corridor", ctx)
    walls = [g.offset for g in c.gaps if g.kind == "wall"]
    reach = max([c.max_half_width() + c.slopes.daylight_limit] + walls)
    ground = from_params(params["ground"], al, ctx, reach, model,
                         log=lambda m: print(m, file=sys.stderr))
    divide = per_component(c, ground)
    # a cut is ground taken out of the TERRAIN (emit_ifc #364), when there
    # is one to void and a schema with IfcEarthworksCut to void it with
    from bimforge.author.spatial import schema_has_facilities
    host = _terrain(model) if schema_has_facilities(ctx.schema) else None

    def survey(s, u, v):
        return survey_point(al, prof, s, u, v)

    def ground_dz(s, u, v):
        n, e, z = survey(s, u, v)
        return ground.z(n, e) - z

    def run_stations(s0, s1):
        return densify(al, prof, c.stations(
            s0, s1, geometry_stations(al, prof, s0, s1)))

    if c.auto_walls:
        # V1.1: a wall wherever a side's slope cannot fit, found on the
        # stations the corridor cuts, then added as wall gaps. `c` changes
        # here, so run_stations below also cuts each wall's own stations
        c = c.with_walls([g for s0, s1 in c.runs()
                          for g in auto_walls.find(c, run_stations(s0, s1),
                                                   ground_dz)])
    hauls, haul_elements, every = [], [], []
    for r, (s0, s1) in enumerate(c.runs(), start=1):
        segment, parts = _parts(r)
        stations = run_stations(s0, s1)
        secs = [resolve(c, s, ground_dz) for s in stations]
        # a section where a side turns between cut and fill
        # (section.kind_changes), unless a station is already that close
        turns = [t for a, b in zip(secs, secs[1:])
                 for t in kind_changes(c, a, b, ground_dz)
                 if min(t - a.s, b.s - t) > TURN_GAP_FT]
        if turns:
            stations = sorted(stations + turns)
            known = {sec.s: sec for sec in secs}
            secs = [known.get(s) or resolve(c, s, ground_dz) for s in stations]
        every.extend(secs)
        for i0, i1 in bands(stations, al.s_start, c.band):
            b0, b1 = stations[i0], stations[i1]
            ss, bs = stations[i0:i1 + 1], secs[i0:i1 + 1]
            tag = f"STA {sta(b0)} to {sta(b1)}"
            for k, course in enumerate(c.courses):
                for j, comp in enumerate(c.components):
                    name = f"{course.name} {comp.name} {tag}"
                    if j == 0:
                        # the two sides meet at the crown: one body, so
                        # the element's bodies do not touch
                        rings = [[across_crown(sec.courses[k, j, "L"],
                                               sec.courses[k, j, "R"])
                                  for sec in bs]]
                        names = [name]
                    else:
                        rings = [[sec.courses[k, j, side] for sec in bs]
                                 for side in SIDES]
                        names = [f"{name} {side}" for side in SIDES]
                    lofts = [StationLoft(n, al, prof, ctx, ss, rs,
                                         ifc="IfcCourse", layer=LAYER)
                             for n, rs in zip(names, rings)]
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
                    # the mesh against a figure that does not read it: the
                    # post gate's volume leg for an exact sweep is the
                    # loft's own mesh volume, so this is the independent one
                    model.stated_quantities.append(
                        (f"{name}: mesh volume vs average end area", vol, aea,
                         AEA_TOL * max(aea, 1.0)))
            cut, fill, cut_d, fill_d = [], [], 0.0, 0.0
            for a, b in zip(bs, bs[1:]):
                cp, fp, cd, fd = earthwork.strip(f"{tag} {sta(a.s)}", a, b,
                                                 survey, ground.z, ctx,
                                                 per_component=divide)
                cut += cp
                fill += fp
                cut_d, fill_d = max(cut_d, cd), max(fill_d, fd)
            width = sum(sec.width() for sec in bs) / len(bs)
            cut_cf = sum(p.volume_cf for p in cut)
            fill_cf = sum(p.volume_cf for p in fill)
            els = []
            if cut:
                els.append(model.add(Element(
                    f"Cut {tag}", ifc_class="IfcEarthworksCut",
                    geometry=earthwork.merge(f"Cut {tag}", "cut", cut),
                    predefined_type="CUT", layer=LAYER, body="solids",
                    spatial_part=segment, voids=host,
                    quantities={"length_ft": b1 - b0, "volume_cf": cut_cf},
                    standard_qto={"Qto_EarthworksCutBaseQuantities": {
                        "Length": ("length", b1 - b0), "Width": ("length", width),
                        "Depth": ("length", cut_d),
                        "UndisturbedVolume": ("volume", cut_cf),
                        "LooseVolume": ("volume", cut_cf * (1.0 + c.swell))}})))
            if fill:
                bank = fill_cf / (1.0 - c.shrink)
                els.append(model.add(Element(
                    f"Fill {tag}", ifc_class="IfcEarthworksFill",
                    geometry=earthwork.merge(f"Fill {tag}", "fill", fill),
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
            # stations as BIMForge_LinearReference writes them: lengths,
            # with their texts; the ordinate a volume (the CSV keeps CY)
            el.psets["BIMForge_MassHaul"] = {
                "StartStation": ("length", row.start),
                "EndStation": ("length", row.station),
                "StartStationText": sta(row.start),
                "EndStationText": sta(row.station),
                "CumulativeVolume": ("volume",
                                     row.cumulative_cy * masshaul.CF_PER_CY)}
    if c.auto_walls:
        rows = auto_walls.rows(c, every, ground_dz)
        model.tables["walls"] = auto_walls.walls_csv(rows)
        model.tables["structures"] = auto_walls.structures_csv(
            auto_walls.structures(rows, sorted(sec.s for sec in every),
                                  lambda s: ground.z(*survey(s, 0.0, 0.0)[:2])))
    return model
```

Without `walls: auto` this is V1's `build` line for line: the stations, sections, bands and elements are the same, in the same order.

- [ ] **Step 5: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_road_corridor.py bimforge/author/tests/test_road_corridor_v1.py -q`
Expected: PASS.

If `test_the_steep_road_s_earthwork_is_closed` fails on a band holding a wall's lead-in (10+00 to 11+00 or 11+00 to 12+00), print that band's sides with `[(sec.s, sec.sides["R"].kind, sec.sides["R"].line[:2]) for sec in secs]` from a debug copy of `build`; a wall line must be the hinge twice. If it fails on a guarded band, check that `_widening`'s first point is `GUARD_STEP_FT` out, not at the shoulder edge itself.

- [ ] **Step 6: Commit**

```bash
git add bimforge/author/model.py bimforge/author/families/road_corridor.py bimforge/author/tests/test_road_corridor.py
git commit -F - <<'EOF'
road corridor: walls auto in the family, with the wall and structure tables (P.6 V1.1)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---
### Task 7: Guardrail runs and their length of need

**Files:**
- Create: `bimforge/author/corridor/guardrail.py`
- Test: create `bimforge/author/tests/test_corridor_guardrail.py`

The length of need (TSSM length-of-need calculator), for a parallel rail with in-line terminals (Y = 0): X = (LH - L) / (LH / LR), LH the 20 ft clear-zone edge (HDM 309.1), L the rail face's offset (from the edge of traveled way for the lane beside the rail, from the centreline for the opposing lane), LR the runout length (195 ft at 45 mph, 230 ft at 50 mph). Each X is rounded up to whole 12.5 ft rail elements. On a two-lane road (right-hand traffic) the lane beside a right-side rail runs up-station, so its X extends the run's start; the opposing lane's X extends its end. A left-side rail is the mirror. A run is then cut back at a structure gap (an AGT) or a wall (tied in), runs closer than a 50 ft terminal join, and a run with a terminal is made whole elements and 150 ft at least, the extra at its terminal ends.

- [ ] **Step 1: Write the failing tests** in `bimforge/author/tests/test_corridor_guardrail.py`

```python
"""road-corridor guardrail runs (V1.1): the length of need by hand.

The cases are a two-lane road with 12 ft lanes and 5 ft shoulders, the rail
face at the shoulder edge: 5 ft from the edge of traveled way (L2), 17 ft
from the centreline (the opposing lane's L). LH is 20 ft.
"""
import pytest

from bimforge.author.corridor import guardrail as gr
from bimforge.author.corridor.guardrail import AGT, TERMINAL, WALL, RailRun

ENDS = ((1000.0, TERMINAL), (2000.0, TERMINAL))


def test_length_of_need_at_45_and_50_mph():
    # 45 mph, LR 195: own lane (20 - 5) / (20 / 195) = 146.25, 11.7
    # elements, so 12: 150 ft; opposing (20 - 17) / (20 / 195) = 29.25, so
    # 3 elements: 37.5 ft
    assert gr.need(5.0, 45) == 150.0
    assert gr.need(17.0, 45) == 37.5
    # 50 mph, LR 230: 15 x 230 / 20 = 172.5, so 14 elements: 175 ft;
    # 3 x 230 / 20 = 34.5, so 37.5 ft
    assert gr.need(5.0, 50) == 175.0
    assert gr.need(17.0, 50) == 37.5
    # a rail face beyond the clear zone needs no length: 20 - 22 < 0
    assert gr.need(22.0, 45) == 0.0


def test_a_right_side_run_extends_up_station_for_its_own_lane():
    # 150 ft before 13+00, 37.5 ft past 14+00: 11+50 to 14+37.5, 287.5 ft
    # = 23 elements; 287.5 / 6.25 = 46 spaces, 47 posts
    (run,) = gr.lay_out("R", [(1300.0, 1400.0)], 5.0, 17.0, 45, *ENDS)
    assert run == RailRun("R", 1150.0, 1437.5, TERMINAL, TERMINAL)
    assert (run.length, run.posts, run.terminals, run.agts) == (287.5, 47, 2, 0)


def test_a_left_side_run_extends_down_station_for_its_own_lane():
    # 37.5 ft before 13+00, 150 ft past 14+00: 12+62.5 to 15+50
    assert gr.lay_out("L", [(1300.0, 1400.0)], 5.0, 17.0, 45, *ENDS) == [
        RailRun("L", 1262.5, 1550.0, TERMINAL, TERMINAL)]


def test_at_50_mph_the_run_is_longer():
    # 175 ft before, 37.5 past: 11+25 to 14+37.5, 312.5 ft = 25 elements,
    # 312.5 / 6.25 = 50 spaces, 51 posts
    (run,) = gr.lay_out("R", [(1300.0, 1400.0)], 5.0, 17.0, 50, *ENDS)
    assert (run.start, run.end, run.posts) == (1125.0, 1437.5, 51)


def test_a_short_run_is_whole_elements_and_150_ft_at_least():
    # 8 ft shoulders: the face 8 ft from the ETW, 20 from the centreline.
    # Own lane (20 - 8) x 195 / 20 = 117, so 10 elements, 125 ft; opposing
    # 20 - 20 = 0. 13+00 to 13+10 becomes 11+75 to 13+10, 135 ft; whole
    # elements 137.5, at least 150: 15 ft more, 7.5 at each terminal:
    # 11+67.5 to 13+17.5
    (run,) = gr.lay_out("R", [(1300.0, 1310.0)], 8.0, 20.0, 45, *ENDS)
    assert (run.start, run.end, run.length) == (1167.5, 1317.5, 150.0)


def test_runs_closer_than_a_terminal_join():
    # 11+50 to 14+37.5 and 14+50 to 16+87.5 are 12.5 ft apart, under a
    # 50 ft terminal: one run, 11+50 to 16+87.5, 537.5 ft = 43 elements
    assert gr.lay_out("R", [(1300.0, 1400.0), (1600.0, 1650.0)], 5.0, 17.0, 45,
                      *ENDS) == [RailRun("R", 1150.0, 1687.5, TERMINAL, TERMINAL)]
    # 15+50 is 112.5 ft past 14+37.5: two runs, the second 15+50 to
    # 17+87.5, 237.5 ft = 19 elements
    assert gr.lay_out("R", [(1300.0, 1400.0), (1700.0, 1750.0)], 5.0, 17.0, 45,
                      *ENDS) == [RailRun("R", 1150.0, 1437.5, TERMINAL, TERMINAL),
                                 RailRun("R", 1550.0, 1787.5, TERMINAL, TERMINAL)]


def test_a_run_into_a_structure_gap_ends_on_an_agt():
    # the bridge starts at 14+50: 14+30 + 37.5 = 14+67.5 is cut back to it,
    # an AGT. 13+05 - 150 = 11+55 to 14+50 is 295 ft; 300 in whole
    # elements, the 5 ft at the one terminal: 11+50
    (run,) = gr.lay_out("R", [(1305.0, 1430.0)], 5.0, 17.0, 45,
                        (1000.0, TERMINAL), (1450.0, AGT))
    assert run == RailRun("R", 1150.0, 1450.0, TERMINAL, AGT)
    assert (run.terminals, run.agts) == (1, 1)


def test_a_run_ties_into_a_wall():
    # a left rail's own lane runs down-station: 14+00 + 150 = 15+50, past
    # the wall at 15+00, so it ties in there: 12+62.5 to 15+00, 237.5 ft
    # = 19 elements
    assert gr.lay_out("L", [(1300.0, 1400.0)], 5.0, 17.0, 45, *ENDS,
                      walls=[(1500.0, 1600.0)]) == [
        RailRun("L", 1262.5, 1500.0, TERMINAL, WALL)]


def test_runs_do_not_join_across_a_wall():
    # the first 11+50 to 14+37.5 stops short of the wall at 14+50; the
    # second, 15+20 - 150 = 13+70, is cut back to the wall's end 15+00 and
    # runs to 16+00 + 37.5 = 16+37.5: 137.5 ft, made 150 at its terminal:
    # 15+00 to 16+50
    assert gr.lay_out("R", [(1300.0, 1400.0), (1520.0, 1600.0)], 5.0, 17.0, 45,
                      *ENDS, walls=[(1450.0, 1500.0)]) == [
        RailRun("R", 1150.0, 1437.5, TERMINAL, TERMINAL),
        RailRun("R", 1500.0, 1650.0, WALL, TERMINAL)]


def test_a_run_at_the_alignment_s_start_stops_there():
    # 37.5 ft before 10+00 is off the alignment: the run starts at 10+00,
    # with its terminal there; to 11+25 + 150 = 12+75: 275 ft = 22 elements
    assert gr.lay_out("L", [(1000.0, 1125.0)], 5.0, 17.0, 45, *ENDS) == [
        RailRun("L", 1000.0, 1275.0, TERMINAL, TERMINAL)]


def test_guarded_stations_make_spans():
    assert gr.spans([0.0, 25.0, 50.0, 75.0, 100.0],
                    [False, True, True, False, True]) == [(25.0, 50.0), (100.0, 100.0)]


def test_the_w_beam_band_and_the_table():
    # 3 1/4 in deep outward from the face, 12 1/4 in tall up to 31 in
    top, bottom = 31.0 / 12.0, (31.0 - 12.25) / 12.0
    assert [c for p in gr.band("L", 17.0) for c in p] == pytest.approx(
        [17.0, bottom, 17.0 + 3.25 / 12.0, bottom, 17.0 + 3.25 / 12.0, top,
         17.0, top])
    assert gr.band("R", -17.0)[1] == pytest.approx((-17.0 - 3.25 / 12.0, bottom))
    assert gr.to_csv([RailRun("L", 1000.0, 1275.0, TERMINAL, TERMINAL)]) == (
        gr.HEADER + "\n" "L,1000.00,1275.00,275.00,TERMINAL,TERMINAL,45\n")
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_corridor_guardrail.py -q`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'bimforge.author.corridor.guardrail'`.

- [ ] **Step 3: Write** `bimforge/author/corridor/guardrail.py`

```python
"""Guardrail for the road corridor (V1.1): MGS where a steep fill is
guarded, laid out by its length of need.

A guarded station is a 2:1 fill (section.Side.guarded); consecutive guarded
stations on a side are one span. Each span is extended by its length of
need for each direction of travel (TSSM length-of-need calculator, a
parallel rail with in-line terminals): X = (LH - L) / (LH / LR), LH the
20 ft clear-zone edge (HDM Index 309.1), L the rail face's offset (from the
edge of traveled way for the lane beside the rail, from the centreline for
the opposing lane), LR the runout length by design speed, each X rounded up
to whole 12.5 ft rail elements. The extended run stops on a Type AGT
transition at a structure gap and ties into a wall; runs closer than a
terminal's length join; a run with a terminal is whole elements and 150 ft
at least (TSSM 3.6(1)), the extra at its terminal ends.

The rail face stands at the shoulder edge; the body is the W-beam band,
31 in to the top of rail (A77N3), swept along the alignment. Posts are
counted at 6'-3", not modelled.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from bimforge.author.corridor.params import RUNOUT_FT

#: the clear-zone edge on a conventional highway, feet (HDM Index 309.1)
CLEAR_ZONE_FT = 20.0
#: one W-beam rail element, feet
ELEMENT_FT = 12.5
#: the shortest guardrail installation, feet (TSSM 3.6(1))
MIN_RUN_FT = 150.0
#: an in-line terminal's length: runs closer than this join, feet
TERMINAL_FT = 50.0
#: MGS post spacing, 6'-3" (A77N3)
POST_SPACING_FT = 6.25
#: top of rail above the shoulder edge, 31 in (A77N3)
RAIL_TOP_FT = 31.0 / 12.0
#: the W-beam's height, 12 1/4 in, and depth, 3 1/4 in
W_BEAM_HEIGHT_FT = 12.25 / 12.0
W_BEAM_DEPTH_FT = 3.25 / 12.0
#: how far the shoulder edge may move under one run's constant rail, feet
EDGE_TOL_FT = 0.01
#: the IfcRailingType name (the dictionary class road-corridor-guardrail)
TYPE_NAME = "Midwest guardrail system"
TERMINAL, AGT, WALL = "TERMINAL", "AGT", "WALL"
HEADER = "side,start,end,length_ft,start_treatment,end_treatment,posts"
_EPS = 1e-9


@dataclass(frozen=True)
class RailRun:
    side: str
    start: float
    end: float
    start_end: str          # TERMINAL, AGT or WALL
    end_end: str

    @property
    def length(self) -> float:
        return self.end - self.start

    @property
    def posts(self) -> int:
        return math.floor(self.length / POST_SPACING_FT + _EPS) + 1

    @property
    def terminals(self) -> int:
        return [self.start_end, self.end_end].count(TERMINAL)

    @property
    def agts(self) -> int:
        return [self.start_end, self.end_end].count(AGT)


def round_up(x: float, step: float = ELEMENT_FT) -> float:
    """`x` up to whole rail elements."""
    return math.ceil(x / step - _EPS) * step


def need(offset: float, speed_mph: int, lh: float = CLEAR_ZONE_FT,
         y: float = 0.0) -> float:
    """The length of need X = (LH - L - Y) / (LH / LR) for a rail face
    `offset` ft out (L), rounded up to whole elements; 0 beyond LH."""
    x = (lh - offset - y) / (lh / RUNOUT_FT[speed_mph])
    return round_up(x) if x > 0.0 else 0.0


def spans(stations: list, flags: list) -> list:
    """[(first, last)]: the runs of consecutive stations whose flag is set."""
    out, start = [], None
    for s, flag in zip(stations, flags):
        if flag and start is None:
            start = s
        if flag:
            last = s
        if not flag and start is not None:
            out.append((start, last))
            start = None
    if start is not None:
        out.append((start, last))
    return out


def _clamped(side: str, start: float, end: float, lo: tuple, hi: tuple) -> RailRun:
    """A run cut back to its limits (station, treatment) at either end."""
    s_kind = e_kind = TERMINAL
    if start <= lo[0] + _EPS:
        start, s_kind = lo
    if end >= hi[0] - _EPS:
        end, e_kind = hi
    return RailRun(side, start, end, s_kind, e_kind)


def lay_out(side: str, guarded: list, l2: float, lc: float, speed_mph: int,
            lower: tuple, upper: tuple, walls=()) -> list:
    """The rail runs on `side` for its `guarded` spans [(s0, s1)], the rail
    face `l2` ft from the edge of traveled way and `lc` ft from the
    centreline. `lower` and `upper` are the corridor run's ends, (station,
    AGT at a structure gap or TERMINAL at the alignment's end); `walls`
    [(start, end)] are the side's walls, which a run ties into."""
    near = need(l2, speed_mph)            # the lane beside the rail
    far = need(lc, speed_mph)             # the opposing lane
    up, down = (near, far) if side == "R" else (far, near)
    runs = []
    for a, b in guarded:
        lo = max([lower] + [(e, WALL) for _s, e in walls if e <= a + _EPS],
                 key=lambda t: t[0])
        hi = min([upper] + [(s, WALL) for s, _e in walls if s >= b - _EPS],
                 key=lambda t: t[0])
        runs.append((_clamped(side, a - up, b + down, lo, hi), lo, hi))
    merged = []
    for run, lo, hi in runs:
        if merged:
            prev, plo, _phi = merged[-1]
            if (prev.end_end == TERMINAL and run.start_end == TERMINAL
                    and run.start - prev.end < TERMINAL_FT):
                merged[-1] = (RailRun(side, prev.start, max(prev.end, run.end),
                                      prev.start_end, run.end_end), plo, hi)
                continue
        merged.append((run, lo, hi))
    return [_whole(run, lo, hi) for run, lo, hi in merged]


def _whole(run: RailRun, lo: tuple, hi: tuple) -> RailRun:
    """`run` made whole elements and MIN_RUN_FT at least, the extra at its
    terminal ends (split between two), then cut back to its limits."""
    free = (run.start_end == TERMINAL and run.start > lo[0] + _EPS,
            run.end_end == TERMINAL and run.end < hi[0] - _EPS)
    extra = max(MIN_RUN_FT, round_up(run.length)) - run.length
    if extra <= _EPS or not any(free):
        return run
    start, end = run.start, run.end
    if all(free):
        start, end = start - extra / 2.0, end + extra / 2.0
    elif free[0]:
        start -= extra
    else:
        end += extra
    return _clamped(run.side, start, end, lo, hi)


def band(side: str, face_u: float) -> list:
    """The W-beam band's (x, z) section for SweptSection: from the rail face
    at offset `face_u` (u, left positive) outward, top of rail RAIL_TOP_FT
    above the shoulder edge."""
    sign = 1.0 if side == "L" else -1.0
    x0, x1 = face_u, face_u + sign * W_BEAM_DEPTH_FT
    z0, z1 = RAIL_TOP_FT - W_BEAM_HEIGHT_FT, RAIL_TOP_FT
    return [(x0, z0), (x1, z0), (x1, z1), (x0, z1)]


def to_csv(runs: list) -> str:
    return "\n".join([HEADER] + [
        f"{r.side},{r.start:.2f},{r.end:.2f},{r.length:.2f},"
        f"{r.start_end},{r.end_end},{r.posts}" for r in runs]) + "\n"
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_corridor_guardrail.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bimforge/author/corridor/guardrail.py bimforge/author/tests/test_corridor_guardrail.py
git commit -F - <<'EOF'
road corridor: guardrail runs by the TSSM length of need (P.6 V1.1)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

### Task 8: Guardrail elements: `IfcRailing` GUARDRAIL and the guardrail table

**Files:**
- Modify: `bimforge/author/families/road_corridor.py`
- Test: `bimforge/author/tests/test_road_corridor.py`

The rail body is a kernel `SweptSection` in the plumb frame along the alignment and profile: the W-beam band at the shoulder edge's offset, raised by the edge's height off the profile grade line as the sweep's `camber` table (the edge's `v` at the corridor's stations, linear between them as superelevation is). A rail is one constant section, so a run whose shoulder edge moves sideways (a width transition under it) is refused.

- [ ] **Step 1: Write the failing tests** (append to `bimforge/author/tests/test_road_corridor.py`)

```python
def flat(points):
    return [c for p in points for c in p]


def test_the_steep_road_s_guardrail(steep):
    from bimforge.author.corridor import guardrail as gr
    # Left: 16.41 - 0.05 d ft of fill at the hinge (17 west, 318.11, over
    # ground 301.7 + 0.05 d), over 10 ft to d = 128.2: guarded 10+00 to
    # 11+25. Its own lane runs down-station: 150 ft past 11+25, to 12+75; the
    # opposing 37.5 ft before 10+00 is off the alignment, so it starts there.
    # 275 ft = 22 elements, 275 / 6.25 = 44 spaces, 45 posts.
    # Right: guarded from 11+12 (past the first wall) to 11+96 (before the
    # second); 150 ft before and 37.5 after both reach a wall, so it ties
    # into both: 11+11 to 11+97, 86 ft, 86 / 6.25 = 13.76, 14 posts
    assert steep.tables["guardrail"] == (
        gr.HEADER + "\n"
        "L,1000.00,1275.00,275.00,TERMINAL,TERMINAL,45\n"
        "R,1111.00,1197.00,86.00,WALL,WALL,14\n")
    left = steep.element("Guardrail L STA 10+00.00 to 12+75.00")
    assert (left.ifc_class, left.predefined_type) == ("IfcRailing", "GUARDRAIL")
    assert left.type_name == gr.TYPE_NAME
    assert left.quantities["length_ft"] == pytest.approx(275.0)
    # the band, 3 1/4 in by 12 1/4 in, swept 275 ft on a level tangent
    assert left.quantities["volume_cf"] == pytest.approx(
        3.25 * 12.25 / 144.0 * 275.0, rel=1e-9)
    assert left.psets["BIMForge_Guardrail"] == {
        "PostCount": 45, "StartTreatment": "TERMINAL", "EndTreatment": "TERMINAL",
        "Terminals": 2, "AGTTransitions": 0}
    sweep = left.geometry
    assert flat(sweep.section) == pytest.approx(flat(gr.band("L", 17.0)))
    # the shoulder edge is 0.49 ft under the PGL all along
    assert {round(v, 9) for _s, v in sweep.camber} == {-0.49}
    right = steep.element("Guardrail R STA 11+11.00 to 11+97.00")
    assert right.psets["BIMForge_Guardrail"]["StartTreatment"] == "WALL"


def test_a_rail_over_a_moving_shoulder_edge_is_refused():
    from bimforge.author.alignment import Alignment, Profile
    from bimforge.author.corridor.guardrail import TERMINAL, RailRun
    from bimforge.author.corridor.params import parse
    from bimforge.author.families.road_corridor import rail_element
    p = copy.deepcopy(STEEP)
    p["widths"] = [{"component": "shoulder", "side": "L", "at": [[1100, 5.0], [1200, 8.0]]}]
    al = Alignment(p["alignment"]["pob"], p["alignment"]["run"])
    prof = Profile(p["profile"]["curves"])
    c = parse(p, al.s_start, al.s_end)
    # the edge goes from 17 to 20 ft out under 10+00 to 12+75: 3 ft
    with pytest.raises(ValueError, match=r"Guardrail L STA 10\+00\.00 to 12\+75\.00: "
                       r"the shoulder edge moves 3\.00 ft under the rail"):
        rail_element(RailRun("L", 1000.0, 1275.0, TERMINAL, TERMINAL), c, al, prof,
                     CTX, None)


def test_the_steep_road_s_rails_are_ifc_guardrails(steep, tmp_path):
    import ifcopenshell
    import ifcopenshell.util.element as E

    from bimforge.author.emit_ifc import emit_ifc
    from bimforge.author.gate import schema_issues
    from bimforge.author.model import StructureModel
    one = StructureModel("rails", CTX)
    for el in steep.elements:
        if el.ifc_class == "IfcRailing":
            one.add(el)
    out = tmp_path / "rails.ifc"
    emit_ifc(one, str(out))
    f = ifcopenshell.open(str(out))
    assert not schema_issues(f)
    rails = f.by_type("IfcRailing")
    assert len(rails) == 2
    for rail in rails:
        assert E.get_predefined_type(rail) == "GUARDRAIL"
        assert E.get_type(rail).Name == "Midwest guardrail system"
        assert "Qto_RailingBaseQuantities" in E.get_psets(rail, qtos_only=True)


def test_a_corridor_with_no_steep_rule_makes_no_guardrail(model):
    assert "guardrail" not in model.tables
    assert not [e for e in model.elements if e.ifc_class == "IfcRailing"]
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_road_corridor.py -q -k "guardrail or rail"`
Expected: FAIL with `KeyError: 'guardrail'` (no table) and `ImportError: cannot import name 'rail_element'`.

- [ ] **Step 3: Add the rail functions** to `bimforge/author/families/road_corridor.py`, after `_parts`:

```python
def guardrail_runs(c, s0: float, s1: float, secs: list) -> list:
    """The guardrail runs (corridor.guardrail.RailRun) of the corridor's run
    from s0 to s1, from its sections' guarded sides: each side's guarded
    spans with their length of need, ended on an AGT where the run meets a
    structure gap and tied into any wall gap on that side."""
    from bimforge.author.corridor import guardrail
    from bimforge.author.corridor.params import SIDES
    from bimforge.author.corridor.section import grade_edge

    def at_gap(s: float, start_of_gap: bool) -> bool:
        return any(g.kind == "structure"
                   and abs((g.start if start_of_gap else g.end) - s) < 1e-6
                   for g in c.gaps)

    lower = (s0, guardrail.AGT if at_gap(s0, False) else guardrail.TERMINAL)
    upper = (s1, guardrail.AGT if at_gap(s1, True) else guardrail.TERMINAL)
    out = []
    for side in SIDES:
        spans = guardrail.spans([sec.s for sec in secs],
                                [sec.sides[side].guarded for sec in secs])
        if not spans:
            continue
        s = spans[0][0]
        face = abs(grade_edge(c, s, side)[0])
        walls = [(g.start, g.end) for g in c.gaps
                 if g.kind == "wall" and g.side == side]
        out += guardrail.lay_out(side, spans, face - c.etw(side, s), face,
                                 c.guard.speed_mph, lower, upper, walls)
    return out


def rail_element(rail, c, al, prof, ctx, segment):
    """`rail` (corridor.guardrail.RailRun) as an IfcRailing GUARDRAIL: the
    W-beam band at the shoulder edge, a SweptSection in the plumb frame on
    the profile, raised by the edge's height off the profile grade line (its
    camber). Posts are counted (BIMForge_Guardrail), not modelled."""
    from bimforge.author.alignment import sta
    from bimforge.author.corridor import guardrail
    from bimforge.author.corridor.section import grade_edge
    from bimforge.author.model import Element
    from bimforge.author.sweep import SweptSection
    name = f"Guardrail {rail.side} STA {sta(rail.start)} to {sta(rail.end)}"
    stations = c.stations(rail.start, rail.end)
    edges = [grade_edge(c, s, rail.side) for s in stations]
    faces = [abs(u) for u, _v in edges]
    if max(faces) - min(faces) > guardrail.EDGE_TOL_FT:
        raise ValueError(
            f"{name}: the shoulder edge moves {max(faces) - min(faces):.2f} ft "
            f"under the rail (a width transition); a rail is one section, so "
            f"end the transition outside the run")
    sweep = SweptSection(name, guardrail.band(rail.side, edges[0][0]), al,
                         rail.start, rail.end, profile=prof,
                         camber=[(s, v) for s, (_u, v) in zip(stations, edges)],
                         frame="plumb", ifc="IfcRailing", layer=LAYER, origin=ctx)
    return Element.from_geometry(
        name, sweep, ifc_class="IfcRailing", predefined_type="GUARDRAIL",
        type_name=guardrail.TYPE_NAME, typed_late=True, material="Steel",
        layer=LAYER, spatial_part=segment,
        psets={"BIMForge_Guardrail": {
            "PostCount": rail.posts, "StartTreatment": rail.start_end,
            "EndTreatment": rail.end_end, "Terminals": rail.terminals,
            "AGTTransitions": rail.agts}},
        standard_qto={"Qto_RailingBaseQuantities": {
            "Length": ("length", rail.length)}})
```

- [ ] **Step 4: Call them from `build`.** Add to the imports at the top of `build`:

```python
    from bimforge.author.corridor import guardrail
```

Replace:

```python
    hauls, haul_elements, every = [], [], []
```

with:

```python
    hauls, haul_elements, every, rails = [], [], [], []
```

Replace:

```python
            hauls.append((b0, b1, cut_cf, fill_cf))
            haul_elements.append(els)
    model.mass_haul = masshaul.mass_haul(hauls, c.shrink)
```

with:

```python
            hauls.append((b0, b1, cut_cf, fill_cf))
            haul_elements.append(els)
        if c.guard is not None:
            # after the run's courses and earthwork, so their order is V1's
            for rail in guardrail_runs(c, s0, s1, secs):
                rails.append(rail)
                model.add(rail_element(rail, c, al, prof, ctx, segment))
    model.mass_haul = masshaul.mass_haul(hauls, c.shrink)
```

and replace the final `return model` with:

```python
    if c.guard is not None:
        model.tables["guardrail"] = guardrail.to_csv(rails)
    return model
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_road_corridor.py bimforge/author/tests/test_road_corridor_v1.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add bimforge/author/families/road_corridor.py bimforge/author/tests/test_road_corridor.py
git commit -F - <<'EOF'
road corridor: guardrail as IfcRailing GUARDRAIL, a swept W-beam band, and its table (P.6 V1.1)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

### Task 9: Kernel: Formulas on standard quantities, text and optional dimensions, a formula over the element's dimensions

The spec's `Length: EndStation - StartStation` is a difference over names that live in `BIMForge_Dimensions`, not in the quantity set, and the gate's formula grammar (M.3) reads only a product of names in the set. This task widens the grammar to a product or one difference, over the set's quantities and then the element's `BIMForge_Dimensions` numbers; adds a Formula to `Element.standard_qto` entries; lets a dictionary property be text (`IfcLabel`, for the station-text twins) and a class property optional (`IsRequired: false`, for `RockDepth`).

**Files:**
- Modify: `bimforge/author/model.py` (the `standard_qto` comment)
- Modify: `bimforge/author/emit_ifc.py` (`_standard_quantity`, the standard-set loop, `_dimensions`)
- Modify: `bimforge/author/gate.py` (`formula_value`, `_ifc_formula_check`)
- Modify: `bimforge/author/family_dictionary.py` (`measure`, `required_dimensions`)
- Modify: `bimforge/bim/model_elements.py` (`described`)
- Test: `bimforge/author/tests/test_emit.py`, `bimforge/author/tests/test_dictionary.py`

- [ ] **Step 1: Write the failing tests.** Append to `bimforge/author/tests/test_emit.py`:

```python
def test_a_standard_quantity_may_carry_its_formula(tmp_path):
    import ifcopenshell
    from bimforge.author.gate import _ifc_formula_check
    m = _fixture_model()
    # a 4 x 4 x 2 ft footing: GrossVolume 32 cf is its box
    m.element("PS-1 footing").standard_qto = {"Qto_FootingBaseQuantities": {
        "Length": ("length", 4.0), "Width": ("length", 4.0),
        "Height": ("length", 2.0),
        "GrossVolume": ("volume", 32.0, "Length * Width * Height")}}
    out = tmp_path / "std.ifc"
    emit_ifc(m, str(out), PC)
    f = ifcopenshell.open(str(out))
    q = {x.Name: x for qs in f.by_type("IfcElementQuantity")
         if qs.Name == "Qto_FootingBaseQuantities" for x in qs.Quantities}
    assert q["GrossVolume"].Formula == "Length * Width * Height"
    assert q["Length"].Formula is None
    assert _ifc_formula_check(m, str(out)) == []


def test_a_formula_is_a_product_or_one_difference():
    from bimforge.author.gate import formula_value
    v = {"EndStation": 1275.0, "StartStation": 1000.0, "Width": 2.0}
    assert formula_value("EndStation - StartStation", v) == 275.0
    assert formula_value("Width * EndStation", v) == 2550.0
    with pytest.raises(ValueError, match="one difference"):
        formula_value("EndStation - StartStation - Width", v)
    with pytest.raises(ValueError, match="not a quantity name"):
        formula_value("EndStation - Width * 2", v)


#: a family dictionary of one class, "x": two lengths, a text and an
#: optional length
_TEXT_DOC = {
    "OrganizationCode": "bimforge", "DictionaryCode": "families",
    "DictionaryVersion": "0.1",
    "Classes": [{"Code": "x", "Name": "X", "ClassProperties": [
        {"Code": p, "PropertyCode": p, "PropertySet": "BIMForge_Dimensions",
         "IsRequired": p != "O"} for p in ("A", "B", "T", "O")]}],
    "Properties": [{"Code": "A", "DataType": "Real", "PhysicalQuantity": "length"},
                   {"Code": "B", "DataType": "Real", "PhysicalQuantity": "length"},
                   {"Code": "T", "DataType": "String"},
                   {"Code": "O", "DataType": "Real", "PhysicalQuantity": "length"}]}


def test_dimensions_take_text_leave_out_an_optional_one_and_feed_a_formula(
        tmp_path, monkeypatch):
    import ifcopenshell
    from bimforge.author import family_dictionary as fd
    from bimforge.author.gate import _ifc_formula_check
    monkeypatch.setattr(fd, "_document", lambda: _TEXT_DOC)
    m = _fixture_model()
    el = m.element("PS-1 footing")
    el.family_class = "x"
    el.dimensions = {"A": 12.0, "B": 2.5, "T": "12+50.00"}
    # a Length over two dimensions in another set: 12 - 2.5 = 9.5 ft
    el.standard_qto = {"Qto_FootingBaseQuantities": {
        "Length": ("length", 9.5, "A - B")}}
    out = tmp_path / "dims.ifc"
    emit_ifc(m, str(out), PC)
    f = ifcopenshell.open(str(out))
    foot = next(e for e in f.by_type("IfcFooting") if e.Name == "PS-1 footing")
    dims = {p.Name: p.NominalValue for r in foot.IsDefinedBy
            if r.RelatingPropertyDefinition.is_a("IfcPropertySet")
            and r.RelatingPropertyDefinition.Name == fd.DIMENSIONS
            for p in r.RelatingPropertyDefinition.HasProperties}
    assert set(dims) == {"A", "B", "T"}                   # O is optional
    assert dims["T"].is_a("IfcLabel") and dims["T"].wrappedValue == "12+50.00"
    assert dims["A"].wrappedValue == pytest.approx(12.0 * m.ctx.ft_to_m)
    assert _ifc_formula_check(m, str(out)) == []
    # a dimension the formula reads, changed in the file, fails it
    a = next(p for p in f.by_type("IfcPropertySingleValue") if p.Name == "A")
    a.NominalValue = f.create_entity("IfcLengthMeasure", 13.0 * m.ctx.ft_to_m)
    bad = tmp_path / "bad.ifc"
    f.write(str(bad))
    (fail,) = _ifc_formula_check(m, str(bad))
    assert "PS-1 footing: Length" in fail
    # a required dimension left out is refused
    el.dimensions = {"A": 12.0, "T": "12+50.00"}
    with pytest.raises(ValueError, match=r"requires \['A', 'B', 'T'\]"):
        emit_ifc(m, str(tmp_path / "missing.ifc"), PC)
```

Append to `bimforge/author/tests/test_dictionary.py`:

```python
def test_a_text_dimension_and_an_optional_one(monkeypatch):
    from bimforge.author import family_dictionary as fd
    doc = {"Classes": [{"Code": "x", "Name": "X", "ClassProperties": [
        {"Code": p, "PropertyCode": p, "PropertySet": fd.DIMENSIONS,
         "IsRequired": p != "O"} for p in ("A", "T", "O")]}],
        "Properties": [{"Code": "A", "DataType": "Real", "PhysicalQuantity": "length"},
                       {"Code": "T", "DataType": "String"},
                       {"Code": "O", "DataType": "Real", "PhysicalQuantity": "ratio"}]}
    monkeypatch.setattr(fd, "_document", lambda: doc)
    assert fd.dimensions("x") == ["A", "T", "O"]
    assert fd.required_dimensions("x") == ["A", "T"]
    assert fd.measure("T") == ("IfcLabel", False)
    assert fd.measure("A") == ("IfcLengthMeasure", True)
    assert fd.measure("O") == ("IfcRatioMeasure", False)
```

In `test_dictionary.py`'s `test_every_class_dimension_is_written`, replace:

```python
    measures = {"IfcLengthMeasure": float, "IfcRatioMeasure": float}
```

with:

```python
    measures = {"IfcLengthMeasure": float, "IfcRatioMeasure": float,
                "IfcLabel": str}
```

and replace:

```python
            assert sorted(pset) == sorted(declared), el.Name
            for code in declared:
```

with:

```python
            assert set(fd.required_dimensions(cls["code"])) <= set(pset) \
                <= set(declared), el.Name
            for code in pset:
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_emit.py bimforge/author/tests/test_dictionary.py -q -k "formula or dimension"`
Expected: FAIL. `_standard_quantity` is handed a 3-tuple (`ValueError: too many values to unpack`); `formula_value("EndStation - StartStation", ...)` raises `not a quantity name`; `fd.required_dimensions` does not exist; `fd.measure("T")` raises `KeyError: 'PhysicalQuantity'`.

- [ ] **Step 3: The standard quantity's Formula.** In `bimforge/author/emit_ifc.py`, replace `_standard_quantity` with:

```python
def _standard_quantity(f, name: str, measure: str, value: float,
                       ft_to_m: float, formula: str | None = None):
    """One quantity of an Element.standard_qto set, converted to metres,
    with its Formula (M.3) when the family gives one."""
    if measure not in _STANDARD_MEASURES:
        raise ValueError(f"standard quantity {name}: measure {measure!r} is "
                         f"not one of {sorted(_STANDARD_MEASURES)}")
    ent, power = _STANDARD_MEASURES[measure]
    q = f.create_entity(ent, Name=name)
    setattr(q, _QTY_ATTR[ent], float(value) * ft_to_m ** power)
    if formula:
        q.Formula = formula
    return q
```

and in the standard-set loop replace:

```python
                sq.Quantities = tuple(
                    _standard_quantity(f, qname, measure, value, ctx.ft_to_m)
                    for qname, (measure, value) in values.items())
```

with:

```python
                sq.Quantities = tuple(
                    _standard_quantity(f, qname, spec[0], spec[1], ctx.ft_to_m,
                                       spec[2] if len(spec) > 2 else None)
                    for qname, spec in values.items())
```

In `bimforge/author/model.py`, replace the `standard_qto` comment with:

```python
    #: The class's standard quantity set (roadmap M.17), {set name:
    #: {quantity name: (measure, value) or (measure, value, formula)}},
    #: measure one of "length", "area", "volume", values in the feet
    #: domain: emit_ifc writes each as an IfcElementQuantity beside
    #: Qto_BaseQuantities, which consumers read until M.17 retires it, a
    #: formula as the quantity's Formula (M.3), over names in the same set or
    #: the element's BIMForge_Dimensions ({"Qto_CourseBaseQuantities":
    #: {"Length": ("length", 100.0, "EndStation - StartStation")}}).
```

- [ ] **Step 4: Text and optional dimensions.** In `bimforge/author/family_dictionary.py`, after `MEASURES` add:

```python
#: A dictionary property whose DataType is String: written as text, unscaled
TEXT = ("IfcLabel", False)
```

replace `measure` with:

```python
def measure(prop: str) -> tuple:
    """(IFC measure type, scales by the foot) of a dictionary property."""
    for p in _document()["Properties"]:
        if p["Code"] == prop:
            if p.get("DataType") == "String":
                return TEXT
            return MEASURES[p["PhysicalQuantity"]]
    raise KeyError(f"no property {prop!r} in the family dictionary "
                   f"({DICTIONARY.name})")
```

and after `dimensions` add:

```python
def required_dimensions(code: str) -> list:
    """The dimension properties a class requires (IsRequired, true unless
    the class says false), by Code, in order."""
    return [cp["PropertyCode"] for cp in _class(code).get("ClassProperties", [])
            if cp.get("PropertySet") == DIMENSIONS and cp.get("IsRequired", True)]
```

In `bimforge/author/emit_ifc.py`, replace the body of `_dimensions` from `from bimforge.author import family_dictionary as fd` to the line `pset = run("pset.add_pset", ...)` (exclusive) with:

```python
    from bimforge.author import family_dictionary as fd
    for product, el in dimensioned:
        declared = fd.dimensions(el.family_class) if el.family_class else []
        required = (fd.required_dimensions(el.family_class)
                    if el.family_class else [])
        given = set(el.dimensions)
        if not set(required) <= given <= set(declared):
            raise ValueError(
                f"{el.name}: dimensions {sorted(given)}, but its class "
                f"{el.family_class!r} requires {sorted(required)} and "
                f"declares {sorted(declared)}")
        if not declared:
            continue
        props = {}
        for code in declared:
            if code not in given:
                continue                    # an optional dimension
            ifc_type, scales = fd.measure(code)
            if ifc_type == fd.TEXT[0]:
                props[code] = f.create_entity(ifc_type, str(el.dimensions[code]))
                continue
            value = float(el.dimensions[code]) * (ctx.ft_to_m if scales else 1.0)
            props[code] = f.create_entity(ifc_type, round(value, 9))
```

In its docstring, replace the sentence `An element carries exactly what its class declares: a class that declares a dimension the family did not size, or a dimension no class declares, fails the build.` with `An element carries every dimension its class requires and none it does not declare; anything else fails the build. A text dimension is an IfcLabel.`

- [ ] **Step 5: The formula grammar.** In `bimforge/author/gate.py`, replace `formula_value` with:

```python
def formula_value(formula: str, values: dict) -> float:
    """A quantity Formula evaluated over {name: value}: a product of names
    (`Length * Width * Height`) or the difference of two (`EndStation -
    StartStation`). Anything else, or a name not in `values`, raises
    ValueError."""
    def name(term: str) -> float:
        n = term.strip()
        if not n.isidentifier():
            raise ValueError(f"formula {formula!r}: {n!r} is not a quantity name")
        if n not in values:
            raise ValueError(f"formula {formula!r}: no quantity {n!r} in the "
                             f"set or the element's dimensions")
        return values[n]

    if "-" in formula:
        terms = formula.split("-")
        if len(terms) != 2:
            raise ValueError(f"formula {formula!r}: a formula takes one "
                             f"difference, of two names")
        return name(terms[0]) - name(terms[1])
    out = 1.0
    for term in formula.split("*"):
        out *= name(term)
    return out


def _dimension_values(product) -> dict:
    """{name: value} of a product's BIMForge_Dimensions numbers (M.2), in
    the file's units: what a Formula may read beside its own set."""
    from bimforge.author.family_dictionary import DIMENSIONS
    out = {}
    for rel in getattr(product, "IsDefinedBy", None) or ():
        pset = getattr(rel, "RelatingPropertyDefinition", None)
        if pset is None or not pset.is_a("IfcPropertySet") or pset.Name != DIMENSIONS:
            continue
        for prop in pset.HasProperties or ():
            nv = getattr(prop, "NominalValue", None)
            if nv is not None and isinstance(nv.wrappedValue, (int, float)):
                out[prop.Name] = float(nv.wrappedValue)
    return out
```

In `_ifc_formula_check`, replace:

```python
            owners = ", ".join(o.Name for r in qset.DefinesOccurrence
                               for o in r.RelatedObjects) or f"#{qset.id()}"
            try:
                got = formula_value(formula, values)
```

with:

```python
            products = [o for r in qset.DefinesOccurrence for o in r.RelatedObjects]
            owners = ", ".join(o.Name for o in products) or f"#{qset.id()}"
            # the set's own quantities first, then the element's dimensions
            names = {}
            for o in products:
                names.update(_dimension_values(o))
            names.update(values)
            try:
                got = formula_value(formula, names)
```

and change its docstring's first sentence to: `Every quantity written with a Formula (roadmap M.3) is that formula over the quantities of its own set and its element's BIMForge_Dimensions, as the file states them: a reader that recomputes gets the number in the file.`

- [ ] **Step 6: Station texts are not parameters to send.** In `bimforge/bim/model_elements.py`, in `described`, replace:

```python
            nv = getattr(prop, "NominalValue", None)
            unit = PARAMETER_UNITS.get(nv.is_a()) if nv is not None else None
```

with:

```python
            nv = getattr(prop, "NominalValue", None)
            if nv is not None and nv.is_a() in ("IfcLabel", "IfcText"):
                continue        # a station's text twin: the number is sent
            unit = PARAMETER_UNITS.get(nv.is_a()) if nv is not None else None
```

- [ ] **Step 7: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_emit.py bimforge/author/tests/test_dictionary.py bimforge/bim/tests/test_model_elements.py bimforge/author/tests/test_road_corridor_v1.py -q`
Expected: PASS. The existing formula tests still pass: a product over the set is read as before, and `no quantity 'Depth'` is still in the message for a missing name.

- [ ] **Step 8: Commit**

```bash
git add bimforge/author/model.py bimforge/author/emit_ifc.py bimforge/author/gate.py bimforge/author/family_dictionary.py bimforge/bim/model_elements.py bimforge/author/tests/test_emit.py bimforge/author/tests/test_dictionary.py
git commit -F - <<'EOF'
Formulas on standard quantities, over the element's dimensions too; text and optional dimensions (M.2, M.3)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---
### Task 10: Dictionary classes, `BIMForge_Dimensions` and Formulas on the corridor's elements

**Files:**
- Modify: `bimforge/author/dictionary/bimforge-families.bsdd.json`
- Create: `bimforge/author/corridor/dimensions.py`
- Modify: `bimforge/author/corridor/earthwork.py` (`plan_area_sf`)
- Modify: `bimforge/author/families/road_corridor.py`
- Test: `bimforge/author/tests/test_road_corridor.py`, `bimforge/author/tests/test_corridor_earthwork.py`, `bimforge/author/tests/test_dictionary.py`

`Qto_CourseBaseQuantities` has no `NetVolume` (its volumes are `Volume` and `GrossVolume`), so the course's volume Formula goes on `Volume`, the quantity V1 writes.

- [ ] **Step 1: Write the failing tests.** Append to `bimforge/author/tests/test_corridor_earthwork.py`:

```python
def test_the_plan_area_of_columns_is_their_bases():
    from bimforge.author.primitives import Prismatoid
    # two columns on a 10 x 10 ft right triangle: 50 sf each
    p = Prismatoid("t", [(0, 0, 0), (10, 0, 0), (0, 10, 0)],
                   [(0, 0, 1), (10, 0, 1), (0, 10, 1)])
    assert earthwork.plan_area_sf([p, p]) == pytest.approx(100.0)
```

Append to `bimforge/author/tests/test_road_corridor.py`:

```python
STEEP_PAYCODES = """\
rules:
  - {match: "(?i)^(HMA|AB) ", group: rc_pave}
  - {match: "(?i)^(Cut|Fill) ", group: rc_earth}
  - {match: "(?i)^Guardrail ", group: rc_mgs}
groups:
  rc_pave: {measure: GrossVolume}
  rc_earth: {measure: GrossVolume}
  rc_mgs: {measure: Length}
codes:
  RC-PAVE: {group: rc_pave, measure: GrossVolume, unit: CY, item_number: "0001",
            description: "Pavement courses"}
  RC-EARTH: {group: rc_earth, measure: GrossVolume, unit: CY, item_number: "0002",
             description: "Earthwork"}
  RC-MGS: {group: rc_mgs, measure: Length, unit: LF, item_number: "0003",
           description: "Midwest guardrail system"}
"""


def _spec_path(tmp_path, params, outputs, schema="IFC4X3_ADD2"):
    import yaml
    (tmp_path / "rc.paycodes.yaml").write_text(STEEP_PAYCODES, "utf-8")
    spec = {"family": "road-corridor", "params": copy.deepcopy(params),
            "paycodes": "./rc.paycodes.yaml",
            "outputs": {"ifc": "out/rc.ifc", **outputs},
            "project": {"name": "Corridor fixture", "epsg": 2226,
                        "base": [E0, N0, 300.0], "guid_ns": str(uuid.UUID(int=9)),
                        "schema": schema, "facility": {"kind": "road"}}}
    path = tmp_path / "rc.spec.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False), "utf-8")
    return path


def _built_from(tmp_path, params, outputs=None):
    import contextlib

    import ifcopenshell

    from bimforge.author.families.registry import build_from_spec
    path = _spec_path(tmp_path, params, outputs or {})
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        # 0: the pre and post gates passed, the formula check among them
        assert build_from_spec(str(path)) == 0, err.getvalue()[-2000:]
    return ifcopenshell.open(str(tmp_path / "out" / "rc.ifc")), tmp_path / "out"


@pytest.fixture(scope="module")
def steep_x3(tmp_path_factory):
    return _built_from(tmp_path_factory.mktemp("steep"), STEEP)


CORRIDOR_CLASSES = {"road-corridor-course", "road-corridor-cut",
                    "road-corridor-fill", "road-corridor-guardrail"}


def test_every_corridor_element_is_classed_and_dimensioned(steep_x3):
    import ifcopenshell.util.element as E

    from bimforge.author import family_dictionary as fd
    from bimforge.bim.ifc_takeoff import family_class_of
    f, _out = steep_x3
    seen = set()
    for el in f.by_type("IfcElement"):
        if el.is_a("IfcGeographicElement"):
            continue                                     # the TERRAIN
        cls = family_class_of(el)
        assert cls and cls["code"] in CORRIDOR_CLASSES, el.Name
        dims = dict(E.get_pset(el, fd.DIMENSIONS) or {})
        dims.pop("id", None)
        assert set(fd.required_dimensions(cls["code"])) <= set(dims) \
            <= set(fd.dimensions(cls["code"])), el.Name
        seen.add(cls["code"])
    assert seen == CORRIDOR_CLASSES
    # the steep road's cut has rock, so its cut carries RockDepth: 8 ft
    cut = f.by_type("IfcEarthworksCut")[0]
    assert E.get_pset(cut, fd.DIMENSIONS)["RockDepth"] == pytest.approx(8.0 * US_FT)


def test_the_left_rail_s_dimensions_and_length(steep_x3):
    import ifcopenshell.util.element as E

    from bimforge.author import family_dictionary as fd
    f, _out = steep_x3
    rail = next(e for e in f.by_type("IfcRailing") if e.Name.startswith("Guardrail L "))
    d = E.get_pset(rail, fd.DIMENSIONS)
    assert d["StartStation"] == pytest.approx(1000.0 * US_FT)
    assert d["EndStation"] == pytest.approx(1275.0 * US_FT)
    assert (d["StartStationText"], d["EndStationText"]) == ("10+00.00", "12+75.00")
    assert d["RailHeight"] == pytest.approx(31.0 / 12.0 * US_FT)
    assert d["PostSpacing"] == pytest.approx(6.25 * US_FT)
    q = E.get_psets(rail, qtos_only=True)["Qto_RailingBaseQuantities"]
    assert q["Length"] == pytest.approx(275.0 * US_FT)


def test_every_formula_holds_and_level_tangent_courses_are_boxes(steep_x3):
    from bimforge.author.gate import _ifc_formula_check
    f, out = steep_x3
    assert _ifc_formula_check(None, str(out / "rc.ifc")) == []
    found = {(qs.Name, q.Name, q.Formula) for qs in f.by_type("IfcElementQuantity")
             for q in qs.Quantities if getattr(q, "Formula", None)}
    for qset in ("Qto_CourseBaseQuantities", "Qto_EarthworksCutBaseQuantities",
                 "Qto_EarthworksFillBaseQuantities", "Qto_RailingBaseQuantities"):
        assert (qset, "Length", "EndStation - StartStation") in found
    # on a level tangent of constant width every course is its box: the
    # lane 24 ft x 0.4 ft x 100 ft = 960 cf to the mesh's 1e-12
    for course in f.by_type("IfcCourse"):
        (vol,) = [q for r in course.IsDefinedBy
                  if r.RelatingPropertyDefinition.is_a("IfcElementQuantity")
                  and r.RelatingPropertyDefinition.Name == "Qto_CourseBaseQuantities"
                  for q in r.RelatingPropertyDefinition.Quantities if q.Name == "Volume"]
        assert vol.Formula == "Length * Width * Thickness", course.Name


def test_a_course_on_a_curve_or_a_grade_gets_no_volume_formula(model):
    from bimforge.author.corridor import dimensions as dims
    # PARAMS climbs 1% and curves at 500 ft radius: the mesh volume runs
    # sqrt(1 + 0.01^2) = 1.00005 past the box on the tangents, and the
    # chorded curve is short of it: both past the gate's 1e-6
    for el in courses(model):
        qset = el.standard_qto["Qto_CourseBaseQuantities"]
        assert len(qset["Volume"]) == 2, el.name
        assert qset["Length"][2] == dims.LENGTH
    # the box at 1% grade: 960 x 1.00005 = 960.048 cf misses by 5e-5
    assert dims.course_volume(960.0, 100.0, 24.0, 0.4) == ("volume", 960.0, dims.VOLUME)
    assert dims.course_volume(960.048, 100.0, 24.0, 0.4) == ("volume", 960.048)


def test_bidsheet_reads_the_dimensions_and_not_the_station_texts(steep_x3):
    from bimforge.bim.model_elements import plan_modelled_elements
    _f, out = steep_x3
    plan = plan_modelled_elements(str(out / "rc.ifc"), all_elements=True)
    assert not [w for w in plan["warnings"] if "StationText" in w]
    rail = next(e for e in plan["elements"] if e["name"].startswith("Guardrail L "))
    assert rail["parameters"]["StartStation"] == {"value": 1000.0, "unit": "FT"}
    assert "StartStationText" not in rail["parameters"]
```

In `bimforge/author/tests/test_dictionary.py`, after `LINEAR_PSET = "BIMForge_LinearReference"` add:

```python
#: the road corridor's classes (V1.1): its example is checked in
#: test_road_corridor, since a course is typed by its spec's course name
#: (HMA, AB), not by a class Name
CORRIDOR = "road-corridor-"
```

In `test_every_emitted_type_is_a_dictionary_class`, replace the last assertion with:

```python
    # every class but the optional D90 guardrail and the corridor's (typed
    # by the spec's course names) is exercised by the examples
    assert seen == {c["Code"] for c in dictionary["Classes"]
                    if not c["Code"].startswith(CORRIDOR)} - {"pipe-guardrail-d90"}
```

and in `test_every_class_dimension_is_written` replace the last assertion with:

```python
    corridor = {cp["PropertyCode"] for c in dictionary["Classes"]
                if c["Code"].startswith(CORRIDOR)
                for cp in c.get("ClassProperties", [])
                if cp.get("PropertySet") == fd.DIMENSIONS}
    assert seen == {p["Code"] for p in dictionary["Properties"]
                    if fd.DIMENSIONS in p.get("Description", "")} - corridor
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_road_corridor.py bimforge/author/tests/test_corridor_earthwork.py -q -k "classed or rail_s or formula or bidsheet or plan_area"`
Expected: FAIL. `earthwork.plan_area_sf` and `bimforge.author.corridor.dimensions` do not exist, and the corridor's elements carry no class (`family_class_of` is None).

- [ ] **Step 3: Add the classes and properties** to the dictionary (run once from the worktree root; it keeps the file's two-space JSON):

```bash
python - <<'PY'
import json
from pathlib import Path
path = Path("bimforge/author/dictionary/bimforge-families.bsdd.json")
d = json.loads(path.read_text("utf-8"))
DIMS = "BIMForge_Dimensions"
LEN = ("Property set BIMForge_Dimensions, written on every element of a class that "
       "declares it: the family's parameters that size the element and are not "
       "quantities. Measured in the project length unit.")
TXT = ("Property set BIMForge_Dimensions, written on every element of a class that "
       "declares it: the family's parameters that size the element and are not "
       "quantities.")


def dim(code, required=True):
    return {"Code": code, "PropertyCode": code, "PropertySet": DIMS,
            "IsRequired": required,
            "Description": "A dimension that sizes the element (M.2)."}


STATIONS = [dim(p) for p in ("StartStation", "EndStation", "StartStationText",
                             "EndStationText")]
COURSE_TYPES = ("ARMOUR", "BALLASTBED", "CORE", "FILTER", "PAVEMENT", "PROTECTION")
d["Classes"] += [
    {"Code": "road-corridor-course", "Name": "Corridor course", "ClassType": "Class",
     "Definition": "One pavement course of a road corridor under one component "
                   "(a lane, a shoulder, a median) over one station band: an IfcCourse "
                   "typed by the course's own IfcCourseType (HMA, AB, ...).",
     "RelatedIfcEntityNamesList": ["IfcCourse"] + [f"IfcCourse{t}" for t in COURSE_TYPES],
     "CountryOfOrigin": "US",
     "ClassProperties": [dim("Thickness"), dim("Width")] + STATIONS},
    {"Code": "road-corridor-cut", "Name": "Corridor cut", "ClassType": "Class",
     "Definition": "The cut of a road corridor over one station band, both sides: "
                   "ground removed down to the subgrade and its side slopes.",
     "RelatedIfcEntityNamesList": ["IfcEarthworksCut", "IfcEarthworksCutCUT"],
     "CountryOfOrigin": "US",
     "ClassProperties": [dim("MaxDepth"), dim("MeanDepth"), dim("SlopeRatio")]
                        + STATIONS + [dim("RockDepth", required=False)]},
    {"Code": "road-corridor-fill", "Name": "Corridor fill", "ClassType": "Class",
     "Definition": "The fill of a road corridor over one station band, both sides: "
                   "embankment from the ground up to the subgrade and its side slopes.",
     "RelatedIfcEntityNamesList": ["IfcEarthworksFill", "IfcEarthworksFillEMBANKMENT"],
     "CountryOfOrigin": "US",
     "ClassProperties": [dim("MaxDepth"), dim("MeanDepth"), dim("SlopeRatio")] + STATIONS},
    {"Code": "road-corridor-guardrail", "Name": "Midwest guardrail system",
     "ClassType": "Class",
     "Definition": "A run of Midwest Guardrail System (MGS) along a road corridor's "
                   "shoulder edge, from terminal or transition to terminal or "
                   "transition: the W-beam band, its posts counted at 6'-3\".",
     "RelatedIfcEntityNamesList": ["IfcRailing", "IfcRailingGUARDRAIL"],
     "CountryOfOrigin": "US",
     "DocumentReference": "Caltrans Standard Plan A77N3",
     "ClassProperties": [dim("RailHeight"), dim("PostSpacing")] + STATIONS},
]


def length(code, definition):
    return {"Code": code, "Name": code, "DataType": "Real",
            "Dimension": "1 0 0 0 0 0 0", "PhysicalQuantity": "length",
            "Units": ["m"], "Definition": definition, "Description": LEN}


d["Properties"] += [
    length("Thickness", "A course's thickness, measured along the section's "
                        "vertical axis, parallel to finished grade."),
    length("Width", "The element's width across the road: a course's bodies' "
                    "mean width over its station band, both sides together."),
    length("StartStation", "Station where the element starts: a length along "
                           "the alignment."),
    length("EndStation", "Station where the element ends: a length along the "
                         "alignment."),
    {"Code": "StartStationText", "Name": "StartStationText", "DataType": "String",
     "Definition": "StartStation as station text, such as 12+50.00.",
     "Description": TXT},
    {"Code": "EndStationText", "Name": "EndStationText", "DataType": "String",
     "Definition": "EndStation as station text.", "Description": TXT},
    length("MaxDepth", "The deepest cut or fill under the element: ground to "
                       "the design line."),
    length("MeanDepth", "The element's volume over its plan area."),
    {"Code": "SlopeRatio", "Name": "SlopeRatio", "DataType": "Real",
     "Dimension": "0 0 0 0 0 0 0", "PhysicalQuantity": "ratio",
     "Definition": "The side slope, horizontal per vertical: a cut's soil "
                   "ratio, or the steepest fill ratio in the band.",
     "Description": TXT},
    length("RockDepth", "Soil over rock in a cut: how far the rock surface lies "
                        "under the ground, the band's mean."),
    length("RailHeight", "Top of rail above the shoulder edge."),
    length("PostSpacing", "Guardrail post spacing, centre to centre."),
]
path.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", "utf-8")
PY
git diff --stat bimforge/author/dictionary/bimforge-families.bsdd.json
```

Expected: only additions in the diff.

- [ ] **Step 4: Write** `bimforge/author/corridor/dimensions.py`

```python
"""The road corridor's dictionary classes, dimensions and quantity
Formulas (V1.1; roadmap M.1, M.2, M.3).

Each course, cut, fill and guardrail element is a family-dictionary class
whose Codes are its BIMForge_Dimensions names. A station is a length along
the alignment, so an element's Length is `EndStation - StartStation`, on
curves as on tangents. A course's volume is `Length * Width * Thickness`
only where the element's mesh volume is that box within the gate's formula
tolerance, which is a course of constant width on a level tangent: on a
grade the sections stand square to the 3D tangent, so the volume runs
sqrt(1 + g^2) past the box (5e-5 at 1%), and on a curve the mesh is chorded
between stations (up to 0.125%), both far past the gate's 1e-6. There no
volume Formula is written.
"""
from __future__ import annotations

from bimforge.author.alignment import sta

COURSE = "road-corridor-course"
CUT = "road-corridor-cut"
FILL = "road-corridor-fill"
GUARDRAIL = "road-corridor-guardrail"
LENGTH = "EndStation - StartStation"
VOLUME = "Length * Width * Thickness"


def stations(s0: float, s1: float) -> dict:
    """An element's station dimensions: lengths, with their texts."""
    return {"StartStation": s0, "EndStation": s1,
            "StartStationText": sta(s0), "EndStationText": sta(s1)}


def course_volume(volume_cf: float, length: float, width: float,
                  thickness: float) -> tuple:
    """A course's Volume entry for Element.standard_qto: with the box
    Formula where the box is the volume within the gate's tolerance."""
    from bimforge.author.gate import FORMULA_TOLERANCE
    if abs(length * width * thickness - volume_cf) <= FORMULA_TOLERANCE * abs(volume_cf):
        return ("volume", volume_cf, VOLUME)
    return ("volume", volume_cf)
```

- [ ] **Step 5: The plan area.** In `bimforge/author/corridor/earthwork.py`, after `strip`, add:

```python
def plan_area_sf(columns: list) -> float:
    """The plan area under `columns` (strip's prismatoids): their bases."""
    return sum(abs(p.area_sf) for p in columns)
```

- [ ] **Step 6: Class, dimension and formula the elements** in `bimforge/author/families/road_corridor.py`.

Add to the imports at the top of `build`:

```python
    from bimforge.author.corridor import dimensions as dims
```

Replace the course block:

```python
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
```

with:

```python
                    vol = sum(lf.volume_cf for lf in lofts)
                    aea = sum(lf.average_end_area_cf for lf in lofts)
                    wide = sum(lf.mean_width_ft for lf in lofts)
                    model.add(Element(
                        name, ifc_class="IfcCourse", geometry=lofts,
                        predefined_type=course.type, type_name=course.name,
                        material=course.name, layer=LAYER, body="solids",
                        spatial_part=parts[comp.kind], family_class=dims.COURSE,
                        dimensions={"Thickness": course.thickness, "Width": wide,
                                    **dims.stations(b0, b1)},
                        quantities={"length_ft": b1 - b0, "volume_cf": vol},
                        standard_qto={"Qto_CourseBaseQuantities": {
                            "Length": ("length", b1 - b0, dims.LENGTH),
                            "Width": ("length", wide),
                            "Thickness": ("length", course.thickness),
                            "Volume": dims.course_volume(vol, b1 - b0, wide,
                                                         course.thickness)}}))
```

Replace the earthwork block from `            els = []` down to (and including) the fill element's `"LooseVolume": ("volume", bank * (1.0 + c.swell))}})))` with:

```python
            els = []
            if cut:
                cut_dims = {"MaxDepth": cut_d,
                            "MeanDepth": cut_cf / earthwork.plan_area_sf(cut),
                            "SlopeRatio": c.slopes.cut_ratio,
                            **dims.stations(b0, b1)}
                if c.slopes.rock is not None:
                    cut_dims["RockDepth"] = (sum(c.slopes.rock.depth_at(sec.s)
                                                 for sec in bs) / len(bs))
                els.append(model.add(Element(
                    f"Cut {tag}", ifc_class="IfcEarthworksCut",
                    geometry=earthwork.merge(f"Cut {tag}", "cut", cut),
                    predefined_type="CUT", layer=LAYER, body="solids",
                    spatial_part=segment, voids=host,
                    family_class=dims.CUT, dimensions=cut_dims,
                    quantities={"length_ft": b1 - b0, "volume_cf": cut_cf},
                    standard_qto={"Qto_EarthworksCutBaseQuantities": {
                        "Length": ("length", b1 - b0, dims.LENGTH),
                        "Width": ("length", width),
                        "Depth": ("length", cut_d),
                        "UndisturbedVolume": ("volume", cut_cf),
                        "LooseVolume": ("volume", cut_cf * (1.0 + c.swell))}})))
            if fill:
                bank = fill_cf / (1.0 - c.shrink)
                # the steepest fill slope the band's sections take
                ratio = min([sec.sides[side].ratio for sec in bs for side in SIDES
                             if sec.sides[side].kind == "fill"]
                            or [c.slopes.fill_ratio])
                els.append(model.add(Element(
                    f"Fill {tag}", ifc_class="IfcEarthworksFill",
                    geometry=earthwork.merge(f"Fill {tag}", "fill", fill),
                    predefined_type="EMBANKMENT", layer=LAYER, body="solids",
                    spatial_part=segment, family_class=dims.FILL,
                    dimensions={"MaxDepth": fill_d,
                                "MeanDepth": fill_cf / earthwork.plan_area_sf(fill),
                                "SlopeRatio": ratio, **dims.stations(b0, b1)},
                    quantities={"length_ft": b1 - b0, "volume_cf": fill_cf},
                    standard_qto={"Qto_EarthworksFillBaseQuantities": {
                        "Length": ("length", b1 - b0, dims.LENGTH),
                        "Width": ("length", width),
                        "Depth": ("length", fill_d),
                        "CompactedVolume": ("volume", fill_cf),
                        "LooseVolume": ("volume", bank * (1.0 + c.swell))}})))
```

In `rail_element`, add to its imports:

```python
    from bimforge.author import family_dictionary as fd
    from bimforge.author.corridor import dimensions as dims
```

and replace its `return Element.from_geometry(...)` with:

```python
    return Element.from_geometry(
        name, sweep, ifc_class="IfcRailing", predefined_type="GUARDRAIL",
        type_name=fd.type_name(dims.GUARDRAIL), typed_late=True,
        family_class=dims.GUARDRAIL, material="Steel", layer=LAYER,
        spatial_part=segment,
        dimensions={"RailHeight": guardrail.RAIL_TOP_FT,
                    "PostSpacing": guardrail.POST_SPACING_FT,
                    **dims.stations(rail.start, rail.end)},
        psets={"BIMForge_Guardrail": {
            "PostCount": rail.posts, "StartTreatment": rail.start_end,
            "EndTreatment": rail.end_end, "Terminals": rail.terminals,
            "AGTTransitions": rail.agts}},
        standard_qto={"Qto_RailingBaseQuantities": {
            "Length": ("length", rail.length, dims.LENGTH)}})
```

- [ ] **Step 7: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_road_corridor.py bimforge/author/tests/test_corridor_earthwork.py bimforge/author/tests/test_dictionary.py bimforge/author/tests/test_road_corridor_v1.py -q`
Expected: PASS. The V1 pin still passes: the class references and the dimension sets are written after the GlobalId sweep, and a Formula adds no root.

If `test_the_left_rail_s_dimensions_and_length` finds `StartStationText` missing, `_dimensions` skipped it: check `fd.measure` reads the property's `DataType` before its `PhysicalQuantity`.

- [ ] **Step 8: Commit**

```bash
git add bimforge/author/dictionary/bimforge-families.bsdd.json bimforge/author/corridor/dimensions.py bimforge/author/corridor/earthwork.py bimforge/author/families/road_corridor.py bimforge/author/tests/test_road_corridor.py bimforge/author/tests/test_corridor_earthwork.py bimforge/author/tests/test_dictionary.py
git commit -F - <<'EOF'
road corridor: dictionary classes, BIMForge_Dimensions and quantity Formulas (P.6 V1.1, M.1 to M.3)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

### Task 11: The registry writes the tables, and refuses one no family makes

**Files:**
- Modify: `bimforge/author/families/registry.py`
- Test: `bimforge/author/tests/test_registry.py`, `bimforge/author/tests/test_road_corridor.py`

- [ ] **Step 1: Write the failing tests.** Append to `bimforge/author/tests/test_registry.py`:

```python
@pytest.mark.parametrize("key", ["walls", "structures", "guardrail"])
def test_a_corridor_table_output_needs_a_family_that_makes_it(tmp_path, key):
    spec = _stage_example(tmp_path)
    text = spec.read_text(encoding="utf-8")
    spec.write_text(text.replace("outputs:\n", f"outputs:\n  {key}: out/x.csv\n", 1),
                    encoding="utf-8")
    with pytest.raises(ValueError, match=rf"outputs\.{key}.*demo-box.*no {key} table"):
        registry.build_from_spec(spec, check_only=True)
```

Append to `bimforge/author/tests/test_road_corridor.py`:

```python
def test_the_tables_are_written_where_the_spec_says(tmp_path):
    from bimforge.author.families.road_corridor import build
    outputs = {key: f"out/rc.{key}.csv" for key in ("walls", "structures", "guardrail")}
    _f, out = _built_from(tmp_path, STEEP, outputs)
    m = build(copy.deepcopy(STEEP), CTX)
    for key in outputs:
        assert (out / f"rc.{key}.csv").read_text("utf-8") == m.tables[key]


def test_a_corridor_without_walls_auto_has_no_wall_table(tmp_path):
    from bimforge.author.families.registry import build_from_spec
    path = _spec_path(tmp_path, PARAMS, {"walls": "out/rc.walls.csv"})
    with pytest.raises(ValueError, match=r"outputs\.walls.*road-corridor.*no walls table"):
        build_from_spec(str(path), check_only=True)
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_registry.py bimforge/author/tests/test_road_corridor.py -q -k "table"`
Expected: FAIL with `ValueError: ...: unknown outputs keys ['walls']` (and the other keys): `load_spec` does not know them.

- [ ] **Step 3: Implement** in `bimforge/author/families/registry.py`. Replace `OUTPUT_KEYS` with:

```python
OUTPUT_KEYS = ("dxf", "ifc", "takeoff_map", "qto", "step", "bbs", "masshaul",
               "walls", "structures", "guardrail")
#: outputs a family writes from StructureModel.tables, as CSV
TABLE_OUTPUTS = ("walls", "structures", "guardrail")
```

In `build_from_spec`, directly after the `outputs.masshaul` check (`raise ValueError(... "makes no mass haul (only a road corridor does)")`), add:

```python
    for key in TABLE_OUTPUTS:
        if spec["outputs"].get(key) and key not in model.tables:
            raise ValueError(
                f"{Path(spec_path).name}: outputs.{key} is set, but family "
                f"{spec['family']!r} makes no {key} table here (a road "
                f"corridor makes walls and structures with walls: auto, and "
                f"guardrail with a steep fill rule or a guardrail: block)")
```

Inside the `try:`, after the `masshaul` block, add:

```python
        for key in TABLE_OUTPUTS:
            if outs.get(key):
                p = Path(outs[key])
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(model.tables[key], encoding="utf-8")
                print(f"{key} table written to {p}", file=sys.stderr)
                written[key] = str(p)
```

In the module docstring, after the `masshaul:` line of `outputs:`, add:

```
              walls: CAD/x.walls.csv,   # a road corridor's automatic walls
              structures: CAD/x.structures.csv,   # its structure candidates
              guardrail: CAD/x.guardrail.csv,     # its guardrail runs
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_registry.py bimforge/author/tests/test_road_corridor.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bimforge/author/families/registry.py bimforge/author/tests/test_registry.py bimforge/author/tests/test_road_corridor.py
git commit -F - <<'EOF'
est-bim build: walls, structures and guardrail outputs (P.6 V1.1)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

### Task 12: The shipped example: guarded fill, a rock cut, an automatic wall

**Files:**
- Modify: `bimforge/author/examples/road-corridor.spec.yaml`, `bimforge/author/examples/road-corridor.paycodes.yaml`
- Modify: `bimforge/author/tests/fixtures/example_globalids.json` (the `road-corridor` block, re-recorded)
- Modify: `docs/ifc-inventory.json`, `docs/ifc-inventory.md` (regenerated)
- Modify: `scripts/bsi_baseline.yaml` (only for a finding accepted in Step 6)

The ground plane's slope along the road drops from 0.03 to 0.02, so the fill past the bridge deepens over 10 ft (about 10 ft at 18+00 on the left, 22 ft at the end): 4:1 below that, 2:1 behind guardrail above it. A left footprint of 64 ft puts an automatic fill wall where the left 2:1 would reach past it (from about 23+95 to the end), over 20 ft, so a structure candidate too. The cut at the start meets rock 3 ft (rising to 4 ft) under the ground on part of its length. The listed left wall gap at 22+00 to 23+00 stays.

- [ ] **Step 1: Rewrite** `bimforge/author/examples/road-corridor.spec.yaml`

```yaml
# Worked road-corridor run (P.6, V1.1): a two-lane road on a tangent, a
# 1000 ft right curve and a second tangent, over a sloping plane of ground.
# A cut at the start meets shallow rock; past the bridge the fill deepens
# beyond 10 ft, so it runs 4:1 below that and 2:1 behind guardrail above,
# and an automatic wall stands where the left slope would reach past its
# footprint. A superelevation run through the curve, a shoulder that
# widens, a gap for a bridge and a listed wall gap on the left.
# --check-only writes nothing (CI fixture). Fictitious alignment and
# stationing: nothing here is a real project.
family: road-corridor
params:
  alignment:
    name: "ML"
    pob: {station: 1000.0, northing: 1943000.0, easting: 6594000.0}
    run:
      - {kind: tangent, bearing: "N 0-0-0 E", length: 600.0}
      - {kind: curve, delta: "20-0-0", radius: 1000.0, turn: R, length: 349.07}
      - {kind: tangent, bearing: "N 20-0-0 E", length: 600.0}
  profile:                              # one sag VC: cut, then fill
    curves:
      - bvc_station: 1000.0
        bvc_elev: 298.0
        g_in_pct: 3.0
        g_out_pct: 5.6
        length_ft: 1549.07
        evc_station: 2549.07
        evc_elev: 364.6100
  ground: {source: plane, elevation: 300.0, slope_n: 0.02, slope_e: 0.04}
  section:
    crown: centerline
    components:                         # outward from the crown, both sides
      - {name: lane, kind: carriageway, width: 12.0}
      - {name: shoulder, kind: shoulder, width: 5.0, slope: -0.05}
    courses:                            # top down
      - {name: HMA, type: PAVEMENT, thickness: 0.40}
      - {name: AB, type: CORE, thickness: 1.00}
    side_slopes:
      cut:
        ratio: 2.0
        ditch: {width: 4.0, depth: 1.5}
        rock: {depth_ft: [[1000, 3.0], [1250, 4.0]], ratio: 0.5, bench_ft: 6.0}
      fill: {ratio: 4.0, steep: {ratio: 2.0, above_height_ft: 10.0}}
      daylight_limit_ft: 150
      footprint_ft: {L: 64, R: 120}
  walls: auto                           # where a slope cannot fit
  max_wall_height_ft: 20                # a fill wall taller: a structure candidate
  guardrail: {design_speed_mph: 45}
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
  walls: out/road-corridor.walls.csv
  structures: out/road-corridor.structures.csv
  guardrail: out/road-corridor.guardrail.csv
project:
  name: "Fixture Road (example)"
  epsg: 2226
  base: [6594000.0, 1943000.0, 300.0]
  guid_ns: "3b7a5c2e-0000-4000-8000-0000000000c6"
  facility: {kind: road}
```

- [ ] **Step 2: Add the guardrail** to `bimforge/author/examples/road-corridor.paycodes.yaml`: change the first comment line to `# Road corridor: pavement courses and earthwork (CY), guardrail (LF).`; under `rules:` after the `Fill` rule add

```yaml
  - match: "(?i)^Guardrail "
    group: rc_mgs
```

under `groups:` add `  rc_mgs: {measure: Length}`; under `codes:` add

```yaml
  RAIL-MGS:
    group: rc_mgs
    measure: Length
    unit: LF
    description: "Midwest guardrail system (steel post)"
```

(no `item_number`: the item code is the owner's call, P.7).

- [ ] **Step 3: Build it and read the tables**

```bash
python - <<'PY'
import shutil, tempfile
from pathlib import Path
from bimforge.author.families.registry import build_from_spec
tmp = Path(tempfile.mkdtemp())
for p in Path("bimforge/author/examples").glob("road-corridor.*.yaml"):
    shutil.copy(p, tmp / p.name)
assert build_from_spec(str(tmp / "road-corridor.spec.yaml")) == 0
for key in ("walls", "structures", "guardrail"):
    print((tmp / "out" / f"road-corridor.{key}.csv").read_text("utf-8"))
PY
```

Expected (the stations are from a hand estimate over a plane, so read "about"):
- walls: one row, `L,fill`, from about 23+95 to `2549.07`, `barrier yes`, `too_tall yes` (about 20 to 24 ft exposed);
- structures: one row on `L` over the same stretch;
- guardrail: on `L`, a run from `1800.00` (an `AGT`, the bridge's departure end) to `2200.00` (`WALL`, the listed wall); a run from `2300.00` (`WALL`) to the automatic wall's start (`WALL`); on `R`, a run from about 18+35 (`TERMINAL`) to `2549.07` (`TERMINAL`, the alignment's end).

If the build fails with `walls: auto puts a fill wall on the L side ... against the listed wall gap 22+00.00 to 23+00.00`, the left 2:1 reaches the footprint too soon after the listed wall: raise `footprint_ft.L` 2 ft at a time until the automatic wall starts past 23+02. If it fails with a slope that finds no ground, the profile has run too far from the ground at the station the error names: fix the ground's slopes, not the daylight limit. Then confirm the three features above before going on.

- [ ] **Step 4: Run the conformance suite on it and regenerate the inventory**

Use one scratch folder outside the repository for Steps 4 and 6 (each shell command sets it again):

```bash
OUT="${TMPDIR:-/tmp}/rc-conformance"
BIMFORGE_CONFORMANCE_OUT="$OUT" python -m pytest bimforge/bim/tests/test_conformance.py -q
python scripts/ifc_inventory.py "$OUT"
python scripts/ifc_inventory.py "$OUT" --check
git diff --stat docs/ifc-inventory.json docs/ifc-inventory.md
```

Expected: the conformance tests PASS on IFC4X3 and IFC4 (the example joins by its file name); `--check` passes after the regeneration; the diff adds `Qto_RailingBaseQuantities`, `BIMForge_Guardrail` and the corridor's new `BIMForge_Dimensions` properties for `build`, and removes nothing.

- [ ] **Step 5: Re-record the example's GlobalIds**

Run `python -m pytest bimforge/author/tests/test_example_globalids.py -q`. Expected: FAIL for `road-corridor` (new elements; the roots written in the sweep renumber after the new rails, walls and cuts). V1.1 changes the example's elements, so its block is re-recorded, as the spec says (the V1 build stays pinned by Task 1's fixture):

```bash
python - <<'PY'
import contextlib, io, json, shutil, tempfile
from pathlib import Path
import ifcopenshell
from bimforge.author.families.registry import build_from_spec
tmp = Path(tempfile.mkdtemp())
for p in Path("bimforge/author/examples").glob("road-corridor.*.yaml"):
    shutil.copy(p, tmp / p.name)
with contextlib.redirect_stderr(io.StringIO()):
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

Expected: the diff touches only the `road-corridor` block. If other blocks move, the file was not written with `sort_keys=True`: revert it and rewrite with the original key order. Then `python -m pytest bimforge/author/tests/test_example_globalids.py -q` PASSES.

- [ ] **Step 6: The bSI rules**

If an `ifc-gherkin-rules` checkout and its Python are at hand (`scripts/bsi_rules.py`'s docstring), run:

```bash
OUT="${TMPDIR:-/tmp}/rc-conformance"
python scripts/bsi_rules.py --rules ifc-gherkin-rules --python rules-venv/bin/python "$OUT"
```

Expected: `road-corridor` and `road-corridor-ifc4` report only the baseline's QTY001, GRF005, ALS016 (IFC4X3) and PSE001, and nothing is stale. A NEW finding on the `IfcRailing` or the new sets is fixed in the code if it is the writer's error; if it is the rule's (as GRF005 is), add it to `scripts/bsi_baseline.yaml` under its rule with a `why`, and list it in the PR for review. Without a checkout, CI's bSI job runs it on the PR.

- [ ] **Step 7: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add bimforge/author/examples/road-corridor.spec.yaml bimforge/author/examples/road-corridor.paycodes.yaml bimforge/author/tests/fixtures/example_globalids.json docs/ifc-inventory.json docs/ifc-inventory.md
git add scripts/bsi_baseline.yaml   # only if Step 6 changed it
git commit -F - <<'EOF'
road-corridor example: guarded fill, a rock cut, an automatic wall (P.6 V1.1)

The ground falls less along the road, so the fill past the bridge deepens
over 10 ft: 4:1 below, 2:1 behind guardrail above, and a left wall where the
2:1 would reach past a 64 ft footprint, over 20 ft and so a structure
candidate. The cut at the start meets rock 3 to 4 ft down. The example's
GlobalIds are re-recorded (its elements change); the V1 build stays pinned
in tests/fixtures/road-corridor-v1. The IFC inventory is regenerated for
the railing and the new dimension properties.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

### Task 13: Changelog

**Files:**
- Modify: `CHANGELOG.md` (Unreleased > Added)

- [ ] **Step 1: Add the entry** under `## Unreleased` > `### Added`, after the `road-corridor` family's entry:

```markdown
- **Road corridor V1.1 (P.6): slope rules, walls, guardrail, dimensions.**
  All optional; a V1 spec builds as before.
  - fill takes `fill.ratio` (4:1) and, over `steep.above_height_ft` of fill
    at the hinge, `steep.ratio` (2:1) behind guardrail, with the 10:1
    widening to a hinge 30 in behind the post (TSSM 3.6, A77N3);
  - cut runs soil to `rock.depth_ft` (a number or `[station, depth]` rows),
    a level bench, then the rock face;
  - `walls: auto` puts a wall wherever a slope finds no daylight within the
    limit or daylights past `footprint_ft`: a fill wall at the hinge with a
    barrier, a cut wall beside a 10 ft shoulder (HDM 309.1); a fill wall
    over `max_wall_height_ft` is flagged as a structure candidate;
    `outputs.walls` and `outputs.structures` list them;
  - guardrail runs are `IfcRailing` GUARDRAIL, typed "Midwest guardrail
    system", with their length of need (TSSM calculator, 45 and 50 mph),
    whole 12.5 ft elements and 150 ft at least, in-line terminals, an AGT at
    a bridge and a tie-in at a wall; posts counted at 6'-3";
    `outputs.guardrail` lists them.
- **For ProjectCommand and BidSheet.ai:** every corridor course, cut, fill
  and guardrail now references its family-dictionary class
  (`road-corridor-course`, `-cut`, `-fill`, `-guardrail`) and carries
  `BIMForge_Dimensions` (stations as lengths with text twins, thickness,
  width, depths, slope ratio, rock depth, rail height, post spacing). Every
  `Length` in its standard quantity set has `Formula = "EndStation -
  StartStation"`, over the element's dimensions; a course on a level
  tangent of constant width also has `Volume` = `Length * Width *
  Thickness`. The gate's formula check reads a difference and the element's
  dimensions. The shipped example's GlobalIds are re-recorded (V1.1 changes
  its elements); a V1 spec's GlobalIds do not move.
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -F - <<'EOF'
Changelog: road corridor V1.1 (P.6)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

## Decisions the plan makes

Each of these is where the code makes a spec point impossible or leaves it open. The controller should confirm them with the user before Task 9 at the latest.

1. **The course volume Formula holds only on a level tangent.** The spec says `Length * Width * Thickness` holds "on tangents and curves alike" for the course across the crown. It does for the exact IFC4X3 solid (Pappus), but the quantity written is the mesh volume (V1: "Volume comes from the mesh faces"): on a grade the sections stand square to the 3D tangent, so the volume is `sqrt(1 + g^2)` past the box (5e-5 at 1%), and on a curve the mesh is chorded (up to 1.25e-3). Both are far past `FORMULA_TOLERANCE` (1e-6). The plan keeps the spec's own rule (write it only where the family's check passes), so in practice only level tangents of constant width get it, and the shipped example (a sag curve throughout) gets none. The alternative, writing the exact solid's volume as the course's Volume, would change V1's quantities.
2. **`NetVolume` is `Volume`.** `Qto_CourseBaseQuantities` has no `NetVolume`; the Formula goes on its `Volume`, the quantity V1 writes.
3. **`Length = EndStation - StartStation` needs a wider formula grammar.** M.3 says a Formula is "over names in the same quantity set", and the gate reads only products. The plan lets a Formula take one difference and read the element's `BIMForge_Dimensions` numbers after the set's own quantities (Task 9). ProjectCommand and BidSheet.ai readers that recompute Formulas need the same rule.
4. **Station texts in `BIMForge_Dimensions`.** The twins are `IfcLabel` properties of the set (dictionary `DataType: String`); `model_elements` skips them instead of warning that they are not lengths.
5. **`RockDepth` is optional.** A dictionary class property may now be `IsRequired: false`; the cut class declares `RockDepth` optional, written only when the spec has rock (its band mean). An element must carry every required dimension and none undeclared.
6. **The bench collapses onto the toe, not the daylight.** The spec says onto "its daylight point". Collapsing onto the toe (the ditch's outer edge) keeps the same vertex count and keeps the padded segment on the soil slope at every station; onto daylight would leave a zero-length last segment for `_samples` to divide.
7. **The guarded widening starts 0.01 ft out (`GUARD_STEP_FT`).** A vertical step up the courses' outer edge, from the hinge to the shoulder edge, made the merged fill two bodies touching along an edge (checked in a scratch run against `earthwork.merge`); a 0.01 ft step makes one closed body.
8. **The fill height is read at the subgrade hinge** (the resolver's hinge, the bottom outer corner of the courses), not at the widening's TSSM hinge.
9. **The widening is built only at guarded stations.** The rail's length-of-need extension runs over 4:1 fill or cut at the shoulder edge with no widening behind it.
10. **Guardrail layout details.** Each direction's X is rounded up to 12.5 ft, then the run is made whole elements and 150 ft at least, the extra split between its terminal ends (all to the one terminal when the other end is an AGT or a wall). Runs join when under 50 ft (an in-line terminal) apart, never across a wall. A run reaching the alignment's end stops there with its terminal, and may fall short of its length of need (no error). A run ends `WALL` at any wall gap on its side, listed or automatic, cut or fill (the spec names automatic walls).
11. **The rail body** is a kernel `SweptSection` in the plumb frame with `camber` = the shoulder edge's height off the profile grade line, the section constant at the edge's offset. A run under which the shoulder edge moves more than 0.01 ft sideways (a width transition) is refused with an error naming the run, a new error the spec does not list. On a grade the plumb sweep is written as its mesh (the exact form leans past 2 mm), as other plumb sweeps are.
12. **`walls:` takes only `auto`.** The spec's "or a list of wall gaps, as V1": listed walls stay in `gaps:` as in V1; a list under `walls:` is an error pointing there. `side_slopes` stays under `section` (V1); `walls`, `max_wall_height_ft` and `guardrail` are top-level params.
13. **A footprint without `walls: auto` is an error** naming the station, side and offset, as "no daylight" is.
14. **Wall details.** A wall run is cut where the 1 ft probe beyond its end first fits (so the lead-in is a slope). The wall's `offset` in `outputs.walls` is the largest hinge offset over its stations; its height is the shoulder edge's above the ground (fill) or the ground's above the edge (cut). A cut wall needs a shoulder component to widen (an error otherwise); the outermost shoulder widens. Only fill walls become structure candidates. An automatic wall touching a listed one (lead-ins included) is the spec's "same side and stations" error.
15. **`SlopeRatio`** on a fill band is the steepest fill ratio its sections take (2.0 where any is guarded); on a cut band, the soil ratio.
16. **Tables exist only when configured.** `walls` and `structures` with `walls: auto`; `guardrail` with a steep rule or a `guardrail:` block (a steep rule brings the 45 mph, 1.44 ft defaults). Requesting one otherwise is the spec's "output on a family that makes none" error, also for a road corridor not so configured.
17. **"V1 unchanged" means V1's geometry, quantities, mass haul and GlobalIds.** Every corridor element (V1 specs included) gains a class reference, `BIMForge_Dimensions` and `Length` Formulas; these are written after the GlobalId sweep, so no V1 root moves (Task 1's fixture proves it).
18. **The example's ground** is changed (`slope_n` 0.03 to 0.02) to make a fill over 10 ft; its guardrail pay code has no item number (the owner's call, P.7).
