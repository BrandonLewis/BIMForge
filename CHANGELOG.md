# Changelog

Newest first. Versions follow `pyproject.toml`; a tag `vX.Y.Z` releases to PyPI.

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
