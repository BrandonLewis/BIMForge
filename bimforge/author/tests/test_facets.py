"""bimforge.author.facets: coplanar facet merging for the IFC brep writer."""
import math
import uuid

import pytest

from bimforge.author.facets import facet_plane, merge_coplanar_facets

# a unit cube, outward-wound (the same tessellation test_ifc_mesh uses)
_V = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
      (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
_F = [(0, 2, 1), (0, 3, 2),          # bottom
      (4, 5, 6), (4, 6, 7),          # top
      (0, 1, 5), (0, 5, 4),          # front
      (1, 2, 6), (1, 6, 5),          # right
      (2, 3, 7), (2, 7, 6),          # back
      (3, 0, 4), (3, 4, 7)]          # left


def _tris(verts, faces, scale=1.0, shift=(0.0, 0.0, 0.0)):
    return [tuple(tuple(c * scale + s for c, s in zip(verts[i], shift))
                  for i in tri) for tri in faces]


def _ring_normal(ring):
    """Newell normal of a 3D polygon: its direction is the winding sense."""
    nx = ny = nz = 0.0
    for (x0, y0, z0), (x1, y1, z1) in zip(ring, ring[1:] + ring[:1]):
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    return (nx, ny, nz)


def _signed_volume(faces):
    """Divergence-theorem volume of a closed set of planar polygon faces,
    each ring fanned from its first vertex. A hole ring winds against its
    outer, so its signed tetrahedra subtract on their own."""
    vol = 0.0
    for outer, holes in faces:
        for ring in [outer, *holes]:
            a = ring[0]
            for b, c in zip(ring[1:], ring[2:]):
                vol += (a[0] * (b[1] * c[2] - b[2] * c[1])
                        - a[1] * (b[0] * c[2] - b[2] * c[0])
                        + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6.0
    return vol


def test_cube_merges_to_six_faces_with_the_cube_volume():
    faces = merge_coplanar_facets(_tris(_V, _F, scale=2.5))
    assert len(faces) == 6
    assert all(len(outer) == 4 and not holes for outer, holes in faces)
    assert _signed_volume(faces) == pytest.approx(2.5 ** 3)
    # outer loops wind about the OUTWARD normal (+z on the top face)
    top = [outer for outer, _ in faces if all(p[2] == 2.5 for p in outer)]
    assert len(top) == 1
    assert _ring_normal(top[0])[2] > 0


def test_unmergeable_facets_come_back_as_they_were():
    # a tetrahedron: four planes, nothing coplanar
    t = [((0, 0, 0), (1, 0, 0), (0, 1, 0)), ((0, 0, 0), (0, 0, 1), (1, 0, 0)),
         ((0, 0, 0), (0, 1, 0), (0, 0, 1)), ((1, 0, 0), (0, 0, 1), (0, 1, 0))]
    faces = merge_coplanar_facets(t)
    assert [tuple(o) for o, _ in faces] == [tuple(x) for x in t]
    assert all(not h for _, h in faces)


def test_zero_area_facets_are_dropped():
    t = _tris(_V, _F) + [((0, 0, 0), (1, 0, 0), (2, 0, 0))]
    assert len(merge_coplanar_facets(t)) == 6
    assert facet_plane(((0, 0, 0), (1, 0, 0), (2, 0, 0))) is None


def test_a_through_hole_becomes_an_inner_bound():
    """A 4 x 4 x 1 slab with a 2 x 2 square hole, tessellated: the top and
    bottom come back as one face each with one clockwise hole, and the
    volume is 16 - 4 = 12."""
    from shapely.geometry import Polygon
    from shapely.ops import triangulate

    outer = Polygon([(0, 0), (4, 0), (4, 4), (0, 4)])
    hole = Polygon([(1, 1), (3, 1), (3, 3), (1, 3)])
    region = outer.difference(hole)
    # constrained-enough triangulation of the annulus: Delaunay of the
    # vertices, keeping triangles inside the region
    cap = [t for t in triangulate(region) if region.contains(t.centroid)]
    tris = []
    for t in cap:
        (a, b, c) = list(t.exterior.coords)[:3]
        if Polygon([a, b, c]).exterior.is_ccw:
            top = [a, b, c]
        else:
            top = [a, c, b]
        tris.append(tuple((x, y, 1.0) for x, y in top))          # +z out
        tris.append(tuple((x, y, 0.0) for x, y in reversed(top)))  # -z out
    # walls: outer ring CCW (outward), hole ring CW (outward into the hole)
    for ring, ccw in ((list(outer.exterior.coords)[:-1], True),
                      (list(hole.exterior.coords)[:-1], False)):
        pts = ring if ccw else list(reversed(ring))
        for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
            tris.append(((x0, y0, 0), (x1, y1, 0), (x1, y1, 1)))
            tris.append(((x0, y0, 0), (x1, y1, 1), (x0, y0, 1)))
    faces = merge_coplanar_facets(tris)
    caps = [(o, h) for o, h in faces if len({p[2] for p in o}) == 1]
    assert len(caps) == 2
    for o, h in caps:
        assert len(o) == 4 and len(h) == 1 and len(h[0]) == 4
        # the hole winds against the outer
        assert _ring_normal(o)[2] * _ring_normal(h[0])[2] < 0
    assert len(faces) == 2 + 4 + 4
    assert _signed_volume(faces) == pytest.approx(12.0)


def test_merged_boundary_keeps_a_neighbours_vertex():
    """Two coplanar facets whose shared edge ends at a vertex another face
    uses: merging must not drop that vertex from the merged boundary, or the
    shell would open there. A box whose top is split into two quads by a
    mid-edge vertex that the FRONT face also uses."""
    verts = list(_V) + [(0.5, 0, 1), (0.5, 1, 1)]          # 8, 9 on the top
    faces = [(0, 2, 1), (0, 3, 2),                          # bottom
             (4, 5, 8), (4, 8, 7), (8, 9, 7), (5, 6, 9), (5, 9, 8),  # top
             (0, 1, 5), (0, 5, 8), (0, 8, 4),               # front, through 8
             (2, 3, 9), (3, 7, 9), (2, 9, 6),               # back, through 9
             (1, 2, 6), (1, 6, 5), (3, 0, 4), (3, 4, 7)]    # right, left
    tris = _tris(verts, faces)
    out = merge_coplanar_facets(tris)
    top = [o for o, _ in out if all(p[2] == 1 for p in o)]
    assert len(top) == 1
    assert (0.5, 0.0, 1.0) in top[0]          # the front face's vertex stays
    # closed: every directed edge has its reverse (holes none here)
    edges = {}
    for o, _ in out:
        for a, b in zip(o, o[1:] + o[:1]):
            edges[(a, b)] = edges.get((a, b), 0) + 1
    assert all((b, a) in edges for a, b in edges)


def test_emitted_brep_has_merged_faces_and_the_same_volume(tmp_path):
    """Through emit_ifc: a tapered (per-vertex-top) prism is a brep; its
    facets merge to planar faces, ifcopenshell still reads a closed solid of
    the analytic volume."""
    ifcopenshell = pytest.importorskip("ifcopenshell")
    import ifcopenshell.geom
    from bimforge.author.emit_ifc import emit_ifc
    from bimforge.author.model import Element, StructureModel
    from bimforge.author.primitives import Prism
    from bimforge.author.project import ProjectContext
    from bimforge.bim.ifc_mesh import mesh_topology

    ctx = ProjectContext(name="Facets Fixture", epsg=2226,
                         base_e=6_594_000.0, base_n=1_943_000.0,
                         guid_ns=uuid.UUID(int=21))
    m = StructureModel("facets", ctx)
    # a 10 x 4 block whose top slopes from z=3 at y=-2 to z=5 at y=+2
    p = Prism("wedge", [(0, -2), (10, -2), (10, 2), (0, 2)], z_bot=0.0,
              top_z=[3.0, 3.0, 5.0, 5.0], ifc="IfcWall")
    m.add(Element.from_geometry(p.name, p, ifc_class="IfcWall"))
    out = tmp_path / "w.ifc"
    emit_ifc(m, str(out))
    f = ifcopenshell.open(str(out))
    (wall,) = f.by_type("IfcWall")
    (brep,) = [i for r in wall.Representation.Representations
               for i in r.Items if i.is_a("IfcFacetedBrep")]
    assert len(brep.Outer.CfsFaces) == 6          # a wedge has six planes
    sh = ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(), wall)
    t = mesh_topology(sh.geometry.verts, sh.geometry.faces)
    assert t["closed"] and t["components"] == 1
    k = ctx.ft_to_m
    import numpy as np
    v = np.asarray(sh.geometry.verts).reshape(-1, 3)
    tri = np.asarray(sh.geometry.faces).reshape(-1, 3)
    vol = abs(np.einsum("ij,ij->i", v[tri[:, 0]],
                        np.cross(v[tri[:, 1]], v[tri[:, 2]])).sum()) / 6.0
    assert vol / k ** 3 == pytest.approx(p.volume_cf, rel=1e-9)
    assert math.isclose(p.volume_cf, 10 * 4 * 4.0)


def _notch(width):
    """A unit square with a slit down to y = 0.3 at x = 0.5, `width` wide at
    the top: one polygon whose two slit vertices are `width` apart."""
    h = width / 2.0
    P = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0.5 + h, 1, 0), (0.5, 0.3, 0),
         (0.5 - h, 1, 0), (0, 1, 0)]
    return [(P[0], P[1], P[4]), (P[1], P[2], P[4]), (P[2], P[3], P[4]),
            (P[0], P[4], P[5]), (P[0], P[5], P[6])]


