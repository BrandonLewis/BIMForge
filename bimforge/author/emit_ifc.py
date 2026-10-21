"""IFC emitter (spec §1/§2): ifcopenshell.api, extending dxf2bim's pattern.

* georef REQUIRED from ProjectContext (`allow_local=True` is the explicit
  opt-out — the rebar-pilot regression made local-only-by-accident a named bug);
* Qto_BaseQuantities with the L x W invariant: Height is the VOLUME-EQUIVALENT
  mean height (volume/area) and Length x Width == GrossArea exactly, so a
  downstream count x L x W x H reproduces GrossVolume to the last decimal
  (bridge-pilot `_plan_dims_ft` / `base_quantities`, ported);
* BidSchedule classification references, one IfcClassificationReference per
  code, associating ALL that code's products (multi-code elements carry one
  association per code — IFC4X3 permits it; the reader has been multi-code
  since 0.1.33);
* openings as IfcOpeningElement voids; assemblies as IfcElementAssembly;
* deterministic GUIDs from ProjectContext (elements by guid_key; every other
  IfcRoot swept afterward in file order) and a pinned header timestamp, so a
  rebuild of an unchanged model is byte-identical;
* presentation styling (IfcSurfaceStyle / IfcPresentationLayerAssignment /
  IfcMaterial) from `bimforge.author.ifc_styles` — presentation-only: it must
  never affect geometry, GUIDs, quantities, or determinism.
"""
from __future__ import annotations

import math
import sys
import warnings

import numpy as np

from bimforge.author.alignment import poly_area
from bimforge.author.ifc_styles import resolve_surface, sanitize_pack
from bimforge.author.primitives import (
    ARC_SEGMENTS, equal_area_polygon_radius, exact_of,
    taper_prism_triangles)
from bimforge.cad.stylepack import resolve_style_pack

BUILD_STAMP = "2026-08-15T12:00:00"


class GeoreferenceError(ValueError):
    pass


class DuplicateGuidError(ValueError):
    """Two elements resolve to the same GlobalId.

    `StructureModel.add` dedupes elements by NAME only; an explicit
    `guid_key` override on two differently-named elements collides silently
    and corrupts the IFC (two products would claim one GlobalId). Verified
    BEFORE any ifcopenshell write.
    """


# --------------------------------------------------------------- quantities
#: length:width above which `width` is really a section thickness, not a
#: plan-rectangle side (#180). Cosmetic threshold — no pay measure reads Length
#: on such an element — kept generous so an honest long-thin run never trips it.
_THICKNESS_ASPECT = 500.0


def _is_thickness_aspect(length: float, width: float) -> bool:
    """True when the length:width ratio is so extreme that `width` can only be a
    section thickness, not a side of the plan/face rectangle (#180)."""
    return length > 0.0 and width > 0.0 and length / width > _THICKNESS_ASPECT


def _rectangle_from_perimeter(area_ft2: float, perim_ft: float):
    """The rectangle with this area AND perimeter, or None if none exists
    (footprint too squat for a real solution). Exact for a true rectangle."""
    half = perim_ft / 2.0
    disc = half * half - 4.0 * area_ft2
    if disc > 0.0:
        root = math.sqrt(disc)
        w = (half - root) / 2.0
        if w > 1e-9:
            return (area_ft2 / w, w)
    return None


def plan_dims_ft(el, area_ft2: float, perim_ft: float):
    """(length, width) in feet whose PRODUCT IS THE PLAN AREA, exactly.

    Width comes from a known section (`dims_ft` on the geometry, or explicit
    width_ft) when available; otherwise from the rectangle with this
    footprint's own area AND perimeter (exact for a rectangle, close for a
    slightly curved strip); footprints too squat for a real solution fall
    back to a square of the same area. (bridge-pilot port.)

    But `width_ft` is the SOLID's section width — a valid plan-rectangle side
    only when `area_sf` is the footprint. When `area_sf` is a FACE, dividing it
    by the section thickness invents an absurd Length (#180: a 15 ft lagging bay
    reported 253 ft). When width_ft is that extreme it is discarded for a real
    plan side — `length_ft` when the element carries one (recovering the true
    face rectangle), else the area+perimeter rectangle solve. If neither yields
    a better rectangle the original (length, width) is kept, so a genuine
    long-thin run is never regressed to a square (the square fallback above
    applies only when width_ft is absent entirely). Either way Length x Width
    still equals the area, and no phantom length is emitted.
    """
    width = el.quantities.get("width_ft")
    if width is None:
        dims = getattr(el.geometry, "dims_ft", None)
        if dims is not None:
            width = abs(dims[1])
    if width and width > 1e-9:
        length = area_ft2 / width
        if not _is_thickness_aspect(length, width):
            return (length, width)
        # width_ft is a section thickness, not a plan side (#180). Warn, then
        # override it ONLY when we have a concretely better rectangle — a real
        # plan side (length_ft) or a valid area+perimeter solve — so a genuine
        # long-thin run (no length_ft, squat/absent perimeter) is NOT regressed
        # to a meaningless square; it keeps its (length, width).
        _warn_if_width_is_a_thickness(el, area_ft2, length, width)
        length_ft = el.quantities.get("length_ft")
        if length_ft and length_ft > 1e-9:
            w = area_ft2 / length_ft
            if not _is_thickness_aspect(length_ft, w):
                return (length_ft, w)      # recovers the true face rectangle
        rect = _rectangle_from_perimeter(area_ft2, perim_ft)
        if rect is not None and not _is_thickness_aspect(*rect):
            return rect
        return (length, width)
    rect = _rectangle_from_perimeter(area_ft2, perim_ft)
    if rect is not None:
        return rect
    side = math.sqrt(area_ft2) if area_ft2 > 0.0 else 0.0
    return (side, side)


def _style_name(appear: dict, key: str | None) -> str:
    """A name a human reads in a viewer's style list.

    The material first (what the thing IS), else the layer or class it
    resolved on. The old `surf-0.75-0.73-0.68-0.0` told a reader nothing and
    changed whenever a colour was tuned.
    """
    return appear.get("material") or key or "Surface"


def _surface_style(run, f, cache: dict, appear: dict, key: str | None):
    """The cached IfcSurfaceStyle for one resolved appearance.

    IfcSurfaceStyleRendering when the appearance carries EITHER finish field
    (it is a SUBTYPE of IfcSurfaceStyleShading, so every reader that handled
    the old flat style still does), otherwise plain shading exactly as before.
    Cached on the full appearance so two entries that differ only in finish do
    not collapse onto one style.
    """
    name = _style_name(appear, key)
    skey = (name, tuple(appear["rgb"]), appear["transparency"],
            appear.get("reflectance"), appear.get("specular"))
    style = cache.get(skey)
    if style is not None:
        return style
    colour = {"Name": None, "Red": appear["rgb"][0],
              "Green": appear["rgb"][1], "Blue": appear["rgb"][2]}
    attrs = {"SurfaceColour": colour, "Transparency": appear["transparency"]}
    ifc_class = "IfcSurfaceStyleShading"
    # EITHER finish field promotes to rendering: they are documented as
    # independently optional, so a specular set without a reflectance method
    # must not be silently dropped. ReflectanceMethod is mandatory on the
    # entity, and NOTDEFINED is what the enum provides for exactly this.
    if appear.get("reflectance") or appear.get("specular") is not None:
        ifc_class = "IfcSurfaceStyleRendering"
        attrs["ReflectanceMethod"] = appear.get("reflectance") or "NOTDEFINED"
        attrs["DiffuseColour"] = 1.0 - float(appear["transparency"])
        if appear.get("specular") is not None:
            attrs["SpecularHighlight"] = {
                "IfcSpecularRoughness": float(appear["specular"])}
    style = run("style.add_style", f, name=name)
    run("style.add_surface_style", f, style=style,
        ifc_class=ifc_class, attributes=attrs)
    cache[skey] = style
    return style


def _warn_if_width_is_a_thickness(el, area_ft2: float, length: float,
                                  width: float) -> None:
    """Flag a `width_ft` that is a SECTION thickness, not a plan-rectangle side.

    `width_ft` serves two masters: the gate's `count x L x W x H == volume`
    invariant wants the solid's section width, while `plan_dims_ft` wants a
    side of the plan rectangle. They agree for a run-shaped solid whose
    `area_sf` IS its footprint, and disagree whenever `area_sf` is a FACE and
    `width_ft` a thickness - dividing one by the other reports a Length nobody
    could build (seen in the field as Length = 1,066 ft on a 22 sf covering
    whose width_ft was a 1/4" skin, and 253 ft on a 15 ft bay of lagging).

    Deliberately just the aspect ratio. Comparing `area_sf` against the
    element's own plan footprint sounds sharper and is not: a face area with a
    correct face width trips it too, and a guard that cries wolf gets muted.
    Cosmetic either way - no pay measure reads Length on such an element - so
    warn and carry on.
    """
    if _is_thickness_aspect(length, width):
        warnings.warn(
            f"{el.name}: width_ft {width:g} ft gives Length {length:,.0f} ft "
            f"on {area_ft2:,.1f} sf - width_ft should be a side of the plan "
            f"rectangle, not a section thickness", UserWarning, stacklevel=3)


