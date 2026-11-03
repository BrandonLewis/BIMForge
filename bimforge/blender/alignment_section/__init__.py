"""Alignment Section — a Blender add-on: slide a cross-section along an IFC
alignment.

View3D > Sidebar (N) > Section. Pick the IFC (the one Bonsai has open, or a
file on disk), pick an IfcAlignment, and drag the station slider. At each
station the add-on:

* stands a section plane square to the alignment (vertical, normal to the
  PLAN tangent: a highway cross-section, not a cut normal to the grade);
* aims an orthographic "Section Camera" down the alignment, its near clip on
  the plane, so View Section shows exactly what lies beyond the cut;
* cuts every mesh in the scene (or one collection) at the plane and fills
  the cut faces into "Section Cut", each per its own styling — concrete as
  concrete, rebar, asphalt, gravel — from the item's material (Bonsai's
  IfcSurfaceStyle), else from what its name says it is;
* reports station, elevation of the grade line, grade and bearing;
* slides by STATION (a slider from the first station to the last, in the
  display unit) and by OFFSET (a slider across the view, Lt to Rt, that
  carries the 3D cursor and reads the surface as it moves);
* shows the model as it stands on a date of the IFC's 4D schedule (what is
  not yet built, or already removed, is hidden and not cut);
* draws an offset ruler (CL, 10' Lt, 10' Rt, ...) across the section, puts
  the 3D cursor at a station + offset Lt/Rt and reads the top surface
  there, and inquires the cursor back to station + offset.

Export Section DXF writes what the section camera shows (the station,
width, depth and look) to a DXF sheet; Exit leaves the camera view, and the
developed-elevation scene, back to the model.

The slider can follow the timeline, so scrubbing frames sweeps the section
along the alignment (and rendering the frames makes a fly-through).

Stationing comes from bimforge.bim.alignment_station, which this add-on
carries as its own copy (`python -m bimforge.blender` builds the zip). It
needs ifcopenshell inside Blender: Bonsai provides it.
"""
from __future__ import annotations

import math

bl_info = {
    "name": "Alignment Section (bimforge)",
    "author": "bimforge",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Section",
    "description": "Station slider that cuts a section along an IFC alignment",
    "category": "3D View",
}

try:                                    # the add-on zip carries its own copy
    from . import alignment_station as _st
    from . import developed as _dev
    from . import schedule_state as _ss
    from . import section_style as _sty
except ImportError:                     # running from the bimforge package
    from bimforge.bim import alignment_station as _st
    from bimforge.bim import developed as _dev
    from bimforge.bim import schedule_state as _ss
    from bimforge.bim import section_style as _sty

try:
    import bpy
except ImportError:                     # imported outside Blender (packaging)
    bpy = None

COLL = "Alignment Section"
CAM, PLANE, CUT, AXIS = ("Section Camera", "Section Plane", "Section Cut",
                         "Alignment Axis")
CAM_BACK = 1.0          # m: camera sits this far behind the plane
NEAR_GAP = 0.002        # m: near clip this far in front of the plane

# Live state that cannot sit in bpy properties: the open file, the
# stationers, the last frame. Rebuilt on demand after a reload.
_STATE: dict = {"key": None, "file": None, "stationers": [], "frame": None,
                "error": "", "point": None, "spans": {}, "events": [],
                "hidden": set(), "counts": None}
_ENUM_CACHE: list = []
_DRAW_HANDLE = None


# ---------------------------------------------------------------- sources
def _bonsai_file():
    import importlib
    for mod, get in (("bonsai.tool", lambda m: m.Ifc.get()),
                     ("bonsai.bim.ifc", lambda m: m.IfcStore.get_file()),
                     ("blenderbim.tool", lambda m: m.Ifc.get()),
                     ("blenderbim.bim.ifc", lambda m: m.IfcStore.get_file())):
        try:
            f = get(importlib.import_module(mod))
        except Exception:
            continue
        if f is not None:
            return f
    return None


def _open(props):
    """(file, stationers) for the current source, cached; raises on error."""
    if props.source == "BONSAI":
        f = _bonsai_file()
        if f is None:
            raise RuntimeError("Bonsai has no IFC open")
        key = ("BONSAI", id(f))
    else:
        path = bpy.path.abspath(props.ifc_path)
        if not path:
            raise RuntimeError("choose an IFC file")
        key = ("FILE", path)
        f = None
    if _STATE["key"] != key:
        if f is None:
            import ifcopenshell
            f = ifcopenshell.open(path)
        stationers = [_st.AlignmentStationer(f, a) for a in _st.alignments(f)]
        if not stationers:
            raise RuntimeError(f"no IFC4X3 IfcAlignment with a curve "
                               f"(schema {f.schema})")
        spans = _ss.element_spans(f)
        _STATE.update(key=key, file=f, stationers=stationers, frame=None,
                      error="", spans=spans, events=_ss.event_days(spans),
                      counts=None)
    return _STATE["file"], _STATE["stationers"]


def _stationer(props):
    try:
        _f, sts = _open(props)
    except Exception as exc:            # surfaced in the panel, not a crash
        _STATE["error"] = str(exc)
        return None
    i = min(int(props.alignment or 0), len(sts) - 1)
    return sts[i]


def _alignment_items(self, context):
    _ENUM_CACHE.clear()
    for i, st in enumerate(_STATE["stationers"]):
        _ENUM_CACHE.append((str(i), st.name,
                            f"{st.format_station(st.start_station)} to "
                            f"{st.format_station(st.end_station)}"))
    if not _ENUM_CACHE:
        _ENUM_CACHE.append(("0", "(load an IFC)", ""))
    return _ENUM_CACHE


def _unit(props, st) -> str:
    return st.station_unit if props.units == "AUTO" else props.units.lower()


# ---------------------------------------------------------------- objects
def _collection(scene):
    coll = bpy.data.collections.get(COLL)
    if coll is None:
        coll = bpy.data.collections.new(COLL)
    if coll.name not in scene.collection.children:
        scene.collection.children.link(coll)
    return coll


def _obj(scene, name, data_fn):
    ob = bpy.data.objects.get(name)
    if ob is None:
        ob = bpy.data.objects.new(name, data_fn())
    coll = _collection(scene)
    if ob.name not in coll.objects:
        coll.objects.link(ob)
    return ob


def _cut_material():
    mat = bpy.data.materials.get("Section Cut")
    if mat is None:
        mat = bpy.data.materials.new("Section Cut")
        mat.diffuse_color = (0.95, 0.25, 0.10, 1.0)
    return mat


#: Section fill by what the thing IS, for a cut item whose own styling says
#: nothing (no material, or Blender's / ifcopenshell's default 0.8 grey):
#: bimforge.bim.section_style, shared with the DXF sheets. (kind, regex, rgb)
FILL_PALETTE: list[tuple[str, str, tuple]] = [(k.kind, k.pattern, k.rgb)
                                              for k in _sty.KINDS]
UNSTYLED = _sty.UNSTYLED
_DEFAULT_GREY = (0.8, 0.8, 0.8)
classify = _sty.classify
#: section ink: the hatch's colour, this fraction of the fill's
INK = 0.30
PERIOD_NODE = "BIMForge hatch period"


def _styled_rgb(mat):
    """The colour a material's styling gives, or None when it is the
    unstyled default. Bonsai writes the IfcSurfaceStyle colour into both
    the viewport colour and the Principled base colour; either will do."""
    if mat is None:
        return None
    rgb = tuple(mat.diffuse_color[:3])
    if any(abs(c - d) > 1e-3 for c, d in zip(rgb, _DEFAULT_GREY)):
        return rgb
    bsdf = _principled(mat)
    if bsdf is not None:
        base = tuple(bsdf.inputs["Base Color"].default_value[:3])
        if any(abs(c - d) > 1e-3 for c, d in zip(base, _DEFAULT_GREY)):
            return base
    return None


def _principled(mat):
    tree = getattr(mat, "node_tree", None)
    if tree is None:
        return None
    return next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)


def fill_for(mat, ob) -> tuple[str, tuple]:
    """(name, rgb) of the section fill for faces of `ob` styled `mat`.

    The item's own styling first — its material's colour, which is its
    IfcSurfaceStyle when Bonsai loaded it — then what its material or
    object name says it is, then a neutral grey.
    """
    rgb = _styled_rgb(mat)
    if rgb is not None:
        return mat.name, rgb
    hit = classify(mat.name if mat else "", ob.name)
    return hit if hit is not None else UNSTYLED


def _section_material(name: str, rgb, paint: str | None = None,
                      prefix: str = "Section") -> "bpy.types.Material":
    """An opaque section fill in `rgb` (opaque even when the source is
    see-through, like earthwork: a cut face is solid). UNLIT - an emission,
    so the viewport light never tints it - with the kind's hatch inked over
    it (bimforge.bim.section_style; `paint` overrides, "" is flat). Solid
    mode shows the flat colour; Material Preview and Rendered the hatch."""
    k = _sty.style_of(name)
    own = k.paint if k else ""
    if paint is None:
        paint = own
    # a view's own materials (the developed scene keeps its hatch size);
    # a paint the name would not give gets its own material
    key = f"{prefix} · {name}" + ("" if paint == own else f" [{paint}]")
    mat = bpy.data.materials.get(key)
    if mat is None:
        mat = bpy.data.materials.new(key)
    if getattr(mat, "node_tree", None) is None:
        mat.use_nodes = True
    mat.diffuse_color = (*rgb, 1.0)
    sig = f"{paint} {rgb[0]:.4f} {rgb[1]:.4f} {rgb[2]:.4f}"
    if mat.get("bimforge_paint") != sig:
        _paint(mat, tuple(rgb), paint)
        mat["bimforge_paint"] = sig
    return mat


