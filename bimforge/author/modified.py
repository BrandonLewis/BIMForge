"""Modified standards (roadmap M.8, M.9).

A modified standard, the plans' "(MOD)", is its standard class plus
recorded differences: never a new class. Every element whose family checks
it carries the route it was built by and, when modified, each value it
changed, with the standard's and its own. The differences come from what a
spec already says: a project's tables over the packaged ones
(`table_differences`, kept by `load_spec`), the row a project's tables
choose where the packaged ones would choose another (a "Row" difference,
`assign_routes`), a barrier run's Mod dimensions (`barrier_template`).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

#: The routes an element is built by: from the standard's values; the
#: standard's shape with values changed; with a part added, removed or
#: replaced (nothing produces it yet); the standard's class with its own
#: section; authored outright.
ROUTES = ("standard", "modified-by-value", "modified-by-part",
          "modified-by-section", "bespoke")

#: The property set every routed element carries (Route, BasedOn and one
#: IfcComplexProperty per difference, UsageName DIFFERENCE).
ROUTE_PSET = "BIMForge_Route"
DIFFERENCE = "Difference"

#: What `gate.modified` may be: report, fail the build, or ignore.
MODIFIED_MODES = ("warn", "error", "off")


def modified_mode(value) -> str:
    """`gate.modified` as one of `MODIFIED_MODES` (if valid): YAML reads an
    unquoted `off` as false, and an empty `modified:` as None (the default,
    "warn")."""
    if value is None:
        return "warn"
    return "off" if value is False else str(value).lower()


#: A packaged table field that is a dictionary dimension, by the dimension's
#: Code: a difference in it is named by the Code when the element's class
#: declares that dimension, else by the field.
FIELD_DIMENSIONS = {"C_ft": "ToeWidth", "toe_ft": "ToeWidth",
                    "B_ft": "HeelWidth", "T_ft": "StemThickness",
                    "stem_thickness_ft": "StemThickness",
                    "stem_top_thickness_ft": "StemThickness",
                    "batter": "Batter"}


@dataclass(frozen=True)
class Difference:
    """One packaged value the project changed: where it is in the tables,
    the pack's value (None: a row or field the project added) and the
    project's."""
    path: tuple
    standard: object
    actual: object


def _same(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-9)
    return a == b


def _added(value, path: tuple) -> list:
    if isinstance(value, dict):
        return [d for k, v in value.items() for d in _added(v, path + (k,))]
    return [Difference(path, None, value)]


def table_differences(standard: dict, merged: dict, path: tuple = ()) -> list:
    """Every leaf of `merged` that differs from `standard` (numbers within
    1e-9, anything else exactly), and every leaf `standard` does not have,
    in `merged`'s order. A key is matched as written: "8" is not 8."""
    out: list = []
    for key, value in merged.items():
        here = path + (key,)
        if key not in standard:
            out.extend(_added(value, here))
            continue
        base = standard[key]
        if isinstance(value, dict) and isinstance(base, dict):
            out.extend(table_differences(base, value, here))
        elif not _same(base, value):
            out.append(Difference(here, base, value))
    return out


def path_text(path: tuple) -> str:
    """`("type_1_case_1", "table", 8, "W_ft")` -> "type_1_case_1.table.8.W_ft"."""
    return ".".join(str(p) for p in path)


def difference_measure(name: str) -> tuple:
    """(IFC measure, feet per unit or None when not a length) of a
    difference named `name`: a dictionary dimension's own measure, else by
    the field's suffix (`_ft` feet, `_in` inches), a raw `batter` field a
    ratio, else an IfcReal (a "Row" difference's tabulated key)."""
    from bimforge.author import family_dictionary as fd
    if name.lower() == "batter":
        return ("IfcRatioMeasure", None)
    try:
        ifc_type, scales = fd.measure(name)
    except KeyError:
        if name.endswith("_ft"):
            return ("IfcLengthMeasure", 1.0)
        if name.endswith("_in"):
            return ("IfcLengthMeasure", 1.0 / 12.0)
        return ("IfcReal", None)
    return (ifc_type, 1.0 if scales else None)


