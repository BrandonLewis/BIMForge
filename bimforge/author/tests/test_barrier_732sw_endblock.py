import pytest

from bimforge.author.alignment import poly_area
from bimforge.author.barrier_section import type_732sw_profile
from bimforge.author.barrier_732sw_endblock import (
    nose_section, endblock_solid, endblock_bars)

# Running section governing dims (feet), flat slab:
ROW = {
    "top_w_ft": 1.0, "top_h_ft": 14.0 / 12.0, "stem_w_ft": 10.0 / 12.0,
    "barrier_h_ft": 2.0 + 8.0 / 12.0, "sw_top_face_ft": 0.7624,
    "sw_thick_toe_ft": 8.0 / 12.0, "sw_width_ft": 6.0 + 2.0 / 12.0,
    "deck_slope_pct": 0.0,
}
APPROACH_TOP_Z = 0.7624 + 2.0 + 11.0 / 12.0    # 2'-11" above sidewalk face
RUNNING_TOP_Z = 0.7624 + 2.0 + 8.0 / 12.0      # 2'-8"


def test_nose_solidifies_back_relief_and_raises_top_for_approach():
    nose = nose_section(ROW, approach=True)
    # every ring vertex is either at the outboard face x==0 or inboard (x>=top_w
    # for the parapet / sidewalk); NO vertex sits at the 2" relief x==stem_out.
    stem_out = ROW["top_w_ft"] - ROW["stem_w_ft"]     # 0.16667
    assert all(abs(x - stem_out) > 1e-9 for x, _z in nose)
    assert max(z for _x, z in nose) == pytest.approx(APPROACH_TOP_Z)


def test_nose_departure_keeps_running_height_but_still_solid():
    nose = nose_section(ROW, approach=False)
    stem_out = ROW["top_w_ft"] - ROW["stem_w_ft"]
    assert all(abs(x - stem_out) > 1e-9 for x, _z in nose)
    assert max(z for _x, z in nose) == pytest.approx(RUNNING_TOP_Z)


def test_nose_area_exceeds_running_area():
    # solidified (relief filled) + (approach) taller => bigger section than A-A
    running_area = poly_area(type_732sw_profile(ROW))
    assert poly_area(nose_section(ROW, approach=True)) > running_area
    assert poly_area(nose_section(ROW, approach=False)) > running_area


def test_endblock_loft_cf_is_a_real_taper_between_the_two_ends():
    sol = endblock_solid("NB block", ROW, approach=True, y_inboard=6.0,
                         y_nose=0.0, ifc="IfcWall", layer="S-CONC")
    running_area = poly_area(type_732sw_profile(ROW))
    nose_area = poly_area(nose_section(ROW, approach=True))
    length = 6.0
    cf = sol.volume_cf
    # STRICTLY between the two constant-prism extremes: proves the taper is
    # real (a constant-nose or constant-running prism regression would fail).
    assert running_area * length < cf < nose_area * length
    # independent cross-check: linear-loft (prismatoid) volume, midsection area
    # from the per-vertex average of the two rings.
    a0 = [(x, y) for x, y in type_732sw_profile(ROW)]
    a1 = [(x, y) for x, y in nose_section(ROW, approach=True)]
    mid = [((x0 + x1) / 2.0, (z0 + z1) / 2.0)
           for (x0, z0), (x1, z1) in zip(a0, a1)]
    prismatoid = length * (poly_area(a0) + 4 * poly_area(mid)
                           + poly_area(a1)) / 6.0
    # the emitted mesh integrates to the exact prismatoid volume (loft_faces'
    # triangulation is consistent); the strict bracket above is the real
    # anti-vacuous assertion, this pins the absolute number.
    assert cf == pytest.approx(prismatoid, rel=1e-6)


def test_departure_endblock_loft_cf_brackets_between_ends():
    sol = endblock_solid("NB block", ROW, approach=False, y_inboard=6.0,
                         y_nose=0.0, ifc="IfcWall", layer="S-CONC")
    running_area = poly_area(type_732sw_profile(ROW))
    nose_area = poly_area(nose_section(ROW, approach=False))
    length = 6.0
    assert running_area * length < sol.volume_cf < nose_area * length


def test_endblock_body_solids_is_a_mesh():
    sol = endblock_solid("NB block", ROW, approach=True, y_inboard=6.0,
                         y_nose=0.0, ifc="IfcWall", layer="S-CONC")
    solids = sol.body_solids()
    assert len(solids) == 1 and solids[0]["kind"] == "mesh"
    assert solids[0]["verts"] and solids[0]["tris"]


def test_approach_endblock_has_heavy_number6_traffic_face():
    bars = endblock_bars(6.0, approach=True)
    assert any(b.size == 6 for b in bars)                 # #6 traffic face
    assert sum(b.weight for b in bars) > 0.0


def test_departure_endblock_is_all_number5():
    bars = endblock_bars(6.0, approach=False)
    assert bars and all(b.size == 5 for b in bars)        # lighter, no #6


def test_approach_endblock_is_heavier_than_departure():
    ap = sum(b.weight for b in endblock_bars(6.0, approach=True))
    dp = sum(b.weight for b in endblock_bars(6.0, approach=False))
    assert ap > dp
