"""Convert a georeferenced est-bim IFC into a KMZ for Google Earth — the
roadmap D3 deliverable — with a glTF escape hatch for Cesium.

Default: a Google Earth **web** KMZ (#306). Earth for web/mobile imports only
Placemark / Folder / Style / Point / LineString / Polygon / MultiGeometry; a KML
``<Model>`` is "Unsupported element" there, and Earth Pro (desktop), the only
viewer that draws one, is deprecated. So the default KMZ is `kml.ifc_to_kml`'s
polygon KML zipped as ``doc.kml``, printed at 9/4 decimals so small triangles
don't collapse, with degenerate rings dropped and Earth web's import limits
(250,000 vertices, 10,000 features) enforced. It never contains ``<Model>``.

``collada=True`` keeps the original COLLADA ``<Model>`` KMZ for Earth Pro;
``gltf=True`` writes only a .glb. Both are described below.

Geometry for those two routes is serialized in-process with ifcopenshell's bundled native
``ColladaSerializer`` (``ifcopenshell.geom.serializers.collada`` — the same
serializer IfcConvert wraps; no external binary). Feed sequence verified
against the installed wrapper:

    s = serializers.collada(dae_path, geom_settings)
    s.ready(); s.setUnitNameAndMagnitude("METER", 1.0)
    s.setFile(model); s.writeHeader()
    s.write(create_shape(...))  # one TriangulationElement per product
    s.finalize(); del s         # flushes/closes only on destruction

Requires ifcopenshell >= 0.9, which changed that first line: 0.8 took a third
``serializer_settings`` argument, and 0.9 folded those options into
``geom_settings``. ``serializers`` also became a class attribute of
``ifcopenshell.geom`` rather than a submodule, so it must be reached as
``from ifcopenshell.geom import serializers`` (importing
``ifcopenshell.geom.serializers`` as a module raises ModuleNotFoundError).

A geometry fact this module depends on (verified against the sample model):

* Shapes are produced with DEFAULT (local-coords) settings. ``use-world-coords``
  is unnecessary here: the serializer bakes each product's placement
  (``shape.transformation.matrix``) into the vertex data regardless of that
  setting — the .dae ``<node>`` matrices come out identity and the
  ``<float_array>`` vertices are already world model-space metres relative to
  the model origin.

Because the .dae is model metres anchored at the model origin, the KML
``<Model>`` anchor is exactly the georeference base: Location =
``lonlat(base_e, base_n)`` reprojected from the IfcProjectedCRS to WGS84
(same MapConversion math as kml.py), altitude = OrthogonalHeight, heading 0
(dxf2bim writes no rotation). Google Earth reads model +X as east and +Y as
north in metres, matching the model's grid axes (grid-vs-ground scale
differences are negligible at structure scale).

A COLLADA KMZ is a zip: ``doc.kml`` at the root plus ``files/model.dae``. In
``gltf=True`` mode NO KMZ is written — only ``<out>.glb`` (the Cesium
escape-hatch artifact) — and its path is returned.

Requires the `bim` extra (ifcopenshell, pyproj).
"""
from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import ifcopenshell
import ifcopenshell.geom
from ifcopenshell.geom import serializers
from pyproj import Transformer

from bimforge.bim.georef import read_map_conversion

# Mirrors kml.py: |model coordinate| beyond this is not plausible for a
# properly-based model in metres; it is the signature of the <= 0.1.10
# georeferencing bug.
_LEGACY_COORD_LIMIT_M = 1e6

#: Google Earth web import limits ("Import KML" help): total vertices across
#: the file, and features (placemarks).
GE_WEB_MAX_VERTICES = 250_000
GE_WEB_MAX_FEATURES = 10_000
#: (lon/lat, altitude) decimals for the web KMZ: 1e-9 deg ~ 0.1 mm, so a small
#: mesh triangle keeps three distinct printed corners.
WEB_PRECISION = (9, 4)


