# Terrain from a spec and a command (G.9): design

Date: 2026-11-23. Roadmap row G.9. Builds on P.6 (the road corridor's `ground:`).

## Goal

Any spec can ask for the existing ground around its model, and one command fetches it ahead of the build, so a model gets USGS 3DEP terrain without a script and every rebuild after the first is offline. The shift from 3DEP's NAVD88 to the project's vertical datum comes from the datum the project names, never a silent zero.

## What the code does today

- `bimforge.terrain.attach_terrain` fetches 3DEP (the 1 m DEM, or the lidar point cloud's bare earth), shifts it by `vshift_m` or an NCAT lookup, meshes it, optionally carves excavation frustums, and adds an IfcGeographicElement TERRAIN carrying its provenance. Every download is cached under a path stem.
- Only the road corridor calls it from a spec: `ground: {source: 3dep, cache, spacing_m, margin_ft, vshift_m}` (`bimforge/author/corridor/ground.py`). The corridor needs the ground before it builds (its daylight lines are found against it), adds the TERRAIN element in the model frame, and its cuts void it (`Element.voids`, IfcRelVoidsElement). `vshift_m` defaults to 0 whatever `project.vertical_datum` says.
- No other family reads terrain, and no structure family digs an excavation.
- `est-bim` has no terrain command (`terrain-diff`, `contours`, `contour-surface` work on plan-sheet surfaces).

## The spec

A new top-level block, read by `build_from_spec` for every family:

```yaml
terrain:
  source: dem          # dem (3DEP 1 m DEM, default) | lpc (lidar bare earth)
  cache: terrain/site  # path stem, relative to the spec's directory; required
  margin_ft: 200       # around the model's footprint (default 200)
  spacing_m: 1.0       # cell size, in the CRS's own unit as attach_terrain takes it (default 1.0)
  vshift_m: 0.71       # optional: overrides the datum rule
```

- It needs `project.epsg` and a real `project.base` (ProjectContext already refuses a zero base with an epsg); without an epsg the build fails: `terrain: needs project.epsg`.
- Unknown keys fail, naming them.
- A road corridor spec whose `ground:` is `source: 3dep` and that also has `terrain:` fails: `terrain: the corridor's ground (source 3dep) already adds the terrain; drop one`. A corridor on `ground: {source: plane}` may take `terrain:`; its plane TERRAIN element is then dropped in favour of the fetched one, since a model carries one existing ground. (The plane still measures the corridor.)

## The footprint

After the family builds (and after `spatial_parts` and the routes), the plan extent of every element's placed geometry, the model frame's x and y, in feet. Elements that are TERRAIN, or carry no geometry, are left out. Converted to CRS coordinates by `base_e + x`, `base_n + y` (`ProjectContext.local` reversed) and the CRS unit, then grown by `margin_ft` each way. The model's bounds code (`placement.local_bounds` over placed bodies, as `backfill._placed_bounds` places them) is reused, not duplicated.

## The vertical datum

One function, `terrain_vshift(ctx, cache_stem, vshift_m=None, log=print) -> (shift_m, source)`, used by `terrain:` and by the corridor's `ground: {source: 3dep}`:

| Case | Shift | Source written |
|---|---|---|
| `vshift_m` given | that value | `spec vshift_m` |
| `project.vertical_datum` NAVD88 (any case, `NAVD 88`, `NAVD-88`) | 0 | `NAVD88: none` |
| `project.vertical_datum` NGVD29 (likewise) | NOAA NCAT at the base point, cached in `<stem>-3DEP-vshift.json` (`ncat_vertshift`) | `NOAA NCAT VERTCON 3.0` |
| anything else, or none | fails: `terrain: 3DEP heights are NAVD88; project.vertical_datum <x> has no rule; give terrain.vshift_m` | |

The base point's latitude and longitude come from pyproj (`EPSG:<epsg>` to 4326). An unreachable NCAT with no cached shift fails the build, saying to give `vshift_m`; no fallback grid is supplied. The applied shift and its source are written into the provenance (`AppliedVerticalShift`, a new `VerticalShiftSource`).

The corridor's `ground: {source: 3dep}` takes its shift from the same function: `vshift_m` when given, else the datum rule. A corridor spec on NAVD88 builds as before; one on NGVD29 with no `vshift_m` now gets the NCAT shift where it got 0. No shipped spec or fixture uses `source: 3dep`.

## The element

`attach_terrain` as it is, called with the footprint, the shift, the cache stem and `lonlat` (for the 3DEP work-unit vintage), then moved into the model frame as the corridor moves its own (`corridor.ground._to_model_frame`, moved to `bimforge.terrain.attach` and shared). It is contained in the IfcSite (the facility tree's `site` kind, as the corridor's is). Nothing is carved: no structure family has a cut, and the corridor's cuts void its own ground as today. No pay code, no quantities, no classification; takeoff is unchanged.

## The command

`est-bim terrain SPEC [--refresh] [--family-path DIR]`:

1. loads the spec as `est-bim build` does and builds the model in memory (no gate, no outputs);
2. for a `terrain:` block, computes the footprint and fetches into the cache (`refresh` refetches); for a corridor on `ground: {source: 3dep}`, the corridor's build has already fetched;
3. prints one block per terrain: footprint (CRS units and the size in feet), cells, source, source project, acquisition dates, quality level, the shift and its source, and the cache files.

A spec with neither block prints `terrain: the spec asks for no terrain` and exits 0. Once it has run, `est-bim build` reads only the cache. `refresh` is a command flag only; the spec has none, so a build never refetches by itself.

## Not changed

Shipped examples (none uses `terrain:`), takeoff, GlobalIds of existing elements, the corridor's spec format.

## Testing

All offline: the fetchers (`fetch_3dep_dem`, `fetch_3dep_lpc`, `workunit_meta`, the NCAT request) are replaced with a synthetic grid and canned responses, as the corridor's tests do.

- A B3 wall spec with `terrain:` gets one TERRAIN element whose plan extent covers the wall's footprint plus the margin, placed under the wall in the model frame, with the provenance's source, spacing and shift.
- The datum rule: NAVD88 (0), NGVD29 (the stubbed NCAT value, cached; a second run makes no request), explicit `vshift_m`, a missing or unknown datum failing, NCAT unreachable failing.
- Spec errors: no epsg, no cache, an unknown key, a corridor with both 3DEP ground and `terrain:`.
- A plane-ground corridor with `terrain:` carries one TERRAIN element, the fetched one.
- The corridor's 3DEP ground on NGVD29 takes the NCAT shift.
- `est-bim terrain` fetches once and reports; run again it reports from the cache with the fetchers failing on any call; `--refresh` calls them again; a spec without terrain exits 0.
- The IFC validators and the buildingSMART rules job pass on a B3 wall with terrain.
