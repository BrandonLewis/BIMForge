"""The B11-51 R=4'-0" end-post bent-down return: true arc geometry, and the
one-number coupling of drawn curl to paid steel weight."""
import math
from collections import Counter

import pytest

from bimforge.author import rail_run as rr
from bimforge.author import rail_section as rs
from bimforge.author.primitives import FACET_TOLERANCE

SIZE = "HSS3x2x3/16"
R = rr.END_RETURN_RADIUS_FT


def _tube(**kw):
    outer, voids = rs.hollow_ring(SIZE, 0.0, 4.0)
    base = dict(outer=outer, voids=voids, x0=0.0, z_center=4.0, radius_ft=R,
                phi0=0.0, phi1=0.8, y_bc=0.0, toward=-1.0,
                ifc="IfcMember", layer="S-METAL")
    base.update(kw)
    return rr._BentTube("t", **base)


def test_volume_is_pappus_net_area_times_arc_length():
    t = _tube(phi1=0.8)
    net = rs.area_sf(SIZE)
    assert t.volume_cf == pytest.approx(net * R * 0.8, rel=1e-12)


def test_faceted_mesh_matches_closed_form_within_facet_tolerance():
    t = _tube(phi1=0.8)
    # honest coupling: the chorded mesh volume must land within the same band
    # the arc-faceting gate enforces -- not merely "close".
    err = abs(t.faceted_volume_cf - t.volume_cf) / t.volume_cf
    assert 0.0 < err <= FACET_TOLERANCE          # nonzero: real facets, not a copy


def test_mesh_is_closed_and_consistently_oriented():
    # every directed edge appears exactly once <=> watertight, single winding.
    _, tris = _tube()._mesh()
    edges = Counter()
    for a, b, c in tris:
        edges[(a, b)] += 1
        edges[(b, c)] += 1
        edges[(c, a)] += 1
    assert edges, "no triangles"
    assert all(n == 1 for n in edges.values())
    assert all((b, a) in edges for (a, b) in edges)   # each edge has its reverse


def test_sweep_angle_curls_tube_bottom_down_to_the_barrier_top():
    rail = rs.CONFIG_B11_51.rails[0]                   # top rail
    phi = rr._return_sweep_angle(rail, R)
    half_d = rs.HSS[rail.size][1] / 12.0 / 2.0
    # tilt-aware: the tube's lowest fibre (not the centerline) reaches z=0.
    assert math.cos(phi) == pytest.approx((R - rail.z_center_ft) / (R - half_d))
    verts, _ = _tube(z_center=rail.z_center_ft, phi1=phi,
                     outer=rs.hollow_ring(rail.size, 0.0, rail.z_center_ft)[0],
                     voids=rs.hollow_ring(rail.size, 0.0, rail.z_center_ft)[1]
                     )._mesh()
    zmin = min(z for _x, _y, z in verts)
    assert zmin == pytest.approx(0.0, abs=1e-9)        # bottom lands at z=0 (barrier)


def test_return_is_shorter_than_a_full_quarter_circle():
    # the fix: the rail only drops its own height, ~47 deg, NOT a 90 deg quarter.
    phi = rr._return_sweep_angle(rs.CONFIG_B11_51.rails[0], R)
    assert 0.7 < phi < 0.9                             # ~46-47 deg in radians
    assert R * phi < math.pi / 2.0 * R                 # developed length < old stub


def test_start_curls_toward_minus_y_end_curls_toward_plus_y():
    lo = _tube(toward=-1.0, y_bc=0.0, phi1=0.8)
    hi = _tube(toward=1.0, y_bc=24.0, phi1=0.8)
    lo_y = [y for _x, y, _z in lo._mesh()[0]]
    hi_y = [y for _x, y, _z in hi._mesh()[0]]
    assert min(lo_y) < 0.0 and max(lo_y) == pytest.approx(0.0, abs=1e-9)
    assert max(hi_y) > 24.0 and min(hi_y) == pytest.approx(24.0, abs=1e-9)


def test_degenerate_profile_fails_loud_not_indexerror():
    # a collapsed section cleans to [] -- _mesh must raise the guarding
    # ValueError (with the element name), NOT an IndexError from winding [].
    t = _tube(outer=[(0.0, 4.0), (1.0, 4.0)], voids=[])   # 2 pts -> degenerate
    with pytest.raises(ValueError, match="collapses to < 3 points"):
        t._mesh()


def test_begin_curve_section_meets_the_straight_rail_flush():
    # at phi=0 the section is the flat rail end at (x0, y_bc, z_center): the
    # return joins the straight top rail with a horizontal tangent, no gap.
    t = _tube(y_bc=0.0)
    x, y, z = t._map(0.1, 4.05, 0.0)
    assert (x, y, z) == pytest.approx((0.1, 0.0, 4.05))
