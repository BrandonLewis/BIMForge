# Internal ESTIMATE schedule keyed by bid item

Status: approved design, 2026-11-09. Follows #39 (0.1.111, the TENDER schedule).

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
AppliedValue of its own. cost5d keeps its current sibling values.

Readers must evaluate a composite:

- `cost_categories.categories_of` reads components' Categories;
- `schedule_read.read_costs` sums a value's components when it has them.

## read_costs keys

`read_costs` keys each leaf by its Identification, which leaves no longer
have. It will use the nearest ancestor with an Identification (`"10.PS-FTG"`).
For estimate-model files this changes the `costs` keys from the item code to
`"<item>.<code>"`. The consumers are `est-bim cost5d --costs` (`cli.py`),
`cost5d.load_schedule_costs` and `bimforge/web/contract.py`. Each will be
checked and its tests updated; totals per task must not change.

## Out of scope

- The TENDER writer's output (unchanged apart from calling `pay_item_id`).
- Labour hours on IfcResourceTime (ProjectCommand doesn't read them).
- BUDGET / approval stage for the ESTIMATE schedule.

## Tests

- Same bid through estimate5d and estimate-model: the ESTIMATE top-level
  Identifications equal the TENDER parents' Identifications.
- Every Identification in the ESTIMATE schedule is unique; parents and code
  nodes are valueless; each leaf has exactly one ADD value whose components
  sum to its share (cents).
- A spread activity lands as `"<item>.<code>"` under each item it pays; a
  share with no item becomes a top-level `"<code>"` item.
- `read_costs` per-task totals and categories match the pre-change values for
  the existing fixtures.
- A re-run leaves exactly one ESTIMATE schedule and one IfcRelDeclares.

## Release

0.1.112, with CHANGELOG **Changed** (schedule shape, read_costs keys) and
**Added** (composed cost values, top-level indirects).
