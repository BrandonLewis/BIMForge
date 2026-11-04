"""Developed elevations along an IfcAlignment, drawn to DXF sheets.

A developed elevation unrolls the model along an OFFSET LINE of the
alignment (a wall face, a barrier's back, the line 2 ft behind a wall where
its drains run) and looks at it square-on: horizontal = true length along
that line (on an arc, not the station span), vertical = elevation. Station
ticks along the bottom label it.

    view = ElevationView("OVERALL", from_station=54740, to_station=54780,
                         offset=23.0, side="Lt", look_from="left", depth=15)
    drawing = develop(ifc, view)          # cut + visible edges, view frame
    write_dxf([drawing, ...], "wall.dxf", sheet=Sheet())

What is drawn, per view:

* CUT - everything the offset surface passes through, filled (hatched) per
  its IFC surface style, so the wall reads as concrete and the backfill as
  earth. An open surface (terrain, finished grade) cuts as a LINE: the
  existing and finished ground along the face.
* BEYOND - the visible edges of everything between the cut and `depth`
  further on, hidden lines removed (a depth buffer at `resolution`).
  What stands on the viewer's side of the cut is not drawn.
* GRID - station ticks and elevation lines; a title.

`look_from` is the viewer's side of the line: "left" looks toward the
right (the formed face of a wall on the Rt, seen from the road), "right"
toward the left (its retained side, where the drainage runs). The view is
TRUE - as seen - so looking from the left, stations increase to the LEFT;
`true_view=False` mirrors it to read left to right (noted in the title).

`date` shows the model as it stands on that day (its 4D schedule).

The geometry is unrolled per vertex (station/offset of every vertex,
bimforge.bim.alignment_station.locate_many); on a curved line long faces are
split first so they bend with it (`max_edge`).

`est-bim elevation set.yaml` draws a whole sheet set: an overall view and
enlarged segments (see `load_set`).

`cross_section` draws the other view, a SECTION square to the alignment at one
station (what the Blender add-on's section camera shows): the same cut,
ground lines and visible edges beyond, to the same DXF sheets, with offset
ticks (CL, 10 Lt, 10 Rt) along the bottom instead of stations.

    sec = SectionView("STA 1+00", station=100.0, width=40, depth=1)
    write_dxf([cross_section(ifc, sec)], "section.dxf")
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

STATION_RX = re.compile(r"^\s*(-?)(\d+)\+(\d+(?:\.\d*)?)\s*$")


def parse_station(v, unit: str = "ft") -> float:
    """547+62.90 -> 54762.90 (ft) / 1+234.5 -> 1234.5 (m); numbers pass."""
    if isinstance(v, (int, float)):
        return float(v)
    m = STATION_RX.match(str(v))
    if not m:
        return float(v)
    per = 100.0 if unit == "ft" else 1000.0
    val = int(m.group(2)) * per + float(m.group(3))
    return -val if m.group(1) else val


@dataclass
class ElevationView:
    name: str
    from_station: float                     # station unit (ft / m)
    to_station: float
    offset: float = 0.0                     # distance from the line
    side: str = "Lt"                        # which side the offset is
    look_from: str = "left"                 # the viewer's side of the line
    depth: float = 20.0                     # how far beyond the cut to draw
    alignment: str | None = None            # IfcAlignment Name (default: first)
    scale: float | None = None              # model units per paper inch
    exaggeration: float = 1.0               # vertical
    true_view: bool = True
    date: str | None = None
    resolution: float | None = None         # depth-buffer cell (model units)
    title: str | None = None

    @property
    def offset_left(self) -> float:
        right = str(self.side).strip().upper() in ("RT", "R", "RIGHT")
        return -abs(self.offset) if right else abs(self.offset)


@dataclass
class SectionView:
    """A cross section square to the alignment (in plan) at `station`:
    x across the view, the viewer's left to right (looking ahead, Lt is on
    the left), `width` wide and centred on the line; y elevation. Lengths in
    the station unit."""
    name: str
    station: float
    width: float = 40.0                     # across, centred on the line
    depth: float = 1.0                      # how far beyond the cut to draw
    look_back: bool = False                 # look down-station
    alignment: str | None = None
    scale: float | None = None
    exaggeration: float = 1.0
    date: str | None = None
    resolution: float | None = None
    title: str | None = None

    @property
    def from_station(self) -> float:
        return self.station

    @property
    def to_station(self) -> float:
        return self.station


@dataclass
class Drawing:
    """One view, in its own 2D frame: x = length along the developed line
    (0 at from_station, flipped for a true view from the left), y =
    elevation (exaggerated). Units: the station unit."""
    view: ElevationView
    cut: list = field(default_factory=list)      # (layer, rgb, [rings])
    ground: list = field(default_factory=list)   # (layer, rgb, polyline)
    beyond: list = field(default_factory=list)   # visible polylines [(x, y)...]
    ticks: list = field(default_factory=list)    # (x, station) every unit
    extent: tuple = (0.0, 0.0, 1.0, 1.0)         # xmin, ymin, xmax, ymax
    length: float = 0.0
    unit: str = "ft"
    foot_m: float = 1200.0 / 3937.0              # the file's foot, metres
    elements: int = 0
    limits: list = field(default_factory=list)   # excavation limits [(x, y)...]
    tick_kind: str = "station"                   # "offset": ticks are offsets left


# ---------------------------------------------------------------- geometry
_BODY_CACHE: dict = {}
#: an excavation's outline in a cut: the limit of excavation (a pay line),
#: never a fill - the cut is ground removed (IfcEarthworksCut voiding it)
LIMIT = "limit"
LIMIT_LAYER = "E-EXCV-LIMIT"
LIMIT_RGB = (0.95, 0.45, 0.05)


def _all_bodies(f, date):
    """[(name, layer, surface?, verts (n,3) model m, tris (k,3), rgb per tri)]
    of every element with a body standing on `date` (None: all) - read once
    per file and date, shared by every view drawn from it."""
    key = (id(f), date)
    if key in _BODY_CACHE:
        return _BODY_CACHE[key]
    import ifcopenshell.geom as geom
    import ifcopenshell.util.element as ue
    import numpy as np
    spans = None
    if date:
        from .schedule_state import element_spans, standing
        spans = element_spans(f)
    s = geom.settings()
    s.set("use-world-coords", True)
    it = geom.iterator(s, f)
    out, undug = [], []
    if it.initialize():
        while True:
            sh = it.get()
            el = f.by_id(sh.id)
            g = sh.geometry
            t = np.asarray(g.faces, dtype=np.int64).reshape(-1, 3)
            if el.is_a("IfcFeatureElementSubtraction") or is_excavation(el):
                # excavation is ground REMOVED: never a body. Its outline is
                # the limit of excavation; until it is dug (a 4D date before
                # its task) it is still ground, drawn as its host is.
                if is_excavation(el) and len(t):
                    v = np.asarray(g.verts, dtype=float).reshape(-1, 3)
                    out.append((el.Name or el.is_a(), LIMIT_LAYER, LIMIT, v, t,
                                [LIMIT_RGB] * len(t)))
                    dug = spans is None or standing(spans.get(el.GlobalId), date)
                    if not dug:
                        hosts = [r.RelatingBuildingElement
                                 for r in getattr(el, "VoidsElements", None) or ()]
                        undug.append((el.Name or el.is_a(),
                                      hosts[0].Name if hosts else None, v, t))
            elif (el.is_a("IfcElement") and len(t)
                    and not (spans is not None
                             and not standing(spans.get(el.GlobalId), date))):
                v = np.asarray(g.verts, dtype=float).reshape(-1, 3)
                mats = [_named(f, m) for m in g.materials]
                ids = np.asarray(g.material_ids, dtype=np.int64)
                rgb = [_surface_rgb(m) for m in mats] or [(0.6, 0.6, 0.6)]
                tri_rgb = ([rgb[i] if 0 <= i < len(rgb) else rgb[0] for i in ids]
                           if len(ids) == len(t) else [rgb[0]] * len(t))
                # a multi-material product (concrete and steel solids) cuts
                # per material: each part its own layer, colour and hatch
                parts = ([(ids == i, [mats[i]], [rgb[i]], None)
                          for i in sorted(set(ids.tolist())) if 0 <= i < len(mats)]
                         if len(ids) == len(t) and len(set(ids.tolist())) > 1
                         else [(None, mats, rgb, ue.get_material(el))])
                # a surface (terrain, finished grade) cuts as a LINE; a body
                # with any solid item is never one, even when the geometry
                # kernel draws it open (IfcSectionedSolidHorizontal, #9820)
                solid = any(i.is_a("IfcSolidModel")
                            for r in (el.Representation.Representations
                                      if el.Representation else ())
                            for i in r.Items)
                for sel, pm, prgb, pmat in parts:
                    pt = t if sel is None else t[sel]
                    ptr = tri_rgb if sel is None else [prgb[0]] * len(pt)
                    layer, ptr = _cut_layer(el, pmat, pm, prgb, ptr)
                    out.append((el.Name or el.is_a(), layer,
                                (not solid) and _is_surface(v, pt), v, pt, ptr))
            if not it.next():
                break
    host_style = {name: (layer, trgb[0]) for name, layer, surf, _v, _t, trgb in out
                  if surf is not LIMIT and trgb}
    for name, host, v, t in undug:
        layer, rgb = host_style.get(host, (_layer_name("Earthwork"), (0.56, 0.44, 0.30)))
        out.append((f"{name} (not yet dug)", layer, False, v, t, [rgb] * len(t)))
    _BODY_CACHE[key] = out
    return out


def _named(f, m):
    """A kernel material with its IfcSurfaceStyle's NAME ("Concrete"): the
    kernel names it after its rendering ("IfcSurfaceStyleRendering-170"),
    which says nothing; instance_id() is the style (0.8 and 0.9 alike)."""
    from types import SimpleNamespace
    name = getattr(m, "name", None)
    try:
        iid = m.instance_id() if callable(m.instance_id) else m.instance_id
        e = f.by_id(int(iid))
        if e.is_a("IfcSurfaceStyleShading"):
            e = next((x for x in f.get_inverse(e) if x.is_a("IfcSurfaceStyle")), e)
        if e.is_a("IfcSurfaceStyle") and e.Name:
            name = e.Name
    except Exception:                   # no id, or not a style: keep the kernel's
        pass
    return SimpleNamespace(name=name, surface=getattr(m, "surface", None),
                           diffuse=m.diffuse)


def is_excavation(el) -> bool:
    """Excavation: an IfcEarthworksCut (voiding the ground), or the pay-item
    body emit_ifc writes for an unhosted one (IfcEarthworksElement,
    ObjectType EXCAVATION, #364) - ground removed either way."""
    if el.is_a("IfcEarthworksCut"):
        return True
    return (el.is_a("IfcEarthworksElement")
            and (getattr(el, "ObjectType", None) or "").upper() == "EXCAVATION")


def _surface_rgb(m) -> tuple:
    """A style's own colour: the SURFACE colour, not the diffuse the kernel
    scales by (1 - transparency) - a cut face is solid, so see-through earth
    must still fill as earth, not half-dark."""
    for c in (getattr(m, "surface", None), m.diffuse):
        if c is not None:
            return tuple(c.components)
    return (0.6, 0.6, 0.6)


def _cut_layer(el, mat, mats, rgb, tri_rgb):
    """(layer, tri_rgb) of a cut: the layer names the material (its
    IfcMaterial, else its IfcSurfaceStyle, else its class), and when that
    name does not say what it is, the kind its style, element name or class
    does (drain rock, AB, CDF), as the Blender add-on reads it - whatever
    its colour. Only an unstyled body takes the kind's colour."""
    from .section_style import style_of
    style = next((m.name for m in mats if getattr(m, "name", None)
                  and not _unstyled(_surface_rgb(m))), None)
    base = getattr(mat, "Name", None) or style or el.is_a()
    # the class last: an unstyled IfcWall named "Lean Concrete" is lean
    k = style_of(getattr(mat, "Name", None), style, el.Name, el.is_a())
    layer = _layer_name(base)
    # judged on the layer as written (sanitised, 40 characters): the hatch
    # builders classify that, and a cut name can read differently
    if k is not None and style_of(layer.replace("E-CUT-", "")) is not k:
        layer = _layer_name(k.kind)
    if k is not None and all(_unstyled(c) for c in rgb):
        tri_rgb = [k.rgb] * len(tri_rgb)
    return layer, tri_rgb


def _unstyled(rgb) -> bool:
    """The kernel's default grey (no IfcSurfaceStyle)."""
    return all(abs(c - d) < 1e-3 for c, d in zip(rgb, (0.6, 0.6, 0.6))) or \
        all(abs(c - d) < 1e-3 for c, d in zip(rgb, (0.8, 0.8, 0.8)))


def _layer_name(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", s).strip("-")[:40] or "X"
    return f"E-CUT-{s}"


def _is_surface(v, t) -> bool:
    """An open mesh (a terrain ribbon): some edge used by one triangle only."""
    from collections import Counter
    c = Counter()
    for a, b, d in t:
        for e in ((a, b), (b, d), (d, a)):
            c[(min(e), max(e))] += 1
    open_edges = sum(1 for n in c.values() if n == 1)
    return open_edges > 0.02 * len(c)


def _subdivide(v, t, max_edge):
    """Split triangles whose plan edges exceed `max_edge` (longest edge
    midpoint, repeatedly) so the unroll can bend them along a curve."""
    import numpy as np
    verts = [tuple(p) for p in v]
    tris = [tuple(x) for x in t]
    out, keep_idx = [], []
    stack = [(tri, i) for i, tri in enumerate(tris)]
    cache = {}
    while stack:
        (a, b, c), src = stack.pop()
        pa, pb, pc = verts[a], verts[b], verts[c]
        ls = [math.hypot(pb[0] - pa[0], pb[1] - pa[1]),
              math.hypot(pc[0] - pb[0], pc[1] - pb[1]),
              math.hypot(pa[0] - pc[0], pa[1] - pc[1])]
        k = max(range(3), key=lambda i: ls[i])
        if ls[k] <= max_edge:
            out.append((a, b, c))
            keep_idx.append(src)
            continue
        i, j, o = [(a, b, c), (b, c, a), (c, a, b)][k]
        key = (min(i, j), max(i, j))
        if key not in cache:
            pi, pj = verts[i], verts[j]
            verts.append(tuple((x + y) / 2 for x, y in zip(pi, pj)))
            cache[key] = len(verts) - 1
        m = cache[key]
        stack += [((i, m, o), src), ((m, j, o), src)]
    return np.array(verts), np.array(out, dtype=np.int64), keep_idx


class _Unroll:
    """Model plan point -> (length along the offset line, offset left)."""

    def __init__(self, st, offset_left_m, d0, d1, step=0.25):
        import numpy as np
        self.st = st
        pad = 5.0
        a, b = max(0.0, d0 - pad), min(st.length, d1 + pad)
        n = max(2, int(math.ceil((b - a) / step)) + 1)
        self.d = np.linspace(a, b, n)
        pts = np.array([st.point_at(float(x), offset_left_m)[:2] for x in self.d])
        seg = np.hypot(*(pts[1:] - pts[:-1]).T)
        self.u = np.concatenate([[0.0], np.cumsum(seg)])
        self.u -= float(np.interp(d0, self.d, self.u))

    def u_of(self, d):
        import numpy as np
        return np.interp(d, self.d, self.u)

    def curved(self) -> bool:
        import numpy as np
        az = [self.st.frame(float(x)).azimuth for x in self.d[:: max(1, len(self.d) // 50)]]
        return float(np.ptp(np.unwrap(np.radians(az)))) > 1e-6


def _stationer_for(f, name):
    from .alignment_station import AlignmentStationer, alignments
    found = alignments(f)
    if not found:
        raise ValueError("no IFC4X3 IfcAlignment to draw along")
    label = lambda a: a.Name or f"#{a.id()}"  # noqa: E731  AlignmentStationer.name
    al = next((a for a in found if label(a) == name), None) if name else found[0]
    if al is None:
        raise ValueError(f"no IfcAlignment {name!r} (has {[label(a) for a in found]})")
    return AlignmentStationer(f, al)


def develop(f, view: ElevationView, *, max_edge: float | None = None) -> Drawing:
    """The view's cut, ground lines and visible edges (see the module
    docstring). `f`: an open IFC4X3 file with the alignment."""
    import numpy as np
    st = _stationer_for(f, view.alignment)
    unit = st.station_unit
    to_m = st.from_unit(1.0, unit)                        # unit -> metres
    proj = lambda s: s * to_m / st.unit_scale             # noqa: E731  unit -> project
    d0 = st.distance_at(proj(view.from_station))
    d1 = st.distance_at(proj(view.to_station))
    if not 0.0 <= d0 < d1 <= st.length + 1e-6:
        raise ValueError(f"{view.name}: {view.from_station}..{view.to_station} "
                         f"is not along {st.name}")
    o_cut = view.offset_left * to_m                       # metres, + left
    depth = view.depth * to_m
    left_viewer = str(view.look_from).lower().startswith("l")
    band = (o_cut - depth, o_cut) if left_viewer else (o_cut, o_cut + depth)
    un = _Unroll(st, o_cut, d0, d1)
    if max_edge is None:
        max_edge = 1.0 if un.curved() else float("inf")
    sign = -1.0 if (left_viewer and view.true_view) else 1.0
    u_len = float(un.u_of(d1))
    k = st.to_unit(1.0, unit)                             # metres -> unit
    ex = view.exaggeration
    za = st.to_unit(st.elevation_m(0.0), unit)            # model z -> elevation:
    zb = st.to_unit(st.elevation_m(1.0), unit) - za       # linear (map conversion)

    def to2d(u, z):
        x = (u * k) if sign > 0 else (u_len - u) * k
        return x, z * ex

    drawing = Drawing(view=view, unit=unit, length=u_len * k, foot_m=st.foot_m)
    # warped bodies: (u, dist-from-viewer, z) per vertex, cut to the view:
    # triangles within the stations (plus a pad) and the depth band only
    pad = 1.0
    warped = []
    for name, layer, surface, v, t, trgb in _all_bodies(f, view.date):
        d, o = st.locate_many(v[:, :2])
        dist = (o_cut - o) if left_viewer else (o - o_cut)
        td, tz = d[t], dist[t]
        crosses = (tz.max(1) >= 0.0) & (tz.min(1) <= 0.0)  # the cut: whole length,
        keep = (crosses | ((td.max(1) >= d0 - pad)          # so it closes
                           & (td.min(1) <= d1 + pad)))
        keep &= (tz.max(1) >= 0.0) & (tz.min(1) <= depth)
        if not keep.any():
            continue
        idx = np.nonzero(keep)[0]
        t = t[idx]
        trgb = [trgb[i] for i in idx]
        if max_edge != float("inf"):
            used = np.unique(t)
            remap = -np.ones(len(v), dtype=np.int64)
            remap[used] = np.arange(len(used))
            v, t = v[used], remap[t]
            v, t, kept = _subdivide(v, t, max_edge)
            trgb = [trgb[i] for i in kept]
            d, o = st.locate_many(v[:, :2])
            dist = (o_cut - o) if left_viewer else (o - o_cut)
        u = un.u_of(d)
        z = za + zb * v[:, 2]
        inside = (d >= d0 - 1e-9) & (d <= d1 + 1e-9)
        warped.append((name, layer, surface, u, dist, z, t, trgb, inside))
    drawing.elements = len(warped)
    # ---------------------------------------------------------------- cut
    for name, layer, surface, u, dist, z, t, trgb, inside in warped:
        segs, rgbs = _plane_cut(u, dist, z, t, trgb)
        if not segs:
            continue
        segs = [(to2d(*a), to2d(*b)) for a, b in segs]
        if surface is LIMIT:              # the limit of excavation: a line
            segs = _clip_segments_x(segs, 0.0, drawing.length)
            drawing.limits += _chain(segs) if segs else []
            continue
        rgb = max(set(rgbs), key=rgbs.count)
        rings = [] if surface else _polygons(segs, 0.0, drawing.length)
        if not rings:
            segs = _clip_segments_x(segs, 0.0, drawing.length)
            if not segs:
                continue
        if rings:
            drawing.cut.append((layer, rgb, rings))
        else:                     # a surface, or a body whose cut does not close
            for line in _chain(segs):
                drawing.ground.append((layer.replace("E-CUT-", "E-GROUND-"), rgb, line))
    # ----------------------------------------------------- visible beyond
    drawing.beyond = _visible_edges([w for w in warped if w[2] is not LIMIT], to2d,
                                    drawing, view, depth * k, k)
    # ---------------------------------------------------------- ticks
    drawing.ticks = _ticks(st, un, view, d0, d1, to2d, unit, k)
    zs = [p[1] for _l, _r, polys in drawing.cut for poly in polys for loop in poly
          for p in loop]
    zs += [p[1] for _l, _r, line in drawing.ground for p in line]
    zs += [p[1] for line in drawing.beyond for p in line]
    if zs:
        drawing.extent = (0.0, min(zs), drawing.length, max(zs))
    return drawing


def cross_section(f, view: SectionView) -> Drawing:
    """The section square to the alignment at `view.station`: the cut
    filled per styling, open surfaces as ground lines, the visible edges up
    to `depth` beyond, offset ticks along the bottom. The plane is the one
    the Blender add-on's section camera stands on: vertical, square to the
    PLAN tangent."""
    import numpy as np
    st = _stationer_for(f, view.alignment)
    unit = st.station_unit
    to_m = st.from_unit(1.0, unit)                        # unit -> metres
    k = 1.0 / to_m                                        # metres -> unit
    d = st.distance_at(view.station * to_m / st.unit_scale)
    if not -1e-6 <= d <= st.length + 1e-6:
        raise ValueError(f"{view.name}: station {view.station} is not along {st.name}")
    fr = st.frame(d)
    T = np.array(fr.plan_tangent[:2]) * (-1.0 if view.look_back else 1.0)
    R = np.array([T[1], -T[0]])                           # the viewer's right
    P = np.array(fr.point[:2])
    half = view.width * to_m / 2.0
    depth = view.depth * to_m
    ex = view.exaggeration
    za = st.to_unit(st.elevation_m(0.0), unit)            # model z -> elevation
    zb = st.to_unit(st.elevation_m(1.0), unit) - za

    def to2d(u, z):
        return u * k, z * ex

    drawing = Drawing(view=view, unit=unit, length=2.0 * half * k,
                      foot_m=st.foot_m, tick_kind="offset")
    warped = []
    for name, layer, surface, v, t, trgb in _all_bodies(f, view.date):
        rel = v[:, :2] - P
        dist, across = rel @ T, rel @ R
        tz, tx = dist[t], across[t]
        # the cut: every triangle the plane crosses, however wide, so a body
        # wider than the view (the ground) closes; beyond: within the width
        crosses = (tz.max(1) >= 0.0) & (tz.min(1) <= 0.0)
        keep = crosses | ((tz.max(1) >= 0.0) & (tz.min(1) <= depth)
                          & (tx.max(1) >= -half - 1.0) & (tx.min(1) <= half + 1.0))
        if not keep.any():
            continue
        idx = np.nonzero(keep)[0]
        warped.append((name, layer, surface, across + half, dist,
                       za + zb * v[:, 2], t[idx], [trgb[i] for i in idx], None))
    drawing.elements = len(warped)
    for _name, layer, surface, u, dist, z, t, trgb, _in in warped:
        segs, rgbs = _plane_cut(u, dist, z, t, trgb)
        if not segs:
            continue
        segs = [(to2d(*a), to2d(*b)) for a, b in segs]
        if surface is LIMIT:              # the limit of excavation: a line
            segs = _clip_segments_x(segs, 0.0, drawing.length)
            drawing.limits += _chain(segs) if segs else []
            continue
        rgb = max(set(rgbs), key=rgbs.count)
        rings = [] if surface else _polygons(segs, 0.0, drawing.length)
        if not rings:
            segs = _clip_segments_x(segs, 0.0, drawing.length)
            if not segs:
                continue
        if rings:
            drawing.cut.append((layer, rgb, rings))
        else:                     # a surface, or a body whose cut does not close
            for line in _chain(segs):
                drawing.ground.append((layer.replace("E-CUT-", "E-GROUND-"), rgb, line))
    drawing.beyond = _visible_edges([w for w in warped if w[2] is not LIMIT], to2d,
                                    drawing, view, depth * k, k)
    # an offset tick every whole unit: (x, offset left); looking ahead the
    # left is on the viewer's left
    w2 = view.width / 2.0
    o = math.ceil(-w2 - 1e-9)
    while o <= w2 + 1e-9:
        drawing.ticks.append((float(w2 + (o if view.look_back else -o)), float(o)))
        o += 1
    drawing.ticks.sort()
    zs = [p[1] for _l, _r, polys in drawing.cut for poly in polys for loop in poly
          for p in loop]
    zs += [p[1] for _l, _r, line in drawing.ground for p in line]
    zs += [p[1] for line in drawing.beyond for p in line]
    if zs:
        drawing.extent = (0.0, min(zs), drawing.length, max(zs))
    else:
        g = st.to_unit(st.elevation_m(fr.point[2]), unit) * ex
        drawing.extent = (0.0, g - 1.0, drawing.length, g + 1.0)
    return drawing


def offset_label(offset_left: float) -> str:
    """'CL', '10 Lt', '7.5 Rt' from an offset left (whole units bare)."""
    if abs(offset_left) < 1e-9:
        return "CL"
    return f"{abs(offset_left):g} {'Lt' if offset_left > 0 else 'Rt'}"


def _plane_cut(u, dist, z, t, trgb):
    """Segments where triangles cross dist = 0, as ((u, z), (u, z)) in
    metres along / unit elevations."""
    segs, rgbs = [], []
    for (a, b, c), rgb in zip(t, trgb):
        ds = (dist[a], dist[b], dist[c])
        if min(ds) > 0 or max(ds) < 0 or (min(ds) == 0 and max(ds) == 0):
            continue
        pts = []
        for i, j in ((a, b), (b, c), (c, a)):
            di, dj = dist[i], dist[j]
            if (di < 0) != (dj < 0) or di == 0:
                if di == dj:
                    continue
                w = di / (di - dj) if di != dj else 0.0
                pts.append((u[i] + w * (u[j] - u[i]), z[i] + w * (z[j] - z[i])))
        pts = list(dict.fromkeys((round(p[0], 9), round(p[1], 9)) for p in pts))
        if len(pts) == 2:
            segs.append((pts[0], pts[1]))
            rgbs.append(tuple(rgb))
    return segs, rgbs


def _clip_segments_x(segs, x0, x1):
    out = []
    for (ax, ay), (bx, by) in segs:
        if max(ax, bx) < x0 or min(ax, bx) > x1:
            continue
        if ax != bx:
            ta, tb = sorted(((x0 - ax) / (bx - ax), (x1 - ax) / (bx - ax)))
            ta, tb = max(0.0, ta), min(1.0, tb)
            if ta >= tb:
                continue
            a = (ax + ta * (bx - ax), ay + ta * (by - ay))
            b = (ax + tb * (bx - ax), ay + tb * (by - ay))
        else:
            a, b = (ax, ay), (bx, by)
        out.append((a, b))
    return out


def _polygons(segs, x0, x1):
    """Closed rings (outer CCW, holes CW) of the cut segments, clipped to
    the view's x0..x1."""
    from shapely.geometry import LineString, Polygon, box
    from shapely.geometry.polygon import orient
    from shapely.ops import polygonize, unary_union
    lines = unary_union([LineString([a, b]) for a, b in segs if a != b])
    polys = [p for p in polygonize(lines) if p.area > 1e-8]
    if not polys:
        return []
    merged = unary_union(polys)
    ys = [c[1] for a, b in segs for c in (a, b)]
    merged = merged.intersection(box(x0, min(ys) - 1.0, x1, max(ys) + 1.0))
    out = []
    for p in getattr(merged, "geoms", [merged]):
        if not isinstance(p, Polygon) or p.is_empty or p.area <= 1e-8:
            continue                  # clipped away: outside the view
        p = orient(p, 1.0)
        out.append([list(p.exterior.coords)] + [list(i.coords) for i in p.interiors])
    return out


def _chain(segs):
    """Polylines through the segments (a ground line along the face)."""
    from shapely.geometry import LineString, MultiLineString
    from shapely.ops import linemerge, unary_union
    u = unary_union([LineString([a, b]) for a, b in segs if a != b])
    merged = linemerge(u) if isinstance(u, MultiLineString) else u
    geoms = merged.geoms if isinstance(merged, MultiLineString) else [merged]
    return [list(g.coords) for g in geoms]


def _visible_edges(warped, to2d, drawing, view, depth_u, k):
    """Visible feature edges between the cut and `depth`: a depth buffer
    over the drawing, then each edge sampled and kept where it is in front."""
    import numpy as np
    L = drawing.length
    tris2d, depths, edges = [], [], []
    for name, layer, surface, u, dist, z, t, trgb, inside in warped:
        x, y = to2d(np.asarray(u), np.asarray(z))
        dd = dist * k
        for a, b, c in t:
            ds = (dd[a], dd[b], dd[c])
            if max(ds) < 0 or min(ds) > depth_u:
                continue
            for poly in _clip_tri([(x[a], y[a], dd[a]), (x[b], y[b], dd[b]),
                                   (x[c], y[c], dd[c])], depth_u):
                tris2d.append(poly)
        if not surface:
            edges += _feature_edges(x, y, dd, t)
    if not tris2d:
        return []
    ys = [p[1] for tri in tris2d for p in tri]
    y0, y1 = min(ys), max(ys)
    # the cell: 0.02" on the plotted sheet at the view's scale - finer than a
    # plotted line weight, so a hidden-line decision never shows - else
    # 1/1500 of the view
    res = view.resolution or (0.02 * view.scale if view.scale
                              else max(L, (y1 - y0)) / 1500.0)
    nx = int(math.ceil(L / res)) + 1
    ny = int(math.ceil((y1 - y0) / res)) + 1
    zbuf = np.full((ny, nx), np.inf)
    for tri in tris2d:
        _raster(zbuf, tri, res, y0)
    _raster_cut(zbuf, drawing.cut, res, y0)
    tol = 2.0 * res + 1e-6
    out = []
    for (p, q) in edges:
        (px, py, pd), (qx, qy, qd) = p, q
        # clip the edge to the drawing and the depth band
        n = max(2, int(math.hypot(qx - px, qy - py) / (0.5 * res)) + 1)
        ts = np.linspace(0.0, 1.0, n)
        xs, ys_, ds = px + ts * (qx - px), py + ts * (qy - py), pd + ts * (qd - pd)
        ok = (xs >= 0) & (xs <= L) & (ds >= -1e-9) & (ds <= depth_u)
        ix = np.clip(((xs) / res).astype(int), 0, nx - 1)
        iy = np.clip(((ys_ - y0) / res).astype(int), 0, ny - 1)
        near = np.min(np.stack([zbuf[np.clip(iy + dy, 0, ny - 1),
                                     np.clip(ix + dx, 0, nx - 1)]
                                for dy in (-1, 0, 1) for dx in (-1, 0, 1)]), axis=0)
        vis = ok & (ds <= near + tol)
        # runs of visible samples -> segments
        i = 0
        while i < n:
            if not vis[i]:
                i += 1
                continue
            j = i
            while j + 1 < n and vis[j + 1]:
                j += 1
            if j > i:
                out.append(((float(xs[i]), float(ys_[i])), (float(xs[j]), float(ys_[j]))))
            i = j + 1
    return _merge_runs(out, res)


def _merge_runs(segs, res):
    """Visible pieces joined into polylines, collinear vertices dropped."""
    from shapely.geometry import LineString, MultiLineString
    from shapely.ops import linemerge
    if not segs:
        return []
    q = lambda p: (round(p[0] / (res * 0.05)) * res * 0.05,  # noqa: E731
                   round(p[1] / (res * 0.05)) * res * 0.05)
    lines = [LineString([q(a), q(b)]) for a, b in segs if q(a) != q(b)]
    if not lines:
        return []
    m = linemerge(MultiLineString(lines))
    geoms = m.geoms if isinstance(m, MultiLineString) else [m]
    return [list(g.simplify(res * 0.05).coords) for g in geoms]


def _raster_cut(zbuf, cut, res, y0) -> None:
    """The cut faces into the depth buffer at depth 0 (holes left open), so
    what lies behind a filled cut is hidden by it - the cut is a face, not
    the open edge of a clipped solid."""
    import numpy as np
    import shapely
    from shapely.geometry import Polygon
    ny, nx = zbuf.shape
    for _layer, _rgb, rings in cut:
        for ring in rings:
            if not ring or len(ring[0]) < 3:
                continue
            poly = Polygon(ring[0], [h for h in ring[1:] if len(h) >= 3])
            if poly.is_empty:
                continue
            a, b, c, d = poly.bounds
            i0, i1 = max(0, int(a / res)), min(nx - 1, int(math.ceil(c / res)))
            j0 = max(0, int((b - y0) / res))
            j1 = min(ny - 1, int(math.ceil((d - y0) / res)))
            if i1 < i0 or j1 < j0:
                continue
            X, Y = np.meshgrid((np.arange(i0, i1 + 1) + 0.5) * res,
                               (np.arange(j0, j1 + 1) + 0.5) * res + y0)
            inside = shapely.contains_xy(poly, X, Y)
            sub = zbuf[j0:j1 + 1, i0:i1 + 1]
            sub[inside] = np.minimum(sub[inside], 0.0)


def _clip_tri(poly, depth):
    """Triangle (x, y, depth) clipped to 0 <= depth <= `depth`: fan
    triangles of what is left."""
    def clip(pts, keep, edge):
        out = []
        for i, a in enumerate(pts):
            b = pts[(i + 1) % len(pts)]
            ka, kb = keep(a), keep(b)
            if ka:
                out.append(a)
            if ka != kb:
                w = (edge - a[2]) / (b[2] - a[2])
                out.append(tuple(a[j] + w * (b[j] - a[j]) for j in range(3)))
        return out
    pts = clip(poly, lambda p: p[2] >= 0.0, 0.0)
    if len(pts) >= 3:
        pts = clip(pts, lambda p: p[2] <= depth, depth)
    if len(pts) < 3:
        return []
    return [(pts[0], pts[i], pts[i + 1]) for i in range(1, len(pts) - 1)]


def _raster(zbuf, tri, res, y0):
    import numpy as np
    (ax, ay, ad), (bx, by, bd), (cx, cy, cd) = tri
    ny, nx = zbuf.shape
    i0 = max(0, int(math.floor(min(ax, bx, cx) / res)))
    i1 = min(nx - 1, int(math.ceil(max(ax, bx, cx) / res)))
    j0 = max(0, int(math.floor((min(ay, by, cy) - y0) / res)))
    j1 = min(ny - 1, int(math.ceil((max(ay, by, cy) - y0) / res)))
    if i1 < i0 or j1 < j0:
        return
    det = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    if abs(det) < 1e-14:
        return
    xs = (np.arange(i0, i1 + 1) + 0.5) * res
    ys = (np.arange(j0, j1 + 1) + 0.5) * res + y0
    X, Y = np.meshgrid(xs, ys)
    l1 = ((by - cy) * (X - cx) + (cx - bx) * (Y - cy)) / det
    l2 = ((cy - ay) * (X - cx) + (ax - cx) * (Y - cy)) / det
    l3 = 1.0 - l1 - l2
    eps = -1e-9
    m = (l1 >= eps) & (l2 >= eps) & (l3 >= eps)
    if not m.any():
        return
    d = l1 * ad + l2 * bd + l3 * cd
    sub = zbuf[j0:j1 + 1, i0:i1 + 1]
    upd = m & (d < sub)
    sub[upd] = d[upd]


def _feature_edges(x, y, dd, t, angle_deg: float = 20.0):
    """Edges between faces turning more than `angle_deg` (or open edges),
    in the drawing frame with their depth: [((x, y, d), (x, y, d))]."""
    import numpy as np
    P = np.stack([x, y, dd], axis=1)
    n = np.cross(P[t[:, 1]] - P[t[:, 0]], P[t[:, 2]] - P[t[:, 0]])
    ln = np.linalg.norm(n, axis=1)
    ln[ln == 0] = 1.0
    n = n / ln[:, None]
    by_edge: dict = {}
    for fi, (a, b, c) in enumerate(t):
        for e in ((a, b), (b, c), (c, a)):
            key = (min(e), max(e))
            by_edge.setdefault(key, []).append(fi)
    cosmax = math.cos(math.radians(angle_deg))
    out = []
    for (a, b), fs in by_edge.items():
        if len(fs) == 2 and float(np.dot(n[fs[0]], n[fs[1]])) > cosmax:
            continue
        out.append((tuple(P[a]), tuple(P[b])))
    return out


def _ticks(st, un, view, d0, d1, to2d, unit, k):
    """(x, station) at every whole station unit inside the view; the sheet
    writer picks the ones its scale has room for."""
    out = []
    to_m = 1.0 / k
    s = math.ceil(view.from_station - 1e-9)
    while s <= view.to_station + 1e-9:
        d = st.distance_at(s * to_m / st.unit_scale)
        x, _ = to2d(float(un.u_of(d)), 0.0)
        out.append((float(x), float(s)))
        s += 1.0
    return out


# ------------------------------------------------------------------ sheets
@dataclass
class Sheet:
    """A paper sheet (inches): size, margin, title band."""
    width: float = 34.0
    height: float = 22.0
    margin: float = 1.0
    title_band: float = 1.5


SCALES = (1, 2, 4, 5, 8, 10, 20, 30, 40, 50, 60, 100, 200, 400, 500, 1000)


def fit_scale(drawing: Drawing, sheet: Sheet) -> float:
    """The smallest standard scale (units per paper inch) the view fits at."""
    x0, y0, x1, y1 = drawing.extent
    w = sheet.width - 2 * sheet.margin
    h = sheet.height - 2 * sheet.margin - sheet.title_band
    need = max((x1 - x0) / w, (y1 - y0 + 4.0) / h)
    return next((s for s in SCALES if s >= need), SCALES[-1])


def write_dxf(drawings: list, path: str, sheet: Sheet | None = None) -> list[str]:
    """One DXF: each view drawn in model space (stacked), and a paper-space
    layout per view with a viewport at its scale and a title. Returns one
    report line per sheet."""
    import ezdxf
    from ezdxf import colors
    from ezdxf.enums import TextEntityAlignment
    sheet = sheet or Sheet()
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 2 if drawings and drawings[0].unit == "ft" else 6
    msp = doc.modelspace()
    for name, color in (("E-BEYOND", 7), ("E-GRID", 8), ("E-TEXT", 7)):
        if name not in doc.layers:
            doc.layers.add(name, color=color)
    report = []
    y_cursor = 0.0
    for n, dr in enumerate(drawings):
        v = dr.view
        x0, y0, x1, y1 = dr.extent
        # each view far below the last, so no sheet's viewport frames another
        oy = y_cursor - y0
        y_cursor = oy + y1 + 2.0 * sheet.height * (v.scale or fit_scale(dr, sheet))
        dy = lambda p: (p[0], p[1] + oy)            # noqa: E731
        scale = v.scale or fit_scale(dr, sheet)
        for layer, rgb, rings in dr.cut:
            _cut_to_dxf(doc, msp, layer, rgb, rings, dy, scale)
        for layer, rgb, line in dr.ground:
            if layer not in doc.layers:
                doc.layers.add(layer).rgb = tuple(int(c * 255) for c in rgb)
            msp.add_lwpolyline([dy(p) for p in line],
                               dxfattribs={"layer": layer, "lineweight": 35})
        for line in dr.beyond:
            msp.add_lwpolyline([dy(p) for p in line],
                               dxfattribs={"layer": "E-BEYOND", "lineweight": 18})
        if dr.limits and LIMIT_LAYER not in doc.layers:
            lay = doc.layers.add(LIMIT_LAYER, color=30, linetype="DASHED")
            lay.description = "Limit of excavation (pay line)"
        for line in dr.limits:
            msp.add_lwpolyline([dy(p) for p in line],
                               dxfattribs={"layer": LIMIT_LAYER, "lineweight": 25,
                                           "linetype": "DASHED"})
        th = 0.10 * scale                            # 0.10" text on the sheet
        # labelled ticks at least an inch apart on the sheet, minor ones between
        from .alignment_station import format_station
        major = next((st_ for st_ in (1, 2, 5, 10, 20, 25, 50, 100, 200, 500, 1000,
                                      2000, 5000) if st_ >= scale), 10000)
        minor = next(m for m in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000)
                     if m >= scale / 4.0)
        for x, sta in dr.ticks:
            if abs(sta / minor - round(sta / minor)) > 1e-6:
                continue
            is_major = abs(sta / major - round(sta / major)) < 1e-6
            msp.add_line((x, y0 + oy - (th if is_major else th / 2)), (x, y0 + oy),
                         dxfattribs={"layer": "E-GRID"})
            if is_major:
                label = (offset_label(sta) if dr.tick_kind == "offset"
                         else format_station(sta, dr.unit, 0))
                msp.add_text(label, height=th,
                             dxfattribs={"layer": "E-TEXT"}).set_placement(
                    (x, y0 + oy - 2.5 * th), align=TextEntityAlignment.TOP_CENTER)
        ystep = _nice(max((y1 - y0) / 6.0, 3.0 * th))
        e = math.floor(y0 / ystep) * ystep
        while e <= y1 + 1e-9:
            msp.add_line((0.0, e + oy), (dr.length, e + oy),
                         dxfattribs={"layer": "E-GRID", "linetype": "DASHED"})
            msp.add_text(f"El {e / v.exaggeration:.2f}", height=th * 0.8,
                         dxfattribs={"layer": "E-TEXT"}).set_placement(
                (-th, e + oy), align=TextEntityAlignment.MIDDLE_RIGHT)
            e += ystep
        sec_title = (f"{v.name}: SECTION AT STA {format_station(v.station, dr.unit)}, "
                     f"LOOKING {'BACK' if v.look_back else 'AHEAD'}"
                     if isinstance(v, SectionView) else None)
        title = v.title or sec_title or (
            f"{v.name}: DEVELOPED ELEVATION {v.offset:.2f} {v.side.upper()}, "
            f"LOOKING {'RIGHT' if v.look_from.lower().startswith('l') else 'LEFT'}"
            f"{'' if v.true_view else ' (MIRRORED: STATIONS LEFT TO RIGHT)'}")
        lay = doc.layouts.new(f"{n + 1:02d} {v.name}"[:31])
        lay.page_setup(size=(sheet.width, sheet.height), margins=(0, 0, 0, 0),
                       units="inch")
        vw = sheet.width - 2 * sheet.margin
        vh = sheet.height - 2 * sheet.margin - sheet.title_band
        cx, cy = sheet.width / 2, sheet.margin + sheet.title_band + vh / 2
        lay.add_viewport(center=(cx, cy), size=(vw, vh),
                         view_center_point=((x0 + x1) / 2, (y0 + y1) / 2 + oy - th),
                         view_height=vh * scale)
        lay.add_lwpolyline([(sheet.margin, sheet.margin),
                            (sheet.width - sheet.margin, sheet.margin),
                            (sheet.width - sheet.margin, sheet.height - sheet.margin),
                            (sheet.margin, sheet.height - sheet.margin)], close=True)
        unit_txt = "'" if dr.unit == "ft" else " m"
        lay.add_text(title, height=0.25).set_placement(
            (sheet.margin + 0.3, sheet.margin + 0.9))
        lay.add_text(f'SCALE 1" = {scale:g}{unit_txt}'
                     + (f"   VERT x{v.exaggeration:g}" if v.exaggeration != 1 else "")
                     + (f"   AS OF {v.date}" if v.date else ""),
                     height=0.16).set_placement((sheet.margin + 0.3, sheet.margin + 0.45))
        fits = (x1 - x0) / scale <= vw + 1e-6 and (y1 - y0) / scale <= vh + 1e-6
        span = (f"section at {format_station(v.station, dr.unit)}, {dr.length:.2f} wide"
                if isinstance(v, SectionView) else
                f"{v.from_station:.2f} to {v.to_station:.2f}, {dr.length:.2f} along the line")
        report.append(f"{lay.name}: {span}, 1\" = {scale:g}"
                      + ("" if fits else "  (DOES NOT FIT the sheet at this scale)"))
    _ = colors
    if drawings and "Layout1" in doc.layouts:
        doc.layouts.delete("Layout1")             # ezdxf's empty default sheet
    doc.saveas(path)
    return report


def _cut_to_dxf(doc, msp, layer, rgb, rings, dy, scale) -> None:
    """One material's cut: a solid fill in its colour on `layer` (a colour
    plot; freeze it for black and white), its hatch pattern in ink on
    `layer`-PATT (bimforge.bim.section_style: concrete stipple, earth, fill,
    gravel ...) with the heavy cut outline, so freezing the colour layers
    leaves a black-and-white section. Rebar plots solid, and a bar
    smaller than MIN_DOT_IN on paper as a dot that size."""
    from .section_style import MIN_DOT_IN, hatch_scale, style_of
    kind = style_of(layer.replace("E-CUT-", ""))
    col = tuple(int(c * 255) for c in rgb)
    patt = f"{layer}-PATT"
    for name, colour in ((layer, col), (patt, None)):
        if name not in doc.layers:
            lay = doc.layers.add(name, color=7)
            if colour:
                lay.rgb = colour
    rebar = kind is not None and kind.dxf == "SOLID"
    r_min = MIN_DOT_IN / 2.0 * scale
    for ring in rings:
        if not ring or len(ring[0]) < 3:
            continue
        outer = [dy(p) for p in ring[0]]
        h = msp.add_hatch(dxfattribs={"layer": layer})
        h.rgb = col
        h.paths.add_polyline_path(outer, is_closed=True)
        for hole in ring[1:]:
            h.paths.add_polyline_path([dy(p) for p in hole], is_closed=True)
        if rebar:
            _area, cx, cy = _ring_centroid(outer)
            ink = msp.add_hatch(color=7, dxfattribs={"layer": patt})
            # a dot only when the whole cut fits inside it (a long thin bar
            # keeps its length and outline), as the Blender add-on's _dot
            if max(math.hypot(x - cx, y - cy) for x, y in outer) < r_min:
                ink.paths.add_edge_path().add_arc((cx, cy), r_min, 0.0, 360.0)
                continue                      # the dot is the bar: no outline
            ink.paths.add_polyline_path(outer, is_closed=True)
        elif kind is not None:
            ink = msp.add_hatch(color=7, dxfattribs={"layer": patt,
                                                     "lineweight": 9})
            ink.set_pattern_fill(kind.dxf, scale=hatch_scale(kind, scale))
            ink.paths.add_polyline_path(outer, is_closed=True)
            for hole in ring[1:]:
                ink.paths.add_polyline_path([dy(p) for p in hole], is_closed=True)
        for loop in ring:               # on the ink layer: kept in B/W
            msp.add_lwpolyline([dy(p) for p in loop], close=True,
                               dxfattribs={"layer": patt, "color": 7,
                                           "lineweight": 50})


def _ring_centroid(pts):
    """(signed area, cx, cy) of a closed ring."""
    a = cx = cy = 0.0
    n = len(pts)
    for i in range(n):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        c = x0 * y1 - x1 * y0
        a += c
        cx += (x0 + x1) * c
        cy += (y0 + y1) * c
    a *= 0.5
    if abs(a) < 1e-18:
        xs, ys = zip(*pts)
        return 0.0, sum(xs) / n, sum(ys) / n
    return a, cx / (6 * a), cy / (6 * a)


def _nice(x: float) -> float:
    if x <= 0:
        return 1.0
    p = 10 ** math.floor(math.log10(x))
    return next(m * p for m in (1, 2, 5, 10) if m * p >= x)


# --------------------------------------------------------------- sheet sets
def load_set(path) -> tuple[str, list[ElevationView], Sheet, str]:
    """(ifc path, views, sheet, dxf path) from a developed-elevation set:

        ifc: ../out/combined.4d.ifc
        out: ../out/wall-developed.dxf
        alignment: ML                      # default: the first
        offset: 23.0                       # defaults every view takes
        side: Lt
        look_from: left
        depth: 15
        date: 2027-09-21                   # optional: as built that day
        sheet: {width: 34, height: 22}
        views:
          - {name: OVERALL, from: 547+40, to: 547+80}    # scale fitted
        segments:                          # optional: enlarged pieces of
          from: 547+40                     # a range, each its own sheet
          to: 547+80
          length: 10                       # along the stations
          overlap: 1
          scale: 5
          name: SEGMENT
    """
    from pathlib import Path

    import yaml
    p = Path(path)
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    base = p.parent
    keys = ("offset", "side", "look_from", "depth", "alignment", "exaggeration",
            "true_view", "date", "resolution")
    defaults = {k: doc[k] for k in keys if k in doc}
    if "date" in defaults:
        defaults["date"] = str(defaults["date"])
    views = []
    for v in doc.get("views") or []:
        kw = dict(defaults, **{k: v[k] for k in keys if k in v})
        if "date" in kw:
            kw["date"] = str(kw["date"])
        views.append(ElevationView(name=str(v["name"]),
                                   from_station=parse_station(v["from"]),
                                   to_station=parse_station(v["to"]),
                                   scale=v.get("scale"), title=v.get("title"), **kw))
    seg = doc.get("segments")
    if seg:
        a, b = parse_station(seg["from"]), parse_station(seg["to"])
        L, ov = float(seg["length"]), float(seg.get("overlap", 0.0))
        if L <= ov:
            raise ValueError("segments: length must exceed overlap")
        i, s = 1, a
        while s < b - 1e-9:
            e = min(b, s + L)
            views.append(ElevationView(
                name=f"{seg.get('name', 'SEGMENT')} {i}", from_station=s, to_station=e,
                scale=seg.get("scale"), **defaults))
            i += 1
            s = e - ov if e < b else b
    if not views:
        raise ValueError(f"{p.name}: no views (views: / segments:)")
    sh = Sheet(**(doc.get("sheet") or {}))
    return (str((base / doc["ifc"]).resolve()), views, sh,
            str((base / doc.get("out", p.with_suffix(".dxf").name)).resolve()))