def test_a_near_self_touching_merge_is_written_as_its_triangles():
    """A boolean sliver can leave a merged face whose vertices sit a fraction
    of a millimetre from an edge they are not on; a kernel's tolerance closes
    that gap, mis-triangulates the face and opens the shell (a backfill body
    read back 5.9% over its volume). Such a group stays triangles."""
    tight = merge_coplanar_facets(_notch(4e-5))
    assert len(tight) == 5 and all(len(o) == 3 and not h for o, h in tight)
    (face,) = merge_coplanar_facets(_notch(0.1))      # a real notch merges
    assert len(face[0]) == 7


# a 4 x 4 square with a triangular hole whose apex t sits on the edge c-d
_PINCH_P = {"a": (0, 0, 0), "b": (4, 0, 0), "c": (4, 4, 0), "d": (0, 4, 0),
            "h1": (1, 1, 0), "h2": (3, 1, 0), "t": (2, 4, 0)}
_PINCH_T = [("a", "b", "h2"), ("a", "h2", "h1"), ("b", "c", "h2"),
            ("c", "t", "h2"), ("t", "d", "h1"), ("d", "a", "h1")]


def test_a_hole_touching_the_outer_bound_is_written_as_its_triangles():
    """A hole whose vertex lies on the outer bound is valid to OGC, but IFC
    viewers drop the face (web-ifc skips it; #42). minimum_clearance misses
    it, since the shared vertex sits on the edges it is near. Such a group
    stays triangles, with the patch's full area."""
    out = merge_coplanar_facets(
        [tuple(_PINCH_P[k] for k in t) for t in _PINCH_T])
    assert len(out) == 6 and all(len(o) == 3 and not h for o, h in out)
    area = sum(abs((o[1][0] - o[0][0]) * (o[2][1] - o[0][1])
                   - (o[2][0] - o[0][0]) * (o[1][1] - o[0][1])) / 2
               for o, _ in out)
    assert area == pytest.approx(16 - 3)      # the 3 m^2 hole stays open


