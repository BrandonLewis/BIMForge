"""STEP emitter ([solids] extra): true B-rep solids from the same body_solids
dicts the IFC emitter consumes, via build123d — plus a true-volume cross-check
registered as an OPTIONAL post-emit gate check when build123d is importable.

Lazy import, friendly error: bimforge base does not depend on build123d.
"""
from __future__ import annotations

import math
import re

#: mirrors emit_ifc.BUILD_STAMP: OCCT's STEP writer stamps FILE_NAME's
#: time_stamp field with wall-clock time, which would otherwise break
#: byte-determinism for an unchanged model rebuilt at a different time.
STEP_BUILD_STAMP = "2026-08-15T12:00:00"
_FILE_NAME_TIME_RE = re.compile(r"(FILE_NAME\('[^']*',')[^']*(')")


def _pin_step_timestamp(path) -> None:
    from pathlib import Path
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    pinned, n = _FILE_NAME_TIME_RE.subn(
        rf"\g<1>{STEP_BUILD_STAMP}\g<2>", text, count=1)
    if n:
        p.write_text(pinned, encoding="utf-8")


def _require_build123d():
    try:
        import build123d  # noqa: F401
        return build123d
    except ImportError:
        raise RuntimeError(
            "emit_step needs the [solids] extra: "
            'pip install "bimforge[solids]"') from None


