"""Carry a returned IFC's own additions onto a rebuilt one (#83).

A downstream tool (a contractor's scheduler, an approvals register) returns
the file bimforge wrote with its own work added: its own IfcWorkSchedule, a
full copy of ours whose tasks are tied to ours by IfcRelDefinesByObject;
IfcApproval on our GlobalIds; progress on its own tasks. It never modifies
an entity of ours (what it added itself it may replace or remove, stamped
MODIFIED), and stamps everything it adds with an IfcOwnerHistory naming its
application. A rebuild regenerates bimforge's part from the source, then
`carry_forward` copies every stamped addition onto the rebuilt file, from the
returned file alone (nothing of an earlier carry is read):

- its GlobalIds are kept exactly, so the tool sees its own entities again;
- what it references of ours is re-pointed onto the rebuilt entity by
  GlobalId (our ids are stable: #74, #80);
- what it references that is not rooted (an IfcApproval, its organizations,
  a task's IfcTaskTime) is copied with it.

Nothing is merged field by field. The report says, both ways, what no longer
lines up: additions whose target is gone (dropped, or the whole relationship
when nothing is left to relate), our tasks and elements no downstream task
covers, and our entities the returned file changed anyway (they are rebuilt
from the source, so that edit is lost, but loudly).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from bimforge.bim.stable_ids import _ends, foreign

# what a changed entity of ours is looked for in: what the embedders write
_OURS = ("IfcProcess", "IfcControl", "IfcResource")


@dataclass
class CarryReport:
    carried: int = 0                         # rooted additions copied
    already_present: int = 0                 # additions the rebuilt file has
    applications: list[str] = field(default_factory=list)
    vanished: list[dict] = field(default_factory=list)
    dropped: list[dict] = field(default_factory=list)
    uncovered_tasks: list[dict] = field(default_factory=list)
    uncovered_elements: list[dict] = field(default_factory=list)
    modified: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _label(ent) -> dict:
    return {"global_id": ent.GlobalId, "class": ent.is_a(),
            "name": getattr(ent, "Name", None)}


def _app(ent) -> str:
    app = ent.OwnerHistory.OwningApplication
    return app.ApplicationFullName or app.ApplicationIdentifier or "?"


class _Copier:
    """Copies entities of `src` into `dst`. A rooted entity of ours maps to
    the rebuilt one by GlobalId (None when it is gone); anything else is
    copied once, with what it references."""

    def __init__(self, src, dst):
        self.src, self.dst = src, dst
        self.memo: dict[int, object] = {}
        self.missing: dict[str, object] = {}       # GlobalId -> returned entity

    def _ours(self, ent):
        try:
            hit = self.dst.by_guid(ent.GlobalId)
        except RuntimeError:
            hit = None
        if hit is None:
            self.missing[ent.GlobalId] = ent
        return hit

    def entity(self, ent):
        if ent.id() == 0:
            # a typed value in a select (an IfcDuration lag, an IfcLabel
            # NominalValue): not an instance, so every one has id 0 and
            # must never be memoised
            return self.dst.create_entity(ent.is_a(), ent.wrappedValue)
        if ent.id() in self.memo:
            return self.memo[ent.id()]
        if ent.is_a("IfcRoot") and not foreign(ent):
            hit = self._ours(ent)
            self.memo[ent.id()] = hit
            return hit
        if ent.is_a("IfcRoot"):
            try:
                hit = self.dst.by_guid(ent.GlobalId)
            except RuntimeError:
                hit = None
            if hit is not None:                     # carried before
                self.memo[ent.id()] = hit
                return hit
        ctx = self._context(ent)
        if ctx is not None:
            self.memo[ent.id()] = ctx
            return ctx
        new = self.dst.create_entity(ent.is_a())
        self.memo[ent.id()] = new                    # before the attributes: cycles
        for i in range(len(ent)):
            value = self.value(ent[i])
            if value is not None:
                new[i] = value
        return new

    def _context(self, ent):
        """A representation context of ours maps onto the rebuilt file's,
        so a copied shape does not bring a second model context."""
        if not ent.is_a("IfcGeometricRepresentationContext"):
            return None
        sub = ent.is_a("IfcGeometricRepresentationSubContext")
        for c in self.dst.by_type(ent.is_a()):
            if c.is_a() != ent.is_a():
                continue
            same = (c.ContextType, c.ContextIdentifier) == (
                ent.ContextType, ent.ContextIdentifier)
            if same and (not sub or c.TargetView == ent.TargetView):
                return c
        return None

    def value(self, value):
        import ifcopenshell
        if isinstance(value, ifcopenshell.entity_instance):
            return self.entity(value)
        if isinstance(value, tuple):
            items = [self.value(v) for v in value]
            items = [v for v in items if v is not None]
            return tuple(items) if items else None
        return value


def _signature(ent, depth: int = 0):
    """An entity's direct attributes, ours compared by GlobalId and the
    resources it holds (an IfcTaskTime) by value."""
    out = []
    for i in range(len(ent)):
        if ent.attribute_name(i) == "OwnerHistory":
            continue
        out.append(_value_sig(ent[i], depth))
    return tuple(out)


def _value_sig(v, depth):
    import ifcopenshell
    if isinstance(v, ifcopenshell.entity_instance):
        if v.is_a("IfcRoot"):
            return v.GlobalId
        return (v.is_a(), _signature(v, depth + 1)) if depth < 3 else v.is_a()
    if isinstance(v, tuple):
        return tuple(_value_sig(x, depth) for x in v)
    if isinstance(v, float):
        return round(v, 9)
    return v


def carry_forward(returned, rebuilt) -> CarryReport:
    """Copy every addition another application stamped in `returned` onto
    `rebuilt` (in place) and report what no longer lines up.

    Raises ValueError when the two files are different projects."""
    rp, bp = returned.by_type("IfcProject"), rebuilt.by_type("IfcProject")
    if not rp or not bp or rp[0].GlobalId != bp[0].GlobalId:
        raise ValueError(
            "the returned file is another project: its IfcProject GlobalId "
            f"{rp[0].GlobalId if rp else None} is not the rebuilt file's "
            f"{bp[0].GlobalId if bp else None}")
    report = CarryReport()
    added = [e for e in returned.by_type("IfcRoot") if foreign(e)]
    report.applications = sorted({_app(e) for e in added})
    copier = _Copier(returned, rebuilt)

    def present(ent) -> bool:
        try:
            return rebuilt.by_guid(ent.GlobalId) is not None
        except RuntimeError:
            return False

    rels = [e for e in added if e.is_a("IfcRelationship")]
    for ent in [e for e in added if not e.is_a("IfcRelationship")]:
        if present(ent):
            report.already_present += 1
            continue
        copier.entity(ent)
        report.carried += 1
    for rel in rels:
        if present(rel):
            report.already_present += 1
            continue
        relating, related = _ends(rel)
        before = set(copier.missing)
        live_relating = [copier.entity(e) for e in relating]
        live_related = [copier.entity(e) for e in related]
        gone = [copier.missing[g] for g in set(copier.missing) - before]
        if None in live_relating or not any(x is not None for x in live_related):
            report.dropped.append({**_label(rel), "missing": [
                _label(e) for e in gone]})
            continue
        copier.entity(rel)
        report.carried += 1
        if gone:
            report.vanished.append({**_label(rel), "missing": [
                _label(e) for e in gone]})
    for gid, ent in copier.missing.items():
        if not any(gid in [m["global_id"] for m in r["missing"]]
                   for r in report.vanished + report.dropped):
            report.vanished.append({**_label(ent), "missing": [_label(ent)]})

    _modified(returned, rebuilt, report)
    _uncovered(rebuilt, report)
    return report


def _modified(returned, rebuilt, report: CarryReport) -> None:
    for cls in _OURS:
        for ent in returned.by_type(cls):
            if foreign(ent):
                continue
            try:
                mine = rebuilt.by_guid(ent.GlobalId)
            except RuntimeError:
                continue                  # the source dropped it
            stamped = (ent.OwnerHistory is not None
                       and ent.OwnerHistory.ChangeAction == "MODIFIED")
            if stamped or _signature(ent) != _signature(mine):
                report.modified.append(_label(ent))


def _uncovered(rebuilt, report: CarryReport) -> None:
    """With a downstream schedule in the file: our tasks no downstream task
    is tied to, and elements our tasks build that no downstream task does."""
    theirs = [ws for ws in rebuilt.by_type("IfcWorkSchedule") if foreign(ws)]
    if not theirs:
        return
    tied = {rel.RelatingObject.id() for rel in rebuilt.by_type("IfcRelDefinesByObject")
            if foreign(rel) and rel.RelatingObject is not None}
    built_by_them, built_by_us = set(), {}
    for rel in rebuilt.by_type("IfcRelAssignsToProduct"):
        if rel.RelatingProduct is None:
            continue
        tasks = [o for o in rel.RelatedObjects if o.is_a("IfcTask")]
        if any(foreign(t) for t in tasks):
            built_by_them.add(rel.RelatingProduct.id())
        if any(not foreign(t) for t in tasks):
            built_by_us[rel.RelatingProduct.id()] = rel.RelatingProduct
    for task in rebuilt.by_type("IfcTask"):
        if not foreign(task) and task.id() not in tied:
            report.uncovered_tasks.append(_label(task))
    for eid, el in built_by_us.items():
        if eid not in built_by_them:
            report.uncovered_elements.append(_label(el))
