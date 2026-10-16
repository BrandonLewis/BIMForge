"""Registered construct families: `build(params, ctx) -> StructureModel`.

Shipped families register by import in `registry._shipped()`; external packages
register via the `bimforge.families` entry-point group. Bespoke structures
skip the dispatcher entirely and script directly against the kernel — both
consumption modes are first-class (spec §4)."""
