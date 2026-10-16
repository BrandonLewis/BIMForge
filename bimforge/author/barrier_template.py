"""Shared writer for the barrier families (732sw, 842, ...): a typed
`BarrierTemplate` (data + geometry callables) driving one `build_barrier`
run-loop + prism + LF bookkeeping + end placement, plus the shared
`bar_elements` rebar grouper and `end_kinds` dual-dialect end normalizer.

Promoted from the validated spike `_spike_barrier_template.py`; see
docs/superpowers/plans/2026-08-30-barrier-template-refactor.md.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Optional

from bimforge.author import curved_run as _curved
from bimforge.author.model import Element, StructureModel
from bimforge.author.primitives import SectionPrism

_END_VALUES = ("approach", "departure", "none")


@dataclass(frozen=True)
class BarrierTemplate:
    family_id: str            # registry id, e.g. "concrete-barrier-842"
    label: str                # element-name infix, e.g. "842"
    endblock_len_ft: float
    section_fn: Callable      # (run) -> section  (.outline, .top_z)
    rebar_fn: Callable        # (name, section, run, run_len) -> list[Element]
    endblock_fn: Callable     # (name, run, section, *, kind, pos, y_nose, y_inboard) -> list[Element]
    validate_fn: Optional[Callable] = None   # (name, run) -> None (raise on bad)
    extras_fn: Optional[Callable] = None     # (name, run, section, length) -> list[Element]
    default_run_name: str = "barrier"
    endblock_rings_fn: Optional[Callable] = None   # (run, section, kind) -> (inboard_ring, nose_ring)


def bar_elements(sname: str, label: str, bars: list) -> list:
    """Group weight-only bars by (mark, size) into IfcReinforcingBar Elements
    named ``"{sname} {label} reinforcing {mark} #{size}"``. Deterministic
    (sorted) ordering — the byte-identical equivalence gate depends on it.
    Returns the list; the caller adds them to the model."""
    groups: dict = defaultdict(list)
    for b in bars:
        groups[(b.mark, b.size)].append(b)
    out = []
    for (mark, size), bs in sorted(groups.items()):
        out.append(Element(
            f"{sname} {label} reinforcing {mark} #{size}", "IfcReinforcingBar",
            quantities={"count": len(bs),
                        "length_ft": sum(b.length for b in bs),
                        "weight_lb": sum(b.weight for b in bs)},
            layer="S-REBAR", description=f"#{size} {mark}"))
    return out


def end_kinds(run) -> tuple[str, str]:
    """Normalize both end-selection dialects to (start_kind, end_kind), each one
    of approach/departure/none. The 842 enum (start_end/end_end) takes
    precedence when either key is present; otherwise the 732sw booleans
    (approach_end_block/departure_end_block) map to (approach|none,
    departure|none). Default is a block at each end."""
    if "start_end" in run or "end_end" in run:
        return run.get("start_end", "approach"), run.get("end_end", "departure")
    start = "approach" if run.get("approach_end_block", True) else "none"
    end = "departure" if run.get("departure_end_block", True) else "none"
    return start, end


def build_barrier(tmpl: BarrierTemplate, params: dict, ctx) -> StructureModel:
    """Assemble one barrier family's straight runs from a BarrierTemplate.

    Per run: emit a running SectionPrism (shortened by the end blocks) plus
    rebar, end blocks, and any extras. LF contract (the R29 lesson): the running
    prism and each end block carry explicit ``length_ft`` so total barrier LF
    sums back to the full ``straight_length_ft``. End blocks are placed by
    position (pos=start/end) and typed by kind (approach/departure)."""
    runs = params.get("runs")
    if not runs:
        raise ValueError(f"{tmpl.family_id}: params.runs is required")
    model = StructureModel(tmpl.family_id, ctx)
    for run in runs:
        name = run.get("name", tmpl.default_run_name)
        if "path" in run:
            _build_curved_run(tmpl, run, name, model)
            continue
        if "straight_length_ft" not in run:
            raise ValueError(f"{name}: straight_length_ft is required "
                             f"(alignment-bound runs are a follow-on, issue #149)")
        length = float(run["straight_length_ft"])
        start_kind, end_kind = end_kinds(run)
        for lbl, v in (("start", start_kind), ("end", end_kind)):
            if v not in _END_VALUES:
                raise ValueError(f"{name}: {lbl}-end value {v!r} must be one "
                                 f"of {_END_VALUES}")
        if tmpl.validate_fn:
            tmpl.validate_fn(name, run)
        n_blocks = (start_kind != "none") + (end_kind != "none")
        run_len = length - tmpl.endblock_len_ft * n_blocks
        if run_len < 2.0:
            raise ValueError(f"{name}: straight_length_ft={length} is too short "
                             f"for {n_blocks} end block(s) "
                             f"(needs >= {tmpl.endblock_len_ft * n_blocks + 2.0})")
        section = tmpl.section_fn(run)
        y0 = tmpl.endblock_len_ft if start_kind != "none" else 0.0
        sp = SectionPrism(f"{name} {tmpl.label} barrier", section.outline,
                          run_len, y0=y0, ifc="IfcWall", layer="S-CONC")
        model.add(Element.from_geometry(
            sp.name, sp, ifc_class="IfcWall", layer="S-CONC",
            quantities={"length_ft": run_len}))
        for el in tmpl.rebar_fn(name, section, run, run_len):
            model.add(el)
        L = tmpl.endblock_len_ft
        if start_kind != "none":
            for el in tmpl.endblock_fn(name, run, section, kind=start_kind,
                                       pos="start", y_nose=0.0, y_inboard=L):
                model.add(el)
        if end_kind != "none":
            for el in tmpl.endblock_fn(name, run, section, kind=end_kind,
                                       pos="end", y_nose=length,
                                       y_inboard=length - L):
                model.add(el)
        if tmpl.extras_fn:
            for el in tmpl.extras_fn(name, run, section, length):
                model.add(el)
    return model


def _path_total_length(path: list) -> float:
    """Arc length of a barrier `path` (straight lengths + R*radians(delta) per
    arc). Mirrors `curved_run.alignment_from_path`'s per-segment measure."""
    import math
    total = 0.0
    for seg in path:
        if seg.get("kind") == "straight":
            total += float(seg["length"])
        elif seg.get("kind") == "arc":
            total += float(seg["radius"]) * math.radians(float(seg["delta"]))
    return total


