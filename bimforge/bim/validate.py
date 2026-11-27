"""Accept a file: every check that ships in the package, one verdict (C.11).

`validate(path)` runs the schema and its rules, buildingSMART's alignment
checks, the gate's file-only structure checks and the takeoff contract (X.1)
on any IFC, and returns a `bimforge-validate/1` result. buildingSMART's
normative rules are not run here: CI holds every family bimforge ships to
them (C.8), and the result names the rule set it pinned.
"""
from __future__ import annotations

import hashlib
from importlib.metadata import PackageNotFoundError, version
from importlib.resources import files
from pathlib import Path

import yaml

CONTRACT = "bimforge-validate/1"
#: the sections whose findings fail the file
FAILING = ("schema", "rules", "alignment", "structure", "takeoff")
NO_IDS = "pip install bimforge[ids]"


def _version(dist: str) -> str | None:
    try:
        return version(dist)
    except PackageNotFoundError:
        return None


def rule_set() -> str:
    p = yaml.safe_load((files("bimforge.bim") / "contract" / "bsi_rules.yaml")
                       .read_text("utf-8"))
    return f"{p['repository']}@{p['ref']}"


def _finding(check: str, message: str, inst=None) -> dict:
    out = {"check": check}
    if inst is not None:
        name = getattr(inst, "Name", None)
        out["instance"] = f"#{inst.id()} {inst.is_a()}" + (
            f" {name!r}" if name else "")
    out["message"] = message
    return out


def _lines(check: str, lines) -> list[dict]:
    """A gate check's one-line findings, as findings."""
    return [_finding(check, line) for line in lines]


def _section(findings: list[dict], advisory: bool = False) -> dict:
    if advisory:
        return {"status": "advisory", "findings": findings}
    return {"status": "fail" if findings else "pass", "findings": findings}


def _ids_findings(f, path) -> list[dict]:
    """Each failed entity of each specification of one IDS document."""
    from ifctester import ids
    doc = ids.open(str(path), validate=True)
    doc.validate(f)
    label = Path(str(path)).name
    out = []
    for spec in doc.specifications:
        for inst in spec.failed_entities:
            out.append(_finding(f"{label}: {spec.name}",
                                "fails the specification's requirements", inst))
    return out


def _schema_split(f, rules: bool):
    """(attribute-type findings, rule findings or None when not run).
    schema_issues(f, rules=False) is the attribute pass; the rule findings
    are what the full pass adds."""
    from bimforge.author.gate import schema_issues
    types = schema_issues(f, rules=False)
    if not rules:
        return types, None
    full = schema_issues(f, rules=True)
    seen = list(types)
    extra = []
    for line in full:
        if line in seen:
            seen.remove(line)
        else:
            extra.append(line)
    return types, extra


def validate(path, extra_ids=(), rules: bool = True) -> dict:
    """The bimforge-validate/1 result for the IFC at `path`. Raises
    ValueError naming the file when it cannot be opened as IFC, and naming
    an extra IDS document that does not exist or does not parse."""
    import ifcopenshell

    from bimforge.author.gate import (alignment_issues, formula_issues,
                                      representation_issues, spatial_issues,
                                      unhosted_cut_issues)
    path = Path(path)
    try:
        f = ifcopenshell.open(str(path))
    except (OSError, ValueError, RuntimeError, ifcopenshell.Error) as exc:
        raise ValueError(f"cannot open {path.name}: {exc}") from exc
    for doc in extra_ids:
        if not Path(doc).is_file():
            raise ValueError(f"--ids {doc}: no such file")

    types, rule_lines = _schema_split(f, rules)
    sections = {
        "schema": _section(_lines("schema", types)),
        "rules": (_section(_lines("rule", rule_lines)) if rule_lines is not None
                  else {"status": "not run", "reason": "--no-rules"}),
        "alignment": _section(_lines("alignment", alignment_issues(f))),
        "structure": _section(
            _lines("spatial tree", spatial_issues(f))
            + _lines("formula", formula_issues(f))
            + _lines("representation", representation_issues(f))
            + _lines("earthworks cut", unhosted_cut_issues(f))),
    }
    try:
        import ifctester.ids  # noqa: F401
        have_ids = True
    except ImportError:
        have_ids = False
    contract = files("bimforge.bim") / "contract"
    if have_ids:
        takeoff = _ids_findings(f, contract / "takeoff.ids")
        for doc in extra_ids:
            try:
                takeoff += _ids_findings(f, doc)
            except Exception as exc:     # ifctester raises its own on a bad doc
                raise ValueError(f"--ids {doc}: {exc}") from exc
        sections["takeoff"] = _section(takeoff)
        sections["coverage"] = _section(
            _ids_findings(f, contract / "takeoff-coverage.ids"), advisory=True)
    else:
        for name in ("takeoff", "coverage"):
            sections[name] = {"status": "not run", "reason": NO_IDS}

    failing = sum(len(sections[n].get("findings", [])) for n in FAILING
                  if sections[n]["status"] == "fail")
    if failing:
        verdict = "issues"
    elif any(sections[n]["status"] == "not run" for n in FAILING):
        verdict = "incomplete"
    else:
        verdict = "clean"
    return {
        "contract": CONTRACT,
        "file": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "schema": f.schema_identifier,
        "verdict": verdict,
        "failing": failing,
        "versions": {"bimforge": _version("bimforge"),
                     "ifcopenshell": ifcopenshell.version,
                     "ifctester": _version("ifctester")},
        "sections": sections,
        "not_run": {"normative_rules": {
            "reason": "buildingSMART's ifc-gherkin-rules are run in CI on "
                      "every family bimforge ships, not on this file",
            "rule_set": rule_set()}},
    }
