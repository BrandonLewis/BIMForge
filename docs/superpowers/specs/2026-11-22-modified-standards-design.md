# Modified standards (M.8, M.9): design

Date: 2026-11-22. Roadmap rows M.8 and M.9. Builds on M.1 (the family class reference) and M.2 (`BIMForge_Dimensions`).

## Goal

A modified standard, the plans' "(MOD)", is its standard class plus recorded differences: never a new class and never an unlabelled bespoke shape. Every element whose family checks it says the route it was built by and, when it differs from the standard, each changed value with its standard and its actual value. The differences come from what a spec already says (a project's tables over the packaged ones, a barrier run's "Mod" dimensions), with no extra authoring.

## What the code does today (and the roadmap row gets wrong)

- `load_spec` (`bimforge/author/families/registry.py`) merges `tables_pack` refs and then the project's `tables_file` into `params["tables"]`, field by field (`_merge_tables`). Nothing reports the merge and the packaged values are not kept.
- No build-time check holds an element to its packaged table. `gate: {ignore: [...]}` only silences the unread-params check for catalog rows a table-driven family never reads; it switches no table check off. M.9's last sentence and the README line that pairs `ignore: [tables]` with modified elements are corrected to say this.
- The shipped examples use a full copy of the packaged tables as their `tables_file`; `bimforge/caltrans/tests/test_pack.py` proves pack and example build byte-identical IFC.
- The barrier families (842, 732SW) take per-run "Mod" dimensions (`_MOD_KEYS`, `_row_732` over `SECTION_DEFAULTS`) or an explicit `profile` ring.

## Routes

| Route | Meaning | Produced by |
|---|---|---|
| `standard` | built from the standard's values | an element whose family says what it read (B3) that read no changed value and chose the standard's row; a barrier run with no Mod dimension |
| `modified-by-value` | the standard's shape, some values changed | a project table value over the packaged one; a row the packaged tables would not choose (a `Row` difference); a barrier run's Mod dimension |
| `modified-by-part` | the standard with a part added, removed or replaced | defined; nothing produces it yet |
| `modified-by-section` | the standard's class, its own section | a barrier run with an explicit `profile` ring |
| `bespoke` | authored outright | a `bimforge.author` script's element with `based_on` (or one that sets `route="bespoke"` itself) |

A route is recorded only on an element whose family says what it read (`Element.table_reads` or `table_rows`: the B3 wall) or sets the route itself (the barriers), and `bespoke` on an element with `based_on`. A typed element with nothing to check against (the road corridor, the D-series, B11-51 today) keeps `route = None` and gets no `BIMForge_Route` set: saying `standard` there would claim a check that was not made.

## The baseline (M.9)

`load_spec` keeps the packaged tables as they stood before the project's file is merged:

- the `tables_pack` refs the spec names, merged in order; or, when it names none, the family's own default pack, from `registry.DEFAULT_TABLES_PACKS` (family -> ref: `standard-plan` -> `caltrans/b3-retaining-wall`, in the current edition). A family without an entry, naming no `tables_pack`, has no baseline and reports nothing.
- `table_differences(baseline, merged) -> list[Difference]`: every leaf path where the merged value differs from the baseline's (numbers compared within 1e-9; text exactly), and every row the project added (`standard: None`). `Difference = (path: tuple, standard, actual)`.
- The build log prints one line per changed value, `tables: type_1_case_1.table.8.W_ft 6.5833 -> 7 (standard: caltrans/2025/b3-retaining-wall)`, and one line counting the values the project added: `tables: N values added that the standard does not have (caltrans/2025/b3-retaining-wall)`.
- When the tables differ but no element of the family says what it read, the build warns once: `warning: tables differ from <standard> but family <name> does not say which values its elements read; their routes are not recorded`.
- A project file equal to the pack reports none, so every shipped example's IFC is unchanged.

The baseline's label (pack, edition, table), the differences and the baseline tables themselves ride on the spec as `spec["_tables_standard"]`, `spec["_tables_differences"]` and `spec["_tables_baseline"]`, not on the params, so the unread-params check never sees them. A family only says which table paths each element read (`Element.table_reads`) and which row it chose for which design H (`Element.table_rows`, with the model's `row_lookup`); `build_from_spec` then gives each element that says so its route and the differences it read (`modified.assign_routes`), keeping a route the family set itself (the barriers).

### The row (M.9)

