# Internal ESTIMATE schedule keyed by bid item

Status: approved design, 2026-11-09; revised 2026-11-10 (readers, audit overlaps). Follows #39 (0.1.111, the TENDER schedule).

## Goal

`est-bim estimate-model` (`bimforge/bim/estimate_model5d.py`) writes the
internal cost schedule in the shape ProjectCommand reads, so that it pairs with
the TENDER schedule `est-bim estimate5d` writes **by Identification alone**:

- one ESTIMATE schedule per file, declared to the IfcProject (already true);
- its top-level items are the bid items, with Identification exactly equal to
  the TENDER pay item's;
- the internal cost codes are nested beneath, `"<item>.<code>"`;
- only leaves carry money, one ADD-composed IfcCostValue whose components are
  categorised LABOR / MATERIAL / EQUIPMENT / SUBCONTRACT / OTHER;
- no relationship between the two schedules, and the same currency as the
  TENDER (no conversion).

This re-keys the existing schedule. It does not add a second ESTIMATE
schedule: ProjectCommand compares against the first and ignores any other.

## Structure

```
IfcCostSchedule "<schedule> cost"  ESTIMATE, declared, BidSheet_EstimateModel marker
├─ "10"             bid item        valueless; Identification = pay_item_id(item)
│  └─ "10.PS-FTG"   cost code       valueless; nested (IfcRelNests)
│     └─ leaf       one per share   no Identification; one ADD IfcCostValue;
│                                   control-linked to its IfcTask and element
└─ "MOB"            indirect        top level; only for shares with no bid item
   └─ leaf ...                      (ProjectCommand: "not in bid")
```

- **Top-level items** are assigned to the schedule (IfcRelAssignsToControl, as
  `cost.add_cost_item(cost_schedule=...)` does); nested items inherit it.
- **Bid item key.** `pay_item_id(item_number, code)` is the item number, else
  the code: the rule estimate5d's `_item_key` applies today, moved to one
  shared helper both writers call, so the two cannot drift. The current
  uniqueness suffixes (`"<code> [<schedule>]"`, `"<code> [item <id>]"`) apply
  only when two bid items in the model resolve to the same key. They are a
  data error ProjectCommand reports as a duplicate, and the embed also warns.
- **Cost code key.** The activity's `cost_code`, else its activity key (`a<id>`),
  giving `"<item>.<code>"`. All of an item's shares with the same code sit
  under one code node.
- **Leaves** stay one per BidSheet share (activity × element), with the same
  exact-cent apportioning (`apportion_cents`) and the same
  `Bimforge_CostItem` pset (TaskId, LaborHours, ...). Labour hours are never a
  cost value. Crews stay IfcLaborResource, as today.

## Indirects follow BidSheet

Whether mobilization is its own pay item or is spread across items depends on
the contract, so the writer does not decide; it files each share under the bid
item the share names:

- mob as a pay item: its shares name that item, giving `"1.MOB"` under `"1"`;
- mob spread: its shares name each item paid for, giving `"<item>.MOB"` under each;
- a share that names **no** bid item (`item_id` null): a top-level item
  keyed by the code alone (`"MOB"`). Today such shares are dropped with a
  warning. A share naming an item id the model does not list is still dropped
  with that warning (bad data, not an indirect).

## Cost values

`cost_categories.write_cost_values` gains a composed form, used by
estimate_model5d's leaves: one IfcCostValue with `ArithmeticOperator=ADD` and
its Components the per-category values (an uncategorised balance becomes an
`Unallocated` component with no Category, as now). The composite carries no
AppliedValue of its own (agreed with ProjectCommand: it sums the components,
and a written total would be one more thing to mismatch). cost5d keeps its
current sibling values.

**No CostQuantities on leaves.** IFC 4.3 reads a cost item's values as unit
rates when it carries CostQuantities (amount × summed quantity / UnitBasis),
and ProjectCommand follows that rule. Leaves carry extended totals, so they
carry no CostQuantities; the element is linked by IfcRelAssignsToControl
only, as today. A test asserts that no leaf has CostQuantities.

