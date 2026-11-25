# Terrain from a spec and a command (G.9): design

Date: 2026-11-23, revised 2026-11-24 (one `terrain:` block). Roadmap row G.9. Builds on P.6 (the road corridor's `ground:`).

## Goal

A model's existing ground is named once, in one top-level `terrain:` block, for every family. It is written as one TERRAIN element, and the road corridor calculates against the same ground. One command fetches it ahead of the build, so every rebuild after the first is offline. The shift from 3DEP's NAVD88 to the project's vertical datum comes from the datum the project names, never a silent zero.

## What the code does today

- `bimforge.terrain.attach_terrain` fetches 3DEP (the 1 m DEM, or the lidar point cloud's bare earth), shifts it by `vshift_m` or an NCAT lookup, meshes it, optionally carves excavation frustums, and adds an IfcGeographicElement TERRAIN carrying its provenance. Every download is cached under a path stem.
- Only the road corridor calls it from a spec: `ground: {source: 3dep, cache, spacing_m, margin_ft, vshift_m}` (`bimforge/author/corridor/ground.py`). The corridor needs the ground before it builds (its daylight lines are found against it), adds the TERRAIN element in the model frame, and its cuts void it (`Element.voids`, IfcRelVoidsElement). `vshift_m` defaults to 0 whatever `project.vertical_datum` says. `ground: {source: plane}` adds a TERRAIN element meshed from the plane.
- No other family reads terrain, and no structure family digs an excavation.
- `est-bim` has no terrain command (`terrain-diff`, `contours`, `contour-surface` work on plan-sheet surfaces).

## Existing grade and finish grade

The TERRAIN element is the existing grade, and a model has at most one. The finish grade is not a surface of its own: it is the tops of what is built (the courses, the fills, the face a cut leaves in the voided ground, a structure's concrete and backfill). This design does not change that; whether to write a finish-grade surface is roadmap row G.10.

## The spec

```yaml
terrain:
  source: dem          # dem (3DEP 1 m DEM, default) | lpc (lidar bare earth)
  cache: terrain/site  # path stem, relative to the spec's directory; required
  margin_ft: 200       # around the footprint (default 200)
  spacing_m: 1.0       # cell size, in METRES (default 1.0)
  vshift_m: 0.71       # optional: overrides the datum rule
```

- It needs `project.epsg` and a real `project.base` (ProjectContext already refuses a zero base with an epsg); without an epsg the build fails: `terrain: needs project.epsg`. Unknown keys fail, naming them.
- `build_from_spec` parses it into a `TerrainSpec` (source, cache path resolved against the spec's directory, margin, spacing, vshift) before the family builds. The block is not a family parameter, so the unread-params check never sees it.

### The corridor's `ground:`

The corridor's `ground:` says only what the corridor calculates against:

- `ground: {source: terrain}`: the top-level `terrain:` ground. Without a `terrain:` block the build fails: `ground: source terrain needs a top-level terrain: block`. The corridor fetches it over its own footprint (the alignment grown by the corridor's reach and the margin, as today), measures against it and adds the TERRAIN element.
- `ground: {source: plane, elevation, slope_n, slope_e}`: a test plane, for CI and the shipped example. With no `terrain:` block it adds its plane TERRAIN element, as today, so the example's cuts still have a host to void. With a `terrain:` block the plane still sets the corridor's levels, cut and fill, and the element written is the fetched ground, not the plane.
- `ground: {source: 3dep, cache, spacing_m, margin_ft, vshift_m}`, the 0.1.132 form, keeps working. It is read as `terrain: {source: dem, cache, spacing_m, margin_ft, vshift_m}` plus `ground: {source: terrain}`, with a build-log note: `ground: source 3dep is now terrain: {...} with ground: {source: terrain}`. The IFC is the same either way. A spec with both the old form and a `terrain:` block fails: `ground: source 3dep and a terrain: block both name the ground; keep the terrain: block`. No shipped spec or fixture uses the old form.

The corridor receives the `TerrainSpec` from `build_from_spec` (as `params["terrain"]`, set only when its ground's source is `terrain` or the translated `3dep`, so no other family is handed a key it does not read).

## Who adds the element

One rule: the TERRAIN element is added once. A family that calculates against the ground (the corridor, on `source: terrain`) adds it over its own footprint while it builds. Otherwise, when the spec has `terrain:`, `build_from_spec` adds it after the family builds (and after `spatial_parts` and the routes), over the model's footprint; a plane TERRAIN element is then replaced by the fetched one.

The model's footprint: the plan extent of every element's placed geometry (model frame x and y, feet), leaving out TERRAIN elements and elements with no geometry, converted to CRS coordinates by `base_e + x`, `base_n + y` (`ProjectContext.local` reversed) and the CRS unit, then grown by `margin_ft` each way. It reuses the model's bounds code (`placement.local_bounds` over placed bodies, as `backfill._placed_bounds` places them).

## The vertical datum

One function, `terrain_vshift(ctx, cache_stem, vshift_m=None, log=print) -> (shift_m, source)`, used wherever the terrain is fetched:

| Case | Shift | Source written |
|---|---|---|
| `vshift_m` given | that value | `spec vshift_m` |
| `project.vertical_datum` NAVD88 (any case, `NAVD 88`, `NAVD-88`) | 0 | `NAVD88: none` |
| `project.vertical_datum` NGVD29 (likewise) | NOAA NCAT at the base point, cached in `<stem>-3DEP-vshift.json` (`ncat_vertshift`) | `NOAA NCAT VERTCON 3.0` |
| anything else, or none | fails: `terrain: 3DEP heights are NAVD88; project.vertical_datum <x> has no rule; give terrain.vshift_m` | |

The base point's latitude and longitude come from pyproj (`EPSG:<epsg>` to 4326); they also give `attach_terrain` its `lonlat` for the 3DEP work-unit vintage. An unreachable NCAT with no cached shift fails the build, saying to give `vshift_m`; no fallback grid is supplied. The applied shift and its source are written into the provenance (`AppliedVerticalShift`, and a new `VerticalShiftSource`).

A corridor on the old `ground: {source: 3dep}` with no `vshift_m` and an NGVD29 project now gets the NCAT shift where it got 0. On NAVD88 it builds as before.

## The element

`attach_terrain` as it is, called with the footprint, the shift, the cache stem and `lonlat`, then moved into the model frame as the corridor moves its own (`corridor.ground._to_model_frame`, moved to `bimforge.terrain.attach` and shared). It is contained where `emit_ifc` puts every element (the structure's default container, the storey on the IFC4 building path), as the corridor's TERRAIN is today; moving it to the IfcSite would be an emitter change, outside this design. Nothing new is carved: no structure family has a cut, and the corridor's cuts void the ground as today. No pay code, no quantities, no classification; takeoff is unchanged.

## The command

`est-bim terrain SPEC [--refresh] [--family-path DIR]`:

1. loads the spec as `est-bim build` does and builds the model in memory (no gate, no outputs), which fetches the terrain wherever the build would (`--refresh` refetches);
2. prints the footprint (CRS units and the size in feet), cells, source, source project, acquisition dates, quality level, the shift and its source, and the cache files.

A spec with no `terrain:` block (and no old `ground: {source: 3dep}`) prints `terrain: the spec asks for no terrain` and exits 0. Once it has run, `est-bim build` reads only the cache. `refresh` is a command flag only, so a build never refetches by itself.

## Not changed

Shipped examples (none uses `terrain:` or `source: 3dep`), takeoff, GlobalIds of existing elements, the corridor's plane ground.

## Testing

All offline: the fetchers (`fetch_3dep_dem`, `fetch_3dep_lpc`, `workunit_meta`, the NCAT request) are replaced with a synthetic grid and canned responses, as the corridor's tests do.

- A B3 wall spec with `terrain:` gets one TERRAIN element whose plan extent covers the wall's footprint plus the margin, placed under the wall in the model frame, with the provenance's source, spacing, shift and shift source.
- The datum rule: NAVD88 (0), NGVD29 (the stubbed NCAT value, cached; a second run makes no request), explicit `vshift_m`, a missing or unknown datum failing, NCAT unreachable failing.
- Spec errors: no epsg, no cache, an unknown key, `ground: {source: terrain}` with no `terrain:` block, the old `source: 3dep` together with `terrain:`.
- A corridor on `ground: {source: terrain}` measures against the fetched ground and carries one TERRAIN element, voided by its cuts.
- The old `ground: {source: 3dep}` builds an IFC identical to the same spec written as `terrain:` plus `ground: {source: terrain}`, and logs the note.
- A plane-ground corridor without `terrain:` is unchanged (the shipped example's IFC is byte-identical); with `terrain:` it carries one TERRAIN element, the fetched one.
- `est-bim terrain` fetches once and reports; run again it reports from the cache with the fetchers failing on any call; `--refresh` calls them again; a spec without terrain exits 0.
- The IFC validators and the buildingSMART rules job pass on a B3 wall with terrain.
