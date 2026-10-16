"""bimforge.bim.ifc_mesh: iterator-based measured-geometry reader."""
import math
import uuid

import pytest

pytest.importorskip("ifcopenshell")

from bimforge.author.model import Element, StructureModel
from bimforge.author.emit_ifc import emit_ifc
from bimforge.author.primitives import Prism
from bimforge.author.project import ProjectContext
from bimforge.bim.ifc_mesh import _accumulate, mesh_leg, mesh_volume, plan_area

# Metres per US survey foot (1200/3937); the literal matches
# project.US_SURVEY_FT_TO_M bit-for-bit and is asserted against
# ProjectContext.ft_to_m below so it cannot drift.
FT = 0.30480060960121924

# The unit-cube tessellation used by several tests: 12 triangles, volume 1,
# projected plan area 1.
CUBE_V = [0,0,0, 1,0,0, 1,1,0, 0,1,0, 0,0,1, 1,0,1, 1,1,1, 0,1,1]
CUBE_F = [0,2,1, 0,3,2,          # bottom
          4,5,6, 4,6,7,          # top
          0,1,5, 0,5,4,          # front
          1,2,6, 1,6,5,          # right
          2,3,7, 2,7,6,          # back
          3,0,4, 3,4,7]          # left


def _offset_cube(dx, dy, dz):
    return [c + (dx, dy, dz)[i % 3] for i, c in enumerate(CUBE_V)]


def _ctx(name="Mesh Fixture"):
    return ProjectContext(name=name, epsg=2226,
                          base_e=6_594_000.0, base_n=1_943_000.0, base_h=200.0,
                          guid_ns=uuid.UUID("5a0e2c4d-9b17-4f36-8d25-3c1a7e9b0f42"))


def _emit(m, tmp_path, name="m.ifc"):
    out = tmp_path / name
    emit_ifc(m, str(out))
    return str(out)


def test_mesh_volume_and_plan_area_unit_cube():
    assert mesh_volume(CUBE_V, CUBE_F) == pytest.approx(1.0)
    assert plan_area(CUBE_V, CUBE_F) == pytest.approx(1.0)


def test_mesh_volume_survives_large_world_coordinates():
    # use-world-coords bakes state-plane offsets into the vertices; a raw
    # signed-tet sum over such positions catastrophically cancels. The unit
    # cube is z-rotated 0.3 rad (volume and plan area both stay 1.0) and
    # offset by FRACTIONAL state-plane-scale coordinates — axis-aligned
    # integer offsets happen to cancel exactly in float64 and would not bind
    # the in-frame shift. Pre-fix this mesh measured relerr ~8.8; post-fix
    # ~1e-11.
    c, s = math.cos(0.3), math.sin(0.3)
    dx, dy, dz = 2_009_876.54321, 578_431.0987, 123_456.789
    v = []
    for i in range(0, len(CUBE_V), 3):
        x, y, z = CUBE_V[i:i + 3]
        v += [c * x - s * y + dx, s * x + c * y + dy, z + dz]
    assert mesh_volume(v, CUBE_F) == pytest.approx(1.0, rel=1e-9)
    assert plan_area(v, CUBE_F) == pytest.approx(1.0, rel=1e-9)


def test_accumulate_sums_volumes_and_unions_bboxes():
    # ifcopenshell may or may not merge a product's representation items into
    # one iterator shape, so the multi-shape branch is pinned directly: two
    # unit cubes at different offsets folded under the SAME guid.
    acc = {}
    _accumulate(acc, "G1", "IfcFooting", _offset_cube(0.0, 0.0, 0.0), CUBE_F)
    _accumulate(acc, "G1", "IfcFooting", _offset_cube(3.0, 0.0, 2.0), CUBE_F)
    a = acc["G1"]
    assert a["type"] == "IfcFooting"
    assert a["vol"] == pytest.approx(2.0)
    assert a["area"] == pytest.approx(2.0)
    assert list(a["lo"]) == pytest.approx([0.0, 0.0, 0.0])
    assert list(a["hi"]) == pytest.approx([4.0, 1.0, 3.0])