**One evaluator.** `cost_categories` gets `value_of(cv)`: a value's
AppliedValue, else the ADD sum of its Components (recursively). Every reader
uses it, so a composite is never read as $0:

- `cost_categories.total_of` / `categories_of` (categories come from the
  components' Category; a value with no components is read as today);
- `schedule_read.read_costs` (today sums `cv.AppliedValue` inline);
- `web/contract._shares` (the same inline sum).

**Category vocabulary.** BIMForge keeps `CATEGORIES` ("Labor", "Material",
"Equipment", "Subcontract", "Other"), spelled one way across the file.
ProjectCommand reads Category verbatim and groups by exact string (confirmed);
an `Unallocated` component with no Category shows as uncategorised.

**Currency.** The file declares an IfcMonetaryUnit (USD) in its
IfcUnitAssignment when it has none, so cost values have a currency (audit
Phase 1). The TENDER and ESTIMATE schedules share it.

## Locating the schedule

Today the readers find the schedule by the exact name `"<ws> cost"`. They will
find it by type instead: the IfcCostSchedule with PredefinedType ESTIMATE that
carries the `BidSheet_EstimateModel` marker (estimate-model), else the one
named `"<ws> cost"` (cost5d, unchanged). The writer refuses to leave two
ESTIMATE schedules in a file: a re-run replaces its own, and an ESTIMATE
schedule it did not write is a warning, not a second one.

## read_costs keys

`read_costs` keys each leaf by its Identification, which leaves no longer
have. For an estimate-model file it keys each leaf by its **top-level** item's
Identification, the bid item (`"10"`), so the `costs` keys stay a bid item
number, as `costload.distribute_to_tasks` matches against
`t.bid_item_codes` (`bid_items=[item_number]` on the tasks). A top-level
indirect (`"MOB"`) keys as itself. Each record also gains `"cost_code"`: the
code node's Identification (`"10.PS-FTG"`), which gives the finer split
without changing the key.

cost5d files are flat and keep their keys.

The consumers are `est-bim cost5d --costs` (`cli.py`),
`cost5d.load_schedule_costs`, `costload.distribute_to_tasks` and
`bimforge/web/contract.py`. Each is checked and its tests are kept; totals per
task must not change.

## Contract view

`web/contract._shares` reads the bid item from the leaf's immediate parent's
`BidSheet_EstimateItem`. With the code node in between, it walks up to the
**top-level** item for `item_number` (the pset stays on the bid item), and takes
`code` from the code node, as the classification or the part after `"<item>."`.
`_bid_items` keeps scanning for `BidSheet_EstimateItem`; it is written only on
top-level items.

## Out of scope

- The TENDER writer's output (unchanged apart from calling `pay_item_id`).
- Other audit Phase 1 units (MASS, PLANEANGLE, TIME) and the 4D items
  (#37, negative lag, IfcRelAssignsToProduct): separate work.
- Labour hours on IfcResourceTime (ProjectCommand doesn't read them).
- BUDGET / approval stage for the ESTIMATE schedule.

## Tests

- Same bid through estimate5d and estimate-model: the ESTIMATE top-level
  Identifications equal the TENDER parents' Identifications.
- Every Identification in the ESTIMATE schedule is unique; parents and code
  nodes are valueless; each leaf has exactly one ADD value whose components
  sum to its share (cents), with no AppliedValue on the composite and no
  CostQuantities on the leaf.
- A spread activity lands as `"<item>.<code>"` under each item it pays; a
  share with no item becomes a top-level `"<code>"` item.
- `read_costs` per-task totals and categories match the pre-change values for
  the existing fixtures, and its `costs` keys are still bid item numbers.
- A composite value reads at its components' sum in `total_of`,
  `categories_of`, `read_costs` and `_shares` (none reads $0).
- `_shares` gives the top-level item's `item_number` and the code node's code.
- The file has one IfcMonetaryUnit; the schedule is found by type when it is
  renamed.
- A re-run leaves exactly one ESTIMATE schedule and one IfcRelDeclares.

## Release

0.1.112, with CHANGELOG **Changed** (schedule shape, read_costs keys) and
**Added** (composed cost values, top-level indirects, the monetary
unit, `cost_code` in read_costs records).
