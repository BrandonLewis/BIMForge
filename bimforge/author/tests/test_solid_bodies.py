"""Solid bodies: mesh_topology and the post-emit solid-body gate check.

What a viewer renders and a section cuts must be solid: one closed manifold
shell per element (or several, not touching, when declared "solids"), with
terrain-like surfaces exempt only when declared "surface".
"""
from __future__ import annotations

import uuid

import pytest

from bimforge.bim.ifc_mesh import mesh_topology

CUBE_V = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
          (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
CUBE_F = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
          (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]


def _shift(v, dx=0.0, dz=0.0):
    return [(x + dx, y, z + dz) for x, y, z in v]


def _two(dx):
    v = list(CUBE_V) + _shift(CUBE_V, dx)
    f = list(CUBE_F) + [(a + 8, b + 8, c + 8) for a, b, c in CUBE_F]
    return v, f


def test_a_cube_is_one_closed_body():
    t = mesh_topology(CUBE_V, CUBE_F)
    assert t == {"triangles": 12, "open_edges": 0, "nonmanifold_edges": 0,
                 "nonmanifold_vertices": 0, "components": 1,
                 "empty_components": 0, "closed": True}


def test_coincident_corners_are_welded():
    # each triangle with its own three corners, as a kernel may emit them
    v = [CUBE_V[i] for tri in CUBE_F for i in tri]
    f = [(3 * k, 3 * k + 1, 3 * k + 2) for k in range(12)]
    assert mesh_topology(v, f)["closed"]


def test_a_fan_across_a_collinear_vertex_is_still_closed():
    # a 2 x 1 x 1 block whose bottom/top long edges carry a midpoint vertex
    # (a stepped-top prism ring); the caps are fanned from vertex 0, so one
    # cap triangle is (0, mid, far) - zero area, but it closes the shell
    ring = [(0, 0), (1, 0), (2, 0), (2, 1), (0, 1)]
    n = len(ring)
    v = [(x, y, 0.0) for x, y in ring] + [(x, y, 1.0) for x, y in ring]
    f = [(0, i + 1, i) for i in range(1, n - 1)]               # bottom fan
    f += [(n, n + i, n + i + 1) for i in range(1, n - 1)]      # top fan
    for i in range(n):
        j = (i + 1) % n
        f += [(i, j, j + n), (i, j + n, i + n)]
    t = mesh_topology(v, f)
    assert t["open_edges"] == 0 and t["nonmanifold_edges"] == 0
    assert t["closed"] and t["components"] == 1


def test_an_open_box_is_not_closed():
    t = mesh_topology(CUBE_V, CUBE_F[2:])          # no bottom
    assert t["open_edges"] == 4 and not t["closed"]


def test_apart_cubes_are_two_closed_pieces():
    t = mesh_topology(*_two(3.0))
    assert t["closed"] and t["components"] == 2


def test_touching_cubes_are_not_a_solid():
    # a stack of cells: the shared face is drawn twice, its edges used 4x
    t = mesh_topology(*_two(1.0))
    assert t["nonmanifold_edges"] > 0 and not t["closed"]
    assert t["components"] == 1


def test_a_face_doubled_back_encloses_nothing():
    # one quad drawn both ways round (no shared diagonal): every edge is
    # used twice, so only the empty volume shows it is not a body
    v = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
    f = [(0, 1, 2), (0, 2, 3), (0, 2, 1), (0, 3, 2)]
    t = mesh_topology(v, f)
    assert t["open_edges"] == 0 and t["empty_components"] == 1
    assert not t["closed"]


def test_zero_thickness_cells_are_caught():
    # a grid "solid" whose bottom is clamped to its top in places
    flat = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
    v = flat + flat                                  # top == bottom
    f = [(0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6)]
    t = mesh_topology(v, f)
    assert not t["closed"]


# ------------------------------------------------------------- the gate
ifcopenshell = pytest.importorskip("ifcopenshell")

from bimforge.author.emit_ifc import emit_ifc  # noqa: E402
from bimforge.author.gate import (_ifc_solid_body_check,  # noqa: E402
                                  run_post)
from bimforge.author.model import Element, StructureModel  # noqa: E402
from bimforge.author.primitives import Prism  # noqa: E402
from bimforge.author.project import ProjectContext  # noqa: E402


def _mesh(v, f):
    return {"kind": "mesh", "units": "ft", "verts": [tuple(map(float, p))
                                                     for p in v],
            "tris": [tuple(t) for t in f]}


def _model(mode="warn"):
    ctx = ProjectContext(name="Solids", schema="IFC4X3_ADD2", epsg=2226,
                         base_e=6_594_000.0, base_n=1_943_000.0, base_h=0.0,
                         guid_ns=uuid.UUID(int=77))
    m = StructureModel("solids", ctx)
    m.solid_body_gate = mode
    m.add(Element.from_geometry(
        "footing", Prism("footing", [(0, 0), (10, 0), (10, 4), (0, 4)],
                         z_bot=0.0, z_top=2.0), ifc_class="IfcFooting"))
    m.add(Element("backfill cells", "IfcEarthworksFill",
                  geometry=_mesh(*_two(1.0))))           # touching boxes
    m.add(Element("sheet pans", "IfcWall", geometry=_mesh(*_two(3.0)),
                  body="solids"))                        # apart: allowed
    m.add(Element("ties", "IfcWall", geometry=_mesh(*_two(3.0))))   # not 1
    m.add(Element("grade", "IfcGeographicElement",
                  geometry=_mesh(CUBE_V, CUBE_F[2:]), body="surface"))
    return m


def test_the_check_names_exactly_the_non_solids(tmp_path):
    m = _model()
    out = tmp_path / "s.ifc"
    emit_ifc(m, str(out))
    msgs = _ifc_solid_body_check(m, str(out))
    assert len(msgs) == 2
    assert msgs[0].startswith("backfill cells (IfcEarthworksFill): not a "
                              "solid body") and "shared by 3+" in msgs[0]
    assert msgs[1].startswith("ties (IfcWall)") and "2 separate pieces" in \
        msgs[1]


def test_warn_keeps_outputs_and_error_deletes_them(tmp_path):
    for mode, kept in (("warn", True), ("error", False), ("off", True)):
        m = _model(mode)
        out = tmp_path / f"{mode}.ifc"
        emit_ifc(m, str(out))
        rep = run_post(m, {"ifc": str(out)})
        assert out.exists() == kept
        if mode == "warn":
            assert rep.passed and len(rep.warnings) == 2
            assert "warnings (2)" in rep.format("post")
        elif mode == "error":
            assert not rep.passed and len(rep.failures) == 2
        else:
            assert rep.passed and not rep.warnings


def test_body_kind_is_validated():
    with pytest.raises(ValueError, match="body"):
        Element("x", "IfcWall", body="shell")


def test_spec_settings_configure_the_check():
    from bimforge.author.gate import configure_solid_bodies
    m = _model()
    m.element("ties").body = "solid"
    configure_solid_bodies(m, {"gate": {"solid_bodies": "error"},
                               "bodies": [{"match": "^ties$", "body": "solids"},
                                          {"match": ".", "body": "surface"}]})
    assert m.solid_body_gate == "error"
    assert m.element("ties").body == "solids"
    assert m.element("sheet pans").body == "solids"      # family's own stands
    assert m.element("footing").body == "surface"        # first match wins
    with pytest.raises(ValueError):
        configure_solid_bodies(m, {"gate": {"solid_bodies": "loud"}})
    with pytest.raises(ValueError):
        configure_solid_bodies(m, {"bodies": [{"match": "x", "body": "air"}]})


def test_a_void_tangent_to_the_section_edge_is_a_pinch_not_a_crack():
    import math
    from bimforge.author.primitives import SectionPrism
    # a 3 ft opening whose invert sits exactly on the bottom of the face
    # (the D89 default D/3 + 6 in centre for a 36 in pipe): the concrete is
    # zero-thick there. The shell must close (no T-junction cracks); the
    # one remaining non-manifold edge IS the pinch, and is reported.
    circ = [(5.0 + 1.5 * math.cos(2 * math.pi * i / 32),
             1.5 + 1.5 * math.sin(2 * math.pi * i / 32)) for i in range(32)]
    sp = SectionPrism("stem", [(0, 0), (10, 0), (10, 6), (0, 6)], 1.0,
                      voids=[circ])
    d = sp.body_solids()[0]
    t = mesh_topology(d["verts"], d["tris"])
    assert t["open_edges"] == 0 and t["nonmanifold_edges"] == 1