def _solid_from_dict(b3d, d):
    """One build123d Part per solids dict (same schema as emit_ifc)."""
    from build123d import (BuildPart, BuildSketch, Plane, Polygon, extrude)
    k = 1.0 if d.get("units", "ft") == "ft" else 1.0 / 12.0
    parts = []
    if d["kind"] == "prism":
        if d.get("z_top") is not None and d.get("bottom_z") is None:
            from build123d import Mode
            with BuildPart() as bp:
                with BuildSketch(Plane.XY.offset(d["z_bot"] * k)):
                    Polygon(*[(u * k, v * k) for u, v in d["base"]], align=None)
                    # subtract each void ring — the same holes emit_ifc punches
                    # via IfcArbitraryProfileDefWithVoids. Without them a hollow
                    # Prism (HSS post, mortar pocket) rebuilds SOLID, so
                    # true_volume_check reads high and gate.run_post deletes an
                    # otherwise-correct IFC/DXF/QTO. (#254)
                    for h in d.get("holes", []):
                        Polygon(*[(u * k, v * k) for u, v in h], align=None,
                                mode=Mode.SUBTRACT)
                extrude(amount=(d["z_top"] - d["z_bot"]) * k)
            parts.append(bp.part)
        else:
            # per-vertex top and/or bottom (a taper / wedge): no uniform sweep
            # depth exists, so build the exact triangulated B-rep (same facets
            # emit_ifc's IfcFacetedBrep uses) instead of `extrude`'s flat box.
            # (#251 adds the bottom_z leg, mirroring emit_ifc.)
            from bimforge.author.primitives import taper_prism_triangles
            from build123d import Face, Shell, Solid, Wire
            ring = [(u * k, v * k) for u, v in d["base"]]
            top_z = (d["top_z"] if d.get("top_z") is not None
                     else [d["z_top"]] * len(ring))
            bottom_z = ([z * k for z in d["bottom_z"]]
                        if d.get("bottom_z") is not None else None)
            tris = taper_prism_triangles(
                ring, [z * k for z in top_z], d["z_bot"] * k, bottom_z)
            faces = [Face(Wire.make_polygon(list(tri), close=True))
                     for tri in tris]
            parts.append(Solid(Shell(faces).fix()))
    elif d["kind"] == "box":
        from build123d import Mode
        from bimforge.author.primitives import (ARC_SEGMENTS,
                                                equal_area_polygon_radius)
        dia = d.get("hole_dia", 0.0)
        segs = d.get("segments", ARC_SEGMENTS)
        for box in d["boxes"]:
            cx, cy, cz, dx, dy, dz = box[:6]
            holes_c = box[6] if len(box) > 6 else []
            with BuildPart() as bp:
                with BuildSketch(Plane.XY.offset((cz - dz / 2) * k)):
                    Polygon(*[((cx - dx / 2) * k, (cy - dy / 2) * k),
                              ((cx + dx / 2) * k, (cy - dy / 2) * k),
                              ((cx + dx / 2) * k, (cy + dy / 2) * k),
                              ((cx - dx / 2) * k, (cy + dy / 2) * k)],
                            align=None)
                    # bolt holes: same equal-area polygons emit_ifc punches —
                    # without them a pierced plate's B-rep reads high by
                    # exactly the hole volume and true_volume_check fails.
                    if holes_c and dia > 0:
                        r = equal_area_polygon_radius(dia / 2.0, segs)
                        for u, v in holes_c:
                            Polygon(
                                *[((cx + u + r * math.cos(2 * math.pi * i / segs)) * k,
                                   (cy + v + r * math.sin(2 * math.pi * i / segs)) * k)
                                  for i in range(segs)],
                                align=None, mode=Mode.SUBTRACT)
                extrude(amount=dz * k)
            parts.append(bp.part)
    elif d["kind"] == "rod":
        from build123d import Cylinder, Locations, Mode
        r = d["radius"] * k
        r_in = d.get("r_inner")                 # None/0 -> a solid bar (rebar/bolts)
        rot = None if d["axis"] == "z" else (
            (0, 90, 0) if d["axis"] == "x" else (90, 0, 0))
        for cx, cy, cz in d["centres"]:
            kw = {} if rot is None else {"rotation": rot}
            with BuildPart() as bp:
                with Locations(((cx * k), (cy * k), (cz * k))):
                    Cylinder(r, d["length"] * k, **kw)
                    if r_in:
                        Cylinder(r_in * k, d["length"] * k, mode=Mode.SUBTRACT, **kw)
            parts.append(bp.part)
    elif d["kind"] in ("arc_band", "gusset"):
        # section-profile sweeps: extrude the same 2D ring emit_ifc builds,
        # in the X (along-structure) direction via a rotated sketch plane.
        from build123d import BuildLine, Plane as Pl, Polyline, make_face
        rings = []
        if d["kind"] == "arc_band":
            n, wrap = d["segments"], math.radians(d["wrap_deg"])
            start = math.radians(d.get("start_deg", 180.0))
            r_i, r_o = d["r_inner"], d["r_outer"]
            ang = [start + wrap * i / n for i in range(n + 1)]
            ring = ([(r_o * math.cos(a), r_o * math.sin(a)) for a in ang]
                    + [(r_i * math.cos(a), r_i * math.sin(a))
                       for a in reversed(ang)])
            rings = [((d["cx"] - d["width"] / 2.0), d["cz"], ring, d["width"])]
        else:  # gusset
            rings = [((cx - d["thickness"] / 2.0), d["cz"], ring, d["thickness"])
                     for cx, ring in d["placements"]]
        for x0, cz, ring, depth in rings:
            pl = Pl(origin=(x0 * k, 0, cz * k), x_dir=(0, 1, 0), z_dir=(1, 0, 0))
            with BuildPart() as bp:
                with BuildSketch(pl):
                    with BuildLine():
                        Polyline(*[(u * k, v * k) for u, v in ring], close=True)
                    make_face()
                extrude(amount=depth * k)
            parts.append(bp.part)
    elif d["kind"] == "mesh":
        # triangulated B-rep (SectionPrism/BatteredWall lofts): the same
        # facets emit_ifc's IfcFacetedBrep carries, so the true volume IS
        # the analytic volume_cf the primitives declared from their faces.
        from build123d import Face, Shell, Solid, Wire
        verts = [(x * k, y * k, z * k) for x, y, z in d["verts"]]
        faces = [Face(Wire.make_polygon([verts[i] for i in tri], close=True))
                 for tri in d["tris"]]
        parts.append(Solid(Shell(faces).fix()))
    elif d["kind"] == "swept_disk":
        # emit_ifc carries the exact IfcSweptDiskSolid; STEP has no lean
        # equivalent, so build the watertight faceted tube the shared
        # tessellator produces (volume ~= pi r^2 * centreline length).
        from build123d import Face, Shell, Solid, Wire
        from bimforge.author.primitives import swept_disk_mesh
        # tessellate in MODEL units (verts + radius both scaled by k) so a
        # units:"in" bar is not 12x oversized; sides=48 keeps the faceted tube
        # within the 0.5% mesh tolerance (a 12-gon under-reports ~4.5%).
        mv, tris = swept_disk_mesh(
            [(x * k, y * k, z * k) for x, y, z in d["verts"]],
            d["segments"], d["radius"] * k, sides=48)
        faces = [Face(Wire.make_polygon([mv[i] for i in tri], close=True))
                 for tri in tris]
        parts.append(Solid(Shell(faces).fix()))
    elif d["kind"] == "tube":
        # A FULL annulus cannot be one concatenated outer+inner polyline: the
        # seam vertices coincide (angle 0 == angle 2pi) and OCCT refuses the
        # self-touching wire ("Face can only be created with closed wires") —
        # and dropping the duplicate vertex instead leaves the closing edge
        # radial at angle 0 while the outer->inner transition sits at
        # 2pi(n-1)/n, losing one wedge (1/n of the volume: 1.7% at n=64,
        # outside MESH_TOLERANCE). So: outer polygon FACE, inner polygon HOLE.
        from build123d import Mode, Plane as Pl, Polygon
        n = 64
        r_o, r_i = d["r_outer"], d["r_outer"] - d["wall"]
        def _circle(r):
            return [(r * math.cos(2 * math.pi * i / n) * k,
                     r * math.sin(2 * math.pi * i / n) * k) for i in range(n)]
        # sweep direction per "axis" (same world mapping as emit_ifc's
        # {"x": (D_X,D_Y), "y": (D_Y,D_Z)} table — plane normal (z_dir) is
        # the sweep axis, x_dir the matching RefDirection): PREVIOUSLY
        # hardcoded to the "x" case regardless of "axis" — silently wrong
        # for any non-x tube (e.g. a void punched along Y through a wall's
        # thickness, headwall-926's pipe opening).
        # "y0" (default 0.0): the Y origin both emitters used to hard-code,
        # pinning an axis="y" tube to sweep world-Y from zero (issue #131).
        y0 = d.get("y0", 0.0) * k
        if d.get("axis", "x") == "y":
            pl = Pl(origin=(d["x0"] * k, y0, d["cz"] * k),
                    x_dir=(0, 0, 1), z_dir=(0, 1, 0))
        else:
            pl = Pl(origin=(d["x0"] * k, y0, d["cz"] * k),
                    x_dir=(0, 1, 0), z_dir=(1, 0, 0))
        with BuildPart() as bp:
            with BuildSketch(pl):
                Polygon(*_circle(r_o), align=None)
                # r_i can be 0 (wall == r_outer): a SOLID cylinder used as a
                # boolean-subtract void tool, not a true hollow tube — a
                # zero-radius inner polygon is degenerate and OCCT refuses it.
                if r_i > 1e-9:
                    Polygon(*_circle(r_i), align=None, mode=Mode.SUBTRACT)
            extrude(amount=d["length"] * k)
        parts.append(bp.part)
    elif d["kind"] == "ribbon":
        # a draped OPEN layout surface (issue #192): zero-thickness, so it is
        # not a STEP solid — emit nothing here (it lands only in the IFC as a
        # tessellated face set). The DXF draws its plan trace.
        pass
    elif d["kind"] == "none":
        # geometry-less sentinel ({"kind":"none"}): a quantity-only element
        # (rebar/hardware) some families/specs declare in place of
        # geometry=None. Contributes no solid, so true_volume_check treats
        # it exactly as geometry=None. (#255)
        pass
    else:
        raise KeyError(f"unknown geometry kind {d['kind']!r}")
    return parts


