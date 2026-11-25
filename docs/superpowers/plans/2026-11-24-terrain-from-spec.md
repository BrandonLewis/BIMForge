# Terrain from a spec and a command (G.9) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One top-level `terrain:` block gives any spec's model its existing ground (one IfcGeographicElement TERRAIN from USGS 3DEP), the road corridor calculates against the same ground, the vertical shift comes from `project.vertical_datum`, and `est-bim terrain SPEC` fetches it ahead of the build.

**Architecture:** A new module `bimforge/terrain/spec.py` owns the block (`TerrainSpec`, `parse`, `from_ground`), the datum rule (`terrain_vshift`), the model's footprint (`model_footprint`) and the one fetch-and-attach path (`attach_over`, `add_spec_terrain`). `bimforge/terrain/attach.py` gains `fetch_grid` (split out of `attach_terrain`), `is_terrain` and `to_model_frame` (moved from the corridor). The registry parses the block in `load_spec`, hands it to a family that declares `takes_terrain` (the corridor), and otherwise adds the ground after the family builds. The corridor's `ground:` takes `source: terrain | plane`, and the 0.1.132 `source: 3dep` form is translated in `load_spec`.

**Tech Stack:** Python 3.11+, numpy, pyproj (core dependency), Pillow (the `terrain` extra), ifcopenshell, pytest with monkeypatched transports.

**Design:** `docs/superpowers/specs/2026-11-23-terrain-from-spec-design.md`.

---

## Conventions for every task

- Work in `C:\Users\brand\PycharmProjects\BIMForge\.claude\worktrees\feat-estimate5d-internal-schedule`, branch `feat/g9-terrain-spec`.
- Run tests with `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider <paths>`.
- Most `.py` files are CRLF. Edit them with the Edit tool (it keeps the line endings), or a Python script using `open(..., newline="")`. Never `sed -i` a CRLF file. Check with `file <path>`.
- Lint: `C:/Python314/python.exe -m ruff check <files>` must pass.
- No network in any test. Every transport is replaced: `bimforge.terrain.fetch._urlopen` (DEM and work-unit index), `bimforge.terrain.datum._urlopen` (NCAT), or the fetch functions at `bimforge.terrain.attach`'s names.
- Commit after each task with a message ending in `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Files

| File | Change |
|---|---|
| `bimforge/terrain/provenance.py` | `build_provenance(..., shift_source=None)` writes `VerticalShiftSource` |
| `bimforge/terrain/attach.py` | `fetch_grid` split out; `attach_terrain(..., grid=None, vshift_source=None)`; `is_terrain`; `to_model_frame` moved here |
| `bimforge/terrain/spec.py` | new: `TerrainSpec`, `parse`, `from_ground`, `crs_per_ft`, `base_lonlat`, `terrain_vshift`, `model_footprint`, `attach_over`, `add_spec_terrain`, `report_lines` |
| `bimforge/author/corridor/ground.py` | `from_params(..., terrain=None)`: `source: terrain`, `plane` with or without terrain, `3dep` delegating; `_to_model_frame` replaced by the shared one |
| `bimforge/author/families/road_corridor.py` | reads `params.get("terrain")`; `build.takes_terrain = True`; `_terrain` uses `is_terrain` |
| `bimforge/author/families/registry.py` | `load_spec` parses `terrain:` and translates `ground: {source: 3dep}`; `build_from_spec` passes and adds the terrain and prints notes; new `terrain_from_spec` |
| `bimforge/bim/cli.py` | `est-bim terrain SPEC [--refresh] [--family-path DIR]` |
| Tests | `bimforge/terrain/tests/test_provenance.py`, `test_attach.py`, new `test_spec.py`; `bimforge/author/tests/test_corridor_ground.py`; new `bimforge/author/tests/test_spec_terrain.py`; new `bimforge/bim/tests/test_cli_terrain.py` |
| Docs | `ROADMAP.md` G.9; `README.md`; `CHANGELOG.md` "## Unreleased" |

---

### Task 1: The provenance names where the shift came from

**Files:**
- Modify: `bimforge/terrain/provenance.py` (`build_provenance`)
- Test: `bimforge/terrain/tests/test_provenance.py`

- [ ] **Step 1: Write the failing test** (append to `test_provenance.py`)

```python
def test_the_shift_source_is_written_when_given():
    from bimforge.terrain.provenance import build_provenance
    p = build_provenance("dem", {"crs_epsg": 2226}, {}, 0.71, 3.28, False,
                         shift_source="NOAA NCAT VERTCON 3.0")
    assert p["AppliedVerticalShift"] == -0.71
    assert p["VerticalShiftSource"] == "NOAA NCAT VERTCON 3.0"
    q = build_provenance("dem", {"crs_epsg": 2226}, {}, 0.0, 3.28, False)
    assert "VerticalShiftSource" not in q
```

- [ ] **Step 2: Run it; it fails** with `TypeError: build_provenance() got an unexpected keyword argument 'shift_source'`.

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/terrain/tests/test_provenance.py`

- [ ] **Step 3: Implement.** Change the signature and add one line after `prov.update({...})`:

```python
def build_provenance(source, info, workunit, shift_m, spacing_m, carved,
                     shift_source=None):
```

Add to the docstring: ``shift_source`` names where the shift came from (``"spec vshift_m"``, ``"NAVD88: none"``, ``"NOAA NCAT VERTCON 3.0"``); written as ``VerticalShiftSource`` when given. After the `prov.update({...})` block:

```python
    if shift_source:
        prov["VerticalShiftSource"] = str(shift_source)
```

- [ ] **Step 4: Run it; it passes.** Same command, then the whole `bimforge/terrain/tests` folder: all pass.

- [ ] **Step 5: Commit** `git add bimforge/terrain/provenance.py bimforge/terrain/tests/test_provenance.py` with the message "terrain provenance names its vertical shift's source (G.9)".

---

### Task 2: attach.py: fetch_grid, a supplied grid, is_terrain, to_model_frame

**Files:**
- Modify: `bimforge/terrain/attach.py`
- Modify: `bimforge/author/corridor/ground.py` (use the moved `to_model_frame`)
- Test: `bimforge/terrain/tests/test_attach.py`

- [ ] **Step 1: Write the failing tests** (append to `test_attach.py`; `_model`, `_grid`, `_never`, `FT` are already defined there)

```python
def test_a_supplied_grid_is_not_fetched_and_the_shift_source_is_kept(tmp_path,
                                                                     monkeypatch):
    monkeypatch.setattr(A, "fetch_3dep_dem", _never)
    monkeypatch.setattr(A, "fetch_3dep_lpc", _never)
    monkeypatch.setattr(A, "workunit_meta", _never)
    m = _model()
    el = A.attach_terrain(m, (0.0, 0.0, 4.0, 4.0), crs_epsg=26942,
                          cache_stem=str(tmp_path / "site"), unit_scale=FT,
                          spacing_m=1.0, vshift_m=0.0, vshift_source="NAVD88: none",
                          grid=_grid(), log=lambda *_: None)
    assert el.geometry["provenance"]["VerticalShiftSource"] == "NAVD88: none"


def test_fetch_grid_picks_the_dem_cache_path(tmp_path, monkeypatch):
    seen = {}

    def fake_dem(bbox_m, spacing_m, crs_epsg, cache_path, refresh=False, log=print):
        seen.update(cache=str(cache_path), refresh=refresh)
        return _grid()

    monkeypatch.setattr(A, "fetch_3dep_dem", fake_dem)
    g = A.fetch_grid((0.0, 0.0, 4.0, 4.0), crs_epsg=26942,
                     cache_stem=str(tmp_path / "site"), spacing_m=1.0,
                     refresh=True, log=lambda *_: None)
    assert g.z.shape == (4, 4)
    assert seen == {"cache": str(tmp_path / "site") + "-3DEP-DEM.tif",
                    "refresh": True}


def test_is_terrain_and_to_model_frame():
    from bimforge.author.model import Element
    m = _model()
    el = A.add_terrain(m, "g", [(10.0, 20.0, 30.0)], [], {})
    assert A.is_terrain(el)
    assert not A.is_terrain(Element("w", ifc_class="IfcWall"))
    ctx = ProjectContext(name="t", epsg=26942, base_e=5.0, base_n=8.0,
                         base_h=1.0, guid_ns=uuid.UUID(int=11))
    A.to_model_frame(el, ctx)
    # (northing 10, easting 20, elevation 30) -> x = 20 - 5, y = 10 - 8, z = 29
    assert el.geometry["verts"] == [(15.0, 2.0, 29.0)]
```

