"""SectionPrism batter and mitred ends (#24): a battered panel that still
carries its pipe opening, cut on the planes the walls meeting it share."""
import pytest

from bimforge.author.primitives import SectionPrism, _signed_volume, circle_poly

L, H, T = 10.0, 6.0, 1.0
B = 0.5 / 12.0                        # B3-1A Type 1's 0.5:12
FACE = [(0.0, 0.0), (L, 0.0), (L, H), (0.0, H)]


def _closed_form(k0, k1, void_area=0.0, void_z=0.0):
    """x spans [k0*y, L + k1*y], y spans [-B*(H - z), T]: integrate the width
    over y then z; a void well clear of the ends removes its area times the
    depth at its centroid."""
    c = k1 - k0
    solid = L * (T * H + B * H ** 2 / 2) + c / 2 * (T ** 2 * H - B ** 2 * H ** 3 / 3)
    return solid - void_area * (T + B * (H - void_z))


def _mesh(sp):
    d = sp.body_solids()[0]
    v = d["verts"]
    return v, [(v[a], v[b], v[c]) for a, b, c in d["tris"]]


def _closed_edges(tris):
    """Every directed edge has its reverse: a watertight, consistently wound shell."""
    edges = {}
    for t in tris:
        for p, q in zip(t, t[1:] + t[:1]):
            k = (tuple(round(c, 9) for c in p), tuple(round(c, 9) for c in q))
            edges[k] = edges.get(k, 0) + 1
    return all(edges.get((q, p), 0) == n for (p, q), n in edges.items())


def test_a_plain_prism_is_unchanged():
    sp = SectionPrism("p", FACE, T)
    assert not sp.sheared
    assert sp.volume_cf == pytest.approx(L * H * T)
    assert "exact" in sp.body_solids()[0]


@pytest.mark.parametrize("k0, k1", [(0.0, 0.0), (0.27, -0.13), (-0.1, 0.2)])
def test_batter_and_mitres_integrate_to_the_closed_form(k0, k1):
    sp = SectionPrism("p", FACE, T, batter=B, end_slopes=(k0, k1))
    v, tris = _mesh(sp)
    assert sp.sheared and "exact" not in sp.body_solids()[0]
    assert _closed_edges(tris)
    assert sp.volume_cf == pytest.approx(_closed_form(k0, k1), rel=1e-12)
    assert _signed_volume(tris) > 0


def test_the_far_face_stays_plumb_and_the_near_face_batters():
    v, _ = _mesh(SectionPrism("p", FACE, T, batter=B))
    far = {round(p[1], 9) for p in v if p[1] > 0.5}
    assert far == {T}
    near_base = {round(p[1], 9) for p in v if p[1] < 0.5 and p[2] == 0.0}
    near_top = {round(p[1], 9) for p in v if p[1] < 0.5 and p[2] == H}
    assert near_base == {round(-B * H, 9)} and near_top == {0.0}


def test_a_void_runs_straight_through_the_battered_panel():
    void = [(5.0 + x, 2.0 + z) for x, z in circle_poly(1.5, 32)]
    from bimforge.author.alignment import poly_area
    sp = SectionPrism("p", FACE, T, voids=[void], batter=B, end_slopes=(0.27, -0.27))
    _, tris = _mesh(sp)
    assert _closed_edges(tris)
    assert sp.volume_cf == pytest.approx(
        _closed_form(0.27, -0.27, poly_area(void), 2.0), rel=1e-9)


def test_ends_ride_their_planes():
    k0, k1 = 0.27, -0.13
    v, _ = _mesh(SectionPrism("p", FACE, T, batter=B, end_slopes=(k0, k1)))
    left = [p for p in v if p[0] < L / 2 and abs(p[0] - k0 * p[1]) < 1e-9]
    right = [p for p in v if p[0] > L / 2 and abs(p[0] - (L + k1 * p[1])) < 1e-9]
    assert len(left) == 4 and len(right) == 4


def test_a_batter_that_inverts_the_section_is_refused():
    with pytest.raises(ValueError, match="inverts"):
        SectionPrism("p", FACE, T, batter=-0.5)


def _merged_faces_close(sp):
    """The shell as the IFC writer emits it, coplanar facets merged into
    faces: every loop edge has its reverse. A triangle that folds when a mitre
    moves its corner leaves a slit here that the raw mesh hides."""
    from bimforge.author.facets import merge_coplanar_facets
    _, tris = _mesh(sp)
    edges = {}
    for outer, holes in merge_coplanar_facets(tris):
        for ring in [outer] + holes:
            r = [tuple(round(c, 7) for c in p) for p in ring]
            for p, q in zip(r, r[1:] + r[:1]):
                edges[(p, q)] = edges.get((p, q), 0) + 1
    return all(edges.get((q, p), 0) == n for (p, q), n in edges.items())


@pytest.mark.parametrize("cz", [0.5 + 1.555, 2.0, 3.5])
def test_a_mitred_voided_panel_still_closes_once_its_faces_are_merged(cz):
    void = [(5.0 + x, cz + z) for x, z in circle_poly(1.555, 32)]
    for batter in (0.0, B):
        sp = SectionPrism("p", FACE, T, voids=[void], batter=batter,
                          end_slopes=(0.268, -0.268))
        assert _merged_faces_close(sp), f"batter {batter}, cz {cz}"
