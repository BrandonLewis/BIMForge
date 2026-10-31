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
  the cut faces into "Section Cut", so the section reads as solid hatch;
* reports station, elevation of the grade line, grade and bearing.

The slider can follow the timeline, so scrubbing frames sweeps the section
along the alignment (and rendering the frames makes a fly-through).

Stationing comes from bimforge.bim.alignment_station, which this add-on
carries as its own copy (`python -m bimforge.blender` builds the zip). It
needs ifcopenshell inside Blender: Bonsai provides it.
"""
from __future__ import annotations

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
except ImportError:                     # running from the bimforge package
    from bimforge.bim import alignment_station as _st

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
                "error": ""}
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
        _STATE.update(key=key, file=f, stationers=stationers, frame=None,
                      error="")
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
    off = Vector(props.offset)
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
    off = Vector(props.offset)
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
    _STATE["frame"] = fr
    _redraw()


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
    object's closed loops."""
    import bmesh
    depsgraph = bpy.context.evaluated_depsgraph_get()
    helper = bpy.data.collections.get(COLL)
    pool = (props.target.all_objects if props.target
            else scene.objects)
    out = bmesh.new()
    shift = -look * (NEAR_GAP / 4)       # cap a hair toward the camera
    for ob in pool:
        if ob.type != "MESH" or not ob.visible_get():
            continue
        if helper and ob.name in helper.objects:
            continue
        if not _straddles(ob, co, look):
            continue
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
            vmap, new_edges = {}, []
            for e in cut_edges:
                a, b = (vmap.get(v) or vmap.setdefault(
                    v, out.verts.new(v.co + shift)) for v in e.verts)
                if a is not b:
                    new_edges.append(out.edges.new((a, b)))
            if props.fill and new_edges:
                bmesh.ops.triangle_fill(out, use_beauty=True,
                                        use_dissolve=False, edges=new_edges,
                                        normal=-look)
        finally:
            bm.free()
    me = bpy.data.meshes.get(CUT) or bpy.data.meshes.new(CUT)
    out.to_mesh(me)
    out.free()
    if not me.materials:
        me.materials.append(_cut_material())
    ob = _obj(scene, CUT, lambda: me)
    ob.data = me
    ob.show_in_front = False
    return ob


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
        offset: FloatVectorProperty(
            name="Offset", size=3, subtype="TRANSLATION",
            update=_on_alignment,
            description="Add to alignment coordinates (Bonsai false origin)")
        live_cut: BoolProperty(name="Live cut", default=True,
                               update=_on_view,
                               description="Re-cut the meshes as you slide")
        fill: BoolProperty(name="Fill", default=True, update=_on_view,
                           description="Fill closed cut loops with faces")
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
            step_m = props.step * (_st.US_SURVEY_FT_M if u == "ft" else 1.0)
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
            station_m = props.goto * (_st.US_SURVEY_FT_M if u == "ft" else 1.0)
            d = st.distance_at(station_m / st.unit_scale)
            if not -1e-6 <= d <= st.length + 1e-6:
                self.report({"WARNING"}, "station is off the alignment")
            props.position = min(1.0, max(0.0, d / st.length))
            return {"FINISHED"}

    class BIMFORGE_OT_section_view(bpy.types.Operator):
        bl_idname = "bimforge.section_view"
        bl_label = "View Section"
        bl_description = "Look through the section camera"

        def execute(self, context):
            cam = bpy.data.objects.get(CAM)
            if cam is None:
                self.report({"ERROR"}, "load an alignment first")
                return {"CANCELLED"}
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
            cut(context.scene, props, Vector(fr.point) + Vector(props.offset),
                look)
            return {"FINISHED"}

    # ------------------------------------------------------------ panel
    class BIMFORGE_PT_section(bpy.types.Panel):
        bl_label = "Alignment Section"
        bl_space_type = "VIEW_3D"
        bl_region_type = "UI"
        bl_category = "Section"

        def draw(self, context):
            props = context.scene.bimforge_section
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
            box.prop(props, "position", slider=True)
            row = box.row(align=True)
            row.operator("bimforge.section_step", text="",
                         icon="TRIA_LEFT").direction = -1
            row.prop(props, "step")
            row.operator("bimforge.section_step", text="",
                         icon="TRIA_RIGHT").direction = 1
            row = box.row(align=True)
            row.prop(props, "goto")
            row.operator("bimforge.section_goto")
            if fr is not None:
                info = box.column(align=True)
                elev = _st.metres_to(st.elevation_m(fr.point[2]), u)
                info.label(text=f"Grade EL {elev:,.2f} {u}  "
                                f"{fr.grade * 100:+.3f} %")
                info.label(text=f"Bearing {_bearing(fr.azimuth)}")
                info.label(text=(f"{st.format_station(st.start_station, u)}"
                                 f" to {st.format_station(st.end_station, u)}"))
            self.layout.operator("bimforge.section_view", icon="VIEW_CAMERA")
            view = self.layout.column(align=True)
            view.row().prop(props, "look", expand=True)
            view.prop(props, "width")
            view.prop(props, "depth")
            view.prop(props, "lift")
            cutc = self.layout.column(align=True)
            row = cutc.row(align=True)
            row.prop(props, "live_cut")
            row.prop(props, "fill")
            cutc.prop(props, "target")
            if not props.live_cut:
                cutc.operator("bimforge.section_cut", icon="MOD_BOOLEAN")
            more = self.layout.column(align=True)
            more.prop(props, "units")
            more.prop(props, "follow_frames")
            more.prop(props, "overlay")
            more.prop(props, "offset")


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
    elev = _st.metres_to(st.elevation_m(fr.point[2]), u)
    text = (f"{st.name}   Sta {st.format_station(fr.station, u)}   "
            f"EL {elev:,.2f}   {fr.grade * 100:+.2f}%   "
            f"looking {'back' if props.look == 'BACK' else 'ahead'}")
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
    _STATE.update(key=None, file=None, stationers=[], frame=None, error="")


_CLASSES = () if bpy is None else (
    SectionProps, BIMFORGE_OT_section_load, BIMFORGE_OT_section_step,
    BIMFORGE_OT_section_goto, BIMFORGE_OT_section_view,
    BIMFORGE_OT_section_cut, BIMFORGE_PT_section)
_HANDLERS: list = []


def register():
    global _DRAW_HANDLE
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
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
