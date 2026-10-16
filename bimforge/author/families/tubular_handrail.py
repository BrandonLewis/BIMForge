"""tubular-handrail -- Caltrans B11-51 tubular handrailing: one or
more runs, each a call into the reusable `rail_run` primitive. Straight runs
are authored in a local frame (+Y = run); an alignment-bound run (curved
host) is a follow-on (see spec R27).
"""
from __future__ import annotations

from bimforge.author import rail_run
from bimforge.author import rail_section as rs
from bimforge.author.model import StructureModel


def _as_list(val, field: str, name: str) -> list:
    """Normalise a YAML scalar-or-sequence into a list, failing loud on the
    string trap (`tuple("start")` -> characters). A bare scalar is wrapped;
    a str is treated as a single item, never iterated char-by-char."""
    if val is None:
        return []
    if isinstance(val, (str, bytes)) or not isinstance(val, (list, tuple)):
        return [val]
    return list(val)


def build(params: dict, ctx) -> StructureModel:
    runs = params.get("runs")
    if not runs:
        raise ValueError("tubular-handrail: params.runs is required")
    model = StructureModel("tubular-handrail", ctx)
    for run in runs:
        name = run.get("name", "handrail")
        if "straight_length_ft" not in run:
            raise ValueError(
                f"{name}: only straight_length_ft runs are supported in v1 "
                f"(alignment-bound runs are a follow-on)")
        els = rail_run.build_run(
            length_ft=float(run["straight_length_ft"]),
            base_z_ft=float(run.get("base_z_ft", 0.0)),
            cfg=rs.CONFIG_B11_51,
            run_name=name,
            post_spacing_ft=float(run.get("post_spacing_ft",
                                          6.0 + 2.0 / 12.0)),
            anchorage=bool(run.get("anchorage", True)),
            end_posts=tuple(_as_list(
                run.get("end_posts", ["start", "end"]), "end_posts", name)),
            joints=tuple(
                float(s) for s in _as_list(run.get("joints"), "joints", name)),
        )
        for el in els:
            model.add(el)
    return model