def base_quantities(el, ft_to_m: float):
    """[(ifc entity, quantity name, SI value)] for one element.

    The NAMES are the API — `bimforge.bim.ifc_takeoff` and a takeoff map's
    `measure:` key on exactly these strings — so emit ALL of them and let the
    map choose (the sample-bridge gap-#1 lesson: one measure per element is not
    enough).
    """
    q = el.quantities
    out = [("IfcQuantityCount", "Count", float(int(q.get("count", 1) or 1)))]
    vol_cf = q.get("volume_cf")
    if vol_cf is not None:
        out.append(("IfcQuantityVolume", "GrossVolume", vol_cf * ft_to_m ** 3))
    area = q.get("area_sf")
    base = getattr(el.geometry, "base", None)
    if area is None and base:
        area = poly_area(base)
    if area is None and q.get("length_ft") and q.get("width_ft"):
        # A swept member (SectionPrism, tube) declares its pay length and
        # section width but carries no footprint (#371): the footprint IS
        # L x W, which keeps Length x Width == GrossArea and makes Height the
        # volume-equivalent mean height of the run.
        area = q["length_ft"] * q["width_ft"]
    if area:
        perim = q.get("perimeter_ft")
        if perim is None and base:
            perim = sum(math.dist(base[i], base[(i + 1) % len(base)])
                        for i in range(len(base)))
        perim = perim or 4.0 * math.sqrt(area)
        h_ft = (vol_cf / area) if vol_cf else q.get("height_ft", 0.0) or 0.0
        length_ft, width_ft = plan_dims_ft(el, area, perim)
        # A declared length_ft is the payment length and beats one derived from
        # area+perimeter: a swept member (SectionPrism/tube) whose area_sf is a
        # CROSS-SECTION, not a plan footprint, must not have that section area
        # override its stated LF pay line (#252). Recompute width from the area
        # so the L x W == GrossArea invariant (check_lxw_volume) still holds:
        # width becomes the mean width implied by the footprint and pay length.
        if q.get("length_ft") is not None:
            length_ft = q["length_ft"]
            if length_ft:
                width_ft = area / length_ft
        out.append(("IfcQuantityArea", "GrossArea", area * ft_to_m ** 2))
        out.append(("IfcQuantityLength", "Perimeter", perim * ft_to_m))
        out.append(("IfcQuantityLength", "Height", h_ft * ft_to_m))
        out.append(("IfcQuantityLength", "Length", length_ft * ft_to_m))
        out.append(("IfcQuantityLength", "Width", width_ft * ft_to_m))
    else:
        for name, key in (("Length", "length_ft"), ("Width", "width_ft"),
                          ("Height", "height_ft")):
            if q.get(key) is not None:
                out.append(("IfcQuantityLength", name, q[key] * ft_to_m))
    if q.get("surface_sf") is not None:
        out.append(("IfcQuantityArea", "OuterSurfaceArea",
                    q["surface_sf"] * ft_to_m ** 2))
    w = el.weight_lb
    if w is not None:
        out.append(("IfcQuantityWeight", "GrossWeight", w * 0.45359237))  # kg
    return out


_QTY_ATTR = {"IfcQuantityArea": "AreaValue", "IfcQuantityLength": "LengthValue",
             "IfcQuantityVolume": "VolumeValue", "IfcQuantityCount": "CountValue",
             "IfcQuantityWeight": "WeightValue"}


# ------------------------------------------------------------------ geometry
def _profile(f, ring, holes=()):
    def pl(points):
        pts = [f.create_entity("IfcCartesianPoint", Coordinates=(float(u), float(v)))
               for u, v in points]
        return f.create_entity("IfcPolyline", Points=pts + [pts[0]])
    if holes:
        return f.create_entity(
            "IfcArbitraryProfileDefWithVoids", ProfileType="AREA",
            OuterCurve=pl(ring), InnerCurves=[pl(h) for h in holes])
    return f.create_entity("IfcArbitraryClosedProfileDef", ProfileType="AREA",
                           OuterCurve=pl(ring))


def _place3(f, x, y, z, axis=None, ref=None):
    kw = {"Location": f.create_entity("IfcCartesianPoint",
                                      Coordinates=(float(x), float(y), float(z)))}
    if axis:
        kw["Axis"] = f.create_entity("IfcDirection", DirectionRatios=axis)
    if ref:
        kw["RefDirection"] = f.create_entity("IfcDirection", DirectionRatios=ref)
    return f.create_entity("IfcAxis2Placement3D", **kw)


def _extrude(f, profile, pos, depth_m):
    return f.create_entity(
        "IfcExtrudedAreaSolid", SweptArea=profile, Position=pos,
        ExtrudedDirection=f.create_entity("IfcDirection",
                                          DirectionRatios=(0.0, 0.0, 1.0)),
        Depth=float(depth_m))


def _faceted_brep(f, triangles):
    """An IfcFacetedBrep from explicit triangular facets (metres): the
    per-vertex-top Prism taper has no uniform sweep depth, so it cannot be
    an IfcExtrudedAreaSolid. Every individual facet is trivially planar (3
    points), so this represents the triangulated loft exactly."""
    faces = []
    for tri in triangles:
        pts = [f.create_entity("IfcCartesianPoint",
                               Coordinates=tuple(float(c) for c in p))
               for p in tri]
        loop = f.create_entity("IfcPolyLoop", Polygon=pts)
        bound = f.create_entity("IfcFaceOuterBound", Bound=loop, Orientation=True)
        faces.append(f.create_entity("IfcFace", Bounds=[bound]))
    shell = f.create_entity("IfcClosedShell", CfsFaces=faces)
    return f.create_entity("IfcFacetedBrep", Outer=shell)


D_X, D_Y, D_Z = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)


def _dot(a, b):
    return sum(p * q for p, q in zip(a, b))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _parametric_solid(f, d, k):
    """The exact IfcExtrudedAreaSolid an "extrusion" dict names (#330).

    The dict's profile plane {"o", "x", "y"} becomes the IfcAxis2Placement3D
    (RefDirection x, Axis x × y, so the profile's (u, v) land on (x, y)
    unchanged) and the sweep vector is re-expressed in that placement's own
    frame, which is what IFC measures it in. The voids are the profile's
    InnerCurves — no keyhole bridge on this path.
    """
    pl = d["plane"]
    x, y = pl["x"], pl["y"]
    z = _cross(x, y)
    sign = 1.0
    if _dot(d["dir"], z) < 0:
        # keep the sweep on the placement's +Z side (a mirrored frame lands
        # it on -Z): flip RefDirection and the profile's u with it, which
        # draws the same section and flips Axis = x × y.
        x, sign, z = tuple(-c for c in x), -1.0, tuple(-c for c in z)
    prof = _profile(f, [(sign * u * k, v * k) for u, v in d["profile"]],
                    [[(sign * u * k, v * k) for u, v in h]
                     for h in d.get("voids") or ()])
    o = pl["o"]
    pos = _place3(f, o[0] * k, o[1] * k, o[2] * k, axis=z, ref=x)
    v = d["dir"]
    depth = math.sqrt(_dot(v, v))
    local = tuple(_dot(v, e) / depth for e in (x, y, z))
    return f.create_entity(
        "IfcExtrudedAreaSolid", SweptArea=prof, Position=pos,
        ExtrudedDirection=f.create_entity("IfcDirection",
                                          DirectionRatios=local),
        Depth=float(depth * k))


def _ensure_radians(f) -> None:
    """Declare a radian PLANEANGLEUNIT on the project's unit assignment, once.

    Only a file that writes a plane angle needs one, and a file that does
    and declares none leaves its reader to guess; adding it only then keeps
    every other file byte-identical (test_ifc4_golden)."""
    for ua in f.by_type("IfcUnitAssignment"):
        if any(getattr(u, "UnitType", None) == "PLANEANGLEUNIT"
               for u in ua.Units):
            continue
        ua.Units = list(ua.Units) + [f.create_entity(
            "IfcSIUnit", UnitType="PLANEANGLEUNIT", Name="RADIAN")]


def _revolved_solid(f, d, k):
    """The exact IfcRevolvedAreaSolid a "revolution" dict names (#331).

    The profile plane becomes the Position as for an extrusion (RefDirection
    x, Axis x × y), and the turning axis — a line in that plane — is
    re-expressed in the Position's own frame, which is what IFC measures it
    in. The angle is radians, and the file says so (_ensure_radians).
    """
    _ensure_radians(f)
    pl, ax = d["plane"], d["axis"]
    x, y = pl["x"], pl["y"]
    z = _cross(x, y)
    o = pl["o"]
    prof = _profile(f, [(u * k, v * k) for u, v in d["profile"]],
                    [[(u * k, v * k) for u, v in h]
                     for h in d.get("voids") or ()])
    rel = tuple(a - b for a, b in zip(ax["o"], o))
    loc = (_dot(rel, x) * k, _dot(rel, y) * k)
    a = ax["dir"]
    return f.create_entity(
        "IfcRevolvedAreaSolid", SweptArea=prof,
        Position=_place3(f, o[0] * k, o[1] * k, o[2] * k, axis=z, ref=x),
        Axis=f.create_entity(
            "IfcAxis1Placement",
            Location=f.create_entity("IfcCartesianPoint",
                                     Coordinates=(float(loc[0]),
                                                  float(loc[1]), 0.0)),
            Axis=f.create_entity("IfcDirection", DirectionRatios=(
                float(_dot(a, x)), float(_dot(a, y)), 0.0))),
        Angle=float(d["angle"]))