def _build_curved_run(tmpl: BarrierTemplate, run: dict, name: str,
                      model: StructureModel) -> None:
    """Emit one alignment-bound (`path`) run: a constant-section running prism
    over the alignment interior, plus rebar, end blocks (Task 7) and extras.
    LF contract matches the straight path — the running prism is shortened by
    the end blocks and every piece carries an explicit ``length_ft``."""
    path = run["path"]
    if "straight_length_ft" in run:
        raise ValueError(f"{name}: give either straight_length_ft OR path, "
                         f"not both")
    if not any(seg.get("kind") == "arc" for seg in path):
        raise ValueError(f"{name}: a straight-only run should use "
                         f"straight_length_ft")
    start_kind, end_kind = end_kinds(run)
    for lbl, v in (("start", start_kind), ("end", end_kind)):
        if v not in _END_VALUES:
            raise ValueError(f"{name}: {lbl}-end value {v!r} must be one "
                             f"of {_END_VALUES}")
    if tmpl.validate_fn:
        tmpl.validate_fn(name, run)
    align = _curved.alignment_from_path(path, name=name)
    length = _path_total_length(path)
    L = tmpl.endblock_len_ft
    n_blocks = (start_kind != "none") + (end_kind != "none")
    s0 = L if start_kind != "none" else 0.0
    s1 = length - (L if end_kind != "none" else 0.0)
    if s1 - s0 < 2.0:
        raise ValueError(f"{name}: path length {length:.2f} ft is too short for "
                         f"{n_blocks} end block(s)")
    section = tmpl.section_fn(run)
    run_len = s1 - s0
    prism = _curved.build_running_prism(
        f"{name} {tmpl.label} barrier", section.outline, align, s0, s1,
        ifc="IfcWall", layer="S-CONC")
    model.add(prism)
    for el in tmpl.rebar_fn(name, section, run, run_len):
        model.add(el)
    _place_curved_end_blocks(tmpl, run, name, model, section, align, length, L,
                             start_kind, end_kind)
    if tmpl.extras_fn:
        for el in tmpl.extras_fn(name, run, section, length):
            model.add(el)


