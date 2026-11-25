# Changelog

Newest first. Versions follow `pyproject.toml`; a tag `vX.Y.Z` releases to PyPI.

## Unreleased

**For ProjectCommand and BidSheet.ai:** `BIMForge_Route` holds the first
`IfcComplexProperty`s BIMForge writes (one per changed value, UsageName
`Difference`); a reader of property sets that expects single values must
skip or read them. `model-elements` sends `route`, `based_on` and
`differences`.

### Added

- **Terrain from a spec (G.9).** A top-level `terrain:` block gives any
  model its existing ground: `{source: dem | lpc, cache, margin_ft,
  spacing_m, vshift_m}`, one IfcGeographicElement TERRAIN from USGS 3DEP
  (the 1 m DEM or the lidar point cloud's bare earth) over the plan extent
  of the model's elements grown by `margin_ft`, cached under `cache` so
  rebuilds are offline. The shift from 3DEP's NAVD88 comes from `vshift_m`,
  else from `project.vertical_datum` (NAVD88 none, NGVD29 by NOAA NCAT at
  the base point), and is written into the provenance with its source
  (`VerticalShiftSource`). The road corridor measures against the same
  ground with `ground: {source: terrain}`; a plane-ground corridor with a
  `terrain:` block keeps its plane levels and carries the fetched ground.
  `est-bim terrain SPEC [--refresh] [--family-path DIR]` fetches the ground
  ahead of the build and reports its footprint, cells, source, vintage,
  quality level, shift and cache files. A cached DEM now records the area it
  was fetched for beside it (`<cache>.json`), and a lidar grid its bbox and
  CRS: a build whose footprint, margin, spacing or CRS has changed fails,
  naming the cache and `est-bim terrain SPEC --refresh`, where it stretched
  the old raster over the new area. A `params.terrain` key is refused.
- **Modified standards are recorded (M.8, M.9).** Every element whose
  family checks it (the B3 wall, the 842 and 732SW barriers) carries
  `BIMForge_Route`: its `Route` (standard, modified-by-value,
  modified-by-part, modified-by-section or bespoke), the class it is
  `BasedOn` (its classification stays the standard's, so a Type 842 (MOD)
  is found as a Type 842), and each value it changed as an
  IfcComplexProperty (UsageName `Difference`) of `Standard`, `Actual` and
  `Source`. The differences come from what the spec says: a project's
  `tables_file` is compared with the packaged tables it names, or its
  family's own (the B3 wall's `caltrans/b3-retaining-wall`), and the build
  log lists every changed value and counts the values it adds; a row the
  project's tables choose where the pack would choose another (a table
  missing rows) is a `Row` difference; a barrier run's Mod dimensions (842,
  732SW) are modified by value, its own `profile` modified by section. A
  bespoke `bimforge.author` element may say what it is `based_on`. An
  element its family does not check (the road corridor, the D-series,
  B11-51) gets no route.
  `gate: {modified: warn | error | off}` (default warn) lists, fails on,
  or ignores modified elements. `model-elements` sends `route`,
  `based_on` and `differences`. The shipped B3 examples' tables differ
  from the 2025 pack in 13 values (rounded Type 1 rows), so their Type 1
  slices are modified by value.

