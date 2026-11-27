# One command to accept a file (C.11): design

Date: 2026-11-27. Roadmap row C.11. Builds on C.7 (schema and where-rules), C.8 (buildingSMART's normative rules in CI), C.12 (the alignment checks) and X.1 (the takeoff contract as IDS); closes X.8.

## Goal

A consumer accepting a file (a conformed.ai worker, the corpus build of M.12, a user before `est-bim takeoff`) runs one command that needs nothing beyond the package and its `ids` extra, and gets one machine-readable verdict. buildingSMART's normative rules are not run on the consumer's machine: they hold the family library to account in CI, where every family is built with its options, so a family cannot ship without having been held to them.

## What the code does today

- `est-bim validate IFC [--no-rules]` (`bimforge/bim/cli.py`, `_run_validate`) runs `gate.schema_issues` (attribute types, and the schema's where and global rules unless `--no-rules`), flags an `IfcEarthworksCut` that voids no host, prints element counts per class and exits 1 on any issue. No JSON, no versions.
- The build gate (`gate.run_post`) runs coded checks on a file it has just written. Some read only the file: `_ifc_spatial_chain_check` (storeys, the IFC4X3 facility tree, products reaching the site), `_ifc_formula_check` (M.3) and `_ifc_representation_type_check`; their `model` argument is unused. Others need the in-memory model (`_ifc_mesh_check`, `_ifc_alignment_check`, the exact sweep and revolution checks) and stay in the gate.
- `gate.alignment_issues` (C.12) reads only the file, and runs in the conformance suite.
- `bimforge/bim/contract/takeoff.ids` and `takeoff-coverage.ids` ship in the package; `bimforge[ids]` installs `ifctester`. Nothing in `est-bim` runs them (X.8).
- buildingSMART's `ifc-gherkin-rules` run only in CI (`bsi-rules` job, `scripts/bsi_rules.py`, `scripts/bsi_baseline.yaml`), from a checkout pinned in `.github/workflows/ci.yml` (commit `893f8275...`), on what `test_conformance.py` writes: every shipped example on IFC4X3 and IFC4, plus the 4D/5D, estimate, dxf2bim, federate and carried-forward outputs.
- The package registers 15 families. Four have no example and so are never built by the conformance suite or held to the normative rules: `approach-slab`, `headwall-926`, `pipe-supports`, `spillway`. The examples also leave options off (the 926 headwall's rack, which was built below its structure until 0.1.133, is one).

## 1. `est-bim validate`

```
est-bim validate model.ifc [--json out.json] [--ids extra.ids ...] [--no-rules]
```

One library function, `bimforge.bim.validate.validate(path, extra_ids=(), rules=True) -> dict`, which the command prints and writes; the corpus build and tests call the function.

### Sections

| Section | What it runs | Fails the file |
|---|---|---|
| `schema` | attribute types (`schema_issues(f, rules=False)`) | yes |
| `rules` | the schema's where and global rules (the rest of `schema_issues`); `not run` with `--no-rules` | yes |
| `alignment` | `gate.alignment_issues` (C.12) | yes |
| `structure` | the spatial tree and facility parts, products reaching the site, quantity formulas (M.3), representation types, an unhosted `IfcEarthworksCut` | yes |
| `takeoff` | `takeoff.ids`, and each `--ids` document | yes |
| `coverage` | `takeoff-coverage.ids` | no: advisory |

The `structure` checks are the gate's file-only checks, moved into `bimforge.bim.validate` as functions of an open file (`f`), with `gate` calling them from there so the build and `validate` hold a file to one code path. Each is a function returning findings, as today. A check that needs the model stays in the gate.

### The result

```json
{
  "contract": "bimforge-validate/1",
  "file": "model.ifc",
  "sha256": "...",
  "schema": "IFC4X3_ADD2",
  "verdict": "clean",
  "failing": 0,
  "versions": {"bimforge": "0.1.134", "ifcopenshell": "0.8.5", "ifctester": "0.8.5"},
  "sections": {
    "schema":    {"status": "pass", "findings": []},
    "takeoff":   {"status": "fail", "findings": [
       {"check": "takeoff.ids: Paid elements carry a quantity", "instance": "#412 IfcWall 'B3 stem 3'", "message": "..."}]},
    "coverage":  {"status": "advisory", "findings": [...]},
    "rules":     {"status": "not run", "reason": "--no-rules"}
  },
  "not_run": {
    "normative_rules": {
      "reason": "buildingSMART's ifc-gherkin-rules are run in CI on every family bimforge ships, not on this file",
      "rule_set": "buildingSMART/ifc-gherkin-rules@893f8275049b8960c3ce0c7379b4b57aefeaa8f9"
    }
  }
}
```

- A section's `status` is `pass`, `fail`, `advisory` (coverage, whatever it finds) or `not run` with a `reason`. Each finding is `{check, instance, message}`; `instance` is `#id Class 'Name'` where the finding names one, else omitted.
- `verdict` is `clean` only when every failing section ran and passed; `issues` when any failed; `incomplete` when none failed but a failing section did not run (no `ifctester`, or `--no-rules`). `failing` counts the findings in failing sections.
- Without `ifctester`, `takeoff` and `coverage` are `not run` with `reason: "pip install bimforge[ids]"`, and the verdict is `incomplete`, so a missing extra never reads as a pass.
- `rule_set` is read from `bimforge/bim/contract/bsi_rules.yaml` (`repository`, `ref`), which ships in the package; CI's `bsi-rules` job reads its checkout ref from the same file, so the report names the rules this release's families were held to.

### The command

- Stdout: one line per section (`takeoff: fail (3)`), the class counts as today, then the verdict. `--json PATH` writes the result; `--json -` prints it instead of the summary.
- Exit 0 when `clean`, 1 when `issues` or `incomplete`, 2 when the file cannot be opened or is not IFC (the result, when asked for, then carries `verdict: "unreadable"` and the error).
- `--no-rules` keeps its meaning (skip the where and global rules on very large files); the result says so.
- An `--ids` file that does not exist or does not parse is exit 2, naming it.

## 2. CI holds every family to the normative rules, with its options

- `bimforge/bim/tests/conformance_specs/` holds spec files the conformance suite builds besides the shipped examples: one or more per family with no example (`approach-slab`, `headwall-926`, `pipe-supports`, `spillway`), and variants that switch on what the examples leave off. The first set:
  - `headwall-926` with the rack and the guardrail; `approach-slab` on a B3-style alignment with a real base;
  - `pipe-supports` and `spillway` as their tests build them;
  - `concrete-barrier-842` with a `profile` ring (`modified-by-section`) and with a Mod dimension;
  - a B3 wall with a `terrain:` block on a stubbed ground (the conformance build stubs the 3DEP fetch as the terrain tests do).
  They use neutral round values and cite no bid, as the fixtures do.
- `test_conformance.py` builds them on IFC4X3 and IFC4 beside the examples, holds them to the same checks (now `validate`'s failing sections, so the suite and the command agree) and writes them to `BIMFORGE_CONFORMANCE_OUT`, so `bsi-rules` and the inventory see them. A variant that does not build on IFC4 (anything with an alignment sweep that IFC4 cannot write) says so in the spec (`conformance: {schemas: [IFC4X3_ADD2]}`) and is built on that schema only.
- A new test fails when a family the package registers is built by no example and no conformance spec, naming it.
- New findings the variants raise in `bsi-rules` are fixed in the family, or listed in `bsi_baseline.yaml` with the reason and a roadmap row, as C.8 requires; the baseline is not widened silently.
- `docs/ifc-inventory.*` is regenerated for what the variants add.

## 3. A new-family skill

`.claude/skills/new-family/SKILL.md` in this repository: the steps a family takes to ship, each with the file it touches and the check that proves it:

1. Register it (`FAMILIES`, the registry).
2. Type its elements from the family dictionary (X.4, M.1).
3. Build in the model frame: elevations through `to_model_elev`, plan points through `to_model`, a pob in survey coordinates (`check_pob_survey`).
4. Declare its facility and parts (`project.facility`, `spatial_parts`) by what it serves.
5. An example spec, or a conformance spec, and a conformance variant per option.
6. Pin its GlobalIds (`example_globalids.json`, for an example).
7. Regenerate the inventory.
8. Run `est-bim validate` on its output and the suite.

It records what review has had to catch (raw elevations, a part in the wrong container, an option never built), so the next family starts from it.

## Not changed

- The normative rules are not run by `validate`, and nothing downloads or installs them.
- The build gate's model checks, and what a build writes.
- The takeoff contract's documents.
- The profile's per-concept IDS documents remain C.9's next step; `--ids` takes them when they exist.
- M.12's corpus wiring: it needs only the exit code and the JSON.

## Testing

- `validate` on a shipped example: `clean`, every failing section `pass`, the versions and `rule_set` present; the JSON matches the contract.
- Each section fails on a file broken for it: a wrong attribute type, a broken where-rule (`IfcWall.CorrectPredefinedType`), an alignment ending with a non-zero segment, a storey with no building, a formula that does not hold, a paid element with no quantity (takeoff); a coverage finding leaves the verdict `clean`.
- Without `ifctester` (patched import), `takeoff` and `coverage` are `not run` and the verdict is `incomplete`, exit 1.
- `--no-rules`: `rules` is `not run`, verdict `incomplete`. An unreadable file is exit 2.
- `--ids` adds a document's specifications to `takeoff`.
- The gate and `validate` give the same findings for the moved checks (the gate's existing tests keep passing through the moved functions).
- Every registered family is built by an example or a conformance spec; the variants build and pass on the schemas they name; `bsi-rules` and the inventory check pass in CI.
- CI's `bsi-rules` checkout ref is the one in `bsi_rules.yaml`.
