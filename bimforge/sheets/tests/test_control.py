"""Control sheet: points on NCS layers, table, KML, QC report."""
import re

import pytest

pytest.importorskip("bimforge.cad")
ezdxf = pytest.importorskip("ezdxf")

from bimforge.sheets.control import draw_control_sheet, qc_report
from bimforge.sheets.model import ControlPoint, SheetMeta

PTS = [
    ControlPoint("CP1", "SURVEY CONTROL - MAG NAIL", 2121427.76, 6441889.26, 153.04),
    ControlPoint("BM1", "BENCHMARK - X SCRIBED ON CURB", 2121500.00, 6441900.00, 150.10),
]
META = SheetMeta(project="Job X", sheet_title="GEOMETRIC CONTROL", grade="survey",
                 crs_epsg=2227, basis_note="CA SP Zone 3 NAD83, ftUS", date="2026-08-02")


def test_draw_control_sheet(tmp_path):
    out = draw_control_sheet(PTS, META, tmp_path / "control.dxf")
    doc = ezdxf.readfile(out)
    msp = doc.modelspace()
    layers = {e.dxf.layer for e in msp}
    assert "V-CTRL-PNTS" in layers and "C-ANNO-TEXT" in layers
    # one marker per point at (easting, northing)
    circles = [e for e in msp.query("CIRCLE") if e.dxf.layer == "V-CTRL-PNTS"]
    assert len(circles) == 2
    assert circles[0].dxf.center[0] == pytest.approx(6441889.26)
    assert "GEOMETRIC CONTROL" in {lay.name for lay in doc.layouts}
    assert "C-ANNO-TEXT" in {layer.dxf.name for layer in doc.layers}


def test_control_table_shows_dash_for_missing_elevation(tmp_path):
    pts = [ControlPoint("CP1", "SURVEY CONTROL", 1000.0, 5000.0, elevation_ft=None)]
    out = draw_control_sheet(pts, META, tmp_path / "control.dxf")
    doc = ezdxf.readfile(out)
    texts = " ".join(e.text for e in doc.modelspace().query("MTEXT"))
    # elevation column renders "-" (not "0.00") when elevation_ft is None
    assert re.search(r"CP1\s+[\d.]+\s+[\d.]+\s+-\s+SURVEY CONTROL", texts)


def test_approximate_grade_stamps_caveat(tmp_path):
    meta = SheetMeta(project="J", sheet_title="CONTROL", grade="approximate")
    out = draw_control_sheet(PTS, meta, tmp_path / "c.dxf")
    doc = ezdxf.readfile(out)
    texts = " ".join(e.text for e in doc.modelspace().query("MTEXT"))
    assert "NOT FOR CONSTRUCTION LAYOUT" in texts


def test_qc_report_contents(tmp_path):
    text = qc_report(PTS, META)
    assert "GEOMETRIC CONTROL" in text and "CP1" in text
    assert "EPSG:2227" in text and "survey" in text


def test_control_kml():
    pytest.importorskip("pyproj")
    from bimforge.sheets.control import control_kml
    kml = control_kml(PTS, META)
    assert kml is not None and "<kml" in kml and "CP1" in kml and "BM1" in kml
    m = re.search(r"<coordinates>(-?[\d.]+),(-?[\d.]+)", kml)
    lon, lat = float(m.group(1)), float(m.group(2))
    assert -125 < lon < -114 and 32 < lat < 42  # CA; also proves lon,lat order
    no_crs = SheetMeta(project="J", sheet_title="X", grade="survey")
    assert control_kml(PTS, no_crs) is None


def test_control_kml_applies_combined_factor():
    pytest.importorskip("pyproj")
    from bimforge.cad.geo import StatePlane
    from bimforge.sheets.control import control_kml
    cf = 1.000254948
    meta = SheetMeta(project="Job X", sheet_title="CTRL", grade="survey",
                     crs_epsg=2227, combined_factor=cf)
    p = PTS[0]
    kml = control_kml([p], meta)
    m = re.search(r"<coordinates>(-?[\d.]+),(-?[\d.]+)", kml)
    lon, lat = float(m.group(1)), float(m.group(2))
    sp = StatePlane(2227)
    exp_lon, exp_lat = sp.to_lonlat_ne(p.northing_ft / cf, p.easting_ft / cf)
    raw_lon, raw_lat = sp.to_lonlat_ne(p.northing_ft, p.easting_ft)
    assert lat == pytest.approx(exp_lat, abs=1e-6)
    assert lon == pytest.approx(exp_lon, abs=1e-6)
    # ground-as-grid is the documented thousands-of-feet error class
    assert abs(lat - raw_lat) > 1e-4


def test_annotation_scales_with_plot_scale(tmp_path):
    # R1 item 4: fixed world-foot annotation (3.0 ft text) plots ~0.0025 in
    # at 1"=1200' — blank sheet. Paper-relative: 0.10 in text at ANY scale.
    heights = {}
    for name, sc in (("s30", 1 / 30), ("s1200", 1 / 1200)):
        out = draw_control_sheet(PTS, META, tmp_path / f"{name}.dxf", scale=sc)
        doc = ezdxf.readfile(out)
        hs = {round(e.dxf.char_height, 6)
              for e in doc.modelspace().query("MTEXT")}
        assert len(hs) == 1
        heights[name] = hs.pop()
    assert heights["s30"] == pytest.approx(3.0)      # legacy size at 1"=30'
    assert heights["s1200"] == pytest.approx(120.0)  # 40x larger world size


def test_autofit_annotation_matches_resolved_scale(tmp_path):
    from bimforge.cad.sheet import SHEET_WINDOWS
    from bimforge.cad.viewport import bbox, resolve_scale
    out = draw_control_sheet(PTS, META, tmp_path / "fit.dxf")  # scale=None
    doc = ezdxf.readfile(out)
    h = {round(e.dxf.char_height, 6)
         for e in doc.modelspace().query("MTEXT")}.pop()
    xy = [(p.easting_ft, p.northing_ft) for p in PTS]
    eff = resolve_scale(bbox(xy, margin=50.0), None,
                        size=SHEET_WINDOWS["ARCH_D"]["size"])
    assert h == pytest.approx(0.10 / eff, rel=1e-6)