def _sectioned_solid(f, d, k, curve):
    """One IfcSectionedSolidHorizontal along the alignment's IfcCurve (#332).

    Sections sit at their DistanceAlong — horizontal distance from the
    alignment's start station — with the placement left implicit, the one
    form ifcopenshell 0.9 draws correctly. IFC 4.3 then squares each section
    to the curve's 3D tangent: pitched with the grade, SweptSection's
    "normal" frame (its exact_reason says when a plumb sweep is close
    enough). Profile u runs to the LEFT of travel, v up the pitched axis,
    the sweep's own section convention.
    """
    s0 = d["alignment"].s_start
    sections, positions = [], []
    for sec in d["sections"]:
        sections.append(_profile(
            f, [(u * k, v * k) for u, v in sec["outer"]],
            [[(u * k, v * k) for u, v in h] for h in sec["voids"]]))
        positions.append(f.create_entity(
            "IfcAxis2PlacementLinear",
            Location=f.create_entity(
                "IfcPointByDistanceExpression",
                DistanceAlong=f.create_entity("IfcLengthMeasure",
                                              float((sec["s"] - s0) * k)),
                BasisCurve=curve)))
    return f.create_entity("IfcSectionedSolidHorizontal", Directrix=curve,
                           CrossSections=sections,
                           CrossSectionPositions=positions)


#: IfcShapeRepresentation.RepresentationType -> the item entities it admits
#: (IFC4 IfcShapeRepresentationTypes / the implementer agreement). Most
#: specific first: representation_type() names the FIRST that admits every
#: item. #329: the old chain fell through to "SweptSolid" for anything it did
#: not name, so every IfcFacetedBrep shipped labelled a swept solid.
REPRESENTATION_ITEMS = {
    "SweptSolid": ("IfcExtrudedAreaSolid", "IfcRevolvedAreaSolid"),
    "AdvancedSweptSolid": ("IfcSweptAreaSolid", "IfcSweptDiskSolid",
                           "IfcSectionedSolidHorizontal"),
    "Brep": ("IfcFacetedBrep",),
    "AdvancedBrep": ("IfcManifoldSolidBrep",),
    "CSG": ("IfcBooleanResult", "IfcCsgPrimitive3D", "IfcCsgSolid"),
    "Tessellation": ("IfcTessellatedItem",),
    "SolidModel": ("IfcSolidModel",),
}
#: tapered sweeps are an AdvancedSweptSolid, never a plain SweptSolid
_NOT_SWEPT_SOLID = ("IfcExtrudedAreaSolidTapered", "IfcRevolvedAreaSolidTapered")


def admits(rep_type: str, item) -> bool:
    """Whether `rep_type` admits `item` (False for an unknown rep_type)."""
    if rep_type == "SweptSolid" and any(item.is_a(e) for e in _NOT_SWEPT_SOLID):
        return False
    return any(item.is_a(e) for e in REPRESENTATION_ITEMS.get(rep_type, ()))


def representation_type(items, where: str = "") -> str:
    """The RepresentationType that names every item in a Body representation.

    Raises rather than guess: a label that does not match its items is
    invisible to ifcopenshell.validate (RepresentationType is a bare
    IfcLabel) but fails strict importers and MVD/IDS checkers.
    """
    for rep_type in REPRESENTATION_ITEMS:
        if all(admits(rep_type, i) for i in items):
            return rep_type
    raise ValueError(
        f"{where}: no RepresentationType admits the item mix "
        f"{sorted({i.is_a() for i in items})} — give the mixed solids "
        "their own Elements")


def body_dicts(el):
    """Each geometry's body_solids() dicts, in order — the one expansion
    solids_for writes from and the gate re-reads exact solids from."""
    geoms = el.geometry if isinstance(el.geometry, (list, tuple)) else [el.geometry]
    out = []
    for g in geoms:
        if hasattr(g, "body_solids"):
            out.append(g.body_solids())
        elif isinstance(g, dict):
            out.append([g])
        # else a bare primitive with no body_solids() (Plate/ArcBand/
        # ShapedStiffener/Bolt): listed alongside its placed-solids dict so
        # check_arc_faceting sees the exact/faceted pair; it carries no
        # geometry of its own, so it emits nothing here.
    return out


def sweep_key(ex) -> tuple:
    """The alignment an exact sweep runs on: emit_alignments' curves key."""
    return (id(ex["alignment"]), id(ex["vprofile"]), id(ex["origin"]))


