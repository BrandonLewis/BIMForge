# IFC compliance audit and plugin shim list

Date: 2026-11-09. Base: main `d5abdfb` (0.1.111). Read-only audit; nothing changed.

## How it was checked

- **Validator.** 515 files written by BIMForge were checked with `ifcopenshell.validate` 0.9.0, schema plus EXPRESS where-rules and global rules (the rule executor was confirmed firing on a broken file).
  - 476 were captured from the full test suite.
  - 10 came from `est-bim build` of every example spec.
  - 29 came from an end-to-end chain: IFC4 builds, dxf2bim, XER → schedule → cost5d → estimate5d → estimate-model, federate, add-alignments, stations and terrain.
- **Spec review.** Four reviews were made against IFC4 / IFC4X3_ADD2 and its concept templates: 5D cost, 4D schedule, spatial/georef/units, and quantities/psets/geometry. Pset and Qto names were checked against ifcopenshell's 4X3 templates programmatically.
- **Dependency map.** The estimating plugin's dependencies on BIMForge were mapped from estimating-plugin, the installed estimating_tools 0.1.98 and its skills, plus ProjectCommand's reader.

**The headline:** almost everything BIMForge writes is *schema-valid*. Only three where-rule failures were found, all in narrow paths. What it gets wrong is *semantics*: reserved names, missing units, relationships pointing the wrong way, and spatial trees built for buildings. The validator cannot see these, but Bonsai, Synchro, ProjectCommand, web-ifc and the bSI validation service can.

## Phase 0 — bugs (fix now, no shape change)