Check `Element("w", ifc_class="IfcWall")` constructs (read `Element.__init__` / its dataclass fields in `bimforge/author/model.py`); if `Element` requires more arguments, pass the minimum it requires.

- [ ] **Step 2: Run them; they fail** (`fetch_grid`, `is_terrain`, `to_model_frame` and the `grid`/`vshift_source` arguments do not exist).

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/terrain/tests/test_attach.py`

- [ ] **Step 3: Implement in `bimforge/terrain/attach.py`.**

Split the fetch out of `attach_terrain` into a new function above it (the body is the current `if source == "lpc": ... else: ...` block, unchanged):

```python
def fetch_grid(bbox_m, *, crs_epsg, cache_stem, spacing_m, source="dem",
               refresh=False, log=print):
    """The 3DEP TerrainGrid over ``bbox_m`` (CRS units), fetched or read from
    the cache under ``cache_stem``: the 1 m DEM (``source="dem"``) or the
    lidar point cloud's bare earth (``"lpc"``, its WGS84 discovery bbox
    derived from ``bbox_m`` via pyproj). Elevations are NAVD88 metres."""
    cache_stem = str(cache_stem)
    if source == "lpc":
        try:
            from pyproj import Transformer
        except ImportError as e:
            raise RuntimeError(
                "pyproj is required for the lpc terrain source — "
                'pip install "bimforge[terrain]"') from e
        to_ll = Transformer.from_crs(crs_epsg, 4326, always_xy=True)
        lo1, la1 = to_ll.transform(bbox_m[0], bbox_m[1])
        lo2, la2 = to_ll.transform(bbox_m[2], bbox_m[3])
        wgs = (f"{min(lo1, lo2)},{min(la1, la2)},"
               f"{max(lo1, lo2)},{max(la1, la2)}")
        return fetch_3dep_lpc(bbox_m, spacing_m, crs_epsg, wgs, cache_stem,
                              refresh=refresh, log=log)
    return fetch_3dep_dem(bbox_m, spacing_m, crs_epsg,
                          Path(cache_stem + "-3DEP-DEM.tif"),
                          refresh=refresh, log=log)
```

Change `attach_terrain`'s signature to add `grid=None, vshift_source=None` at the end of the keyword arguments, document both in the docstring (``grid``: an already-fetched TerrainGrid over ``bbox_m``, which is then not fetched again; ``vshift_source``: written into the provenance as ``VerticalShiftSource``), and replace its fetch block with:

```python
    cache_stem = str(cache_stem)
    if grid is None:
        grid = fetch_grid(bbox_m, crs_epsg=crs_epsg, cache_stem=cache_stem,
                          spacing_m=spacing_m, source=source,
                          refresh=refresh, log=log)
```

and its provenance line with:

```python
    prov = build_provenance(source, info, wu, shift, spacing_m, closed,
                            shift_source=vshift_source)
```

Add at the end of the module:

```python
def is_terrain(el) -> bool:
    """The element is the model's existing ground: IfcGeographicElement
    TERRAIN."""
    return (el.ifc_class == "IfcGeographicElement"
            and (el.predefined_type or "").upper() == "TERRAIN")


def to_model_frame(el, ctx) -> None:
    """Move a TERRAIN element's mesh, (northing, easting, elevation) in survey
    feet as `attach_terrain` and `add_terrain` mesh it, into the model frame
    every other body is in (x east, y north, local to the project base)."""
    from bimforge.author.sweep import to_model
    d = el.geometry
    d["verts"] = [to_model(ctx, n, e, z) for n, e, z in d["verts"]]
```

- [ ] **Step 4: Use the shared function in the corridor.** In `bimforge/author/corridor/ground.py` delete `_to_model_frame` and replace its two call sites `_to_model_frame(X, ctx)` with `to_model_frame(X, ctx)`, importing `from bimforge.terrain.attach import to_model_frame` inside each function that calls it (the module imports terrain lazily; keep it lazy).

- [ ] **Step 5: Run the tests; they pass.**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/terrain/tests bimforge/author/tests/test_corridor_ground.py bimforge/author/tests/test_road_corridor.py bimforge/author/tests/test_road_corridor_v1.py`
Expected: all pass (nothing else changed behaviour).

- [ ] **Step 6: Commit** the three files and the test, message "terrain: fetch_grid, a supplied grid, is_terrain and the shared model frame (G.9)".

---

### Task 3: bimforge/terrain/spec.py: the block and the datum rule

**Files:**
- Create: `bimforge/terrain/spec.py`
- Test: `bimforge/terrain/tests/test_spec.py` (new)

- [ ] **Step 1: Write the failing tests** (`bimforge/terrain/tests/test_spec.py`)

```python
"""terrain/spec: the `terrain:` block and the vertical datum rule (G.9).

Offline: NCAT's transport (bimforge.terrain.datum._urlopen) is replaced."""
import json
import uuid

import pytest

from bimforge.author.project import ProjectContext
from bimforge.terrain import datum as D
from bimforge.terrain import spec as S


def ctx(vd=None, epsg=2226):
    return ProjectContext(name="t", epsg=epsg, base_e=6594000.0,
                          base_n=1943000.0, vertical_datum=vd,
                          guid_ns=uuid.UUID(int=3))


def test_parse_defaults_and_resolves_the_cache_against_the_spec(tmp_path):
    ts = S.parse({"cache": "terrain/site"}, tmp_path)
    assert ts == S.TerrainSpec(cache=str(tmp_path / "terrain" / "site"))
    assert (ts.source, ts.margin_ft, ts.spacing_m, ts.vshift_m, ts.refresh) == (
        "dem", 200.0, 1.0, None, False)
    lp = S.parse({"cache": str(tmp_path / "x"), "source": "LPC",
                  "margin_ft": 50, "spacing_m": 2, "vshift_m": 0.7}, None)
    assert (lp.cache, lp.source, lp.margin_ft, lp.spacing_m, lp.vshift_m) == (
        str(tmp_path / "x"), "lpc", 50.0, 2.0, 0.7)


@pytest.mark.parametrize("block, match", [
    ({}, "needs `cache`"),
    ({"cache": "x", "source": "srtm"}, "not dem or lpc"),
    ({"cache": "x", "bbox": [0, 0, 1, 1]}, r"unknown keys \['bbox'\]"),
    ("dem", "must be a mapping"),
])
def test_parse_refuses(block, match):
    with pytest.raises(ValueError, match=match):
        S.parse(block, None)


def test_from_ground_reads_the_0_1_132_form():
    ts = S.from_ground({"source": "3dep", "cache": "c", "spacing_m": 2.0,
                        "margin_ft": 40.0, "vshift_m": 0.5})
    assert ts == S.TerrainSpec(cache="c", spacing_m=2.0, margin_ft=40.0,
                               vshift_m=0.5)


@pytest.mark.parametrize("vd", ["NAVD88", "navd 88", "NAVD-88"])
def test_navd88_needs_no_shift(vd, tmp_path):
    assert S.terrain_vshift(ctx(vd), tmp_path / "s") == (0.0, "NAVD88: none")


def test_an_explicit_shift_wins(tmp_path):
    assert S.terrain_vshift(ctx("NGVD29"), tmp_path / "s", 0.7) == (
        0.7, "spec vshift_m")


def test_ngvd29_asks_ncat_once_then_reads_the_cache(tmp_path, monkeypatch):
    calls = []

    def fake(url, timeout):
        calls.append(url)
        return json.dumps({"srcOrthoht": 0.0, "destOrthoht": 0.713})

    monkeypatch.setattr(D, "_urlopen", fake)
    stem = tmp_path / "sub" / "s"
    got = S.terrain_vshift(ctx("NGVD 29"), stem, log=lambda *_: None)
    assert got == (pytest.approx(0.713), "NOAA NCAT VERTCON 3.0")
    assert len(calls) == 1 and "lat=38." in calls[0]   # the base point's latitude
    again = S.terrain_vshift(ctx("NGVD29"), stem, log=lambda *_: None)
    assert again == got and len(calls) == 1


def test_ngvd29_without_ncat_fails(tmp_path, monkeypatch):
    def down(url, timeout):
        raise OSError("no route")

    monkeypatch.setattr(D, "_urlopen", down)
    with pytest.raises(ValueError, match="give terrain.vshift_m"):
        S.terrain_vshift(ctx("NGVD29"), tmp_path / "s", log=lambda *_: None)


@pytest.mark.parametrize("vd", [None, "MLLW"])
def test_another_datum_fails(vd, tmp_path):
    with pytest.raises(ValueError, match="has no rule; give terrain.vshift_m"):
        S.terrain_vshift(ctx(vd), tmp_path / "s")


def test_crs_per_ft_and_the_base_lonlat():
    assert S.crs_per_ft(ctx()) == pytest.approx(1.0)          # ftUS under ftUS
    lon, lat = S.base_lonlat(ctx())
    assert -123.0 < lon < -120.0 and 37.0 < lat < 40.0      # CA zone 2
```

