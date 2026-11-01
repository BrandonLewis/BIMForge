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


#: Feature size (ft) below which a boolean's output edges are collapsed.
#: Slicing leaves nanometre slivers where planes graze vertices; they weld
#: into false cracks in IFC and break a STEP shell, and no drawn detail is
#: that small.
SIMPLIFY_FT = 1e-5


@dataclass
class Lift:
    index: int                    # 1 = the bottom lift
    z_bot: float                  # model-frame feet
    z_top: float
    verts: list
    tris: list
    volume_cf: float
    #: separate closed bodies in the lift: a lift is level, so where walls
    #: or wings divide the fill it comes out in pieces, placed together
    pieces: int = 1
    #: knife-edge boolean leftovers dropped from the slice (`sliver_cf`)
    dropped_cf: float = 0.0
    #: the exact slice failed the weld check (`weld`) and this lift is its
    #: level-section prism instead; exact_cf is what the exact slice held
    prismatic: bool = False
    exact_cf: float | None = None

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
              min_top_fraction: float = 0.25, minus=None,
              sliver_cf: float = 0.0, weld: float = 0.0) -> list[Lift]:
    """Slice `solid` (manifold3d, model-frame feet) into horizontal lifts of
    `lift_ft` compacted thickness, from `base_elev` (model z) or the solid's
    bottom. Empty slices are skipped; each lift is a closed manifold.
    (split_into_lifts holds their sum to the body within `tol`, RELATIVE.)

    `minus` (a manifold3d solid) is taken out of EACH SLICE: a fill that is
    "this region less the structures in it" (a refill around footings,
    piles and deadmen) is sliced as the region and then cut, which keeps
    the slices exact - slicing an already-differenced body with many
    tunnels and coincident faces loses volume in manifold3d.

    `sliver_cf`: pieces of a slice smaller than this are dropped (and
    counted in Lift.dropped_cf) - the near-zero wedges a boolean leaves where
    a cut face runs a hair off a structure face. They weld shut at the IFC's
    precision into faces enclosing nothing, which no viewer draws as solid.

    `weld` (model units, 0 = off): each slice is checked the way the solid-
    body gate reads the IFC (vertices welded at `weld`); a slice that is not
    then a closed solid - a pinch where two cut faces meet along an edge -
    is replaced by its level-section prism (section_lifts), flagged
    Lift.prismatic, its exact volume kept in Lift.exact_cf."""
    m3 = _need_manifold()
    if lift_ft <= 0:
        raise ValueError("lift_ft must be positive")
    (x0, y0, z0), (x1, y1, z1) = _bbox(solid)
    planes = _planes(z0, z1, lift_ft, base_elev, min_top_fraction)
    pad = 1.0
    out = []
    for a, b in zip(planes, planes[1:]):
        lo = max(a, z0) if a == planes[0] else a
        slab = m3.Manifold.cube((x1 - x0 + 2 * pad, y1 - y0 + 2 * pad,
                                 b - lo)).translate((x0 - pad, y0 - pad, lo))
        piece = solid ^ slab
        if minus is not None:
            piece = piece - minus
        piece, dropped = _tidy(m3, piece, sliver_cf)
        if piece.is_empty() or piece.volume() <= 1e-9:
            continue
        mesh = piece.to_mesh64()
        lf = Lift(index=len(out) + 1, z_bot=a, z_top=b,
                  verts=[tuple(map(float, p)) for p in mesh.vert_properties[:, :3]],
                  tris=[tuple(map(int, t)) for t in mesh.tri_verts],
                  volume_cf=float(piece.volume()),
                  pieces=len(piece.decompose()), dropped_cf=dropped)
        if weld > 0 and not _welds_closed(lf, weld):
            prism = _section_prism(m3, solid, minus, lo, b)
            if prism is not None:
                exact = lf.volume_cf
                lf = _lift_of(prism, lf.index, a, b)
                lf.dropped_cf, lf.prismatic, lf.exact_cf = dropped, True, exact
        out.append(lf)
    return out


def _welds_closed(lf: Lift, weld: float) -> bool:
    from bimforge.bim.ifc_mesh import mesh_topology
    return mesh_topology(lf.verts, lf.tris, weld=weld)["closed"]


def _lift_of(piece, index, a, b) -> Lift:
    mesh = piece.to_mesh64()
    return Lift(index=index, z_bot=a, z_top=b,
                verts=[tuple(map(float, p)) for p in mesh.vert_properties[:, :3]],
                tris=[tuple(map(int, t)) for t in mesh.tri_verts],
                volume_cf=float(piece.volume()), pieces=len(piece.decompose()))