def _reject_legacy_coords(prod, shape) -> None:
    """The same legacy-georef guard kml.py applies, on the same world verts.

    The serializer bakes ``shape.transformation.matrix`` into the .dae, so
    world coordinates are what Earth will see — check them, same message.
    """
    verts = shape.geometry.verts  # flat [x y z ...] metres, local coords
    mt = shape.transformation.matrix  # column-major 4x4, last column = T
    for i in range(len(verts) // 3):
        x, y, z = verts[i * 3], verts[i * 3 + 1], verts[i * 3 + 2]
        wx = mt[0] * x + mt[4] * y + mt[8] * z + mt[12]
        wy = mt[1] * x + mt[5] * y + mt[9] * z + mt[13]
        if abs(wx) > _LEGACY_COORD_LIMIT_M or abs(wy) > _LEGACY_COORD_LIMIT_M:
            raise ValueError(
                f"{prod.is_a()} '{prod.Name}' sits at |model coordinate| > 1e6 m — "
                "this IFC was written with the broken pre-0.1.11 georeferencing "
                "(base subtracted without unit conversion); regenerate the IFC "
                "with est-bim >= 0.1.11")


def _serialize(model, out_path: Path, factory) -> int:
    """Feed every product shape through a native write-only serializer.

    Returns the element count. The serializer object must be destroyed to
    flush and close the output file (finalize() alone leaves it empty), so
    it never escapes this function.
    """
    settings = ifcopenshell.geom.settings()  # default local coords, see module doc
    # ifcopenshell 0.9 merged the separate `serializer_settings` object into
    # `settings`, so the factory takes (out_filename, settings). bimforge only
    # ever passed a default-constructed serializer_settings, so there is nothing
    # to carry over. 0.8 required the three-argument form; this module now
    # requires >= 0.9 (see bimforge's pyproject).
    s = factory(str(out_path), settings)
    if not s.ready():
        raise RuntimeError(f"geometry serializer could not open {out_path}")
    # Without this the .dae <unit> magnitude is uninitialized garbage.
    s.setUnitNameAndMagnitude("METER", 1.0)
    # 0.9 takes the ifcopenshell.file itself; `.wrapped_data` is gone.
    s.setFile(model)
    s.writeHeader()
    count = 0
    try:
        for prod in model.by_type("IfcProduct"):
            if not prod.Representation:
                continue
            try:
                shape = ifcopenshell.geom.create_shape(settings, prod)
            except Exception:
                continue
            _reject_legacy_coords(prod, shape)
            s.write(shape)
            count += 1
        s.finalize()
    finally:
        del s  # the native serializer flushes + closes only on destruction
    return count


def _require_products(count: int, ifc_path: Path) -> None:
    """An IFC with no serializable products (nothing has a Representation, or
    every create_shape failed) would still yield a syntactically valid but
    empty .dae/.glb — refuse instead of silently writing an unusable file."""
    if count == 0:
        raise ValueError(
            f"no products with usable geometry in {ifc_path} — "
            "refusing to write an empty model")


def _doc_kml(name: str, lon: float, lat: float, alt: float) -> str:
    """Hand-rolled doc.kml: a site Point placemark + the COLLADA Model."""
    name = escape(name)
    loc = (f"<longitude>{lon:.9f}</longitude>"
           f"<latitude>{lat:.9f}</latitude>"
           f"<altitude>{alt:.3f}</altitude>")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
        f"<name>{name}</name>"
        f"<Placemark><name>{name}</name>"
        "<Point><altitudeMode>absolute</altitudeMode>"
        f"<coordinates>{lon:.9f},{lat:.9f},{alt:.3f}</coordinates></Point>"
        "</Placemark>"
        f"<Placemark><name>{name} model</name>"
        "<Model><altitudeMode>absolute</altitudeMode>"
        f"<Location>{loc}</Location>"
        "<Orientation><heading>0</heading><tilt>0</tilt><roll>0</roll></Orientation>"
        "<Scale><x>1</x><y>1</y><z>1</z></Scale>"
        "<Link><href>files/model.dae</href></Link>"
        "</Model></Placemark>"
        "</Document></kml>"
    )


