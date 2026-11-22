# Road corridor V1.1, part A+B: slope rules, walls, guardrail, dimensions: design

Date: 2026-11-21. Roadmap row P.6 (V1.1). Builds on the V1 family (`docs/superpowers/specs/2026-11-21-road-corridor-design.md`, PR #118). Part C (a path beside the road on its own profile) is a separate spec.

## Goal

Hold a corridor's side slopes to Caltrans practice on steep ground: fill 4:1, 2:1 behind guardrail above a fill height, soil over rock in cut, and a wall wherever a slope cannot fit. Write guardrail as elements with their length of need and end treatments, list every wall and every stretch a structure should take, and give courses, earthwork and guardrail the `BIMForge_Dimensions` and quantity `Formula`s ProjectCommand checks.

Sources, each cited where used: Caltrans Highway Design Manual (HDM, combined edition of 08/08/2025), Traffic Safety Systems Manual (TSSM, April 2025) and its length-of-need calculator, and Caltrans Standard Plans A77N2, A77N3, A77N4 and A77P1 (2025 edition as checked; the research cited the 2026 sheets).

## Spec format

```yaml
section:   # side_slopes sits under section, as in V1
  side_slopes:
  fill:  {ratio: 4.0, steep: {ratio: 2.0, above_height_ft: 10.0}}
  cut:
    ratio: 2.0
    ditch: {width: 4.0, depth: 1.5}
    rock: {depth_ft: 8.0, ratio: 0.5, bench_ft: 6.0}   # depth_ft: a number or [station, depth] rows
  daylight_limit_ft: 150
  footprint_ft: {L: 120, R: 120}                      # optional
walls: auto                                           # only `auto`; listed walls stay under gaps:
max_wall_height_ft: 30
guardrail: {design_speed_mph: 45, rail_depth_ft: 1.44}
outputs:
  walls: out/<name>.walls.csv
  structures: out/<name>.structures.csv
  guardrail: out/<name>.guardrail.csv
```

Every new key is optional. A V1 spec builds exactly as before: one fill ratio, one cut ratio, walls only where listed, no guardrail.

## Fill

- At each station and side the resolver tries `fill.ratio` (4:1).
- If the fill at the hinge (the subgrade hinge, so the courses' depth below the finished shoulder, which makes the trigger that much more conservative than TSSM's embankment height) is taller than `steep.above_height_ft`, it uses `steep.ratio` (2:1) instead, and that side is **guarded** at that station.
- The 10 ft default is below TSSM's warrant for 2:1 (the Equal Severity Curve, TSSM 3.4 Figure 2, is at about 12 ft for 2:1), so every 2:1 slope is guarded and nothing rests on a chart reading. HDM Index 304.1 asks for 4:1 or flatter on new fill.

## Cut

- The cut runs at `cut.ratio` through the soil to `rock.depth_ft` below ground, then a level bench `rock.bench_ft` wide, then `rock.ratio` in rock down to grade or daylight.
- `depth_ft` is one value or `[station, depth]` rows, interpolated linearly with the end values holding, as widths are. It stands for a geotechnical report the project does not have yet.
- The rock face is built up from the cut's toe: rock depth is measured vertically below ground at each point along the face, so the face's top (the bench's inner end) sits on the soil/rock interface and the face only ever stands in rock.
- **Tall rock faces.** `rock.face_bench: {every_ft: 30, width_ft: 10}` breaks a rock face taller than `every_ft` with a level bench `width_ft` wide at each `every_ft` of face height, measured up from the toe. `rock.catchment: {width_ft, depth_ft}` makes the cut's ditch at least that wide and deep wherever the rock face is taller than `every_ft`, to catch rockfall at the toe. Both are optional; without them a face is one plane, as before. A side keeps a fixed point count: the corridor allows `rock.face_bench.max` benches (default 4) and collapses unused ones onto the top of the face; a face that would need more is an error naming the station and side. Bench and catchment sizes are planning values until a geotechnical report sets them.
- A cut whose toe is not in rock collapses the face and bench onto the toe, so the cut side keeps a fixed point count (lofting needs it).

## Walls

`walls: auto` places walls where a slope cannot fit:

- **Trigger:** no daylight within `daylight_limit_ft`, or a daylight point past `footprint_ft` on that side.
- **Fill wall:** at the hinge, with no slope in front. It carries a barrier on top (a barrier slab), so its side gets no guardrail there.
- **Cut wall:** HDM requires a 10 ft shoulder beside a wall in cut, so through the wall's stations that side's shoulder widens to 10 ft (with a linear transition over the 1 ft lead-in at each end) and the wall stands at its outer edge; no ditch.
- **Runs:** failing stations on a side merge into runs, cut 1 ft outside each end as V1 wall gaps are. Walls of the same kind on a side closer than one station interval merge into one, so noisy ground gives one continuous wall. Each run is then a wall gap like a listed one.
- **`outputs.walls`:** one row per run: side, kind (fill or cut), start and end station, offset, minimum and maximum exposed height, and whether it carries a barrier. The wall itself is the wall family's.
- **Too tall:** a fill wall taller than `max_wall_height_ft` is kept and flagged, and its stretch becomes a structure candidate.

## Structure candidates

`outputs.structures` lists each stretch a short bridge or a culvert (precast arch or box) should take instead of a wall: side or both, start and end station, the tallest fill, and the station of the ground's low point. It is a list for the designer, who adds a structure gap to the spec, as V1 does. Choosing culvert locations from drainage paths belongs to the drainage study and is out of scope.

## Guardrail

- **Where:** every guarded station (a 2:1 fill) on a side; consecutive guarded stations merge into a run, then extend by their length of need. Every structure gap also gets approach and departure rail at both ends, from the bridge rail (a Type AGT) outward by the length of need, with the bridge end as the hazard, for each side and direction whose rail face is inside that traffic's 20 ft clear zone (TSSM 3.6(2)(a)). Fill walls carry their own barrier.
- **Section behind the rail** (TSSM 3.6, Standard Plan A77N3 Detail A): MGS, rail face at the shoulder edge; a 10:1 widening behind it out to a hinge 30 in behind the back of post; then the 2:1 slope. Face to back of post is `rail_depth_ft`, 1.44 ft by default: the 3 1/4 in W-beam, the standard 6 x 8 in block that holds the rail 8 in off the post, and a W6 post about 6 in deep (2025 Standard Plans A77N2, A77N3; the 12 in block, used with a 6 in Type A dike, makes it about 1.77 ft). Top of rail 31 in, posts at 6'-3", hinge at least 30 in behind the back of post (A77N3 Detail A). The widening is earthwork. It runs the whole length of the rail, length-of-need stretches included, on any kind of side: where the rail passes a cut, the ditch moves out behind the widening. So every post is a 6 ft post on Detail A.
- **Length of need** (TSSM length-of-need calculator), each run extended upstream and downstream, for each direction of travel on a two-lane road:
  - X = (LH − L2 − Y) / (LH / LR).
  - LR (runout length) from `design_speed_mph`: 195 ft at 45 mph, 230 ft at 50 mph.
  - LH: the clear-zone edge, 20 ft (HDM Index 309.1), measured from centerline for opposing traffic.
  - L2: the rail face's offset from the edge of traveled way. Y: 0, in-line terminals.
  - The run is rounded up to whole 12.5 ft rail elements, 150 ft minimum (TSSM 3.6(1)); the extra is split evenly between free ends. A run held at both ends (bridge, wall, alignment end) that cannot reach 150 ft is flagged, not passed silently.
  - The length of need is measured to a point 12.5 ft in from a terminal's nose, so a terminal end extends 12.5 ft past it.
  - Runs closer than 200 ft join (TSSM 3.6(11)), unless a wall or a structure gap lies between them.
- **Ends:** a crashworthy in-line terminal; a Type AGT transition at a bridge rail or a wall (TSSM 3.6(10)(c)); a Type SFT-M anchor where that direction's length of need is zero (TSSM 3.6(10)(b)).
- **Element:** each run is an `IfcRailing` GUARDRAIL; its body is a W-beam band at 31 in to the top of rail, swept along its offset line with the kernel's sweep. Posts are not modelled as solids.
- **Quantities:** rail length, post count at 6'-3", terminals, AGT transitions and SFT-M anchors. `outputs.guardrail`: side, start and end station, length, end treatments, and the below-minimum flag.

## Dimensions and formulas

New family-dictionary classes for a corridor course, a cut, a fill and a guardrail run; their Codes are the `BIMForge_Dimensions` property names, as for the B3 wall (M.1, M.2). A station is a length along the alignment: `StartStation` and `EndStation` are `IfcLengthMeasure` in the file's length unit, with station-text twins. Ratios are `IfcRatioMeasure`.

| Element | `BIMForge_Dimensions` | `Formula` |
|---|---|---|
| Course | `Thickness`, `Width` (or `StartWidth` and `EndWidth` through a transition), `Offset` (its centroid's, LT or RT), `PathLength`, `StartStation`, `EndStation` | `Length`: `EndStation - StartStation`. `Volume`: `PathLength * Width * Thickness`, or `PathLength * (StartWidth + EndWidth) / 2 * Thickness` through a transition, where it holds (see below) |
| Cut, fill | `MaxDepth`, `MeanDepth`, `SlopeRatio`, `StartStation`, `EndStation`, and on cut `RockDepth` | `Length`: `EndStation - StartStation`. No volume formula |
| Guardrail | `RailHeight`, `PostSpacing`, `StartStation`, `EndStation` | `Length`: `EndStation - StartStation` |

`Length` is measured along the alignment by station, so `EndStation - StartStation` holds on curves as on tangents. An element off the centreline is located by station and offset (LT or RT), as `BIMForge_LinearReference` records it, and a line held at that offset has its own stationing. With the elevations along it, that gives the element's true path. `PathLength` is that length for a course: the 3D length of the line its section's centroid travels, at the centroid's offset and following its elevations, between the course's stations.

A volume is its section area times the length of the path its centroid travels (Pappus). The declared `Volume` is that exact figure, integrated along the course (as the kernel's sweeps declare their closed form), not the faceted mesh; the mesh is checked against it at the corridor's 0.5%. So `PathLength * Width * Thickness` holds for any course of constant width, on tangents, grades and curves, shoulders included, to within the term (kappa * g * r)^2 / 2 that comes from cutting sections square to the centreline's 3D tangent rather than the course's own path (r: the centroid's distance from the centreline). That is under the gate's 1e-6 on a course across the crown and on most curves; on a tight curve at a steep grade a one-sided course misses (a shoulder about 14 ft out on a 300 ft curve at 6% misses by about 4e-6), and the family withholds the formula there. Through a width transition the trapezoid form is exact on a tangent; on a curve, where the centroid drifts as the width changes, it is written only if it holds within the gate's tolerance. Earthwork's section changes at every station, so cut and fill keep their integrated volume and no volume formula; their dimensions describe them.

A Formula is written only where it is true: the family tests each against the element's declared volume at the gate's formula tolerance before writing it, the gate's formula check (M.3) recomputes each on the written file, and a formula that misses would fail every check on it.

## Errors

- `steep.above_height_ft`, `rock.depth_ft`, `rock.bench_ft`, `footprint_ft`, `max_wall_height_ft` non-positive or not finite;
- `steep.ratio` not steeper than `fill.ratio`; `rock.ratio` not steeper than `cut.ratio`;
- `walls: auto` together with a listed wall gap on the same side and stations;
- a guardrail run over a width transition (its face would move under the rail);
- automatic walls of different kinds on one side less than 2 ft apart (list a wall or a structure gap there).
- `guardrail.design_speed_mph` outside the table (45, 50);
- a requested output (`walls`, `structures`, `guardrail`) on a family that makes none.

V1's errors stand, except that "no daylight within the limit" is now a wall under `walls: auto`.

## Testing

- **Section resolver:** hand-worked sections for 4:1 below the height limit, 2:1 above it (with the guarded widening), a cut into rock with its bench, a cut that never reaches rock, a fill wall, a cut wall with its 10 ft shoulder.
- **Walls:** runs merge and end 1 ft outside; `outputs.walls` heights by hand; a too-tall wall becomes a structure candidate.
- **Guardrail:** length of need by hand at 45 and 50 mph, both directions; rounding to 12.5 ft and the 150 ft minimum; joining of near runs; AGT at a structure gap.
- **Dimensions:** every Formula passes the gate's formula check; a course on a curve gets its volume formula where it holds within the gate's tolerance and not where it misses (a one-sided shoulder on a tight, steep curve).
- **IFC:** `IfcRailing` GUARDRAIL passes `schema_issues` and the bsi rules; the shipped example gains a guarded fill, a rock cut and an automatic wall, and its GlobalIds are re-recorded.
- **V1 unchanged:** every V1 test and the V1 example build as before when the new keys are absent.

## Out of scope

The path beside the road (part C); 3:1 slopes and the runout band; fixed objects other than walls; flared terminals; the District Traffic Safety Engineer's concurrence; culvert sizing and drainage paths (the drainage study); concrete barrier as its own element.