def section_lifts(solid, lift_ft: float, base_elev: float | None = None,
                  min_top_fraction: float = 0.25, minus=None,
                  open_ft: float = 0.01) -> list[Lift]:
    """Lifts as LEVEL PRISMS: each lift is the plan section of `solid` less
    `minus` at the lift's mid-height, extruded through the lift.

    For a fill that is a region less many structures in it (a work-cut
    refill around footings, piles, sheets and deadmen) the 3D slice-and-
    subtract of cut_lifts leaves sub-micron wedges and pinches wherever a
    cut face runs a hair off a structure face, which no viewer welds into a
    solid. The plan section is a 2D boolean (robust, snapped), opened by
    `open_ft` (shrunk then regrown: knife-edge strips and point contacts
    between bodies close up), so every lift is a clean closed prism. The
    price is a stair-step of half a lift on sloped faces: the sum differs
    from the body by the midpoint rule (split_into_lifts holds it to
    `prism_tol`)."""
    m3 = _need_manifold()
    if lift_ft <= 0:
        raise ValueError("lift_ft must be positive")
    (_x0, _y0, z0), (_x1, _y1, z1) = _bbox(solid)
    planes = _planes(z0, z1, lift_ft, base_elev, min_top_fraction)
    out = []
    for a, b in zip(planes, planes[1:]):
        lo = max(a, z0) if a == planes[0] else a
        piece = _section_prism(m3, solid, minus, lo, b, open_ft)
        if piece is not None:
            out.append(_lift_of(piece, len(out) + 1, a, b))
    return out


def _section_prism(m3, solid, minus, lo, b, open_ft: float = 0.01):
    """The level prism lo..b of `solid` less `minus` at mid-height (None if
    the section is empty); see section_lifts."""
    zm = 0.5 * (lo + b)
    cs = solid.slice(zm)
    if minus is not None:
        cs = cs - minus.slice(zm)
    # simplify FIRST: Clipper's offset of a section carrying near-
    # duplicate vertices can collapse the whole thing to nothing
    cs = cs.simplify(SIMPLIFY_FT * 10)
    if open_ft > 0:
        opened = cs.offset(-open_ft, m3.JoinType.Miter).offset(
            open_ft, m3.JoinType.Miter)
        # opening takes knife-edges, not ground: if it took more, keep
        # the section as it was rather than lose a lift
        if opened.area() >= 0.98 * cs.area():
            cs = opened
    if cs.is_empty() or cs.area() <= 1e-9:
        return None
    return m3.Manifold.extrude(cs, b - lo).translate((0.0, 0.0, lo))


def _planes(z0, z1, lift_ft, base, min_top_fraction):
    base = z0 if base is None else base
    n = max(1, math.ceil((z1 - base) / lift_ft - 1e-9))
    planes = [base + i * lift_ft for i in range(n)] + [z1]
    if len(planes) > 2 and planes[-1] - planes[-2] < min_top_fraction * lift_ft:
        planes.pop(-2)                    # a sliver on top joins the lift below
    return planes


