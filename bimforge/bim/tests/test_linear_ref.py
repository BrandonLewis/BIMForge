"""bimforge.bim.linear_ref: station / offset written into the IFC."""
from __future__ import annotations

import sqlite3

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

from bimforge.author.tests.test_emit_alignment import _emit, _model  # noqa: E402
from bimforge.bim.linear_ref import PSET, REL_NAME, annotate, read  # noqa: E402

FT = 1200.0 / 3937.0


def test_every_element_gets_its_range_and_is_positioned(tmp_path):
    m, al, _prof = _model()
    path, _f = _emit(tmp_path, m)
    rep = annotate(str(path))
    assert rep == {"elements": 1, "alignments": {"ML": 1}}
    f = ifcopenshell.open(str(path))
    (deck,) = f.by_type("IfcSlab")
    ps = read(f)[deck.GlobalId]
    # project unit is the metre; stations are the alignment's
    assert ps["StationStart"] == pytest.approx(1010.0 * FT, abs=1e-3)
    assert ps["StationEnd"] == pytest.approx(1360.0 * FT, abs=1e-3)
    assert (ps["StationStartText"], ps["StationEndText"]) == ("10+10.00", "13+60.00")
    assert ps["StationUnit"] == "ft" and ps["Alignment"] == "ML"
    # +/-6 ft section (the exact sweep draws a hair wide near the reverse
    # curve: IfcOpenShell#9820), + = left
    assert ps["OffsetLeftMax"] == pytest.approx(6.0 * FT, abs=0.25 * FT)
    assert ps["OffsetLeftMin"] == pytest.approx(-6.0 * FT, abs=0.25 * FT)
    (rel,) = f.by_type("IfcRelPositions")
    assert rel.Name == REL_NAME and rel.RelatingPositioningElement.Name == "ML"
    assert list(rel.RelatedProducts) == [deck]


def _ids(path):
    f = ifcopenshell.open(str(path))
    return (read(f), sorted(e.GlobalId for e in f.by_type("IfcPropertySet")
                            if e.Name == PSET),
            sorted(r.GlobalId for r in f.by_type("IfcRelPositions")))


def test_rerunning_replaces_and_a_rebuild_is_byte_stable(tmp_path):
    anchors = {"deck": {"alignment": "ML", "station": 1200.0 * FT,
                        "offset_left": -2.0 * FT}}
    files = []
    for name in ("a.ifc", "b.ifc"):
        m, *_ = _model()
        path, _f = _emit(tmp_path, m, name)
        annotate(str(path), anchors=anchors)
        files.append(path)
    a, b = (p.read_bytes() for p in files)
    assert a.replace(b"a.ifc", b"b.ifc") == b         # a rebuild: same bytes
    once = _ids(files[0])
    annotate(str(files[0]))                   # keeps the anchor it wrote
    assert _ids(files[0]) == once             # same values and GlobalIds
    path = files[0]
    f = ifcopenshell.open(str(path))
    assert len([p for p in f.by_type("IfcPropertySet") if p.Name == PSET]) == 1
    assert len(f.by_type("IfcRelPositions")) == 1
    ps = read(f)[f.by_type("IfcSlab")[0].GlobalId]
    assert (ps["AnchorStationText"], ps["AnchorOffsetText"]) == ("12+00.00", "2.00 Rt")


def test_no_alignment_writes_nothing(tmp_path):
    m, *_ = _model(schema="IFC4")
    path, _f = _emit(tmp_path, m)
    before = path.read_bytes()
    assert annotate(str(path))["elements"] == 0
    assert path.read_bytes() == before


def test_the_cli_writes_and_lists(tmp_path):
    from bimforge.bim.cli import main
    m, *_ = _model()
    path, _f = _emit(tmp_path, m)
    out, csv = tmp_path / "s.ifc", tmp_path / "s.csv"
    assert main(["stations", str(path), "--out", str(out), "--csv", str(csv)]) == 0
    assert read(ifcopenshell.open(str(out)))
    rows = csv.read_text(encoding="utf-8").splitlines()
    assert rows[0].startswith("Name,GlobalId,Alignment,StationStartText")
    assert rows[1].startswith("deck,") and ",ML,10+10.00,13+60.00," in rows[1]


