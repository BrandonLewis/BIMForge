"""DXF emitter: modelspace plan geometry + annotation primitives on the
bimforge.cad engine, styled through Phase 2's style packs, deterministically
saved (the pipe-supports-pilot lesson: ezdxf stamps wall-clock times and per-save GUIDs —
24 spurious diff lines per rebuild — unless saved under its fixed-meta
switch, with the sentinels substituted for the model's own build stamp).
"""
from __future__ import annotations

import datetime
import math
import pathlib

import ezdxf

from bimforge.author.emit_ifc import BUILD_STAMP

_SENTINEL_DATE = "2451545.0"                                    # 2000-01-01
_SENTINEL_GUID = "{00000000-0000-0000-0000-000000000000}"
_SENTINEL_MARKER = "0.0 @ 2000-01-01T00:00:00.000000+00:00"
_FIXED_FINGERPRINTGUID = "{B1F04CE0-2026-0815-1200-000000000001}"
_FIXED_VERSIONGUID = "{B1F04CE0-2026-0815-1200-000000000002}"

#: Default author layers (ACI color, description); stylepack `layers:` wins.
LAYERS = {
    "S-CONC-OTLN": (7, "Concrete outlines"),
    "S-REBAR":     (1, "Reinforcing"),
    "S-STEEL":     (5, "Fabricated steel"),
    "S-BOLT":      (6, "Bolts and their plate holes"),
    "S-PIPE-REF":  (8, "Reference pipe - NOT IN SCOPE"),
    "S-ANNO-TEXT": (2, "Annotation"),
    "S-ANNO-DIMS": (4, "Dimensions"),
}


def _doc(stylepack=None):
    from bimforge.cad.stylepack import resolve_style_pack
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 2          # feet
    styles = (stylepack or resolve_style_pack()).styles.get("layers") or {}
    for name, (color, desc) in LAYERS.items():
        attrs = styles.get(name) or {}
        ly = doc.layers.add(name)
        ly.dxf.color = attrs.get("color", color)
        if attrs.get("linetype"):
            ly.dxf.linetype = attrs["linetype"]
        ly.description = desc
    return doc


def txt(msp, s, p, h=0.14, layer="S-ANNO-TEXT", rot=0):
    t = msp.add_text(s, height=h, dxfattribs={"layer": layer, "rotation": rot})
    t.set_placement(p)
    return t


def dim(msp, base, p1, p2, text=None, angle=0):
    d = msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle,
                           dxfattribs={"layer": "S-ANNO-DIMS"},
                           **({"text": text} if text else {}))
    d.render()
    return d


def emit_dxf(model, path, stylepack=None, deterministic: bool = True) -> str:
    prior = ezdxf.options.write_fixed_meta_data_for_testing
    ezdxf.options.write_fixed_meta_data_for_testing = deterministic
    try:
        doc = _doc(stylepack)
        msp = doc.modelspace()
        drawn = 0
        for el in model.elements:
            layer = el.layer or "S-CONC-OTLN"
            if layer not in doc.layers:
                doc.layers.add(layer)
            geoms = (el.geometry if isinstance(el.geometry, (list, tuple))
                     else [el.geometry] if el.geometry is not None else [])
            for g in geoms:
                if hasattr(g, "body_solids"):
                    dicts = g.body_solids()
                elif isinstance(g, dict):
                    dicts = [g]
                else:
                    # bare primitive (no body_solids()) kept only so
                    # check_arc_faceting sees its exact/faceted pair; its
                    # paired placed-solids dict draws the plan footprint.
                    dicts = []
                for d in dicts:
                    drawn += _draw_plan(msp, d, el, layer)
        for annotate in model.dxf_annotations:
            annotate(msp, model)
        # instanced annotation plans (issue #195): same resolved polylines the
        # IFC mapped items carry, so CAD and IFC stationing cannot drift.
        from bimforge.author.annotate import annotate_dxf
        for plan in getattr(model, "annotations", None) or []:
            drawn += annotate_dxf(msp, plan)
        p = pathlib.Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        doc.saveas(p)
        if deterministic:
            _pin_metadata(p)
        return f"{drawn} plan shapes written to {path}"
    finally:
        ezdxf.options.write_fixed_meta_data_for_testing = prior