def _box(x0, x1, y0, y1, z0, z1):
    """A closed, outward-wound box: 12 triangles."""
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    return _tris(v, _F)


def _faults(faces):
    """Edges used by one face (open) or by three or more (non-manifold)."""
    uses = {}
    for outer, holes in faces:
        for ring in [outer, *holes]:
            for p, q in zip(ring, ring[1:] + ring[:1]):
                k = frozenset((p, q))
                uses[k] = uses.get(k, 0) + 1
    return sum(1 for n in uses.values() if n != 2)


def test_a_piece_touching_edge_on_keeps_its_vertices_off_its_neighbour():
    """Two closed boxes in one body, the small one's end flush (to 50 nm)
    against the big one's side: their front faces fall in one plane group
    but stay two parts. The small box's corners lie on the big front's edge;
    putting them there splits an edge the big box's side does not, and the
    shell opens (#47, a formwork kicker against a stud). Each part keeps
    only the vertices of its own triangles."""
    tris = (_box(0, 1, 0, 1, 0, 1)
            + _box(1 + 5e-8, 2, 0, 1, 0.4, 0.6))
    assert _faults([(list(t), []) for t in tris]) == 0
    out = merge_coplanar_facets(tris)
    assert _faults(out) == 0
    assert len(out) == 12                     # both boxes still merge
    assert _signed_volume(out) == pytest.approx(1 + (1 - 5e-8) * 0.2)
    front = [o for o, _ in out if all(p[1] == 0 for p in o)
             and all(p[0] <= 1 for p in o)]
    assert len(front) == 1 and len(front[0]) == 4


def test_a_merge_that_would_open_the_shell_is_written_as_its_triangles():
    """The same two boxes exactly flush: the union joins their fronts (and
    backs) into one face whose boundary splits the big box's side edges,
    which nothing can close without an edge shared by four faces. The body
    is written as its triangles, which are as closed as they came."""
    tris = _box(0, 1, 0, 1, 0, 1) + _box(1, 2, 0, 1, 0.4, 0.6)
    out = merge_coplanar_facets(tris)
    assert _faults(out) == 0
    assert len(out) == len(tris)
    assert _signed_volume(out) == pytest.approx(1.2)