def test_gis_reads_the_stations_from_the_ifc(tmp_path):
    from bimforge.bim.ifc2gis import ifc_to_gpkg
    m, *_ = _model()
    path, _f = _emit(tmp_path, m)
    annotate(str(path), anchors={"deck": {"alignment": "ML", "station": 1200.0 * FT,
                                          "offset_left": 0.0}})
    out = tmp_path / "m.gpkg"
    ifc_to_gpkg([str(path)], str(out))
    con = sqlite3.connect(str(out))
    (table,) = [r[0] for r in con.execute(
        "select table_name from gpkg_geometry_columns "
        "where geometry_type_name = 'MULTIPOLYGON'")]
    row = con.execute(f'select sta_from_txt, sta_to_txt, sta_at_txt, off_at_txt '
                      f'from "{table}" where name = "deck"').fetchone()
    assert row == ("10+10.00", "13+60.00", "12+00.00", "CL")


def _dense_along(st, d0, d1, far):
    """9000 plan points on the line between two distances, with the point at
    `far` (beyond d1) second in the list - where a stride sample skips it."""
    import numpy as np
    ds = np.linspace(d0, d1, 9000)
    pts = np.array([st.point_at(float(x), 0.0) for x in ds])
    pts[1] = st.point_at(far, 0.0)
    return pts


def test_ranges_use_every_vertex(tmp_path, monkeypatch):
    import bimforge.bim.linear_ref as lr
    from bimforge.bim.alignment_station import AlignmentStationer, alignments
    m, *_ = _model()
    path, _f = _emit(tmp_path, m)
    f = ifcopenshell.open(str(path))
    st = AlignmentStationer(f, alignments(f)[0])
    (deck,) = f.by_type("IfcSlab")
    pts = _dense_along(st, 10.0, 50.0, 80.0)
    monkeypatch.setattr(lr, "_bodies", lambda _f: {deck.id(): pts})
    (v,) = lr.measure(f).values()
    assert st.distance_at(v["StationEnd"]) == pytest.approx(80.0, abs=1e-3)


def test_gis_ranges_use_every_vertex(tmp_path):
    from bimforge.bim.alignment_station import AlignmentStationer, alignments
    from bimforge.bim.ifc2gis import _station_range
    m, *_ = _model()
    path, f = _emit(tmp_path, m)
    st = AlignmentStationer(f, alignments(f)[0])
    pts = _dense_along(st, 10.0, 50.0, 80.0)
    r = _station_range(st, pts)
    assert r["sta_to"] == pytest.approx(st.convert(st.station_at(80.0), "ft"), abs=0.01)


def test_a_new_anchor_by_name_replaces_the_carried_one(tmp_path):
    m, *_ = _model()
    path, _f = _emit(tmp_path, m)
    annotate(str(path), anchors={"deck": {"alignment": "ML", "station": 1200.0 * FT,
                                          "offset_left": 0.0}})
    annotate(str(path), anchors={"deck": {"alignment": "ML", "station": 1250.0 * FT,
                                          "offset_left": 3.0 * FT}})
    f = ifcopenshell.open(str(path))
    (deck,) = f.by_type("IfcSlab")
    ps = read(f)[deck.GlobalId]
    assert (ps["AnchorStationText"], ps["AnchorOffsetText"]) == ("12+50.00", "3.00 Lt")
    # a GlobalId entry wins over a name entry for the same element
    annotate(str(path), anchors={
        "deck": {"alignment": "ML", "station": 1100.0 * FT, "offset_left": 0.0},
        deck.GlobalId: {"alignment": "ML", "station": 1300.0 * FT, "offset_left": 0.0}})
    f = ifcopenshell.open(str(path))
    assert read(f)[deck.GlobalId]["AnchorStationText"] == "13+00.00"