def solids_for(f, el, ft_to_m: float, curves=None):
    """Every IfcExtrudedAreaSolid of one element, from its body_solids dicts.

    Solid coordinates are relative to the ELEMENT's placement. `units` per
    dict: "ft" (structure primitives) or "in" (steel members). `curves` is
    emit_alignments' {sweep_key: IfcCurve}; an exact alignment sweep whose
    alignment has no curve there (IFC4, or a call without one) is written as
    its mesh.
    """
    out = []
    for dicts in body_dicts(el):
        for d in dicts:
            k = ft_to_m if d.get("units", "ft") == "ft" else ft_to_m / 12.0
            kind = d["kind"]
            if kind == "none":
                # geometry-less sentinel: the {"kind":"none"} form some
                # families/specs use in place of geometry=None for a
                # quantity-only element (rebar/hardware). Emits no solid,
                # exactly as geometry=None does. (#255)
                continue
            if kind == "prism":
                ring = [(u * k, v * k) for u, v in d["base"]]
                holes = [[(u * k, v * k) for u, v in h] for h in d.get("holes", [])]
                if d.get("z_top") is not None and d.get("bottom_z") is None:
                    pos = _place3(f, 0, 0, d["z_bot"] * k)
                    out.append(_extrude(f, _profile(f, ring, holes), pos,
                                        (d["z_top"] - d["z_bot"]) * k))
                else:
                    # per-vertex top and/or per-vertex bottom (a taper / wedge):
                    # no uniform sweep depth exists, so a triangulated B-rep is
                    # the only exact representation (holes are not supported
                    # combined with a per-vertex face; not exercised by any
                    # shipped family). (#251 adds the bottom_z leg.)
                    top_z = (d["top_z"] if d.get("top_z") is not None
                             else [d["z_top"]] * len(ring))
                    bottom_z = ([z * k for z in d["bottom_z"]]
                                if d.get("bottom_z") is not None else None)
                    tris = taper_prism_triangles(
                        ring, [z * k for z in top_z], d["z_bot"] * k, bottom_z)
                    out.append(_faceted_brep(f, tris))
            elif kind == "fill":
                # backfill (bridge-pilot port): the gross prism chained-DIFFERENCEd
                # by each cut. The result IS the backfill — the excavated
                # void less the structure standing in it — so a viewer shows
                # the real shape and ifcopenshell derives the real volume
                # from it. Lands in the representation as type "CSG".
                ring = [(u * k, v * k) for u, v in d["base"]]
                holes = [[(u * k, v * k) for u, v in h] for h in d.get("holes", [])]
                pos = _place3(f, 0, 0, d["z_bot"] * k)
                acc = _extrude(f, _profile(f, ring, holes), pos,
                               (d["z_top"] - d["z_bot"]) * k)
                for c in d["cuts"]:
                    if c.get("top_z") is not None:
                        raise ValueError(
                            f"{el.name}: fill cut has a per-vertex top "
                            "(top_z) — not portable to a clean boolean "
                            "difference; cuts must be flat-topped (z_top)")
                    c_ring = [(u * k, v * k) for u, v in c["base"]]
                    c_holes = [[(u * k, v * k) for u, v in h]
                               for h in c.get("holes", [])]
                    tool = _extrude(
                        f, _profile(f, c_ring, c_holes),
                        _place3(f, 0, 0, c["z_bot"] * k),
                        (c["z_top"] - c["z_bot"]) * k)
                    acc = f.create_entity(
                        "IfcBooleanResult", Operator="DIFFERENCE",
                        FirstOperand=acc, SecondOperand=tool)
                out.append(acc)
            elif kind == "box":
                dia = d.get("hole_dia", 0.0)
                segs = d.get("segments", ARC_SEGMENTS)
                for box in d["boxes"]:
                    cx, cy, cz, dx, dy, dz = box[:6]
                    holes_c = box[6] if len(box) > 6 else []
                    ring = [(-dx / 2 * k, -dy / 2 * k), (dx / 2 * k, -dy / 2 * k),
                            (dx / 2 * k, dy / 2 * k), (-dx / 2 * k, dy / 2 * k)]
                    holes = []
                    if holes_c and dia > 0:
                        r = equal_area_polygon_radius(dia / 2.0, segs)
                        for u, v in holes_c:
                            holes.append([
                                ((u + r * math.cos(-2 * math.pi * i / segs)) * k,
                                 (v + r * math.sin(-2 * math.pi * i / segs)) * k)
                                for i in range(segs)])
                    pos = _place3(f, cx * k, cy * k, (cz - dz / 2.0) * k)
                    out.append(_extrude(f, _profile(f, ring, holes), pos, dz * k))
            elif kind == "rod":
                segs, r = d["segments"], d["radius"]
                ring = [(r * math.cos(2 * math.pi * i / segs) * k,
                         r * math.sin(2 * math.pi * i / segs) * k)
                        for i in range(segs)]
                r_in = d.get("r_inner")          # None/0 -> a solid bar (rebar/bolts)
                holes = []
                if r_in:
                    # opposite (clockwise) winding for the void loop, same
                    # convention the "box" bolt-hole rings above use.
                    holes = [[(r_in * math.cos(-2 * math.pi * i / segs) * k,
                              r_in * math.sin(-2 * math.pi * i / segs) * k)
                             for i in range(segs)]]
                prof = _profile(f, ring, holes)
                for cx, cy, cz in d["centres"]:
                    if d["axis"] == "z":
                        pos = _place3(f, cx * k, cy * k, (cz - d["length"] / 2.0) * k)
                    elif d["axis"] == "x":
                        pos = _place3(f, (cx - d["length"] / 2.0) * k, cy * k,
                                      cz * k, axis=D_X, ref=D_Y)
                    else:
                        pos = _place3(f, cx * k, (cy - d["length"] / 2.0) * k,
                                      cz * k, axis=D_Y, ref=D_Z)
                    out.append(_extrude(f, prof, pos, d["length"] * k))
            elif kind == "mesh":
                # indexed triangle mesh (terrain, or any measured surface):
                # verts scaled by the dict's units factor, one facet per
                # triangle — the same exact-triangulation argument as the
                # taper above. An optional "provenance" dict on this solids
                # dict emits as Pset_BimforgeTerrain (see the element loop).
                # A mesh that still IS its exact form is written as that
                # solid instead (#330, #332; primitives.exact_of).
                ex = exact_of(d)
                curve = ((curves or {}).get(sweep_key(ex))
                         if ex and ex["kind"] == "sectioned" else None)
                if ex and ex["kind"] == "extrusion":
                    out.append(_parametric_solid(f, ex, k))
                elif ex and ex["kind"] == "revolution":
                    out.append(_revolved_solid(f, ex, k))
                elif (curve is not None
                      and not any((el.x_ft, el.y_ft, el.z_ft,
                                   el.bearing_deg))):
                    # an alignment sweep on its curve — unless the file has
                    # no directrix (IFC4, or an opening host: see
                    # emit_combined_ifc) or the element is placed, which
                    # the absolute curve would not follow
                    out.append(_sectioned_solid(f, ex, k, curve))
                else:
                    verts = [tuple(float(c) * k for c in v)
                             for v in d["verts"]]
                    out.append(_faceted_brep(
                        f, [tuple(verts[i] for i in tri) for tri in d["tris"]]))
            elif kind == "arc_band":
                n = d["segments"]
                wrap = math.radians(d["wrap_deg"])
                start = math.radians(d.get("start_deg", 180.0))
                r_i, r_o = d["r_inner"], d["r_outer"]
                ang = [start + wrap * i / n for i in range(n + 1)]
                ring = ([(r_o * math.cos(a) * k, r_o * math.sin(a) * k) for a in ang]
                        + [(r_i * math.cos(a) * k, r_i * math.sin(a) * k)
                           for a in reversed(ang)])
                pos = _place3(f, (d["cx"] - d["width"] / 2.0) * k, 0.0,
                              d["cz"] * k, axis=D_X, ref=D_Y)
                out.append(_extrude(f, _profile(f, ring), pos, d["width"] * k))
            elif kind == "gusset":
                for cx, ring_uv in d["placements"]:
                    ring = [(u * k, v * k) for u, v in ring_uv]
                    pos = _place3(f, (cx - d["thickness"] / 2.0) * k, 0.0,
                                  d["cz"] * k, axis=D_X, ref=D_Y)
                    out.append(_extrude(f, _profile(f, ring), pos,
                                        d["thickness"] * k))
            elif kind == "tube":
                # wall == r_outer means a SOLID cylinder (a boolean void tool,
                # e.g. headwall-926's pipe opening); IfcCircleHollowProfileDef
                # requires WallThickness < Radius, so emit the solid profile
                # (same 1e-9 solid/hollow split as emit_step's tube branch).
                if d["r_outer"] - d["wall"] > 1e-9:
                    prof = f.create_entity(
                        "IfcCircleHollowProfileDef", ProfileType="AREA",
                        Radius=d["r_outer"] * k, WallThickness=d["wall"] * k)
                else:
                    prof = f.create_entity(
                        "IfcCircleProfileDef", ProfileType="AREA",
                        Radius=d["r_outer"] * k)
                axis, ref = {"x": (D_X, D_Y), "y": (D_Y, D_Z)}.get(
                    d.get("axis", "x"), (None, None))
                # "y0" (default 0.0) is the Y origin the branch used to
                # hard-code, which left an axis="y" tube always sweeping
                # world-Y FROM ZERO with no dict key able to move it —
                # issue #131. emit_step reads the same key.
                pos = _place3(f, d["x0"] * k, d.get("y0", 0.0) * k,
                              d["cz"] * k, axis=axis, ref=ref)
                out.append(_extrude(f, prof, pos, d["length"] * k))
            elif kind == "swept_disk":
                # A disk swept along the bar's filleted centreline directrix:
                # ONE IfcSweptDiskSolid (arcs carried exactly as IfcArcIndex)
                # instead of the ~6-IFC-entities-per-triangle mesh a bent bar
                # used to fall back to (issue #191). Indices are 1-based.
                pts = [(x * k, y * k, z * k) for x, y, z in d["verts"]]
                plist = f.create_entity("IfcCartesianPointList3D", CoordList=pts)
                seg_ents = []
                for seg in d["segments"]:
                    if seg[0] == "line":
                        seg_ents.append(f.create_entity(
                            "IfcLineIndex", [seg[1] + 1, seg[2] + 1]))
                    else:                    # ("arc", start, mid, end)
                        seg_ents.append(f.create_entity(
                            "IfcArcIndex",
                            [seg[1] + 1, seg[2] + 1, seg[3] + 1]))
                curve = f.create_entity(
                    "IfcIndexedPolyCurve", Points=plist, Segments=seg_ents,
                    SelfIntersect=False)
                r_in = d.get("inner_radius")
                out.append(f.create_entity(
                    "IfcSweptDiskSolid", Directrix=curve,
                    Radius=d["radius"] * k,
                    InnerRadius=(r_in * k if r_in else None)))
            elif kind == "ribbon":
                # a draped OPEN layout surface (corridor / edge-of-pavement /
                # layout ribbon), issue #192: an IfcTriangulatedFaceSet with
                # Closed=False, not a solid. CoordIndex is 1-based.
                from bimforge.author.ribbon import ribbon_mesh
                verts, tris = ribbon_mesh(d["points"], d["width"])
                pts = [(x * k, y * k, z * k) for x, y, z in verts]
                plist = f.create_entity("IfcCartesianPointList3D", CoordList=pts)
                out.append(f.create_entity(
                    "IfcTriangulatedFaceSet", Coordinates=plist, Closed=False,
                    CoordIndex=[(a + 1, b + 1, c + 1) for a, b, c in tris]))
            else:
                raise KeyError(f"{el.name}: unknown geometry kind {kind!r}")
    return out


#: Carrier for a product class the target schema cannot express. IFC's own
#: "no enumerated type covers this" escape hatch, and the class the field
#: report already reached for (an IfcBuildingElementProxy carries a test
#: boring with its log in the Description perfectly well).
FALLBACK_CLASS = "IfcBuildingElementProxy"


def _class_for_schema(schema: str, ifc_class: str, el_name: str) -> str:
    """`ifc_class` if the target schema HAS it, else FALLBACK_CLASS + a warning.

    IFC4 is the opt-in for mainstream viewers that cannot open IFC4X3
    (issue #133) — but bimforge authors 4X3-only classes (`Fill` defaults to
    IfcEarthworksFill), and under IFC4 ifcopenshell raises "Entity ... not
    found in schema". Refusing would make IFC4 unusable for earthwork;
    swapping silently would hide a real loss of semantics. So downgrade,
    record the intent in ObjectType (see the caller), and say so on stderr —
    which is also what makes the IFC4X3 opt-in discoverable.
    """
    import ifcopenshell.ifcopenshell_wrapper as wrapper
    try:
        wrapper.schema_by_name(schema).declaration_by_name(ifc_class)
        return ifc_class
    except RuntimeError:
        print(f"note: {el_name!r} wants {ifc_class}, which schema {schema} "
              f"does not define — emitting {FALLBACK_CLASS} with "
              f"ObjectType={ifc_class!r}. Drop project.schema: IFC4 (the "
              "default is IFC4X3_ADD2) to keep the civil class.",
              file=sys.stderr)
        return FALLBACK_CLASS


def _schema_has(schema: str, ifc_class: str) -> bool:
    import ifcopenshell.ifcopenshell_wrapper as wrapper
    try:
        wrapper.schema_by_name(schema).declaration_by_name(ifc_class)
        return True
    except RuntimeError:
        return False


