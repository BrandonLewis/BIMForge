"""Tests for bimforge.cad.kml — the pure-stdlib KML builder."""
from __future__ import annotations

import xml.dom.minidom as minidom

import pytest

from bimforge.cad.kml import Coord, Folder, KMLDocument, Style, _coords, _fmt_coord


def test_fmt_coord_2d_appends_zero_altitude():
    assert _fmt_coord((-120.84392, 37.92122)) == "-120.84392000,37.92122000,0"


def test_fmt_coord_3d_formats_altitude():
    assert _fmt_coord((-120.84392, 37.92122, 56.3)) == "-120.84392000,37.92122000,56.30"


def test_coords_joins_with_spaces():
    s = _coords([(0.0, 0.0), (1.0, 1.0)])
    assert s == "0.00000000,0.00000000,0 1.00000000,1.00000000,0"


def test_line_style_xml():
    xml = Style("deck", line_color="ff0000ff", line_width=2).to_xml()
    assert '<Style id="deck">' in xml
    assert "<LineStyle><color>ff0000ff</color><width>2</width></LineStyle>" in xml
    assert "PolyStyle" not in xml


def test_poly_and_icon_style_xml():
    xml = Style(
        "cp", poly_color="5500aaff", poly_fill=False,
        icon_color="ff0000ff", icon_scale=0.8,
        icon_href="http://example/icon.png", label_scale=0.9,
    ).to_xml()
    assert "<PolyStyle>" in xml and "<fill>0</fill>" in xml
    assert "<IconStyle>" in xml and "<scale>0.8</scale>" in xml
    assert "<href>http://example/icon.png</href>" in xml
    assert "<LabelStyle><scale>0.9</scale></LabelStyle>" in xml


def test_folder_point_line_polygon():
    f = Folder("Geo")
    f.point("P", (-120.0, 38.0), style="cp", description="a point")
    f.line("L", [(-120.0, 38.0), (-120.1, 38.1)], style="deck")
    f.polygon("Poly", [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)], style="deck")
    xml = f.to_xml()
    assert xml.count("<Placemark>") == 3
    assert "<Point>" in xml and "<LineString>" in xml and "<Polygon>" in xml
    assert "<styleUrl>#cp</styleUrl>" in xml


def test_polygon_closes_ring():
    f = Folder("g")
    f.polygon("p", [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)])
    # first coord repeated at the end
    coords = f.to_xml().split("<coordinates>")[1].split("</coordinates>")[0]
    pts = coords.split()
    assert pts[0] == pts[-1]


def test_absolute_altitude_mode():
    f = Folder("g")
    f.line("l", [(0.0, 0.0, 100.0), (1.0, 1.0, 90.0)], absolute=True)
    assert "<altitudeMode>absolute</altitudeMode>" in f.to_xml()


def test_escaping_in_names_and_descriptions():
    doc = KMLDocument("A & B <bridge>", "10' < 12' & rising")
    f = doc.folder("Folder & co")
    f.point("pt <1>", (0.0, 0.0), description="x & y")
    out = doc.to_string()
    assert "&amp;" in out and "&lt;" in out
    assert "<bridge>" not in out  # the raw angle bracket was escaped


def test_document_is_well_formed_xml():
    doc = KMLDocument("Milton Rd over Hoods Creek", "From the 100% plans")
    doc.add_style(Style("deck", line_color="ff0000ff", line_width=2,
                        poly_color="553c14dc"))
    f = doc.folder("Deck")
    f.polygon("Deck slab",
              [(-120.844, 37.921), (-120.843, 37.921), (-120.843, 37.922)],
              style="deck", description="126' x 32'")
    f.point("BB", (-120.8442, 37.9210), description="Begin bridge")
    out = doc.to_string()
    # minidom raises on malformed XML -> this asserts well-formedness
    parsed = minidom.parseString(out)
    assert parsed.documentElement.tagName == "kml"
    assert out.startswith('<?xml version="1.0" encoding="UTF-8"?>')


def test_chaining_returns_self():
    f = Folder("g")
    assert f.point("a", (0.0, 0.0)) is f
    assert f.line("b", [(0.0, 0.0), (1.0, 1.0)]) is f
    doc = KMLDocument("d")
    assert doc.add_style(Style("s", line_color="ffffffff")) is doc


# ----------------------------------------------------- timespan + multipolygon
def test_placemark_timespan_begin_only_matches_schedule_format():
    doc = KMLDocument("t")
    doc.folder("F").point("p", (-120.0, 37.0), timespan=("2026-07-10", None))
    text = doc.to_string()
    # exact begin-only form the bim schedule tests pin
    assert "<TimeSpan><begin>2026-07-10</begin></TimeSpan>" in text
    assert "<end>" not in text


def test_placemark_timespan_begin_and_end_and_escaping():
    doc = KMLDocument("t")
    doc.folder("F").point("p", (-120.0, 37.0),
                          timespan=("2026-07-10", "2026-<08>-01"))
    text = doc.to_string()
    assert "<begin>2026-07-10</begin>" in text
    assert "<end>2026-&lt;08&gt;-01</end>" in text


def test_placemark_without_timespan_is_unchanged():
    doc = KMLDocument("t")
    doc.folder("F").line("l", [(-120.0, 37.0), (-120.1, 37.1)])
    assert "<TimeSpan>" not in doc.to_string()


def test_multipolygon_is_one_placemark_many_polygons():
    doc = KMLDocument("t")
    rings = [[(-120.0, 37.0, 10.0), (-120.001, 37.0, 10.0), (-120.0, 37.001, 10.0)],
             [(-120.2, 37.2, 20.0), (-120.201, 37.2, 20.0), (-120.2, 37.201, 20.0)]]
    doc.add_style(Style("s1", line_color="66000000", poly_color="ff9bb5d1"))
    doc.folder("F").multipolygon("elem", rings, style="s1", absolute=True,
                                 timespan=("2026-07-10", None))
    text = doc.to_string()
    assert text.count("<Placemark>") == 1
    assert text.count("<Polygon>") == 2
    assert text.count("<altitudeMode>absolute</altitudeMode>") == 2
    assert "<styleUrl>#s1</styleUrl>" in text
    assert "<TimeSpan><begin>2026-07-10</begin></TimeSpan>" in text
    # each ring was closed: first point repeated at the end of each ring
    assert text.count("-120.00000000,37.00000000,10.00") == 2


def test_multipolygon_empty_rings_yield_empty_multigeometry():
    doc = KMLDocument("t")
    doc.folder("F").multipolygon("ghost", [])
    text = doc.to_string()
    assert "<MultiGeometry></MultiGeometry>" in text
    assert text.count("<Placemark>") == 1
