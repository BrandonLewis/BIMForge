"""IFC -> GeoPackage: sample DXF (ft, EPSG:2227) -> dxf2bim -> ifc2gis -> read
the .gpkg back with stdlib sqlite3 (the way OGR/QGIS would) and assert CRS, 3D,
unit normalization, TIN validity, and the structures-index join.

The synthetic site sits near E 6.44e6 / N 2.12e6 ftUS (CA State Plane zone 3);
a 40ft x 30ft x 0.5ft deck slab and two pile markers exercise the solid path.
"""
from __future__ import annotations

import sqlite3
import struct

import pytest

ezdxf = pytest.importorskip("ezdxf")
pytest.importorskip("shapely")
ifcopenshell = pytest.importorskip("ifcopenshell")
pytest.importorskip("pyproj")

import shapely  # noqa: E402

from bimforge.bim.dxf2bim import UNIT_TO_M, build_ifc, extract_features  # noqa: E402
from bimforge.bim.ifc2gis import (  # noqa: E402
    _match_structure, features_for, ifc_to_gpkg, structure_index,
)

BASE_E, BASE_N = 6_440_000.0, 2_120_000.0
FT = UNIT_TO_M["ft"]

LAYERS = {
    "S-DECK": {"ifc_class": "IfcSlab", "predefined_type": "FLOOR",
               "feature": "area", "height": 0.5,
               "classification": {"system": "Caltrans", "code": "51-01",
                                  "name": "Structural Concrete Bridge"}},
    "S-PILE": {"ifc_class": "IfcPile", "feature": "count", "height": 10.0,
               "marker_size": 0.5},
}


def _write_dxf(path) -> str:
    doc = ezdxf.new("R2010")
    for name in LAYERS:
        doc.layers.add(name)
    msp = doc.modelspace()
    deck = [(BASE_E + 100, BASE_N + 50), (BASE_E + 140, BASE_N + 50),
            (BASE_E + 140, BASE_N + 80), (BASE_E + 100, BASE_N + 80)]
    msp.add_lwpolyline(deck, close=True, dxfattribs={"layer": "S-DECK"})
    blk = doc.blocks.new(name="PILE")
    blk.add_circle((0, 0), 1.0)
    for px, py in [(BASE_E + 110, BASE_N + 55), (BASE_E + 130, BASE_N + 55)]:
        msp.add_blockref("PILE", (px, py), dxfattribs={"layer": "S-PILE"})
    doc.saveas(str(path))
    return str(path)


def _config(base_e=BASE_E, base_n=BASE_N, base_h=0.0, epsg=2227) -> dict:
    return {
        "project": {"name": "GIS test"},
        "units": {"dxf_length_unit": "ft"},
        "georeference": {"crs_epsg": epsg, "base_easting": base_e,
                         "base_northing": base_n, "base_height": base_h},
        "layers": LAYERS,
    }


def _build_ifc(tmp_path, name="site", **cfg_kw) -> str:
    dxf = _write_dxf(tmp_path / f"{name}.dxf")
    cfg = _config(**cfg_kw)
    features = extract_features(dxf, cfg["layers"], FT)
    ifc = str(tmp_path / f"{name}.ifc")
    build_ifc(features, cfg, ifc)
    return ifc


# ---- GeoPackage readback helpers -------------------------------------------

def _rows(gpkg, table):
    con = sqlite3.connect(gpkg)
    try:
        return con.execute(f'SELECT geom FROM "{table}"').fetchall()
    finally:
        con.close()


def _geom_from_gpb(blob):
    """Strip the GeoPackage binary header (flags=1 -> no envelope, 8 bytes) and
    parse the WKB with shapely."""
    env = (blob[3] >> 1) & 0x07
    envlen = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[env]
    return shapely.from_wkb(blob[8 + envlen:])


