"""Measured-geometry reader: tessellate every element with the geometry
ITERATOR and return per-element mesh measurements in SI metres.

The per-product `create_shape` path silently returns EMPTY meshes on this
codebase's files and must not be used (pipe-supports-pilot lesson) — the iterator is the
only correct API. One product may yield several shapes: volumes and plan
areas SUM, bounding boxes and z-ranges UNION. Elements with no geometric
representation (a Qto-only IFC) are simply absent from the result —
legitimate authoring, not an error.

Consumed by the est-takeoff audit's mesh leg and by
bimforge.author.gate._ifc_mesh_check — one home for the iterator discipline.
"""
from __future__ import annotations


def mesh_volume(verts, faces) -> float:
    """Signed-tet sum over triangles; origin-independent for a closed mesh."""
    import numpy as np
    v = np.asarray(verts, dtype=float).reshape(-1, 3)
    # Large world coordinates catastrophically cancel the tet sum; volume is
    # translation-invariant, so shift the mesh into its own frame first.
    v = v - v[0]
    t = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    return float(abs(np.einsum("ij,ij->i", a, np.cross(b, c)).sum()) / 6.0)


def plan_area(verts, faces) -> float:
    """Footprint area: half the summed |z-projected| triangle area — a closed
    solid contributes its top AND bottom faces, hence the extra /2."""
    import numpy as np
    v = np.asarray(verts, dtype=float).reshape(-1, 3)
    t = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    cr = np.cross(b - a, c - a)
    return float(abs(cr[:, 2]).sum() / 4.0)


