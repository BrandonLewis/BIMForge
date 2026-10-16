"""concrete-barrier-732sw -- Caltrans Type 732SW concrete barrier with an
integral raised sidewalk (B11-58/59/59A), swept over a straight or
alignment-bound (curved `path`) run, hosting the R27 B11-51 tubular handrail on
top via rail_run.build_run. One or more runs; the handrail geometry is straight
only, so a curved run must set `handrail: false` (curved rail is deferred, #149).

Built on the shared `barrier_template.build_barrier` writer: this module
supplies only the 732sw-specific geometry/rebar/end-block/handrail adapters
plus a `BarrierTemplate` instance. section_fn/rebar_fn/endblock_fn pass the
run dict (via `_row_732`, merging with SECTION_DEFAULTS) into the geometry
builders, lighting up per-row "Mod" dimension overrides -- with no override
keys present the output is unchanged. End-block/hardware element NAMES gain
a `[start]`/`[end]` position suffix (new to 732sw, matching the 842/R31
collision-safety convention); quantities are unaffected.
"""
from __future__ import annotations

from bimforge.author import rail_run
from bimforge.author.barrier_732sw_endblock import (
    ENDBLOCK_LEN, endblock_bars, endblock_solid)
from bimforge.author.barrier_732sw_endblock import nose_section as _nose_732
from bimforge.author.barrier_732sw_rebar import barrier_732sw_bars
from bimforge.author.barrier_732sw_transition import transition_elements
from bimforge.author.barrier_section import BarrierSection, type_732sw_profile
from bimforge.author.barrier_template import BarrierTemplate, bar_elements, build_barrier
from bimforge.author.model import Element

#: Type 732SW governing section dims (feet); run-overridable.
SECTION_DEFAULTS = {
    "top_w_ft": 1.0, "top_h_ft": 14.0 / 12.0, "stem_w_ft": 10.0 / 12.0,
    "barrier_h_ft": 2.0 + 8.0 / 12.0, "sw_top_face_ft": 0.7624,
    "sw_thick_toe_ft": 8.0 / 12.0, "sw_width_ft": 6.0 + 2.0 / 12.0,
    "deck_slope_pct": 0.0,
}


def _rebar_groups(top_z: float, sw_width: float) -> list:
    """Section A-A core reinforcing (developed-length estimates)."""
    return [
        {"mark": "long-barrier", "size": 5, "kind": "long", "count": 12},
        {"mark": "long-deck", "size": 5, "kind": "long", "count": 2},
        {"mark": "vert-face", "size": 6, "kind": "vert", "spacing_in": 8.0,
         "length_ft": top_z},
        {"mark": "vert-back", "size": 5, "kind": "vert", "spacing_in": 16.0,
         "length_ft": top_z},
        {"mark": "sw-transverse", "size": 5, "kind": "vert", "spacing_in": 12.0,
         "length_ft": sw_width},
        {"mark": "sw-bottom", "size": 4, "kind": "vert", "spacing_in": 16.0,
         "length_ft": sw_width},
    ]


def _as_list(val) -> list:
    if val is None:
        return []
    if isinstance(val, (str, bytes)) or not isinstance(val, (list, tuple)):
        return [val]
    return list(val)


# --- template-driven build -------------------------------------------------

def _row_732(run: dict) -> dict:
    """Merge SECTION_DEFAULTS with per-run overrides ("Mod" dims)."""
    row = dict(SECTION_DEFAULTS)
    for k in SECTION_DEFAULTS:
        if k in run:
            row[k] = float(run[k])
    return row


def _section_732(run: dict) -> BarrierSection:
    row = _row_732(run)
    return BarrierSection("type_732sw", "std", {"barriers": {"type_732sw": {
        "shape": "type_732sw", "variants": {"std": row}}}})


def _rebar_732(name, section, run, run_len):
    row = _row_732(run)
    bars = barrier_732sw_bars(
        run_len, _rebar_groups(section.top_z, row["sw_width_ft"]))
    return bar_elements(name, "732sw", bars)