def _parse_tin(blob):
    """Return (n_triangles, has_z) for a hand-written TIN blob."""
    env = (blob[3] >> 1) & 0x07
    p = 8 + {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[env]
    _bo, gt, ntri = struct.unpack_from("<BII", blob, p); p += 9
    assert gt == 1016, f"not TIN-Z: {gt}"
    for _ in range(ntri):
        _bo2, tt, nring, npt = struct.unpack_from("<BIII", blob, p); p += 13
        assert tt == 1017 and nring == 1 and npt == 4, (tt, nring, npt)
        p += npt * 24
    assert p == len(blob), "trailing bytes in TIN blob"
    return ntri, True


# ---- tests -----------------------------------------------------------------

def test_gpkg_is_valid_container_with_layers_and_crs(tmp_path):
    ifc = _build_ifc(tmp_path)
    out = tmp_path / "site.gpkg"
    res = ifc_to_gpkg(ifc, out)
    assert res.features == 3          # 1 slab + 2 piles, all solids
    assert res.solid_type == "MULTIPOLYGON"

    con = sqlite3.connect(str(out))
    try:
        assert con.execute("PRAGMA application_id").fetchone()[0] == 1196444487  # 'GPKG'
        tabs = [r[0] for r in con.execute("SELECT table_name FROM gpkg_contents")]
        assert tabs == ["site_solids"]
        gt, srs, z = con.execute(
            "SELECT geometry_type_name, srs_id, z FROM gpkg_geometry_columns").fetchone()
        assert (gt, srs, z) == ("MULTIPOLYGON", 2227, 1)
        assert con.execute("SELECT count(*) FROM gpkg_spatial_ref_sys "
                           "WHERE srs_id=2227").fetchone()[0] == 1
    finally:
        con.close()


def test_geometry_is_3d_and_lands_on_the_site(tmp_path):
    ifc = _build_ifc(tmp_path)
    out = tmp_path / "site.gpkg"
    ifc_to_gpkg(ifc, out)
    for (blob,) in _rows(str(out), "site_solids"):
        g = _geom_from_gpb(blob)
        assert g.geom_type == "MultiPolygon" and g.has_z
        x0, y0, x1, y1 = g.bounds
        assert BASE_E < x0 < BASE_E + 200 and BASE_N < y0 < BASE_N + 200


def test_unit_normalization_slab_is_40x30_ft(tmp_path):
    # The deck is 40ft x 30ft in the DXF; geometry comes back from ifcopenshell
    # in metres, so a wrong factor (e.g. using it as-is, or *3.28 twice) would
    # blow the footprint far off 40x30.
    ifc = _build_ifc(tmp_path)
    epsg, polys, lines, _sk = features_for(ifc)
    slab = next(pa for pa in polys if pa[1]["ifc_class"] == "IfcSlab")
    xs = [x for tri in slab[0] for x, y, z in tri]
    ys = [y for tri in slab[0] for x, y, z in tri]
    assert 39.0 < (max(xs) - min(xs)) < 41.0
    assert 29.0 < (max(ys) - min(ys)) < 31.0


def test_tin_mode_emits_valid_tin_z(tmp_path):
    ifc = _build_ifc(tmp_path)
    out = tmp_path / "site.gpkg"
    res = ifc_to_gpkg(ifc, out, tin=True)
    assert res.solid_type == "TIN"
    con = sqlite3.connect(str(out))
    try:
        assert con.execute("SELECT geometry_type_name FROM gpkg_geometry_columns "
                           "WHERE table_name='site_solids'").fetchone()[0] == "TIN"
        # extension registration is mandatory for a non-core geometry type
        ext = con.execute("SELECT extension_name, scope FROM gpkg_extensions "
                          "WHERE table_name='site_solids'").fetchone()
        assert ext == ("gpkg_geom_TIN", "read-write")
    finally:
        con.close()
    total = 0
    for (blob,) in _rows(str(out), "site_solids"):
        n, has_z = _parse_tin(blob)
        total += n
        assert has_z
    assert total > 0


def test_attributes_carry_class_and_classification(tmp_path):
    ifc = _build_ifc(tmp_path)
    out = tmp_path / "site.gpkg"
    ifc_to_gpkg(ifc, out)
    con = sqlite3.connect(str(out))
    try:
        cols = [r[1] for r in con.execute('PRAGMA table_info("site_solids")')]
        assert {"ifc_class", "name", "global_id", "cost_code"} <= set(cols)
        codes = {r[0] for r in con.execute('SELECT cost_code FROM site_solids')}
        assert "51-01" in codes  # the deck slab's classification
    finally:
        con.close()


def test_match_structure_longest_prefix():
    idx = {"CULV1": {"Kind": "SHORT"}, "CULV1-HW-IN": {"Kind": "LONG"}}
    assert _match_structure("CULV1-HW-IN headwall", idx)["Kind"] == "LONG"
    assert _match_structure("CULV1 barrel", idx)["Kind"] == "SHORT"
    assert _match_structure("CULV9", idx) == {}
    assert _match_structure("", idx) == {}


def test_structures_index_join_merges_semantics(tmp_path):
    ifc = _build_ifc(tmp_path)
    # discover a real element name, then key an index to it
    _epsg, polys, _lines, _sk = features_for(ifc)
    name = next(a["name"] for _g, a in polys if a["name"])
    index = {name: {"StructureId": name, "Kind": "TEST-KIND", "Station": "1+00"}}
    _epsg, polys2, _lines, _sk = features_for(ifc, index)
    joined = [a for _g, a in polys2 if a.get("s_Kind") == "TEST-KIND"]
    assert joined and joined[0]["s_Station"] == "1+00"


def test_structure_index_reads_pset(tmp_path):
    # a minimal index IFC: one element carrying only a semantics property set
    m = ifcopenshell.file(schema="IFC4")
    proj = m.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), Name="idx")
    el = m.create_entity("IfcBuildingElementProxy", GlobalId=ifcopenshell.guid.new(),
                         Name="CULV1-HW-IN")
    pset = m.create_entity(
        "IfcPropertySet", GlobalId=ifcopenshell.guid.new(), Name="StructureIndex",
        HasProperties=[
            m.create_entity("IfcPropertySingleValue", Name="StructureId",
                            NominalValue=m.create_entity("IfcText", "CULV1-HW-IN")),
            m.create_entity("IfcPropertySingleValue", Name="Kind",
                            NominalValue=m.create_entity("IfcText", "HEADWALL-INLET")),
        ])
    m.create_entity("IfcRelDefinesByProperties", GlobalId=ifcopenshell.guid.new(),
                    RelatedObjects=[el], RelatingPropertyDefinition=pset)
    path = str(tmp_path / "structures.ifc")
    m.write(path)
    idx = structure_index(path)
    assert idx["CULV1-HW-IN"]["Kind"] == "HEADWALL-INLET"


