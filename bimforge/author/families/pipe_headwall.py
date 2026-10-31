"""pipe-headwall -- Caltrans D89 pipe-culvert headwalls (straight and "L",
single/double, circular / CMP round / CMP arch). A HeadwallSection (design-H
cantilever wall) assembled into a stem (SectionPrism, openings cut) + footing
(Prism) main leg, plus an optional perpendicular "L" return leg; concrete by
geometry (CY) and reinforcing by tabulated LB/LF.
"""
from __future__ import annotations

import math

from bimforge.author.headwall_section import HeadwallSection
from bimforge.author.model import Element, StructureModel
from bimforge.author.primitives import Prism, SectionPrism

REQUIRED = ("tables", "headwalls")

#: Pipe invert above the top of footing when an opening gives neither
#: `invert_z_ft` nor `center_z_ft`: 6 in, the usual Caltrans practice (a
#: project's specs may set another; give it per opening). The concrete
#: under the invert must have thickness - an opening tangent to the footing
#: leaves a zero-thickness pinch the solid-body gate reports.
DEFAULT_INVERT_FT = 0.5


def circular_void(dia: float, cu: float, cz: float, n: int = 32) -> list:
    """CCW circle of diameter `dia` centred at (cu, cz) in the stem face
    (u = along wall length, z = height)."""
    r = dia / 2.0
    return [(cu + r * math.cos(2 * math.pi * k / n),
             cz + r * math.sin(2 * math.pi * k / n)) for k in range(n)]


def arch_void(span: float, rise: float, cu: float, cz_invert: float,
              n: int = 32) -> list:
    """CCW CMP-arch opening: flat invert at z = cz_invert, span wide, with a
    semi-elliptical crown of height `rise`. Centre `cu` along the wall length."""
    a = span / 2.0
    ring = [(cu - a, cz_invert), (cu + a, cz_invert)]      # invert L->R base
    for k in range(1, n):                                  # crown R->L over top
        th = math.pi * k / n
        ring.append((cu + a * math.cos(th), cz_invert + rise * math.sin(th)))
    return ring


def _opening_ring(o: dict, z0: float) -> list:
    """One opening as a CCW void ring in the stem face (u, z).

    Height above the top of footing (z0): `invert_z_ft` (the pipe invert),
    or `center_z_ft` (the centre, as some sheets dimension it); neither ->
    the invert DEFAULT_INVERT_FT up. Was D/3 + 6 in to the CENTRE, which put
    a 36 in pipe's invert exactly on the footing."""
    cu = float(o["center_ft"])
    if o["shape"] == "cmp_arch":
        cz_inv = z0 + float(o.get("invert_z_ft", DEFAULT_INVERT_FT))
        return arch_void(float(o["span_ft"]), float(o["rise_ft"]), cu, cz_inv)
    dia = float(o["dia_ft"])
    if o.get("center_z_ft") is not None:
        cz = z0 + float(o["center_z_ft"])
    else:
        cz = z0 + float(o.get("invert_z_ft", DEFAULT_INVERT_FT)) + dia / 2.0
    return circular_void(dia, cu, cz)


def _check_openings(name: str, voids: list, length: float, z0: float,
                    z1: float) -> None:
    """Every opening inside the stem face with concrete all round: a void
    touching or crossing the footing, the top of wall or a wall end makes a
    zero-thickness pinch or cuts the stem in two (not a solid body)."""
    for k, ring in enumerate(voids, 1):
        us, zs = [p[0] for p in ring], [p[1] for p in ring]
        why = []
        if min(zs) <= z0 + 1e-6:
            why.append(f"its invert is {min(zs) - z0:+.2f} ft from the top of footing")
        if max(zs) >= z1 - 1e-6:
            why.append(f"its top is {z1 - max(zs):+.2f} ft below the top of wall")
        if min(us) <= 1e-6 or max(us) >= length - 1e-6:
            why.append("it reaches a wall end")
        if why:
            raise ValueError(f"{name}: opening {k} does not fit in the stem - "
                             f"{'; '.join(why)} (set invert_z_ft / center_z_ft"
                             f" / center_ft on the opening)")


