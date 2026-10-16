"""IFC -> KMZ: sample DXF (ft, EPSG:2227) -> dxf2bim -> kmz -> unzip + parse.

The default KMZ is the Google Earth web polygon KML (#306); the COLLADA
``<Model>`` route is ``collada=True``.

Same site as test_kml.py: E 6.44e6 / N 2.12e6 ftUS (CA State Plane zone 3)
reprojects to roughly lon -120.92, lat 37.82 — the Model anchor must land in
that window, or the georef/anchor math regressed.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile

import pytest

ezdxf = pytest.importorskip("ezdxf")
pytest.importorskip("shapely")
ifcopenshell = pytest.importorskip("ifcopenshell")
pytest.importorskip("pyproj")

from bimforge.bim.dxf2bim import UNIT_TO_M, build_ifc, extract_features  # noqa: E402
from bimforge.bim.kmz import ifc_to_kmz  # noqa: E402

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
        "project": {"name": "KMZ test"},
        "units": {"dxf_length_unit": "ft"},
        "georeference": {"crs_epsg": 2227, "base_easting": base_e,
                         "base_northing": base_n, "base_height": base_h},
        "layers": LAYERS,
    }


def _build_ifc(tmp_path, base_e=BASE_E, base_n=BASE_N, base_h=0.0) -> str:
    dxf = _write_dxf(tmp_path / "site.dxf")
    cfg = _config(base_e, base_n, base_h)
    features = extract_features(dxf, cfg["layers"], FT)
    ifc = str(tmp_path / "site.ifc")
    build_ifc(features, cfg, ifc)
    return ifc


def test_kmz_round_trip_places_the_model_on_the_epsg2227_site(tmp_path):
    ifc = _build_ifc(tmp_path)
    out = ifc_to_kmz(ifc, tmp_path / "site.kmz", collada=True)
    assert out == tmp_path / "site.kmz"

    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        assert names == {"doc.kml", "files/model.dae"}
        # non-trivial COLLADA payload (3 meshed elements, > 1 KB)
        assert zf.getinfo("files/model.dae").file_size > 1024
        dae = zf.read("files/model.dae").decode("utf-8")
        doc = zf.read("doc.kml").decode("utf-8")

    # The serializer bakes placements: identity node matrices, world verts.
    assert "<COLLADA" in dae
    assert 'meter="1"' in dae

    root = ET.fromstring(doc)
    model = root.find(".//k:Placemark/k:Model", KML_NS)
    assert model is not None
    assert model.find("k:altitudeMode", KML_NS).text == "absolute"
    assert model.find("k:Link/k:href", KML_NS).text == "files/model.dae"
    assert model.find("k:Orientation/k:heading", KML_NS).text == "0"
    assert model.find("k:Scale/k:x", KML_NS).text == "1"

    lon = float(model.find("k:Location/k:longitude", KML_NS).text)
    lat = float(model.find("k:Location/k:latitude", KML_NS).text)
    alt = float(model.find("k:Location/k:altitude", KML_NS).text)
    assert -121.0 < lon < -120.8
    assert 37.7 < lat < 37.9
    assert alt == pytest.approx(0.0)

    # the site Point placemark sits at the same anchor, named for the project
    point = root.find(".//k:Placemark/k:Point", KML_NS)
    assert point is not None
    plon, plat, _ = (float(v) for v in
                     point.find("k:coordinates", KML_NS).text.split(","))
    assert plon == pytest.approx(lon) and plat == pytest.approx(lat)
    assert root.find(".//k:Document/k:name", KML_NS).text == "site"


def test_kmz_altitude_converts_orthogonal_height_to_metres(tmp_path):
    # OrthogonalHeight is in CRS units (ftUS for EPSG:2227); KML <altitude> is
    # always metres. A raised datum must be written CONVERTED, not verbatim --
    # writing 2440 (ftUS) as 2440 (m) floats the model ~1700 m too high (#174).
    DATUM_FT = 2440.0
    ifc = _build_ifc(tmp_path, base_h=DATUM_FT)
    out = ifc_to_kmz(ifc, tmp_path / "raised.kmz", collada=True)
    with zipfile.ZipFile(out) as zf:
        doc = zf.read("doc.kml").decode("utf-8")

    root = ET.fromstring(doc)
    datum_m = DATUM_FT * FT
    assert datum_m == pytest.approx(743.71, abs=0.01)          # the high-elevation-bridge figure
    # the Model <Location> anchor altitude is in metres, not the raw 2440 ftUS
    model = root.find(".//k:Placemark/k:Model", KML_NS)
    alt = float(model.find("k:Location/k:altitude", KML_NS).text)
    assert alt == pytest.approx(datum_m, abs=0.01)
    # the site Point placemark carries the same converted altitude
    point = root.find(".//k:Placemark/k:Point", KML_NS)
    palt = float(point.find("k:coordinates", KML_NS).text.split(",")[2])
    assert palt == pytest.approx(datum_m, abs=0.01)


def test_gltf_mode_writes_only_a_glb(tmp_path):
    ifc = _build_ifc(tmp_path)
    out = ifc_to_kmz(ifc, tmp_path / "site.glb", gltf=True)
    assert out == tmp_path / "site.glb"
    assert out.read_bytes()[:4] == b"glTF"
    assert not (tmp_path / "site.kmz").exists()  # gltf mode: no KMZ


def test_default_output_suffix_follows_mode(tmp_path):
    ifc = _build_ifc(tmp_path)
    assert ifc_to_kmz(ifc) == tmp_path / "site.kmz"
    assert ifc_to_kmz(ifc, gltf=True) == tmp_path / "site.glb"


def test_kmz_rejects_non_georeferenced_ifc(tmp_path):
    dxf = _write_dxf(tmp_path / "site.dxf")
    cfg = _config(BASE_E, BASE_N)
    cfg["georeference"] = {}
    features = extract_features(dxf, cfg["layers"], FT)
    ifc = str(tmp_path / "site.ifc")
    build_ifc(features, cfg, ifc)
    with pytest.raises(ValueError, match=r"IfcMapConversion"):
        ifc_to_kmz(ifc)


def test_kmz_rejects_legacy_broken_georef(tmp_path):
    # base 0/0 leaves the survey coordinates (~1.96e6 m) in model space — the
    # same signature as an IFC written by the <= 0.1.10 broken georef.
    ifc = _build_ifc(tmp_path, base_e=0.0, base_n=0.0)
    with pytest.raises(ValueError, match=r"regenerate the IFC with est-bim"):
        ifc_to_kmz(ifc, tmp_path / "site.kmz")


@pytest.mark.parametrize("gltf", [False, True])
def test_kmz_rejects_ifc_with_no_serializable_products(tmp_path, gltf):
    # A georeferenced IFC whose products all lack geometry would serialize to
    # a valid-but-empty .dae/.glb; ifc_to_kmz must refuse rather than emit an
    # unusable file — and must leave nothing at out_path.
    doc = ezdxf.new("R2010")
    for name in LAYERS:
        doc.layers.add(name)  # layers exist, but no entities on them
    dxf = tmp_path / "empty.dxf"
    doc.saveas(str(dxf))
    cfg = _config(BASE_E, BASE_N)
    features = extract_features(str(dxf), cfg["layers"], FT)
    ifc = str(tmp_path / "empty.ifc")
    build_ifc(features, cfg, ifc)

    out = tmp_path / ("empty.glb" if gltf else "empty.kmz")
    with pytest.raises(ValueError, match=r"no products with usable geometry"):
        ifc_to_kmz(ifc, out, gltf=gltf)
    assert not out.exists()


def test_gltf_mode_leaves_no_stale_glb_on_failure(tmp_path):
    # Same legacy-georef fixture, but in gltf mode: the .glb must be staged
    # in a tempdir and moved to out_path only on success, so a mid-write
    # failure (the legacy-coords ValueError, raised partway through
    # serializing products) must not leave a stale file at out_path.
    ifc = _build_ifc(tmp_path, base_e=0.0, base_n=0.0)
    out = tmp_path / "site.glb"
    with pytest.raises(ValueError, match=r"regenerate the IFC with est-bim"):
        ifc_to_kmz(ifc, out, gltf=True)
    assert not out.exists()


def test_cli_kmz_subcommand(tmp_path, capsys):
    from bimforge.bim import cli

    ifc = _build_ifc(tmp_path)
    out = tmp_path / "site.kmz"
    assert cli.main(["kmz", ifc, "--out", str(out)]) == 0
    assert out.is_file()
    assert f"wrote {out}" in capsys.readouterr().out

    glb = tmp_path / "site.glb"
    assert cli.main(["kmz", ifc, "--out", str(glb), "--gltf"]) == 0
    assert glb.read_bytes()[:4] == b"glTF"
    assert "no KMZ written" in capsys.readouterr().out


def test_cli_kmz_corrupt_ifc_is_a_clean_one_liner(tmp_path, capsys):
    from bimforge.bim import cli

    garbage = tmp_path / "garbage.ifc"
    garbage.write_text("this is not a valid ifc file\n", encoding="utf-8")
    out = tmp_path / "site.kmz"
    rc = cli.main(["kmz", str(garbage), "--out", str(out)])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "Traceback" not in err
    assert not out.exists()


def test_dae_bakes_placement_into_vertices_with_identity_node_matrices(tmp_path):
    """The geometry contract this module rests on, pinned.

    kmz.py serializes with DEFAULT (local-coords) settings and relies on the
    native serializer baking each product's placement into the vertex data, so
    the .dae is world model-space metres about the model origin and the KML
    `<Model>` anchor can simply be the georeference base. If a future
    ifcopenshell instead emitted local vertices plus per-node transforms, every
    other assertion here would still pass — the KML anchor, the units, the file
    size — and the model would sit wrong INSIDE Google Earth.

    The numbers are what make this a real check. The fixture's deck occupies
    x = [30.480, 42.672] m: a 12.192 m (40 ft) object translated +30.480 m
    (100 ft). Local-coordinate output would therefore span [0, 12.192] — so a
    bare "some coordinate exceeds a metre" threshold passes on exactly the
    broken output it is meant to catch. What cannot happen without the
    placement is a MINIMUM x of 30.480: local geometry starts at zero.

    Reads the POSITION sources by semantic rather than every `<float_array>`,
    because normals and texcoords are also float arrays and a max over all of
    them says nothing about where the model sits.
    """
    import re
    import zipfile

    out = ifc_to_kmz(_build_ifc(tmp_path), collada=True)
    with zipfile.ZipFile(out) as zf:
        dae = zf.read("files/model.dae").decode("utf-8")

    identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    matrices = re.findall(r"<matrix[^>]*>([^<]+)</matrix>", dae)
    assert matrices, "no <matrix> nodes in the .dae"
    for m in matrices:
        assert [round(v, 6) for v in map(float, m.split())] == identity, (
            "a node carries a non-identity transform, so placement is NOT baked "
            "into the vertices and the KML anchor is no longer sufficient")

    position_ids = re.findall(r'<input semantic="POSITION" source="#([^"]+)"', dae)
    assert position_ids, "no POSITION inputs in the .dae"
    xs = []
    for pid in position_ids:
        src = re.search(
            rf'<source id="{re.escape(pid)}".*?<float_array[^>]*>([^<]+)</float_array>',
            dae, re.DOTALL)
        assert src, f"POSITION source {pid} has no float_array"
        xs += [float(v) for v in src.group(1).split()][0::3]

    assert min(xs) == pytest.approx(30.480, abs=0.01), (
        f"minimum vertex x is {min(xs):.3f}, not the fixture's +30.480 m "
        "placement offset — the serializer emitted LOCAL coordinates and the "
        "placement was dropped")
    assert max(xs) == pytest.approx(42.672, abs=0.01), (
        f"maximum vertex x is {max(xs):.3f}, not the fixture's 42.672 m extent")


# --- the default Google Earth web KMZ (#306) -------------------------------

WEB_TAGS = {"kml", "Document", "name", "Style", "LineStyle", "PolyStyle",
            "color", "width", "fill", "outline", "Folder", "Placemark",
            "styleUrl", "MultiGeometry", "Polygon", "altitudeMode",
            "outerBoundaryIs", "LinearRing", "coordinates"}


def _web_doc(out) -> str:
    with zipfile.ZipFile(out) as zf:
        assert zf.namelist() == ["doc.kml"]
        return zf.read("doc.kml").decode("utf-8")


def test_default_kmz_is_earth_web_polygon_kml(tmp_path):
    out = ifc_to_kmz(_build_ifc(tmp_path), tmp_path / "site.kmz")
    doc = _web_doc(out)
    assert "<Model" not in doc
    root = ET.fromstring(doc)
    tags = {el.tag.split("}")[1] for el in root.iter()}
    assert tags <= WEB_TAGS, f"unsupported in Earth web: {tags - WEB_TAGS}"
    assert len(root.findall(".//k:Placemark", KML_NS)) == 3
    # 9 lon/lat decimals, 4 altitude decimals
    c = root.find(".//k:coordinates", KML_NS).text.split()[0].split(",")
    assert len(c[0].split(".")[1]) == 9 and len(c[2].split(".")[1]) == 4
    lon, lat = float(c[0]), float(c[1])
    assert -121.0 < lon < -120.8 and 37.7 < lat < 37.9


def test_web_kmz_applies_datum_and_geoid_shift(tmp_path):
    from bimforge.bim.kmz import ifc_to_web_kmz
    ifc = _build_ifc(tmp_path, base_h=100.0)
    a = ifc_to_web_kmz(ifc, tmp_path / "a.kmz")
    b = ifc_to_web_kmz(ifc, tmp_path / "b.kmz", vshift_m=-0.264)
    assert a["vshift_m"] == pytest.approx(100.0 * FT)
    assert b["vshift_m"] - a["vshift_m"] == pytest.approx(-0.264)

    def zmin(out):
        root = ET.fromstring(_web_doc(out))
        return min(float(p.split(",")[2])
                   for c in root.iterfind(".//k:coordinates", KML_NS)
                   for p in c.text.split())
    assert zmin(b["out"]) - zmin(a["out"]) == pytest.approx(-0.264, abs=1e-4)


def test_web_kmz_omit_leaves_elements_and_empty_folders_out(tmp_path):
    from bimforge.bim.kmz import ifc_to_web_kmz
    ifc = _build_ifc(tmp_path)
    import ifcopenshell as ios
    names = [p.Name for p in ios.open(ifc).by_type("IfcPile")]
    info = ifc_to_web_kmz(ifc, tmp_path / "o.kmz", omit="|".join(names))
    assert sorted(info["omitted"]) == sorted(names)
    root = ET.fromstring(_web_doc(info["out"]))
    assert len(root.findall(".//k:Placemark", KML_NS)) == 1
    folders = [f.find("k:name", KML_NS).text for f in root.iterfind(".//k:Folder", KML_NS)]
    assert len(folders) == 1 and "51-01" in folders[0]       # the pile folder is gone


def test_web_kmz_drops_degenerate_rings(tmp_path, monkeypatch):
    # A ring whose corners print identically at 9/4 decimals is dropped and
    # counted; the KML builder never sees it.
    import bimforge.bim.kml as kml
    real = kml.ifc_to_kml

    def spy(*a, **kw):
        assert kw["drop_degenerate"] is True and kw["precision"] == (9, 4)
        return real(*a, **kw)
    monkeypatch.setattr(kml, "ifc_to_kml", spy)
    from bimforge.bim.kmz import ifc_to_web_kmz
    info = ifc_to_web_kmz(_build_ifc(tmp_path), tmp_path / "d.kmz")
    assert info["degenerate_dropped"] == 0
    # unit-level: the same filter on a collapsed triangle
    from bimforge.cad.kml import _fmt_coord
    tri = [(-120.9, 37.8, 1.0), (-120.9 + 1e-11, 37.8, 1.0), (-120.9, 37.8 + 1e-11, 1.0)]
    assert len({_fmt_coord(c, 9, 4) for c in tri}) < 3


def test_web_kmz_enforces_the_earth_web_vertex_limit(tmp_path, monkeypatch):
    import bimforge.bim.kmz as kmz
    monkeypatch.setattr(kmz, "GE_WEB_MAX_VERTICES", 10)
    out = tmp_path / "big.kmz"
    with pytest.raises(ValueError, match=r"--massing.*--omit"):
        kmz.ifc_to_web_kmz(_build_ifc(tmp_path), out)
    assert not out.exists()
    info = kmz.ifc_to_web_kmz(_build_ifc(tmp_path), out, check_limits=False)
    assert info["vertices"] > 10 and out.is_file()


def test_kmz_rejects_contradictory_modes(tmp_path):
    ifc = _build_ifc(tmp_path)
    with pytest.raises(ValueError, match="pick one"):
        ifc_to_kmz(ifc, gltf=True, collada=True)
    with pytest.raises(ValueError, match="web"):
        ifc_to_kmz(ifc, collada=True, omit="x")


def test_cli_kmz_default_is_web_and_collada_is_opt_in(tmp_path, capsys):
    from bimforge.bim import cli
    ifc = _build_ifc(tmp_path)
    web = tmp_path / "web.kmz"
    assert cli.main(["kmz", ifc, "--out", str(web), "--geoid-shift-m", "-0.25"]) == 0
    o = capsys.readouterr().out
    assert "placemarks" in o and "geoid -0.250 m" in o
    assert "<Model" not in _web_doc(web)
    dae = tmp_path / "pro.kmz"
    assert cli.main(["kmz", ifc, "--out", str(dae), "--collada"]) == 0
    assert "Earth Pro only" in capsys.readouterr().out
    with zipfile.ZipFile(dae) as zf:
        assert "files/model.dae" in zf.namelist()
        assert "<Model>" in zf.read("doc.kml").decode("utf-8")
