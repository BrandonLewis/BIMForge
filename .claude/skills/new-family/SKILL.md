---
name: new-family
description: Use when adding a structure family to bimforge (a new entry in the shipped families), or a new option to an existing family - the steps a family takes to ship, each with the check that proves it
---

# Adding a family

A family ships when every step below is done and its check passes. Each step
is one that review has had to catch.

1. **Register it.** Its module exports `build`, and
   `_shipped()` in `bimforge/author/families/registry.py` maps the family's
   name to it. Check: `available()` lists it.
2. **Type its elements from the family dictionary** (X.4, M.1):
   `Element.type_name`, the class reference, `Pset_*Common.Reference`, each
   class declared in `bimforge/author/dictionary/bimforge-families.bsdd.json`.
   Check: `bimforge/author/tests/test_dictionary.py`, and `est-bim validate`'s
   `takeoff` section (`takeoff.ids`) passes on its output.
3. **Build in the model frame.** Elevations through
   `to_model_elev(ctx, elev)` (model z = elevation - `project.base`'s
   elevation); plan points through `to_model(ctx, n, e)` (x east, y north),
   both in `bimforge/author/sweep.py`; an alignment `pob` in survey (State
   Plane) coordinates, checked with `alignment.check_pob_survey`. Check: a
   test with a real base, its elevation not 0, puts the structure where the
   elevations say.
4. **Declare its facility by what it serves.** `project.facility` (IfcBridge,
   IfcRoad, IfcFacility) and `spatial_parts` rules for each element; never a
   building storey for a structure that has none. Check:
   `bimforge/author/tests/test_example_facilities.py` pins which element
   lands in which part.
5. **Give it a spec CI builds.** An example under
   `bimforge/author/examples/`, or a spec under
   `bimforge/bim/tests/conformance_specs/`, and one conformance spec per
   option the example leaves off. A spec IFC4 cannot write says
   `conformance: {schemas: [IFC4X3_ADD2]}`. Check:
   `test_every_shipped_family_is_built_by_the_suite`, and
   `test_every_spec_builds_conformant` builds it on both schemas (or the one
   it names) to verdict `clean`
   (`bimforge/bim/tests/test_conformance.py`).
6. **Pin its GlobalIds** (an example only): re-record
   `bimforge/author/tests/fixtures/example_globalids.json` for it. Check:
   `bimforge/author/tests/test_example_globalids.py`.
7. **Regenerate the inventory:** run the conformance suite with
   `BIMFORGE_CONFORMANCE_OUT=DIR` set (a folder outside the repo), then
   `python scripts/ifc_inventory.py DIR`. Check:
   `python scripts/ifc_inventory.py DIR --check` prints `inventory current`.
8. **Validate its output and run the suite.** `est-bim validate out/x.ifc`
   prints `verdict: clean` (exit 0; `issues` or `incomplete` exit 1); the
   full test suite passes; CI's `bsi-rules` job, which runs buildingSMART's
   normative rules at the ref pinned in `bimforge/bim/contract/bsi_rules.yaml`,
   passes on the PR. A new finding there is fixed in the family, or listed
   in `scripts/bsi_baseline.yaml` with the reason and a roadmap row.

Fixtures use neutral round values and cite public sources; no bid numbers or
machine paths (`python scripts/deorg_scan.py` stays clean).
