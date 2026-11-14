"""Backfill derived from its pit (#59): one solid per excavation, no lifts.

A 4D viewer animates each earthwork solid itself: over the task's dates a
level plane moves through the solid by volume, top down for a cut and bottom
up for a fill. So a pit is one IfcEarthworksCut (hosted on the ground it is
dug from, `Element.voids`) and its backfill is one IfcEarthworksFill whose
solid is computed, not drawn by hand:

    backfill = (pit clipped at the backfill's top) - every body standing in it

A stem or wing that rises above the backfill takes away only its buried
part, because the clip leaves nothing above the top. The backfill's
`volume_cf` is the solid's own volume, so the shape and the stated quantity
agree, and a stated-quantity assertion holds it for the gate.

`derive_backfill(model, pit, name, top=...)` adds the backfill to the model
and, with `group=`, ties the pit and the backfill together as one named
`StructureModel.groups` entry (an IfcGroup: a hosted cut already has its
parent, the ground it voids, so the two cannot share an assembly).

manifold3d is an optional dependency (``pip install 'bimforge[terrain]'``),
the kernel `author.lifts` uses.

Examples:
    from bimforge.author.backfill import derive_backfill
    derive_backfill(model, "Abut 1 excavation", "Abut 1 backfill",
                    top=-1.0, group="Abut 1 earthwork")
"""
from __future__ import annotations

#: Classes never taken away from a backfill: the ground (a pit's host
#: overlaps it by definition) and the other earthwork bodies.
NOT_SUBTRACTED = frozenset((
    "IfcGeographicElement", "IfcEarthworksCut", "IfcEarthworksFill",
    "IfcEarthworksElement"))


def _bounds(d):
    """((x0, y0, z0), (x1, y1, z1)) of one body_solids() dict in its own
    frame, or None for a kind whose extent is not read here."""
    kind = d.get("kind")
    if kind in ("prism", "fill"):
        xs = [p[0] for p in d["base"]]
        ys = [p[1] for p in d["base"]]
        tops = d.get("top_z") or [d.get("z_top")]
        bots = d.get("bottom_z") or [d.get("z_bot")]
        return ((min(xs), min(ys), min(bots)), (max(xs), max(ys), max(tops)))
    if kind == "mesh":
        v = d["verts"]
        return (tuple(min(p[i] for p in v) for i in range(3)),
                tuple(max(p[i] for p in v) for i in range(3)))
    if kind == "box":
        lo = [min(b[i] - b[i + 3] / 2 for b in d["boxes"]) for i in range(3)]
        hi = [max(b[i] + b[i + 3] / 2 for b in d["boxes"]) for i in range(3)]
        return tuple(lo), tuple(hi)
    return None


