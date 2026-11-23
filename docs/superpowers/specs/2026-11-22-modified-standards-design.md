# Modified standards (M.8, M.9): design

Date: 2026-11-22. Roadmap rows M.8 and M.9. Builds on M.1 (the family class reference) and M.2 (`BIMForge_Dimensions`).

## Goal

A modified standard, the plans' "(MOD)", is its standard class plus recorded differences: never a new class and never an unlabelled bespoke shape. Every element says the route it was built by and, when it differs from the standard, each changed value with its standard and its actual value. The differences come from what a spec already says (a project's tables over the packaged ones, a barrier run's "Mod" dimensions), with no extra authoring.

## What the code does today (and the roadmap row gets wrong)

- `load_spec` (`bimforge/author/families/registry.py`) merges `tables_pack` refs and then the project's `tables_file` into `params["tables"]`, field by field (`_merge_tables`). Nothing reports the merge and the packaged values are not kept.
- No build-time check holds an element to its packaged table. `gate: {ignore: [...]}` only silences the unread-params check for catalog rows a table-driven family never reads; it switches no table check off. M.9's last sentence and the README line that pairs `ignore: [tables]` with modified elements are corrected to say this.
- The shipped examples use a full copy of the packaged tables as their `tables_file`; `bimforge/caltrans/tests/test_pack.py` proves pack and example build byte-identical IFC.
- The barrier families (842, 732SW) take per-run "Mod" dimensions (`_MOD_KEYS`, `_row_732` over `SECTION_DEFAULTS`) or an explicit `profile` ring.

## Routes

| Route | Meaning | Produced by |
|---|---|---|
| `standard` | built from the standard's values | every typed element that read no changed value |
| `modified-by-value` | the standard's shape, some values changed | a project table value over the packaged one; a barrier run's Mod dimension |
| `modified-by-part` | the standard with a part added, removed or replaced | defined; nothing produces it yet |
| `modified-by-section` | the standard's class, its own section | a barrier run with an explicit `profile` ring |
| `bespoke` | authored outright | a `bimforge.author` script's elements |

## The baseline (M.9)

`load_spec` keeps the packaged tables as they stood before the project's file is merged:

- the `tables_pack` refs the spec names, merged in order; or, when it names none, the family's own default pack (`standard-plan`: `caltrans:b3-retaining-wall` in the current edition). A family declares its default as `DEFAULT_TABLES_PACK`; a family without one has no baseline and reports nothing.
- `table_differences(baseline, merged) -> list[Difference]`: every leaf path where the merged value differs from the baseline's (numbers compared within 1e-9; text exactly), and every row the project added (`standard: None`). `Difference = (path: tuple, standard, actual)`.
- The build log lists every difference: `tables: 3 values differ from caltrans:b3-retaining-wall (2025): type_1_case_1.table.8.W_ft 6.5 -> 7.0, ...`.
- A project file equal to the pack reports none, so every shipped example's IFC is unchanged.

The baseline and the differences ride on the params as `params["tables_standard"]` (the pack's name and edition) and `params["tables_differences"]`, so a family reads them as it reads `tables`.

## Per element (M.8)

An element records only the differences it read. `WallSection` notes the table paths it read (the type's constants and the selected row); the B3 family gives the stem the stem's (T, batter, stem thickness constants) and the footing the footing's (W, C, B, F, toe). A barrier element's differences are its run's Mod keys that differ from the section defaults.

On the `Element` (`bimforge/author/model.py`):

- `route: str | None` (`None` on untyped elements, which get nothing written)
- `based_on: str | None` (the class code; defaults to `family_class`)
- `differences: list[Difference]`, each named by the class's dimension code when the field maps to one (`ToeWidth`, `HeelWidth`, `StemThickness`, `Batter`), otherwise by its table field (`W_ft`, `F_ft`)

The classification reference stays the standard class, so a Type 842 (MOD) is found as a Type 842 by `family_class_of` and every class reader.

In the IFC, beside `BIMForge_Dimensions`, keyed `pset/<GlobalId>/BIMForge_Route`:

- `BIMForge_Route.Route` (IfcLabel) and `BIMForge_Route.BasedOn` (IfcLabel), on every typed element;
- for each difference, an `IfcComplexProperty` named by the dimension code or field, `UsageName` `Difference`, holding `Standard` and `Actual` (the dimension's measure, as `fd.measure` writes it; IfcLabel for text; `Standard` omitted for an added row) and `Source` (IfcLabel: the pack and path, `caltrans:b3-retaining-wall/2025 type_1_case_1.table.8.W_ft`).

A bespoke `bimforge.author` script may set `based_on` on an element (a dictionary code) or leave it out; either way its route is `bespoke`, and with `based_on` its classification reference points at that class.

## The gate

A new gate key `modified: warn | error | off` (default `warn`): `warn` prints each modified element's differences after the gate, `error` fails the build listing them, `off` is quiet. The unchanged values need no check: a family reads them from the table.

## Sent on

`model-elements` sends `route`, `based_on` and `differences` (`[{name, standard, actual, unit, source}]`, in the same units as `parameters`) on each typed element. BidSheet.ai and ProjectCommand ignore unknown keys. Takeoff is unchanged.

## Scope

- This spec: the general machinery, the B3 wall (stem and footing), the 842 and 732SW barriers, bespoke `based_on`, `model-elements`.
- Next, each needing only its read paths: D80, D84, D89, the D90 headwall, B9.

## Testing

- `table_differences`: equal tables, a changed field, an added row, int vs float keys, text values.
- B3 from the pack plus a project file changing row 8's W_ft: the 8 ft footing slices are `modified-by-value` with `W_ft 6.5 -> 7.0`, the stems and other heights `standard`; the build log lists the difference.
- Every shipped example's IFC is byte-identical apart from the new `BIMForge_Route` sets on typed elements (route `standard`), and `test_pack`'s pack-vs-example identity holds.
- An 842 run with `stem_h_ft` changed is `modified-by-value`; with a `profile` ring, `modified-by-section`; both still classified as the 842 class.
- `gate: {modified: error}` fails a modified build and passes a standard one.
- `model-elements` sends the route and differences.
- The buildingSMART rules job and the IFC validators pass on a modified B3 model.
