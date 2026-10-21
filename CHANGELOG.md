# Changelog

Newest first. Versions follow `pyproject.toml`; a tag `vX.Y.Z` releases to PyPI.

## 0.1.94 — 2026-10-20

(0.1.90 through 0.1.93 were internal builds and were not published.)

### Added

- **`est-bim takeoff-workbook`.** A verifiable per-element takeoff workbook:
  one row per element per pay code with Qty, L, W, H, CY, forming SF, model vs
  L×W×H volume and its delta, surface areas, weight and pay quantity, plus a
  Summary by cost code against official quantities (`--official`), a Legend and
  the SHA-256 of each source IFC. Output is byte-deterministic (the
  `docProps` modified date is pinned too, which openpyxl's save overwrites).
- **`model-elements --takeoff` / `--takeoff-id N`** plans an element payload for
  a named takeoff (no pay items attached).
- **AND-mode filters on the 4D task map.** An entry may carry `filter_re` and/or
  `filter_ifc_class` to narrow its code join, so one bid item spanning several
  stages can be split across tasks.
- **`count_as: <number>`** on a takeoff-map entry overrides the element count.

### Fixed

- A Count row paid LS takes off as 1 (every contributing element is still
  listed), and `estimate5d` prices LS / `count_as` rows at that capped quantity
  instead of rate × element count. The per-task split of such rows sums to the
  row.
- A map saying plain `Weight` resolves to the `GrossWeight` Qto that the emitter
  writes.
- An unhosted `IfcEarthworksCut` is written as `IfcEarthworksElement`, so it
  validates.
- `est-bim validate` no longer crashes on IFC2X3 files.
- A `SectionPrism`'s cross-section area is no longer exported as its plan
  area; the footprint comes from length × width.
- `cost5d --task-map` help says selectors and filters have no effect there.
- CI's pip-audit runs on the 3.12 leg: pillow 13's advisory fixes need Python
  3.11+.

## 0.1.89 — 2026-10-17

(0.1.88 was an internal build and was not published.)

### Fixed

- **IFC area and volume read their own declared units.** The takeoff and
  `estimate5d` scaled area and volume by the length unit squared and cubed,
  ignoring `AREAUNIT` and `VOLUMEUNIT`. A file declaring mm / m² / m³
  (ifcopenshell's default, and the shape of a Revit metric export) therefore
  read 10 m³ as 1e-8 m³. Each dimension now reads its own declared unit, and a
  quantity's own `Unit` wins. Only an undeclared area or volume unit still
  falls back to the length unit.

### Added

- **`bimforge.bim.model_elements` and `est-bim model-elements`.** These plan an
  element upsert from an IFC, keyed by GlobalId:
  - Volumes go to `concrete_cy`, `excavation_cy` (IfcEarthworksCut) or
    `backfill_cy` (IfcEarthworksFill), and a pile's length to `pile_lf`. Each is
    converted into the key's unit and names its source Qto.
  - Pay items are matched by classification code; an ambiguous code maps to
    no item, and the command warns.
  - By default only typed and classified elements are sent (`--all-elements`
    widens this). Malformed or repeated GlobalIds are skipped.
- **`bimforge.bim.estimate_model5d` and `est-bim estimate-model`.** These write
  an estimate document into the IFC:
  - an IfcWorkSchedule with a dated IfcTask per activity, linked to its
    elements;
  - an ESTIMATE IfcCostSchedule with a cost item per bid item and per
    allocation share;
  - an IfcLaborResource per crew.

  Re-runs replace only what the command wrote, and a same-named schedule from
  another tool is refused. `read_costs` reads nested cost items and each task's
  own hours back.
- **New post-emit gate check for revolved solids.** It tessellates each
  `IfcRevolvedAreaSolid` and requires every vertex to be a profile point turned
  by an angle inside the model's sweep. The volume check can't catch these
  errors, because each has the same volume:
  - a solid turned the wrong way;
  - a solid turned about the far side of the axis;
  - a solid turned from a shifted profile.

### Changed

- **The B11-51 handrail's bent-down end returns and their tip caps are exact.**
  Each is one `IfcRevolvedAreaSolid`, replacing a faceted mesh: the rectangular
  HSS section turned about the axis one bend radius below the rail.
  - The declared volume is still the closed-form Pappus volume.
  - DXF and STEP still draw the chorded mesh.
  - A file holding a revolved solid now declares a radian `PLANEANGLEUNIT`; a
    file without one is byte-identical to before.
- **Custom property sets leave the reserved `Pset_` prefix.** 4D tasks now
  carry `Bimforge_Task` and 5D cost items `Bimforge_CostItem`. Models written
  with the old `Pset_BimforgeTask` / `Pset_BimforgeCostItem` still read back
  unchanged.

## 0.1.87 — first public cut

bimforge began life inside a private construction-estimating monorepo, where
it reached this version over some 340 pull requests as the CAD/BIM engine under
an estimating plugin: DXF → IFC authoring, plan-sheet measurement, the
structure-family kernel, terrain, sheet production, 4D/5D schedule and cost
embeds. This repository starts with a fresh history at that version — the
code, its tests and the Caltrans table data as of the public cut, without the
private planning trail. The last change before the cut removed bimforge's
remaining imports of the estimating layer: schedule readers moved in
(`bimforge.bim.schedule_io`, `bimforge.bim.xer`) and CAD style packs resolve
through the `bimforge.style_packs` entry-point group.
