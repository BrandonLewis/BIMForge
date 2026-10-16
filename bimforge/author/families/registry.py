"""Family registry + est-bim build spec loading/orchestration (spec §4).

The spec file:

    family: pipe-supports
    params: { ...family-specific, cites plan sheets... }
    paycodes: ./paycodes.yaml
    outputs: {dxf: CAD/x.dxf, ifc: CAD/x.ifc,
              takeoff_map: CAD/x-takeoff-map.yaml,
              qto: CAD/x-QTO.xlsx, step: null,
              ifc_allow_local: false}
    project: {name: "...", epsg: 2226, base: [.., ..], guid_ns: "<uuid>",
              schema: IFC4X3_ADD2,                       # optional (#318:
              facility: {kind: bridge, predefined_type: GIRDER}}  # 4X3 only)
    spatial_parts:          # optional: element-name regex -> facility part
      - {match: "(?i)abut", part: ABUTMENT}

The dispatcher is NOT a geometry language: a family is python; the spec is
parameters. Orchestration: spec -> family.build -> paycodes.apply -> gate
pre (refuse-to-write; --check-only stops here) -> emitters -> gate post
(verify-and-delete).
"""
from __future__ import annotations

from pathlib import Path

import yaml

FAMILY_GROUP = "bimforge.families"


def _shipped():
    from bimforge.author.families import (
        approach_slab, box_culvert, bridge_standard, concrete_barrier_732sw,
        concrete_barrier_842, culvert_headwall,
        culvert_wingwall, demo_box, headwall_926, pipe_headwall, pipe_supports,
        spillway, standard_plan, tubular_handrail)
    return {
        "demo-box": demo_box.build,
        "pipe-supports": pipe_supports.build,
        "standard-plan": standard_plan.build,
        "headwall-926": headwall_926.build,
        "spillway": spillway.build,
        "box-culvert": box_culvert.build,
        "pipe-headwall": pipe_headwall.build,
        "bridge-standard": bridge_standard.build,
        "culvert-wingwall": culvert_wingwall.build,
        "culvert-headwall": culvert_headwall.build,
        "tubular-handrail": tubular_handrail.build,
        "concrete-barrier-732sw": concrete_barrier_732sw.build,
        "concrete-barrier-842": concrete_barrier_842.build,
        "approach-slab": approach_slab.build,
    }


def available() -> dict:
    """name -> builder, shipped + entry-point registered (external wins ties
    are NOT allowed: a collision is an error, not a shadow)."""
    out = dict(_shipped())
    from importlib.metadata import entry_points
    for ep in entry_points(group=FAMILY_GROUP):
        if ep.name in out:
            raise ValueError(f"family {ep.name!r} from {ep.value} collides "
                             f"with a shipped family")
        out[ep.name] = ep.load()
    return out


def get(name: str):
    fams = available()
    if name not in fams:
        raise KeyError(f"unknown family {name!r} (available: {sorted(fams)})")
    return fams[name]


REQUIRED_SPEC_KEYS = ("family", "params", "paycodes", "outputs", "project")
OUTPUT_KEYS = ("dxf", "ifc", "takeoff_map", "qto", "step", "bbs")


def load_spec(path: Path | str) -> dict:
    """Parse + validate a build spec; relative paths resolve from the spec."""
    path = Path(path)
    spec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    missing = [k for k in REQUIRED_SPEC_KEYS if not spec.get(k)]
    if missing:
        raise ValueError(f"{path.name}: missing spec keys {missing}")
    outs = spec["outputs"]
    unknown = set(outs) - set(OUTPUT_KEYS) - {"ifc_allow_local"}
    if unknown:
        raise ValueError(f"{path.name}: unknown outputs keys {sorted(unknown)}")
    if not any(outs.get(k) for k in OUTPUT_KEYS):
        raise ValueError(f"{path.name}: outputs names no files to write")
    base = path.parent
    spec["paycodes"] = str((base / spec["paycodes"]).resolve())
    spec["outputs"] = {k: (str((base / v).resolve()) if isinstance(v, str) else v)
                       for k, v in outs.items()}
    params = spec.get("params") or {}
    tf = params.get("tables_file")
    if tf:
        tf_path = (base / tf).resolve()
        if not tf_path.exists():
            raise ValueError(f"{path.name}: tables_file {tf!r} not found "
                             f"at {tf_path}")
        params["tables"] = yaml.safe_load(tf_path.read_text(encoding="utf-8"))
        params.pop("tables_file")
        spec["params"] = params
    if spec.get("spatial_parts") is not None:
        from bimforge.author.spatial import parse_rules
        parse_rules(spec["spatial_parts"], f"{path.name}: spatial_parts")
    spec["_dir"] = str(base)
    return spec


