"""Georeferencing helpers shared by dxf2bim (write) and kml/kmz (read).

`read_map_conversion` is a faithful extraction of kml.py's inline
IfcMapConversion/IfcProjectedCRS reader (same attributes, same error
messages) so kml.py and future consumers (kmz) share one implementation.
The legacy (<= 0.1.10) broken-georeference coordinate guard stays in kml.py:
it inspects triangulated geometry, not the MapConversion entity, so it has
no business living here.

`write_map_unit` states the CRS's own unit on its IfcProjectedCRS (#58),
for both writers (dxf2bim and author.emit_ifc); `crs_unit`, `crs_name` and
`crs_datum` read the EPSG registry it takes them from.

`ZONES` + `resolve_epsg` let a layer map name a State Plane zone instead of
spelling out its EPSG code. The constants mirror the in-house survey
package's canonical zone table but are kept local so the `bim` extra has no
dependency on it.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
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


#: How far MapConversion.Scale may stray (relative) from the model unit over
#: the CRS unit before the georeference is refused. Loose enough for a DXF
#: drawn in international feet on a US-survey-feet CRS (2 ppm, about 2 mm
#: over a 1000 ft model), tight enough to catch a metre/foot or mm mix-up.
SCALE_TOL = 1e-4


@lru_cache(maxsize=None)
def _crs(epsg: int):
    from pyproj import CRS
    return CRS.from_epsg(int(epsg))


def crs_unit(epsg: int) -> tuple[str, float]:
    """(name, metres) of a projected CRS's easting unit, from the EPSG
    registry: ("US survey foot", 0.3048006...), ("foot", 0.3048), ("metre", 1.0)."""
    axis = _crs(epsg).axis_info[0]
    return axis.unit_name, float(axis.unit_conversion_factor)


def crs_name(epsg: int) -> str:
    """The CRS's registry name, e.g. "NAD83 / California zone 3 (ftUS)"."""
    return _crs(epsg).name


def crs_datum(epsg: int) -> str | None:
    """The CRS's geodetic datum name, e.g. "North American Datum 1983"."""
    datum = _crs(epsg).datum
    return datum.name if datum is not None else None


def crs_vertical_datum(epsg: int) -> str | None:
    """The height datum of a compound CRS, e.g. "North American Vertical
    Datum 1988" for EPSG:8700 (… + NAVD88 height (ft)). A plain projected
    CRS states none: None, and the caller's own vertical_datum (or nothing)
    stands."""
    for sub in _crs(epsg).sub_crs_list or ():
        if sub.is_vertical and sub.datum is not None:
            return sub.datum.name
    return None


def _si_metre(f):
    """The project's unprefixed SI metre if it has one, else a new one."""
    for u in f.by_type("IfcSIUnit"):
        if u.UnitType == "LENGTHUNIT" and u.Name == "METRE" and not u.Prefix:
            return u
    return f.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE")


def write_map_unit(f, epsg: int, scale: float):
    """Set the file's IfcProjectedCRS.MapUnit to the CRS's unit (#58).

    Without MapUnit a CRS takes the project's length unit, the metre in
    every file bimforge writes, so a reader that follows the schema took a
    US-survey-feet CRS's eastings and northings as metres. A metre CRS gets
    the SI metre, any other unit an IfcConversionBasedUnit to it ('US survey
    foot', 'foot'), which is the map's alone (not in IfcUnitAssignment).

    Raises ValueError when `scale` (MapConversion.Scale, model units to CRS
    units) disagrees with the CRS unit by more than SCALE_TOL: such a file
    puts the model in the wrong place. A file with no IfcProjectedCRS
    (IFC2X3 georeferences by property set) is left alone; returns the unit,
    or None.
    """
    import ifcopenshell.util.unit as uu
    crss = f.by_type("IfcProjectedCRS") if f.schema != "IFC2X3" else []
    if not crss:
        return None
    name, metres = crs_unit(epsg)
    want = uu.calculate_unit_scale(f) / metres
    if abs(scale - want) > SCALE_TOL * want:
        raise ValueError(
            f"IfcMapConversion Scale {scale:.9g} does not match EPSG:{epsg}, "
            f"which is in {name} ({metres:.12g} m): model units to {name} "
            f"is {want:.9g}. Is the drawing unit the CRS's?")
    if metres == 1.0:
        unit = _si_metre(f)
    else:
        unit = f.create_entity(
            "IfcConversionBasedUnit",
            Dimensions=f.create_entity("IfcDimensionalExponents",
                                       1, 0, 0, 0, 0, 0, 0),
            UnitType="LENGTHUNIT", Name=name,
            ConversionFactor=f.create_entity(
                "IfcMeasureWithUnit",
                ValueComponent=f.create_entity("IfcLengthMeasure", metres),
                UnitComponent=_si_metre(f)))
    for crs in crss:
        crs.MapUnit = unit
    return unit
