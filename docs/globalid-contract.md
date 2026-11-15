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
(#83). It adds and never modifies, and stamps everything it adds, relationships
and property sets included, with an IfcOwnerHistory naming its application:

- its own IfcWorkSchedule, a full copy of ours whose tasks are tied to ours by
  IfcRelDefinesByObject (our task the RelatingObject), carrying its replanning
  and progress;
- IfcApproval with IfcRelAssociatesApproval on our GlobalIds.

A change to bimforge's own plan comes as a BCF topic against our GlobalIds and
is made in the source.

`est-bim schedule --returned <file>` rebuilds the schedule from the source, then
copies every stamped addition onto the rebuilt file (`carry_forward`):

- its GlobalIds are kept exactly;
- what it points at of ours is re-pointed by GlobalId;
- what it holds that has no GlobalId (an IfcApproval and its organizations, a
  task's IfcTaskTime) comes with it.

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
