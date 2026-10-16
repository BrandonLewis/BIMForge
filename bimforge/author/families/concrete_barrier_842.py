"""concrete-barrier-842 -- Caltrans Concrete Barrier Type 842 (B11-81/82/82A):
the 3'-6" sloping-face bridge/wall barrier in three base variants (842 deck /
842A wall / 842B trench footing), swept over a straight or alignment-bound
(curved `path`) run, with approach/departure end blocks + MGS/Type-AGT
guardrail-transition hardware. No top handrail (842's metal railing is a
separate standard plan).

Built on the shared `barrier_template.build_barrier` writer: this module
supplies only the 842-specific geometry/rebar/validation/end-block adapters
plus a `BarrierTemplate` instance. section_fn/endblock_fn pass the run dict
(not {}) into the geometry builders, lighting up per-row "Mod" dimension
overrides -- with no override keys present the output is unchanged.
"""
from __future__ import annotations

from bimforge.author.barrier_842_endblock import (
    ENDBLOCK_842_LEN, endblock_bars, endblock_solid)
from bimforge.author.barrier_842_endblock import nose_section as _nose_842
from bimforge.author.barrier_842_rebar import barrier_842_bars
from bimforge.author.barrier_842_transition import transition_elements
from bimforge.author.barrier_section import BarrierSection
from bimforge.author.barrier_template import (
    BarrierTemplate, bar_elements, build_barrier, _path_total_length)
from bimforge.author.model import Element
from bimforge.author.type_842_profile import type_842_profile

_TRENCH_MIN_LEN = 40.0                 # B11-82 Note 8


def _rebar_groups(top_z: float, base_kind: str) -> list:
    """Section A-A core reinforcing (developed-length estimates)."""
    groups = [
        {"mark": "long-barrier", "size": 5, "kind": "long", "count": 12},
        {"mark": "long-base", "size": 5, "kind": "long", "count": 2},
        {"mark": "vert-face", "size": 5, "kind": "vert", "spacing_in": 8.0,
         "length_ft": top_z},
        {"mark": "vert-back", "size": 5, "kind": "vert", "spacing_in": 16.0,
         "length_ft": top_z},
    ]
    if base_kind == "trench":          # footing longitudinals + transverse
        groups += [
            {"mark": "foot-long", "size": 5, "kind": "long", "count": 8},
            {"mark": "foot-trans", "size": 5, "kind": "vert",
             "spacing_in": 12.0, "length_ft": 23.0 / 12.0},
        ]
    return groups


# --- template-driven build -----------------------------------------------

def _section_842(run: dict) -> BarrierSection:
    """A BarrierSection wrapping the running (sloping-face) 842 profile."""
    base_kind = run.get("base_kind", "deck")
    ring = type_842_profile(run, base_kind=base_kind, face="sloping")  # run: Mod
    # "type_842" shape is a label only -- the explicit "profile" ring is
    # consumed via BarrierSection's explicit-profile path (no generator needed).
    return BarrierSection("type_842", "std", {"barriers": {"type_842": {
        "shape": "type_842", "variants": {"std": {"profile": ring}}}}})


def _rebar_842(name, section, run, run_len):
    base_kind = run.get("base_kind", "deck")
    bars = barrier_842_bars(run_len, _rebar_groups(section.top_z, base_kind))
    return bar_elements(name, "842", bars)


def _validate_842(name, run):
    base_kind = run.get("base_kind", "deck")
    if base_kind not in ("deck", "wall", "trench"):
        raise ValueError(
            f"{name}: base_kind {base_kind!r} must be deck/wall/trench")
    if base_kind == "trench":
        # length comes from EITHER a straight run (straight_length_ft) or a
        # curved run's `path` (arc-summed) -- the Note-8 floor applies to both.
        length = (_path_total_length(run["path"]) if "path" in run
                  else float(run["straight_length_ft"]))
        if length < _TRENCH_MIN_LEN:
            raise ValueError(f"{name}: Type 842B (trench) minimum length is "
                             f"{_TRENCH_MIN_LEN}' (Note 8), got {length}'")


def _endblock_842(name, run, section, *, kind, pos, y_nose, y_inboard):
    base_kind = run.get("base_kind", "deck")
    approach = kind == "approach"
    els = []
    # An end block is identified by its POSITION on the run (`pos`, start/end),
    # not by its `kind`: a run may carry the same treatment at both ends (e.g. a
    # two-way run with an approach block each end). Position keys every emitted
    # name (solid, rebar, hardware) so same-kind ends never collide, while the
    # `(kind)` parenthetical is retained as descriptive text.
    sol = endblock_solid(f"{name} 842 barrier end block ({kind}) [{pos}]", run,
                         base_kind=base_kind, y_nose=y_nose, y_inboard=y_inboard,
                         ifc="IfcWall", layer="S-CONC")
    # length_ft is an explicit analytic quantity so the LF pay item
    # (CONC-BARRIER-842) sums running-prism + blocks back to the full run.
    els.append(Element.from_geometry(
        sol.name, sol, ifc_class="IfcWall", layer="S-CONC",
        quantities={"length_ft": ENDBLOCK_842_LEN}))
    tag = "ap" if approach else "dp"
    # bracket [pos] form (matches the solid/transition names and 732sw) so the
    # shared position-normalizer strips it uniformly across families.
    els += bar_elements(f"{name} endblock-{tag} [{pos}]", "842",
                        endblock_bars(ENDBLOCK_842_LEN, approach=approach))
    # HSS is block-mounted hardware billed at the 3'-6" block length -- use the
    # transition_elements default (HSS_LEN_FT), NOT the 9'-10" end treatment.
    els += list(transition_elements(f"{name} ({kind}) [{pos}]", approach=approach))
    return els


def _endblock_rings_842(run, section, kind):
    """The (inboard, nose) (x, z) rings the curved end-block loft morphs
    between -- the SAME pair the straight `endblock_solid` lofts (running
    sloping face -> plumb vertical nose), so vertex counts correspond per
    variant (deck=6, wall=7, trench=10 -- #320 stepped the 842A/842B rings)."""
    base_kind = run.get("base_kind", "deck")
    inboard = type_842_profile(run, base_kind=base_kind, face="sloping")
    nose = _nose_842(run, base_kind=base_kind)
    return inboard, nose


_TEMPLATE = BarrierTemplate(
    family_id="concrete-barrier-842", label="842",
    endblock_len_ft=ENDBLOCK_842_LEN, default_run_name="842",
    section_fn=_section_842, rebar_fn=_rebar_842,
    endblock_fn=_endblock_842, validate_fn=_validate_842,
    endblock_rings_fn=_endblock_rings_842)


def build(params: dict, ctx):
    return build_barrier(_TEMPLATE, params, ctx)
