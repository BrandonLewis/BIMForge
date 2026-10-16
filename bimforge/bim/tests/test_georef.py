"""Georeferencing contract (IFC4 semantics, fixed after the 0.1.10 field bug):

  model space  = (dxf_coord - base) * unit_to_m   (base subtracted in DXF units)
  MapConversion.Eastings/Northings = base in CRS units (yaml values, unchanged)
  MapConversion.Scale = 1/unit_to_m               (model metres -> CRS units)

0.1.10 subtracted the un-converted base from metre coordinates (model coords
like -4.5e6 m) and wrote Scale=1.0 — any consumer trusting MapConversion
misplaced the model.
"""
from __future__ import annotations

import pytest

ezdxf = pytest.importorskip("ezdxf")
pytest.importorskip("shapely")
ifcopenshell = pytest.importorskip("ifcopenshell")

from bimforge.bim.dxf2bim import UNIT_TO_M, build_ifc, extract_features  # noqa: E402

# A ftUS survey base near the EPSG:2227 (CA zone 3) test site.
BASE_E, BASE_N = 6_440_000.0, 2_120_000.0
FT = UNIT_TO_M["ft"]  # 0.3048

LAYERS = {
    "A-SLAB": {
        "ifc_class": "IfcSlab",
        "predefined_type": "FLOOR",
        "feature": "area",
        "height": 0.2,
    },
}


def _write_dxf(path) -> str:
    """A 40ft x 30ft slab whose SW corner sits 100ft E / 50ft N of the base."""
    doc = ezdxf.new("R2010")
    doc.layers.add("A-SLAB")
    msp = doc.modelspace()
    pts = [(BASE_E + 100, BASE_N + 50), (BASE_E + 140, BASE_N + 50),
           (BASE_E + 140, BASE_N + 80), (BASE_E + 100, BASE_N + 80)]
    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "A-SLAB"})
    doc.saveas(str(path))
    return str(path)


def _config(base_e, base_n) -> dict:
    return {
        "project": {"name": "Georef test"},
        "units": {"dxf_length_unit": "ft"},
        "georeference": {
            "crs_epsg": 2227,
            "base_easting": base_e,
            "base_northing": base_n,
            "base_height": 0.0,
        },
        "layers": LAYERS,
    }


def _profile_xy(model) -> list[tuple[float, float]]:
    """All 2D vertices used by profile curves, model (metre) coordinates."""
    pts: list[tuple[float, float]] = []
    for plist in model.by_type("IfcCartesianPointList2D"):
        pts.extend((float(x), float(y)) for x, y in plist.CoordList)
    for p in model.by_type("IfcCartesianPoint"):
        if p.Coordinates and len(p.Coordinates) >= 2:
            pts.append((float(p.Coordinates[0]), float(p.Coordinates[1])))
    return pts


def _has_point(pts, x, y, tol=1e-6) -> bool:
    return any(abs(px - x) <= tol and abs(py - y) <= tol for px, py in pts)


def test_known_base_lands_vertex_at_dxf_minus_base_times_0_3048(tmp_path):
    dxf = _write_dxf(tmp_path / "site.dxf")
    cfg = _config(BASE_E, BASE_N)
    features = extract_features(dxf, cfg["layers"], FT)
    ifc = str(tmp_path / "site.ifc")
    build_ifc(features, cfg, ifc)

    model = ifcopenshell.open(ifc)
    pts = _profile_xy(model)
    # SW corner: (6,440,100 - 6,440,000) * 0.3048 = 30.48 m, (2,120,050 - 2,120,000) * 0.3048 = 15.24 m
    assert _has_point(pts, 100 * FT, 50 * FT)
    # NE corner: 140 ft, 80 ft from base
    assert _has_point(pts, 140 * FT, 80 * FT)
    # nothing survey-sized leaks into model space
    assert all(abs(x) < 1e6 and abs(y) < 1e6 for x, y in pts)

    conv = model.by_type("IfcMapConversion")[0]
    assert float(conv.Eastings) == BASE_E          # CRS units, unchanged pass-through
    assert float(conv.Northings) == BASE_N
    assert float(conv.Scale) == pytest.approx(1.0 / FT)  # 3.280839895... (m -> ft)
    crs = model.by_type("IfcProjectedCRS")[0]
    assert crs.Name == "EPSG:2227"


def test_null_base_uses_bbox_min_in_dxf_units_with_same_treatment(tmp_path):
    dxf = _write_dxf(tmp_path / "site.dxf")
    cfg = _config(None, None)
    features = extract_features(dxf, cfg["layers"], FT)
    ifc = str(tmp_path / "site.ifc")
    build_ifc(features, cfg, ifc)

    model = ifcopenshell.open(ifc)
    conv = model.by_type("IfcMapConversion")[0]
    # base = bbox min, expressed in DXF (= CRS) units
    assert float(conv.Eastings) == pytest.approx(BASE_E + 100, abs=1e-6)
    assert float(conv.Northings) == pytest.approx(BASE_N + 50, abs=1e-6)
    assert float(conv.Scale) == pytest.approx(1.0 / FT)

    pts = _profile_xy(model)
    # SW corner is the origin; NE corner is 40ft x 30ft away in metres
    assert _has_point(pts, 0.0, 0.0)
    assert _has_point(pts, 40 * FT, 30 * FT)


def test_build_ifc_writes_true_north_from_convergence(tmp_path):
    pytest.importorskip("pyproj")
    from bimforge.cad.geo import true_north_direction
    dxf = _write_dxf(tmp_path / "tn.dxf")
    cfg = _config(BASE_E, BASE_N)
    features = extract_features(dxf, cfg["layers"], FT)
    ifc = str(tmp_path / "tn.ifc")
    build_ifc(features, cfg, ifc)
    f = ifcopenshell.open(ifc)
    ctxs = [c for c in f.by_type("IfcGeometricRepresentationContext")
            if not c.is_a("IfcGeometricRepresentationSubContext")]
    tn = ctxs[0].TrueNorth
    assert tn is not None
    ex, ey = true_north_direction(2227, BASE_E, BASE_N)
    assert float(tn.DirectionRatios[0]) == pytest.approx(ex, abs=1e-6)
    assert float(tn.DirectionRatios[1]) == pytest.approx(ey, abs=1e-6)
