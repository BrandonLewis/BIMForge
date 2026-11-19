# GlobalId contract

A consumer can attach its own records (documents, RFIs, submittals,
correspondence) to the entities bimforge writes, by GlobalId, and expect them
to hold through a rebuild. This page says which ids are stable and what
changes one.

Every stable id is `uuid5(namespace, key)`, compressed to the IFC form.

## Stable ids

| Writer | Entity | Namespace | Key |
|---|---|---|---|
| `est-bim build` | IfcProject | `project.guid_ns` | `root/0/IfcProject` |
| `est-bim build` | element, opening | `project.guid_ns` | its `guid_key`, by default `element/<name>` (prefixed `<structure>/` in a combined file) |
| `est-bim build` | assembly, group | `project.guid_ns` | `assembly/<name>`, `group/<name>` |
| `est-bim build` | spatial containers, types | `project.guid_ns` | `spatial/...`, the type's class and name |
| `est-bim build` | a bar type's IfcRelDefinesByType | `project.guid_ns` | `rel/IfcRelDefinesByType/<type id>` |
| `est-bim build` | a late-typed element's (`Element.typed_late`: the B3 retaining wall) IfcRelDefinesByType, property sets and their IfcRelDefinesByProperties | `project.guid_ns` | `rel/IfcRelDefinesByType/<type id>`, `pset/<element id>/<pset name>`, `rel/IfcRelDefinesByProperties/<pset id>` |
| `est-bim build` | a family class's (M.1) IfcRelAssociatesClassification | `project.guid_ns` | `rel/IfcRelAssociatesClassification/` + the reference's `stable_ids` name (its system and class code) |
| `est-bim build` | a layered element's (`Element.layer_thickness_ft`, X.6) IfcRelAssociatesMaterial: its type's layer set, its own layer set usage | `project.guid_ns` | `rel/IfcRelAssociatesMaterial/IfcMaterialLayerSet:<type name>`, `rel/IfcRelAssociatesMaterial/IfcMaterialLayerSetUsage/<element id>` |
| `est-bim build` | an element's `BIMForge_Dimensions` (M.2) and its IfcRelDefinesByProperties | `project.guid_ns` | `pset/<element id>/BIMForge_Dimensions`, `rel/IfcRelDefinesByProperties/<pset id>` |
| `est-bim build` | the types' IfcRelDeclares | the file's IfcProject GlobalId | `rel/IfcRelDeclares/<project id>`, the key the embedders give it |
| `author.federate` | aggregates, storeys | derived from the source ids | |
| `est-bim schedule` | IfcWorkSchedule | the file's IfcProject GlobalId | `work-schedule/<name>` |
| `est-bim schedule` | IfcWorkCalendar | the file's IfcProject GlobalId | `calendar/<calendar name>` |
| `est-bim schedule` | IfcTask | the file's IfcProject GlobalId | `task/<schedule>/<task id>`, unless the task carries a `global_id` |
| `cost5d`, `estimate5d`, `estimate-model` | IfcCostSchedule | the file's IfcProject GlobalId | `cost-schedule/<name>` |
| `estimate5d`, `estimate-model` | IfcCostItem | the file's IfcProject GlobalId | `cost-item/<cost schedule>/<path>` |
| `cost5d` | IfcCostItem | the file's IfcProject GlobalId | `cost-item/<cost schedule>/<task id>/<code>` |
| `cost5d` | IfcLaborResource (crew) | the file's IfcProject GlobalId | `crew/<schedule>/<task id>` |
| `estimate-model` | IfcLaborResource (crew) | the file's IfcProject GlobalId | `crew/<schedule>/<crew id, or its name>` |
| `dxf2bim` | IfcProject, site, building, storey | `project.guid_ns` in the layer map | `project`, `site`, `building`, `storey/<name>` |
| `dxf2bim` | element | `project.guid_ns` in the layer map | `element/<layer>-<DXF handle>` |
| `add-alignments` | IfcAlignment | the file's IfcProject GlobalId | `alignment/<name>` |
| `add-alignments` | horizontal, vertical layout | the file's IfcProject GlobalId | `alignment/<name>/horizontal`, `.../vertical` |
| `add-alignments` | IfcAlignmentSegment | the file's IfcProject GlobalId | `alignment/<name>/<layout>/segment/<n>`, in layout order |
| `add-alignments` | IfcReferent | the file's IfcProject GlobalId | `referent/<alignment>/<Pset_Stationing Station, metres, 4 places>` |
| `build`, `dxf2bim`, `federate` | `BIMForge_Model` (the model's identity) and its IfcRelDefinesByProperties | the file's IfcProject GlobalId | `pset/<project id>/BIMForge_Model`, `rel/IfcRelDefinesByProperties/<its id>` |
| the embedders, `add-alignments` | property set | the file's IfcProject GlobalId | `pset/<owner ids>/<pset name>` |
| the embedders, `add-alignments` | IfcRelSequence | the file's IfcProject GlobalId | `rel/IfcRelSequence/<predecessor id>/<successor id>` |
| the embedders, `add-alignments` | other relationships | the file's IfcProject GlobalId | `rel/<type>/<relating entity's id>` |

A cost item's `<path>` is the Identification (or, without one, the Name) of
each item from the schedule down to it, joined by `/`: a pay item is
`cost-item/<schedule>/<item>`, a share under it
`cost-item/<schedule>/<item>/<share name>`. Siblings with one label are
numbered `#1`, `#2` in file order.

A relationship's key leaves its related set out, so a writer that adds a
task or a product to an existing assignment keeps the relationship's id. A
relating entity without a GlobalId (a classification reference, a system) is
named by its class and label; a reference also by its system. A repeated key
is numbered `#1`, `#2` in the order of its related entities' ids.
`stable_ids.key_relationships(model)` keys every relationship and property set
that touches a schedule, task, cost item, calendar or crew (cost5d keys its
code system's association to the project itself); the embedders run it last,
and a downstream writer that adds to an embedded file runs it before saving.
A relationship or property set stamped by another application (an OwnerHistory
whose OwningApplication is not bimforge) keeps its id: it is that tool's own.

The embedders key under the file's IfcProject, so they need no input of their
own, and one schedule embedded into two projects gets two sets of ids.

## What changes an id

- An element's id changes when the element is renamed (unless its `guid_key`
  is pinned), when its structure is renamed in a combined file, or when
  `guid_ns` changes.
- A task's id changes when its task id or its schedule's name changes.
- A cost item's id changes when its schedule's name, its Identification, or a
  parent's Identification changes, or when a sibling with the same label is
  added before it.
- A `cost5d` item's id changes when its task id or code changes; its crew's
  when the task id does. An `estimate-model` crew's changes when its crew id
  does (or its name, for a crew without one).
- A dxf2bim element's id changes when the DXF entity is redrawn (a new handle)
  or moved to another layer.
- A relationship's id changes when its relating entity's id does, a
  sequence's when either task's does, and a property set's when its owner's
  id or its name does. An alignment's parts change when it is renamed, a
  segment's when a segment is added or removed before it, a referent's when
  its station moves.
- Every id an embedder writes changes when the IfcProject's id does, so a
  file rebuilt without `guid_ns` takes new ones.

## What never changes an id

Moving an element, changing its class, geometry, quantities or properties,
reordering the spec or the schedule, editing a task's dates, re-embedding a
schedule by the same name, a dependency's type or lag, adding members to a
relationship, and upgrading bimforge.

## Returned files

A downstream tool may return a file bimforge wrote with its own work added
(#83). It never modifies an entity of ours, and stamps everything it adds,
relationships and property sets included, with an IfcOwnerHistory naming its
application:

- its own IfcWorkSchedule, a full copy of ours whose tasks are tied to ours by
  IfcRelDefinesByObject (our task the RelatingObject), carrying its replanning
  and progress;
- IfcApproval with IfcRelAssociatesApproval on our GlobalIds.

What it added itself it may replace or remove on a later write: an entity its
OwningApplication names, what hangs from one with no GlobalId of its own, and
its relationships to ours, never the entities of ours they point at. So:

- a rewrite deletes its old lines and appends new ones, or rewrites a line of
  its own where it stands (stamped MODIFIED, the first CreationDate kept; an
  addition only re-pointed onto the replacing task keeps its stamp); our lines
  stay byte for byte;
- it writes one update, replacing its last, and an update it keeps to compare
  against is retyped BASELINE (rule 2 below keeps it from taking the update's
  place);
- a changed approval keeps its IfcRelAssociatesApproval and points at a new
  IfcApproval, and a withdrawn one goes with its relationship.

Its GlobalIds are its own to key. ProjectCommand keys its update's as we key
ours, `uuid5(<IfcProject GlobalId>, key)`, every key starting
`projectcommand/` (`projectcommand/task/<our task GlobalId>`, and
`projectcommand/baseline/<time kept>/<the id it had>` for a kept update), so
one of them can never be one of ours, and a rewritten update has the ids of
the one it replaces. Its other GlobalIds (a task added in it, an approval's
relationship, a saved view) are stable from write to write but not keyed this
way: random, or seeded by its own scheme. Our `stable_ids.assign` refuses an id
another entity holds, so a collision would fail loudly, not overwrite. Its
ApplicationIdentifier does not change: it is how both sides tell its entities
from ours (`stable_ids.foreign`).

A change to bimforge's own plan comes as a BCF topic against our GlobalIds and
is made in the source.

Which schedule a reader plays:

1. Schedules whose tasks are tied by IfcRelDefinesByObject form a group.
2. A schedule supersedes the one its tasks are tied to (the superseded
   schedule's task is the RelatingObject, the copy the RelatedObjects), unless
   the copying schedule is BASELINE. That is how a baseline is tied to the live
   plan (IfcOpenShell's `create_baseline`), and it must not take its place.
3. The current schedule is a non-BASELINE one that nothing supersedes.
4. Where more than one is left (two downstream updates both tied to ours), the
   latest CreationDate wins, then the last in the file. A reader that cannot
   follow the links takes Purpose `Contractor update` as the tie-break.

So bimforge's CreationDate never decides which schedule is current. The ties
do, which is why the carry-forward reports a tie whose task of ours is gone
and keeps the rest: one surviving tie holds the group together.

`est-bim schedule --returned <file>` rebuilds the schedule from the source, then
copies every stamped addition onto the rebuilt file (`carry_forward`):

- its GlobalIds are kept exactly;
- what it points at of ours is re-pointed by GlobalId;
- what it holds that has no GlobalId (an IfcApproval and its organizations, a
  task's IfcTaskTime) comes with it.

It works from the returned file alone. `<out>.carry.json` is written, never
read, so a file holding fewer additions than the last one reads as it is. An
addition's ChangeAction (ADDED or MODIFIED) does not matter; only our own
entities are checked for change.

The report (`<out>.carry.json`) lists what no longer lines up:

- an addition dropped because nothing is left to relate;
- one that lost some of its targets;
- our tasks no downstream task is tied to, and elements our tasks build that
  no downstream task does (only when the returned file has a schedule of its
  own);
- our entities the returned file changed. They are rebuilt from the source,
  so that change is lost, but named.

A returned file from another project is refused. bimforge writes its schedule
as PLANNED (or the source's `schedule_type`), with CreationDate taken from the
schedule's start, not the clock, so a rebuild does not move it.

## Not stable

Roots nobody keys are numbered by file order (`est-bim build`) or random
(dxf2bim's relationships and property sets, and a relationship whose relating
entity has neither an id nor a label). Attach nothing to relationships or
property sets: they are stable so a file diffs cleanly run to run, not to
carry records.

`dxf2bim` without `project.guid_ns` writes random ids and warns.