def classify_faces(verts, faces, *, flat: float = 0.85,
                   split_el: float | None = None) -> dict:
    """Classify a tessellated boundary's triangles by the direction their
    normal points (the spillway-pilot build_takeoff `measure` port):

        top     nz > +flat   screeded / finished — no form
        bottom  nz < -flat   bears on subgrade or mud mat — no form
        side    otherwise    the candidate formwork face (SFCA)

    Battered and sloped faces land in `side` and are measured on the TRUE
    slope, not the plan projection — the area a form carpenter actually
    builds. `buried_sf` is a SUBSET of `side_sf`: the part below `split_el`
    (same units/frame as the verts' z), reported so cast-against-earth can
    price differently. It is flagged, not deducted.

    Unit-agnostic: areas/volume come back in the units of the verts you pass
    (the `_cf`/`_sf` keys name the CLI's feet convention). Volume reuses
    `mesh_volume`, which shifts into a local frame first — on raw State
    Plane coordinates the tet sum catastrophically cancels (a measured 2.3%
    error on spillway-pilot's chute blocks). Areas are built from coordinate
    differences and need no such shift.

    Returns {"volume_cf", "top_sf", "bottom_sf", "side_sf", "buried_sf"}.
    """
    import numpy as np
    v = np.asarray(verts, dtype=float).reshape(-1, 3)
    t = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    if len(v) == 0 or len(t) == 0:
        return {"volume_cf": 0.0, "top_sf": 0.0, "bottom_sf": 0.0,
                "side_sf": 0.0, "buried_sf": 0.0}
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    cross = np.cross(b - a, c - a)
    area = 0.5 * np.linalg.norm(cross, axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        nz = cross[:, 2] / (2.0 * area)
    nz = np.nan_to_num(nz)
    top = float(area[nz > flat].sum())
    bot = float(area[nz < -flat].sum())
    side = np.abs(nz) <= flat
    side_sf = float(area[side].sum())
    buried = 0.0
    if split_el is not None:
        # Buried is a SUBSET of side. Clip each side triangle at the split
        # plane rather than assigning it whole by its centroid: a 6-ft-tall
        # slab edge is two triangles, and by centroid the whole thing lands
        # on one side of a split that actually cuts it 3/4 of the way up.
        z = np.sort(v[t[side]][:, :, 2], axis=1)
        a_s = area[side]
        z0, z1, z2 = z[:, 0], z[:, 1], z[:, 2]
        frac = np.zeros(len(a_s))
        with np.errstate(divide="ignore", invalid="ignore"):
            # one vertex below: the cut-off corner scales as the product of
            # the two edge parameters; two below: the complement of the
            # corner above
            lo = (z0 < split_el) & (split_el <= z1)
            t01 = np.where(z1 != z0, (split_el - z0) / (z1 - z0), 1.0)
            t02 = np.where(z2 != z0, (split_el - z0) / (z2 - z0), 1.0)
            frac = np.where(lo, np.clip(t01 * t02, 0.0, 1.0), frac)
            mid = (z1 < split_el) & (split_el <= z2)
            t20 = np.where(z0 != z2, (split_el - z2) / (z0 - z2), 1.0)
            t21 = np.where(z1 != z2, (split_el - z2) / (z1 - z2), 1.0)
            frac = np.where(mid, 1.0 - np.clip(t20 * t21, 0.0, 1.0), frac)
        frac = np.where(z2 <= split_el, 1.0, frac)
        frac = np.where(z0 >= split_el, 0.0, frac)
        buried = float((a_s * np.nan_to_num(frac)).sum())
    return {"volume_cf": mesh_volume(v, t), "top_sf": top, "bottom_sf": bot,
            "side_sf": side_sf, "buried_sf": buried}


def element_meshes(ifc_path: str, *, skip_classes=()) -> list:
    """Per-element tessellated meshes in SI metres via the geometry ITERATOR
    (same discipline as `mesh_leg` — the per-product create_shape path
    silently returns EMPTY meshes and must not be used).

    Returns [(guid, name, ifc_class, verts (N, 3) float, faces (M, 3) int)]
    in iteration order; a product's several shapes concatenate into one
    mesh. `skip_classes` filters by IFC type with subtype matching (is_a) —
    e.g. pipe barrels that pass THROUGH a headwall and are not concrete.
    """
    import numpy as np
    import ifcopenshell
    import ifcopenshell.geom as geom

    f = ifcopenshell.open(str(ifc_path))
    s = geom.settings()
    s.set("use-world-coords", True)
    acc: dict[str, list] = {}
    order: list[str] = []
    it = geom.iterator(s, f)
    if not it.initialize():
        return []
    while True:
        sh = it.get()
        v = np.asarray(sh.geometry.verts, dtype=float).reshape(-1, 3)
        fa = np.asarray(sh.geometry.faces, dtype=np.int64).reshape(-1, 3)
        if len(v) and len(fa):
            a = acc.get(sh.guid)
            if a is None:
                a = acc[sh.guid] = [sh.type, [], []]
                order.append(sh.guid)
            a[2].append(fa + sum(len(x) for x in a[1]))
            a[1].append(v)
        if not it.next():
            break
    out = []
    for gid in order:
        typ, vs, fs = acc[gid]
        el = f.by_guid(gid)
        if any(el.is_a(t) for t in skip_classes):
            continue
        out.append((gid, el.Name or f"{typ}-{gid[:6]}", typ,
                    np.vstack(vs), np.vstack(fs)))
    return out


def _accumulate(acc: dict, guid: str, ifc_type: str, verts, faces) -> None:
    """Fold one shape's mesh into acc[guid]: volumes and plan areas SUM,
    bounding boxes UNION. Empty meshes are ignored."""
    import numpy as np
    v = np.asarray(verts, dtype=float)
    fa = np.asarray(faces, dtype=np.int64)
    if not (len(v) and len(fa)):
        return
    V = v.reshape(-1, 3)
    a = acc.get(guid)
    if a is None:
        a = acc[guid] = {"type": ifc_type, "vol": 0.0, "area": 0.0,
                         "lo": V.min(axis=0), "hi": V.max(axis=0)}
    a["vol"] += mesh_volume(v, fa)
    a["area"] += plan_area(v, fa)
    a["lo"] = np.minimum(a["lo"], V.min(axis=0))
    a["hi"] = np.maximum(a["hi"], V.max(axis=0))


def mesh_leg(ifc_path: str) -> dict:
    """{GlobalId: {"name", "ifc_class", "mesh": {"volume_m3", "plan_area_m2",
    "len_m", "wid_m", "hgt_m", "z_min_m", "z_max_m"}}} for every element the
    geometry iterator yields; {} when the file has no geometry at all."""
    import ifcopenshell
    import ifcopenshell.geom as geom

    f = ifcopenshell.open(str(ifc_path))
    s = geom.settings()
    s.set("use-world-coords", True)
    acc: dict[str, dict] = {}
    it = geom.iterator(s, f)
    if not it.initialize():
        return {}
    while True:
        sh = it.get()
        _accumulate(acc, sh.guid, sh.type, sh.geometry.verts, sh.geometry.faces)
        if not it.next():
            break
    out: dict[str, dict] = {}
    for gid, a in acc.items():
        el = f.by_guid(gid)
        lo, hi = a["lo"], a["hi"]
        out[gid] = {
            "name": el.Name or f"{a['type']}-{gid[:6]}",
            "ifc_class": a["type"],
            "mesh": {"volume_m3": a["vol"], "plan_area_m2": a["area"],
                     "len_m": float(hi[0] - lo[0]),
                     "wid_m": float(hi[1] - lo[1]),
                     "hgt_m": float(hi[2] - lo[2]),
                     "z_min_m": float(lo[2]), "z_max_m": float(hi[2])}}
    return out
