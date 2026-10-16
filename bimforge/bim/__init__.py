"""DXF -> BIM (IFC) -> CanonicalTakeoff pipeline.

Measure directly off 2D CAD plans, author the measurements as a typed,
quantified, classified IFC model, then roll the model up into the open
CanonicalTakeoff (`estimating_tools.takeoff.model`) the push-takeoff flow
consumes, or into 3D KML for Google Earth. Requires the `bim` extra
(ezdxf, shapely, ifcopenshell, numpy, pyproj).
"""

__all__ = ["extract_features", "build_ifc", "build_takeoff", "write_sample_dxf",
           "ifc_to_kml"]


def __getattr__(name):  # lazy so importing the package doesn't pull the heavy deps
    if name in ("extract_features", "build_ifc"):
        from bimforge.bim import dxf2bim
        return getattr(dxf2bim, name)
    if name == "ifc_to_kml":
        from bimforge.bim.kml import ifc_to_kml
        return ifc_to_kml
    if name == "build_takeoff":
        from bimforge.bim.ifc_takeoff import build_takeoff
        return build_takeoff
    if name == "write_sample_dxf":
        from bimforge.bim.sample import write_sample_dxf
        return write_sample_dxf
    raise AttributeError(name)
