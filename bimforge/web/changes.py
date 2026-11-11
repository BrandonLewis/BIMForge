"""Apply a change-set — what the IFC Navigator add-in hands back — to an
IFC (`est-bim apply-changes`).

The add-in diffs the sheets against the bundle it loaded and emits::

    {"contract": "bimforge-changes/1",
     "source": {"file": "model.ifc", "schema": "IFC4X3"},
     "operations": [
       {"op": "set_property", "global_id": G, "pset": P, "property": N,
        "value": V, "value_type": "IfcLabel" | ... | null},
       {"op": "remove_property", "global_id": G, "pset": P, "property": N},
       {"op": "set_name", "global_id": G, "value": "new name"}]}

`global_id` names an element or a type (a type's properties are edited
once, for every occurrence). A `set_property` on a pset the object lacks
adds the pset; `value_type` names the IFC type to write (the one the
bundle reported for an existing property, or the one the add-in chose for
a new one) and a null type lets IfcOpenShell infer from the Python value.

Every operation is validated BEFORE anything is written: an unknown
GlobalId, op or value type fails the whole set with every problem listed,
so a change-set either applies entirely or not at all. The writer is
IfcOpenShell's pset API, so the result is a normal IFC any viewer opens.
"""
from __future__ import annotations

import json
from pathlib import Path

CONTRACT = "bimforge-changes/1"
OPS = ("set_property", "remove_property", "set_name")

_BOOL_TYPES = {"IfcBoolean", "IfcLogical"}
_INT_TYPES = {"IfcInteger", "IfcCountMeasure"}
_TEXT_TYPES = {"IfcLabel", "IfcText", "IfcIdentifier", "IfcDate", "IfcDateTime", "IfcTime",
               "IfcDuration", "IfcURIReference"}


def coerce(value, value_type: str | None):
    """The Python value an IFC `value_type` wants: bool, int, float or str.
    None stays None. A text that reads as a number is accepted for a
    numeric type (a spreadsheet cell comes back as text more often than
    not); anything else raises ValueError."""
    if value is None or value_type is None:
        return value
    if value_type in _BOOL_TYPES:
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("true", "t", "yes", "y", "1"):
            return True
        if text in ("false", "f", "no", "n", "0"):
            return False
        raise ValueError(f"{value!r} is not a {value_type}")
    if value_type in _INT_TYPES:
        try:
            f = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{value!r} is not a {value_type}") from None
        if f != int(f):
            raise ValueError(f"{value!r} is not a whole {value_type}")
        return int(f)
    if value_type in _TEXT_TYPES or value_type.endswith("Enum"):
        return str(value)
    if value_type.endswith("Measure") or value_type in ("IfcReal", "IfcNumericMeasure", "IfcRatioMeasure"):
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{value!r} is not a {value_type}") from None
    # an IfcLabel-like type we do not know: keep the value as given
    return value


def validate_changes(model, changes: dict) -> list[str]:
    """Every problem with `changes` against `model`, as text; [] when it
    can be applied."""
    problems = []
    if not isinstance(changes, dict) or changes.get("contract") != CONTRACT:
        return [f"not a {CONTRACT} change-set: contract={(changes or {}).get('contract')!r}"]
    ops = changes.get("operations")
    if not isinstance(ops, list):
        return ["change-set lacks an operations list"]
    for i, op in enumerate(ops):
        where = f"operation {i}"
        kind = op.get("op")
        if kind not in OPS:
            problems.append(f"{where}: unknown op {kind!r}")
            continue
        gid = op.get("global_id")
        try:
            obj = model.by_guid(gid) if gid else None
        except RuntimeError:
            obj = None
        if obj is None:
            problems.append(f"{where}: no object with GlobalId {gid!r}")
            continue
        if not (obj.is_a("IfcObject") or obj.is_a("IfcTypeObject")):
            problems.append(f"{where}: {gid} is an {obj.is_a()}, not an object or type")
            continue
        if kind in ("set_property", "remove_property"):
            if not op.get("pset") or not op.get("property"):
                problems.append(f"{where}: {kind} needs pset and property")
        if kind == "set_property":
            vt = op.get("value_type")
            if vt is not None:
                try:
                    model.create_entity(vt, coerce(op.get("value"), vt))
                except Exception as exc:        # unknown type, or a value it refuses
                    problems.append(f"{where}: {gid} {op['pset']}.{op['property']}: {exc}")
        if kind == "set_name" and not isinstance(op.get("value"), (str, type(None))):
            problems.append(f"{where}: set_name value must be text")
    return problems


def apply_changes(ifc_path, changes: dict, out_path) -> dict:
    """Apply `changes` to the IFC at `ifc_path` and write `out_path` (the
    same path edits in place). Raises ValueError, writing nothing, if
    `validate_changes` finds a problem. Returns the report:
    {"applied", "objects", "added_psets", "removed", "renamed"}."""
    import ifcopenshell
    import ifcopenshell.api
    import ifcopenshell.util.element as ue

    model = ifcopenshell.open(str(ifc_path))
    problems = validate_changes(model, changes)
    if problems:
        raise ValueError("change-set refused:\n  " + "\n  ".join(problems))

    report = {"applied": 0, "objects": set(), "added_psets": 0, "removed": 0, "renamed": 0}
    for op in changes["operations"]:
        obj = model.by_guid(op["global_id"])
        report["objects"].add(op["global_id"])
        if op["op"] == "set_name":
            obj.Name = op["value"]
            report["renamed"] += 1
        else:
            psets = ue.get_psets(obj, psets_only=True, should_inherit=False)
            existing = psets.get(op["pset"])
            if op["op"] == "remove_property":
                if existing and op["property"] in existing:
                    pset = model.by_id(existing["id"])
                    ifcopenshell.api.run("pset.edit_pset", model, pset=pset,
                                         properties={op["property"]: None})
                    report["removed"] += 1
            else:
                if existing:
                    pset = model.by_id(existing["id"])
                else:
                    pset = ifcopenshell.api.run("pset.add_pset", model, product=obj, name=op["pset"])
                    report["added_psets"] += 1
                vt = op.get("value_type")
                value = coerce(op.get("value"), vt)
                if vt is not None and value is not None:
                    value = model.create_entity(vt, value)
                ifcopenshell.api.run("pset.edit_pset", model, pset=pset,
                                     properties={op["property"]: value})
        report["applied"] += 1
    model.write(str(out_path))
    report["objects"] = len(report["objects"])
    return report


def load_changes(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
