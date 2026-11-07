"""author.landxml: LandXML alignments -> pob/run traverses, gated on closure."""
from __future__ import annotations

import math

import pytest
import yaml

from bimforge.author.alignment import Alignment
from bimforge.author.landxml import LandXMLGateError, convert, read_landxml

NS = "http://www.landxml.org/schema/LandXML-1.2"


def _xml(alignments: str, epsg: int | None = 2227) -> str:
    cs = f'<CoordinateSystem epsgCode="{epsg}"/>' if epsg else ""
    return (f'<?xml version="1.0"?><LandXML xmlns="{NS}" version="1.2">{cs}'
            f"<Alignments>{alignments}</Alignments></LandXML>")


def _line(n0, e0, n1, e1):
    length = math.hypot(n1 - n0, e1 - e0)
    return (f'<Line length="{length}"><Start>{n0} {e0}</Start>'
            f"<End>{n1} {e1}</End></Line>")


#: 100 ft north, a 90-degree right curve of radius 200 (centre 200 ft east of
#: the PC), then 100 ft east. LandXML directions: CCW from grid east.
R = 200.0
CURVE = (f'<Curve rot="cw" radius="{R}" delta="90" length="{math.pi * R / 2}" '
         f'dirStart="90" dirEnd="0"><Start>100 0</Start><Center>100 200</Center>'
         f"<End>300 200</End></Curve>")
TCT = (f'<Alignment name="CL" staStart="1000">'
       f"<CoordGeom>{_line(0, 0, 100, 0)}{CURVE}{_line(300, 200, 300, 300)}"
       "</CoordGeom></Alignment>")
#: two tangents with a 45-degree angle point between them
KINKED = (f'<Alignment name="K" staStart="0"><CoordGeom>'
          f"{_line(0, 0, 100, 0)}{_line(100, 0, 100 + 50 * math.sqrt(2), 50 * math.sqrt(2))}"
          "</CoordGeom></Alignment>")


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_line_curve_line_becomes_a_closing_traverse(tmp_path):
    doc = read_landxml([_write(tmp_path, "a.xml", _xml(TCT))])
    assert doc["epsg"] == 2227
    (al,) = doc["alignments"]
    assert [r["kind"] for r in al["run"]] == ["tangent", "curve", "tangent"]
    assert al["run"][0]["bearing"].startswith("N 0-00-")
    assert al["run"][1]["turn"] == "R"
    assert al["run"][1]["radius"] == R
    assert al["pob"] == {"station": 1000.0, "northing": 0.0, "easting": 0.0}
    assert al["closure_ft"] < 1e-6
    A = Alignment(al["pob"], al["run"], name=al["name"])
    assert A.end_point == (pytest.approx(300.0), pytest.approx(300.0))
    yaml.safe_dump(doc)                      # plain data, serialisable


def test_an_angle_point_splits_the_alignment_into_stationed_pieces(tmp_path):
    recs = convert(_write(tmp_path, "k.xml", _xml(KINKED)))
    assert [r["name"] for r in recs] == ["K [1/2]", "K [2/2]"]
    assert recs[0]["kinks_deg"] == [45.0]
    assert recs[1]["pob"]["station"] == pytest.approx(100.0)


def test_a_repeat_with_identical_geometry_is_kept_once(tmp_path):
    a = _write(tmp_path, "a.xml", _xml(TCT))
    b = _write(tmp_path, "b.xml", _xml(TCT))
    (al,) = read_landxml([a, b])["alignments"]
    assert al["also_in"] == ["b.xml"]


def test_a_repeat_whose_stated_end_misses_is_still_gated(tmp_path):
    # same traverse (so it would dedupe), but this file's end point is 1 ft off
    moved = TCT.replace("<End>300 300</End>", "<End>300 301</End>")
    a = _write(tmp_path, "a.xml", _xml(TCT))
    with pytest.raises(LandXMLGateError, match=r"CL \(b\.xml\)"):
        read_landxml([a, _write(tmp_path, "b.xml", _xml(moved))])


def test_gate_failures_return_nothing(tmp_path):
    longer = TCT.replace(_line(300, 200, 300, 300), _line(300, 200, 300, 310))
    a = _write(tmp_path, "a.xml", _xml(TCT))
    with pytest.raises(LandXMLGateError, match="duplicate names"):
        read_landxml([a, _write(tmp_path, "b.xml", _xml(longer))])
    with pytest.raises(LandXMLGateError, match="EPSG"):
        read_landxml([a, _write(tmp_path, "c.xml", _xml(KINKED, epsg=2226))])
    gap = TCT.replace(_line(300, 200, 300, 300), _line(300, 201, 300, 300))
    with pytest.raises(LandXMLGateError, match="closure/gap"):
        read_landxml([_write(tmp_path, "d.xml", _xml(gap))])


def test_a_line_without_a_length_uses_its_chord(tmp_path):
    # `length` is optional on <Line> in LandXML 1.2
    bare = ('<Alignment name="B" staStart="0"><CoordGeom>'
            "<Line><Start>0 0</Start><End>30 40</End></Line></CoordGeom></Alignment>")
    (rec,) = convert(_write(tmp_path, "b.xml", _xml(bare)))
    assert rec["run"][0]["length"] == pytest.approx(50.0)
    assert rec["closure_ft"] < 1e-6


def test_a_spiral_is_refused(tmp_path):
    spiral = ('<Alignment name="S" staStart="0"><CoordGeom><Spiral length="10">'
              "<Start>0 0</Start><End>10 0</End></Spiral></CoordGeom></Alignment>")
    with pytest.raises(LandXMLGateError, match="spirals"):
        convert(_write(tmp_path, "s.xml", _xml(spiral)))


def test_cli_writes_the_yaml(tmp_path):
    from bimforge.bim.cli import main as cli_main
    out = tmp_path / "out" / "alignments.yaml"
    assert cli_main(["landxml-alignments", str(_write(tmp_path, "a.xml", _xml(TCT))),
                     "-o", str(out)]) == 0
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert doc["alignments"][0]["name"] == "CL"
