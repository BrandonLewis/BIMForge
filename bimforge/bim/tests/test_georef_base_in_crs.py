"""A georeference base must land inside its CRS, and federated sources must
share the federation's georeference (on top of #58).

Metre Eastings/Northings under a US-survey-feet zone keep MapConversion.Scale
right, so #58's Scale check passes them, yet read as declared the model sits
~1,480 km off the coast. These pin the base-point check that refuses that,
and the federation check that a source's own georeference matches the ctx.
"""
from __future__ import annotations

import uuid

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
pytest.importorskip("pyproj")

from pyproj import Transformer  # noqa: E402

from bimforge.cad.geo import check_base_in_crs  # noqa: E402

FTUS = 0.30480060960121924
SITE_LAT, SITE_LON = 38.60, -121.50                  # a point in CA zone 2
E_M, N_M = Transformer.from_crs(4326, 26942, always_xy=True).transform(SITE_LON, SITE_LAT)
E_FT, N_FT = Transformer.from_crs(4326, 2226, always_xy=True).transform(SITE_LON, SITE_LAT)


def test_base_in_crs_accepts_matching_units_and_full_coordinate_origin():
    check_base_in_crs(2226, E_FT, N_FT)
    check_base_in_crs(26942, E_M, N_M)
    check_base_in_crs(2226, 0.0, 0.0)               # geometry at full coordinates


def test_metre_values_under_ftus_zone_refused_with_hint():
    with pytest.raises(ValueError, match="read as metres"):
        check_base_in_crs(2226, E_M, N_M)


def test_foot_values_under_metre_zone_refused_with_hint():
    with pytest.raises(ValueError, match="read as US survey feet"):
        check_base_in_crs(26942, E_FT, N_FT)


def _ctx(**kw):
    from bimforge.author.project import ProjectContext
    base = dict(name="Units Fixture", epsg=2226, base_e=E_FT, base_n=N_FT,
                guid_ns=uuid.UUID(int=815))
    base.update(kw)
    return ProjectContext(**base)


def _emit(ctx, path):
    from bimforge.author.emit_ifc import emit_ifc
    from bimforge.author.model import Element, StructureModel
    from bimforge.author.primitives import Prism
    m = StructureModel("u", ctx)
    p = Prism("pad", [(0, 0), (10, 0), (10, 10), (0, 10)], z_bot=0.0, z_top=1.0,
              ifc="IfcFooting")
    m.add(Element.from_geometry(p.name, p, ifc_class="IfcFooting"))
    emit_ifc(m, str(path))
    return ifcopenshell.open(str(path))


def test_emit_ifc_round_trips_to_site(tmp_path):
    import ifcopenshell.util.geolocation as geo
    f = _emit(_ctx(), tmp_path / "ok.ifc")
    e, n, _ = geo.auto_xyz2enh(f, 0.0, 0.0, 0.0)
    lon, lat = Transformer.from_crs(2226, 4326, always_xy=True).transform(e, n)
    assert lat == pytest.approx(SITE_LAT, abs=1e-5)  # ~1 m
    assert lon == pytest.approx(SITE_LON, abs=1e-5)
    tn = next(c for c in f.by_type("IfcGeometricRepresentationContext")
              if c.TrueNorth).TrueNorth.DirectionRatios
    assert tuple(tn) != (0.0, 1.0)                   # never the placeholder


def test_emit_ifc_refuses_metre_crs_for_foot_project(tmp_path):
    with pytest.raises(ValueError, match="does not match EPSG:26942"):
        _emit(_ctx(epsg=26942, base_e=E_M, base_n=N_M), tmp_path / "m.ifc")


def test_emit_ifc_refuses_metre_base_under_ftus_crs(tmp_path):
    with pytest.raises(ValueError, match="read as metres"):
        _emit(_ctx(base_e=E_M, base_n=N_M), tmp_path / "mbase.ifc")


def test_dxf2bim_metre_dxf_on_ftus_zone_converts_base(tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    pytest.importorskip("shapely")
    import ifcopenshell.util.geolocation as geo
    from bimforge.bim.dxf2bim import build_ifc, extract_features
    doc = ezdxf.new("R2010")
    doc.layers.add("A-SLAB")
    doc.modelspace().add_lwpolyline(
        [(E_M, N_M), (E_M + 12, N_M), (E_M + 12, N_M + 9), (E_M, N_M + 9)],
        close=True, dxfattribs={"layer": "A-SLAB"})
    dxf = tmp_path / "m.dxf"
    doc.saveas(str(dxf))
    cfg = {"project": {"name": "m"}, "units": {"dxf_length_unit": "m"},
           "georeference": {"crs_epsg": 2226},
           "layers": {"A-SLAB": {"ifc_class": "IfcSlab", "predefined_type": "FLOOR",
                                 "feature": "area", "height": 0.2}}}
    out = tmp_path / "m.ifc"
    build_ifc(extract_features(str(dxf), cfg["layers"], 1.0), cfg, str(out))
    f = ifcopenshell.open(str(out))
    conv = f.by_type("IfcMapConversion")[0]
    assert float(conv.Eastings) == pytest.approx(E_FT, abs=1e-3)   # ftUS now
    assert float(conv.Scale) == pytest.approx(1 / FTUS)
    e, n, _ = geo.auto_xyz2enh(f, 12.0, 9.0, 0.0)                 # NE corner
    assert e == pytest.approx((E_M + 12) / FTUS, abs=1e-3)
    assert n == pytest.approx((N_M + 9) / FTUS, abs=1e-3)


def test_federate_refuses_source_on_another_base(tmp_path):
    from bimforge.author.federate import federate
    a = tmp_path / "a.ifc"
    _emit(_ctx(base_e=E_FT + 1000.0), a)
    with pytest.raises(ValueError, match="Eastings"):
        federate([(a, "A")], str(tmp_path / "fed.ifc"), _ctx())
    federate([(a, "A")], str(tmp_path / "fed2.ifc"), _ctx(), georef_check=False)


def test_local_base_outside_zone_in_every_unit_only_warns():
    with pytest.warns(UserWarning, match="outside the CRS's area of use"):
        check_base_in_crs(26910, 6440.0, 2120.0)
