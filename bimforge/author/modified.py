"""Modified standards (roadmap M.8, M.9).

A modified standard, the plans' "(MOD)", is its standard class plus
recorded differences: never a new class. Every typed element carries the
route it was built by and, when modified, each value it changed, with the
standard's and its own. The differences come from what a spec already
says: a project's tables over the packaged ones (`table_differences`, kept
by `load_spec`), a barrier run's Mod dimensions (`barrier_template`).
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
    the field's suffix (`_ft` feet, `_in` inches), else an IfcReal."""
    from bimforge.author import family_dictionary as fd
    try:
        ifc_type, scales = fd.measure(name)
    except KeyError:
        if name.endswith("_ft"):
            return ("IfcLengthMeasure", 1.0)
        if name.endswith("_in"):
            return ("IfcLengthMeasure", 1.0 / 12.0)
        return ("IfcReal", None)
    return (ifc_type, 1.0 if scales else None)