def _main_leg(model: StructureModel, name: str, sec: HeadwallSection,
              length: float, openings: list) -> None:
    z0, z1 = sec.F, sec.F + sec.stem_height
    face = [(0.0, z0), (length, z0), (length, z1), (0.0, z1)]
    voids = [_opening_ring(o, z0) for o in openings]
    _check_openings(f"{name} headwall stem", voids, length, z0, z1)
    stem = SectionPrism(f"{name} headwall stem", face, sec.T, y0=sec.C,
                        voids=voids, ifc="IfcWall", layer="S-CONC")
    # a voided SectionPrism carries length + net volume only (box-culvert
    # precedent) -- bounding width/height would trip the gate's LxWxH check.
    model.add(Element.from_geometry(
        stem.name, stem, ifc_class="IfcWall", layer="S-CONC",
        quantities={"length_ft": length, "volume_cf": stem.volume_cf}))
    foot = Prism(f"{name} headwall footing",
                 [(0.0, 0.0), (length, 0.0), (length, sec.W), (0.0, sec.W)],
                 z_bot=0.0, z_top=sec.F, dims_ft=(length, sec.W),
                 ifc="IfcFooting", layer="S-CONC")
    model.add(Element.from_geometry(
        foot.name, foot, ifc_class="IfcFooting", layer="S-CONC",
        quantities={"length_ft": length, "width_ft": sec.W,
                    "height_ft": sec.F, "volume_cf": foot.volume_cf}))


def _return_leg(model: StructureModel, name: str, sec: HeadwallSection,
                length: float, return_len: float) -> None:
    # perpendicular leg at the far end (x = length), running +y; no opening,
    # so the stem is a plain vertical box.
    x0 = length
    rstem = Prism(f"{name} headwall return stem",
                  [(x0 + sec.C, 0.0), (x0 + sec.C + sec.T, 0.0),
                   (x0 + sec.C + sec.T, return_len), (x0 + sec.C, return_len)],
                  z_bot=sec.F, z_top=sec.F + sec.stem_height,
                  dims_ft=(return_len, sec.T), ifc="IfcWall", layer="S-CONC")
    model.add(Element.from_geometry(
        rstem.name, rstem, ifc_class="IfcWall", layer="S-CONC",
        quantities={"length_ft": return_len, "width_ft": sec.T,
                    "height_ft": sec.stem_height, "volume_cf": rstem.volume_cf}))
    rfoot = Prism(f"{name} headwall return footing",
                  [(x0, 0.0), (x0 + sec.W, 0.0),
                   (x0 + sec.W, return_len), (x0, return_len)],
                  z_bot=0.0, z_top=sec.F, dims_ft=(return_len, sec.W),
                  ifc="IfcFooting", layer="S-CONC")
    model.add(Element.from_geometry(
        rfoot.name, rfoot, ifc_class="IfcFooting", layer="S-CONC",
        quantities={"length_ft": return_len, "width_ft": sec.W,
                    "height_ft": sec.F, "volume_cf": rfoot.volume_cf}))


def build(params: dict, ctx) -> StructureModel:
    missing = [k for k in REQUIRED if params.get(k) is None]
    if missing:
        raise ValueError(f"pipe-headwall params missing {missing}")
    table = params["tables"]
    model = StructureModel("pipe-headwall", ctx)
    for hw in params["headwalls"]:
        name = hw["name"]
        sec = HeadwallSection(hw["design_h_ft"], table)
        length = float(hw["length_ft"])
        _main_leg(model, name, sec, length, hw.get("openings", []))
        total_len = length
        if str(hw.get("form", "straight")).lower() == "l" and hw.get("return_len_ft"):
            rl = float(hw["return_len_ft"])
            _return_leg(model, name, sec, length, rl)
            total_len += rl
        steel = sec.reinf_lb_lf * total_len
        model.add(Element(
            f"{name} headwall reinforcing", "IfcReinforcingBar",
            quantities={"length_ft": total_len, "weight_lb": steel},
            layer="S-REBAR"))
    return model
