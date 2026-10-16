"""Tests for bimforge.cad.geo — State Plane <-> WGS84 projection and grid/ground scaling."""
from __future__ import annotations

import pytest

pytest.importorskip("pyproj")

from bimforge.cad.geo import (  # noqa: E402
    CA_SP_ZONE2,
    CA_SP_ZONE3,
    DEFAULT_COMBINED_FACTOR,
    StatePlane,
    ground_to_grid,
    grid_to_ground,
    sp_to_wgs84,
    wgs84_to_sp,
)

# A plausible CA Zone 2 (EPSG:2226, US survey ft) point.
E_FT, N_FT = 6_462_000.0, 2_157_000.0


# --- zone constants ----------------------------------------------------------
def test_known_ca_zone_constants():
    assert CA_SP_ZONE2 == 2226
    assert CA_SP_ZONE3 == 2227


# --- round trips -------------------------------------------------------------
def test_sp_to_wgs84_round_trip_zone2():
    lon, lat = sp_to_wgs84(E_FT, N_FT, epsg=CA_SP_ZONE2)
    # Sanity: northern California, western hemisphere.
    assert -125.0 < lon < -114.0
    assert 32.0 < lat < 42.5
    e_back, n_back = wgs84_to_sp(lon, lat, epsg=CA_SP_ZONE2)
    assert e_back == pytest.approx(E_FT, abs=1e-3)
    assert n_back == pytest.approx(N_FT, abs=1e-3)


def test_state_plane_class_round_trip():
    sp = StatePlane(CA_SP_ZONE2)
    lon, lat = sp.to_lonlat(E_FT, N_FT)
    e_back, n_back = sp.from_lonlat(lon, lat)
    assert e_back == pytest.approx(E_FT, abs=1e-3)
    assert n_back == pytest.approx(N_FT, abs=1e-3)


def test_state_plane_ne_variants_swap_argument_order():
    sp = StatePlane(CA_SP_ZONE2)
    assert sp.to_lonlat_ne(N_FT, E_FT) == sp.to_lonlat(E_FT, N_FT)
    lon, lat = sp.to_lonlat(E_FT, N_FT)
    n, e = sp.from_lonlat_ne(lon, lat)
    assert (e, n) == sp.from_lonlat(lon, lat)


def test_zone3_round_trip():
    # Plausible Zone 3 (Stanislaus area) coordinates.
    e_ft, n_ft = 6_300_000.0, 1_900_000.0
    sp = StatePlane(CA_SP_ZONE3)
    lon, lat = sp.to_lonlat(e_ft, n_ft)
    e_back, n_back = sp.from_lonlat(lon, lat)
    assert e_back == pytest.approx(e_ft, abs=1e-3)
    assert n_back == pytest.approx(n_ft, abs=1e-3)


def test_default_zone_matches_zone2():
    assert sp_to_wgs84(E_FT, N_FT) == sp_to_wgs84(E_FT, N_FT, epsg=CA_SP_ZONE2)
    assert StatePlane().epsg == CA_SP_ZONE2


# --- grid vs ground ----------------------------------------------------------
def test_default_combined_factor_is_near_one():
    assert DEFAULT_COMBINED_FACTOR == pytest.approx(1.0, abs=1e-3)


def test_grid_ground_default_is_noop():
    assert grid_to_ground(500.0) == pytest.approx(500.0)
    assert ground_to_grid(500.0) == pytest.approx(500.0)


def test_grid_ground_round_trip_with_job_factor():
    # Convention (R1 item 3): combined_factor is the PLAN-STATED grid-to-
    # ground factor — ground = grid * cf, grid = ground / cf (Industrial-
    # Wastewater README: "true grid = ground / 1.000254948").
    cf = 1.000254948
    grid = 6_592_000.0
    ground = grid_to_ground(grid, cf)
    assert ground == pytest.approx(grid * cf)
    assert ground_to_grid(ground, cf) == pytest.approx(grid)


def test_ground_coordinates_project_through_grid():
    import math
    cf = 1.000254948
    sp = StatePlane(CA_SP_ZONE2)
    n_ground, e_ground = 1_943_000.0, 6_592_000.0
    lon_g, lat_g = sp.to_lonlat_ne(n_ground, e_ground, combined_factor=cf)
    lon_r, lat_r = sp.to_lonlat_ne(n_ground, e_ground)
    # Reproject both to grid feet; the factored one must sit ground/cf (i.e.
    # SMALLER coordinates — a sign-flipped port would land larger).
    e_g, n_g = sp.from_lonlat(lon_g, lat_g)
    e_r, n_r = sp.from_lonlat(lon_r, lat_r)
    assert e_g == pytest.approx(e_ground / cf, abs=0.01)
    assert n_g == pytest.approx(n_ground / cf, abs=0.01)
    assert e_g < e_r and n_g < n_r
    # The error class is thousands of feet, not noise (README: ~3,789 ft
    # on the origin job; magnitude scales with the coordinate values).
    shift = math.hypot(e_r - e_g, n_r - n_g)
    expected = math.hypot(e_ground - e_ground / cf, n_ground - n_ground / cf)
    assert shift == pytest.approx(expected, rel=0.01)
    assert shift > 1000.0


def test_combined_factor_none_or_one_is_noop():
    sp = StatePlane(CA_SP_ZONE2)
    base = sp.to_lonlat_ne(N_FT, E_FT)
    assert sp.to_lonlat_ne(N_FT, E_FT, combined_factor=None) == base
    assert sp.to_lonlat_ne(N_FT, E_FT, combined_factor=1.0) == base


def test_combined_factor_zero_or_negative_raises():
    sp = StatePlane(CA_SP_ZONE2)
    with pytest.raises(ValueError, match="combined_factor"):
        sp.to_lonlat_ne(N_FT, E_FT, combined_factor=0.0)
    with pytest.raises(ValueError, match="combined_factor"):
        sp.to_lonlat_ne(N_FT, E_FT, combined_factor=-1.0)


# --- true north / grid convergence -------------------------------------------
def test_true_north_is_unit_and_nonaxial():
    import math
    from bimforge.cad.geo import convergence_deg, true_north_direction
    # Well east of zone 2's central longitude -> nonzero convergence.
    x, y = true_north_direction(CA_SP_ZONE2, E_FT, N_FT)
    assert math.hypot(x, y) == pytest.approx(1.0, abs=1e-9)
    assert abs(x) > 1e-4                     # grid north != true north here
    assert y > 0.99                          # still overwhelmingly north
    gamma = convergence_deg(CA_SP_ZONE2, E_FT, N_FT)
    assert gamma == pytest.approx(
        math.degrees(math.atan2(x, y)), abs=1e-9)
    assert 0.01 < abs(gamma) < 3.0


def test_true_north_rejects_out_of_domain_point():
    from bimforge.cad.geo import true_north_direction
    with pytest.raises(ValueError, match="not usable"):
        true_north_direction(CA_SP_ZONE2, float("nan"), float("nan"))
