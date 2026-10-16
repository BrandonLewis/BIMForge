"""demo-box — the smallest real family: N square footings on a line.

Exists so the registry, the spec loader, the gate and every emitter have a
neutral, dependency-light structure to exercise (CI's est-bim build
--check-only leg runs on it). It is also the template a new family starts
from: params -> primitives -> Elements -> registered checks.
"""
from __future__ import annotations

from bimforge.author.model import Element, StructureModel
from bimforge.author.primitives import Prism

REQUIRED = ("count", "size_ft", "depth_ft", "spacing_ft")


def build(params: dict, ctx) -> StructureModel:
    missing = [k for k in REQUIRED if params.get(k) is None]
    if missing:
        raise ValueError(f"demo-box params missing {missing}")
    n, s = int(params["count"]), float(params["size_ft"])
    d, sp = float(params["depth_ft"]), float(params["spacing_ft"])
    m = StructureModel("demo-box", ctx)
    for i in range(n):
        p = Prism(f"DB-{i + 1} demo footing",
                  [(-s / 2, -s / 2), (s / 2, -s / 2), (s / 2, s / 2), (-s / 2, s / 2)],
                  z_bot=0.0, z_top=d, dims_ft=(s, s), ifc="IfcFooting")
        m.add(Element.from_geometry(p.name, p, ifc_class="IfcFooting",
                                    x_ft=i * sp, layer="S-CONC-OTLN",
                                    quantities={"length_ft": s, "width_ft": s,
                                                "height_ft": d,
                                                "volume_cf": s * s * d}))
    m.stated_quantities.append(
        ("demo-box total CY", n * s * s * d / 27.0,
         float(params.get("stated_cy", n * s * s * d / 27.0)), 5e-4))
    m.checks.append(_check_spacing_clears_size(sp, s))
    return m


def _check_spacing_clears_size(spacing: float, size: float):
    def check(model):
        if spacing < size:
            return [f"demo-box: spacing {spacing} ft < footing size {size} ft "
                    f"- the footings overlap"]
        return []
    return check
