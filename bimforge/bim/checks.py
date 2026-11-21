"""A measurement check recorded in the model (roadmap M.5).

The owner measures an element in Bonsai or ProjectCommand and compares the
measurement to the plan sheet. ProjectCommand records a check where it is
taken; `record_check` records one made in Bonsai, in the same shape
(ProjectCommand's crates/core/src/ifc/check.rs, agreed with it), so either
reads the other's:

- an IfcObjective "Check: <name>" (ObjectiveQualifier USERDEFINED,
  "measurement") of three IfcMetric: `SheetValue` (ValueSource the sheet,
  ConstraintSource its revision), `ModelValue` (ValueSource "stated", the
  file's own value, or "measured", off the geometry; ConstraintSource
  "build:<BuildId>; sha256:<the file as opened>") and `Tolerance`
  (relative, an IfcRatioMeasure). The two values are IfcLengthMeasure,
  IfcAreaMeasure or IfcVolumeMeasure in the file's project units, and name
  what was measured by an IfcReference chain (set, then quantity or
  property), never by pointing at it: a rebuild makes those anew;
- tied to the element by IfcRelAssociatesConstraint;
- an IfcApproval: Identifier "<GlobalId>/<set>/<name>" (one check per thing
  on one element; recording it again replaces it), Status "agrees" or
  "differs", Level "measurement", Qualifier the tolerance in words,
  TimeOfApproval the day, GivingApproval who checked;
- tied to the objective by an IfcResourceApprovalRelationship "Checked" and
  to the element by IfcRelAssociatesApproval;
- the sheet as IfcDocumentInformation (Identification the sheet, Revision
  the plan set's revision), one per element per sheet per revision, tied to
  the element by IfcRelAssociatesDocument.

The rooted relationships are stamped with an IfcOwnerHistory naming the
application the check was made in (Bonsai by default), ADDED when new and
MODIFIED when written again, so `carry_forward` carries the check through a
rebuild; a reader calls it lapsed when the file's value has moved past the
tolerance, nothing drops it.
"""
from __future__ import annotations

import time
import uuid

import ifcopenshell
import ifcopenshell.guid

from bimforge.bim.ifc_takeoff import CONVERT, QUANTITY_DIM, _unit_scales

LEVEL = "measurement"

#: the measures ProjectCommand reads a check's two values as
MEASURES = {"length": "IfcLengthMeasure", "area": "IfcAreaMeasure",
            "volume": "IfcVolumeMeasure"}

#: a property's measure -> its dimension
PROPERTY_DIM = {"IfcLengthMeasure": "length",
                "IfcPositiveLengthMeasure": "length",
                "IfcAreaMeasure": "area", "IfcVolumeMeasure": "volume"}

_NS = uuid.UUID("6b1d0f4e-5c1a-4f3e-9d0b-6d5f8f0c2a11")


def _gid(identifier: str, role: str) -> str:
    """A stable GlobalId for one part of one check."""
    return ifcopenshell.guid.compress(
        uuid.uuid5(_NS, f"{identifier}#{role}").hex)


def _target(element, set_name: str, name: str):
    """(dimension, the file's value in project units, is a quantity) of the
    named quantity or property on `element`."""
    from bimforge.bim.ifc_takeoff import quantity_sets
    for qto in quantity_sets(element):
        if qto.Name != set_name:
            continue
        for q in qto.Quantities or []:
            if q.Name == name:
                dim = QUANTITY_DIM.get(q.is_a())
                if dim not in MEASURES:
                    raise ValueError(f"{set_name}.{name} is a {q.is_a()}: a "
                                     f"check is of a length, area or volume")
                return dim, float(q[3]), True
    for rel in getattr(element, "IsDefinedBy", None) or []:
        pset = getattr(rel, "RelatingPropertyDefinition", None)
        if pset is None or not pset.is_a("IfcPropertySet") \
                or pset.Name != set_name:
            continue
        for prop in pset.HasProperties or []:
            if prop.Name != name:
                continue
            nv = getattr(prop, "NominalValue", None)
            dim = PROPERTY_DIM.get(nv.is_a()) if nv is not None else None
            if dim is None:
                raise ValueError(
                    f"{set_name}.{name} is "
                    f"{nv.is_a() if nv is not None else 'empty'}: a check "
                    f"is of a length, area or volume")
            return dim, float(nv.wrappedValue), False
    raise ValueError(f"element {element.GlobalId} has no {set_name}.{name}")