A value diff alone misses a project table that omits packaged rows: the shipped `caltrans-b3-tables.example.yaml` has only rows 8 and 12 of `type_1a_case_1`, so a Type 1a wall at design H 10 takes row 12 where the pack takes row 10, and no value differs. `WallSection` records the row it chose and for which H (`rows = {(table, "table"): (H, key)}`), the B3 elements carry it as `table_rows`, and `standard_plan` sets `StructureModel.row_lookup = WallSection._lookup_key`. `assign_routes` looks each H up in the baseline's table at the same path with that lookup; when the baseline chooses another key, or has no such table or no row for that H, the element gets a difference `{"name": "Row", "standard": <the baseline's key or None>, "actual": <the chosen key>, "source": "<standard> <table path>"}` and is `modified-by-value`. In the IFC a numeric key is an `IfcReal` (`difference_measure`'s fallback), a text key an `IfcLabel`.

## Per element (M.8)

An element records only the differences it read. `WallSection` notes the table paths it read (the type's constants and the selected row); the B3 family gives the stem the stem's (T, batter, stem thickness constants) and the footing the footing's (W, C, B, F, toe). A barrier element's differences are its run's Mod keys that differ from the section defaults.

On the `Element` (`bimforge/author/model.py`):

- `route: str | None` (`None` on untyped elements, which get nothing written)
- `based_on: str | None` (the class code; defaults to `family_class`)
- `differences: list[Difference]`, each named by the class's dimension code when the field maps to one (`ToeWidth`, `HeelWidth`, `StemThickness`, `Batter`), otherwise by its table field (`W_ft`, `F_ft`)

The classification reference stays the standard class, so a Type 842 (MOD) is found as a Type 842 by `family_class_of` and every class reader.

In the IFC, beside `BIMForge_Dimensions`, keyed `pset/<GlobalId>/BIMForge_Route`:

- `BIMForge_Route.Route` (IfcLabel) and `BIMForge_Route.BasedOn` (IfcLabel), on every element with a route or `based_on`;
- for each difference, an `IfcComplexProperty` named by the dimension code or field, `UsageName` `Difference`, holding `Standard` and `Actual` (the dimension's measure, as `fd.measure` writes it; else by the field: `_ft` or `_in` a length, a raw `batter` a ratio, anything else an IfcReal; IfcLabel for text; `Standard` omitted for an added row) and `Source` (IfcLabel: the pack and path, `caltrans/2025/b3-retaining-wall type_1_case_1.table.8.W_ft`).

A bespoke `bimforge.author` script may set `based_on` on an element (a dictionary code): its route is then `bespoke` and its classification reference points at that class. Without `based_on` nothing is written unless the script sets `route="bespoke"` itself.

## The gate

A new gate key `modified: warn | error | off` (default `warn`; an empty `modified:` is `warn`): `warn` prints each modified element's differences after the gate, `error` fails the build listing them, `off` is quiet. The unchanged values need no check: a family reads them from the table.

## Sent on

`model-elements` sends `route`, `based_on` and `differences` (`[{name, standard, actual, unit, source}]`, in the same units as `parameters`: FT for any length, so a `chamfer_in` difference is in feet) on each element with a `BIMForge_Route` set. BidSheet.ai and ProjectCommand ignore unknown keys. Takeoff is unchanged.

## Scope

- This spec: the general machinery, the B3 wall (stem and footing), the 842 and 732SW barriers, bespoke `based_on`, `model-elements`.
- Next, each needing only its read paths: D80, D84, D89, the D90 headwall, B9.

## Testing

- `table_differences`: equal tables, a changed field, an added row, int vs float keys, text values.
- B3 from the pack plus a project file changing row 8's W_ft: the 8 ft footing slices are `modified-by-value` with `W_ft 6.5833 -> 7.0`, the stems and other heights `standard`; the build log lists the difference.
- The shipped B3 examples' `caltrans-b3-tables.example.yaml` differs from the 2025 pack in 13 values (row 8 of Type 1, among them a vertical stem where the pack batters it): those examples' elements become `modified-by-value`, which is what they are.
- Every shipped example's IFC is byte-identical apart from the new `BIMForge_Route` sets on the B3 and barrier elements, and `test_pack`'s pack-vs-example identity holds; a road corridor, D-series or B11-51 element gets no route.
- A Type 1a wall over tables lacking the row the pack would choose gets a `Row` difference and is `modified-by-value`.
- An 842 run with `stem_h_ft` changed is `modified-by-value`; with a `profile` ring, `modified-by-section`; both still classified as the 842 class.
- `gate: {modified: error}` fails a modified build and passes a standard one.
- `model-elements` sends the route and differences.
- The buildingSMART rules job and the IFC validators pass on a modified B3 model.
