"""IFC -> QGIS-consumable GeoPackage (the GIS export route).

Turns a georeferenced IFC (ours or a foreign export) into a true-3D GeoPackage
that opens directly in QGIS: solids become MultiPolygonZ (the triangulated
boundary mesh) or, with ``tin=True``, OGC-valid TIN Z; curve-only elements
(Axis/GeometricCurveSet linework — culvert axes, alignments) become
MultiLineStringZ. One feature table (== QGIS layer) per input IFC per geometry
kind. Each feature carries its IFC class, name, GlobalId, classification (cost
code) and base quantities as attributes, so the layer is queryable, not just
viewable.

Georeferencing reuses ``bimforge.bim.georef.read_map_conversion``: model metres
map onto the projected CRS (E = base + x_model * factor) exactly as kml.py does,
but the coordinates STAY in the projected CRS (no WGS84 round-trip) so distances
read in the CRS's own unit and QGIS edits in engineering feet/metres.

Two unit subtleties this module gets right:
  * The metre->CRS-unit factor is taken from the CRS (pyproj), NOT from
    IfcMapConversion.Scale, which is authored inconsistently across files (1.0
    where it should be ~3.28); geometry from ifcopenshell.geom is always metres,
    so one CRS-derived factor scales X/Y/Z uniformly.
  * Qto quantity values are stored in the FILE's length unit (not metres), so
    they scale by ``calculate_unit_scale * factor`` (1.0 for a feet-authored
    file), a different factor from the geometry's.

An optional ``index_path`` (a locations/index IFC — geometry-less elements that
carry only property sets, e.g. a project's structures index) merges each
element's semantics (station/offset/elevation/source-sheet/...) onto the matching
detailed geometry by longest-prefix name match, prefixed ``s_``. Restrict which
property set is read with ``index_pset``; the default merges every set.

The GeoPackage is written with stdlib sqlite3 + shapely ISO WKB (TIN WKB is
hand-assembled), so the export needs no GDAL/fiona. Requires the ``bim`` extra
(ifcopenshell, shapely, pyproj).

Examples:
    from bimforge.bim.ifc2gis import ifc_to_gpkg
    ifc_to_gpkg(["culverts.ifc", "site.ifc"], "site.gpkg",
                index_path="structures.ifc", tin=True)
"""
from __future__ import annotations

import sqlite3
import struct
from dataclasses import dataclass, field
from pathlib import Path

import ifcopenshell
import ifcopenshell.geom
from ifcopenshell.util.unit import calculate_unit_scale

from bimforge.bim.georef import read_map_conversion
from bimforge.bim.ifc2dxf import _chains_from_edges, _world_pts

_LEGACY_COORD_LIMIT_M = 1e6   # pre-0.1.11 broken-georef signature (same as kml.py)
_AREA_EPS = 1e-9              # degenerate-triangle cutoff (true 3D area)

# ISO SQL/MM WKB type codes (Z variants = 2D code + 1000)
_WKB_TIN_Z = 1016
_WKB_TRIANGLE_Z = 1017


@dataclass
class Ifc2GisResult:
    """What `ifc_to_gpkg` did; feeds the CLI summary."""
    out: str
    solid_type: str                                # "TIN" | "MULTIPOLYGON"
    layers: list = field(default_factory=list)     # {name, geom_type, epsg, features}
    index_matched: int = 0
    skipped: list = field(default_factory=list)    # {global_id, ifc_class, reason}

    @property
    def features(self) -> int:
        return sum(l["features"] for l in self.layers)


# ---- geometry helpers ------------------------------------------------------

def _metre_to_crs(epsg: int) -> float:
    """CRS units per metre, from the CRS itself (a US-ft zone -> 3.28083...)."""
    from pyproj import CRS
    crs = CRS.from_epsg(epsg)
    if not crs.is_projected:
        raise ValueError(
            f"EPSG:{epsg} is a geographic CRS (lon/lat degrees) — ifc2gis needs "
            "a projected CRS")
    return 1.0 / crs.axis_info[0].unit_conversion_factor


def _rotation(model) -> tuple[float, float]:
    """(XAxisAbscissa, XAxisOrdinate) grid rotation; identity when absent."""
    conv = model.by_type("IfcMapConversion")[0]
    xa, xo = conv.XAxisAbscissa, conv.XAxisOrdinate
    return (1.0 if xa is None else float(xa), 0.0 if xo is None else float(xo))


