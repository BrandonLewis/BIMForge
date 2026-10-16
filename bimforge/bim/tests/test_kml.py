"""IFC -> KML: sample DXF (ft, EPSG:2227) -> dxf2bim -> kml -> parse the output.

The test site sits near E 6.44e6 / N 2.12e6 ftUS (CA State Plane zone 3),
which reprojects to roughly lon -120.92, lat 37.82 — the assertions bound the
coordinates to that neighbourhood, so a georef regression (wrong Scale, wrong
base units) throws the model far outside the window and fails loudly.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

ezdxf = pytest.importorskip("ezdxf")
pytest.importorskip("shapely")
ifcopenshell = pytest.importorskip("ifcopenshell")
pytest.importorskip("pyproj")

from bimforge.bim.dxf2bim import UNIT_TO_M, build_ifc, extract_features  # noqa: E402
from bimforge.bim.kml import ifc_to_kml  # noqa: E402

BASE_E, BASE_N = 6_440_000.0, 2_120_000.0
FT = UNIT_TO_M["ft"]
KML_NS = {"k": "http://www.opengis.net/kml/2.2"}

LAYERS = {
    "S-DECK": {
        "ifc_class": "IfcSlab",
        "predefined_type": "FLOOR",
        "feature": "area",
        "height": 0.5,
        "classification": {"system": "Caltrans", "code": "51-01",
                           "name": "Structural Concrete Bridge"},
    },
    "S-PILE": {
        "ifc_class": "IfcPile",
        "feature": "count",
        "height": 10.0,
        "marker_size": 0.5,
        "classification": {"system": "Caltrans", "code": "49-01",
                           "name": "Piling"},
    },
}


def _write_dxf(path) -> str:
    """A 40ft x 30ft deck slab and two pile markers near the survey base."""
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


def _config(base_e, base_n, base_h=0.0) -> dict:
    return {
        "project": {"name": "KML test"},
        "units": {"dxf_length_unit": "ft"},
        "georeference": {"crs_epsg": 2227, "base_easting": base_e,
                         "base_northing": base_n, "base_height": base_h},
        "layers": LAYERS,
    }


def _build_ifc(tmp_path, base_e=BASE_E, base_n=BASE_N, base_h=0.0,
               name="site") -> str:
    dxf = _write_dxf(tmp_path / f"{name}.dxf")
    cfg = _config(base_e, base_n, base_h)
    features = extract_features(dxf, cfg["layers"], FT)
    ifc = str(tmp_path / f"{name}.ifc")
    build_ifc(features, cfg, ifc)
    return ifc


def test_kml_coordinates_land_on_the_epsg2227_site(tmp_path):
    ifc = _build_ifc(tmp_path)
    info = ifc_to_kml(ifc, tmp_path / "site.kml")
    assert info["elements"] == 3 and info["groups"] == 2

    root = ET.fromstring((tmp_path / "site.kml").read_text(encoding="utf-8"))
    folders = root.findall(".//k:Folder", KML_NS)
    placemarks = root.findall(".//k:Placemark", KML_NS)
    assert len(folders) == 2
    assert len(placemarks) == 3
    names = {f.find("k:name", KML_NS).text for f in folders}
    assert names == {"51-01 — Structural Concrete Bridge", "49-01 — Piling"}

    coords = []
    for node in root.findall(".//k:coordinates", KML_NS):
        for triple in node.text.split():
            lon, lat, alt = (float(v) for v in triple.split(","))
            coords.append((lon, lat, alt))
    assert coords
    for lon, lat, _alt in coords:
        assert -121.0 < lon < -120.8
        assert 37.7 < lat < 37.9


def test_kml_absolute_altitude_and_style(tmp_path):
    ifc = _build_ifc(tmp_path)
    ifc_to_kml(ifc, tmp_path / "site.kml")
    text = (tmp_path / "site.kml").read_text(encoding="utf-8")
    assert "<altitudeMode>absolute</altitudeMode>" in text
    assert "ff9bb5d1" in text  # IfcSlab class colour
    assert "ff4a6a8a" in text  # IfcPile class colour


def test_kml_rejects_legacy_broken_georef(tmp_path):
    # base 0/0 leaves the survey coordinates (~1.96e6 m) in model space — the
    # same signature as an IFC written by the <= 0.1.10 broken georef.
    ifc = _build_ifc(tmp_path, base_e=0.0, base_n=0.0)
    with pytest.raises(ValueError, match=r"regenerate the IFC with est-bim"):
        ifc_to_kml(ifc, tmp_path / "site.kml")


def test_kml_rejects_non_georeferenced_ifc(tmp_path):
    dxf = _write_dxf(tmp_path / "site.dxf")
    cfg = _config(BASE_E, BASE_N)
    cfg["georeference"] = {}
    features = extract_features(dxf, cfg["layers"], FT)
    ifc = str(tmp_path / "site.ifc")
    build_ifc(features, cfg, ifc)
    with pytest.raises(ValueError, match=r"IfcMapConversion"):
        ifc_to_kml(ifc)


def test_cli_kml_subcommand(tmp_path, capsys):
    from bimforge.bim import cli

    ifc = _build_ifc(tmp_path)
    out = tmp_path / "site.kml"
    assert cli.main(["kml", ifc, "--out", str(out)]) == 0
    assert out.is_file()
    assert "3 elements, 2 groups" in capsys.readouterr().out


def _coords(path):
    """Every (lon, lat, alt) triple in the KML, in document order."""
    root = ET.fromstring(path.read_text(encoding="utf-8"))
    out = []
    for node in root.findall(".//k:coordinates", KML_NS):
        for triple in node.text.split():
            lon, lat, alt = (float(v) for v in triple.split(","))
            out.append((lon, lat, alt))
    return out


def test_kml_vshift_shifts_every_altitude_and_nothing_else(tmp_path):
    # Opt-in NAVD88 -> EGM96 correction (terrain.datum.geoid_shift_m): every
    # emitted altitude moves by exactly vshift_m; horizontal stays put.
    ifc = _build_ifc(tmp_path)
    ifc_to_kml(ifc, tmp_path / "plain.kml")
    ifc_to_kml(ifc, tmp_path / "shifted.kml", vshift_m=-0.9)
    plain = _coords(tmp_path / "plain.kml")
    shifted = _coords(tmp_path / "shifted.kml")
    assert plain and len(plain) == len(shifted)
    for (lon0, lat0, a0), (lon1, lat1, a1) in zip(plain, shifted):
        assert lon1 == lon0 and lat1 == lat0
        assert a1 == pytest.approx(a0 - 0.9, abs=1e-9)


def test_kml_without_vshift_is_byte_identical_to_default(tmp_path):
    # The parameter is strictly opt-in: not passing it and passing None must
    # both leave the output exactly as it was before the parameter existed.
    ifc = _build_ifc(tmp_path)
    ifc_to_kml(ifc, tmp_path / "a.kml")
    ifc_to_kml(ifc, tmp_path / "b.kml", vshift_m=None)
    assert (tmp_path / "a.kml").read_bytes() == (tmp_path / "b.kml").read_bytes()


def test_group_label_carries_every_classification_code(tmp_path):
    # issue #106, display surface: _group_of used to keep only the LAST code;
    # a two-code element now shows both so the folder label agrees with the
    # takeoff rows it feeds.
    import ifcopenshell
    import ifcopenshell.api.classification
    import ifcopenshell.api.root

    from bimforge.bim.kml import _group_of

    f = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="p")
    pile = ifcopenshell.api.root.create_entity(f, ifc_class="IfcPile",
                                               name="P-1")
    system = ifcopenshell.api.classification.add_classification(
        f, classification="BidSchedule")
    for code in ("PILE-200W-FRN", "PILE-200W-DRV"):
        ifcopenshell.api.classification.add_reference(
            f, products=[pile], identification=code, name=code,
            classification=system)
    label = _group_of(pile)
    assert "PILE-200W-FRN" in label and "PILE-200W-DRV" in label

    # grouping must be stable: a second element with the SAME code set in the
    # OPPOSITE association order lands in the same folder, and the same code
    # under a different reference name still appears only once
    pile2 = ifcopenshell.api.root.create_entity(f, ifc_class="IfcPile",
                                                name="P-2")
    for code in ("PILE-200W-DRV", "PILE-200W-FRN"):     # reversed
        ifcopenshell.api.classification.add_reference(
            f, products=[pile2], identification=code, name=code,
            classification=system)
    ifcopenshell.api.classification.add_reference(       # same code, new name
        f, products=[pile2], identification="PILE-200W-FRN",
        name="Furnish 200W pile", classification=system)
    assert _group_of(pile2) == label
    assert _group_of(pile2).count(" + ") == 1        # exactly two entries
    assert "Furnish 200W pile" not in _group_of(pile2)   # dup code: first name wins


# ---------------------------------------------------------------------------
# Vertical georeference (issue #134): the house convention keeps geometry near
# the model origin and carries the site datum in IfcMapConversion's
# OrthogonalHeight. ifc_to_kml used to emit model-space Z straight out as KML
# absolute altitude, so on the high-elevation bridge (DATUM ELEVATION = 2440.00) the bridge landed
# at -37.8..28.9 ft instead of 2402..2469 ft NAVD88 — 2440 ft underground in
# Google Earth. Authoring absolute elevations into model Z instead is not an
# option: that puts geometry 742 m from the origin, where Bonsai's default
# view never frames it and the model reads as empty.
# ---------------------------------------------------------------------------

DATUM_FT = 2440.0


def test_kml_altitude_includes_the_map_conversion_orthogonal_height(tmp_path):
    flat = _build_ifc(tmp_path, name="flat")
    raised = _build_ifc(tmp_path, base_h=DATUM_FT, name="raised")
    ifc_to_kml(flat, tmp_path / "flat.kml")
    ifc_to_kml(raised, tmp_path / "raised.kml")
    a = _coords(tmp_path / "flat.kml")
    b = _coords(tmp_path / "raised.kml")
    assert a and len(a) == len(b)
    datum_m = DATUM_FT * FT
    assert datum_m == pytest.approx(743.71, abs=0.01)   # the high-elevation-bridge figure
    for (lon0, lat0, alt0), (lon1, lat1, alt1) in zip(a, b):
        assert (lon1, lat1) == (lon0, lat0)             # horizontal untouched
        # tolerance is the KML's own altitude precision (2 dp), not ours
        assert alt1 == pytest.approx(alt0 + datum_m, abs=0.01)


def test_kml_reports_the_shift_it_applied(tmp_path):
    """Nothing silent: the caller gets back the altitude shift actually
    applied, so the CLI can print it and a wrong datum is visible."""
    ifc = _build_ifc(tmp_path, base_h=DATUM_FT)
    info = ifc_to_kml(ifc, tmp_path / "site.kml")
    assert info["vshift_m"] == pytest.approx(DATUM_FT * FT, abs=1e-6)


def test_kml_geoid_shift_adds_to_the_datum_height(tmp_path):
    """`vshift_m` stays what it always was — the NAVD88 -> EGM96 geoid
    correction — and now composes with the datum height rather than replacing
    it. They answer different questions and both apply."""
    ifc = _build_ifc(tmp_path, base_h=DATUM_FT)
    ifc_to_kml(ifc, tmp_path / "datum.kml")
    ifc_to_kml(ifc, tmp_path / "both.kml", vshift_m=-0.9)
    datum = _coords(tmp_path / "datum.kml")
    both = _coords(tmp_path / "both.kml")
    for (_lon, _lat, a0), (_lon1, _lat1, a1) in zip(datum, both):
        assert a1 == pytest.approx(a0 - 0.9, abs=1e-9)


def test_cli_kml_exposes_geoid_shift_and_prints_the_applied_shift(
        tmp_path, capsys):
    """A correct KML was not producible from the command line at all: the CLI
    passed neither the datum height nor any geoid separation."""
    from bimforge.bim import cli
    ifc = _build_ifc(tmp_path, base_h=DATUM_FT)
    out = tmp_path / "site.kml"
    assert cli.main(["kml", ifc, "--out", str(out),
                     "--geoid-shift-m", "-0.9"]) == 0
    printed = capsys.readouterr().out
    total = DATUM_FT * FT - 0.9
    assert f"{total:.3f}" in printed
    alts = [alt for _lon, _lat, alt in _coords(out)]
    assert min(alts) > 700.0        # metres above the EGM96 geoid, not ~0