def to_project_units(model, value: float, unit: str, dim: str) -> float:
    """`value` in `unit` (M, FT, IN, YD, M2, SF, SY, M3, CY, CF) as the
    file's project units of `dim`. A foot is the project's foot, as its
    stations and dimensions are (US survey unless the file declares the
    international foot)."""
    from bimforge.bim.alignment_station import foot_m
    u = unit.upper()
    if dim == "length" and u in ("FT", "IN", "YD"):
        si = value * foot_m(model) * {"FT": 1.0, "IN": 1 / 12, "YD": 3.0}[u]
    else:
        factors = CONVERT.get(dim, {})
        if u not in factors:
            raise ValueError(f"unit {unit!r} is not a {dim} unit (choices: "
                             f"{sorted(set(factors) | ({'FT', 'IN', 'YD'} if dim == 'length' else set()))})")
        si = value / factors[u]
    return si / _unit_scales(model)[dim]


def _reference(model, set_name: str, name: str, quantity: bool):
    if quantity:
        inner = model.createIfcReference("IfcPhysicalQuantity", "Quantities",
                                         name, None, None)
        return model.createIfcReference("IfcElementQuantity", None, set_name,
                                        None, inner)
    inner = model.createIfcReference("IfcPropertySingleValue",
                                     "HasProperties", name, None, None)
    return model.createIfcReference("IfcPropertySet", None, set_name, None,
                                    inner)


def _owner_history(model, app: str, action: str, by: str | None):
    # an application is unique in a file (IfcApplication UR1, UR2)
    application = next((a for a in model.by_type("IfcApplication")
                        if a.ApplicationIdentifier == app), None)
    if application is None:
        application = model.createIfcApplication(
            model.createIfcOrganization(Name=app), "", app, app)
    org = application.ApplicationDeveloper
    who = model.createIfcPersonAndOrganization(
        model.createIfcPerson(FamilyName=by or app), org)
    now = int(time.time())
    return model.createIfcOwnerHistory(who, application, None, action, now,
                                       None, None, now)


def _existing(model, identifier: str):
    for rel in model.by_type("IfcRelAssociatesApproval"):
        a = rel.RelatingApproval
        if a is not None and a.Identifier == identifier \
                and a.Level == LEVEL:
            return rel
    return None


def _remove(model, identifier: str) -> dict | None:
    """Remove the check recorded under `identifier`, whoever recorded it,
    keeping its sheet; the GlobalIds of its relationships, to write it
    again under, or None when there was none."""
    rel = _existing(model, identifier)
    if rel is None:
        return None
    gids = {"approval": rel.GlobalId}
    approval = rel.RelatingApproval
    objectives = []
    for link in model.by_type("IfcResourceApprovalRelationship"):
        if link.RelatingApproval == approval:
            objectives += list(link.RelatedResourceObjects or [])
            model.remove(link)
    for c in model.by_type("IfcRelAssociatesConstraint"):
        if c.RelatingConstraint in objectives:
            gids["constraint"] = c.GlobalId
            model.remove(c)
    for obj in objectives:
        _remove_objective(model, obj)
    model.remove(rel)
    model.remove(approval)
    return gids


def _remove_objective(model, objective) -> None:
    try:
        model.by_id(objective.id())
    except RuntimeError:
        return
    for m in objective.BenchmarkValues or []:
        ref = m.ReferencePath
        model.remove(m)
        while ref is not None:
            inner = ref.InnerReference
            if not model.get_inverse(ref):
                model.remove(ref)
            ref = inner
    model.remove(objective)


def _sheet(model, element, sheet: str, revision: str | None, oh):
    for rel in model.by_type("IfcRelAssociatesDocument"):
        doc = rel.RelatingDocument
        if doc is not None and doc.is_a("IfcDocumentInformation") \
                and doc.Identification == sheet \
                and (doc.Revision or None) == (revision or None) \
                and element in (rel.RelatedObjects or ()):
            return
    doc = model.createIfcDocumentInformation(sheet, sheet)
    doc.Revision = revision
    model.createIfcRelAssociatesDocument(
        _gid(f"{element.GlobalId}/{sheet}/{revision or ''}", "sheet"), oh,
        None, None, [element], doc)


