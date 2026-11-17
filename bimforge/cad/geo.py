"""Coordinate-reference helpers for georeferencing structure models.

Georeferenced scripts each built their own :class:`pyproj.Transformer` from a
State Plane zone to WGS84 and wrapped it in a one-liner, no two of them
alike.

This module centralises those transformers, caches them, and offers a
:class:`StatePlane` projector plus grid-vs-ground scaling notes so the callers no
longer disagree on argument order.

pyproj uses ``always_xy=True`` throughout: transform inputs/outputs are ordered
``(easting/lon, northing/lat)``.
"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import TYPE_CHECKING

from pyproj import CRS, Transformer

if TYPE_CHECKING:
    from collections.abc import Iterable

#: WGS84 geographic (lon/lat) EPSG code.
WGS84 = 4326

#: California State Plane, NAD83, US survey feet, by zone number.
CA_SP_ZONE2 = 2226   # Sacramento-area zone
CA_SP_ZONE3 = 2227   # e.g. Stanislaus area jobs

#: The grid-to-ground combined factor as survey control sheets state it:
#: ``ground = grid * combined_factor`` and ``grid = ground / combined_factor``
#: (e.g. 1.000254948 on the Industrial-Wastewater control sheet). Site-
#: specific; the 1.0 default makes grid == ground. Treating ground
#: coordinates as grid (skipping the divide) shifts a State-Plane site by
#: thousands of feet (~3,789 ft on the documented job) — pass the survey's
#: factor whenever the plans state one. Assumes ground coordinates scaled
#: about the grid origin (the plan-README recipe); base-point-scaled or
#: truncated ground systems need a different correction.
DEFAULT_COMBINED_FACTOR = 1.0


@lru_cache(maxsize=None)
def transformer(from_epsg: int, to_epsg: int) -> Transformer:
    """Return a cached ``always_xy`` :class:`~pyproj.Transformer`.

    Args:
        from_epsg: Source CRS EPSG code.
        to_epsg: Target CRS EPSG code.
    """
    return Transformer.from_crs(from_epsg, to_epsg, always_xy=True)


class StatePlane:
    """A bound State Plane <-> WGS84 projector for one zone.

    Args:
        epsg: State Plane zone EPSG code (default :data:`CA_SP_ZONE2`).

    The ``*_ne`` variants take/return ``(northing, easting)`` — the order
    surveyors quote — while the plain methods use pyproj's ``(easting, northing)``
    / ``(lon, lat)`` order.
    """

    def __init__(self, epsg: int = CA_SP_ZONE2):
        self.epsg = epsg
        self._to = transformer(epsg, WGS84)
        self._from = transformer(WGS84, epsg)

    def to_lonlat(self, easting: float, northing: float,
                  combined_factor: float | None = None) -> tuple[float, float]:
        """Project ``(easting, northing)`` ft -> ``(lon, lat)`` degrees.

        ``combined_factor``: the survey's grid-to-ground factor, when the
        inputs are GROUND coordinates — they are scaled back to grid
        (``grid = ground / factor``) before projecting. ``None``/1.0 treats
        the inputs as grid coordinates."""
        if combined_factor is not None and combined_factor != 1.0:
            if combined_factor <= 0:
                raise ValueError(
                    f"combined_factor must be positive, got {combined_factor!r}")
            easting = easting / combined_factor
            northing = northing / combined_factor
        lon, lat = self._to.transform(easting, northing)
        return lon, lat

    def to_lonlat_ne(self, northing: float, easting: float,
                     combined_factor: float | None = None) -> tuple[float, float]:
        """Project ``(northing, easting)`` ft -> ``(lon, lat)`` degrees."""
        return self.to_lonlat(easting, northing, combined_factor)

    def from_lonlat(self, lon: float, lat: float) -> tuple[float, float]:
        """Project ``(lon, lat)`` degrees -> ``(easting, northing)`` ft."""
        easting, northing = self._from.transform(lon, lat)
        return easting, northing

    def from_lonlat_ne(self, lon: float, lat: float) -> tuple[float, float]:
        """Project ``(lon, lat)`` degrees -> ``(northing, easting)`` ft."""
        easting, northing = self.from_lonlat(lon, lat)
        return northing, easting


def sp_to_wgs84(easting: float, northing: float,
                epsg: int = CA_SP_ZONE2) -> tuple[float, float]:
    """Project a single State Plane ``(easting, northing)`` to ``(lon, lat)``.

    Convenience wrapper over :class:`StatePlane` for one-off conversions.
    """
    return StatePlane(epsg).to_lonlat(easting, northing)


def wgs84_to_sp(lon: float, lat: float,
                epsg: int = CA_SP_ZONE2) -> tuple[float, float]:
    """Project a single ``(lon, lat)`` to State Plane ``(easting, northing)``."""
    return StatePlane(epsg).from_lonlat(lon, lat)


def grid_to_ground(grid: float,
                   combined_factor: float = DEFAULT_COMBINED_FACTOR) -> float:
    """Scale a grid distance/coordinate to ground (``ground = grid * factor``)."""
    return grid * combined_factor


def ground_to_grid(ground: float,
                   combined_factor: float = DEFAULT_COMBINED_FACTOR) -> float:
    """Scale a ground distance/coordinate to grid (``grid = ground / factor``)."""
    return ground / combined_factor


def true_north_direction(epsg: int, easting: float,
                         northing: float) -> tuple[float, float]:
    """Unit ``(x, y)`` of TRUE north in grid axes (x=Easting, y=Northing) at
    a point, via grid convergence: project the point to lon/lat, step
    1e-4 deg (~11 m) due true north, and take the grid bearing of that step —
    sign-correct without hard-coding the convergence formula (the bridge-pilot
    d810401 recipe). Where grid north == true north this returns (0.0, 1.0)."""
    lon0, lat0 = transformer(epsg, WGS84).transform(easting, northing)
    back = transformer(WGS84, epsg)
    e0, n0 = back.transform(lon0, lat0)
    e1, n1 = back.transform(lon0, lat0 + 1.0e-4)
    mag = math.hypot(e1 - e0, n1 - n0)
    if not math.isfinite(mag) or mag == 0.0:
        raise ValueError(
            f"true_north_direction: EPSG:{epsg} transform is not usable at "
            f"({easting}, {northing}) — non-finite/degenerate north step")
    return (e1 - e0) / mag, (n1 - n0) / mag


def convergence_deg(epsg: int, easting: float, northing: float) -> float:
    """Grid convergence at a point, in degrees: the angle from grid north
    to true north, positive when true north leans toward +x (east)."""
    x, y = true_north_direction(epsg, easting, northing)
    return math.degrees(math.atan2(x, y))

def _inside(aou, lon: float, lat: float, margin_deg: float) -> bool:
    return (math.isfinite(lon) and math.isfinite(lat)
            and aou.west - margin_deg <= lon <= aou.east + margin_deg
            and aou.south - margin_deg <= lat <= aou.north + margin_deg)


def check_base_in_crs(epsg: int, easting: float, northing: float, *,
                      what: str = "base point", margin_deg: float = 0.5) -> None:
    """Refuse a georeference base that does not land inside its CRS.

    ``easting``/``northing`` are read in EPSG:epsg's OWN units, which is what
    IfcMapConversion.Eastings/Northings mean (MapUnit is the CRS's unit,
    #58). A base outside the CRS's area of use that lands inside it when
    read in another unit is a unit mix-up: metre values under a ftUS zone put
    a Central Valley structure in the Pacific, ~1,480 km off. That raises,
    and the error says which unit the numbers fit. A base outside the zone
    in every unit (a local or synthetic base) only warns.

    A base of exactly (0, 0) is skipped: that is the "geometry drawn at full
    State Plane coordinates" convention, not a placement.
    """
    if easting == 0.0 and northing == 0.0:
        return
    crs = CRS.from_epsg(epsg)
    aou = crs.area_of_use
    if aou is None:
        return
    to_ll = transformer(epsg, WGS84)
    lon, lat = to_ll.transform(easting, northing)
    if _inside(aou, lon, lat, margin_deg):
        return
    k = float(crs.axis_info[0].unit_conversion_factor)
    unit = crs.axis_info[0].unit_name
    hint = ""
    for label, unit_m in (("metres", 1.0), ("US survey feet", 0.30480060960121924)):
        factor = unit_m / k
        if abs(factor - 1.0) < 1e-3:
            continue
        lon2, lat2 = to_ll.transform(easting * factor, northing * factor)
        if _inside(aou, lon2, lat2, margin_deg):
            hint = (f" The numbers fit the zone if read as {label}: convert them "
                    f"to {unit} (multiply by {factor:.12g}) or declare the CRS "
                    f"that is in {label}.")
            break
    msg = (f"{what} E={easting} N={northing}, read in {unit} as EPSG:{epsg} "
           f"({crs.name}) declares, lands at lat {lat:.6f} lon {lon:.6f}, outside "
           f"the CRS's area of use.")
    if not hint:
        # outside the zone in every unit: a local or synthetic base, not a
        # unit mix-up, so say so and go on
        import warnings
        warnings.warn(msg, stacklevel=2)
        return
    raise ValueError(msg + hint)
