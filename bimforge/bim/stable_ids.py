"""Stable GlobalIds for what the embedders write (#74).

A downstream viewer attaches records (submittals, RFIs, correspondence)
to tasks, cost items and schedules by GlobalId, so a re-embed must write
the same ids again. Each id is `uuid5(namespace, key)`, the rule
`ProjectContext.guid` already applies to authored elements:

- the namespace is the file's IfcProject GlobalId, expanded to a UUID, so
  the embedders need no new input and two projects never collide;
- the key names the entity by what the source calls it:
  `work-schedule/<name>`, `calendar/<name>`, `task/<schedule>/<task id>`,
  `cost-schedule/<name>`, `cost-item/<cost schedule>/<path>` (cost5d:
  `.../<task id>/<code>`) and `crew/<schedule>/<task or crew id>`.

Renaming what a key names changes the id, by design. Relationships and
property sets stay random: records never attach to them. The contract is
docs/globalid-contract.md.
"""
from __future__ import annotations

import uuid
from collections import Counter

import ifcopenshell.guid


def namespace(model) -> uuid.UUID:
    """The uuid5 namespace for `model`: its IfcProject's GlobalId."""
    projects = model.by_type("IfcProject")
    if not projects:
        raise ValueError("stable ids need an IfcProject to key from")
    return uuid.UUID(ifcopenshell.guid.expand(projects[0].GlobalId))


def stable_id(model, key: str) -> str:
    """The GlobalId `key` gets in `model`."""
    return ifcopenshell.guid.compress(uuid.uuid5(namespace(model), key).hex)


def assign(model, ent, key: str) -> str:
    """Give `ent` the stable id for `key`, refusing one another entity holds.

    A clash means two entities share a key (two tasks with one id, say), or
    an earlier embed left one behind: either way the ids would not be
    stable, so it fails loud."""
    gid = stable_id(model, key)
    try:
        clash = model.by_guid(gid)
    except RuntimeError:
        clash = None
    if clash is not None and clash != ent:
        raise ValueError(f"stable id for {key!r} is already used by "
                         f"{clash.is_a()} '{getattr(clash, 'Name', '') or ''}'")
    ent.GlobalId = gid
    return gid


def _children(ci) -> list:
    return [o for rel in (getattr(ci, "IsNestedBy", None) or ())
            for o in rel.RelatedObjects if o.is_a("IfcCostItem")]


def _label(ci) -> str:
    return ci.Identification or ci.Name or ""


def _keyed(items: list, prefix: str):
    """(item, key) for each sibling: its label, with `#n` on a repeat."""
    counts = Counter(_label(ci) for ci in items)
    seen: Counter = Counter()
    for ci in items:
        label = _label(ci)
        seen[label] += 1
        n = f"#{seen[label]}" if counts[label] > 1 else ""
        yield ci, f"{prefix}/{label}{n}"


def key_cost_items(model, cs) -> int:
    """Key every IfcCostItem under `cs` by its path of Identification (or
    Name) from the schedule; return how many were keyed.

    A pay item keys on its Identification, a leaf under it on its own
    label: the same names `read_costs` reports. Siblings that share a label
    are numbered in file order."""
    roots = [o for rel in (cs.Controls or ()) for o in rel.RelatedObjects
             if o.is_a("IfcCostItem")
             and not (getattr(o, "Nests", None) or ())]
    n = 0
    stack = list(_keyed(roots, f"cost-item/{cs.Name}"))
    while stack:
        ci, key = stack.pop(0)
        assign(model, ci, key)
        n += 1
        stack.extend(_keyed(_children(ci), key))
    return n
