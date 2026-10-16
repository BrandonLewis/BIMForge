"""approach-slab -- Caltrans B9 structure approach slabs (Types N/R/EQ): a
constant-thickness skewed RC slab placed at a bridge abutment by station, skew,
and roadway width. Concrete pays by CY per type; reinforcement/dowels/joint/
drainage are modeled for QTO and render.

Spec: docs/superpowers/specs/2026-08-31-caltrans-b9-approach-slab-design.md
"""
from __future__ import annotations

import math
from collections import defaultdict

from bimforge.author.alignment import Alignment, _resolve_pob
from bimforge.author.approach_slab_rebar import (
    approach_dowel_bars, approach_slab_bars)
from bimforge.author.approach_slab_section import ApproachSlabSection
from bimforge.author.model import Element, StructureModel
from bimforge.author.primitives import Prism

REQUIRED = ("alignment", "tables", "slabs")

#: Skew is used in width/cos(skew) throughout (transverse bars, joint, pipe);
#: past this it explodes toward a divide-by-zero. Mirrors the fail-loud bound
#: in culvert_headwall_section (_MAX_SKEW_DEG = 85.0).
_MAX_SKEW_DEG = 85.0


def _slab_element_name(name: str, type_key: str) -> str:
    """The IfcSlab concrete element's name for a slab -- the single source of
    truth shared by build() (creation), the pay-isolation check (verification),
    and the bid-side paycodes rules (classification). The type_key suffix lets
    paycodes route concrete CY per slab type (Structural Concrete, Approach
    Slab (Type __))."""
    return f"{name} approach slab {type_key}"


def _emit_bars(model, tag: str, label: str, bars: list) -> None:
    """Group bars by (mark, size) into one IfcReinforcingBar element each."""
    groups = defaultdict(list)
    for b in bars:
        groups[(b.mark, b.size)].append(b)
    for (mark, size), bs in sorted(groups.items()):
        model.add(Element(
            f"{tag} approach {label} {mark} #{size}", "IfcReinforcingBar",
            quantities={"count": len(bs),
                        "length_ft": sum(x.length for x in bs),
                        "weight_lb": sum(x.weight for x in bs)},
            layer="S-REBAR", description=f"#{size} {mark}"))


def _slab_corners(align, station: float, skew_deg: float, length_ft: float,
                  width_ft: float, approach: str) -> list:
    """Four world (n, e) corners of the slab parallelogram, centred on the
    alignment. The slab runs `length_ft` off the abutment seat in the approach
    direction and `width_ft` across; skew shears both transverse edges equally
    (a pure shear, so plan area stays length*width)."""
    n0, e0, az = align.point_az(station)
    azr = math.radians(az)
    t = (math.cos(azr), math.sin(azr))            # travel unit (n, e)
    ln = align.left_normal(station)                # left-normal unit (n, e)
    ap = str(approach).lower()
    if ap not in ("ahead", "back"):
        raise ValueError(f"approach must be 'ahead' or 'back', got {approach!r}")
    sign = 1.0 if ap == "ahead" else -1.0          # ahead/back
    shear = math.tan(math.radians(skew_deg))
    half = width_ft / 2.0
    corners = []
    for a, y in ((0.0, -half), (length_ft, -half), (length_ft, half), (0.0, half)):
        along = sign * a + y * shear
        corners.append((n0 + along * t[0] + y * ln[0],
                        e0 + along * t[1] + y * ln[1]))
    return corners


