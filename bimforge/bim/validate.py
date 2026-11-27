"""Accept a file: every check that ships in the package, one verdict (C.11).

`validate(path)` runs the schema and its rules, buildingSMART's alignment
checks, the gate's file-only structure checks and the takeoff contract (X.1)
on any IFC, and returns a `bimforge-validate/1` result. buildingSMART's
normative rules are not run here: CI holds every family bimforge ships to
them (C.8), and the result names the rule set it pinned.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from importlib.metadata import PackageNotFoundError, version
from importlib.resources import files
from pathlib import Path

import yaml

CONTRACT = "bimforge-validate/1"
#: the sections whose findings fail the file
FAILING = ("schema", "rules", "alignment", "structure", "takeoff")
NO_IDS = "pip install bimforge[ids]"


class UnreadableFile(ValueError):
    """The IFC cannot be opened, or is not IFC: the verdict is unreadable."""


class BadIds(ValueError):
    """An --ids document does not exist or does not parse."""


def _version(dist: str) -> str | None:
    try:
        return version(dist)
    except PackageNotFoundError:
        return None


def rule_set() -> str:
    """`repository@ref` of buildingSMART's normative rules CI holds every
    family to, read from the shipped contract/bsi_rules.yaml (the file CI's
    bsi-rules job checks its rules out from)."""
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


def _raised(check: str, exc: Exception) -> dict:
    """A check that raised on this file: a failing finding, never a
    traceback (the gate's _run_contained, for a file someone else wrote)."""
    return _finding(f"{check} raised", f"{type(exc).__name__}: {exc}")


def _lines(check: str, fn, *args) -> list[dict]:
    """A gate check's one-line findings, as findings; a raise is one."""
    try:
        return [_finding(check, line) for line in fn(*args)]
    except Exception as exc:     # noqa: BLE001 - a hostile file fails, not crashes
        return [_raised(check, exc)]


def _section(findings: list[dict], advisory: bool = False) -> dict:
    if advisory:
        return {"status": "advisory", "findings": findings}
    return {"status": "fail" if findings else "pass", "findings": findings}


def _not_run(reason: str) -> dict:
    return {"status": "not run", "reason": reason}


def _open_ids(path):
    """An IDS document opened and checked against the IDS schema; BadIds
    naming it when it does not exist or does not parse."""
    from ifctester import ids
    if not Path(path).is_file():
        raise BadIds(f"--ids {path}: no such file")
    try:
        return ids.open(str(path), validate=True)
    except Exception as exc:     # noqa: BLE001 - ifctester raises its own types
        raise BadIds(f"--ids {path}: {exc}") from exc


def _open_shipped(path):
    """One of the package's own contract documents. A broken one is a
    bimforge bug, not the user's argument: it raises as ifctester raises."""
    from ifctester import ids
    return ids.open(str(path), validate=True)


def _ids_findings(f, doc, label: str) -> list[dict]:
    """Each failure of each specification of one opened IDS document. A
    required specification nothing applies to, and a prohibited one that
    applies, fail with no failed entity: they are findings too."""
    try:
        doc.validate(f)
    except Exception as exc:     # noqa: BLE001
        return [_raised(label, exc)]
    out = []
    for spec in doc.specifications:
        check = f"{label}: {spec.name}"
        for inst in spec.failed_entities:
            out.append(_finding(check, "fails the specification's "
                                       "requirements", inst))
        if spec.status is False and not spec.failed_entities:
            if spec.maxOccurs == 0:
                out += [_finding(check, "prohibited by the specification",
                                 inst) for inst in spec.applicable_entities]
            else:
                out.append(_finding(check, "required by the specification; "
                                           "no applicable entity"))
    return out


def _covers(doc, schema: str) -> list[str]:
    """The IFC versions an IDS document's specifications name, when none of
    them is `schema` (ifctester's own test: schema_identifier in
    ifcVersion); empty when the document covers the file."""
    versions = sorted({v for spec in doc.specifications
                       for v in (spec.ifcVersion or ())})
    return [] if schema in versions else versions


NO_PYTEST = ("the schema's rules need pytest, which ifcopenshell's rule "
             "executor imports (pip install bimforge[ids])")


def _missing_pytest(exc: BaseException) -> bool:
    """Whether `exc` is, or was raised from, a missing pytest/_pytest
    (ifcopenshell.express.rule_executor imports _pytest to run the rules)."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, ModuleNotFoundError) and (exc.name or "").split(
                ".")[0] in ("pytest", "_pytest"):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def _schema_sections(f, rules: bool) -> tuple[dict, dict]:
    """(schema, rules) sections from one ifcopenshell.validate pass. When
    the pass with the rules raises, the attribute pass alone gives the
    schema section and the rules are not run (no pytest) or a failing
    finding (anything else): never a pass for a check that did not run."""
    from bimforge.author import gate

    def schema_of(stmts):
        return _section([_finding("schema", line)
                         for kind, line in stmts if kind == "schema"])

    def attributes_only():
        try:
            return schema_of(gate.schema_statements(f, rules=False))
        except Exception as exc:     # noqa: BLE001
            return _section([_raised("schema", exc)])

    if not rules:
        return attributes_only(), _not_run("--no-rules")
    try:
        stmts = gate.schema_statements(f, rules=True)
    except Exception as exc:     # noqa: BLE001
        return attributes_only(), (_not_run(NO_PYTEST) if _missing_pytest(exc)
                                   else _section([_raised("rules", exc)]))
    return schema_of(stmts), _section([_finding("rule", line)
                                       for kind, line in stmts if kind == "rule"])


def _validate(path, extra_ids=(), rules: bool = True) -> tuple[dict, Counter]:
    """validate()'s result, and the file's IfcElement count per class (what
    est-bim validate prints beside it, so the file is opened once)."""
    import ifcopenshell

    from bimforge.author import gate
    path = Path(path)
    try:
        import ifctester.ids  # noqa: F401
        have_ids = True
    except ImportError:
        have_ids = False
    # every --ids document before any check runs: a bad argument costs nothing
    if have_ids:
        extra = [(Path(str(d)).name, _open_ids(d)) for d in extra_ids]
    else:
        for d in extra_ids:
            if not Path(d).is_file():
                raise BadIds(f"--ids {d}: no such file")
        extra = []
    try:
        f = ifcopenshell.open(str(path))
    except (OSError, ValueError, RuntimeError, ifcopenshell.Error) as exc:
        raise UnreadableFile(f"cannot open {path.name}: {exc}") from exc

    schema, rule_section = _schema_sections(f, rules)
    sections = {
        "schema": schema,
        "rules": rule_section,
        "alignment": _section(_lines("alignment", gate.alignment_issues, f)),
        "structure": _section(
            _lines("spatial tree", gate.spatial_issues, f)
            + _lines("formula", gate.formula_issues, f)
            + _lines("representation", gate.representation_issues, f)
            + _lines("earthworks cut", gate.unhosted_cut_issues, f)),
    }
    if have_ids:
        contract = files("bimforge.bim") / "contract"
        takeoff_doc = _open_shipped(contract / "takeoff.ids")
        outside = _covers(takeoff_doc, f.schema_identifier)
        if outside:
            uncovered = (f"the takeoff contract covers {', '.join(outside)}, "
                         f"not {f.schema_identifier}")
            skipped = ", ".join(label for label, _ in extra)
            sections["takeoff"] = _not_run(
                uncovered + (f"; not run: {skipped}" if skipped else ""))
            sections["coverage"] = _not_run(uncovered)
        else:
            takeoff = _ids_findings(f, takeoff_doc, "takeoff.ids")
            for label, doc in extra:
                takeoff += _ids_findings(f, doc, label)
            sections["takeoff"] = _section(takeoff)
            sections["coverage"] = _section(_ids_findings(
                f, _open_shipped(contract / "takeoff-coverage.ids"),
                "takeoff-coverage.ids"), advisory=True)
    else:
        skipped = [Path(str(d)).name for d in extra_ids]
        sections["takeoff"] = _not_run(
            NO_IDS + (f"; not run: {', '.join(skipped)}" if skipped else ""))
        sections["coverage"] = _not_run(NO_IDS)

    failing = sum(len(sections[n].get("findings", [])) for n in FAILING
                  if sections[n]["status"] == "fail")
    if failing:
        verdict = "issues"
    elif any(sections[n]["status"] == "not run" for n in FAILING):
        verdict = "incomplete"
    else:
        verdict = "clean"
    with open(path, "rb") as fh:
        sha256 = hashlib.file_digest(fh, "sha256").hexdigest()
    try:
        counts = Counter(e.is_a() for e in f.by_type("IfcElement"))
    except RuntimeError:         # a schema with no IfcElement: nothing to count
        counts = Counter()
    result = {
        "contract": CONTRACT,
        "file": path.name,
        "sha256": sha256,
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
    return result, counts


def validate(path, extra_ids=(), rules: bool = True) -> dict:
    """The bimforge-validate/1 result for the IFC at `path`. Raises
    UnreadableFile naming the file when it cannot be opened as IFC, and
    BadIds naming an extra IDS document that does not exist or does not
    parse (both before any check runs). A check that raises on the file is
    a failing finding in its section, not an exception."""
    return _validate(path, extra_ids, rules)[0]
