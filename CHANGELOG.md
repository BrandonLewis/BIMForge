# Changelog

Newest first. Versions follow `pyproject.toml`; a tag `vX.Y.Z` releases to PyPI.

## Unreleased

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
