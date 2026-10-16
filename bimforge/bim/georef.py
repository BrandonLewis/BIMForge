"""Georeferencing helpers shared by dxf2bim (write) and kml/kmz (read).

`read_map_conversion` is a faithful extraction of kml.py's inline
IfcMapConversion/IfcProjectedCRS reader (same attributes, same error
messages) so kml.py and future consumers (kmz) share one implementation.
The legacy (<= 0.1.10) broken-georeference coordinate guard stays in kml.py:
it inspects triangulated geometry, not the MapConversion entity, so it has
no business living here.

`ZONES` + `resolve_epsg` let a layer map name a State Plane zone instead of
spelling out its EPSG code. The constants mirror the in-house survey
package's canonical zone table but are kept local so the `bim` extra has no
dependency on it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Mirrors the in-house survey package's zone constants (CA zones); duplicated
# (not imported) so the bim extra has no dependency on it. NV West verified against the
# EPSG registry: 3423 = NAD83 / Nevada West (ftUS); 3421 is Nevada EAST —
# an easy silent-wrong-zone trap.
ZONES = {
    "CA_SP_ZONE2": 2226,
    "CA_SP_ZONE3": 2227,
    "NV_SP_WEST": 3423,
}


@dataclass
class GeoRef:
    base_e: float
    base_n: float
    scale: float
    epsg: int
    height: float


def read_map_conversion(ifc: Any) -> GeoRef:
    """Read the IFC's IfcMapConversion + IfcProjectedCRS into a `GeoRef`.

    Raises ValueError for a non-georeferenced IFC (no MapConversion/CRS) or
    one carrying an invalid (zero) Scale — same messages kml.py has always
    raised.
    """
    convs = ifc.by_type("IfcMapConversion")
    crss = ifc.by_type("IfcProjectedCRS")
    if not convs or not crss:
        raise ValueError(
            "the IFC carries no IfcMapConversion/IfcProjectedCRS — author it "
            "georeferenced (set georeference.crs_epsg in the dxf2bim layer map)")
    conv = convs[0]
    base_e, base_n = float(conv.Eastings), float(conv.Northings)
    scale = 1.0 if conv.Scale is None else float(conv.Scale)
    if scale == 0.0:
        raise ValueError("IfcMapConversion Scale is 0.0 — the IFC's georeference is invalid")
    height = 0.0 if conv.OrthogonalHeight is None else float(conv.OrthogonalHeight)
    epsg = int(crss[0].Name.split(":")[-1])
    return GeoRef(base_e=base_e, base_n=base_n, scale=scale, epsg=epsg, height=height)


def resolve_epsg(georeference_cfg: dict) -> int | None:
    """Resolve a layer map's `georeference` block to an EPSG code.

    `crs_epsg` (an int) wins when both `crs_epsg` and `zone` are present.
    `zone` is looked up case-insensitively in `ZONES`; an unrecognized zone
    name raises ValueError listing the known zones. Neither key present (or
    an empty/missing config) resolves to None (georeferencing skipped).
    """
    if not georeference_cfg:
        return None
    crs_epsg = georeference_cfg.get("crs_epsg")
    zone = georeference_cfg.get("zone")
    zone_epsg = None
    if zone is not None:
        key = str(zone).upper()
        if key not in ZONES:
            known = ", ".join(sorted(ZONES))
            raise ValueError(f"unknown georeference zone '{zone}' — known zones: {known}")
        zone_epsg = ZONES[key]
    if crs_epsg is not None:
        epsg = int(crs_epsg)
        if epsg == 0:
            raise ValueError(
                "crs_epsg 0 is not a valid EPSG code — remove it (or set a "
                "real code / a zone name) rather than georeferencing to EPSG:0")
        if zone_epsg is not None and zone_epsg != epsg:
            import warnings
            warnings.warn(
                f"georeference: both zone={zone!r} (EPSG:{zone_epsg}) and "
                f"crs_epsg={epsg} set — crs_epsg wins", stacklevel=2)
        return epsg
    return zone_epsg