def _linear(rgb) -> tuple:
    """sRGB (what an IFC colour and a DXF fill are) to Blender's linear
    scene colour, so a fill shows the colour the style names, not a paler
    one."""
    return tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
                 for c in rgb)


def _paint(mat, rgb, paint: str) -> None:
    """Emission in `rgb`, mixed toward ink where the procedural hatch
    `paint` is. The hatch is laid out in CAMERA space, every
    `PERIOD_NODE` metres (set to the view's width by set_hatch_period), so it
    reads at one size on screen like a hatch on paper."""
    rgb = _linear(rgb)
    nt = mat.node_tree
    N, L = nt.nodes, nt.links
    N.clear()
    out = N.new("ShaderNodeOutputMaterial")
    emit = N.new("ShaderNodeEmission")
    L.new(emit.outputs["Emission"], out.inputs["Surface"])
    if paint in ("", "solid"):
        emit.inputs["Color"].default_value = (*rgb, 1.0)
        return
    period = N.new("ShaderNodeValue")
    period.name = period.label = PERIOD_NODE
    period.outputs[0].default_value = 0.3
    tc = N.new("ShaderNodeTexCoord")
    sep = N.new("ShaderNodeSeparateXYZ")
    L.new(tc.outputs["Camera"], sep.inputs[0])

    def math(op, a, b=None):
        n = N.new("ShaderNodeMath")
        n.operation = op
        for i, x in enumerate((a, b)):
            if x is None:
                continue
            if isinstance(x, (int, float)):
                n.inputs[i].default_value = float(x)
            else:
                L.new(x, n.inputs[i])
        return n.outputs[0]
    u = math("DIVIDE", sep.outputs["X"], period.outputs[0])
    v = math("DIVIDE", sep.outputs["Y"], period.outputs[0])

    def lines(a, b, spacing, width):
        """Ink on lines u*a + v*b = n * spacing, `width` of a spacing."""
        t = math("ADD", math("MULTIPLY", u, a), math("MULTIPLY", v, b))
        return math("LESS_THAN", math("FRACT", math("DIVIDE", t, spacing)), width)

    def voronoi(scale, feature, below):
        cv = N.new("ShaderNodeCombineXYZ")
        L.new(u, cv.inputs["X"])
        L.new(v, cv.inputs["Y"])
        vo = N.new("ShaderNodeTexVoronoi")
        vo.voronoi_dimensions = "2D"
        vo.feature = feature
        vo.inputs["Scale"].default_value = scale
        L.new(cv.outputs[0], vo.inputs["Vector"])
        return math("LESS_THAN", vo.outputs["Distance"], below)
    if paint == "lines":
        f = lines(1.0, 1.0, 1.0, 0.12)
    elif paint == "cross":
        f = math("MAXIMUM", lines(1.0, 1.0, 1.0, 0.10), lines(1.0, -1.0, 1.0, 0.10))
    elif paint == "earth":       # sparse crossed lines, heavier one way
        f = math("MAXIMUM", lines(1.0, 1.0, 2.0, 0.07), lines(1.0, -1.0, 4.0, 0.04))
    elif paint == "stipple":     # aggregate: scattered dots, a few large
        f = math("MAXIMUM", voronoi(1.6, "F1", 0.10), voronoi(0.45, "F1", 0.09))
    elif paint == "sand":
        f = voronoi(1.3, "F1", 0.13)
    elif paint == "gravel":
        f = voronoi(0.8, "DISTANCE_TO_EDGE", 0.05)
    else:
        f = None
    if f is None:
        emit.inputs["Color"].default_value = (*rgb, 1.0)
        return
    mix = N.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    L.new(f, mix.inputs["Factor"])
    a_col = next(i for i in mix.inputs if i.identifier == "A_Color")
    b_col = next(i for i in mix.inputs if i.identifier == "B_Color")
    a_col.default_value = (*rgb, 1.0)
    b_col.default_value = (*(c * INK for c in rgb), 1.0)
    res = next(o for o in mix.outputs if o.identifier == "Result_Color")
    L.new(res, emit.inputs["Color"])


def set_hatch_period(metres: float, prefix: str = "Section") -> None:
    """The hatches of one view's materials (`prefix`) repeat every
    `metres` (camera space); the other view's keep theirs."""
    for mat in bpy.data.materials:
        if mat.name.startswith(f"{prefix} · ") and mat.node_tree is not None:
            n = mat.node_tree.nodes.get(PERIOD_NODE)
            if n is not None:
                n.outputs[0].default_value = max(metres, 1e-4)


def _basis(fr, look_back):
    """Camera basis: -Z looks down the alignment, +Y is world up, +X is
    the alignment's right (looking ahead) — a section drawn as plans are."""
    from mathutils import Vector
    look = Vector(fr.plan_tangent) * (-1.0 if look_back else 1.0)
    up = Vector((0.0, 0.0, 1.0))
    z = -look
    x = up.cross(z)
    return x.normalized(), up, z.normalized(), look


def _matrix(x, y, z, loc):
    from mathutils import Matrix
    return Matrix(((x[0], y[0], z[0], loc[0]),
                   (x[1], y[1], z[1], loc[1]),
                   (x[2], y[2], z[2], loc[2]),
                   (0.0, 0.0, 0.0, 1.0)))


def build_axis(scene, props, st):
    """The alignment itself as a 3-D poly curve, so a misplaced model (a
    false origin, a wrong offset) is visible at a glance."""
    from mathutils import Vector
    off = Vector(props.shift)
    cu = bpy.data.curves.get(AXIS) or bpy.data.curves.new(AXIS, "CURVE")
    cu.dimensions = "3D"
    cu.splines.clear()
    pts = st.points(max(0.5, st.length / 2000.0))
    sp = cu.splines.new("POLY")
    sp.points.add(len(pts) - 1)
    for p, q in zip(sp.points, pts):
        v = Vector(q) + off
        p.co = (v.x, v.y, v.z, 1.0)
    ob = _obj(scene, AXIS, lambda: cu)
    ob.data = cu
    ob.hide_render = True
    return ob


def place(scene, props, st, fr):
    """Stand the plane and the camera at frame `fr`; cut if live."""
    from mathutils import Vector
    off = Vector(props.shift)
    p = Vector(fr.point) + off + Vector((0.0, 0.0, props.lift))
    x, y, z, look = _basis(fr, props.look == "BACK")

    plane = _obj(scene, PLANE, lambda: _plane_mesh())
    plane.display_type = "WIRE"
    plane.hide_render = True
    plane.show_in_front = True
    w = props.width
    plane.matrix_world = _matrix(x * (w / 2), y * (w * 0.3), z, p)

    cam = _obj(scene, CAM, lambda: bpy.data.cameras.new(CAM))
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = w
    cam.data.clip_start = CAM_BACK - NEAR_GAP
    cam.data.clip_end = CAM_BACK + props.depth
    cam.matrix_world = _matrix(x, y, z, p - look * CAM_BACK)
    if scene.camera is None:
        scene.camera = cam

    if props.live_cut:
        cut(scene, props, Vector(fr.point) + off, look)
    set_hatch_period(w / 120.0)
    ruler(scene, props, st, fr, look)
    _STATE["frame"] = fr
    _redraw()


RULER, LABEL = "Section Offsets", "Offset Label"


def _ruler_text(offset_left_m: float, unit: str, step: float,
                foot: float | None = None) -> str:
    v = abs(offset_left_m) / ((foot or _st.US_SURVEY_FT_M) if unit == "ft" else 1.0)
    if round(v, 6) == 0:
        return "CL"
    mark = "'" if unit == "ft" else " m"
    num = f"{v:.0f}" if abs(step - round(step)) < 1e-9 else f"{v:.2f}"
    return f"{num}{mark} {'Lt' if offset_left_m > 0 else 'Rt'}"


