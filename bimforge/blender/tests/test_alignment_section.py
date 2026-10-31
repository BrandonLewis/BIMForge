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
    """Each IFC product's world mesh as a Blender object (Bonsai stand-in)."""
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
        bpy.context.scene.collection.objects.link(
            bpy.data.objects.new(sh.name or "el", me))
        if not it.next():
            break


@pytest.fixture(scope="module")
def addon(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("addon")
    with zipfile.ZipFile(build_addon(tmp / f"{ADDON}.zip")) as z:
        assert sorted(z.namelist()) == [f"{ADDON}/__init__.py",
                                        f"{ADDON}/alignment_station.py"]
        z.extractall(tmp / "addons")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sys.path.insert(0, str(tmp / "addons"))
    mod = importlib.import_module(ADDON)
    mod.register()
    m, al, prof = _model()
    path, f = _emit(tmp, m)
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
