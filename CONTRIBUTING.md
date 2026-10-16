# Contributing to bimforge

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[all,terrain]' pytest
python -m pytest bimforge -q
```

Tests live next to the code (`bimforge/<subpackage>/tests/`). The suite must
pass **without** `estimating_tools` installed — CI asserts it is absent. If a
test needs the estimating layer, it belongs in that repository, not here.

The production-catalog tests read the Caltrans tables in
`data/caltrans-2025/tables/` (see the README there); they skip when the
directory is missing.

## Rules the CI gate enforces

- **Fixture provenance.** A fixture cites a public source or derives its
  quantities in-repo. Never an employer bid number, a project working
  directory, or a person's attribution. `scripts/deorg_scan.py` refuses bid
  numbers (`B2xxx`), machine paths and credential-shaped strings on every
  tracked file; the maintainer adds project-specific tokens through the
  `DEORG_EXTRA_PATTERNS` repository secret.
- **No secrets, ever,** including in history — gitleaks runs over the full
  history on every push.
- **Dependencies audited** — pip-audit runs against the resolved `[all]` set.
- **The wheel installs clean** and every CLI responds, in a fresh venv.

## Quantities come from geometry

Any family or primitive that reports a quantity takes it from the emitted
solid's faces (`face_volume`, mesh area), never from a parallel hand formula.
A test that checks a quantity compares the declared Qto against the geometry.

## Style packs

CAD styling resolves explicit argument → registered providers → built-in
defaults. A provider is an entry point in the `bimforge.style_packs` group:
a zero-argument callable returning a pack spec (package name or directory) or
`None`. bimforge never imports a provider's package by name.

## Where development happens

bimforge grew up inside a construction-estimating monorepo and is, for now,
exported from it: this repository's tree is produced by that repo's
`scripts/export_bimforge.py`. Pull requests here are welcome and are ported
back; once the estimating layer depends on the PyPI release instead of a
bundled wheel, development moves here outright.

## Releasing

1. Bump `version` in `pyproject.toml` and add the changelog entry.
2. Tag `vX.Y.Z` (the release workflow refuses a tag that does not equal the
   committed version), push the tag.
3. `release.yml` tests, builds the sdist and wheel, publishes to PyPI through
   **trusted publishing** (configured on PyPI for this repository, workflow
   `release.yml`, environment `pypi` — no API token is stored), and creates
   the GitHub release.

Security reports: see `SECURITY.md`.