#: Pay-item excavation (#364). IfcEarthworksCut is an
#: IfcFeatureElementSubtraction: the schema REQUIRES it to void a host
#: through IfcRelVoidsElement (like an opening), and an Element's class is
#: never hosted that way — the file failed `est-bim validate`. An unhosted
#: cut is therefore written as IfcEarthworksElement with ObjectType
#: EXCAVATION (the class carries no PredefinedType in IFC4X3_ADD2).
EXCAVATION_CLASS = "IfcEarthworksElement"
EXCAVATION_OBJECT_TYPE = "EXCAVATION"


def _unhosted_cut_class(schema: str, ifc_class: str, el_name: str) -> tuple[str, str | None]:
    """(class to emit, ObjectType) — the #364 rewrite for an unhosted cut."""
    if ifc_class != "IfcEarthworksCut" or not _schema_has(schema, EXCAVATION_CLASS):
        return ifc_class, None
    print(f"note: {el_name!r} is an unhosted IfcEarthworksCut (a feature "
          f"subtraction must void a host) — emitting {EXCAVATION_CLASS} "
          f"with ObjectType={EXCAVATION_OBJECT_TYPE!r}, the pay-item "
          "excavation class.", file=sys.stderr)
    return EXCAVATION_CLASS, EXCAVATION_OBJECT_TYPE


def _place_product(run, f, product, el, ft_to_m: float) -> None:
    """Put one product at its Element's model-frame x/y/z.

    Shared by the element loop and the OPENING loop: openings used to skip
    this entirely, so a void stayed at the origin while its host moved and
    the host emitted solid (issue #131). emit_step has always placed
    openings, so the two emitters silently disagreed — one function, called
    from both loops, is what keeps them from drifting apart again.
    """
    mtx = np.eye(4)
    if el.bearing_deg:
        # Rotate about +Z (element-local origin) BEFORE the translation.
        # Guarded so bearing_deg == 0 leaves the identity 3x3 byte-identical
        # to before (no computed cos/sin introducing -0.0 / 1e-17).
        th = math.radians(el.bearing_deg)
        c, s = math.cos(th), math.sin(th)
        mtx[0, 0], mtx[0, 1] = c, -s
        mtx[1, 0], mtx[1, 1] = s, c
    mtx[0, 3] = el.x_ft * ft_to_m
    mtx[1, 3] = el.y_ft * ft_to_m
    mtx[2, 3] = el.z_ft * ft_to_m
    run("geometry.edit_object_placement", f, product=product, matrix=mtx)


# ------------------------------------------------------------- annotations
def _emit_annotation_plan(f, run, plan, anno_ctx, storey, ctx, guid_key,
                          layer_cache) -> None:
    """One AnnotationPlan (#195) as an IfcAnnotation whose representation is a
    set of IfcMappedItems: each unique stamp becomes ONE IfcRepresentationMap
    (built once, in the plan's deterministic stamp order) and each placement a
    mapped item with a rotate+translate transform. Coordinates scale ft -> m;
    rotation-derived ratios round to 9 dp (the TrueNorth precedent)."""
    k = ctx.ft_to_m
    repmaps: dict[str, object] = {}
    for key, polys in plan.stamps.items():
        curves = [
            f.create_entity("IfcPolyline", Points=[
                f.create_entity("IfcCartesianPoint",
                                Coordinates=(round(x * k, 9), round(y * k, 9), 0.0))
                for x, y in poly])
            for poly in polys]
        src = f.create_entity(
            "IfcShapeRepresentation", ContextOfItems=anno_ctx,
            RepresentationIdentifier="Annotation",
            RepresentationType="GeometricCurveSet", Items=curves)
        origin = f.create_entity(
            "IfcAxis2Placement3D",
            Location=f.create_entity("IfcCartesianPoint",
                                     Coordinates=(0.0, 0.0, 0.0)))
        repmaps[key] = f.create_entity(
            "IfcRepresentationMap", MappingOrigin=origin, MappedRepresentation=src)

    items = []
    for inst in plan.instances:
        th = math.radians(inst.rot_deg)
        c, s = math.cos(th), math.sin(th)
        target = f.create_entity(
            "IfcCartesianTransformationOperator3D",
            Axis1=f.create_entity("IfcDirection",
                                  DirectionRatios=(round(c, 9), round(s, 9), 0.0)),
            Axis2=f.create_entity("IfcDirection",
                                  DirectionRatios=(round(-s, 9), round(c, 9), 0.0)),
            Axis3=f.create_entity("IfcDirection", DirectionRatios=(0.0, 0.0, 1.0)),
            LocalOrigin=f.create_entity(
                "IfcCartesianPoint",
                Coordinates=(round(inst.x * k, 9), round(inst.y * k, 9), 0.0)),
            Scale=1.0)
        items.append(f.create_entity(
            "IfcMappedItem", MappingSource=repmaps[inst.stamp],
            MappingTarget=target))

    ann = run("root.create_entity", f, ifc_class="IfcAnnotation", name=plan.name)
    ann.GlobalId = ctx.guid(guid_key)
    rep = f.create_entity(
        "IfcShapeRepresentation", ContextOfItems=anno_ctx,
        RepresentationIdentifier="Annotation",
        RepresentationType="MappedRepresentation", Items=items)
    ann.Representation = f.create_entity(
        "IfcProductDefinitionShape", Representations=[rep])
    run("spatial.assign_container", f, products=[ann], relating_structure=storey)
    if plan.layer:
        lyr = layer_cache.get(plan.layer)
        if lyr is None:
            lyr = f.create_entity("IfcPresentationLayerAssignment",
                                  Name=plan.layer, AssignedItems=[])
            layer_cache[plan.layer] = lyr
        lyr.AssignedItems = tuple(lyr.AssignedItems or ()) + tuple(rep.Items)


def _annotation_guid_key(scope, i, plan):
    return _gk(scope, f"annotation/{i}/{plan.name}")


# ------------------------------------------------------- deterministic order
def _pin_relationship_order(f) -> None:
    """Sort every relationship's entity-list attributes by GlobalId.

    ifcopenshell.api's usecases (spatial/aggregate/classification/pset/unit,
    and whatever a later task adds) merge relationship members through
    Python `set` unions hashed on (step id, FILE POINTER) — a raw memory
    address that differs between two separately-built `ifcopenshell.file`
    objects — so rebuilding an UNCHANGED model can silently reorder a
    relationship's members even though every GlobalId is identical.

    Generic on purpose: every IfcRelationship attribute whose value is a
    non-empty tuple/list of GlobalId-carrying entities is sorted by
    GlobalId, so ANY relationship type a future emitter path creates is
    covered with no allowlist to maintain. (These aggregates are SETs in
    the EXPRESS schema, so order carries no meaning — with the one
    schema-verified exception, IfcRelNests, whose member order IS
    semantically meaningful; it is skipped below rather than normalized.)
    Call AFTER the deterministic GUID sweep so swept roots sort on their
    final GlobalIds. IfcUnitAssignment.Units (same set-union
    nondeterminism, but units have no GlobalId) sorts by UnitType.
    """
    for rel in f.by_type("IfcRelationship"):
        if rel.is_a("IfcRelNests"):
            continue
        for i in range(len(rel)):
            v = rel[i]
            if (isinstance(v, (tuple, list)) and v
                    and all(hasattr(x, "GlobalId") for x in v)):
                rel[i] = tuple(sorted(v, key=lambda e: e.GlobalId))
    for ua in f.by_type("IfcUnitAssignment"):
        ua.Units = tuple(sorted(
            ua.Units, key=lambda u: str(getattr(u, "UnitType", "") or u.is_a())))


# ------------------------------------------------------------ GUID collision
def _assert_guid_uniqueness(model, *, scope: str = "", spatial_keys=()) -> None:
    """Every authored item's resolved GlobalId must be unique.

    `StructureModel.add` only rejects duplicate NAMES; an explicit `guid_key`
    override is not similarly checked, so two differently-named items can
    collide on the same GlobalId and silently corrupt the IFC (two IfcRoots
    claiming one identity). The keyed roots share ONE GlobalId space —
    elements (`guid_key`), openings (`guid_key`), assemblies
    (`assembly/<name>`) and annotation plans (`annotation/<i>/<name>`) — and
    the deterministic sweep's `assigned` set dedupes by value, so a collision
    between ANY two of them writes duplicate identities. Check the whole space
    under the same scope prefix the writer uses; fail loud before any write,
    naming every colliding item."""
    by_guid: dict[str, list[str]] = {}

    def note(key: str, label: str) -> None:
        by_guid.setdefault(model.ctx.guid(_gk(scope, key)), []).append(label)

    for el in model.elements:
        note(el.guid_key, el.name)
    for _host, op in model.openings:
        note(op.guid_key, f"opening {op.name}")
    for asm_name in model.assemblies:
        note(f"assembly/{asm_name}", f"assembly {asm_name}")
    for i, plan in enumerate(getattr(model, "annotations", None) or []):
        note(f"annotation/{i}/{plan.name}", f"annotation {plan.name}")
    for key, label in spatial_keys:
        note(key, label)

    collisions = {g: names for g, names in by_guid.items() if len(names) > 1}
    if not collisions:
        return
    detail = "; ".join(f"{{{', '.join(sorted(names))}}}"
                       for names in collisions.values())
    raise DuplicateGuidError(
        f"{model.name}: {len(collisions)} GlobalId collision(s) — items "
        f"{detail} resolve to the same GlobalId (duplicate/shared guid_key). "
        "Explicit guid_key overrides must be unique.")


