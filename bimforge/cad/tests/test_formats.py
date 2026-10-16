"""Tests for bimforge.cad.formats — the pure dimension/survey formatters."""
from __future__ import annotations

import math

import pytest

from bimforge.cad.formats import (
    FT2M,
    IN_PER_FT,
    bearing_to_azimuth,
    dms,
    forward,
    ft_in,
    station,
)


def test_constants():
    assert FT2M == 0.3048
    assert IN_PER_FT == 12.0


@pytest.mark.parametrize(
    "inches, expected",
    [
        (240, "20'-0\""),
        (0, "0'-0\""),
        (12, "1'-0\""),
        (247, "20'-7\""),
        (13, "1'-1\""),
        (246.5, "20'-6.5\""),
    ],
)
def test_ft_in(inches, expected):
    assert ft_in(inches) == expected


def test_ft_in_rounds_near_whole():
    # 20'-0" (240") plus a rounding-noise epsilon still reads clean.
    assert ft_in(240 + 1e-9) == "20'-0\""


@pytest.mark.parametrize(
    "sta, decimals, expected",
    [
        (10522.58, 2, "105+22.58"),
        (10500.0, 0, "105+00"),
        (10000.0, 2, "100+00.00"),
        (585.58, 2, "5+85.58"),
    ],
)
def test_station(sta, decimals, expected):
    assert station(sta, decimals) == expected


def test_dms():
    assert dms(58) == 58.0
    assert dms(58, 16, 11) == pytest.approx(58.269722, abs=1e-6)
    assert dms(0, 30) == 0.5


@pytest.mark.parametrize(
    "quad, expected",
    [
        (("N", 58, 16, 11, "E"), 58.2697),
        (("S", 30, 48, 45.66, "E"), 149.1873),
        (("N", 71, 23, 47.65, "W"), 288.6034),
        (("S", 30, 48, 45.66, "W"), 210.8127),
    ],
)
def test_bearing_to_azimuth(quad, expected):
    assert bearing_to_azimuth(*quad) == pytest.approx(expected, abs=1e-3)


def test_bearing_to_azimuth_wraps_into_range():
    az = bearing_to_azimuth("N", 0, 0, 0, "E")
    assert 0.0 <= az < 360.0


def test_bearing_to_azimuth_rejects_bad_quadrant():
    with pytest.raises(ValueError):
        bearing_to_azimuth("X", 10, 0, 0, "E")


def test_forward_due_east():
    n, e = forward(0.0, 0.0, 90.0, 100.0)
    assert n == pytest.approx(0.0, abs=1e-9)
    assert e == pytest.approx(100.0)


def test_forward_due_north():
    n, e = forward(1000.0, 2000.0, 0.0, 50.0)
    assert n == pytest.approx(1050.0)
    assert e == pytest.approx(2000.0, abs=1e-9)


def test_forward_roundtrip_distance():
    n, e = forward(500.0, 500.0, 37.0, 123.4)
    assert math.hypot(n - 500.0, e - 500.0) == pytest.approx(123.4)