def ruler(scene, props, st, fr, look):
    """Offset ticks across the section: a line `ruler_height` above the
    grade point, a tick and a label every `ruler_step` Lt and Rt, and a CL
    drop to the grade line. Drawn in the cut plane, a hair toward the
    camera, so it shows in the section view and renders."""
    from mathutils import Vector
    old = [o for o in bpy.data.objects if o.name.startswith(LABEL)]
    if not props.ruler:
        for o in old + [bpy.data.objects.get(RULER)]:
            if o is not None:
                bpy.data.objects.remove(o)
        return
    u = _unit(props, st)
    step_m = st.from_unit(props.ruler_step, u)
    half = props.width / 2
    n = min(200, int(half // step_m))
    left = Vector(fr.left)
    up = Vector((0.0, 0.0, 1.0))
    base = (Vector(fr.point) + Vector(props.shift) - look * (NEAR_GAP * 0.9))
    top = base + up * props.ruler_height
    tick = props.width / 120
    verts = [top - left * (n * step_m), top + left * (n * step_m),
             base, top]                                   # line; CL drop
    edges = [(0, 1), (2, 3)]
    offs = [i * step_m for i in range(-n, n + 1)]
    for o in offs:
        a = top + left * o
        verts += [a, a - up * tick]
        edges.append((len(verts) - 2, len(verts) - 1))
    rob = _strip_mesh(scene, RULER, [(verts[a], verts[b]) for a, b in edges],
                      look, props.width / 1400, (0.04, 0.04, 0.05))
    rob.hide_render = False
    # labels: text objects facing the camera, reused across slides
    x, y, z, _look = _basis(fr, props.look == "BACK")
    size = props.width / 70
    mat = _section_material("Ruler", (0.05, 0.05, 0.06))
    for i, o in enumerate(offs):
        name = f"{LABEL} {i:03d}"
        cu = bpy.data.curves.get(name) or bpy.data.curves.new(name, "FONT")
        cu.body = _ruler_text(o, u, props.ruler_step, st.foot_m)
        cu.align_x = "CENTER"
        cu.size = size
        if not cu.materials:
            cu.materials.append(mat)
        ob = _obj(scene, name, lambda: cu)
        ob.data = cu
        ob.matrix_world = _matrix(x, y, z, top + left * o + up * (tick * 0.6))
    for o in old[len(offs):]:
        bpy.data.objects.remove(o)


def locate(scene, props, st, distance, offset_left):
    """Mark station + offset: the 3D cursor and a "Station Offset" empty at
    the grade elevation, and the top surface found straight below/above."""
    from mathutils import Vector
    p = Vector(st.point_at(distance, offset_left)) + Vector(props.shift)
    mark = _obj(scene, "Station Offset", lambda: None)
    mark.empty_display_type = "SPHERE"
    mark.empty_display_size = max(0.1, props.width / 150)
    mark.location = p
    scene.cursor.location = p
    hit = top_surface(scene, p.x, p.y)
    _STATE["point"] = (distance, offset_left, p.z, hit)
    _redraw()
    return _STATE["point"]


def top_surface(scene, x, y):
    """(z, object name) of the highest visible model surface at plan (x, y),
    or None. The add-on's own helpers are looked through."""
    from mathutils import Vector
    depsgraph = bpy.context.evaluated_depsgraph_get()
    helper = bpy.data.collections.get(COLL)
    skip = set(helper.all_objects) if helper else set()
    origin = Vector((x, y, 1.0e5))
    for _ in range(64):
        ok, loc, _n, _i, ob, _m = scene.ray_cast(depsgraph, origin,
                                                 Vector((0, 0, -1)))
        if not ok:
            return None
        if ob.original not in skip:
            return loc.z, ob.name
        origin = loc - Vector((0, 0, 1e-4))
    return None


def _plane_mesh():
    me = bpy.data.meshes.new(PLANE)
    me.from_pydata([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)],
                   [], [(0, 1, 2, 3)])
    return me


def _straddles(ob, co, no) -> bool:
    from mathutils import Vector
    mw = ob.matrix_world
    s = [(mw @ Vector(c) - co).dot(no) for c in ob.bound_box]
    return min(s) <= 0.0 <= max(s)


def cut(scene, props, co, look):
    """Bisect every candidate mesh at the plane (point `co`, normal `look`)
    into one "Section Cut" mesh: the cut edges, and faces filled from each
    object's closed loops.

    Each cut edge comes from a face; the fill takes that face's material, so
    a multi-material item fills each part per its styling (concrete as
    concrete, rebar as rebar, asphalt, gravel). Loops are filled per object
    AND per material, never across them. `fill_style` SINGLE fills
    everything in one colour instead.
    """
    import bmesh
    depsgraph = bpy.context.evaluated_depsgraph_get()
    helper = bpy.data.collections.get(COLL)
    pool = (props.target.all_objects if props.target
            else scene.objects)
    out = bmesh.new()
    by_style = props.fill_style == "STYLE"
    fills: dict[tuple, int] = {}          # (name, rgb, paint) -> output slot
    groups: list[tuple[int, list]] = []
    bars: list[tuple[int, list]] = []     # rebar cuts: dotted when tiny
    for ob in pool:
        if ob.type != "MESH" or not ob.visible_get():
            continue
        if helper and ob.name in helper.objects:
            continue
        if not _straddles(ob, co, look):
            continue
        slots = [s.material for s in ob.material_slots]
        bm = bmesh.new()
        try:
            bm.from_object(ob, depsgraph)
            bm.transform(ob.matrix_world)
            bm.verts.index_update()
            side = [(v.co - co).dot(look) for v in bm.verts]
            faces = [f for f in bm.faces
                     if min(side[v.index] for v in f.verts) < 0.0
                     < max(side[v.index] for v in f.verts)]
            if not faces:
                continue
            edges = {e for f in faces for e in f.edges}
            verts = {v for f in faces for v in f.verts}
            res = bmesh.ops.bisect_plane(
                bm, geom=list(verts) + list(edges) + faces, dist=1e-6,
                plane_co=co, plane_no=look)
            cut_edges = [g for g in res["geom_cut"]
                         if isinstance(g, bmesh.types.BMEdge)]
            vmap, per_mat = {}, {}
            for e in cut_edges:
                a, b = (vmap.get(v) or vmap.setdefault(
                    v, out.verts.new(v.co)) for v in e.verts)
                if a is b:
                    continue
                mi = e.link_faces[0].material_index if e.link_faces else 0
                per_mat.setdefault(mi, []).append(out.edges.new((a, b)))
            for mi, new_edges in sorted(per_mat.items()):
                mat = slots[mi] if 0 <= mi < len(slots) else None
                fill = fill_for(mat, ob) if by_style else ("Cut", None)
                k = _sty.style_of(fill[0], ob.name) if by_style else None
                # the hatch: what the material says, else the object name
                fill = (*fill, k.paint if k else "")
                slot = fills.setdefault(fill, len(fills))
                groups.append((slot, new_edges))
                if k is not None and k.kind == "Reinforcing Steel":
                    bars.append((slot, new_edges))
        finally:
            bm.free()
    lift: dict = {}                       # vert -> shift toward the camera
    for slot, new_edges in groups:
        area = 0.0
        if props.fill:
            res = bmesh.ops.triangle_fill(out, use_beauty=True,
                                          use_dissolve=False,
                                          edges=new_edges, normal=-look)
            for f in res["geom"]:
                if isinstance(f, bmesh.types.BMFace):
                    f.material_index = slot
                    area += f.calc_area()
        d = _layer(area)
        for e in new_edges:
            for v in e.verts:
                lift[v] = max(lift.get(v, 0.0), d)
    if props.fill:
        r_min = props.width * DOT_FRACTION
        for slot, new_edges in bars:
            for verts in _components(new_edges):
                _dot(out, verts, r_min, look, slot, lift)
    for v, d in lift.items():
        v.co -= look * d
    segs = [(tuple(e.verts[0].co), tuple(e.verts[1].co))
            for _slot, es in groups for e in es]
    me = bpy.data.meshes.get(CUT) or bpy.data.meshes.new(CUT)
    me.materials.clear()          # clearing AFTER to_mesh zeroes the indices
    out.to_mesh(me)
    out.free()
    for (name, rgb, paint), _slot in sorted(fills.items(), key=lambda kv: kv[1]):
        me.materials.append(_cut_material() if rgb is None
                            else _section_material(name, rgb, paint))
    if not me.materials:
        me.materials.append(_cut_material())
    ob = _obj(scene, CUT, lambda: me)
    ob.data = me
    ob.show_in_front = False
    set_hatch_period(props.width / 120.0)  # Cut Now too, not only place()
    outline(scene, props, segs, co, look)
    return ob


#: a cut bar narrower than this fraction of the view width is drawn as a dot
#: this size (a #8 bar is a pixel at 130 ft: a dot reads as the bar it is)
DOT_FRACTION = 0.0035


def _components(edges) -> list[list]:
    """The verts of each connected loop among `edges`."""
    parent: dict = {}

    def find(x):
        while parent.setdefault(x, x) is not x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for e in edges:
        a, b = (find(v) for v in e.verts)
        if a is not b:
            parent[a] = b
    groups: dict = {}
    for v in parent:
        groups.setdefault(find(v), []).append(v)
    return list(groups.values())


def _dot(bm, verts, r_min, look, slot, lift) -> None:
    """A filled disc of radius `r_min` over a bar's cut when the cut is
    smaller, in the section plane, over every other fill."""
    from mathutils import Vector
    c = sum((v.co for v in verts), Vector()) / len(verts)
    if max((v.co - c).length for v in verts) >= r_min:
        return
    x = look.orthogonal().normalized()
    y = look.cross(x).normalized()
    ring = [bm.verts.new(c + (x * math.cos(t) + y * math.sin(t)) * r_min)
            for t in (2 * math.pi * i / 12 for i in range(12))]
    face = bm.faces.new(ring if (ring[1].co - ring[0].co).cross(
        ring[2].co - ring[1].co).dot(-look) > 0 else ring[::-1])
    face.material_index = slot
    d = _layer(0.0) + NEAR_GAP * 0.02          # under the outline (0.8)
    for v in ring:
        lift[v] = d


LINES = "Section Lines"


def strips(segs, look, width):
    """(verts, faces) of flat strips `width` wide along each segment, lying
    in the section plane (normal `look`), each run on half a width past
    its ends so corners close. Flat, so they draw and RENDER as lines, and
    no near clip can slice them as it would a round tube."""
    from mathutils import Vector
    verts, faces = [], []
    h = width / 2
    for a, b in segs:
        a, b = Vector(a), Vector(b)
        d = b - a
        d -= look * d.dot(look)        # in-plane: float32 noise on a short
        if d.length < 1e-5:            # segment must not tip the strip out
            continue
        d.normalize()
        n = look.cross(d).normalized() * h
        a, b = a - d * h, b + d * h
        i = len(verts)
        verts += [a - n, b - n, b + n, a + n]
        faces.append((i, i + 1, i + 2, i + 3))
    return verts, faces


def _strip_mesh(scene, name, segs, look, width, rgb):
    verts, faces = strips(segs, look, width)
    me = bpy.data.meshes.get(name) or bpy.data.meshes.new(name)
    me.clear_geometry()
    me.from_pydata([tuple(v) for v in verts], [], faces)
    if not me.materials:
        me.materials.append(_section_material("Line", rgb))
    ob = _obj(scene, name, lambda: me)
    ob.data = me
    return ob


def outline(scene, props, segs, co, look):
    """Every cut edge as a thin dark line ("Section Lines"): outlines the
    fills and shows open cuts (a ground SURFACE has no inside to fill).
    Projected back onto the plane, then lifted over every fill layer and
    still inside the near-clip gap."""
    lift = -look * (NEAR_GAP * 0.8)

    def put(q):
        q = _v(q)
        return q - look * (q - co).dot(look) + lift
    segs = [(put(a), put(b)) for a, b in segs] if props.outline else []
    ob = _strip_mesh(scene, LINES, segs, look, props.width / 1000,
                     (0.04, 0.04, 0.05))
    ob.hide_viewport = ob.hide_render = not props.outline


def _layer(area: float) -> float:
    """How far toward the camera a fill of `area` m^2 sits off the plane.

    Fills are coplanar, so rebar inside a deck, or a pipe inside its
    bedding, would z-fight the fill around it. Smaller fills stand nearer
    the camera, a step per halving of area. Every step is inside the
    near-clip gap, so it never hides a fill.
    """
    import math
    level = 0 if area <= 0 else min(31, max(0, int(math.log2(area)) + 21))
    return NEAR_GAP * (0.25 + 0.5 * (31 - level) / 31)


def _v(p):
    from mathutils import Vector
    return Vector(p)


# ------------------------------------------------------------------ 4D date
def _ifc_name_index(f) -> dict:
    """Product Name -> GlobalId, for names that are unique in the file."""
    seen: dict = {}
    for p in f.by_type("IfcProduct"):
        if p.Name:
            seen[p.Name] = None if p.Name in seen else p.GlobalId
    return {k: v for k, v in seen.items() if v}


def global_id(ob, f, by_name: dict) -> str | None:
    """The IFC GlobalId a Blender object stands for: Bonsai's link first
    (BIMObjectProperties.ifc_definition_id), then a GlobalId custom
    property, then the object's name (Bonsai names objects 'IfcWall/Name';
    a '.001' duplicate suffix is ignored)."""
    try:
        eid = ob.BIMObjectProperties.ifc_definition_id
        if eid:
            return f.by_id(eid).GlobalId
    except Exception:
        pass
    for key in ("GlobalId", "ifc_globalid", "global_id"):
        if key in ob.keys():
            return str(ob[key])
    import re
    name = re.sub(r"\.\d{3}$", "", ob.name)
    for cand in (name, name.split("/", 1)[-1]):
        if cand in by_name:
            return by_name[cand]
    return None


def apply_date(scene) -> dict | None:
    """Hide what does not stand on `props.date` (or show everything again
    when the filter is off), then re-cut. Returns the counts."""
    props = scene.bimforge_section
    f = _STATE["file"]
    helper = bpy.data.collections.get(COLL)
    skip = set(helper.all_objects) if helper else set()
    for name in list(_STATE["hidden"]):           # undo the last filter
        ob = bpy.data.objects.get(name)
        if ob is not None:
            ob.hide_set(False)
            ob.hide_render = False
    _STATE["hidden"] = set()
    _STATE["counts"] = None
    if not (props.date_filter and props.date and f is not None):
        return None
    try:
        day = _ss.shift_day(props.date, 0)
    except ValueError:
        _STATE["error"] = f"date {props.date!r} is not YYYY-MM-DD"
        return None
    by_name = _ifc_name_index(f)
    counts = {"standing": 0, "not yet built": 0, "removed": 0,
              "unmatched": 0}
    for ob in scene.objects:
        if ob.type != "MESH" or ob in skip:
            continue
        gid = global_id(ob, f, by_name)
        if gid is None:
            counts["unmatched"] += 1
            continue
        st = _ss.state(_STATE["spans"].get(gid), day)
        counts[st] += 1
        if st != "standing":
            ob.hide_set(True)
            ob.hide_render = True
            _STATE["hidden"].add(ob.name)
    _STATE["counts"] = counts
    return counts


def _on_date(self, context):
    if _STATE["file"] is None:
        return
    apply_date(context.scene)
    if _STATE["frame"] is not None:
        update(context.scene)
    _redraw()


def _redraw():
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type in ("VIEW_3D", "PROPERTIES"):
                area.tag_redraw()


def update(scene):
    props = scene.bimforge_section
    st = _stationer(props)
    if st is None:
        return
    define_sliders(props, st)
    if bpy.data.objects.get(AXIS) is None:       # after Exit
        build_axis(scene, props, st)
    place(scene, props, st, st.frame_at_fraction(props.position))


def _on_position(self, context):
    update(context.scene)


def _on_alignment(self, context):
    st = _stationer(self)
    if st is not None and _STATE["frame"] is not None:
        build_axis(context.scene, self, st)
        update(context.scene)


def _on_view(self, context):
    if _STATE["frame"] is not None:
        update(context.scene)


# ---------------------------------------------------------------- sliders
def _quiet_stationer(props):
    """The loaded stationer, or None - never opens a file (sliders are read
    while the panel draws)."""
    sts = _STATE["stationers"]
    if not sts:
        return None
    return sts[min(int(props.alignment or 0), len(sts) - 1)]


def _sta_get(self) -> float:
    st = _quiet_stationer(self)
    if st is None:
        return 0.0
    return st.convert(st.station_at(self.position * st.length), _unit(self, st))


def _sta_set(self, value: float) -> None:
    st = _quiet_stationer(self)
    if st is None or not st.length:
        return
    d = st.distance_at(st.from_unit(value, _unit(self, st)) / st.unit_scale)
    self.position = min(1.0, max(0.0, d / st.length))


def _off_get(self) -> float:
    return self.pt_offset * (-1.0 if self.pt_side == "LT" else 1.0)


def _off_set(self, value: float) -> None:
    """Offset slider, - = Lt, + = Rt (Lt on the left looking up-station):
    the typed offset and side follow it, and the 3D cursor moves there."""
    self.pt_offset = abs(value)
    self.pt_side = "LT" if value < 0 else "RT"
    st, fr = _quiet_stationer(self), _STATE["frame"]
    if st is None or fr is None:
        return
    m = st.from_unit(abs(value), _unit(self, st))
    try:
        locate(bpy.context.scene, self, st, fr.distance, -m if value > 0 else m)
    except Exception as exc:            # a slider never raises into the UI
        _STATE["error"] = str(exc)


_SLIDER_KEY: list = [None]


def define_sliders(props, st) -> None:
    """(Re)define the station and offset sliders for this alignment, unit
    and view width: Blender takes a slider's range from its definition, so
    the range follows the alignment by redefining it."""
    u = _unit(props, st)
    a, b = sorted((st.convert(st.start_station, u), st.convert(st.end_station, u)))
    half = st.to_unit(props.width / 2.0, u)          # the view, no wider
    key = (round(a, 6), round(b, 6), round(half, 4), u)
    if _SLIDER_KEY[0] == key:
        return
    _SLIDER_KEY[0] = key
    SectionProps.station = FloatProperty(
        name="Station", min=a, max=b, soft_min=a, soft_max=b, precision=2,
        step=100, get=_sta_get, set=_sta_set,
        description=(f"Station along the alignment, {u} "
                     f"({st.format_station(st.start_station, u)} to "
                     f"{st.format_station(st.end_station, u)})"))
    SectionProps.offset = FloatProperty(
        name="Offset", min=-half, max=half, soft_min=-half, soft_max=half,
        precision=2, step=100, get=_off_get, set=_off_set,
        description=(f"Offset across the view, {u}: - Lt, + Rt (Lt on the "
                     "left looking up-station). Moves the 3D cursor there "
                     "and reads the surface"))


# --------------------------------------------------------------- property
if bpy is not None:
    from bpy.props import (BoolProperty, EnumProperty, FloatProperty,
                           FloatVectorProperty, PointerProperty,
                           StringProperty)

    class SectionProps(bpy.types.PropertyGroup):
        source: EnumProperty(
            name="Source", items=[
                ("BONSAI", "Bonsai", "The IFC Bonsai has open"),
                ("FILE", "File", "An IFC file on disk")],
            default="BONSAI")
        ifc_path: StringProperty(name="IFC", subtype="FILE_PATH")
        alignment: EnumProperty(name="Alignment", items=_alignment_items,
                                update=_on_alignment)
        position: FloatProperty(
            name="Station", description="Position along the alignment",
            min=0.0, max=1.0, default=0.0, subtype="FACTOR",
            precision=4, update=_on_position)
        goto: FloatProperty(name="Station", description=(
            "Station to jump to, in the display unit"), default=0.0)
        step: FloatProperty(name="Step", min=0.001, default=25.0,
                            description="Prev/next step, display unit")
        units: EnumProperty(name="Units", items=[
            ("AUTO", "Auto", "The project's (feet on a ftUS grid)"),
            ("FT", "Feet", "US survey feet, 12+34.56"),
            ("M", "Metres", "Metres, 1+234.567")], default="AUTO",
            update=_on_view)
        look: EnumProperty(name="Look", items=[
            ("AHEAD", "Ahead", "Look up-station"),
            ("BACK", "Back", "Look down-station")], default="AHEAD",
            update=_on_view)
        width: FloatProperty(name="Width", min=0.1, default=40.0,
                             subtype="DISTANCE", update=_on_view,
                             description="Section view width")
        depth: FloatProperty(name="Depth", min=0.0, default=0.25,
                             subtype="DISTANCE", update=_on_view,
                             description="How far past the cut to show")
        lift: FloatProperty(name="Lift", default=0.0, subtype="DISTANCE",
                            update=_on_view,
                            description="Raise the view centre above grade")
        shift: FloatVectorProperty(
            name="Model shift", size=3, subtype="TRANSLATION",
            update=_on_alignment,
            description="Add to alignment coordinates (Bonsai false origin)")
        ruler: BoolProperty(name="Offset ruler", default=True,
                            update=_on_view, description=(
                                "Offset ticks Lt/Rt of the alignment across "
                                "the section"))
        ruler_step: FloatProperty(name="Every", min=0.01, default=10.0,
                                  update=_on_view,
                                  description="Ruler spacing, display unit")
        ruler_height: FloatProperty(
            name="Ruler height", default=3.0, subtype="DISTANCE",
            update=_on_view,
            description="Ruler height above the grade line")
        date_filter: BoolProperty(
            name="Show the model on a date", default=False, update=_on_date,
            description=("Hide what is not yet built, or already removed, "
                         "on the date (the IFC's 4D schedule)"))
        date: StringProperty(
            name="Date", default="", update=_on_date,
            description="YYYY-MM-DD; the state at the end of that day")
        dev_from: StringProperty(name="From", default="",
                                 description="First station, e.g. 547+30")
        dev_to: StringProperty(name="To", default="",
                               description="Last station, e.g. 548+95")
        dev_offset: FloatProperty(name="Offset", min=0.0, default=0.0,
                                  description="The developed line's offset, display unit")
        dev_side: EnumProperty(name="Side", items=[
            ("LT", "Lt", "The line is left of the alignment"),
            ("RT", "Rt", "The line is right of the alignment")], default="LT")
        dev_look: EnumProperty(name="Look from", items=[
            ("LEFT", "From Lt", "Stand left of the line, look right "
             "(a Rt wall's formed face from the road)"),
            ("RIGHT", "From Rt", "Stand right of the line, look left "
             "(its retained side, the drainage)")], default="LEFT")
        dev_depth: FloatProperty(name="Depth", min=0.0, default=20.0,
                                 description="How far beyond the line to draw, display unit")
        dev_true: BoolProperty(name="True view", default=True,
                               description=("As seen; off mirrors a view from the left so "
                                            "stations read left to right"))
        dev_exag: FloatProperty(name="Vertical x", min=0.1, default=1.0,
                                description="Vertical exaggeration")
        pt_offset: FloatProperty(name="Offset", min=0.0, default=12.0,
                                 description="Offset to locate, display unit")
        pt_side: EnumProperty(name="Side", items=[
            ("LT", "Lt", "Left of the alignment (looking up-station)"),
            ("RT", "Rt", "Right of the alignment (looking up-station)")],
            default="LT")
        live_cut: BoolProperty(name="Live cut", default=True,
                               update=_on_view,
                               description="Re-cut the meshes as you slide")
        fill: BoolProperty(name="Fill", default=True, update=_on_view,
                           description="Fill closed cut loops with faces")
        outline: BoolProperty(name="Outline", default=True,
                              update=_on_view,
                              description="Draw every cut edge as a line")
        fill_style: EnumProperty(name="Fill", items=[
            ("STYLE", "By styling", "Each item's own styling: its material "
             "(the IFC surface style), else what its name says it is "
             "(concrete, rebar, asphalt, gravel, ...)"),
            ("SINGLE", "Single colour", "Every cut in one highlight colour")],
            default="STYLE", update=_on_view)
        target: PointerProperty(
            name="Cut", type=bpy.types.Collection, update=_on_view,
            description="Only cut this collection (empty: every mesh)")
        follow_frames: BoolProperty(
            name="Follow timeline", default=False,
            description="Frame start..end sweeps the whole alignment")
        overlay: BoolProperty(name="Viewport label", default=True)

    # -------------------------------------------------------------- ops
    class BIMFORGE_OT_section_load(bpy.types.Operator):
        bl_idname = "bimforge.section_load"
        bl_label = "Load Alignments"
        bl_description = "Read the IfcAlignments and draw the chosen one"

        def execute(self, context):
            props = context.scene.bimforge_section
            _STATE["key"] = None
            st = _stationer(props)
            if st is None:
                self.report({"ERROR"}, _STATE["error"])
                return {"CANCELLED"}
            build_axis(context.scene, props, st)
            update(context.scene)
            self.report({"INFO"}, f"{len(_STATE['stationers'])} alignment(s)")
            return {"FINISHED"}

    class BIMFORGE_OT_section_step(bpy.types.Operator):
        bl_idname = "bimforge.section_step"
        bl_label = "Step Station"
        bl_description = "Move the section by the step"
        direction: bpy.props.IntProperty(default=1)

        def execute(self, context):
            props = context.scene.bimforge_section
            st = _stationer(props)
            if st is None:
                return {"CANCELLED"}
            u = _unit(props, st)
            step_m = st.from_unit(props.step, u)
            d = props.position * st.length + self.direction * step_m
            props.position = min(1.0, max(0.0, d / st.length))
            return {"FINISHED"}

    class BIMFORGE_OT_section_goto(bpy.types.Operator):
        bl_idname = "bimforge.section_goto"
        bl_label = "Go"
        bl_description = "Jump to the typed station"

        def execute(self, context):
            props = context.scene.bimforge_section
            st = _stationer(props)
            if st is None:
                return {"CANCELLED"}
            u = _unit(props, st)
            station_m = st.from_unit(props.goto, u)
            d = st.distance_at(station_m / st.unit_scale)
            if not -1e-6 <= d <= st.length + 1e-6:
                self.report({"WARNING"}, "station is off the alignment")
            props.position = min(1.0, max(0.0, d / st.length))
            return {"FINISHED"}

    class BIMFORGE_OT_section_to_selected(bpy.types.Operator):
        bl_idname = "bimforge.section_to_selected"
        bl_label = "Go to Selected"
        bl_description = ("Slide the section to the selected element: its "
                          "station from the IFC (BIMForge_LinearReference), "
                          "else where its bounding box centre locates")

        def execute(self, context):
            props = context.scene.bimforge_section
            ob = context.active_object
            st = _stationer(props)
            if st is None or ob is None:
                self.report({"WARNING"}, "select an object and load an alignment")
                return {"CANCELLED"}
            f, sts = _open(props)
            gid = global_id(ob, f, _ifc_name_index(f))
            hit = element_station(f, sts, gid) if gid else None
            if hit is not None:
                idx, d, text = hit
                if str(idx) != props.alignment:
                    props.alignment = str(idx)
                st = sts[idx]
            else:
                from mathutils import Vector
                c = sum((ob.matrix_world @ Vector(v) for v in ob.bound_box),
                        Vector()) / 8.0 - Vector(props.shift)
                d, off = st.locate(c.x, c.y)
                text = (f"{ob.name}: Sta {st.format_station(st.station_at(d))}, "
                        f"{_st.format_offset(off, st.station_unit, st.foot_m)} (measured: "
                        "no BIMForge_LinearReference in the IFC)")
            props.position = min(1.0, max(0.0, d / st.length)) if st.length else 0.0
            self.report({"INFO"}, text)
            return {"FINISHED"}

    class BIMFORGE_OT_developed_build(bpy.types.Operator):
        bl_idname = "bimforge.developed_build"
        bl_label = "Develop"
        bl_description = ("Draw the developed elevation along the offset line in "
                          "its own scene: the cut filled per styling, the visible "
                          "edges beyond, the ground lines and the station ticks")

        def execute(self, context):
            props = context.scene.bimforge_section
            try:
                view, f = developed_view(props)
                dr = _dev.develop(f, view)
            except Exception as exc:          # surfaced, never a crash
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}
            sc = build_developed(dr)
            if context.window is not None:
                if context.window.scene.name != DEV_SCENE:
                    _STATE["home_scene"] = context.window.scene.name
                context.window.scene = sc
            self.report({"INFO"}, (f"{view.name}: {dr.length:.2f} along the line, "
                                   f"{len(dr.cut)} cut, {len(dr.beyond)} lines beyond"))
            return {"FINISHED"}

    class BIMFORGE_OT_developed_dxf(bpy.types.Operator):
        bl_idname = "bimforge.developed_dxf"
        bl_label = "Export DXF"
        bl_description = "Write the developed elevation as a DXF sheet (needs ezdxf)"
        filepath: StringProperty(subtype="FILE_PATH", default="developed.dxf")

        def invoke(self, context, event):
            context.window_manager.fileselect_add(self)
            return {"RUNNING_MODAL"}

        def execute(self, context):
            props = context.scene.bimforge_section
            try:
                view, f = developed_view(props)
                lines = _dev.write_dxf([_dev.develop(f, view)],
                                       bpy.path.abspath(self.filepath))
            except ImportError:
                self.report({"ERROR"}, "DXF needs ezdxf in Blender's Python "
                            "(or run: est-bim elevation set.yaml)")
                return {"CANCELLED"}
            except Exception as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}
            self.report({"INFO"}, lines[0])
            return {"FINISHED"}

    class BIMFORGE_OT_section_dxf(bpy.types.Operator):
        bl_idname = "bimforge.section_dxf"
        bl_label = "Export Section DXF"
        bl_description = ("Write the cross section the camera shows (this station, "
                          "the view width, depth and look) as a DXF sheet "
                          "(needs ezdxf)")
        filepath: StringProperty(subtype="FILE_PATH", default="section.dxf")

        def invoke(self, context, event):
            context.window_manager.fileselect_add(self)
            return {"RUNNING_MODAL"}

        def execute(self, context):
            props = context.scene.bimforge_section
            try:
                view, f = section_view_def(props)
                lines = _dev.write_dxf([_dev.cross_section(f, view)],
                                       bpy.path.abspath(self.filepath))
            except ImportError:
                self.report({"ERROR"}, "DXF needs ezdxf in Blender's Python")
                return {"CANCELLED"}
            except Exception as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}
            self.report({"INFO"}, lines[0])
            return {"FINISHED"}

    class BIMFORGE_OT_section_exit(bpy.types.Operator):
        bl_idname = "bimforge.section_exit"
        bl_label = "Exit"
        bl_description = ("Leave the section completely: a free 3D view of "
                          "the whole model, the section camera, plane, cut, "
                          "ruler and labels removed. The slider or View "
                          "Section brings it back")
        full: bpy.props.BoolProperty(default=True, options={"SKIP_SAVE"})

        def execute(self, context):
            done = close_section(context) if self.full else exit_views(context)
            self.report({"INFO"}, "; ".join(done) if done else "section closed")
            return {"FINISHED"}

    class BIMFORGE_OT_section_view(bpy.types.Operator):
        bl_idname = "bimforge.section_view"
        bl_label = "View Section"
        bl_description = "Look through the section camera"

        def execute(self, context):
            if bpy.data.objects.get(CAM) is None:
                update(context.scene)             # after Exit: build it again
            cam = bpy.data.objects.get(CAM)
            if cam is None:
                self.report({"ERROR"}, "load an alignment first")
                return {"CANCELLED"}
            if context.scene.camera not in (None, cam):
                _STATE["home_camera"] = context.scene.camera.name
            context.scene.camera = cam
            area = context.area if context.area and \
                context.area.type == "VIEW_3D" else next(
                    (a for a in context.screen.areas if a.type == "VIEW_3D"),
                    None)
            if area is not None:
                area.spaces.active.region_3d.view_perspective = "CAMERA"
            return {"FINISHED"}

    class BIMFORGE_OT_section_cut(bpy.types.Operator):
        bl_idname = "bimforge.section_cut"
        bl_label = "Cut Now"
        bl_description = "Cut the meshes at the current station"

        def execute(self, context):
            props = context.scene.bimforge_section
            fr = _STATE["frame"]
            if fr is None:
                return {"CANCELLED"}
            from mathutils import Vector
            _x, _y, _z, look = _basis(fr, props.look == "BACK")
            cut(context.scene, props, Vector(fr.point) + Vector(props.shift),
                look)
            return {"FINISHED"}

    class BIMFORGE_OT_section_date_step(bpy.types.Operator):
        bl_idname = "bimforge.section_date_step"
        bl_label = "Step Date"
        bl_description = ("Move the 4D date by days, or to the previous / "
                          "next day something appears or is removed")
        days: bpy.props.IntProperty(default=1)
        event: bpy.props.IntProperty(default=0)    # -1 / +1: jump to event

        def execute(self, context):
            props = context.scene.bimforge_section
            ev = _STATE["events"]
            if not ev:
                self.report({"WARNING"}, "the IFC carries no 4D schedule")
                return {"CANCELLED"}
            day = props.date or ev[0]
            if self.event > 0:
                nxt = [d for d in ev if d > day]
                day = nxt[0] if nxt else ev[-1]
            elif self.event < 0:
                prv = [d for d in ev if d < day]
                day = prv[-1] if prv else ev[0]
            else:
                day = _ss.shift_day(day, self.days)
            props.date_filter = True
            props.date = day                  # its update re-filters
            return {"FINISHED"}

    class BIMFORGE_OT_section_offset_locate(bpy.types.Operator):
        bl_idname = "bimforge.section_offset_locate"
        bl_label = "Locate"
        bl_description = ("Put the 3D cursor at the offset from the current "
                          "station and read the surface there")

        def execute(self, context):
            props = context.scene.bimforge_section
            st, fr = _stationer(props), _STATE["frame"]
            if st is None or fr is None:
                return {"CANCELLED"}
            u = _unit(props, st)
            m = st.from_unit(props.pt_offset, u)
            locate(context.scene, props, st, fr.distance,
                   m if props.pt_side == "LT" else -m)
            self.report({"INFO"}, _point_text(props, st))
            return {"FINISHED"}

    class BIMFORGE_OT_section_offset_inquire(bpy.types.Operator):
        bl_idname = "bimforge.section_offset_inquire"
        bl_label = "Inquire Cursor"
        bl_description = ("Station and offset of the 3D cursor; with Cut, "
                          "also slide the section there")
        cut_there: bpy.props.BoolProperty(default=False)

        def execute(self, context):
            props = context.scene.bimforge_section
            st = _stationer(props)
            if st is None:
                return {"CANCELLED"}
            from mathutils import Vector
            c = context.scene.cursor.location - Vector(props.shift)
            d, off = st.locate(c.x, c.y)
            if self.cut_there:
                props.position = d / st.length if st.length else 0.0
            _STATE["point"] = (d, off, c.z + props.shift[2],
                               top_surface(context.scene, *context.scene
                                           .cursor.location.xy))
            self.report({"INFO"}, _point_text(props, st))
            _redraw()
            return {"FINISHED"}

    # ------------------------------------------------------------ panel
    class BIMFORGE_PT_section(bpy.types.Panel):
        bl_label = "Alignment Section"
        bl_space_type = "VIEW_3D"
        bl_region_type = "UI"
        bl_category = "Section"

        def draw(self, context):
            props = context.scene.bimforge_section
            if context.scene.name == DEV_SCENE:
                self.layout.operator("bimforge.section_exit",
                                     text="Back to the model",
                                     icon="LOOP_BACK").full = False
                return
            col = self.layout.column(align=True)
            col.row().prop(props, "source", expand=True)
            if props.source == "FILE":
                col.prop(props, "ifc_path", text="")
            col.operator("bimforge.section_load", icon="FILE_REFRESH")
            if _STATE["error"]:
                self.layout.label(text=_STATE["error"], icon="ERROR")
            if not _STATE["stationers"]:
                return
            st = _stationer(props)
            if st is None:
                return
            u = _unit(props, st)
            box = self.layout.box()
            box.prop(props, "alignment", text="")
            fr = _STATE["frame"]
            if fr is not None:
                box.label(text=f"Sta {st.format_station(fr.station, u)}",
                          icon="CURVE_PATH")
            box.prop(props, "station", slider=True)
            row = box.row(align=True)
            row.operator("bimforge.section_step", text="",
                         icon="TRIA_LEFT").direction = -1
            row.prop(props, "step")
            row.operator("bimforge.section_step", text="",
                         icon="TRIA_RIGHT").direction = 1
            row = box.row(align=True)
            row.prop(props, "goto")
            row.operator("bimforge.section_goto")
            box.operator("bimforge.section_to_selected", icon="RESTRICT_SELECT_OFF")
            if fr is not None:
                info = box.column(align=True)
                elev = st.to_unit(st.elevation_m(fr.point[2]), u)
                info.label(text=f"Grade EL {elev:,.2f} {u}  "
                                f"{fr.grade * 100:+.3f} %")
                info.label(text=f"Bearing {_bearing(fr.azimuth)}")
                info.label(text=(f"{st.format_station(st.start_station, u)}"
                                 f" to {st.format_station(st.end_station, u)}"))
            row = self.layout.row(align=True)
            row.operator("bimforge.section_view", icon="VIEW_CAMERA")
            row.operator("bimforge.section_exit", icon="LOOP_BACK")
            self.layout.operator("bimforge.section_dxf", icon="EXPORT")
            if _STATE["events"]:
                dbox = self.layout.box()
                dbox.label(text="4D date", icon="TIME")
                row = dbox.row(align=True)
                row.prop(props, "date_filter", text="")
                row.prop(props, "date", text="")
                row = dbox.row(align=True)
                for icon, kw in (("PREV_KEYFRAME", {"event": -1}),
                                 ("TRIA_LEFT", {"days": -7}),
                                 ("REW", {"days": -1}),
                                 ("FF", {"days": 1}),
                                 ("TRIA_RIGHT", {"days": 7}),
                                 ("NEXT_KEYFRAME", {"event": 1})):
                    op = row.operator("bimforge.section_date_step", text="",
                                      icon=icon)
                    for k, v in kw.items():
                        setattr(op, k, v)
                ev = _STATE["events"]
                dbox.label(text=f"schedule {ev[0]} to {ev[-1]}")
                c = _STATE["counts"]
                if c:
                    dbox.label(text=(f"{c['standing']} standing, "
                                     f"{c['not yet built']} not yet built, "
                                     f"{c['removed']} removed"))
                    if c["unmatched"]:
                        dbox.label(text=(f"{c['unmatched']} objects not "
                                         f"matched to the IFC (shown)"),
                                   icon="INFO")
            offs = self.layout.box()
            offs.label(text="Offsets", icon="DRIVER_DISTANCE")
            row = offs.row(align=True)
            row.prop(props, "ruler")
            row.prop(props, "ruler_step")
            if props.ruler:
                offs.prop(props, "ruler_height")
            offs.prop(props, "offset", slider=True)
            row = offs.row(align=True)
            row.prop(props, "pt_offset")
            row.prop(props, "pt_side", expand=True)
            row = offs.row(align=True)
            row.operator("bimforge.section_offset_locate", icon="PIVOT_CURSOR")
            row.operator("bimforge.section_offset_inquire", text="Inquire",
                         icon="CURSOR")
            row.operator("bimforge.section_offset_inquire", text="Cut",
                         icon="MOD_BOOLEAN").cut_there = True
            if _STATE.get("point"):
                for line in _point_text(props, st).split("  |  "):
                    offs.label(text=line)
            dev = self.layout.box()
            dev.label(text="Developed elevation", icon="VIEW_ORTHO")
            row = dev.row(align=True)
            row.prop(props, "dev_from")
            row.prop(props, "dev_to")
            row = dev.row(align=True)
            row.prop(props, "dev_offset")
            row.prop(props, "dev_side", expand=True)
            dev.row().prop(props, "dev_look", expand=True)
            row = dev.row(align=True)
            row.prop(props, "dev_depth")
            row.prop(props, "dev_exag")
            dev.prop(props, "dev_true")
            row = dev.row(align=True)
            row.operator("bimforge.developed_build", icon="SEQ_LUMA_WAVEFORM")
            row.operator("bimforge.developed_dxf", icon="EXPORT")
            view = self.layout.column(align=True)
            view.row().prop(props, "look", expand=True)
            view.prop(props, "width")
            view.prop(props, "depth")
            view.prop(props, "lift")
            cutc = self.layout.column(align=True)
            row = cutc.row(align=True)
            row.prop(props, "live_cut")
            row.prop(props, "fill")
            row.prop(props, "outline")
            cutc.prop(props, "fill_style", text="")
            cutc.prop(props, "target")
            if not props.live_cut:
                cutc.operator("bimforge.section_cut", icon="MOD_BOOLEAN")
            more = self.layout.column(align=True)
            more.prop(props, "units")
            more.prop(props, "follow_frames")
            more.prop(props, "overlay")
            more.prop(props, "shift")