Check the NCAT query string encodes `lat=` with the value starting `38.` for that base point (CA zone 2, E 6,594,000, N 1,943,000 ftUS is near 38.5 N). If the base point lands elsewhere, change the assertion to the latitude pyproj gives, printed once.

- [ ] **Step 2: Run them; they fail** (`No module named 'bimforge.terrain.spec'`).

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/terrain/tests/test_spec.py`

- [ ] **Step 3: Create `bimforge/terrain/spec.py`** (LF line endings, as a new file)

```python
"""The spec's `terrain:` block (roadmap G.9): a model's one existing ground.

`terrain: {source, cache, margin_ft, spacing_m, vshift_m}` names the USGS
3DEP ground a model carries as its TERRAIN element, for any family. The
road corridor calculates against the same ground (`ground: {source:
terrain}`). 3DEP heights are NAVD88; the shift to the project's datum comes
from `vshift_m`, else from `project.vertical_datum` (`terrain_vshift`).
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

#: the keys a `terrain:` block may hold
KEYS = ("source", "cache", "margin_ft", "spacing_m", "vshift_m")
#: dem: the 3DEP 1 m DEM; lpc: the lidar point cloud's bare earth
SOURCES = ("dem", "lpc")


@dataclass
class TerrainSpec:
    """A parsed `terrain:` block. `cache` is the path stem every download
    hangs off; `spacing_m` is in the CRS's own unit, as `attach_terrain`
    takes it (the name is historical); `refresh` is set only by `est-bim
    terrain --refresh`, never by a spec."""

    cache: str
    source: str = "dem"
    margin_ft: float = 200.0
    spacing_m: float = 1.0
    vshift_m: float | None = None
    refresh: bool = False


def parse(block, base_dir, where: str = "terrain") -> TerrainSpec:
    """The `terrain:` mapping as a TerrainSpec; a relative `cache` resolves
    against `base_dir` (the spec's directory) unless that is None."""
    if not isinstance(block, dict):
        raise ValueError(f"{where}: must be a mapping ({{source, cache, "
                         f"margin_ft, spacing_m, vshift_m}})")
    unknown = sorted(set(block) - set(KEYS))
    if unknown:
        raise ValueError(f"{where}: unknown keys {unknown}; it takes "
                         f"{', '.join(KEYS)}")
    if not block.get("cache"):
        raise ValueError(f"{where}: needs `cache`, the path stem its "
                         f"downloads are kept under")
    source = str(block.get("source", "dem")).lower()
    if source not in SOURCES:
        raise ValueError(f"{where}: source {block['source']!r} is not dem or lpc")
    cache = Path(str(block["cache"]))
    if base_dir is not None and not cache.is_absolute():
        cache = Path(base_dir) / cache
    vs = block.get("vshift_m")
    return TerrainSpec(cache=str(cache), source=source,
                       margin_ft=float(block.get("margin_ft", 200.0)),
                       spacing_m=float(block.get("spacing_m", 1.0)),
                       vshift_m=None if vs is None else float(vs))


def from_ground(gp: dict) -> TerrainSpec:
    """The road corridor's 0.1.132 `ground: {source: 3dep, cache,
    spacing_m, margin_ft, vshift_m}` as the `terrain:` block it now is (its
    cache path as written, as it was read then)."""
    return parse({k: gp[k] for k in ("cache", "spacing_m", "margin_ft",
                                     "vshift_m") if k in gp},
                 None, "ground")


def crs_per_ft(ctx) -> float:
    """CRS units per model foot: 1.0 for a ftUS CRS under a ftUS model."""
    from bimforge.bim.georef import crs_unit
    return ctx.ft_to_m / crs_unit(ctx.epsg)[1]


def base_lonlat(ctx) -> tuple:
    """(lon, lat) of the project base point."""
    from pyproj import Transformer
    c = crs_per_ft(ctx)
    t = Transformer.from_crs(ctx.epsg, 4326, always_xy=True)
    return t.transform(ctx.base_e * c, ctx.base_n * c)


def _datum(name) -> str:
    return re.sub(r"[\s_\-]", "", str(name or "")).upper()


def terrain_vshift(ctx, cache_stem, vshift_m=None, log=print) -> tuple:
    """(shift_m, source): the NAVD88 -> project-datum shift 3DEP heights take,
    in metres (the mesh moves by -shift_m), and where it came from.
    `vshift_m` when given; NAVD88 none; NGVD29 from NOAA NCAT at the base
    point, cached beside the downloads; anything else fails."""
    if vshift_m is not None:
        return float(vshift_m), "spec vshift_m"
    d = _datum(ctx.vertical_datum)
    if d == "NAVD88":
        return 0.0, "NAVD88: none"
    if d == "NGVD29":
        from bimforge.terrain import datum
        path = Path(str(cache_stem) + "-3DEP-vshift.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        lon, lat = base_lonlat(ctx)
        try:
            shift = datum.ncat_vertshift(lat, lon, path, log=log)
        except RuntimeError as e:
            raise ValueError(f"terrain: the NGVD29 shift comes from NOAA NCAT, "
                             f"which did not answer ({e}); give "
                             f"terrain.vshift_m") from None
        source = json.loads(path.read_text()).get("source",
                                                  "NOAA NCAT VERTCON 3.0")
        return float(shift), source
    raise ValueError(f"terrain: 3DEP heights are NAVD88; "
                     f"project.vertical_datum {ctx.vertical_datum!r} has no "
                     f"rule; give terrain.vshift_m")
```

`math` is used by Task 4's additions to this module; if ruff flags it unused at this step, add the import in Task 4 instead.

- [ ] **Step 4: Run them; they pass.** Same command.

- [ ] **Step 5: Commit** `bimforge/terrain/spec.py` and the test, message "terrain: the terrain: block and the vertical datum rule (G.9)".

---

### Task 4: spec.py: the footprint, one fetch-and-attach path, the report

**Files:**
- Modify: `bimforge/terrain/spec.py`
- Test: `bimforge/terrain/tests/test_spec.py`

- [ ] **Step 1: Write the failing tests** (append to `test_spec.py`)

```python
import numpy as np

from bimforge.author.model import Element, StructureModel
from bimforge.terrain import attach as A
from bimforge.terrain.grid import TerrainGrid


def _box(name, x, y, bearing=0.0):
    return Element(name, ifc_class="IfcWall", x_ft=x, y_ft=y, bearing_deg=bearing,
                   geometry={"kind": "prism", "base": [(0, 0), (10, 0), (10, 2), (0, 2)],
                             "z_bot": 0.0, "z_top": 5.0})


def test_the_footprint_is_the_placed_plan_extent_in_survey_feet():
    c = ctx("NAVD88")
    m = StructureModel("f", c)
    m.add(_box("a", 0.0, 0.0))
    m.add(_box("b", 100.0, 50.0, bearing=90.0))   # base turned to run north
    A.add_terrain(m, "old ground", [(0.0, -9999.0, 0.0)], [], {})  # left out
    e0, n0, e1, n1 = S.model_footprint(m, c)
    assert (e0, n0) == pytest.approx((6594000.0, 1943000.0))
    # b's (10, 2) corner turned 90 deg: (-2, 10), placed at (98, 60)
    assert (e1, n1) == pytest.approx((6594000.0 + 100.0, 1943000.0 + 60.0))


def test_a_model_with_no_geometry_has_no_footprint():
    with pytest.raises(ValueError, match="no geometry"):
        S.model_footprint(StructureModel("e", ctx("NAVD88")), ctx("NAVD88"))


def _flat(bbox_m, spacing_m, crs_epsg, cache_path, refresh=False, log=print):
    xmin, ymin, xmax, ymax = bbox_m
    cols = max(2, int(round((xmax - xmin) / spacing_m)))
    rows = max(2, int(round((ymax - ymin) / spacing_m)))
    return TerrainGrid(z=np.full((rows, cols), 30.48), bbox_m=bbox_m,
                       spacing_m=spacing_m, crs_epsg=crs_epsg)


def test_attach_over_adds_one_ground_in_the_model_frame(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "fetch_3dep_dem", _flat)
    monkeypatch.setattr(A, "workunit_meta", lambda *a, **k: {})
    c = ctx("NAVD88")
    m = StructureModel("f", c)
    ts = S.TerrainSpec(cache=str(tmp_path / "t" / "site"), margin_ft=20.0,
                       spacing_m=10.0)
    el, grid, shift = S.attach_over(m, c, ts, (6594000.0, 1943000.0,
                                               6594100.0, 1943060.0),
                                    log=lambda *_: None)
    assert m.elements == [el] and A.is_terrain(el) and shift == 0.0
    xs = [v[0] for v in el.geometry["verts"]]
    ys = [v[1] for v in el.geometry["verts"]]
    zs = {round(v[2], 6) for v in el.geometry["verts"]}
    # pixel centres inside the footprint grown by 20 ft, model frame
    assert -20.0 < min(xs) < 0.0 and 100.0 < max(xs) < 120.0
    assert -20.0 < min(ys) < 0.0 and 60.0 < max(ys) < 80.0
    assert zs == {round(30.48 / c.ft_to_m - c.base_h, 6)}
    prov = el.geometry["provenance"]
    assert prov["VerticalShiftSource"] == "NAVD88: none"
    assert prov["MeshSpacing"] == pytest.approx(10.0)


def test_add_spec_terrain_adds_none_when_the_model_has_ground(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "fetch_3dep_dem", _flat)
    monkeypatch.setattr(A, "workunit_meta", lambda *a, **k: {})
    c = ctx("NAVD88")
    m = StructureModel("f", c)
    m.add(_box("a", 0.0, 0.0))
    ts = S.TerrainSpec(cache=str(tmp_path / "site"), spacing_m=10.0)
    S.add_spec_terrain(m, c, ts, log=lambda *_: None)
    S.add_spec_terrain(m, c, ts, log=lambda *_: None)
    assert sum(A.is_terrain(e) for e in m.elements) == 1


def test_the_report_names_the_footprint_source_and_shift(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "fetch_3dep_dem", _flat)
    monkeypatch.setattr(A, "workunit_meta", lambda *a, **k: {
        "project": "CA_NoCAL_2018", "workunit": "W1", "collect_start": "2018-04-01",
        "collect_end": "2018-05-01", "ql": "QL2"})
    c = ctx("NAVD88")
    m = StructureModel("f", c)
    ts = S.TerrainSpec(cache=str(tmp_path / "site"), spacing_m=10.0)
    (tmp_path / "site-3DEP-DEM.tif").write_bytes(b"x")   # a cache file to list
    el, _g, _s = S.attach_over(m, c, ts, (6594000.0, 1943000.0, 6594100.0,
                                          1943060.0), log=lambda *_: None)
    text = "\n".join(S.report_lines(el, c, ts))
    for want in ("Existing ground - USGS 3DEP DEM", "footprint: E 6,59", "ft",
                 "CA_NoCAL_2018", "2018-04-01 to 2018-05-01", "QL2",
                 "shift 0.000 m (NAVD88: none)", "site-3DEP-DEM.tif"):
        assert want in text, want
```

- [ ] **Step 2: Run them; they fail** (`model_footprint`, `attach_over`, `add_spec_terrain`, `report_lines` missing).

- [ ] **Step 3: Implement** (append to `bimforge/terrain/spec.py`)

```python
def model_footprint(model, ctx) -> tuple:
    """(e_min, n_min, e_max, n_max), survey feet: the plan extent of every
    element's placed geometry, leaving out the ground itself."""
    from bimforge.author.emit_ifc import body_dicts
    from bimforge.author.gate import _solid_points
    from bimforge.terrain.attach import is_terrain
    xs, ys = [], []
    for el in model.elements:
        if is_terrain(el):
            continue
        th = math.radians(el.bearing_deg or 0.0)
        c, s = math.cos(th), math.sin(th)
        for dicts in body_dicts(el):
            for d in dicts:
                k = 1.0 if d.get("units", "ft") == "ft" else 1.0 / 12.0
                for p in _solid_points(d):
                    x, y = p[0] * k, p[1] * k
                    xs.append(x * c - y * s + el.x_ft)
                    ys.append(x * s + y * c + el.y_ft)
    if not xs:
        raise ValueError("terrain: the model has no geometry to put the "
                         "ground around")
    return (min(xs) + ctx.base_e, min(ys) + ctx.base_n,
            max(xs) + ctx.base_e, max(ys) + ctx.base_n)


def attach_over(model, ctx, ts: TerrainSpec, bbox_ft, *, log=print) -> tuple:
    """Fetch `ts`'s ground over `bbox_ft` ((e0, n0, e1, n1), survey feet)
    grown by its margin (at least two cells, so a point at the edge has
    pixel centres around it), and add it to `model` as the TERRAIN element
    in the model frame. Returns (element, grid, shift_m): the corridor
    measures against the grid."""
    from bimforge.bim.georef import crs_unit
    from bimforge.terrain.attach import attach_terrain, fetch_grid, to_model_frame
    if ctx is None or ctx.epsg is None:
        raise ValueError("terrain: needs project.epsg")
    c = crs_per_ft(ctx)
    spacing = ts.spacing_m / crs_unit(ctx.epsg)[1]       # in CRS units
    margin = max(ts.margin_ft, 2.0 * ts.spacing_m / ctx.ft_to_m)
    e0, n0, e1, n1 = bbox_ft
    bbox = ((e0 - margin) * c, (n0 - margin) * c,
            (e1 + margin) * c, (n1 + margin) * c)
    Path(ts.cache).parent.mkdir(parents=True, exist_ok=True)
    shift, source = terrain_vshift(ctx, ts.cache, ts.vshift_m, log=log)
    grid = fetch_grid(bbox, crs_epsg=ctx.epsg, cache_stem=ts.cache,
                      spacing_m=spacing, source=ts.source,
                      refresh=ts.refresh, log=log)
    el = attach_terrain(model, bbox, crs_epsg=ctx.epsg, cache_stem=ts.cache,
                        unit_scale=1.0 / ctx.ft_to_m, plan_scale=1.0 / c,
                        spacing_m=spacing, source=ts.source, vshift_m=shift,
                        vshift_source=source, lonlat=base_lonlat(ctx),
                        grid=grid, log=log)
    to_model_frame(el, ctx)
    return el, grid, shift


def add_spec_terrain(model, ctx, ts: TerrainSpec, *, log=print):
    """The spec's ground over the model's footprint, unless the model already
    has one (a family that calculates against it added it while it built).
    Returns the TERRAIN element."""
    from bimforge.terrain.attach import is_terrain
    for el in model.elements:
        if is_terrain(el):
            return el
    return attach_over(model, ctx, ts, model_footprint(model, ctx), log=log)[0]


def report_lines(el, ctx, ts: TerrainSpec) -> list:
    """What `est-bim terrain` prints for one TERRAIN element."""
    from bimforge.terrain.provenance import spacing_unit
    v = el.geometry["verts"]
    c = crs_per_ft(ctx)
    x0, x1 = min(p[0] for p in v), max(p[0] for p in v)
    y0, y1 = min(p[1] for p in v), max(p[1] for p in v)
    unit = spacing_unit(ctx.epsg) or "CRS units"
    p = el.geometry.get("provenance") or {}
    lines = [
        el.name,
        f"  footprint: E {(x0 + ctx.base_e) * c:,.1f} to {(x1 + ctx.base_e) * c:,.1f}, "
        f"N {(y0 + ctx.base_n) * c:,.1f} to {(y1 + ctx.base_n) * c:,.1f} {unit} "
        f"({x1 - x0:,.0f} x {y1 - y0:,.0f} ft)",
        f"  cells: {len(v):,} points at {p.get('MeshSpacing', ts.spacing_m):g} "
        f"{p.get('MeshSpacingUnit', unit)}",
        f"  source: {p.get('Source', '')}",
    ]
    if p.get("SourceProject"):
        lines.append(f"  project: {p['SourceProject']}")
    if p.get("AcquisitionStart") or p.get("AcquisitionEnd"):
        lines.append(f"  acquired: {p.get('AcquisitionStart', '')} to "
                     f"{p.get('AcquisitionEnd', '')}")
    if p.get("QualityLevel"):
        lines.append(f"  quality level: {p['QualityLevel']}")
    lines.append(f"  shift {-float(p.get('AppliedVerticalShift', 0.0)):.3f} m "
                 f"({p.get('VerticalShiftSource', '')})")
    stem = Path(ts.cache)
    for f in sorted(stem.parent.glob(stem.name + "-3DEP-*")):
        lines.append(f"  cache: {f}")
    return lines
```

`AppliedVerticalShift` is written negated (`-shift_m`), so the report negates it back. Using `gate._solid_points` (one leading underscore) from another package is deliberate: it is the one walk over every body kind; do not copy it.

- [ ] **Step 4: Run them; they pass.** Then `bimforge/terrain/tests` in full: all pass.

- [ ] **Step 5: Commit**, message "terrain: the model's footprint, one fetch-and-attach path and the report (G.9)".

---

### Task 5: The registry: parse the block, translate the 0.1.132 ground, add the terrain

**Files:**
- Modify: `bimforge/author/families/registry.py` (`load_spec`, `build_from_spec`, new `terrain_from_spec`)
- Modify: `bimforge/author/families/road_corridor.py` (one line: `build.takes_terrain = True`; Task 6 makes it read the block)
- Test: `bimforge/author/tests/test_spec_terrain.py` (new)

- [ ] **Step 1: Write the failing tests** (`bimforge/author/tests/test_spec_terrain.py`)

```python
"""A spec's terrain: block (G.9): parsed, translated, added once.

Offline: 3DEP's transport is replaced; the DEM is a flat float32 TIFF."""
import io
import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from bimforge.author.families import registry as R
from bimforge.terrain import fetch as F

EX = Path(R.__file__).resolve().parents[1] / "examples"


def tiff(rows=40, cols=40, z_m=30.48):
    Image = pytest.importorskip("PIL.Image")
    buf = io.BytesIO()
    Image.fromarray(np.full((rows, cols), z_m, dtype="float32"), mode="F").save(
        buf, format="TIFF")
    return buf.getvalue()


class _Resp:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data


def offline(monkeypatch, calls=None):
    """3DEP answered locally: the DEM a flat 30.48 m, the work-unit index one
    feature."""
    def fake(url, timeout):
        if calls is not None:
            calls.append(url)
        if "exportImage" in url:
            return _Resp(tiff())
        return _Resp(json.dumps({"features": [{"attributes": {
            "project": "CA_Test", "workunit": "W1", "collect_start": 0,
            "collect_end": 0, "ql": "QL2"}}]}).encode())
    monkeypatch.setattr(F, "_urlopen", fake)


def b3_spec(tmp_path, terrain=None, vertical_datum="NAVD88", **extra):
    s = yaml.safe_load((EX / "caltrans-b3-retaining-wall.spec.yaml").read_text())
    s["params"]["tables_file"] = str(EX / "caltrans-b3-tables.example.yaml")
    s["paycodes"] = str(EX / "caltrans-b3-retaining-wall.paycodes.yaml")
    s["outputs"] = {"ifc": str(tmp_path / "out" / "b3.ifc")}
    s["project"]["vertical_datum"] = vertical_datum
    if terrain is not None:
        s["terrain"] = terrain
    s.update(extra)
    p = tmp_path / "b3.spec.yaml"
    p.write_text(yaml.safe_dump(s), encoding="utf-8")
    return p


def test_load_spec_parses_the_block(tmp_path):
    spec = R.load_spec(b3_spec(tmp_path, {"cache": "terrain/site"}))
    ts = spec["_terrain"]
    assert ts.cache == str((tmp_path / "terrain" / "site").resolve())
    assert "terrain" not in spec["params"]


@pytest.mark.parametrize("terrain, project, match", [
    ({"source": "srtm", "cache": "x"}, {}, "not dem or lpc"),
    ({"cache": "x"}, {"epsg": None}, "terrain: needs project.epsg"),
])
def test_load_spec_refuses(tmp_path, terrain, project, match):
    p = b3_spec(tmp_path, terrain)
    s = yaml.safe_load(p.read_text())
    s["project"].update(project)
    p.write_text(yaml.safe_dump(s), encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        R.load_spec(p)


def test_a_b3_wall_gets_one_ground_around_it(tmp_path, monkeypatch, capsys):
    import ifcopenshell
    offline(monkeypatch)
    p = b3_spec(tmp_path, {"cache": "terrain/site", "margin_ft": 30.0,
                           "spacing_m": 3.0})
    assert R.build_from_spec(p) == 0
    f = ifcopenshell.open(str(tmp_path / "out" / "b3.ifc"))
    (g,) = [e for e in f.by_type("IfcGeographicElement")
            if e.PredefinedType == "TERRAIN"]
    container = g.ContainedInStructure[0].RelatingStructure
    assert container.is_a("IfcSite")
    psets = {pd.RelatingPropertyDefinition.Name: {
        p.Name: p.NominalValue.wrappedValue
        for p in pd.RelatingPropertyDefinition.HasProperties}
        for pd in g.IsDefinedBy if pd.is_a("IfcRelDefinesByProperties")}
    prov = next(v for v in psets.values() if "Source" in v)
    assert prov["Source"] == "USGS 3DEP 1m DEM"
    assert prov["VerticalShiftSource"] == "NAVD88: none"
    assert prov["QualityLevel"] == "QL2"
    assert (tmp_path / "terrain" / "site-3DEP-DEM.tif").exists()


def test_the_build_needs_a_datum_rule(tmp_path, monkeypatch, capsys):
    offline(monkeypatch)
    p = b3_spec(tmp_path, {"cache": "terrain/site"}, vertical_datum=None)
    with pytest.raises(ValueError, match="has no rule"):
        R.build_from_spec(p)


def test_a_spec_without_terrain_is_unchanged(tmp_path, monkeypatch):
    def never(url, timeout):
        raise AssertionError(url)
    monkeypatch.setattr(F, "_urlopen", never)
    assert R.build_from_spec(b3_spec(tmp_path)) == 0
```

The pset-reading lines assume BIMForge writes the provenance as a property set of single values (as `emit_ifc` writes `geometry["provenance"]`, line ~2445). If the provenance lands under a known pset name, read it by that name instead of `next(...)`.

- [ ] **Step 2: Run them; they fail** (`KeyError: '_terrain'` and the like).

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/author/tests/test_spec_terrain.py`

- [ ] **Step 3: Implement `load_spec`.** In `registry.py`, just before `spec["_dir"] = str(base)` at the end of `load_spec`, add:

```python
    # the model's one existing ground (G.9): the terrain: block, and the
    # road corridor's 0.1.132 ground: {source: 3dep} read as one
    notes = []
    gp = (spec.get("params") or {}).get("ground")
    old_3dep = isinstance(gp, dict) and str(gp.get("source", "")).lower() == "3dep"
    if spec.get("terrain") is not None:
        if old_3dep:
            raise ValueError(f"{path.name}: ground: source 3dep and a terrain: "
                             f"block both name the ground; keep the terrain: block")
        from bimforge.terrain.spec import parse as parse_terrain
        spec["_terrain"] = parse_terrain(spec["terrain"], base,
                                         f"{path.name}: terrain")
    elif old_3dep:
        from bimforge.terrain.spec import from_ground
        spec["_terrain"] = from_ground(gp)
        spec["params"]["ground"] = {"source": "terrain"}
        notes.append("note: ground: source 3dep is now terrain: {source: dem, "
                     "cache, spacing_m, margin_ft, vshift_m} with ground: "
                     "{source: terrain}")
    if spec.get("_terrain") is not None and not proj.get("epsg"):
        raise ValueError(f"{path.name}: terrain: needs project.epsg")
    spec["_notes"] = notes
```

`base` is resolved with `.resolve()` elsewhere in `load_spec` only for individual paths; `parse` joins `base / cache` without resolving. Make the test's expectation and the code agree: in `parse_terrain`'s call pass `base.resolve()` so the cache path is absolute.

- [ ] **Step 4: Implement `build_from_spec`.** After `params = spec_params(spec, alignments)` and before `if unread != "off":`, add:

```python
    terrain = spec.get("_terrain")
    for note in spec.get("_notes") or ():
        print(note, file=sys.stderr)
    if terrain is not None and getattr(builder, "takes_terrain", False):
        # a family that calculates against the ground fetches it itself, over
        # its own footprint (the road corridor)
        params = dict(params)
        params["terrain"] = terrain
```

After the `if spec.get("spatial_parts"): ...` block and before `pc_mod.apply(model, pc)`, add:

```python
    if terrain is not None:
        # the ground, once: over the model's footprint unless the family
        # already added it
        from bimforge.terrain.spec import add_spec_terrain
        add_spec_terrain(model, ctx, terrain,
                         log=lambda m: print(m, file=sys.stderr))
```

- [ ] **Step 5: Mark the corridor.** At the end of `bimforge/author/families/road_corridor.py` add:

```python
#: the corridor calculates against the ground, so build_from_spec hands it the
#: spec's terrain: block (params["terrain"]) instead of adding the ground after
build.takes_terrain = True
```

- [ ] **Step 6: Run the tests; they pass.** Same command. Then run `bimforge/author/tests/test_road_corridor.py bimforge/author/tests/test_road_corridor_v1.py`: they still pass (the corridor ignores `params["terrain"]` until Task 6 and no example has the block).

- [ ] **Step 7: Commit**, message "build: the spec's terrain: block gives any model its ground (G.9)".

---

### Task 6: The corridor's ground: terrain, plane with terrain, and 3dep as a library call

**Files:**
- Modify: `bimforge/author/corridor/ground.py` (`from_params`)
- Modify: `bimforge/author/families/road_corridor.py` (pass `params.get("terrain")`; `_terrain` via `is_terrain`)
- Test: `bimforge/author/tests/test_corridor_ground.py`, `bimforge/author/tests/test_spec_terrain.py`

- [ ] **Step 1: Update the existing tests that change.** In `test_corridor_ground.py`:
  - `test_bad_ground_is_refused`: the two `"plane or 3dep"` matches become `"plane, terrain or 3dep"`.
  - `test_3dep_fetches_in_crs_units_and_reads_back_in_feet` and `test_the_fetch_margin_is_at_least_two_dem_cells`: add `monkeypatch.setattr(A, "workunit_meta", lambda *a, **k: {})` (the ground now passes the base point's lon/lat, so the work-unit vintage is looked up), and give the second test's `ProjectContext` `vertical_datum="NAVD88"` (it has no `vshift_m`, and a missing datum now fails).

- [ ] **Step 2: Write the new failing tests** (append to `test_corridor_ground.py`)

```python
def _fake_grid(bbox_m, spacing_m, crs_epsg, cache_path, refresh=False, log=print):
    xmin, ymin, xmax, ymax = bbox_m
    cols = max(2, int(round((xmax - xmin) / spacing_m)))
    rows = max(2, int(round((ymax - ymin) / spacing_m)))
    return TerrainGrid(z=np.full((rows, cols), 30.48), bbox_m=bbox_m,
                       spacing_m=spacing_m, crs_epsg=crs_epsg)


def _ctx(vd="NAVD88"):
    return ProjectContext(name="g", epsg=2226, vertical_datum=vd,
                          guid_ns=uuid.UUID(int=5))


def test_source_terrain_measures_against_the_terrain_block(monkeypatch, tmp_path):
    import bimforge.terrain.attach as A
    from bimforge.author.model import StructureModel
    from bimforge.terrain.spec import TerrainSpec
    monkeypatch.setattr(A, "fetch_3dep_dem", _fake_grid)
    monkeypatch.setattr(A, "workunit_meta", lambda *a, **k: {})
    ctx = _ctx()
    model = StructureModel("g", ctx)
    ts = TerrainSpec(cache=str(tmp_path / "ml"), margin_ft=10.0)
    g = from_params({"source": "terrain"}, line(), ctx, 40.0, model,
                    log=lambda *_: None, terrain=ts)
    assert g.z(50.0, 0.0) == pytest.approx(30.48 / US_FT)
    (t,) = [el for el in model.elements if el.predefined_type == "TERRAIN"]
    assert t.geometry["provenance"]["VerticalShiftSource"] == "NAVD88: none"


def test_source_terrain_needs_the_block():
    with pytest.raises(ValueError, match="needs a top-level terrain: block"):
        from_params({"source": "terrain"}, line(), _ctx(), 40.0, None)


def test_a_plane_with_terrain_writes_the_fetched_ground(monkeypatch, tmp_path):
    import bimforge.terrain.attach as A
    from bimforge.author.model import StructureModel
    from bimforge.terrain.spec import TerrainSpec
    monkeypatch.setattr(A, "fetch_3dep_dem", _fake_grid)
    monkeypatch.setattr(A, "workunit_meta", lambda *a, **k: {})
    ctx = _ctx()
    model = StructureModel("g", ctx)
    g = from_params({"source": "plane", "elevation": 95.0}, line(), ctx, 40.0,
                    model, log=lambda *_: None,
                    terrain=TerrainSpec(cache=str(tmp_path / "ml")))
    assert g.z(0.0, 0.0) == pytest.approx(95.0)              # the plane measures
    (t,) = [el for el in model.elements if el.predefined_type == "TERRAIN"]
    assert t.name.startswith("Existing ground - USGS 3DEP")  # not the plane


def test_3dep_with_a_terrain_block_is_refused(tmp_path):
    from bimforge.terrain.spec import TerrainSpec
    with pytest.raises(ValueError, match="both name the ground"):
        from_params({"source": "3dep", "cache": "x"}, line(), _ctx(), 40.0, None,
                    terrain=TerrainSpec(cache=str(tmp_path / "ml")))
```

- [ ] **Step 3: Run them; they fail** (`from_params() got an unexpected keyword argument 'terrain'`).

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/author/tests/test_corridor_ground.py`

- [ ] **Step 4: Implement `from_params`.** Replace the function in `bimforge/author/corridor/ground.py` with:

```python
def from_params(gp: dict, alignment, ctx, reach: float, model, log=print,
                terrain=None):
    """The ground `gp` (the spec's `ground:`) names, which the corridor
    calculates against. `reach` is how far from the line the corridor can
    reach, feet; `terrain` is the spec's `terrain:` block (a
    `bimforge.terrain.spec.TerrainSpec`), or None.

    `source: terrain`: the terrain block's 3DEP ground, fetched over the
    corridor's footprint, which it adds as the TERRAIN element. `source:
    plane`: a test plane; the TERRAIN element is the terrain block's ground
    when there is one, else the plane meshed over the same footprint.
    `source: 3dep` (0.1.132) is read as a terrain block of its own settings.
    The element is added in the model frame."""
    source = str((gp or {}).get("source", "")).lower()
    if source == "3dep":
        if terrain is not None:
            raise ValueError("ground: source 3dep and a terrain: block both "
                             "name the ground; keep the terrain: block")
        if not gp.get("cache"):
            raise ValueError("ground: source 3dep needs `cache`, the path stem "
                             "its downloads are kept under")
        from bimforge.terrain.spec import from_ground
        terrain, source = from_ground(gp), "terrain"
    if source == "plane":
        n0, e0, _az = alignment.point_az(alignment.s_start)
        ground = PlaneGround(float(gp["elevation"]), n0=n0, e0=e0,
                             slope_n=float(gp.get("slope_n", 0.0)),
                             slope_e=float(gp.get("slope_e", 0.0)))
        if model is not None and ctx is not None:
            if terrain is not None:
                from bimforge.terrain.spec import attach_over
                attach_over(model, ctx, terrain, footprint(alignment, reach),
                            log=log)
            else:
                _plane_terrain(ground, alignment, ctx, reach,
                               float(gp.get("margin_ft", 200.0)), model)
        return ground
    if source == "terrain":
        if terrain is None:
            raise ValueError("ground: source terrain needs a top-level "
                             "terrain: block")
        if ctx is None or ctx.epsg is None:
            raise ValueError("ground: the terrain needs project.epsg")
        from bimforge.author.model import StructureModel
        from bimforge.terrain.spec import attach_over, crs_per_ft
        target = model if model is not None else StructureModel("ground", ctx)
        _el, grid, shift = attach_over(target, ctx, terrain,
                                       footprint(alignment, reach), log=log)
        return GridGround(grid, ctx.ft_to_m, shift, crs_per_ft=crs_per_ft(ctx))
    raise ValueError(f"ground: source {gp.get('source') if gp else None!r} is "
                     f"not plane, terrain or 3dep")
```

Update the module docstring's description of the sources to match (`plane`, `terrain`, and `3dep` as the 0.1.132 form). Remove the imports the old 3DEP branch used that are now unused (`Path` if nothing else uses it; check with ruff).

Note the footprint: the old code fetched over `footprint(alignment, reach + margin)` with the margin floored to two cells; `attach_over` grows `footprint(alignment, reach)` by the same floored margin, so the bbox is the same. `test_3dep_fetches_in_crs_units_and_reads_back_in_feet` asserts the bbox and still passes unchanged.

- [ ] **Step 5: Pass the block from the family.** In `bimforge/author/families/road_corridor.py`, change the `from_params(...)` call in `build` to:

```python
    ground = from_params(params["ground"], al, ctx, ground_reach(c), model,
                         log=log, terrain=params.get("terrain"))
```

and `_terrain` to use the shared test:

```python
def _terrain(model) -> str | None:
    """The TERRAIN element's name, when the ground added one."""
    from bimforge.terrain.attach import is_terrain
    for el in model.elements:
        if is_terrain(el):
            return el.name
    return None
```

- [ ] **Step 6: Add the spec-level corridor tests** (append to `bimforge/author/tests/test_spec_terrain.py`)

```python
def corridor_spec(tmp_path, ground, terrain=None, name="rc.spec.yaml"):
    s = yaml.safe_load((EX / "road-corridor.spec.yaml").read_text())
    s["paycodes"] = str(EX / "road-corridor.paycodes.yaml")
    s["outputs"] = {"ifc": str(tmp_path / "out" / (name + ".ifc"))}
    s["project"]["vertical_datum"] = "NAVD88"
    s["params"]["ground"] = ground
    if terrain is not None:
        s["terrain"] = terrain
    p = tmp_path / name
    p.write_text(yaml.safe_dump(s), encoding="utf-8")
    return p


def test_the_0_1_132_ground_builds_the_same_ifc(tmp_path, monkeypatch, capsys):
    offline(monkeypatch)
    cache = str(tmp_path / "t" / "ml")
    old = corridor_spec(tmp_path, {"source": "3dep", "cache": cache,
                                   "spacing_m": 3.0}, name="old.yaml")
    new = corridor_spec(tmp_path, {"source": "terrain"},
                        {"cache": cache, "spacing_m": 3.0}, name="new.yaml")
    assert R.build_from_spec(old) == 0
    assert "ground: source 3dep is now terrain:" in capsys.readouterr().err
    assert R.build_from_spec(new) == 0
    a = (tmp_path / "out" / "old.yaml.ifc").read_text()
    b = (tmp_path / "out" / "new.yaml.ifc").read_text()
    strip = lambda t: "\n".join(l for l in t.splitlines()
                                if not l.startswith(("FILE_NAME", "FILE_DESCRIPTION")))
    assert strip(a) == strip(b)


def test_the_old_ground_and_a_terrain_block_are_refused(tmp_path):
    p = corridor_spec(tmp_path, {"source": "3dep", "cache": "x"}, {"cache": "x"})
    with pytest.raises(ValueError, match="both name the ground"):
        R.load_spec(p)


def test_a_plane_corridor_with_terrain_carries_one_ground(tmp_path, monkeypatch):
    import ifcopenshell
    offline(monkeypatch)
    s = yaml.safe_load((EX / "road-corridor.spec.yaml").read_text())
    p = corridor_spec(tmp_path, s["params"]["ground"],
                      {"cache": str(tmp_path / "t" / "ml"), "spacing_m": 3.0})
    assert R.build_from_spec(p) == 0
    f = ifcopenshell.open(str(tmp_path / "out" / "rc.spec.yaml.ifc"))
    grounds = [e for e in f.by_type("IfcGeographicElement")
               if e.PredefinedType == "TERRAIN"]
    assert len(grounds) == 1 and "3DEP" in grounds[0].Name
```

The IFC header lines `FILE_NAME` (timestamp, source name) and `FILE_DESCRIPTION` may differ by spec name; strip whatever header lines differ, and nothing else. If the model's identity property set records the spec's file name or hash, strip that line too and say so in the commit. Before relying on the example: confirm the shipped `road-corridor.spec.yaml`'s `project.base`, `epsg` and footprint give a DEM bbox the 40 x 40 test TIFF can stand for (the fetch is stubbed, so any bbox works; the ground is flat 30.48 m = 100 ft NAVD88). If the corridor's cut or fill no longer fits flat ground at 100 ft (the build raises `NoDaylight` or the gate fails), set the stub's `z_m` to the plane's `elevation` converted to metres.

- [ ] **Step 7: Run the corridor and spec tests; they pass.**

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/author/tests/test_corridor_ground.py bimforge/author/tests/test_spec_terrain.py bimforge/author/tests/test_road_corridor.py bimforge/author/tests/test_road_corridor_v1.py bimforge/author/tests/test_excavation_void.py`

- [ ] **Step 8: Check the shipped corridor example is byte-identical.** Build `bimforge/author/examples/road-corridor.spec.yaml` before and after the change (`git stash` is forbidden here; use `git worktree add` of `origin/main` into the scratchpad, or compare against the regression fixture the corridor tests already hold) and confirm the IFC is unchanged.

- [ ] **Step 9: Commit**, message "road corridor: ground: source terrain, a plane beside the terrain, 3dep read as terrain (G.9)".

---

### Task 7: est-bim terrain

**Files:**
- Modify: `bimforge/author/families/registry.py` (new `terrain_from_spec`)
- Modify: `bimforge/bim/cli.py` (parser, dispatch, `_run_terrain`, the module docstring's command list)
- Test: `bimforge/bim/tests/test_cli_terrain.py` (new)

- [ ] **Step 1: Write the failing tests** (`bimforge/bim/tests/test_cli_terrain.py`)

```python
"""est-bim terrain (G.9): fetch a spec's ground ahead of the build."""
import pytest

from bimforge.author.tests.test_spec_terrain import b3_spec, offline
from bimforge.bim import cli


def test_it_fetches_once_then_reads_the_cache(tmp_path, monkeypatch, capsys):
    calls = []
    offline(monkeypatch, calls)
    p = b3_spec(tmp_path, {"cache": "terrain/site", "spacing_m": 3.0})
    assert cli.main(["terrain", str(p)]) == 0
    out = capsys.readouterr().out
    assert "Existing ground - USGS 3DEP DEM" in out
    assert "shift 0.000 m (NAVD88: none)" in out and "QL2" in out
    assert any("exportImage" in u for u in calls)
    fetched = len(calls)
    assert cli.main(["terrain", str(p)]) == 0           # all from the cache
    assert len(calls) == fetched
    assert cli.main(["terrain", str(p), "--refresh"]) == 0
    assert sum("exportImage" in u for u in calls) == 2


def test_a_spec_without_terrain_says_so(tmp_path, capsys):
    p = b3_spec(tmp_path)
    assert cli.main(["terrain", str(p)]) == 0
    assert "terrain: the spec asks for no terrain" in capsys.readouterr().out
```

Check how `cli.main` takes its arguments (read `main`'s signature near the bottom of `bimforge/bim/cli.py`); if it reads `sys.argv`, use `monkeypatch.setattr(sys, "argv", ["est-bim", "terrain", str(p)])` instead. The work-unit index is cached after the first run (`workunit_meta` caches `{}` or the answer), so the second run makes no call at all.

- [ ] **Step 2: Run them; they fail** (`invalid choice: 'terrain'`).

Run: `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider bimforge/bim/tests/test_cli_terrain.py`

- [ ] **Step 3: Implement `terrain_from_spec`** in `registry.py`, after `build_from_spec`:

```python
def terrain_from_spec(spec_path: Path | str, refresh: bool = False,
                      family_paths=(), log=None):
    """Fetch the ground a spec asks for (or read it from the cache), building
    the model in memory to find its footprint: no gate, nothing written.
    Returns (TERRAIN elements, ProjectContext, TerrainSpec), or ([], None,
    None) when the spec asks for none."""
    from bimforge.author.project import ProjectContext
    from bimforge.terrain.attach import is_terrain
    from bimforge.terrain.spec import add_spec_terrain
    spec = load_spec(spec_path)
    terrain = spec.get("_terrain")
    if terrain is None:
        return [], None, None
    terrain.refresh = bool(refresh)
    say = log or (lambda m: print(m, file=sys.stderr))
    for note in spec.get("_notes") or ():
        say(note)
    builder = get(spec["family"], family_paths)
    ctx = ProjectContext.from_spec(spec["project"])
    alignments = spec_alignments(spec)
    params = spec_params(spec, alignments)
    if getattr(builder, "takes_terrain", False):
        params = dict(params)
        params["terrain"] = terrain
    model = builder(params, ctx)
    place_from_spec(model, spec, alignments)
    add_spec_terrain(model, ctx, terrain, log=say)
    return [el for el in model.elements if is_terrain(el)], ctx, terrain
```

`build_from_spec` and `terrain_from_spec` share the lines that hand the block to a family; if they grow apart later, factor them, but not now.

- [ ] **Step 4: Implement the command** in `bimforge/bim/cli.py`. Next to the `build` parser:

```python
    tr = sub.add_parser("terrain", help="fetch the existing ground a build spec's "
                                        "terrain: block asks for, ahead of the "
                                        "build, and report it")
    tr.add_argument("spec", help="build spec YAML")
    tr.add_argument("--refresh", action="store_true",
                    help="fetch again over a cached download")
    tr.add_argument("--family-path", action="append", default=[], dest="family_paths",
                    metavar="DIR", help="as for est-bim build; repeatable")
```

In the dispatch, beside `if args.cmd == "build":`:

```python
        if args.cmd == "terrain":
            try:
                return _run_terrain(args)
            except (OSError, ValueError, KeyError) as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
```

and the runner, beside `_run_terrain_diff`:

```python
def _run_terrain(args) -> int:
    """The spec's ground, fetched or from the cache, reported."""
    from bimforge.author.families.registry import terrain_from_spec
    from bimforge.terrain.spec import report_lines
    els, ctx, ts = terrain_from_spec(args.spec, refresh=args.refresh,
                                     family_paths=args.family_paths)
    if not els:
        print("terrain: the spec asks for no terrain")
        return 0
    for el in els:
        print("\n".join(report_lines(el, ctx, ts)))
    return 0
```

Add to the module docstring's command list, beside `est-bim build`:

```
  est-bim terrain spec.yaml [--refresh]   fetch the spec's terrain: ground ahead of the build
```

- [ ] **Step 5: Run the tests; they pass.** Same command, plus `bimforge/author/tests/test_spec_terrain.py`.

- [ ] **Step 6: Commit**, message "est-bim terrain: fetch a spec's ground ahead of the build (G.9)".

---

### Task 8: Validators on a wall with terrain, docs, the full suite

**Files:**
- Test: `bimforge/author/tests/test_spec_terrain.py`
- Modify: `ROADMAP.md` (G.9 row), `README.md`, `CHANGELOG.md`

- [ ] **Step 1: Write the validator test** (append to `test_spec_terrain.py`)

```python
def test_a_wall_with_terrain_passes_the_validators(tmp_path, monkeypatch):
    import ifcopenshell
    import ifcopenshell.validate as V
    offline(monkeypatch)
    p = b3_spec(tmp_path, {"cache": "terrain/site", "spacing_m": 3.0})
    assert R.build_from_spec(p) == 0
    f = ifcopenshell.open(str(tmp_path / "out" / "b3.ifc"))
    log = V.json_logger()
    V.validate(f, log)
    assert log.statements == []
```

Match the call to the way `bimforge/author/tests/test_excavation_void.py` (lines ~60-82) runs `ifcopenshell.validate` and reads its logger; copy that pattern exactly rather than this sketch if it differs. If the repository has a helper for the buildingSMART normative rules used by other tests (search `bimforge/author/tests` for `normative` or `bsi`), run it here too.

- [ ] **Step 2: Run it; it passes.** If it fails, the failure names an IFC rule the TERRAIN element breaks: fix the emission, not the test.

- [ ] **Step 3: Docs.**
  - `ROADMAP.md` G.9 row, state column: `Done in #N: the top-level terrain: block for every family (USGS 3DEP DEM or lidar, over the model's footprint, cached), the road corridor's ground: {source: terrain}, the shift from project.vertical_datum (NAVD88 none, NGVD29 by NOAA NCAT), and est-bim terrain`. Leave `#N` until the PR exists, then fill it in.
  - `README.md`: where the spec keys or the road corridor's `ground:` are described (search `ground:`), add the `terrain:` block with its five keys, `ground: {source: terrain}`, the datum rule, and `est-bim terrain SPEC [--refresh]`. One short paragraph and the YAML example from the design.
  - `CHANGELOG.md` under `## Unreleased`, in `### Added`: "**Terrain from a spec (G.9).** A top-level `terrain:` block gives any model its existing ground ...", and in a `### Changed` section: the corridor's `ground: {source: 3dep}` is now read as `terrain:` plus `ground: {source: terrain}`, and takes its shift from `project.vertical_datum` when it gives no `vshift_m` (an NGVD29 project now gets the NCAT shift where it got 0).

- [ ] **Step 4: Regenerate the IFC inventory if CI asks.** Run `C:/Python314/python.exe scripts/ifc_inventory.py --check` (read the script's options first). No shipped example gains a terrain, so it should report current; if it does not, regenerate it with the script and commit `docs/ifc-inventory.json` and `.md`.

- [ ] **Step 5: Lint and the full suite.**

Run: `C:/Python314/python.exe -m ruff check bimforge`
Run (about 20 minutes; write the output to a file and read the last lines): `PYTHONPATH=. C:/Python314/python.exe -m pytest -q -p no:cacheprovider > "<scratchpad>/g9-suite.txt" 2>&1; tail -5 "<scratchpad>/g9-suite.txt"`
Expected: every test passes (the count is 2988 + the new ones, 11 skipped).

- [ ] **Step 6: Commit**, message "G.9 docs: the terrain: block, ground: source terrain, est-bim terrain".

---

## Known, outside this plan

- **The B3 wall's elevations are not local to the project base.** The shipped B3 example has `project.base` elevation 100 and its footing bottom at elevation 100, and its elements sit at model z 100 (checked 2026-11-24), where the house convention (`ProjectContext.local`, the spillway family) puts them at `elevation - base_h` = 0. Terrain follows the convention, so on that example the ground lands 100 ft below the wall. The test specs here use the example as it is and assert plan coverage, not height. Whether the B3 family should subtract `base_h` is a separate fix for the owner to rule on (it moves every B3 example's IFC 100 ft).
- **Structure families dig no excavations,** so nothing is carved into a structure's ground; the corridor's cuts void its own as before.