# ---------------------------------------------------------------- the writer
def _gk(scope: str, key: str) -> str:
    """GUID key, namespaced by structure. In a combined (multi-structure) file
    two structures can share an element name — and the default guid_key is
    ``element/<name>`` — so without a per-structure prefix their GlobalIds
    collide. An empty scope returns the key unchanged, so a single-structure
    emit stays byte-identical to historical output.

    The prefix is length-tagged (``<len(scope)>:<scope><key>``) so the map is
    injective regardless of what characters a structure name or key contains —
    a plain separator like ``::`` is NOT injective (scope="a::b",key="c" would
    collide with scope="a",key="b::c")."""
    return f"{len(scope)}:{scope}{key}" if scope else key


def _ctx_site_identity(ctx):
    """The ProjectContext fields that define the shared IfcSite, its georeference
    and the GUID space. Every structure in a combined model must agree on these,
    or combining them would silently adopt the first structure's site/datum."""
    return (ctx.schema, ctx.name, ctx.long_name, ctx.epsg,
            ctx.base_e, ctx.base_n, ctx.base_h, ctx.ft_to_m, ctx.guid_ns,
            ctx.site_name, ctx.site_desc, ctx.crs_desc,
            ctx.geodetic_datum, ctx.vertical_datum)


# ------------------------------------------------- IFC4X3 facility tree (#318)
class _Home:
    """Where one structure's products are contained.

    The building path has one container (the storey). The facility path has
    the facility (or, for kind `site`, the IfcSite) plus one part per distinct
    `Element.spatial_part`. `keyed` lists the spatial entities that carry an
    explicit GlobalId, so the deterministic sweep leaves them alone."""

    def __init__(self, default, parts=None, keyed=(), owner=""):
        self.default = default
        self.parts = parts or {}
        self.keyed = list(keyed)
        self.owner = owner

    def container_for(self, el):
        part = getattr(el, "spatial_part", None)
        if part is not None and part.name in self.parts:
            return self.parts[part.name]
        return self.default

    def container_for_assembly(self, asm_name, members):
        """An IfcElementAssembly's members leave their container when they are
        aggregated (ifcopenshell's aggregate.assign_object unassigns it), so
        the ASSEMBLY carries their part. Members spread over several parts
        cannot be expressed (one assembly has one container), so that is
        refused rather than silently emptying a part."""
        if not self.parts or not members:
            return self.default
        containers = {self.container_for(el).id(): self.container_for(el)
                      for el in members}
        if len(containers) > 1:
            names = sorted(c.Name or "" for c in containers.values())
            raise ValueError(
                f"{self.owner}: assembly {asm_name!r} spans spatial "
                f"containers {names}: an IfcElementAssembly is contained in "
                "ONE spatial structure; give its members one spatial_part")
        return next(iter(containers.values()))


def _effective_facilities(models, schema):
    """Per model, its ctx.facility if the schema can express it, else None."""
    from bimforge.author.spatial import schema_has_facilities
    out = []
    for m in models:
        fac = getattr(m.ctx, "facility", None)
        if fac is not None and not schema_has_facilities(schema):
            print(f"note: {m.name!r}: project.facility ({fac.kind}) is ignored "
                  f"under schema {schema}; the facility tree is IFC4X3-only. "
                  "Set project.schema: IFC4X3_ADD2 to write it (most viewers "
                  "cannot open IFC4X3).", file=sys.stderr)
            fac = None
        if fac is None and any(getattr(e, "spatial_part", None)
                               for e in m.elements):
            print(f"note: {m.name!r}: elements carry spatial_part but the "
                  "project has no IFC4X3 facility; parts are ignored.",
                  file=sys.stderr)
        out.append(fac)
    return out


def _model_parts(m, fac):
    """Distinct parts of a model, in first-appearance order: name -> part.
    Two elements naming one part with different types is a spec error."""
    parts: dict = {}
    if fac is None or fac.part_class is None:
        return parts
    for el in m.elements:
        part = getattr(el, "spatial_part", None)
        if part is None:
            continue
        seen = parts.setdefault(part.name, part)
        if seen != part:
            raise ValueError(
                f"{m.name}: spatial part {part.name!r} is declared twice with "
                f"different types ({seen} vs {part}, on {el.name!r})")
    return parts


def _spatial_keys(m, fac):
    """(guid key, label) for the spatial entities given explicit GlobalIds."""
    if fac is None or fac.facility_class is None:
        return []
    keys = [("spatial/facility", f"facility {fac.name or m.name}")]
    keys += [(f"spatial/part/{name}", f"spatial part {name}")
             for name in _model_parts(m, fac)]
    return keys


def _facility_tree(run, f, ctx, models, facilities, site, project, combined):
    """Build Site > facility > parts (and, for a model with no facility in a
    mixed combined file, the usual Building > Storey). Returns one _Home per
    model. Entities first, then aggregates, then origin placements: the
    same discipline as the building path, so the sweep's file order (and so
    every swept GlobalId) is a function of the models alone."""
    from bimforge.author.spatial import resolve_part_type, resolve_predefined

    homes, spatials, aggregates = [], [], []
    for m, fac in zip(models, facilities):
        scope = m.name if combined else ""
        if fac is None:
            building = run("root.create_entity", f, ifc_class="IfcBuilding",
                           name=m.name)
            storey = run("root.create_entity", f,
                         ifc_class="IfcBuildingStorey", name=m.name)
            spatials += [building, storey]
            aggregates += [(building, site), (storey, building)]
            homes.append(_Home(storey, owner=m.name))
            continue
        if fac.facility_class is None:              # kind: site
            if any(getattr(e, "spatial_part", None) for e in m.elements):
                print(f"note: {m.name!r}: facility kind 'site' has no parts; "
                      "spatial_part is ignored and elements are contained in "
                      "the IfcSite.", file=sys.stderr)
            homes.append(_Home(site, owner=m.name))
            continue
        facility = run("root.create_entity", f, ifc_class=fac.facility_class,
                       name=fac.name or m.name)
        facility.GlobalId = ctx.guid(_gk(scope, "spatial/facility"))
        pdt, obj = resolve_predefined(ctx.schema, fac.facility_class,
                                      fac.predefined_type)
        if pdt is not None:
            facility.PredefinedType = pdt
        facility.ObjectType = obj
        spatials.append(facility)
        aggregates.append((facility, site))
        parts = {}
        for name, part in _model_parts(m, fac).items():
            ent = run("root.create_entity", f, ifc_class=fac.part_class,
                      name=name)
            ent.GlobalId = ctx.guid(_gk(scope, f"spatial/part/{name}"))
            pdt, obj = resolve_part_type(ctx.schema, fac.part_class, part)
            ent.PredefinedType = pdt
            ent.ObjectType = obj
            # UsageType is REQUIRED on every IfcFacilityPart in IFC4X3_ADD2.
            ent.UsageType = part.usage_type or "NOTDEFINED"
            spatials.append(ent)
            aggregates.append((ent, facility))
            parts[name] = ent
        homes.append(_Home(facility, parts,
                           keyed=[facility, *parts.values()], owner=m.name))

    run("aggregate.assign_object", f, products=[site], relating_object=project)
    for child, parent in aggregates:
        run("aggregate.assign_object", f, products=[child],
            relating_object=parent)
    for spatial in (site, *spatials):
        run("geometry.edit_object_placement", f, product=spatial,
            matrix=np.eye(4))
    return homes


def emit_ifc(model, path: str, paycodes=None, *, allow_local: bool = False,
             stylepack=None) -> str:
    """Emit one structure. A thin wrapper over emit_combined_ifc so the single-
    and multi-structure paths share one writer (issue #188)."""
    return emit_combined_ifc([model], path, paycodes,
                             allow_local=allow_local, stylepack=stylepack)