DEV_SCENE = "BIMForge Developed Elevation"
DEV_PREFIX = "Elevation"             # the developed scene's own fill materials


def developed_view(props):
    """(ElevationView, file) from the panel: the loaded alignment, the panel's
    stations / offset / side / look / depth, and the 4D date when the date
    filter is on."""
    f, _sts = _open(props)
    st = _stationer(props)
    u = _unit(props, st)
    if not props.dev_from or not props.dev_to:
        raise ValueError("a developed elevation needs From and To stations "
                         "(for the cross section, use Export Section DXF)")
    a, b = (_dev.parse_station(x, u) for x in (props.dev_from, props.dev_to))
    if u != st.station_unit:                  # the engine speaks the file's unit
        k = st.to_unit(1.0, st.station_unit) / st.to_unit(1.0, u)
        a, b = a * k, b * k
        off, depth = props.dev_offset * k, props.dev_depth * k
    else:
        off, depth = props.dev_offset, props.dev_depth
    view = _dev.ElevationView(
        name=f"{st.name} {props.dev_offset:g} {props.dev_side.title()}",
        from_station=a, to_station=b, offset=off, side=props.dev_side.title(),
        look_from=props.dev_look.lower(), depth=depth, alignment=st.name,
        true_view=props.dev_true, exaggeration=props.dev_exag,
        date=(props.date or None) if props.date_filter else None)
    return view, f