def _tri_area(a, b, c) -> float:
    """True 3D triangle area = 0.5*|(b-a) x (c-a)|; a vertical face has real
    area even though its XY projection is degenerate."""
    ux, uy, uz = b[0]-a[0], b[1]-a[1], b[2]-a[2]
    vx, vy, vz = c[0]-a[0], c[1]-a[1], c[2]-a[2]
    cx, cy, cz = uy*vz-uz*vy, uz*vx-ux*vz, ux*vy-uy*vx
    return 0.5 * (cx*cx + cy*cy + cz*cz) ** 0.5


# ---- structures index (semantic join) --------------------------------------

def structure_index(path: str, pset_name: str | None = None) -> dict:
    """{key: {property: value}} from a locations/index IFC, so detailed geometry
    can inherit semantics (station/offset/elevation/source-sheet/...) that live
    only there, not on the geometry files. Reads every IfcPropertySet on each
    element (or only the one named `pset_name`); the merge key is a `StructureId`
    property when present, else the element Name."""
    model = ifcopenshell.open(path)
    idx: dict = {}
    for prod in model.by_type("IfcProduct"):
        props: dict = {}
        for rel in getattr(prod, "IsDefinedBy", []) or []:
            if not rel.is_a("IfcRelDefinesByProperties"):
                continue
            pdef = rel.RelatingPropertyDefinition
            if not pdef.is_a("IfcPropertySet"):
                continue
            if pset_name and pdef.Name != pset_name:
                continue
            for p in pdef.HasProperties or []:
                if p.is_a("IfcPropertySingleValue") and p.NominalValue is not None:
                    props[p.Name] = p.NominalValue.wrappedValue
        key = props.get("StructureId") or prod.Name
        if props and key:
            idx[key] = props
    return idx


def _match_structure(name: str, index: dict) -> dict:
    """Longest StructureId equal to `name` or a space-delimited prefix of it
    ('CULV1-HW-IN' matches 'CULV1-HW-IN headwall'). {} if none."""
    if not name:
        return {}
    best = None
    for sid in index:
        if (name == sid or name.startswith(sid + " ")) and (best is None or len(sid) > len(best)):
            best = sid
    return index.get(best, {}) if best else {}


# ---- attributes ------------------------------------------------------------

def _cost_code(prod) -> str:
    codes = []
    for rel in getattr(prod, "HasAssociations", []) or []:
        if rel.is_a("IfcRelAssociatesClassification"):
            ref = rel.RelatingClassification
            code = getattr(ref, "Identification", None) or getattr(ref, "ItemReference", None)
            if code:
                codes.append(str(code))
    return " + ".join(sorted(set(codes)))


_QTY_VALUE = {"IfcQuantityLength": "LengthValue", "IfcQuantityArea": "AreaValue",
              "IfcQuantityVolume": "VolumeValue", "IfcQuantityWeight": "WeightValue",
              "IfcQuantityCount": "CountValue"}


def _quantities(prod, qf: float) -> dict:
    """Base quantities normalized to CRS units. `qf` is the file-unit -> CRS-unit
    LENGTH factor (calculate_unit_scale * metre_to_crs): Qto values are stored in
    the file's length unit, so this differs from the geometry factor. Length*qf,
    area*qf^2, volume*qf^3; weight/count unscaled."""
    dim = {"IfcQuantityLength": qf, "IfcQuantityArea": qf*qf, "IfcQuantityVolume": qf**3,
           "IfcQuantityWeight": 1.0, "IfcQuantityCount": 1.0}
    out: dict = {}
    for rel in getattr(prod, "IsDefinedBy", []) or []:
        if not rel.is_a("IfcRelDefinesByProperties"):
            continue
        pdef = rel.RelatingPropertyDefinition
        if not pdef.is_a("IfcElementQuantity"):
            continue
        for q in pdef.Quantities or []:
            k = q.is_a()
            v = getattr(q, _QTY_VALUE.get(k, ""), None) if k in _QTY_VALUE else None
            if v is not None:
                out[q.Name] = float(v) * dim[k]
    return out


# ---- extraction ------------------------------------------------------------

