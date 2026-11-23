# Road Corridor Part C (shared-use path) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Carry a separated shared-use path on one side of the road corridor, on its own designed profile, as the outer part of that side's section, so cut, fill and walls are computed once over the whole section; grade the strip between road and path as a slope or hold the higher side up with a wall; let the path take its own structures (path gaps), carry an equestrian tread, and leave the road on a corridor of its own (own stretches); check it against the Caltrans Class I bikeway standards (HDM Index 1003.1) and the USFS equestrian guidance; and write it as an `IfcRoadPart` USERDEFINED `SHAREDUSEPATH` with its courses, rails and fence.

**Architecture:** Every `params.path` key is parsed and validated in a new `corridor/path.py` (`Path`, `parse_path`, `validate`); `params.parse` takes the road's `Alignment` and `Profile` so the path can be placed (its profile is an elevation; the section's `v` is measured from the road's profile grade line, in a plane square to the road's 3D tangent). `corridor/path.py` also holds the path's geometry at a station (`surface`, `course_rings`, each course `thickness / cos θ` deep, θ the angle between the section plane's normal and the path's 3D tangent) and the strip resolver (`_strip`: natural ground between, a slope no steeper than `strip.max_ratio`, a guarded slope, a wall at the road's hinge or at the path's shoulder). `section.resolve` hands the path's side to `path.side()`, which returns one `Side` whose line runs hinge, strip, path top, outer slope with a fixed point count (`path.side_count`), so every station's earthwork line still lofts point to point and the earthwork is counted once. Automatic walls gain a location: `walls.find` looks for outer walls and strip walls separately, and a wall `Gap.auto` token names it (`fill`, `cut`, `path-fill`, `path-cut`, `strip-road`, `strip-path`). `loft.centroid_path` measures a course's centroid line as it rises, falls and drifts on its own, so `Volume = PathLength * Width * Thickness` holds for the path's courses. A new `corridor/path_checks.py` writes `outputs.path` and `outputs.path_checks`. The kernel gains a dictionary class on a spatial part (`SpatialPart.family_class`). Phase 2 adds path gaps and the equestrian tread to `path.py`. Phase 3 fixes `bim.add_alignment.add_alignments` for a two-PVI profile, then adds `corridor/own.py`: an own stretch's hand-over point, its `Alignment`, its section (`OwnSection`), its walls and the plan footprint test; the family writes its courses, earthwork, rails and `IfcAlignment`.

**Tech Stack:** Python 3.11+, ifcopenshell 0.9, pytest.

**Spec:** `docs/superpowers/specs/2026-11-22-road-corridor-path-design.md` (approved; the authority). V1.1: `docs/superpowers/specs/2026-11-21-road-corridor-v1.1-slopes-guardrail-design.md` and `docs/superpowers/plans/2026-11-21-road-corridor-v1.1.md`.

**Conventions to keep:**
- Section coordinates: `u` positive to the LEFT of travel, `v` up from the road's profile grade line, in the plane square to the road's 3D tangent (`frame.survey_point`). Road cross slopes negative down, outward from the crown; the path's `cross_slope` and `shoulder.slope` negative down AWAY from the road and from the paved path. A ratio is horizontal per vertical (2.0 is 2:1).
- `Path.sign` is `+1.0` for a path on the left and `-1.0` on the right: `u = edge_u + sign * distance_out`.
- The path's profile is the elevation of its paved INNER edge (the edge toward the road), on ROAD stations; an own stretch's profile is the same edge's elevation on the stretch's own stationing.
- The model is in US survey feet, the IFC in metres; `emit_ifc` converts. Families never convert.
- A spec without `path` builds exactly as V1.1 does (Task 1 pins this): the same elements, GlobalIds, volumes, mass haul, guardrail and tables. The one change is two new CSV columns, `location` in `outputs.walls` and `carries` in `outputs.structures`, which the pin drops before comparing.
- Every new key is optional except `path.side`, `separation`, `width`, `courses` and `profile`.
- A station is a length along the alignment (`StartStation`/`EndStation`, `IfcLengthMeasure`, with `...Text` twins).
- A Formula is written only where the family has checked it holds within `gate.FORMULA_TOLERANCE`; the post gate recomputes every one.
- Run tests from the worktree root: `python -m pytest <path> -q`.
- No real project, place or route names anywhere: "a test route", fictitious stations.
- Every commit message ends, after a blank line, with:
  ```
  Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
  ```

---

## File structure

| File | Responsibility |
|---|---|
| Create `bimforge/author/tests/fixtures/road-corridor-v11/` (`road-corridor.spec.yaml`, `road-corridor.paycodes.yaml`, `globalids.json`, `volumes.json`, `masshaul.csv`, `walls.csv`, `structures.csv`, `guardrail.csv`) | The V1.1 example and what it built, frozen before the path changes the example |
| Create `bimforge/author/tests/test_road_corridor_v11.py` | V1.1 builds unchanged |
| Create `bimforge/author/corridor/path.py` | `Path`, `PathGap` and `Equestrian` (phase 2), `parse_path`, the path profile's checks, `validate` (separation, approaches, deck meeting, path gaps), `section_v`, `surface`, `cos_theta`, `course_rings`, the strip resolver, `side()`, `needs_wall()`, point counts, the path's extra stations |
| Create `bimforge/author/corridor/path_checks.py` | The HDM 1003.1 and USFS advisory rows (`outputs.path_checks`), the per-station table (`outputs.path`), their CSVs |
| Create `bimforge/author/corridor/own.py` (phase 3) | `Own`, `parse_own`, the hand-over point and heading, the own `Alignment` and the rejoin check, `OwnSection`, the own walls, the plan footprint test, the radius rows |
| Modify `bimforge/author/corridor/params.py` | `Corridor.path`, `path_at()`, `wall(strip=)`, the path's stations, `with_walls` by location; `Gap.strip`, `Gap.carries`; `parse(..., alignment=, profile=)`; a path brings a guardrail |
| Modify `bimforge/author/corridor/section.py` | `_slope(widen=)`, `Section.side_counts` and `Section.path`, `resolve` hands the path side to `path.side`, `needs_wall(location=)` |
| Modify `bimforge/author/corridor/walls.py` | Outer and strip walls found apart; `WallRow.location` and `carries`; strip and path wall heights; the `location` and `carries` columns |
| Modify `bimforge/author/corridor/loft.py` | `centroid_path()`: the centroid's line following the rings |
| Modify `bimforge/author/corridor/dimensions.py` | Class codes for the path's road parts, rail and fence |
| Modify `bimforge/author/families/road_corridor.py` | The path's courses, rails, fence and road parts, the tables; the road's rail ignores path walls; own stretches (phase 3) |
| Modify `bimforge/author/spatial.py`, `bimforge/author/emit_ifc.py` | A spatial part's dictionary class |
| Modify `bimforge/author/dictionary/bimforge-families.bsdd.json` | `road-corridor-shared-use-path`, `-path-rail`, `-equestrian-tread`, `-equestrian-rail`, `-path-fence` |
| Modify `bimforge/author/families/registry.py` | `outputs.path`, `outputs.path_checks` |
| Modify `bimforge/bim/add_alignment.py` (phase 3) | A two-PVI profile is written, not dropped |
| Modify `bimforge/author/examples/road-corridor.spec.yaml`, `road-corridor.paycodes.yaml` | A path on the right on its own profile, an approach each side of the bridge, a strip wall |
| Modify `bimforge/author/tests/fixtures/example_globalids.json`, `docs/ifc-inventory.json`, `docs/ifc-inventory.md`, `scripts/bsi_baseline.yaml` (only for an accepted finding) | Re-recorded for the example |
| Create tests `test_corridor_path.py`, `test_corridor_path_checks.py`, `test_road_corridor_path.py`, `test_corridor_own.py`; modify `test_corridor_walls.py`, `test_corridor_loft.py`, `test_registry.py`, `bimforge/bim/tests/test_add_alignment.py` | Unit and integration tests |
| Modify `CHANGELOG.md`, `ROADMAP.md` | Unreleased entries, the P.6 row |

---

## Phase 1: the path beside the road

Phase 1 ends with a corridor that carries a path beside it over its stations: the strip resolved at every station, the path's courses, rails and road part in the IFC, its checks and tables, and the shipped example using it. `path.gaps`, `path.equestrian` and `path.own` are refused as unknown keys until phases 2 and 3 add them.

### Task 1: Pin the V1.1 build

The example changes in Task 12, so freeze it now with what it builds, and test that the frozen copy keeps building the same thing through every later task.

**Files:**
- Create: `bimforge/author/tests/fixtures/road-corridor-v11/` (eight files)
- Create: `bimforge/author/tests/test_road_corridor_v11.py`

- [ ] **Step 1: Record the fixture** (from the worktree root):

```bash
python - <<'PY'
import contextlib, io, json, shutil, tempfile
from pathlib import Path
import ifcopenshell
import ifcopenshell.util.element as E
from bimforge.author.families.registry import build_from_spec
fx = Path("bimforge/author/tests/fixtures/road-corridor-v11")
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
for key in ("masshaul", "walls", "structures", "guardrail"):
    shutil.copy(tmp / "out" / f"road-corridor.{key}.csv", fx / f"{key}.csv")
print(len(recorded["elements"]), "elements,", len(vols), "volumes")
PY
```

Expected: the element count of the `road-corridor` block of `example_globalids.json`, then the number of elements with a GrossVolume. `globalids.json` is that block exactly.

- [ ] **Step 2: Write the test** `bimforge/author/tests/test_road_corridor_v11.py`

```python
"""The V1.1 road corridor builds as it did before the path (P.6, part C).

fixtures/road-corridor-v11/ holds the shipped example as V1.1 shipped it,
its spec and paycodes copied before part C changed the example, and what it
built then: every element's and root's GlobalId, every element's
Qto_BaseQuantities GrossVolume, and the mass-haul, walls, structures and
guardrail tables. Every part C key is optional: without `path` the corridor
builds the same elements, GlobalIds, quantities and tables. The only change
is two new columns, `location` in the walls table and `carries` in the
structures table, which are dropped before comparing.
"""
from __future__ import annotations

import contextlib
import csv
import io
import json
import shutil
from pathlib import Path

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

FIXTURE = Path(__file__).parent / "fixtures" / "road-corridor-v11"
SPEC = "road-corridor.spec.yaml"


def _recorded(name: str):
    return json.loads((FIXTURE / name).read_text("utf-8"))


def _rows(text: str, drop: str | None = None) -> list:
    """The CSV's rows, the column `drop` taken out where it is there."""
    rows = list(csv.reader(io.StringIO(text)))
    if drop is not None and drop in rows[0]:
        k = rows[0].index(drop)
        rows = [r[:k] + r[k + 1:] for r in rows]
    return rows


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    from bimforge.author.families.registry import build_from_spec
    tmp = tmp_path_factory.mktemp("v11")
    for name in (SPEC, "road-corridor.paycodes.yaml"):
        shutil.copy(FIXTURE / name, tmp / name)
    with contextlib.redirect_stderr(io.StringIO()):
        assert build_from_spec(str(tmp / SPEC)) == 0
    return ifcopenshell.open(str(tmp / "out" / "road-corridor.ifc")), tmp / "out"


def test_every_v11_element_keeps_its_globalid(built):
    f, _out = built
    was = _recorded("globalids.json")["elements"]
    now = {el.Name: el.GlobalId for el in f.by_type("IfcElement")}
    assert now == was                             # none moved, none added


def test_every_v11_root_keeps_its_globalid(built):
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
    assert not moved, f"{len(moved)} V1.1 root(s) moved or dropped: {moved}"


def test_every_v11_volume_is_unchanged(built):
    import ifcopenshell.util.element as E
    f, _out = built
    now = {}
    for el in f.by_type("IfcElement"):
        base = E.get_psets(el, qtos_only=True).get("Qto_BaseQuantities", {})
        if "GrossVolume" in base:
            now[el.Name] = base["GrossVolume"]
    was = _recorded("volumes.json")
    assert set(now) == set(was)
    for name, v in was.items():
        assert now[name] == pytest.approx(v, rel=1e-9), name


@pytest.mark.parametrize("key, drop", [("masshaul", None), ("guardrail", None),
                                       ("walls", "location"),
                                       ("structures", "carries")])
def test_every_v11_table_is_unchanged(built, key, drop):
    _f, out = built
    now = (out / f"road-corridor.{key}.csv").read_text("utf-8")
    was = (FIXTURE / f"{key}.csv").read_text("utf-8")
    assert _rows(now, drop) == _rows(was, drop)
```

- [ ] **Step 3: Run it**

