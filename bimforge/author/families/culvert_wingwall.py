"""culvert-wingwall -- Caltrans box-culvert wingwalls (D84 Types A/B/C straight
flared, D85 Type D straight & Type E stepped, D86 warped). A tapering cantilever
retaining wall: stem + footing (+ stiffening beam for warped). Concrete is
geometry-derived (CY); reinforcing for the stepped (D85 Type E) and warped
(D86) kinds is a generated per-mark bar schedule (wingwall_rebar) whose bar
lengths come from the wingwall geometry, emitted as one weight-only
IfcReinforcingBar per mark; the straight kinds keep a supplied explicit
`reinf_lb` (their steel is by-reference to the adjoining box).
"""
from __future__ import annotations

from collections import defaultdict

from bimforge.author.model import Element, StructureModel
from bimforge.author.primitives import Prism
from bimforge.author.wingwall_rebar import wingwall_bars
from bimforge.author.wingwall_section import (
    WarpedStem, stiffening_beam_prism, taper_footing_prism, taper_stem_prism)
from bimforge.author.wingwall_steel import WingwallSteel

REQUIRED = ("wingwalls",)


def _add_geom(model: StructureModel, prism, ifc: str, box: bool) -> None:
    """Add a concrete Element from a Prism. Clean boxes (with dims_ft) carry
    L x W x H so the gate's LxWxH==volume invariant holds; sloped/trapezoid
    prisms carry length + volume only (which the gate skips)."""
    q = {"volume_cf": prism.volume_cf}
    xs = [p[0] for p in prism.base]
    q["length_ft"] = max(xs) - min(xs)
    if box and prism.dims_ft is not None:
        q["width_ft"] = prism.dims_ft[1]
        q["height_ft"] = (prism.z_top - prism.z_bot)
    model.add(Element.from_geometry(prism.name, prism, ifc_class=ifc,
                                    layer=prism.layer,
                                    quantities=q))


def _emit_bars(model: StructureModel, hw: dict, bars: list) -> None:
    """Emit one weight-only IfcReinforcingBar per (mark, size): count, total
    length, total weight -- aggregated into BAR-STEEL-WW by the paycode. The
    name keeps 'wingwall reinforcing' (the steel paycode rule matches it first,
    so the 'beam' mark is not miscoded as concrete by the `wingwall.*beam`
    rule); the description carries the mark + size for the bar-bending
    schedule."""
    groups: dict = defaultdict(list)
    for b in bars:
        groups[(b.mark, b.size)].append(b)
    for (mark, size), bs in sorted(groups.items()):
        model.add(Element(
            f"{hw['name']} wingwall reinforcing {mark} #{size}",
            "IfcReinforcingBar",
            quantities={"count": len(bs),
                        "length_ft": sum(b.length for b in bs),
                        "weight_lb": sum(b.weight for b in bs)},
            layer="S-REBAR", description=f"#{size} {mark}"))


def _straight(model: StructureModel, hw: dict) -> float:
    """A/B/C/D straight flared wingwall: sloped-top stem + footing. Returns the
    total run length (for reinforcing)."""
    name = hw["name"]
    L = float(hw["length_ft"])
    T, C, B, F = (float(hw["stem_t_ft"]), float(hw["toe_ft"]),
                  float(hw["heel_ft"]), float(hw["foot_t_ft"]))
    h_max = float(hw["wall_h_ft"]) + 0.5   # stem is 6" taller than culvert wall H at the culvert (D84)
    h_min = float(hw["min_h_ft"])
    stem = taper_stem_prism(L, T, C, F, h_max, h_min,
                            name=f"{name} wingwall stem")
    _add_geom(model, stem, "IfcWall", box=False)
    foot = taper_footing_prism(L, C, B, F, heel_toe=hw.get("heel_toe_ft"),
                               name=f"{name} wingwall footing")
    _add_geom(model, foot, "IfcFooting", box=hw.get("heel_toe_ft") is None)
    return L