def test_rejects_non_georeferenced_ifc(tmp_path):
    dxf = _write_dxf(tmp_path / "site.dxf")
    cfg = _config()
    cfg["georeference"] = {}
    features = extract_features(dxf, cfg["layers"], FT)
    ifc = str(tmp_path / "site.ifc")
    build_ifc(features, cfg, ifc)
    with pytest.raises(ValueError, match=r"IfcMapConversion"):
        ifc_to_gpkg(ifc, tmp_path / "site.gpkg")


def test_duplicate_input_basenames_get_unique_tables(tmp_path):
    # two inputs sharing a basename must not collide on one GeoPackage table
    a = _build_ifc(tmp_path, name="site")
    sub = tmp_path / "sub"; sub.mkdir()
    b = _build_ifc(sub, name="site")  # same stem "site", different dir
    out = tmp_path / "both.gpkg"
    res = ifc_to_gpkg([a, b], out)
    con = sqlite3.connect(str(out))
    try:
        tabs = sorted(r[0] for r in con.execute("SELECT table_name FROM gpkg_contents"))
    finally:
        con.close()
    assert tabs == ["site_solids", "site_solids_2"]
    assert {l["name"] for l in res.layers} == {"site_solids", "site_solids_2"}


def test_cli_ifc2gis_subcommand(tmp_path, capsys):
    from bimforge.bim import cli
    ifc = _build_ifc(tmp_path)
    out = tmp_path / "site.gpkg"
    assert cli.main(["ifc2gis", "--ifc", ifc, "--out", str(out), "--tin"]) == 0
    assert out.exists()
    assert "TIN solids" in capsys.readouterr().out
