"""Layout sheet: alignment on C-ROAD-CNTR, station ticks, structure markers."""
import pytest

pytest.importorskip("bimforge.cad")
ezdxf = pytest.importorskip("ezdxf")

from bimforge.sheets.layout import draw_layout_sheet
from bimforge.sheets.model import Alignment, SheetMeta

ALIGN = Alignment(name="P-LINE", points=[
    {"station": 10000.0, "northing": 1000.0, "easting": 5000.0},
    {"station": 10300.0, "northing": 1300.0, "easting": 5000.0}])
META = SheetMeta(project="Job X", sheet_title="LAYOUT", grade="approximate")
STRUCTURES = [{"structure_id": "headwall-type-1", "station": 10150.0,
               "offset_ft": 20.0, "side": "RT"}]


def _entity_text(e):
    """TEXT keeps its string on dxf.text; MTEXT exposes it as `.text`."""
    return e.dxf.text if e.dxftype() == "TEXT" else e.text


def test_draw_layout_sheet(tmp_path):
    out = draw_layout_sheet(ALIGN, META, tmp_path / "layout.dxf",
                            structures=STRUCTURES, tick_interval=100.0)
    doc = ezdxf.readfile(out)
    msp = doc.modelspace()
    center = [e for e in msp.query("LWPOLYLINE") if e.dxf.layer == "C-ROAD-CNTR"]
    assert len(center) == 1
    tick_texts = [e for e in msp.query("TEXT MTEXT") if "100+" in _entity_text(e)]
    assert tick_texts  # station labels rendered (e.g. 100+00)
    # structure marker sits offset RIGHT of the northbound alignment (+E side)
    markers = [e for e in msp.query("CIRCLE") if e.dxf.layer == "S-ANNO-SYMB"]
    assert markers and markers[0].dxf.center[0] == pytest.approx(5020.0)
    texts = " ".join(getattr(e, "text", "") for e in msp.query("MTEXT"))
    assert "NOT FOR CONSTRUCTION LAYOUT" in texts  # approximate grade caveat
    assert "C-ANNO-TEXT" in {layer.dxf.name for layer in doc.layers}


def test_offset_side_convention_east_alignment():
    a = Alignment(name="E", points=[
        {"station": 0.0, "northing": 0.0, "easting": 0.0},
        {"station": 100.0, "northing": 0.0, "easting": 100.0}])
    from bimforge.sheets.layout import station_offset_to_ne
    n, e = station_offset_to_ne(a, 50.0, 10.0, "RT")
    assert (n, e) == (pytest.approx(-10.0), pytest.approx(50.0))  # RT of eastbound = south
    n, e = station_offset_to_ne(a, 50.0, 10.0, "LT")
    assert n == pytest.approx(10.0)
    assert e == pytest.approx(50.0)


SP_ALIGN = Alignment(name="P-LINE", points=[
    {"station": 10000.0, "northing": 2121427.76, "easting": 6441889.26},
    {"station": 10300.0, "northing": 2121500.00, "easting": 6441900.00}])
SP_STRUCTURES = [{"structure_id": "headwall-type-1", "station": 10150.0,
                  "offset_ft": 20.0, "side": "RT"}]


def test_layout_kml():
    pytest.importorskip("pyproj")
    import re

    from bimforge.sheets.layout import layout_kml

    meta = SheetMeta(project="Job X", sheet_title="LAYOUT", grade="approximate",
                     crs_epsg=2227)
    kml = layout_kml(SP_ALIGN, meta, SP_STRUCTURES)
    assert kml is not None and "<kml" in kml
    assert "headwall-type-1" in kml
    m = re.search(r"<coordinates>(-?[\d.]+),(-?[\d.]+)", kml)
    lon, lat = float(m.group(1)), float(m.group(2))
    assert -125 < lon < -114 and 32 < lat < 42  # CA; also proves lon,lat order
    assert layout_kml(SP_ALIGN, META) is None  # META has no crs_epsg


def test_layout_kml_applies_combined_factor():
    pytest.importorskip("pyproj")
    import re

    from bimforge.cad.geo import StatePlane
    from bimforge.sheets.layout import layout_kml, station_offset_to_ne
    cf = 1.000254948
    sp = StatePlane(2227)
    align = Alignment("A", [
        {"station": 0.0, "northing": 2_121_000.0, "easting": 6_441_000.0},
        {"station": 100.0, "northing": 2_121_100.0, "easting": 6_441_000.0}])
    meta = SheetMeta(project="J", sheet_title="L", grade="survey",
                     crs_epsg=2227, combined_factor=cf)
    kml = layout_kml(align, meta, structures=[
        {"structure_id": "S1", "station": 50.0, "offset_ft": 20.0, "side": "RT"}])
    coords = re.findall(r"<coordinates>(-?[\d.]+),(-?[\d.]+)", kml)
    assert len(coords) == 2  # alignment linestring, then the S1 point
    lon, lat = float(coords[0][0]), float(coords[0][1])
    exp_lon, exp_lat = sp.to_lonlat_ne(2_121_000.0 / cf, 6_441_000.0 / cf)
    assert lat == pytest.approx(exp_lat, abs=1e-6)
    assert lon == pytest.approx(exp_lon, abs=1e-6)
    # the structures leg must be factored too, not just the linestring
    s_lon, s_lat = float(coords[1][0]), float(coords[1][1])
    n, e = station_offset_to_ne(align, 50.0, 20.0, "RT")
    exp_s_lon, exp_s_lat = sp.to_lonlat_ne(n / cf, e / cf)
    assert s_lat == pytest.approx(exp_s_lat, abs=1e-6)
    assert s_lon == pytest.approx(exp_s_lon, abs=1e-6)


def test_structure_without_side_labels_default_rt(tmp_path):
    """A structures entry with no `side` key still resolves to RT for both
    the placement math and the callout label (never a blank side)."""
    structures = [{"structure_id": "headwall-type-2", "station": 10150.0,
                   "offset_ft": 20.0}]
    out = draw_layout_sheet(ALIGN, META, tmp_path / "layout_no_side.dxf",
                            structures=structures, tick_interval=100.0)
    doc = ezdxf.readfile(out)
    msp = doc.modelspace()
    callouts = [e.text for e in msp.query("MTEXT") if "headwall-type-2" in e.text]
    assert callouts and "RT" in callouts[0]


def test_layout_annotation_scales_with_plot_scale(tmp_path):
    from bimforge.sheets.layout import draw_layout_sheet
    align = Alignment("A", [
        {"station": 0.0, "northing": 1000.0, "easting": 5000.0},
        {"station": 400.0, "northing": 1400.0, "easting": 5000.0}])
    meta = SheetMeta(project="J", sheet_title="L", grade="survey")
    heights = {}
    for name, sc in (("s30", 1 / 30), ("s1200", 1 / 1200)):
        out = draw_layout_sheet(align, meta, tmp_path / f"{name}.dxf",
                                scale=sc)
        doc = ezdxf.readfile(out)
        hs = {round(e.dxf.height, 6) for e in doc.modelspace().query("TEXT")}
        assert len(hs) == 1
        heights[name] = hs.pop()
    assert heights["s1200"] == pytest.approx(heights["s30"] * 40.0)