def features_for(model_path, index: dict | None = None):
    """Return (epsg, polygons, lines). polygons items are (triangles, attrs)
    where triangles is a list of ((x,y,z),(x,y,z),(x,y,z)) in CRS units; lines
    items are (list_of_polylines, attrs). If `index` is given each feature
    inherits its matched structure's `s_`-prefixed semantics."""
    index = index or {}
    model = ifcopenshell.open(str(model_path))
    gr = read_map_conversion(model)
    f = _metre_to_crs(gr.epsg)                    # geometry: metres -> CRS unit
    qf = calculate_unit_scale(model) * f          # quantities: file unit -> CRS unit
    xa, xo = _rotation(model)
    base_e, base_n, H = gr.base_e, gr.base_n, gr.height

    def to_crs(x, y, z):
        return (base_e + f * (x*xa - y*xo), base_n + f * (x*xo + y*xa), z*f + H)

    import ifcopenshell.ifcopenshell_wrapper as ifc_wrapper
    settings = ifcopenshell.geom.settings()
    # Include curve geometry so curve-only elements (Axis/GeometricCurveSet:
    # alignments, stationing, control lines) tessellate to edges instead of
    # raising; solids are unaffected. Uses the named enum, not a magic int.
    settings.set("dimensionality", ifc_wrapper.CURVES_SURFACES_AND_SOLIDS)

    polygons, lines, skipped = [], [], []
    for prod in model.by_type("IfcProduct"):
        if not prod.Representation:
            continue
        try:
            shape = ifcopenshell.geom.create_shape(settings, prod)
        except Exception as exc:   # ifcopenshell raises plain RuntimeError
            skipped.append({"global_id": prod.GlobalId, "ifc_class": prod.is_a(),
                            "reason": f"tessellation failed: {exc}"})
            continue
        # create_shape returns SI metres (it applies the file's unit scale
        # internally), verified against a foot-unit file: a 21 ft object comes
        # back as 6.40 m. So `f` (metre->CRS unit) scales geometry directly and
        # NO model_unit_scale factor is applied here — that differs from
        # ifc2dxf, whose settings hand back native units. `qf` still carries the
        # file-unit factor for Qto values (which ARE stored in file units).
        pts = _world_pts(shape)
        if any(abs(p[0]) > _LEGACY_COORD_LIMIT_M or abs(p[1]) > _LEGACY_COORD_LIMIT_M for p in pts):
            raise ValueError(
                f"{prod.is_a()} '{prod.Name}' sits at |model coordinate| > 1e6 m — "
                "this IFC was written with the broken pre-0.1.11 georeferencing; "
                "regenerate the IFC with est-bim >= 0.1.11")
        cpts = [to_crs(*p) for p in pts]
        attrs = {"ifc_class": prod.is_a(),
                 "predefined_type": str(getattr(prod, "PredefinedType", "") or ""),
                 "name": prod.Name or "", "global_id": prod.GlobalId,
                 "cost_code": _cost_code(prod)}
        # Quantity/index names are user-defined IFC strings; never let one
        # overwrite a canonical identity field (a Qto literally named "name").
        for k, v in _quantities(prod, qf).items():
            attrs.setdefault(k, v)
        for k, v in _match_structure(prod.Name or "", index).items():
            attrs.setdefault(f"s_{k}", v)

        faces, edges = shape.geometry.faces, shape.geometry.edges
        if faces:
            tris = []
            for k in range(0, len(faces), 3):
                a, b, c = cpts[faces[k]], cpts[faces[k+1]], cpts[faces[k+2]]
                if _tri_area(a, b, c) > _AREA_EPS:
                    tris.append((a, b, c))
            if tris:
                polygons.append((tris, attrs))
        elif edges:
            chains = _chains_from_edges(list(edges))
            polylines = [[cpts[i] for i in ch] for ch in chains if len(ch) >= 2]
            if polylines:
                lines.append((polylines, attrs))
    return gr.epsg, polygons, lines, skipped


# ---- GeoPackage writer (stdlib sqlite3, no GDAL) ---------------------------

_GP_MAGIC = b"GP"


def _gp_header(srs_id: int) -> bytes:
    return _GP_MAGIC + struct.pack("<BBi", 0, 0x01, srs_id)  # v0, LE, no envelope


def _multipolygon_wkb(triangles) -> bytes:
    """ISO MultiPolygon Z (each triangle a closed polygon) via shapely."""
    import shapely
    from shapely.geometry import MultiPolygon, Polygon
    mp = MultiPolygon([Polygon([*tri, tri[0]]) for tri in triangles])
    return shapely.to_wkb(mp, output_dimension=3, flavor="iso", byte_order=1)


def _multilinestring_wkb(polylines) -> bytes:
    import shapely
    from shapely.geometry import LineString, MultiLineString
    mls = MultiLineString([LineString(pl) for pl in polylines])
    return shapely.to_wkb(mls, output_dimension=3, flavor="iso", byte_order=1)


