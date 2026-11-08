"""Family registry + est-bim build spec loading/orchestration (spec §4).

The spec file:

    family: pipe-supports
    params: { ...family-specific, cites plan sheets... }
    paycodes: ./paycodes.yaml
    outputs: {dxf: CAD/x.dxf, ifc: CAD/x.ifc,
              takeoff_map: CAD/x-takeoff-map.yaml,
              qto: CAD/x-QTO.xlsx, step: null,
              ifc_allow_local: false,
              ifc_sweeps: exact}    # overrides ifc.sweeps for this emit
    ifc: {sweeps: exact}    # exact (default) | mesh: how alignment sweeps
                            # are written (StructureModel.ifc_sweeps; viewers
                            # that cannot draw IfcSectionedSolidHorizontal)
    project: {name: "...", epsg: 2226, base: [.., ..], guid_ns: "<uuid>",
              schema: IFC4X3_ADD2,                       # optional (#318:
              facility: {kind: bridge, predefined_type: GIRDER}}  # 4X3 only)
    spatial_parts:          # optional: element-name regex -> facility part
      - {match: "(?i)abut", part: ABUTMENT}
    gate: {solid_bodies: warn,   # optional: warn (default) | error | off
           unread_params: warn, # optional: off (default) | warn | error -
           ignore: [notes]}     #  params the family never reads (params_tracking)
    ifc_surfaces:           # optional: {layer or IfcClass: {rgb, transparency,
      IfcCovering: {rgb: [0.5, 0.5, 0.5]}  # ...}} merged over the style pack's
    bodies:                 # optional: element-name regex -> body kind
      - {match: "^existing-grade", body: surface}
    placement:              # optional: put a local-frame family on a line
      alignment: ROUTE-1    # (bimforge.author.placement; the line comes from
      items: [...]          #  project.alignments: ./alignments.yaml)

A family is resolved from the shipped set, the `bimforge.families` entry
points, and any `family_paths` directory (`est-bim build --family-path DIR`):
every module there that exports a `FAMILIES = {name: build}` dict. A name
declared twice, anywhere, is an error.

`project.alignments` names the project's shared alignments file: params
`alignment: {ref: NAME}` / `profile: {ref: NAME}` read from it, `placement:`
places on it, and a family's own declared line of a shared name is held to
it and replaced by it (one IfcAlignment per line).

The dispatcher is NOT a geometry language: a family is python; the spec is
parameters. Orchestration: spec -> family.build -> paycodes.apply -> gate
pre (refuse-to-write; --check-only stops here) -> emitters -> gate post
(verify-and-delete).
"""
from __future__ import annotations

import importlib
import sys
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


def available(family_paths=()) -> dict:
    """name -> builder, shipped + entry-point registered + `family_paths`
    directories (external wins ties are NOT allowed: a collision is an error,
    not a shadow)."""
    out = dict(_shipped())
    from importlib.metadata import entry_points
    for ep in entry_points(group=FAMILY_GROUP):
        if ep.name in out:
            raise ValueError(f"family {ep.name!r} from {ep.value} collides "
                             f"with a shipped family")
        out[ep.name] = ep.load()
    for name, (builder, origin) in load_family_dirs(family_paths).items():
        if name in out:
            raise ValueError(f"family {name!r} from {origin} collides with a "
                             f"shipped or entry-point family")
        out[name] = builder
    return out