def record_check(model, global_id: str, set_name: str, name: str, *,
                 sheet: str, sheet_value: float, unit: str,
                 tolerance: float = 0.01, revision: str | None = None,
                 by: str | None = None, day: str | None = None,
                 measured: float | None = None, file_sha256: str = "",
                 app: str = "Bonsai") -> dict:
    """Record in `model` that `set_name`.`name` on the element `global_id`
    was compared to `sheet_value` (in `unit`) on `sheet`: the model value is
    the file's own (`stated`) unless `measured` (in `unit`, off the
    geometry) is given; it agrees within `tolerance`, relative. Replaces a
    check recorded before on the same thing. Returns what was recorded."""
    from bimforge.bim import model_identity
    try:
        element = model.by_guid(global_id)
    except RuntimeError:
        raise ValueError(f"no element {global_id} in the model") from None
    if not element.is_a("IfcElement"):
        raise ValueError(f"{global_id} is a {element.is_a()}, not an element")
    if not (0 <= tolerance < 1):
        raise ValueError(f"tolerance {tolerance} is relative: 0 to under 1")
    dim, stated, quantity = _target(element, set_name, name)
    sheet_pu = to_project_units(model, sheet_value, unit, dim)
    if measured is None:
        model_pu, source = stated, "stated"
    else:
        model_pu, source = to_project_units(model, measured, unit, dim), \
            "measured"
    agrees = abs(model_pu - sheet_pu) <= tolerance * abs(sheet_pu)
    identifier = f"{global_id}/{set_name}/{name}"
    old = _remove(model, identifier)
    replaced = old is not None
    gids = {"approval": _gid(identifier, "approval"),
            "constraint": _gid(identifier, "constraint"), **(old or {})}
    oh = _owner_history(model, app, "MODIFIED" if replaced else "ADDED", by)
    ident = model_identity.read(model) or {}
    origin = "; ".join(p for p in (
        f"build:{ident['BuildId']}" if ident.get("BuildId") else "",
        f"sha256:{file_sha256}" if file_sha256 else "") if p) or None
    measure = MEASURES[dim]
    metrics = (
        model.createIfcMetric(
            "SheetValue", None, "ADVISORY", revision, None, None, None,
            "EQUALTO", sheet, model.create_entity(measure, sheet_pu),
            _reference(model, set_name, name, quantity)),
        model.createIfcMetric(
            "ModelValue", None, "ADVISORY", origin, None, None, None,
            "EQUALTO", source, model.create_entity(measure, model_pu),
            _reference(model, set_name, name, quantity)),
        model.createIfcMetric(
            "Tolerance", None, "ADVISORY", None, None, None, None,
            "LESSTHANOREQUALTO", "relative",
            model.createIfcRatioMeasure(tolerance), None))
    title = f"Check: {name}"
    objective = model.createIfcObjective(
        title, None, "ADVISORY", None, None, None, None, metrics, None,
        "USERDEFINED", LEVEL)
    model.createIfcRelAssociatesConstraint(
        gids["constraint"], oh, title, None, [element], None,
        objective)
    giver = model.createIfcPerson(FamilyName=by) if by else None
    status = "agrees" if agrees else "differs"
    approval = model.createIfcApproval(
        identifier, title, None,
        f"{day or time.strftime('%Y-%m-%d')}T00:00:00", status, LEVEL,
        f"within {tolerance * 100:g}%", None, giver)
    model.createIfcResourceApprovalRelationship("Checked", None,
                                                (objective,), approval)
    model.createIfcRelAssociatesApproval(
        gids["approval"], oh, title, None, [element], approval)
    _sheet(model, element, sheet, revision, oh)
    return {"identifier": identifier, "status": status,
            "sheet_value": sheet_pu, "model_value": model_pu,
            "value_source": source, "replaced": replaced,
            "measure": measure}


def read_checks(model) -> list[dict]:
    """Every measurement check in `model`, whoever recorded it: {identifier,
    status, day, by, sheet, revision, sheet_value, model_value,
    value_source, model_origin, tolerance} (values in project units)."""
    out = []
    links = {link.RelatingApproval.id(): link
             for link in model.by_type("IfcResourceApprovalRelationship")
             if link.RelatingApproval is not None}
    for rel in model.by_type("IfcRelAssociatesApproval"):
        a = rel.RelatingApproval
        if a is None or a.Level != LEVEL:
            continue
        rec = {"identifier": a.Identifier, "status": a.Status,
               "day": (a.TimeOfApproval or "")[:10],
               "by": getattr(a.GivingApproval, "FamilyName", None)
               if a.GivingApproval is not None else None}
        link = links.get(a.id())
        for obj in (link.RelatedResourceObjects or ()) if link else ():
            for m in getattr(obj, "BenchmarkValues", None) or []:
                v = m.DataValue.wrappedValue if m.DataValue is not None \
                    else None
                if m.Name == "SheetValue":
                    rec.update(sheet=m.ValueSource,
                               revision=m.ConstraintSource, sheet_value=v)
                elif m.Name == "ModelValue":
                    rec.update(model_value=v, value_source=m.ValueSource,
                               model_origin=m.ConstraintSource)
                elif m.Name == "Tolerance":
                    rec["tolerance"] = v
        out.append(rec)
    return sorted(out, key=lambda r: r["identifier"] or "")
