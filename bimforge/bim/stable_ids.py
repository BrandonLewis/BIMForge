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
  `.../<task id>/<code>`), `crew/<schedule>/<task or crew id>` and
  `alignment/<name>[/horizontal|/vertical[/segment/<n>]]`,
  `referent/<alignment>/<station m>` (add_alignment).

Renaming what a key names changes the id, by design. Relationships and
property sets are keyed from what they join (`key_relationships`, #80), so
a re-embed writes the same file. The contract is docs/globalid-contract.md.
"""
from __future__ import annotations

import uuid
from collections import Counter

import ifcopenshell
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


# what the embedders write: schedules, tasks, cost items, calendars, crews
_SCOPE = ("IfcProcess", "IfcControl", "IfcResource")


def _names(ent) -> list[str]:
    return [ent.attribute_name(i) for i in range(len(ent))]


def _ref(ent) -> str | None:
    """What a key calls `ent`: its GlobalId, or for a resource entity with
    none (a classification reference, a material) its class and label."""
    if ent is None:
        return None
    gid = getattr(ent, "GlobalId", None)
    if gid:
        return gid
    if ent.is_a("IfcClassificationReference") and ent.ReferencedSource:
        # one code can sit in two systems (an element's pay code, a cost
        # item's): the system keeps them apart
        return f"{_ref(ent.ReferencedSource)}/{ent.Identification or ent.Name}"
    names = _names(ent)
    for attr in ("Identification", "Location", "Name"):
        label = getattr(ent, attr) if attr in names else None
        if label:
            return f"{ent.is_a()}:{label}"
    return None


def _ends(rel) -> tuple[list, list]:
    """A relationship's Relating* and Related* entities."""
    relating, related = [], []
    for i, attr in enumerate(_names(rel)):
        value = rel[i]
        if value is None:
            continue
        values = list(value) if isinstance(value, tuple) else [value]
        values = [v for v in values if isinstance(v, ifcopenshell.entity_instance)]
        if attr.startswith("Relating"):
            relating += values
        elif attr.startswith("Related"):
            related += values
    return relating, related


def _rel_key(rel) -> str | None:
    """`rel/<type>/<relating>`, plus a single related entity (a sequence's
    successor) when the related side is one entity, not a set. The related
    set stays out, so adding a member keeps the id."""
    relating, related = _ends(rel)
    parts = [_ref(e) for e in relating]
    single = [a for a in _names(rel)
              if a.startswith("Related") and isinstance(
                  getattr(rel, a), ifcopenshell.entity_instance)]
    if single:
        parts += [_ref(e) for e in related]
    if not parts or None in parts:
        return None
    return "/".join(["rel", rel.is_a(), *parts])


def _pset_key(pset) -> str | None:
    # a downstream tool may share our pset with its own copies through its
    # own (stamped) rel: those owners are not ours, so they stay out (#83)
    owners = sorted(_ref(o) or "" for rel in (pset.DefinesOccurrence or ())
                    if not foreign(rel) for o in rel.RelatedObjects)
    owners += sorted(_ref(t) or "" for t in (getattr(pset, "DefinesType", None) or ()))
    if not owners or "" in owners:
        return None
    return f"pset/{'+'.join(owners)}/{pset.Name}"


def foreign(ent) -> bool:
    """Stamped by another application: a downstream tool's own entity,
    whose id is its writer's to keep (bimforge stamps no OwnerHistory)."""
    oh = getattr(ent, "OwnerHistory", None)
    app = oh.OwningApplication if oh is not None else None
    if app is None:
        return False
    name = f"{app.ApplicationIdentifier or ''} {app.ApplicationFullName or ''}"
    return "bimforge" not in name.lower()


def _rekey(model, keyed: list) -> int:
    """Give each (entity, key) its stable id, numbering repeated keys `#n`
    in the order of the third item, all at once: an id another
    entity in the batch holds now is not a clash, one held elsewhere is."""
    counts = Counter(k for _, k, _ in keyed)
    seen: Counter = Counter()
    batch = {e.id() for e, _, _ in keyed}
    out = []
    for ent, key, _ in sorted(keyed, key=lambda x: (x[1], x[2])):
        seen[key] += 1
        full = f"{key}#{seen[key]}" if counts[key] > 1 else key
        gid = stable_id(model, full)
        try:
            clash = model.by_guid(gid)
        except RuntimeError:
            clash = None
        if clash is not None and clash.id() not in batch:
            raise ValueError(f"stable id for {full!r} is already used by "
                             f"{clash.is_a()} '{getattr(clash, 'Name', '') or ''}'")
        out.append((ent, gid))
    for ent, _ in out:          # clear first, so a swap never meets itself
        ent.GlobalId = ifcopenshell.guid.new()
    for ent, gid in out:
        ent.GlobalId = gid
    return len(out)


def key_relationships(model, entities=None) -> int:
    """Key every property set and relationship that touches a schedule,
    task, cost item, calendar or crew (or `entities`); return how many were
    keyed (#80).

    Run it last, once those entities hold their own stable ids:

    - a property set: `pset/<owner ids>/<name>`;
    - a relationship: `rel/<type>/<relating id>`, with the related entity
      too when that side is one entity (a sequence: predecessor and
      successor), so a lag or type change keeps the id;
    - a repeated key takes `#n`, in the order of its members' ids.

    `entities` narrows the scope to those (an alignment and its parts,
    say); by default it is every IfcProcess, IfcControl and IfcResource.
    A relationship or property set stamped by another application (its
    OwnerHistory names one) keeps its id: a downstream tool's additions
    are its own.
    One whose relating side has no id or label stays random. Writers that
    add tasks or assignments to an embedded file call it before saving."""
    if entities is None:
        entities = [e for cls in _SCOPE for e in model.by_type(cls)]
    scope = {e.id() for e in entities}
    psets, rels = [], []
    for rel in model.by_type("IfcRelationship"):
        relating, related = _ends(rel)
        if foreign(rel) or not any(e.id() in scope for e in relating + related):
            continue
        if rel.is_a("IfcRelDefinesByProperties"):
            for p in relating:
                if p.is_a("IfcPropertySetDefinition") and not foreign(p):
                    psets.append(p)
        rels.append(rel)
    pset_keyed = []
    for p in {p.id(): p for p in psets}.values():
        key = _pset_key(p)
        if key:
            pset_keyed.append((p, key, p.id()))
    n = _rekey(model, pset_keyed)
    rel_keyed = []
    for rel in rels:
        key = _rel_key(rel)
        if key:
            _, related = _ends(rel)
            rel_keyed.append((rel, key, ",".join(sorted(_ref(e) or "" for e in related))))
    return n + _rekey(model, rel_keyed)
