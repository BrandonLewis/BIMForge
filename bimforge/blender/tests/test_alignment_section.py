"""The Blender alignment-section add-on, driven headless through `bpy`.

Skipped unless the `bpy` wheel is importable (it is not a bimforge
dependency). The add-on is loaded from the zip `build_addon` writes — the
artifact a user installs — and slid along the fixture deck: the cut must lie
on the plane square to the alignment, and fill to the deck's section area.
"""
from __future__ import annotations

import importlib
import sys
import zipfile

import pytest

bpy = pytest.importorskip("bpy")
ifcopenshell = pytest.importorskip("ifcopenshell")
import ifcopenshell.geom  # noqa: E402

from bimforge.author.tests.test_emit_alignment import _emit, _model  # noqa: E402
from bimforge.blender import ADDON, build_addon  # noqa: E402

SQ_M_PER_SQ_FT = (1200.0 / 3937.0) ** 2


def _import_meshes(f):
    """Each IFC product's world mesh as a Blender object, a material per
    IfcSurfaceStyle as Bonsai makes them (the Bonsai stand-in)."""
    s = ifcopenshell.geom.settings()
    s.set("use-world-coords", True)
    it = ifcopenshell.geom.iterator(s, f)
    assert it.initialize()
    while True:
        sh = it.get()
        v = sh.geometry.verts
        t = sh.geometry.faces
        me = bpy.data.meshes.new(sh.name or "el")
        me.from_pydata([v[i:i + 3] for i in range(0, len(v), 3)], [],
                       [t[i:i + 3] for i in range(0, len(t), 3)])
        # one material per product: its IfcSurfaceStyle, named and coloured
        # as Bonsai names and colours it
        for style in _styles(f.by_id(sh.id))[:1]:
            mat = bpy.data.materials.new(style.Name or "style")
            c = style.Styles[0].SurfaceColour
            mat.diffuse_color = (c.Red, c.Green, c.Blue, 1.0)
            me.materials.append(mat)
        bpy.context.scene.collection.objects.link(
            bpy.data.objects.new(sh.name or "el", me))
        if not it.next():
            break


def _styles(product):
    return [st for rep in product.Representation.Representations
            for item in rep.Items for si in item.StyledByItem
            for st in si.Styles if st.is_a("IfcSurfaceStyle")]


def _schedule_deck(f, path):
    """A 4D schedule in the fixture: the deck is poured 2027-09-15."""
    import ifcopenshell.api
    run = ifcopenshell.api.run
    ws = run("sequence.add_work_schedule", f, name="baseline")
    t = run("sequence.add_task", f, work_schedule=ws, name="Deck pour")
    t.PredefinedType = "CONSTRUCTION"
    tt = run("sequence.add_task_time", f, task=t)
    run("sequence.edit_task_time", f, task_time=tt,
        attributes={"ScheduleStart": "2027-09-15T08:00:00"})
    (deck,) = [p for p in f.by_type("IfcSlab") if p.Name == "deck"]
    run("sequence.assign_product", f, relating_product=deck,
        related_object=t)
    f.write(str(path))


