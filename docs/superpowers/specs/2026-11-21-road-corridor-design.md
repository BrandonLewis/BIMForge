# Road corridor family (P.6): design

Date: 2026-11-21. Roadmap row P.6. Next after it: G.9 (terrain command), then P.5 (girder bridge family).

## Goal

A `road-corridor` family that builds a road from an alignment, a profile, a typical section and the ground, and writes it as IFC4X3 road elements with standard quantities and a mass-haul report. The family builds its own sections from the spec; nothing is resolved upstream.

V1 includes superelevation, width transitions, gaps for structures and walls, and mass haul. Design-criteria checks (sight distance, superelevation rates against design speed, minimum radii) are out of scope.

## Architecture

New package `bimforge/author/corridor/`, plus the family module.

| Unit | Does | Depends on |
|---|---|---|
| `corridor/params.py` | Parses and validates the spec; reads widths and cross slopes by station; splits the alignment into runs at structure gaps; lists the stations to cut | spec params |
| `corridor/section.py` | `resolve(corridor, station, ground_dz) -> Section`: finished-grade points, course rings and the subgrade line in section coordinates, then daylights each side to ground | `params`, a ground callback |
| `corridor/frame.py` | Maps section coordinates to survey points (the sweep engine's "normal" frame), and densifies stations on curves | `alignment` |
| `corridor/loft.py` | `StationLoft`: a closed solid through one ring per station; its mesh, its volume and its exact IfcSectionedSolidHorizontal form | `frame`, kernel mesh helpers |
| `corridor/ground.py` | A plane (tests, CI) or 3DEP over the footprint plus a margin, cached; adds the TERRAIN element for 3DEP | `bimforge.terrain` |
| `corridor/earthwork.py` | Cut and fill between two sections as triangular prismatoids, split where ground crosses the design line | kernel `Prismatoid` |
| `corridor/masshaul.py` | Cumulative cut minus fill per station band, with shrink, and its CSV | earthwork volumes |
| `families/road_corridor.py` | Drives the above, builds the spatial tree, writes the elements with their standard Qto sets and mass-haul psets | the corridor package |

`params`, `section` and `masshaul` have no geometry or IFC dependency and are tested on their own. `ground.py` is the only unit that touches the network.

### Section resolver

- **Components** (lane, shoulder, median) run outward from the crown on each side. Each has a width and a kind (`carriageway`, `shoulder`, `median`). A shoulder may carry its own cross slope; otherwise a component takes the side's superelevation rate.
- **Superelevation** is `[station, left, right]` rows, interpolated linearly. Each value is that side's cross slope measured outward from the crown; negative slopes down away from the crown. A normal crown is `[sta, -0.02, -0.02]`; full super for a curve to the right is `[sta, 0.06, -0.06]`. A component with its own `slope` keeps it regardless of superelevation.
- **Width transitions** are `[station, width]` pairs per component and side, interpolated linearly. Outside the listed range the end value holds.
- **Courses** run top down, each parallel to finished grade at a fixed thickness, measured along the section's vertical axis. Each course is split by component and side, so a course under a lane and the same course under a shoulder are separate bodies. The subgrade line is the bottom of the last course. Each side's **hinge** is the subgrade line's outer end: the bottom outer corner of the last course.
- **Side slopes:** at each hinge the resolver decides cut or fill from the ground. Cut takes the optional ditch (flat bottom, given width and depth) and then the cut ratio up to ground. Fill takes the fill ratio down to ground. The daylight point is the first ground crossing within `daylight_limit_ft` of the hinge. Finding none is an error that gives the station and side.

### Ground

- `ground: {source: 3dep, cache: <path stem>, margin_ft: 200, spacing_m: 1.0, vshift_m: 0.0}` fetches the 3DEP 1 m DEM over the alignment's footprint, buffered by the section's half-width, the daylight limit and the margin. It caches under the stem, as `attach_terrain` does, so rebuilds are offline. The terrain element is added from the same cache.
- `ground: {source: plane, elevation, slope_n: 0, slope_e: 0}` is a plane through the point of beginning, for tests and the CI example, so CI makes no network calls.
- A local point cloud and a grid file are left for G.9, which owns terrain input.
- `vshift_m` is the NAVD88-to-project-datum shift, as `attach_terrain` takes it (0 for a NAVD88 project).

### Bodies

- **Courses** are `IfcCourse` elements typed by `IfcCourseType` (PAVEMENT, CORE, ...), one per course, component and station band, holding the left and right bodies. Each body is a loft through one ring per station in the sweep engine's "normal" frame (sections square to the alignment's 3D tangent). On IFC4X3 it is written as an `IfcSectionedSolidHorizontal` along the alignment's `IfcGradientCurve`, with one profile per station. On IFC4 it is the closed mesh. Stations are densified on plan curves and vertical curves with the sweep engine's own step rules, so the mesh lies on the exact solid. Volume comes from the mesh faces. The gate checks it against an independent average-end-area figure, corrected for curvature at the ring's centroid and for grade, and fails beyond 0.5%.
- **Earthwork** is `IfcEarthworksCut` and `IfcEarthworksFill`, between ground and the subgrade line plus side slopes. Each is lofted as two triangular prismatoids per quad, so faces stay planar, as in the private trail family. Volume comes from the closed faces.
- **Grouping:** one element per course or earthwork kind per station band (`stations.band`, 100 ft by default), split at gaps and at cut/fill changes. Each element records its start and end station.
- **Line markings** are out of V1. The tree leaves room for `IfcSurfaceFeature` LINEMARKING later.