def _placed_parts(b3d, el):
    """[Part, ...] for one Element's geometry, placed at its x/y/z."""
    from build123d import Location
    geoms = el.geometry if isinstance(el.geometry, (list, tuple)) else [el.geometry]
    parts = []
    for g in geoms:
        if hasattr(g, "body_solids"):
            dicts = g.body_solids()
        elif isinstance(g, dict):
            dicts = [g]
        else:
            # bare primitive (no body_solids()) kept only so
            # check_arc_faceting sees its exact/faceted pair; its
            # paired placed-solids dict is the true B-rep source.
            dicts = []
        for d in dicts:
            parts.extend(_solid_from_dict(b3d, d))
    # Rotate about +Z by bearing_deg then translate. Guarded so bearing_deg == 0
    # keeps the translation-only Location and existing STEP output byte-identical.
    if el.bearing_deg:
        place = Location((el.x_ft, el.y_ft, el.z_ft), (0, 0, 1), el.bearing_deg)
    else:
        place = Location((el.x_ft, el.y_ft, el.z_ft))
    return [p.located(place * p.location) for p in parts]


def build_solids(model):
    """[(element, [Part, ...])] for the whole model, placed at element x/y/z,
    with `model.openings` boolean-SUBTRACTED from their host — the same
    void every consumer's IfcRelVoidsElement/mesh-check already accounts for
    (emit_ifc's IfcOpeningElement feature), so the STEP solid's true volume
    matches the model's analytic (net-of-opening) volume_cf too."""
    b3d = _require_build123d()
    out = []
    by_index: dict[str, int] = {}
    for el in model.elements:
        if el.geometry is None:
            continue
        by_index[el.name] = len(out)
        out.append((el, _placed_parts(b3d, el)))

    for host_name, opening in model.openings:
        idx = by_index.get(host_name)
        if idx is None or opening.geometry is None:
            continue
        void_parts = _placed_parts(b3d, opening)
        el, parts = out[idx]
        for v in void_parts:
            parts = [p - v for p in parts]
        out[idx] = (el, parts)
    return out


def emit_step(model, path) -> str:
    _require_build123d()
    from build123d import Compound, export_step
    solids = build_solids(model)
    children = []
    for el, parts in solids:
        for i, p in enumerate(parts):
            p.label = el.name if len(parts) == 1 else f"{el.name} [{i}]"
            children.append(p)
    asm = Compound(label=model.name, children=children)
    export_step(asm, str(path))
    _pin_step_timestamp(path)
    return f"{len(children)} solids written to {path}"


def true_volume_check(model, outputs, tol: float = 0.005):
    """Post-emit gate check: B-rep volumes vs the model's analytic volumes.
    Registered only when build123d imports (see families/registry wiring)."""
    fail = []
    for el, parts in build_solids(model):
        want = el.quantities.get("volume_cf")
        if not want:
            continue
        got = sum(p.volume for p in parts)
        if abs(got - want) / want > tol:
            fail.append(f"{el.name}: STEP true volume {got:.4f} cf is "
                        f"{abs(got - want) / want:.4%} off analytic {want:.4f} cf")
    return fail
