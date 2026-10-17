"""CLI for the DXF -> BIM -> takeoff pipeline:

  est-bim sample  [--dir out] [--with-configs]
  est-bim dxf2bim --dxf plans.dxf --config layer_map.yaml --out model.ifc
  est-bim validate model.ifc
  est-bim ifc2dxf --ifc model.ifc [--out model.plan.dxf] [--include IfcSlab,IfcFooting] [--exclude IfcRailing] [--simplify-ft 0.05]
  est-bim ifc2gis --ifc model.ifc [model2.ifc ...] [--out model.gpkg] [--index structures.ifc] [--tin]
  est-bim takeoff --ifc model.ifc [--map takeoff_map.yaml] [--out takeoff.json] [--csv takeoff.csv]
  est-bim schedule-read --ifc model.4d.ifc [--schedule NAME] --out schedule.json [--takeoff-map map.yaml --takeoff-out takeoff.json] [--costs-out costs.json]
  est-bim sfca    model.ifc [--flat 0.85] [--split-el EL] [--skip-class IfcPipeSegment,...]
  est-bim model-elements model.ifc [--items items.json] [--estimate-id N] [--complete] [--structure-id ID] [--structure-ids ids.json] [--form-area Qto_Set.Name] [--schedule LABEL] [--all-elements] [--out upsert.json]
  est-bim estimate-model model.ifc estimate_model.json out.ifc [--schedule-name NAME] [--placeholders]
  est-bim kml     model.ifc [--out model.kml]
  est-bim kmz     model.ifc [--out model.kmz] [--geoid-shift-m M] [--omit RE] [--massing] [--collada | --gltf]
  est-bim build   spec.yaml [--check-only]

and the PDF plan-sheet measurement path (vector PDFs are plotted from CAD —
the paths ARE the geometry):

  est-bim calibrate --pdf plans.pdf --sheet 13 [--zone n:x0,y0,x1,y1] [--render sheet.png --dpi 150] [--hints hints.yaml] [--evidence report.json] [--ft-per-pt F | --scale "1/4in=1ft"] [--alignment a.yaml] [--out calib.yaml]
  est-bim vectors   --pdf plans.pdf --sheet 13 --calib calib.yaml --out vectors.dxf [--classes classes.yaml] [--regions] [--regions-json regions.json]
  est-bim measure   --pdf plans.pdf --sheet 13 --calib calib.yaml --traces traces.json --layer-map layer_map.yaml --out takeoff.dxf [--sidecar prov.json] [--hints hints.yaml] [--report qc.md]

and the terrain source path (plan-sheet contours -> TIN -> QA vs 3DEP):

  est-bim contours        --pdf plans.pdf --sheet 28 [--profile] [--calib calib.yaml] [--tie PX,PY=N,E ... [--tie-model affine] [--crs-epsg N]] [--viewport N] [--geopdf-bbox page] [--no-geopdf] [--clip x0,y0,x1,y1] --layer 'EXIST=0.753@0.72|EXIST=ocg:GLOB' ... [--surface NAME=existing] [--role NAME=index] [--max-residual-ft F] [--out contours.dxf] [--json contours.json]
  est-bim contour-surface --contours contours.json ... --anchors anchors.yaml [--spots spots.yaml] [--propagate --interval 1] [--surface existing|proposed] [--include-review] --out tin.npz [--dxf surface.dxf] [--report surface.md] [--max-rmse 1.0] [--contact-ft 0.5] [--strict] [--spot-pins] [--review-dir DIR [--pdf plans.pdf]]
  est-bim terrain-diff    --surface surface.xyz|tin.npz (--grid grid.npz [--vshift-json vshift.json] [--units ftUS] | --against other.npz [--step 5] [--tie-tol 0.5] [--zones zones.yaml] [--report r.md]) [--csv diff.csv] [--png diff.png]
  est-bim label-crops     --contours contours.json --pdf plans.pdf --sheet 94 [--sources mask,gap] [--labels 'ocg:GLOB'] [--spots 'ocg:GLOB'] [--dpi 300] --out-dir crops/ --anchors anchors.skeleton.yaml

Calibration auto-accepts only when >=2 independent evidence source types
agree within 0.5% (ticks / grids / scale bars / live text dims / vision
hints); otherwise it exits 2 with a machine-readable evidence report so the
operating agent knows what hint to supply.

Requires the `bim` extra (ezdxf, shapely, ifcopenshell, numpy, pyproj, pymupdf).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

EXAMPLES = ("layer_map.example.yaml", "takeoff_map.example.yaml")


def _copy_examples(dest_dir: str) -> list[str]:
    """Copy the shipped example maps next to the sample DXF; return the paths."""
    from importlib.resources import files

    written = []
    for name in EXAMPLES:
        text = (files("bimforge.bim") / "examples" / name).read_text(encoding="utf-8")
        path = os.path.join(dest_dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        written.append(path)
    return written


def _run_sample(args) -> int:
    from bimforge.bim.sample import write_sample_dxf

    os.makedirs(args.dir, exist_ok=True)
    path = write_sample_dxf(os.path.join(args.dir, args.name))
    print(f"wrote {path}")
    if args.with_configs:
        for p in _copy_examples(args.dir):
            print(f"wrote {p}")
    return 0


def _run_dxf2bim(args) -> int:
    import yaml

    from bimforge.bim.dxf2bim import UNIT_TO_M, build_ifc, extract_features

    try:
        with open(args.config, encoding="utf-8") as fh:
            config = yaml.safe_load(fh) or {}
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    unit = config.get("units", {}).get("dxf_length_unit", "mm")
    scale = UNIT_TO_M.get(unit)
    if scale is None:
        print(f"error: unknown dxf_length_unit '{unit}' (use one of {list(UNIT_TO_M)})",
              file=sys.stderr)
        return 1

    print(f"Reading {args.dxf} (units: {unit}) ...")
    features = extract_features(args.dxf, config.get("layers", {}), scale)
    print(f"Extracted {len(features)} features across "
          f"{len({f.layer for f in features})} layers.")
    print(build_ifc(features, config, args.out))
    return 0


def _run_ifc2dxf(args) -> int:
    from bimforge.bim.ifc2dxf import ifc_to_dxf, write_sidecar

    def _split(csv):
        return [s.strip() for s in csv.split(",") if s.strip()] if csv else None

    try:
        res = ifc_to_dxf(args.ifc, args.out, include=_split(args.include),
                         exclude=_split(args.exclude),
                         simplify_ft=args.simplify_ft)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    sidecar = args.sidecar or (res.out + ".sidecar.json")
    write_sidecar(res, args.ifc, sidecar)
    g = res.georef
    where = (f"EPSG:{g['epsg']} coordinates ({g['unit']})"
             if g["status"] == "crs"
             else "UNGEOREFERENCED — local model coordinates in feet")
    print(f"wrote {res.out} ({res.elements} elements, "
          f"{len(res.skipped)} skipped) — {where}")
    print(f"sidecar: {sidecar}")
    for row in res.skipped:
        print(f"  skipped {row['ifc_class']} {row['global_id']}: "
              f"{row['reason']}", file=sys.stderr)
    print("\nNext: write a layer_map.yaml against the IFCCLASS[-TYPE] layers "
          "(heights from the sidecar z-ranges), then run est-bim dxf2bim / "
          "the measurement path off this DXF.")
    return 0


def _run_ifc2gis(args) -> int:
    from bimforge.bim.ifc2gis import ifc_to_gpkg

    ifcs = args.ifc
    out = args.out or (Path(ifcs[0]).with_suffix(".gpkg") if len(ifcs) == 1
                       else "model.gpkg")
    try:
        res = ifc_to_gpkg(ifcs, out, index_path=args.index,
                          index_pset=args.index_pset, tin=args.tin)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.index:
        print(f"index: {res.index_matched} features joined to {args.index}",
              file=sys.stderr)
    print(f"wrote {res.out} — {res.features} features in {len(res.layers)} layers "
          f"({res.solid_type} solids):")
    for l in res.layers:
        print(f"  {l['name']}: {l['features']} {l['geom_type']} (EPSG:{l['epsg']})")
    if res.skipped:
        print(f"skipped {len(res.skipped)} product(s) with unconvertible geometry:",
              file=sys.stderr)
        for row in res.skipped:
            print(f"  {row['ifc_class']} {row['global_id']}: {row['reason']}",
                  file=sys.stderr)
    print("\nNext: open the .gpkg in QGIS (drag it in, pick layers), set the "
          "project CRS to match, and use View > 3D Map Views to see the Z.")
    return 0


def _run_validate(args) -> int:
    """Open + schema-validate an IFC and report element counts per class.

    The dxf-to-bim SKILL's step-4 verification as a command: surface what
    the model actually contains so nothing is silently dropped.
    """
    from collections import Counter

    import ifcopenshell
    import ifcopenshell.validate as V

    if not os.path.isfile(args.ifc):
        print(f"error: no such file: {args.ifc}", file=sys.stderr)
        return 1
    try:
        model = ifcopenshell.open(args.ifc)
    except (OSError, ValueError, RuntimeError, ifcopenshell.Error) as exc:
        print(f"error: cannot open {args.ifc}: {exc}", file=sys.stderr)
        return 1

    logger = V.json_logger()
    V.validate(model, logger)
    issues = list(logger.statements)

    counts = Counter(e.is_a() for e in model.by_type("IfcElement"))
    width = max(len("CLASS"), len("TOTAL"), *(len(c) for c in counts)) \
        if counts else len("CLASS")
    print(f"{'CLASS':<{width}}  COUNT")
    for cls in sorted(counts):
        print(f"{cls:<{width}}  {counts[cls]:>5}")
    print(f"{'TOTAL':<{width}}  {sum(counts.values()):>5}")
    print(f"schema issues: {len(issues)}")
    if not counts:
        print("warning: model contains no IfcElement", file=sys.stderr)
    if issues:
        for stmt in issues[:20]:
            msg = stmt.get("message", stmt) if isinstance(stmt, dict) else stmt
            print(f"  ! {msg}", file=sys.stderr)
        if len(issues) > 20:
            print(f"  ... {len(issues) - 20} more", file=sys.stderr)
        return 1
    return 0


def _run_takeoff(args) -> int:
    import yaml

    from bimforge.bim.ifc_takeoff import (
        build_takeoff, print_summary, print_warnings, write_csv,
    )

    try:
        tmap = {}
        if args.map:
            with open(args.map, encoding="utf-8") as fh:
                tmap = yaml.safe_load(fh) or {}
        takeoff, warnings = build_takeoff(args.ifc, tmap)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(takeoff, fh, indent=2)
    print_summary(takeoff)
    if args.csv:
        write_csv(takeoff, args.csv)
        print(f"CSV written to {args.csv}")
    print(f"CanonicalTakeoff written to {args.out}")
    print_warnings(warnings)
    print("\nNext: hand this JSON to the estimating-core push-takeoff skill "
          "(or `est-takeoff plan` for a dry-run push plan).")
    return 0


def _run_sfca(args) -> int:
    """Per-element face classification: volume + top/bottom/side (SFCA) SF.

    Reads the IFC through the shared iterator reader (SI metres), converts
    to feet with the package's M_TO_FT convention, and classifies each
    element's tessellated boundary. --split-el (feet, model frame) flags the
    buried SUBSET of side — cast-against-earth prices differently.
    """
    from bimforge.bim.ifc_mesh import classify_faces, element_meshes
    from bimforge.bim.ifc_takeoff import M_TO_FT

    skip = [s.strip() for s in args.skip_class.split(",") if s.strip()]
    try:
        elems = element_meshes(args.ifc, skip_classes=skip)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not elems:
        print("error: no tessellatable elements (after --skip-class filter)",
              file=sys.stderr)
        return 1

    keys = ["volume_cf", "top_sf", "bottom_sf", "side_sf"]
    cols = ["VOL CF", "TOP SF", "BOTTOM SF", "SIDE SF"]
    if args.split_el is not None:
        keys.append("buried_sf")
        cols.append("BURIED SF")
    rows, totals = [], dict.fromkeys(keys, 0.0)
    for _gid, name, ifc_class, verts, faces in elems:
        r = classify_faces(verts * M_TO_FT, faces, flat=args.flat,
                           split_el=args.split_el)
        rows.append((name, ifc_class, r))
        for k in keys:
            totals[k] += r[k]

    name_w = max(len("ELEMENT"), len("TOTAL"),
                 *(len(n) for n, _, _ in rows))
    cls_w = max(len("CLASS"), *(len(c) for _, c, _ in rows))
    print(f"{'ELEMENT':<{name_w}}  {'CLASS':<{cls_w}}"
          + "".join(f"{c:>12}" for c in cols))
    for name, ifc_class, r in rows:
        print(f"{name:<{name_w}}  {ifc_class:<{cls_w}}"
              + "".join(f"{r[k]:>12,.1f}" for k in keys))
    print(f"{'TOTAL':<{name_w}}  {'':<{cls_w}}"
          + "".join(f"{totals[k]:>12,.1f}" for k in keys))
    return 0


def _run_schedule(args) -> int:
    import json as _json
    from pathlib import Path

    import ifcopenshell

    from bimforge.bim.schedule4d import embed_schedule
    from bimforge.bim.schedule_io import load_schedule
    from bimforge.bim.schedule_model import resolve_bid_item_codes

    try:
        sched = load_schedule(args.schedule)
        task_map = {}
        if args.task_map:
            task_map = _json.loads(Path(args.task_map).read_text(encoding="utf-8"))
            if not isinstance(task_map, dict):
                raise ValueError("--task-map must be a JSON object "
                                 "{task id|wbs: [codes]}")
        report_map = resolve_bid_item_codes(
            sched, task_map=task_map, name_code_re=args.name_code_re)
        model = ifcopenshell.open(args.ifc)
        report = embed_schedule(model, sched,
                                schedule_name=args.schedule_name)
    except (OSError, ValueError, ifcopenshell.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    out = args.out or str(Path(args.ifc).with_suffix(".4d.ifc"))
    model.write(out)
    print(f"Embedded schedule '{report.schedule_name}': {report.tasks} tasks "
          f"({report.tasks_timed} dated), {report.sequences} dependencies, "
          f"{report.assigned_elements} elements assigned across "
          f"{report.assignments} links.")
    print(f"4D IFC written to {out}")
    # both-ways gaps, on stderr like the takeoff QC warnings
    if report_map.unmapped:
        print(f"\nReview: {len(report_map.unmapped)} leaf task(s) mapped to no "
              f"bid item code (add --task-map / --name-code-re entries):",
              file=sys.stderr)
        for tid in report_map.unmapped[:20]:
            print(f"  ! task {tid}", file=sys.stderr)
    if report.codes_without_elements:
        print(f"\nReview: {len(report.codes_without_elements)} task code(s) "
              f"match no element in the IFC:", file=sys.stderr)
        for code in report.codes_without_elements:
            print(f"  ! code {code}", file=sys.stderr)
    if report.selectors_without_elements:
        print(f"\nReview: {len(report.selectors_without_elements)} task "
              f"selector(s) match no element in the IFC:", file=sys.stderr)
        for sel in report.selectors_without_elements:
            print(f"  ! {sel}", file=sys.stderr)
    if report.unscheduled_elements:
        print(f"\nReview: {report.unscheduled_element_count} "
              f"element(s) claimed by no task:", file=sys.stderr)
        for nm in report.unscheduled_elements[:20]:
            print(f"  ! {nm}", file=sys.stderr)
    print("\nNext: open the 4D IFC in Bonsai to animate the staging, or "
          "`est-bim kmz --schedule` (slice 3) for the Google Earth time slider.")
    return 0


def _run_schedule_read(args) -> int:
    from pathlib import Path

    import ifcopenshell
    import yaml

    from bimforge.bim.ifc_takeoff import print_warnings, takeoff_by_task
    from bimforge.bim.schedule_read import (read_costs, read_schedule,
                                            task_elements)

    if bool(args.takeoff_map) != bool(args.takeoff_out):
        print("est-bim schedule-read: --takeoff-map and --takeoff-out go "
              "together", file=sys.stderr)
        return 2
    try:
        model = ifcopenshell.open(args.ifc)
        sched = read_schedule(model, args.schedule_name)
        links = task_elements(model, sched.name)
        takeoff = warnings = costs = None
        if args.costs_out:
            costs = read_costs(model, sched.name)
        if args.takeoff_map:
            with open(args.takeoff_map, encoding="utf-8") as fh:
                tmap = yaml.safe_load(fh) or {}
            if not isinstance(tmap, dict):
                raise ValueError("--takeoff-map must be a YAML mapping")
            takeoff, warnings = takeoff_by_task(args.ifc, tmap, schedule=sched)
    except (OSError, ValueError, ifcopenshell.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    Path(args.out).write_text(sched.to_json() + "\n", encoding="utf-8")
    deps = sum(len(t.dependencies) for t in sched.tasks)
    linked = sum(bool(v) for v in links.values())
    print(f"Read schedule '{sched.name}': {len(sched.tasks)} tasks, {deps} "
          f"dependencies, {len(sched.calendars)} task calendar(s); "
          f"{linked} task(s) linked to "
          f"{len({l['global_id'] for v in links.values() for l in v})} "  # noqa: E741
          f"element(s).")
    print(f"CanonicalSchedule written to {args.out}")
    if takeoff is not None:
        Path(args.takeoff_out).write_text(json.dumps(takeoff, indent=2) + "\n",
                                          encoding="utf-8")
        open_rows = [r for r in takeoff["rows"] if r["unassigned"]]
        print(f"Takeoff by task written to {args.takeoff_out} "
              f"({len(takeoff['rows'])} rows, {len(open_rows)} with "
              f"quantity no task claims).")
        print_warnings(warnings)
    if costs is not None:
        Path(args.costs_out).write_text(json.dumps(costs, indent=2) + "\n",
                                        encoding="utf-8")
        total = sum(r["cost"] for r in costs["costs"].values())
        hours = sum(r["labor_hours"] or 0.0 for r in costs["costs"].values())
        print(f"Costs written to {args.costs_out} ({len(costs['costs'])} "
              f"code(s) over {len(costs['tasks'])} task(s), ${total:,.0f}, "
              f"{hours:,.0f} labor hr).")
        print_warnings(costs["warnings"])
    return 0


def _run_cost5d(args) -> int:
    import json as _json
    from pathlib import Path

    import ifcopenshell

    from bimforge.bim.cost5d import embed_cost_and_resources
    from bimforge.bim.costload import validate_costs
    from bimforge.bim.schedule_io import load_schedule
    from bimforge.bim.schedule_model import resolve_bid_item_codes

    try:
        sched = load_schedule(args.schedule)
        task_map = {}
        if args.task_map:
            task_map = _json.loads(Path(args.task_map).read_text(encoding="utf-8"))
            if not isinstance(task_map, dict):
                raise ValueError("--task-map must be a JSON object")
        resolve_bid_item_codes(sched, task_map=task_map,
                               name_code_re=args.name_code_re)
        costs = _json.loads(Path(args.costs).read_text(encoding="utf-8"))
        validate_costs(costs)
        model = ifcopenshell.open(args.ifc)
        report = embed_cost_and_resources(
            model, sched, costs, schedule_name=args.schedule_name,
            work_hours_per_day=args.work_hours_per_day)
    except (OSError, ValueError, ifcopenshell.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    out = args.out or str(Path(args.ifc).with_suffix(".5d.ifc"))
    model.write(out)
    print(f"Embedded 5D '{report.schedule_name}': {report.cost_items} cost "
          f"items (${report.total_cost:,.0f}), {report.resources} labor "
          f"resources ({report.total_labor_hours:,.0f} hr).")
    print(f"5D IFC written to {out}")
    if report.tasks_without_entity:
        print(f"\nReview: {len(report.tasks_without_entity)} loaded task(s) had "
              f"no matching IfcTask (is this the 4D IFC?):", file=sys.stderr)
        for tid in report.tasks_without_entity:
            print(f"  ! task {tid}", file=sys.stderr)
    return 0


def _run_estimate5d(args) -> int:
    import json as _json
    from pathlib import Path

    import ifcopenshell
    import yaml

    from bimforge.bim.costload import validate_costs
    from bimforge.bim.estimate5d import embed_estimate

    try:
        with open(args.map, encoding="utf-8") as fh:
            tmap = yaml.safe_load(fh) or {}
        if not isinstance(tmap, dict):
            raise ValueError("--map must be a YAML mapping (the takeoff map)")
        costs = _json.loads(Path(args.costs).read_text(encoding="utf-8"))
        validate_costs(costs)
        model = ifcopenshell.open(args.ifc)
        report = embed_estimate(model, tmap, costs, schedule_name=args.name)
    except (OSError, ValueError, ifcopenshell.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    out = args.out or str(Path(args.ifc).with_suffix(".est.ifc"))
    model.write(out)
    print(f"Embedded ESTIMATE '{report.schedule_name}': {report.parents} bid "
          f"item(s), {report.children} element child(ren), extended "
          f"${report.extended_total:,.0f}.")
    print(f"estimate IFC written to {out}")
    for code, v in sorted(report.by_code.items()):
        if v["variance_pct"] is None:
            print(f"  {code}: extended ${v['extended']:,.0f} "
                  f"(no BM cost to compare)")
        else:
            print(f"  {code}: extended ${v['extended']:,.0f} vs BM "
                  f"${v['bm_cost']:,.0f} ({v['variance_pct']:+.1f}%)")
    for label, entries in (
            ("no unit_price — skipped", report.codes_without_rate),
            ("no explicit measure — skipped", report.codes_without_measure),
            ("no classified elements", report.codes_without_elements)):
        for code in entries:
            print(f"  ! code {code}: {label}", file=sys.stderr)
    for el, code, measure in report.elements_missing_measure:
        print(f"  ! element '{el}' (code {code}) lacks {measure} — skipped",
              file=sys.stderr)
    return 0


def _run_model_elements(args) -> int:
    """IFC elements -> the BidSheet.ai upsert_modelled_elements payload."""
    from pathlib import Path

    import ifcopenshell

    from bimforge.bim.model_elements import plan_modelled_elements

    try:
        items = (json.loads(Path(args.items).read_text(encoding="utf-8"))
                 if args.items else None)
        structure_ids = (json.loads(Path(args.structure_ids).read_text(
            encoding="utf-8")) if args.structure_ids else None)
        if structure_ids is not None and not isinstance(structure_ids, dict):
            raise ValueError("--structure-ids must be a JSON object "
                             "{code: structure id}")
        plan = plan_modelled_elements(
            args.ifc, items, structure_id=args.structure_id,
            structure_ids=structure_ids, form_area=args.form_area,
            all_elements=args.all_elements, schedule=args.schedule)
    except (OSError, ValueError, KeyError, ifcopenshell.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    payload = {}
    if args.estimate_id is not None:
        payload["estimate_id"] = args.estimate_id
    payload["complete"] = bool(args.complete)
    payload.update(plan)
    text = json.dumps(payload, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    else:
        print(text)
    print(f"{len(plan['elements'])} element(s) planned, "
          f"{len(plan['skipped'])} skipped, "
          f"{len(plan['without_quantities'])} with no quantities"
          + (f"; written to {args.out}" if args.out else ""), file=sys.stderr)
    for s_ in plan["skipped"]:
        print(f"  - skipped {s_['name']} ({s_['ifc_class']}): {s_['reason']}",
              file=sys.stderr)
    for w in plan["warnings"]:
        print(f"  ! {w}", file=sys.stderr)
    return 0


def _run_estimate_model(args) -> int:
    """Embed a get_estimate_model document into an IFC."""
    from pathlib import Path

    import ifcopenshell

    from bimforge.bim.estimate_model5d import embed_estimate_model

    try:
        model_json = json.loads(Path(args.model).read_text(encoding="utf-8"))
        if not isinstance(model_json, dict) or "items" not in model_json:
            raise ValueError("the model JSON must be a get_estimate_model "
                             "document (estimate, items, elements, "
                             "activities, shares)")
        summary = embed_estimate_model(
            args.ifc, model_json, args.out, schedule_name=args.schedule_name,
            placeholders=args.placeholders)
    except (OSError, ValueError, KeyError, ifcopenshell.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2))
    print(f"Embedded '{summary['schedule_name']}': {summary['tasks']} task(s), "
          f"{summary['cost_items']} item(s) / {summary['share_items']} share "
          f"cost item(s) (${float(summary['allocated_total']):,.2f}), "
          f"{summary['labor_resources']} crew(s); written to {args.out}",
          file=sys.stderr)
    if summary["unmatched_elements"]:
        print(f"  ! {len(summary['unmatched_elements'])} model element(s) "
              f"are not in the IFC (see unmatched_elements)", file=sys.stderr)
    for w in summary["warnings"]:
        print(f"  ! {w}", file=sys.stderr)
    return 0


def _run_kml(args) -> int:
    import ifcopenshell

    from bimforge.bim.kml import ifc_to_kml

    try:
        info = ifc_to_kml(args.ifc, args.out, schedule=args.schedule,
                          massing=args.massing,
                          vshift_m=args.geoid_shift_m)
    except (OSError, ValueError, ifcopenshell.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {info['out']} ({info['elements']} elements, {info['groups']} groups)")
    # Say what was applied: a wrong datum is otherwise invisible until someone
    # opens Google Earth and finds the model underground (issue #134).
    geoid = f", geoid {args.geoid_shift_m:+.3f} m" \
        if args.geoid_shift_m is not None else ""
    print(f"altitude shift {info['vshift_m']:+.3f} m (datum "
          f"{info['datum_height_m']:+.3f} m from OrthogonalHeight{geoid})")
    if args.geoid_shift_m is None:
        print("note: no geoid separation applied — Google Earth reads "
              "absolute altitude above EGM96 while a US plan-set model is "
              "NAVD88, so altitudes are off by the local separation "
              "(decimetres). Derive it with terrain.datum.geoid_shift_m and "
              "pass --geoid-shift-m.", file=sys.stderr)
    if args.schedule:
        if info["timed"]:
            print(f"{info['timed']} element(s) carry a construction TimeSpan — "
                  "open in Google Earth and use the time slider to play the staging.")
        else:
            print("no scheduled elements found: embed a schedule first with "
                  "`est-bim schedule` (the IFC carries no IfcWorkSchedule "
                  "assignments).", file=sys.stderr)
    return 0


def _run_kmz(args) -> int:
    import ifcopenshell

    from bimforge.bim.kmz import ifc_to_kmz, ifc_to_web_kmz

    web = not (args.gltf or args.collada)
    try:
        if web:
            info = ifc_to_web_kmz(args.ifc, args.out, massing=args.massing,
                                  vshift_m=args.geoid_shift_m, omit=args.omit)
            out = info["out"]
        else:
            out = ifc_to_kmz(args.ifc, args.out, gltf=args.gltf,
                             collada=args.collada, massing=args.massing,
                             vshift_m=args.geoid_shift_m, omit=args.omit)
    except (OSError, ValueError, ifcopenshell.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {out}")
    if args.gltf:
        print("glTF escape hatch: no KMZ written — load the .glb in Cesium.")
    elif args.collada:
        print("COLLADA <Model> KMZ: opens in Google Earth Pro only (Earth web "
              "reports 'Unsupported element: Model').")
    else:
        print(f"{info['placemarks']} placemarks, {info['vertices']:,} vertices"
              f" ({info['degenerate_dropped']} degenerate triangles dropped"
              f"{', omitted ' + ', '.join(info['omitted']) if info['omitted'] else ''})")
        print(f"altitude shift {info['vshift_m']:+.3f} m (datum "
              f"{info['datum_height_m']:+.3f} m from OrthogonalHeight"
              f"{f', geoid {args.geoid_shift_m:+.3f} m' if args.geoid_shift_m is not None else ''})")
        print("Open it in Google Earth (web: Projects > New > Import KML file).")
    if args.geoid_shift_m is None and not args.gltf:
        print("note: no geoid separation applied — pass --geoid-shift-m "
              "(see `est-bim kml --help`).", file=sys.stderr)
    return 0


def _parse_zone_arg(spec: str):
    """--zone name:x0,y0,x1,y1 (unrotated page points) -> (name, bbox)."""
    name, sep, rest = spec.partition(":")
    parts = rest.split(",") if sep else []
    if not name or len(parts) != 4:
        raise ValueError(f"bad --zone {spec!r} (expected name:x0,y0,x1,y1)")
    x0, y0, x1, y1 = (float(p) for p in parts)
    return name, (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _render_page(pdf: str, sheet: int, out_png: str, dpi: int) -> None:
    import fitz

    doc = fitz.open(pdf)
    try:
        page = doc[sheet - 1]
        pix = page.get_pixmap(dpi=dpi)
        pix.save(out_png)
        print(f"wrote {out_png} ({pix.width}x{pix.height} px at {dpi} dpi; "
              f"1 px = {72.0 / dpi:.6f} pt — hint near_pt = pixel * that, "
              "visual frame)")
    finally:
        doc.close()


def _run_calibrate(args) -> int:
    import yaml

    from bimforge.bim.plansheet.calibrate import (
        CalibrationInsufficient, build_calibration, save_calibration,
    )
    from bimforge.bim.plansheet.hints import load_hints
    from bimforge.bim.plansheet.vectors import extract_sheet

    def _write_evidence(reports) -> None:
        payload = {"pdf": args.pdf, "sheet": args.sheet, "zones": reports}
        text = json.dumps(payload, indent=2)
        if args.evidence:
            with open(args.evidence, "w", encoding="utf-8") as fh:
                fh.write(text)
            print(f"wrote {args.evidence}")
        return text

    try:
        if args.render:
            _render_page(args.pdf, args.sheet, args.render, args.dpi)
        zones = [_parse_zone_arg(z) for z in (args.zone or [])]
        alignment = None
        if args.alignment:
            with open(args.alignment, encoding="utf-8") as fh:
                alignment = yaml.safe_load(fh)
        sv = extract_sheet(args.pdf, args.sheet - 1, min_path_pt=args.min_path_pt)
        hints = load_hints(args.hints, sv) if args.hints else None
        calib = build_calibration(sv, args.sheet, zones=zones or None,
                                  ft_per_pt=args.ft_per_pt, scale=args.scale,
                                  alignment=alignment, hints=hints)
    except CalibrationInsufficient as exc:
        text = _write_evidence(exc.reports)
        print(f"error: {exc}", file=sys.stderr)
        print(text)                       # machine-readable evidence report
        return 2
    except (OSError, ValueError) as exc:   # CalibrationError is a ValueError
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"sheet {calib.sheet} (page index {calib.page_index}, "
          f"/Rotate {sv.rotation}): {len(sv.segments)} segments, "
          f"{len(sv.texts)} text spans")
    for z in calib.zones:
        res = "n/a" if z.residual_ft is None else f"{z.residual_ft:.3f} ft"
        print(f"  zone {z.name}: method={z.method}  ft_per_pt={z.ft_per_pt:.6f}  "
              f"rotation={z.rotation_deg} deg  residual={res}")
        if z.evidence:
            print(f"    evidence: {z.evidence}")
    for w in calib.warnings:
        print(f"  WARNING: {w}", file=sys.stderr)
    if calib.evidence_reports and args.evidence:
        _write_evidence(calib.evidence_reports)
    if args.out:
        save_calibration(calib, args.out)
        print(f"wrote {args.out}")
    return 0


def _run_vectors(args) -> int:
    from bimforge.bim.plansheet.calibrate import load_calibration
    from bimforge.bim.plansheet.measure import write_vectors_dxf
    from bimforge.bim.plansheet.regions import find_regions
    from bimforge.bim.plansheet.vectors import extract_sheet, load_classes

    try:
        calib = load_calibration(args.calib)
        if args.sheet and args.sheet != calib.sheet:
            print(f"error: --sheet {args.sheet} does not match the calibration's "
                  f"sheet {calib.sheet}", file=sys.stderr)
            return 1
        sv = extract_sheet(args.pdf, calib.page_index, min_path_pt=args.min_path_pt)
        zone = calib.zone(args.zone_name)
        classes = load_classes(args.classes) if args.classes else None
        regions = None
        if args.regions or args.regions_json:
            regions = find_regions(sv.segments, zone.bbox_pt, classes=classes)
        info = write_vectors_dxf(sv, zone, args.out, classes=classes,
                                 regions=regions)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    per_layer = ", ".join(f"{k}: {v}" for k, v in sorted(info["layers"].items()))
    print(f"wrote {info['out']} ({info['segments']} segments in zone "
          f"'{zone.name}' — {per_layer})")
    if regions is not None:
        print(f"  {info['regions']} closed regions (largest first):")
        for row in info["region_rows"][:20]:
            print(f"    {row['layer']}: {row['area_ft2']} ft2 "
                  f"({row['area_sy']} SY), {row['vertices']} vertices, "
                  f"centroid {row['centroid_ft']}")
        if info["regions"] > 20:
            print(f"    ... {info['regions'] - 20} more (see --regions-json)")
    if args.regions_json:
        with open(args.regions_json, "w", encoding="utf-8") as fh:
            json.dump({"zone": zone.name, "ft_per_pt": zone.ft_per_pt,
                       "regions": info["region_rows"]}, fh, indent=2)
        print(f"wrote {args.regions_json}")
    return 0


def _run_measure(args) -> int:
    import yaml

    from bimforge.bim.plansheet.calibrate import load_calibration
    from bimforge.bim.plansheet.measure import (
        measure_traces, write_sidecar,
    )
    from bimforge.bim.plansheet.vectors import extract_sheet

    from bimforge.bim.plansheet.crosscheck import (
        collect_lettered, cross_check, render_report,
    )
    from bimforge.bim.plansheet.hints import load_hints

    try:
        calib = load_calibration(args.calib)
        if args.sheet and args.sheet != calib.sheet:
            print(f"error: --sheet {args.sheet} does not match the calibration's "
                  f"sheet {calib.sheet}", file=sys.stderr)
            return 1
        with open(args.traces, encoding="utf-8") as fh:
            traces = json.load(fh)
        with open(args.layer_map, encoding="utf-8") as fh:
            layer_map = yaml.safe_load(fh) or {}
        sv = extract_sheet(args.pdf, calib.page_index, min_path_pt=args.min_path_pt)
        hints = load_hints(args.hints, sv) if args.hints else None
        res = measure_traces(sv, calib, traces, layer_map, args.out, tol_ft=args.tol)
        # QC cross-check: measured dims vs the engineer's lettering (live
        # text spans, or dimension hints on flattened sheets). Mutates the
        # sidecar rows with confidence flags before they are written.
        rows = cross_check(res.sidecar, collect_lettered(sv, calib, hints),
                           tol_pct=args.qc_tol)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"wrote {res.out}: {res.entities} entities, {res.vertices} vertices "
          f"snapped (max snap {res.max_snap_ft:.3f} ft, tol {args.tol} ft)")
    n_rev = sum(1 for r in rows if r.status == "REVIEW")
    n_unv = sum(1 for r in rows if r.status == "UNVERIFIED")
    print(f"cross-check: {sum(1 for r in rows if r.status == 'OK')} OK, "
          f"{n_rev} REVIEW, {n_unv} UNVERIFIED "
          f"(tolerance {args.qc_tol}%)")
    if n_rev:
        for r in rows:
            if r.status == "REVIEW":
                print(f"  REVIEW {r.entity}: vector {r.vector_ft} ft vs "
                      f"lettered {r.lettered_text} — d {r.delta_pct}%",
                      file=sys.stderr)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            fh.write(render_report(rows, tol_pct=args.qc_tol))
        print(f"wrote {args.report}")
    if args.sidecar:
        write_sidecar(res, calib, args.sidecar, pdf=args.pdf, tol_ft=args.tol)
        print(f"wrote {args.sidecar}")
    if res.unsnapped:
        where = [f"{e['layer']}[{e['index']}]" for e in res.sidecar
                 if any(e["unsnapped"])]
        print(f"UNSNAPPED: {res.unsnapped} vertices found no vector within "
              f"{args.tol} ft ({', '.join(where)}) — re-trace them or raise --tol",
              file=sys.stderr)
        if not args.allow_unsnapped:
            return 2
    return 0


def _print_contours_profile(args, sv) -> None:
    """Sheet triage, GeoPDF viewports, the OCG table, then the pen table.

    On a plotted set the pen table IS the layer table — unless the PDF kept
    its CAD layers as optional content, in which case the OCG table is the
    better one. Triage says whether vector extraction applies at all.
    """
    from bimforge.bim.plansheet.contours import ocg_table, pen_table
    from bimforge.bim.plansheet.geopdf import anisotropy_ok, is_foot_crs
    from bimforge.bim.plansheet.triage import sheet_triage

    try:
        t = sheet_triage(args.pdf, args.sheet - 1)
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        print(f"sheet {args.sheet}: triage unavailable ({exc})")
        t = None
    if t is not None:
        print(f"sheet {args.sheet}: {t.kind} — images cover "
              f"{t.image_coverage:.0%} of the page")
        print(f"  GeoPDF viewports: {len(t.viewports)}")
        if t.kind == "raster":
            print("  raster sheet: there are no vector contours to extract here")
        for vp in t.viewports:
            flag = ("" if anisotropy_ok(vp) else
                    f"  <- scales differ by {vp.anisotropy_pct:.1f}%; "
                    "use --geopdf-bbox page")
            foot = is_foot_crs(vp)
            unit_label = "ft/pt" if foot else "m/pt"
            note = "" if foot else " — v1 needs a foot-unit CRS"
            print(f"  GeoPDF viewport {vp.index}: EPSG:{vp.crs_epsg} ({vp.unit}), "
                  f"{vp.scale_x:.5f} x {vp.scale_y:.5f} {unit_label}{note}{flag}")
        if t.viewport_error:
            print(f"  GeoPDF viewport unreadable: {t.viewport_error}")

    rows = ocg_table(sv.segments)
    print(f"layers (OCGs): {sum(1 for r in rows if r['layer'] is not None)}")
    if rows:
        print(f"{'segments':>9} {'length_pt':>11}  {'pens':<24} layer")
        for r in rows:
            pens = ", ".join(r["pens"])
            print(f"{r['segments']:>9} {r['length_pt']:>11.0f}  {pens[:24]:<24} "
                  f"{r['layer'] or '(untagged)'}")

    print(f"{'grey':>7} {'width':>6} {'coloured':>9} {'segments':>9} "
          f"{'length_pt':>11}")
    for r in pen_table(sv.segments):
        print(f"{str(r['grey']):>7} {r['width']:>6} "
              f"{str(r['coloured']):>9} {r['segments']:>9} "
              f"{r['length_pt']:>11.0f}")


class _GateFailure(Exception):
    """A quality gate refused the input: the command exits 2."""


def _parse_tags(specs, allowed, flag) -> dict:
    """``NAME=value`` tags (``--surface`` / ``--role``) -> {name: value}."""
    out = {}
    for spec in specs or []:
        name, sep, value = spec.partition("=")
        if not sep or not name.strip() or value not in allowed:
            raise ValueError(f"bad {flag} {spec!r}; expected "
                             f"NAME={'|'.join(sorted(allowed))}")
        out[name.strip()] = value
    return out


def _pick_viewport(args, log):
    """The page's GeoPDF viewport to georeference with, or None.

    Raises ValueError (exit 1) for a metre CRS or an ambiguous page and
    _GateFailure (exit 2) when the viewport's two scales disagree.
    """
    from bimforge.bim.plansheet.geopdf import (
        anisotropy_ok, is_foot_crs, read_viewports,
    )

    try:
        vps = read_viewports(args.pdf, args.sheet - 1, bbox_mode=args.geopdf_bbox)
    except (OSError, ValueError, KeyError, RuntimeError, ImportError) as exc:
        if args.viewport is not None:
            raise ValueError(f"--viewport {args.viewport}: GeoPDF viewport "
                             f"unreadable ({exc})") from exc
        log(f"  GeoPDF: viewport unreadable ({exc}); not used")
        return None
    if not vps:
        if args.viewport is not None:
            raise ValueError(f"--viewport {args.viewport} given but sheet "
                             f"{args.sheet} has no GeoPDF viewport")
        return None
    if args.viewport is None:
        if len(vps) > 1:
            raise ValueError(f"page has {len(vps)} GeoPDF viewports "
                             f"({', '.join(str(v.index) for v in vps)}); "
                             "pick one with --viewport, or fall back to "
                             "--calib/--tie with --no-geopdf")
        vp = vps[0]
    else:
        pick = [v for v in vps if v.index == args.viewport]
        if not pick:
            raise ValueError(f"no GeoPDF viewport {args.viewport} "
                             f"(have: {[v.index for v in vps]})")
        vp = pick[0]
    if not is_foot_crs(vp):
        raise ValueError(f"GeoPDF CRS EPSG:{vp.crs_epsg} is in {vp.unit}; v1 "
                         "needs a foot-unit CRS — georeference with --tie "
                         "instead, or use --no-geopdf to fall back to "
                         "--calib/--tie")
    if not anisotropy_ok(vp):
        raise _GateFailure(
            f"GeoPDF viewport {vp.index}: its two scales differ by "
            f"{vp.anisotropy_pct:.1f}% ({vp.scale_x:.5f} vs {vp.scale_y:.5f} "
            "ft/pt) — the viewport /BBox is likely wrong; retry with "
            "--geopdf-bbox page, or fall back to --calib/--tie with "
            "--no-geopdf")
    log(f"  GeoPDF: viewport {vp.index}, EPSG:{vp.crs_epsg}, "
        f"{vp.scale_x:.5f} x {vp.scale_y:.5f} ft/pt ({vp.bbox_mode} box), "
        f"residuals up to {max(vp.residuals_ft):.2f} ft")
    return vp


#: a tie landing more than this far from the GeoPDF viewport's mapping is a
#: wrong /BBox or a mis-keyed tie (GeoPDF is good to ~1 ft; ties are precise).
_TIE_GEOPDF_OFFSET_WARN_FT = 3.0


def _geopdf_crosscheck(args, ties, georef, log):
    """When ties win, cross-check them against a GeoPDF viewport if the page
    carries a usable one (#231), and return that viewport's EPSG to inherit
    when it covers the ties (#232). Best-effort: never fatal, never changes
    which georeference source wins — it only measures and warns.
    """
    if args.no_geopdf:
        return None
    from bimforge.bim.plansheet.contours import crosscheck_ties_vs_viewport
    from bimforge.bim.plansheet.geopdf import (
        anisotropy_ok, is_foot_crs, read_viewports,
    )
    try:
        vps = read_viewports(args.pdf, args.sheet - 1, bbox_mode=args.geopdf_bbox)
    except (OSError, ValueError, KeyError, RuntimeError, ImportError) as exc:
        if args.viewport is not None:
            raise ValueError(f"--viewport {args.viewport}: GeoPDF viewport "
                             f"unreadable ({exc})") from exc
        return None
    if args.viewport is not None:
        if not vps:
            raise ValueError(f"--viewport {args.viewport} given but sheet "
                             f"{args.sheet} has no GeoPDF viewport")
        have = [v.index for v in vps]
        vps = [v for v in vps if v.index == args.viewport]
        if not vps:
            raise ValueError(f"no GeoPDF viewport {args.viewport} "
                             f"(have: {have})")
    elif len(vps) > 1:
        log(f"  ties: GeoPDF cross-check skipped (page has {len(vps)} "
            "viewports; use --viewport to pick one)")
        return None
    if not vps:
        return None
    vp = vps[0]
    if not is_foot_crs(vp):
        log(f"  ties: GeoPDF cross-check skipped (viewport EPSG:{vp.crs_epsg} "
            f"is in {vp.unit}, not feet)")
        return None
    if not anisotropy_ok(vp):
        log(f"  ties: GeoPDF cross-check skipped (viewport /BBox looks wrong — "
            f"scales {vp.scale_x:.5f} vs {vp.scale_y:.5f} ft/pt)")
        return None
    drift, max_off, inside = crosscheck_ties_vs_viewport(
        ties, georef.ft_per_pt, vp)
    log(f"  ties vs GeoPDF viewport {vp.index} (EPSG:{vp.crs_epsg}): scale "
        f"drift {drift:+.2f}%, tie offset up to {max_off:.1f} ft")
    if abs(drift) > 1.0:
        log("  WARNING: ties disagree with the GeoPDF viewport scale by >1% — "
            "check the viewport /BBox or the ties")
    if max_off > _TIE_GEOPDF_OFFSET_WARN_FT:
        log(f"  WARNING: ties land up to {max_off:.1f} ft from the GeoPDF "
            "viewport's mapping — a wrong viewport /BBox or a mis-keyed tie")
    if not inside:
        log("  ties fall outside the GeoPDF viewport — not inheriting its CRS")
        return None
    if abs(drift) > 1.0 or max_off > _TIE_GEOPDF_OFFSET_WARN_FT:
        log("  ties and GeoPDF viewport do not agree closely enough — not "
            "inheriting its CRS")
        return None
    return vp.crs_epsg


def _run_contours(args) -> int:
    """Contour polylines off a flattened sheet -> DXF + JSON manifest.

    The pure cores live in ``bimforge.bim.plansheet.contours``; this wires
    the plansheet extractor + calibration in and owns the ezdxf output
    (the Work pdf_contours main's DXF port).
    """
    from dataclasses import replace

    from bimforge.bim.plansheet.contours import (
        extract_contours, georef_from_ties, georef_from_viewport,
        georef_from_zone, parse_layer_spec, parse_tie,
    )
    from bimforge.bim.plansheet.vectors import extract_sheet

    def _log(msg):
        print(msg, file=sys.stderr)

    try:
        sv = extract_sheet(args.pdf, args.sheet - 1,
                           min_path_pt=args.min_path_pt)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _log(f"sheet {args.sheet}: {len(sv.segments)} segments, "
         f"{len(sv.texts)} text spans"
         f"{'' if sv.texts else ' (flattened — no text layer)'}")

    if args.profile:
        _print_contours_profile(args, sv)
        return 0

    if not args.layer:
        print("error: at least one --layer is required, plus --calib, two or "
              "more --tie, or a GeoPDF viewport (or use --profile to see the "
              "sheet's pens and layers)", file=sys.stderr)
        return 1
    try:
        specs = [parse_layer_spec(s) for s in args.layer]
        surfaces = _parse_tags(args.surface, {"existing", "proposed"}, "--surface")
        roles = _parse_tags(args.role, {"index", "intermediate"}, "--role")
        unknown = sorted((set(surfaces) | set(roles)) - {s.name for s in specs})
        if unknown:
            raise ValueError(f"--surface/--role name(s) {unknown} match no --layer")
        ties = [parse_tie(t) for t in (args.tie or [])]
        clip = None
        if args.clip:
            parts = [float(v) for v in args.clip.split(",")]
            if len(parts) != 4:
                raise ValueError("--clip needs four page points: x0,y0,x1,y1")
            if not all(math.isfinite(v) for v in parts):
                raise ValueError("--clip page points must be finite")
            clip = tuple(parts)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    zone = None
    if args.calib:
        from bimforge.bim.plansheet.calibrate import load_calibration
        try:
            calib = load_calibration(args.calib)
            if calib.sheet != args.sheet:
                raise ValueError(f"calibration is for sheet {calib.sheet}, "
                                 f"not {args.sheet}")
            zone = calib.zone(args.zone_name)
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        _log(f"  calibration: {zone.ft_per_pt:.6f} ft/pt "
             f"(1in={zone.ft_per_pt * 72:.1f}ft), method={zone.method}")

    # georeference precedence: ties > GeoPDF viewport > calibration
    bounds = None
    inherited_crs = None
    try:
        if ties:
            georef = georef_from_ties(ties, args.tie_model)
            # #231/#232: independent cross-check + optional CRS inheritance.
            inherited_crs = _geopdf_crosscheck(args, ties, georef, _log)
        else:
            vp = None if args.no_geopdf else _pick_viewport(args, _log)
            if vp is not None:
                georef, bounds = georef_from_viewport(vp), vp.bbox_pt
            elif zone is not None:
                georef = georef_from_zone(zone)
            else:
                raise ValueError("no georeference: pass --calib, two or more "
                                 "--tie, or use a sheet with a GeoPDF viewport")
    except _GateFailure as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if georef.method != "calibration":
        res = ", ".join(f"{r:.3f}" for r in georef.residuals_ft) or "n/a"
        _log(f"  georeference: {georef.method} ({georef.model}), "
             f"{georef.ft_per_pt:.6f} ft/pt, residuals {res} ft")
        if zone is not None:
            drift = 100 * (georef.ft_per_pt / zone.ft_per_pt - 1)
            _log(f"  {georef.method} scale vs calibration: {drift:+.2f}%")
            if abs(drift) > 1.0:
                _log(f"  WARNING: {georef.method} scale disagrees with the "
                     "calibration by >1% — check the georeference before "
                     "trusting a quantity")
            if georef.method == "geopdf":
                _log(f"  output frame: {georef.frame} (from the GeoPDF "
                     f"viewport) — not the calibration's sheet_local_ft; "
                     "--no-geopdf keeps the old behaviour")
    if (args.max_residual_ft is not None and georef.residuals_ft
            and max(georef.residuals_ft) > args.max_residual_ft):
        print(f"error: georeference residual {max(georef.residuals_ft):.3f} ft "
              f"exceeds --max-residual-ft {args.max_residual_ft:g}",
              file=sys.stderr)
        return 2

    # horizontal CRS on the manifest (#232). Ties give coordinates but no CRS;
    # --crs-epsg supplies it (else an agreeing GeoPDF viewport is inherited).
    # A calibration frame is sheet-local with no world CRS; geopdf already
    # carries its viewport's CRS.
    if georef.method == "ties":
        if (args.crs_epsg is not None and inherited_crs is not None
                and args.crs_epsg != inherited_crs):
            print(f"error: --crs-epsg {args.crs_epsg} conflicts with the "
                  f"GeoPDF viewport's EPSG:{inherited_crs}", file=sys.stderr)
            return 1
        crs = args.crs_epsg if args.crs_epsg is not None else inherited_crs
        if crs is not None:
            georef = replace(georef, crs_epsg=crs)
            src = ("--crs-epsg" if args.crs_epsg is not None
                   else "inherited from GeoPDF viewport")
            _log(f"  CRS: EPSG:{crs} ({src})")
        else:
            _log("  WARNING: ties give coordinates but no CRS — pass "
                 "--crs-epsg N so contour-surface / terrain-ifc can place the "
                 "TIN in a model")
    elif args.crs_epsg is not None:
        if georef.method == "geopdf" and args.crs_epsg != georef.crs_epsg:
            print(f"error: --crs-epsg {args.crs_epsg} conflicts with the "
                  f"GeoPDF viewport's EPSG:{georef.crs_epsg}", file=sys.stderr)
            return 1
        if georef.method == "calibration":
            print("error: --crs-epsg needs --tie or a GeoPDF viewport — a "
                  "calibration-only manifest is in sheet_local_ft with no "
                  "world CRS", file=sys.stderr)
            return 1

    manifest = {"manifest_version": 2,
                "pdf": os.path.basename(args.pdf), "sheet": args.sheet,
                "source_kind": "vector",
                "ft_per_pt": zone.ft_per_pt if zone is not None else georef.ft_per_pt,
                "calibration_method": zone.method if zone is not None else "",
                "frame": georef.frame,
                "georef": georef.record(),
                "layers": {}}
    if clip is not None:
        manifest["clip"] = list(clip)
    for spec in specs:
        rec = extract_contours(sv, spec, zone, georef=georef, bounds=bounds,
                               clip=clip, min_length_ft=args.min_length,
                               gap_pt=args.gap, gap_angle_deg=args.gap_angle)
        if spec.name in surfaces:
            rec["surface"] = surfaces[spec.name]
        if spec.name in roles:
            rec["role"] = roles[spec.name]
        manifest["layers"][spec.name] = rec
        _log(f"  {spec.name:8s} {rec['segments']:6d} segments -> "
             f"{rec['raw_chains']:5d} chains -> "
             f"{rec['stitched_chains']:5d} stitched -> "
             f"{rec['polylines']:4d} polylines >= {args.min_length:g} ft "
             f"({rec['total_length_ft']:,.0f} ft total, "
             f"{rec['closed']} closed)")
        if rec.get("outside_bounds"):
            _log(f"  {spec.name:8s} {rec['outside_bounds']} segment(s) outside "
                 "the GeoPDF viewport excluded")

    if args.out:
        import ezdxf
        doc = ezdxf.new(setup=True)
        doc.header["$INSUNITS"] = 2                    # feet
        msp = doc.modelspace()
        for name, rec in manifest["layers"].items():
            layer = f"C-{name}"
            if layer not in doc.layers:
                doc.layers.add(layer)
            for line in rec["lines"]:
                msp.add_lwpolyline(line["points"],
                                   dxfattribs={"layer": layer},
                                   close=line["closed"])
        doc.saveas(args.out)
        print(f"wrote {args.out}")
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=1)
        print(f"wrote {args.json_out}")
    if not args.out and not args.json_out:
        json.dump(manifest, sys.stdout, indent=1)
    return 0


def _manifest_placement(manifests, sheet):
    """(page_to_world, label) from the v2 manifest the anchors' sheet names.

    With no ``sheet:`` in the anchors file, only a single manifest can place
    page records; several manifests without a sheet leave nothing to place
    them (``place_anchors`` then says how to fix it).
    """
    from bimforge.terrain.anchors import manifest_page_to_world
    if sheet is None and len(manifests) != 1:
        return None, None
    for m in manifests:
        if sheet is not None and m.get("sheet") != sheet:
            continue
        fn = manifest_page_to_world(m)
        if fn is not None:
            method = (m.get("georef") or {}).get("method", "?")
            return fn, f"manifest sheet {m.get('sheet')} georef ({method})"
    return None, None


def _surface_of(flag, layer_meta) -> str:
    """The one surface this run builds: --surface, else the layers' tag."""
    tags = {v["surface"] for v in layer_meta.values() if v.get("surface")}
    if flag:
        if tags and tags != {flag}:
            raise ValueError(f"--surface {flag} but the manifest layers are "
                             f"tagged {sorted(tags)}")
        return flag
    if len(tags) > 1:
        raise ValueError(f"manifest layers mix surfaces {sorted(tags)}; build "
                         "one surface per run (--layers or --surface)")
    return tags.pop() if tags else "existing"


def _thin_points(line, z, thin):
    """A contour's vertices at least ``thin`` ft apart, as (x, y, z)."""
    import math

    keep = [line[0]]
    for p in line[1:]:
        if math.dist(tuple(p), tuple(keep[-1])) >= thin:
            keep.append(p)
    if len(keep) < 2 and len(line) > 1:
        keep = [line[0], line[-1]]
    return [(float(p[0]), float(p[1]), float(z)) for p in keep]


def _leave_one_out(polys, graph, lettered, interval, spots, *, roles,
                   index_interval, snap_tol, thin, max_edge):
    """Score every spot against a surface rebuilt without its own pin.

    Only for ``--spot-pins --propagate``: without ``--propagate`` the pins
    cannot change the surface (it is the lettered contours alone), so each
    spot is simply held out.
    """
    import math

    import numpy as np

    from bimforge.terrain.contours import (build_tin, propagate, sample_tin,
                                           score_stats)
    from bimforge.terrain.reconcile import reconcile
    rows = []
    for k, s in enumerate(spots):
        rec_k = reconcile(polys, graph, lettered, interval, roles=roles,
                          index_interval=index_interval,
                          spot_pins=spots[:k] + spots[k + 1:])
        added, _ = propagate(polys, lettered, interval, snap_tol=snap_tol,
                             roles=roles, index_interval=index_interval,
                             reconciliation=rec_k)
        e = {**lettered, **added}
        pts = [q for i, (line, _, _) in enumerate(polys) if i in e
               for q in _thin_points(line, e[i], thin)]
        z = math.nan
        if len(pts) >= 3:
            try:
                z = float(sample_tin(build_tin(pts, max_edge),
                                     np.array([s["xy"]], dtype=float))[0])
            except (RuntimeError, ValueError):
                z = math.nan
        ok = math.isfinite(z)
        rows.append({"elev": s["elev"], "tin": z if ok else None,
                     "err": (z - s["elev"]) if ok else None})
    return {"rows": rows, "stats": score_stats([r["err"] for r in rows])}


def _run_contour_surface(args) -> int:
    """Labelled contour manifests -> TIN npz + spot score report (held-out
    spots, or leave-one-out with ``--spot-pins --propagate``)."""
    import math
    from pathlib import Path

    import numpy as np
    import yaml

    from bimforge.bim.plansheet.contours import parse_tie, solve_georef
    from bimforge.terrain.anchors import load_anchors, place_anchors
    from collections import Counter

    from bimforge.terrain.contours import (
        assign_lettered, build_tin, check_index_labels, flat_triangle_share,
        merge_fragments, propagate, save_tin_npz, score_against_spots,
        tin_provenance,
    )
    from bimforge.terrain.reconcile import (
        build_findings, neighbour_graph, reconcile,
    )

    def _log(msg):
        print(msg, file=sys.stderr)

    if args.pdf and not args.review_dir:
        print("error: --pdf needs --review-dir (the crops go there)",
              file=sys.stderr)
        return 1
    if not (math.isfinite(args.review_crop_ft) and args.review_crop_ft > 0):
        print("error: --review-crop-ft must be a finite number > 0 "
              f"(got {args.review_crop_ft:g})", file=sys.stderr)
        return 1
    if args.dpi <= 0:
        print(f"error: --dpi must be > 0 (got {args.dpi})", file=sys.stderr)
        return 1
    if args.review_dir:
        from bimforge.bim.plansheet.review import check_review_dir
        try:
            check_review_dir(args.review_dir)
        except ValueError as exc:
            print(f"error: --review-dir: {exc}", file=sys.stderr)
            return 1

    try:
        polys, manifests, layer_meta = [], [], {}
        wanted = set(args.layers or [])
        skipped_review = 0
        for p in args.contours:
            m = json.loads(Path(p).read_text(encoding="utf-8"))
            manifests.append(m)
            for name, d in m["layers"].items():
                if wanted and name not in wanted:
                    continue
                if name == "REVIEW" and not args.include_review:
                    skipped_review += len(d.get("lines", []))
                    continue
                src = f"sheet {m['sheet']}"
                layer_meta[(src, name)] = {"surface": d.get("surface"),
                                           "role": d.get("role")}
                for ln in d["lines"]:
                    polys.append((np.asarray(ln["points"], dtype=float),
                                  src, name))
        raw = load_anchors(args.anchors)
        extra_spots = []
        if args.spots:
            extra = yaml.safe_load(
                Path(args.spots).read_text(encoding="utf-8")) or []
            extra_spots = (extra.get("spots") or [] if isinstance(extra, dict)
                           else extra)
            if not isinstance(extra_spots, list):
                raise ValueError("--spots file: expected a list of spot "
                                 "records or {spots: [...]}")
        if args.tie:
            page_to_world, scale, res = solve_georef(
                [parse_tie(t) for t in args.tie])
            placed_by = f"{len(args.tie)} --tie point(s)"
            _log(f"anchors placed with {len(args.tie)} --tie point(s) "
                 f"(overriding any manifest georef), scale {scale:.6f} ft/pt, "
                 f"residuals {', '.join(f'{r:.3f}' for r in res)} ft")
        else:
            page_to_world, placed_by = _manifest_placement(manifests,
                                                           raw.get("sheet"))
        anchors = place_anchors(raw, extra_spots=extra_spots,
                                page_to_world=page_to_world)
        labels, spots = anchors.contours, anchors.spots
        surface = _surface_of(args.surface, layer_meta)
    except (OSError, ValueError, KeyError, json.JSONDecodeError,
            yaml.YAMLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if skipped_review:
        _log(f"skipped {skipped_review} REVIEW line(s); pass --include-review "
             "to use them")
    if anchors.unread:
        _log(f"{anchors.unread} anchor record(s) have elev: null (unread) — "
             "skipped")
    uses_page = any("page" in r for r in (raw.get("contours") or [])
                    + list(raw.get("spots") or []))
    if uses_page and placed_by and not args.tie:
        _log(f"page anchors placed by the {placed_by}")

    pre = "EG" if surface == "existing" else "FG"

    _log(f"{len(polys)} polylines from {len(args.contours)} manifest(s)")
    merge_stats: dict = {"refused": 0}
    if args.merge_gap > 0:
        before = len(polys)
        polys = merge_fragments(polys, args.merge_gap, args.merge_angle,
                                contact_ft=args.contact_ft, stats=merge_stats)
        _log(f"fragment merge (<= {args.merge_gap:g} ft, "
             f"<= {args.merge_angle:g} deg): {before} -> {len(polys)} contours"
             + (f"; {merge_stats['refused']} join(s) refused (would cross or "
                "touch another line)" if merge_stats["refused"] else ""))

    elev, label_rows = assign_lettered(polys, labels, args.max_label_dist)
    ok = sum(1 for r in label_rows if r["accepted"])
    _log(f"lettered: {ok}/{len(label_rows)} labels matched a contour "
         f"-> {len(elev)} contours carry a plan value")

    index_lines = {i for i, (_, src, lay) in enumerate(polys)
                   if (layer_meta.get((src, lay)) or {}).get("role") == "index"}
    elev, index_rows = check_index_labels(elev, index_lines,
                                          anchors.index_interval_ft)
    line_ids: dict = {}
    for r in label_rows:
        if r["accepted"] and r.get("id"):
            line_ids.setdefault(r["line"], []).append(r["id"])
    for r in index_rows:
        r["id"] = ", ".join(line_ids.get(r["line"], [])) or None
    index_on = bool(index_lines) and bool(anchors.index_interval_ft)
    idx_txt = (f"{len(index_rows)} off the index interval" if index_on else
               "index check off (no role: index layer / no index_interval_ft)")
    if index_rows:
        _log(f"label checks: {idx_txt} — not assigned (see the report)")
    elif not index_on:
        _log(f"label checks: {idx_txt}")

    interval = (args.interval if args.interval is not None
                else anchors.interval_ft)
    if interval is not None and not (math.isfinite(interval) and interval > 0):
        where = ("--interval" if args.interval is not None
                 else "anchors interval_ft")
        print(f"error: {where} must be a finite number > 0 (got {interval:g})",
              file=sys.stderr)
        return 1
    if interval is None and args.propagate:
        interval = 1.0
    if args.spot_pins and not interval:
        print("error: --spot-pins needs a contour interval (interval_ft in "
              "the anchors file, or --interval)", file=sys.stderr)
        return 1
    pins = list(spots) if args.spot_pins else None
    if args.spot_pins and not spots:
        _log("--spot-pins: there are no spot elevations to pin")
    line_roles = {i: (layer_meta.get((src, lay)) or {}).get("role")
                  for i, (_, src, lay) in enumerate(polys)}
    graph = neighbour_graph(polys, contact_ft=args.contact_ft)

    def _reconcile(e, reuse=None):
        return reconcile(polys, graph, e, interval, roles=line_roles,
                         index_interval=anchors.index_interval_ft,
                         spot_pins=pins, reuse=reuse)

    rec = None
    if interval:
        rec = _reconcile(elev)
        c = rec.counts()
        _log(f"reconciliation: {c['pinned']} pinned, {c['ambiguous']} "
             f"ambiguous, {c['conflict']} conflict, {c['unreached']} "
             f"unreached; {c['label_conflicts']} lettered value(s) in "
             "conflict (kept)")
    else:
        _log("reconciliation off (no interval_ft)")
    findings = build_findings(
        polys, graph, elev, rec, labels=labels, label_rows=label_rows,
        index_rows=index_rows, line_ids=line_ids,
        recheck=(lambda e: _reconcile(e, reuse=rec)) if rec is not None else None)

    from bimforge.bim.plansheet.review import affine_of, world_to_page

    def _placement(sheet):
        if args.tie:
            return page_to_world
        return _manifest_placement(manifests, sheet)[0]

    def _sheet_num(src):
        try:
            return int(str(src).split()[-1])
        except (ValueError, IndexError):
            return None

    # an anchors file with no sheet: is placed by its one manifest (see
    # _manifest_placement), so a finding with no line is on that sheet
    lone = manifests[0].get("sheet") if len(manifests) == 1 else None
    line_sheet = [_sheet_num(src) for _, src, _ in polys]

    def sheet_of(f):
        if f.lines:
            return line_sheet[f.lines[0]]
        s = anchors.sheet if anchors.sheet is not None else lone
        return None if s is None else _sheet_num(f"sheet {s}")

    for f in findings:
        s = sheet_of(f)
        fn = _placement(s) if s is not None else None
        if fn is not None and math.isfinite(f.xy[0]):
            try:
                f.page = world_to_page(affine_of(fn))(*f.xy)
            except ValueError as exc:
                print(f"error: sheet {s}: {exc} — cannot place finding "
                      f"{f.id} on the page", file=sys.stderr)
                return 1

    kinds_txt = ", ".join(f"{v} {k}" for k, v in
                          Counter(f.kind for f in findings).items())
    _log(f"findings: {len(findings)} ({kinds_txt})" if findings
         else "findings: none")

    lettered = dict(elev)
    tiers = {"lettered": len(elev), "inferred": 0}
    inferred: set = set()
    prop_rows: list = []
    if args.propagate:
        added, prop_rows = propagate(polys, elev, interval,
                                     snap_tol=args.snap_tol, roles=line_roles,
                                     index_interval=anchors.index_interval_ft,
                                     reconciliation=rec)
        elev = {**elev, **added}
        inferred = set(added)
        tiers["inferred"] = len(added)
        _log(f"inferred: {len(added)}/{len(prop_rows)} unlabelled contours "
             f"assigned by neighbour count "
             f"({len(prop_rows) - len(added)} rejected: "
             f"{', '.join(sorted({r['reason'] for r in prop_rows if r['reason']})) or 'none'})")

    # thin the elevation-bearing vertices, then triangulate
    pts, pt_line, tin_lines = [], [], []
    for i, (line, src, lay) in enumerate(polys):
        if i not in elev:
            continue
        k = len(tin_lines)
        tin_lines.append({
            "points": np.asarray(line, dtype=float),
            "elev": float(elev[i]),
            "tier": "inferred" if i in inferred else "lettered",
            "role": (layer_meta.get((src, lay)) or {}).get("role"),
            "source": f"{src} / {lay}"})
        for q in _thin_points(line, elev[i], args.thin):
            pts.append(q)
            pt_line.append(k)
    if len(pts) < 3:
        print("error: not enough elevation-bearing vertices to triangulate",
              file=sys.stderr)
        return 1
    _log(f"TIN input: {len(pts)} points from {len(elev)} contours")

    try:
        tin = build_tin(pts, args.max_edge)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _log(f"TIN: {len(tin.simplices)} triangles "
         f"({tin.dropped} dropped as void-spanning)")

    flat = flat_triangle_share(pts, tin.simplices, pt_line)
    _log(f"flat-triangle share: {flat:.1%} of the TIN area (all three "
         "vertices on one contour — measured, not repaired)")
    crs_set = {(m.get("georef") or {}).get("crs_epsg") for m in manifests}
    crs_set.discard(None)
    if len(crs_set) > 1:
        print("error: the contour manifests are in different horizontal "
              f"CRSs (EPSG {', '.join(str(c) for c in sorted(crs_set))}) — "
              "one surface needs one frame", file=sys.stderr)
        return 1
    crs_epsg = crs_set.pop() if crs_set else None

    # pins change the surface only through --propagate (they can withdraw an
    # assigned contour); without it every spot is simply held out
    scoring = "held-out"
    if args.spot_pins and spots and args.propagate:
        scoring = "leave-one-out"
        score = _leave_one_out(polys, graph, lettered, interval, spots,
                               roles=line_roles,
                               index_interval=anchors.index_interval_ft,
                               snap_tol=args.snap_tol,
                               thin=args.thin, max_edge=args.max_edge)
    else:
        score = score_against_spots(tin, spots)
    st = score["stats"]
    if spots:
        if st["n"]:
            _log(f"scorecard vs {st['n']} {scoring} spot elevations: "
                 f"mean {st['mean']:+.2f} ft, MAE {st['mae']:.2f} ft, "
                 f"RMSE {st['rmse']:.2f} ft, max |err| {st['max_abs']:.2f} ft")
        else:
            _log("scorecard: no spot elevation fell inside the TIN")

    prov = tin_provenance(
        tiers, st["rmse"], f"contour vertices thinned to {args.thin:g} ft")

    # npz — points/simplices/per-contour arrays plus a JSON info string
    info = {"tiers": tiers, "score": st, "provenance": prov,
            "thin_ft": args.thin, "max_edge_ft": args.max_edge,
            "dropped_triangles": tin.dropped,
            "propagate": bool(args.propagate),
            "surface": surface, "vertical_datum": anchors.vertical_datum,
            "unread_anchors": anchors.unread,
            "label_checks": {"index_multiple": len(index_rows),
                             "label_conflicts": (len(rec.label_conflicts)
                                                 if rec is not None else 0)},
            "reconcile": rec.counts() if rec is not None else None,
            "findings": len(findings),
            "spot_scoring": scoring,
            "graph": {**graph.params, "same": len(graph.same),
                      "joints": len(graph.joints),
                      "refused_merges": merge_stats["refused"]},
            "flat_triangle_share": round(flat, 4), "crs_epsg": crs_epsg}
    out = save_tin_npz(args.out, pts, tin.simplices, info, tin_lines, pt_line)
    print(f"wrote {out}")

    if args.dxf:
        import ezdxf
        doc = ezdxf.new(setup=True)
        doc.header["$INSUNITS"] = 2
        msp = doc.modelspace()
        for name in (f"{pre}-CONTOUR-LETTERED", f"{pre}-CONTOUR-INFERRED",
                     f"{pre}-TIN", f"{pre}-SPOT"):
            if name not in doc.layers:
                doc.layers.add(name)
        for i, (line, _, _) in enumerate(polys):
            if i not in elev:
                continue
            lay = (f"{pre}-CONTOUR-INFERRED" if i in inferred
                   else f"{pre}-CONTOUR-LETTERED")
            msp.add_polyline3d([(x, y, elev[i]) for x, y in line],
                               dxfattribs={"layer": lay})
        P = np.asarray(pts, dtype=float)
        for s in tin.simplices:
            msp.add_3dface([tuple(P[s[0]]), tuple(P[s[1]]),
                            tuple(P[s[2]]), tuple(P[s[2]])],
                           dxfattribs={"layer": f"{pre}-TIN"})
        for s in spots:
            msp.add_point((s["xy"][0], s["xy"][1], s["elev"]),
                          dxfattribs={"layer": f"{pre}-SPOT"})
        doc.saveas(args.dxf)
        print(f"wrote {args.dxf}")

    if args.review_dir:
        from bimforge.bim.plansheet.review import (
            clear_stale, contact_sheet, line_rows, render_crops, write_review)
        removed = clear_stale(args.review_dir)
        if removed:
            _log(f"removed {removed} stale review output(s)")
        assigned = {k: elev[k] for k in inferred}
        crops: dict = {}
        if args.pdf:
            named = {m.get("pdf") for m in manifests if m.get("pdf")}
            if named and Path(args.pdf).name not in named:
                _log(f"warning: --pdf is {Path(args.pdf).name} but the "
                     f"manifests came from {', '.join(sorted(named))}")
            try:
                for sheet in sorted({s for s in map(sheet_of, findings)
                                     if s is not None}):
                    fn = _placement(sheet)
                    if fn is None:
                        _log(f"sheet {sheet}: no page placement — its "
                             "findings get no crop")
                        continue
                    crops.update(render_crops(
                        args.pdf, affine_of(fn), polys,
                        [f for f in findings if sheet_of(f) == sheet],
                        args.review_dir, sheet_of=sheet_of, elev=lettered,
                        assigned=assigned, spots=spots, line_sheet=line_sheet,
                        crop_ft=args.review_crop_ft, dpi=args.dpi))
            except (OSError, RuntimeError, ValueError) as exc:
                print(f"error: --pdf: {exc}", file=sys.stderr)
                return 1
            contact_sheet([(f.id, f"{f.id} · {f.kind} · lines "
                                  f"{', '.join(str(k) for k in f.lines[:8])}")
                           for f in findings if f.id in crops], args.review_dir)
        paths = write_review(args.review_dir, findings,
                             line_rows(polys, graph, rec, lettered,
                                       roles=line_roles, added=assigned,
                                       prop_rows=prop_rows),
                             crops=crops)
        print(f"wrote {paths['review']} ({len(crops)} crop(s))")

    if args.report:
        lines = [f"# {'Existing-ground' if surface == 'existing' else 'Proposed-grade'} "
                 "surface — build report", "",
                 f"- contours in: **{len(polys)}**",
                 f"- lettered contours: **{tiers['lettered']}**",
                 f"- inferred contours: **{tiers['inferred']}**",
                 f"- TIN: **{len(pts)} points / {len(tin.simplices)} "
                 f"triangles** ({tin.dropped} void-spanning dropped)",
                 f"- flat-triangle share: **{flat:.1%}** of the TIN area "
                 "(triangles with all three vertices on one contour — "
                 "measured, not repaired)",
                 f"- findings: **{len(findings)}**"
                 + (f" ({kinds_txt})" if findings else ""),
                 f"- duplicate linework pairs: {len(graph.same)} · fragment "
                 f"joints: {len(graph.joints)} · refused merges: "
                 f"{merge_stats['refused']} · unreached lines: "
                 f"{rec.counts()['unreached'] if rec is not None else '—'}",
                 "",
                 "## Label matching", "",
                 "`id` is the anchors record (the skeleton's crop); `line` "
                 "here is the contour index after fragment merging, not the "
                 "skeleton's `nearest_line`.", "",
                 "| id | lettered | line | nearest contour (ft) | "
                 "margin to 2nd (ft) | accepted |",
                 "|---|---|---|---|---|---|"]
        for r in label_rows:
            lines.append(
                f"| {r.get('id') or ''} | {r['elev']:g} | "
                f"{'' if r['line'] is None else r['line']} | "
                f"{r['dist_ft']:.2f} | {r['margin_ft']:.2f} | "
                f"{'yes' if r['accepted'] else 'NO'} |")
        lines += ["", "## Label checks", ""]
        if index_rows:
            lines += ["| id | line | lettered | check | detail |",
                      "|---|---|---|---|---|"]
            lines += [f"| {r.get('id') or ''} | {r['line']} | {r['elev']:g} | "
                      f"{r['check']} | {r['detail']} |" for r in index_rows]
        elif index_on:
            lines.append("none — every index label is on the index interval")
        else:
            lines.append(idx_txt)
        lines += ["", "## Reconciliation", ""]
        if rec is None:
            lines.append("off — no contour interval (interval_ft or --interval)")
        else:
            c, gp = rec.counts(), graph.params
            lines += [f"neighbour graph: contact_ft {gp['contact_ft']:g} · "
                      f"min_facing_ft {gp['min_facing_ft']:g} · "
                      f"sample_ft {gp['sample_ft']:g}", "",
                      "| pinned | ambiguous | conflict | unreached | "
                      "lettered in conflict |", "|---|---|---|---|---|",
                      f"| {c['pinned']} | {c['ambiguous']} | {c['conflict']} | "
                      f"{c['unreached']} | {c['label_conflicts']} |"]
            if args.propagate:
                why = Counter(r["reason"] for r in prop_rows if r["reason"])
                lines += ["", f"assigned (tier inferred): **{tiers['inferred']}**"
                          + ("; rejected: " + ", ".join(
                              f"{v} {k}" for k, v in sorted(why.items()))
                             if why else "")]
        lines += ["", "## Findings", ""]
        if findings:
            lines += ["| id | kind | lines | labels | E | N | page | check |",
                      "|---|---|---|---|---|---|---|---|"]
            for f in findings:
                labs = ", ".join(f"{lab['elev']:g}"
                                 + (f" ({lab['id']})" if lab.get("id") else "")
                                 for lab in f.labels)
                shown = ", ".join(str(k) for k in f.lines[:12])
                more = " …" if len(f.lines) > 12 else ""
                page = ("" if f.page is None
                        else f"{f.page[0]:.0f}, {f.page[1]:.0f}")
                lines.append(f"| {f.id} | {f.kind} | {shown}{more} | {labs} | "
                             f"{f.xy[0]:.1f} | {f.xy[1]:.1f} | {page} | "
                             f"{f.check} |")
            for f in findings:
                if f.detail or f.paths:
                    lines += ["", f"**{f.id} · {f.kind}** — {f.detail}"]
                    lines += [f"- {p}" for p in f.paths]
        else:
            lines.append("none")
        if args.review_dir:
            lines += ["", f"Crops and details: `{args.review_dir}/review.md`"]
        if spots:
            lines += ["", f"## Scorecard — {scoring} spot elevations", "",
                      "| spot | TIN | error (ft) |", "|---|---|---|"]
            for r in score["rows"]:
                t = "outside TIN" if r["tin"] is None else f"{r['tin']:.2f}"
                e = "—" if r["err"] is None else f"{r['err']:+.2f}"
                lines.append(f"| {r['elev']:.1f} | {t} | {e} |")
            if st["n"]:
                lines += ["", f"**n={st['n']} · mean {st['mean']:+.2f} ft · "
                              f"MAE {st['mae']:.2f} ft · "
                              f"RMSE {st['rmse']:.2f} ft · "
                              f"max |err| {st['max_abs']:.2f} ft**"]
        with open(args.report, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        print(f"wrote {args.report}")

    if args.max_rmse is not None:
        if st["rmse"] is None:
            print(f"error: --max-rmse {args.max_rmse:g} given but the "
                  "surface is unscored (no spot fell inside the TIN) — "
                  "RMSE cannot be verified", file=sys.stderr)
            return 2
        if st["rmse"] > args.max_rmse:
            print(f"error: spot RMSE {st['rmse']:.2f} ft exceeds "
                  f"--max-rmse {args.max_rmse:g} ft", file=sys.stderr)
            return 2
    if args.strict and findings:
        where = (f"see {args.report}" if args.report
                 else "rerun with --report for the details")
        print(f"error: --strict: {len(findings)} finding(s) ({kinds_txt}) — "
              f"{where}", file=sys.stderr)
        return 2
    return 0


def _load_surface_points(path):
    """(N, 3) surface points from a whitespace XYZ, comma CSV, or TIN .npz.

    A leading non-numeric line (a CSV header) is skipped; extra columns
    are ignored.
    """
    if str(path).endswith(".npz"):
        from bimforge.terrain.contours import load_tin_npz
        return load_tin_npz(path).points
    import numpy as np
    with open(path, encoding="utf-8") as fh:
        first = fh.readline()
    delim = "," if "," in first else None
    skip = 0
    try:
        [float(t) for t in first.replace(",", " ").split()[:3]]
    except ValueError:
        skip = 1
    P = np.loadtxt(path, delimiter=delim, skiprows=skip, ndmin=2)
    if P.shape[1] < 3:
        raise ValueError(
            f"surface file {path} needs at least 3 columns (x y z)")
    return P[:, :3]


def _run_terrain_diff(args) -> int:
    """Plan-frame surface vs a terrain grid cache on one datum -> CSV [+PNG]."""
    if args.against:
        return _run_tin_vs_tin(args)

    from pathlib import Path

    import numpy as np

    from bimforge.terrain.diff import (
        M_PER_FT, diff_surface, plot_diff, write_diff_csv,
    )
    from bimforge.terrain.grid import TerrainGrid

    def _log(msg):
        print(msg, file=sys.stderr)

    unit_scale = {"ftUS": M_PER_FT, "ft": 0.3048, "m": 1.0}[args.units]
    is_tin = str(args.surface).endswith(".npz")
    tin_datum = None
    try:
        if is_tin:
            from bimforge.terrain.contours import load_tin_npz
            t = load_tin_npz(args.surface)
            P, tin_datum = t.points, t.info.get("vertical_datum")
        else:
            P = _load_surface_points(args.surface)
        # fetch.py's grid-cache format: numeric members + a JSON info string
        # — loaded with pickling OFF, always.
        g = np.load(args.grid, allow_pickle=False)
        z = np.asarray(g["z"], dtype="float64")
        bbox = (float(g["xmin"]), float(g["ymin"]),
                float(g["xmax"]), float(g["ymax"]))
        info = {}
        if "info" in g.files:
            try:
                info = json.loads(str(g["info"]))
            except (ValueError, TypeError):
                pass
        grid = TerrainGrid(z=z, bbox_m=bbox,
                           spacing_m=(bbox[2] - bbox[0]) / z.shape[1],
                           crs_epsg=0, info=info)  # CRS rides with the caller
        vshift = 0.0
        vsrc = "none (surface already NAVD88)"
        if args.vshift_json:
            v = json.loads(Path(args.vshift_json).read_text(encoding="utf-8"))
            vshift = float(v["shift_m"])
            vsrc = v.get("source", "?")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    _log(f"surface: {len(P)} points ({args.units})   terrain: "
         f"{z.shape[0]}x{z.shape[1]} grid {info.get('project', '?')} "
         f"pub {info.get('publication', '?')}")
    tin_note = ""
    if is_tin:
        tin_note = (f"; the surface TIN records vertical datum "
                    f"{tin_datum or 'none'}")
    _log(f"vertical: project datum -> NAVD88 {vshift:+.3f} m ({vsrc}){tin_note}")

    rows = diff_surface(P, grid, unit_scale_to_m=unit_scale, vshift_m=vshift)
    d = rows[:, 4]
    finite = np.isfinite(d)
    _log(f"{int(finite.sum())}/{len(d)} surface points fall on the "
         f"terrain grid")
    if not finite.any():
        print("error: no overlap between the surface and the terrain grid",
              file=sys.stderr)
        return 1
    v = d[finite]
    print(f"plan - terrain, m (+ = plan above): n={int(finite.sum())}  "
          f"mean {v.mean():+.3f}  median {float(np.median(v)):+.3f}  "
          f"sd {v.std():.3f}  min {v.min():+.3f}  max {v.max():+.3f}")
    if args.csv:
        write_diff_csv(rows, args.csv, log=_log)   # logs count + path itself
    if args.png:
        plot_diff(rows, args.png, log=_log)   # degrades without matplotlib
    return 0


def _run_tin_vs_tin(args) -> int:
    """TIN vs TIN on one grid: surface minus against, ft — never a volume."""
    from pathlib import Path

    import numpy as np
    import yaml

    from bimforge.terrain.contours import load_tin_npz
    from bimforge.terrain.diff import (
        diff_tins, plot_diff, summarize_tin_diff, write_tin_diff_csv,
    )

    def _log(msg):
        print(msg, file=sys.stderr)

    try:
        if not (str(args.surface).endswith(".npz")
                and str(args.against).endswith(".npz")):
            raise ValueError("--against compares two contour-TIN .npz files "
                             "(--surface must be one too)")
        a, b = load_tin_npz(args.surface), load_tin_npz(args.against)
        da, db = a.info.get("vertical_datum"), b.info.get("vertical_datum")
        if da and db and da != db:
            raise ValueError(f"the surfaces are on different vertical datums "
                             f"({da} vs {db}) — compare them on one datum")
        ca, cb = a.info.get("crs_epsg"), b.info.get("crs_epsg")
        if ca and cb and ca != cb:
            raise ValueError(f"the surfaces are in different horizontal CRSs "
                             f"(EPSG:{ca} vs EPSG:{cb}) — compare them in one "
                             "CRS")
        zones = []
        if args.zones:
            doc = yaml.safe_load(
                Path(args.zones).read_text(encoding="utf-8")) or {}
            if not isinstance(doc, dict):
                raise ValueError("zones file: expected a mapping {zones: "
                                 "[{name, polygon}]}")
            zones = doc.get("zones", [])
            if not isinstance(zones, list):
                raise ValueError("zones file: 'zones' must be a list of "
                                 "{name, polygon} records")
            from shapely.geometry import Polygon
            for i, z in enumerate(zones):
                poly = (z.get("polygon") if isinstance(z, dict) else None)
                ok = (isinstance(z, dict) and z.get("name")
                      and isinstance(poly, (list, tuple)) and len(poly) >= 3)
                if ok:
                    try:
                        p = Polygon(poly)
                        ok = p.is_valid and p.area > 0
                    except (ValueError, TypeError, AttributeError):
                        ok = False
                if not ok:
                    raise ValueError(
                        f"--zones entry {i}: needs name and a polygon of "
                        ">= 3 [x, y] points with positive area")
    except (OSError, ValueError, KeyError, yaml.YAMLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if bool(da) != bool(db):
        stated, bare = (da, args.against) if da else (db, args.surface)
        _log(f"warning: {Path(bare).name} records no vertical datum; "
             f"comparing as if it were {stated}")
    datum_line = da or db or "unstated"
    if da and not db:
        datum_line = f"{da} (against: unstated)"
    elif db and not da:
        datum_line = f"{db} (surface: unstated)"

    rows = diff_tins(a, b, step=args.step)
    if len(rows) == 0:
        print("error: the two surfaces do not overlap", file=sys.stderr)
        return 1
    s = summarize_tin_diff(rows, step=args.step, tie_tol=args.tie_tol,
                           zones=zones)
    al = s["all"]
    print("surface − against, ft (+ = surface higher) — NOT A PAY QUANTITY: "
          f"n={al['n']} ({al['area_sqft']:,.0f} sq ft shared)  "
          f"median {al['median']:+.3f}  mean {al['mean']:+.3f}  "
          f"sd {al['sd']:.3f}  min {al['min']:+.3f}  max {al['max']:+.3f}  "
          f"within ±{args.tie_tol:g} ft: {al['within_tie_tol']:.1%}")
    for name, z in s["zones"].items():
        med = "—" if z["median"] is None else f"{z['median']:+.3f}"
        print(f"  zone {name}: n={z['n']}  median {med}")
    if args.csv:
        write_tin_diff_csv(rows, args.csv, log=_log)
    if args.png:
        plot_diff(rows, args.png, log=_log,
                  label="surface − against, ft  (+ = surface is higher)",
                  unit="ft")
    if args.report:
        lines = ["# Surface comparison — not a pay quantity", "",
                 f"- surface: `{Path(args.surface).name}` "
                 f"({a.info.get('surface', '?')}), against: "
                 f"`{Path(args.against).name}` ({b.info.get('surface', '?')})",
                 f"- vertical datum: {datum_line}",
                 f"- grid step {args.step:g} ft; shared footprint "
                 f"{al['area_sqft']:,.0f} sq ft ({al['n']} samples)",
                 f"- within ±{args.tie_tol:g} ft (tie-in / daylight): "
                 f"**{al['within_tie_tol']:.1%}**",
                 f"- surface − against: median **{al['median']:+.2f} ft**, "
                 f"mean {al['mean']:+.2f}, sd {al['sd']:.2f}, "
                 f"range {al['min']:+.2f} … {al['max']:+.2f}", "",
                 "No volumes are computed: a difference between two plan "
                 "surfaces is not an earthwork pay quantity."]
        if s["zones"]:
            lines += ["", "## Zones", "", "| zone | n | median (ft) | within tol |",
                      "|---|---|---|---|"]
            for name, z in s["zones"].items():
                med = "—" if z["median"] is None else f"{z['median']:+.2f}"
                tol = "—" if z["within_tie_tol"] is None else f"{z['within_tie_tol']:.0%}"
                lines.append(f"| {name} | {z['n']} | {med} | {tol} |")
        Path(args.report).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {args.report}")
    return 0


def _positive_float(text):
    """argparse type: a finite number > 0."""
    try:
        v = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}") from None
    if not 0 < v < float("inf"):
        raise argparse.ArgumentTypeError(f"must be > 0 (got {text})")
    return v


def _positive_int(text):
    """argparse type: an integer > 0."""
    try:
        v = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}") from None
    if v <= 0:
        raise argparse.ArgumentTypeError(f"must be > 0 (got {text})")
    return v


def _ocg_glob(spec):
    """``ocg:GLOB`` (or a bare glob) -> the glob; None stays None."""
    if not spec:
        return None
    return spec[4:] if spec.startswith("ocg:") else spec


#: what label-crops writes, and so may clear from a previous run: crops
#: L/S + 3 or more digits, the contact sheet and its page PNGs
_LABEL_CROPS_OUTPUT = r"(?:[LS][0-9]{3,}\.png|contact-sheet\.pdf|contact-sheet-[0-9]{2,}\.png)"


def _run_label_crops(args) -> int:
    """Label candidates -> centred crops, a contact sheet, an anchors skeleton."""
    import re
    from pathlib import Path

    import yaml

    from bimforge.bim.plansheet.labels import find_candidates

    sources = tuple(s.strip() for s in args.sources.split(",") if s.strip())
    if not sources or set(sources) - {"mask", "gap", "layer"}:
        print(f"error: --sources takes mask, gap and layer (got "
              f"{args.sources!r})", file=sys.stderr)
        return 1
    header = ("# Anchors skeleton written by est-bim label-crops. Read each crop\n"
              "# in the out-dir (the candidate is at its centre) and fill elev;\n"
              "# leave elev: null where there is no label. vertical_datum is\n"
              "# REQUIRED (the sheet's benchmark datum). Never guess a value.\n"
              "# nearest_line is the manifest line index (across layers, in\n"
              "# order); the contour-surface report names each label by its id.\n")
    doc = None
    try:
        import fitz
        manifest = json.loads(Path(args.contours).read_text(encoding="utf-8"))
        if manifest.get("sheet") not in (None, args.sheet):
            raise ValueError(f"the manifest is for sheet {manifest.get('sheet')}, "
                             f"not {args.sheet}")
        doc = fitz.open(args.pdf)
        if not 0 <= args.sheet - 1 < doc.page_count:
            raise ValueError(f"sheet {args.sheet} is out of range (document has "
                             f"{doc.page_count} pages)")
        page = doc[args.sheet - 1]
        labels, spots = find_candidates(
            page.get_drawings(), manifest, sources=sources,
            labels_glob=_ocg_glob(args.labels), spots_glob=_ocg_glob(args.spots))

        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        removed = 0
        for p in out.iterdir():
            if p.is_file() and re.fullmatch(_LABEL_CROPS_OUTPUT, p.name):
                p.unlink()
                removed += 1
        if removed:
            print(f"removed {removed} stale output(s) from a previous run",
                  file=sys.stderr)
        tiles, contours, spot_recs = [], [], []
        for prefix, cands, recs in (("L", labels, contours),
                                    ("S", spots, spot_recs)):
            for k, c in enumerate(cands, start=1):
                cid = f"{prefix}{k:03d}"
                # get_pixmap clips in the rotated (visual) frame
                page.get_pixmap(clip=fitz.Rect(c.bbox) * page.rotation_matrix,
                                dpi=args.dpi).save(str(out / f"{cid}.png"))
                rec = {"id": cid,
                       "page": [round(c.page[0], 1), round(c.page[1], 1)],
                       "elev": None}
                if prefix == "L":
                    rec.update({"source": c.source, "nearest_line": c.line,
                                "dist_ft": c.dist_ft, "margin_ft": c.margin_ft})
                recs.append(rec)
                tiles.append((cid, f"{cid} · {c.source}"
                              + ("" if c.line is None else f" · line {c.line}")))
        from bimforge.bim.plansheet.review import contact_sheet
        sheet_pdf = contact_sheet(tiles, out)

        skeleton = {"sheet": args.sheet, "vertical_datum": None,
                    "interval_ft": None, "index_interval_ft": None,
                    "contours": contours, "spots": spot_recs}
        Path(args.anchors).write_text(
            header + yaml.safe_dump(skeleton, sort_keys=False), encoding="utf-8")
    except (OSError, ValueError, RuntimeError, KeyError,
            json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if doc is not None:
            doc.close()
    by: dict = {}
    for c in labels:
        by[c.source] = by.get(c.source, 0) + 1
    where = sheet_pdf.name if sheet_pdf else "no contact sheet"
    print(f"{len(labels)} label candidate(s) ("
          f"{', '.join(f'{k} {v}' for k, v in sorted(by.items())) or 'none'}), "
          f"{len(spots)} spot marker(s) -> {out}/ ({where}) and {args.anchors}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="est-bim")
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sample", help="generate the sample plan DXF")
    s.add_argument("--dir", default=".", help="output directory (default: .)")
    s.add_argument("--name", default="sample_plan.dxf", help="DXF filename")
    s.add_argument("--with-configs", action="store_true",
                   help="also write the example layer/takeoff maps")

    d = sub.add_parser("dxf2bim", help="author an IFC from a DXF + layer map")
    d.add_argument("--dxf", required=True, help="input DXF file")
    d.add_argument("--config", required=True, help="layer-map YAML")
    d.add_argument("--out", default="model.ifc", help="output IFC path")

    x = sub.add_parser("ifc2dxf", help="flatten an IFC (ours or a foreign "
                       "Tekla/Revit export) into a plan-view takeoff DXF")
    x.add_argument("--ifc", required=True, help="input IFC file")
    x.add_argument("--out", help="output DXF path (default: <ifc stem>.plan.dxf)")
    x.add_argument("--include", help="comma-separated IFC classes to keep "
                                     "(subtypes match)")
    x.add_argument("--exclude", help="comma-separated IFC classes to drop "
                                     "(wins over --include)")
    x.add_argument("--simplify-ft", dest="simplify_ft", type=float, default=0.0,
                   help="ring decimation tolerance in feet (default: off)")
    x.add_argument("--sidecar", help="QC sidecar JSON path "
                                     "(default: <out>.sidecar.json)")

    gis = sub.add_parser("ifc2gis", help="export georeferenced IFC(s) into a "
                         "true-3D, QGIS-consumable GeoPackage")
    gis.add_argument("--ifc", required=True, nargs="+",
                     help="one or more input IFC files (each -> its own layer)")
    gis.add_argument("--out", help="output .gpkg path (default: <ifc stem>.gpkg, "
                                   "or model.gpkg for multiple inputs)")
    gis.add_argument("--index", help="a locations/index IFC (geometry-less "
                                     "elements carrying property sets) whose "
                                     "semantics join onto the matching detailed "
                                     "geometry by name")
    gis.add_argument("--index-pset", dest="index_pset",
                     help="restrict the index join to this property-set name "
                          "(default: merge every set)")
    gis.add_argument("--tin", action="store_true",
                     help="emit OGC-valid TIN Z solids instead of MultiPolygon Z")

    va = sub.add_parser("validate",
                        help="open + schema-validate an IFC and report "
                             "element counts per class (exit 1 on issues)")
    va.add_argument("ifc", help="input IFC file")

    t = sub.add_parser("takeoff", help="roll an IFC up into a CanonicalTakeoff")
    t.add_argument("--ifc", required=True, help="input IFC file")
    t.add_argument("--map", help="takeoff_map YAML (pay units, item numbers)")
    t.add_argument("--out", default="takeoff.json", help="output JSON path")
    t.add_argument("--csv", help="also write a CSV for eyeballing")

    sf = sub.add_parser("sfca",
                        help="classify an IFC's tessellated faces into "
                             "top/bottom/side (SFCA) + volume, per element")
    sf.add_argument("ifc", help="input IFC file")
    sf.add_argument("--flat", type=float, default=0.85,
                    help="|nz| above this is a top/bottom face; below, side "
                         "— battered faces measured on the true slope "
                         "(default 0.85)")
    sf.add_argument("--split-el", dest="split_el", type=float, default=None,
                    help="elevation (ft, model frame) splitting side area: "
                         "the part below is reported as buried (a subset of "
                         "side, flagged not deducted)")
    sf.add_argument("--skip-class", dest="skip_class",
                    default="IfcPipeSegment,IfcDistributionChamberElement,"
                            "IfcSite,IfcGeographicElement",
                    help="comma-separated IFC classes to exclude, subtypes "
                         "match (default: pipe barrels/chambers — "
                         "penetrations, not concrete — plus site/terrain "
                         "reference meshes, which would silently inflate "
                         "the totals)")

    sc = sub.add_parser("schedule",
                        help="embed a schedule (gw.json/…) into an IFC as IfcWorkSchedule")
    sc.add_argument("--ifc", required=True, help="input IFC file (from dxf2bim)")
    sc.add_argument("--schedule", required=True, dest="schedule",
                    help="schedule file (GanttWarrior .gw.json; XER/MSPDI later)")
    sc.add_argument("--task-map", dest="task_map",
                    help='JSON {"<task id|wbs>": ["<bid_item_code>", …]} — '
                         "wins over --name-code-re")
    sc.add_argument("--name-code-re", dest="name_code_re",
                    help="regex; first capture group per match extracts bid "
                         "item codes from each task name")
    sc.add_argument("--name", dest="schedule_name",
                    help="IfcWorkSchedule name (default: the schedule's own name)")
    sc.add_argument("--out", help="output IFC path (default: alongside the input, "
                                  "<stem>.4d.ifc)")

    sr = sub.add_parser("schedule-read",
                        help="read a 4D IFC's IfcWorkSchedule back into "
                             "CanonicalSchedule JSON (+ quantities per task)")
    sr.add_argument("--ifc", required=True, help="4D IFC file")
    sr.add_argument("--schedule", dest="schedule_name",
                    help="IfcWorkSchedule name (default: the file's only one)")
    sr.add_argument("--out", required=True, help="CanonicalSchedule JSON path")
    sr.add_argument("--takeoff-map", dest="takeoff_map",
                    help="takeoff map YAML; with --takeoff-out writes the "
                         "takeoff with each row split across the tasks")
    sr.add_argument("--takeoff-out", dest="takeoff_out",
                    help="takeoff-by-task JSON path (needs --takeoff-map)")
    sr.add_argument("--costs-out", dest="costs_out",
                    help="5D: per-task costs + labor JSON (needs the "
                         "est-bim cost5d cost schedule)")

    c5 = sub.add_parser("cost5d", help="embed cost + labor resources into a 4D IFC")
    c5.add_argument("--ifc", required=True)
    c5.add_argument("--schedule", required=True, dest="schedule")
    c5.add_argument("--costs", required=True)
    c5.add_argument("--task-map", dest="task_map", default=None)
    c5.add_argument("--name-code-re", dest="name_code_re", default=None)
    c5.add_argument("--schedule-name", dest="schedule_name", default=None)
    c5.add_argument("--work-hours-per-day", dest="work_hours_per_day",
                    type=float, default=8.0)
    c5.add_argument("--out", default=None)

    e5 = sub.add_parser("estimate5d",
                        help="embed a quantity-backed ESTIMATE cost schedule "
                             "(CostQuantities reference the elements' own Qtos)")
    e5.add_argument("--ifc", required=True)
    e5.add_argument("--map", required=True,
                    help="the takeoff map yaml est-bim takeoff reads")
    e5.add_argument("--costs", required=True,
                    help="costs.json with unit_price (and optional unit) per code")
    e5.add_argument("--name", default=None,
                    help="schedule base name (default: the map's project_ref)")
    e5.add_argument("--out", help="output IFC path (default: alongside the "
                                  "input, <stem>.est.ifc)")

    me = sub.add_parser("model-elements",
                        help="plan BidSheet.ai upsert_modelled_elements "
                             "entries (GlobalId + Qto quantities in the "
                             "key's unit) from an IFC")
    me.add_argument("ifc", help="input IFC file")
    me.add_argument("--items",
                    help="JSON {bid item code: estimate item id} — or a "
                         "get_estimate_model document (its items[])")
    me.add_argument("--estimate-id", dest="estimate_id", type=int,
                    help="BidSheet.ai estimate id, carried into the payload")
    me.add_argument("--complete", action="store_true",
                    help="mark the payload as the full model (BidSheet.ai "
                         "then reports modelled elements it lacks)")
    me.add_argument("--structure-id", dest="structure_id",
                    help="structure id for every element (default: none)")
    me.add_argument("--structure-ids", dest="structure_ids",
                    help="JSON {classification code: structure id}")
    me.add_argument("--form-area", dest="form_area",
                    help="the Qto quantity holding the formed area "
                         "(Qto_Set.Name, or a bare name) -> form_contact_sf; "
                         "never inferred")
    me.add_argument("--schedule",
                    help="match --items only against this schedule label "
                         "(get_estimate_model items[].schedule)")
    me.add_argument("--all-elements", dest="all_elements",
                    action="store_true",
                    help="also send unclassified, untyped elements and "
                         "beams/members/plates/courses/pavements, as generic "
                         "(their volume is stored as concrete_cy)")
    me.add_argument("--out", help="output JSON (default: stdout)")

    em = sub.add_parser("estimate-model",
                        help="embed a BidSheet.ai get_estimate_model document "
                             "as IfcTask / IfcCostItem / IfcLaborResource")
    em.add_argument("ifc", help="input IFC file")
    em.add_argument("model", help="get_estimate_model JSON")
    em.add_argument("out", help="output IFC path")
    em.add_argument("--schedule-name", dest="schedule_name",
                    help='work schedule name (default "BidSheet.ai estimate '
                         '<id>"; the cost schedule is "<name> cost")')
    em.add_argument("--placeholders", action="store_true",
                    help="add an IfcBuildingElementProxy (no geometry) for "
                         "each model element the IFC lacks, under its GlobalId")

    k = sub.add_parser("kml", help="convert a georeferenced IFC into 3D KML (Google Earth)")
    k.add_argument("ifc", help="input IFC file (georeferenced, est-bim >= 0.1.11)")
    k.add_argument("--out", help="output KML path (default: alongside the IFC)")
    k.add_argument("--schedule", action="store_true",
                   help="stamp each element with a TimeSpan from its embedded "
                        "IfcWorkSchedule task (run `est-bim schedule` first) so "
                        "Google Earth's time slider plays the construction staging")
    k.add_argument("--massing", action="store_true",
                   help="draw each element as its bounding-box block instead of "
                        "the full triangle mesh — for detailed models whose "
                        "per-triangle KML is too large for Google Earth to open")
    k.add_argument("--geoid-shift-m", type=float, dest="geoid_shift_m",
                   metavar="METRES",
                   help="NAVD88 -> EGM96 separation, added to every altitude "
                        "on top of the datum height already taken from "
                        "IfcMapConversion.OrthogonalHeight. Google Earth "
                        "reads absolute altitude above EGM96; derive the "
                        "value once with bimforge.terrain.datum.geoid_shift_m "
                        "and pin it here")

    z = sub.add_parser("kmz", help="convert a georeferenced IFC into a KMZ for "
                                   "Google Earth web (polygon KML; --collada "
                                   "for the Earth Pro COLLADA model)")
    z.add_argument("ifc", help="input IFC file (georeferenced, est-bim >= 0.1.11)")
    z.add_argument("--out", help="output KMZ path (default: alongside the IFC; "
                                 ".glb with --gltf)")
    zmode = z.add_mutually_exclusive_group()
    zmode.add_argument("--collada", action="store_true",
                       help="write the COLLADA <Model> KMZ instead (Google "
                            "Earth Pro only; Earth web rejects <Model>)")
    zmode.add_argument("--gltf", action="store_true",
                       help="write ONLY a .glb (Cesium escape hatch; no KMZ)")
    z.add_argument("--geoid-shift-m", type=float, dest="geoid_shift_m",
                   metavar="METRES",
                   help="NAVD88 -> EGM96 separation added to every altitude "
                        "(as `est-bim kml --geoid-shift-m`)")
    z.add_argument("--massing", action="store_true",
                   help="web KMZ: bounding-box blocks instead of the full mesh "
                        "(for models over Earth web's 250,000-vertex limit)")
    z.add_argument("--omit", metavar="REGEX",
                   help="web KMZ: leave out elements whose name matches "
                        "(reference geometry, e.g. an existing-ground mesh)")

    c = sub.add_parser("calibrate",
                       help="derive a plan sheet's page->world calibration (sheet-calibration.yaml)")
    c.add_argument("--pdf", required=True, help="plan-set PDF")
    c.add_argument("--sheet", required=True, type=int, help="PDF page number (1-based)")
    c.add_argument("--zone", action="append", metavar="NAME:X0,Y0,X1,Y1",
                   help="add a view zone (unrotated page points); default: one full-page zone")
    c.add_argument("--ft-per-pt", type=float, dest="ft_per_pt",
                   help="manual scale override (feet per page point)")
    c.add_argument("--scale", help='manual scale override, e.g. "1/4in=1ft" or "1in=40ft"')
    c.add_argument("--alignment", help="alignment YAML (bearing+ties+EPSG) passed through verbatim")
    c.add_argument("--min-path-pt", type=float, default=2.0, dest="min_path_pt",
                   help="drop drawing paths shorter than this (hatch noise; default 2.0 pt)")
    c.add_argument("--render", metavar="PNG",
                   help="also render the page to PNG (prints the pt-per-pixel "
                        "factor for locating hints)")
    c.add_argument("--dpi", type=int, default=150,
                   help="render resolution (default 150)")
    c.add_argument("--hints",
                   help="vision hints YAML: what the flattened lettering says "
                        "(agent-read; validated against vector geometry)")
    c.add_argument("--evidence", metavar="JSON",
                   help="write the machine-readable evidence report here "
                        "(always printed on exit 2)")
    c.add_argument("--out", help="write the calibration YAML here")

    v = sub.add_parser("vectors",
                       help="dump extracted vector paths as a world-feet DXF (tracing surface)")
    v.add_argument("--pdf", required=True, help="plan-set PDF")
    v.add_argument("--sheet", type=int, help="PDF page number (1-based; checked against --calib)")
    v.add_argument("--calib", required=True, help="sheet-calibration YAML from `est-bim calibrate`")
    v.add_argument("--zone", dest="zone_name", help="zone name (default: first zone)")
    v.add_argument("--min-path-pt", type=float, default=2.0, dest="min_path_pt",
                   help="drop drawing paths shorter than this (default 2.0 pt)")
    v.add_argument("--classes",
                   help="dash-pattern feature classes YAML (layers become "
                        "V-<CLASS>; see plansheet/classes.example.yaml)")
    v.add_argument("--regions", action="store_true",
                   help="also chain segments into closed regions "
                        "(V-REGION-<class> layers, sorted by area)")
    v.add_argument("--regions-json", dest="regions_json", metavar="JSON",
                   help="write the region list (areas, centroids, points) here")
    v.add_argument("--out", required=True, help="output DXF path")

    m = sub.add_parser("measure",
                       help="snap agent traces to the vectors and write the takeoff-mapped DXF")
    m.add_argument("--pdf", required=True, help="plan-set PDF")
    m.add_argument("--sheet", type=int, help="PDF page number (1-based; checked against --calib)")
    m.add_argument("--calib", required=True, help="sheet-calibration YAML")
    m.add_argument("--traces", required=True,
                   help='traces JSON: {"layers": {"S-DECK": [{"closed": true, "points": [[x,y],...]}]}}')
    m.add_argument("--layer-map", required=True, dest="layer_map",
                   help="dxf2bim layer-map YAML (trace layers must exist in it)")
    m.add_argument("--tol", type=float, default=0.15,
                   help="snap tolerance in feet (default 0.15)")
    m.add_argument("--allow-unsnapped", action="store_true",
                   help="exit 0 even when vertices found no vector within --tol")
    m.add_argument("--min-path-pt", type=float, default=2.0, dest="min_path_pt",
                   help="drop drawing paths shorter than this (default 2.0 pt)")
    m.add_argument("--hints",
                   help="vision hints YAML — kind=dimension hints feed the "
                        "cross-check on flattened sheets")
    m.add_argument("--report", metavar="MD",
                   help="write the QC cross-check report (markdown table) here")
    m.add_argument("--qc-tol", type=float, default=0.5, dest="qc_tol",
                   help="cross-check tolerance in percent (default 0.5; above "
                        "it a row is REVIEW)")
    m.add_argument("--out", required=True, help="output takeoff DXF path")
    m.add_argument("--sidecar", help="provenance sidecar JSON path")

    co = sub.add_parser(
        "contours",
        help="extract contour polylines off a flattened plan sheet "
             "(pen-style selectors -> world-feet DXF + JSON manifest)")
    co.add_argument("--pdf", required=True, help="plan-set PDF")
    co.add_argument("--sheet", required=True, type=int,
                    help="PDF page number (1-based)")
    co.add_argument("--calib",
                    help="sheet-calibration YAML from `est-bim calibrate`")
    co.add_argument("--zone", dest="zone_name",
                    help="calibration zone name (default: first zone)")
    co.add_argument("--layer", action="append", default=[],
                    metavar="NAME=GREY[@W]|NAME=ocg:GLOB",
                    help="selector -> output layer C-NAME: a pen style, or a "
                         "glob over the PDF's CAD layer (OCG) names, e.g. "
                         "'EXIST=ocg:*|C-TOPO-M*R-N'; repeatable (profile "
                         "first)")
    co.add_argument("--min-length", type=float, default=20.0,
                    dest="min_length",
                    help="drop polylines shorter than this, world feet "
                         "(default 20)")
    co.add_argument("--gap", type=float, default=0.0, metavar="PT",
                    help="re-stitch a dashed linetype across gaps up to this "
                         "many page points (default 0 = off)")
    co.add_argument("--gap-angle", type=float, default=25.0, dest="gap_angle",
                    metavar="DEG",
                    help="max direction change across a --gap jump "
                         "(default 25)")
    co.add_argument("--min-path-pt", type=float, default=2.0,
                    dest="min_path_pt",
                    help="drop source paths shorter than this, page points "
                         "(default 2)")
    co.add_argument("--tie", action="append", default=[],
                    metavar="PX,PY=N,E",
                    help="survey tie page point -> northing,easting; two or "
                         "more switch output to state-plane feet")
    co.add_argument("--surface", action="append", default=[],
                    metavar="NAME=existing|proposed",
                    help="tag a --layer's surface (manifest v2); repeatable")
    co.add_argument("--role", action="append", default=[],
                    metavar="NAME=index|intermediate",
                    help="tag a --layer's contour role (manifest v2); repeatable")
    co.add_argument("--tie-model", choices=["similarity", "affine"],
                    default="similarity", dest="tie_model",
                    help="tie fit: similarity (>=2 ties) or affine (>=3 ties, "
                         "absorbs paper stretch); default similarity")
    co.add_argument("--viewport", type=int, default=None,
                    help="GeoPDF viewport index when the page carries several")
    co.add_argument("--geopdf-bbox", choices=["viewport", "page"],
                    default="viewport", dest="geopdf_bbox",
                    help="use the viewport's /BBox (default) or the page "
                         "MediaBox — the repair when the scale gate trips")
    co.add_argument("--no-geopdf", action="store_true", dest="no_geopdf",
                    help="ignore the page's GeoPDF viewport")
    co.add_argument("--clip", default=None, metavar="x0,y0,x1,y1",
                    help="clip picked paths to this page rectangle (unrotated "
                         "points): a crossing contour is CUT at the edge, a "
                         "title-block glyph outside the plan view is dropped")
    co.add_argument("--max-residual-ft", type=float, default=None,
                    dest="max_residual_ft",
                    help="exit 2 when the georeference's worst residual "
                         "exceeds this, ft")
    co.add_argument("--crs-epsg", type=_positive_int, default=None, dest="crs_epsg",
                    help="horizontal CRS (EPSG) to stamp on a --tie manifest — "
                         "ties give coordinates but no CRS; contour-surface/"
                         "terrain-ifc need it to place the TIN in a model. "
                         "Inherited from an agreeing GeoPDF viewport when one "
                         "covers the ties")
    co.add_argument("--profile", action="store_true",
                    help="print the sheet triage (vector/raster, GeoPDF "
                         "viewports), the OCG table, then the pen table, "
                         "and exit")
    co.add_argument("--out", help="output DXF path")
    co.add_argument("--json", dest="json_out",
                    help="output polyline manifest (JSON); with neither "
                         "--out nor --json the manifest prints to stdout")

    cs = sub.add_parser(
        "contour-surface",
        help="labelled contour manifests -> existing-ground TIN npz + "
             "spot scorecard (held out, or leave-one-out with --spot-pins "
             "--propagate)")
    cs.add_argument("--contours", nargs="+", required=True,
                    help="est-bim contours JSON manifest(s)")
    cs.add_argument("--anchors", required=True,
                    help="anchors YAML: vertical_datum (required), "
                         "interval_ft, optional index_interval_ft and sheet, "
                         "contours/spots: [{elev, xy|page}] — page records "
                         "are placed by --tie or the v2 manifest's georef; "
                         "elev: null records are unread and skipped")
    cs.add_argument("--spots",
                    help="spot elevations YAML — the scorecard (held out; "
                         "with --spot-pins also a consistency check on the "
                         "contours, scored leave-one-out when --propagate is "
                         "on too); never TIN vertices")
    cs.add_argument("--tie", action="append", default=[],
                    metavar="PX,PY=N,E",
                    help="ties to place page-coordinate anchors (use the "
                         "same ties as the extraction)")
    cs.add_argument("--layers", nargs="*", default=[],
                    help="only these manifest layers")
    cs.add_argument("--surface", choices=["existing", "proposed"],
                    default=None,
                    help="the surface this run builds (default: the manifest "
                         "layers' surface tag, else existing); sets the DXF "
                         "layer prefix EG- / FG-")
    cs.add_argument("--include-review", action="store_true",
                    dest="include_review",
                    help="also use the REVIEW layer (low-confidence raster "
                         "lines; skipped by default)")
    cs.add_argument("--max-label-dist", type=float, default=6.0,
                    dest="max_label_dist",
                    help="max label->contour distance, ft (default 6)")
    cs.add_argument("--propagate", action="store_true",
                    help="also assign unlabelled contours by neighbour "
                         "counting (tier: inferred; off by default)")
    cs.add_argument("--interval", type=float, default=None,
                    help="contour interval, ft (default: the anchors file's "
                         "interval_ft, else 1)")
    cs.add_argument("--snap-tol", type=float, default=0.35, dest="snap_tol",
                    help="reject an inferred contour when interpolating "
                         "between the two lettered contours that bracket it "
                         "misses its interval by more than this, ft "
                         "(default 0.35)")
    cs.add_argument("--merge-gap", type=float, default=0.0, dest="merge_gap",
                    metavar="FT",
                    help="rejoin contour fragments across gaps up to this, "
                         "world ft (default 0 = off)")
    cs.add_argument("--merge-angle", type=float, default=15.0,
                    dest="merge_angle", metavar="DEG",
                    help="max direction change across a --merge-gap join "
                         "(default 15)")
    cs.add_argument("--thin", type=float, default=8.0,
                    help="min spacing between kept contour vertices, ft "
                         "(default 8)")
    cs.add_argument("--max-edge", type=float, default=250.0, dest="max_edge",
                    help="drop TIN triangles with an edge longer than this, "
                         "ft (default 250)")
    cs.add_argument("--max-rmse", type=float, default=None, dest="max_rmse",
                    help="exit 2 when the spot RMSE (held out, or "
                         "leave-one-out with --spot-pins --propagate) exceeds "
                         "this, ft "
                         "(or when the surface is unscored)")
    cs.add_argument("--contact-ft", type=float, default=0.5, dest="contact_ft",
                    metavar="FT",
                    help="contours closer than this are in contact: never "
                         "neighbours, and a finding where they touch or cross; "
                         "also how close a merge join may pass another line "
                         "(default 0.5)")
    cs.add_argument("--strict", action="store_true",
                    help="exit 2 when there is any finding (after writing "
                         "every output)")
    cs.add_argument("--spot-pins", action="store_true", dest="spot_pins",
                    help="check the contours against the spot elevations: a "
                         "spot limits its nearest line to within one "
                         "interval, and one that contradicts the labels is a "
                         "conflict finding. It narrows the reported ranges "
                         "but never adds a contour to the TIN (it can "
                         "withdraw one); with --propagate the scorecard "
                         "becomes leave-one-out")
    cs.add_argument("--review-dir", dest="review_dir", metavar="DIR",
                    help="write review.md, findings.json and lines.csv here "
                         "(plus an overlay crop per finding and a contact "
                         "sheet with --pdf); a previous run's review files "
                         "are cleared")
    cs.add_argument("--pdf", help="the plan PDF the manifests came from "
                                  "(sheet N is page N): overlay crops for "
                                  "the review (needs --review-dir)")
    cs.add_argument("--review-crop-ft", type=float, default=80.0,
                    dest="review_crop_ft", metavar="FT",
                    help="crop window around a finding, world ft (default "
                         "80; a conflict widens to its lines, up to 3x)")
    cs.add_argument("--dpi", type=int, default=300,
                    help="review crop resolution (default 300)")
    cs.add_argument("--out", required=True,
                    help="output TIN .npz (points + simplices + JSON info; "
                         "no pickle)")
    cs.add_argument("--dxf",
                    help="also write a DXF (3D contours by tier + TIN faces "
                         "+ spots)")
    cs.add_argument("--report", help="markdown build/score report path")

    td = sub.add_parser(
        "terrain-diff",
        help="difference a plan-frame surface against a terrain grid cache "
             "on one datum (plan minus terrain)")
    td.add_argument("--surface", required=True,
                    help="surface points: whitespace XYZ, comma CSV, or a "
                         "contour-TIN .npz")
    td_mode = td.add_mutually_exclusive_group(required=True)
    td_mode.add_argument("--grid",
                         help="terrain grid .npz cache (bimforge.terrain.fetch "
                              "format, NAVD88 metres)")
    td_mode.add_argument("--against",
                         help="a second contour-TIN .npz: compare --surface "
                              "(also a TIN .npz) against it, surface minus "
                              "against, in feet — not a pay quantity")
    td.add_argument("--step", type=_positive_float, default=5.0,
                    help="--against sampling grid spacing, ft (default 5)")
    td.add_argument("--tie-tol", type=_positive_float, default=0.5,
                    dest="tie_tol",
                    help="--against: agreement tolerance for the tie-in "
                         "share, ft (default 0.5)")
    td.add_argument("--zones",
                    help="--against: YAML {zones: [{name, polygon: [[x, y], "
                         "...]}]} in world ft for per-zone statistics")
    td.add_argument("--report", help="--against: markdown report path")
    td.add_argument("--vshift-json", dest="vshift_json",
                    help="cached NCAT shift JSON (project vertical datum -> "
                         "NAVD88, metres; see bimforge.terrain.datum)")
    td.add_argument("--units", choices=["ftUS", "ft", "m"], default="ftUS",
                    help="surface units (default ftUS)")
    td.add_argument("--csv", help="write per-point differences here")
    td.add_argument("--png",
                    help="write a difference map here (matplotlib — the "
                         "[draw] extra; skipped with a log line when absent)")

    lc = sub.add_parser(
        "label-crops",
        help="find every contour label on a sheet -> centred crops, a "
             "contact sheet and an anchors skeleton for the reader")
    lc.add_argument("--contours", required=True,
                    help="the sheet's v2 contours manifest (est-bim contours "
                         "--json); extract every contour class with a small "
                         "--min-length first — a label mask is only found "
                         "over a line the manifest carries")
    lc.add_argument("--pdf", required=True, help="plan-set PDF")
    lc.add_argument("--sheet", required=True, type=int,
                    help="PDF page number (1-based)")
    lc.add_argument("--sources", default="mask,gap",
                    help="label sources: mask, gap, layer (default mask,gap)")
    lc.add_argument("--labels", metavar="ocg:GLOB",
                    help="also look for glyph clusters on this label layer, "
                         "e.g. 'ocg:*SURF-LABL*' (adds the layer source)")
    lc.add_argument("--spots", metavar="ocg:GLOB",
                    help="spot-elevation marker layer, e.g. 'ocg:Topo|E_SPOT'")
    lc.add_argument("--dpi", type=int, default=300,
                    help="crop resolution (default 300)")
    lc.add_argument("--out-dir", required=True, dest="out_dir",
                    help="directory for the crops and the contact sheet")
    lc.add_argument("--anchors", required=True,
                    help="anchors skeleton YAML to write (elev: null)")

    b = sub.add_parser("build", help="build a registered structure family from "
                                     "a spec YAML (model -> gate -> emitters)")
    b.add_argument("spec", help="build spec YAML (family/params/paycodes/"
                                "outputs/project)")
    b.add_argument("--check-only", action="store_true", dest="check_only",
                   help="run the pre-emit validation gate and exit; write nothing")

    args = parser.parse_args(argv)
    try:
        if args.cmd == "sample":
            return _run_sample(args)
        if args.cmd == "dxf2bim":
            return _run_dxf2bim(args)
        if args.cmd == "ifc2dxf":
            return _run_ifc2dxf(args)
        if args.cmd == "ifc2gis":
            return _run_ifc2gis(args)
        if args.cmd == "validate":
            return _run_validate(args)
        if args.cmd == "takeoff":
            return _run_takeoff(args)
        if args.cmd == "sfca":
            return _run_sfca(args)
        if args.cmd == "schedule":
            return _run_schedule(args)
        if args.cmd == "schedule-read":
            return _run_schedule_read(args)
        if args.cmd == "cost5d":
            return _run_cost5d(args)
        if args.cmd == "estimate5d":
            return _run_estimate5d(args)
        if args.cmd == "model-elements":
            return _run_model_elements(args)
        if args.cmd == "estimate-model":
            return _run_estimate_model(args)
        if args.cmd == "kml":
            return _run_kml(args)
        if args.cmd == "kmz":
            return _run_kmz(args)
        if args.cmd == "calibrate":
            return _run_calibrate(args)
        if args.cmd == "vectors":
            return _run_vectors(args)
        if args.cmd == "measure":
            return _run_measure(args)
        if args.cmd == "contours":
            return _run_contours(args)
        if args.cmd == "contour-surface":
            return _run_contour_surface(args)
        if args.cmd == "terrain-diff":
            return _run_terrain_diff(args)
        if args.cmd == "label-crops":
            return _run_label_crops(args)
        if args.cmd == "build":
            from bimforge.author.families.registry import build_from_spec
            try:
                return build_from_spec(args.spec, check_only=args.check_only)
            except (OSError, ValueError, KeyError) as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
    except ImportError as exc:
        # The subcommand imports pull in the bim extra's heavy deps lazily;
        # a bare traceback here would just mean "not installed".
        print(
            f"error: missing BIM dependency ({exc.name or exc}); install with:\n"
            '  pip install "bimforge[all]"',
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