def section_view_def(props):
    """(SectionView, file) of the section the camera shows: the slider's
    station, the panel's width / depth / look (Blender metres to the station
    unit) and the 4D date when the date filter is on."""
    f, _sts = _open(props)
    st = _stationer(props)
    fr = _STATE["frame"]
    if st is None or fr is None:
        raise ValueError("load an alignment first")
    u = st.station_unit                       # the engine speaks the file's unit
    sta = st.convert(fr.station, u)
    view = _dev.SectionView(
        name=f"{st.name} STA {st.format_station(fr.station)}", station=sta,
        width=st.to_unit(props.width, u), depth=st.to_unit(max(props.depth, 0.0), u),
        look_back=props.look == "BACK", alignment=st.name,
        date=(props.date or None) if props.date_filter else None)
    return view, f


def exit_views(context) -> list[str]:
    """Back to the model: from the developed-elevation scene to the scene it
    was built from, and every 3D view out of the camera into a free view."""
    done = []
    win = context.window
    if win is not None and win.scene.name == DEV_SCENE:
        back = bpy.data.scenes.get(_STATE.get("home_scene") or "") or next(
            (sc for sc in bpy.data.scenes if sc.name != DEV_SCENE), None)
        if back is not None:
            win.scene = back
            done.append(f"scene {back.name}")
    screen = win.screen if win is not None else context.screen
    for area in (screen.areas if screen is not None else ()):
        if area.type != "VIEW_3D":
            continue
        r3d = area.spaces.active.region_3d
        if r3d.view_perspective == "CAMERA":
            r3d.view_perspective = "PERSP"
            done.append("free view")
    return done


