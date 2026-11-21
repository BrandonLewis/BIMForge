# Road corridor family (P.6): design

Date: 2026-11-21. Roadmap row P.6. Next after it: G.9 (terrain command), then P.5 (girder bridge family).

## Goal

A `road-corridor` family that builds a road from an alignment, a profile, a typical section and the ground, and writes it as IFC4X3 road elements with standard quantities and a mass-haul report. The family builds its own sections from the spec; nothing is resolved upstream.

V1 includes superelevation, width transitions, gaps for structures and walls, and mass haul. Design-criteria checks (sight distance, superelevation rates against design speed, minimum radii) are out of scope.

## Architecture

New package `bimforge/author/corridor/`, plus the family module.

| Unit | Does | Depends on |
|---|---|---|
| `corridor/section.py` | `resolve(station) -> Section`: finished-grade points, course polygons and the subgrade line in (offset, elevation), then daylights each side to ground | spec params, `alignment.Profile`, a ground sampler |
| `corridor/ground.py` | Fetches 3DEP (or reads an LPC) over the footprint plus a margin, caches it, samples ground across a section, and adds the TERRAIN element to the model | `bimforge.terrain.attach_terrain` |
| `corridor/bodies.py` | Turns resolved sections into bodies: courses swept along the gradient curve; cut and fill lofted between stations; grouped by station band and run | kernel `sweep`, `Prismatoid` |
| `corridor/masshaul.py` | Cumulative cut minus fill per station, with shrink and swell | bodies' volumes |
| `families/road_corridor.py` | Validates params, drives the above, builds the spatial tree, writes Qto sets and the mass-haul pset and CSV | the corridor package |

`section.py` has no IFC dependency and is tested on its own. `ground.py` is the only unit that touches the network.

### Section resolver

- **Components** (lane, shoulder, median) run outward from the crown on each side. Each has a width and a kind (`carriageway`, `shoulder`, `median`). A shoulder may carry its own cross slope; otherwise a component takes the side's superelevation rate.
- **Superelevation** is `[station, left, right]` rows, interpolated linearly. Each value is that side's cross slope measured outward from the crown; negative slopes down away from the crown. A normal crown is `[sta, -0.02, -0.02]`; full super for a curve to the right is `[sta, 0.06, -0.06]`. A component with its own `slope` keeps it regardless of superelevation.
- **Width transitions** are `[station, width]` pairs per component and side, interpolated linearly. Outside the listed range the end value holds.
- **Courses** run top down under the full width of the components, each parallel to finished grade at a fixed thickness. The subgrade line is the bottom of the last course, extended out to the hinge points.
- **Side slopes:** at each hinge the resolver decides cut or fill from the ground. Cut takes the optional ditch (flat bottom, given width and depth) and then the cut ratio up to ground. Fill takes the fill ratio down to ground. The daylight point is the first ground crossing within `daylight_limit_ft` of the hinge. Finding none is an error that gives the station and side.

### Ground

- `ground: {source: 3dep, margin_ft: 200}` fetches a DEM over the alignment's footprint buffered by the margin plus the daylight limit. The result is cached under the existing terrain cache, keyed by bounds and resolution.
- `ground: {source: lpc, path: ...}` takes class-2 ground from a local point cloud.
- `ground: {source: plane, elevation: ...}` and `{source: grid, path: ...}` are for tests and the CI example, so CI makes no network calls.
- Ground is in the model's vertical datum. The datum shift is done by `attach_terrain` as it is now.

### Bodies

- **Courses** are `IfcCourse` elements typed by `IfcCourseType` (PAVEMENT, CORE, ...). On IFC4X3 each is an `IfcSectionedSolidHorizontal` along the alignment's `IfcGradientCurve`, with one profile per resolved station. On IFC4 each is a closed mesh lofted the same way as earthwork. Volume comes from section areas by the average-end-area rule along the curve. On X3 that volume is checked against the meshed equivalent, which fails beyond 0.5%.
- **Earthwork** is `IfcEarthworksCut` and `IfcEarthworksFill`, between ground and the subgrade line plus side slopes. Each is lofted as two triangular prismatoids per quad, so faces stay planar, as in the private trail family. Volume comes from the closed faces.
- **Grouping:** one element per course or earthwork kind per station band (`stations.band`, 100 ft by default), split at gaps and at cut/fill changes. Each element records its start and end station.
- **Line markings** are out of V1. The tree leaves room for `IfcSurfaceFeature` LINEMARKING later.

### Gaps

- `kind: structure` stops the corridor between two stations. No course or earthwork element lies inside the range, and both ends close with a vertical face. The bridge is a separate model, federated by shared GlobalIds.
- `kind: wall` with `side` and `offset` replaces that side's slope with a vertical face at the offset. The earthwork closes on that face. The wall itself is a separate family.
- Gaps may not overlap and must lie on the alignment.

