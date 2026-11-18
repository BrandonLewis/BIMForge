"""The family dictionary, read: the names and standard-plan references the
typed families write come from `dictionary/bimforge-families.bsdd.json`, not
from string literals in each family (roadmap X.4). A class is looked up by
its Code, so a renamed class renames every type the families emit."""
from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files

DICTIONARY = files("bimforge.author") / "dictionary" / "bimforge-families.bsdd.json"


@lru_cache(maxsize=None)
def classes() -> dict:
    """Every class of the dictionary, by Code."""
    doc = json.loads(DICTIONARY.read_text(encoding="utf-8"))
    return {c["Code"]: c for c in doc["Classes"]}


def has_class(code: str) -> bool:
    return code in classes()


def _class(code: str) -> dict:
    try:
        return classes()[code]
    except KeyError:
        raise KeyError(f"no class {code!r} in the family dictionary "
                       f"({DICTIONARY.name})") from None


def type_name(code: str, suffix: str | None = None) -> str:
    """The IFC type name of a class: its Name, with `suffix` (a section
    size) appended where the class says the type name appends one."""
    name = _class(code)["Name"]
    return f"{name} {suffix}" if suffix else name


def standard_plan(code: str) -> str | None:
    """The standard plan a class is built to: its Reference property's
    value, else the plan its DocumentReference names."""
    c = _class(code)
    for cp in c.get("ClassProperties", []):
        if cp["Code"] == "Reference":
            return cp["PredefinedValue"]
    doc = c.get("DocumentReference") or ""
    prefix = "Caltrans Standard Plan "
    return doc[len(prefix):] if doc.startswith(prefix) else None


def reference_psets(code: str) -> dict:
    """The property sets a class fixes on its elements, {pset: {prop: value}}:
    today the standard plan as Pset_*Common.Reference."""
    out: dict = {}
    for cp in _class(code).get("ClassProperties", []):
        if cp.get("PropertySet") and "PredefinedValue" in cp:
            out.setdefault(cp["PropertySet"], {})[cp["Code"]] = cp["PredefinedValue"]
    return out
