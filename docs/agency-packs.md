# Agency packs

A pack holds what one agency's standards say: Caltrans, a city, a county, a
district. `bimforge.caltrans` is the first. This is the brief for whoever
goes through an agency's standard drawings and specifications to build one.

## What a pack is

| Part | Where | What it holds |
|---|---|---|
| Sheet manifest | `data/<agency>-<edition>/manifest.json` | Every source document read: title, URL, sha256, date fetched. The documents themselves are not committed. |
| Dictionary | `bimforge/<agency>/dictionary/<agency>-<edition>.bsdd.json` | The vocabulary, in bSDD's import format: one class per standard type, its parts, its properties and their allowed values. |
| Tables | `bimforge/<agency>/tables/<edition>/*.yaml` | The numbers: one table per standard drawing, rows keyed the way the sheet keys them, each table named for the class it sizes. |
| Families | `bimforge/<agency>/families/` | The python that builds a type from a table row. Written last, and only for types someone will model. |

The dictionary and the tables are the survey. They are worth having before
any family exists: they are what a Revit or Tekla template, a checker and a
family all agree on.

An edition is the agency's own (Caltrans 2025 Standard Plans; a city's
drawings by their adoption or revision date). A new edition is a new
directory, never an edit to an old one.

## What goes in the dictionary

One class for each thing a standard drawing defines that a model would
contain as an element or a type.

- **Code**: the drawing number and the type, lower case, hyphenated
  (`b11-58-type-732sw`, `d89-pipe-headwall`). Stable across editions when the
  agency keeps the number.
- **Name** and **Definition**: the sheet's title and what the thing is, in
  the sheet's words where they are clear.
- **RelatedIfcEntityNamesList**: the IFC class and predefined type it is
  modelled as. Check the IFC4X3 definition; do not pick a class by its name.
- **Reference** property: the drawing number, as its predefined value.
- **Parts**: a class per part that is paid, scheduled or counted on its own
  (post, rail, footing), related to the whole with a part-of relation.
- **Properties**: the parameters the sheet tabulates against (design height,
  pipe diameter, cover, skew) with unit and allowed values, and the outputs
  it tabulates (concrete per foot, reinforcing per foot) named as the
  takeoff's quantities are named.
- **Specification**: the standard specification section that governs the
  type, and the agency's standard pay item codes that pay for it. Pay items
  are a second dictionary of the same pack (`<agency>-items-<edition>`), one
  class per item code with its unit and measurement rule, related to the
  types it pays for.

A type the sheets leave to the Engineer (D90 wingwall length and flare) gets
its class and its fixed rules, and the dictionary says which properties the
project supplies.

## What goes in a table

The table a sheet prints, transcribed. Keys as printed (a design height of
3'-11" is `3-11`), lengths in decimal feet with the `_ft` suffix, bars as
printed (`#5@12`). Nothing derived, nothing rounded further than the sheet.
Head each file with the drawing number, the edition and the sheet's file name
in the manifest.

## Order of work

1. **Inventory.** List every standard drawing and specification section in
   the edition: number, title, and one of *type* (defines something to
   model), *detail* (a note or a detail of another type), *not modelled*.
   Commit the inventory and the manifest. This is the first PR and decides
   the rest.
2. **Dictionary, by series.** One PR per series of drawings. Classes, parts
   and properties for every *type* in the inventory, tables or not.
3. **Tables**, for the types that tabulate dimensions or quantities, each
   with the checks below.
4. **Families**, when a project needs one.

## Rules

- **Public sources only**: the agency's published standard drawings,
  standard specifications and item code lists. Nothing from a project's
  plans, nothing from a bid, no prices, no job or bid identifiers. Manufacturer
  drawings are not agency standards and stay out.
- **Cite everything.** A class or a row with no sheet in the manifest does
  not merge.
- **Transcribe, then check.** Every table has a test that holds the
  transcription to something the sheet itself states: a sum of dimensions
  (`W == C + B`), a modelled section area against the tabulated concrete, a
  bar schedule against the tabulated weight. A table with nothing to check
  against gets a second, independent reading.
- **Mark what you could not read.** A cell that is illegible or ambiguous is
  left out and listed in the table's header, not guessed.
- `scripts/deorg_scan.py` runs in CI and refuses bid numbers, machine paths
  and credentials.

## Done, for one pack

- The inventory covers the edition, and every *type* in it is a class.
- The dictionary passes `bimforge/author/tests/test_dictionary.py`'s
  well-formedness checks, and every table name is a class code.
- Every table loads through the pack (`tables_pack: <agency>/<edition>/<table>`)
  and has its transcription test.
- A family in the pack emits its type names and references from the
  dictionary, never from a string in the module.
