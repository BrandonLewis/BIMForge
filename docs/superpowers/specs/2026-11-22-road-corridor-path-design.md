# Road corridor V1.2, part C: a shared-use path on its own profile: design

Date: 2026-11-22. Roadmap row P.6. Builds on V1 (`2026-11-21-road-corridor-design.md`, #118) and V1.1 (`2026-11-21-road-corridor-v1.1-slopes-guardrail-design.md`, #122).

## Goal

Carry a separated shared-use path beside the road, on one side, on its own profile, as part of the road's section. Cut, fill and walls are computed once over the whole section, so nothing is counted twice. Where the path and the road are at different levels, the ground between them is graded as a slope, or a wall holds up the higher of the two. The family checks the path against the Caltrans Class I bikeway standards and lists every advisory deviation.

The driver is a test route held to the HDM at 45 mph. Its road climbs at up to 7 %, and the path keeps to 5 % on its own profile wherever the road is steeper.

The path may carry an equestrian tread beside its paved width, as one shared-use corridor with separate treads.

Sources:

- **HDM:** Caltrans Highway Design Manual, 08/08/2025 combined edition.
  - Chapter 1000, Index 1003.1 (pages 1000-5 to 1000-15, rev. July 1, 2020) and Index 1003.4.
  - Index 208.7 (equestrian under- and overcrossings).
- **USFS-EDG:** USDA Forest Service, *Equestrian Design Guidebook for Trails, Trailheads, and Campgrounds*, 0723-2816-MTDC, December 2007.
  - Ch. 3: shared-use, separate-tread trails; trails beside roads.
  - Ch. 4: Tables 4-1 to 4-4.
  - Ch. 5: bridges.
- **CSP-TH:** California State Parks *Trails Handbook*, Ch. 7 (2019), Ch. 9 (2018) and Ch. 18 (railings, 2018).

The HDM's figures are standards. The equestrian figures are guidance, so the family makes them defaults and advisories, never errors.

## Decisions

These were made with the user on 2026-11-22.

1. **Part of the road section while it is beside the road.** There the path is the outer part of one side of the road's section, with its own offset and its own profile. Its separation can grow, so the path can drift away from the road and stay part of its section.
2. **The profile is designed and given in the spec**, in the same form as `params.profile`. The family builds it and checks it; it does not fit grades. A project fits the path's grade in its own design work and writes the result into the spec.
3. **Between the road and the path:**
   - a straight slope, where one at 2:1 or flatter fits;
   - otherwise a wall holding up whichever of the two is higher.
4. **On structures the path follows the deck by default.** Its profile must meet the deck at each structure gap's ends. A deck grade over 5 % is an advisory deviation, because HDM 1003.1(14) says "should".
5. **The path may have its own bridge** wherever it makes sense, for example where a deck is steeper than 5 % or a strip wall gets too tall. A path gap (below) marks where it goes. Inside it, the path keeps its own profile and is off the road's deck.
6. **An equestrian tread can be part of the shared-use path.** It is unpaved and lies beside the paved width, away from the road, with a buffer between them. It shares the path's profile, side, gaps and own stretches. Horses are not allowed on a Class I path (HDM Ch. 200, before 208.7), so the tread is separate from it.
7. **The path may wander off on its own corridor.** Bike and equestrian paths can meander away from the road. Where one does, it becomes its own corridor in the same build: its own alignment and profile, a path section, its own earthwork and walls. It hands over to and from the road's section at stations the spec names. The footprints of the two never overlap, so earthwork is still counted once.

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
    gaps:                           # the path's own structures
      - {from: 3440, to: 4660, kind: structure}   # a separate path bridge
    own:                            # stretches where the path leaves the road
      - from: 6000                  # road station of the hand-over
        to: 7400                    # road station where it rejoins
        run:                        # the path's own horizontal, from the
          - {kind: curve, delta: "30-0-0", radius: 300.0, turn: R, length: 157.08}
          - ...                     # hand-over point, the road's form
        profile: {curves: [...]}    # on the path's own stationing
    equestrian:                     # optional: a tread beyond the paved path
      width: 8.0                    # two-way tread (USFS-EDG Table 4-2: 8-12)
      buffer: 6.0                   # paved edge to tread edge (USFS-EDG Ch. 3)
      clear_ft: 3.0                 # graded clear each side (USFS-EDG Table 4-1)
      cross_slope: -0.02            # away from the road (Table 4-4: 2-5 %)
      courses:                      # DG surfacing; depth per the geotech report
        - {name: EQ-DG, type: PAVEMENT, thickness: 0.33}
      fence: true                   # open rail fence on the tread side of the buffer
      fence_height_ft: 4.5
      rail_height_ft: 4.5           # on walls along the tread (54 in)
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

## The equestrian tread

Where `path.equestrian` is given, the path's outer shoulder is replaced by the tread. Outward from the paved path, the section is:

1. **The buffer**, `buffer` wide from the paved path's outer edge to the tread's edge.
   - It is graded at `shoulder.slope`, away from the road. The paved path's 2 ft graded shoulder and the tread's inner clear strip lie within it.
   - It is earth, left for planting.
2. **The tread**, `width` wide, at `cross_slope`, with its `courses` below it.
   - Each course's thickness is held normal to the path's grade, as the paved courses are.
3. **The outer clear strip**, `clear_ft` wide, at `shoulder.slope`.
4. **The outer slope**, under the same rules as without a tread.

**Levels.** The tread has no profile of its own. Its elevation follows from the path's profile, through the paved cross slope, the buffer and its own cross slope. So it leaves the road with the path, onto a path gap or an own stretch, and stays beside the paved width.

**The fence.** With `fence: true`, an open rail fence runs along the buffer, `clear_ft` in from the tread's inner edge, over the tread's stations. It is HDM 1003.4's open fence on the equestrian side, keeping sight lines open. It stops at gaps.

**Rails.** A wall along the tread's outer side, or a strip wall where the tread is the higher side, carries a rail of `rail_height_ft`, 54 in (USFS-EDG Ch. 3 and 5; CSP-TH 18.2.1). The paved path keeps its 42 in rail where it is on the wall side.

**On a road deck.** In a road structure gap the whole path, tread included, is on the deck, so the deck must be wide enough for it. `path_checks` lists, for each gap, the width the deck has to carry, measured from the road's edge of shoulder to the tread's outer clear edge, and the 54 in rail the tread side needs. The bridge family sizes the deck from that.

**Advisory checks** (`path_checks`, guidance, never errors):

- `buffer` under 6 ft (USFS-EDG Ch. 3; 2–3 ft only where constrained);
- tread `width` under 8 ft (two-way, USFS-EDG Table 4-2);
- `clear_ft` under 3 ft (Table 4-1);
- tread cross slope outside 2–5 % (Table 4-4);
- the path's grade over 10 % sustained, or over 15 % for more than 200 ft (USFS-EDG Table 4-3; HDM 208.7 gives 10 % at crossings). These are listed for the tread in addition to the paved path's 5 % rows.

**Errors:**

- a non-positive `width`, `buffer`, `clear_ft`, course thickness, `fence_height_ft` or `rail_height_ft`;
- a `buffer` narrower than `shoulder.width`, which would leave no room for the paved path's graded shoulder (HDM 1003.1(1), a "shall").

## The strip between road and path

The strip runs from the road's hinge to the outer edge of the path's inner shoulder. It is resolved in this order, at each station:

- **Natural ground between.** First, the road's outer slope is tried at V1.1's rules, and the path's inner slope at the same rules mirrored. If both daylight before they meet, the ground between them is left as it is. This is what lets the separation grow: the path drifts away and the strip becomes two slopes with ground between.
- **A slope.** Otherwise, The strip is a straight line between those two points if its slope is `strip.max_ratio` (2:1) or flatter, up or down. It may lie in cut or in fill. The earthwork measures it against the ground with the rest of the section.
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

## Where the path wanders off (own stretches)

`path.own` lists stretches where the path leaves the road and runs on a corridor of its own. Each stretch gives the road stations where it hands over (`from`) and rejoins (`to`), the path's own horizontal `run` and its own `profile`.

**The horizontal**

- The run starts at the hand-over point: the path's centreline at road station `from`, at that station's separation, heading the road's way. The family derives that point and heading; the spec gives no POB.
- **Rejoining.** The run must end on the path's centreline at road station `to`, at that station's separation, heading the road's way.
  - The tolerance is 0.1 ft in position and 0.1° in heading.
  - Otherwise it is an error naming both points.

**The profile**

- It is on the path's own stationing, which starts at 0+00 at the hand-over.
- It must meet `path.profile` at both ends within 0.01 ft. `path.profile` is on road stations.

**The section and earthwork**

- **The section:** the path's paved width, courses and shoulders, crowned or one-way by `cross_slope`, with V1.1's side slopes on both sides. Those are fill 4:1 or 2:1 by the steep rule, and soil over rock with benches.
- **Walls:** automatic, with the path's rail on fill walls.
- **Footprint:** `footprint_ft`, if given, applies to it as well.
- **Earthwork:** its own cut and fill elements, separate from the road's.
- **The road's section through the stretch:** the same as if there were no path on that side, as in a path gap.

**Hand-over**

- Each hand-over and rejoin station must be one where the beside section resolves to **natural ground between** (see the strip), so the two footprints are already apart. Otherwise it is an error naming the station. Move the hand-over or widen the separation.
- **No overlap.** Along the own stretch, the path's plan footprint (daylight to daylight) must not cross the road's footprint at any station. The check is a polygon test in plan; a crossing is an error naming the path station and the road station. This is what keeps the earthwork counted once.

**Checks on own stretches.** The grade, crest and deck checks apply as they do beside the road. These apply as well:

- **Horizontal radius** under the 1003.1(10) minimum for the design speed (90 / 160 / 260 ft at 20 / 25 / 30 mph): advisory ("should").
- **Radius under the no-superelevation radius** (100 / 180 / 320 ft): advisory. The path's cross slope stays at most 2 %, which is the HDM's maximum superelevation for a path.
- **Path gaps inside an own stretch** are on the path's own stationing. Use `own[].gaps` for a path bridge across a creek.

**IFC**

- **The alignment:** each own stretch has its own `IfcAlignment`, horizontal and vertical, aggregated to the project as C.12 requires. Its solids are swept along that alignment's `IfcGradientCurve`. Short path profiles have two PVIs, so `add_alignments` must be fixed for them first: it crashes on a profile with two PVIs today.
- **The path's parts:** its courses and rails belong to the same path `IfcRoadPart`. Its earthwork is `IfcEarthworksCut` and `IfcEarthworksFill`, named for the path, and voids TERRAIN as the road's does.

## The path's own structures (path gaps)

`path.gaps` lists stretches where the path is on a structure of its own, such as a separate path bridge or a path culvert. Each is `{from, to, kind: structure}`.

**Inside a path gap**

- The family builds nothing for the path: no path courses, no strip, no path walls. The structure belongs to its own family.
- The path's side of the road's section ends at the road's hinge and takes V1.1's outer slope, with its automatic walls and guardrail. The section is the one the road would have without a path.
- **Inside a road gap too:** where a path gap overlaps a road structure gap, the road's deck carries no path there. Its width is the bridge family's business. The family only lists the overlap.
- **The path's profile still runs through the gap.** It is the path structure's grade, so the grade and crest checks apply to it as anywhere else, and the deck's grade does not.
- The separation through the gap is the path structure's offset from the road. It is kept in `outputs.path` but not held to the 5 ft rule, since a bridge is separated by its own edge.

**At a path gap's ends**

- The path's section is built up to 1 ft outside each end, as V1 wall gaps are.
- **The deck-meeting check is waived** at a road structure gap's end that lies inside a path gap.
- **The approach rule is waived** at a road structure gap's end that lies inside a path gap. The separation need not narrow to `deck_separation_ft` there.

**Where one makes sense.** The family does not place path gaps itself; the designer adds them. It does point out where one would help:

- **Too-tall walls:** a strip wall or a path outer wall taller than `max_wall_height_ft` becomes a structure candidate in `outputs.structures`, as V1.1's walls do. Its `carries` column is set to `path`.
- **Steep decks:** a deck stretch over 5 % is listed in `path_checks` with the note "or a separate path structure".

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
- A path gap outside the path's stations, overlapping another path gap, or of a kind other than `structure`.
- Own stretches that overlap each other or a path gap.
- An own stretch whose run does not rejoin.
- A hand-over without natural ground between.
- A path footprint that crosses the road's.
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

Beside the road, the path follows the road's horizontal alignment at an offset. Its radii are the road's, give or take the offset: 500 ft or more on the driving route, far above the 90–260 ft minimums of 1003.1(10). So radius is checked only on own stretches.

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
- **The equestrian tread** is its own `IfcRoadPart` beside the path's.
  - `PredefinedType` USERDEFINED, `ObjectType` `EQUESTRIANTRAIL`, dictionary class `road-corridor-equestrian-tread`.
  - Its DG courses are `IfcCourse` PAVEMENT, with the same quantities, dimensions and formulas as the paved courses.
  - Its 54 in rail is an `IfcRailing` GUARDRAIL of type `road-corridor-equestrian-rail`.
  - Its fence is an `IfcRailing` FENCE of type `road-corridor-path-fence`. It carries `BIMForge_Guardrail` with its height and stations, and `Length` as `EndStation - StartStation`.

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
- **Strip, natural ground:** a path drifting out to 60 ft on a cross slope gives two slopes with ground between, and its earthwork equals the road's alone plus the path's alone.
- **Own stretches:**
  - the derived hand-over point and heading match a hand computation;
  - a run ending 0.2 ft off the rejoin point is an error;
  - a hand-over at a station without natural ground between is an error;
  - a run that swings back into the road's footprint is an error naming both stations;
  - a 150 ft radius is listed at 25 mph and 30 mph but not at 20;
  - its IfcAlignment passes `gate.alignment_issues`, and a two-PVI path profile builds.
- **Equestrian tread:**
  - the section with a tread is hand-worked, covering the buffer, the tread, the clear strip and the outer slope;
  - its elevation follows the path's profile through the cross slopes;
  - it goes with the path onto an own stretch;
  - the fence runs over the tread's stations and stops at gaps;
  - a wall along the tread carries a 54 in rail;
  - a 4 ft buffer is listed as advisory, and a 1.5 ft buffer is an error;
  - a deck gap lists the width it must carry;
  - the tread's road part and its courses, rail and fence pass `schema_issues` and the bsi rules.
- **Path gaps:**
  - inside one, the section and earthwork equal those of the same corridor with no path;
  - a path gap over a road structure gap waives the deck-meeting and approach rules there, and its profile is checked for grade;
  - a strip wall taller than `max_wall_height_ft` becomes a structure candidate with `carries: path`.
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

- Horizontal sight lines on the path's own curves (1003.1(13)), which need the obstruction surface. Radius is checked.
- A path stretch that crosses the road at grade or under it. A crossing is its own design. Equestrian crossings need a 10 x 10 ft opening (HDM 208.7), with 12 ft preferred (USFS-EDG).
- Vertical clearance over the treads: 8 ft for the path and 10–12 ft for riders. Nothing in the corridor is overhead.
- An equestrian tread that splits from the paved path onto its own line, or one on the road side of the paved path. That needs a 54–60 in barrier toward traffic (USFS-EDG Ch. 3).
- An equestrian center or trailhead. These are site features.
- Drainage in the strip (the drainage study).
- Concrete barrier as its own element, carried over from V1.1.
- Path crossings and ramps.
- Fitting the path's grade. That belongs to the project's design work, not the family.