def _add_joint_and_drainage(model, tag, s, sec, width, skew):
    """Optional transverse joint (LF) and under-slab drainage (TPB area + pipe
    LF) -- each toggleable (default on), each on its own layer/ifc class so it
    never folds into the concrete CY pay line. The joint and slotted pipe run
    parallel to BB/EB along the skewed abutment edge, so their LF stretches by
    1/cos(skew) -- the same factor the transverse rebar uses. The TPB pad is a
    plan-area quantity, which is skew-invariant (parallelogram)."""
    skew_w = float(width) / math.cos(math.radians(skew))
    if s.get("joint", True):
        # a thin ribbon across the roadway (transverse) end of the slab
        model.add(Element(
            f"{tag} approach joint", "IfcCovering",
            quantities={"length_ft": skew_w},
            layer="S-CONC-JT", predefined_type="MEMBRANE",
            description="expansion joint filler + seal (B9)"))
    if s.get("drainage", True):
        # TPB pad = slab footprint area; slotted pipe = one run across the width
        area = float(sec.length_ft) * float(width)
        model.add(Element(
            f"{tag} approach drainage TPB", "IfcBuildingElementProxy",
            quantities={"area_sf": area},
            layer="S-DRAIN", description="treated permeable base (B9-6)"))
        model.add(Element(
            f"{tag} approach drainage pipe", "IfcPipeSegment",
            quantities={"length_ft": skew_w},
            layer="S-DRAIN", description="3-inch slotted plastic pipe (B9-6)"))


def build(params: dict, ctx) -> StructureModel:
    missing = [k for k in REQUIRED if params.get(k) is None]
    if missing:
        raise ValueError(f"approach-slab params missing {missing}")
    pl = params["alignment"]
    align = Alignment(_resolve_pob(pl), pl["run"], name=pl.get("name", "P"))
    table = params["tables"]
    model = StructureModel("approach-slab", ctx)

    for s in params["slabs"]:
        tag = s["name"]
        sec = ApproachSlabSection(s["slab_type"], table)
        width = float(s["width_ft"])
        if width <= 0.0:
            raise ValueError(f"{tag}: width_ft must be positive")
        z0 = float(s.get("soffit_elev_ft", 0.0))
        skew = float(s.get("skew_deg", 0.0))
        if abs(skew) > _MAX_SKEW_DEG:
            raise ValueError(
                f"{tag}: skew_deg {skew} exceeds +/-{_MAX_SKEW_DEG} deg "
                f"(width/cos(skew) becomes unstable near 90 deg)")
        corners = _slab_corners(
            align, float(s["station"]), skew,
            sec.length_ft, width, s.get("approach", "ahead"))
        p = Prism(_slab_element_name(tag, sec.type_key), corners, z0, z0 + sec.thickness_ft,
                  dims_ft=(sec.length_ft, width), ifc="IfcSlab",
                  layer="S-CONC-OTLN")
        model.add(Element.from_geometry(
            p.name, p, ifc_class="IfcSlab", layer="S-CONC-OTLN",
            quantities={"length_ft": sec.length_ft, "width_ft": width,
                        "height_ft": sec.thickness_ft, "area_sf": p.area_sf,
                        "volume_cf": p.volume_cf}))
        _emit_bars(model, tag, "slab reinforcing",
                   approach_slab_bars(sec, width, skew))
        dowels = approach_dowel_bars(sec, width, skew, s.get("abutment_type", "seat"))
        if dowels:
            model.add(Element(
                f"{tag} approach dowels", "IfcReinforcingBar",
                quantities={"count": len(dowels),
                            "length_ft": sum(x.length for x in dowels),
                            "weight_lb": sum(x.weight for x in dowels)},
                layer="S-REBAR", description=f"#{dowels[0].size} dowel"))
        _add_joint_and_drainage(model, tag, s, sec, width, skew)
    model.checks.append(_check_length_vs_type_key(params))
    model.checks.append(_check_pay_isolation(params))
    return model


def _check_length_vs_type_key(params):
    def check(model):
        fail = []
        table = params["tables"]
        for s in params["slabs"]:
            sec = ApproachSlabSection(s["slab_type"], table)
            if abs(sec.length_ft - sec.key_length_ft) > 1e-6:
                fail.append(
                    f"{s['name']}: type key {sec.type_key!r} encodes "
                    f"{sec.key_length_ft} ft but row length_ft is {sec.length_ft}")
        return fail
    return check


def _check_pay_isolation(params):
    def check(model):
        slab_names = {_slab_element_name(s["name"], s["slab_type"]) for s in params["slabs"]}
        fail = []
        for e in model.elements:
            if e.ifc_class == "IfcSlab" and e.name not in slab_names:
                fail.append(
                    f"{e.name}: non-slab element carries IfcSlab (concrete pay "
                    f"class) -- would fold into the CY pay line")
        return fail
    return check