def _tidy(m3, piece, sliver_cf: float):
    """(piece, dropped_cf): each body of `piece` simplified (collapsing the
    slab's nanometre edges) where that holds its volume - on a body with
    many holes simplify can fold real faces away - and bodies under
    `sliver_cf` dropped."""
    bodies = piece.decompose() if sliver_cf > 0 else [piece]
    keep, dropped = [], 0.0
    for b in bodies:
        v = b.volume()
        if sliver_cf > 0 and v < sliver_cf:
            dropped += v
            continue
        tidy = b.simplify(SIMPLIFY_FT)
        keep.append(tidy if abs(tidy.volume() - v) <= 1e-7 * max(v, 1.0)
                    else b)
    if not keep:
        return m3.Manifold(), dropped
    if len(keep) == 1:
        return keep[0], dropped
    return m3.Manifold.batch_boolean(keep, m3.OpType.Add), dropped


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
                     tol: float = 1e-5, minus=None,
                     sliver_cf: float = 0.0, prismatic: bool = False,
                     prism_tol: float = 0.03, weld: float | None = None) -> list:
    """Replace element `name` in `model` with its lift elements (returned,
    bottom first). `base_elev` is a TRUE elevation (ft) of the first lift's
    bottom; None starts at the body's bottom.

    `prismatic`: level-section prisms (section_lifts) instead of exact
    slices; their sum is held to the body within `prism_tol` (relative),
    not `tol`.

    `weld` (model units): see cut_lifts; None = the solid-body gate's weld
    (bimforge.bim.ifc_mesh.WELD_M) in the model's units, 0 = off."""
    from bimforge.author.emit_ifc import body_dicts
    from bimforge.author.model import Element
    parent = model.element(name)
    dicts = [d for ds in body_dicts(parent) for d in ds]
    solid = solid_of(dicts)
    base_h = getattr(model.ctx, "base_h", 0.0) or 0.0
    z_base = None if base_elev is None else base_elev - base_h
    if prismatic:
        lifts = section_lifts(solid, lift_ft, z_base, min_top_fraction,
                              minus=minus)
        tol = prism_tol
    else:
        if weld is None:
            from bimforge.bim.ifc_mesh import WELD_M
            weld = WELD_M / (getattr(model.ctx, "ft_to_m", None) or 0.3048)
        lifts = cut_lifts(solid, lift_ft, z_base, min_top_fraction,
                          minus=minus, sliver_cf=sliver_cf, weld=weld)
    # dropped slivers count toward the sum: the check is that the slicing
    # lost nothing BUT what it reports dropping (Lift.dropped_cf)
    # a lift that fell back to a prism counts at its exact slice's volume:
    # the check is on the slicing; the prisms are reported (lift metadata)
    total = sum((l.exact_cf if l.exact_cf is not None else l.volume_cf)  # noqa: E741
                + l.dropped_cf for l in lifts)
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
        if lf.pieces > 1:
            el.body = "solids"               # one lift, separate bodies
        el.lift = {"index": lf.index, "of": len(lifts), "parent": name,
                   "bottom_elev": lf.z_bot + base_h,
                   "top_elev": lf.z_top + base_h,
                   "thickness_ft": lf.thickness_ft, "pieces": lf.pieces}
        if lf.dropped_cf:
            el.lift["dropped_cf"] = lf.dropped_cf
        if lf.prismatic:
            el.lift["prismatic"] = True
            el.description += " (level prism: the exact slice pinched)"
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
    want = parent.quantities.get("volume_cf") or float(
        (solid - minus).volume() if minus is not None else solid.volume())
    # RELATIVE: booleans on a thousand-CF body round in the 4th decimal
    what = "level lifts within {:g}% of".format(100 * tol) if prismatic \
        else "lifts sum to"
    model.stated_quantities.append(
        (f"{name}: {what} the fill", total, want, max(tol * abs(want), 1e-6)))
    return elements


def lift_dates(lifts, start: str, finish: str | None = None, *,
               rate_cy_per_day: float | None = None,
               workdays: frozenset = frozenset(range(5))) -> list[tuple]:
    """(start, finish) ISO days per lift, bottom first.

    With `rate_cy_per_day` (the crew's compacted production rate) each lift
    takes its own volume / rate, working days only, starting at `start` and
    carrying over to the next working day: lift 5 begins where lift 4
    ended, so a big lower lift and a thin top lift take what they take, and
    `finish` (if given) is only a check — `lift_overrun` tells by how much
    the rate misses it. Without a rate the lifts share the working days of
    `start`..`finish` by cumulative volume. `lifts` carry `.volume_cf`
    (Lift) or quantities["volume_cf"] (an Element)."""
    from datetime import date, timedelta

    def vol(x):
        return getattr(x, "volume_cf", None) or x.quantities["volume_cf"]
    vols = [vol(x) for x in lifts]
    d0 = date.fromisoformat(start)

    def workday(i):                       # the i-th working day from d0
        d, n = d0, -1
        while True:
            if d.weekday() in workdays:
                n += 1
                if n == i:
                    return d
            d += timedelta(1)

    if rate_cy_per_day:
        if rate_cy_per_day <= 0:
            raise ValueError("rate_cy_per_day must be positive")
        out, t = [], 0.0                  # t: working days elapsed
        for v in vols:
            a = t
            t += v / 27.0 / rate_cy_per_day
            out.append((workday(int(math.floor(a + 1e-9))).isoformat(),
                        workday(max(int(math.floor(a + 1e-9)),
                                    int(math.ceil(t - 1e-9)) - 1)).isoformat()))
        return out
    if finish is None:
        raise ValueError("lift_dates needs a finish or a rate_cy_per_day")
    d1 = date.fromisoformat(finish)
    days = [d0 + timedelta(i) for i in range((d1 - d0).days + 1)
            if (d0 + timedelta(i)).weekday() in workdays] or [d0]
    tot = sum(vols) or 1.0
    out, acc = [], 0.0
    for v in vols:
        a = int(math.floor(acc / tot * len(days) + 1e-9))
        acc += v
        b = max(a, int(math.ceil(acc / tot * len(days) - 1e-9)) - 1)
        out.append((days[min(a, len(days) - 1)].isoformat(),
                    days[min(b, len(days) - 1)].isoformat()))
    return out


def lift_overrun(dates, finish: str,
                 workdays: frozenset = frozenset(range(5))) -> int:
    """Working days the last lift ends AFTER `finish` (0 if on time)."""
    from datetime import date, timedelta
    end, f = date.fromisoformat(dates[-1][1]), date.fromisoformat(finish)
    n, d = 0, f
    while d < end:
        d += timedelta(1)
        n += d.weekday() in workdays
    return n
