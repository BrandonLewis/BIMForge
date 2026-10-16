"""bim.georef: resolve_epsg zone-name wiring + read_map_conversion.

resolve_epsg cases are pure-Python (no ifcopenshell needed); the round-trip
and read_map_conversion tests build a tiny DXF -> IFC through dxf2bim, same
fixture pattern as test_georef.py.
"""
from __future__ import annotations

import pytest

from bimforge.bim.georef import ZONES, GeoRef, resolve_epsg  # noqa: E402

ezdxf = pytest.importorskip("ezdxf")
pytest.importorskip("shapely")
ifcopenshell = pytest.importorskip("ifcopenshell")

from bimforge.bim.dxf2bim import UNIT_TO_M, build_ifc, extract_features  # noqa: E402
from bimforge.bim.georef import read_map_conversion  # noqa: E402

BASE_E, BASE_N = 6_440_000.0, 2_120_000.0
FT = UNIT_TO_M["ft"]

LAYERS = {
    "A-SLAB": {
        "ifc_class": "IfcSlab",
        "predefined_type": "FLOOR",
        "feature": "area",
        "height": 0.2,
    },
}


# ----------------------------------------------------------------------------
# resolve_epsg
# ----------------------------------------------------------------------------
def test_resolve_epsg_from_crs_epsg_int():
    assert resolve_epsg({"crs_epsg": 2227}) == 2227


def test_resolve_epsg_from_zone_name():
    assert resolve_epsg({"zone": "CA_SP_ZONE3"}) == ZONES["CA_SP_ZONE3"] == 2227


def test_resolve_epsg_zone_name_case_insensitive():
    assert resolve_epsg({"zone": "ca_sp_zone3"}) == 2227
    assert resolve_epsg({"zone": "Ca_Sp_Zone2"}) == ZONES["CA_SP_ZONE2"] == 2226


def test_resolve_epsg_crs_epsg_wins_when_both_present():
    assert resolve_epsg({"crs_epsg": 4326, "zone": "CA_SP_ZONE3"}) == 4326


def test_resolve_epsg_unknown_zone_raises_listing_zones():
    with pytest.raises(ValueError) as exc:
        resolve_epsg({"zone": "TX_SP_CENTRAL"})
    msg = str(exc.value)
    assert "TX_SP_CENTRAL" in msg
    for name in ZONES:
        assert name in msg


def test_resolve_epsg_neither_key_returns_none():
    assert resolve_epsg({}) is None
    assert resolve_epsg({"base_easting": 0.0}) is None
    assert resolve_epsg(None) is None


# ----------------------------------------------------------------------------
# dxf2bim round-trip: zone: vs crs_epsg: produce the identical IfcProjectedCRS
# ----------------------------------------------------------------------------
def _write_dxf(path) -> str:
    doc = ezdxf.new("R2010")
    doc.layers.add("A-SLAB")
    msp = doc.modelspace()
    pts = [(BASE_E + 100, BASE_N + 50), (BASE_E + 140, BASE_N + 50),
           (BASE_E + 140, BASE_N + 80), (BASE_E + 100, BASE_N + 80)]
    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "A-SLAB"})
    doc.saveas(str(path))
    return str(path)


def _config(georeference: dict) -> dict:
    return {
        "project": {"name": "Georef zone test"},
        "units": {"dxf_length_unit": "ft"},
        "georeference": {
            "base_easting": BASE_E,
            "base_northing": BASE_N,
            "base_height": 12.5,
            **georeference,
        },
        "layers": LAYERS,
    }


def _build(tmp_path, name, georeference: dict) -> str:
    dxf = _write_dxf(tmp_path / f"{name}.dxf")
    cfg = _config(georeference)
    features = extract_features(dxf, cfg["layers"], FT)
    ifc = str(tmp_path / f"{name}.ifc")
    build_ifc(features, cfg, ifc)
    return ifc


def test_zone_name_and_crs_epsg_produce_identical_projected_crs(tmp_path):
    ifc_zone = _build(tmp_path, "by-zone", {"zone": "CA_SP_ZONE3"})
    ifc_epsg = _build(tmp_path, "by-epsg", {"crs_epsg": 2227})

    model_zone = ifcopenshell.open(ifc_zone)
    model_epsg = ifcopenshell.open(ifc_epsg)

    crs_zone = model_zone.by_type("IfcProjectedCRS")[0]
    crs_epsg = model_epsg.by_type("IfcProjectedCRS")[0]
    assert crs_zone.Name == crs_epsg.Name == "EPSG:2227"

    conv_zone = model_zone.by_type("IfcMapConversion")[0]
    conv_epsg = model_epsg.by_type("IfcMapConversion")[0]
    assert float(conv_zone.Eastings) == float(conv_epsg.Eastings) == BASE_E
    assert float(conv_zone.Northings) == float(conv_epsg.Northings) == BASE_N
    assert float(conv_zone.Scale) == pytest.approx(float(conv_epsg.Scale))


def test_unknown_zone_in_layer_map_raises_before_writing_ifc(tmp_path):
    dxf = _write_dxf(tmp_path / "site.dxf")
    cfg = _config({"zone": "TX_SP_CENTRAL"})
    features = extract_features(dxf, cfg["layers"], FT)
    ifc = str(tmp_path / "site.ifc")
    with pytest.raises(ValueError, match="TX_SP_CENTRAL"):
        build_ifc(features, cfg, ifc)


# ----------------------------------------------------------------------------
# read_map_conversion happy path
# ----------------------------------------------------------------------------
def test_read_map_conversion_happy_path(tmp_path):
    ifc_path = _build(tmp_path, "read-happy", {"crs_epsg": 2227})
    model = ifcopenshell.open(ifc_path)

    georef = read_map_conversion(model)

    assert isinstance(georef, GeoRef)
    assert georef.base_e == BASE_E
    assert georef.base_n == BASE_N
    assert georef.scale == pytest.approx(1.0 / FT)
    assert georef.epsg == 2227
    assert georef.height == pytest.approx(12.5)


def test_nv_west_is_3423_not_3421():
    # EPSG:3423 = NAD83 / Nevada West (ftUS); 3421 is Nevada EAST.
    assert ZONES["NV_SP_WEST"] == 3423
    assert resolve_epsg({"zone": "nv_sp_west"}) == 3423


def test_crs_epsg_zero_rejected():
    with pytest.raises(ValueError, match="EPSG code"):
        resolve_epsg({"crs_epsg": 0})


def test_conflicting_zone_and_epsg_warns():
    import warnings as _w
    with _w.catch_warnings(record=True) as caught:
        _w.simplefilter("always")
        assert resolve_epsg({"zone": "CA_SP_ZONE2", "crs_epsg": 2227}) == 2227
    assert any("crs_epsg wins" in str(c.message) for c in caught)