| # | Defect | Where | Fix |
|---|---|---|---|
| 0.1 | **estimate5d crashes on IFC4X3** for any element with an IfcQuantityCount (`RuntimeError: Attribute not set`). This shipped in 0.1.111; reproduced. IfcCountMeasure is INTEGER in 4X3, and the code passes `1.0`. | `bim/estimate5d.py:76,177` | Pass `int` for the count basis; add a 4X3 count test |
| 0.2 | federate orphans every IfcBuildingStorey (WR41, 14 files). Dropping the placeholder storey removes the whole Building→storeys IfcRelAggregates. | `author/federate.py:736-737` | Unassign only the placeholder |
| 0.3 | IfcSectionedSolidHorizontal `DirectrixIs3D` fails (12 files). With no vertical profile the directrix is the 2D horizontal curve. | `author/emit_alignment.py:156`, `emit_ifc.py:703` | Emit a flat IfcGradientCurve, or fall back to the faceted body |
| 0.4 | IfcAnnotation has a Representation but no ObjectPlacement (`PlacementForShapeRepresentation`). | `author/emit_ifc.py:1115-1122` | Place it relative to its container |
| 0.5 | A negative lag is written `P-1.5D`, which is not ISO 8601. The reader reads it back as **0**. | `bim/schedule4d.py:387`, `schedule_read.py:75-77` | Write `-P1.5D`; accept a leading `-` |
| 0.6 | dxf2bim's georef Scale/Eastings assume the DXF unit equals the CRS unit. A mm DXF on a metric CRS is off by 1000. | `bim/dxf2bim.py:271-277` | Take the CRS unit from pyproj |
| 0.7 | A fake georef at E=0, N=0 (3 example specs) puts the model at the zone's false origin, with TrueNorth off by 13°. | `author/emit_ifc.py:1514` | Refuse an EPSG with a zero base unless explicitly allowed |
| 0.8 | KML shows elements on DEMOLITION/REMOVAL tasks *appearing* on their removal date. | `bim/kml.py:154` | Use `schedule_state.element_spans` |
| 0.9 | dxf2bim IFC2X3 crashes in `create_owner_history`. | `bim/dxf2bim.py:226` | Drop 2X3 from the example, or create an owner |
| 0.10 | A hole touching its outer bound is written into an IfcClosedShell (#42; reproduced). | `author/facets.py` `_merge_group` | Fall back to triangles |

## Phase 1 — additive compliance (file contents change; nothing downstream reads them)

- **Units.** Always assign MASSUNIT kg: weights are written in kg today, which stock readers take as grams. Also always assign PLANEANGLEUNIT radian, since alignment segments carry radians. Assign a TIMEUNIT of hour, because cost5d's `StandardWork` hours currently default to seconds. Assign an IfcMonetaryUnit (USD, configurable) whenever a cost value is written; there is none anywhere today. Sources: `emit_ifc.py:1527-1531`, `dxf2bim.py:231-235`, `cost5d.add_declared_cost_schedule`.
- **Georef.** Write IfcProjectedCRS.MapUnit (US survey foot) and the datums from pyproj, and keep `Scale` so the current readers still work (`emit_ifc.py:1586-1597`). Federation should refuse sources whose MapConversion or CRS differ (`federate.py:559-586`).
- **4D.**
  - IfcWorkSchedule PredefinedType defaults to PLANNED (#37).
  - StartTime and CreationDate come from the data, not `now()` (#36).
  - The project calendar gets IfcRelAssignsToControl to the root tasks.
  - estimate_model5d tasks get PredefinedType CONSTRUCTION.
  - Task finish is written as 17:00 and start as 08:00, not midnight (readers slice `[:10]`).
  - XER actual dates go to ActualStart/ActualFinish.
- **5D.** Give BUDGET/ESTIMATE schedules a Status, and give TENDER a SubmittedOn. Guard at write time against a second ESTIMATE schedule. ProjectCommand reads only the first.
- **Typing.** Set PredefinedTypes:
  - IfcBeam PIERCAP
  - IfcColumn PIERSTEM
  - IfcWall RETAININGWALL
  - IfcSlab APPROACH_SLAB
  - IfcFooting PAD_FOOTING / STRIP_FOOTING / PILE_CAP
  - IfcReinforcingBar MAIN / LIGATURE

  The proxy fallback must set USERDEFINED along with ObjectType (`emit_ifc.py:1680-1682`). Add one IfcReinforcingBarType per bar size, with NominalDiameter, CrossSectionArea and BarSurface. Rebar is never sent to BidSheet, so this is safe.
- **Declarations.** Declare IfcTypeObjects to the project (`emit_ifc.py:1008`). See the GlobalId note under Phase 3: this inserts an IfcRoot and shifts the swept ids.
- **Misc.**
  - `add_alignment.py:255-260` aggregates the alignment under the IfcProject, not the IfcSite, as emit_alignment and federate already do.
  - Add a FootPrint subcontext.
  - Classification Source/Edition.
  - Material layer and profile set usages.

## Phase 2 — relationship and reader semantics (BIMForge readers dual-read; JSON outputs change)

| Change | Spec basis | What downstream sees |
|---|---|---|
| Task builds element: **IfcRelAssignsToProduct** (element relating, task related). Today it is `assign_process`, which IFC reads as the task *consuming* the element. Verified: ifcopenshell `get_task_outputs` reads only AssignsToProduct. Sources: `schedule4d.py:463`, `estimate_model5d.py:386`. | IFC4 process input/output (ICOM) | Readers already accept both directions. `task_elements()` / `schedule_links()` `direction` flips from `"input"` to `"output"`. |
| Task uses crew: IfcRelAssignsToProcess (task relating). Today it is IfcRelAssignsToResource. Sources: `cost5d.py:261`, `estimate_model5d.py:492`. | Resource assignment concept | `read_costs` must find crews via `task.OperatesOn`, with a fallback; otherwise `labor_hours` reads null. |
| Crews: IfcCrewResource with nested IfcLaborResource. Hours go in IfcResourceTime.ScheduleWork and headcount in ScheduleUsage. Today they are a text Description plus the `BidSheet_Crew`, `BidSheet_Activity.Manhours` and `Bimforge_CostItem.LaborHours` psets. | Construction resource concept | `read_costs` `labor_hours` is sourced from resources. The psets stay as mirrors for the BidSheet round trip. |
| One cost-value evaluator for every reader: ×CostQuantities/UnitBasis, Components + ArithmeticOperator, ApplicableDate. Today every reader sums AppliedValue, reading an IfcMeasureWithUnit as 0 and a ratio as money. Sources: `schedule_read.py:595`, `web/contract.py:272`, `cost_categories.py:406-425`. | IfcAppliedValue / IfcCostItem | Totals unchanged for today's files. This is a prerequisite for the ESTIMATE re-key. |
| Cost Category vocabulary. The spec's informal list is title case: `Labor`, `Material`, `Sub-Contract`, `Hire`, `Overhead`, with no `Equipment`/`Other`. ProjectCommand wants LABOR/MATERIAL/EQUIPMENT/SUBCONTRACT/OTHER. Pick one, documented as a local agreement with ProjectCommand, and match case exactly: parent roll-ups compare Category strings. | IfcCostValue.Category (IfcLabel) | **Every `categories` JSON key changes** (read_costs, contract shares). |
| ESTIMATE schedule re-keyed by bid item → `"<item>.<code>"` → per-share leaves with one ADD value. `read_costs` keys by the top-level bid item. Spec: `2026-11-09-estimate-schedule-by-bid-item-design.md`. | ProjectCommand contract | The `read_costs` `costs` keys for estimate-model files change from item code to item number. The contract `_shares` must walk to the top-level item. |
| Readers locate cost and work schedules by PredefinedType plus declaration, not by the name `"<ws> cost"` / `"<name> bid"`. ProjectCommand already pairs by type. Sources: `schedule_read.py:576-582`, `contract.py:235`. | Project declaration | Keep the names as written; only lookup changes. |
| `contract._bid_items` scans every IfcCostItem for `BidSheet_EstimateItem`. Scope it to the ESTIMATE schedule, or read prices from the TENDER's UnitBasis/CostQuantities. | IfcCostValue/UnitBasis | Provenance only. |

## Phase 3 — renames and restructuring (output shapes change; shims required)

| Change | Where | Breaks unless shimmed |
|---|---|---|
| `Qto_BaseQuantities`: the `Qto_` prefix is reserved and this is not a bSI template. Write the class's `Qto_<Class>BaseQuantities` with only its template names, and move the rest to `Bimforge_BaseQuantities` under today's names. | `emit_ifc.py:1778` | Takeoff is safe, because `quantity_entities` merges sets by quantity name and ignores the set name. **model_elements** `source: "Qto_BaseQuantities.GrossVolume"` strings sent to BidSheet change, and `_pick` (`model_elements.py:205`) ranks `Qto_*` first. Five test files pin the name. |
| `Qto_TakeoffBaseQuantities` (reserved prefix). Slab `Width` should be `Depth`, and wall/slab sets carry names outside their templates. | `dxf2bim.py:316-318` | `ifc_takeoff.py:146-148` reads `Width` for the Structures grid; `MEASURE_DIM` has no `Depth`. Add the alias first. |
| `Pset_BimforgeTerrain` → `Bimforge_Terrain`. This is the last custom `Pset_`, and it has no alias. | `emit_ifc.py:1798` | Readers must accept both, as `_TASK_PSETS` does. The plugin's `build-structure` skill prose names it. |
| Rebar weight `GrossWeight` → `Weight` (Qto_ReinforcingElementBaseQuantities). | `emit_ifc.py:258`, `emit_qto.py:21` | Takeoff is safe via `MEASURE_ALIASES`. `emit_qto._MEASURE_KEY` needs `Weight`. |
| Earthworks `GrossVolume` → `UndisturbedVolume` (cut) / `CompactedVolume` (fill). | earthworks writers | `measure: GrossVolume` map keys. Write both, or alias. |
| The 4X3 default tree becomes IfcSite → IfcBridge/IfcRoad/… → IfcFacilityPart, not IfcBuilding → IfcBuildingStorey (#25), with multiple facilities per model (#41). | `emit_ifc.py:1550-1580`, `dxf2bim.py:241-247`, `project.py:89` | Spatial names; `estimate_model5d.py:230` looks for a storey first; `takeoff_workbook._container_of`, which also ignores `Decomposes`. |
| Class corrections: diaphragm IfcPlate → IfcBeam DIAPHRAGM; culvert barrel / spillway / pocket mortar proxies → real classes; C-CURB → IfcKerb. | `bridge_standard.py:243-246`, `box_culvert.py:36,41`, `spillway.py:269`, `rail_run.py:127-129` | `ifc_class` / `element_type` sent to BidSheet change, so **BidSheet sees new elements**, and the takeoff's class-derived section types change. |

**GlobalId stability is a hard requirement for every Phase 3 change.** Site, rel and pset GlobalIds are swept by file index (`emit_ifc.py:1931`). Inserting any IfcRoot (a declaration, a facility, a type) shifts them. BidSheet.ai element identity (`upsert_modelled_elements`) keys on *element* GlobalIds, so before Phase 3 starts, pin element GlobalIds to a deterministic key such as spec + element path, and add a test asserting they survive these changes.

## What to pass down to the estimating plugin

The plugin floor is `bimforge>=0.1.108` (`packages/estimating-tools/pyproject.toml:20`). The installed runtime is 0.1.108, so it **does not have the 0.1.111 TENDER work or bug 0.1 yet**.

1. **Version skew is the biggest risk.** A 0.1.108 reader opening a Phase 2 file (an ADD-composed cost value) reports **$0 with no error**. Raise the floor in the same release that changes the writers, and have the plugin read costs only through bimforge (`est-bim schedule-read --costs-out`), never by walking IFC itself.
2. **`read_costs` JSON (cost-load-schedule skill):**
   - `categories` key spelling changes.
   - Estimate-model `costs` keys become bid item numbers.
   - `labor_hours` is sourced from resources.

   The skill reads `costs{code:{cost,labor_hours}}`, `tasks` and `warnings`; update its prose and examples.
3. **`schedule-read` links:** `direction` becomes `"output"` for construction links. Nothing in the plugin keys on it today, but say so in the skill.
4. **Quantity names in code:**
   - `intake/bid_frame.py:15-20,103` hard-codes `GrossVolume`, `GrossArea`, `Length` and `Count` as `measure:`.
   - `takeoff/audit.py:267,323` reads `qtys["GrossVolume"]` then `NetVolume`.

   These keep working only while BIMForge keeps today's names, in `Bimforge_BaseQuantities` or as aliases. Earthworks should prefer `UndisturbedVolume`/`CompactedVolume` once BIMForge writes them, and rebar `Weight`.
5. **`takeoff/audit.py:382-388` `mark_wholes`** assumes a barrier or handrail "whole" has no body and no quantity set. Change it to test `IsDecomposedBy` alone, or BIMForge must guarantee that wholes never get a Qto.
6. **`rebar/ifc.py`** writes `IfcReinforcingBar` with a kg `Weight` in `Qto_ReinforcingElementBaseQuantities`. That is only correct once the file declares MASSUNIT kg (Phase 1). It should also stop relying on the classification system's exact name `"BidSchedule"` (`:79,92`), and adopt IfcReinforcingBarType when BIMForge does. `EPset_Rebar` is not a reserved prefix, but it should be renamed to the house prefix.
7. **Element identity in BidSheet:** class corrections change `ifc_class`/`element_type` in `upsert_modelled_elements`, and the push-takeoff skill must expect a one-time "missing + new" churn. `model_elements` `quantities.*.source` strings change with the Qto rename.
8. **Names matched exactly:** cost schedules `"<name> cost"` / `"<name> bid"`, and the classifications `"Owner bid items"` (tasks) and `"BidSchedule"` (elements). BIMForge will keep writing these names, but the plugin and skills should treat them as labels, not keys.
9. **Private imports:**
   - `schedule/costload.py:14` imports `_bucketize`, `_d`, `_month_key`, `_week_key`, `_workdays`.
   - `schedule/importers.py:10` imports `_looks_canonical`, `_looks_ganttwarrior`.
   - `schedule/xer.py:30` imports `_DATE_SOURCES`, `_SUMMARY_TYPES`, `_XER_WORKDAY_HR`, `_require_positive_hpd`.
   - `schedule/model.py:6` imports `_d`.

   BIMForge should make these public (or the plugin vendors them) before any refactor touches these modules.

## Already compliant (keep)

- Cost and work schedules, calendars and resources are declared to the project.
- IfcRelNests for cost and task trees; root items controlled by their schedule.
- Classification via IfcRelAssociatesClassification.
- No reserved prefix outside the items above; `Bimforge_Task` and `Bimforge_CostItem` are correct.
- IfcAlignment structure: nested layouts, terminators, IfcCompositeCurve/IfcGradientCurve, IfcReferent + Pset_Stationing, IfcRelPositions.
- TrueNorth from grid convergence.
- Representation types; styled items; IfcQuantityCount as integer in families.
- Every element sits in exactly one container; no duplicate GlobalIds.
- Leaving out IfcOwnerHistory is legal in IFC4/4X3; it is only expected by Reference View importers.

## Re-running the checks

The scripts are in the session scratchpad `validate/`, `cost/`, `sched/`, `spatial/` and `qto/` folders: `build_specs.py`, `pipeline.py`, `run_validate.py` and `summarize.py`, plus a pytest plugin `capture_ifc_plugin` that captures every IFC the suite writes. They should be moved into `scripts/ifc_audit/` and run in CI as a gate on where-rule failures and reserved prefixes.