def _stepped(model: StructureModel, hw: dict) -> float:
    """Type E stepped wingwall: stem as discrete constant-height Prism boxes,
    footing one clean box over the summed length. Returns the total length."""
    name = hw["name"]
    T, C, B, F = (float(hw["stem_t_ft"]), float(hw["toe_ft"]),
                  float(hw["heel_ft"]), float(hw["foot_t_ft"]))
    x = 0.0
    for i, st in enumerate(hw["steps"], start=1):
        li, h = float(st["length_ft"]), float(st["h_ft"])
        box = Prism(f"{name} wingwall stem step {i}",
                    [(x, C), (x + li, C), (x + li, C + T), (x, C + T)],
                    z_bot=F, z_top=F + h, dims_ft=(li, T),
                    ifc="IfcWall", layer="S-CONC")
        _add_geom(model, box, "IfcWall", box=True)
        x += li
    total_len = x
    foot = taper_footing_prism(total_len, C, B, F,
                               name=f"{name} wingwall footing")
    _add_geom(model, foot, "IfcFooting", box=True)
    return total_len


def _warped(model: StructureModel, hw: dict) -> float:
    """D86 warped wingwall: twisted-face stem + optional stiffening beam / toe
    cutoff. Returns the total length."""
    name = hw["name"]
    L = float(hw["length_ft"])
    T, C, B, F = (float(hw["stem_t_ft"]), float(hw["toe_ft"]),
                  float(hw["heel_ft"]), float(hw["foot_t_ft"]))
    h_max = float(hw["wall_h_ft"]) + 0.5
    h_min = float(hw["min_h_ft"])
    batter = float(hw.get("batter_toe", 0.0))
    stem = WarpedStem(f"{name} wingwall stem", length=L, stem_t=T, toe=C,
                      foot_t=F, h_max=h_max, h_min=h_min, batter_toe=batter)
    _add_geom(model, stem, "IfcWall", box=False)
    foot = taper_footing_prism(L, C, B, F, heel_toe=hw.get("heel_toe_ft"),
                               name=f"{name} wingwall footing")
    _add_geom(model, foot, "IfcFooting", box=hw.get("heel_toe_ft") is None)
    sb = hw.get("stiffening_beam")
    if sb:
        beam = stiffening_beam_prism(L, float(sb["w_ft"]), float(sb["d_ft"]),
                                     z0=F + h_max, toe=C,
                                     name=f"{name} wingwall stiffening beam")
        _add_geom(model, beam, "IfcBeam", box=True)
    tc = hw.get("toe_cutoff")
    if tc:
        cw, cd = float(tc["w_ft"]), float(tc["d_ft"])
        cut = Prism(f"{name} wingwall toe cutoff",
                    [(0.0, 0.0), (L, 0.0), (L, cw), (0.0, cw)],
                    z_bot=-cd, z_top=0.0, dims_ft=(L, cw),
                    ifc="IfcFooting", layer="S-CONC")
        _add_geom(model, cut, "IfcFooting", box=True)
    return L


def build(params: dict, ctx) -> StructureModel:
    missing = [k for k in REQUIRED if params.get(k) is None]
    if missing:
        raise ValueError(f"culvert-wingwall params missing {missing}")
    table = params.get("tables") or {}
    steel = WingwallSteel(table["steel"]) if table.get("steel") else None
    model = StructureModel("culvert-wingwall", ctx)
    for hw in params["wingwalls"]:
        kind = hw.get("kind", "straight")
        if kind == "straight":
            total_len = _straight(model, hw)
            if hw.get("reinf_lb"):                # skip None/0 (parity w/ R19)
                model.add(Element(
                    f"{hw['name']} wingwall reinforcing", "IfcReinforcingBar",
                    quantities={"length_ft": total_len,
                                "weight_lb": float(hw["reinf_lb"])},
                    layer="S-REBAR"))
        elif kind in ("stepped", "warped"):
            (_stepped if kind == "stepped" else _warped)(model, hw)
            if steel is None:
                raise ValueError(
                    f"{hw['name']}: {kind} wingwall needs a steel table "
                    f"(params.tables.steel)")
            _emit_bars(model, hw,
                       wingwall_bars(hw, steel, float(hw.get("cover_in", 2.0))))
        else:
            raise ValueError(f"{hw['name']}: unknown wingwall kind {kind!r}")
    return model