def _placed_bounds(el, dicts):
    """The element's model-frame bounding box from its dicts, or None when
    any dict's extent is unknown (then the solid itself is built)."""
    import math
    boxes = [_bounds(d) for d in dicts if d.get("kind") != "none"]
    if not boxes or any(b is None for b in boxes):
        return None
    th = math.radians(el.bearing_deg or 0.0)
    c, s = math.cos(th), math.sin(th)
    pts = [(x * c - y * s + el.x_ft, x * s + y * c + el.y_ft, z + el.z_ft)
           for lo, hi in boxes
           for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    return (tuple(min(p[i] for p in pts) for i in range(3)),
            tuple(max(p[i] for p in pts) for i in range(3)))


def _overlaps(a, b, eps=1e-9):
    return all(a[0][i] < b[1][i] - eps and b[0][i] < a[1][i] - eps
               for i in range(3))


def _solid(el):
    """The element's body as one model-frame manifold3d solid (feet)."""
    from bimforge.author.emit_ifc import body_dicts
    from bimforge.author.lifts import solid_of
    dicts = [d for ds in body_dicts(el) for d in ds]
    try:
        solid = solid_of(dicts)
    except ValueError as exc:
        raise ValueError(f"backfill: {el.name!r} is not a closed solid the "
                         f"backfill can be cut from ({exc}); exclude it or "
                         f"give it a closed body") from exc
    if el.bearing_deg:
        solid = solid.rotate((0.0, 0.0, float(el.bearing_deg)))
    if el.x_ft or el.y_ft or el.z_ft:
        solid = solid.translate((el.x_ft, el.y_ft, el.z_ft))
    return solid, dicts


def _below(m3, top, pit):
    """The region at or below `top`, over the pit: a level plane (a number,
    model-frame ft) or a surface ({"verts": [(x, y, z)...], "tris": [...]},
    model-frame ft) that covers the pit in plan."""
    lo_x, lo_y, lo_z, hi_x, hi_y, hi_z = pit.bounding_box()
    floor = lo_z - 1.0
    if isinstance(top, (int, float)):
        size = (hi_x - lo_x + 2.0, hi_y - lo_y + 2.0, float(top) - floor)
        if size[2] <= 0:
            return m3.Manifold()
        return m3.Manifold.cube(size).translate((lo_x - 1.0, lo_y - 1.0, floor))
    from bimforge.author.lifts import _from_mesh
    from bimforge.author.primitives import taper_prism_triangles
    verts, parts = top["verts"], []
    for tri in top["tris"]:
        ring = [tuple(verts[i][:2]) for i in tri]
        area = ((ring[1][0] - ring[0][0]) * (ring[2][1] - ring[0][1])
                - (ring[2][0] - ring[0][0]) * (ring[1][1] - ring[0][1]))
        if abs(area) < 1e-12:
            continue                         # a vertical facet covers nothing
        zs = [verts[i][2] for i in tri]
        if area < 0:                         # counter-clockwise in plan
            ring, zs = ring[::-1], zs[::-1]
        if min(zs) <= floor:
            raise ValueError("backfill: the top surface dips below the pit")
        flat, idx = [], []
        for t in taper_prism_triangles(ring, zs, floor):
            idx.append(tuple(range(len(flat), len(flat) + 3)))
            flat += [tuple(p) for p in t]
        parts.append(_from_mesh(flat, idx))
    if not parts:
        raise ValueError("backfill: the top surface has no triangles")
    return m3.Manifold.batch_boolean(parts, m3.OpType.Add)


def derive_backfill(model, pit: str, name: str, *, top, exclude=(),
                    group: str | None = None, pieces: int | None = 1,
                    sliver_cf: float = 0.0, ifc_class: str = "IfcEarthworksFill",
                    predefined_type: str = "BACKFILL", **element_kw):
    """Add backfill `name`: element `pit`'s body at or below `top`, less every
    element body inside it. Returns the new Element.

    `top`: a level (model-frame ft) or a surface dict (see `_below`).
    `exclude`: element names never taken away (a pipe the backfill is placed
    around later, say). Ground and other earthwork bodies are never taken
    away (NOT_SUBTRACTED), nor is the pit's host.
    `group`: also record the pit and the backfill as `model.groups[group]`.
    `pieces`: how many separate bodies the backfill must come out as (a wall
    across the whole pit splits it in two); None accepts any.
    `sliver_cf`: drop bodies smaller than this (reported in the stated
    quantity, as lifts do), 0 keeps everything.
    `element_kw`: passed to Element (material, layer, classifications, ...).

    Raises ValueError, writing nothing, when a body to take away is not a
    closed solid, when nothing is left, or when the backfill comes out in
    another number of pieces than `pieces`.
    """
    from bimforge.author.emit_ifc import body_dicts
    from bimforge.author.lifts import _need_manifold, _tidy
    from bimforge.author.model import Element
    m3 = _need_manifold()
    pit_el = model.element(pit)
    pit_solid, _ = _solid(pit_el)
    clipped = pit_solid ^ _below(m3, top, pit_solid)
    if clipped.is_empty() or clipped.volume() <= 1e-9:
        raise ValueError(f"backfill {name!r}: nothing of {pit!r} lies below "
                         f"the backfill's top")
    bb = clipped.bounding_box()
    box = ((bb[0], bb[1], bb[2]), (bb[3], bb[4], bb[5]))
    skip = set(exclude) | {pit, name, getattr(pit_el, "voids", None)}
    taken, names = [], []
    for el in model.elements:
        if el.name in skip or el.ifc_class in NOT_SUBTRACTED or el.geometry is None:
            continue
        dicts = [d for ds in body_dicts(el) for d in ds]
        if not dicts or all(d.get("kind") == "none" for d in dicts):
            continue
        quick = _placed_bounds(el, dicts)
        if quick is not None and not _overlaps(quick, box):
            continue
        solid, _ = _solid(el)
        if (solid ^ clipped).volume() > 1e-9:
            taken.append(solid)
            names.append(el.name)
    standing = (m3.Manifold.batch_boolean(taken, m3.OpType.Add)
                if len(taken) > 1 else taken[0] if taken else None)
    fill = clipped - standing if standing is not None else clipped
    fill, dropped = _tidy(m3, fill, sliver_cf)
    volume = fill.volume() if not fill.is_empty() else 0.0
    if volume <= 1e-9:
        raise ValueError(f"backfill {name!r}: nothing is left of {pit!r} once "
                         f"{', '.join(names) or 'its contents'} are taken away")
    n = len(fill.decompose())
    if pieces is not None and n != pieces:
        raise ValueError(f"backfill {name!r} comes out in {n} pieces, not "
                         f"{pieces}: pass pieces={n} if that is the design "
                         f"(a wall across the pit), else check what stands "
                         f"in it ({', '.join(names) or 'nothing'})")
    mesh = fill.to_mesh()
    verts = [tuple(float(c) for c in p[:3]) for p in mesh.vert_properties]
    tris = [tuple(int(i) for i in t) for t in mesh.tri_verts]
    el = Element(name, ifc_class, geometry={"kind": "mesh", "units": "ft",
                                            "verts": verts, "tris": tris},
                 quantities={"volume_cf": volume},
                 predefined_type=predefined_type, **element_kw)
    if n > 1:
        el.body = "solids"                   # one backfill, separate bodies
    model.add(el)
    want = clipped.volume() - ((clipped ^ standing).volume()
                               if standing is not None else 0.0)
    model.stated_quantities.append(
        (f"{name}: the backfill is {pit} below its top less "
         f"{len(names)} element(s) standing in it", volume + dropped, want,
         max(1e-6 * abs(want), 1e-6)))
    if group:
        members = model.groups.setdefault(group, [])
        for member in (pit, name):
            if member not in members:
                members.append(member)
    return el