def ifc_to_web_kmz(ifc_path, out_path=None, *, massing: bool = False,
                   vshift_m: float | None = None, omit: str | None = None,
                   check_limits: bool = True) -> dict:
    """Write the Google Earth web KMZ (polygon KML as ``doc.kml``).

    Returns `kml.ifc_to_kml`'s stats dict with ``out`` = the KMZ. Raises
    ValueError when the model exceeds Earth web's import limits (suggesting
    ``massing`` / ``omit``) unless ``check_limits`` is False.
    """
    from bimforge.bim.kml import ifc_to_kml
    ifc_path = Path(ifc_path)
    if not ifc_path.is_file():
        raise OSError(f"no such IFC file: {ifc_path}")
    out = Path(out_path) if out_path else ifc_path.with_suffix(".kmz")
    with tempfile.TemporaryDirectory() as td:
        doc = Path(td) / "doc.kml"
        info = ifc_to_kml(ifc_path, doc, massing=massing, vshift_m=vshift_m,
                          precision=WEB_PRECISION, omit=omit,
                          drop_degenerate=True)
        if not info["elements"]:
            raise ValueError(f"no products with usable geometry in {ifc_path} — "
                             "refusing to write an empty model")
        text = doc.read_text(encoding="utf-8")
        if re.search(r"<Model[\s>]", text):      # never on this route (#306)
            raise RuntimeError("web KMZ would contain a <Model> element, "
                               "which Google Earth web cannot import")
        if check_limits and (info["vertices"] > GE_WEB_MAX_VERTICES
                             or info["placemarks"] > GE_WEB_MAX_FEATURES):
            raise ValueError(
                f"{info['vertices']:,} vertices / {info['placemarks']:,} "
                f"placemarks exceeds Google Earth web's import limit "
                f"({GE_WEB_MAX_VERTICES:,} vertices, {GE_WEB_MAX_FEATURES:,} "
                "features) — rerun with --massing (bounding-box blocks) or "
                "--omit REGEX to leave reference geometry out")
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(doc, "doc.kml")
    info["out"] = out
    return info


def ifc_to_kmz(ifc_path, out_path=None, *, gltf: bool = False,
               collada: bool = False, massing: bool = False,
               vshift_m: float | None = None, omit: str | None = None) -> Path:
    """Write a KMZ (or, with ``gltf=True``, ONLY a .glb) for the IFC.

    Default: the Google Earth web polygon KMZ (`ifc_to_web_kmz`). With
    ``collada=True``: the COLLADA ``<Model>`` KMZ (Google Earth Pro only).
    Default output sits next to the IFC (`.kmz` / `.glb`). Returns the path
    written. Raises ValueError for a non-georeferenced IFC or one carrying
    the legacy (<= 0.1.10) broken georeference — same messages as kml.py.
    """
    if gltf and collada:
        raise ValueError("gltf and collada are alternative outputs; pick one")
    if (gltf or collada) and (massing or omit):
        raise ValueError("massing / omit apply to the web (polygon) KMZ only")
    if not (gltf or collada):
        return ifc_to_web_kmz(ifc_path, out_path, massing=massing,
                              vshift_m=vshift_m, omit=omit)["out"]
    ifc_path = Path(ifc_path)
    if not ifc_path.is_file():
        raise OSError(f"no such IFC file: {ifc_path}")
    suffix = ".glb" if gltf else ".kmz"
    out = Path(out_path) if out_path else ifc_path.with_suffix(suffix)

    model = ifcopenshell.open(str(ifc_path))
    georef = read_map_conversion(model)
    tfm = Transformer.from_crs(f"EPSG:{georef.epsg}", "EPSG:4326", always_xy=True)
    # The .dae is model metres anchored at the model origin, so the anchor is
    # the MapConversion base itself (base + 0 * Scale).
    lon, lat = tfm.transform(georef.base_e, georef.base_n)
    # OrthogonalHeight is in target-CRS units (ftUS for a foot State Plane
    # zone), but KML <altitude> is always metres -- convert exactly as kml.py
    # does (#134/#174). 1 model unit = unit_scale m = Scale map units, so map
    # units -> metres is unit_scale / Scale. Passing georef.height verbatim
    # floated foot-CRS models ~200 ft high in Google Earth.
    from ifcopenshell.util.unit import calculate_unit_scale
    datum_m = georef.height * calculate_unit_scale(model) / georef.scale
    datum_m += vshift_m or 0.0      # NAVD88 -> EGM96 geoid correction, as kml.py

    with tempfile.TemporaryDirectory() as td:
        if gltf:
            glb = Path(td) / "model.glb"
            _require_products(_serialize(model, glb, serializers.gltf), ifc_path)
            shutil.move(str(glb), out)
            return out

        dae = Path(td) / "model.dae"
        _require_products(_serialize(model, dae, serializers.collada), ifc_path)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("doc.kml", _doc_kml(ifc_path.stem, lon, lat, datum_m))
            zf.write(dae, "files/model.dae")
    return out
