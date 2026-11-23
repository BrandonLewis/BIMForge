# Road corridor V1.2, part C: a shared-use path on its own profile: design

Date: 2026-11-22. Roadmap row P.6. Builds on V1 (`2026-11-21-road-corridor-design.md`, #118) and V1.1 (`2026-11-21-road-corridor-v1.1-slopes-guardrail-design.md`, #122).

## Goal

Carry a separated shared-use path beside the road, on one side, on its own profile, as part of the road's section. Cut, fill and walls are computed once over the whole section, so nothing is counted twice. Where the path and the road are at different levels, the ground between them is graded as a slope, or a wall holds up the higher of the two. The family checks the path against the Caltrans Class I bikeway standards and lists every advisory deviation.

The driver is a test route held to the HDM at 45 mph. Its road climbs at up to 7 %, and the path keeps to 5 % on its own profile wherever the road is steeper.

Sources: Caltrans Highway Design Manual (HDM, 08/08/2025 combined edition), Chapter 1000, Index 1003.1 (pages 1000-5 to 1000-15, rev. July 1, 2020).

## Decisions

These were made with the user on 2026-11-22.

1. **Part of the road section.** The path is not a second corridor. It is the outer part of one side of the road's section, with its own offset and its own profile.
2. **The profile is designed and given in the spec**, in the same form as `params.profile`. The family builds it and checks it; it does not fit grades. A project fits the path's grade in its own design work and writes the result into the spec.
3. **Between the road and the path:**
   - a straight slope, where one at 2:1 or flatter fits;
   - otherwise a wall holding up whichever of the two is higher.
4. **On structures the path follows the deck.** Its profile must meet the deck at each structure gap's ends. A deck grade over 5 % is an advisory deviation, because HDM 1003.1(14) says "should".

## Spec format

```yaml
params:
  path:
    side: R                         # L or R of travel
    stations: [3460, 12780]         # optional; default the whole corridor
    separation: [[3460, 1.5], [3560, 10.0], [4600, 10.0]]
                                    # ft, by station: road's outer edge of
                                    # shoulder to the path's paved edge
    width: 12.0                     # paved
    cross_slope: -0.02              # one direction, - is away from the road
    shoulder: {width: 2.0, slope: -0.05}      # graded, both sides, sloping away
    courses:                        # top down, like section.courses
      - {name: PATH-HMA, type: PAVEMENT, thickness: 0.25}
      - {name: PATH-AB, type: CORE, thickness: 0.50}
    profile: {curves: [...]}        # the same form as params.profile
    design_speed_mph: 20            # 20 (mopeds prohibited) or 30
    strip: {max_ratio: 2.0}         # steepest slope between road and path
    approach_ft: 100                # see Separation
    deck_separation_ft: 1.5         # the deck's barrier between traffic and path
    rail_height_ft: 3.5             # the path's rail on a wall (42 in)
outputs:
  path: out/<name>.path.csv
  path_checks: out/<name>.path-checks.csv
```

- Every key is optional except `side`, `separation`, `width`, `courses` and `profile`.
- A spec without `path` builds exactly as V1.1 does.
- Widths and separations are interpolated linearly by station, with the end values holding, as V1's `widths` are.

## The section on the path's side

Outward from the road's crown, the path's side is:

1. the road's components, unchanged, including any climbing-lane widening;
2. the road's hinge, as V1.1 defines it, including the guardrail widening where the road is guarded;
3. **the strip** (see below);
4. the path's inner shoulder;
5. the paved path;
6. the path's outer shoulder;
7. the outer slope, cut or fill, under V1.1's rules (4:1 or 2:1 with the steep rule, soil over rock with benches and catchment, automatic walls, the footprint).

**Placement and levels**

- The separation is measured from the road's outer edge of shoulder, not from the centreline. Where the road widens (a climbing lane, a shoulder widening, the 10 ft shoulder beside a cut wall), the path moves out with it.
- **The path's paved edge, inner side:** at the separation. Its elevation is the path's profile at that station.
- **The path's cross slope:** `cross_slope`, in one direction, away from the road. It does not take the road's superelevation, and the HDM allows at most 2 % (1003.1(10)).

**Structure**

- **Courses:** under the paved width only. Each course's `thickness` is held normal to the path's own grade (see Dimensions and formulas).
- **Shoulders:** graded earth at the finished surface, sloping away at `shoulder.slope`.
- The earthwork's top surface follows the subgrade under the path's courses and the finished surface on its shoulders.

**The road's other side** is unchanged from V1.1.

## The strip between road and path

The strip runs from the road's hinge to the outer edge of the path's inner shoulder.

- **A slope.** The strip is a straight line between those two points if its slope is `strip.max_ratio` (2:1) or flatter, up or down. It may lie in cut or in fill. The earthwork measures it against the ground with the rest of the section.
- **Road higher, slope too steep:** a **fill wall at the road's hinge**, carrying a barrier, as V1.1's automatic fill wall does. The strip is level at the path's shoulder-edge elevation from the wall's foot to the path.
- **Path higher, slope too steep:** a **wall at the outer edge of the path's inner shoulder**, retaining the path, with the path's rail on top (`rail_height_ft`, HDM's 42 in). The strip is level at the road's hinge elevation from the road to the wall's foot.
  - The road faces this wall at least 5 ft beyond its edge of shoulder, so its shoulder is 13 ft or more from the wall. That is wider than V1.1's 10 ft cut-wall shoulder (HDM 309.1(3)(b)), so the road's shoulder does not widen.

**Walls in the strip**

- These walls follow V1.1's rules:
  - they join the same wall runs (merged when closer than one station interval, 1 ft lead-in);
  - they appear in `outputs.walls`, with `location` either `strip` or `outer`;
  - a fill wall taller than `max_wall_height_ft` becomes a structure candidate.
- A wall needs `walls: auto`. Without it, a strip that does not fit is an error that names the station.

**Guardrail on the road.** Where the road is higher and the strip is steeper than `fill.ratio` (4:1), the road's side is **guarded** at that station, as a V1.1 steep fill is.
- The guardrail's widening is taken out of the strip.
- If that leaves less than 2:1 room, the strip takes a wall instead.

**The path's outer side.** A fill wall on the path's outer side (V1.1's automatic wall, at the path's outer shoulder) also carries the path's rail.

## Separation (HDM 1003.1(7))

**The rules**

- **At least 5 ft** from the road's edge of shoulder to the path's paved edge, everywhere except the approaches below. Less is an error.
- **Under 10 ft: a barrier.** The stretch is listed in `path_checks` as needing one. Guardrail on the road (above) counts as that barrier. Concrete barrier as its own element is still out of scope, as in V1.1.
- **Approaches to a structure gap.** Within `approach_ft` of a structure gap's end, the separation may narrow to `deck_separation_ft`, so that it meets the deck's layout: traffic, a 1.5 ft barrier, then the path. A barrier is listed through the narrowing. Any part of it under 5 ft is listed as a deviation from the 5 ft minimum.
- **At a structure gap's end**, the separation must equal `deck_separation_ft`, within 0.01 ft.

**What a structure gap does**

- In a structure gap the path is on the deck. The family builds nothing there for the path, just as it builds nothing for the road.
- **Meeting the deck.** At each end of the gap, the path's profile must equal the road's cross slope at that station (superelevation included), extended from the road's edge of shoulder to the path's paved edge, within 0.01 ft. Otherwise the build fails with the station, both elevations and the difference.
- **Deck grade.** The deck's grade along the path is the road profile's grade. Any stretch of a gap where it is over 5 % is listed as advisory.

## Checks (HDM 1003.1)

**Errors**

- `path.side` not `L` or `R`.
- A non-positive `width`, `shoulder.width`, course thickness, `approach_ft` or `rail_height_ft`.
- `cross_slope` outside 1–2 % in magnitude (1003.1(16), DIB 82).
- `shoulder.slope` outside 2–5 % (1003.1(16)), or not sloping away from the path.
- `design_speed_mph` other than 20 or 30 (Table 1003.1).
- A profile that does not cover the path's stations.
- `path.stations` outside the alignment.
- Separation under 5 ft outside an approach, or under `deck_separation_ft` anywhere.
- The path not meeting a deck at a gap end.
- A strip that does not fit without `walls: auto`.
- A listed wall gap on the path's side overlapping the path's stations. Its offset would be ambiguous; use `walls: auto`.
- A requested `path` or `path_checks` output with no `path`.

**Advisory, listed in `path_checks`, one row per stretch:** check, from station, to station, value, limit, HDM reference.

- **Grade over 5 %**, on the path's profile or on a deck (1003.1(14)).
- **Sustained grade over 2 %** for more than 500 ft (1003.1(14), "should be limited to 2 percent"). This is listed for information only: on a mountain route it is most of the path.
- **Crest vertical curve short of stopping sight distance** (1003.1(11), (12)).
  - The required length is L = AS²/1600 when S < L, or L = 2S − 1600/A when S > L.
  - S is 125 ft at 20 mph and 230 ft at 30 mph.
  - A downgrade steeper than 4 % for more than 500 ft takes 30 mph whatever `design_speed_mph` says (Table 1003.1). The check works this out for each curve, from the grades on its two sides.
- **Separation under 10 ft**: a barrier is needed.
- **Separation under 5 ft** on an approach.
- **A wall in the strip**, with its side and height.

The path follows the road's horizontal alignment at an offset. Its radii are the road's, give or take the offset: 500 ft or more on the driving route, far above the 90–260 ft minimums of 1003.1(10). So horizontal curvature and the 1003.1(13) sight line are not checked; they are out of scope.

## IFC

- **The road part.** The path is an `IfcRoadPart` under the corridor's ROADSEGMENT, beside its CARRIAGEWAY and SHOULDER parts.
  - `PredefinedType` USERDEFINED, `ObjectType` `SHAREDUSEPATH`. IfcRoadPartTypeEnum has no path value; SIDEWALK is for pedestrians.
  - It has a dictionary class, `road-corridor-shared-use-path`, in the family dictionary.
- **Courses.** The path's courses are `IfcCourse`, typed by `IfcCourseType`, aggregated to that part.
  - They carry `Qto_CourseBaseQuantities`, `BIMForge_Dimensions` and Formulas, as the road's courses do.
  - `Offset` is the course centroid's offset from the road's centreline, LT or RT.
- **Bodies.** Every solid is `IfcSectionedSolidHorizontal` along the road's `IfcGradientCurve`, cut at the road's stations, as V1 does.
  - The path's courses are separate solids.
  - The earthwork solids take in the whole section, path included.
- **The path's rail** on a wall is an `IfcRailing`.
  - `PredefinedType` GUARDRAIL, which IFC defines as a railing that keeps people from falling.
  - Its own type, `road-corridor-path-rail`, sets it apart from the road's MGS.
  - It carries `BIMForge_Guardrail` with its height and stations.
- **Walls** are written as V1.1's automatic walls are.

## Dimensions and formulas

The road's sections are cut square to the road centreline's 3D tangent. The path runs at its own grade, so those planes cut its courses obliquely. To keep the formula honest, each path course's **thickness is held normal to the path's own grade**:

- in the section plane, the course is `thickness / cos θ` deep;
- θ is the angle between the plane's normal and the path's tangent at that station.

A sweep of plane sections then has volume ∫ A (n̂ · dc), where c is the centroid's path:

- the oblique area A = W t / cos θ;
- the centroid's advance along the plane's normal is |dc| cos θ.

The two cosines cancel, so the volume is W t × PathLength. `Volume = PathLength * Width * Thickness` therefore holds for the path's courses, as it does for the road's, except for V1.1's curvature residual (κgr)²/2.

The family writes the formula wherever it holds within the gate's 1e-6 and withholds it elsewhere, as V1.1 does. On a 500 ft curve, with the path's centroid about 30–40 ft out at the road's 7 %, the residual is about 1e-5, so the formula is withheld there. Each such stretch is listed in the build log.

Without the correction, a 2 % grade difference would miss by about 2e-4, and the formula would be withheld along most of the climb.

`PathLength` is the path course centroid's 3D length, along its offset and following its own profile, between the course's stations, as V1.1 defines it.

## Outputs

- **`outputs.path`**, one row per station:
  - station;
  - side;
  - separation;
  - the path's centre offset from the centreline;
  - the road's hinge elevation and the path's elevation;
  - the difference between them;
  - the path's grade;
  - the strip: its slope ratio, or `wall-road` or `wall-path`;
  - whether a barrier is needed;
  - a note: `deck`, `approach`, `grade>5%`.
- **`outputs.path_checks`**: the advisory rows listed under Checks.
- **The masshaul, walls, structures and guardrail outputs** include the path's side as part of the section. They need no new columns, except `location` in `walls`.

## Testing

- **Section resolver, on plane ground, hand-worked:**
  - path level with the road (a strip slope);
  - path 3 ft below (a 2:1 strip that fits);
  - path 12 ft below (a road fill wall with a barrier);
  - path 12 ft above (a path wall with a rail);
  - the separation moving out with a widened shoulder.
- **Earthwork:** on plane ground, the section's cut and fill equal the hand-computed polygon areas. There is no double count: a path level with the road and 0 ft from it gives the same earthwork as a road whose shoulder is that much wider.
- **Separation:**
  - under 5 ft is an error;
  - an approach narrowing to 1.5 ft at a gap end builds;
  - a gap end with the wrong separation is an error.
- **Deck meeting:** a path profile 0.02 ft off the deck at a gap end is an error naming the station; at 0.005 ft off it builds.
- **Checks:**
  - a 6 % path grade is listed;
  - a crest VC short of 125 ft SSD at 20 mph is listed, and so is one that is enough at 20 mph but short at 30 mph on a 4.5 % downgrade 600 ft long;
  - a crest that is enough is not listed.
- **Formulas:**
  - path courses on a tangent at a grade 2 % off the road's pass the gate's formula check;
  - on a 500 ft curve at a 7 % road grade, the formula is withheld and the stretch is logged.
- **IFC:**
  - the path's IfcRoadPart (USERDEFINED, `SHAREDUSEPATH`) and its rail pass `schema_issues` and the bsi rules;
  - the inventory is regenerated.
- **Example:** the shipped example gains a path on the right with a stretch on its own profile, an approach to the bridge gap, and a strip wall. Its GlobalIds are re-recorded.
- **V1.1 unchanged:** every V1 and V1.1 test, and the V1.1 example without `path`, build as before.

## Out of scope

- A path that leaves the road horizontally, on its own alignment.
- Writing the path's line as its own `IfcAlignment`.
- The path's horizontal curvature and its horizontal sight lines.
- Drainage in the strip (the drainage study).
- Concrete barrier as its own element, carried over from V1.1.
- Path crossings and ramps.
- Fitting the path's grade. That belongs to the project's design work, not the family.