def _tin_wkb(triangles) -> bytes:
    """OGC-valid TIN Z (ISO WKB): a TIN of Triangle Z patches. Each Triangle
    carries its own byte-order+type header (OGC SFA 06-103r4); its single closed
    ring has 4 points (a,b,c,a). shapely has no TIN type, so this is assembled
    by hand."""
    buf = bytearray(struct.pack("<BII", 1, _WKB_TIN_Z, len(triangles)))
    for a, b, c in triangles:
        buf += struct.pack("<BIII", 1, _WKB_TRIANGLE_Z, 1, 4)
        for x, y, z in (a, b, c, a):
            buf += struct.pack("<ddd", x, y, z)
    return bytes(buf)


def _srs_rows(epsg: int):
    """(srs_name, srs_id, organization, organization_coordsys_id, definition,
    description) rows: the two mandatory undefined SRSes, WGS84, and ours."""
    from pyproj import CRS
    return [
        ("Undefined cartesian SRS", -1, "NONE", -1, "undefined",
         "undefined cartesian coordinate reference system"),
        ("Undefined geographic SRS", 0, "NONE", 0, "undefined",
         "undefined geographic coordinate reference system"),
        ("WGS 84 geodetic", 4326, "EPSG", 4326, CRS.from_epsg(4326).to_wkt(),
         "longitude/latitude coordinates in decimal degrees on WGS 84"),
        (f"EPSG:{epsg}", epsg, "EPSG", epsg, CRS.from_epsg(epsg).to_wkt(), f"EPSG:{epsg}"),
    ]


def _bbox(feats):
    minx = miny = float("inf"); maxx = maxy = float("-inf")
    for geom, _ in feats:
        for part in geom:                       # triangle or polyline
            for x, y, *_ in part:
                minx, miny, maxx, maxy = min(minx, x), min(miny, y), max(maxx, x), max(maxy, y)
    return (minx, miny, maxx, maxy) if feats and maxx > -float("inf") else (0, 0, 0, 0)


_GPKG_DDL = """
CREATE TABLE gpkg_spatial_ref_sys (
  srs_name TEXT NOT NULL, srs_id INTEGER PRIMARY KEY,
  organization TEXT NOT NULL, organization_coordsys_id INTEGER NOT NULL,
  definition TEXT NOT NULL, description TEXT);
CREATE TABLE gpkg_contents (
  table_name TEXT PRIMARY KEY, data_type TEXT NOT NULL, identifier TEXT UNIQUE,
  description TEXT DEFAULT '',
  last_change DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  min_x DOUBLE, min_y DOUBLE, max_x DOUBLE, max_y DOUBLE, srs_id INTEGER);
CREATE TABLE gpkg_geometry_columns (
  table_name TEXT NOT NULL, column_name TEXT NOT NULL, geometry_type_name TEXT NOT NULL,
  srs_id INTEGER NOT NULL, z TINYINT NOT NULL, m TINYINT NOT NULL,
  CONSTRAINT pk_geom_cols PRIMARY KEY (table_name, column_name));
CREATE TABLE gpkg_extensions (
  table_name TEXT, column_name TEXT, extension_name TEXT NOT NULL,
  definition TEXT NOT NULL, scope TEXT NOT NULL,
  CONSTRAINT ge_tce UNIQUE (table_name, column_name, extension_name));
"""


