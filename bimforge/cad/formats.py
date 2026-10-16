"""Dimension and survey text formatters for detailing scripts.

Pure stdlib — imports nothing beyond :mod:`math` — so it is safe to use in
unit-tested geometry modules that must not pull in ezdxf or pyproj.

The helpers were consolidated from project scripts that each carried their
own copy.
"""
from __future__ import annotations

import math

#: Feet per US survey foot -> metres (exact, by definition of the international foot).
FT2M: float = 0.3048

#: Inches per foot.
IN_PER_FT: float = 12.0

#: Cardinal directions accepted by :func:`bearing_to_azimuth`.
_QUADRANT = {
    ("N", "E"): lambda a: a,
    ("S", "E"): lambda a: 180.0 - a,
    ("S", "W"): lambda a: 180.0 + a,
    ("N", "W"): lambda a: 360.0 - a,
}


def ft_in(inches: float) -> str:
    """Format a length in inches as a feet-inches string.

    Whole feet render as ``N'-0"``; whole remaining inches render as
    ``N'-M"``; fractional inches fall back to ``:g`` formatting.

    >>> ft_in(240)
    '20\\'-0"'
    >>> ft_in(247)
    '20\\'-7"'
    >>> ft_in(246.5)
    '20\\'-6.5"'
    """
    feet = int(inches // 12)
    rem = inches - feet * 12
    if abs(rem) < 1e-6:
        return f"{feet}'-0\""
    if abs(rem - round(rem)) < 1e-6:
        return f"{feet}'-{int(round(rem))}\""
    return f"{feet}'-{rem:g}\""


def station(sta: float, decimals: int = 2) -> str:
    """Format a chainage value (feet) as a survey station string.

    >>> station(10522.58)
    '105+22.58'
    >>> station(10500.0, decimals=0)
    '105+00'
    """
    hundreds = int(sta // 100)
    rem = sta - hundreds * 100
    width = 2 if decimals == 0 else decimals + 3
    return f"{hundreds}+{rem:0{width}.{decimals}f}"


def dms(degrees: float, minutes: float = 0.0, seconds: float = 0.0) -> float:
    """Convert degrees-minutes-seconds to decimal degrees.

    >>> round(dms(58, 16, 11), 6)
    58.269722
    """
    return degrees + minutes / 60.0 + seconds / 3600.0


def bearing_to_azimuth(ns: str, degrees: float, minutes: float,
                       seconds: float, ew: str) -> float:
    """Convert a quadrant bearing (e.g. N 58-16-11 E) to an azimuth in degrees.

    Azimuths are measured clockwise from north, in ``[0, 360)``.

    >>> round(bearing_to_azimuth("N", 58, 16, 11, "E"), 4)
    58.2697
    >>> round(bearing_to_azimuth("S", 30, 48, 45.66, "E"), 4)
    149.1873
    """
    quad = (ns.upper(), ew.upper())
    if quad not in _QUADRANT:
        raise ValueError(f"invalid bearing quadrant {quad!r}; expected N/S paired with E/W")
    return _QUADRANT[quad](dms(degrees, minutes, seconds)) % 360.0


def forward(northing: float, easting: float, azimuth_deg: float,
            distance: float) -> tuple[float, float]:
    """Traverse ``distance`` from ``(N, E)`` along ``azimuth_deg`` -> ``(N, E)``.

    Azimuth is clockwise from north, so ``dN = d*cos(az)`` and ``dE = d*sin(az)``.

    >>> n, e = forward(0.0, 0.0, 90.0, 100.0)
    >>> round(n, 6), round(e, 6)
    (0.0, 100.0)
    """
    a = math.radians(azimuth_deg)
    return (northing + distance * math.cos(a), easting + distance * math.sin(a))
