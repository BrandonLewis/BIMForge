"""Control CSV round-trip, alignment interpolation, sheet meta validation."""
import pytest

from bimforge.sheets.model import (
    Alignment, ControlPoint, SheetMeta, load_control_csv, save_control_csv,
    scale_from_engineering,
)

CP = ControlPoint(point_id="CP100", description="SURVEY CONTROL - MAG NAIL",
                  northing_ft=2121427.76, easting_ft=6441889.26,
                  elevation_ft=153.04, station="107+70.53", offset_ft=2.84,
                  side="RT", latitude=37.9, longitude=-121.3)


def test_control_csv_round_trip(tmp_path):
    p = tmp_path / "control-points.csv"
    save_control_csv([CP], p)
    pts = load_control_csv(p)
    assert pts[0] == CP


def test_control_csv_minimal_columns(tmp_path):
    p = tmp_path / "min.csv"
    p.write_text("point_id,description,northing_ft,easting_ft\n"
                 "BM1,BENCHMARK,1000.0,2000.0\n", encoding="utf-8")
    pts = load_control_csv(p)
    assert pts[0].elevation_ft is None and pts[0].station is None


def test_control_csv_requires_core_columns(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("id,n,e\nBM1,1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required columns"):
        load_control_csv(p)


def test_alignment_station_interpolation():
    a = Alignment(name="P-LINE", points=[
        {"station": 10000.0, "northing": 0.0, "easting": 0.0},
        {"station": 10100.0, "northing": 100.0, "easting": 0.0}])
    n, e = a.at_station(10050.0)
    assert (n, e) == (pytest.approx(50.0), pytest.approx(0.0))
    with pytest.raises(ValueError, match="outside the alignment"):
        a.at_station(9000.0)


def test_alignment_ticks():
    a = Alignment(name="P", points=[
        {"station": 10000.0, "northing": 0.0, "easting": 0.0},
        {"station": 10250.0, "northing": 250.0, "easting": 0.0}])
    stations = [t[0] for t in a.ticks(100.0)]
    assert stations == [10000.0, 10100.0, 10200.0]


def test_alignment_ticks_no_float_drift():
    a = Alignment(name="P", points=[
        {"station": 10000.0, "northing": 0.0, "easting": 0.0},
        {"station": 10300.0, "northing": 300.0, "easting": 0.0}])
    stations = [t[0] for t in a.ticks(0.33)]
    # index-multiplied stations are exact: start + i*interval
    assert stations[900] == 10000.0 + 900 * 0.33


def test_alignment_ticks_rejects_nonpositive_interval():
    a = Alignment(name="P", points=[
        {"station": 10000.0, "northing": 0.0, "easting": 0.0},
        {"station": 10100.0, "northing": 100.0, "easting": 0.0}])
    with pytest.raises(ValueError, match="must be positive"):
        a.ticks(0)
    with pytest.raises(ValueError, match="must be positive"):
        a.ticks(-5.0)


def test_sheet_meta_grade_validated():
    with pytest.raises(ValueError, match="invalid grade"):
        SheetMeta(project="Job X", sheet_title="CONTROL", grade="exact")
    m = SheetMeta(project="Job X", sheet_title="CONTROL", grade="approximate")
    assert m.not_for_layout  # approximate => caveat applies


def test_scale_from_engineering():
    assert scale_from_engineering('1"=30\'') == pytest.approx(1 / 30)
    assert scale_from_engineering("1in=20ft") == pytest.approx(1 / 20)
    with pytest.raises(ValueError, match="unrecognized scale"):
        scale_from_engineering("banana")
