"""Run buildingSMART's normative rules on bimforge's outputs, against a baseline (#94).

The schema's own rules are checked in the test suite (gate.schema_issues).
The normative rules — implementer agreements, informal propositions and
industry practice — live in buildingSMART's ifc-gherkin-rules, a behave
suite with its own pinned dependencies, so it runs here from a checkout
and its own Python:

    python scripts/bsi_rules.py --rules ifc-gherkin-rules \
        --python rules-venv/bin/python DIR

DIR holds the .ifc files to check (test_conformance.py writes them under
BIMFORGE_CONFORMANCE_OUT). Each rule a file breaks is a finding. A finding
is accepted only when scripts/bsi_baseline.yaml lists it under that rule,
with why; anything else fails. So does a baseline entry no longer found, so
the baseline shrinks as the findings are fixed. A rule whose own code
raised is reported, never gated: it says nothing about the file.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

BASELINE = Path(__file__).with_name("bsi_baseline.yaml")
_OUTCOME = re.compile(r"ValidationOutcome\(inst=(\d+).*?severity=ValidationOutcome"
                      r"\.OutcomeSeverity\.(ERROR|WARNING)")


def run_rules(rules: Path, python: str, ifc: Path) -> tuple[dict, list[str]]:
    """({rule code: [instance ids]}, [rule codes whose code raised])."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "behave.json"
        subprocess.run(
            [python, "-m", "behave", "--tags=-disabled",
             "--define", f"input={ifc.resolve()}",
             "--define", "execution_mode=None",
             "--define", "max_outcomes_per_rule=0",
             "-f", "outcome_embedding_json", "-o", str(out)],
            cwd=rules, capture_output=True, check=False)
        log = json.loads(out.read_text("utf-8"))
    found, raised = {}, []
    for feat in log:
        if feat.get("status") != "failed":
            continue
        code = feat["name"].split(" - ")[0].strip()
        for step in (s for sc in feat.get("elements", [])
                     for s in sc.get("steps", [])):
            result = step.get("result", {})
            if result.get("status") != "failed":
                continue
            msg = " ".join(result.get("error_message", []))
            insts = [int(i) for i, _sev in _OUTCOME.findall(msg)]
            if insts:
                found.setdefault(code, []).extend(insts)
            elif code not in raised:
                raised.append(code)
    return found, raised


def compare(results: dict, baseline: dict) -> tuple[list[str], list[str]]:
    """(new findings, stale baseline entries), as printable lines.
    `results` is {output: {rule code: [instance ids]}}."""
    accepted = {(out, code) for code, entry in (baseline.get("accepted") or {}).items()
                for out in entry.get("outputs", [])}
    found = {(out, code) for out, rules in results.items() for code in rules}
    new = [f"{out}: {code} (#{', #'.join(map(str, sorted(set(results[out][code]))[:5]))})"
           for out, code in sorted(found - accepted)]
    stale = [f"{out}: {code}" for out, code in sorted(accepted - found)
             if out in results]
    return new, stale


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dir", type=Path, help="folder of .ifc files to check")
    ap.add_argument("--rules", type=Path, required=True,
                    help="an ifc-gherkin-rules checkout, with its submodule")
    ap.add_argument("--python", default=sys.executable,
                    help="the Python the rules' requirements are installed in")
    ap.add_argument("--baseline", type=Path, default=BASELINE)
    args = ap.parse_args(argv)

    files = sorted(args.dir.glob("*.ifc"))
    if not files:
        print(f"no .ifc files in {args.dir}", file=sys.stderr)
        return 2
    results = {}
    for ifc in files:
        found, raised = run_rules(args.rules, args.python, ifc)
        results[ifc.stem] = found
        print(f"{ifc.stem}: {', '.join(sorted(found)) or 'clean'}"
              + (f"  (rule code raised: {', '.join(raised)})" if raised else ""))
    baseline = yaml.safe_load(args.baseline.read_text("utf-8")) or {}
    new, stale = compare(results, baseline)
    for line in new:
        print(f"NEW   {line}", file=sys.stderr)
    for line in stale:
        print(f"STALE {line}: fixed? remove it from {args.baseline.name}",
              file=sys.stderr)
    return 1 if new or stale else 0


if __name__ == "__main__":
    sys.exit(main())