def build_from_spec(spec_path: Path | str, check_only: bool = False) -> int:
    """The est-bim build pipeline. Returns a process exit code."""
    import sys

    from bimforge.author import gate, paycodes as pc_mod
    from bimforge.author.project import ProjectContext

    spec = load_spec(spec_path)
    builder = get(spec["family"])
    ctx = ProjectContext.from_spec(spec["project"])
    pc = pc_mod.load(spec["paycodes"])
    model = builder(spec["params"], ctx)
    if spec.get("spatial_parts"):
        # the spec's own rules first: apply() only fills elements that have no
        # part yet, so these win over the paycodes' spatial_parts.
        from bimforge.author.spatial import apply_spatial_parts, parse_rules
        apply_spatial_parts(model, parse_rules(spec["spatial_parts"]))
    pc_mod.apply(model, pc)

    rep = gate.run_pre(model, pc)
    print(rep.format("pre"), file=sys.stderr)
    if not rep.passed:
        return 1
    if check_only:
        print("--check-only: nothing written", file=sys.stderr)
        return 0

    outs = spec["outputs"]
    written = {}
    try:
        if outs.get("dxf"):
            from bimforge.author.emit_dxf import emit_dxf
            print(emit_dxf(model, outs["dxf"]), file=sys.stderr)
            written["dxf"] = outs["dxf"]
        if outs.get("ifc"):
            from bimforge.author.emit_ifc import emit_ifc
            print(emit_ifc(model, outs["ifc"], pc,
                           allow_local=bool(outs.get("ifc_allow_local"))),
                  file=sys.stderr)
            written["ifc"] = outs["ifc"]
        if outs.get("takeoff_map"):
            tmap = pc.takeoff_map(model.codes_used())
            p = Path(outs["takeoff_map"])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(
                "# GENERATED by est-bim build - DO NOT EDIT BY HAND\n"
                f"# family: {spec['family']}; paycodes: {Path(spec['paycodes']).name}\n"
                + yaml.safe_dump(tmap, sort_keys=False), encoding="utf-8")
            print(f"takeoff map written to {p}", file=sys.stderr)
            written["takeoff_map"] = str(p)
        if outs.get("qto"):
            from bimforge.author.emit_qto import emit_qto
            print(emit_qto(model, outs["qto"], pc), file=sys.stderr)
            written["qto"] = outs["qto"]
        if outs.get("bbs"):
            from bimforge.author.emit_bbs import emit_bbs
            print(emit_bbs(model, outs["bbs"]), file=sys.stderr)
            written["bbs"] = outs["bbs"]
        if outs.get("step"):
            from bimforge.author.emit_step import emit_step
            print(emit_step(model, outs["step"]), file=sys.stderr)
            written["step"] = outs["step"]
    except Exception:
        # refuse-partial: an emitter failing mid-loop (unwritable path, disk
        # full) must not orphan the outputs already written — the same
        # contract as the post-gate's verify-and-delete, extended to I/O
        # failures.
        gate.delete_outputs(written)
        raise

    extra_post = []
    try:
        import build123d  # noqa: F401
        from bimforge.author.emit_step import true_volume_check
        extra_post.append(true_volume_check)
    except ImportError:
        pass
    post = gate.run_post(model, written, pc, extra_checks=extra_post)
    print(post.format("post"), file=sys.stderr)
    return 0 if post.passed else 1