def close_section(context) -> list[str]:
    """Leave the section completely: out of the camera (and the developed
    scene), the 4D filter off so the whole model shows, the scene's own
    camera back, and every helper the section drew - camera, plane frame,
    cut, lines, ruler, labels, marker, axis - removed with its data. The
    alignment stays loaded: the slider or View Section brings it back."""
    done = exit_views(context)
    scene = context.window.scene if context.window else context.scene
    props = scene.bimforge_section
    if props.date_filter:
        _STATE["frame"] = None                # so turning it off does not re-cut
        props.date_filter = False
        done.append("4D filter off")
    cam = bpy.data.objects.get(CAM)
    if cam is not None and scene.camera is cam:
        scene.camera = bpy.data.objects.get(_STATE.get("home_camera") or "")
    coll = bpy.data.collections.get(COLL)
    n = 0
    if coll is not None:
        for ob in list(coll.all_objects):
            data = ob.data
            bpy.data.objects.remove(ob, do_unlink=True)
            n += 1
            if data is not None and data.users == 0:
                for kind in (bpy.data.meshes, bpy.data.curves, bpy.data.cameras):
                    if data.name in kind and kind[data.name] == data:
                        kind.remove(data)
                        break
        bpy.data.collections.remove(coll)
    for mat in list(bpy.data.materials):          # the section's own fills
        if mat.users == 0 and (mat.name.startswith("Section ")
                               or mat.name == "Section Cut"):
            bpy.data.materials.remove(mat)
    _STATE["frame"] = None
    _STATE["point"] = None
    _redraw()
    if n:
        done.append(f"{n} section objects removed")
    return done