@pytest.fixture(scope="module")
def addon(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("addon")
    with zipfile.ZipFile(build_addon(tmp / f"{ADDON}.zip")) as z:
        assert sorted(z.namelist()) == [f"{ADDON}/__init__.py",
                                        f"{ADDON}/alignment_station.py",
                                        f"{ADDON}/developed.py",
                                        f"{ADDON}/schedule_state.py"]
        z.extractall(tmp / "addons")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sys.path.insert(0, str(tmp / "addons"))
    mod = importlib.import_module(ADDON)
    mod.register()
    m, al, prof = _model()
    path, f = _emit(tmp, m)
    _schedule_deck(f, path)
    from bimforge.bim.linear_ref import annotate
    assert annotate(str(path))["elements"] == 1      # the deck's station range
    _import_meshes(f)
    props = bpy.context.scene.bimforge_section
    props.source = "FILE"
    props.ifc_path = str(path)
    assert bpy.ops.bimforge.section_load() == {"FINISHED"}
    yield mod, m, al, prof
    mod.unregister()
    sys.path.remove(str(tmp / "addons"))


def test_load_draws_the_axis_and_reads_feet(addon):
    mod, m, al, _ = addon
    props = bpy.context.scene.bimforge_section
    st = mod._stationer(props)
    assert st.name == "ML" and st.station_unit == "ft"
    axis = bpy.data.objects[mod.AXIS]
    assert len(axis.data.splines[0].points) > 10
    assert mod._STATE["frame"].station == pytest.approx(st.start_station)


def test_the_cut_is_square_to_the_alignment_and_fills_the_deck(addon):
    mod, m, al, _ = addon
    props = bpy.context.scene.bimforge_section
    st = mod._stationer(props)
    props.goto = 1123.4                       # mid-curve, feet
    assert bpy.ops.bimforge.section_goto() == {"FINISHED"}
    fr = mod._STATE["frame"]
    assert st.format_station(fr.station) == "11+23.40"
    me = bpy.data.objects[mod.CUT].data
    assert len(me.vertices) >= 4 and len(me.polygons) >= 2
    from mathutils import Vector
    p, n = Vector(fr.point), Vector(fr.plan_tangent)
    assert max(abs((v.co - p).dot(n)) for v in me.vertices) < 1e-3
    area = sum(poly.area for poly in me.polygons)
    assert area == pytest.approx(12.0 * 3.0 * SQ_M_PER_SQ_FT, rel=1e-3)


def test_camera_looks_down_the_alignment(addon):
    mod, *_ = addon
    props = bpy.context.scene.bimforge_section
    props.position = 0.5
    fr = mod._STATE["frame"]
    cam = bpy.data.objects[mod.CAM]
    look = -(cam.matrix_world.to_3x3().col[2])
    assert look.dot(fr.plan_tangent) == pytest.approx(1.0)
    assert cam.matrix_world.to_3x3().col[1].z == pytest.approx(1.0)  # up
    props.look = "BACK"
    look = -(cam.matrix_world.to_3x3().col[2])
    assert look.dot(fr.plan_tangent) == pytest.approx(-1.0)
    props.look = "AHEAD"


def test_step_and_timeline(addon):
    mod, *_ = addon
    scene = bpy.context.scene
    props = scene.bimforge_section
    st = mod._stationer(props)
    props.position = 0.0
    props.step = 50.0
    bpy.ops.bimforge.section_step(direction=1)
    assert st.convert(mod._STATE["frame"].station - st.start_station, "ft") \
        == pytest.approx(50.0)
    props.follow_frames = True
    scene.frame_start, scene.frame_end = 1, 101
    scene.frame_set(51)
    assert props.position == pytest.approx(0.5)
    props.follow_frames = False


def test_bearing_text():
    from bimforge.blender.alignment_section import _bearing
    assert _bearing(10.0) == "N 10-00-00 E"
    assert _bearing(180 - 82.844566666) == "S 82-50-40 E"
    assert _bearing(330.5) == "N 29-30-00 W"


def _box(name, fr, x0, x1, z0, z1, mats=(), split=None):
    """A box across the alignment at frame `fr`: x right, z up, 2 m long.
    `split` (an x) gives the faces right of it material slot 1."""
    from mathutils import Vector
    p, t = Vector(fr.point), Vector(fr.plan_tangent)
    r, up = t.cross(Vector((0, 0, 1))), Vector((0, 0, 1))
    xs = [x0, x1] if split is None else [x0, split, x1]
    verts, faces = [], []
    for i, (a, b) in enumerate(zip(xs, xs[1:])):
        base = len(verts)
        for x, y, z in [(a, -1, z0), (b, -1, z0), (b, 1, z0), (a, 1, z0),
                        (a, -1, z1), (b, -1, z1), (b, 1, z1), (a, 1, z1)]:
            verts.append(p + r * x + t * y + up * z)
        faces += [[base + j for j in f] for f in
                  [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                   (2, 3, 7, 6), (3, 0, 4, 7)]]
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    for m in mats:
        me.materials.append(m)
    if split is not None:
        for poly in me.polygons[6:]:
            poly.material_index = 1
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def _mat(name, rgb=None):
    mat = bpy.data.materials.new(name)
    if rgb is not None:
        mat.diffuse_color = (*rgb, 1.0)
    return mat


def test_each_item_fills_per_its_styling(addon):
    mod, *_ = addon
    props = bpy.context.scene.bimforge_section
    props.goto = 1200.0
    bpy.ops.bimforge.section_goto()
    fr = mod._STATE["frame"]
    ft = 1200.0 / 3937.0
    hma = (0.10, 0.10, 0.11)
    made = [
        # styled: an asphalt overlay whose material carries its colour
        _box("Overlay", fr, -1.8, 1.8, 0.0, 0.1, [_mat("HMA Type A", hma)]),
        # unstyled, named for what it is: gravel base under the deck
        _box("AB Class 2 base", fr, -2.0, 2.0, -1.2, -0.95),
        # default-grey material named for what it is: a rebar "bar"
        _box("bar", fr, -0.5, 0.5, -0.5, -0.45, [_mat("Reinforcing Steel")]),
        # one item, two styles: concrete left of x = 3, steel plate right
        _box("Abutment", fr, 2.5, 3.5, -1.0, 0.0,
             [_mat("Concrete", (0.75, 0.73, 0.68)), _mat("Steel")], split=3.0),
    ]
    try:
        props.fill_style = "STYLE"
        bpy.ops.bimforge.section_cut()
        me = bpy.data.objects[mod.CUT].data
        area: dict[str, float] = {}
        for poly in me.polygons:
            name = me.materials[poly.material_index].name
            area[name] = area.get(name, 0.0) + poly.area
        colour = {m.name: tuple(m.diffuse_color[:3]) for m in me.materials}
        # the deck carries bimforge's Concrete IfcSurfaceStyle; the
        # abutment's left half is a Concrete material too, so they share a
        # fill. The rebar box sits inside the deck: both fills are counted.
        assert area["Section · Concrete"] == pytest.approx(
            12 * 3 * ft * ft + 0.5 * 1.0, rel=1e-3)
        assert colour["Section · Concrete"] == pytest.approx((0.75, 0.73, 0.68))
        assert area["Section · HMA Type A"] == pytest.approx(3.6 * 0.1, rel=1e-3)
        assert colour["Section · HMA Type A"] == pytest.approx(hma)
        assert area["Section · Gravel"] == pytest.approx(4.0 * 0.25, rel=1e-3)
        assert colour["Section · Gravel"] == pytest.approx((0.62, 0.55, 0.42))
        assert area["Section · Reinforcing Steel"] == pytest.approx(
            1.0 * 0.05, rel=1e-3)
        assert area["Section · Structural Steel"] == pytest.approx(
            0.5 * 1.0, rel=1e-3)
        # coplanar fills are layered: the small rebar fill stands nearer the
        # camera than the deck around it, so it never z-fights; all of them
        # stay behind the near clip
        from mathutils import Vector
        look, p0 = Vector(fr.plan_tangent), Vector(fr.point)
        depth = {}
        for poly in me.polygons:
            depth.setdefault(me.materials[poly.material_index].name,
                             []).append((poly.center - p0).dot(look))
        rebar = max(depth["Section · Reinforcing Steel"])
        conc = min(depth["Section · Concrete"])
        assert rebar < conc <= 0.0
        assert -mod.NEAR_GAP < rebar
        # every cut edge is outlined by a flat strip, which renders
        lines = bpy.data.objects[mod.LINES].data
        assert len(lines.polygons) >= len(me.edges) // 2
        assert max(abs((v.co - p0).dot(look)) for v in lines.vertices) \
            < mod.NEAR_GAP
        props.fill_style = "SINGLE"
        bpy.ops.bimforge.section_cut()
        me = bpy.data.objects[mod.CUT].data
        assert [m.name for m in me.materials] == ["Section Cut"]
    finally:
        for ob in made:
            bpy.data.objects.remove(ob)
        props.fill_style = "STYLE"


def test_palette_agrees_with_the_ifc_styles():
    from bimforge.author import ifc_styles as S
    from bimforge.blender.alignment_section import FILL_PALETTE, classify
    rgb = {k: v for k, _p, v in FILL_PALETTE}
    for kind, src in [("Concrete", S._CONCRETE), ("Reinforcing Steel", S._REBAR),
                      ("Structural Steel", S._STEEL), ("Earthwork", S._EARTH),
                      ("Timber", S._TIMBER)]:
        assert rgb[kind] == pytest.approx(tuple(src["rgb"]))
    assert classify("S-REBAR")[0] == "Reinforcing Steel"
    assert classify("IfcReinforcingBar/B1")[0] == "Reinforcing Steel"
    assert classify("AC Pavement")[0] == "Asphalt"
    assert classify("Class 2 AB")[0] == "Gravel"
    assert classify("RSP Class IV")[0] == "Gravel"
    assert classify("IfcSlab/Deck")[0] == "Concrete"
    assert classify("S-EW-FILL")[0] == "Earthwork"
    assert classify("Widget") is None
    assert classify("Existing reinforced concrete (Br 12-3456), to be removed")[0] \
        == "Existing (to remove)"
    assert classify("existing 12-3456 slab stage 1")[0] == "Existing (to remove)"
    assert classify("Structure backfill (bridge)")[0] == "Earthwork"
    assert classify("Concrete Backfill")[0] == "Concrete"


def test_offsets_ruler_locate_and_inquire(addon):
    mod, m, al, prof = addon
    scene = bpy.context.scene
    props = scene.bimforge_section
    st = mod._stationer(props)
    props.goto = 1200.0
    bpy.ops.bimforge.section_goto()
    fr = mod._STATE["frame"]
    k = m.ctx.ft_to_m
    # ruler: CL plus 10-ft ticks out to the view's half width, labelled
    props.ruler, props.ruler_step, props.width = True, 10.0, 40.0
    labels = sorted(o.data.body for o in bpy.data.objects
                    if o.name.startswith(mod.LABEL))
    half_ft = 20.0 / k
    n = int(half_ft // 10)
    assert len(labels) == 2 * n + 1 and "CL" in labels
    assert f"{10 * n}' Lt" in labels and f"{10 * n}' Rt" in labels
    # locate 6 ft Rt: on the deck (12 ft wide, top at grade) -> top EL = PG
    props.pt_offset, props.pt_side = 5.0, "RT"
    assert bpy.ops.bimforge.section_offset_locate() == {"FINISHED"}
    d, off, z, hit = mod._STATE["point"]
    assert off == pytest.approx(-5.0 * k)
    n_, e_ = al.station_offset(1200.0, 5.0, "Rt")
    from bimforge.author.sweep import to_model
    want = [c * k for c in to_model(m.ctx, n_, e_, prof.elev(1200.0))]
    assert tuple(scene.cursor.location) == pytest.approx(want, abs=1e-3)
    assert hit is not None and hit[1] == "deck"
    # the deck top is the grade at CL, falling 0 here (flat section)
    assert st.elevation_m(hit[0]) / k == pytest.approx(prof.elev(1200.0),
                                                       abs=1e-3)
    text = mod._point_text(props, st)
    assert text.startswith("Sta 12+00.00, 5.00 Rt") and "top EL" in text
    # inquire: move the cursor 20 ft Lt at another station and cut there
    scene.cursor.location = st.point_at((1300.0 - al.s_start) * k, 20.0 * k)
    assert bpy.ops.bimforge.section_offset_inquire(cut_there=True) \
        == {"FINISHED"}
    assert mod._point_text(props, st).startswith("Sta 13+00.00, 20.00 Lt")
    assert st.convert(mod._STATE["frame"].station, "ft") == pytest.approx(
        1300.0)
    assert mod._STATE["point"][3] is None          # off the 12-ft deck
    props.ruler = False
    assert not [o for o in bpy.data.objects if o.name.startswith(mod.LABEL)]


def test_the_date_filter_hides_what_is_not_built_and_skips_its_cut(addon):
    mod, *_ = addon
    scene = bpy.context.scene
    props = scene.bimforge_section
    assert mod._STATE["events"] == ["2027-09-15"]
    deck = bpy.data.objects["deck"]
    props.position = 0.5
    assert len(bpy.data.objects[mod.CUT].data.polygons) > 0
    props.date_filter = True
    props.date = "2027-06-15"                      # before the pour
    # the alignment's own axis object (as Bonsai loads it) is unscheduled
    assert mod._STATE["counts"] == {"standing": 1, "not yet built": 1,
                                    "removed": 0, "unmatched": 0}
    assert not deck.visible_get() and deck.hide_render
    assert len(bpy.data.objects[mod.CUT].data.polygons) == 0
    bpy.ops.bimforge.section_date_step(event=1)    # next event: the pour
    assert props.date == "2027-09-15"
    assert deck.visible_get() and not deck.hide_render
    assert len(bpy.data.objects[mod.CUT].data.polygons) > 0
    bpy.ops.bimforge.section_date_step(days=-1)
    assert props.date == "2027-09-14" and not deck.visible_get()
    props.date_filter = False                      # everything back
    assert deck.visible_get() and not mod._STATE["hidden"]


def test_go_to_selected_reads_the_station_from_the_ifc(addon):
    mod, m, al, _prof = addon
    props = bpy.context.scene.bimforge_section
    deck = bpy.data.objects["deck"]
    bpy.context.view_layer.objects.active = deck
    props.position = 0.0
    assert bpy.ops.bimforge.section_to_selected() == {"FINISHED"}
    st = mod._stationer(props)
    k = m.ctx.ft_to_m
    # the deck runs 1010 -> 1360: the middle of its range, read off the IFC
    want = (0.5 * (1010.0 + 1360.0) - al.s_start) * k
    assert props.position * st.length == pytest.approx(want, abs=1e-3)
    f, sts = mod._open(props)
    hit = mod.element_station(f, sts, f.by_type("IfcSlab")[0].GlobalId)
    assert hit[2].startswith("deck: 10+10.00 to 13+60.00")


def test_developed_elevation_in_its_own_scene(addon):
    """Develop along the line itself (offset 0) through the fixture deck: a
    3 ft deep longitudinal section, its true length along the line."""
    pytest.importorskip("shapely")
    mod, m, al, _prof = addon
    home = bpy.context.scene
    props = home.bimforge_section
    props.dev_from, props.dev_to = "10+20", "13+50"
    props.dev_offset, props.dev_side, props.dev_look = 0.0, "LT", "LEFT"
    props.dev_depth = 10.0
    try:
        assert bpy.ops.bimforge.developed_build() == {"FINISHED"}
        sc = bpy.data.scenes[mod.DEV_SCENE]
        info = sc["bimforge_developed"]
        assert info["length"] == pytest.approx(330.0, abs=0.05)   # on the line
        cuts = [o for o in sc.objects if o.name.startswith("Developed cut")]
        area = sum(p.area for o in cuts for p in o.data.polygons) / SQ_M_PER_SQ_FT
        assert area == pytest.approx(3.0 * 330.0, rel=5e-3)
        assert sc.camera is not None and sc.camera.data.type == "ORTHO"
        assert any(o.type == "FONT" and o.data.body == "11+00" for o in sc.objects)
    finally:
        if bpy.context.window is not None:
            bpy.context.window.scene = home


def test_export_section_dxf_is_the_section_the_camera_shows(addon, tmp_path):
    """No From / To: the cross section at the slider's station, the view's
    width and look, to a DXF sheet."""
    pytest.importorskip("shapely")
    ezdxf = pytest.importorskip("ezdxf")
    mod, m, al, _prof = addon
    props = bpy.context.scene.bimforge_section
    props.dev_from = props.dev_to = ""
    props.position = 0.5
    props.look = "AHEAD"
    view, f = mod.section_view_def(props)
    st = mod._stationer(props)
    assert view.station == pytest.approx(st.convert(mod._STATE["frame"].station, "ft"))
    assert view.width == pytest.approx(st.to_unit(props.width, "ft"))
    out = tmp_path / "sec.dxf"
    assert bpy.ops.bimforge.section_dxf(filepath=str(out)) == {"FINISHED"}
    doc = ezdxf.readfile(str(out))
    (lay,) = [x for x in doc.layouts if x.name != "Model"]
    titles = [e.dxf.text for e in lay if e.dxftype() == "TEXT"]
    assert any("SECTION AT STA" in t and "LOOKING AHEAD" in t for t in titles)
    assert any(e.dxf.layer.startswith("E-CUT-") for e in doc.modelspace())
    # the developed export still asks for its range, and says where to go
    with pytest.raises(ValueError, match="Export Section DXF"):
        mod.developed_view(props)


def test_exit_leaves_the_camera_and_the_developed_scene(addon):
    mod, *_ = addon
    win = bpy.context.window
    if win is None:
        pytest.skip("no window in background mode")
    home = win.scene
    mod._STATE["home_scene"] = home.name
    dev = bpy.data.scenes.get(mod.DEV_SCENE) or bpy.data.scenes.new(mod.DEV_SCENE)
    win.scene = dev
    mod.exit_views(bpy.context)
    assert win.scene == home