def test_accumulate_ignores_empty_meshes():
    acc = {}
    _accumulate(acc, "G1", "IfcFooting", [], [])
    assert acc == {}


def test_mesh_leg_measures_a_box(tmp_path):
    assert FT == _ctx().ft_to_m   # keep the module constant honest
    m = StructureModel("mesh", _ctx())
    p = Prism("box footing", [(-2, -2), (2, -2), (2, 2), (-2, 2)],
              z_bot=0.0, z_top=2.0, ifc="IfcFooting")
    m.add(Element.from_geometry(p.name, p, ifc_class="IfcFooting"))
    leg = mesh_leg(_emit(m, tmp_path))
    assert len(leg) == 1
    (gid, info), = leg.items()
    assert gid == m.ctx.guid("element/box footing")
    assert info["name"] == "box footing"
    assert info["ifc_class"] == "IfcFooting"
    mm = info["mesh"]
    assert mm["volume_m3"] == pytest.approx(32.0 * FT**3, rel=1e-6)
    assert mm["plan_area_m2"] == pytest.approx(16.0 * FT**2, rel=1e-6)
    assert mm["len_m"] == pytest.approx(4.0 * FT, rel=1e-6)
    assert mm["wid_m"] == pytest.approx(4.0 * FT, rel=1e-6)
    assert mm["hgt_m"] == pytest.approx(2.0 * FT, rel=1e-6)
    assert mm["z_max_m"] - mm["z_min_m"] == pytest.approx(2.0 * FT, rel=1e-6)


def test_mesh_leg_aggregates_multiple_shapes_per_product(tmp_path):
    # One element carrying TWO disjoint prisms. The iterator may merge a
    # product's items into ONE shape, so this pins the end-to-end totals
    # (sum/union); the accumulate branch itself is unit-tested above.
    m = StructureModel("mesh", _ctx())
    m.add(Element("twin blocks", ifc_class="IfcFooting", geometry=[
        {"kind": "prism", "units": "ft",
         "base": [(0, 0), (1, 0), (1, 1), (0, 1)], "z_bot": 0.0, "z_top": 1.0},
        {"kind": "prism", "units": "ft",
         "base": [(3, 0), (4, 0), (4, 1), (3, 1)], "z_bot": 0.0, "z_top": 1.0}]))
    leg = mesh_leg(_emit(m, tmp_path))
    (info,) = leg.values()
    assert info["mesh"]["volume_m3"] == pytest.approx(2.0 * FT**3, rel=1e-6)
    assert info["mesh"]["plan_area_m2"] == pytest.approx(2.0 * FT**2, rel=1e-6)
    assert info["mesh"]["len_m"] == pytest.approx(4.0 * FT, rel=1e-6)   # 0..4 union
    assert info["mesh"]["wid_m"] == pytest.approx(1.0 * FT, rel=1e-6)


def test_qto_only_elements_are_absent_and_empty_file_is_empty(tmp_path):
    # A Qto-only element (quantities, no geometry) never reaches the iterator
    # and must simply be ABSENT — legitimate authoring, not an error. A file
    # with ONLY such elements yields {}.
    m = StructureModel("mesh", _ctx())
    m.add(Element("phantom bolt group", ifc_class="IfcMechanicalFastener",
                  quantities={"count": 4, "length_ft": 6.0}))
    assert mesh_leg(_emit(m, tmp_path, "qto-only.ifc")) == {}

    m2 = StructureModel("mesh2", _ctx("Mesh Fixture 2"))
    p = Prism("real box", [(0, 0), (1, 0), (1, 1), (0, 1)], 0.0, 1.0)
    m2.add(Element.from_geometry(p.name, p, ifc_class="IfcFooting"))
    m2.add(Element("phantom", ifc_class="IfcMechanicalFastener",
                   quantities={"count": 2}))
    leg = mesh_leg(_emit(m2, tmp_path, "mixed.ifc"))
    assert set(leg) == {m2.ctx.guid("element/real box")}