def _write_gpkg(out_path, layers):
    """layers: list of (table_name, geom_type_name, epsg, [(geom, attrs)])."""
    out = Path(out_path)
    if out.exists():
        out.unlink()
    con = sqlite3.connect(str(out))
    try:
        cur = con.cursor()
        cur.execute("PRAGMA application_id = 1196444487;")   # 'GPKG'
        cur.execute("PRAGMA user_version = 10200;")
        cur.executescript(_GPKG_DDL)
        seen = set()
        for _, _, epsg, _ in layers:
            for row in _srs_rows(epsg):
                if row[1] not in seen:
                    seen.add(row[1])
                    cur.execute("INSERT INTO gpkg_spatial_ref_sys VALUES (?,?,?,?,?,?)", row)
        for table, gtype, epsg, feats in layers:
            attr_keys, texty = {}, set()
            for _, a in feats:
                for k, v in a.items():
                    attr_keys.setdefault(k, "REAL")
                    if isinstance(v, str):
                        texty.add(k)
            for k in texty:
                attr_keys[k] = "TEXT"
            # Attribute names are user-defined IFC strings: make each a safe,
            # UNIQUE SQL identifier. Escape embedded quotes; dedupe
            # case-insensitively (SQLite identifiers are case-insensitive) and
            # against the reserved fid/geom columns, suffixing collisions.
            keys = list(attr_keys)
            reserved = {"fid", "geom"}
            colname = {}
            for k in keys:
                ident = k.replace('"', '""')
                base = ident.lower()
                if base in reserved:
                    i = 2
                    while f"{base}_{i}" in reserved:
                        i += 1
                    ident, base = f"{ident}_{i}", f"{base}_{i}"
                reserved.add(base)
                colname[k] = ident
            cols = ", ".join(f'"{colname[k]}" {attr_keys[k]}' for k in keys)
            cur.execute(f'CREATE TABLE "{table}" (fid INTEGER PRIMARY KEY AUTOINCREMENT, '
                        f'geom {gtype}{", " if cols else ""}{cols});')
            cur.execute("INSERT INTO gpkg_geometry_columns VALUES (?,?,?,?,?,?)",
                        (table, "geom", gtype, epsg, 1, 0))
            if gtype in ("TIN", "POLYHEDRALSURFACE", "TRIANGLE"):
                cur.execute("INSERT INTO gpkg_extensions VALUES (?,?,?,?,?)",
                            (table, "geom", f"gpkg_geom_{gtype}",
                             "http://www.geopackage.org/spec/#extension_geometry_types",
                             "read-write"))
            minx, miny, maxx, maxy = _bbox(feats)
            cur.execute("INSERT INTO gpkg_contents "
                        "(table_name,data_type,identifier,min_x,min_y,max_x,max_y,srs_id) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        (table, "features", table, minx, miny, maxx, maxy, epsg))
            ph = ",".join(["?"] * (1 + len(keys)))
            colnames = ",".join(["geom"] + [f'"{colname[k]}"' for k in keys])
            for geom, a in feats:
                if gtype == "TIN":
                    wkb = _tin_wkb(geom)
                elif gtype == "MULTIPOLYGON":
                    wkb = _multipolygon_wkb(geom)
                else:
                    wkb = _multilinestring_wkb(geom)
                cur.execute(f'INSERT INTO "{table}" ({colnames}) VALUES ({ph})',
                            (_gp_header(epsg) + wkb, *[a.get(k) for k in keys]))
        con.commit()
    finally:
        con.close()
    return out


# ---- driver ----------------------------------------------------------------

def ifc_to_gpkg(ifc_paths, out_path, *, index_path=None, index_pset=None,
                tin=False) -> Ifc2GisResult:
    """Export one or more georeferenced IFCs into a single GeoPackage.

    `ifc_paths` is a list of IFC files (each becomes a `<stem>_solids` and/or
    `<stem>_lines` layer). `index_path` optionally names a locations/index IFC
    whose per-element property-set semantics are joined onto matching detailed
    geometry (restrict to one set with `index_pset`). `tin=True` emits OGC-valid
    TIN Z solids instead of MultiPolygon Z. Raises ValueError for a
    non-georeferenced IFC.
    """
    if isinstance(ifc_paths, (str, Path)):
        ifc_paths = [ifc_paths]
    index = structure_index(index_path, index_pset) if index_path else {}
    solid_type = "TIN" if tin else "MULTIPOLYGON"
    layers, layer_meta, matched, skipped = [], [], 0, []
    used = set()

    def _uniq(base: str) -> str:
        # two inputs sharing a basename (e.g. two structures.ifc) must not
        # collide on one GeoPackage table name — suffix the later ones.
        name = base
        i = 2
        while name in used:
            name = f"{base}_{i}"
            i += 1
        used.add(name)
        return name

    for p in ifc_paths:
        stem = Path(p).stem.replace("-", "_").replace(" ", "_")
        epsg, polys, lines, sk = features_for(p, index)
        skipped.extend(sk)
        matched += sum(1 for g, a in polys + lines if any(k.startswith("s_") for k in a))
        if polys:
            name = _uniq(f"{stem}_solids")
            layers.append((name, solid_type, epsg, polys))
            layer_meta.append({"name": name, "geom_type": solid_type,
                               "epsg": epsg, "features": len(polys)})
        if lines:
            name = _uniq(f"{stem}_lines")
            layers.append((name, "MULTILINESTRING", epsg, lines))
            layer_meta.append({"name": name, "geom_type": "MULTILINESTRING",
                               "epsg": epsg, "features": len(lines)})
    _write_gpkg(out_path, layers)
    return Ifc2GisResult(out=str(out_path), solid_type=solid_type,
                         layers=layer_meta, index_matched=matched, skipped=skipped)