### Gaps

- `kind: structure` stops the corridor between two stations. No course or earthwork element lies inside the range, and both ends close with a vertical face. The bridge is a separate model, federated by shared GlobalIds.
- `kind: wall` with `side` and `offset` replaces that side's slope with a level line at subgrade out to the offset; the earthwork closes on a vertical face there. Stations are cut 1 ft outside each end of a wall gap, so the change from slope to wall happens within 1 ft. The wall itself is a separate family.
- Gaps must lie on the alignment. A structure gap may not overlap any other gap, and two walls on the same side may not overlap; walls on opposite sides may.

### Spatial tree and quantities

- `IfcRoad` > `IfcRoadPart` ROADSEGMENT (one per run between structure gaps, LONGITUDINAL) > `IfcRoadPart` CARRIAGEWAY, SHOULDER and CENTRALRESERVE (LATERAL). A component's kind picks its part: `carriageway`, `shoulder`, `median`. Courses are contained in the part of the component they sit under.
- Earthwork is contained in the ROADSEGMENT.
- The tree is written when the spec sets `project: {facility: {kind: road}}` on IFC4X3, as for every family until C.13 makes it the default.
- The road is positioned on its `IfcAlignment` by `IfcRelPositions`.
- Quantities use the standard per-class sets (roadmap M.17): `Qto_CourseBaseQuantities` (Length, Width, Thickness, Volume) and `Qto_EarthworksCutBaseQuantities` / `Qto_EarthworksFillBaseQuantities` (Length, Width, Depth, plus UndisturbedVolume and LooseVolume for cut, CompactedVolume and LooseVolume for fill). They are written from a new `Element.standard_qto` field, beside the existing `Qto_BaseQuantities`, which consumers read today; M.17 retires that later.
- Earthwork is one `IfcEarthworksCut` (CUT) and one `IfcEarthworksFill` (EMBANKMENT) per station band, each a group of prismatoids.
- Mass haul: each band's cut and fill elements carry `BIMForge_MassHaul` {StartStation, EndStation, CumulativeCY}. The whole table is written to `outputs.masshaul` (a CSV) with columns start, station, cut CY, fill CY, adjusted fill CY and cumulative CY. Cut is bank volume. Adjusted fill = fill / (1 - shrink), the bank volume it takes; the ordinate adds cut minus adjusted fill. Swell gives the loose volumes: cut x (1 + swell), and adjusted fill x (1 + swell).

## Spec format

```yaml
family: road-corridor
params:
  alignment: {name: ML, pob: {...}, run: [...]}   # as bridge-standard
  profile: {curves: [...]}
  ground: {source: 3dep, cache: terrain/ml, margin_ft: 200, vshift_m: 0.0}  # or plane
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

The shipped example `bimforge/author/examples/road-corridor.spec.yaml` uses a made-up alignment with a curve, a superelevation transition, one shoulder widening, one structure gap and one wall gap, on `plane` ground. It carries no real project names or stationing. `--check-only` writes nothing, as for the other families.

## Errors

Each error comes from params validation or resolution and names the field and, where there is one, the station:

- a side slope with no ground inside `daylight_limit_ft` (gives station and side);
- gaps that overlap, or a gap off the alignment;
- width, superelevation or gap stations off the alignment;
- a non-positive course thickness, no courses, or a course type outside IfcCourseTypeEnum;
- a component width that is zero or negative at either end of a transition;
- a wall offset inside the hinge;
- swept volume and meshed volume of a course differing by more than 0.5%;
- ground missing under part of the footprint (a DEM tile that didn't come back);
- a 3DEP ground with no cache path, or a project with no EPSG.

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
- **GlobalIds:** the example is recorded in `example_globalids.json` as it first ships.

## Out of scope for V1

Design-criteria checks, line markings, curbs and gutters, intersections, multiple alignments in one corridor, subgrade benching, and a `corridor` CLI command beyond the family runner. G.9 adds the terrain command.