def _endblock_732(name, run, section, *, kind, pos, y_nose, y_inboard):
    row = _row_732(run)
    approach = kind == "approach"
    els = []
    # An end block is identified by its POSITION on the run (`pos`, start/end),
    # not by its `kind`: position keys every emitted name (solid, rebar,
    # hardware) so same-kind ends never collide, while the `(kind)`
    # parenthetical is retained as descriptive text. NEW to 732sw (legacy
    # named blocks by kind only, always approach@start/departure@end) -- the
    # position-normalized equivalence test accounts for this.
    sol = endblock_solid(f"{name} 732sw barrier end block ({kind}) [{pos}]",
                         row, approach=approach, y_nose=y_nose,
                         y_inboard=y_inboard, ifc="IfcWall", layer="S-CONC")
    # length_ft is an explicit analytic quantity so the LF pay item
    # (CONC-BARRIER-732SW) sums running-prism + blocks back to the full run.
    els.append(Element.from_geometry(
        sol.name, sol, ifc_class="IfcWall", layer="S-CONC",
        quantities={"length_ft": ENDBLOCK_LEN}))
    tag = "ap" if approach else "dp"
    els += bar_elements(f"{name} endblock-{tag} [{pos}]", "732sw",
                        endblock_bars(ENDBLOCK_LEN, approach=approach))
    # HSS is block-mounted hardware billed at the 6' block length explicitly
    # -- 732sw's transition is NOT the transition_elements default length.
    els += list(transition_elements(f"{name} ({kind}) [{pos}]",
                                    approach=approach, length_ft=ENDBLOCK_LEN))
    return els


def _extras_732(name, run, section, length):
    if not run.get("handrail", True):
        return []
    if "path" in run:
        # rail_run.build_run is alignment-unaware: on a curved run it would lay
        # a STRAIGHT rail of the arc length floating off the curve. Curved
        # handrail geometry is deferred (#149) -- fail loud rather than emit
        # silently-wrong geometry.
        raise ValueError(
            f"{name}: handrail geometry on curved runs is not yet supported "
            f"(issue #149); set handrail: false to build the barrier without it")
    rail_x = min(x for x, _z in section.outline) + 0.5   # 6" in
    # rail spans the FULL run `length` (per B11-59A the tubular handrail
    # continues over the end blocks, not just the shortened middle prism).
    # Over the approach block its base (at the running section.top_z) sits
    # ~3" below the raised approach-nose top -- an intentional estimate-level
    # interpenetration with no quantity impact (rail LF/steel and block CF
    # are measured independently).
    return list(rail_run.build_run(
        length, base_z_ft=section.top_z, x0_ft=rail_x, run_name=name,
        post_spacing_ft=float(run.get("post_spacing_ft", 6.0 + 2.0 / 12.0)),
        joints=tuple(float(s) for s in _as_list(run.get("joints"))),
        end_posts=tuple(_as_list(run.get("end_posts", ["start", "end"])))))


def _endblock_rings_732(run, section, kind):
    """The (inboard, nose) (x, z) rings the curved end-block loft morphs
    between -- the SAME pair the straight `endblock_solid` lofts (running
    Section A-A -> solidified nose, top raised on approach), both 8-vertex and
    index-corresponding."""
    row = _row_732(run)
    inboard = list(type_732sw_profile(row))
    nose = _nose_732(row, approach=(kind == "approach"))
    return inboard, nose


_TEMPLATE = BarrierTemplate(
    family_id="concrete-barrier-732sw", label="732sw",
    endblock_len_ft=ENDBLOCK_LEN, default_run_name="732SW",
    section_fn=_section_732, rebar_fn=_rebar_732,
    endblock_fn=_endblock_732, extras_fn=_extras_732,
    endblock_rings_fn=_endblock_rings_732)


def build(params: dict, ctx):
    return build_barrier(_TEMPLATE, params, ctx)