- **Road corridor part C: a shared-use path on its own profile (P.6).** All
  optional (`params.path`); a spec without it builds as before. Held to the
  Caltrans HDM (08/08/2025), Index 1003.1, and the USFS Equestrian Design
  Guidebook (2007) as guidance:
  - the path is part of one side of the road's section while it is beside
    the road: its paved edge `separation` ft from the road's outer edge of
    shoulder (5 ft at least - up to a path gap's 1 ft transition foot, so a
    row inside the gap cannot hide a narrowing beside it - narrowing to the
    deck's 1.5 ft over `approach_ft` each side of a bridge, where it must
    meet the deck within 0.01 ft), on the profile the spec gives, its courses held normal to its
    own grade; cut, fill and walls are one earthwork over the whole section,
    counted once, and a course's `Volume = PathLength * Width * Thickness`
    holds across curve ends;
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
    between, its footprint never crossing the road's, its profile carrying
    the path's grade on at both ends (both along the path's centreline, so
    on a road curve path.profile's per-station grade over 1 - kappa u), its
    radius (at 20 or 30 mph, `design_speed_mph`), grade and crest checks and
    its runs followed along the path's own length;
  - `outputs.path` lists the path by road station (an own stretch's
    hand-over and rejoin rows note it, `own <n> hand-over` / `rejoin`; a
    strip with no slope or flatter than 100:1 is `level`; the barrier is
    `rail` where the road's guardrail or a `wall-road` strip wall's barrier
    stands, and no barrier-needed check is listed there);
    `outputs.path_checks` lists
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
  `wall-path`; `outputs.structures` gains `carries` (`road` or `path`) and
  `location` (as the walls table's), the last two columns. The road-corridor
  example gains a path on the right; its GlobalIds were
  re-recorded.

### Changed

- The road corridor's `ground: {source: 3dep, cache, spacing_m, margin_ft,
  vshift_m}` is now read as `terrain:` plus `ground: {source: terrain}`,
  with a build-log note; the old and the new form give the same IFC. It
  takes its shift from `project.vertical_datum` when it gives no
  `vshift_m`: an NGVD29 project now gets the NCAT shift where it got 0, and
  a spec with no `vshift_m` and no or an unrecognised
  `project.vertical_datum` now fails, "has no rule; give terrain.vshift_m",
  where it built with a shift of 0. An old-form corridor whose footprint has
  changed since its fetch now fails, naming the cache, where it built. Its
  IFC differs from 0.1.132's in the provenance: a rebuild now records
  `VerticalShiftSource` and the work-unit fields, so the first rebuild after
  upgrading makes one work-unit lookup.
- A DEM cache made by 0.1.132 has no record of its area and is checked only
  by its size: a footprint shifted by the same size is not caught. `est-bim
  terrain SPEC --refresh` fetches it again and writes the record.
- `est-bim terrain --refresh` (or `refresh=True`) fetches every cache again:
  the DEM, the NCAT shift (whose cache for another base point now fails) and
  the work-unit vintage, which is no longer cached when the index does not
  answer. On lidar it re-bins the LAZ tiles on disk and downloads only the
  missing ones; a cached lidar grid that covers the footprint is used as it
  is.

### Fixed

- `est-bim add-alignments` (`bim.add_alignment.add_alignments`) crashed on
  a profile with two PVIs (no vertical curve): it is written as one
  gradient.

- **An element is stationed on the alignment it lies along.** With a short
  second alignment (an own path stretch's), an element along its extension
  went to it - `locate_many` clamps a point past an end and keeps only its
  square offset - and was stationed at its end station (`0+00.00` to
  `0+00.01`): the path, tread, fence, rails and road fill beside the road
  before the hand-over and after the rejoin. The linear reference (the
  build's and `est-bim stations`) now ranks the alignments by true plan
  distance (past an end, the distance to it), and an element mostly past
  the nearest one's end goes to an alignment it lies along only if that is
  within twice the nearest distance, or the nearest plus the element's own
  plan extent. So an element just past a short alignment's end - an
  approach slab or a wingwall past a bridge's - stays on it, stationed at
  its end, rather than going to a crossing road it lies along farther off.

- **`station()` rounds before it splits,** so 1299.999999 ft is `13+00.00`,
  not `12+100.00`. A negative station prints its sign in front of the
  rounded value: -50 ft is `-0+50.00` (it was `-1+50.00`, the hundreds
  floored), and -0.001 ft is `0+00.00` (it was `-1+100.00`).

- **Road-corridor earthwork follows the leaning section rays.** A corridor
  section stands square to the road's 3D tangent, so a point v up sits
  v sin(grade angle) back along the line; earthwork columns stood
  vertically over plan triangles folded over at short bays on a grade (a
  wall's 1 ft lead-in, a path's 1 ft end transition), leaving the body not
  closed and the volume over-counted (54 % off the post gate for a fill wall
  on 7 %). Columns are now triangulated in station and offset and run along
  each corner's section ray to the ground. Earthwork volumes move: +0.09 % on
  the V1.1 example (now the test fixture; 1,008,083.5 to 1,009,008.4 cf),
  +0.03 % on V1, with the mass haul. The earthwork's plan
  rings come from its ground corners, for cut as well as fill, and MaxDepth /
  MeanDepth shift slightly (V1.1's last fill band: MaxDepth 22.6011 to
  22.5600 ft).

## 0.1.132 — 2026-11-22

The road corridor (P.6): pavement courses, cut and fill to daylight and mass haul (#118), then slope rules, automatic walls, guardrail and dimensions with arithmetic formulas (#122). `model-elements` now sends each element's measurement checks and, with `--checked-takeoff`, the takeoff's sum (#121), closing M.6's check.

**For BidSheet.ai:** a `model-elements` element may carry `checks` (a list, each with `what`, `unit`, `sheet_value`, `model_value`, `value_now`, `tolerance`, `result`, `standing`, `value_source`, `sheet`, `revision`, `day`, `by`, `model_origin`; a key with no value is left out) and the call may carry `takeoff_check`; both are left out when empty. Only `standing` `agrees` is a check that still holds.

**For ProjectCommand and BidSheet.ai:** quantity `Formula`s are now
arithmetic (`+ - * /`, numbers, parentheses) and may name the element's
`BIMForge_Dimensions` properties, so a reader that recomputes formulas must
evaluate the wider grammar and look names up in the quantity's own set first,
then in the element's dimensions; it should also cap a formula's length
(1,000 characters) and refuse a result that is not finite. Road-corridor
elements carry `StartStation` / `EndStation` dimensions (lengths, with
`StartStationText` / `EndStationText` labels); `BIMForge_LinearReference`
keeps its own `StationStart` / `StationEnd`. A corridor `Offset` is the
centroid's, left positive, as the linear reference's offsets are.

### Added

- **Road corridor V1.1: slope rules, walls, guardrail, dimensions (P.6).**
  Held to Caltrans practice (HDM 08/08/2025, TSSM April 2025, 2025 Standard
  Plans A77N2 and A77N3):
  - a fill rule that switches to a steeper slope above a fill height
    (`fill.steep`, e.g. 4:1, then 2:1 above 10 ft); a cut that runs through
    the soil, then a bench and a rock face below a depth that may vary by
    station (`cut.rock`, e.g. 2:1, then 0.5:1); an optional footprint line
    per side (`footprint_ft`);
  - `walls: auto` (the only value `walls:` takes) places a wall wherever a slope finds no daylight or runs
    past the footprint: a fill wall at the hinge carrying a barrier, a cut
    wall beside a shoulder widened to 10 ft; a fill wall taller than
    `max_wall_height_ft` becomes a structure candidate (a short bridge or a
    culvert). `outputs.walls` and `outputs.structures` list them;
  - guardrail (MGS) on every 2:1 fill and at both ends of each structure gap,
    by the TSSM length of need for each direction of travel, in whole 12.5 ft
    elements with a 150 ft minimum, joined where runs are 200 ft or less
    apart, ending in terminals, Type AGT transitions at bridges and walls, or
    SFT-M anchors; the 10:1 widening behind the rail runs its whole length.
    Each run is an `IfcRailing` typed GUARDRAIL with its length, posts and
    end treatments; `outputs.guardrail` lists them and flags a run under
    150 ft or cut short by the alignment's end;
  - courses, cut, fill and guardrail carry `BIMForge_Dimensions` from new
    family-dictionary classes. Every element's `Length` has the Formula
    `EndStation - StartStation`. A course's declared volume is now exact
    (its section times the path its centroid travels, along plan and grade),
    and `Volume = PathLength * Width * Thickness` (or the trapezoid through a
    taper) is written wherever it holds within the formula check's tolerance.

  The shipped example uses them all and adds a `RAIL-MGS` pay code (no item
  number); its GlobalIds were re-recorded. Other examples are unchanged.
- **The `road-corridor` family (P.6).** A road from an alignment, a
  profile, a typical section and the ground:
  - pavement courses are `IfcCourse` elements typed by `IfcCourseType`,
    written as `IfcSectionedSolidHorizontal` along the alignment on IFC4X3
    (a closed mesh on IFC4), under `IfcRoad` > ROADSEGMENT > CARRIAGEWAY /
    SHOULDER / CENTRALRESERVE;
  - cut and fill run to daylight, with an optional ditch, as
    `IfcEarthworksCut` and `IfcEarthworksFill`, one of each per station
    band; on IFC4X3 every cut voids the TERRAIN element;
  - superelevation, width transitions, and gaps for bridges and walls;
  - a mass-haul table, in a `BIMForge_MassHaul` property set on each band's
    earthwork and as a CSV (`outputs.masshaul`, in CY), with shrink and
    swell; the set's `StartStation` / `EndStation` are `IfcLengthMeasure`
    and `CumulativeVolume` an `IfcVolumeMeasure`, in the file's metres as
    `BIMForge_LinearReference` writes stations, with `StartStationText` /
    `EndStationText` ("14+00.00");
  - ground is a plane (tests and CI, which write a TERRAIN surface too) or
    3DEP over the corridor's footprint, cached.

  Each course's volume is checked against an independent average-end-area
  figure, within 0.5%. The shipped example `road-corridor.spec.yaml` joins
  the conformance set and the buildingSMART rules job.

- **`Element.standard_qto`: a class's standard quantity set**
  (`Qto_CourseBaseQuantities`, `Qto_EarthworksCutBaseQuantities`, ...),
  written beside `Qto_BaseQuantities` and only on the class it belongs to
  (M.17's first step). Where a name is in both, takeoff keeps reading
  `Qto_BaseQuantities`, so no takeoff number changes.

- **`model-elements` sends each element's measurement checks (M.6, M.5).**
  An element with a check (ProjectCommand's or `est-bim check`'s) carries
  `checks`: what was measured (`<set>.<name>`), the sheet value, the model
  value it was checked at and the file's value now, in FT (the project's
  foot), SF or CY, the tolerance, the result as recorded, the sheet,
  revision, day, who and the model it was checked on, and its `standing`
  as ProjectCommand reads it: the result, or `lapsed` when the file's
  value has moved past the tolerance since (a rebuild that changed it), or
  `gone` when the element no longer has what was checked.
  `--checked-takeoff takeoff.json` also sends that takeoff's sum checked
  against the model, as the call-level `takeoff_check`. Additive: BidSheet.ai
  ignores both until it stores them.

### Changed

- **Quantity Formulas are arithmetic.** A `Formula` may use names, numbers,
  `+ - * /` and parentheses (parsed, never evaluated as code), over the
  quantity's own set and then the element's `BIMForge_Dimensions` numbers,
  on `Qto_BaseQuantities` and on standard sets alike. A formula longer than
  1,000 characters, one that cannot be read, or one whose result is not
  finite fails only its own quantity. `BIMForge_Dimensions` may hold text
  (`IfcLabel`, not sent as a parameter) and optional properties.

### Fixed

- **3DEP terrain on a feet CRS.** The terrain module sent the bounding box
  and grid spacing to 3DEP in the CRS's own unit but scaled plan and height
  by one factor, so it only worked on a metric CRS. `grid_to_mesh` and
  `attach_terrain` take an optional `plan_scale`; existing callers are
  unchanged.

- **An uncarved terrain is declared a surface,** so the solid-body check no
  longer reports its rim as open edges.

- **The terrain's mesh spacing names its unit.** `Pset_BimforgeTerrain`
  gains `MeshSpacingUnit` (the CRS's: `ftUS`, `ft` or `m`), and the build
  log gives the spacing in it, not always "m".

- **A facility on an alignment is positioned on it.** `IfcRelPositions`
  now lists the `IfcRoad` (or other facility) as well as its elements.


## 0.1.131 — 2026-11-22

The check is recorded (M.5): every takeoff carries its sum checked against the model (#116), and `est-bim check` records a measurement made in Bonsai in the model, in ProjectCommand's shape (#117). A measurement check now comes through a rebuild whole.

**For ProjectCommand:** a check written by `est-bim check` is the shape your `check.rs` writes, stamped with the application it was made in (`--app`, default Bonsai); recording one again replaces yours under its GlobalIds. A rebuild now carries the `Checked` IfcResourceApprovalRelationship, so a check reads back whole after `carry_forward`.

**For estimating_tools and BidSheet.ai:** the takeoff JSON gains a top-level `check`; `CanonicalTakeoff.from_json` ignores it. Rows are unchanged.

### Added

- **Every takeoff records its sum, checked against the model (M.5).**
  `est-bim takeoff` writes a top-level `check` into the takeoff JSON
  (CanonicalTakeoff readers ignore it): the model's `build_id`, each row's
  quantity beside its elements' sum (`basis` "sum", or "stated" for a lump
  sum or `count_as` row), and the result. It fails when a row does not add
  up to its elements, an element is in a row twice, or a classified element
  with quantities is in no row; each failure is a review line.
  `est-bim takeoff-check --takeoff t.json --ifc model.ifc` re-checks a
  takeoff written earlier against a rebuilt model, by GlobalId: an element
  whose value moved or that is gone fails the rows it backs, and the
  command exits 1.
- **`est-bim check` records a measurement made in Bonsai in the model
  (M.5),** in the shape ProjectCommand writes and reads (its `check.rs`):
  an IfcObjective of `SheetValue`, `ModelValue` and `Tolerance` metrics
  naming what was measured by set and name, an IfcApproval with Level
  `measurement` and Status `agrees` or `differs`, and the sheet as
  IfcDocumentInformation, stamped with the application the check was made
  in so a rebuild carries it. `--what` is a quantity
  (`Qto_BaseQuantities.GrossVolume`) or a property
  (`BIMForge_Dimensions.DesignHeight`); values are given in `--unit` (a
  foot is the project's foot) and written in the file's units; without
  `--measured` the file's own value is checked. Recording the same thing
  again replaces the check under its ids, whoever recorded it. `--list`
  lists every check a model carries.

### Fixed

- **A measurement check carried through a rebuild keeps its link (M.5).**
  `carry_forward` dropped the IfcResourceApprovalRelationship that ties
  ProjectCommand's check approval to its objective (the sheet value, model
  value and tolerance), since nothing references it. It is now copied when
  both ends come across, so a carried check reads whole and a reader can
  call it lapsed.

## 0.1.130 — 2026-11-21

What the model says about each element now goes to BidSheet.ai with its quantities (M.6, #114), and buildingSMART's alignment checks run in CI (C.12, #113). No file BIMForge writes changes.

**For BidSheet.ai:** `upsert_modelled_elements` payloads from `est-bim model-elements` gain optional keys: per element `family_class`, `class_uri`, `type_name`, `standard_plan`, `parameters` and `linear_reference`, per quantity `formula`, and per call `model` (keyed on `build_id`). All are additive; they are ignored until BidSheet.ai stores them (its rows 5.16 to 5.19).

### Added

- **buildingSMART's alignment checks run in CI (C.12).**
  `gate.alignment_issues` holds a file to the checks buildingSMART's IFC4.3
  sample models pass:
  - every alignment layout ends with a zero-length segment;
  - every IfcAlignment is aggregated to the IfcProject;
  - every distance along a curve is an IfcLengthMeasure.

  The conformance suite runs it on every file it writes, beside the schema
  check, and the `add-alignments` tests run it on what that command writes.
  The examples' alignment already passed; nothing written changes.
- **`est-bim model-elements` sends what the model says about each element
  (M.6).** Beside its quantities, an entry now carries, when the file has
  them: `family_class` and `class_uri` (the dictionary class, M.1),
  `type_name`, `standard_plan`, `parameters` (`BIMForge_Dimensions`, M.2,
  {Code: {value, unit}}, lengths in FT of the project's foot, ratios as
  RATIO) and `linear_reference` (alignment, stations and offsets in FT); a
  quantity carries its `formula` (M.3). The call carries `model`, the
  file's identity (`build_id`, `bimforge_version`, `ifc_schema`, `source`).
  Every key is optional and BidSheet.ai ignores keys it does not store, so
  old and new payloads are both valid; BidSheet.ai storing them is its own
  change (its rows 5.16 to 5.19). Named `parameters`, not `dimensions`,
  which a BidSheet.ai takeoff element already uses for "measured from
  dimensions". A parameter, station or offset that is not finite in feet
  (a broken export) is left out with a warning, so the payload stays valid
  JSON.

## 0.1.129 — 2026-11-20

The B3 wall's sizing dimensions (M.2, #109) and how each of its volumes was derived, checked on the written file (M.3, #110). With M.1 in 0.1.128, the B3 wall's part of Stage 1 is done.

**For ProjectCommand and BidSheet.ai:** each B3 stem and footing slice now carries a `BIMForge_Dimensions` property set (`DesignHeight`, `StemThickness`, `StemBaseThickness`, `Batter`, `ToeWidth`, `HeelWidth`, as its class declares), whose names are the family dictionary's Codes and stable; and its `GrossVolume` has `Formula = "Length * Width * Height"` over its own quantity set. No GlobalId moves.

### Added

- **The B3 wall's sizing dimensions are written on each slice (M.2).** A
  property set `BIMForge_Dimensions` whose properties and measures come from
  the family dictionary, so "design height" is one property on every job:
  every slice has `DesignHeight`; a stem has `StemThickness` (and, battered,
  `StemBaseThickness` and `Batter`, a ratio); a footing has `ToeWidth` and
  `HeelWidth`. Lengths are IfcLengthMeasure in the project unit. What is a
  quantity (length, width, height, volume) stays in the quantity set. A
  class declares its dimensions and the build fails on an element missing
  one or carrying an undeclared one (`Element.dimensions`,
  `family_dictionary.dimensions`). Written after the GlobalId sweep, keyed,
  so no GlobalId moves.
- **A quantity says how it was derived (M.3).** A family declares how an
  element's volume was found (`Element.volume_formula`), and its
  `GrossVolume` is written with that `Formula` over names in the same
  quantity set: `box` is `Length * Width * Height`, `section` is
  `CrossSectionArea * Length` (the section area is then written as
  `CrossSectionArea`), and `solid` writes none. Every B3 stem and footing
  slice is a box. A new post-build check recomputes every formula from the
  written file and fails the build, deleting the outputs, when one is more
  than 1e-6 (relative) off its quantity or names a quantity the set does
  not have (`gate.FORMULA_TOLERANCE`, `gate.formula_value`); a formula over a
  quantity the element will not have is refused at build time, naming it.
  Elements of the other families carry no formula until their family
  declares one. No GlobalId moves.

## 0.1.128 — 2026-11-18

The retaining wall typed from the dictionary (X.4, X.6, #105), every typed element's family class (M.1, #106), material layer sets on the constant-thickness B3 stems (X.6, #108), and a fix to `federate(merge_facilities=True)`, which re-keyed a folded facility on 0.1.127.

**For anyone who federated on 0.1.127 with `merge_facilities`:** rebuild on 0.1.128. A facility and its parts whose GlobalIds moved get their 0.1.126 GlobalIds back.

**For ProjectCommand and BidSheet.ai:** typed elements now carry a second IfcClassificationReference, to their family class, under an IfcClassification named `bimforge families`. It is not a pay code: bimforge's pay readers skip it, and so should any reader that keys pay items on element classifications.

### Added

- **Every element of a typed family references its dictionary class
  (M.1).** An IfcClassificationReference with the class's Code as
  Identification ("retaining-wall-b3-type-1"), its Name, and its bSDD URI
  as Location, under one IfcClassification `bimforge families` (Source
  `bimforge`, Edition the dictionary version, the dictionary URI as its
  Location/Specification): the B3 walls and footings, the barrier runs and
  bodies, the B11-51 handrailing and its parts, the D90 guardrail, and
  every sized reinforcing bar. A reader gets the class without matching a
  type name's prefix: `ifc_takeoff.family_class_of(element)`. Written after
  the GlobalId sweep, the relationship keyed by its reference, so no
  GlobalId moves.

- **The B3 retaining wall is typed (X.6).** Every stem slice is an
  IfcWall/RETAININGWALL of an IfcWallType named for its wall type
  ("Retaining wall Type 1"), every footing slice an IfcFooting/STRIP_FOOTING
  of an IfcFootingType ("Retaining wall Type 1 footing"), and both carry the
  B3 sheet they are built to as `Pset_WallCommon.Reference` /
  `Pset_FootingCommon.Reference` (B3-1A, B3-3A, B3-4A, B3-7A). The family
  dictionary has a class for each of the five wall types and its footing.
  A reader groups a run's slices by type instead of by name.
  No GlobalId moves: the types and sets are written after the sweep that
  numbers the file's other roots, each keyed (`Element.typed_late`,
  docs/globalid-contract.md), as the bar types are.

- **The constant-thickness B3 stems carry a material layer set (X.6).**
  Types 1A, 6A and 6B, both stem faces vertical, are written as IFC's "wall
  with material layer set usage": the wall type has a one-layer
  IfcMaterialLayerSet of its concrete at the stem thickness, each slice an
  IfcMaterialLayerSetUsage of it (AXIS2) and an 'Axis' polyline, and the
  slice is placed in its own frame along that axis (where it sits is
  unchanged, to the vertex). The battered stems (Types 1 and 5) and every
  footing keep a plain IfcMaterial: IFC writes a battered or L-shaped
  retaining wall without a layer set, and has no tapered wall layer
  (IfcMaterialLayerWithOffsets offsets a layer's edges, not its thickness;
  the tapering usage is for beams and columns). IfcFooting has no layer
  set concept, and a Type 1 footing's thickness changes with its design H.
  `Element.layer_thickness_ft` asks for it. New example
  `caltrans-b3-wall-types`: one wall of every type on a skewed tangent, so
  conformance and buildingSMART's rules see every wall class.

### Changed

- **Pay readers skip the family class.** `classifications_of` (the
  takeoff, `estimate5d`, `model-elements`, the takeoff workbook, the web
  contract, the 4D schedule) and the GIS export's cost code leave out
  references under `bimforge families`. The takeoff IDS applies its
  classified-element rules to every system but that one.

- **Families read their names from the dictionary (X.4).** The type names
  and standard-plan references of the barriers, the B11-51 handrailing and
  the D90 pipe guardrail come from `bimforge-families.bsdd.json` through
  `bimforge.author.family_dictionary`, not from literals in each family.
  What is written is unchanged. `BarrierTemplate.standard_plan` is gone: the
  plan is the dictionary class's, by `family_id`.

### Fixed

- **Folding one facility from several sources keeps the first source's.**
  `federate(merge_facilities=True)` kept whichever facility came first among
  the site's children, an order that follows entity numbers, so a source
  that wrote fewer entities (0.1.127's mesh weld) could hand the fold to a
  later source and give the facility and its parts new GlobalIds. It now
  keeps the first source's, as documented; files federated on 0.1.126 get
  their GlobalIds back.

## 0.1.127 — 2026-11-18

Conformance as a standing gate on IFC4 too (C.7, #101), the inventory of what each command writes (C.9, #102), the model's identity (M.6, #103), mesh conformance (GEM001, GEM111) and fast output links (#64).

**For ProjectCommand and BidSheet.ai:** this is the first release that writes `BIMForge_Model.BuildId` on the IfcProject. Models built earlier have no set. The estimating plugin's floor need not move.

### Added

- **The model names itself (M.6).** Every file `est-bim build`, `dxf2bim`
  and `federate` write carries `BIMForge_Model` on its IfcProject:
  `BuildId` (sha256 over the canonical source, the bimforge version and the
  schema), `BimforgeVersion`, `Schema` and `Source`. The source is what the
  build reads, parsed: the spec and the files it names, without its output
  paths; dxf2bim's layer map and the features read from the DXF; a
  federation's sources' BuildIds. So the same source gets the same id on any
  machine and after any rebuild, and the embedders leave it alone. A model
  emitted with no source named is identified by the file itself
  (`bimforge.bim.model_identity`).
- **An inventory of what each command writes (C.9).** `docs/ifc-inventory.md`
  lists the entity types, property sets and quantity sets (with their
  properties and the classes they apply to) that `build`, `dxf2bim`,
  `schedule`, `cost5d`, `estimate-model`, a carried rebuild and `federate`
  write, on IFC4X3 and IFC4, generated from the conformance suite's files by
  `scripts/ifc_inventory.py`. CI fails when a writer starts writing something
  the inventory does not hold.
- **Conformance on IFC4 too, and on a carried-forward rebuild (C.7).** The
  conformance suite builds every example on IFC4 as well as IFC4X3, runs the
  4D, cost, estimate, dxf2bim and federate writers on both, and checks a
  schedule rebuild with a downstream update carried onto it. All pass the
  schema's rules, and buildingSMART's rules find nothing beyond the three
  listed kinds.

### Changed

- **A downstream tool may rewrite what it added itself.** The returned-files
  contract (`docs/globalid-contract.md`) keeps "never modifies an entity of
  ours" and now lets the tool replace or remove its own additions: one
  update instead of a pile, a kept update retyped BASELINE, approvals changed
  or withdrawn. `carry_forward` already carried these unchanged; tests now
  pin a MODIFIED update and a kept BASELINE beside the current one.

### Fixed

- **An open mesh is a surface, and a mesh's near-duplicate corners are one
  (#103).** A `mesh` that is not closed (terrain, a measured surface) was
  written as a closed faceted brep, its rim edges each on one face
  (buildingSMART's GEM001); it is now an IfcTriangulatedFaceSet with
  `Closed=False`. A boolean's corners microns apart were written as two
  points one loop holds (GEM111, under the context's 1e-5 m precision); they
  are welded, and the slivers and flattened fins that leaves are dropped, so
  a closed mesh stays closed.

- **Linking a task to many elements is fast again** (follow-up to #60). The output
  links are written once per element by `schedule4d.link_outputs`, not once per
  task-element pair through `sequence.assign_product`, which looked through the
  task's assignments on every call. One task on 4,000 elements took 33 s after #60
  (3.4 s before it) and now takes 0.2 s. The relationships written are the same.

## 0.1.126 — 2026-11-17

IFC compliance audit Phase 2 (roadmap C.5): relationship semantics; and buildingSMART's normative rules in CI (#94).

**For the estimating plugin:** raise the floor to `bimforge>=0.1.126`. An earlier bimforge reads a 0.1.126 cost5d file's task `labor_hours` as null, since it looks for crews only through IfcRelAssignsToResource; per-code hours and estimate-model hours are unaffected.

### Added

- **The CI checks buildingSMART's normative rules (#94).** `validate`, the build
  gate and a new conformance suite check the schema's WHERE and global rules
  on every kind of file bimforge writes (`est-bim validate --no-rules`
  keeps the attribute-only check). A `bsi-rules` CI job runs buildingSMART's
  ifc-gherkin-rules, at a pinned commit, on the same files and fails on any
  finding that `scripts/bsi_baseline.yaml` does not list with its reason.
  Three kinds are listed: QTY001 (the generic Qto set, C.6), ALS016 (plan-rounded
  arc lengths, a warning) and GRF005, where the rule inverts the map
  conversion's Scale.
- `bimforge.bim.materials.governing_material(element)`: the IfcMaterial that governs an element or its type, through an IfcMaterialLayerSetUsage or IfcMaterialProfileSetUsage, a layer, profile or constituent set (its first member) or a list. The developed views' cut layers use it, so they keep naming the material once X.5 and X.6 write sets.
- `schedule_read.crews_of(task)`: the resources assigned to a task, by either relationship below.

### Changed

- **Crews are assigned to tasks with IfcRelAssignsToProcess**, the task relating, in `cost5d` and `estimate-model`; it was IfcRelAssignsToResource (the crew relating). `read_costs` reads both, so earlier files read the same hours. A tool that copies a task's process assignments (ProjectCommand's schedule update) now carries the crew along. A re-embed removes the old crews' assignments with them (ifcopenshell's `remove_resource` leaves process assignments behind). The 4D readers (`task_elements`, element start dates, appear and vanish spans) skip resources among a task's process inputs.
- `read_costs` and the web contract find a work schedule's cost schedule by type and link: a BUDGET or ESTIMATE schedule declared to the project whose cost items control its tasks, whatever it is named. The name "<ws> cost" and the estimate-model marker remain the fallbacks. The error for none or several now says which.
- The web contract reads bid items (`BidSheet_EstimateItem`) only from ESTIMATE cost schedules.

### Fixed

- **A typed occurrence's PredefinedType is unset, not NOTDEFINED.** 0.1.125
  wrote NOTDEFINED on an occurrence whose type carries the predefined type.
  IFC's CorrectPredefinedType has it unset ("e.g. because a type is
  associated"), and buildingSMART's OJT001 refuses NOTDEFINED there. A
  reader still resolves it through the type
  (`ifcopenshell.util.element.get_predefined_type`).
- **A crest vertical curve's radius is negative.** IFC4.3 signs
  `IfcAlignmentVerticalSegment.RadiusOfCurvature` (positive turns
  counter-clockwise, so a sag; negative clockwise, so a crest), and
  buildingSMART's ALB012 checks it as HorizontalLength / (EndGradient −
  StartGradient). The alignment writer wrote every radius positive.
- **`federate` leaves nothing stranded on the storey path.** Each source's own
  site/building/storey placements, and each merged context's
  WorldCoordinateSystem and TrueNorth, were left in the file referenced by
  nothing (buildingSMART IFC106). Only the facility path cleaned up placements.
- **The sample layer map's wall is `SOLIDWALL`.** `STANDARD` is deprecated in
  IFC4.3 (buildingSMART IFC102).

## 0.1.125 — 2026-11-16

IFC compliance audit Phase 1 (roadmap C.4): additive compliance.

### Added

- The project calendar ("<schedule> calendar") controls the root tasks through IfcRelAssignsToControl, with a stable GlobalId; a root on a named calendar keeps only that one.
- P6 XER actual dates (`act_start_date` / `act_end_date`) are carried as `actual_start` / `actual_finish` and written to IfcTaskTime ActualStart / ActualFinish; `schedule-read` returns them.
- **Units:** emitted and dxf2bim IFCs declare MASSUNIT kilogram and PLANEANGLEUNIT radian. cost5d's StandardWork hours are declared as hours (a project TIMEUNIT, or the quantity's own Unit in a file that keeps its own). The currency every cost writer declares is configurable (`--currency` on cost5d, estimate5d and estimate-model; default the file's, else USD), and a conflicting currency is refused.
- IfcProjectedCRS.VerticalDatum comes from a compound EPSG CRS when the spec gives none.
- `estimate5d --submitted-on YYYY-MM-DD` writes the TENDER's SubmittedOn. BUDGET and ESTIMATE cost schedules carry Status PLANNED, as TENDER already did.
- **Element typing:** family elements carry IFC PredefinedTypes: PIERCAP and PIERSTEM bents, RETAININGWALL retaining walls and wingwalls, APPROACH_SLAB, STRIP_FOOTING and PAD_FOOTING footings, MAIN and LIGATURE bars by mark. Values IFC4 lacks are written USERDEFINED with the value as ObjectType.
- Sized bars are typed to one IfcReinforcingBarType per size ("Reinforcing bar #5") with NominalDiameter, CrossSectionArea and BarSurface, and every IfcTypeObject is declared to the IfcProject, in a federated file too (`federate` declares the types it carries to its own project). No existing GlobalId changes; `test_example_globalids` pins every example's ids.
- IfcClassification carries Source: paycodes `source:` (new, optional) or a dxf2bim rule's `source`, else the known publisher (CSI/CSC, ASTM E1557, NBS; "Project pay codes" for the default BidSchedule). dxf2bim classification rules also accept `edition`.

### Changed

- **ObjectType only with USERDEFINED** (#77): an `object_type` with no predefined type is written PredefinedType USERDEFINED, and one beside any other predefined type is refused. A typed element's type carries USERDEFINED with the ElementType, and the occurrence is NOTDEFINED. The IFC4 downgrade writes USERDEFINED. Every family proxy names what it is (BOX_CULVERT_BARREL, GROUT_PAD, TREATED_PERMEABLE_BASE, APPURTENANCE).
- Task ScheduleStart is written at 08:00 and ScheduleFinish at 17:00 instead of midnight, so a one-day task is a working day long; a single-date milestone has zero length. Dates and durations read back unchanged.
- `est-bim estimate-model` writes its tasks with PredefinedType CONSTRUCTION instead of NOTDEFINED.
- `federate` also refuses sources whose MapConversion or CRS differ from each other (including a georeferenced source beside an ungeoreferenced one, or a different OrthogonalHeight), naming both; `georef_check=False` turns this off with the per-source check below.
- `add_declared_cost_schedule` takes `submitted_on` beside 0.1.124's `update_date`; UpdateDate is `update_date`, else `submitted_on`, else unset.
- `add-alignments` aggregates the IfcAlignment to the IfcProject and references it into the IfcSite (IFC4.3 CT 4.1.4.1.1), as emit_ifc and federate do; it was aggregated under the site.
- The IFC4 golden digests are re-recorded under ifcopenshell 0.9.0.post1, so they run in CI again instead of skipping.

### Fixed

- **A georeference base in the wrong unit for its CRS is refused.** #58 checks
  `IfcMapConversion.Scale` against the CRS unit, but metre Eastings/Northings
  under a US-survey-feet zone keep Scale right and still put the model ~1,480 km
  off the coast. `emit_ifc` and `dxf2bim` now refuse a base that falls outside
  the CRS's area of use but inside it in another unit, and say which unit the
  numbers fit (`cad.geo.check_base_in_crs`). A base outside the zone in every
  unit, such as a local test base, only warns; (0, 0) is skipped.
- **`federate` refuses a source on another georeference.** The federated file
  takes its map conversion from the ctx alone, so a source written on another
  CRS, base, Scale or rotation was placed wrong with no error. Pass
  `georef_check=False` when that is deliberate.

## 0.1.124 — 2026-11-15

### Fixed

- A cost schedule's UpdateDate is no longer the clock. ifcopenshell stamps it
  with the current time, so `est-bim cost5d`, `estimate5d` and `estimate-model`
  wrote a different file on every run of the same source.
  `add_declared_cost_schedule` takes an `update_date` from the caller and
  otherwise leaves it unset, like the work schedule's CreationDate (#83).

## 0.1.123 — 2026-11-15

### Added

- **`bimforge.caltrans`: the Caltrans Standard Plans tables ship in the wheel.**
  The 2025 B3, D80, D84, D89 and D90 tables are package data
  (`caltrans.load_table("d89-pipe-headwall")`), so a spec names them instead of
  carrying a copy: `params.tables_pack: caltrans/2025/d89-pipe-headwall`, or a
  list of them. A spec's own `tables_file` now merges over the packaged tables,
  mapping by mapping, so it holds only the project's rows.

### Changed

- The tables moved from `data/caltrans-2025/tables/` to
  `bimforge/caltrans/tables/2025/`. `data/caltrans-2025/` keeps the sheet
  manifest. The catalog tests no longer skip on an installed wheel.

### Fixed

- `est-bim schedule --returned` copies each typed value in a select as written
  (#83). An IfcDuration lag, or an IfcLabel or other measure a property holds, has
  no instance id, and 0.1.122 cached its copies by that id, so every such value
  became the first one copied: a returned file's lags all read alike. Rebuild any
  file carried with 0.1.122.

## 0.1.122 — 2026-11-15

### Added

- **Carry a returned IFC's additions through a rebuild** (#83). `est-bim
  schedule --returned <file>` rebuilds the schedule from the source, then
  copies what another application added to the returned file onto it, with
  its GlobalIds: its own work schedule, its links to our tasks and elements,
  approvals and progress. An addition is anything whose IfcOwnerHistory
  names another application. Anything it points at of ours is re-pointed by
  GlobalId (`bimforge.bim.carry_forward`). A JSON report lists, both ways,
  what no longer lines up: additions whose target is gone, our tasks and
  elements no downstream task covers, and our entities the returned file
  changed, which are rebuilt from the source. A file from another project
  is refused. The model is in `docs/globalid-contract.md`.
- **A schedule type** (#37): the canonical schedule's `schedule_type`
  (BASELINE, PLANNED or ACTUAL), or `est-bim schedule --schedule-type`, sets
  IfcWorkSchedule.PredefinedType, and `schedule-read` reads it back.

### Changed

- `est-bim schedule` writes the IfcWorkSchedule as PLANNED, not NOTDEFINED,
  when the source names no type. Its CreationDate is the schedule's start
  date, not the time of the run, so a rebuild writes the same file.

## 0.1.121 — 2026-11-15

### Changed

- **A spec giving `project.epsg` with a zero base point is refused** (audit 0.7). E=0, N=0 georeferenced the model to the CRS's false origin with TrueNorth about 13° off. Set a real base, drop the EPSG for a local model, or set `project.allow_zero_origin: true` to keep it on purpose. The 732SW, 842 and tubular-handrail examples now use a real base point.
- **KML staging matches elements by GlobalId through `schedule_state.element_spans`** (audit 0.8). An element touched only by tasks of other types (OPERATION, LOGISTIC, …) no longer gets a TimeSpan.

### Fixed

- `federate` no longer orphans the real IfcBuildingStorey entities (WR41): it removes only the placeholder storey from the Building→storeys IfcRelAggregates instead of deleting the whole relationship (audit 0.2).
- An alignment sweep with no vertical profile runs on a flat IfcGradientCurve over the horizontal curve, so IfcSectionedSolidHorizontal passes `DirectrixIs3D` and keeps its exact geometry (audit 0.3).
- IfcAnnotation has an ObjectPlacement relative to its container, fixing `PlacementForShapeRepresentation` (audit 0.4).
- Negative task-sequence lags are written as ISO 8601 `-P1.5D` (was `P-1.5D`, which read back as 0); files with the old form still read correctly (audit 0.5).
- KML staging: elements on DEMOLITION/REMOVAL tasks stand until the removal date and disappear then (an end-only `<TimeSpan>` when nothing builds them), instead of appearing on it (audit 0.8).
- `dxf2bim` refuses IFC2X3 by name before reading the DXF, instead of crashing in `create_owner_history`; the example layer map no longer offers it (audit 0.9).

## 0.1.120 — 2026-11-15

### Added

- **Stable GlobalIds for relationships, property sets and alignments**
  (#80), so a 4D or 5D file is the same run to run, not only its tasks and
  cost items. `stable_ids.key_relationships` keys each property set by its
  owner and name, each IfcRelSequence by its two tasks, and every other
  relationship by its type and relating entity, leaving the related set out
  so adding a member keeps the id. `est-bim schedule`, `cost5d`, `estimate5d`
  and `estimate-model` run it last; a writer that adds to an embedded file
  calls it before saving. `est-bim add-alignments` keys its alignments,
  layouts, segments and referents, and the nests and Pset_Stationing around
  them. The contract is `docs/globalid-contract.md`.

## 0.1.119 — 2026-11-15

### Added

- **Stable GlobalIds for what the embedders write** (#74), so records a
  consumer attaches by GlobalId survive a rebuild or a re-embed. `est-bim
  schedule`, `cost5d`, `estimate5d` and `estimate-model` key their work
  schedules, calendars, tasks, cost schedules, cost items and crews as
  `uuid5(<the file's IfcProject GlobalId>, <key>)`, the rule elements already
  follow (`bimforge.bim.stable_ids`). A task's `global_id` from write-back
  still wins. `dxf2bim` keys its project, spatial containers and elements
  (`element/<layer>-<DXF handle>`) from a new layer-map `project.guid_ns`, and
  warns without one. `est-bim build` keys the IfcProject explicitly, to the id
  it already had. What changes an id, and what never does, is in
  `docs/globalid-contract.md`.

### Changed

- **Re-running an embedder over a file it wrote before this release changes
  that file's schedule and cost ids once**, from random to keyed. After that
  they hold.

## 0.1.118 — 2026-11-14

### Changed

- **`est-bim estimate-model` writes ProjectCommand's ESTIMATE shape.** Each bid
  item's Identification is now its pay item id, the one the TENDER schedule
  (`est-bim estimate5d`) writes, so the two pair by Identification. Beneath it,
  one `"<item>.<cost code>"` item per cost code, and one leaf per share with a
  single ADD-composed IfcCostValue (its components are the money by kind) and
  no CostQuantities. `read_costs` keys and the dashboard's share `code` are
  unchanged; the old key rides on the bid item as `BidSheet_EstimateItem.CostKey`.
  A reader older than 0.1.118 reads the composed leaves as $0, and re-running an
  older `estimate-model` over a new file leaves orphan cost values: adopt
  0.1.118 everywhere at once.
- **Pay item ids are the bare item number** in both schedules
  (`estimate5d.pay_item_id`): "Item # 2" is written "2".
- **A TENDER rate over an undeclared unit is per one raw unit** (`estimate5d`):
  where the project declares no unit for the dimension, the UnitBasis is 1 of a
  unit the size of the raw quantity (a prefixed IfcSIUnit such as MILLI
  SQUARE_METRE, else an IfcConversionBasedUnit), not the SI base unit valued at
  that size, so a reader that divides by the basis value without converting
  units (ProjectCommand's) reads the right money.

### Added

- **Top-level indirects:** an estimate share naming no bid item is filed under
  a top-level cost item keyed by its cost code (`"<code> [indirect]"` when the
  code is also a bid item's id or key). Before, it was dropped with a warning.
- **Composite cost values are read everywhere** (`cost_categories.value_of`):
  `read_costs`, the categories and the web contract sum an ADD value's
  components.
- **`cost_code`** in `read_costs` per-task records and contract shares of
  estimate-model files.
- **The file's currency:** every cost schedule BIMForge writes declares an
  IfcMonetaryUnit (USD) in the project's units when it has none.
- An ESTIMATE schedule renamed in another tool is still found and replaced (its
  `BidSheet_EstimateModel.WorkSchedule`). `estimate-model` warns about a second
  ESTIMATE schedule in the file, bid items that share a pay item id, and any
  repeated Identification.
- **costs.json `"items"`** for bid items no element carries (mobilization):
  `est-bim estimate5d` writes each as a top-level total in the TENDER schedule (#49).

### Fixed

- **The TENDER schedule totals the bid** (#49): a code whose extension is within
  float residue of its `cost` (0.001%, at least $0.01) has its non-count rates
  scaled so its children sum to the cost exactly, and `estimate5d` refuses to
  write a schedule that does not read back at its priced total to $0.01.

## 0.1.117 — 2026-11-14

### Fixed

- **The unhosted-excavation warning names the terrain** (#59). It took the first
  IfcGeographicElement as the ground, so a model with rock slope protection listed first
  was told to void the RSP. It now considers only a TERRAIN IfcGeographicElement, and
  warns only when the model has one.
- **More material names have a Category** (#65): redwood and cedar are wood, baserock is
  stone.

## 0.1.116 — 2026-11-14

### Added

- **A backfill derived from its pit** (#59). `author.backfill.derive_backfill(model,
  pit, name, top=...)` adds one IfcEarthworksFill (BACKFILL) whose solid is the pit
  clipped at the backfill's top (a level or a surface) less every element body
  standing in it, cut with manifold3d when the model is built: a stem rising above the
  backfill takes away only its buried part. Its `volume_cf` is the solid's volume, held
  by a stated-quantity assertion. Ground and other earthwork bodies are never taken
  away; `exclude=` names more. A body that is not a closed solid, nothing left to
  backfill, or a backfill in another number of pieces than `pieces=` (default 1) is
  refused. A 4D viewer animates the one solid by volume, so no lifts are needed;
  `author.lifts` is no longer the way for 4D.
- **Groups** (#59). `StructureModel.groups` ({name: [element names]}) is written as one
  named IfcGroup each, with IfcRelAssignsToGroup; `derive_backfill(group=...)` ties a
  pit and its backfill together ("Abut 1 earthwork"). A group is an assignment, not a
  parent, so a hosted cut (whose parent is the ground it voids) can join one where it
  cannot join an IfcElementAssembly. A group naming a missing element is refused.
- **Every IfcMaterial states its IFC Category** (#65): `concrete`, `steel`, `aluminium`,
  `block`, `brick`, `stone`, `wood`, `glass`, `gypsum`, `plastic` or `earth`, so a
  viewer can give each kind of material its own surface without parsing the free-text
  Name. It comes from `Element.material_category`, else the first keyword in the
  material's name (shotcrete, mortar and concrete are concrete; pipe, rod, bar and cable
  are steel; ground, backfill, fill and excavation are earth; timber and plyform are
  wood; ...), else the element's surface; no match leaves it unset. One material has
  one Category: a clash is warned and the first element decides.
- **Palettes** (#65). A style pack's `ifc.surfaces` can be keyed by
  `material:<name>` and `category:<category>` as well as by layer and IFC class, in
  that order (name, layer, category, class), each key merging field by field over the
  built-in entry. Entries take `diffuse` and `specular_colour` (a factor or an rgb)
  alongside colour, transparency, reflectance and roughness; `texture` is reserved and
  ignored with a warning. A build spec's `style_pack:` (or `est-bim build
  --style-pack`) picks the palette for one job, over the org pack. Every category has a
  built-in look (steel and aluminium METAL, glass GLASS and see-through, concrete,
  stone, masonry, wood and earth MATT), so a material whose layer the table does not
  know now reads as what it is rather than as its IFC class's default.

### Changed

- **An excavation written unhosted while existing ground is in the model is warned**
  (#59). The hosted IfcEarthworksCut (`Element.voids` naming the ground) is the
  standard form a 4D viewer opens the ground with; the unhosted rewrite to
  IfcEarthworksElement / EXCAVATION (#364) is unchanged.

## 0.1.115 — 2026-11-14

### Fixed

- **A georeferenced IFC states the unit of its map coordinates** (#58). Neither
  `emit_ifc` nor `dxf2bim` set `IfcProjectedCRS.MapUnit`, and a CRS without one takes
  the project's length unit, the metre, so a reader that follows the schema took a
  US-survey-feet CRS's eastings and northings as metres. Both now write the CRS's
  unit from the EPSG registry, through one helper (`bim.georef.write_map_unit`): an
  `IfcConversionBasedUnit` ('US survey foot', 'foot') or the SI metre. A
  MapConversion Scale that disagrees with that unit is refused.
- **`dxf2bim` converts a drawing in another unit than its CRS through metres.** A mm
  DXF on a metre CRS passed its mm base through as metre eastings and wrote Scale
  1000, putting the model 1000x off; a drawing in the CRS's own unit (a ft DXF on a
  ftUS CRS) is unchanged.
- **`dxf2bim` names the CRS and its geodetic datum** from the EPSG registry unless the
  layer map's `georeference` block gives `crs_desc` / `geodetic_datum` /
  `vertical_datum`; `emit_ifc` falls back to the registry datum when the project spec
  gives none.

### Changed

- **Tasks link to the elements they build or take away as outputs, not inputs**
  (#60). `est-bim schedule` and `est-bim estimate-model` wrote every task-to-element
  link as `IfcRelAssignsToProcess`, which IFC, Bonsai and other 4D readers take as
  material the task consumes, so a construction task showed nothing built. They now
  write `IfcRelAssignsToProduct` (the element relating, the task related) for both
  construction tasks and DEMOLITION / DISMANTLE / REMOVAL tasks; the task's
  PredefinedType still says which. bimforge's readers read both forms, so older
  models load as before, and re-embedding a schedule replaces its old input links.
  `schedule-read`'s link `direction` is now `"output"` for these links.

## 0.1.114 — 2026-11-13

### Fixed

- **A merged face no longer opens the shell where two pieces touch edge-on** (#47).
  A body fused from separate closed pieces (formwork: a kicker flush against a stud)
  can put two pieces' faces in one plane group as two parts. The T-junction closure
  put every vertex of the group on every part's boundary, so one piece's corners split
  the other's edge where its neighbouring face did not: 3 open edges and 1 non-manifold
  edge, and the post-emit gate deleted the outputs. Each part now keeps only the
  vertices of its own triangles. As a backstop, a body whose merge would leave more
  open or non-manifold edges than its triangles had is written as its triangles.

## 0.1.113 — 2026-11-12

### Fixed

- **An alignment's zero-length closing segment faces the way the alignment ends**
  (#51). ifcopenshell 0.9 writes the terminator `IfcAlignmentHorizontalSegment` π off
  the end tangent whenever the final heading is past 90°; the geometry was right, so
  only the semantic segment disagreed. `emit_alignment.fix_terminator` (moved from
  `bim.add_alignment`, which already applied it) now runs for every authored alignment
  too.
- **`est-bim add-alignments` writes a curve that follows a curve where the traverse
  has it** (#52). ifcopenshell's PI layout misplaces a curve with no tangent before it:
  a curve split across two sheets came out as a 313° loop turning the other way, with
  the next segment starting up to 182 m away, and a reverse curve divided by zero. The
  start and end still matched, so the gate passed. The horizontal segments are now
  written straight from bimforge's traverse, as `emit_alignment` writes them, and the
  vertical is still laid out by PI. The gate also checks that every horizontal segment
  ends where the next one starts.

## 0.1.112 — 2026-11-10

### Changed

- **An IFC2X3 model is refused by name.** `est-bim takeoff`, the takeoff workbook and
  the web bundle now stop with "IFC2X3 is not supported: the takeoff reads IFC4X3, or
  IFC4 as a fallback" (`ifc_takeoff.require_supported_schema`). A classified IFC2X3
  element used to raise an AttributeError mid-read.

### Added

- **The takeoff contract as IDS.** `bimforge/bim/contract/takeoff.ids` states what
  `est-bim takeoff` needs from any IFC (ours, Revit's, Tekla's) as a buildingSMART
  IDS 1.0 document: a classified element carries a quantity to measure, each named
  quantity is stored as its own dimension, and every classification reference has a
  code. `takeoff-coverage.ids` is the advisory companion: every measured element is
  classified. Both are generated from the reader's own tables
  (`python -m bimforge.bim.takeoff_ids`) and run in any IDS checker;
  `pip install 'bimforge[ids]'` adds `ifctester`. IFC4 and IFC4X3 only.
- **A draft family dictionary** in bSDD's import format,
  `bimforge/author/dictionary/bimforge-families.bsdd.json`: the classes the typed
  families emit (Type 842 and 732SW barrier runs, B11-51 tubular handrailing and its
  parts, the D90 pipe guardrail), their IFC entities and standard-plan `Reference`,
  and the `BIMForge_LinearReference` properties. It is a local file; nothing is
  published to bSDD and nothing reads it yet.

### Fixed

- **A coplanar merge no longer writes a face whose hole touches its outer bound**
  (#42). Such a face is valid to OGC, but IFC viewers drop it (web-ifc skips it in
  `GetFlatMesh`), and the 0.1.110 clearance guard missed it because the shared vertex
  lies on the edges it is near. `facets` now writes a plane group as its triangles
  when an inner bound comes within `MIN_CLEARANCE` of the outer bound or of another
  inner bound.

## 0.1.111 — 2026-11-09

### Changed

- **`est-bim estimate5d` writes the bid as a TENDER schedule** (was ESTIMATE). It
  is named `"<name> bid"`, with Status PLANNED, and `--stage awarded` (`embed_estimate(...,
  stage="awarded")`) writes PRICEDBILLOFQUANTITIES / APPROVED. A re-run replaces a
  pre-0.1.111 `"<name> estimate"` ESTIMATE schedule. This frees ESTIMATE for the
  internal cost schedule.
- **Pay items are keyed by bid item.** A parent IfcCostItem's Identification is the
  map entry's `item_number` (the code when there is none), and every code an item
  takes off lands under that one parent. An internal schedule pairs with it by
  Identification.

### Added

- **UnitBasis on every estimate5d cost value**: an IfcMeasureWithUnit of 1 raw unit
  of the child's quantity. That is the quantity's own Unit, else the project unit, else
  EACH for a count, else the SI base unit at the raw unit's size. Item total =
  AppliedValue x quantity / UnitBasis.
- **The governing code.** A code with no `unit_price` whose `item_number` names a
  priced item has its elements assigned (IfcRelAssignsToControl) to that item at $0,
  with no CostQuantities, and is reported in `covered_by_item` rather than as
  missing a rate. A code whose item prices nothing is still `codes_without_rate`.

- **`SectionPrism(batter=, end_slopes=)`**: a section that leans its near face back
  by `batter` (a retaining wall's battered earth face, voids carried straight
  through it) and cuts its ends on vertical planes `x = xmin + k0*y`,
  `x = xmax + k1*y`. Either one measures the volume from the faces and drops the
  `exact` extrusion. **`BatteredWall(mitre_from=, mitre_to=)`** mitres an end
  section as though the wall turned that corner.
- **Mod barriers: a run's own section ring** (`concrete-barrier-842`,
  `concrete-barrier-732sw`; #26). `runs[].profile: [[x, z], ...]` replaces the
  computed section, and the run keeps the family's end blocks, rebar and
  validation, straight, `path` and `on:` alike. The 842 derives its end-block
  nose from the ring (`barrier_custom.plumb_nose`: the B11-82 Section G-G
  substitution, exact for the three standard rings). `nose_profile` (one ring, or
  `{approach: ..., departure: ...}`) gives it outright, and the 732SW, whose nose
  is not a plumbed running section, needs it. A ring that crosses itself, a nose
  that cannot pair with it by index, or a ring given together with the family's
  Mod dimension keys is refused. The 842 also takes **`chamfer_in`**, which cuts
  B11-82's top-corner chamfers on the standard ring and its nose. `template()` on
  both modules returns the family's `BarrierTemplate`, in place of the private
  `_TEMPLATE`.

### Fixed

- **A work schedule's StartTime is never the time the file was written** (#36).
  `embed_schedule` used to pass a source's missing `start_date` (a gw file without
  one, an XER without `plan_start_date`) through to ifcopenshell, which wrote
  `now()`. The schedule now starts at its earliest dated task, and
  `est-bim schedule` says so. A schedule with no date anywhere (an estimate's
  unscheduled activities) still gets today's date, since StartTime is mandatory,
  but `EmbedReport.start_from` is `"none"` and both `est-bim schedule` and
  `est-bim estimate-model` warn that the start is not real.

- **Cost schedules are declared to the IfcProject** (IfcRelDeclares; #38), via
  `cost5d.add_declared_cost_schedule` / `remove_declared_cost_schedule`, in
  estimate5d, cost5d (BUDGET) and estimate-model (ESTIMATE). A re-run drops the old
  declaration with the schedule.
- **estimate5d no longer crashes on an IFC4X3 count.** The EACH UnitBasis wrote its
  IfcCountMeasure as `1.0`, which IFC4X3 (an INTEGER there, a NUMBER in IFC4)
  refuses with `RuntimeError: Attribute not set`, so any IFC4X3 model with an
  IfcQuantityCount could not be estimated. It is now written as `1`.

- **culvert-headwall: the panel batters and the wingwalls close on it** (#24).
  The headwall panel now carries the B3-1A batter on its earth face with its creek
  face plumb, like the wings. Each wing and the panel meet on one vertical plane
  bisecting the corner, so the plumb step at the creek face and the plan overlap
  are gone. On the shipped D90 example (no batter) the two structures' panels and
  wings drop from 10.134 to 9.967 cy, the concrete the square-ended wings counted
  twice. A flared panel is now an `IfcFacetedBrep`, not an extrusion.
- **Plan-sheet vectors honour the PDF's clip paths** (#17). `extract_sheet` cuts
  each stroke to the clip active where it is drawn, so line work outside a
  viewport's clip no longer comes back from `est-bim contours` (or measure,
  regions) as phantom contours and labels that never plot. A clip is taken as its
  bounding box, which is exact for rectangular viewport clips. `est-bim contours`
  logs what the clip removed and records it as `pdf_clip: {cut, dropped}` in the
  manifest; `extract_sheet(..., honor_clip=False)` keeps the old harvest.

## 0.1.110 — 2026-11-08

### Added

- **`est-bim build --family-path DIR`** (repeatable; `registry.load_family_dirs`,
  `available(family_paths)`, `build_from_spec(..., family_paths=)`): resolve a
  spec's family from a folder of family modules, each exporting
  `FAMILIES = {name: build}`, without packaging them as entry points. The folder
  goes on `sys.path`, so a module can import its siblings. A module that fails to
  import is skipped with a note, and a name declared twice or shadowing a shipped
  family is an error.
- **Spec `ifc_surfaces`** (`registry.spec_stylepack`): `{layer or IfcClass: {rgb,
  transparency, material, reflectance, specular}}` merged over the style pack's
  `ifc.surfaces` for one build, so a model can carry its own presentation colours.
- **Spec `gate.unread_params: off | warn | error`** with `gate.ignore`
  (`bimforge.author.params_tracking`): reports spec params the family never read, a
  transcribed value the model silently ignores. `error` makes it a pre-emit gate
  failure. Off by default, so existing specs build exactly as before;
  `build_from_spec(..., unread_params=)` sets the default for a caller.
- **Nested facility parts** (`SpatialPart.parent`, spec part `parent:`): a part
  aggregates under its parent part rather than the facility, so a bridge reads
  Substructure > Abutment 1 > Foundation in one emit, and federate carries the
  nesting. A parent that no element names directly is still written, and a
  bare-name parent resolves to the part declared in full. Two different full
  declarations of one name, or a parent cycle, are refused.
- **`federate(..., merge_facilities=True)`**: sources that describe one facility
  (same class and name, such as a bridge and its structure earthwork modelled
  apart) become one facility. Their part trees merge by part name, recursively,
  and the first source's GlobalIds are kept. Containment, references, aggregates
  and placements move to the surviving parts. Two sources placing the facility
  differently, or one part with two predefined types, are refused. Off by
  default.

### Fixed

- **A merged IFC face no longer opens the shell.** The coplanar-facet merge
  could leave a planar polygon with a vertex a fraction of a millimetre from an
  edge it is not on, for example a notch from a boolean sliver. The kernel's
  tolerance closes the gap and mis-triangulates the face: one earthwork backfill
  read back with 8 open edges and 5.9% over its volume, so the post-emit gate
  deleted the outputs. A plane group whose merged polygon has a
  `minimum_clearance` under 1 mm (`facets.MIN_CLEARANCE`) is now written as its
  triangles.

## 0.1.109 — 2026-11-08

### Added

- **`est-bim add-alignments`** (`bimforge.bim.add_alignment`): adds IfcAlignment to a
  finished, georeferenced IFC4X3 from `pob`/`run` blocks. That covers a federated or
  foreign file, or a model whose alignment is known only after the build. It writes
  the horizontal layout, an optional vertical (`profile: pvis`, `vc_length_ft`) and
  Pset_Stationing referents: at the start, at every segment break, and at any
  `--referents NAME=STA,...`. A tangent-to-tangent break is laid out as an angle
  point (a radius-0 PI), so an all-tangent traverse keeps every leg instead of
  collapsing to one chord. The gate checks start, end, every angle point and every
  PVI elevation; the file is written only if it passes. It refuses a file that
  already holds an alignment of the same name, so a rerun never stacks a second
  copy. This brings upstream a post-processor that lived in an estimating repo.
- **`est-bim landxml-alignments`** (`bimforge.author.landxml`): LandXML 1.2
  alignments to `pob`/`run` YAML. It splits at angle points, dedupes repeated
  files, and is gated on closure, element gaps and a single EPSG code.
  Improvements over the script it replaces:
  - A repeated alignment is gated too: two files with the same traverse but
    different stated end points are no longer silently deduplicated.
  - A `<Line>` without the optional `length` attribute uses its chord.

- **The Caltrans catalog tests and scripts, ported from estimating-plugin**
  (#5). `tests/test_caltrans_manifest.py` checks `data/caltrans-2025/manifest.json`
  (all 91 sheets with URL, sha256 and size, and every transcribed family in
  scope) and, where the sheets are fetched, their digests;
  `tests/test_d90_catalog.py` checks the D90 headwall catalog's fixed rules;
  `tests/test_dgn_to_dxf.py` covers the converter's command lines. CI runs
  `tests/` beside `bimforge/`. `scripts/fetch_caltrans_dgn.py` and
  `scripts/dgn_to_dxf.py` come with them; the converter takes ExDgnImport
  from `--dgn-importer` or `ODA_DGN_IMPORTER` and has no machine default.

### Fixed

- The provenance scan flags a Windows machine path written with
  backslashes, not only one written with forward slashes.

## 0.1.108 — 2026-11-06

### Changed

- **Python 3.10 is no longer supported**: `requires-python` is `>=3.11`.
  3.10 reaches end of life in October 2026, and current dependency fixes
  (pillow 13, scipy 1.16) already need 3.11+. CI runs the floor and the
  newest supported interpreter, 3.11 and 3.13. Nothing in the package
  changed; a 3.10 interpreter now gets 0.1.107 from PyPI instead of a
  broken resolve.

## 0.1.107 — 2026-11-06

### Added

- **`StructureModel.ifc_sweeps = "mesh"`: the sweep mode as a model
  setting**, so a model built for an ifcopenshell 0.8.x viewer carries
  its own choice. A spec sets it with `ifc: {sweeps: mesh}` (`est-bim
  build`); `emit_ifc(sweeps=)` and `outputs.ifc_sweeps` (0.1.102) override
  it for one emit. The default `"exact"` is unchanged: an exact
  `SweptSection` is written as an `IfcSectionedSolidHorizontal` on the
  `IfcAlignment` curve. An unknown value is refused before any write. (PR #6)

### Known limitations

- **ifcopenshell 0.8.5, which Bonsai 0.8.x bundles, misplaces every
  `IfcSectionedSolidHorizontal`.** This is a kernel bug; the emitter's
  output is not the cause. 0.8.5 evaluates the directrix itself exactly as
  0.9 does, but it puts each cross-section at the right point plus an offset
  that grows with `DistanceAlong`, and the direction of that offset changes
  with the curve's heading. A section point (u, v) at distance d along a
  due-east line lands at (d, u + d, v), not (d, u, v); on a due-north line
  at (-u, d, v + d), not (-u, d, v). So the solid draws rotated and moved
  off its line. Files that pass every IFC 4.3 rule are misplaced too. Read
  models (extrusions, faceted breps) and plumb-on-grade sweeps, which are
  already written as meshes, draw the same in both versions. For a model
  meant for a 0.8.x viewer, set `ifc_sweeps = "mesh"`: the fixture wall
  then draws identically under 0.8.5 and 0.9. (ifcopenshell 0.9 draws the
  sectioned solid in the right place but lofts it as an open shell; the
  same mode is the remedy.)
- **A sweep with no vertical profile fails `IfcSectionedSolid.DirectrixIs3D`.**
  Its directrix is the 2D horizontal `IfcCompositeCurve`, which
  `ifcopenshell.validate --rules` reports as an error. ifcopenshell 0.9
  draws it correctly anyway. Separate from the 0.8.5 placement bug: graded
  sweeps on a 3D `IfcGradientCurve` are rule-valid and are still misplaced
  by 0.8.5. Not fixed yet.

## 0.1.106 — 2026-11-06

Review fixes for 0.1.102–0.1.105.

### Fixed

- **One named type has one predefined type.** A type's GlobalId is keyed
  by class and name; two predefined types under one name would have been
  two IfcTypeObjects with one GlobalId. Emit refuses it before any write.
- **Categorising a cost never changes it.** A split that covers less than
  the cost writes the balance as one more value with no Category (it
  reads back in `cost`, not in `categories`); a split that exceeds the
  cost is refused by `validate_costs` and the writer. The writer also
  accepts the reader's own form (`categories: {Labor: 60, ...}`), so
  `read_costs` output re-embeds with its split intact.
- **Web bundle:** each takeoff row's element quantities are scaled to the
  row's pay quantity (a lump sum over three elements is 1 LS, `count_as`
  stands), so the dashboard earns an item once; the bid total follows the
  priced bid list's quantity and price before the estimate's stored
  amount; the 4D spans (appear, vanish) come from the selected schedule's
  tasks only (`element_spans(f, tasks)`), not every task in the file.
- **Dashboard:** a task's own calendar (its weekdays, holidays and yearly
  blackouts) decides its working days; only building tasks
  (construction, installation, undefined) earn pay, not operation or
  logistics; an element's own share with zero of the chosen kind stays
  zero rather than borrowing the task's total; the labour-hours basis
  uses the element's share hours before the task's; an item's cost on the
  day is its bid item's shares, or its code's shares shared equally among
  the items of that code, so a dollar is never counted twice; chart
  tooltips escape their labels; Gantt rows are keyboard-focusable and
  activate on Enter or Space, keeping focus across a redraw.
- **Pages:** a selection with no host copies only when the clipboard
  accepted it and otherwise offers the GlobalIds in a dialog; the takeoff's
  "only items with a variance" keeps an item whose official quantity is
  zero but whose modelled quantity is not.

## 0.1.105 — 2026-11-05

### Added

- **The labour / material / equipment split reaches the IFC, and the pay
  can follow one kind of it** (`bimforge.bim.cost_categories`). IFC puts no
  price on an element, a task or an IfcMaterial: money lives in an
  IfcCostItem as a list of IfcCostValue, each with a `Category`, and the
  item is tied to the task it is spent in and the element it builds by
  IfcRelAssignsToControl. So a split is one cost item with one value per
  kind, Category = Labor / Material / Equipment / Subcontract / Other.
  - `est-bim cost5d --costs`: a code's record may carry `labor`,
    `material`, `equipment`, `subcontract` (or `sub`), `other` (or
    `overhead`), the parts of its `cost`; each task's item is written with
    one value per kind, scaled to the task's part of the code, to the
    cent. An unknown kind is refused.
  - `est-bim estimate5d`: each element's share of an activity is written
    in the activity's own `cost_split` proportions, one value per kind.
  - `schedule_read.read_costs` returns `categories` {kind: amount} per
    task, per code and per task-code (`{}` when the values carry none);
    `cost` stays the sum of every value. The web bundle's `costs.shares`
    carry `categories` too.
  - The 4D/5D dashboard draws cumulative labour, material, equipment (and
    subcontract, other) cost beside total cost and earned pay, shows the
    split on the day, and lets you choose what the pay follows: all cost
    (the default), one kind of cost, or labour hours. A kind recorded
    nowhere for an element falls back to all cost, so a material-only item
    is never earned on nothing.

## 0.1.104 — 2026-11-05

### Changed

- **The pay follows the labour, the tasks and the materials.** The 4D/5D
  dashboard no longer drops an element's pay quantity on its appear date.
  Each element's quantity is EARNED over the tasks that build it, in
  proportion to the cost the 5D schedule spends on that element in each
  task (the estimate's activity shares), else the task's cost under the
  pay item's code, else its labour hours, else its cost, else evenly; and
  within a task evenly over its working days (the schedule's week and
  holidays, which the cost and labour curves now respect too). An element
  no dated task builds is still earned on its appear date; one with
  neither is reported as undated. With unit prices, earned dollars are
  the earned quantity at the bid item's price: the dashboard shows earned
  pay against cost, cumulative and per pay item on the day, with the
  margin.
  - The bundle carries `costs.shares` (every priced cost item of the 5D
    schedule: task, element, bid item, code, cost, labour hours) and each
    takeoff row's `unit_price` and `bid_total`, from the priced bid list
    (`--official` now reads `unit_price` / `price` and `total` / `amount`)
    or, failing that, from the estimate the IFC carries
    (BidSheet_EstimateItem).
  - What the embed does not record yet, the dashboard cannot split: the
    estimate's labour / material / equipment split of an activity is not
    written to the IFC, so pay follows total cost and hours. Writing the
    split as cost categories is the follow-on.

## 0.1.103 — 2026-11-05

### Added

- **Web pages on a JSON contract (`bimforge.web`, `est-bim web`).** A
  takeoff page and a 4D/5D dashboard, written as views of ONE JSON
  document, the *bundle* (`contract: bimforge-web/1`), that
  `bimforge.web.build_bundle` produces headlessly from an IFC: every
  element (class, type, predefined type, whole and parts, container, pay
  codes, Qto values, appear and vanish dates, tasks), the pay-item takeoff
  (the CanonicalTakeoff rows with each element's quantity in the pay unit,
  the official bid quantity and the variance), the IfcWorkSchedule as a
  CanonicalSchedule with its task-to-element links, and the IfcCostSchedule
  costs and labour hours per task. The bundle carries no timestamp, so a
  rebuild of an unchanged model is byte-identical.
  - `est-bim web --ifc model.ifc [--map takeoff_map.yaml] [--official
    bid.json] [--schedule NAME] [--out DIR] [--serve [PORT] --open]` writes
    `index.html`, `takeoff.html`, `dashboard.html`, their assets and
    `data/bundle.json` + `data/bundle.js`, and serves the directory when
    asked. The pages are plain HTML, CSS and JavaScript with no external
    library, and open straight from disk.
  - **Takeoff:** pay items with modelled, official, variance and variance
    %, sortable and filterable, expanding to the elements behind each item
    with class, type, quantity, 4D span and GlobalId; a CSV download; the
    elements no pay item counts.
  - **4D/5D dashboard:** a day scrubber; cost and labour to date; cumulative
    cost and labour curves; the cumulative pay quantity in place per pay
    item (from each element's appear date); a Gantt of the schedule (task
    types coloured, milestones, summaries, the scrubbed day and today);
    a task's cost, hours, predecessors and elements; and what stands on
    the day, by class.
  - **The host adapter.** A page talks to whatever hosts it through
    `window.bimforgeHost` (`select(globalIds, label)`, `gotoDate(day)`) and
    listens for a `bimforge:date` event, so the same page runs standalone
    (a selection copies GlobalIds) or inside an editor's bridge (a Blender
    add-on serving the same bundle from the open file, as Bonsai's web
    pages do).

## 0.1.102 — 2026-11-05

A barrier rail reaches FreeCAD, Revit and Bonsai as a barrier rail, not as
loose triangles and a flat list of posts. Measured on the shipped examples
before and after:

| | before | after |
|---|---|---|
| Type 842 end block | 30 triangular IfcFaces | 11 planar faces |
| Handrail run, 87 elements | 87 unrelated products, no types | 1 IfcRailing whole with 87 parts, 8 types |
| Handrail bodies | 43 IfcExtrudedAreaSolid | 5 solids, 40 IfcMappedItem |

### Added

- **Element types (`Element.type_name`).** One IfcWallType / IfcRailingType /
  IfcMemberType ... per distinct (class, name) in the file, related by
  IfcRelDefinesByType and carrying the element's predefined type (the
  occurrence inherits it, as IFC requires; read it with
  `ifcopenshell.util.element.get_predefined_type`). Revit shows the name
  as the family type, FreeCAD and Bonsai as the type tree: twenty posts are
  twenty occurrences of "B11-51 post HSS2x2x3/16". Type GlobalIds are
  deterministic (`type/<class>/<name>`).
- **Wholes and parts (`Element.part_of`).** An element named as another's
  part hangs under it by IfcRelAggregates and leaves the spatial container,
  which is what a viewer's tree shows and what Revit's category is read
  from. The whole is an ordinary, usually geometry-less, Element; emit
  refuses a part of a missing element, of itself, or a cycle, before any
  write. `paycodes.apply` never classifies a whole that measures nothing,
  so a name rule written for its parts ("842 barrier") does not catch it.
- **Property sets (`Element.psets`)**: `{"Pset_RailingCommon": {"Reference":
  "B11-51"}}` on the product. `Element.object_type` writes
  IfcObject.ObjectType.
- **The rail and barrier families use all three.** A tubular-handrail run
  is one IfcRailing (HANDRAIL, type "Tubular handrailing B11-51",
  Reference B11-51) whose rails, posts (IfcMember/POST), returns, caps,
  sleeves, pocket mortar and dowels are its parts, every kind typed. A
  Type 842 / 732SW run is one IfcWall (PARAPET, type "Concrete barrier
  Type 842", Reference B11-81 / B11-58) whose barrier, end blocks,
  reinforcing and hardware are its parts; the concrete bodies carry the
  same type. The D90 headwall guardrail is an IfcRailing/GUARDRAIL. The
  element lists grow by the wholes (one per run, two for a 732SW with its
  handrail), which measure nothing: every quantity baseline is unchanged.
- **Instancing (`StructureModel.instancing`, spec
  `outputs.ifc_instancing`).** Repeated identical bodies (a flat prism, a
  box, a rod, a tube) are written once as an IfcRepresentationMap and
  placed by IfcMappedItem, keyed by the solid up to translation and its
  style; the instanced mesh equals the direct one to the vertex. Off by
  default (an existing consumer's file is unchanged); the rail and barrier
  families turn it on.
- **`outputs.ifc_sweeps: mesh`** (`emit_ifc(sweeps=)`): an exact alignment
  sweep is written as its closed faceted brep instead of an
  IfcSectionedSolidHorizontal, for a consumer that lofts the sectioned
  solid open (ifcopenshell 0.9, so FreeCAD's native importer and Bonsai:
  17 and 40 open edges measured on the test sweeps) or cannot read IFC4X3
  (Revit opens IFC2x3 and IFC4; IFC4X3 is link-only and experimental). The
  IfcAlignment is written either way. A second "Body-FallBack"
  representation beside the sweep was measured and rejected: ifcopenshell's
  iterator draws both, so every reader built on it would see the body twice.

### Changed

- **Coplanar facets are merged in the IFC brep writer**
  (`bimforge.author.facets`). A tapered prism, a loft, a mesh, or a sweep
  written as its mesh used to reach the IFC as one IfcFace per triangle,
  and every importer showed every triangle edge. Facets in one plane
  (to 0.1 µm) are now unioned into one planar IfcFace each, holes as
  IfcFaceBound, outer loop counter-clockwise about the outward normal;
  the shell's points are shared. The surface and its volume are unchanged,
  every vertex a neighbouring facet ends at stays on the merged boundary
  (the shell is as closed as the triangles were), and a facet that merges
  with nothing is written as it was. Curved surfaces stay faceted. The STEP
  emitter has done this since the hand-off work; the two now agree.
- `developed` resolves an IfcMappedItem to the solid it instances when it
  decides whether a body cuts as a fill or a line.

## 0.1.101 — 2026-11-05

### Fixed

- **Ground still to dig draws its edges beyond the cut.** Before the dig
  date, the visible edges beyond a section or elevation now show the ground
  as it stands, not the ground with its hole already dug. When every void
  of a host is still to dig, the host is drawn uncut beyond the plane. A
  ground solid that its cut removes entirely, lying behind the plane, no
  longer vanishes from the pre-dig view. A host with some voids already
  dug is drawn as before, with all of its voids. Ground that is not
  standing at the date (placed later, or already removed) restores nothing.

## 0.1.100 — 2026-11-05

### Removed

- **The Blender add-on moved to its own project,
  [IfcSection](https://github.com/BrandonLewis/ifcsection)**, with its
  history. `bimforge.blender` and `python -m bimforge.blender` are gone.
  BIMForge does not depend on IfcSection. It keeps its own copies of
  `bimforge.bim.alignment_station`, `developed`, `schedule_state` and
  `section_style`, which `est-bim stations`, `est-bim elevation` and the GIS
  export use. Install the add-on from IfcSection's releases, after removing
  the old "Alignment Section (bimforge)" add-on.

### Added

- **Excavation is drawn as ground removed, not as a block in the hole.**
  The section and elevation readers (`bimforge.bim.developed`, DXF) and the
  Blender add-on never fill an excavation. "Excavation" means either:
  - an `IfcEarthworksCut`, or
  - the pay-item `IfcEarthworksElement` with ObjectType EXCAVATION (#364).

  The excavation's outline in the cut is drawn as the dashed limit of
  excavation: the `E-EXCV-LIMIT` DXF layer, or an orange line in Blender.
  With a 4D date before its dig task, the excavation is still ground and is
  filled as the ground it voids. The add-on reads the excavations from the
  IFC, so they are drawn whether or not the viewer imported them. Its new
  **Excavation** setting picks:
  - **Limits** (the default);
  - **Solid** (the volume removed, filled and shown, as before);
  - **Hidden**.

  In Limits and Hidden, Bonsai's excavation objects are hidden in the
  viewport; Exit shows them again.
- **`Element.voids`: an `IfcEarthworksCut` that voids a host.** Naming the
  host (the existing-ground solid) emits the cut as itself, related by
  `IfcRelVoidsElement`. It is kept out of the spatial tree, and it keeps its
  quantities and pay code (the takeoff counts it as excavation). The cut and
  its host are written as meshes: a boolean against an exact sweep, which
  draws as an open shell, empties the host. Unhosted cuts are written as
  before (#364).

### Fixed

- **A cavity wholly inside a body cuts as a hole.** Sections and
  elevations filled an enclosed cavity as part of the body around it: the
  cavity's boundary is a face of the arrangement too. A wall job's root-crown
  overexcavation, below the footing, showed as ground instead of its CLSM
  backfill. Faces are now kept by even-odd nesting.

### Known limitations

- **Viewers' booleans are unreliable on terrain-scale voids.** These were
  measured on a retaining-wall job's ground (a 1 ft raster): a cut sharing the
  ground's top face is silently dropped. With low-poly voids clear of that
  face:
  - ifcopenshell 0.9 drew one run's strip right, but dropped the other run's
    void;
  - 0.8.5 (Bonsai 0.8.x) drew the first strip wrong by 1,496 CF, and
    returned corrupt geometry for the second.

  So for ground, keep the pay-item excavation body and a ground already
  less the dig (the readers above draw that correctly). Use `voids` where a
  viewer's boolean is sound.

## 0.1.99 — 2026-11-04

### Fixed

- `networkx` is now a core dependency. `est-bim schedule` authors through
  `ifcopenshell.api.sequence`, which needs networkx for `recalculate_schedule`.
  With networkx only in the `terrain` extra, an install without that extra printed
  `API not available due to missing dependencies: sequence.recalculate_schedule`
  and wrote the 4D IFC with schedule recalculation unavailable.

## 0.1.98 — 2026-11-03

Contour reconciliation work built in the estimating-plugin monorepo after the
0.1.94 split, brought upstream (estimating-plugin #400, #402, #404).

### Added

- `est-bim contour-surface` can stop contours facing each other across a gap in the linework
  (a roadway cut) from counting as one interval apart: `--barrier-layers LAYER ...` loads
  manifest layers (such as the proposed-grading contours) as obstacles, never contours or TIN
  lines; a `breaks:` list of page- or world-coordinate polylines in the anchors file does the
  same and survives re-extraction; and `--no-face A,B` drops one pair by line number. Every pair
  set aside is a `barrier` finding naming its lines, what set it aside and the facing it set
  aside, and the run logs a one-line summary. A barrier blocks only where it crosses the
  interior of the gap between two lines, never where it lies along a contour. A barrier that
  stops short leaves the pair in place and is reported as a partial `barrier` finding. Only
  partial findings fail `--strict` (estimating-plugin #397).

### Fixed

- `est-bim contours` keeps every drawing path by default (`--min-path-pt` 0, was 2): the length
  filter dropped the short connector paths contour runs are built from, fragmenting contours and
  silently losing line work, and now warns when set (estimating-plugin #398).
- `est-bim contour-surface` exposes the neighbour graph's `--min-facing-ft` (default 4) beside
  `--contact-ft`, and every reconciliation conflict now lists the chain between each pair of
  conflicting sources with the feet per hop it implies against the contour interval (in the
  report, `review.md`, and `findings.json` `chains`). A chain steeper than the interval is called
  out as a likely `faces` edge spanning a gap in the linework, such as two contours facing each
  other across a roadway prism, so the failure can be diagnosed without tracing lines by hand
  (estimating-plugin #397).

## 0.1.97 — 2026-11-03

### Added

- **Cross sections to DXF.** `bimforge.bim.developed.cross_section(f,
  SectionView(...))` draws the section square to the alignment at one
  station: the cut filled per styling, ground lines, the visible edges
  beyond, and offset ticks (CL, 10 Lt, 10 Rt) on the same DXF sheets as the
  developed elevations. In the Blender add-on, **Export Section DXF** writes
  what the section camera shows (the slider's station, Width, Depth,
  Ahead/Back, the 4D date). It needs no From/To; those belong to the
  developed elevation, whose message now points here.
- **Sections read like drafted sections.** A shared table
  (`bimforge.bim.section_style`) says what each cut is (concrete, lean
  concrete / CDF, concrete backfill, compacted fill, native earth, gravel,
  asphalt, steel, timber, rebar, existing work to remove), by its material
  name, else its object name, and how it is drawn:
  - **DXF:** a standard pattern per kind (CONCRETE1, SACNCR, AR-CONC,
    AR-SAND, EARTH, GRAVEL, ASPHALT, ANSI32, WOOD1, CONC_DEMOLITION), plotting
    at its nominal size at any sheet scale on a `-PATT` layer in ink. The
    colour fill stays on the cut layer (freeze it for black and white).
    Rebar plots solid, and a bar smaller than 0.04" on paper as a dot that
    size.
  - **Blender:** the section fills are unlit (emission), so the viewport
    light no longer tints them, in the style's true colour (sRGB converted to
    linear). They are hatched procedurally in camera space at a size that
    follows the view width: stipple, sand, earth crosshatch, gravel cells,
    lines. Hatches show in Material Preview and Rendered; Solid mode shows
    the flat colour. A cut bar narrower than 0.35% of the view width is
    drawn as a dot that size.
- **Station and offset sliders.** The section's slider is now in stations
  (first to last, in the display unit) instead of a 0-1 fraction, and the
  Offsets box has an offset slider across the view (- Lt, + Rt) that moves
  the 3D cursor and reads the surface as it slides. The typed Go / Locate
  fields stay for exact values. Their ranges follow the loaded alignment, the
  unit and the view width.
- **Exit** (next to View Section) leaves the section completely. It goes
  back to a free 3D view, turns the 4D date filter off so the whole model
  shows, and gives the scene its own camera back. It removes everything the
  section drew (camera, plane frame, cut, lines, ruler, labels, marker,
  axis) and stops the viewport label. The alignment stays loaded, so the
  slider or View Section rebuilds it. In the developed-elevation scene,
  **Back to the model** returns to the scene Develop was run from and
  leaves the section as it was.

### Changed

- **Default colours a section can tell apart.** Native earth
  (0.56/0.44/0.30) and compacted fill (0.80/0.69/0.46, a light straw) are
  now far apart, as are concrete, lean concrete / CDF (0.90/0.85/0.62, pale
  cream) and concrete backfill (0.58/0.64/0.70, blue-grey); concrete
  backfill used to be 0.05 off concrete. `S-EW-FILL` resolves to compacted
  fill, not native earth. Models take the new colours when they are
  rebuilt; their styles are written into the IFC.

### Fixed

- **Cut faces hide what lies behind them** in developed elevations and
  cross sections. The cut polygons are painted into the depth buffer at
  depth 0, so an edge beyond the plane (rebar inside a wall, a footing's far
  edge) no longer draws over the fill.
- **A multi-material product cuts per material** (concrete and steel parts
  of one element each get their own layer, colour and hatch). The kernel's
  materials are named after their IfcSurfaceStyle ("Concrete"), not its
  rendering ("IfcSurfaceStyleRendering-170").
- **"Reinforced concrete" classifies as concrete**, not rebar. A cut's kind
  is judged on its layer name as written (sanitised, 40 characters), so a
  long name keeps its hatch.

- **Cut fills of see-through styles.** The DXF used the kernel's diffuse
  colour, which is scaled by (1 - transparency), so the 50 % transparent
  earth filled half-dark. It now uses the style's surface colour.
- **A cross section closes bodies wider than the view.** The native ground
  was cut only within the view width, so it never closed and drew as a line.
  Everything the plane crosses is now cut, then clipped (as `develop` does).

- **The Blender add-on in Bonsai 0.8.x.** Loading an alignment failed with
  "in method 'map_shape', argument 2 of type 'IfcUtil::IfcBaseClass *'":
  Bonsai 0.8.x bundles ifcopenshell 0.8.5, whose kernel binding takes the
  raw wrapped instance. `AlignmentStationer` now maps the curve through
  `ifcopenshell.geom.map_shape`, which unwraps in 0.8 and 0.9 alike. The
  add-on's reading side (stationing, 4D spans, developed elevations) gives
  identical results under 0.8.5 and 0.9.

## 0.1.96 — 2026-11-02

(0.1.95 is skipped: a plugin runtime already carries a wheel labelled 0.1.95.)

### Added

- **Blender alignment-section add-on (`bimforge.blender`).** A station slider
  in the 3D view sidebar (N) that slides a cross-section along an IFC4X3
  `IfcAlignment`. At each station it stands a vertical plane square to the
  alignment in plan and aims an orthographic camera down the alignment, with
  its near clip on the plane. It cuts every mesh at the plane and fills each
  item per its styling (its material / IFC surface style). Unstyled items
  are filled by what their name says they are: concrete, rebar, asphalt,
  gravel, steel, timber or earthwork. The panel reports station, grade elevation, grade and bearing. It also has step and
  go-to-station controls, can look ahead or back, and can follow the timeline
  for fly-throughs. It reads Bonsai's open IFC or a file on disk.
  `python -m bimforge.blender` builds the installable zip.
- **Solid-body gate check.** Post-emit, every element's mesh must be what
  it declares. `Element.body` is `"solid"` (default: one closed manifold
  shell), `"solids"` (closed shells, none touching) or `"surface"` (exempt,
  e.g. terrain). The check reads the file the way a viewer draws it, and
  reports:
  - open edges (cracks, open surfaces);
  - edges shared by three or more faces (stacked or touching bodies,
    zero-thickness cells);
  - pieces enclosing no volume;
  - several pieces where one body is declared.

  `StructureModel.solid_body_gate` sets it to "warn" (the default: reported,
  outputs kept), "error" or "off". `GateReport.warnings` carries the warn
  output. The measurement is `bimforge.bim.ifc_mesh.mesh_topology` /
  `solid_bodies`. A spec sets it with `gate: {solid_bodies: warn|error|off}`
  and declares bodies by name with `bodies: [{match, body}]`
  (`gate.configure_solid_bodies`, used by `est-bim build`).
- **QGIS: 4D dates and stations on every GIS feature (`ifc2gis`).** When
  the IFC carries a 4D schedule, each feature gets `appear_date` and
  `vanish_date` as GeoPackage DATE columns (NULL = open-ended). QGIS's
  Temporal Controller then plays the staging ("Separate Fields for Start
  and End Date"). When it carries an IfcAlignment, each feature gets
  `alignment`, `sta_from`/`sta_to` (numeric, project station unit),
  `sta_from_txt`/`sta_to_txt` (`547+58.20`) and `off_from`/`off_to`
  (+ = Lt), so a layer filters by station like a plan sheet.
  `AlignmentStationer.locate_many` stations many points at once, exact on
  tangents and circular curves: it interpolates between the normal lines,
  not the chord.
- **True arcs.** Circles reach IFC and STEP as circles, not polygons, so
  Revit and Tekla import round members as round (their IFC converters map an
  IfcCircleProfileDef extrusion to a native pipe or rod section; a faceted
  polygon stays a dumb solid).
  - `circle_poly` returns a `CircleRing`: the same equal-area polygon every
    mesh and volume consumer reads, which also remembers `(cx, cy, r)`.
    Rebuilding the list forgets it, and the polygon is then written, never a
    wrong circle. `copy_ring` keeps it.
  - Exact extrusions carry `circles`. `emit_ifc` writes
    IfcCircleProfileDef, IfcCircleHollowProfileDef (concentric tube), or
    IfcCircle curves inside an arbitrary profile (a round opening).
    `emit_step` writes true cylinders, and now oblique extrusions too.
  - New `CircularColumn(name, bottom, top, r, r_inner=None)`: a TRUE
    cylinder on the axis bottom -> top, cut off level at both ends, for
    piles, posts and sleeves. It is round square to its axis, so on a batter
    the level ends are ellipses (semi-axes r / cos(theta) along the batter
    and r across it). IFC gets an IfcEllipseProfileDef extruded along the
    axis (IfcCircleProfileDef when plumb), and STEP a true cylinder. Its
    volume is pi r^2 x the length along the axis; a section kept horizontal
    instead runs about 5 % short at 3:1. Exact forms' `circles` entries may
    be ellipses `(cx, cy, a, b)`, written as IfcEllipse / IfcEllipseProfileDef
    and as build123d ellipses.
  - `SectionPrism` keeps circular profiles and voids. The `pipe-headwall`
    opening is a CircleRing, so its net volume is now the true circle's
    (about 0.6 % of the opening's area less concrete than the old inscribed
    polygon).
  - The D90 `culvert-headwall` pipe void (`elliptical_void`) is now an
    equal-area CircleRing too: a circle when square, an ellipse
    `(cu, cz, a, r)` when skewed. IFC and STEP draw the true arc, and the
    panel's net volume is the true curve's, not the inscribed polygon's.
  - The gate tessellates curved IFC finely (`GATE_ANGULAR_DEFLECTION`,
    0.1 rad; `mesh_leg(angular_deflection=)`), so it checks the true circle,
    not a viewer's 25-gon, which reads 0.97 % low.
- **STEP for engineering hand-off.** `emit_step` now writes geometry an
  engineer can use, not just view:
  - an exact straight extrusion (SectionPrism: girders, barriers, walls
    with voids) is written as a real extrusion of its profile;
  - other meshes are sewn (OCCT sewing, robust to boolean slivers and
    T-vertices), split one solid per closed shell, and coplanar facets are
    merged, so a box is 6 faces, not 12 triangles. Curved surfaces stay
    faceted, because the model authors them as facets.
  - A 300-element girder bridge with lifted backfill writes 336 valid solids, matching
    the model's volumes to 3e-5. Before, the shell constructor failed on
    every multi-piece lift.
- **`pipe-headwall` opening height.** A circular opening with no
  `center_z_ft` now sits with its pipe INVERT `invert_z_ft` above the top of
  footing, default `DEFAULT_INVERT_FT` = 0.5 ft (6 in, the usual practice).
  The old rule was D/3 + 6 in to the CENTRE, which put a 36 in pipe's invert
  on the footing. An opening that does not fit inside the stem, with
  concrete all round, is refused with the reason. This moves existing specs'
  default openings up (a 24 in pipe by 4 in), but not their volumes.
- **Developed elevations (`bimforge.bim.developed`, `est-bim elevation`,
  Blender "Developed elevation").** A view unrolls the model along an
  offset line of an IfcAlignment (a wall face, the line behind it):
  horizontal = true length along that line (on an arc, not the station
  span), vertical = elevation.
  - **Cut:** everything on the line, filled per IFC surface style; a
    terrain or grade surface cuts as a ground line.
  - **Beyond:** the visible edges of what stands up to `depth` further
    on, hidden lines removed (a depth buffer at 0.02" on the sheet).
  - **Grid and title:** station ticks spaced for the scale, and elevation
    lines.
  - `look_from` left / right picks the side you stand on: a wall's formed
    face, or its retained side and drainage. The view is true (from the
    left, stations run right to left); `true_view: false` mirrors it.
  - `date` draws the 4D model as it stands that day.
  - `est-bim elevation set.yaml [--ifc] [--out] [--date]` writes one DXF
    from a view set YAML (`load_set`): an overall view plus `segments:` of
    a station range at a larger scale. Each view is its own paper-space
    sheet with a viewport at its scale, model in feet, layers `E-CUT-*`
    (hatched per style), `E-GROUND-*`, `E-BEYOND`, `E-GRID`, `E-TEXT`.
  - The Blender add-on's Developed elevation box draws the same view in
    its own scene, with an ortho camera, and exports it to DXF. The add-on
    zip now carries `developed.py` (shapely; ezdxf for the DXF).
- **Barrier runs ON a project line (`on:`).** A Type 842 / 732SW run can
  take `on: {from_station, to_station, offset, side, grade | elevation}`
  in place of `straight_length_ft` / `path`. It sweeps the running barrier
  and its section-morphing end blocks along the spec's alignment (a shared
  line by `params.alignment: {ref: NAME}`): tangents, arcs and the vertical
  profile, with the outboard face (section x = 0) on the offset line. A
  level run is an exact `IfcSectionedSolidHorizontal` on the same
  IfcAlignment; on a grade, the plumb section is kept as its mesh
  (`exact_reason`).
  - Pay length is measured along the face, `barrier_template.offset_length`
    (exact on arcs); the end blocks take their length along the face too.
  - `curved_run.build_running_prism` / `sweep_morph` now take `profile`
    and `origin`.
  - Handrail on such a run is refused, as on a curved `path`.
- **Alignment checks for every model on a line.**
  - An alignments file can carry the plan's `ties:` (station/offset to
    N/E, `tol_ft`) and `profile_ties:` (station to elevation). Every model
    built on the line (declared, adopted, placed on or swept along) is held
    to them pre-emit (`placement.check_ties`; `est-bim build` adds it).
  - Post-emit, the gate re-stations the written IFC against every line
    the model is built on (plan and profile, 0.005 ft) and re-measures
    every spec-placed element's anchor through its placement IN THE FILE
    (`placement.ifc_alignment_problems`).
  - `Element.placed_on` now records the anchor (in the element's own
    frame) and the elevation.
- **Station and offset in the IFC (`bimforge.bim.linear_ref`,
  `est-bim stations`).** Every element with a body gets a property set
  `BIMForge_LinearReference` and is linked to its alignment by
  `IfcRelPositions`. The set holds the alignment, station range and
  offset range (+ = left, as IFC's OffsetLateral), with "547+58.20" /
  "12.00 Lt" texts. A spec-placed element also gets its authored anchor
  station and offset. Ranges are measured on the file's own bodies. An
  element goes to the alignment it was placed on, else the nearest.
  `est-bim build` stations what it writes when the model has an
  alignment. `est-bim stations model.ifc [--out] [--csv]` stations any
  IFC4X3 file, a federated one included; a re-run keeps the anchors, and
  GlobalIds are derived, so a rebuild is byte-stable. `ifc2gis` reads the
  set when present (new `sta_at_txt` / `off_at_txt` anchor columns). The
  Blender add-on's **Go to Selected** slides the section to the selected
  element's station from it, and measures the object when it is absent.
- **Shared alignments and the spec `placement:` block
  (`bimforge.author.placement`).** A spec names the project's alignments
  file (`project.alignments:`). Then:
  - `params.alignment: {ref: NAME}` / `params.profile: {ref: NAME}` give a
    line-native family the shared line.
  - `placement:` puts a family built in its own frame on the line: per
    element-name regex, station, offset and side, an anchor (a local point
    or a bounding-box point of the elements matching `of`), elevation or
    `grade:`, local axes and skew. It sets each element's rigid placement
    (`x_ft`/`y_ft`/`z_ft`/`bearing_deg`, composed with any the family set),
    so exact solids, rebar and quantities are untouched.
  - `Element.placed_on` records the station and offset.
  - A line a family declares under a shared name is held to the shared one
    (a pre-gate check) and replaced by it.

  `est-bim build` applies all of it (`registry.place_from_spec`).
- **`federate` merges duplicate alignments.** A source re-carrying a line
  an earlier source carried (same name, map conversion and segment design
  parameters) is merged into it: one IfcAlignment per line.
- **Lifts of a region less what stands in it (`minus`), level prisms,
  and a weld check.** `split_into_lifts(..., minus=solid)` takes `minus`
  out of each slice. A refill around footings, piles and sheets is sliced
  as the region and then cut. Slicing the already-differenced body loses
  volume on its many holes. `sliver_cf` drops a slice's near-zero boolean
  wedges and counts them in the sum check. `prismatic=True` builds each
  lift as the level plan section at mid-lift, less `minus`, extruded
  through the lift (`section_lifts`). It is robust where the 3D cut leaves
  sub-micron wedges against coincident faces, and its sum is held to
  `prism_tol` (3%). Exact slices are now checked at the solid-body gate's
  weld (`weld`, default `WELD_M`). One that pinches falls back to its
  level prism, is flagged `lift["prismatic"]`, and its exact volume still
  counts in the sum check. The sum tolerance is now relative.
- **Compacted fill styling.** `IfcEarthworksFill` defaults to an opaque
  fill colour, distinct from the existing ground (`IfcGeographicElement`),
  so a section or 4D playback tells the ground dug from the fill put back.
- **Lifts in pieces.** A level lift cut through by a wall or wing is
  several bodies placed together. `Lift.pieces` counts them, and such a lift
  element is declared `body="solids"`.
- **`SectionPrism` with a void touching its edge.** The keyhole bridge
  could land inside an outer edge that the side walls ran past whole,
  leaving a T-junction (an open crack along the cap). Walls now split at
  every such vertex. A void TANGENT to the section edge, such as the D89
  default opening for a 36 in pipe, now reads as what it is: one pinch edge
  of zero-thickness concrete.
- **Earthwork lifts: `bimforge.author.lifts`.** `split_into_lifts(model,
  name, lift_ft)` makes an element's fill body one exact solid. It accepts
  mesh, prism, the `fill` kind (pit less its cuts), boxes, and touching cells,
  which are unioned. It slices that solid into closed lifts of COMPACTED
  thickness, from the body's bottom or a given base elevation. A sub-quarter
  sliver on top joins the lift below. The element is replaced by its lifts,
  named `... lift 07 (El a-b)`, which carry its class, material, pay codes
  and facility part, plus `Element.lift` metadata. The parent becomes an
  IfcElementAssembly, and a stated quantity holds the lifts' sum to it.
  `lift_dates` dates the lifts at a production rate (`rate_cy_per_day`,
  compacted, working days, each lift starting where the one below ends), or
  shares a task's working days by volume when no rate is given.
  `lift_overrun` reports how far the rate misses the task's finish.
  Needs manifold3d (the `terrain` extra).
- **4D date filter in the section add-on.** It shows the model as it stands
  on a date of the IFC's embedded schedule. Construction tasks' elements
  appear at their start, and demolition, dismantle and removal tasks'
  elements disappear at theirs. Hidden elements are not cut. The panel steps
  by day or week, or jumps to the next or previous event, and counts what is
  standing, not yet built and removed. Blender objects are matched to IFC
  elements by Bonsai's link, a GlobalId property or the element name. The
  state logic is `bimforge.bim.schedule_state` (`element_spans`, `standing`,
  `state`, `event_days`), which uses only ifcopenshell and ships inside the
  add-on zip.
- **Declared alignments: `StructureModel.alignments`.** A family whose solids
  are built off its own line frame can declare its control line as
  `(Alignment, Profile | None)`. `emit_ifc` then writes it as an IfcAlignment
  although no geometry sweeps along it.
- **`federate` carries IfcAlignment whole.** The alignment is aggregated to
  the target project and referenced in the site, never contained in a
  storey. Its layouts, segments and stationing referents keep their ordered
  nests. Its Axis curve keeps a Model/Axis subcontext instead of being merged
  into Body. The new relationships get deterministic GlobalIds, and
  `FederationResult.alignments` counts what was carried.
- **Offsets in the section add-on.** An offset ruler (CL, 10' Lt, 10' Rt, ...)
  is drawn and rendered across the section. *Locate* puts the 3D cursor at
  station + offset Lt/Rt and reads the top surface there. *Inquire* reads the
  cursor back as station + offset, and *Cut* slides the section to it. Cut
  edges are outlined with flat strips, so they render, and open cuts such as
  a ground surface show as lines. Existing work to be removed and structure
  backfill get their own fills when unstyled. The false-origin field is now
  *Model shift*, so it isn't confused with station offsets.
- **`bimforge.bim.alignment_station`.** Evaluates an `IfcAlignment` at a
  distance or a station: point, 3-D and plan tangent, grade, azimuth and true
  elevation (through `IfcMapConversion`). It also converts station + offset
  to a point and back (`point_at` / `locate`, offsets square to the
  alignment, as on the plans). It uses ifcopenshell's curve
  kernel, so every segment type is exact. Polyline alignments are
  interpolated. Station equations are not applied yet.

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