### Spatial tree and quantities

- `IfcRoad` > `IfcRoadPart` ROADSEGMENT (one per run between gaps) > `IfcRoadPart` CARRIAGEWAY and SHOULDER. Courses are contained in the part of the component they sit under. Where a course spans several components it is contained in the ROADSEGMENT.
- Earthwork is contained in the ROADSEGMENT.
- The road is positioned on its `IfcAlignment` by `IfcRelPositions`.
- Quantities use the standard per-class sets (roadmap M.17): `Qto_CourseBaseQuantities` (Length, Width, Thickness, Volume) and `Qto_EarthworksCutBaseQuantities` / `Qto_EarthworksFillBaseQuantities` (Length, Width, Depth, plus volumes: UndisturbedVolume and LooseVolume for cut, CompactedVolume and LooseVolume for fill).
- The mass-haul ordinate per station goes in a `BIMForge_MassHaul` pset on the IfcRoad and in `<name>.masshaul.csv`. Its columns are station, cut CY, fill CY, adjusted fill CY and cumulative CY.

## Spec format

```yaml
family: road-corridor
params:
  alignment: {name: ML, pob: {...}, run: [...]}   # as bridge-standard
  profile: {curves: [...]}
  ground: {source: 3dep, margin_ft: 200}          # or lpc / plane / grid
  section:
    crown: centerline
    components:                                   # outward from the crown, both sides
      - {name: lane, kind: carriageway, width: 12.0}
      - {name: shoulder, kind: shoulder, width: 5.0, slope: -0.05}
    courses:                                      # top down
      - {name: HMA, type: PAVEMENT, thickness: 0.40}
      - {name: AB,  type: CORE,     thickness: 1.00}
    side_slopes:
      cut:  {ratio: 2.0, ditch: {width: 4.0, depth: 1.5}}
      fill: {ratio: 2.0}
      daylight_limit_ft: 150
  widths:
    - {component: shoulder, side: R, at: [[1200, 5.0], [1300, 10.0]]}
  superelevation:                                 # [station, left, right]; - slopes down away
    - [1000, -0.02, -0.02]
    - [1400,  0.06, -0.06]
  gaps:
    - {from: 4100, to: 5275, kind: structure}
    - {from: 2200, to: 2450, kind: wall, side: L, offset: 30.0}
  stations: {interval: 25, band: 100}
  mass_haul: {shrink: 0.10, swell: 0.20}
```

- Sections are resolved every `stations.interval` ft, and also at every listed width, superelevation and gap station, and at each horizontal and vertical geometry point.
- `widths`, `superelevation`, `gaps` and `mass_haul` are optional. Without superelevation the section uses a -0.02 normal crown on both sides.
- Units are US survey feet, as in the other families. The IFC length unit stays METRE.

The shipped example `bimforge/author/examples/road-corridor.spec.yaml` uses a made-up alignment with a curve, a superelevation transition, one shoulder widening, one structure gap and one wall gap, on `plane`/`grid` ground. It carries no real project names or stationing. `--check-only` writes nothing, as for the other families.

## Errors

Each error comes from params validation or resolution and names the field and, where there is one, the station:

- a side slope with no ground inside `daylight_limit_ft` (gives station and side);
- gaps that overlap, or a gap off the alignment;
- width, superelevation or gap stations off the alignment;
- a non-positive course thickness, or no courses;
- a component width that becomes negative through a transition;
- swept volume and meshed volume of a course differing by more than 0.5%;
- ground missing under part of the footprint (a DEM tile that didn't come back).

## Testing

- **Section resolver** (`test_corridor_section.py`), no IFC: hand-worked sections for a normal crown, full super, a mid-transition station, a width taper, cut with a ditch, fill, and no daylight (the error).
- **Volumes:** a straight corridor on a plane at constant fill depth must equal the prism formula to 1e-6. A curved corridor must agree within 0.5% of average end area.
- **IFC:**
  - `schema_issues` and `alignment_issues` are clean on X3;
  - the tree is IfcRoad > ROADSEGMENT > CARRIAGEWAY/SHOULDER;
  - every course is an IfcCourse typed by an IfcCourseType;
  - each element carries its standard Qto set;
  - IFC4 builds meshes and passes `schema_issues`.
- **Gaps:** no element's station range overlaps a structure gap; a wall gap's earthwork ends at the offset.
- **Mass haul:** a balanced cut-then-fill example ends near zero after shrink and swell; the CSV matches the pset.
- **Conformance:** the example spec joins the built-model set in `test_conformance.py`, so the bsi-rules CI job checks it.
- **Ground:** the 3DEP path is tested with a stubbed fetch. No test touches the network.

## Out of scope for V1

Design-criteria checks, line markings, curbs and gutters, intersections, multiple alignments in one corridor, subgrade benching, and a `corridor` CLI command beyond the family runner. G.9 adds the terrain command.