def build_developed(dr) -> "bpy.types.Scene":
    """The drawing in its own scene, in the XZ plane (x along the line,
    z elevation), seen by an orthographic camera looking +Y: cut fills per
    styling, ground and visible lines as flat strips, station labels."""
    import bmesh
    from mathutils import Vector
    sc = bpy.data.scenes.get(DEV_SCENE) or bpy.data.scenes.new(DEV_SCENE)
    for ob in list(sc.collection.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    look = Vector((0.0, 1.0, 0.0))
    k = (dr.foot_m if dr.unit == "ft" else 1.0)      # drawing unit -> metres

    def p3(p, lift=0.0):
        return Vector((p[0] * k, -lift, p[1] * k))

    def link(name, data):
        ob = bpy.data.objects.new(name, data)
        sc.collection.objects.link(ob)
        return ob
    for i, (layer, rgb, polys) in enumerate(dr.cut):
        bm = bmesh.new()
        edges = []
        for poly in polys:
            for ring in poly:
                vs = [bm.verts.new(p3(q)) for q in ring[:-1]]
                edges += [bm.edges.new((vs[j], vs[(j + 1) % len(vs)]))
                          for j in range(len(vs))]
        bmesh.ops.triangle_fill(bm, use_beauty=True, use_dissolve=False,
                                edges=edges, normal=-look)
        me = bpy.data.meshes.new(f"Developed cut {i}")
        bm.to_mesh(me)
        bm.free()
        me.materials.append(_section_material(layer.replace("E-CUT-", ""), rgb,
                                              prefix=DEV_PREFIX))
        link(me.name, me)
    width = max(dr.length * k, 1.0) / 1500.0
    lines = [(tuple(p3(a, 0.01)), tuple(p3(b, 0.01)))
             for ln in dr.beyond for a, b in zip(ln, ln[1:])]
    lines += [(tuple(p3(a, 0.02)), tuple(p3(b, 0.02)))
              for _l, _rgb, ln in dr.ground for a, b in zip(ln, ln[1:])]
    if lines:
        verts, faces = strips(lines, look, width)
        me = bpy.data.meshes.new("Developed lines")
        me.from_pydata([tuple(v) for v in verts], [], faces)
        me.materials.append(_section_material("Line", (0.05, 0.05, 0.05)))
        link(me.name, me)
    x0, y0, x1, y1 = dr.extent
    th = max(y1 - y0, 1.0) * k / 25.0
    for x, sta in dr.ticks:
        if abs(sta - round(sta / 10.0) * 10.0) > 1e-6:
            continue
        cu = bpy.data.curves.new(f"Sta {sta:g}", "FONT")
        cu.body = _st.format_station(sta, dr.unit, 0)
        cu.size = th
        cu.align_x = "CENTER"
        ob = link(cu.name, cu)
        ob.location = p3((x, y0), 0.03) - Vector((0, 0, 2.0 * th))
        ob.rotation_euler = (math.pi / 2, 0.0, 0.0)
    cam_data = bpy.data.cameras.new("Developed camera")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = max((x1 - x0) * k, (y1 - y0) * k * 2.0) * 1.1
    set_hatch_period(cam_data.ortho_scale / 150.0, DEV_PREFIX)
    cam = link("Developed camera", cam_data)
    cam.location = Vector(((x0 + x1) / 2 * k, -50.0, (y0 + y1) / 2 * k))
    cam.rotation_euler = (math.pi / 2, 0.0, 0.0)          # looks +Y
    sc.camera = cam
    sc["bimforge_developed"] = {"view": dr.view.name, "length": dr.length,
                                "unit": dr.unit}
    return sc


LINEAR_REF_PSET = "BIMForge_LinearReference"     # bimforge.bim.linear_ref.PSET


def element_station(f, stationers, gid):
    """(stationer index, distance along (m), report text) of an element from
    the IFC's own BIMForge_LinearReference (est-bim stations / est-bim build
    write it): its authored anchor when it has one, else the middle of its
    station range. None when the element carries no such set."""
    import ifcopenshell.util.element as ue
    try:
        el = f.by_guid(gid)
    except Exception:
        return None
    ps = ue.get_pset(el, LINEAR_REF_PSET)
    if not ps or "StationStart" not in ps:
        return None
    idx = next((i for i, st in enumerate(stationers)
                if st.name == ps.get("Alignment")), None)
    if idx is None:
        return None
    st = stationers[idx]
    if "AnchorStation" in ps:
        station = float(ps["AnchorStation"])
    else:
        station = 0.5 * (float(ps["StationStart"]) + float(ps["StationEnd"]))
    text = (f"{el.Name}: {ps.get('StationStartText')} to "
            f"{ps.get('StationEndText')}, {ps.get('OffsetText')}")
    if "AnchorStationText" in ps:
        text += (f" (placed at {ps['AnchorStationText']} "
                 f"{ps.get('AnchorOffsetText', '')})")
    return idx, st.distance_at(station), text


def _point_text(props, st) -> str:
    """'Sta 12+50.00, 12.00 Lt  |  PG EL 160.42  |  top EL 161.07 deck'."""
    d, off, z, hit = _STATE["point"]
    u = _unit(props, st)
    el = lambda zz: f"{st.to_unit(st.elevation_m(zz), u):,.2f}"  # noqa: E731
    pg = st.frame(d).point[2]
    parts = [f"Sta {st.format_station(st.station_at(d), u)}, "
             f"{_st.format_offset(off, u, st.foot_m)}", f"PG EL {el(pg)}"]
    if abs(z - pg) > 1e-6:
        parts.append(f"cursor EL {el(z)}")
    if hit is not None:
        parts.append(f"top EL {el(hit[0])} {hit[1][:28]}")
    return "  |  ".join(parts)


def _bearing(az: float) -> str:
    """Azimuth (deg, CW from north) as a quadrant bearing N 12-34-56 E."""
    az %= 360.0
    if az <= 90:
        ns, ew, a = "N", "E", az
    elif az <= 180:
        ns, ew, a = "S", "E", 180 - az
    elif az <= 270:
        ns, ew, a = "S", "W", az - 180
    else:
        ns, ew, a = "N", "W", 360 - az
    s = int(round(a * 3600))
    return f"{ns} {s // 3600:02d}-{s // 60 % 60:02d}-{s % 60:02d} {ew}"


def _draw_overlay():
    ctx = bpy.context
    props = getattr(ctx.scene, "bimforge_section", None)
    fr = _STATE["frame"]
    if props is None or not props.overlay or fr is None:
        return
    rv3d = ctx.region_data
    cam = bpy.data.objects.get(CAM)
    if rv3d is None or rv3d.view_perspective != "CAMERA" or \
            ctx.scene.camera is not cam:
        return
    st = _stationer(props)
    if st is None:
        return
    import blf
    u = _unit(props, st)
    elev = st.to_unit(st.elevation_m(fr.point[2]), u)
    text = (f"{st.name}   Sta {st.format_station(fr.station, u)}   "
            f"EL {elev:,.2f}   {fr.grade * 100:+.2f}%   "
            f"looking {'back' if props.look == 'BACK' else 'ahead'}")
    if props.date_filter and props.date:
        text += f"   4D {props.date}"
    blf.size(0, 16)
    blf.color(0, 1.0, 1.0, 1.0, 0.95)
    blf.position(0, 24, ctx.region.height - 64, 0)
    blf.draw(0, text)


def _persistent(fn):
    from bpy.app.handlers import persistent
    return persistent(fn)


def _frame_change(scene, *_):
    props = getattr(scene, "bimforge_section", None)
    if props is None or not props.follow_frames:
        return
    span = max(1, scene.frame_end - scene.frame_start)
    u = min(1.0, max(0.0, (scene.frame_current - scene.frame_start) / span))
    if abs(u - props.position) > 1e-9:
        props.position = u              # its update re-places the section


def _load_post(*_):
    _STATE.update(key=None, file=None, stationers=[], frame=None, error="",
                  point=None, spans={}, events=[], hidden=set(), counts=None)


_CLASSES = () if bpy is None else (
    SectionProps, BIMFORGE_OT_section_load, BIMFORGE_OT_section_step,
    BIMFORGE_OT_section_goto, BIMFORGE_OT_section_view,
    BIMFORGE_OT_section_cut, BIMFORGE_OT_section_offset_locate,
    BIMFORGE_OT_section_to_selected,
    BIMFORGE_OT_developed_build, BIMFORGE_OT_developed_dxf,
    BIMFORGE_OT_section_dxf, BIMFORGE_OT_section_exit,
    BIMFORGE_OT_section_offset_inquire, BIMFORGE_OT_section_date_step,
    BIMFORGE_PT_section)
_HANDLERS: list = []


def register():
    global _DRAW_HANDLE
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    _SLIDER_KEY[0] = None
    SectionProps.station = FloatProperty(name="Station", get=_sta_get,
                                         set=_sta_set, precision=2)
    SectionProps.offset = FloatProperty(name="Offset", get=_off_get,
                                        set=_off_set, precision=2)
    bpy.types.Scene.bimforge_section = bpy.props.PointerProperty(
        type=SectionProps)
    fc, lp = _persistent(_frame_change), _persistent(_load_post)
    bpy.app.handlers.frame_change_post.append(fc)
    bpy.app.handlers.load_post.append(lp)
    _HANDLERS[:] = [(bpy.app.handlers.frame_change_post, fc),
                    (bpy.app.handlers.load_post, lp)]
    _DRAW_HANDLE = bpy.types.SpaceView3D.draw_handler_add(
        _draw_overlay, (), "WINDOW", "POST_PIXEL")


def unregister():
    global _DRAW_HANDLE
    if _DRAW_HANDLE is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_DRAW_HANDLE, "WINDOW")
        _DRAW_HANDLE = None
    for lst, fn in _HANDLERS:
        if fn in lst:
            lst.remove(fn)
    _HANDLERS.clear()
    del bpy.types.Scene.bimforge_section
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
    _load_post()