def load_family_dirs(family_paths) -> dict:
    """name -> (builder, origin file) from every module in each directory
    that exports `FAMILIES = {name: build}`.

    Each directory goes on sys.path and its modules are imported by their
    plain names, so family modules can import their siblings (shared checks,
    solids helpers). Discovered rather than listed, so a new family is one new
    module. A module that fails to import for want of an optional dependency
    is skipped with a note rather than taking every other family down with it;
    a name declared twice is an error.

    Because the import is by plain name and the directory goes FIRST on
    sys.path, a module named like one already imported (or like a stdlib
    module) resolves to that module instead: give family modules unique
    names.
    """
    out: dict = {}
    for d in family_paths or ():
        d = Path(d).resolve()
        if not d.is_dir():
            raise ValueError(f"family path {d} is not a directory")
        if str(d) not in sys.path:
            sys.path.insert(0, str(d))
        for path in sorted(d.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                mod = importlib.import_module(path.stem)
            except ImportError as exc:
                print(f"skipping {path.name}: {exc}", file=sys.stderr)
                continue
            for name, builder in (getattr(mod, "FAMILIES", None) or {}).items():
                if name in out:
                    raise ValueError(f"family {name!r} is declared in both "
                                     f"{out[name][1]} and {path}")
                out[name] = (builder, str(path))
    return out


def get(name: str, family_paths=()):
    fams = available(family_paths)
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
    unknown = set(outs) - set(OUTPUT_KEYS) - {"ifc_allow_local", "ifc_sweeps",
                                              "ifc_instancing"}
    if unknown:
        raise ValueError(f"{path.name}: unknown outputs keys {sorted(unknown)}")
    from bimforge.author.emit_ifc import SWEEP_MODES
    if outs.get("ifc_sweeps", "exact") not in SWEEP_MODES:
        raise ValueError(f"{path.name}: outputs.ifc_sweeps "
                         f"{outs['ifc_sweeps']!r} must be one of {SWEEP_MODES}")
    ifc_block = spec.get("ifc") or {}
    if not isinstance(ifc_block, dict):
        raise ValueError(f"{path.name}: ifc: must be a mapping ({{sweeps: mesh}})")
    if str(ifc_block.get("sweeps", "exact")).lower() not in SWEEP_MODES:
        raise ValueError(f"{path.name}: ifc.sweeps {ifc_block['sweeps']!r} "
                         f"must be one of {SWEEP_MODES}")
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
    proj = spec.get("project") or {}
    if proj.get("alignments"):
        ap = (base / proj["alignments"]).resolve()
        if not ap.exists():
            raise ValueError(f"{path.name}: project.alignments {proj['alignments']!r} "
                             f"not found at {ap}")
        proj["alignments"] = str(ap)
    if spec.get("placement") is not None and not proj.get("alignments"):
        raise ValueError(f"{path.name}: placement: needs project.alignments")
    surfaces = spec.get("ifc_surfaces")
    if surfaces is not None and not isinstance(surfaces, dict):
        raise ValueError(f"{path.name}: ifc_surfaces: must be a mapping "
                         f"({{layer or IfcClass: {{rgb: [r, g, b], ...}}}})")
    from bimforge.author.params_tracking import UNREAD_PARAM_MODES
    unread = (spec.get("gate") or {}).get("unread_params")
    if unread is not None and str(unread).lower() not in UNREAD_PARAM_MODES:
        raise ValueError(f"{path.name}: gate.unread_params {unread!r} must be "
                         f"one of {UNREAD_PARAM_MODES}")
    if spec.get("spatial_parts") is not None:
        from bimforge.author.spatial import parse_rules
        parse_rules(spec["spatial_parts"], f"{path.name}: spatial_parts")
    spec["_dir"] = str(base)
    return spec


def spec_alignments(spec: dict) -> dict | None:
    """The spec's shared alignments ({name: SharedAlignment}) or None."""
    path = (spec.get("project") or {}).get("alignments")
    if not path:
        return None
    from bimforge.author.placement import load_alignments
    return load_alignments(path)


def spec_params(spec: dict, alignments: dict | None) -> dict:
    """The family's params with `{ref: NAME}` alignment/profile resolved."""
    if not alignments:
        return spec["params"]
    from bimforge.author.placement import resolve_refs
    return resolve_refs(spec["params"], alignments)


def place_from_spec(model, spec: dict, alignments: dict | None, log=None) -> None:
    """After the family built: hold a declared line of a shared name to the
    shared one (a pre-gate check when it does not agree) and apply the
    spec's `placement:` block."""
    if not alignments:
        return
    from bimforge.author.placement import adopt_shared, apply_placement, check_ties
    model.checks.append(check_ties(alignments))
    problems = adopt_shared(model, alignments)
    if problems:
        def check_shared_alignment(_model, _p=tuple(problems)):
            """A line the family declares under a shared name is the shared line."""
            return list(_p)
        model.checks.append(check_shared_alignment)
    for line in apply_placement(model, spec.get("placement") or {}, alignments):
        if log:
            log(f"placed {line}")


def station_ifc(model, ifc_path, log=None) -> dict | None:
    """Write every element's station / offset into the emitted IFC
    (bimforge.bim.linear_ref) when the model declares an alignment, with the
    spec-placed elements' anchors. Returns the report, or None."""
    from bimforge.author.emit_alignment import model_alignments
    if not getattr(model, "alignments", None) and not model_alignments([model]):
        return None
    from bimforge.bim.linear_ref import anchors_from_model, annotate
    rep = annotate(str(ifc_path), anchors=anchors_from_model(model))
    if log and rep["elements"]:
        log(f"stationed {rep['elements']} elements on "
            + ", ".join(f"{k} ({v})" for k, v in rep["alignments"].items()))
    return rep


def spec_stylepack(spec: dict):
    """The active style pack with the spec's `ifc_surfaces` merged OVER its
    `ifc.surfaces`: a model's own presentation colours (stone tones for rock
    slope protection, say) without touching the pack. None when the spec has
    none, so emit_ifc resolves the pack exactly as before."""
    extra = spec.get("ifc_surfaces")
    if not extra:
        return None
    from bimforge.cad.stylepack import StylePack, resolve_style_pack
    base = resolve_style_pack()
    styles = dict(base.styles)
    ifc = dict(styles.get("ifc") or {})
    ifc["surfaces"] = {**(ifc.get("surfaces") or {}), **extra}
    styles["ifc"] = ifc
    return StylePack(templates_dir=base.templates_dir, styles=styles)


def build_from_spec(spec_path: Path | str, check_only: bool = False,
                    family_paths=(), unread_params: str = "off") -> int:
    """The est-bim build pipeline. Returns a process exit code.

    `family_paths`: directories of extra family modules (`load_family_dirs`).
    `unread_params`: the default for the spec's `gate.unread_params`.
    """
    from bimforge.author import gate, paycodes as pc_mod
    from bimforge.author.params_tracking import (
        TrackedParams, unread_params as find_unread, unread_params_check)
    from bimforge.author.project import ProjectContext

    spec = load_spec(spec_path)
    builder = get(spec["family"], family_paths)
    ctx = ProjectContext.from_spec(spec["project"])
    pc = pc_mod.load(spec["paycodes"])
    alignments = spec_alignments(spec)
    gate_cfg = spec.get("gate") or {}
    unread = str(gate_cfg.get("unread_params", unread_params)).lower()
    ignore = tuple(gate_cfg.get("ignore") or ())
    params = spec_params(spec, alignments)
    if unread != "off":
        params = TrackedParams(params)
    model = builder(params, ctx)
    place_from_spec(model, spec, alignments,
                    log=lambda m: print(m, file=sys.stderr))
    if spec.get("spatial_parts"):
        # the spec's own rules first: apply() only fills elements that have no
        # part yet, so these win over the paycodes' spatial_parts.
        from bimforge.author.spatial import apply_spatial_parts, parse_rules
        apply_spatial_parts(model, parse_rules(spec["spatial_parts"]))
    pc_mod.apply(model, pc)
    gate.configure_solid_bodies(model, spec)
    if "ifc_instancing" in spec["outputs"]:         # overrides the family
        model.instancing = bool(spec["outputs"]["ifc_instancing"])
    # ifc: {sweeps: mesh} - the model's own sweep mode (StructureModel.ifc_sweeps)
    if "sweeps" in (spec.get("ifc") or {}):
        model.ifc_sweeps = str(spec["ifc"]["sweeps"]).lower()

    extra_pre = [unread_params_check(params, ignore)] if unread == "error" else []
    rep = gate.run_pre(model, pc, extra_checks=extra_pre)
    print(rep.format("pre"), file=sys.stderr)
    if unread == "warn":
        # after the gate, so a parameter a check reads lazily counts as read
        for p in find_unread(params, ignore):
            print(f"warning: spec declares {p!r} but the family never reads it",
                  file=sys.stderr)
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
                           allow_local=bool(outs.get("ifc_allow_local")),
                           stylepack=spec_stylepack(spec),
                           sweeps=outs.get("ifc_sweeps")),   # None: the model's
                  file=sys.stderr)
            written["ifc"] = outs["ifc"]
            station_ifc(model, outs["ifc"], log=lambda m: print(m, file=sys.stderr))
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