def _draw_plan(msp, d, el, layer) -> int:
    """Plan-view footprint of one solids dict, in FEET at the element x/y."""
    k = 1.0 if d.get("units", "ft") == "ft" else 1.0 / 12.0
    ox, oy = el.x_ft, el.y_ft
    # bearing is constant per element: resolve the rotation once, not per vertex.
    _b = el.bearing_deg
    if _b:
        _th = math.radians(_b)
        _c, _s = math.cos(_th), math.sin(_th)

    def pl(u, v):
        """Local (u, v) -> placed plan coord: rotate by bearing_deg about the
        element origin, then offset by (ox, oy). Guarded so bearing_deg == 0
        reduces EXACTLY to the old (ox + u*k, oy + v*k)."""
        x, y = u * k, v * k
        if _b:
            x, y = _c * x - _s * y, _s * x + _c * y
        return (ox + x, oy + y)

    n = 0
    if d["kind"] == "prism":
        msp.add_lwpolyline([pl(u, v) for u, v in d["base"]],
                           close=True, dxfattribs={"layer": layer})
        n += 1
        for h in d.get("holes", []):
            msp.add_lwpolyline([pl(u, v) for u, v in h],
                               close=True, dxfattribs={"layer": layer})
            n += 1
    elif d["kind"] == "box":
        for box in d["boxes"]:
            cx, cy, _cz, dx, dy, _dz = box[:6]
            msp.add_lwpolyline(
                [pl(cx - dx / 2, cy - dy / 2),
                 pl(cx + dx / 2, cy - dy / 2),
                 pl(cx + dx / 2, cy + dy / 2),
                 pl(cx - dx / 2, cy + dy / 2)],
                close=True, dxfattribs={"layer": layer})
            n += 1
    elif d["kind"] == "rod":
        for cx, cy, _cz in d["centres"]:
            msp.add_circle(pl(cx, cy), d["radius"] * k,
                           dxfattribs={"layer": layer})
            n += 1
    elif d["kind"] == "tube":
        msp.add_circle(pl(0.0, 0.0), d["r_outer"] * k,
                       dxfattribs={"layer": layer})
        n += 1
    elif d["kind"] == "fill":
        # backfill: the GROSS base ring is the plan footprint (the cuts are
        # interior structure — their owners draw their own footprints).
        msp.add_lwpolyline([pl(u, v) for u, v in d["base"]],
                           close=True, dxfattribs={"layer": layer})
        n += 1
        for h in d.get("holes", []):          # inner rings, same as prism
            msp.add_lwpolyline([pl(u, v) for u, v in h],
                               close=True, dxfattribs={"layer": layer})
            n += 1
    elif d["kind"] == "mesh":
        # a mesh with a declared plan footprint (SectionPrism/BatteredWall)
        # draws each ring; a bare mesh (R5a terrain) still draws nothing.
        for ring in d.get("plan") or []:
            msp.add_lwpolyline([pl(u, v) for u, v in ring],
                               close=True, dxfattribs={"layer": layer})
            n += 1
    elif d["kind"] == "swept_disk":
        # plan trace of the bar: its centreline directrix (arcs tessellated),
        # projected to x/y as an open polyline.
        from bimforge.author.primitives import densify_directrix
        chain = densify_directrix(d["verts"], d["segments"])
        msp.add_lwpolyline([pl(x, y) for x, y, _z in chain],
                           dxfattribs={"layer": layer})
        n += 1
    elif d["kind"] == "ribbon":
        # plan trace of a draped ribbon (issue #192): its centreline polyline.
        msp.add_lwpolyline([pl(x, y) for x, y, _z in d["points"]],
                           dxfattribs={"layer": layer})
        n += 1
    # arc_band / gusset are section-plane members: no plan footprint; the
    # family draws them via dxf_annotations (pipe-supports-pilot's section view).
    return n


def _pin_metadata(path: pathlib.Path) -> None:
    from ezdxf.tools import juliandate
    stamp = datetime.datetime.fromisoformat(BUILD_STAMP)
    text = path.read_text(encoding="utf-8")
    fixed_marker = (
        f"{ezdxf.__version__} @ "
        f"{stamp.replace(tzinfo=datetime.timezone.utc).isoformat(timespec='microseconds')}")
    text = text.replace(_SENTINEL_DATE, repr(juliandate(stamp)))
    text = text.replace(_SENTINEL_GUID, _FIXED_FINGERPRINTGUID, 1)
    text = text.replace(_SENTINEL_GUID, _FIXED_VERSIONGUID, 1)
    text = text.replace(_SENTINEL_MARKER, fixed_marker)
    path.write_text(text, encoding="utf-8")