def _geomless(e) -> bool:
    """True for a quantity-only Element (rebar/hardware) carrying no geometry.
    Handles both the default `geometry=None` and the historical
    `geometry={"kind":"none"}` sentinel some families used."""
    g = getattr(e, "geometry", None)
    return g is None or (isinstance(g, dict) and g.get("kind") == "none")


def _ring_at_factory(inboard, nose, s_join, L):
    """A `ring_at(s)` that lerps the (x, z) block section from the inboard ring
    (at the join, u=0) to the nose ring (at the free terminal, u=1). The rings
    must be vertex-count-matched and index-corresponding (the same pair the
    family's straight end-block loft uses)."""
    def ring_at(s):
        u = abs(s - s_join) / L          # 0 at the join (inboard), 1 at nose
        u = min(max(u, 0.0), 1.0)
        return [(a[0] + u * (b[0] - a[0]), a[1] + u * (b[1] - a[1]))
                for a, b in zip(inboard, nose)]
    return ring_at


def _place_curved_end_blocks(tmpl, run, name, model, section, align, length, L,
                             start_kind, end_kind):
    """Section-morphing end blocks that follow the alignment (arc terminals
    included). The block SOLID is a `sweep_morph` loft from the inboard ring at
    the run join to the nose ring at the free terminal, replacing the straight
    solid the family's `endblock_fn` also builds; the block's REBAR/HARDWARE are
    reused from `endblock_fn`, filtered to the geometry-less (quantity-only)
    Elements so only the straight solid is discarded. The solid NAME matches the
    straight convention so the concrete pay rule catches it and the R31
    position-keyed uniqueness holds."""
    if start_kind == "none" and end_kind == "none":
        return
    if tmpl.endblock_rings_fn is None:
        raise ValueError(f"{name}: curved runs with end blocks need the family "
                         f"to define endblock_rings_fn")

    if start_kind != "none":
        inboard, nose = tmpl.endblock_rings_fn(run, section, start_kind)
        # start block: nose at the free terminal (s=0), inboard at the join (s=L)
        model.add(_curved.sweep_morph(
            f"{name} {tmpl.label} barrier end block ({start_kind}) [start]",
            _ring_at_factory(inboard, nose, L, L), align, 0.0, L,
            ifc="IfcWall", layer="S-CONC"))
        for e in tmpl.endblock_fn(name, run, section, kind=start_kind,
                                  pos="start", y_nose=0.0, y_inboard=L):
            if _geomless(e):
                model.add(e)
    if end_kind != "none":
        inboard, nose = tmpl.endblock_rings_fn(run, section, end_kind)
        # end block: inboard at the join (s=length-L), nose at the terminal (s=length)
        model.add(_curved.sweep_morph(
            f"{name} {tmpl.label} barrier end block ({end_kind}) [end]",
            _ring_at_factory(inboard, nose, length - L, L), align,
            length - L, length, ifc="IfcWall", layer="S-CONC"))
        for e in tmpl.endblock_fn(name, run, section, kind=end_kind,
                                  pos="end", y_nose=length, y_inboard=length - L):
            if _geomless(e):
                model.add(e)