def _value(name: str, value):
    """A difference's value in the author domain: a ratio dimension given
    as text ("0.5:12", "NONE"), a raw `batter` field among them, is its
    ratio; anything else as written."""
    if isinstance(value, str) and difference_measure(name)[0] in (
            "IfcRatioMeasure", "IfcPositiveRatioMeasure"):
        from bimforge.author.alignment import parse_batter
        return parse_batter(value)
    return value


def _at(tables, path: tuple):
    """The value at `path` in `tables`, or None when it has none."""
    for key in path:
        if not isinstance(tables, dict) or key not in tables:
            return None
        tables = tables[key]
    return tables


def _row_differences(el, lookup, baseline: dict, source: str) -> list:
    """A "Row" difference for each of `el.table_rows` the standard would
    choose another row of (or has no such table, or no row for that H):
    `lookup(table, H)` is how the family chooses one."""
    out = []
    for path, (H, key) in el.table_rows.items():
        table = _at(baseline, path)
        std = None
        if isinstance(table, dict) and table:
            try:
                std = lookup(table, H)
            except ValueError:              # H beyond the standard's rows
                pass
        if std is not None and _same(std, key):
            continue
        out.append({"name": "Row", "standard": std, "actual": key,
                    "source": f"{source} {path_text(path)}".strip()})
    return out


def assign_routes(model, differences: list, source: str,
                  baseline: dict | None = None) -> None:
    """Give each typed element (a `family_class`) whose family checks it a
    route: the one the family set (a barrier's), else, for an element that
    says what it read (`Element.table_reads`, `Element.table_rows`),
    "modified-by-value" with the `differences` it read and a "Row"
    difference for each row the `baseline` tables would not have chosen
    (by `model.row_lookup`), else "standard". An element with nothing to
    check keeps route None: no route is recorded. `source` is the
    standard's label, prefixed to each difference's path."""
    by_path = {d.path: d for d in differences}
    lookup = getattr(model, "row_lookup", None)
    for el in model.elements:
        if el.family_class is None or el.route is not None:
            continue
        if not el.table_reads and not el.table_rows:
            continue
        hit = [
            {"name": name,
             "standard": (None if by_path[p].standard is None
                          else _value(name, by_path[p].standard)),
             "actual": _value(name, by_path[p].actual),
             "source": f"{source} {path_text(p)}".strip()}
            for p, name in el.table_reads.items() if p in by_path]
        if baseline is not None and lookup is not None:
            hit += _row_differences(el, lookup, baseline, source)
        el.route = "modified-by-value" if hit else "standard"
        el.differences = hit


def fmt_value(v) -> str:
    """A difference's value as the build log prints it: a float in its
    shortest form (7.0 is "7"), a row the project added "(added)"."""
    if v is None:
        return "(added)"
    return f"{v:g}" if isinstance(v, float) else str(v)


def tables_lines(differences: list, standard: str) -> list:
    """The build log's lines for a project's changes to the tables: one per
    changed value, and one counting the values the standard does not have."""
    lines = [f"tables: {path_text(d.path)} {fmt_value(d.standard)} -> "
             f"{fmt_value(d.actual)} (standard: {standard})"
             for d in differences if d.standard is not None]
    added = sum(d.standard is None for d in differences)
    if added:
        lines.append(f"tables: {added} value{'s' if added != 1 else ''} "
                     f"added that the standard does not have ({standard})")
    return lines


def modified_lines(model) -> list:
    """One line per kind of modified element: how many, the first's name,
    its route and class, and what it changed."""
    groups: dict = {}
    for el in model.elements:
        if not el.route or not el.route.startswith("modified"):
            continue
        what = (", ".join(f"{d['name']} {fmt_value(d['standard'])} -> "
                          f"{fmt_value(d['actual'])}" for d in el.differences)
                or "its own section")
        key = (el.route, el.based_on or el.family_class, what)
        groups.setdefault(key, []).append(el.name)
    lines = []
    for (route, cls, what), names in groups.items():
        who = (f"{len(names)} elements ({names[0]}, ...)" if len(names) > 1
               else names[0])
        lines.append(f"{who} {route} of {cls}: {what}")
    return lines


def modified_check(model):
    """`gate: {modified: error}`: a pre-emit check failing on every
    modified element of `model`."""
    def check_modified(_model) -> list:
        return modified_lines(model)
    return check_modified