def emit_combined_ifc(models, path: str, paycodes=None, *,
                      allow_local: bool = False, stylepack=None) -> str:
    """Emit one or more structures into a single IFC, each structure as its own
    named IfcBuilding under one shared IfcSite (issue #188, Lever A).

    The Bonsai outliner mirrors the spatial-decomposition tree, so giving each
    structure its own building makes a multi-structure model navigable instead
    of collapsing to one flat storey. A single structure degenerates to one
    building (named after the structure, not the old hardcoded "Building") and
    is emitted byte-for-byte as before apart from that name.

    Under IFC4X3, a model whose ctx carries a `facility` (#318) becomes its own
    IfcBridge/IfcRoad/... (or, kind `site`, is contained in the IfcSite) with
    one facility part per distinct `Element.spatial_part` — see
    bimforge.author.spatial. Without one, or under IFC4, nothing changes."""
    from ifcopenshell.api import run

    if not models:
        raise ValueError("emit_combined_ifc: no models to emit")
    combined = len(models) > 1
    ctx = models[0].ctx

    if combined:
        names = [m.name for m in models]
        if len(set(names)) != len(names):
            dupe = sorted({n for n in names if names.count(n) > 1})
            raise ValueError(
                "emit_combined_ifc: structure names must be unique — each "
                f"becomes an IfcBuilding; duplicates {dupe}")
        for m in models[1:]:
            if _ctx_site_identity(m.ctx) != _ctx_site_identity(ctx):
                raise GeoreferenceError(
                    f"emit_combined_ifc: {m.name!r} has a different "
                    "ProjectContext (site/EPSG/datum/GUID-namespace) than "
                    f"{models[0].name!r} — a combined model shares ONE IfcSite, "
                    "so every structure must share one project context.")

    if ctx.epsg is None and not allow_local:
        raise GeoreferenceError(
            f"{ctx.name}: ProjectContext has no EPSG — a local-only IFC is a "
            "drift bug unless deliberate. Set project.epsg, or pass "
            "allow_local=True (est-bim build: outputs.ifc_allow_local: true).")

    facilities = _effective_facilities(models, ctx.schema)
    for m, fac in zip(models, facilities):
        scope = m.name if combined else ""
        _assert_guid_uniqueness(m, scope=scope,
                                spatial_keys=_spatial_keys(m, fac))

    f = run("project.create_file", version=ctx.schema)
    project = run("root.create_entity", f, ifc_class="IfcProject", name=ctx.name)
    project.LongName = ctx.long_name or None
    run("unit.assign_unit", f, units=[
        run("unit.add_si_unit", f, unit_type="LENGTHUNIT"),
        run("unit.add_si_unit", f, unit_type="AREAUNIT"),
        run("unit.add_si_unit", f, unit_type="VOLUMEUNIT"),
    ])
    mctx = run("context.add_context", f, context_type="Model")
    body = run("context.add_context", f, context_type="Model",
               context_identifier="Body", target_view="MODEL_VIEW", parent=mctx)

    # Project -> Site -> Building -> Storey. The BUILDING level is not
    # decoration: a storey decomposes a building and a site contains
    # buildings, so an importer walking the IfcRelAggregates chain stops dead
    # at a site whose only child is a storey and renders NOTHING — while
    # ifcopenshell.validate() and geom.iterator both pass, because products
    # place absolutely and never traverse the tree (issue #132; dxf2bim's
    # build_ifc has always written this level). The post-emit gate
    # _ifc_spatial_chain_check refuses to ship a file without it.
    #
    # Issue #188: each structure gets its OWN named IfcBuilding under the one
    # shared site, so a combined model's outliner branches per structure. A
    # lone structure is the one-building case, named after the structure —
    # de-hardcoding the old "Building" placeholder.
    site = run("root.create_entity", f, ifc_class="IfcSite",
               name=ctx.site_name or "Site")
    site.Description = ctx.site_desc or None
    site.RefElevation = ctx.base_h * ctx.ft_to_m
    if not any(facilities):
        # Create every spatial ENTITY first, then every aggregate RELATIONSHIP —
        # site, building, storey, then site->project, building->site, storey->
        # building. That is the exact creation order of the historical single-
        # structure path, so with one model the swept relationship GUIDs (and thus
        # the bytes) are unchanged; only the building's name differs.
        buildings, storeys = [], []
        for m in models:
            buildings.append(run("root.create_entity", f, ifc_class="IfcBuilding",
                                 name=m.name))
            storeys.append(run("root.create_entity", f,
                               ifc_class="IfcBuildingStorey", name=m.name))
        run("aggregate.assign_object", f, products=[site], relating_object=project)
        for building, storey in zip(buildings, storeys):
            run("aggregate.assign_object", f, products=[building],
                relating_object=site)
            run("aggregate.assign_object", f, products=[storey],
                relating_object=building)
        # Origin placements on the containers: every product places ABSOLUTELY
        # (PlacementRelTo $), so nothing moves — but an importer resolving a
        # product's container chain into a transform must not hit a null
        # placement on the way up.
        for spatial in (site, *buildings, *storeys):
            run("geometry.edit_object_placement", f, product=spatial,
                matrix=np.eye(4))
        homes = [_Home(storey) for storey in storeys]
    else:
        # Issue #318: the IFC4X3 facility tree. A separate branch so the
        # building path above stays byte-identical (golden test).
        homes = _facility_tree(run, f, ctx, models, facilities, site, project,
                               combined)

    if ctx.epsg is not None:
        run("georeference.add_georeferencing", f)
        run("georeference.edit_georeferencing", f,
            projected_crs={"Name": ctx.crs_name,
                           "Description": ctx.crs_desc or None,
                           "GeodeticDatum": ctx.geodetic_datum,
                           "VerticalDatum": ctx.vertical_datum},
            coordinate_operation={
                "Eastings": ctx.base_e, "Northings": ctx.base_n,
                "OrthogonalHeight": ctx.base_h,
                "Scale": 1.0 / ctx.ft_to_m,
            })

        # Grid north != true north by the grid convergence angle. Model axes
        # ARE the grid axes, so the declaration belongs on the context's
        # TrueNorth — NOT on the MapConversion rotation, which would claim
        # the model is rotated relative to grid.
        from bimforge.cad.geo import convergence_deg, true_north_direction
        tnx, tny = true_north_direction(ctx.epsg, ctx.base_e, ctx.base_n)
        mctx.TrueNorth = f.create_entity(
            "IfcDirection", DirectionRatios=(round(tnx, 9), round(tny, 9)))
        print(f"true north ({tnx:+.6f}, {tny:+.6f}) — grid convergence "
              f"{convergence_deg(ctx.epsg, ctx.base_e, ctx.base_n):+.3f} deg "
              f"at project base", file=sys.stderr)

    # #332: the alignments the geometry sweeps along, as IfcAlignment with its
    # IfcCompositeCurve / IfcGradientCurve — written BEFORE the elements,
    # because an exact sweep is built on its curve. Only models
    # that sweep get one, and only under IFC4X3; every other file is
    # byte-identical. The Axis subcontext is made here, under the ONE Model
    # context: left to itself ifcopenshell.api.alignment mints a second one.
    from bimforge.author.emit_alignment import emit_alignments, model_alignments
    if model_alignments(models) and ctx.schema.upper().startswith("IFC4X3"):
        run("context.add_context", f, context_type="Model",
            context_identifier="Axis", target_view="MODEL_VIEW", parent=mctx)
    curves = emit_alignments(run, f, models, ctx, site)

    pack = stylepack if stylepack is not None else resolve_style_pack()
    _ifc = pack.styles.get("ifc")
    if _ifc is not None and not isinstance(_ifc, dict):
        warnings.warn(f"ifc styles: 'ifc' section is not a mapping "
                      f"({type(_ifc).__name__}); ignoring", UserWarning)
        _ifc = {}
    pack_ifc = sanitize_pack((_ifc or {}).get("surfaces"))
    style_cache: dict = {}     # resolved appearance -> IfcSurfaceStyle
    layer_cache: dict = {}     # layer name -> IfcPresentationLayerAssignment
    by_material: dict = {}     # material name -> [products]
    mat_appear: dict = {}      # material name -> the appearance it resolved on
    cls_cache: dict = {}
    by_code: dict[str, list] = {}
    by_name_by_model: dict[int, dict] = {}
    for idx, m in enumerate(models):
        home = homes[idx]
        scope = m.name if combined else ""
        by_name: dict[str, object] = {}
        hosts = {h for h, _op in m.openings}
        for el in m.elements:
            # an Element is never the RelatedOpeningElement of an
            # IfcRelVoidsElement (only m.openings are), so every
            # IfcEarthworksCut Element is unhosted (#364)
            wanted, object_type = _unhosted_cut_class(ctx.schema, el.ifc_class,
                                                      el.name)
            ifc_class = _class_for_schema(ctx.schema, wanted, el.name)
            product = run("root.create_entity", f, ifc_class=ifc_class,
                          predefined_type=el.predefined_type, name=el.name)
            product.GlobalId = ctx.guid(_gk(scope, el.guid_key))
            if ifc_class != wanted:
                product.ObjectType = wanted
            elif object_type:
                product.ObjectType = object_type
            # Issue #190: carry the estimator's per-element note (assumptions,
            # placement-honesty notes, sheet cites) onto IfcRoot.Description.
            # `or None` keeps an unset description a true null, not "".
            product.Description = el.description or None
            run("spatial.assign_container", f, products=[product],
                relating_structure=home.container_for(el))
            appear = resolve_surface(el.layer, el.ifc_class, pack_ifc, el.material)
            if appear["material"]:
                by_material.setdefault(appear["material"], []).append(product)
                mat_appear.setdefault(appear["material"], appear)
            # an opening host keeps its sweeps as meshes: ifcopenshell draws
            # an IfcSectionedSolidHorizontal as an open shell (#9820), and a
            # boolean against an open shell is silently dropped — the
            # opening would not show
            items = (solids_for(f, el, ctx.ft_to_m,
                                None if el.name in hosts else curves)
                     if el.geometry is not None else [])
            if items:
                # an open surface (ribbon -> IfcTriangulatedFaceSet) cannot
                # share ONE Body representation with solids — the RepresentationType
                # can only name one, and a mixed list is invalid IFC. Author a
                # ribbon as its own element rather than beside solid geometry.
                face_sets = [i for i in items if i.is_a("IfcTriangulatedFaceSet")]
                if face_sets and len(face_sets) != len(items):
                    raise ValueError(
                        f"{el.name}: a ribbon (open surface) cannot share a "
                        "representation with solid geometry — give it its own "
                        "Element")
                # named from the items themselves (#329): CSG for booleans,
                # Tessellation for a ribbon, Brep for a faceted mesh,
                # SweptSolid / AdvancedSweptSolid for the sweeps.
                rep_type = representation_type(items, el.name)
                rep = f.create_entity(
                    "IfcShapeRepresentation", ContextOfItems=body,
                    RepresentationIdentifier="Body",
                    RepresentationType=rep_type, Items=items)
                product.Representation = f.create_entity(
                    "IfcProductDefinitionShape", Representations=[rep])

                style = _surface_style(run, f, style_cache, appear,
                                       el.layer or el.ifc_class)
                run("style.assign_representation_styles", f,
                    shape_representation=rep, styles=[style])
                if el.layer:
                    lyr = layer_cache.get(el.layer)
                    if lyr is None:
                        # built by hand (not layer.assign_layer):
                        # IfcPresentationLayerAssignment is neither IfcRoot nor
                        # IfcRelationship, so it escapes both determinism sweeps;
                        # append-ordered AssignedItems keeps emits byte-stable.
                        lyr = f.create_entity("IfcPresentationLayerAssignment",
                                              Name=el.layer, AssignedItems=[])
                        layer_cache[el.layer] = lyr
                    lyr.AssignedItems = (tuple(lyr.AssignedItems or ())
                                         + tuple(rep.Items))
            _place_product(run, f, product, el, ctx.ft_to_m)

            # Qto only when the model carries quantities: terrain and other pure
            # reference meshes have quantities == {} and get none, while
            # unclassified-but-quantified elements keep theirs (the audit mesh
            # leg reads GrossVolume by GUID on elements with no pay code). The
            # never-a-pay-quantity contract for classifications == [] is
            # enforced by the classification loop below, not here.
            if el.quantities:
                qto = run("pset.add_qto", f, product=product,
                          name="Qto_BaseQuantities")
                quantities = []
                for ent, qname, value in base_quantities(el, ctx.ft_to_m):
                    qq = f.create_entity(ent, Name=qname)
                    setattr(qq, _QTY_ATTR[ent],
                            int(value) if ent == "IfcQuantityCount"
                            else float(value))
                    quantities.append(qq)
                qto.Quantities = tuple(quantities)

            # provenance rides the solids dict (smallest carrier: no new Element
            # field) and emits as a Pset on the product — terrain's source/
            # vintage/datum-shift record (design: Pset_BimforgeTerrain).
            prov: dict = {}
            for g in (el.geometry if isinstance(el.geometry, (list, tuple))
                      else [el.geometry]):
                if isinstance(g, dict) and g.get("provenance"):
                    prov.update(g["provenance"])
            if prov:
                pset = run("pset.add_pset", f, product=product,
                           name="Pset_BimforgeTerrain")
                run("pset.edit_pset", f, pset=pset, properties=prov)

            for code in el.classifications:
                by_code.setdefault(code, []).append(product)
            by_name[el.name] = product
        by_name_by_model[idx] = by_name

    # Classification identity comes from the paycodes (the cost-code system's IFC
    # identity -- spec §5.4): source_system -> IfcClassification.Name, edition ->
    # .Edition. Default "BidSchedule" with no edition keeps historical output
    # byte-identical.
    system = (paycodes.source_system if paycodes else None) or "BidSchedule"
    edition = (paycodes.edition if paycodes else "") or ""
    if system not in cls_cache:
        cls = run("classification.add_classification", f, classification=system)
        if edition:
            cls.Edition = edition
        cls_cache[system] = cls
    for code in sorted(by_code):
        desc = ""
        if paycodes is not None and code in paycodes.codes:
            desc = paycodes.codes[code].get("description", "") or ""
        run("classification.add_reference", f, products=by_code[code],
            identification=code, name=desc, classification=cls_cache[system])

    for idx, m in enumerate(models):
        scope = m.name if combined else ""
        home = homes[idx]
        by_name = by_name_by_model[idx]
        for host_name, opening in m.openings:
            op = run("root.create_entity", f, ifc_class="IfcOpeningElement",
                     name=opening.name)
            op.GlobalId = ctx.guid(_gk(scope, opening.guid_key))
            op.Description = opening.description or None   # issue #190, openings too
            items = solids_for(f, opening, ctx.ft_to_m)
            rep = f.create_entity("IfcShapeRepresentation", ContextOfItems=body,
                                  RepresentationIdentifier="Body",
                                  RepresentationType=representation_type(
                                      items, opening.name),
                                  Items=items)
            op.Representation = f.create_entity("IfcProductDefinitionShape",
                                                Representations=[rep])
            run("feature.add_feature", f, feature=op,
                element=by_name[host_name])
            # AFTER add_feature: it re-applies an existing placement on its way
            # through, so placing first would just be redone. An opening carries
            # the same model-frame x/y/z any element does (issue #131).
            _place_product(run, f, op, opening, ctx.ft_to_m)

        for asm_name, members in m.assemblies.items():
            asm = run("root.create_entity", f, ifc_class="IfcElementAssembly",
                      name=asm_name)
            asm.GlobalId = ctx.guid(_gk(scope, f"assembly/{asm_name}"))
            run("spatial.assign_container", f, products=[asm],
                relating_structure=home.container_for_assembly(
                    asm_name, [m.element(n) for n in members]))
            # one member per call, in model order: a multi-product call iterates
            # a Python set while re-localizing each member's placement, so the
            # placement entities' CREATION ORDER (not just relationship member
            # order) goes nondeterministic — and creation order is beyond
            # _pin_relationship_order's post-hoc reach.
            for n in members:
                run("aggregate.assign_object", f, products=[by_name[n]],
                    relating_object=asm)

    # annotations (issue #195): instanced IfcAnnotation, only when a model
    # carries a plan — so every family that emits none is byte-identical to
    # before (no annotation context, no IfcAnnotation created). The Plan/
    # Annotation context is built lazily on the first plan for the same reason.
    anno_ctx = None
    for idx, m in enumerate(models):
        plans = getattr(m, "annotations", None) or []
        if not plans:
            continue
        scope = m.name if combined else ""
        storey = homes[idx].default
        for i, plan in enumerate(plans):
            if anno_ctx is None:
                anno_ctx = run("context.add_context", f, context_type="Plan",
                               context_identifier="Annotation",
                               target_view="PLAN_VIEW", parent=mctx)
            _emit_annotation_plan(f, run, plan, anno_ctx, storey, ctx,
                                  _annotation_guid_key(scope, i, plan),
                                  layer_cache)

    for name in sorted(by_material):
        mat = run("material.add_material", f, name=name)
        run("material.assign_material", f, products=by_material[name], material=mat)
        # Give the MATERIAL an appearance too, not just the shapes. Viewers
        # that colour by material (and Revit's IFC link) read
        # IfcMaterialDefinitionRepresentation; without it a file can carry
        # nine named materials and show nothing. The shape's own style still
        # wins where both exist, so this only adds a fallback.
        appear = mat_appear.get(name)
        if appear is not None:
            run("style.assign_material_style", f, material=mat, context=body,
                style=_surface_style(run, f, style_cache, appear, name))

    # deterministic sweep: every remaining IfcRoot (rels, psets, spatial) in
    # file order — creation order is deterministic, so the file is diffable.
    # `assigned` must cover EVERYTHING given an explicit key above — elements,
    # openings, assemblies — or the sweep clobbers those stable GlobalIds.
    assigned = set()
    for m in models:
        scope = m.name if combined else ""
        assigned |= {ctx.guid(_gk(scope, el.guid_key)) for el in m.elements}
        assigned |= {ctx.guid(_gk(scope, op.guid_key))
                     for _host, op in m.openings}
        assigned |= {ctx.guid(_gk(scope, f"assembly/{name}"))
                     for name in m.assemblies}
        assigned |= {ctx.guid(_annotation_guid_key(scope, i, plan))
                     for i, plan in enumerate(getattr(m, "annotations", None)
                                              or [])}
    assigned |= {h.GlobalId for home in homes for h in home.keyed}
    for i, ent in enumerate(f.by_type("IfcRoot")):
        if ent.GlobalId not in assigned:
            ent.GlobalId = ctx.guid(f"root/{i}/{ent.is_a()}")

    # then pin every relationship's member order (see _pin_relationship_order:
    # ifcopenshell.api set-unions reorder members nondeterministically) — after
    # the sweep, so the sort keys are the final GlobalIds.
    _pin_relationship_order(f)

    try:
        # NOT os.path.basename(path): the header must depend only on the
        # MODEL, never on the output path, or writing an unchanged model to
        # two different paths would spuriously break byte-determinism.
        f.header.file_name.name = ctx.name if combined else models[0].name
        f.header.file_name.time_stamp = BUILD_STAMP
        f.header.file_name.author = ("bimforge",)
        f.header.file_name.organization = ("bimforge",)
        f.header.file_name.originating_system = "bimforge.author.emit_ifc"
    except (AttributeError, TypeError):
        pass
    f.write(path)
    total = sum(len(m.elements) for m in models)
    return f"{total} elements written to {path}"
