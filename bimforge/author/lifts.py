"""Earthwork lifts: an element's fill body cut into compacted lifts.

Embankment and structure backfill are placed and compacted in lifts — Caltrans
19-3 structure backfill in 0.67 ft layers, embankment per 19-6 — and the fill
rises lift by lift over its task. A model that carries the fill as one body
can neither show that nor schedule against it (backfill may not outrun the
wall; a tie-back goes in when the fill reaches its elevation).

`split_into_lifts(model, name, lift_ft)` replaces one element with its lifts:

* the element's body (its `body_solids()`: mesh, prism, the shipped `fill`
  kind — a gross prism less its cuts — or boxes; a list of touching cell
  solids too) is made ONE exact solid with manifold3d (union / difference);
* that solid is cut by horizontal planes every `lift_ft` (COMPACTED
  thickness: the planes are the design, as-compacted surface) from its
  bottom, or from `base_elev` (the grading plane the first lift sits on);
* each slice is a closed manifold solid — a lift element named
  "<name> lift 07 (El 148.00-148.67)", carrying the parent's class,
  material, layer, facility part and pay codes, its volume_cf, and
  `lift` metadata (index, bottom, top, thickness) on `Element.lift`;
* the parent's name becomes an assembly of its lifts, and a stated-quantity
  assertion holds the lifts' summed volume to the parent's.

The thin remainder at the top (less than `min_top_fraction` of a lift) is
merged into the lift below, as the last lift is in the field.

manifold3d is an optional dependency (``pip install 'bimforge[terrain]'``).

Examples:
    from bimforge.author.lifts import split_into_lifts
    lifts = split_into_lifts(model, "Abut 1 structure backfill", 0.67)
    [e.name for e in lifts][:2]
    # ['Abut 1 structure backfill lift 01 (El 138.00-138.67)', ...]
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Lift:
    index: int                    # 1 = the bottom lift
    z_bot: float                  # model-frame feet
    z_top: float
    verts: list
    tris: list
    volume_cf: float

    @property
    def thickness_ft(self) -> float:
        return self.z_top - self.z_bot


def _need_manifold():
    try:
        import manifold3d
    except ImportError as exc:                       # pragma: no cover
        raise ImportError("earthwork lifts need manifold3d: "
                          "pip install 'bimforge[terrain]'") from exc
    return manifold3d


def _from_mesh(verts, tris):
    import numpy as np
    m3 = _need_manifold()
    mesh = m3.Mesh64(vert_properties=np.asarray(verts, dtype=np.float64),
                     tri_verts=np.asarray(tris, dtype=np.uint64))
    mesh.merge()
    solid = m3.Manifold(mesh)
    if solid.status() != m3.Error.NoError:
        raise ValueError(f"not a closed manifold mesh ({solid.status()})")
    return solid


def _prism(ring, holes, z_bot, z_top):
    m3 = _need_manifold()
    cs = m3.CrossSection([list(map(tuple, ring))] +
                         [list(map(tuple, h)) for h in holes or ()],
                         m3.FillRule.EvenOdd)
    return cs.extrude(z_top - z_bot).translate((0.0, 0.0, z_bot))


def solid_of(dicts) -> "object":
    """ONE manifold3d solid from body_solids() dicts (units: ft), the
    union of all of them. Raises on a kind that is not earthwork-shaped."""
    from bimforge.author.primitives import taper_prism_triangles
    m3 = _need_manifold()
    parts = []
    for d in dicts:
        if d.get("units", "ft") != "ft":
            raise ValueError("lifts: only feet-unit solids are supported")
        kind = d["kind"]
        if kind == "none":
            continue
        if kind == "mesh":
            parts.append(_from_mesh(d["verts"], d["tris"]))
        elif kind == "prism":
            if d.get("z_top") is not None and d.get("top_z") is None \
                    and d.get("bottom_z") is None:
                parts.append(_prism(d["base"], d.get("holes"), d["z_bot"],
                                    d["z_top"]))
            else:
                top_z = d.get("top_z") or [d["z_top"]] * len(d["base"])
                tris = taper_prism_triangles(d["base"], top_z, d["z_bot"],
                                             d.get("bottom_z"))
                verts, idx = [], []
                for tri in tris:
                    idx.append(tuple(range(len(verts), len(verts) + 3)))
                    verts += [tuple(p) for p in tri]
                parts.append(_from_mesh(verts, idx))
        elif kind == "fill":
            acc = _prism(d["base"], d.get("holes"), d["z_bot"], d["z_top"])
            for c in d.get("cuts") or ():
                acc = acc - _prism(c["base"], c.get("holes"), c["z_bot"],
                                   c["z_top"])
            parts.append(acc)
        elif kind == "box":
            for cx, cy, cz, dx, dy, dz, *_ in d["boxes"]:
                parts.append(m3.Manifold.cube((dx, dy, dz), center=True)
                             .translate((cx, cy, cz)))
        else:
            raise ValueError(f"lifts: a {kind!r} solid is not earthwork")
    if not parts:
        raise ValueError("lifts: no solid to cut")
    return m3.Manifold.batch_boolean(parts, m3.OpType.Add) \
        if len(parts) > 1 else parts[0]


def cut_lifts(solid, lift_ft: float, base_elev: float | None = None,
              min_top_fraction: float = 0.25) -> list[Lift]:
    """Slice `solid` (manifold3d, model-frame feet) into horizontal lifts of
    `lift_ft` compacted thickness, from `base_elev` (model z) or the solid's
    bottom. Empty slices are skipped; each lift is a closed manifold."""
    m3 = _need_manifold()
    if lift_ft <= 0:
        raise ValueError("lift_ft must be positive")
    (x0, y0, z0), (x1, y1, z1) = _bbox(solid)
    base = z0 if base_elev is None else base_elev
    n = max(1, math.ceil((z1 - base) / lift_ft - 1e-9))
    planes = [base + i * lift_ft for i in range(n)] + [z1]
    if len(planes) > 2 and planes[-1] - planes[-2] < min_top_fraction * lift_ft:
        planes.pop(-2)                    # a sliver on top joins the lift below
    pad = 1.0
    out = []
    for a, b in zip(planes, planes[1:]):
        lo = max(a, z0) if a == planes[0] else a
        slab = m3.Manifold.cube((x1 - x0 + 2 * pad, y1 - y0 + 2 * pad,
                                 b - lo)).translate((x0 - pad, y0 - pad, lo))
        piece = solid ^ slab
        if piece.is_empty() or piece.volume() <= 1e-9:
            continue
        mesh = piece.to_mesh64()
        out.append(Lift(index=len(out) + 1, z_bot=a, z_top=b,
                        verts=[tuple(map(float, p))
                               for p in mesh.vert_properties[:, :3]],
                        tris=[tuple(map(int, t)) for t in mesh.tri_verts],
                        volume_cf=float(piece.volume())))
    return out


def _bbox(solid):
    bb = solid.bounding_box()
    return (bb[0], bb[1], bb[2]), (bb[3], bb[4], bb[5])


def lift_name(parent: str, lift: Lift, base_h: float, n: int) -> str:
    w = max(2, len(str(n)))
    return (f"{parent} lift {lift.index:0{w}d} "
            f"(El {lift.z_bot + base_h:.2f}-{lift.z_top + base_h:.2f})")


def split_into_lifts(model, name: str, lift_ft: float, *,
                     base_elev: float | None = None,
                     min_top_fraction: float = 0.25,
                     tol: float = 0.001) -> list:
    """Replace element `name` in `model` with its lift elements (returned,
    bottom first). `base_elev` is a TRUE elevation (ft) of the first lift's
    bottom; None starts at the body's bottom."""
    from bimforge.author.emit_ifc import body_dicts
    from bimforge.author.model import Element
    parent = model.element(name)
    dicts = [d for ds in body_dicts(parent) for d in ds]
    solid = solid_of(dicts)
    base_h = getattr(model.ctx, "base_h", 0.0) or 0.0
    z_base = None if base_elev is None else base_elev - base_h
    lifts = cut_lifts(solid, lift_ft, z_base, min_top_fraction)
    total = sum(l.volume_cf for l in lifts)  # noqa: E741
    elements = []
    for lf in lifts:
        el = Element(
            lift_name(name, lf, base_h, len(lifts)), parent.ifc_class,
            geometry={"kind": "mesh", "units": "ft", "verts": lf.verts,
                      "tris": lf.tris},
            quantities={"volume_cf": lf.volume_cf},
            classifications=list(parent.classifications),
            material=parent.material, density_pcf=parent.density_pcf,
            layer=parent.layer, predefined_type=parent.predefined_type,
            description=(f"lift {lf.index} of {len(lifts)}, "
                         f"{lf.thickness_ft:.2f} ft compacted, El "
                         f"{lf.z_bot + base_h:.2f}-{lf.z_top + base_h:.2f}"),
            spatial_part=parent.spatial_part)
        el.lift = {"index": lf.index, "of": len(lifts), "parent": name,
                   "bottom_elev": lf.z_bot + base_h,
                   "top_elev": lf.z_top + base_h,
                   "thickness_ft": lf.thickness_ft}
        elements.append(el)
    model.elements = [e for e in model.elements if e.name != name]
    for el in elements:
        model.add(el)
    for asm, members in model.assemblies.items():
        if name in members:
            i = members.index(name)
            members[i:i + 1] = [e.name for e in elements]
    if name not in model.assemblies:
        model.assemblies[name] = [e.name for e in elements]
    want = parent.quantities.get("volume_cf") or float(solid.volume())
    model.stated_quantities.append(
        (f"{name}: lifts sum to the fill", total, want, tol))
    return elements


def lift_dates(lifts, start: str, finish: str,
               workdays: frozenset = frozenset(range(5))) -> list[tuple]:
    """(start, finish) ISO days per lift, bottom first: the task's working
    days shared out by CUMULATIVE VOLUME (a lift of twice the volume takes
    twice the time), each lift starting the day the one below finishes or
    the next. `lifts` carry `.volume_cf` (Lift) or quantities["volume_cf"]
    (an Element)."""
    from datetime import date, timedelta
    d0, d1 = date.fromisoformat(start), date.fromisoformat(finish)
    days = [d0 + timedelta(i) for i in range((d1 - d0).days + 1)
            if (d0 + timedelta(i)).weekday() in workdays] or [d0]

    def vol(x):
        return getattr(x, "volume_cf", None) or x.quantities["volume_cf"]
    vols = [vol(x) for x in lifts]
    tot = sum(vols) or 1.0
    out, acc = [], 0.0
    for v in vols:
        a = int(math.floor(acc / tot * len(days) + 1e-9))
        acc += v
        b = max(a, int(math.ceil(acc / tot * len(days) - 1e-9)) - 1)
        out.append((days[min(a, len(days) - 1)].isoformat(),
                    days[min(b, len(days) - 1)].isoformat()))
    return out