Run: `python -m pytest bimforge/author/tests/test_road_corridor_v11.py -q`
Expected: 7 passed (it pins today's output). To see it bite, change `shrink: 0.10` to `shrink: 0.11` in the fixture spec and rerun: `test_every_v11_table_is_unchanged[masshaul-None]` FAILS. Put `0.10` back.

- [ ] **Step 4: Commit**

```bash
git add bimforge/author/tests/fixtures/road-corridor-v11 bimforge/author/tests/test_road_corridor_v11.py
git commit -F - <<'EOF'
road corridor: pin the V1.1 build before the path (P.6, part C)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

### Task 2: Params for the path

**Files:**
- Create: `bimforge/author/corridor/path.py`
- Modify: `bimforge/author/corridor/params.py`
- Test: `bimforge/author/tests/test_corridor_path.py` (create)

`params.parse` gains `alignment=` and `profile=` keywords, the road's: the path is placed against them, so a `path:` without them is an error. The family passes them (Task 9).

- [ ] **Step 1: Write the failing tests** `bimforge/author/tests/test_corridor_path.py`

```python
"""road-corridor V1.2 part C: the shared-use path's params, geometry and
section, hand-worked on a level road on a tangent (P.6)."""
import copy
import math

import pytest

from bimforge.author.alignment import Alignment, Profile
from bimforge.author.corridor.params import Gap, Guard, parse

AL = Alignment({"station": 1000.0, "northing": 0.0, "easting": 0.0},
               [{"kind": "tangent", "bearing": "N 0-0-0 E", "length": 1000.0}],
               name="T")


def grade(elev, pct=0.0, s0=1000.0, s1=2000.0):
    """A profile at one grade from s0 to s1: one curve whose grades are
    equal, as the road's profiles are written."""
    return {"curves": [{"bvc_station": s0, "bvc_elev": elev, "g_in_pct": pct,
                        "g_out_pct": pct, "length_ft": s1 - s0,
                        "evc_station": s1,
                        "evc_elev": elev + pct / 100.0 * (s1 - s0)}]}


#: the road: level at elevation 100
PROF = Profile(grade(100.0)["curves"])
BASE = {"section": {
    "components": [{"name": "lane", "kind": "carriageway", "width": 12.0},
                   {"name": "shoulder", "kind": "shoulder", "width": 5.0,
                    "slope": -0.05}],
    "courses": [{"name": "HMA", "type": "PAVEMENT", "thickness": 0.4},
                {"name": "AB", "type": "CORE", "thickness": 1.0}],
    "side_slopes": {"cut": {"ratio": 2.0, "ditch": {"width": 4.0, "depth": 1.5}},
                    "fill": {"ratio": 2.0}, "daylight_limit_ft": 150}}}
#: on BASE at a normal crown the road's left edge of shoulder is 12 ft at
#: -2 % and 5 ft at -5 % out: (17, -0.49); its hinge 1.4 ft lower, (17, -1.89)
PATH = {"side": "L", "separation": [[1000, 10.0]], "width": 12.0,
        "courses": [{"name": "PATH-HMA", "type": "PAVEMENT", "thickness": 0.25},
                    {"name": "PATH-AB", "type": "CORE", "thickness": 0.5}],
        "profile": grade(99.51)}       # level with the road's edge of shoulder


def path(**over):
    d = copy.deepcopy(PATH)
    d.update(copy.deepcopy(over))
    return d


def corridor(p=None, prof=PROF, **over):
    params = copy.deepcopy(BASE)
    params.update(copy.deepcopy(over))
    params["path"] = copy.deepcopy(PATH if p is None else p)
    return parse(params, 1000.0, 2000.0, alignment=AL, profile=prof)


def test_without_a_path_a_corridor_is_v11():
    c = parse(copy.deepcopy(BASE), 1000.0, 2000.0)
    assert c.path is None and c.guard is None
    assert not c.path_at(1500.0)


def test_a_path_takes_its_defaults():
    p = corridor().path
    assert (p.side, p.sign, p.s_start, p.s_end) == ("L", 1.0, 1000.0, 2000.0)
    assert (p.width, p.cross_slope, p.shoulder_width, p.shoulder_slope) == (
        12.0, -0.02, 2.0, -0.05)
    assert (p.design_speed, p.strip_ratio, p.approach, p.deck_separation,
            p.rail_height) == (20, 2.0, 100.0, 1.5, 3.5)
    assert [x.name for x in p.courses] == ["PATH-HMA", "PATH-AB"]
    assert p.depth() == pytest.approx(0.75)
    assert p.separation_at(1500.0) == 10.0
    assert p.profile.elev(1500.0) == pytest.approx(99.51)
    assert p.road_profile is PROF and p.alignment is AL


def test_a_path_brings_a_guardrail_at_its_defaults():
    # a strip steeper than fill.ratio below a higher road is guarded, as a
    # V1.1 steep fill is: 45 mph, the MGS depth
    assert corridor().guard == Guard(speed_mph=45, rail_depth=1.44)
    assert corridor(path(side="R")).path.sign == -1.0


def test_separation_interpolates_by_station_and_holds_its_ends():
    p = corridor(path(separation=[[1100, 10.0], [1300, 20.0]])).path
    # 12+00 is halfway from 11+00 (10 ft) to 13+00 (20 ft): 15 ft
    assert [p.separation_at(s) for s in (1000.0, 1200.0, 1900.0)] == [10.0, 15.0, 20.0]


def test_path_stations_limit_it():
    c = corridor(path(stations=[1200, 1800]))
    assert (c.path.s_start, c.path.s_end) == (1200.0, 1800.0)
    assert c.path_at(1500.0) and not c.path_at(1100.0)


def test_the_path_s_ends_and_rows_are_stations():
    c = corridor(path(stations=[1210, 1790],
                      separation=[[1210, 10.0], [1240, 12.0]]))
    # the interval (25 ft) and band stations, 1 ft outside the path's start
    # (where its section turns into the road's own), its start, and the
    # separation rows
    assert c.stations(1150.0, 1260.0) == [1150.0, 1175.0, 1200.0, 1209.0,
                                          1210.0, 1225.0, 1240.0, 1250.0, 1260.0]


def test_a_path_vertical_curve_is_densified():
    # a 200 ft sag from -4 % to +4 %: a chord's sagitta r h^2 / 8 within
    # 0.01 ft (sweep.VC_SAGITTA_FT) takes h <= sqrt(8 x 0.01 x 200 / 0.08),
    # 14.14 ft: 15 parts of 13.33 ft
    prof = {"curves": [
        {"bvc_station": 1000.0, "bvc_elev": 99.51, "g_in_pct": -4.0,
         "g_out_pct": -4.0, "length_ft": 400.0, "evc_station": 1400.0,
         "evc_elev": 83.51},
        {"bvc_station": 1400.0, "bvc_elev": 83.51, "g_in_pct": -4.0,
         "g_out_pct": 4.0, "length_ft": 200.0, "evc_station": 1600.0,
         "evc_elev": 83.51},
        {"bvc_station": 1600.0, "bvc_elev": 83.51, "g_in_pct": 4.0,
         "g_out_pct": 4.0, "length_ft": 400.0, "evc_station": 2000.0,
         "evc_elev": 99.51}]}
    got = corridor(path(profile=prof)).stations(1400.0, 1600.0)
    assert max(b - a for a, b in zip(got, got[1:])) <= 200.0 / 15 + 1e-9
    assert 1500.0 in got                                   # the PVI


@pytest.mark.parametrize("over, match", [
    ({"side": "X"}, r"path\.side: 'X' is not L or R"),
    ({"width": 0}, r"path\.width: must be positive"),
    ({"shoulder": {"width": 0}}, r"path\.shoulder\.width: must be positive"),
    ({"shoulder": {"slope": -0.06}}, r"path\.shoulder\.slope: -0\.06 is outside 2-5 %"),
    ({"shoulder": {"slope": 0.03}}, r"path\.shoulder\.slope: 0\.03 does not slope away"),
    ({"cross_slope": -0.03}, r"path\.cross_slope: -0\.03 is outside 1-2 %"),
    ({"cross_slope": 0.005}, r"path\.cross_slope: 0\.005 is outside 1-2 %"),
    ({"design_speed_mph": 25}, r"path\.design_speed_mph: 25 is not 20 or 30"),
    ({"courses": [{"name": "X", "type": "PAVEMENT", "thickness": 0}]},
     r"path\.courses\[0\]\.thickness: must be positive"),
    ({"courses": [{"name": "X", "type": "TOPSOIL", "thickness": 0.5}]},
     r"path\.courses\[0\]: type 'TOPSOIL' is not one of"),
    ({"courses": []}, r"path\.courses: needs at least one course"),
    ({"approach_ft": 0}, r"path\.approach_ft: must be positive"),
    ({"rail_height_ft": -1}, r"path\.rail_height_ft: must be positive"),
    ({"deck_separation_ft": 0}, r"path\.deck_separation_ft: must be positive"),
    ({"strip": {"max_ratio": 0}}, r"path\.strip\.max_ratio: must be positive"),
    ({"stations": [1200, 2500]}, r"path\.stations: station 25\+00\.00 is off the alignment"),
    ({"stations": [1500, 1200]}, r"path\.stations: 'to' must be past 'from'"),
    ({"separation": [[2500, 10.0]]}, r"path\.separation: station 25\+00\.00 is off"),
    ({"separation": []}, r"path\.separation: needs \[station, ft\] rows"),
    ({"profile": grade(99.51, s0=1100.0)},
     r"path\.profile: covers 11\+00\.00 to 20\+00\.00, not the path's "
     r"10\+00\.00 to 20\+00\.00"),
    ({"profile": {"curves": [dict(grade(99.51)["curves"][0], evc_elev=99.6)]}},
     r"path\.profile\.curves\[0\]: evc_elev 99\.6 is not the curve's 99\.5100"),
    ({"profile": {"curves": [dict(grade(99.51)["curves"][0], length_ft=0)]}},
     r"path\.profile\.curves\[0\]\.length_ft: must be positive"),
    ({"profile": None}, r"path\.profile: a profile is \{curves: \[\.\.\.\]\}"),
    ({"colour": "red"}, r"path: unknown keys \['colour'\]"),
])
def test_bad_path_params_are_refused(over, match):
    with pytest.raises(ValueError, match=match):
        corridor(path(**over))


def test_a_path_needs_the_road_s_alignment_and_profile():
    params = copy.deepcopy(BASE)
    params["path"] = copy.deepcopy(PATH)
    with pytest.raises(ValueError, match=r"path: needs the road's alignment and profile"):
        parse(params, 1000.0, 2000.0)


def test_a_listed_wall_gap_on_the_path_s_side_is_refused():
    with pytest.raises(ValueError, match=r"gaps: a listed wall gap on the L side, "
                       r"12\+00\.00 to 13\+00\.00, overlaps the path's stations"):
        corridor(gaps=[{"from": 1200, "to": 1300, "kind": "wall", "side": "L",
                        "offset": 40.0}])
    corridor(gaps=[{"from": 1200, "to": 1300, "kind": "wall", "side": "R",
                    "offset": 40.0}])                    # the other side
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_corridor_path.py -q`
Expected: FAIL: `TypeError: parse() got an unexpected keyword argument 'alignment'` in every test that builds a path, and `AttributeError: 'Corridor' object has no attribute 'path'` in the first.

- [ ] **Step 3: Create** `bimforge/author/corridor/path.py`

```python
"""A shared-use path beside the road corridor (P.6, V1.2 part C): parsed
from `params.path`, placed on the road's section by station, and checked
against the Caltrans Class I bikeway standards (HDM Index 1003.1).

Spec: docs/superpowers/specs/2026-11-22-road-corridor-path-design.md.

While it is beside the road the path is the outer part of one side of the
road's section: its paved inner edge `separation` ft out from the road's
outer edge of shoulder, at the elevation its own profile gives on road
stations. Section coordinates are section.py's: u left of travel, v up from
the road's profile grade line in the plane square to the road's 3D tangent.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from bimforge.author.alignment import Profile, sta
from bimforge.author.corridor.params import (COURSE_TYPES, SIDES, Course,
                                             _ascending, _name, _num,
                                             _on_alignment, _row, interp)

#: the least separation from the road's edge of shoulder to the path's
#: paved edge, outside an approach, feet (HDM 1003.1(7))
MIN_SEPARATION_FT = 5.0
#: under this separation a barrier is needed (1003.1(7)), feet
BARRIER_SEPARATION_FT = 10.0
#: the path's cross slope, magnitude (1003.1(16), DIB 82)
CROSS_SLOPE = (0.01, 0.02)
#: the graded shoulders' slope, magnitude (1003.1(16))
SHOULDER_SLOPE = (0.02, 0.05)
#: the design speeds Table 1003.1 gives, mph
DESIGN_SPEEDS = (20, 30)
#: a profile meets a deck, or another profile, within this, feet
MEET_TOL_FT = 0.01
#: the path's section turns into the road's own over this at the path's
#: ends, as a V1 section turns into a wall gap, feet
PATH_TRANSITION_FT = 1.0
#: the earthwork's step down a course's edge, as section.GUARD_STEP_FT: a
#: vertical face would put two columns on one plan edge, feet
STEP_FT = 0.01
#: points on the ground between the road's slope and the path's, where
#: natural ground is left between them
GROUND_SAMPLES = 8
#: the keys `params.path` takes
KEYS = {"side", "stations", "separation", "width", "cross_slope", "shoulder",
        "courses", "profile", "design_speed_mph", "strip", "approach_ft",
        "deck_separation_ft", "rail_height_ft"}
_EPS = 1e-9


@dataclass(frozen=True)
class Path:
    """The path beside the road (`params.path`), and the road's alignment
    and profile it is placed against."""
    side: str                      # "L" or "R" of travel
    s_start: float                 # its stations, road stations
    s_end: float
    separation: tuple              # ((station, ft), ...): the road's outer
                                   # edge of shoulder to the paved inner edge
    width: float                   # paved, feet
    cross_slope: float             # one way; negative: down away from the road
    shoulder_width: float          # each graded shoulder, feet
    shoulder_slope: float          # negative: down away from the paved path
    courses: tuple                 # params.Course, top down, under the paved width
    profile: Profile               # the paved inner edge's elevation, road stations
    design_speed: int              # 20 or 30 mph (Table 1003.1)
    strip_ratio: float             # the steepest slope between road and path
    approach: float                # ft from a structure gap's end
    deck_separation: float         # the deck's barrier between traffic and path
    rail_height: float             # the path's rail on a wall, feet
    road_profile: Profile          # the road's
    alignment: object              # the road's

    @property
    def sign(self) -> float:
        """+1 on the left, -1 on the right: u = edge u + sign x distance out."""
        return 1.0 if self.side == "L" else -1.0

    def separation_at(self, s: float) -> float:
        return interp(list(self.separation), s)

    def depth(self) -> float:
        """The courses' thickness, normal to the path's grade."""
        return sum(x.thickness for x in self.courses)

    def covers(self, s: float) -> bool:
        return self.s_start - _EPS <= s <= self.s_end + _EPS


def _separation(value, s0: float, s1: float) -> tuple:
    where = "path.separation"
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError(f"{where}: needs [station, ft] rows")
    rows = tuple((_on_alignment(s, where, s0, s1), _num(v, where))
                 for s, v in (_row(r, 2, where, "[station, ft]") for r in value))
    _ascending([s for s, _v in rows], where)
    return rows


def _courses(value, where: str = "path.courses") -> list:
    out = []
    for i, x in enumerate(value or []):
        at = f"{where}[{i}]"
        ctype = str((x or {}).get("type", "")).upper()
        if ctype not in COURSE_TYPES:
            raise ValueError(f"{at}: type {(x or {}).get('type')!r} is not one of "
                             f"{COURSE_TYPES}")
        out.append(Course(_name(x, at), ctype,
                          _num(x.get("thickness"), f"{at}.thickness")))
    if not out:
        raise ValueError(f"{where}: needs at least one course")
    return out


def _profile(value, where: str, s0: float, s1: float) -> Profile:
    """A profile in params.profile's form (`{curves: [...]}`): each curve
    whole (its EVC where its length and grades put it, within MEET_TOL_FT),
    the tangents between them continuous, covering stations s0 to s1."""
    if (not isinstance(value, dict) or not isinstance(value.get("curves"), list)
            or not value["curves"]):
        raise ValueError(f"{where}: a profile is {{curves: [...]}}, as params.profile")
    keys = ("bvc_station", "bvc_elev", "g_in_pct", "g_out_pct", "length_ft",
            "evc_station", "evc_elev")
    curves = []
    for i, cv in enumerate(value["curves"]):
        at = f"{where}.curves[{i}]"
        if not isinstance(cv, dict):
            raise ValueError(f"{at}: a mapping ({', '.join(keys)})")
        row = {k: _num(cv.get(k), f"{at}.{k}", positive=(k == "length_ft"))
               for k in keys}
        if abs(row["bvc_station"] + row["length_ft"] - row["evc_station"]) > MEET_TOL_FT:
            raise ValueError(f"{at}: evc_station {row['evc_station']:g} is not "
                             f"bvc_station + length_ft")
        g1, g2 = row["g_in_pct"] / 100.0, row["g_out_pct"] / 100.0
        length = row["length_ft"]
        z = row["bvc_elev"] + g1 * length + 0.5 * (g2 - g1) * length
        if abs(z - row["evc_elev"]) > MEET_TOL_FT:
            raise ValueError(f"{at}: evc_elev {row['evc_elev']:g} is not the "
                             f"curve's {z:.4f}")
        curves.append(row)
    for i, (a, b) in enumerate(zip(curves, curves[1:])):
        at = f"{where}.curves[{i + 1}]"
        if b["bvc_station"] < a["evc_station"] - _EPS:
            raise ValueError(f"{at}: starts at {sta(b['bvc_station'])}, inside the "
                             f"curve before it")
        if abs(a["g_out_pct"] - b["g_in_pct"]) > 1e-9:
            raise ValueError(f"{at}: g_in_pct {b['g_in_pct']:g} is not the grade "
                             f"before it, {a['g_out_pct']:g}")
        z = a["evc_elev"] + a["g_out_pct"] / 100.0 * (b["bvc_station"] - a["evc_station"])
        if abs(z - b["bvc_elev"]) > MEET_TOL_FT:
            raise ValueError(f"{at}: bvc_elev {b['bvc_elev']:g} is off the tangent "
                             f"before it ({z:.4f})")
    first, last = curves[0]["bvc_station"], curves[-1]["evc_station"]
    if first > s0 + _EPS or last < s1 - _EPS:
        raise ValueError(f"{where}: covers {sta(first)} to {sta(last)}, not the "
                         f"path's {sta(s0)} to {sta(s1)}")
    return Profile(curves)


def parse_path(pp, c, alignment, profile) -> Path:
    """The path `pp` (`params.path`) describes beside corridor `c`
    (params.Corridor), placed against the road's `alignment` and `profile`;
    ValueError names the first field that is wrong."""
    if not isinstance(pp, dict):
        raise ValueError("path: a mapping ({side, separation, width, courses, "
                         "profile, ...})")
    unknown = sorted(set(pp) - KEYS)
    if unknown:
        raise ValueError(f"path: unknown keys {unknown}")
    if alignment is None or profile is None:
        raise ValueError("path: needs the road's alignment and profile "
                         "(params.parse(..., alignment=, profile=))")
    side = str(pp.get("side", "")).upper()
    if side not in SIDES:
        raise ValueError(f"path.side: {pp.get('side')!r} is not L or R")
    s0, s1 = c.s_start, c.s_end
    if pp.get("stations") is not None:
        st = _row(pp["stations"], 2, "path.stations", "[from, to]")
        s0 = _on_alignment(st[0], "path.stations", c.s_start, c.s_end)
        s1 = _on_alignment(st[1], "path.stations", c.s_start, c.s_end)
        if not s1 > s0:
            raise ValueError("path.stations: 'to' must be past 'from'")
    separation = _separation(pp.get("separation"), c.s_start, c.s_end)
    width = _num(pp.get("width"), "path.width")
    cs = _num(pp.get("cross_slope", -0.02), "path.cross_slope", positive=False)
    if not CROSS_SLOPE[0] - _EPS <= abs(cs) <= CROSS_SLOPE[1] + _EPS:
        raise ValueError(f"path.cross_slope: {cs:g} is outside 1-2 % "
                         f"(HDM 1003.1(16), DIB 82)")
    sh = pp.get("shoulder") or {}
    if not isinstance(sh, dict):
        raise ValueError("path.shoulder: a mapping ({width, slope})")
    sw = _num(sh.get("width", 2.0), "path.shoulder.width")
    ss = _num(sh.get("slope", -0.05), "path.shoulder.slope", positive=False)
    if ss >= 0.0:
        raise ValueError(f"path.shoulder.slope: {ss:g} does not slope away from "
                         f"the path; give it negative (HDM 1003.1(16))")
    if not SHOULDER_SLOPE[0] - _EPS <= -ss <= SHOULDER_SLOPE[1] + _EPS:
        raise ValueError(f"path.shoulder.slope: {ss:g} is outside 2-5 % "
                         f"(HDM 1003.1(16))")
    speed = _num(pp.get("design_speed_mph", 20), "path.design_speed_mph")
    if speed not in DESIGN_SPEEDS:
        raise ValueError(f"path.design_speed_mph: {speed:g} is not 20 or 30 "
                         f"(HDM Table 1003.1)")
    strip = pp.get("strip") or {}
    if not isinstance(strip, dict):
        raise ValueError("path.strip: a mapping ({max_ratio})")
    courses = _courses(pp.get("courses"))
    return Path(
        side=side, s_start=float(s0), s_end=float(s1), separation=separation,
        width=width, cross_slope=cs, shoulder_width=sw, shoulder_slope=ss,
        courses=tuple(courses),
        profile=_profile(pp.get("profile"), "path.profile", s0, s1),
        design_speed=int(speed),
        strip_ratio=_num(strip.get("max_ratio", 2.0), "path.strip.max_ratio"),
        approach=_num(pp.get("approach_ft", 100.0), "path.approach_ft"),
        deck_separation=_num(pp.get("deck_separation_ft", 1.5),
                             "path.deck_separation_ft"),
        rail_height=_num(pp.get("rail_height_ft", 3.5), "path.rail_height_ft"),
        road_profile=profile, alignment=alignment)


def stations_extra(c) -> list:
    """The stations a corridor with a path cuts sections at, beside V1.1's:
    the path's ends and a foot outside them (where its section turns into
    the road's own), its separation rows, its vertical curves' BVC, PVI and
    EVC, and enough inside each curve to hold its chords to
    sweep.VC_SAGITTA_FT (frame.densify does this for the road's profile
    only)."""
    from bimforge.author.sweep import VC_SAGITTA_FT
    p = c.path
    out = [p.s_start, p.s_end]
    out += [x for x in (p.s_start - PATH_TRANSITION_FT, p.s_end + PATH_TRANSITION_FT)
            if c.s_start + _EPS < x < c.s_end - _EPS]
    out += [s for s, _v in p.separation]
    for cv in p.profile.curves:
        a, length = cv["bvc_station"], cv["length_ft"]
        out += [a, a + 0.5 * length, a + length]
        dg = abs(cv["g_out_pct"] - cv["g_in_pct"]) / 100.0
        if dg > 1e-12:
            n = math.ceil(length / math.sqrt(8.0 * VC_SAGITTA_FT * length / dg) - _EPS)
            out += [a + length * i / n for i in range(1, n)]
    return out


def validate(c) -> None:
    """The path's checks that need the whole corridor `c`; ValueError names
    the field and the station."""
    p = c.path
    for g in c.gaps:
        if (g.kind == "wall" and g.auto is None and g.side == p.side
                and g.start < p.s_end - _EPS and g.end > p.s_start + _EPS):
            raise ValueError(
                f"gaps: a listed wall gap on the {g.side} side, {sta(g.start)} to "
                f"{sta(g.end)}, overlaps the path's stations ({sta(p.s_start)} to "
                f"{sta(p.s_end)}): its offset would be ambiguous; use walls: auto")
```

- [ ] **Step 4: Wire it into** `bimforge/author/corridor/params.py`

Add a field at the end of `Corridor` (after `guard`):

```python
    #: V1.2 C: the shared-use path beside the road (corridor.path.Path)
    path: object = None
```

Add this method to `Corridor` (after `wall`):

```python
    def path_at(self, s: float) -> bool:
        """Whether the path is part of the section at station s (V1.2 C): on
        its stations, and not strictly inside a structure gap (there it is
        on the deck, and no section is cut)."""
        p = self.path
        if p is None or not p.covers(s):
            return False
        return not any(g.kind == "structure" and g.start + _EPS < s < g.end - _EPS
                       for g in self.gaps)
```

In `Corridor.stations`, before `cuts.update(extra)`:

```python
        if self.path is not None:
            from bimforge.author.corridor.path import stations_extra
            cuts.update(stations_extra(self))
```

Change `parse`'s signature and docstring:

```python
def parse(params: dict, s_start: float, s_end: float, alignment=None,
          profile=None) -> Corridor:
    """The corridor `params` describe on an alignment from `s_start` to
    `s_end`; ValueError names the first field that is wrong. A `path:`
    (V1.2 C) is placed against the road's `alignment` and `profile`
    (bimforge.author.alignment.Alignment and Profile), which it needs."""
```

and replace its final `return Corridor(...)` with the same constructor bound to `c`, its `guard=` changed so a path brings a guardrail as a steep rule does, then the path:

```python
    c = Corridor(
        s_start=float(s_start), s_end=float(s_end),
        components=tuple(comps), courses=tuple(_courses(sec)),
        slopes=slopes,
        widths=_widths(params, [comp.name for comp in comps], s_start, s_end),
        superelevation=tuple(_superelevation(params, s_start, s_end)),
        gaps=tuple(_gaps(params, s_start, s_end)),
        interval=_num(st.get("interval", 25.0), "stations.interval"),
        band=_num(st.get("band", 100.0), "stations.band"),
        shrink=shrink, swell=swell,
        auto_walls=walls == "auto",
        max_wall_height=_num(params.get("max_wall_height_ft", 30.0),
                             "max_wall_height_ft"),
        guard=_guard(params.get("guardrail"),
                     slopes.steep is not None or params.get("path") is not None))
    if params.get("path") is None:
        return c
    from bimforge.author.corridor.path import parse_path, validate
    c = replace(c, path=parse_path(params["path"], c, alignment, profile))
    validate(c)
    return c
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_corridor_path.py bimforge/author/tests/test_corridor_params.py bimforge/author/tests/test_road_corridor_v11.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add bimforge/author/corridor/path.py bimforge/author/corridor/params.py bimforge/author/tests/test_corridor_path.py
git commit -F - <<'EOF'
road corridor: params for a shared-use path beside the road (P.6, part C)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

### Task 3: Separation, approaches and meeting the deck

**Files:**
- Modify: `bimforge/author/corridor/path.py`
- Test: `bimforge/author/tests/test_corridor_path.py`

HDM 1003.1(7): at least 5 ft from the road's edge of shoulder to the path's paved edge, except within `approach_ft` of a structure gap's end, where it may narrow to `deck_separation_ft` (traffic, a 1.5 ft barrier, the path, as the deck lays them out); at the gap's end it equals `deck_separation_ft` within 0.01 ft, and the path's profile meets the deck: the road's cross slope at that station (superelevation included) extended from the road's edge of shoulder to the path's paved edge, within 0.01 ft.

The separation is linear between its rows, so its least value on any stretch is at a row or a stretch end: `validate` reads it there, and just outside each approach (an approach that starts under 5 ft has a violation a hair outside it).

- [ ] **Step 1: Write the failing tests** (append to `test_corridor_path.py`)

```python
from bimforge.author.corridor.path import approaches, deck_elevation, on_approach

GAP = [{"from": 1400, "to": 1500, "kind": "structure"}]
#: the deck at its paved edge on the level road: the left edge of shoulder
#: (99.51) and the lane's -2 % over the 1.5 ft deck separation, 0.03 down
DECK = 99.48
#: 10 ft, narrowing over each 100 ft approach to the deck's 1.5 ft
NARROW = [[1000, 10.0], [1300, 10.0], [1400, 1.5], [1500, 1.5], [1600, 10.0]]


def deck_path(elev=DECK, separation=NARROW, **over):
    return path(separation=separation, profile=grade(elev), **over)


def test_an_approach_narrowing_to_the_deck_builds():
    c = corridor(deck_path(), gaps=GAP)
    assert approaches(c) == [(1300.0, 1400.0, 1400.0), (1500.0, 1600.0, 1500.0)]
    assert on_approach(c, 1350.0) and on_approach(c, 1600.0)
    assert not on_approach(c, 1250.0)
    assert deck_elevation(c, 1400.0) == pytest.approx(DECK)
    # the path is on the deck inside the gap: no section is cut there
    assert c.path_at(1400.0) and not c.path_at(1450.0) and c.path_at(1500.0)


def test_the_deck_takes_the_road_s_superelevation():
    # +4 % on the left through the gap: the edge of shoulder 12 x 0.04 -
    # 5 x 0.05 = +0.23 up, and +0.04 x 1.5 = +0.06 more to the path's edge
    se = [[1000, 0.04, -0.04], [2000, 0.04, -0.04]]
    c = corridor(deck_path(100.29), gaps=GAP, superelevation=se)
    assert deck_elevation(c, 1500.0) == pytest.approx(100.29)


@pytest.mark.parametrize("separation, match", [
    ([[1000, 10.0], [1200, 4.0], [1300, 10.0], [1400, 1.5], [1500, 1.5],
      [1600, 10.0]],
     r"path\.separation: 4\.00 ft at 12\+00\.00 is under the 5 ft minimum "
     r"\(HDM 1003\.1\(7\)\) outside an approach to a structure gap"),
    # 5 ft at 12+80 to 1.5 at 14+00: 4.42 ft at 13+00, where the approach
    # starts, so a hair outside it too
    ([[1000, 10.0], [1280, 5.0], [1400, 1.5], [1500, 1.5], [1600, 10.0]],
     r"path\.separation: 4\.42 ft at 13\+00\.00 is under the 5 ft minimum"),
    ([[1000, 10.0], [1300, 10.0], [1350, 1.0], [1400, 1.5], [1500, 1.5],
      [1600, 10.0]],
     r"path\.separation: 1\.00 ft at 13\+50\.00 is under deck_separation_ft 1\.5"),
    ([[1000, 10.0]],
     r"path\.separation: 10\.00 ft at the structure gap's end 14\+00\.00 is not "
     r"deck_separation_ft 1\.5"),
])
def test_bad_separations_are_refused(separation, match):
    with pytest.raises(ValueError, match=match):
        corridor(deck_path(separation=separation), gaps=GAP)


def test_a_path_0_02_ft_off_the_deck_is_refused_and_0_005_builds():
    with pytest.raises(ValueError, match=(
            r"path\.profile: at the structure gap's end 14\+00\.00 the path is "
            r"at 99\.5000 ft and the deck at its paved edge 99\.4800 ft, "
            r"0\.0200 ft off \(more than 0\.01 ft\)")):
        corridor(deck_path(DECK + 0.02), gaps=GAP)
    corridor(deck_path(DECK + 0.005), gaps=GAP)


def test_a_gap_off_the_path_s_stations_is_no_approach():
    c = corridor(path(stations=[1000, 1300]), gaps=GAP)
    assert approaches(c) == []
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_corridor_path.py -q`
Expected: collection ERROR, `ImportError: cannot import name 'approaches'`.

- [ ] **Step 3: Implement** in `bimforge/author/corridor/path.py`. Add these functions before `validate`:

```python
def approaches(c) -> list:
    """[(a, b, end)]: the stretches within approach_ft of a structure gap's
    end on the path's stations, where the separation may narrow to the
    deck's (HDM 1003.1(7)); `end` is the gap end each leads to."""
    p = c.path
    out = []
    for g in c.gaps:
        if g.kind != "structure":
            continue
        if p.covers(g.start):
            out.append((g.start - p.approach, g.start, g.start))
        if p.covers(g.end):
            out.append((g.end, g.end + p.approach, g.end))
    return out


def on_approach(c, s: float) -> bool:
    return any(a - _EPS <= s <= b + _EPS for a, b, _e in approaches(c))


def deck_elevation(c, s: float) -> float:
    """The deck at the path's paved edge at station s: the road's edge of
    shoulder, then the road's cross slope there (superelevation included)
    over the separation."""
    from bimforge.author.corridor.section import grade_edge
    p = c.path
    prof = p.road_profile
    g = prof.grade(s)
    _u, v = grade_edge(c, s, p.side)
    return (prof.elev(s) + v / math.sqrt(1.0 + g * g)
            + c.cross_slope(p.side, s) * p.separation_at(s))


def _on_deck(c, s: float) -> bool:
    return any(g.kind == "structure" and g.start + _EPS < s < g.end - _EPS
               for g in c.gaps)
```

Append to the end of `validate`:

```python
    zones = approaches(c)
    near = 1e-6                    # just outside an approach
    at = {s for s, _v in p.separation} | {p.s_start, p.s_end}
    for a, b, _e in zones:
        at |= {a, b, a - near, b + near}
    for g in c.gaps:
        if g.kind == "structure":
            at |= {g.start, g.end}
    for s in sorted(at):
        if not p.covers(s) or _on_deck(c, s):
            continue
        sep = p.separation_at(s)
        if sep < p.deck_separation - _EPS:
            raise ValueError(f"path.separation: {sep:.2f} ft at {sta(s)} is under "
                             f"deck_separation_ft {p.deck_separation:g}")
        if (sep < MIN_SEPARATION_FT - _EPS
                and not any(a - _EPS <= s <= b + _EPS for a, b, _e in zones)):
            raise ValueError(
                f"path.separation: {sep:.2f} ft at {sta(s)} is under the "
                f"{MIN_SEPARATION_FT:g} ft minimum (HDM 1003.1(7)) outside an "
                f"approach to a structure gap")
    for e in sorted({e for _a, _b, e in zones}):
        sep = p.separation_at(e)
        if abs(sep - p.deck_separation) > MEET_TOL_FT:
            raise ValueError(
                f"path.separation: {sep:.2f} ft at the structure gap's end "
                f"{sta(e)} is not deck_separation_ft {p.deck_separation:g}: the "
                f"path meets the deck there")
        got, deck = p.profile.elev(e), deck_elevation(c, e)
        if abs(got - deck) > MEET_TOL_FT:
            raise ValueError(
                f"path.profile: at the structure gap's end {sta(e)} the path is at "
                f"{got:.4f} ft and the deck at its paved edge {deck:.4f} ft, "
                f"{abs(got - deck):.4f} ft off (more than {MEET_TOL_FT:g} ft)")
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_corridor_path.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bimforge/author/corridor/path.py bimforge/author/tests/test_corridor_path.py
git commit -F - <<'EOF'
road corridor: the path's separation, approaches and deck meeting (P.6, part C)

HDM 1003.1(7): 5 ft from the edge of shoulder outside an approach, the
deck's separation at a structure gap's end, and the path's profile on the
deck's line there within 0.01 ft.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

### Task 4: The path's surface and its courses, normal to its own grade

**Files:**
- Modify: `bimforge/author/corridor/path.py`
- Test: `bimforge/author/tests/test_corridor_path.py`

The road's sections are cut square to the road's 3D tangent; a point `v` up in that plane stands at elevation `E(s) + v cos γ` and `v sin γ` down-station of `s` (`frame.survey_point`). The path's profile is an elevation by road station, so its `v` is found by fixed point (`section_v`). Each path course is `thickness / cos θ` deep in the plane, θ the angle between the plane's normal (the road's 3D tangent) and the path centre's 3D tangent: the plane's sweep then has volume `W t × PathLength` (spec, Dimensions and formulas).

Hand values. On the level road (`v` is elevation less 100): the left edge of shoulder (17, -0.49); 10 ft out the paved inner edge at the profile's 99.51, (27, -0.49); 12 ft on at -2 %, (39, -0.73); the shoulders 2 ft at -5 % falling away from the paved path: q (25, -0.59), o (41, -0.83). On a road at 3 %, a target 2 ft under the road's grade line at every station: the fixed point is `v = (E(s - v sin γ) - 2 - E(s)) / cos γ`, so `v (1 + g²) = -2 / cos γ`, `v = -2 / sqrt(1 + g²) = -2 / sqrt(1.0009) = -1.99910`. A path at 5 % on that road, on a tangent: the road's tangent is (1, 0.03), the path's (1, 0.05), `cos θ = (1 + 0.03 × 0.05) / sqrt(1.0009 × 1.0025) = 0.9998006583`.

- [ ] **Step 1: Write the failing tests** (append to `test_corridor_path.py`)

```python
from bimforge.author.corridor.path import (course_rings, cos_theta, section_v,
                                           surface)


def pt(xy):
    return pytest.approx(xy, abs=1e-9)


def test_the_path_s_surface_on_a_level_road():
    sf = surface(corridor(), 1500.0)
    assert sf.edge == pt((17.0, -0.49))
    assert sf.inner == pt((27.0, -0.49))
    assert sf.outer == pt((39.0, -0.73))
    assert sf.q == pt((25.0, -0.59))
    assert sf.o == pt((41.0, -0.83))
    assert (sf.separation, sf.cg) == (10.0, 1.0)
    assert sf.cos_theta == pytest.approx(1.0, abs=1e-12)
    assert sf.depth == pytest.approx(0.75)


def test_on_the_right_the_path_mirrors():
    sf = surface(corridor(path(side="R")), 1500.0)
    assert sf.inner == pt((-27.0, -0.49))
    assert sf.o == pt((-41.0, -0.83))


def test_a_widened_shoulder_moves_the_path_out():
    # the left shoulder is 10 ft from 11+00: the edge of shoulder 22 ft out
    # and 0.24 + 0.50 down; the path keeps its 10 ft from it
    c = corridor(widths=[{"component": "shoulder", "side": "L",
                          "at": [[1000, 5.0], [1100, 10.0]]}])
    sf = surface(c, 1150.0)
    assert sf.edge == pt((22.0, -0.74))
    assert (sf.inner[0], sf.q[0], sf.o[0]) == pytest.approx((32.0, 30.0, 46.0))


def test_near_the_deck_the_inner_shoulder_narrows_to_the_separation():
    # 1.5 ft from the edge: the inner shoulder is 1.49 ft (STEP_FT short),
    # so q stays outside the road's edge of shoulder
    c = corridor(deck_path(), gaps=GAP)
    sf = surface(c, 1400.0)
    assert sf.q[0] == pytest.approx(17.0 + 0.01)


def test_section_v_finds_an_elevation_in_the_leaning_plane():
    road = Profile(grade(100.0, pct=3.0)["curves"])
    c = corridor(path(profile=grade(97.51, pct=3.0)), prof=road)
    got = section_v(c.path, 1500.0, 30.0, lambda st: road.elev(st) - 2.0)
    assert got == pytest.approx(-2.0 / math.sqrt(1.0009), rel=1e-9)


def test_cos_theta_is_the_road_s_tangent_against_the_path_s():
    road = Profile(grade(100.0, pct=3.0)["curves"])
    c = corridor(path(profile=grade(99.51, pct=5.0)), prof=road)
    want = (1 + 0.03 * 0.05) / math.sqrt(1.0009 * 1.0025)
    assert cos_theta(c, 1500.0) == pytest.approx(want, rel=1e-9)
    sf = surface(c, 1500.0)
    rings = course_rings(c.path, sf)
    # each course thickness / cos theta deep in the plane, top down
    (ui, vi), (uo, vo) = sf.inner, sf.outer
    d0, d1 = 0.25 / want, 0.5 / want
    assert rings[0] == pytest.approx([(ui, vi), (uo, vo), (uo, vo - d0),
                                      (ui, vi - d0)])
    assert rings[1] == pytest.approx([(ui, vi - d0), (uo, vo - d0),
                                      (uo, vo - d0 - d1), (ui, vi - d0 - d1)])
    assert sf.depth == pytest.approx(d0 + d1)
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_corridor_path.py -q`
Expected: collection ERROR, `ImportError: cannot import name 'course_rings'`.

- [ ] **Step 3: Implement** (append to `bimforge/author/corridor/path.py`)

```python
@dataclass(frozen=True)
class Surface:
    """The path's finished surface at a station, in section coordinates."""
    edge: tuple            # the road's outer edge of shoulder
    q: tuple               # the road-side edge of the path's inner shoulder
    inner: tuple           # the paved inner edge, `separation` out from edge
    outer: tuple           # the paved outer edge
    o: tuple               # the outer edge of the outer shoulder
    separation: float
    cos_theta: float       # the plane's normal against the path's tangent
    depth: float           # the courses' depth in the plane: sum t / cos theta
    cg: float              # cos of the road's grade: v to elevation


def section_v(p, s: float, u: float, z_at) -> float:
    """v of the point at offset u in station s's section plane whose
    elevation is z_at(station), read at the station where the point lies:
    the plane leans back v sin(gamma) along the road (frame.survey_point),
    (1 - kappa u) to a foot of the road's on a curve. Fixed point; four
    rounds take it to 1e-10 at grades under 10 %."""
    prof = p.road_profile
    g = prof.grade(s)
    root = math.sqrt(1.0 + g * g)
    cg, sg = 1.0 / root, g / root
    scale = 1.0 - p.alignment.curvature(s) * u
    z0 = prof.elev(s)
    v = (z_at(s) - z0) / cg
    for _ in range(4):
        v = (z_at(s - v * sg / scale) - z0) / cg
    return v


def _centre(c, s: float) -> tuple:
    """(u, v) of the paved path's centre at finished grade, station s."""
    from bimforge.author.corridor.section import grade_edge
    p = c.path
    u = grade_edge(c, s, p.side)[0] + p.sign * (p.separation_at(s) + 0.5 * p.width)
    half = 0.5 * p.width * p.cross_slope
    return u, section_v(p, s, u, lambda st: p.profile.elev(st) + half)


def cos_theta(c, s: float, h: float = 0.5) -> float:
    """cos of the angle between station s's section plane's normal (the
    road's 3D tangent) and the paved centre's 3D tangent there: its grade
    against the road's, its drift as the separation changes, and its twist
    on a graded curve, all in one. The tangent is the chord over s +/- h,
    which on a curve of constant curvature and grade is parallel to it."""
    from bimforge.author.corridor.frame import survey_point
    p = c.path
    al, prof = p.alignment, p.road_profile
    a, b = (survey_point(al, prof, x, *_centre(c, x)) for x in (s - h, s + h))
    d = [y - x for x, y in zip(a, b)]
    _n, _e, az = al.point_az(s)
    t = math.radians(az)
    g = prof.grade(s)
    cg = 1.0 / math.sqrt(1.0 + g * g)
    t3 = (math.cos(t) * cg, math.sin(t) * cg, g * cg)
    return sum(x * y for x, y in zip(t3, d)) / math.sqrt(sum(x * x for x in d))


def surface(c, s: float) -> Surface:
    """The path's finished surface at station s: the paved inner edge
    `separation` ft out from the road's outer edge of shoulder (so it moves
    out where the road widens) at the path's profile, the paved width at
    `cross_slope`, a shoulder each side at `shoulder.slope` falling away
    from the paved path. The inner shoulder is no wider than the
    separation less STEP_FT, so near a deck q stays off the road."""
    from bimforge.author.corridor.section import grade_edge
    p = c.path
    edge = grade_edge(c, s, p.side)
    sep = p.separation_at(s)
    g = p.road_profile.grade(s)
    cg = 1.0 / math.sqrt(1.0 + g * g)
    ui = edge[0] + p.sign * sep
    vi = section_v(p, s, ui, p.profile.elev)

    def at(du, dz):
        return (ui + p.sign * du, vi + dz / cg)

    w, sw = p.width, p.shoulder_width
    inner_sw = min(sw, max(sep - STEP_FT, 0.0))
    cos_t = cos_theta(c, s)
    return Surface(edge=edge, q=at(-inner_sw, p.shoulder_slope * inner_sw),
                   inner=(ui, vi), outer=at(w, p.cross_slope * w),
                   o=at(w + sw, p.cross_slope * w + p.shoulder_slope * sw),
                   separation=sep, cos_theta=cos_t,
                   depth=p.depth() / cos_t, cg=cg)


def course_rings(p, sf: Surface) -> dict:
    """{course index: 4-point ring}: the path's courses under its paved
    width, top down, each thickness / cos theta deep in the section plane
    (its thickness held normal to the path's grade)."""
    (ui, vi), (uo, vo) = sf.inner, sf.outer
    out, above = {}, 0.0
    for k, course in enumerate(p.courses):
        d = course.thickness / sf.cos_theta
        out[k] = [(ui, vi - above), (uo, vo - above), (uo, vo - above - d),
                  (ui, vi - above - d)]
        above += d
    return out
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_corridor_path.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bimforge/author/corridor/path.py bimforge/author/tests/test_corridor_path.py
git commit -F - <<'EOF'
road corridor: the path's surface and its courses normal to its grade (P.6, part C)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

### Task 5: The strip, and the path's side of the section

**Files:**
- Modify: `bimforge/author/corridor/path.py`
- Modify: `bimforge/author/corridor/params.py` (`Gap.strip`, `Gap.carries`, `Corridor.wall(strip=)`)
- Modify: `bimforge/author/corridor/section.py`
- Test: `bimforge/author/tests/test_corridor_path.py`

The strip runs from the road's hinge H to q, the road-side edge of the path's inner shoulder. At each station, in the spec's order:
1. **Natural ground between:** the road's V1.1 slope from H and the path's inner slope from q (mirrored), each held to the strip's width and no footprint, both daylight, and the road's daylight is no farther from H than the path's. The line is road slope, `GROUND_SAMPLES` points on the ground between, path slope back to q.
2. **A slope:** the straight line H to q, at `strip.max_ratio` (2:1) or flatter, up or down. Where the road is higher and the line is steeper than `fill.ratio`, the road is **guarded**: the V1.1 10:1 widening is taken out of the strip (held inside it), and the rest must be 2:1 or flatter, else a wall. On an approach the line is taken whatever its slope: the deck's barrier layout stands there (decision 5).
3. **Road higher, too steep:** wall `strip-road` at H, the strip level at q's elevation from its foot.
4. **Path higher, too steep:** wall `strip-path` at q, the strip level at H's elevation from the road to its foot.

A wall needs `walls: auto` (Task 6 places them); without one the station's resolve raises `section.NoDaylight` with kind `strip-road` or `strip-path`, a `ValueError` naming the station. The path's outer slope from o follows V1.1's rules with no MGS widening (a path takes no guardrail), or stands at an automatic `path-fill` / `path-cut` wall.

The side's line is the strip padded to `strip_count(c)` points (`_fixed`), then the path's top (`TOP_POINTS`: q, a step down the courses' inner edge, under the courses, up their outer edge, o), then the outer slope padded to `side_samples(c)`: `side_count(c)` points at every station. A station without the path pads the road's own V1.1 side to the same count (`Section.side_counts`).

Hand values on the level road, the ground level at -5 (95.0), sep 10 (strip 8 ft):
- **Level** (the path at 99.51): H (17, -1.89), q (25, -0.59); the road's 2:1 fill would daylight 6.22 ft out, but the path's inner fill would need 2 × 4.41 = 8.82 > 8: no natural ground; the line rises 1.30 over 8: 6.1538:1, a slope. Its outer fill: from o (41, -0.83) 2:1 down 4.17 to (49.34, -5).
- **3 ft below** (96.51): q (25, -3.59): the road's daylight at 23.22 is past the path's at 25 - 2 × 1.41 = 22.18: they cross; 8 / 1.70 = 4.7059:1, a slope, the road higher but flatter than BASE's 2:1 fill ratio.
- **Guarded**, sep 20, fill.ratio 4.0, the path 6 ft below (93.51): q (35, -6.59), 18 / 4.70 = 3.83:1, steeper than 4:1 below a higher road: guarded. The widening from the edge (17, -0.49): (17.01, -0.491), (20.94, -0.884); the rest to q, 14.06 across, 5.706 down: 2.4641:1, it fits.
- **12 ft below** (87.51): q (25, -12.59), 8 / 10.70 = 0.75:1: `strip-road`; with the wall, the line H, (17.01, -12.59), q.
- **12 ft above** (111.51): q (25, 11.41), 13.30 up over 8: `strip-path`; with the wall, the line H, (24.99, -1.89), q.
- **Natural**, the ground at -3, sep 60 (q at 75): the road's 2:1 fill daylights 2 × 1.11 = 2.22 ft out at (19.22, -3), the path's 2 × 2.41 = 4.82 ft in from q at (70.18, -3): ground between.

- [ ] **Step 1: Write the failing tests** (append to `test_corridor_path.py`)

```python
from bimforge.author.corridor.path import TOP_POINTS, side_count, strip_count
from bimforge.author.corridor.section import (SIDE_SAMPLES, NoDaylight,
                                              needs_wall, resolve)


def level(h):
    """Level ground h ft above the road's profile grade line."""
    return lambda s, u, v: h - v


def on(line, xy):
    return any(abs(u - xy[0]) < 1e-6 and abs(v - xy[1]) < 1e-6 for u, v in line)


def test_point_counts():
    c = corridor()
    assert strip_count(c) == 2 * SIDE_SAMPLES + 8
    assert side_count(c) == strip_count(c) + TOP_POINTS - 1 + SIDE_SAMPLES - 1


def test_a_path_level_with_the_road_takes_a_strip_slope():
    c = corridor()
    sec = resolve(c, 1500.0, level(-5.0))
    ps, side = sec.path, sec.sides["L"]
    assert (ps.strip, side.kind, side.guarded) == ("slope", "path", False)
    assert ps.ratio == pytest.approx(8.0 / 1.30)
    assert len(side.line) == side_count(c) == sec.count("L")
    assert side.line[0] == pt((17.0, -1.89))
    for xy in ((25.0, -0.59), (26.99, -0.4905), (27.0, -1.24), (39.0, -1.48),
               (39.01, -0.7305), (41.0, -0.83)):
        assert on(side.line, xy), xy                     # the path's top
    assert side.line[-1] == pt((49.34, -5.0))            # 2:1 from o
    assert ps.courses[0] == pytest.approx([(27, -0.49), (39, -0.73),
                                           (39, -0.98), (27, -0.74)])
    # the road's other side is V1.1's: 2:1 from its hinge to the ground
    assert sec.sides["R"].line[-1] == pt((-23.22, -5.0))
    assert sec.count("R") == SIDE_SAMPLES
    assert len(sec.earthwork_line()) == (
        side_count(c) + 2 + 2 + SIDE_SAMPLES - 1)        # + the road's subgrade


def test_a_path_3_ft_below_takes_a_slope_that_fits():
    sec = resolve(corridor(path(profile=grade(96.51))), 1500.0, level(-5.0))
    assert sec.path.strip == "slope"
    assert sec.path.ratio == pytest.approx(8.0 / 1.70)


def test_a_steep_strip_below_a_higher_road_is_guarded():
    p = path(separation=[[1000, 20.0]], profile=grade(93.51))
    side_slopes = dict(BASE["section"]["side_slopes"], fill={"ratio": 4.0})
    c = corridor(p, section=dict(BASE["section"], side_slopes=side_slopes))
    sec = resolve(c, 1500.0, level(-5.0))
    assert (sec.path.strip, sec.sides["L"].guarded) == ("guarded", True)
    assert sec.path.ratio == pytest.approx(14.06 / 5.706)
    assert on(sec.sides["L"].line, (17.01, -0.491))
    assert on(sec.sides["L"].line, (20.94, -0.884))


def test_a_path_12_ft_below_needs_a_wall_at_the_road_s_hinge():
    p = path(profile=grade(87.51))
    c = corridor(p)
    assert needs_wall(c, 1500.0, "L", level(-5.0), location="strip") == "strip-road"
    with pytest.raises(NoDaylight, match=r"station 15\+00\.00: the L strip between "
                       r"the road and the path does not fit at 2:1 or flatter"):
        resolve(c, 1500.0, level(-5.0))
    c = corridor(p, walls="auto").with_walls(
        [Gap(1400.0, 1600.0, "wall", "L", None, auto="strip-road")])
    sec = resolve(c, 1500.0, level(-5.0))
    assert sec.path.strip == "wall-road"
    line = sec.sides["L"].line
    assert line[0] == pt((17.0, -1.89))
    assert on(line, (17.01, -12.59)) and on(line, (25.0, -12.59))


def test_a_path_12_ft_above_needs_a_wall_at_its_shoulder():
    p = path(profile=grade(111.51))
    assert needs_wall(corridor(p), 1500.0, "L", level(-5.0),
                      location="strip") == "strip-path"
    c = corridor(p, walls="auto").with_walls(
        [Gap(1400.0, 1600.0, "wall", "L", None, auto="strip-path")])
    sec = resolve(c, 1500.0, level(-5.0))
    assert sec.path.strip == "wall-path"
    assert on(sec.sides["L"].line, (24.99, -1.89))
    assert on(sec.sides["L"].line, (25.0, 11.41))


def test_a_path_drifted_out_leaves_natural_ground_between():
    c = corridor(path(separation=[[1000, 10.0], [1100, 60.0]]))
    sec = resolve(c, 1150.0, level(-3.0))
    assert sec.path.strip == "ground"
    line = sec.sides["L"].line
    assert on(line, (19.22, -3.0)) and on(line, (70.18, -3.0))
    between = [(u, v) for u, v in line if 19.22 + 1e-6 < u < 70.18 - 1e-6]
    assert len(between) >= 8 and all(v == pytest.approx(-3.0) for _u, v in between)


def test_without_the_path_the_side_pads_to_the_path_s_count():
    c = corridor(path(stations=[1200, 1800]))
    sec = resolve(c, 1100.0, level(-5.0))
    assert sec.path is None and sec.sides["L"].kind == "fill"
    assert sec.count("L") == side_count(c)
    assert len(sec.earthwork_line()) == len(
        resolve(c, 1500.0, level(-5.0)).earthwork_line())
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_corridor_path.py -q`
Expected: collection ERROR, `ImportError: cannot import name 'TOP_POINTS'`.

- [ ] **Step 3: Implement the wall tokens** in `bimforge/author/corridor/params.py`. Add to `Gap`:

```python
    @property
    def strip(self) -> bool:
        """An automatic wall in the strip between the road and its path
        (V1.2 C): `strip-road` at the road's hinge, `strip-path` at the
        path's inner shoulder."""
        return (self.auto or "").startswith("strip-")

    @property
    def carries(self) -> str:
        """What a wall's stretch carries, as a structure candidate: the
        road, or the path (a strip wall, or a wall on the path's outer side,
        `path-fill` / `path-cut`)."""
        return "path" if (self.auto or "").startswith(("strip-", "path-")) else "road"
```

and replace `Corridor.wall` with:

```python
    def wall(self, side: str, s: float, strip: bool = False) -> Gap | None:
        """The wall gap on `side` at station s: an outer one (a listed wall,
        a V1.1 automatic wall, a wall on the path's outer side), or with
        `strip` one in the strip between the road and its path."""
        for g in self.gaps:
            if (g.kind == "wall" and g.side == side and g.strip == strip
                    and g.start - _EPS <= s <= g.end + _EPS):
                return g
        return None
```

- [ ] **Step 4: Implement the section changes** in `bimforge/author/corridor/section.py`.

Give `_slope` a `widen` keyword (V1.1 calls keep the default):

```python
def _slope(c, s: float, side: str, sign: float, hinge: tuple, ground_dz,
           rail: bool = False, widen: bool = True) -> Side:
```

add to its docstring: "With `widen` False (the path's slopes, V1.2 C) the steep ratio still applies over its height but no widening is taken: the points collapse onto the hinge as where no rail runs.", and change its fill branch's widening line to:

```python
        pts += (_widening(c, s, side, sign) if widen and (guarded or rail)
                else collapsed)
```

and its cut branch's start to:

```python
        start = [hinge] + (_widening(c, s, side, sign) if widen and rail
                           else collapsed)
```

Add two fields at the end of `Section`, and a `count` method; `earthwork_line` reads it:

```python
    #: V1.2 C: side -> its slope line's point count where it is not
    #: `samples` (the path's side: path.side_count)
    side_counts: dict | None = None
    #: V1.2 C: the path's part of the section (path.PathSection), or None
    path: object = None

    def count(self, side: str) -> int:
        return (self.side_counts or {}).get(side, self.samples)
```

and in `earthwork_line` replace the two `_samples(..., self.samples)` calls:

```python
        left = list(reversed(_samples(self.sides["L"].line, self.count("L"))))
        ...
        right = _samples(self.sides["R"].line, self.count("R"))[1:]
```

Give `needs_wall` a location; the path's side is the path module's:

```python
def needs_wall(c, s: float, side: str, ground_dz, rail: bool = False,
               location: str = "outer") -> str | None:
    """The wall `side` needs at station s when its slope does not fit (no
    daylight within the limit, or past the footprint): "cut" or "fill";
    None when it fits, or where a wall gap already stands. With `rail`, the
    slope behind a guardrail's widening (_slope). V1.2 C: on the path's
    side, where the path is, `location` "outer" asks of the path's outer
    slope ("path-fill" or "path-cut") and "strip" of the strip between the
    road and the path ("strip-road" or "strip-path")."""
    if c.path is not None and side == c.path.side and c.path_at(s):
        from bimforge.author.corridor import path as path_mod
        u, v = grade_edge(c, s, side)
        return path_mod.needs_wall(c, s, (u, v - c.depth()),
                                   _named(ground_dz, side), rail, location)
    if location != "outer" or c.wall(side, s) is not None:
        return None
    sign = 1.0 if side == "L" else -1.0
    u, v = grade_edge(c, s, side)
    try:
        _slope(c, s, side, sign, (u, v - c.depth()), _named(ground_dz, side),
               rail)
    except NoDaylight as exc:
        return exc.kind
    return None
```

In `resolve`, the path's side goes to `path.side()` where the path is, and every section of a corridor with a path carries its side's count:

```python
def resolve(c, s: float, ground_dz, rail=()) -> Section:
    """The section of corridor `c` at station `s` (params.Corridor). `rail`
    names the sides a guardrail runs past at s: each takes the widening
    behind it (_slope). V1.2 C: where the path is (c.path_at), its side is
    path.side's: the strip, the path and its outer slope."""
    depth = c.depth()
    grade, subgrade, courses, sides = {}, {}, {}, {}
    counts, path_sec = None, None
    if c.path is not None:
        from bimforge.author.corridor import path as path_mod
        counts = {c.path.side: path_mod.side_count(c)}
    for side in SIDES:
        sign = 1.0 if side == "L" else -1.0
        pts = _grade(c, s, side)
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
        if c.path is not None and side == c.path.side and c.path_at(s):
            sides[side], path_sec = path_mod.side(
                c, s, subgrade[side][-1], _named(ground_dz, side), side in rail)
        else:
            sides[side] = _side(c, s, side, sign, subgrade[side][-1],
                                _named(ground_dz, side), side in rail)
    return Section(s, grade, courses, subgrade, sides, side_samples(c),
                   side_counts=counts, path=path_sec)
```

- [ ] **Step 5: Implement the strip and the side** (append to `bimforge/author/corridor/path.py`)

```python
#: the path's earthwork top, q to o: q, a step down the courses' inner edge,
#: under the courses, up their outer edge, o
TOP_POINTS = 6


@dataclass(frozen=True)
class PathSection:
    """The path's part of a section (section.Section.path)."""
    strip: str             # "ground", "slope", "guarded", "wall-road", "wall-path"
    ratio: float | None    # the strip's slope ratio (from the widening's hinge
                           # where guarded); None on natural ground or a wall
    surface: Surface
    courses: dict          # course index -> 4-point ring under the paved width


def strip_count(c) -> int:
    """The strip's points on the earthwork line: room for the road's slope
    and the path's inner slope (section.side_samples each) and the ground
    between them."""
    from bimforge.author.corridor.section import side_samples
    return 2 * side_samples(c) + GROUND_SAMPLES


def side_count(c) -> int:
    """The path side's points on every section's earthwork line: the strip,
    the path's top (its first point the strip's last) and its outer slope
    (its first the top's last). A station without the path pads the road's
    own side to it."""
    from bimforge.author.corridor.section import side_samples
    return strip_count(c) + TOP_POINTS - 1 + side_samples(c) - 1


def _fixed(points: list, n: int) -> list:
    """`points` with points added halfway along the longest segment, the
    first of equals, until there are `n`: the line is unchanged."""
    pts = list(points)
    if len(pts) > n:
        raise ValueError(f"the path's strip has {len(pts)} points, more than "
                         f"its {n}")
    while len(pts) < n:
        k = max(range(len(pts) - 1), key=lambda i: math.dist(pts[i], pts[i + 1]))
        (u0, v0), (u1, v1) = pts[k], pts[k + 1]
        pts.insert(k + 1, (0.5 * (u0 + u1), 0.5 * (v0 + v1)))
    return pts


def _ratio(a: tuple, b: tuple, cg: float) -> float:
    """The slope a to b, horizontal per vertical (inf where level)."""
    dz = abs(a[1] - b[1]) * cg
    return math.inf if dz < 1e-9 else abs(a[0] - b[0]) / dz


def _no_fit(c, s: float, a: tuple, q: tuple, cg: float) -> str:
    p = c.path
    dz = (a[1] - q[1]) * cg
    return (f"station {sta(s)}: the {p.side} strip between the road and the path "
            f"does not fit at {p.strip_ratio:g}:1 or flatter: the road "
            f"{abs(dz):.2f} ft {'above' if dz > 0 else 'below'} the path's "
            f"shoulder edge, {abs(q[0] - a[0]):.2f} ft from it; set walls: auto "
            f"for a wall there")


def _widening(c, s: float, room: float) -> list:
    """The road's guardrail widening (section._widening) on the path's
    side, held inside the strip: its hinge no farther out than STEP_FT
    short of q."""
    from bimforge.author.corridor.params import WIDENING_SLOPE
    from bimforge.author.corridor.section import GUARD_STEP_FT, grade_edge
    p = c.path
    eu, ev = grade_edge(c, s, p.side)
    far = max(min(c.guard.widening, room - STEP_FT), GUARD_STEP_FT)
    return [(eu + p.sign * w, ev - WIDENING_SLOPE * w) for w in (GUARD_STEP_FT, far)]


def _on_ground(c, s: float, a: tuple, b: tuple, ground_dz) -> list:
    """GROUND_SAMPLES points evenly between a and b, each moved up or down
    onto the ground."""
    g = c.path.road_profile.grade(s)
    cg = 1.0 / math.sqrt(1.0 + g * g)
    out = []
    for i in range(1, GROUND_SAMPLES + 1):
        t = i / (GROUND_SAMPLES + 1)
        u, v = a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
        for _ in range(3):
            v += ground_dz(s, u, v) / cg
        out.append((u, v))
    return out


def _natural(c, s: float, hinge: tuple, q: tuple, room: float, ground_dz,
             rail: bool) -> tuple | None:
    """The strip as two slopes with natural ground between, or None: the
    road's slope from the hinge (V1.1's rules, with the rail's widening
    where one runs) and the path's inner slope from q toward the road (the
    same rules mirrored, no widening), each held to the strip's width and
    no footprint, both daylighting, the road's no farther from the hinge
    than the path's."""
    from dataclasses import replace

    from bimforge.author.corridor.section import NoDaylight, _slope
    p = c.path
    free = replace(c, slopes=replace(c.slopes, footprint=None, daylight_limit=room))
    try:
        road = _slope(free, s, p.side, p.sign, hinge, ground_dz, rail)
        back = _slope(free, s, p.side, -p.sign, q, ground_dz, widen=False)
    except NoDaylight:
        return None
    dr, dp = road.line[-1], back.line[-1]
    if abs(dr[0] - hinge[0]) > abs(dp[0] - hinge[0]) + _EPS:
        return None                                   # the slopes cross
    pts = road.line + _on_ground(c, s, dr, dp, ground_dz) + back.line[::-1]
    return pts, "ground", None, road.guarded


def _strip(c, s: float, sf: Surface, hinge: tuple, ground_dz,
           rail: bool = False) -> tuple:
    """(points from the hinge to q, mode, ratio, guarded): the strip at
    station s, resolved in the spec's order (the module's Task 5 notes):
    a wall gap standing here, natural ground between, a slope (guarded
    below a higher road where steeper than fill.ratio), else NoDaylight
    with the wall it needs, "strip-road" or "strip-path". With `rail` the
    road's guardrail widening is taken out of the strip as well."""
    from bimforge.author.corridor.section import NoDaylight
    p = c.path
    sign, q = p.sign, sf.q
    hu, hv = hinge
    wall = c.wall(p.side, s, strip=True)
    if wall is not None:
        if wall.auto == "strip-road":
            # V1.1's automatic fill wall at the hinge, its barrier on top;
            # the strip level at q from its foot
            return [hinge, (hu + sign * STEP_FT, q[1]), q], "wall-road", None, False
        # the wall at q retaining the path, its rail on top; the strip
        # level at the hinge's elevation from the road to its foot
        return [hinge, (q[0] - sign * STEP_FT, hv), q], "wall-path", None, False
    room = abs(q[0] - hu)
    natural = _natural(c, s, hinge, q, room, ground_dz, rail)
    if natural is not None:
        return natural
    approach = on_approach(c, s)
    higher = hv > q[1]
    ratio = _ratio(hinge, q, sf.cg)
    guarded = (higher and not approach and c.guard is not None
               and ratio < c.slopes.fill_ratio - _EPS)
    if guarded or (rail and c.guard is not None):
        w = _widening(c, s, room)
        rest = _ratio(w[-1], q, sf.cg)
        if not approach and rest < p.strip_ratio - _EPS:
            raise NoDaylight(_no_fit(c, s, w[-1], q, sf.cg), "strip-road")
        return [hinge] + w + [q], "guarded" if guarded else "slope", rest, guarded
    if not approach and ratio < p.strip_ratio - _EPS:
        raise NoDaylight(_no_fit(c, s, hinge, q, sf.cg),
                         "strip-road" if higher else "strip-path")
    collapsed = [hinge, hinge] if c.guard is not None else []
    return [hinge] + collapsed + [q], "slope", ratio, False


def _top(c, sf: Surface) -> list:
    """The path's earthwork top, q to o (TOP_POINTS): the inner shoulder at
    finished grade, a STEP_FT step down the courses' inner edge, under the
    courses, up their outer edge, the outer shoulder."""
    p = c.path
    k = p.shoulder_slope * STEP_FT / sf.cg
    (ui, vi), (uo, vo) = sf.inner, sf.outer
    return [sf.q, (ui - p.sign * STEP_FT, vi + k), (ui, vi - sf.depth),
            (uo, vo - sf.depth), (uo + p.sign * STEP_FT, vo + k), sf.o]


def _outer(c, s: float, sf: Surface, ground_dz) -> list:
    """The path's outer slope from o by V1.1's rules, with no MGS widening,
    or [o, o] at an automatic wall on the path's outer side."""
    from bimforge.author.corridor.section import _slope
    p = c.path
    if c.wall(p.side, s) is not None:
        return [sf.o, sf.o]
    return _slope(c, s, p.side, p.sign, sf.o, ground_dz, widen=False).line


def side(c, s: float, hinge: tuple, ground_dz, rail: bool = False) -> tuple:
    """(section.Side, PathSection): the path's side of corridor `c`'s
    section at station s, out from the road's subgrade `hinge`. The Side's
    kind is "path"; it is guarded where the strip is, so the road's rail
    is laid there; its line has side_count(c) points."""
    from bimforge.author.corridor.section import Side, _samples, side_samples
    sf = surface(c, s)
    pts, mode, ratio, guarded = _strip(c, s, sf, hinge, ground_dz, rail)
    line = (_fixed(pts, strip_count(c)) + _top(c, sf)[1:]
            + _samples(_outer(c, s, sf, ground_dz), side_samples(c))[1:])
    return (Side("path", line, guarded, ratio),
            PathSection(mode, ratio, sf, course_rings(c.path, sf)))


def needs_wall(c, s: float, hinge: tuple, ground_dz, rail: bool = False,
               location: str = "outer") -> str | None:
    """section.needs_wall on the path's side where the path is: the strip's
    wall ("strip-road", "strip-path") or the outer side's ("path-fill",
    "path-cut"), None where it fits or a wall gap already stands."""
    from bimforge.author.corridor.section import NoDaylight
    p = c.path
    strip = location == "strip"
    if c.wall(p.side, s, strip=strip) is not None:
        return None
    sf = surface(c, s)
    try:
        if strip:
            _strip(c, s, sf, hinge, ground_dz, rail)
        else:
            _outer(c, s, sf, ground_dz)
    except NoDaylight as exc:
        return exc.kind if strip else f"path-{exc.kind}"
    return None
```

- [ ] **Step 6: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_corridor_path.py bimforge/author/tests/test_corridor_section.py bimforge/author/tests/test_road_corridor.py bimforge/author/tests/test_road_corridor_v11.py -q`
Expected: PASS (V1.1's sections take the defaults: no path, `widen` True).

- [ ] **Step 7: Commit**

```bash
git add bimforge/author/corridor/path.py bimforge/author/corridor/params.py bimforge/author/corridor/section.py bimforge/author/tests/test_corridor_path.py
git commit -F - <<'EOF'
road corridor: the strip between road and path, and the path's side (P.6, part C)

Natural ground between where both slopes daylight apart, else a slope at
strip.max_ratio or flatter (guarded below a higher road where it is
steeper than fill.ratio), else a wall at the road's hinge or at the path's
inner shoulder. The path side's earthwork line has one point count at
every station, so the section's earthwork is counted once.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

### Task 6: Walls in the strip and on the path's outer side

**Files:**
- Modify: `bimforge/author/corridor/walls.py`
- Modify: `bimforge/author/corridor/params.py` (`with_walls` by location)
- Modify: `bimforge/author/families/road_corridor.py` (the road's rail ignores path walls)
- Test: `bimforge/author/tests/test_corridor_walls.py`

`walls.find` looks for outer walls on every side and for strip walls on the path's side, apart, so a station may have both. Strip walls join wall runs as V1.1's do (merged under one station interval apart, 1 ft lead-ins). The walls table gains `location` (`outer` or `strip`); a strip wall's `kind` is `wall-road` or `wall-path`, the strip's labels. Its height is the face at finished grade: for `wall-road` the road's edge of shoulder above the level strip at q's elevation, for `wall-path` q above the hinge's level. A fill wall (the road's, the path's outer `path-fill`) or a strip wall taller than `max_wall_height_ft` is a structure candidate; the structures table gains `carries` (`road` or `path`), and candidates that carry different things are not merged. The road's guardrail ties into the road's walls and `strip-road` walls only.

Hand values, level road with the path 12 ft below (Task 5): the `wall-road` face from the edge of shoulder (-0.49) down to the level strip at -12.59: 12.10 ft, at offset 17; with the path 12 ft above, the `wall-path` face from q (11.41) to the hinge level (-1.89): 13.30 ft, at offset 25.

- [ ] **Step 1: Write the failing tests** (append to `bimforge/author/tests/test_corridor_walls.py`)

```python
from bimforge.author.alignment import Alignment, Profile
from bimforge.author.corridor import walls as W
from bimforge.author.corridor.params import Gap as _Gap
from bimforge.author.corridor.params import parse as _parse

_AL = Alignment({"station": 1000.0, "northing": 0.0, "easting": 0.0},
                [{"kind": "tangent", "bearing": "N 0-0-0 E", "length": 1000.0}],
                name="T")
_PROF = Profile([{"bvc_station": 1000.0, "bvc_elev": 100.0, "g_in_pct": 0.0,
                  "g_out_pct": 0.0, "length_ft": 1000.0, "evc_station": 2000.0,
                  "evc_elev": 100.0}])


def _path_corridor(elev, **over):
    """BASE (the module's) with walls: auto and a path on the left 10 ft
    out, level at `elev`."""
    p = copy.deepcopy(BASE)
    p.update(walls="auto", **over)
    p["path"] = {"side": "L", "separation": [[1000, 10.0]], "width": 12.0,
                 "courses": [{"name": "PATH-AB", "type": "CORE", "thickness": 0.75}],
                 "profile": {"curves": [{"bvc_station": 1000.0, "bvc_elev": elev,
                                         "g_in_pct": 0.0, "g_out_pct": 0.0,
                                         "length_ft": 1000.0, "evc_station": 2000.0,
                                         "evc_elev": elev}]}}
    return _parse(p, 1000.0, 2000.0, alignment=_AL, profile=_PROF)


def _level(h):
    return lambda s, u, v: h - v


def test_a_wall_s_token_says_where_it_stands_and_what_it_carries():
    assert [(_Gap(0, 1, "wall", "L", auto=a).strip, _Gap(0, 1, "wall", "L", auto=a).carries)
            for a in ("fill", "cut", "path-fill", "strip-road", "strip-path")] == [
        (False, "road"), (False, "road"), (False, "path"), (True, "path"),
        (True, "path")]


def test_a_path_far_below_the_road_takes_a_strip_wall_over_its_stations():
    c = _path_corridor(87.51)                              # 12 ft below the edge
    found = W.find(c, [1400.0, 1425.0, 1450.0], _level(-5.0))
    assert [(g.side, g.auto, g.start, g.end) for g in found] == [
        ("L", "strip-road", 1400.0, 1450.0)]               # the run's ends
    c = c.with_walls(found)
    (row,) = [r for r in W.rows(c, [], _level(-5.0)) if r.location == "strip"]
    assert (row.kind, row.carries, row.barrier) == ("wall-road", "path", True)
    # the road's edge of shoulder (-0.49) over the strip at q (-12.59)
    assert row.max_height == pytest.approx(12.10)
    assert row.offset == pytest.approx(17.0)


def test_a_path_far_above_the_road_takes_a_wall_at_its_shoulder():
    c = _path_corridor(111.51)                             # 12 ft above
    c = c.with_walls(W.find(c, [1400.0, 1450.0], _level(-5.0)))
    rows = [r for r in W.rows(c, [], _level(-5.0)) if r.location == "strip"]
    (row,) = rows
    assert (row.kind, row.barrier) == ("wall-path", False)
    assert row.max_height == pytest.approx(13.30)          # q 11.41 over -1.89
    assert row.offset == pytest.approx(25.0)


def test_a_strip_wall_and_an_outer_wall_may_share_stations():
    # 12 ft above, and a footprint at 50 ft: the path's 2:1 outer fill from
    # o (41, 11.17) would daylight 32.34 ft beyond it, past the footprint
    c = _path_corridor(111.51, section=dict(BASE["section"], side_slopes=dict(
        BASE["section"]["side_slopes"], footprint_ft={"L": 50.0})))
    found = W.find(c, [1400.0, 1450.0], _level(-5.0))
    assert sorted((g.auto, g.strip) for g in found) == [
        ("path-fill", False), ("strip-path", True)]
    c = c.with_walls(found)                                # no "too close" error
    assert c.wall("L", 1425.0).auto == "path-fill"
    assert c.wall("L", 1425.0, strip=True).auto == "strip-path"


def test_a_too_tall_strip_wall_is_a_structure_candidate_carrying_the_path():
    c = _path_corridor(87.51, max_wall_height_ft=10)
    c = c.with_walls(W.find(c, [1400.0, 1450.0], _level(-5.0)))
    rows = W.rows(c, [], _level(-5.0))
    (cand,) = W.structures(rows, [1400.0, 1450.0], lambda s: 95.0)
    assert (cand.side, cand.carries) == ("L", "path")
    assert W.STRUCTURE_HEADER.endswith(",carries")
    assert W.structures_csv([cand]).splitlines()[1].endswith(",path")
    assert W.WALL_HEADER.split(",")[:3] == ["side", "kind", "location"]
```

`_path_corridor(111.51, ...)`'s o: the paved outer edge at 11.51 - 0.24 = 11.27, o 0.10 lower, 11.17; to the ground at -5, 16.17 down at 2:1, 32.34 ft out, at 73.34 ft: past 50.

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_corridor_walls.py -q`
Expected: FAIL: `find` returns no strip wall (it never asks of the strip), and `WallRow` has no `location`.

- [ ] **Step 3: Implement** in `bimforge/author/corridor/walls.py`. Replace the headers and `WallRow`, `StructureRow`:

```python
#: outputs.walls: heights are exposed at the face, at finished grade, with
#: no barrier, footing or embedment (the module docstring); `location` is
#: "outer", or "strip" between the road and its path (V1.2 C)
WALL_HEADER = ("side,kind,location,start,end,offset_ft,min_height_ft,"
               "max_height_ft,barrier,too_tall")
STRUCTURE_HEADER = "side,start,end,max_fill_ft,low_point_station,carries"


@dataclass(frozen=True)
class WallRow:
    side: str
    kind: str              # "fill" or "cut"; in the strip "wall-road" or
                           # "wall-path" (V1.2 C)
    start: float
    end: float
    offset: float          # the wall's face, feet from the centreline
    min_height: float      # exposed at the face at finished grade, feet
                           # (no barrier, footing or embedment)
    max_height: float
    too_tall: bool         # a fill or strip wall over max_wall_height_ft
    location: str = "outer"        # or "strip"
    carries: str = "road"          # or "path"

    @property
    def barrier(self) -> bool:
        """A wall the road stands on carries a barrier on top: a road fill
        wall, a strip wall at the road's hinge."""
        return (self.kind == "fill" and self.carries == "road") or self.kind == "wall-road"


@dataclass(frozen=True)
class StructureRow:
    side: str              # "L", "R" or "both"
    start: float
    end: float
    max_fill: float        # the tallest wall it replaces, feet
    low_point: float       # the station where the ground is lowest
    carries: str = "road"  # what the structure would carry: "road" or "path"
```

Replace `find` (outer walls on each side, then strip walls on the path's side):

```python
def find(c, stations: list, ground_dz, rail=None) -> list:
    """Wall gaps (params.Gap, `auto` the wall's token) for one run's
    `stations` of corridor `c`, by start station. Each side is searched for
    outer walls and, on the path's side (V1.2 C), for strip walls apart, so
    a station may have one of each. `rail(s, side)`, when given, says
    whether a guardrail's widening stands on `side` at s (the family's
    second pass), so a slope it pushes past the footprint takes a wall
    too."""
    out = []
    for side in SIDES:
        for location in ("outer", "strip"):
            if location == "strip" and (c.path is None or c.path.side != side):
                continue

            def need(s, sd, location=location):
                return needs_wall(c, s, sd, ground_dz,
                                  rail is not None and rail(s, sd), location)

            kinds = [need(s, side) for s in stations]
            i = 0
            while i < len(stations):
                kind = kinds[i]
                if kind is None:
                    i += 1
                    continue
                j = i
                while j + 1 < len(stations) and kinds[j + 1] == kind:
                    j += 1
                start = _reach(side, need, kind, stations[i],
                               stations[i - 1] if i > 0 else None, -1.0)
                end = _reach(side, need, kind, stations[j],
                             stations[j + 1] if j + 1 < len(stations) else None, 1.0)
                out.append(Gap(start, end, "wall", side, None, auto=kind))
                i = j + 1
    return sorted(out, key=lambda g: (g.start, g.side))
```

(Without a path the inner loop runs once per side, as V1.1's did, and `sorted` is stable, so V1.1's wall order is unchanged.)

Replace `rows`:

```python
def _height(c, g, s: float, ground_dz) -> tuple:
    """(exposed height at the face, the face's offset) of wall gap `g` at
    station s: a road wall's at its shoulder edge (V1.1); a wall on the
    path's outer side at o; a strip wall from its top (the road's edge of
    shoulder, or q) down to the level strip at its foot."""
    if g.auto in ("fill", "cut"):
        u, v = grade_edge(c, s, g.side)
        dz = ground_dz(s, u, v)
        return (-dz if g.auto == "fill" else dz), abs(u)
    from bimforge.author.corridor.path import surface
    sf = surface(c, s)
    if g.auto == "strip-road":
        return (sf.edge[1] - sf.q[1]) * sf.cg, abs(sf.edge[0])
    if g.auto == "strip-path":
        hinge_v = sf.edge[1] - c.depth()
        return (sf.q[1] - hinge_v) * sf.cg, abs(sf.q[0])
    dz = ground_dz(s, *sf.o)
    return (-dz if g.auto == "path-fill" else dz), abs(sf.o[0])


#: a wall's token -> its walls-table kind
_KIND = {"fill": "fill", "cut": "cut", "path-fill": "fill", "path-cut": "cut",
         "strip-road": "wall-road", "strip-path": "wall-path"}


def rows(c, secs: list, ground_dz) -> list:
    """One WallRow per automatic wall of `c`, by start station. Its exposed
    height at the face, at finished grade (no barrier, footing or
    embedment), and its offset are read at the stations of the sections
    `secs` (section.Section) on it and at least every HEIGHT_STEP_FT
    between its ends, so a peak in the ground between sections is not
    missed. A fill wall or a strip wall over max_wall_height_ft is too
    tall."""
    out = []
    for g in c.gaps:
        if g.auto is None:
            continue
        n = max(1, math.ceil((g.end - g.start) / HEIGHT_STEP_FT - _EPS))
        at = {g.start + (g.end - g.start) * i / n for i in range(n + 1)}
        at.update(sec.s for sec in secs if g.start - _EPS <= sec.s <= g.end + _EPS)
        heights, offsets = zip(*(_height(c, g, s, ground_dz) for s in sorted(at)))
        top, kind = max(heights), _KIND[g.auto]
        out.append(WallRow(g.side, kind, g.start, g.end, max(offsets),
                           min(heights), top,
                           kind != "cut" and top > c.max_wall_height + _EPS,
                           location="strip" if g.strip else "outer",
                           carries=g.carries))
    return sorted(out, key=lambda r: (r.start, r.side))
```

Replace `structures`, `walls_csv` and `structures_csv`:

```python
def structures(rows: list, stations: list, ground_elev) -> list:
    """The structure candidates: each too-tall wall's stretch, walls on the
    two sides that overlap and carry the same thing merged into one
    ("both"), with the tallest wall and the station of `stations` where
    `ground_elev(s)` (the ground at the centreline) is lowest."""
    groups = []
    for r in sorted((r for r in rows if r.too_tall), key=lambda r: (r.carries, r.start)):
        g = groups[-1] if groups else None
        if g is not None and g[4] == r.carries and r.start <= g[1] + _EPS:
            groups[-1] = (g[0], max(g[1], r.end), max(g[2], r.max_height),
                          g[3] | {r.side}, g[4])
        else:
            groups.append((r.start, r.end, r.max_height, {r.side}, r.carries))
    out = []
    for a, b, top, sides, carries in sorted(groups, key=lambda g: (g[0], g[4])):
        inside = [s for s in stations if a - _EPS <= s <= b + _EPS] or [a, b]
        out.append(StructureRow("both" if len(sides) > 1 else next(iter(sides)),
                                a, b, top, min(inside, key=ground_elev), carries))
    return out


def walls_csv(rows: list) -> str:
    return "\n".join([WALL_HEADER] + [
        f"{r.side},{r.kind},{r.location},{r.start:.2f},{r.end:.2f},{r.offset:.2f},"
        f"{r.min_height:.2f},{r.max_height:.2f},"
        f"{'yes' if r.barrier else 'no'},{'yes' if r.too_tall else 'no'}"
        for r in rows]) + "\n"


def structures_csv(rows: list) -> str:
    return "\n".join([STRUCTURE_HEADER] + [
        f"{r.side},{r.start:.2f},{r.end:.2f},{r.max_fill:.2f},{r.low_point:.2f},"
        f"{r.carries}"
        for r in rows]) + "\n"
```

- [ ] **Step 4: `with_walls` compares walls of one location** (in `bimforge/author/corridor/params.py`). In `with_walls`, change the neighbours' loop to:

```python
        autos = sorted(walls, key=lambda g: (g.side, g.strip, g.start))
        for p, q in zip(autos, autos[1:]):
            if (p.side == q.side and p.strip == q.strip
                    and q.start - p.end < 2 * WALL_TRANSITION_FT - _EPS):
```

(the rest of the loop body unchanged), and in `_merged` sort by `(g.side, g.strip, g.auto, g.start)`.

- [ ] **Step 5: The road's rail ties into the road's walls only** (in `bimforge/author/families/road_corridor.py`). Add:

```python
def road_walls(c, side: str) -> list:
    """The wall gaps on `side` that bound the road's guardrail: listed walls,
    V1.1's automatic road walls, and a strip wall at the road's hinge
    (V1.2 C). A wall on the path's outer side, or one at the path's
    shoulder, is not the road's."""
    return [g for g in c.gaps if g.kind == "wall" and g.side == side
            and g.auto in (None, "fill", "cut", "strip-road")]
```

In `lay_rails` replace the `walls = [...]` comprehension with:

```python
        walls = [(g.start - WALL_TRANSITION_FT, g.end + WALL_TRANSITION_FT)
                 if g.auto == "cut" else (g.start, g.end)
                 for g in road_walls(c, side)]
```

In `under_rail`'s `in_lead_in`, iterate `road_walls(c, side)` in place of `c.gaps` filtered by side:

```python
    def in_lead_in(side):
        return any(g.start - lead <= s < g.start - 1e-6
                   or g.end + 1e-6 < s <= g.end + lead
                   for g in road_walls(c, side))
```

and in `rail_stations` loop `for side in SIDES: for g in road_walls(c, side):` in place of `for g in c.gaps: if g.kind != "wall": continue`, importing `SIDES` from params.

- [ ] **Step 6: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_corridor_walls.py bimforge/author/tests/test_road_corridor.py bimforge/author/tests/test_road_corridor_v11.py -q`
Expected: PASS (V1.1's tables differ only by the two new columns, which the pin drops).

- [ ] **Step 7: Commit**

```bash
git add bimforge/author/corridor/walls.py bimforge/author/corridor/params.py bimforge/author/families/road_corridor.py bimforge/author/tests/test_corridor_walls.py
git commit -F - <<'EOF'
road corridor: walls in the strip and on the path's outer side (P.6, part C)

Outer and strip walls are found apart, so one station may have both. The
walls table says where each stands (location), the structures table what
a candidate would carry (carries); the road's rail ties into the road's
walls only.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

### Task 7: The earthwork is the section's, counted once

**Files:**
- Test: `bimforge/author/tests/test_corridor_path.py`

No new code: Task 5's line is the earthwork line. These tests hold it to hand-computed polygon areas: on a level tangent with level ground, two identical sections 100 ft apart make a prism, so the fill is the section's area between its earthwork line and the ground, times 100.

Level ground at 95.0 (v = -5), the path level with the road, sep 10, both sides fill. Trapezoids along the earthwork line, depth below it to v = -5:
- the right side, V1.1's: its 2:1 slope (-23.22, -5) to (-17, -1.89): 9.6721; the shoulder's subgrade to (-12, -1.64): 16.175; the lane's to (0, -1.4): 41.76;
- the left lane and shoulder: 41.76 + 16.175 = 57.935;
- the strip, H (17, -1.89) to q (25, -0.59): (3.11 + 4.41) / 2 × 8 = 30.08;
- the path's top: q to (26.99, -0.4905): 8.8749025; down to (27, -1.24): 0.0413475; under the courses to (39, -1.48): 43.68; up to (39.01, -0.7305): 0.0389475; across the outer shoulder to o (41, -0.83): 8.3973025;
- its outer 2:1 slope to (49.34, -5): 17.3889.

Total 234.0435 sf; the fill 23 404.35 cf over 100 ft.

Natural ground: the ground at 97.0 (v = -3), sep 60 (from 11+00): the road alone (no path) is 50.3342 sf (its right side 2:1 from -1.89 to -3, the lanes and shoulders, its left 2:1 to (19.22, -3)); the path's own part: its inner slope (70.18, -3) to q (75, -0.59): 5.8081; the top: 4.8949025 + 0.0213475 + 19.68 + 0.0189475 + 4.4173025; its outer slope to (95.34, -3): 4.7089; 39.5495 in all, with nothing between them.

- [ ] **Step 1: Write the tests** (append to `test_corridor_path.py`)

```python
from bimforge.author.corridor import earthwork
from bimforge.author.corridor.frame import survey_point
from bimforge.author.corridor.ground import PlaneGround


def fill_area(c, ground, s=1500.0):
    """The section's fill area at s: trapezoids along its earthwork line,
    down to the ground (earthwork tests' signed_area, negated)."""
    def dz(st, u, v):
        n, e, z = survey_point(AL, PROF, st, u, v)
        return ground.z(n, e) - z
    sec = resolve(c, s, dz)
    d = [(u, dz(s, u, v)) for u, v in sec.earthwork_line()]
    return -sum(0.5 * (d0 + d1) * abs(u1 - u0) for (u0, d0), (u1, d1) in zip(d, d[1:]))


def prism_fill(c, ground, s0=1400.0, s1=1500.0):
    """The fill earthwork.strip builds between two sections."""
    def survey(st, u, v):
        return survey_point(AL, PROF, st, u, v)

    def dz(st, u, v):
        n, e, z = survey(st, u, v)
        return ground.z(n, e) - z
    _cut, fill, _cd, _fd = earthwork.strip("t", resolve(c, s0, dz), resolve(c, s1, dz),
                                           survey, ground.z, None)
    return sum(p.volume_cf for p in fill)


def test_the_section_s_fill_is_its_hand_polygon():
    c = corridor()
    ground = PlaneGround(95.0)
    assert fill_area(c, ground) == pytest.approx(234.0435, abs=1e-6)
    assert prism_fill(c, ground) == pytest.approx(23404.35, rel=1e-9)


def test_with_natural_ground_between_it_is_the_road_s_plus_the_path_s():
    ground = PlaneGround(97.0)
    with_path = corridor(path(separation=[[1000, 10.0], [1100, 60.0]]))
    road = parse(copy.deepcopy(BASE), 1000.0, 2000.0)
    assert fill_area(road, ground) == pytest.approx(50.3342, abs=1e-6)
    assert fill_area(with_path, ground) == pytest.approx(50.3342 + 39.5495, abs=1e-6)
```

- [ ] **Step 2: Run them**

Run: `python -m pytest bimforge/author/tests/test_corridor_path.py -q -k "hand_polygon or natural_ground_between_it"`
Expected: PASS (Task 5's line). If one misses, print `resolve(...).earthwork_line()` and compare it point by point with the list above before touching the code: a miss here is a point in the wrong place, not a tolerance.

- [ ] **Step 3: Commit**

```bash
git add bimforge/author/tests/test_corridor_path.py
git commit -F - <<'EOF'
road corridor: the path's earthwork is the section's hand polygon (P.6, part C)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

### Task 8: A course's centroid line on its own grade

**Files:**
- Modify: `bimforge/author/corridor/loft.py`
- Test: `bimforge/author/tests/test_corridor_loft.py`, `bimforge/author/tests/test_corridor_path.py`

`loft.pappus` holds the centroid's line parallel to the profile grade line, which a path course is not: it rises and falls on its own profile and drifts as the separation changes. `centroid_path` keeps pappus's exact volume and measures the centroid's line through the blended rings' own centroid at each Gauss node, its speed the central difference of its survey points.

The volume is ∫ A J ds (J the speed of the section plane along its normal at the centroid, pappus), the path ∫ J / cos θc ds (θc between the plane's normal and the centroid's tangent). With each course `t / cos θ` deep, A = W t / cos θ, so `Volume = PathLength × W × t` wherever the ring's θ is the centroid's: on tangents and constant curves exactly, and to the bays' blending elsewhere (Task 9 logs where it is not).

Hand values: a 12 × 0.5 ft ring on a level tangent, rising 2 ft per 100 (its v from 0 to 2): its centroid's line is 100 √(1 + 0.02²) = 100.019998 ft; drifting 8.5 ft per 100 sideways instead: 100 √(1 + 0.085²) = 100.360600 ft. The path on a 3 % road at 5 %: `1 / cos θ - 1 = 1.9938e-4`, so the formula would miss by about 2e-4 without the correction (the spec's figure).

- [ ] **Step 1: Write the failing tests.** Append to `bimforge/author/tests/test_corridor_loft.py`:

```python
from bimforge.author.corridor.loft import centroid_path


def _box(u0, v0, w=12.0, t=0.5):
    return [(u0 + w, v0), (u0, v0), (u0, v0 - t), (u0 + w, v0 - t)]


def test_a_rising_ring_s_centroid_climbs_on_its_own_grade():
    lf = StationLoft("r", line(), level(), None, [0.0, 50.0, 100.0],
                     [_box(20.0, 0.0), _box(20.0, 1.0), _box(20.0, 2.0)])
    got = centroid_path([lf])
    assert got.path_ft == pytest.approx(100.0 * math.sqrt(1.0004), rel=1e-9)
    assert got.volume_cf == pytest.approx(pappus([lf]).volume_cf, rel=1e-12)
    assert got.offset_ft == pytest.approx(26.0)


def test_a_drifting_ring_s_centroid_runs_long():
    lf = StationLoft("d", line(), level(), None, [0.0, 100.0],
                     [_box(20.0, 0.0), _box(28.5, 0.0)])
    assert centroid_path([lf]).path_ft == pytest.approx(
        100.0 * math.sqrt(1.0 + 0.085 ** 2), rel=1e-9)
```

Append to `bimforge/author/tests/test_corridor_path.py`:

```python
from bimforge.author.corridor.loft import StationLoft, centroid_path
from bimforge.author.gate import FORMULA_TOLERANCE


def _course_box(c, k, stations):
    """(exact volume, PathLength x Width x Thickness) of path course k as
    the family lofts it over `stations`."""
    al, prof = c.path.alignment, c.path.road_profile
    rings = [course_rings(c.path, surface(c, s))[k] for s in stations]
    got = centroid_path([StationLoft("t", al, prof, None, stations, rings)])
    return got.volume_cf, got.path_ft * c.path.width * c.path.courses[k].thickness


def test_a_path_2_percent_off_the_road_s_grade_is_its_path_box():
    road = Profile(grade(100.0, pct=3.0)["curves"])
    c = corridor(path(profile=grade(99.51, pct=5.0)), prof=road)
    for k in (0, 1):
        vol, box = _course_box(c, k, [1400.0 + 25.0 * i for i in range(5)])
        assert abs(box - vol) <= FORMULA_TOLERANCE * vol
    want = (1 + 0.03 * 0.05) / math.sqrt(1.0009 * 1.0025)
    # without the correction the box misses by 1 / cos(theta) - 1
    assert 1.0 / want - 1.0 == pytest.approx(1.9938e-4, rel=1e-3)


def test_a_path_on_a_graded_curve_is_its_path_box():
    # a 500 ft right curve at 7 %, the path on the right 10 ft out and
    # parallel: its centre about 33 ft out, where V1.1's road courses miss
    # by (kappa g r)^2 / 2 = 1.1e-5; theta takes the twist in as well
    al = Alignment({"station": 1000.0, "northing": 0.0, "easting": 0.0},
                   [{"kind": "tangent", "bearing": "N 0-0-0 E", "length": 100.0},
                    {"kind": "curve", "delta": "11-27-33", "radius": 500.0,
                     "turn": "R", "length": 100.0},
                    {"kind": "tangent", "bearing": "N 11-27-33 E", "length": 800.0}],
                   name="C")
    road = Profile(grade(100.0, pct=7.0)["curves"])
    params = copy.deepcopy(BASE)
    params["path"] = path(side="R", profile=grade(99.48, pct=7.0))
    c = parse(params, 1000.0, 2000.0, alignment=al, profile=road)
    vol, box = _course_box(c, 1, [1110.0 + 5.0 * i for i in range(17)])
    assert abs(box - vol) <= FORMULA_TOLERANCE * vol
```

(`grade(99.48, 7.0)`: the right edge of shoulder is 0.49 down the plane, 0.49 × cos 7 % = 0.4888 ft below the grade line; 99.48 puts the path's edge 0.03 ft under it, a strip slope.)

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_corridor_loft.py bimforge/author/tests/test_corridor_path.py -q`
Expected: collection ERROR, `ImportError: cannot import name 'centroid_path'`.

- [ ] **Step 3: Implement** (append to `bimforge/author/corridor/loft.py`)

```python
def centroid_path(lofts: list) -> Pappus:
    """pappus, the centroid's line following the blended rings' own
    centroid at each station rather than held parallel to the profile
    grade line: a path course rises and falls on its own profile and
    drifts with its separation (V1.2 C). The volume is pappus's exact one;
    the path is 5-point Gauss-Legendre per bay of the centroid's speed, the
    central difference of its survey points over a thousandth of the bay;
    offset and height are the centroid's area-weighted means."""
    from bimforge.author.corridor.frame import survey_point
    first = lofts[0]
    al, prof, ss = first.alignment, first.profile, first.stations
    if any(lf.stations != ss for lf in lofts[1:]):
        raise ValueError(f"{first.name}: centroid_path needs lofts on the same "
                         f"stations")
    volume = pappus(lofts).volume_cf
    path = weight = usum = vsum = 0.0
    for i, (a, b) in enumerate(zip(ss, ss[1:])):
        h = b - a
        pairs = [(lf.rings[i], lf.rings[i + 1]) for lf in lofts]

        def centroid(t):
            area = qu = qv = 0.0
            for ra, rb in pairs:
                da, du, dv = _moments([(ua + t * (ub - ua), va + t * (vb - va))
                                       for (ua, va), (ub, vb) in zip(ra, rb)])
                area, qu, qv = area + da, qu + du, qv + dv
            return area, qu / area, qv / area

        dt = 1e-3
        for x, w in _GAUSS:
            t = 0.5 * (1.0 + x)
            area, u, v = centroid(t)
            p0 = survey_point(al, prof, a + h * (t - dt), *centroid(t - dt)[1:])
            p1 = survey_point(al, prof, a + h * (t + dt), *centroid(t + dt)[1:])
            speed = math.dist(p0, p1) / (2.0 * dt * h)
            dw = 0.5 * h * w
            path += dw * speed
            weight += dw * area
            usum += dw * area * u
            vsum += dw * area * v
    return Pappus(volume, path, usum / weight, vsum / weight)
```

(The outer nodes sit 0.047 of a bay inside it, so `t ± 0.001` stays inside.)

- [ ] **Step 4: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_corridor_loft.py bimforge/author/tests/test_corridor_path.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bimforge/author/corridor/loft.py bimforge/author/tests/test_corridor_loft.py bimforge/author/tests/test_corridor_path.py
git commit -F - <<'EOF'
road corridor: a course's centroid line on its own grade (P.6, part C)

Each path course is thickness / cos(theta) deep in the road's section
plane, so its exact volume is PathLength x Width x Thickness, PathLength
its centroid's 3D length as it climbs and drifts on its own.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

### Task 9: The family builds the path's courses

**Files:**
- Modify: `bimforge/author/families/road_corridor.py`
- Test: `bimforge/author/tests/test_road_corridor_path.py` (create)

The family parses with the road's alignment and profile, reaches far enough for the path when it fetches ground, and adds the path's courses band by band after the road's: one element per path course per band (one body, on the path's side), over the band's sections that carry the path. Each declares its exact volume (`loft.pappus` through `centroid_path`), `PathLength` and `Offset` from `centroid_path`, `Width` the paved width, and `Volume = PathLength * Width * Thickness` where it holds; where it does not, the build log says so (`road-corridor: <name>: Volume formula withheld: ...`). The earthwork needs no change: the section's earthwork line already holds the path's side.

The test corridor: a 600 ft tangent at 1 %, a bridge gap from 13+00 to 13+50, the path on the right 10 ft out narrowing to the deck's 1.5 ft over each 100 ft approach, on a profile 0.51998 ft under the road's grade line: the right edge of shoulder is 0.49 ft down the plane (0.49 × cos 1 % = 0.48998 ft below the grade line) and the lane's -2 % over 1.5 ft drops 0.03 more, so the path meets the deck at both ends. The ground falls 2 % to the right from 296.

A constant band, 10+00 to 11+00: the path parallel to the road on a tangent, so cos θ = 1 and `PATH-HMA`'s volume is 12 × 0.25 × 100 √(1 + 0.01²) = 300.015000 cf. The band 12+00 to 13+00 has the narrowing's kinks at both ends (the section at 12+00 serves a band holding the path and one drifting it): its formula is withheld and logged.

- [ ] **Step 1: Write the failing tests** `bimforge/author/tests/test_road_corridor_path.py`

```python
"""road-corridor V1.2 part C: the family builds a shared-use path beside
the road (P.6)."""
import contextlib
import copy
import io
import uuid

import pytest

from bimforge.author.project import ProjectContext

N0, E0 = 1943000.0, 6594000.0
SECTION = {
    "components": [{"name": "lane", "kind": "carriageway", "width": 12.0},
                   {"name": "shoulder", "kind": "shoulder", "width": 5.0,
                    "slope": -0.05}],
    "courses": [{"name": "HMA", "type": "PAVEMENT", "thickness": 0.4},
                {"name": "AB", "type": "CORE", "thickness": 1.0}],
    "side_slopes": {"cut": {"ratio": 2.0, "ditch": {"width": 4.0, "depth": 1.5}},
                    "fill": {"ratio": 2.0}, "daylight_limit_ft": 150}}


def grade(elev, pct, s0=1000.0, s1=1600.0):
    return {"curves": [{"bvc_station": s0, "bvc_elev": elev, "g_in_pct": pct,
                        "g_out_pct": pct, "length_ft": s1 - s0, "evc_station": s1,
                        "evc_elev": round(elev + pct / 100.0 * (s1 - s0), 5)}]}


PATH = {"side": "R",
        "separation": [[1000, 10.0], [1200, 10.0], [1300, 1.5], [1350, 1.5],
                       [1450, 10.0]],
        "width": 12.0,
        "courses": [{"name": "PATH-HMA", "type": "PAVEMENT", "thickness": 0.25},
                    {"name": "PATH-AB", "type": "CORE", "thickness": 0.5}],
        # on the deck's line at 13+00 and 13+50 (the module docstring)
        "profile": grade(299.48002, 1.0)}
PARAMS = {
    "alignment": {"name": "ML", "pob": {"station": 1000.0, "northing": N0,
                                        "easting": E0},
                  "run": [{"kind": "tangent", "bearing": "N 0-0-0 E",
                           "length": 600.0}]},
    "profile": grade(300.0, 1.0),
    "ground": {"source": "plane", "elevation": 296.0, "slope_e": -0.02},
    "section": SECTION,
    "gaps": [{"from": 1300, "to": 1350, "kind": "structure"}],
    "stations": {"interval": 25, "band": 100},
    "mass_haul": {"shrink": 0.1, "swell": 0.2},
    "path": PATH,
}
CTX = ProjectContext(name="rcp", epsg=2226, base_e=E0, base_n=N0, base_h=300.0,
                     guid_ns=uuid.UUID(int=11))


def build(params, log=None):
    from bimforge.author.families.road_corridor import build as _build
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        m = _build(copy.deepcopy(params), CTX)
    if log is not None:
        log.append(err.getvalue())
    return m


@pytest.fixture(scope="module")
def built():
    log = []
    return build(PARAMS, log), log[0]


def path_courses(m):
    return [e for e in m.elements if e.ifc_class == "IfcCourse" and " path STA " in e.name]


def test_one_path_course_per_course_and_band(built):
    m, _log = built
    names = sorted(e.name for e in path_courses(m))
    bands = ["10+00.00 to 11+00.00", "11+00.00 to 12+00.00", "12+00.00 to 13+00.00",
             "13+50.00 to 14+00.00", "14+00.00 to 15+00.00", "15+00.00 to 16+00.00"]
    assert names == sorted(f"{c} path STA {b}" for c in ("PATH-HMA", "PATH-AB")
                           for b in bands)
    for el in path_courses(m):
        assert el.spatial_part.predefined_type == "SHAREDUSEPATH"
        assert el.spatial_part.parent.predefined_type == "ROADSEGMENT"
        (lf,) = el.geometry
        assert lf.s1 <= 1300.0 + 1e-6 or lf.s0 >= 1350.0 - 1e-6, el.name


def test_a_constant_band_is_its_path_box(built):
    m, _log = built
    el = m.element("PATH-HMA path STA 10+00.00 to 11+00.00")
    assert el.quantities["volume_cf"] == pytest.approx(
        12.0 * 0.25 * 100.0 * (1.0 + 0.01 ** 2) ** 0.5, rel=1e-9)
    vol = el.standard_qto["Qto_CourseBaseQuantities"]["Volume"]
    assert vol[2] == "PathLength * Width * Thickness"
    assert el.dimensions["Width"] == pytest.approx(12.0)
    # the centre of the paved width: 17 + 10 + 6 ft right
    assert el.dimensions["Offset"] == pytest.approx(-33.0, abs=0.01)


def test_a_band_with_a_separation_kink_withholds_its_formula_and_says_so(built):
    m, log = built
    el = m.element("PATH-AB path STA 12+00.00 to 13+00.00")
    assert len(el.standard_qto["Qto_CourseBaseQuantities"]["Volume"]) == 2
    assert ("road-corridor: PATH-AB path STA 12+00.00 to 13+00.00: Volume formula "
            "withheld") in log


def test_every_course_meets_its_stated_volume_and_the_earthwork_is_closed(built):
    from bimforge.author.gate import check_stated_quantities
    m, _log = built
    assert check_stated_quantities(m) == []
    from collections import Counter
    for el in m.elements:
        if not el.ifc_class.startswith("IfcEarthworks"):
            continue
        for g in el.geometry:
            (d,) = g.body_solids()
            directed = Counter((a, b) for t in d["tris"] for a, b in zip(t, t[1:] + t[:1]))
            assert all(n == 1 and directed[b, a] == 1
                       for (a, b), n in directed.items()), el.name


def test_the_ground_reaches_past_the_path():
    from bimforge.author.alignment import Alignment, Profile
    from bimforge.author.corridor.params import parse
    from bimforge.author.families.road_corridor import ground_reach
    al_p = PARAMS["alignment"]
    al = Alignment(al_p["pob"], al_p["run"])
    prof = Profile(PARAMS["profile"]["curves"])
    c = parse(copy.deepcopy(PARAMS), al.s_start, al.s_end, alignment=al, profile=prof)
    # 17 ft to the edge, 10 ft out, 12 paved, two 2 ft shoulders, then the
    # 150 ft daylight limit
    assert ground_reach(c) == pytest.approx(17.0 + 10.0 + 12.0 + 4.0 + 150.0)
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_road_corridor_path.py -q`
Expected: FAIL: `ValueError: path: needs the road's alignment and profile` from `build`.

- [ ] **Step 3: Implement** in `bimforge/author/families/road_corridor.py`.

Add these module-level helpers (after `_parts`):

```python
def path_part(segment: dict, r: int) -> dict:
    """Run r's shared-use path (V1.2 C): an IfcRoadPart beside its
    CARRIAGEWAY and SHOULDER, USERDEFINED SHAREDUSEPATH (IfcRoadPartTypeEnum
    has no path value; SIDEWALK is for pedestrians)."""
    return {"name": f"Segment {r} shared-use path",
            "predefined_type": "SHAREDUSEPATH", "usage_type": "LATERAL",
            "parent": segment}


def path_runs(secs: list) -> list:
    """[(i0, i1)]: the index ranges of `secs` (one band's sections) the path
    is built over: consecutive sections that carry it, two at least."""
    out, start = [], None
    for i, sec in enumerate(list(secs) + [None]):
        has = sec is not None and sec.path is not None
        if has and start is None:
            start = i
        elif not has and start is not None:
            if i - 1 > start:
                out.append((start, i - 1))
            start = None
    return out


def add_path_courses(model, c, al, prof, ctx, ss: list, bs: list, part: dict,
                     log) -> None:
    """The path's courses over one stretch of a band: stations `ss`, their
    sections `bs`, each course one body under the paved width. Its exact
    volume and its centroid's line are loft.centroid_path's; the Volume
    formula is written where it holds and logged where it does not."""
    from bimforge.author.alignment import sta
    from bimforge.author.corridor import dimensions as dims
    from bimforge.author.corridor.loft import StationLoft, centroid_path
    from bimforge.author.gate import FORMULA_TOLERANCE
    from bimforge.author.model import Element
    b0, b1 = ss[0], ss[-1]
    for k, course in enumerate(c.path.courses):
        name = f"{course.name} path STA {sta(b0)} to {sta(b1)}"
        lofts = [StationLoft(name, al, prof, ctx, ss, [sec.path.courses[k] for sec in bs],
                             ifc="IfcCourse", layer=LAYER)]
        centroid = centroid_path(lofts)
        vol = centroid.volume_cf
        aea = lofts[0].average_end_area_cf
        shape, volume = dims.course_volume(vol, centroid.path_ft,
                                           lofts[0].widths_ft, course.thickness)
        if len(volume) == 2:
            log(f"road-corridor: {name}: Volume formula withheld: PathLength * "
                f"Width * Thickness is not its exact volume within "
                f"{FORMULA_TOLERANCE:g}")
        model.add(Element(
            name, ifc_class="IfcCourse", geometry=lofts,
            predefined_type=course.type, type_name=course.name,
            material=course.name, layer=LAYER, body="solids",
            spatial_part=part, family_class=dims.COURSE,
            dimensions={"Thickness": course.thickness, **shape,
                        "Offset": centroid.offset_ft,
                        "PathLength": centroid.path_ft, **dims.stations(b0, b1)},
            quantities={"length_ft": b1 - b0, "volume_cf": vol},
            standard_qto={"Qto_CourseBaseQuantities": {
                "Length": ("length", b1 - b0, dims.LENGTH),
                "Width": ("length", lofts[0].mean_width_ft),
                "Thickness": ("length", course.thickness),
                "Volume": volume}}))
        model.stated_quantities.append(
            (f"{name}: exact volume vs average end area", vol, aea,
             AEA_TOL * max(aea, 1.0)))
```

In `ground_reach`, replace its `return` with:

```python
    out = max([half + c.slopes.daylight_limit] + walls)
    if c.path is not None:
        p = c.path
        # the road's widest side, the path's farthest separation, its paved
        # width and both shoulders, then the daylight limit
        far = max(v for _s, v in p.separation) + p.width + 2.0 * p.shoulder_width
        out = max(out, half + far + c.slopes.daylight_limit)
    return out
```

In `build`, parse with the road's alignment and profile:

```python
    c = parse(params, al.s_start, al.s_end, alignment=al, profile=prof)
```

and in the band loop, after the road's courses (`for k, course in enumerate(c.courses): ...`) and before `cut, fill, cut_d, fill_d = [], [], 0.0, 0.0`:

```python
            if c.path is not None:
                for p0, p1 in path_runs(bs):
                    add_path_courses(model, c, al, prof, ctx, ss[p0:p1 + 1],
                                     bs[p0:p1 + 1], path_part(segment, r), log)
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_road_corridor_path.py bimforge/author/tests/test_road_corridor.py bimforge/author/tests/test_road_corridor_v11.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bimforge/author/families/road_corridor.py bimforge/author/tests/test_road_corridor_path.py
git commit -F - <<'EOF'
road-corridor: build the path's courses beside the road (P.6, part C)

One element per path course and band, under a USERDEFINED SHAREDUSEPATH
road part; Volume = PathLength * Width * Thickness where it holds, the
build log naming each band where it does not.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

### Task 10: The path's road part, its rail, and their dictionary classes

**Files:**
- Modify: `bimforge/author/spatial.py`, `bimforge/author/emit_ifc.py`
- Modify: `bimforge/author/corridor/dimensions.py`
- Modify: `bimforge/author/dictionary/bimforge-families.bsdd.json`
- Modify: `bimforge/author/families/road_corridor.py`
- Test: `bimforge/author/tests/test_road_corridor_path.py`

The spec gives the path's `IfcRoadPart` a dictionary class, `road-corridor-shared-use-path`. Spatial parts carry none today, so `SpatialPart` gains `family_class`, which `emit_ifc` adds to the classification references it already writes after the GlobalId sweep (nothing renumbers). A wall that holds the path up (`strip-path` at q, `path-fill` at o) carries the path's rail, an `IfcRailing` GUARDRAIL (IFC: a railing that keeps people from falling) typed "Path rail" (`road-corridor-path-rail`), its body a 3 in band from the wall's top to `rail_height_ft`, lofted at the road's stations as the courses are (`StationLoft`, an `IfcSectionedSolidHorizontal` along the road's `IfcGradientCurve`), with `BIMForge_Guardrail` (its height and stations) and `Length = EndStation - StartStation`.

The rail test corridor is Task 9's, with no bridge and `walls: auto`, the path rising 7.5 ft above the road from 12+00 to 13+00 and back: six curves on the path's profile, each 100 ft (1 % to 9 %, 9 % to 1 %, 1 %, 1 % to -7 %, -7 % to 1 %, 1 %), each rise `g1 L + (g2 - g1) L / 2`: +5, +5, +1, -3, -3, +1 from 299.48002. Its strip wall stands where q is more than 4 ft above the hinge (8 ft across at 2:1): where the path is 2.21 ft or more above the road's grade line (q 0.10 ft under the path's edge, the hinge 1.89 ft under the grade line), 0.0004 x^2 - 0.52 > 2.21 into the first curve, x > 82.6: from about 10+83 to 14+17.

- [ ] **Step 1: Write the failing tests** (append to `test_road_corridor_path.py`)

```python
def curves(elev, rows):
    """A profile of 100 ft curves from 10+00, one per (g_in, g_out) row."""
    out, s, z = [], 1000.0, elev
    for g1, g2 in rows:
        z1 = z + g1 / 100.0 * 100.0 + (g2 - g1) / 100.0 * 100.0 / 2.0
        out.append({"bvc_station": s, "bvc_elev": round(z, 5), "g_in_pct": g1,
                    "g_out_pct": g2, "length_ft": 100.0, "evc_station": s + 100.0,
                    "evc_elev": round(z1, 5)})
        s, z = s + 100.0, z1
    return {"curves": out}


#: 7.5 ft above the road from 12+00 to 13+00 (309.48 against 302.0)
UP = curves(299.48002, [(1, 9), (9, 1), (1, 1), (1, -7), (-7, 1), (1, 1)])
#: 8.5 ft below it (293.48 against 302.0)
DIP = curves(299.48002, [(1, -7), (-7, 1), (1, 1), (1, 9), (9, 1), (1, 1)])


def wall_params(profile, **over):
    p = copy.deepcopy(PARAMS)
    p.update(walls="auto", gaps=[], **over)
    p["path"] = dict(copy.deepcopy(PATH), separation=[[1000, 10.0]], profile=profile)
    return p


def test_a_path_above_the_road_takes_a_strip_wall_and_its_rail():
    from bimforge.author.corridor import dimensions as dims
    m = build(wall_params(UP))
    (rail,) = [e for e in m.elements if e.ifc_class == "IfcRailing"
               and e.name.startswith("Path rail ")]
    assert rail.name.startswith("Path rail R STA 10+8")
    assert (rail.predefined_type, rail.type_name, rail.family_class) == (
        "GUARDRAIL", "Path rail", dims.PATH_RAIL)
    assert rail.dimensions["RailHeight"] == pytest.approx(3.5)
    length = rail.dimensions["EndStation"] - rail.dimensions["StartStation"]
    assert rail.standard_qto["Qto_RailingBaseQuantities"]["Length"] == (
        "length", pytest.approx(length), dims.LENGTH)
    assert rail.psets["BIMForge_Guardrail"]["RailHeight"] == ("length", pytest.approx(3.5))
    assert rail.spatial_part.predefined_type == "SHAREDUSEPATH"
    assert 320.0 < length < 345.0                      # about 10+83 to 14+17


def test_the_path_s_road_part_and_rail_pass_the_schema(tmp_path):
    import ifcopenshell
    import yaml

    from bimforge.author.families.registry import build_from_spec
    from bimforge.author.gate import schema_issues
    paycodes = ("rules:\n  - {match: \"(?i)^(HMA|AB) \", group: rc_pave}\n"
                "groups:\n  rc_pave: {measure: GrossVolume}\n"
                "codes:\n  RC-PAVE: {group: rc_pave, measure: GrossVolume, unit: CY,\n"
                "            item_number: \"0001\", description: \"Pavement\"}\n")
    (tmp_path / "rc.paycodes.yaml").write_text(paycodes, "utf-8")
    spec = {"family": "road-corridor", "params": wall_params(UP),
            "paycodes": "./rc.paycodes.yaml", "outputs": {"ifc": "out/rc.ifc"},
            "project": {"name": "Path fixture", "epsg": 2226,
                        "base": [E0, N0, 300.0], "guid_ns": str(uuid.UUID(int=11)),
                        "schema": "IFC4X3_ADD2", "facility": {"kind": "road"}}}
    path = tmp_path / "rc.spec.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False), "utf-8")
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        assert build_from_spec(str(path)) == 0, err.getvalue()[-2000:]
    f = ifcopenshell.open(str(tmp_path / "out" / "rc.ifc"))
    assert not schema_issues(f)
    parts = [p for p in f.by_type("IfcRoadPart") if p.ObjectType == "SHAREDUSEPATH"]
    assert parts and all(p.PredefinedType == "USERDEFINED" for p in parts)
    for part in parts:
        refs = [r.RelatingClassification for r in part.HasAssociations
                if r.is_a("IfcRelAssociatesClassification")]
        assert [r.Identification for r in refs] == ["road-corridor-shared-use-path"]
    (rail,) = [r for r in f.by_type("IfcRailing") if r.Name.startswith("Path rail ")]
    import ifcopenshell.util.element as E
    assert E.get_type(rail).Name == "Path rail"
    assert E.get_predefined_type(rail) == "GUARDRAIL"
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_road_corridor_path.py -q -k "rail or road_part"`
Expected: FAIL: no `Path rail` element; `dims` has no `PATH_RAIL`.

- [ ] **Step 3: A spatial part's class.** In `bimforge/author/spatial.py`, add a field to `SpatialPart` (after `parent`):

```python
    #: the family-dictionary class the part references (M.1), e.g. the
    #: road corridor's shared-use path; None for most parts
    family_class: str | None = None
```

include it in `bare`:

```python
        return (self.predefined_type is None and self.usage_type is None
                and self.parent is None and self.family_class is None)
```

and in `parse_part` take the key:

```python
        unknown = set(value) - {"name", "predefined_type", "usage_type", "parent",
                                "family_class"}
        ...
        return SpatialPart(
            name=str(value["name"]),
            predefined_type=(str(value["predefined_type"])
                             if value.get("predefined_type") else None),
            usage_type=str(usage).upper() if usage else None,
            parent=parse_part(value.get("parent"), f"{where}.parent"),
            family_class=(str(value["family_class"])
                          if value.get("family_class") else None))
```

In `bimforge/author/emit_ifc.py`, in `emit_combined_ifc` right after `classed: list = []`, add:

```python
    # a facility part's dictionary class (SpatialPart.family_class), written
    # with the elements' after the sweep
    for m, home, fac in zip(models, homes, facilities):
        for name, part in _model_parts(m, fac).items():
            if part.family_class and name in home.parts:
                classed.append((home.parts[name], part.family_class))
```

- [ ] **Step 4: The class codes** (append to `bimforge/author/corridor/dimensions.py`):

```python
#: V1.2 C: the shared-use path's road part, and its rail on a wall
SHARED_USE_PATH = "road-corridor-shared-use-path"
PATH_RAIL = "road-corridor-path-rail"
```

- [ ] **Step 5: The dictionary classes.** From the worktree root:

```bash
python - <<'PY'
import json
from pathlib import Path
p = Path("bimforge/author/dictionary/bimforge-families.bsdd.json")
d = json.loads(p.read_text("utf-8"))
dims = "A dimension that sizes the element (M.2)."
def prop(code, required=True):
    return {"Code": code, "PropertyCode": code, "PropertySet": "BIMForge_Dimensions",
            "IsRequired": required, "Description": dims}
stations = [prop(c) for c in ("StartStation", "EndStation", "StartStationText",
                              "EndStationText")]
d["Classes"] += [
    {"Code": "road-corridor-shared-use-path", "Name": "Shared-use path",
     "ClassType": "Class",
     "Definition": "A Class I shared-use path beside a road corridor, on its own "
                   "profile: the IfcRoadPart (USERDEFINED SHAREDUSEPATH) its paved "
                   "courses and rails belong to.",
     "RelatedIfcEntityNamesList": ["IfcRoadPart"], "CountryOfOrigin": "US",
     "DocumentReference": "Caltrans Highway Design Manual, Index 1003.1"},
    {"Code": "road-corridor-path-rail", "Name": "Path rail", "ClassType": "Class",
     "Definition": "The rail on a wall that holds a shared-use path up, keeping "
                   "riders and walkers from falling: a run over the wall's "
                   "stations, its height above the wall's top.",
     "RelatedIfcEntityNamesList": ["IfcRailing", "IfcRailingGUARDRAIL"],
     "CountryOfOrigin": "US",
     "DocumentReference": "Caltrans Highway Design Manual, Index 1003.1",
     "ClassProperties": [prop("RailHeight")] + stations},
]
p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", "utf-8")
PY
python -m pytest bimforge/author/tests/test_dictionary.py -q
```

Expected: PASS (`RailHeight` and the stations are existing properties; the new classes start with `road-corridor-`, which the dictionary tests leave to the corridor's).

- [ ] **Step 6: The rail and the part's class** in `bimforge/author/families/road_corridor.py`. Give `path_part` the class:

```python
    return {"name": f"Segment {r} shared-use path",
            "predefined_type": "SHAREDUSEPATH", "usage_type": "LATERAL",
            "parent": segment, "family_class": "road-corridor-shared-use-path"}
```

Add:

```python
#: the path's rail body: a band this deep from the wall's top up to the
#: rail's height, on the path's side of the face, feet
PATH_RAIL_DEPTH_FT = 0.25


def run_of(runs: list, s: float) -> int:
    """The number (from 1) of the corridor run, of `runs` (each its
    sections), that station s is on."""
    from bimforge.author.alignment import sta
    for r, secs in enumerate(runs, start=1):
        if secs[0].s - 1e-6 <= s <= secs[-1].s + 1e-6:
            return r
    raise ValueError(f"station {sta(s)} is on no corridor run")


def path_rail_walls(c) -> list:
    """The wall gaps that carry the path's rail: a strip wall at the path's
    inner shoulder, a fill wall on its outer side."""
    return [g for g in c.gaps if g.auto in ("strip-path", "path-fill")]


def path_rail_element(g, c, al, prof, ctx, part: dict, height: float,
                      type_name: str, family_class: str):
    """The rail on wall gap `g` as an IfcRailing GUARDRAIL: a
    PATH_RAIL_DEPTH_FT band from the wall's top (q for a strip wall, o for
    an outer one) up `height`, on the path's side of the face, lofted at the
    corridor's stations along the road's profile."""
    from bimforge.author.alignment import sta
    from bimforge.author.corridor import dimensions as dims
    from bimforge.author.corridor.frame import densify
    from bimforge.author.corridor.loft import StationLoft
    from bimforge.author.corridor.path import surface
    from bimforge.author.model import Element
    p = c.path
    stations = densify(al, prof, c.stations(
        g.start, g.end, geometry_stations(al, prof, g.start, g.end)))
    rings = []
    for s in stations:
        sf = surface(c, s)
        (bu, bv), inward = (sf.q, p.sign) if g.strip else (sf.o, -p.sign)
        x, top = bu + inward * PATH_RAIL_DEPTH_FT, bv + height / sf.cg
        rings.append([(bu, bv), (x, bv), (x, top), (bu, top)])
    name = f"{type_name} {g.side} STA {sta(g.start)} to {sta(g.end)}"
    loft = StationLoft(name, al, prof, ctx, stations, rings, ifc="IfcRailing",
                       layer=LAYER)
    length = g.end - g.start
    return Element(
        name, ifc_class="IfcRailing", geometry=[loft], predefined_type="GUARDRAIL",
        type_name=type_name, typed_late=True, family_class=family_class,
        material="Steel", layer=LAYER, body="solids", spatial_part=part,
        quantities={"length_ft": length, "volume_cf": loft.volume_cf},
        dimensions={"RailHeight": height, **dims.stations(g.start, g.end)},
        psets={"BIMForge_Guardrail": {
            "RailHeight": ("length", height),
            "StartStation": ("length", g.start), "EndStation": ("length", g.end),
            "StartStationText": sta(g.start), "EndStationText": sta(g.end)}},
        standard_qto={"Qto_RailingBaseQuantities": {
            "Length": ("length", length, dims.LENGTH)}})
```

In `build`, after the road's rails loop (`for rail in rails: ...`):

```python
    if c.path is not None:
        from bimforge.author.corridor import dimensions as dims
        for g in path_rail_walls(c):
            r = run_of(runs, g.start)
            segment, _kinds = _parts(r)
            model.add(path_rail_element(g, c, al, prof, ctx, path_part(segment, r),
                                        c.path.rail_height, "Path rail",
                                        dims.PATH_RAIL))
```

- [ ] **Step 7: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_road_corridor_path.py bimforge/author/tests/test_dictionary.py bimforge/author/tests/test_road_corridor_v11.py bimforge/author/tests/test_spatial.py -q`
Expected: PASS. (If `test_spatial.py` is named otherwise, run `python -m pytest bimforge/author/tests -q -k spatial`.)

- [ ] **Step 8: Commit**

```bash
git add bimforge/author/spatial.py bimforge/author/emit_ifc.py bimforge/author/corridor/dimensions.py bimforge/author/dictionary/bimforge-families.bsdd.json bimforge/author/families/road_corridor.py bimforge/author/tests/test_road_corridor_path.py
git commit -F - <<'EOF'
road-corridor: the path's road part and its rail, with their classes (P.6, part C)

A spatial part may reference a family-dictionary class, written after the
GlobalId sweep. The path's IfcRoadPart is road-corridor-shared-use-path;
a wall holding the path up carries an IfcRailing GUARDRAIL typed Path rail
(road-corridor-path-rail), 42 in by default.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

### Task 11: The path's checks and tables

**Files:**
- Create: `bimforge/author/corridor/path_checks.py`
- Modify: `bimforge/author/families/road_corridor.py`, `bimforge/author/families/registry.py`
- Test: `bimforge/author/tests/test_corridor_path_checks.py` (create), `bimforge/author/tests/test_registry.py`

`outputs.path_checks` lists every advisory deviation, one row per stretch (check, from, to, value, limit, reference): a grade over 5 % on the path or on a deck (1003.1(14)); a grade over 2 % sustained for more than 500 ft (1003.1(14), for information); a crest vertical curve short of stopping sight distance (1003.1(11), (12): L = A S²/1600 where S < L, else 2S - 1600/A; S 125 ft at 20 mph, 230 ft at 30 mph; 30 mph wherever a grade beside the curve is steeper than 4 % for more than 500 ft, whatever `design_speed_mph` says); a separation under 10 ft that no road guardrail shields (a barrier is needed); under 5 ft on an approach; each strip wall with its side and height. Stretches are found every foot and each end refined by bisection to 1e-6 ft. The path's grade is along its own length: the profile's rise per road station over (1 - κu) at the paved centre.

`outputs.path` has one row per section station that carries the path, and one per interval station on a deck.

Hand values (Task 2's level road, the path's stations 10+00 to 20+00):
- a 6 % path: one row, `grade>5%`, 10+00 to 20+00, 6.00 against 5;
- a crest from 5 % to -3 % over 20 ft (A = 8, 20 mph, S = 125): A S²/1600 = 78.1 < S, so L = 2 × 125 - 1600/8 = 50 ft: 20 < 50, listed; the grades beside it run 490 ft, not long enough to make it 30 mph;
- a crest from 3 % to -4.5 % over 100 ft (A = 7.5): at 20 mph L = 250 - 213.33 = 36.67, enough; with the -4.5 % running 600 ft after it, 30 mph: 7.5 × 230²/1600 = 247.97 > 230, short; with it running 400 ft, not listed;
- separation 12 ft, down to 8 ft at 11+00, 8 ft to 13+00, back to 12 ft at 14+00: under 10 ft from 10+50 to 13+50; a rail on its side from 10+00 to 12+00 leaves 12+00 to 13+50;
- Task 3's narrowing approaches: under 5 ft from 13+58.82 (10 - 8.5 × 58.82/100 = 5) to 14+00 and from 15+00 to 15+41.18.

- [ ] **Step 1: Write the failing tests** `bimforge/author/tests/test_corridor_path_checks.py`

```python
"""road-corridor V1.2 part C: the path's advisory checks (HDM 1003.1)."""
import pytest

from bimforge.author.corridor import path_checks as pc
from bimforge.author.tests.test_corridor_path import (GAP, NARROW, corridor,
                                                      deck_path, grade, path)


def curves(rows, s=1000.0, z=100.0):
    """A profile from (g_in, g_out, length) rows, end to end from s."""
    out = []
    for g1, g2, length in rows:
        z1 = z + g1 / 100.0 * length + (g2 - g1) / 100.0 * length / 2.0
        out.append({"bvc_station": s, "bvc_elev": round(z, 6), "g_in_pct": g1,
                    "g_out_pct": g2, "length_ft": length,
                    "evc_station": s + length, "evc_elev": round(z1, 6)})
        s, z = s + length, z1
    return {"curves": out}


def rows(found, check):
    return [(r.start, r.end, r.value, r.limit) for r in found if r.check.startswith(check)]


def test_a_6_percent_path_is_listed():
    found = pc.grade_rows(corridor(path(profile=grade(99.51, pct=6.0))))
    assert rows(found, "grade>5%") == [(pytest.approx(1000.0), pytest.approx(2000.0),
                                        pytest.approx(6.0), 5.0)]
    assert rows(found, "sustained grade>2%") == [(pytest.approx(1000.0),
                                                  pytest.approx(2000.0),
                                                  pytest.approx(1000.0), 500.0)]


def test_a_crest_short_of_ssd_at_20_mph_is_listed():
    c = corridor(path(profile=curves([(5, 5, 490), (5, -3, 20), (-3, -3, 490)])))
    assert rows(pc.crest_rows(c), "crest") == [(1490.0, 1510.0, 20.0,
                                                pytest.approx(50.0))]


def test_a_long_steep_downgrade_makes_it_30_mph():
    long_down = curves([(3, 3, 300), (3, -4.5, 100), (-4.5, -4.5, 600)])
    (row,) = pc.crest_rows(corridor(path(profile=long_down)))
    assert row.check == "crest VC short of SSD at 30 mph"
    assert (row.value, row.limit) == (100.0, pytest.approx(7.5 * 230 ** 2 / 1600))
    short_down = curves([(3, 3, 300), (3, -4.5, 100), (-4.5, -4.5, 400),
                         (-4.5, 0, 100), (0, 0, 100)])
    assert pc.crest_rows(corridor(path(profile=short_down))) == []


def test_the_crest_length_rule():
    assert pc.crest_length(8.0, 125.0) == pytest.approx(50.0)      # S > L
    assert pc.crest_length(7.5, 230.0) == pytest.approx(247.96875)  # S < L
    assert pc.crest_length(2.0, 125.0) == 0.0                      # none needed


class Rail:
    def __init__(self, side, start, end):
        self.side, self.start, self.end = side, start, end


def test_a_separation_under_10_ft_needs_a_barrier_where_no_rail_runs():
    c = corridor(path(separation=[[1000, 12.0], [1100, 8.0], [1300, 8.0], [1400, 12.0]]))
    assert rows(pc.barrier_rows(c, []), "barrier") == [
        (pytest.approx(1050.0), pytest.approx(1350.0), pytest.approx(8.0), 10.0)]
    shielded = pc.barrier_rows(c, [Rail("L", 1000.0, 1200.0), Rail("R", 1000.0, 2000.0)])
    assert rows(shielded, "barrier") == [
        (pytest.approx(1200.0), pytest.approx(1350.0), pytest.approx(8.0), 10.0)]


def test_under_5_ft_on_an_approach_is_listed():
    c = corridor(deck_path(), gaps=GAP)
    assert rows(pc.approach_rows(c), "separation<5ft") == [
        (pytest.approx(1358.8235, abs=1e-3), pytest.approx(1400.0), pytest.approx(1.5), 5.0),
        (pytest.approx(1500.0), pytest.approx(1541.1765, abs=1e-3), pytest.approx(1.5), 5.0)]
    # the deck itself is not the path's to list: no barrier row inside the gap
    assert all(r.end <= 1400.0 + 1e-6 or r.start >= 1500.0 - 1e-6
               for r in pc.barrier_rows(c, []))


def test_the_tables_have_their_headers():
    assert pc.CHECK_HEADER == "check,from,to,value,limit,reference"
    assert pc.PATH_HEADER.startswith("station,side,separation_ft,offset_ft,")
    row = pc.CheckRow("grade>5%", 1000.0, 1100.0, 6.0, 5.0, "HDM 1003.1(14)")
    assert pc.checks_csv([row]).splitlines()[1] == (
        "grade>5%,1000.00,1100.00,6.00,5.00,HDM 1003.1(14)")
```

Append to `bimforge/author/tests/test_road_corridor_path.py`:

```python
def test_the_family_writes_the_path_tables(built):
    m, _log = built
    assert m.tables["path"].splitlines()[0].startswith("station,side,separation_ft")
    lines = m.tables["path"].splitlines()[1:]
    first = lines[0].split(",")
    assert (first[0], first[1], first[2]) == ("1000.00", "R", "10.00")
    assert any(line.split(",")[-1] == "deck" for line in lines)      # on the bridge
    assert any("approach" in line.split(",")[-1] for line in lines)
    checks = m.tables["path_checks"].splitlines()
    assert checks[0] == "check,from,to,value,limit,reference"
    assert any(line.startswith("separation<5ft,") for line in checks)
```

Change `test_registry.py`'s table-output test to cover the new keys:

```python
@pytest.mark.parametrize("key", ["walls", "structures", "guardrail", "path",
                                 "path_checks"])
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_corridor_path_checks.py bimforge/author/tests/test_registry.py -q`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'bimforge.author.corridor.path_checks'`; the registry's new cases FAIL (`outputs.path` is an unknown output key).

- [ ] **Step 3: Create** `bimforge/author/corridor/path_checks.py`

```python
"""The shared-use path's checks and station table (P.6, V1.2 part C).

outputs.path_checks lists every advisory deviation from HDM Index 1003.1
("should"s, and phase 2's USFS equestrian guidance), one row per stretch;
outputs.path lists the path at every section station. Nothing here is an
error: the path's errors are params' and path.validate's.

Stretches are found every SAMPLE_FT along the path and each end refined by
bisection to 1e-6 ft. The path's grade is along its own length: its
profile's rise per road station over (1 - kappa u), u its paved centre's
offset.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

CHECK_HEADER = "check,from,to,value,limit,reference"
PATH_HEADER = ("station,side,separation_ft,offset_ft,hinge_elev_ft,path_elev_ft,"
               "difference_ft,grade_pct,strip,barrier,note")
#: 1003.1(14)
MAX_GRADE = 0.05
SUSTAINED_GRADE = 0.02
SUSTAINED_FT = 500.0
#: stopping sight distance by design speed, feet (1003.1(11))
SSD_FT = {20: 125.0, 30: 230.0}
#: a downgrade steeper than this for longer than STEEP_RUN_FT takes 30 mph
#: (Table 1003.1)
STEEP_DOWNGRADE = 0.04
STEEP_RUN_FT = 500.0
#: the checks' sampling step along the path, feet
SAMPLE_FT = 1.0
DECK_CHECK = "deck grade>5%"
_EPS = 1e-9


@dataclass(frozen=True)
class CheckRow:
    check: str
    start: float
    end: float
    value: float
    limit: float | None          # None where the row only lists (a wall)
    reference: str


def _edge(pred, off: float, on: float) -> float:
    """Where pred starts to hold between `off` (false) and `on` (true), on
    the `on` side, to 1e-6 ft."""
    for _ in range(60):
        if abs(on - off) < 1e-7:
            break
        mid = 0.5 * (off + on)
        if pred(mid):
            on = mid
        else:
            off = mid
    return on


def spans(a: float, b: float, pred) -> list:
    """[(s0, s1)]: the stretches of [a, b] where pred(s) holds."""
    n = max(1, math.ceil((b - a) / SAMPLE_FT - _EPS))
    ss = [a + (b - a) * i / n for i in range(n + 1)]
    flags = [bool(pred(s)) for s in ss]
    out, i = [], 0
    while i < len(ss):
        if not flags[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(ss) and flags[j + 1]:
            j += 1
        s0 = ss[i] if i == 0 else _edge(pred, ss[i - 1], ss[i])
        s1 = ss[j] if j == len(ss) - 1 else _edge(pred, ss[j + 1], ss[j])
        out.append((s0, s1))
        i = j + 1
    return out


def _within(a: float, b: float) -> list:
    n = max(1, math.ceil((b - a) / SAMPLE_FT - _EPS))
    return [a + (b - a) * i / n for i in range(n + 1)]


def on_deck(c, s: float) -> bool:
    """Strictly inside a road structure gap: the path is on the deck."""
    return any(g.kind == "structure" and g.start + _EPS < s < g.end - _EPS
               for g in c.gaps)


def centre_u(c, s: float) -> float:
    from bimforge.author.corridor.section import grade_edge
    p = c.path
    return grade_edge(c, s, p.side)[0] + p.sign * (p.separation_at(s) + 0.5 * p.width)


def path_grade(c, s: float) -> float:
    """The path's grade at road station s, along its own length."""
    p = c.path
    return p.profile.grade(s) / (1.0 - p.alignment.curvature(s) * centre_u(c, s))


def profile_grade_rows(grade_at, s0: float, s1: float, skip, label: str = "") -> list:
    """Grades over 5 % (1003.1(14)) and over 2 % for more than 500 ft
    (1003.1(14), "should be limited to 2 percent": for information) on
    [s0, s1], where skip(s) is false; `grade_at(s)` the grade along the
    path's own length. `label` prefixes the check (an own stretch's)."""
    out = []

    def steep(limit):
        return lambda s: not skip(s) and abs(grade_at(s)) > limit + 1e-12

    for a, b in spans(s0, s1, steep(MAX_GRADE)):
        top = max(abs(grade_at(s)) for s in _within(a, b))
        out.append(CheckRow(f"{label}grade>5%", a, b, 100.0 * top, 100.0 * MAX_GRADE,
                            "HDM 1003.1(14)"))
    for a, b in spans(s0, s1, steep(SUSTAINED_GRADE)):
        if b - a > SUSTAINED_FT + _EPS:
            out.append(CheckRow(f"{label}sustained grade>2%", a, b, b - a,
                                SUSTAINED_FT, "HDM 1003.1(14)"))
    return out


def grade_rows(c) -> list:
    """The path's grade rows beside the road, off the decks it is on."""
    p = c.path
    return profile_grade_rows(lambda s: path_grade(c, s), p.s_start, p.s_end,
                              lambda s: on_deck(c, s))


def deck_rows(c) -> list:
    """A deck the path is on graded over 5 % (1003.1(14), "should")."""
    p = c.path
    out = []
    for g in c.gaps:
        if g.kind != "structure":
            continue
        a, b = max(g.start, p.s_start), min(g.end, p.s_end)
        if b - a <= _EPS:
            continue
        for x, y in spans(a, b, lambda s: abs(p.road_profile.grade(s)) > MAX_GRADE + 1e-12):
            top = max(abs(p.road_profile.grade(s)) for s in _within(x, y))
            out.append(CheckRow(DECK_CHECK, x, y, 100.0 * top, 100.0 * MAX_GRADE,
                                "HDM 1003.1(14)"))
    return out


def crest_length(a_pct: float, ssd: float) -> float:
    """The crest vertical curve that gives a path its stopping sight
    distance (1003.1(12)): L = A S^2 / 1600 where S < L, else 2S - 1600/A;
    0 where that is negative (no curve needed)."""
    long = a_pct * ssd * ssd / 1600.0
    if long > ssd:
        return long
    return max(0.0, 2.0 * ssd - 1600.0 / a_pct)


def _beside(profile, s0: float, s1: float, i: int, after: bool) -> tuple:
    """(grade %, length): the grade beside curve i of `profile`, after its
    EVC or before its BVC, through constant-grade curves to the next grade
    change or the end of [s0, s1]."""
    curves = profile.curves
    if after:
        g, start, end = curves[i]["g_out_pct"], curves[i]["evc_station"], s1
        for cv in curves[i + 1:]:
            if abs(cv["g_out_pct"] - cv["g_in_pct"]) > 1e-12:
                end = cv["bvc_station"]
                break
        return g, max(0.0, min(end, s1) - start)
    g, start, end = curves[i]["g_in_pct"], s0, curves[i]["bvc_station"]
    for cv in reversed(curves[:i]):
        if abs(cv["g_out_pct"] - cv["g_in_pct"]) > 1e-12:
            start = cv["evc_station"]
            break
    return g, max(0.0, end - max(start, s0))


def crest_speed(profile, s0: float, s1: float, design_speed: int, i: int) -> int:
    """30 mph for curve i where a grade beside it is steeper than 4 % for
    more than 500 ft (a downgrade one way of travel or the other, Table
    1003.1); else the design speed."""
    if design_speed == 30:
        return 30
    for g, run in (_beside(profile, s0, s1, i, False), _beside(profile, s0, s1, i, True)):
        if abs(g) > 100.0 * STEEP_DOWNGRADE + 1e-9 and run > STEEP_RUN_FT + _EPS:
            return 30
    return 20


def profile_crest_rows(profile, s0: float, s1: float, design_speed: int,
                       label: str = "") -> list:
    """Crest vertical curves of `profile` short of stopping sight distance
    (1003.1(11), (12))."""
    out = []
    for i, cv in enumerate(profile.curves):
        a_pct = cv["g_in_pct"] - cv["g_out_pct"]
        if a_pct <= 1e-12:
            continue                                     # a sag, or no curve
        speed = crest_speed(profile, s0, s1, design_speed, i)
        need = crest_length(a_pct, SSD_FT[speed])
        if cv["length_ft"] < need - _EPS:
            out.append(CheckRow(f"{label}crest VC short of SSD at {speed} mph",
                                cv["bvc_station"], cv["evc_station"],
                                cv["length_ft"], need, "HDM 1003.1(11), (12)"))
    return out


def crest_rows(c) -> list:
    p = c.path
    return profile_crest_rows(p.profile, p.s_start, p.s_end, p.design_speed)


def _shielded(rails, side: str, s: float) -> bool:
    return any(r.side == side and r.start - 1e-6 <= s <= r.end + 1e-6 for r in rails)


def barrier_rows(c, rails) -> list:
    """A separation under 10 ft with no road guardrail (`rails`,
    guardrail.RailRun) on the path's side: a barrier is needed
    (1003.1(7)). Off the decks."""
    from bimforge.author.corridor.path import BARRIER_SEPARATION_FT
    p = c.path

    def needs(s):
        return (not on_deck(c, s) and p.separation_at(s) < BARRIER_SEPARATION_FT - _EPS
                and not _shielded(rails, p.side, s))

    return [CheckRow("barrier needed (separation<10ft)", a, b,
                     min(p.separation_at(s) for s in _within(a, b)),
                     BARRIER_SEPARATION_FT, "HDM 1003.1(7)")
            for a, b in spans(p.s_start, p.s_end, needs)]


def approach_rows(c) -> list:
    """A separation under 5 ft on an approach: a deviation from 1003.1(7)'s
    minimum."""
    from bimforge.author.corridor.path import MIN_SEPARATION_FT, approaches
    p = c.path
    out = []
    for a, b, _e in approaches(c):
        a, b = max(a, p.s_start), min(b, p.s_end)
        for x, y in spans(a, b, lambda s: p.separation_at(s) < MIN_SEPARATION_FT - _EPS):
            out.append(CheckRow("separation<5ft on an approach", x, y,
                                min(p.separation_at(s) for s in _within(x, y)),
                                MIN_SEPARATION_FT, "HDM 1003.1(7)"))
    return out


def wall_rows(wall_rows_) -> list:
    """Each wall in the strip, with its side and height (walls.WallRow)."""
    return [CheckRow(f"strip wall {r.side} {r.kind}", r.start, r.end, r.max_height,
                     None, "HDM 1003.1(7)")
            for r in wall_rows_ if r.location == "strip"]


def checks(c, rails, walls_) -> list:
    """Every advisory row for corridor `c`'s path, by start station."""
    found = (grade_rows(c) + deck_rows(c) + crest_rows(c) + barrier_rows(c, rails)
             + approach_rows(c) + wall_rows(walls_))
    return sorted(found, key=lambda r: (r.start, r.check))


def checks_csv(rows: list) -> str:
    return "\n".join([CHECK_HEADER] + [
        f"{r.check},{r.start:.2f},{r.end:.2f},{r.value:.2f},"
        f"{'' if r.limit is None else format(r.limit, '.2f')},{r.reference}"
        for r in rows]) + "\n"


def _strip_label(ps) -> str:
    if ps.strip in ("wall-road", "wall-path", "ground"):
        return ps.strip
    return "level" if math.isinf(ps.ratio) else f"{ps.ratio:.2f}"


def path_csv(c, secs: list, rails) -> str:
    """outputs.path: one row per section of `secs` that carries the path,
    and one per corridor station on a deck the path crosses."""
    from bimforge.author.corridor.path import BARRIER_SEPARATION_FT, on_approach
    p = c.path
    prof = p.road_profile
    rows = []
    for sec in secs:
        ps = sec.path
        if ps is None:
            continue
        s, sf = sec.s, ps.surface
        hinge = prof.elev(s) + (sf.edge[1] - c.depth()) * sf.cg
        pz, g = p.profile.elev(s), path_grade(c, s)
        under = sf.separation < BARRIER_SEPARATION_FT - _EPS
        barrier = ("rail" if under and _shielded(rails, p.side, s)
                   else "yes" if under else "no")
        note = ";".join(x for x, on in (("approach", on_approach(c, s)),
                                        ("grade>5%", abs(g) > MAX_GRADE + 1e-12)) if on)
        rows.append((s, f"{s:.2f},{p.side},{sf.separation:.2f},{centre_u(c, s):.2f},"
                        f"{hinge:.3f},{pz:.3f},{pz - hinge:.3f},{100.0 * g:.2f},"
                        f"{_strip_label(ps)},{barrier},{note}"))
    for gap in c.gaps:
        if gap.kind != "structure":
            continue
        for s in c.stations(gap.start, gap.end)[1:-1]:
            if not p.covers(s):
                continue
            pz = p.profile.elev(s)
            rows.append((s, f"{s:.2f},{p.side},{p.separation_at(s):.2f},"
                            f"{centre_u(c, s):.2f},,{pz:.3f},,"
                            f"{100.0 * prof.grade(s):.2f},deck,deck,deck"))
    return "\n".join([PATH_HEADER] + [r for _s, r in sorted(rows)]) + "\n"
```

- [ ] **Step 4: The family writes them.** In `bimforge/author/families/road_corridor.py` `build`, at the end before `return model`:

```python
    if c.path is not None:
        from bimforge.author.corridor import path_checks
        wall_rows = auto_walls.rows(c, every, ground_dz) if c.auto_walls else []
        model.tables["path"] = path_checks.path_csv(c, sorted(every, key=lambda x: x.s),
                                                    rails)
        model.tables["path_checks"] = path_checks.checks_csv(
            path_checks.checks(c, rails, wall_rows))
```

- [ ] **Step 5: The registry writes them.** In `bimforge/author/families/registry.py`:

```python
OUTPUT_KEYS = ("dxf", "ifc", "takeoff_map", "qto", "step", "bbs", "masshaul",
               "walls", "structures", "guardrail", "path", "path_checks")
#: outputs a family writes from StructureModel.tables, as CSV
TABLE_OUTPUTS = ("walls", "structures", "guardrail", "path", "path_checks")
```

the missing-table error's parenthesis:

```python
                f"{spec['family']!r} makes no {key} table here (a road "
                f"corridor makes walls and structures with walls: auto, "
                f"guardrail with a steep fill rule, a guardrail: block or a "
                f"path, and path and path_checks with a path:)")
```

and the module docstring's outputs list gains:

```
              path: CAD/x.path.csv,               # its shared-use path by station
              path_checks: CAD/x.path-checks.csv, # the path's HDM 1003.1 rows
```

- [ ] **Step 6: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_corridor_path_checks.py bimforge/author/tests/test_road_corridor_path.py bimforge/author/tests/test_registry.py bimforge/author/tests/test_road_corridor_v11.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add bimforge/author/corridor/path_checks.py bimforge/author/families/road_corridor.py bimforge/author/families/registry.py bimforge/author/tests/test_corridor_path_checks.py bimforge/author/tests/test_road_corridor_path.py bimforge/author/tests/test_registry.py
git commit -F - <<'EOF'
road-corridor: the path's HDM 1003.1 checks and its station table (P.6, part C)

outputs.path_checks lists grades over 5 % (path and deck), grades over 2 %
for more than 500 ft, crests short of stopping sight distance (30 mph
beside a downgrade over 4 % for 500 ft), separations under 10 ft no rail
shields, under 5 ft on an approach, and strip walls. outputs.path lists
the path at every station.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

### Task 12: The shipped example gains a path

**Files:**
- Modify: `bimforge/author/examples/road-corridor.spec.yaml`, `bimforge/author/examples/road-corridor.paycodes.yaml`
- Modify: `bimforge/author/tests/fixtures/example_globalids.json` (the `road-corridor` block, re-recorded)
- Modify: `docs/ifc-inventory.json`, `docs/ifc-inventory.md` (regenerated)
- Modify: `scripts/bsi_baseline.yaml` (only for a finding accepted in Step 6)

The path runs on the right the whole length, on its own profile: 7.5 ft below the road at the start (a strip wall at the road's hinge until the strip fits 2:1, about 12+35), climbing at 4.9 % to meet the bridge deck at 17+00 and 18+00 (the separation narrowing from 10 ft to 1.5 ft over each 100 ft approach), then 4.26 % and 4.9 % to the end, where the road's 5.6 % leaves it 1.9 ft below. The profile's elevations are the deck's at its paved edge: the right edge of shoulder (the shoulder 10 ft from 13+00 at -5 %, the lane at -4 % of superelevation) and -4 % over 1.5 ft: 322.0730 at 17+00, 326.3319 at 18+00, a grade of 4.2589 % between them.

- [ ] **Step 1: Add the path** to `bimforge/author/examples/road-corridor.spec.yaml`. Change the header comment's first paragraph to:

```yaml
# Worked road-corridor run (P.6, V1.1 and part C): a two-lane road on a
# tangent, a 1000 ft right curve and a second tangent, over a sloping plane
# of ground. A cut at the start meets shallow rock; past the bridge the fill
# deepens beyond 10 ft, so it runs 4:1 below that and 2:1 behind guardrail
# above, and an automatic wall stands where the left slope would reach past
# its footprint. A superelevation run through the curve, a shoulder that
# widens, a gap for a bridge and a listed wall gap on the left. A shared-use
# path on the right on its own profile: a wall at the road's hinge while it
# runs low, an approach each side of the bridge where it meets the deck.
```

and after `mass_haul:` add:

```yaml
  path:                                 # a shared-use path (HDM 1003.1)
    side: R
    separation: [[1000, 10.0], [1600, 10.0], [1700, 1.5], [1800, 1.5], [1900, 10.0]]
    width: 12.0
    cross_slope: -0.02                  # falling away from the road
    shoulder: {width: 2.0, slope: -0.05}
    courses:
      - {name: PATH-HMA, type: PAVEMENT, thickness: 0.25}
      - {name: PATH-AB, type: CORE, thickness: 0.50}
    profile:                            # its paved inner edge; on the deck at
      curves:                           # 17+00 and 18+00
        - {bvc_station: 1000.0, bvc_elev: 290.3374, g_in_pct: 4.9, g_out_pct: 4.2589,
           length_ft: 600.0, evc_station: 1600.0, evc_elev: 317.8141}
        - {bvc_station: 1600.0, bvc_elev: 317.8141, g_in_pct: 4.2589, g_out_pct: 4.2589,
           length_ft: 300.0, evc_station: 1900.0, evc_elev: 330.5908}
        - {bvc_station: 1900.0, bvc_elev: 330.5908, g_in_pct: 4.2589, g_out_pct: 4.9,
           length_ft: 300.0, evc_station: 2200.0, evc_elev: 344.3291}
        - {bvc_station: 2200.0, bvc_elev: 344.3291, g_in_pct: 4.9, g_out_pct: 4.9,
           length_ft: 349.07, evc_station: 2549.07, evc_elev: 361.4335}
    design_speed_mph: 20
```

and under `outputs:`:

```yaml
  path: out/road-corridor.path.csv
  path_checks: out/road-corridor.path-checks.csv
```

- [ ] **Step 2: Pay the path** in `bimforge/author/examples/road-corridor.paycodes.yaml`: change the first comment line to `# Road corridor: pavement courses and earthwork (CY), guardrail and path rail (LF).`; under `rules:` before the `HMA` rule (a rule matches from the name's start, so `PATH-HMA` is not `HMA`) add

```yaml
  - match: "(?i)^PATH-HMA "
    group: rc_path_hma
  - match: "(?i)^PATH-AB "
    group: rc_path_ab
  - match: "(?i)^Path rail "
    group: rc_path_rail
```

under `groups:` add `  rc_path_hma: {measure: GrossVolume}`, `  rc_path_ab: {measure: GrossVolume}`, `  rc_path_rail: {measure: Length}`; under `codes:` add

```yaml
  PATH-HMA:
    group: rc_path_hma
    measure: GrossVolume
    unit: CY
    description: "Hot mix asphalt (shared-use path)"
  PATH-AB:
    group: rc_path_ab
    measure: GrossVolume
    unit: CY
    description: "Class 2 aggregate base (shared-use path)"
  RAIL-PATH:
    group: rc_path_rail
    measure: Length
    unit: LF
    description: "Path rail on a wall (42 in)"
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
for key in ("walls", "structures", "guardrail", "path-checks"):
    print((tmp / "out" / f"road-corridor.{key}.csv").read_text("utf-8"))
print("\n".join((tmp / "out" / "road-corridor.path.csv").read_text("utf-8").splitlines()[:12]))
PY
```

Expected (the stations are hand estimates over a plane, so read "about"):
- walls: an `R,wall-road,strip` row from `1000.00` to about 12+35 (the road's hinge 5.9 ft above q at the start, 2.0 ft at 12+35), barrier `yes`, not too tall; the left side's rows as before, with `location` `outer`;
- path-checks: `barrier needed (separation<10ft)` from 18+00 to 19+00 (the right bridge rail shields 16+00 to 17+00: its length of need runs up-station from about 15+37), `separation<5ft on an approach` from about 16+58.82 to 17+00 and from 18+00 to about 18+41.18, `sustained grade>2%` twice, 10+00 to 17+00 and 18+00 to the end (the deck between is the road's), the `strip wall R wall-road` row; no `grade>5%` (the path keeps 4.9 %), no crest row (its one crest, 4.9 % to 4.2589 %, changes grade by 0.64 %: A S²/1600 = 6.3 ft and 2S - 1600/A is negative, so no curve is needed);
- path: the first row `1000.00,R,10.00,...,wall-road,...`.

If the build fails with `path.profile: at the structure gap's end ...`, the road's edge of shoulder there is not what this task's notes say: print `deck_elevation(c, 1700.0)` and `deck_elevation(c, 1800.0)` from a `parse(...)` of the spec and refit the profile's four curves to them, keeping the grades' continuity (the second curve's grade is their difference over 100 ft). If it fails with `the R ... slope finds no ground`, the path's outer cut at the start reaches past the daylight limit: lower `bvc_elev` no further, raise `daylight_limit_ft`.

- [ ] **Step 4: Run the conformance suite on it and regenerate the inventory**

```bash
OUT="${TMPDIR:-/tmp}/rc-conformance"
BIMFORGE_CONFORMANCE_OUT="$OUT" python -m pytest bimforge/bim/tests/test_conformance.py -q
python scripts/ifc_inventory.py "$OUT"
python scripts/ifc_inventory.py "$OUT" --check
git diff --stat docs/ifc-inventory.json docs/ifc-inventory.md
```

Expected: the conformance tests PASS on IFC4X3 and IFC4; `--check` passes after the regeneration; the diff adds the path's road part (`IfcRoadPart` USERDEFINED `SHAREDUSEPATH`), its `IfcRailing` and `BIMForge_Guardrail`'s `RailHeight`, and removes nothing.

- [ ] **Step 5: Re-record the example's GlobalIds**

Run `python -m pytest bimforge/author/tests/test_example_globalids.py -q`. Expected: FAIL for `road-corridor` (new elements: the path's courses and rail; the roots written in the sweep renumber after them). Re-record its block (the V1.1 build stays pinned by Task 1's fixture):

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

Expected: only the `road-corridor` block changes. Then `python -m pytest bimforge/author/tests/test_example_globalids.py -q` PASSES.

- [ ] **Step 6: The bSI rules**

With an `ifc-gherkin-rules` checkout (`scripts/bsi_rules.py`'s docstring):

```bash
OUT="${TMPDIR:-/tmp}/rc-conformance"
python scripts/bsi_rules.py --rules ifc-gherkin-rules --python rules-venv/bin/python "$OUT"
```

Expected: `road-corridor` and `road-corridor-ifc4` report only the baseline's findings, and nothing is stale. A new finding on the road part, the rail or the classification is fixed in the code if it is the writer's error; if it is the rule's, add it to `scripts/bsi_baseline.yaml` with a `why` and list it in the PR. Without a checkout, CI's bSI job runs it on the PR.

- [ ] **Step 7: Run the full suite**

Run: `python -m pytest bimforge tests -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add bimforge/author/examples/road-corridor.spec.yaml bimforge/author/examples/road-corridor.paycodes.yaml bimforge/author/tests/fixtures/example_globalids.json docs/ifc-inventory.json docs/ifc-inventory.md
git add scripts/bsi_baseline.yaml   # only if Step 6 changed it
git commit -F - <<'EOF'
road-corridor example: a shared-use path on the right (P.6, part C)

The path runs on its own profile: low at the start behind a wall at the
road's hinge, climbing at 4.9 % to meet the bridge deck over a 100 ft
approach each side, then 4.26 % and 4.9 % to the end. Its pay codes have
no item number. The example's GlobalIds are re-recorded (its elements
change); the V1.1 build stays pinned in tests/fixtures/road-corridor-v11.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

## Phase 2: path gaps and the equestrian tread

Phase 2 ends with a path that can leave the road's section for a structure of its own (a path gap), and that can carry an unpaved equestrian tread beyond its paved width, with its fence, its 54 in rail, its advisory checks and its road part.

### Task 13: Path gaps

**Files:**
- Modify: `bimforge/author/corridor/path.py`, `bimforge/author/corridor/params.py`
- Test: `bimforge/author/tests/test_corridor_path.py`

`path.gaps` lists the path's own structures, `{from, to, kind: structure}` on road stations. Inside one the family builds nothing for the path: the path's side of the road's section is the road's own (V1.1's slope, walls and guardrail), as if there were no path. The path's section is built up to 1 ft outside each end and turns into the road's own across that foot, as a V1 section turns into a wall gap. At a road structure gap's end inside a path gap the deck-meeting check and the approach rule are waived (the road's deck carries no path there), and the separation inside a path gap is not held to the 5 ft rule (a path bridge is separated by its own edge).

- [ ] **Step 1: Write the failing tests** (append to `test_corridor_path.py`)

```python
from bimforge.author.corridor.path import PathGap


def test_a_path_gap_takes_the_path_off_the_section():
    c = corridor(path(gaps=[{"from": 1400, "to": 1600, "kind": "structure"}]))
    assert c.path.gaps == (PathGap(1400.0, 1600.0),)
    # built up to 1 ft outside each end; the road's own section inside
    assert [c.path_at(s) for s in (1399.0, 1399.5, 1400.0, 1500.0, 1600.0,
                                   1601.0)] == [True, False, False, False, False, True]
    assert {1399.0, 1400.0, 1600.0, 1601.0} <= set(c.stations(1375.0, 1625.0))


def test_inside_a_path_gap_the_section_is_the_road_s_alone():
    c = corridor(path(gaps=[{"from": 1400, "to": 1600, "kind": "structure"}]))
    road = parse(dict(copy.deepcopy(BASE), guardrail={"design_speed_mph": 45}),
                 1000.0, 2000.0)                      # the same guardrail rule
    sec, alone = resolve(c, 1500.0, level(-5.0)), resolve(road, 1500.0, level(-5.0))
    assert sec.path is None
    assert sec.sides["L"].line == alone.sides["L"].line
    ground = PlaneGround(95.0)
    assert fill_area(c, ground) == pytest.approx(fill_area(road, ground), abs=1e-9)


def test_a_path_gap_over_a_road_gap_waives_the_deck_and_the_approach():
    # 10 ft from the road at the bridge's ends and 0.03 ft off the deck's
    # line: refused without the path gap, built with it
    with pytest.raises(ValueError, match=r"is not deck_separation_ft"):
        corridor(path(), gaps=GAP)
    c = corridor(path(gaps=[{"from": 1380, "to": 1520, "kind": "structure"}]), gaps=GAP)
    assert approaches(c) == []


def test_inside_a_path_gap_the_separation_is_not_held_to_5_ft():
    sep = [[1000, 10.0], [1450, 10.0], [1500, 3.0], [1550, 3.0], [1600, 10.0]]
    with pytest.raises(ValueError, match=r"3\.00 ft at 15\+00\.00 is under the 5 ft"):
        corridor(path(separation=sep))
    corridor(path(separation=sep, gaps=[{"from": 1440, "to": 1610, "kind": "structure"}]))


@pytest.mark.parametrize("gaps, match", [
    ([{"from": 900, "to": 1100, "kind": "structure"}],
     r"path\.gaps\[0\]: 9\+00\.00 to 11\+00\.00 is outside the path's stations"),
    ([{"from": 1200, "to": 1400, "kind": "structure"},
      {"from": 1300, "to": 1500, "kind": "structure"}],
     r"path\.gaps: 12\+00\.00 to 14\+00\.00 overlaps 13\+00\.00 to 15\+00\.00"),
    ([{"from": 1200, "to": 1400, "kind": "wall"}],
     r"path\.gaps\[0\]: kind 'wall' is not 'structure'"),
    ([{"from": 1400, "to": 1200, "kind": "structure"}],
     r"path\.gaps\[0\]: 'to' must be past 'from'"),
])
def test_bad_path_gaps_are_refused(gaps, match):
    with pytest.raises(ValueError, match=match):
        corridor(path(gaps=gaps))
```

`fill_area` and `PlaneGround` are Task 7's.

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_corridor_path.py -q`
Expected: collection ERROR, `ImportError: cannot import name 'PathGap'`.

- [ ] **Step 3: Implement** in `bimforge/author/corridor/path.py`. Add `"gaps"` to `KEYS`. Add before `Path`:

```python
@dataclass(frozen=True)
class PathGap:
    """A stretch where the path is on a structure of its own (`path.gaps`),
    road stations; the structure is its own family's."""
    start: float
    end: float
```

Add a field and two methods to `Path`:

```python
    gaps: tuple = ()               # PathGap, by start station (phase 2)

    def in_gap(self, s: float, margin: float = 0.0) -> bool:
        """Whether station s is inside a path gap grown by `margin` each
        way (strictly: a gap's end grown by the margin is outside it)."""
        return any(g.start - margin + _EPS < s < g.end + margin - _EPS
                   for g in self.gaps)

    def waived(self, s: float) -> bool:
        """A road structure gap's end at s inside a path gap (its ends
        included): the deck carries no path there, so it is not met and no
        approach leads to it."""
        return any(g.start - _EPS <= s <= g.end + _EPS for g in self.gaps)
```

Add the parser (after `_separation`):

```python
def _path_gaps(value, s0: float, s1: float, where: str = "path.gaps") -> tuple:
    """Path gaps on [s0, s1]: road stations, or (phase 3) an own stretch's
    own stations under `where`."""
    out = []
    for i, g in enumerate(value or []):
        at = f"{where}[{i}]"
        if not isinstance(g, dict):
            raise ValueError(f"{at}: a mapping ({{from, to, kind: structure}})")
        kind = str(g.get("kind", "")).lower()
        if kind != "structure":
            raise ValueError(f"{at}: kind {g.get('kind')!r} is not 'structure': a "
                             f"path gap is the path's own structure")
        a = _num(g.get("from"), f"{at}.from", positive=False)
        b = _num(g.get("to"), f"{at}.to", positive=False)
        if not b > a:
            raise ValueError(f"{at}: 'to' must be past 'from'")
        if a < s0 - _EPS or b > s1 + _EPS:
            raise ValueError(f"{at}: {sta(a)} to {sta(b)} is outside the path's "
                             f"stations ({sta(s0)} to {sta(s1)})")
        out.append(PathGap(a, b))
    out.sort(key=lambda g: g.start)
    for p, q in zip(out, out[1:]):
        if q.start < p.end + _EPS:
            raise ValueError(f"{where}: {sta(p.start)} to {sta(p.end)} overlaps "
                             f"{sta(q.start)} to {sta(q.end)}")
    return tuple(out)
```

In `parse_path`'s `Path(...)` add `gaps=_path_gaps(pp.get("gaps"), s0, s1),`.

In `stations_extra`, before `return out`:

```python
    for g in p.gaps:
        out += [g.start - PATH_TRANSITION_FT, g.start, g.end, g.end + PATH_TRANSITION_FT]
```

In `approaches`, skip a waived end:

```python
        if p.covers(g.start) and not p.waived(g.start):
            out.append((g.start - p.approach, g.start, g.start))
        if p.covers(g.end) and not p.waived(g.end):
            out.append((g.end, g.end + p.approach, g.end))
```

In `validate`'s separation loop, skip inside a path gap:

```python
        if not p.covers(s) or _on_deck(c, s) or p.in_gap(s, PATH_TRANSITION_FT):
            continue
```

In `bimforge/author/corridor/params.py` `Corridor.path_at`, after the `covers` test:

```python
        from bimforge.author.corridor.path import PATH_TRANSITION_FT
        if p.in_gap(s, PATH_TRANSITION_FT):
            return False
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_corridor_path.py bimforge/author/tests/test_road_corridor_path.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bimforge/author/corridor/path.py bimforge/author/corridor/params.py bimforge/author/tests/test_corridor_path.py
git commit -F - <<'EOF'
road corridor: path gaps, the path's own structures (P.6, part C)

Inside one the section is the road's alone; the path's section is built to
1 ft outside each end. A road structure gap's end inside a path gap waives
the deck-meeting check and the approach rule.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

### Task 14: Checks where the path leaves the road's deck

**Files:**
- Modify: `bimforge/author/corridor/path_checks.py`
- Test: `bimforge/author/tests/test_corridor_path_checks.py`, `bimforge/author/tests/test_road_corridor_path.py`

Inside a path gap the path's profile is the path structure's grade: the grade and crest checks apply to it, and the deck's grade does not, even over a road structure gap. A path gap overlapping a road structure gap is listed (the road's deck carries no path there; its width is the bridge family's). A deck stretch over 5 % is listed with the note "or a separate path structure". The separation inside a path gap is in `outputs.path` (rows noted `path gap`) but takes no barrier row. A strip wall over `max_wall_height_ft` is a structure candidate carrying the path (Task 6); the family's table says so.

Hand values: a 6 % path with a path gap from 13+80 to 15+20 over the road gap 14+00 to 15+00: one `grade>5%` row from 10+00 to 20+00, not split at the bridge; one overlap row 14+00 to 15+00, 100 ft. The road at 6 % with Task 3's narrowing path on the deck's line (the left edge of shoulder 0.49 ft down the plane, 0.49 / √1.0036 = 0.48912 ft below the grade line, and 0.03 more over 1.5 ft: the path 0.51912 ft under the road's grade line): a deck row 14+00 to 15+00, 6.00 against 5.

- [ ] **Step 1: Write the failing tests** (append to `test_corridor_path_checks.py`)

```python
from bimforge.author.alignment import Profile


def test_inside_a_path_gap_over_a_road_gap_the_path_s_grade_is_checked():
    c = corridor(path(profile=grade(99.51, pct=6.0),
                      gaps=[{"from": 1380, "to": 1520, "kind": "structure"}]), gaps=GAP)
    assert rows(pc.grade_rows(c), "grade>5%") == [
        (pytest.approx(1000.0), pytest.approx(2000.0), pytest.approx(6.0), 5.0)]
    assert pc.deck_rows(c) == []
    assert rows(pc.path_gap_rows(c), "path gap over a road structure gap") == [
        (1400.0, 1500.0, 100.0, None)]


def test_a_steep_deck_is_listed_with_its_note():
    road = Profile(grade(100.0, pct=6.0)["curves"])
    c = corridor(path(separation=NARROW, profile=grade(99.48088, pct=6.0)), gaps=GAP,
                 prof=road)
    (row,) = pc.deck_rows(c)
    assert row.check == "deck grade>5% (or a separate path structure)"
    assert (row.start, row.end, row.value) == (pytest.approx(1400.0),
                                               pytest.approx(1500.0),
                                               pytest.approx(6.0))


def test_a_path_gap_takes_no_barrier_row():
    c = corridor(path(separation=[[1000, 10.0], [1450, 10.0], [1500, 3.0], [1550, 3.0],
                                  [1600, 10.0]],
                      gaps=[{"from": 1440, "to": 1610, "kind": "structure"}]))
    assert pc.barrier_rows(c, []) == []
```

Append to `test_road_corridor_path.py`:

```python
def test_a_too_tall_strip_wall_is_a_candidate_carrying_the_path():
    m = build(wall_params(DIP, max_wall_height_ft=5))
    lines = m.tables["structures"].splitlines()
    assert lines[0].endswith(",carries")
    assert [line.split(",")[0] for line in lines[1:]] == ["R"]
    assert lines[1].endswith(",path")
    walls = m.tables["walls"].splitlines()[1:]
    assert any(w.startswith("R,wall-road,strip,") for w in walls)
```

`DIP` is 8.5 ft below the road at its lowest (Task 10): the face from the edge of shoulder (0.49 under the grade line) down to q (8.62 under it) is about 8.1 ft, over 5.

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_corridor_path_checks.py bimforge/author/tests/test_road_corridor_path.py -q`
Expected: FAIL: `grade_rows` splits the stretch at the road gap; `path_gap_rows` does not exist; the deck row's check has no note.

- [ ] **Step 3: Implement** in `bimforge/author/corridor/path_checks.py`:

```python
DECK_CHECK = "deck grade>5% (or a separate path structure)"
```

```python
def on_deck(c, s: float) -> bool:
    """Strictly inside a road structure gap and not in a path gap: the
    path is on the road's deck."""
    return (not c.path.in_gap(s)
            and any(g.kind == "structure" and g.start + _EPS < s < g.end - _EPS
                    for g in c.gaps))
```

In `deck_rows`, the predicate skips the path's gaps:

```python
        for x, y in spans(a, b, lambda s: not p.in_gap(s)
                          and abs(p.road_profile.grade(s)) > MAX_GRADE + 1e-12):
```

In `barrier_rows`' `needs`, add `and not p.in_gap(s)`. Add:

```python
def path_gap_rows(c) -> list:
    """Each path gap over a road structure gap: the road's deck carries no
    path there; its width is the bridge family's."""
    p = c.path
    out = []
    for pg in p.gaps:
        for g in c.gaps:
            if g.kind != "structure":
                continue
            a, b = max(pg.start, g.start), min(pg.end, g.end)
            if b - a > _EPS:
                out.append(CheckRow("path gap over a road structure gap", a, b, b - a,
                                    None, "the deck carries no path there"))
    return out
```

add `+ path_gap_rows(c)` to `checks`' sum, and in `path_csv`, write the path gaps' stations and keep them out of the deck rows:

```python
    for pg in p.gaps:
        for s in c.stations(pg.start, pg.end):
            pz = p.profile.elev(s)
            rows.append((s, f"{s:.2f},{p.side},{p.separation_at(s):.2f},"
                            f"{centre_u(c, s):.2f},,{pz:.3f},,"
                            f"{100.0 * path_grade(c, s):.2f},path gap,,path gap"))
```

and in the deck loop `if not p.covers(s) or p.in_gap(s): continue`.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_corridor_path_checks.py bimforge/author/tests/test_road_corridor_path.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bimforge/author/corridor/path_checks.py bimforge/author/tests/test_corridor_path_checks.py bimforge/author/tests/test_road_corridor_path.py
git commit -F - <<'EOF'
road-corridor: checks where the path takes its own structure (P.6, part C)

A path gap's profile is checked for grade and crests, not the deck's; a
path gap over a road structure gap is listed; a steep deck is listed with
"or a separate path structure"; a too-tall strip wall is a candidate
carrying the path.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

### Task 15: Params for the equestrian tread, and its advisory checks

**Files:**
- Modify: `bimforge/author/corridor/path.py`, `bimforge/author/corridor/path_checks.py`
- Test: `bimforge/author/tests/test_corridor_path.py`, `bimforge/author/tests/test_corridor_path_checks.py`

`path.equestrian` puts an unpaved tread beyond the paved path, away from the road: `width` (8 ft), `buffer` (6 ft, paved edge to tread edge), `clear_ft` (3 ft each side), `cross_slope` (-0.02, away from the road), `courses` (DG; required), `fence` (false), `fence_height_ft` (4.5), `rail_height_ft` (4.5, on walls along the tread). Its figures are guidance (USFS-EDG), so they are defaults and advisories, never errors, except a non-positive dimension and a buffer narrower than `shoulder.width`, which would leave no room for the paved path's graded shoulder (HDM 1003.1(1), a "shall").

Advisory rows (over the path's stations, off the decks): `buffer` under 6 ft (USFS-EDG Ch. 3); `width` under 8 ft (Table 4-2); `clear_ft` under 3 ft (Table 4-1); `cross_slope` outside 2-5 % (Table 4-4); the path's grade over 10 % for more than 200 ft (sustained, Table 4-3; HDM 208.7 gives 10 % at crossings) and over 15 % for more than 200 ft (Table 4-3's pitch).

- [ ] **Step 1: Write the failing tests.** Append to `test_corridor_path.py`:

```python
from bimforge.author.corridor.path import Equestrian

TREAD = {"courses": [{"name": "EQ-DG", "type": "PAVEMENT", "thickness": 0.33}]}


def test_an_equestrian_tread_takes_its_defaults():
    eq = corridor(path(equestrian=TREAD)).path.equestrian
    assert isinstance(eq, Equestrian)
    assert (eq.width, eq.buffer, eq.clear, eq.cross_slope) == (8.0, 6.0, 3.0, -0.02)
    assert (eq.fence, eq.fence_height, eq.rail_height) == (False, 4.5, 4.5)
    assert eq.depth() == pytest.approx(0.33)
    assert corridor().path.equestrian is None


@pytest.mark.parametrize("over, match", [
    ({"width": 0}, r"path\.equestrian\.width: must be positive"),
    ({"buffer": 1.5}, r"path\.equestrian\.buffer: 1\.5 ft is narrower than "
                      r"path\.shoulder\.width \(2 ft\)"),
    ({"clear_ft": 0}, r"path\.equestrian\.clear_ft: must be positive"),
    ({"fence_height_ft": 0}, r"path\.equestrian\.fence_height_ft: must be positive"),
    ({"rail_height_ft": 0}, r"path\.equestrian\.rail_height_ft: must be positive"),
    ({"courses": [{"name": "EQ-DG", "type": "PAVEMENT", "thickness": 0}]},
     r"path\.equestrian\.courses\[0\]\.thickness: must be positive"),
    ({"courses": []}, r"path\.equestrian\.courses: needs at least one course"),
    ({"fence": "yes"}, r"path\.equestrian\.fence: true or false"),
    ({"horses": 2}, r"path\.equestrian: unknown keys \['horses'\]"),
])
def test_bad_equestrian_params_are_refused(over, match):
    with pytest.raises(ValueError, match=match):
        corridor(path(equestrian=dict(TREAD, **over)))
```

Append to `test_corridor_path_checks.py`:

```python
from bimforge.author.tests.test_corridor_path import TREAD


def test_the_equestrian_guidance_is_advisory():
    c = corridor(path(equestrian=dict(TREAD, buffer=4.0, width=6.0, clear_ft=2.0,
                                      cross_slope=-0.01)))
    got = {r.check: (r.value, r.limit) for r in pc.equestrian_rows(c)}
    assert got == {"equestrian buffer<6ft": (4.0, 6.0),
                   "equestrian tread width<8ft": (6.0, 8.0),
                   "equestrian clear<3ft": (2.0, 3.0),
                   "equestrian cross slope outside 2-5%": (pytest.approx(1.0), 2.0)}
    assert pc.equestrian_rows(corridor(path(equestrian=TREAD))) == []


def test_a_steep_tread_is_listed():
    # 0 % to 12+00, a 10 ft curve to 12 %, 12 % to 15+00, a 10 ft curve to
    # 16 %, 16 % to 18+00, a 10 ft curve back to 0. Inside a curve from g1
    # to g2 over L the grade is g1 + (g2 - g1) x / L: over 10 % from
    # 12+00 + 10 x 10/12 = 12+08.33 to 18+00 + 10 x 6/16 = 18+03.75, 595 ft;
    # over 15 % from 15+00 + 10 x 3/4 = 15+07.50 to 18+00 + 10 x 1/16 =
    # 18+00.625, 293 ft: both over 200 ft
    prof = curves([(0, 0, 200), (0, 12, 10), (12, 12, 290), (12, 16, 10),
                   (16, 16, 290), (16, 0, 10), (0, 0, 190)])
    c = corridor(path(profile=prof, equestrian=TREAD))
    got = {r.check: (r.start, r.end, r.value) for r in pc.equestrian_rows(c)}
    assert got["equestrian grade>10% for over 200ft"] == (
        pytest.approx(1208.3333, abs=1e-3), pytest.approx(1803.75, abs=1e-3),
        pytest.approx(16.0))
    assert got["equestrian grade>15% for over 200ft"] == (
        pytest.approx(1507.5, abs=1e-3), pytest.approx(1800.625, abs=1e-3),
        pytest.approx(16.0))
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_corridor_path.py bimforge/author/tests/test_corridor_path_checks.py -q`
Expected: collection ERROR, `ImportError: cannot import name 'Equestrian'`.

- [ ] **Step 3: Implement** in `bimforge/author/corridor/path.py`. Add `"equestrian"` to `KEYS`, and before `Path`:

```python
#: the keys `path.equestrian` takes
EQ_KEYS = {"width", "buffer", "clear_ft", "cross_slope", "courses", "fence",
           "fence_height_ft", "rail_height_ft"}


@dataclass(frozen=True)
class Equestrian:
    """An unpaved equestrian tread beside the paved path, away from the road,
    a buffer between them (USFS-EDG Ch. 3): one shared-use corridor with
    separate treads. Its figures are guidance: defaults and advisories."""
    width: float           # the tread, feet (Table 4-2: 8-12 two-way)
    buffer: float          # paved edge to tread edge, feet
    clear: float           # graded clear each side, feet (Table 4-1)
    cross_slope: float     # negative: down away from the road (Table 4-4)
    courses: tuple         # params.Course: its surfacing, top down
    fence: bool            # an open rail fence on the tread side of the buffer
    fence_height: float
    rail_height: float     # on walls along the tread, feet (54 in)

    def depth(self) -> float:
        return sum(x.thickness for x in self.courses)
```

Add a field to `Path`: `equestrian: object = None            # Equestrian (phase 2)`, and the parser (after `_path_gaps`):

```python
def _equestrian(value, shoulder_width: float):
    if value is None:
        return None
    where = "path.equestrian"
    if not isinstance(value, dict):
        raise ValueError(f"{where}: a mapping ({{width, buffer, clear_ft, courses, "
                         f"...}})")
    unknown = sorted(set(value) - EQ_KEYS)
    if unknown:
        raise ValueError(f"{where}: unknown keys {unknown}")
    buffer = _num(value.get("buffer", 6.0), f"{where}.buffer")
    if buffer < shoulder_width - _EPS:
        raise ValueError(f"{where}.buffer: {buffer:g} ft is narrower than "
                         f"path.shoulder.width ({shoulder_width:g} ft): no room for "
                         f"the paved path's graded shoulder (HDM 1003.1(1))")
    fence = value.get("fence", False)
    if not isinstance(fence, bool):
        raise ValueError(f"{where}.fence: true or false, got {fence!r}")
    return Equestrian(
        width=_num(value.get("width", 8.0), f"{where}.width"), buffer=buffer,
        clear=_num(value.get("clear_ft", 3.0), f"{where}.clear_ft"),
        cross_slope=_num(value.get("cross_slope", -0.02), f"{where}.cross_slope",
                         positive=False),
        courses=tuple(_courses(value.get("courses"), f"{where}.courses")),
        fence=fence,
        fence_height=_num(value.get("fence_height_ft", 4.5), f"{where}.fence_height_ft"),
        rail_height=_num(value.get("rail_height_ft", 4.5), f"{where}.rail_height_ft"))
```

In `parse_path`'s `Path(...)` add `equestrian=_equestrian(pp.get("equestrian"), sw),`.

In `bimforge/author/corridor/path_checks.py` add:

```python
#: USFS-EDG's guidance for the tread
EQ_BUFFER_FT = 6.0                 # Ch. 3
EQ_WIDTH_FT = 8.0                  # Table 4-2, two-way
EQ_CLEAR_FT = 3.0                  # Table 4-1
EQ_CROSS_SLOPE = (0.02, 0.05)      # Table 4-4
EQ_SUSTAINED = 0.10                # Table 4-3; HDM 208.7 at crossings
EQ_PITCH = 0.15                    # Table 4-3
EQ_RUN_FT = 200.0


def equestrian_rows(c) -> list:
    """The tread's advisory rows (USFS-EDG: guidance, never errors), over
    the path's stations."""
    p = c.path
    eq = p.equestrian
    if eq is None:
        return []
    a, b = p.s_start, p.s_end
    out = []
    for check, value, limit, ref in (
            ("equestrian buffer<6ft", eq.buffer, EQ_BUFFER_FT, "USFS-EDG Ch. 3"),
            ("equestrian tread width<8ft", eq.width, EQ_WIDTH_FT, "USFS-EDG Table 4-2"),
            ("equestrian clear<3ft", eq.clear, EQ_CLEAR_FT, "USFS-EDG Table 4-1")):
        if value < limit - _EPS:
            out.append(CheckRow(check, a, b, value, limit, ref))
    cs = abs(eq.cross_slope)
    lo, hi = EQ_CROSS_SLOPE
    if not lo - _EPS <= cs <= hi + _EPS:
        out.append(CheckRow("equestrian cross slope outside 2-5%", a, b, 100.0 * cs,
                            100.0 * (lo if cs < lo else hi), "USFS-EDG Table 4-4"))
    for limit, check in ((EQ_SUSTAINED, "equestrian grade>10% for over 200ft"),
                         (EQ_PITCH, "equestrian grade>15% for over 200ft")):
        for x, y in spans(a, b, lambda s, limit=limit: not on_deck(c, s)
                          and abs(path_grade(c, s)) > limit + 1e-12):
            if y - x > EQ_RUN_FT + _EPS:
                top = max(abs(path_grade(c, s)) for s in _within(x, y))
                out.append(CheckRow(check, x, y, 100.0 * top, 100.0 * limit,
                                    "USFS-EDG Table 4-3; HDM 208.7"))
    return out
```

and add `+ equestrian_rows(c)` to `checks`' sum.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_corridor_path.py bimforge/author/tests/test_corridor_path_checks.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bimforge/author/corridor/path.py bimforge/author/corridor/path_checks.py bimforge/author/tests/test_corridor_path.py bimforge/author/tests/test_corridor_path_checks.py
git commit -F - <<'EOF'
road corridor: params for an equestrian tread beside the path (P.6, part C)

USFS-EDG's figures are defaults and advisories; a non-positive dimension
and a buffer narrower than the path's graded shoulder are errors.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

### Task 16: The tread in the section

**Files:**
- Modify: `bimforge/author/corridor/path.py`, `bimforge/author/families/road_corridor.py` (`ground_reach`)
- Test: `bimforge/author/tests/test_corridor_path.py`

With a tread the path's outer shoulder is replaced, outward from the paved outer edge, by the buffer (`buffer` wide at `shoulder.slope`, earth), the tread (`width` at its `cross_slope`, its courses below, each `thickness / cos θ` deep as the paved courses are), the outer clear strip (`clear_ft` at `shoulder.slope`), then the outer slope. The tread has no profile of its own: its elevation follows from the path's through the cross slopes. The fence stands on the buffer `clear_ft` in from the tread's inner edge. The path's top takes four more points: a step down the tread courses' inner edge, under them, up their outer edge.

Hand values on the level road (the path at 99.51, sep 10, left): the paved outer edge (39, -0.73); the buffer's end and tread's inner edge 6 ft on at -5 %: (45, -1.03), elevation 98.97; the tread's outer edge 8 ft on at -2 %: (53, -1.19); the clear strip's end 3 ft on at -5 %: o (56, -1.34); the fence 3 ft in from the tread's inner edge: (42, -0.88); `EQ-DG` 0.33 deep: (45, -1.36) and (53, -1.52) under it; the outer 2:1 fill to the ground at -5: (63.32, -5). The fill area grows to 286.0119 sf: the right side and the road's left as Task 7 (67.6071 + 57.935), the strip 30.08, q to the step at the paved outer edge as Task 7 (8.8749025 + 0.0413475 + 43.68 + 0.0389475), then across the buffer to (44.99, -1.0295): 24.6376; down to (45, -1.36): 0.0380525; under the tread to (53, -1.52): 28.48; up to (53.01, -1.1905): 0.0364475; across the clear strip to o: 11.1669025; the outer slope: 13.3956.

- [ ] **Step 1: Write the failing tests** (append to `test_corridor_path.py`)

```python
from bimforge.author.corridor.path import TREAD_POINTS, top_points


def test_the_tread_lies_beyond_the_buffer():
    c = corridor(path(equestrian=dict(TREAD, fence=True)))
    sf = surface(c, 1500.0)
    assert sf.tread == (pt((45.0, -1.03)), pt((53.0, -1.19)))
    assert sf.o == pt((56.0, -1.34))
    assert sf.fence == pt((42.0, -0.88))
    assert sf.tread_depth == pytest.approx(0.33)
    assert top_points(c) == TOP_POINTS + TREAD_POINTS
    sec = resolve(c, 1500.0, level(-5.0))
    assert sec.path.tread_courses[0] == pytest.approx(
        [(45.0, -1.03), (53.0, -1.19), (53.0, -1.52), (45.0, -1.36)])
    line = sec.sides["L"].line
    for xy in ((44.99, -1.0295), (45.0, -1.36), (53.0, -1.52), (53.01, -1.1905),
               (56.0, -1.34)):
        assert on(line, xy), xy
    assert line[-1] == pt((63.32, -5.0))
    assert len(line) == side_count(c)
    assert fill_area(c, PlaneGround(95.0)) == pytest.approx(286.0119, abs=1e-6)


def test_the_tread_follows_the_path_s_profile():
    # the path 2 ft lower: the tread 2 ft lower with it (98.97 - 2)
    c = corridor(path(profile=grade(97.51), equestrian=TREAD))
    assert surface(c, 1500.0).tread[0][1] + 100.0 == pytest.approx(96.97)
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_corridor_path.py -q`
Expected: collection ERROR, `ImportError: cannot import name 'TREAD_POINTS'`.

- [ ] **Step 3: Implement** in `bimforge/author/corridor/path.py`. After `TOP_POINTS`:

```python
#: the tread's four more points on the path's top: a step down its courses'
#: inner edge, under them, up their outer edge, onto the clear strip
TREAD_POINTS = 4


def top_points(c) -> int:
    return TOP_POINTS + (TREAD_POINTS if c.path.equestrian is not None else 0)
```

In `side_count` use `top_points(c)` in place of `TOP_POINTS`.

Give `Surface` three fields with defaults (after `cg`):

```python
    tread: tuple | None = None     # the tread's (inner edge, outer edge)
    fence: tuple | None = None     # where the fence stands on the buffer
    tread_depth: float = 0.0       # the tread courses' depth in the plane
```

In `surface`, replace the `return Surface(...)` with:

```python
    eq = p.equestrian
    o = at(w + sw, p.cross_slope * w + p.shoulder_slope * sw)
    tread = fence = None
    tread_depth = 0.0
    if eq is not None:
        zb = p.cross_slope * w + p.shoulder_slope * eq.buffer
        zt = zb + eq.cross_slope * eq.width
        tread = (at(w + eq.buffer, zb), at(w + eq.buffer + eq.width, zt))
        o = at(w + eq.buffer + eq.width + eq.clear, zt + p.shoulder_slope * eq.clear)
        back = max(eq.buffer - eq.clear, 0.0)
        fence = at(w + back, p.cross_slope * w + p.shoulder_slope * back)
        tread_depth = eq.depth() / cos_t
    return Surface(edge=edge, q=at(-inner_sw, p.shoulder_slope * inner_sw),
                   inner=(ui, vi), outer=at(w, p.cross_slope * w), o=o,
                   separation=sep, cos_theta=cos_t, depth=p.depth() / cos_t, cg=cg,
                   tread=tread, fence=fence, tread_depth=tread_depth)
```

Add after `course_rings`:

```python
def tread_rings(eq, sf: Surface) -> dict:
    """{course index: 4-point ring}: the tread's courses under its width,
    each thickness / cos theta deep, as the paved courses are."""
    (ui, vi), (uo, vo) = sf.tread
    out, above = {}, 0.0
    for k, course in enumerate(eq.courses):
        d = course.thickness / sf.cos_theta
        out[k] = [(ui, vi - above), (uo, vo - above), (uo, vo - above - d),
                  (ui, vi - above - d)]
        above += d
    return out
```

Give `PathSection` a field `tread_courses: dict | None = None`, and in `side` build it:

```python
    eq = c.path.equestrian
    return (Side("path", line, guarded, ratio),
            PathSection(mode, ratio, sf, course_rings(c.path, sf),
                        tread_rings(eq, sf) if eq is not None else None))
```

Replace `_top`'s return:

```python
    top = [sf.q, (ui - p.sign * STEP_FT, vi + k), (ui, vi - sf.depth),
           (uo, vo - sf.depth), (uo + p.sign * STEP_FT, vo + k)]
    if sf.tread is None:
        return top + [sf.o]
    (ti, tv), (to, tov) = sf.tread
    return top + [(ti - p.sign * STEP_FT, tv - k), (ti, tv - sf.tread_depth),
                  (to, tov - sf.tread_depth), (to + p.sign * STEP_FT, tov + k), sf.o]
```

(`k` is the shoulder slope over a step: the buffer and clear strip fall at it too; a step back toward the path rises by it.)

In `bimforge/author/families/road_corridor.py` `ground_reach`, the tread reaches farther:

```python
        far = max(v for _s, v in p.separation) + p.width + 2.0 * p.shoulder_width
        if p.equestrian is not None:
            eq = p.equestrian
            far += eq.buffer + eq.width + eq.clear - p.shoulder_width
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_corridor_path.py bimforge/author/tests/test_road_corridor_path.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bimforge/author/corridor/path.py bimforge/author/families/road_corridor.py bimforge/author/tests/test_corridor_path.py
git commit -F - <<'EOF'
road corridor: the equestrian tread in the path's section (P.6, part C)

Buffer, tread and clear strip outward from the paved path, the tread's
elevation following the path's profile through the cross slopes, its
courses normal to the path's grade.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

### Task 17: The tread's road part, courses, fence and rail; the deck it needs

**Files:**
- Modify: `bimforge/author/corridor/dimensions.py`, `bimforge/author/dictionary/bimforge-families.bsdd.json`
- Modify: `bimforge/author/families/road_corridor.py`, `bimforge/author/corridor/path_checks.py`
- Test: `bimforge/author/tests/test_road_corridor_path.py`, `bimforge/author/tests/test_corridor_path_checks.py`

The tread is its own `IfcRoadPart` beside the path's, USERDEFINED `EQUESTRIANTRAIL` (`road-corridor-equestrian-tread`); its courses are `IfcCourse` PAVEMENT with the paved courses' quantities, dimensions and formulas. Its fence is an `IfcRailing` FENCE typed "Path fence" (`road-corridor-path-fence`) over the tread's stations, one per stretch of sections carrying the path (so it stops at road and path gaps), with `BIMForge_Guardrail` and `Length = EndStation - StartStation`. A wall on the path's outer side, which with a tread runs along the tread, carries a 54 in rail typed "Equestrian rail" (`road-corridor-equestrian-rail`); a strip wall keeps the 42 in path rail. On a road deck the whole path, tread included, is on the deck: `path_checks` lists, for each road structure gap the path crosses, the width the deck must carry from the road's edge of shoulder to the tread's outer clear edge, and the 54 in rail the tread side needs; the bridge family sizes the deck from it.

Hand value: Task 9's corridor with the default tread: 1.5 (deck separation) + 12 + 6 + 8 + 3 = 30.5 ft at the bridge 13+00 to 13+50.

The 54 in rail: Task 10's `UP` corridor with a tread and a right footprint of 70 ft: at the path's highest (7.5 ft above the road) the clear strip's end is 56 ft out and about 13.7 ft above the ground, so its 2:1 fill would daylight about 83 ft out, past 70; near the ends it fits.

- [ ] **Step 1: Write the failing tests** (append to `test_road_corridor_path.py`)

```python
TREAD = {"courses": [{"name": "EQ-DG", "type": "PAVEMENT", "thickness": 0.33}],
         "fence": True}


def tread_params(**over):
    p = copy.deepcopy(PARAMS)
    p["path"] = dict(copy.deepcopy(PATH), equestrian=copy.deepcopy(TREAD), **over)
    return p


def test_the_tread_has_its_own_part_courses_and_fence():
    from bimforge.author.corridor import dimensions as dims
    m = build(tread_params())
    treads = [e for e in m.elements if e.name.startswith("EQ-DG tread STA ")]
    assert len(treads) == 6                                 # a band each
    for el in treads:
        assert el.predefined_type == "PAVEMENT"
        assert el.spatial_part.predefined_type == "EQUESTRIANTRAIL"
        assert el.spatial_part.family_class == dims.EQUESTRIAN_TREAD
        assert el.dimensions["Width"] == pytest.approx(8.0)
    fences = sorted(e.name for e in m.elements if e.name.startswith("Path fence "))
    # one each side of the bridge: it stops at the gap
    assert fences == ["Path fence R STA 10+00.00 to 13+00.00",
                      "Path fence R STA 13+50.00 to 16+00.00"]
    fence = m.element(fences[0])
    assert (fence.ifc_class, fence.predefined_type, fence.type_name,
            fence.family_class) == ("IfcRailing", "FENCE", "Path fence", dims.PATH_FENCE)
    assert fence.dimensions["RailHeight"] == pytest.approx(4.5)
    assert fence.standard_qto["Qto_RailingBaseQuantities"]["Length"][2] == dims.LENGTH
    deck = [line for line in m.tables["path_checks"].splitlines()
            if line.startswith("deck width")]
    assert deck == ["deck width to carry (tread rail 4.50 ft),1300.00,1350.00,30.50,,"
                    "USFS-EDG Ch. 5; CSP-TH 18.2.1"]


def test_a_wall_along_the_tread_carries_the_54_in_rail():
    from bimforge.author.corridor import dimensions as dims
    p = wall_params(UP)
    p["path"]["equestrian"] = copy.deepcopy(TREAD)
    p["section"] = dict(copy.deepcopy(SECTION), side_slopes=dict(
        SECTION["side_slopes"], footprint_ft={"R": 70.0}))
    m = build(p)
    rails = {e.type_name: e for e in m.elements if e.ifc_class == "IfcRailing"
             and e.predefined_type == "GUARDRAIL"}
    assert set(rails) == {"Path rail", "Equestrian rail"}   # strip and outer walls
    eq = rails["Equestrian rail"]
    assert (eq.family_class, eq.dimensions["RailHeight"]) == (
        dims.EQUESTRIAN_RAIL, pytest.approx(4.5))
    assert rails["Path rail"].dimensions["RailHeight"] == pytest.approx(3.5)


def test_the_tread_passes_the_schema(tmp_path):
    import ifcopenshell
    import yaml

    from bimforge.author.families.registry import build_from_spec
    from bimforge.author.gate import schema_issues
    (tmp_path / "rc.paycodes.yaml").write_text(
        "rules:\n  - {match: \"(?i)^(HMA|AB) \", group: rc_pave}\n"
        "groups:\n  rc_pave: {measure: GrossVolume}\n"
        "codes:\n  RC-PAVE: {group: rc_pave, measure: GrossVolume, unit: CY,\n"
        "            item_number: \"0001\", description: \"Pavement\"}\n", "utf-8")
    for schema in ("IFC4X3_ADD2", "IFC4"):
        spec = {"family": "road-corridor", "params": tread_params(),
                "paycodes": "./rc.paycodes.yaml", "outputs": {"ifc": f"out/{schema}.ifc"},
                "project": {"name": "Tread fixture", "epsg": 2226,
                            "base": [E0, N0, 300.0], "guid_ns": str(uuid.UUID(int=11)),
                            "schema": schema}}
        if schema == "IFC4X3_ADD2":
            spec["project"]["facility"] = {"kind": "road"}
        path = tmp_path / f"{schema}.spec.yaml"
        path.write_text(yaml.safe_dump(spec, sort_keys=False), "utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            assert build_from_spec(str(path)) == 0, err.getvalue()[-2000:]
        f = ifcopenshell.open(str(tmp_path / "out" / f"{schema}.ifc"))
        assert not schema_issues(f), schema
        import ifcopenshell.util.element as E
        fence = next(r for r in f.by_type("IfcRailing") if r.Name.startswith("Path fence "))
        # IFC4's IfcRailingTypeEnum has no FENCE: it is written USERDEFINED
        # with FENCE as its ObjectType, which get_predefined_type reads
        assert E.get_predefined_type(fence) == "FENCE", schema
    parts = [p for p in ifcopenshell.open(str(tmp_path / "out" / "IFC4X3_ADD2.ifc"))
             .by_type("IfcRoadPart") if p.ObjectType == "EQUESTRIANTRAIL"]
    assert parts
```

Append to `test_corridor_path_checks.py`:

```python
def test_a_deck_lists_the_width_it_must_carry():
    c = corridor(deck_path(equestrian=dict(TREAD, buffer=7.0)), gaps=GAP)
    (row,) = pc.deck_width_rows(c)
    # 1.5 + 12 + 7 + 8 + 3
    assert (row.start, row.end, row.value, row.limit) == (1400.0, 1500.0, 31.5, None)
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_road_corridor_path.py bimforge/author/tests/test_corridor_path_checks.py -q -k "tread or deck_lists or 54_in"`
Expected: FAIL: no `EQ-DG tread` elements; `dims` has no `EQUESTRIAN_TREAD`; no `deck_width_rows`.

- [ ] **Step 3: The class codes and the dictionary.** Append to `bimforge/author/corridor/dimensions.py`:

```python
EQUESTRIAN_TREAD = "road-corridor-equestrian-tread"
EQUESTRIAN_RAIL = "road-corridor-equestrian-rail"
PATH_FENCE = "road-corridor-path-fence"
```

From the worktree root:

```bash
python - <<'PY'
import json
from pathlib import Path
p = Path("bimforge/author/dictionary/bimforge-families.bsdd.json")
d = json.loads(p.read_text("utf-8"))
dims = "A dimension that sizes the element (M.2)."
def prop(code):
    return {"Code": code, "PropertyCode": code, "PropertySet": "BIMForge_Dimensions",
            "IsRequired": True, "Description": dims}
rail_props = [prop(c) for c in ("RailHeight", "StartStation", "EndStation",
                                "StartStationText", "EndStationText")]
d["Classes"] += [
    {"Code": "road-corridor-equestrian-tread", "Name": "Equestrian tread",
     "ClassType": "Class",
     "Definition": "An unpaved equestrian tread beside a shared-use path, away from "
                   "the road, a buffer between them: the IfcRoadPart (USERDEFINED "
                   "EQUESTRIANTRAIL) its surfacing courses, rail and fence belong to.",
     "RelatedIfcEntityNamesList": ["IfcRoadPart"], "CountryOfOrigin": "US",
     "DocumentReference": "USDA Forest Service, Equestrian Design Guidebook for "
                          "Trails, Trailheads, and Campgrounds (2007), Ch. 3 and 4"},
    {"Code": "road-corridor-equestrian-rail", "Name": "Equestrian rail",
     "ClassType": "Class",
     "Definition": "The rail on a wall along an equestrian tread, 54 in by default: "
                   "a run over the wall's stations, its height above the wall's top.",
     "RelatedIfcEntityNamesList": ["IfcRailing", "IfcRailingGUARDRAIL"],
     "CountryOfOrigin": "US",
     "DocumentReference": "USDA Forest Service, Equestrian Design Guidebook (2007), "
                          "Ch. 3 and 5; California State Parks Trails Handbook, Ch. 18",
     "ClassProperties": rail_props},
    {"Code": "road-corridor-path-fence", "Name": "Path fence", "ClassType": "Class",
     "Definition": "An open rail fence along the buffer between a shared-use path and "
                   "its equestrian tread, keeping sight lines open: a run over the "
                   "tread's stations, stopping at gaps.",
     "RelatedIfcEntityNamesList": ["IfcRailing", "IfcRailingFENCE"],
     "CountryOfOrigin": "US",
     "DocumentReference": "Caltrans Highway Design Manual, Index 1003.4",
     "ClassProperties": rail_props},
]
p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", "utf-8")
PY
python -m pytest bimforge/author/tests/test_dictionary.py -q
```

- [ ] **Step 4: The family** (`bimforge/author/families/road_corridor.py`). Add:

```python
def tread_part(segment: dict, r: int) -> dict:
    """Run r's equestrian tread (V1.2 C): its own IfcRoadPart beside the
    path's, USERDEFINED EQUESTRIANTRAIL."""
    return {"name": f"Segment {r} equestrian tread",
            "predefined_type": "EQUESTRIANTRAIL", "usage_type": "LATERAL",
            "parent": segment, "family_class": "road-corridor-equestrian-tread"}


#: the fence's body: a band this deep, on the buffer, up to its height, feet
FENCE_DEPTH_FT = 0.25


def fence_element(c, al, prof, ctx, secs: list, part: dict):
    """The open rail fence over sections `secs` (consecutive, each carrying
    the path) as an IfcRailing FENCE: a FENCE_DEPTH_FT band on the buffer,
    `clear_ft` in from the tread's inner edge, up `fence_height_ft`."""
    from bimforge.author.alignment import sta
    from bimforge.author.corridor import dimensions as dims
    from bimforge.author.corridor.loft import StationLoft
    from bimforge.author.model import Element
    p = c.path
    eq = p.equestrian
    rings = []
    for sec in secs:
        sf = sec.path.surface
        (fu, fv), top = sf.fence, sf.fence[1] + eq.fence_height / sf.cg
        x = fu + p.sign * FENCE_DEPTH_FT
        rings.append([(fu, fv), (x, fv), (x, top), (fu, top)])
    a, b = secs[0].s, secs[-1].s
    name = f"Path fence {p.side} STA {sta(a)} to {sta(b)}"
    loft = StationLoft(name, al, prof, ctx, [sec.s for sec in secs], rings,
                       ifc="IfcRailing", layer=LAYER)
    return Element(
        name, ifc_class="IfcRailing", geometry=[loft], predefined_type="FENCE",
        type_name="Path fence", typed_late=True, family_class=dims.PATH_FENCE,
        material="Steel", layer=LAYER, body="solids", spatial_part=part,
        quantities={"length_ft": b - a, "volume_cf": loft.volume_cf},
        dimensions={"RailHeight": eq.fence_height, **dims.stations(a, b)},
        psets={"BIMForge_Guardrail": {
            "RailHeight": ("length", eq.fence_height),
            "StartStation": ("length", a), "EndStation": ("length", b),
            "StartStationText": sta(a), "EndStationText": sta(b)}},
        standard_qto={"Qto_RailingBaseQuantities": {
            "Length": ("length", b - a, dims.LENGTH)}})
```

Give `add_path_courses` a `tread` keyword and use it for the names, rings and width:

```python
def add_path_courses(model, c, al, prof, ctx, ss: list, bs: list, part: dict,
                     log, tread: bool = False) -> None:
    """... (as before); with `tread` the equestrian tread's courses."""
    ...
    which = c.path.equestrian.courses if tread else c.path.courses
    for k, course in enumerate(which):
        name = f"{course.name} {'tread' if tread else 'path'} STA {sta(b0)} to {sta(b1)}"
        rings = [(sec.path.tread_courses if tread else sec.path.courses)[k] for sec in bs]
        lofts = [StationLoft(name, al, prof, ctx, ss, rings, ifc="IfcCourse", layer=LAYER)]
        ...                                  # the rest of the loop body unchanged
```

In the band loop, after the path's courses:

```python
                    if c.path.equestrian is not None:
                        add_path_courses(model, c, al, prof, ctx, ss[p0:p1 + 1],
                                         bs[p0:p1 + 1], tread_part(segment, r), log,
                                         tread=True)
```

After the path rails (Task 10's loop), the fence, and the 54 in rail in place of the path rail on an outer wall where there is a tread:

```python
    if c.path is not None:
        from bimforge.author.corridor import dimensions as dims
        eq = c.path.equestrian
        for g in path_rail_walls(c):
            r = run_of(runs, g.start)
            segment, _kinds = _parts(r)
            if eq is not None and not g.strip:
                model.add(path_rail_element(g, c, al, prof, ctx, tread_part(segment, r),
                                            eq.rail_height, "Equestrian rail",
                                            dims.EQUESTRIAN_RAIL))
            else:
                model.add(path_rail_element(g, c, al, prof, ctx, path_part(segment, r),
                                            c.path.rail_height, "Path rail",
                                            dims.PATH_RAIL))
        if eq is not None and eq.fence:
            for r, secs in enumerate(runs, start=1):
                segment, _kinds = _parts(r)
                for i0, i1 in path_runs(secs):
                    model.add(fence_element(c, al, prof, ctx, secs[i0:i1 + 1],
                                            tread_part(segment, r)))
```

(this replaces Task 10's `for g in path_rail_walls(c)` loop.)

- [ ] **Step 5: The deck width** (append to `bimforge/author/corridor/path_checks.py`):

```python
def deck_width_rows(c) -> list:
    """For each road structure gap the path crosses on the deck, the width
    the deck must carry: the road's edge of shoulder to the tread's outer
    clear edge, the 54 in rail the tread side needs in the check's name.
    The bridge family sizes the deck from it."""
    p = c.path
    eq = p.equestrian
    if eq is None:
        return []
    out = []
    for g in c.gaps:
        if g.kind != "structure" or p.waived(g.start) or p.waived(g.end):
            continue
        a, b = max(g.start, p.s_start), min(g.end, p.s_end)
        if b - a <= _EPS:
            continue
        width = p.deck_separation + p.width + eq.buffer + eq.width + eq.clear
        out.append(CheckRow(f"deck width to carry (tread rail {eq.rail_height:.2f} ft)",
                            a, b, width, None, "USFS-EDG Ch. 5; CSP-TH 18.2.1"))
    return out
```

and add `+ deck_width_rows(c)` to `checks`' sum.

- [ ] **Step 6: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_road_corridor_path.py bimforge/author/tests/test_corridor_path_checks.py bimforge/author/tests/test_dictionary.py bimforge/author/tests/test_road_corridor_v11.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add bimforge/author/corridor/dimensions.py bimforge/author/dictionary/bimforge-families.bsdd.json bimforge/author/families/road_corridor.py bimforge/author/corridor/path_checks.py bimforge/author/tests/test_road_corridor_path.py bimforge/author/tests/test_corridor_path_checks.py
git commit -F - <<'EOF'
road-corridor: the equestrian tread's part, courses, fence and rail (P.6, part C)

The tread is its own IfcRoadPart (USERDEFINED EQUESTRIANTRAIL); its fence
an IfcRailing FENCE over its stations, stopping at gaps; a wall along it
carries a 54 in Equestrian rail. Each deck the path crosses lists the
width it must carry.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

## Phase 3: own stretches

Phase 3 ends with a path that leaves the road for a corridor of its own and rejoins it: its own alignment and profile (an `IfcAlignment` of its own), its own section, walls and earthwork, handed over where natural ground is left between road and path, its plan footprint never crossing the road's.

### Task 18: `add_alignments` writes a two-PVI profile

**Files:**
- Modify: `bimforge/bim/add_alignment.py`
- Test: `bimforge/bim/tests/test_add_alignment.py`

A short path profile has two PVIs: one grade, start to end. `add_alignments` crashes on it today. With two PVIs there is no interior PVI, so `vlen = [vc] * (len(vp) - 2)` is `[]`, and `vertical = bool(vp and vlen)` is False: the alignment is created with no vertical layout, and `_gate` then reads the profile through `alapi.get_vertical_layout(ifc_al)`, which returns None, and `get_layout_segments(None)` raises `AttributeError: 'NoneType' object has no attribute 'IsNestedBy'`. `layout_vertical_alignment_by_pi_method` takes an empty `lengths` for two points (it writes the one gradient), so the fix is to write the vertical whenever there is a profile.

- [ ] **Step 1: Write the failing test** (append to `bimforge/bim/tests/test_add_alignment.py`)

```python
def test_a_two_pvi_profile_is_written_as_one_grade():
    f = _model()
    # ZIGZAG runs 10+00 to 14+50; 90.0 to 99.0 over 450 ft is 2 %
    block = dict(ZIGZAG, profile={"pvis": [{"station": 1000.0, "elevation": 90.0},
                                           {"station": 1450.0, "elevation": 99.0}],
                                  "vc_length_ft": 0.0})
    (rep,) = add_alignments(f, [block])
    assert rep["vertical"]
    (al,) = f.by_type("IfcAlignment")
    segs = [s.DesignParameters
            for s in alapi.get_layout_segments(alapi.get_vertical_layout(al))]
    grades = [s for s in segs if s.HorizontalLength > 0]
    assert [s.PredefinedType for s in grades] == ["CONSTANTGRADIENT"]
    assert grades[0].StartGradient == pytest.approx(0.02)
    assert grades[0].HorizontalLength == pytest.approx(450.0 * M_PER_FT)
    assert not alignment_issues(f)
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `python -m pytest bimforge/bim/tests/test_add_alignment.py::test_a_two_pvi_profile_is_written_as_one_grade -v`
Expected: FAIL, `AttributeError: 'NoneType' object has no attribute 'IsNestedBy'` (from `_gate`).

- [ ] **Step 3: Fix it** in `bimforge/bim/add_alignment.py` `add_alignments`. Replace

```python
        vertical = bool(vp and vlen)       # as create_by_pi_method decided it
```

with

```python
        # any profile is written: two PVIs (no interior one, so no curve
        # lengths) are one gradient, which the PI method lays out from an
        # empty `lengths`
        vertical = vp is not None
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest bimforge/bim/tests/test_add_alignment.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bimforge/bim/add_alignment.py bimforge/bim/tests/test_add_alignment.py
git commit -F - <<'EOF'
add-alignments: write a two-PVI profile as one gradient (P.6, part C)

With no interior PVI the curve lengths were an empty list, the vertical
layout was skipped, and the gate then read None.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

### Task 19: Params for an own stretch: the hand-over and the rejoin

**Files:**
- Create: `bimforge/author/corridor/own.py`
- Modify: `bimforge/author/corridor/path.py`, `bimforge/author/corridor/params.py`
- Test: `bimforge/author/tests/test_corridor_own.py` (create)

`path.own` lists `{from, to, run, profile, gaps}`. The run starts at the hand-over point: the path's centreline at road station `from`, at that station's separation, heading the road's way; the family derives it (no POB in the spec), so the run may start with a curve. It must end on the path's centreline at road station `to`, heading the road's way, within 0.1 ft and 0.1°. Its profile is on its own stationing from 0+00 (the paved inner edge's elevation, as `path.profile` is) and meets `path.profile` at both ends within 0.01 ft. Own stretches may not overlap each other or a path gap. Between `from` and `to` the road's section is its own, as in a path gap; the beside section turns into it over 0.01 ft (`own.HANDOVER_FT`), so no sliver of the beside path's earthwork lies over the own stretch's.

Hand values. Task 2's road (a tangent north from N 0, E 0 at 10+00), the path on the right 20 ft out: its centre 17 + 20 + 6 = 43 ft right, so the hand-over at 11+00 is N 100, E 43, heading 0°. A bump away from the road and back: 20° right, 40° left, 20° right, each on a 300 ft radius (104.71976, 209.43951 and 104.71976 ft long, 418.87903 in all). It advances 4 R sin 20° = 410.42417 ft along the road and returns to the same offset (2R(1 - cos 20°) = 36.18 ft out at its farthest), so it rejoins at 15+10.424.

- [ ] **Step 1: Write the failing tests** `bimforge/author/tests/test_corridor_own.py`

```python
"""road-corridor V1.2 part C: own stretches, where the path leaves the road
(P.6)."""
import copy

import pytest

from bimforge.author.tests.test_corridor_path import corridor, level, path

#: a bump away from the road and back: 20 deg right, 40 left, 20 right on
#: 300 ft radii; it advances 4 R sin 20 deg = 410.42417 ft along the road
BUMP = [{"kind": "curve", "delta": "20-0-0", "radius": 300.0, "turn": "R",
         "length": 104.71976},
        {"kind": "curve", "delta": "40-0-0", "radius": 300.0, "turn": "L",
         "length": 209.43951},
        {"kind": "curve", "delta": "20-0-0", "radius": 300.0, "turn": "R",
         "length": 104.71976}]
REJOIN = 1510.424


def own_path(run=BUMP, to=REJOIN, elev=99.51, separation=20.0, **over):
    length = sum(x["length"] for x in run)
    prof = {"curves": [{"bvc_station": 0.0, "bvc_elev": elev, "g_in_pct": 0.0,
                        "g_out_pct": 0.0, "length_ft": length,
                        "evc_station": length, "evc_elev": elev}]}
    own = dict({"from": 1100, "to": to, "run": copy.deepcopy(run), "profile": prof},
               **over)
    return path(side="R", separation=[[1000, separation]], own=[own])


def test_the_hand_over_point_and_heading_are_derived():
    (own,) = corridor(own_path()).path.own
    assert (own.index, own.start, own.end) == (1, 1100.0, REJOIN)
    pob = own.alignment.pob
    assert (pob["station"], pob["northing"], pob["easting"], pob["azimuth"]) == (
        0.0, pytest.approx(100.0), pytest.approx(43.0), pytest.approx(0.0))
    assert own.alignment.name == "T path 1"
    assert own.length == pytest.approx(418.87903)
    n, e = own.alignment.end_point
    assert (n, e) == (pytest.approx(100.0 + 410.42417, abs=1e-4), pytest.approx(43.0, abs=1e-4))


def test_along_an_own_stretch_the_section_is_the_road_s():
    c = corridor(own_path())
    assert [c.path_at(s) for s in (1100.0, 1100.01, 1300.0, 1510.414, REJOIN)] == [
        True, False, False, False, True]
    assert {1100.0, 1100.01, 1510.414, REJOIN} <= set(
        round(s, 3) for s in c.stations(1050.0, 1550.0))


def test_a_run_ending_0_2_ft_off_is_refused():
    with pytest.raises(ValueError, match=(
            r"path\.own\[0\]: its run ends at N 510\.42 E 43\.00 heading .* not on the "
            r"path's centreline at 15\+10\.62 \(N 510\.62 E 43\.00.* 0\.20 ft and")):
        corridor(own_path(to=REJOIN + 0.2))


@pytest.mark.parametrize("over, match", [
    ({"run": [{"kind": "tangent", "bearing": "N 1-0-0 E", "length": 410.0}]},
     r"path\.own\[0\]\.run\[0\]: bearing N 1-0-0 E is not the road's heading at "
     r"the hand-over 11\+00\.00"),
    ({"run": []}, r"path\.own\[0\]\.run: the path's own horizontal"),
    ({"from": 2500}, r"path\.own\[0\]: 'to' must be past 'from'"),
    ({"colour": "red"}, r"path\.own\[0\]: unknown keys \['colour'\]"),
])
def test_bad_own_stretches_are_refused(over, match):
    with pytest.raises(ValueError, match=match):
        corridor(own_path(**over))


def test_an_own_profile_must_meet_the_path_s_at_both_ends():
    p = own_path()
    cv = p["own"][0]["profile"]["curves"][0]
    g = 0.02 / cv["length_ft"] * 100.0           # 0.02 ft up over the stretch
    cv.update(g_in_pct=g, g_out_pct=g, evc_elev=99.53)
    with pytest.raises(ValueError, match=(
            r"path\.own\[0\]\.profile: at the rejoin \(4\+18\.88, road 15\+10\.42\) it "
            r"is at 99\.5300 ft and path\.profile at 99\.5100 ft, 0\.0200 ft off")):
        corridor(p)


def test_own_stretches_may_not_overlap_each_other_or_a_path_gap():
    p = own_path()
    p["gaps"] = [{"from": 1500, "to": 1600, "kind": "structure"}]
    with pytest.raises(ValueError, match=r"path\.own: 11\+00\.00 to 15\+10\.42 overlaps "
                                         r"the path gap 15\+00\.00 to 16\+00\.00"):
        corridor(p)
    p = own_path()
    p["own"].append(copy.deepcopy(p["own"][0]))
    with pytest.raises(ValueError, match=r"path\.own: 11\+00\.00 to 15\+10\.42 overlaps "
                                         r"11\+00\.00 to 15\+10\.42"):
        corridor(p)
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_corridor_own.py -q`
Expected: FAIL, `ValueError: path: unknown keys ['own']`.

- [ ] **Step 3: Create** `bimforge/author/corridor/own.py`

```python
"""A shared-use path on its own corridor (P.6, V1.2 part C, phase 3).

`path.own` lists stretches where the path leaves the road and runs on a
corridor of its own in the same build: its own horizontal (`run`, in the
road's form, from the hand-over point derived here), its own profile on its
own stationing from 0+00, its own section (the paved width, courses and
shoulders, one way by `cross_slope`, V1.1's side slopes both sides), walls
and earthwork. It hands over at road station `from` and rejoins at `to`,
each where the beside section leaves natural ground between road and path,
and its plan footprint never crosses the road's, so earthwork is counted
once.

Own section coordinates: u left of the own alignment's travel, v up from
its profile (the paved inner edge's elevation) in the plane square to its
3D tangent. The own alignment is the paved centreline; the inner edge is on
the side the road was (`inward` = -Path.sign), the cross slope falling away
from it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

from bimforge.author.alignment import Alignment, parse_bearing, sta

#: the run rejoins the path's centreline within these
REJOIN_FT = 0.1
REJOIN_DEG = 0.1
#: the beside section turns into the road's own over this at a hand-over
#: and a rejoin, feet: the own stretch's earthwork starts there
HANDOVER_FT = 0.01
#: HDM 1003.1(10): the least radius, and the radius under which a path
#: would need superelevation (its cross slope stays at most 2 %), by speed
MIN_RADIUS_FT = {20: 90.0, 25: 160.0, 30: 260.0}
NO_SUPER_RADIUS_FT = {20: 100.0, 25: 180.0, 30: 320.0}
#: the keys each `path.own` entry takes
KEYS = {"from", "to", "run", "profile", "gaps"}
_EPS = 1e-9


@dataclass(frozen=True)
class Own:
    """One own stretch."""
    index: int                 # from 1, by start station
    start: float               # the hand-over, road station
    end: float                 # the rejoin, road station
    alignment: object          # its own, the paved centreline, from 0+00
    profile: object            # the paved inner edge, own stations
    gaps: tuple = ()           # path.PathGap on own stations: its structures
    walls: tuple = ()          # its automatic walls, own stations (Task 20)

    @property
    def length(self) -> float:
        return self.alignment.s_end - self.alignment.s_start


def _turn(d: float) -> float:
    return (d + 180.0) % 360.0 - 180.0


def centre_point(c, p, s: float) -> tuple:
    """(northing, easting, azimuth): the path's centreline beside the road
    at road station s, heading the road's way."""
    from bimforge.author.corridor.section import grade_edge
    u = grade_edge(c, s, p.side)[0] + p.sign * (p.separation_at(s) + 0.5 * p.width)
    n, e, az = p.alignment.point_az(s)
    ln, le = p.alignment.left_normal(s)
    return n + u * ln, e + u * le, az


def parse_own(value, p, c) -> tuple:
    """The own stretches `value` (`path.own`) describes for path `p` beside
    corridor `c`, by start station; ValueError names the first field that
    is wrong."""
    from bimforge.author.corridor.params import _num
    from bimforge.author.corridor.path import MEET_TOL_FT, _path_gaps, _profile
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("path.own: a list of {from, to, run, profile}")
    out = []
    for i, o in enumerate(value):
        at = f"path.own[{i}]"
        if not isinstance(o, dict):
            raise ValueError(f"{at}: a mapping ({{from, to, run, profile, gaps}})")
        unknown = sorted(set(o) - KEYS)
        if unknown:
            raise ValueError(f"{at}: unknown keys {unknown}")
        a = _num(o.get("from"), f"{at}.from", positive=False)
        b = _num(o.get("to"), f"{at}.to", positive=False)
        if not b > a:
            raise ValueError(f"{at}: 'to' must be past 'from'")
        if not (p.covers(a) and p.covers(b)):
            raise ValueError(f"{at}: {sta(a)} to {sta(b)} is outside the path's "
                             f"stations ({sta(p.s_start)} to {sta(p.s_end)})")
        run = o.get("run")
        if not isinstance(run, list) or not run:
            raise ValueError(f"{at}.run: the path's own horizontal, [tangent or "
                             f"curve, ...] in the road's form, from the hand-over")
        n, e, az = centre_point(c, p, a)
        if run[0].get("kind") == "tangent":
            got = parse_bearing(run[0]["bearing"])
            if abs(_turn(got - az)) > REJOIN_DEG:
                raise ValueError(f"{at}.run[0]: bearing {run[0]['bearing']} is not the "
                                 f"road's heading at the hand-over {sta(a)} "
                                 f"({az:.4f} deg): the run starts the road's way")
        try:
            al = Alignment({"station": 0.0, "northing": n, "easting": e,
                            "azimuth": az}, run, name=f"{p.alignment.name} path {i + 1}")
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{at}.run: {exc}") from None
        en, ee = al.end_point
        eaz = al.point_az(al.s_end)[2]
        tn, te, taz = centre_point(c, p, b)
        miss, turn = math.hypot(en - tn, ee - te), abs(_turn(eaz - taz))
        if miss > REJOIN_FT + _EPS or turn > REJOIN_DEG + _EPS:
            raise ValueError(
                f"{at}: its run ends at N {en:.2f} E {ee:.2f} heading {eaz:.4f} deg, "
                f"not on the path's centreline at {sta(b)} (N {tn:.2f} E {te:.2f}, "
                f"heading {taz:.4f} deg): {miss:.2f} ft and {turn:.4f} deg off (at "
                f"most {REJOIN_FT:g} ft and {REJOIN_DEG:g} deg)")
        prof = _profile(o.get("profile"), f"{at}.profile", 0.0, al.s_end)
        for st, rs, which in ((0.0, a, "hand-over"), (al.s_end, b, "rejoin")):
            got, want = prof.elev(st), p.profile.elev(rs)
            if abs(got - want) > MEET_TOL_FT:
                raise ValueError(
                    f"{at}.profile: at the {which} ({sta(st)}, road {sta(rs)}) it is "
                    f"at {got:.4f} ft and path.profile at {want:.4f} ft, "
                    f"{abs(got - want):.4f} ft off (more than {MEET_TOL_FT:g} ft)")
        out.append(Own(i + 1, a, b, al, prof,
                       _path_gaps(o.get("gaps"), 0.0, al.s_end, f"{at}.gaps")))
    out.sort(key=lambda x: x.start)
    for x, y in zip(out, out[1:]):
        if y.start < x.end + _EPS:
            raise ValueError(f"path.own: {sta(x.start)} to {sta(x.end)} overlaps "
                             f"{sta(y.start)} to {sta(y.end)}")
    for x in out:
        for g in p.gaps:
            if g.start < x.end + _EPS and g.end > x.start - _EPS:
                raise ValueError(
                    f"path.own: {sta(x.start)} to {sta(x.end)} overlaps the path gap "
                    f"{sta(g.start)} to {sta(g.end)}; a path bridge on an own "
                    f"stretch is one of its own gaps (own[].gaps)")
    return tuple(out)
```

- [ ] **Step 4: Wire it into** `bimforge/author/corridor/path.py`: add `"own"` to `KEYS`; add `from dataclasses import dataclass, replace` at the top; add a field and a method to `Path`:

```python
    own: tuple = ()                # own.Own, by start station (phase 3)

    def in_own(self, s: float) -> bool:
        """Strictly inside an own stretch: the path is on its own corridor."""
        return any(o.start + _EPS < s < o.end - _EPS for o in self.own)
```

extend `waived` (a road structure gap's end on an own stretch has no path beside it):

```python
        return (any(g.start - _EPS <= s <= g.end + _EPS for g in self.gaps)
                or any(o.start - _EPS <= s <= o.end + _EPS for o in self.own))
```

in `parse_path`, bind the constructed `Path(...)` to `p` and then:

```python
    if pp.get("own") is not None:
        from bimforge.author.corridor.own import parse_own
        p = replace(p, own=parse_own(pp["own"], p, c))
    return p
```

in `stations_extra`, before `return out`:

```python
    from bimforge.author.corridor.own import HANDOVER_FT
    for o in p.own:
        out += [o.start, o.start + HANDOVER_FT, o.end - HANDOVER_FT, o.end]
```

and in `validate`'s separation loop skip `p.in_own(s)` too:

```python
        if (not p.covers(s) or _on_deck(c, s) or p.in_gap(s, PATH_TRANSITION_FT)
                or p.in_own(s)):
            continue
```

In `bimforge/author/corridor/params.py` `Corridor.path_at`, after the path-gap test:

```python
        if p.in_own(s):
            return False
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_corridor_own.py bimforge/author/tests/test_corridor_path.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add bimforge/author/corridor/own.py bimforge/author/corridor/path.py bimforge/author/corridor/params.py bimforge/author/tests/test_corridor_own.py
git commit -F - <<'EOF'
road corridor: params for a path on its own corridor (P.6, part C)

The run starts at the hand-over point the family derives (the path's
centreline at `from`, heading the road's way) and must rejoin at `to`
within 0.1 ft and 0.1 deg; its profile meets path.profile at both ends.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

### Task 20: The own stretch's section and walls

**Files:**
- Modify: `bimforge/author/corridor/own.py`, `bimforge/author/corridor/walls.py` (`find(need=)`)
- Test: `bimforge/author/tests/test_corridor_own.py`

The own section: the paved width centred on the own alignment, its inner edge on the side the road was, one way at `cross_slope` falling away from it, a graded shoulder each side, the courses under the paved width (`thickness` deep: the section is square to the path's own tangent, cos θ = 1), the tread beyond the buffer as beside the road; then V1.1's side slope on each side (fill 4:1 or 2:1 by the steep rule with no MGS widening, cut with ditch, soil over rock with benches, the footprint), or an automatic wall (`path-fill`, `path-cut`). Its slopes are read on an own `params.Corridor` (`own_corridor`): the road's slopes on own stations, the rock depth read linearly from the hand-over's to the rejoin's, its own gaps as structure gaps, no path and no guardrail. `walls.find` takes a `need` so it can search the own section.

Hand values: the path on the right (inward +1), level, its own profile 99.51 and the ground at 95.0 (4.51 under the own grade line): the paved inner edge (6, 0), outer (-6, -0.24), q (8, -0.10), o (-8, -0.34); the left (inner) 2:1 fill from q to (16.82, -4.51), the right from o to (-16.34, -4.51). The fill area: 19.4481 (left), 8.8749025 + 0.0413475 + 43.68 + 0.0389475 + 8.3973025 (the top), 17.3889 (right): 97.8695 sf.

- [ ] **Step 1: Write the failing tests** (append to `test_corridor_own.py`)

```python
from bimforge.author.corridor import own as own_mod
from bimforge.author.tests.test_corridor_path import BASE, TREAD, pt


def own_of(p):
    c = corridor(p)
    (own,) = c.path.own
    return c, own, own_mod.own_corridor(c, own)


def test_the_own_section_on_level_ground():
    c, own, oc = own_of(own_path())
    sec = own_mod.own_section(c, oc, own, 200.0, level(-4.51))
    sf = sec.surface
    assert sf.inward == 1.0
    assert (sf.inner, sf.outer, sf.q, sf.o) == (pt((6.0, 0.0)), pt((-6.0, -0.24)),
                                                pt((8.0, -0.10)), pt((-8.0, -0.34)))
    assert sec.courses[0] == pytest.approx([(6, 0), (-6, -0.24), (-6, -0.49), (6, -0.25)])
    line = sec.earthwork_line()
    assert line[0] == pt((16.82, -4.51)) and line[-1] == pt((-16.34, -4.51))
    assert len(line) == 2 * sec.count + 6 - 2
    d = [(u, -4.51 - v) for u, v in line]
    fill = -sum(0.5 * (d0 + d1) * abs(u1 - u0) for (u0, d0), (u1, d1) in zip(d, d[1:]))
    assert fill == pytest.approx(97.8695, abs=1e-6)
    assert sec.width() == pytest.approx(16.82 + 16.34)


def test_a_path_on_the_left_keeps_its_inner_edge_on_the_right():
    p = own_path()
    p["side"] = "L"
    p["own"][0]["run"] = [dict(x, turn="L" if x["turn"] == "R" else "R") for x in BUMP]
    c, own, oc = own_of(p)
    sf = own_mod.own_surface(c.path, own, 100.0)
    assert sf.inward == -1.0
    assert (sf.inner, sf.q) == (pt((-6.0, 0.0)), pt((-8.0, -0.10)))


def test_the_tread_goes_with_the_path():
    p = own_path()
    p["equestrian"] = dict(TREAD, fence=True)
    c, own, oc = own_of(p)
    sf = own_mod.own_surface(c.path, own, 100.0)
    # 6 ft of buffer at -5 % past the outer edge (-6, -0.24): (-12, -0.54);
    # 8 ft of tread at -2 %: (-20, -0.70); 3 ft clear at -5 %: o (-23, -0.85);
    # the fence 3 ft in from the tread: (-9, -0.39)
    assert sf.tread == (pt((-12.0, -0.54)), pt((-20.0, -0.70)))
    assert (sf.o, sf.fence) == (pt((-23.0, -0.85)), pt((-9.0, -0.39)))


def test_an_own_slope_past_its_footprint_takes_a_wall():
    # the right (outer) 2:1 from o (-8, -0.34) down to -20.51 is 20.17 ft of
    # fill: it would daylight 40.34 ft on, at (-48.34, -20.51), past a 30 ft
    # footprint; the inner side has none
    section = dict(BASE["section"], side_slopes=dict(BASE["section"]["side_slopes"],
                                                     footprint_ft={"R": 30.0}))
    c = corridor(own_path(), walls="auto", section=section)
    (own,) = c.path.own
    oc = own_mod.own_corridor(c, own)
    own2, oc2 = own_mod.find_walls(c, oc, own, level(-20.51))
    assert {(g.side, g.auto) for g in own2.walls} == {("R", "path-fill")}
    sec = own_mod.own_section(c, oc2, own2, 200.0, level(-20.51))
    assert sec.sides["R"].kind == "wall"
    (row,) = own_mod.wall_rows(c, oc2, own2, level(-20.51))
    assert (row.kind, row.location, row.carries) == ("fill", "own 1", "path")
    assert row.max_height == pytest.approx(20.17)
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_corridor_own.py -q`
Expected: FAIL, `AttributeError: module 'bimforge.author.corridor.own' has no attribute 'own_corridor'`.

- [ ] **Step 3: `walls.find` takes a `need`** (`bimforge/author/corridor/walls.py`). Change its signature and inner function:

```python
def find(c, stations: list, ground_dz, rail=None, need=None) -> list:
    """... (as before). `need(s, side, location)`, when given, says which
    wall a side needs in place of section.needs_wall (an own stretch's
    section, V1.2 C)."""
    out = []
    for side in SIDES:
        for location in ("outer", "strip"):
            if location == "strip" and (c.path is None or c.path.side != side):
                continue

            def ask(s, sd, location=location):
                if need is not None:
                    return need(s, sd, location)
                return needs_wall(c, s, sd, ground_dz,
                                  rail is not None and rail(s, sd), location)

            kinds = [ask(s, side) for s in stations]
            ...                         # as before, with `ask` for `need` in the _reach calls
```

- [ ] **Step 4: Implement** (append to `bimforge/author/corridor/own.py`)

```python
@dataclass(frozen=True)
class OwnSurface:
    """The path's finished surface on an own stretch at an own station:
    path.Surface's fields, in own section coordinates."""
    q: tuple
    inner: tuple
    outer: tuple
    o: tuple
    cos_theta: float
    depth: float
    cg: float
    inward: float                   # +1: the inner edge left of the own alignment
    tread: tuple | None = None
    fence: tuple | None = None
    tread_depth: float = 0.0


def own_surface(p, own, t: float) -> OwnSurface:
    g = own.profile.grade(t)
    cg = 1.0 / math.sqrt(1.0 + g * g)
    inward, w, sw = -p.sign, p.width, p.shoulder_width
    cs, ss = p.cross_slope, p.shoulder_slope

    def at(du, dz):
        """du ft outward from the paved inner edge, dz ft above it."""
        return (inward * (0.5 * w - du), dz / cg)

    o, tread, fence, tread_depth = at(w + sw, cs * w + ss * sw), None, None, 0.0
    eq = p.equestrian
    if eq is not None:
        zb = cs * w + ss * eq.buffer
        zt = zb + eq.cross_slope * eq.width
        tread = (at(w + eq.buffer, zb), at(w + eq.buffer + eq.width, zt))
        o = at(w + eq.buffer + eq.width + eq.clear, zt + ss * eq.clear)
        back = max(eq.buffer - eq.clear, 0.0)
        fence = at(w + back, cs * w + ss * back)
        tread_depth = eq.depth()
    return OwnSurface(q=at(-sw, ss * sw), inner=at(0.0, 0.0), outer=at(w, cs * w),
                      o=o, cos_theta=1.0, depth=p.depth(), cg=cg, inward=inward,
                      tread=tread, fence=fence, tread_depth=tread_depth)


def own_corridor(c, own):
    """The params.Corridor an own stretch's slopes are read and its walls
    found on: the road's slopes on own stations 0 to its length, the rock
    depth read linearly from the hand-over's to the rejoin's, its own gaps
    as structure gaps and its walls, no path, no guardrail."""
    from bimforge.author.corridor.params import Gap
    sl = c.slopes
    if sl.rock is not None:
        sl = replace(sl, rock=replace(sl.rock, depth=(
            (0.0, sl.rock.depth_at(own.start)), (own.length, sl.rock.depth_at(own.end)))))
    gaps = tuple(Gap(g.start, g.end, "structure") for g in own.gaps) + tuple(own.walls)
    return replace(c, s_start=0.0, s_end=own.length, slopes=sl, widths={},
                   superelevation=(), path=None, guard=None,
                   gaps=tuple(sorted(gaps, key=lambda g: (g.start, g.side or ""))))


@dataclass(frozen=True)
class OwnSection:
    """An own stretch's section: earthwork.strip reads its earthwork_line."""
    s: float                        # own station
    surface: OwnSurface
    sides: dict                     # "L"/"R" -> section.Side, out from q or o
    top: list                       # q to o (path._top)
    courses: dict
    tread_courses: dict | None
    count: int                      # each side's points on the earthwork line

    def earthwork_line(self, per_component=1) -> list:
        """Left daylight to right daylight, the same count at every station."""
        from bimforge.author.corridor.section import _samples
        top = self.top if self.surface.inward > 0 else self.top[::-1]
        left = list(reversed(_samples(self.sides["L"].line, self.count)))
        right = _samples(self.sides["R"].line, self.count)
        return left + top[1:-1] + right

    def width(self) -> float:
        line = self.earthwork_line()
        return abs(line[0][0] - line[-1][0])


def _start(sf: OwnSurface, side: str) -> tuple:
    """(the point `side`'s slope starts at, its outward sign): q on the
    inner side, o on the outer."""
    if (side == "L") == (sf.inward > 0):
        return sf.q, sf.inward
    return sf.o, -sf.inward


def own_section(c, oc, own, t: float, ground_dz) -> OwnSection:
    from bimforge.author.corridor.path import _top, course_rings, tread_rings
    from bimforge.author.corridor.section import Side, _slope, side_samples
    p = c.path
    sf = own_surface(p, own, t)
    sides = {}
    for side in ("L", "R"):
        start, sign = _start(sf, side)
        if oc.wall(side, t) is not None:
            sides[side] = Side("wall", [start, start])
        else:
            sides[side] = _slope(oc, t, side, sign, start, ground_dz, widen=False)
    eq = p.equestrian
    return OwnSection(t, sf, sides, _top(c, sf), course_rings(p, sf),
                      tread_rings(eq, sf) if eq is not None else None,
                      side_samples(oc))


def own_needs_wall(c, oc, own, t: float, side: str, ground_dz) -> str | None:
    """The wall `side` of the own section needs at own station t:
    "path-fill" or "path-cut", None where its slope fits."""
    from bimforge.author.corridor.section import NoDaylight, _slope
    if oc.wall(side, t) is not None:
        return None
    start, sign = _start(own_surface(c.path, own, t), side)
    try:
        _slope(oc, t, side, sign, start, ground_dz, widen=False)
    except NoDaylight as exc:
        return f"path-{exc.kind}"
    return None


def own_runs(oc, own) -> list:
    """Each own run's stations (the stretch less its own gaps), with the own
    alignment's and profile's points, densified as the road's are."""
    from bimforge.author.corridor.frame import densify
    from bimforge.author.families.road_corridor import geometry_stations
    al, prof = own.alignment, own.profile
    return [densify(al, prof, oc.stations(a, b, geometry_stations(al, prof, a, b)))
            for a, b in oc.runs()]


def find_walls(c, oc, own, ground_dz) -> tuple:
    """(own, oc) with the automatic walls its section needs (walls.find on
    its stations, own_needs_wall the need)."""
    from bimforge.author.corridor import walls
    found = [g for ss in own_runs(oc, own) for g in walls.find(
        oc, ss, ground_dz,
        need=lambda t, side, loc: (own_needs_wall(c, oc, own, t, side, ground_dz)
                                   if loc == "outer" else None))]
    if not found:
        return own, oc
    oc = oc.with_walls(found)
    own = replace(own, walls=tuple(g for g in oc.gaps if g.auto is not None))
    return own, own_corridor(c, own)


def own_sections(c, oc, own, ground_dz) -> list:
    """Each own run's sections (OwnSection), by station."""
    return [[own_section(c, oc, own, t, ground_dz) for t in ss]
            for ss in own_runs(oc, own)]


def wall_rows(c, oc, own, ground_dz) -> list:
    """walls.WallRow for each of the own stretch's walls: its exposed height
    at q or o, location "own <index>", carrying the path."""
    from bimforge.author.corridor.walls import HEIGHT_STEP_FT, WallRow
    out = []
    for g in own.walls:
        n = max(1, math.ceil((g.end - g.start) / HEIGHT_STEP_FT - _EPS))
        heights, offsets = [], []
        for i in range(n + 1):
            t = g.start + (g.end - g.start) * i / n
            start, _sign = _start(own_surface(c.path, own, t), g.side)
            dz = ground_dz(t, *start)
            heights.append(-dz if g.auto == "path-fill" else dz)
            offsets.append(abs(start[0]))
        kind, top = ("fill" if g.auto == "path-fill" else "cut"), max(heights)
        out.append(WallRow(g.side, kind, g.start, g.end, max(offsets), min(heights),
                           top, kind == "fill" and top > c.max_wall_height + _EPS,
                           location=f"own {own.index}", carries="path"))
    return out
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_corridor_own.py bimforge/author/tests/test_corridor_walls.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add bimforge/author/corridor/own.py bimforge/author/corridor/walls.py bimforge/author/tests/test_corridor_own.py
git commit -F - <<'EOF'
road corridor: an own stretch's section and walls (P.6, part C)

The paved width centred on its own alignment, one way away from where the
road was, V1.1's side slopes both sides from the shoulders (no MGS
widening), automatic walls where they do not fit, the tread with it.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

### Task 21: The hand-over leaves ground between, and the footprints never cross

**Files:**
- Modify: `bimforge/author/corridor/own.py`
- Test: `bimforge/author/tests/test_corridor_own.py`

Each hand-over and rejoin station must be one where the beside section resolves to natural ground between (Task 5's strip), so the road's and the path's footprints are already apart there. Along the stretch, the path's plan footprint (daylight to daylight) must not cross the road's at any station: a polygon test in plan over each footprint's cross-sections and edges, a crossing an error naming the path station and the road station.

Hand values: Task 19's path 20 ft out on the right on level ground at 97.0 (3 ft under the road's grade line): the road's 2:1 fill from its hinge (-17, -1.89) daylights 2.22 ft out; the path's inner fill from q (-35, -0.59) 4.82 ft in, at -30.18: ground between. 10 ft out over ground at 95.0: the path's inner slope from q (-25, -0.59) needs 8.82 ft, more than the 8 ft strip: a slope, not ground.

- [ ] **Step 1: Write the failing tests** (append to `test_corridor_own.py`)

```python
from bimforge.author.corridor.section import resolve


def test_a_hand_over_needs_natural_ground_between():
    c = corridor(own_path())
    (own,) = c.path.own
    secs = [resolve(c, s, level(-3.0)) for s in (own.start, own.end)]
    assert [s.path.strip for s in secs] == ["ground", "ground"]
    own_mod.check_handover(own, *secs)
    c = corridor(own_path(separation=10.0))
    (own,) = c.path.own
    secs = [resolve(c, s, level(-5.0)) for s in (own.start, own.end)]
    with pytest.raises(ValueError, match=(
            r"path\.own\[0\]: the hand-over at 11\+00\.00 does not leave natural "
            r"ground between the road and the path \(the strip is slope\)")):
        own_mod.check_handover(own, *secs)


def test_footprints_that_cross_are_refused():
    # the road: 40 ft wide, stations 0 to 100 along y; the path beside it at
    # x 25 to 45, then swinging in to 15 to 35 at its station 0+40
    road = [(0.0, (-20.0, 0.0), (20.0, 0.0)), (100.0, (-20.0, 100.0), (20.0, 100.0))]
    clear = [(0.0, (25.0, 10.0), (45.0, 10.0)), (40.0, (26.0, 50.0), (46.0, 50.0))]
    own = own_mod.Own(1, 1100.0, 1200.0, None, None)
    own_mod.check_footprints(own, road, clear)
    swing = [(0.0, (25.0, 10.0), (45.0, 10.0)), (40.0, (15.0, 50.0), (35.0, 50.0))]
    with pytest.raises(ValueError, match=(
            r"path\.own\[0\]: its footprint at path station 0\+40\.00 crosses the "
            r"road's at 0\+00\.00")):
        own_mod.check_footprints(own, road, swing)
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_corridor_own.py -q -k "hand_over_needs or footprints"`
Expected: FAIL, `AttributeError: module 'bimforge.author.corridor.own' has no attribute 'check_handover'`.

- [ ] **Step 3: Implement** (append to `bimforge/author/corridor/own.py`)

```python
def check_handover(own, at_from, at_to) -> None:
    """The beside sections (section.Section) at the hand-over and the
    rejoin must leave natural ground between road and path."""
    for sec, which in ((at_from, "hand-over"), (at_to, "rejoin")):
        strip = sec.path.strip if sec.path is not None else "no path"
        if strip != "ground":
            raise ValueError(
                f"path.own[{own.index - 1}]: the {which} at {sta(sec.s)} does not "
                f"leave natural ground between the road and the path (the strip is "
                f"{strip}): the footprints would meet there; move the {which} or "
                f"widen the separation")


def plan(survey, secs) -> list:
    """[(station, left daylight, right daylight)] in plan, (easting,
    northing): `secs`' earthwork lines' ends through `survey(s, u, v)`."""
    out = []
    for sec in secs:
        line = sec.earthwork_line()
        ends = []
        for u, v in (line[0], line[-1]):
            n, e, _z = survey(sec.s, u, v)
            ends.append((e, n))
        out.append((sec.s, ends[0], ends[1]))
    return out


def _side(a, b, p) -> float:
    """p's signed distance from the line a to b, left positive."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length < 1e-12:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    return (dx * (p[1] - a[1]) - dy * (p[0] - a[0])) / length


def _within(a, b, p, tol) -> bool:
    return (min(a[0], b[0]) - tol <= p[0] <= max(a[0], b[0]) + tol
            and min(a[1], b[1]) - tol <= p[1] <= max(a[1], b[1]) + tol)


def _crosses(p, q, a, b, tol: float = 1e-6) -> bool:
    """Whether segments pq and ab cross or touch (to `tol` ft)."""
    d1, d2 = _side(a, b, p), _side(a, b, q)
    d3, d4 = _side(p, q, a), _side(p, q, b)
    if (((d1 > tol and d2 < -tol) or (d1 < -tol and d2 > tol))
            and ((d3 > tol and d4 < -tol) or (d3 < -tol and d4 > tol))):
        return True
    return any(abs(d) <= tol and _within(x, y, z, tol)
               for d, x, y, z in ((d1, a, b, p), (d2, a, b, q),
                                  (d3, p, q, a), (d4, p, q, b)))


def _segments(footprint: list) -> list:
    """[(station, a, b)]: a footprint's cross-sections, then its two edges,
    each edge segment named by its first station."""
    out = [(s, left, right) for s, left, right in footprint]
    for (s, l0, r0), (_s1, l1, r1) in zip(footprint, footprint[1:]):
        out += [(s, l0, l1), (s, r0, r1)]
    return out


def check_footprints(own, road: list, path: list) -> None:
    """The own stretch's plan footprint `path` must not cross the road's
    `road` (each plan()'s rows), so the earthwork is counted once."""
    road_segs = _segments(road)
    for t, p, q in _segments(path):
        for s, a, b in road_segs:
            if _crosses(p, q, a, b):
                raise ValueError(
                    f"path.own[{own.index - 1}]: its footprint at path station "
                    f"{sta(t)} crosses the road's at {sta(s)}: the earthwork would "
                    f"be counted twice; keep the run off the road's footprint")
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_corridor_own.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bimforge/author/corridor/own.py bimforge/author/tests/test_corridor_own.py
git commit -F - <<'EOF'
road corridor: an own stretch hands over on natural ground, its footprint apart (P.6, part C)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

### Task 22: The family builds an own stretch, with its own IfcAlignment

**Files:**
- Modify: `bimforge/author/families/road_corridor.py`
- Test: `bimforge/author/tests/test_road_corridor_path.py`

For each own stretch the family checks the hand-over and the rejoin, finds its walls (`walls: auto`), cuts its sections, checks the footprints against the road's sections on the stretch, then writes, band by band on its own stationing: its path (and tread) courses under the path's road part, its own `Cut path <n> ...` and `Fill path <n> ...` (voiding TERRAIN as the road's cut does), and its rails on its fill walls and its fence. Every solid is lofted along its own alignment and profile, so `emit_alignments` writes its own `IfcAlignment` (horizontal and vertical, aggregated to the project) and the solids sweep along that alignment's `IfcGradientCurve`. Its earthwork is not in the road's mass haul, which is by road station (decision 13).

To share the code, the road's course and earthwork element builders are lifted out of `build` into `add_courses` and `earthwork_elements` (V1.1's output is unchanged: Task 1's pin); the rail and fence builders share `railing_element`.

The test corridor is Task 9's with no bridge, the path 20 ft out (so the hand-overs leave ground between on the plane that falls 2 % to the right), and Task 19's bump from 11+00 to 15+10.424, its own profile one grade (two PVIs) from the path's 300.48002 at 11+00 to 304.58426 at 15+10.424.

- [ ] **Step 1: Write the failing tests** (append to `test_road_corridor_path.py`)

```python
from bimforge.author.tests.test_corridor_own import BUMP, REJOIN


def own_params(run=BUMP, to=REJOIN):
    p = copy.deepcopy(PARAMS)
    p["gaps"] = []
    z0, z1 = 299.48002 + 0.01 * 100.0, 299.48002 + 0.01 * (to - 1000.0)
    length = sum(x["length"] for x in run)
    g = 100.0 * (z1 - z0) / length
    p["path"] = dict(copy.deepcopy(PATH), separation=[[1000, 20.0]], own=[{
        "from": 1100, "to": to, "run": copy.deepcopy(run),
        "profile": {"curves": [{"bvc_station": 0.0, "bvc_elev": z0, "g_in_pct": g,
                                "g_out_pct": g, "length_ft": length,
                                "evc_station": length, "evc_elev": z1}]}}])
    return p


def test_an_own_stretch_builds_its_own_path_and_earthwork():
    m = build(own_params())
    own_courses = [e for e in m.elements if " path 1 STA " in e.name
                   and e.ifc_class == "IfcCourse"]
    assert {e.name for e in own_courses} >= {"PATH-HMA path 1 STA 0+00.00 to 1+00.00",
                                             "PATH-AB path 1 STA 4+00.00 to 4+18.88"}
    for el in own_courses:
        (lf,) = el.geometry
        assert lf.alignment.name == "ML path 1"
        assert el.spatial_part.predefined_type == "SHAREDUSEPATH"
    earth = [e for e in m.elements if e.name.startswith(("Cut path 1 ", "Fill path 1 "))]
    assert earth and all(e.ifc_class.startswith("IfcEarthworks") for e in earth)
    # beside the road the path stops at the hand-over and starts at the rejoin
    for el in path_courses(m):
        if " path 1 " in el.name:
            continue
        (lf,) = el.geometry
        assert lf.s1 <= 1100.0 + 1e-6 or lf.s0 >= REJOIN - 1e-6, el.name
    # the road's mass haul is the road's bands only
    assert all(row.station <= 1600.0 for row in m.mass_haul)


def test_the_own_alignment_is_an_ifcalignment_with_a_two_pvi_profile(tmp_path):
    import ifcopenshell
    import ifcopenshell.api.alignment as alapi
    import yaml

    from bimforge.author.families.registry import build_from_spec
    from bimforge.author.gate import alignment_issues
    (tmp_path / "rc.paycodes.yaml").write_text(
        "rules:\n  - {match: \"(?i)^(HMA|AB) \", group: rc_pave}\n"
        "groups:\n  rc_pave: {measure: GrossVolume}\n"
        "codes:\n  RC-PAVE: {group: rc_pave, measure: GrossVolume, unit: CY,\n"
        "            item_number: \"0001\", description: \"Pavement\"}\n", "utf-8")
    spec = {"family": "road-corridor", "params": own_params(),
            "paycodes": "./rc.paycodes.yaml", "outputs": {"ifc": "out/rc.ifc"},
            "project": {"name": "Own fixture", "epsg": 2226, "base": [E0, N0, 300.0],
                        "guid_ns": str(uuid.UUID(int=11)), "schema": "IFC4X3_ADD2",
                        "facility": {"kind": "road"}}}
    path = tmp_path / "rc.spec.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False), "utf-8")
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        assert build_from_spec(str(path)) == 0, err.getvalue()[-2000:]
    f = ifcopenshell.open(str(tmp_path / "out" / "rc.ifc"))
    assert not alignment_issues(f)
    (own,) = [a for a in f.by_type("IfcAlignment") if a.Name == "ML path 1"]
    segs = [s.DesignParameters
            for s in alapi.get_layout_segments(alapi.get_vertical_layout(own))]
    assert [s.PredefinedType for s in segs if s.HorizontalLength > 0] == ["CONSTANTGRADIENT"]
    assert [r.RelatingObject.is_a() for r in own.Decomposes] == ["IfcProject"]


def test_a_run_that_swings_into_the_road_is_refused():
    toward = [dict(x, turn="L" if x["turn"] == "R" else "R") for x in BUMP]
    with pytest.raises(ValueError, match=r"path\.own\[0\]: its footprint at path "
                                         r"station .* crosses the road's at "):
        build(own_params(run=toward))
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_road_corridor_path.py -q -k own`
Expected: FAIL: no `path 1` elements (the family does not build own stretches yet).

- [ ] **Step 3: Lift the builders out of `build`** (`bimforge/author/families/road_corridor.py`). Add:

```python
def add_courses(model, courses, label: str, al, prof, ctx, ss: list, rings: list,
                part: dict, log) -> None:
    """One IfcCourse per course of `courses` over stations `ss` (V1.2 C),
    `rings[k]` course k's ring at each station, one body, named
    "<course> <label>"; its exact volume and centroid line
    loft.centroid_path's, the Volume formula written where it holds and
    logged where it does not."""
    from bimforge.author.corridor import dimensions as dims
    from bimforge.author.corridor.loft import StationLoft, centroid_path
    from bimforge.author.gate import FORMULA_TOLERANCE
    from bimforge.author.model import Element
    b0, b1 = ss[0], ss[-1]
    for k, course in enumerate(courses):
        name = f"{course.name} {label}"
        lofts = [StationLoft(name, al, prof, ctx, ss, rings[k], ifc="IfcCourse",
                             layer=LAYER)]
        centroid = centroid_path(lofts)
        vol = centroid.volume_cf
        aea = lofts[0].average_end_area_cf
        shape, volume = dims.course_volume(vol, centroid.path_ft,
                                           lofts[0].widths_ft, course.thickness)
        if len(volume) == 2:
            log(f"road-corridor: {name}: Volume formula withheld: PathLength * "
                f"Width * Thickness is not its exact volume within "
                f"{FORMULA_TOLERANCE:g}")
        model.add(Element(
            name, ifc_class="IfcCourse", geometry=lofts,
            predefined_type=course.type, type_name=course.name,
            material=course.name, layer=LAYER, body="solids",
            spatial_part=part, family_class=dims.COURSE,
            dimensions={"Thickness": course.thickness, **shape,
                        "Offset": centroid.offset_ft,
                        "PathLength": centroid.path_ft, **dims.stations(b0, b1)},
            quantities={"length_ft": b1 - b0, "volume_cf": vol},
            standard_qto={"Qto_CourseBaseQuantities": {
                "Length": ("length", b1 - b0, dims.LENGTH),
                "Width": ("length", lofts[0].mean_width_ft),
                "Thickness": ("length", course.thickness),
                "Volume": volume}}))
        model.stated_quantities.append(
            (f"{name}: exact volume vs average end area", vol, aea,
             AEA_TOL * max(aea, 1.0)))


def add_path_courses(model, c, al, prof, ctx, ss: list, bs: list, part: dict,
                     log, tread: bool = False) -> None:
    """The path's courses (with `tread` the tread's) over one stretch of a
    band beside the road: stations `ss`, their sections `bs`."""
    from bimforge.author.alignment import sta
    which = c.path.equestrian.courses if tread else c.path.courses
    rings = [[(sec.path.tread_courses if tread else sec.path.courses)[k] for sec in bs]
             for k in range(len(which))]
    add_courses(model, which,
                f"{'tread' if tread else 'path'} STA {sta(ss[0])} to {sta(ss[-1])}",
                al, prof, ctx, ss, rings, part, log)


def earthwork_elements(c, tag: str, ss: list, bs: list, cut: list, fill: list,
                       cut_d: float, fill_d: float, segment: dict, host) -> list:
    """The band's cut and fill elements (V1, V1.1's dimensions) from
    earthwork.strip's prismatoids, the band's stations `ss` and sections
    `bs`: the road's, or (V1.2 C) an own stretch's, `c` its corridor."""
    from bimforge.author.corridor import dimensions as dims
    from bimforge.author.corridor import earthwork
    from bimforge.author.corridor.params import SIDES
    from bimforge.author.model import Element
    b0, b1 = ss[0], ss[-1]
    width = dims.band_mean(ss, [sec.width() for sec in bs])
    cut_cf = sum(p.volume_cf for p in cut)
    fill_cf = sum(p.volume_cf for p in fill)
    out = []
    if cut:
        cut_dims = {"MaxDepth": cut_d, "MeanDepth": mean_depth(cut_cf, cut),
                    "SlopeRatio": c.slopes.cut_ratio, **dims.stations(b0, b1)}
        if c.slopes.rock is not None:
            cut_dims["RockDepth"] = dims.band_mean(
                ss, [c.slopes.rock.depth_at(s) for s in ss])
        out.append(Element(
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
                "LooseVolume": ("volume", cut_cf * (1.0 + c.swell))}}))
    if fill:
        bank = fill_cf / (1.0 - c.shrink)
        ratios = [sec.sides[side].ratio for sec in bs for side in SIDES
                  if sec.sides[side].kind == "fill"
                  and sec.sides[side].ratio is not None]
        fill_dims = {"MaxDepth": fill_d, "MeanDepth": mean_depth(fill_cf, fill),
                     **dims.stations(b0, b1)}
        if ratios:
            fill_dims["SlopeRatio"] = min(ratios)
        out.append(Element(
            f"Fill {tag}", ifc_class="IfcEarthworksFill",
            geometry=earthwork.merge(f"Fill {tag}", "fill", fill),
            predefined_type="EMBANKMENT", layer=LAYER, body="solids",
            spatial_part=segment, family_class=dims.FILL,
            dimensions=fill_dims,
            quantities={"length_ft": b1 - b0, "volume_cf": fill_cf},
            standard_qto={"Qto_EarthworksFillBaseQuantities": {
                "Length": ("length", b1 - b0, dims.LENGTH),
                "Width": ("length", width),
                "Depth": ("length", fill_d),
                "CompactedVolume": ("volume", fill_cf),
                "LooseVolume": ("volume", bank * (1.0 + c.swell))}}))
    return out
```

`add_path_courses` is now the wrapper above: delete its Task 9 / Task 17 body. The road's own courses keep V1.1's loop as it is (two bodies on the shoulders, `loft.pappus`): Task 1's pin holds them. In `build`'s band loop, replace the earthwork block, from `width = dims.band_mean(...)` to the end of its `if fill:` block, with:

```python
            els = [model.add(el) for el in earthwork_elements(
                c, tag, ss, bs, cut, fill, cut_d, fill_d, segment, host)]
            cut_cf = sum(p.volume_cf for p in cut)
            fill_cf = sum(p.volume_cf for p in fill)
```

(`hauls.append((b0, b1, cut_cf, fill_cf))` and `haul_elements.append(els)` follow as before.)

Lift the rail and fence bodies into one builder, and rewrite `path_rail_element` and `fence_element` on it:

```python
def railing_element(name: str, al, prof, ctx, stations: list, rings: list,
                    predefined: str, type_name: str, family_class: str,
                    height: float, part: dict):
    """An IfcRailing lofted through `rings` at `stations` (V1.2 C: the
    path's rail, the tread's rail and fence), BIMForge_Guardrail its height
    and stations, Length = EndStation - StartStation."""
    from bimforge.author.alignment import sta
    from bimforge.author.corridor import dimensions as dims
    from bimforge.author.corridor.loft import StationLoft
    from bimforge.author.model import Element
    a, b = stations[0], stations[-1]
    loft = StationLoft(name, al, prof, ctx, stations, rings, ifc="IfcRailing",
                       layer=LAYER)
    return Element(
        name, ifc_class="IfcRailing", geometry=[loft], predefined_type=predefined,
        type_name=type_name, typed_late=True, family_class=family_class,
        material="Steel", layer=LAYER, body="solids", spatial_part=part,
        quantities={"length_ft": b - a, "volume_cf": loft.volume_cf},
        dimensions={"RailHeight": height, **dims.stations(a, b)},
        psets={"BIMForge_Guardrail": {
            "RailHeight": ("length", height),
            "StartStation": ("length", a), "EndStation": ("length", b),
            "StartStationText": sta(a), "EndStationText": sta(b)}},
        standard_qto={"Qto_RailingBaseQuantities": {
            "Length": ("length", b - a, dims.LENGTH)}})


def _band(base: tuple, inward: float, height: float, cg: float,
          depth: float) -> list:
    """A rail or fence ring: `depth` from `base` toward `inward`, `height` up."""
    (bu, bv), x = base, base[0] + inward * depth
    top = bv + height / cg
    return [(bu, bv), (x, bv), (x, top), (bu, top)]


def path_rail_element(g, c, al, prof, ctx, part: dict, height: float,
                      type_name: str, family_class: str):
    """The rail on the path's wall gap `g` beside the road (as Task 10)."""
    from bimforge.author.alignment import sta
    from bimforge.author.corridor.frame import densify
    from bimforge.author.corridor.path import surface
    p = c.path
    stations = densify(al, prof, c.stations(
        g.start, g.end, geometry_stations(al, prof, g.start, g.end)))
    rings = []
    for s in stations:
        sf = surface(c, s)
        base, inward = (sf.q, p.sign) if g.strip else (sf.o, -p.sign)
        rings.append(_band(base, inward, height, sf.cg, PATH_RAIL_DEPTH_FT))
    return railing_element(f"{type_name} {g.side} STA {sta(g.start)} to {sta(g.end)}",
                           al, prof, ctx, stations, rings, "GUARDRAIL", type_name,
                           family_class, height, part)


def fence_element(c, al, prof, ctx, stations: list, surfaces: list, part: dict,
                  label: str = ""):
    """The open rail fence over `stations` (their path surfaces `surfaces`,
    beside the road or on an own stretch) as an IfcRailing FENCE on the
    buffer, `clear_ft` in from the tread's inner edge."""
    from bimforge.author.alignment import sta
    from bimforge.author.corridor import dimensions as dims
    p = c.path
    eq = p.equestrian
    rings = [_band(sf.fence, p.sign, eq.fence_height, sf.cg, FENCE_DEPTH_FT)
             for sf in surfaces]
    name = f"Path fence {label}{p.side} STA {sta(stations[0])} to {sta(stations[-1])}"
    return railing_element(name, al, prof, ctx, stations, rings, "FENCE", "Path fence",
                           dims.PATH_FENCE, eq.fence_height, part)
```

and in Task 17's fence loop call `fence_element(c, al, prof, ctx, [x.s for x in secs[i0:i1 + 1]], [x.path.surface for x in secs[i0:i1 + 1]], tread_part(segment, r))`.

- [ ] **Step 4: Build an own stretch.** Add:

```python
def add_own(model, c, o, ground, ctx, log, runs: list, host) -> list:
    """Own stretch `o` (corridor.own.Own) of corridor `c`'s path: its walls,
    sections and footprint check, then band by band on its own stationing
    its courses (and tread's), cut and fill, its rails and fence, all
    lofted along its own alignment and profile (so emit_alignments writes
    its IfcAlignment). Returns its walls' rows."""
    from bimforge.author.alignment import sta
    from bimforge.author.corridor import dimensions as dims
    from bimforge.author.corridor import earthwork
    from bimforge.author.corridor import own as own_mod
    from bimforge.author.corridor.frame import survey_point
    p = c.path
    al, prof = o.alignment, o.profile

    def survey(t, u, v):
        return survey_point(al, prof, t, u, v)

    def dz(t, u, v):
        n, e, z = survey(t, u, v)
        return ground.z(n, e) - z

    oc = own_mod.own_corridor(c, o)
    if c.auto_walls:
        o, oc = own_mod.find_walls(c, oc, o, dz)
    secs_runs = own_mod.own_sections(c, oc, o, dz)
    road = [sec for secs in runs for sec in secs
            if o.start + own_mod.HANDOVER_FT - 1e-6 <= sec.s
            <= o.end - own_mod.HANDOVER_FT + 1e-6]
    own_mod.check_footprints(
        o, own_mod.plan(lambda s, u, v: survey_point(p.alignment, p.road_profile,
                                                     s, u, v), road),
        own_mod.plan(survey, [x for secs in secs_runs for x in secs]))
    r = run_of(runs, o.start)
    segment, _kinds = _parts(r)
    part, tpart = path_part(segment, r), tread_part(segment, r)
    eq = p.equestrian
    for secs in secs_runs:
        stations = [x.s for x in secs]
        for i0, i1 in bands(stations, 0.0, c.band):
            ss, bs = stations[i0:i1 + 1], secs[i0:i1 + 1]
            span = f"STA {sta(ss[0])} to {sta(ss[-1])}"
            add_courses(model, p.courses, f"path {o.index} {span}", al, prof, ctx, ss,
                        [[x.courses[k] for x in bs] for k in range(len(p.courses))],
                        part, log)
            if eq is not None:
                add_courses(model, eq.courses, f"tread {o.index} {span}", al, prof,
                            ctx, ss, [[x.tread_courses[k] for x in bs]
                                      for k in range(len(eq.courses))], tpart, log)
            cut, fill, cut_d, fill_d = [], [], 0.0, 0.0
            for a, b in zip(bs, bs[1:]):
                cp, fp, cd, fd = earthwork.strip(f"path {o.index} {span} {sta(a.s)}",
                                                 a, b, survey, ground.z, ctx)
                cut += cp
                fill += fp
                cut_d, fill_d = max(cut_d, cd), max(fill_d, fd)
            for el in earthwork_elements(oc, f"path {o.index} {span}", ss, bs, cut,
                                         fill, cut_d, fill_d, segment, host):
                model.add(el)
        if eq is not None and eq.fence:
            model.add(fence_element(c, al, prof, ctx, stations,
                                    [x.surface for x in secs], tpart,
                                    label=f"path {o.index} "))
    for g in o.walls:
        if g.auto != "path-fill":
            continue
        ss = [x.s for secs in secs_runs for x in secs
              if g.start - 1e-6 <= x.s <= g.end + 1e-6]
        first = own_mod.own_surface(p, o, ss[0])
        outer = own_mod._start(first, g.side)[0] == first.o
        kind = "Equestrian rail" if eq is not None and outer else "Path rail"
        height = eq.rail_height if kind == "Equestrian rail" else p.rail_height
        rings = []
        for t in ss:
            sf = own_mod.own_surface(p, o, t)
            base, sign = own_mod._start(sf, g.side)
            rings.append(_band(base, -sign, height, sf.cg, PATH_RAIL_DEPTH_FT))
        model.add(railing_element(
            f"{kind} path {o.index} {g.side} STA {sta(g.start)} to {sta(g.end)}",
            al, prof, ctx, ss, rings, "GUARDRAIL", kind,
            dims.EQUESTRIAN_RAIL if kind == "Equestrian rail" else dims.PATH_RAIL,
            height, tpart if kind == "Equestrian rail" else part))
    return own_mod.wall_rows(c, oc, o, dz)
```

A rail stands on its wall's top toward the path: from q or o back toward the paved centre (`-sign`, `sign` the slope's outward sign); with a tread, a wall on the outer side runs along the tread and takes the 54 in rail.

In `build`, after the path's rails and fence (Task 17's block) and before `model.mass_haul = ...`:

```python
    own_rows = []
    if c.path is not None:
        from bimforge.author.corridor import own as own_mod
        for o in c.path.own:
            own_mod.check_handover(
                o, resolve(c, o.start, ground_dz, rail=under_rail(c, rails, o.start)),
                resolve(c, o.end, ground_dz, rail=under_rail(c, rails, o.end)))
            own_rows += add_own(model, c, o, ground, ctx, log, runs, host)
```

and in the walls table, include them:

```python
        rows = auto_walls.rows(c, every, ground_dz)
        model.tables["walls"] = auto_walls.walls_csv(rows + own_rows)
```

(Task 11's `wall_rows` for `path_checks` stays the road's `rows`.)

- [ ] **Step 5: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_road_corridor_path.py bimforge/author/tests/test_road_corridor.py bimforge/author/tests/test_road_corridor_v11.py bimforge/author/tests/test_road_corridor_v1.py -q`
Expected: PASS (V1 and V1.1 unchanged: `earthwork_elements` builds what the inline code did, in the same order).

- [ ] **Step 6: Commit**

```bash
git add bimforge/author/families/road_corridor.py bimforge/author/tests/test_road_corridor_path.py
git commit -F - <<'EOF'
road-corridor: build a path's own stretch, with its own IfcAlignment (P.6, part C)

Its courses, cut, fill, rails and fence are lofted along its own alignment
and profile, so the file carries its IfcAlignment; the hand-overs leave
ground between and its footprint never crosses the road's. The road's
course, earthwork and railing builders are shared.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

### Task 23: Checks on own stretches: radius, grade, crest

**Files:**
- Modify: `bimforge/author/corridor/own.py`, `bimforge/author/corridor/path_checks.py`
- Test: `bimforge/author/tests/test_corridor_own.py`

On an own stretch the grade and crest checks apply on its own profile and stationing, and two more: a horizontal radius under the 1003.1(10) minimum for the design speed (90 / 160 / 260 ft at 20 / 25 / 30 mph, "should"), and under the no-superelevation radius (100 / 180 / 320 ft), since the path's cross slope stays at most 2 %. Own rows carry `own <n> ` in their check and own stations. Beside the road, the path's grade, barrier and approach rows skip the own stretches.

Hand values: a bump on 150 ft radii (52.35988, 104.71976, 52.35988 ft; it advances 4 × 150 × sin 20° = 205.21209 ft, rejoining at 13+05.212): at 20 mph none (150 is over 90 and 100); at 25 mph each of its three curves is under both 160 and 180: six rows; at 30 mph six rows.

- [ ] **Step 1: Write the failing tests** (append to `test_corridor_own.py`)

```python
from bimforge.author.corridor import path_checks as pc

TIGHT = [dict(x, radius=150.0, length=round(x["length"] / 2.0, 5)) for x in BUMP]


def test_a_150_ft_radius_is_listed_at_25_and_30_mph_but_not_20():
    c = corridor(own_path(run=TIGHT, to=1100.0 + 205.212))
    (own,) = c.path.own
    assert own_mod.radius_rows(own, 20) == []
    for speed in (25, 30):
        found = own_mod.radius_rows(own, speed)
        assert len(found) == 6
        assert {r.check for r in found} == {
            f"own 1 radius under the minimum at {speed} mph",
            f"own 1 radius under the no-superelevation radius at {speed} mph"}
        assert {r.limit for r in found} == {own_mod.MIN_RADIUS_FT[speed],
                                           own_mod.NO_SUPER_RADIUS_FT[speed]}
        assert all(r.value == 150.0 for r in found)


def test_the_path_s_checks_take_in_its_own_stretches():
    p = own_path(run=TIGHT, to=1100.0 + 205.212)
    p["design_speed_mph"] = 30
    checks = pc.checks(corridor(p), [], [])
    assert any(r.check == "own 1 radius under the minimum at 30 mph" for r in checks)
    # beside the road the path is level: no grade rows there
    assert not any(r.check.startswith("grade>5%") for r in checks)
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `python -m pytest bimforge/author/tests/test_corridor_own.py -q -k "radius or take_in"`
Expected: FAIL, `AttributeError: module 'bimforge.author.corridor.own' has no attribute 'radius_rows'`.

- [ ] **Step 3: Implement.** Append to `bimforge/author/corridor/own.py`:

```python
def radius_rows(own, speed: int) -> list:
    """The own stretch's curves under 1003.1(10)'s minimum radius for
    `speed`, and under its no-superelevation radius (both "should")."""
    from bimforge.author.corridor.path_checks import CheckRow
    out = []
    for seg in own.alignment.segments:
        if seg["kind"] != "curve":
            continue
        r = seg["radius"]
        for table, what in ((MIN_RADIUS_FT, "radius under the minimum"),
                            (NO_SUPER_RADIUS_FT, "radius under the no-superelevation radius")):
            if r < table[speed] - _EPS:
                out.append(CheckRow(f"own {own.index} {what} at {speed} mph",
                                    seg["s0"], seg["s1"], r, table[speed],
                                    "HDM 1003.1(10)"))
    return out
```

In `bimforge/author/corridor/path_checks.py`, skip the own stretches beside the road: in `grade_rows` pass `lambda s: on_deck(c, s) or p.in_own(s)`; in `barrier_rows`' `needs` add `and not p.in_own(s)`; and add to `checks`, before sorting:

```python
    from bimforge.author.corridor.own import radius_rows
    p = c.path
    for o in p.own:
        label = f"own {o.index} "
        found += profile_grade_rows(o.profile.grade, 0.0, o.length,
                                    lambda t: False, label)
        found += profile_crest_rows(o.profile, 0.0, o.length, p.design_speed, label)
        found += radius_rows(o, p.design_speed)
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest bimforge/author/tests/test_corridor_own.py bimforge/author/tests/test_corridor_path_checks.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bimforge/author/corridor/own.py bimforge/author/corridor/path_checks.py bimforge/author/tests/test_corridor_own.py
git commit -F - <<'EOF'
road-corridor: radius, grade and crest checks on a path's own stretch (P.6, part C)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

### Task 24: Full suite, conformance, changelog, roadmap

**Files:**
- Modify: `CHANGELOG.md` (Unreleased), `ROADMAP.md` (the P.6 row)

- [ ] **Step 1: Run what CI runs** (`.github/workflows/ci.yml`):

```bash
python -m pytest bimforge tests -q
OUT="${TMPDIR:-/tmp}/rc-conformance"
BIMFORGE_CONFORMANCE_OUT="$OUT" python -m pytest bimforge/bim/tests/test_conformance.py -q
python scripts/ifc_inventory.py "$OUT" --check
python scripts/bsi_rules.py --rules ifc-gherkin-rules --python rules-venv/bin/python "$OUT"   # with a checkout
```

Expected: all PASS; the inventory as Task 12 left it (phases 2 and 3 change no shipped example); the bSI rules only the baseline's findings. A failure here is fixed in its task's code, not by re-recording.

- [ ] **Step 2: The changelog.** Under `## Unreleased` > `### Added`, before the V1.1 entry:

```markdown
- **Road corridor part C: a shared-use path on its own profile (P.6).** All
  optional (`params.path`); a spec without it builds as before. Held to the
  Caltrans HDM (08/08/2025), Index 1003.1, and the USFS Equestrian Design
  Guidebook (2007) as guidance:
  - the path is part of one side of the road's section while it is beside
    the road: its paved edge `separation` ft from the road's outer edge of
    shoulder (5 ft at least, narrowing to the deck's 1.5 ft over
    `approach_ft` each side of a bridge, where it must meet the deck within
    0.01 ft), on the profile the spec gives, its courses held normal to its
    own grade; cut, fill and walls are one earthwork over the whole section;
  - between road and path: natural ground where both slopes daylight apart,
    else a slope at `strip.max_ratio` (2:1) or flatter (guarded below a
    higher road where steeper than `fill.ratio`), else a wall at the road's
    hinge (with its barrier) or at the path's shoulder (with the path's
    42 in rail); `walls: auto` places them;
  - `path.gaps`: the path on a structure of its own; `path.equestrian`: an
    unpaved tread beyond a buffer, with an optional open rail fence and a
    54 in rail on walls along it; `path.own`: stretches where the path
    leaves the road on a corridor of its own (its own alignment, profile,
    section, walls and earthwork), handed over where natural ground lies
    between, its footprint never crossing the road's;
  - `outputs.path` lists the path by station; `outputs.path_checks` lists
    every advisory deviation (grade over 5 %, over 2 % sustained, crests
    short of stopping sight distance with the 30 mph downgrade rule,
    separations needing a barrier, approaches under 5 ft, strip walls, steep
    decks, the deck width a tread needs, radii on own stretches, the
    equestrian guidance).
- **For ProjectCommand and BidSheet.ai:** the path is an `IfcRoadPart`
  USERDEFINED, ObjectType `SHAREDUSEPATH` (class
  `road-corridor-shared-use-path`), and a tread one of ObjectType
  `EQUESTRIANTRAIL` (`road-corridor-equestrian-tread`): spatial parts now
  carry a family-dictionary class reference. Their courses are `IfcCourse`
  (class `road-corridor-course`, named `<course> path STA ...`,
  `<course> tread STA ...`, and `<course> path <n> STA ...` on an own
  stretch's stationing). Rails on walls holding the path up are
  `IfcRailing` GUARDRAIL typed "Path rail" (`road-corridor-path-rail`) or
  "Equestrian rail" (`road-corridor-equestrian-rail`); the fence is
  `IfcRailing` FENCE typed "Path fence" (`road-corridor-path-fence`,
  USERDEFINED FENCE on IFC4). Each carries `BIMForge_Guardrail` with
  `RailHeight` and its stations, and `Length = EndStation - StartStation`.
  An own stretch has its own `IfcAlignment` (`<road> path <n>`), and its
  `Cut path <n> ...` / `Fill path <n> ...` are not in the road's mass haul,
  which is by road station. `outputs.walls` gains a `location` column
  (`outer`, `strip`, `own <n>`) and strip walls the kinds `wall-road` and
  `wall-path`; `outputs.structures` gains `carries` (`road` or `path`).
```

and under `### Fixed` (create it under `## Unreleased` if missing):

```markdown
- `est-bim add-alignments` (`bim.add_alignment.add_alignments`) crashed on
  a profile with two PVIs (no vertical curve): it is written as one
  gradient.
```

The shipped example's GlobalIds were re-recorded in Task 12; add to the V1.1 entry's closing paragraph, or as its own line: `The road-corridor example gains a path on the right; its GlobalIds were re-recorded.`

- [ ] **Step 3: The roadmap.** In `ROADMAP.md`'s P.6 row, replace the status cell (the last column) with:

```markdown
V1 (#118) and V1.1 (#122) released in 0.1.132. Part C, a shared-use path beside the road on its own profile (path gaps, an equestrian tread, own stretches with their own alignment), in review. Next: G.9
```

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md ROADMAP.md
git commit -F - <<'EOF'
Changelog and roadmap: road corridor part C, the shared-use path (P.6)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XRnqNpEZgPBXc8juu3tEFR
EOF
```

---

## Errors part C adds

Each names the field and, where there is one, the station:

- `path.side` not L or R; a non-positive `width`, `shoulder.width`, course thickness, `approach_ft`, `deck_separation_ft`, `rail_height_ft` or `strip.max_ratio`; `cross_slope` outside 1-2 %; `shoulder.slope` outside 2-5 % or not falling away; `design_speed_mph` not 20 or 30; `path.stations` off the alignment; a separation row off it; a profile not covering the path's stations or not whole; unknown keys (Task 2);
- a listed wall gap on the path's side over its stations (Task 2);
- separation under 5 ft outside an approach, under `deck_separation_ft` anywhere, not `deck_separation_ft` at a structure gap's end; the path off the deck there (Task 3);
- a path that needs `alignment=` and `profile=` (Task 2);
- a strip that does not fit without `walls: auto` (Task 5);
- a path gap outside the path's stations, overlapping another, or not `structure` (Task 13);
- a non-positive tread dimension, a buffer narrower than `shoulder.width`, a fence that is not true or false (Task 15);
- an own stretch whose run does not start the road's way or does not rejoin; whose profile misses `path.profile`; overlapping another or a path gap (Task 19);
- a hand-over or rejoin without natural ground between; a path footprint crossing the road's (Task 21);
- `outputs.path` or `outputs.path_checks` with no path (Task 11).

## Decisions the plan makes

Where the spec leaves a point open, or the code makes it hard, the plan chooses as follows; the controller should confirm them.

1. **θ is the full 3D angle** (Task 4), as the spec defines it: the section plane's normal against the paved centre's 3D tangent, so it takes in the grade difference, the drift where the separation changes and the twist on a graded curve. The spec then expects the formula withheld on a 500 ft curve at 7 % (V1.1's (κgr)²/2 residual); with this θ that residual cancels and the formula holds (Task 8 tests that it holds). It is withheld, and logged, where the bays' linear blend cannot follow θ: a band holding a separation row's kink (Task 9). The drift is taken into the depth, not the width: the area is the same, the solid 0.4 % deeper and narrower on a 1 in 12 drift.
2. **The path's grade is along its own length**: the profile's rise per road station over (1 - κu) at the paved centre (Task 11). On the example's 1000 ft curve the path 30 ft out is 3 % steeper than its profile per road station.
3. **The path profile is the paved inner edge** on road stations (the spec's "its elevation is the path's profile"); an own stretch's profile is the same edge on its own stations, so "meets path.profile within 0.01 ft" is a direct comparison.
4. **A path brings a guardrail at its defaults** (45 mph, as a steep rule does), so a guarded strip has its MGS; a spec with a path and a structure gap therefore gets bridge rail at the gap's ends, as a `guardrail:` block does.
5. **On an approach the strip is the straight line from hinge to q whatever its slope**: near the deck the path is at the road's finished level while the hinge is the courses' depth below it, so the 2:1 test would ask for a wall in the last few feet of every approach. The inner shoulder narrows to the separation less 0.01 ft, and the rail's widening is held inside the strip.
6. **"Covering the path's stations"**: the profile's first BVC at or before the path's start and its last EVC at or after its end (the road's profiles are written that way; `Profile` extrapolates, so anything else would always "cover").
7. **A two-PVI profile** in `params.profile`'s form is one curve with equal grades (`Profile` divides by the curve length, so a zero-length curve is no answer); `emit_alignments` writes it as one CONSTANTGRADIENT. The `add_alignments` fix (Task 18) is the `pvis` form's.
8. **Strip walls in the walls table** have kind `wall-road` / `wall-path` (the strip's labels), `location` `strip`; both carry the path as structure candidates (the spec's `carries: path`), and a `wall-road` carries the road's barrier. The spec says the structures table needs no new column; it has none today, so `carries` is added.
9. **The path's outer slope takes no MGS widening** (no guardrail on a path); the steep ratio still applies over its height.
10. **The 54 in rail** goes on a wall on the path's outer side when there is a tread (that wall runs along the tread). The spec's "a strip wall where the tread is the higher side" cannot occur beside the road (the tread is beyond the paved path); strip walls keep the 42 in rail.
11. **The 30 mph crest rule** reads both grades beside the curve, either way of travel: a grade over 4 % for more than 500 ft on either side makes it 30 mph.
12. **The equestrian grade rows**: over 10 % for more than 200 ft (sustained) and over 15 % for more than 200 ft (the spec's pitch), both listed.
13. **Own stretches' earthwork is not in the road's mass haul** (it is on its own stationing). The walls table lists their walls with `location` `own <n>` on own stations.
14. **Own stretches' rock depth** is read linearly from the road's depth at the hand-over to its depth at the rejoin; `footprint_ft` applies by side of the own alignment's travel, from its centreline.
15. **The radius table keeps 25 mph** (the spec's test asks for it) though `design_speed_mph` takes only 20 or 30; `radius_rows(own, 25)` is called directly.
16. **"No double count" is tested on hand polygons** (Task 7): the spec's "a path level with the road and 0 ft from it" cannot be built (the inner shoulder and the 0.01 ft steps leave no room, and 0 ft is under the deck separation), so the test sums the section's polygons by hand and shows the natural-ground case is the road's plus the path's.
17. **The example** gets no own stretch, gap or tread (the spec asks for a path on its own profile, an approach and a strip wall); phases 2 and 3 are tested on their own corridors. Its profile is fitted to the deck by hand in Task 12, with a fallback if the build disagrees.
