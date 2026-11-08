# bimforge

A standalone CAD/BIM toolkit in Python: measure 2D plan sheets, author
parametric IFC models, roll them up into quantities, stage them in 4D/5D, and
produce control, layout and structure sheets.

- **`bimforge.bim`** — DXF → IFC authoring (IFC4X3 by default, exact
  extrusions and alignment sweeps), IFC → quantity takeoff, plan-sheet
  calibration and vector measurement, georeferencing, 3D KML/KMZ for Google
  Earth, 4D schedule embed/read-back (`IfcWorkSchedule`) and 5D cost and
  resource loading (`IfcCostSchedule`). Schedule readers for GanttWarrior JSON,
  Primavera P6 XER and MS Project MSPDI live here too.
- **`bimforge.author`** — the structure-family kernel: alignments, section
  prisms, battered walls, reinforcing bars, plates, saddles, spillways,
  standard-plan families, with quantities taken from the emitted geometry and
  never from a parallel formula.
- **`bimforge.sheets`** and **`bimforge.cad`** — sheet production and the
  org-neutral DXF/KML/geo engine, styled by pluggable **style packs**.
- **`bimforge.terrain`** — terrain grids, watertight terrain solids and
  excavation carves from point clouds and contours.

## Install

```bash
pip install bimforge            # IFC stack included (ifcopenshell, ezdxf, shapely, pyproj, numpy)
pip install 'bimforge[all]'     # + PDF plan sheets, matplotlib drawing, build123d exact solids
pip install 'bimforge[terrain]' # + point-cloud / mesh terrain
```

Two CLIs ship with the package:

```bash
est-bim --help      # dxf2bim, ifc2dxf, takeoff, schedule, cost5d, kml, calibrate, measure, build, ...
est-sheets --help   # control / layout / structure sheet production
```

## Your own families

`est-bim build spec.yaml --family-path families/` resolves the spec's
`family:` from any module in `families/` that exports
`FAMILIES = {"my-wall": build}`, alongside the shipped families and the
`bimforge.families` entry points. A spec can also carry `ifc_surfaces:`
(colours merged over the style pack for that build) and
`gate: {unread_params: warn}`, which reports any param the family never read.

## What a viewer sees

The IFC is written for FreeCAD, Revit and Bonsai as much as for the takeoff:

- A run is **one whole with parts**: a tubular handrail is one
  `IfcRailing` (HANDRAIL) whose rails, posts, returns and pocket mortar are
  its parts (`IfcRelAggregates`); a Type 842 or 732SW barrier is one
  `IfcWall` (PARAPET) over its barrier, end blocks, reinforcing and
  hardware. Any family or script does the same with `Element.part_of`.
- Every kind of part is **typed** (`Element.type_name` → `IfcMemberType`,
  `IfcRailingType`, ...), so twenty posts are twenty occurrences of one
  type with one predefined type, and the standard plan rides in
  `Pset_*Common.Reference` (`Element.psets`).
- Repeated bodies are **instanced** (`IfcMappedItem`,
  `StructureModel.instancing`, spec `outputs.ifc_instancing`).
- Tessellated bodies have their **coplanar facets merged** into planar
  faces, so a box is six faces, not twelve triangles.
- An exact alignment sweep is an `IfcSectionedSolidHorizontal` (IFC4X3).
  For a consumer that cannot draw it as a solid (ifcopenshell 0.9 lofts it
  open; Revit does not open IFC4X3), `outputs.ifc_sweeps: mesh` writes the
  closed mesh instead and keeps the `IfcAlignment`.

## Web pages: takeoff and the 4D/5D dashboard

```bash
est-bim web --ifc model.5d.ifc --map takeoff_map.yaml --official bid.json --serve --open
```

Writes a static site (`takeoff.html`, `dashboard.html`) and the one JSON
document both pages read, the *bundle* (`bimforge.web.build_bundle`,
contract `bimforge-web/1`): elements with their pay codes, quantities and
4D dates, the pay-item takeoff against the official bid quantities, the
schedule with its element links, and the costs per task with their shares
per element. The takeoff page shows every pay item and the elements behind
it; the dashboard scrubs a day through the schedule with earned pay
against cost, labour and per-item pay-quantity curves, and what stands on
that day. Pay is earned as the work is done: over the tasks that build
each element, weighted by the cost and hours spent on it, at the bid
item's unit price. The labour / material / equipment split of a cost
(`est-bim cost5d --costs` records' `labor`, `material`, `equipment`,
`subcontract`, `other`; the estimate's `cost_split`) is written as one
`IfcCostValue` per kind, `Category` naming the kind, and the dashboard can
earn against one kind alone. The pages carry no external library and open from
disk. A host (an editor's bridge add-on) provides `window.bimforgeHost` to
turn a click into a selection; standalone, a click copies GlobalIds.

## Blender: sections along an alignment

The Blender add-on that slides a live cross-section along an IFC4X3
`IfcAlignment` (station and offset sliders, 4D dates, developed elevations,
DXF sheets) is now its own project:
[IfcSection](https://github.com/BrandonLewis/ifcsection). BIMForge does not
depend on it. BIMForge keeps its own copies of the stationing and drawing
modules (`bimforge.bim.alignment_station`, `developed`, `schedule_state`,
`section_style`) for `est-bim stations` and `est-bim elevation`.

## Alignments on a finished model

```bash
est-bim landxml-alignments alignments/*.xml -o alignments.yaml
est-bim add-alignments model.ifc --spec alignments.yaml --path alignments
```

`landxml-alignments` turns LandXML 1.2 alignments into the `pob`/`run`
traverses the authoring layer uses, gated on closure. `add-alignments` adds
them to a georeferenced IFC4X3 that was not built with them, such as a
federated or foreign file. It writes the horizontal layout, an optional
vertical `profile:`, and stationing referents (`--referents NAME=STA,...` adds
more), and it writes nothing unless every alignment closes on its traverse.

## GIS (QGIS)

```bash
est-bim ifc2gis --ifc model.4d.ifc --out model.gpkg
```

The output is a true-3D GeoPackage in the project CRS. It has one layer of
solids and one of lines (the alignment), and each feature carries its class,
name, GlobalId, cost code and quantities. If the IFC has a 4D schedule, each
feature also carries `appear_date` and `vanish_date`. If it has an
alignment, each feature carries its station and offset range. Drag the file
into QGIS and set the project CRS to match. Use *View > 3D Map Views* to
see the Z, and the Temporal Controller (Layer Properties > Temporal >
separate start and end date fields) to play the staging.

## Style packs

CAD styling (title-block borders, layer colours, KML and IFC surface styles)
comes from a *style pack*: a package or directory with `templates/*.dxf` and an
optional `styles.yaml`. Resolution is explicit argument → registered providers
→ built-in neutral defaults. Any installed distribution can register a provider
through the `bimforge.style_packs` entry-point group (a zero-argument callable
returning a pack spec or `None`).

## Fixture provenance

Test fixtures cite public sources or derive their quantities in-repo. They
carry no employer bid numbers and no working-directory paths, and CI's
de-org scan refuses a change that adds one.

## License

Apache-2.0. See `LICENSE` and `NOTICE`. Security reports: `SECURITY.md`.
