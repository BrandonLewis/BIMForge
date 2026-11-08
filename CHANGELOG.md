# Changelog

Newest first. Versions follow `pyproject.toml`; a tag `vX.Y.Z` releases to PyPI.

## Unreleased

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
