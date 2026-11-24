"""bimforge.bim.linear_ref: station / offset written into the IFC."""
from __future__ import annotations

import math
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


class _Line:
    """A straight stationer along +x at height `y`, from x0 to x0 + length
    (metres; stations in metres): what `measure` asks of one. Past an end
    a point clamps there with its offset square to the line, as
    AlignmentStationer.locate_many does."""

    def __init__(self, name, x0, y, length):
        self.name, self.x0, self.y, self.length = name, x0, y, length
        self.unit_scale, self.station_unit, self.foot_m = 1.0, "m", FT

    def locate_many(self, xy):
        import numpy as np
        xy = np.asarray(xy, dtype=float).reshape(-1, 2)
        return (np.clip(xy[:, 0] - self.x0, 0.0, self.length),
                xy[:, 1] - self.y)

    def frame(self, d):
        from types import SimpleNamespace
        d = min(max(float(d), 0.0), self.length)
        return SimpleNamespace(point=(self.x0 + d, self.y, 0.0))

    def station_at(self, d):
        return d

    def format_station(self, s, unit=None):
        return f"{s:.2f}"


def test_an_element_past_a_short_lines_end_goes_to_the_long_line(monkeypatch):
    """A short second line (a path's own stretch) beside a long one: an
    element further along, on the short line's EXTENSION, clamps to its end
    with a near-zero offset - but it is hundreds of metres from it. The
    choice ranks by true plan distance, the overshoot counted."""
    import numpy as np
    from types import SimpleNamespace
    import bimforge.bim.linear_ref as lr
    ml = _Line("ML", 0.0, 0.0, 1000.0)
    own = _Line("ML path 1", 100.0, -9.0, 20.0)      # 9 m right, 100-120 m
    along = np.linspace(400.0, 430.0, 31)
    beyond = np.column_stack([along, np.full_like(along, -9.0), np.zeros_like(along)])
    beside = np.column_stack([np.linspace(105.0, 115.0, 11), np.full(11, -9.0),
                              np.zeros(11)])
    monkeypatch.setattr(lr, "_bodies", lambda f: {1: beyond, 2: beside})
    f = SimpleNamespace(by_id=lambda i: SimpleNamespace(GlobalId=f"g{i}", Name=f"e{i}"))
    out = lr.measure(f, stationers=[ml, own])
    assert out[1]["Alignment"] == "ML"
    assert (out[1]["StationStart"], out[1]["StationEnd"]) == pytest.approx((400.0, 430.0))
    assert out[2]["Alignment"] == "ML path 1"        # on it: still its own


def test_an_element_before_a_short_lines_start_stays_on_the_line_it_is_along(
        monkeypatch):
    """The path beside the road before its own stretch hands over: 55 m
    right of the long line, along the extension of the short line (50 m
    right) that starts where the element ends. Its points are nearer the
    short line's START than the long line on the median, but none lies
    within the short line's stations - a line the element is along wins
    over one it is only past the end of."""
    import numpy as np
    from types import SimpleNamespace
    import bimforge.bim.linear_ref as lr
    ml = _Line("ML", 0.0, 0.0, 1000.0)
    own = _Line("ML path 1", 100.0, -50.0, 120.0)
    x = np.linspace(0.0, 100.0, 101)
    before = np.column_stack([x, np.full_like(x, -55.0), np.zeros_like(x)])
    monkeypatch.setattr(lr, "_bodies", lambda f: {1: before})
    f = SimpleNamespace(by_id=lambda i: SimpleNamespace(GlobalId=f"g{i}", Name=f"e{i}"))
    (v,) = lr.measure(f, stationers=[ml, own]).values()
    assert v["Alignment"] == "ML"
    assert (v["StationStart"], v["StationEnd"]) == pytest.approx((0.0, 100.0))


def test_past_every_line_s_end_the_nearest_end_wins(monkeypatch):
    """Off the stations of both lines: the one whose end is nearest in
    plan, not the one whose end tangent it is least offset from."""
    import numpy as np
    from types import SimpleNamespace
    import bimforge.bim.linear_ref as lr
    a = _Line("A", 0.0, 0.0, 10.0)                  # 2 m off its tangent, 490 m on
    b = _Line("B", 400.0, -30.0, 10.0)              # 28 m off its tangent, 90 m on
    x = np.linspace(500.0, 510.0, 11)
    pts = np.column_stack([x, np.full_like(x, -2.0), np.zeros_like(x)])
    monkeypatch.setattr(lr, "_bodies", lambda f: {1: pts})
    f = SimpleNamespace(by_id=lambda i: SimpleNamespace(GlobalId=f"g{i}", Name=f"e{i}"))
    (v,) = lr.measure(f, stationers=[a, b]).values()
    assert v["Alignment"] == "B"


class _Ray(_Line):
    """A straight stationer from `p0` heading `angle` (radians from +x)."""

    def __init__(self, name, p0, angle, length):
        import numpy as np
        super().__init__(name, 0.0, 0.0, length)
        self.p0 = np.asarray(p0, dtype=float)
        self.t = np.array([np.cos(angle), np.sin(angle)])
        self.n = np.array([-self.t[1], self.t[0]])            # left

    def locate_many(self, xy):
        import numpy as np
        r = np.asarray(xy, dtype=float).reshape(-1, 2) - self.p0
        return np.clip(r @ self.t, 0.0, self.length), r @ self.n

    def frame(self, d):
        from types import SimpleNamespace
        p = self.p0 + min(max(float(d), 0.0), self.length) * self.t
        return SimpleNamespace(point=(p[0], p[1], 0.0))


def _box(x0, x1, y0, y1, n=20):
    import numpy as np
    X, Y = np.meshgrid(np.linspace(x0, x1, n), np.linspace(y0, y1, n))
    return np.column_stack([X.ravel(), Y.ravel(), np.zeros(X.size)])


def _on(monkeypatch, lines, pts):
    from types import SimpleNamespace
    import bimforge.bim.linear_ref as lr
    monkeypatch.setattr(lr, "_bodies", lambda f: {1: pts})
    f = SimpleNamespace(by_id=lambda i: SimpleNamespace(GlobalId=f"g{i}", Name=f"e{i}"))
    (v,) = lr.measure(f, stationers=lines).values()
    return v["Alignment"]


#: a bridge 0 to 60 m along x, and a road crossing under it at x = 30
#: running along y: the bridge's end pieces lie past its end, but the
#: road they lie "along" is 30 m and more away
BRIDGE = (_Ray("BR", (0.0, 0.0), 0.0, 60.0),
          _Ray("SR", (30.0, -500.0), math.pi / 2, 1000.0))


@pytest.mark.parametrize("where", [(61.0, 70.0, -6.0, 6.0),      # approach slab
                                   (59.0, 64.0, 5.0, 6.0)])      # wingwall
def test_an_element_just_past_a_lines_end_stays_on_it(monkeypatch, where):
    """Past the bridge's end by less than its own size, and much nearer
    the bridge than the road it lies along: it stays on the bridge."""
    assert _on(monkeypatch, BRIDGE, _box(*where)) == "BR"


def test_an_element_abeam_an_end_is_not_past_it(monkeypatch):
    # square off the bridge's end, 20 to 30 m out: the bridge is nearer
    # (25 m) than the road (30 m) and the element is not past its end
    pts = _box(60.0, 60.0, 20.0, 30.0)
    assert _on(monkeypatch, BRIDGE, pts) == "BR"


@pytest.mark.parametrize("past", [0.4, 0.6])
@pytest.mark.parametrize("n", [5, 20, 61])
def test_an_element_spanning_an_end_stays_on_its_line_at_any_density(
        monkeypatch, past, n):
    # an abutment 10 m long, 40 % or 60 % of it past the bridge's end
    x0 = 60.0 - 10.0 * (1.0 - past)
    assert _on(monkeypatch, BRIDGE, _box(x0, x0 + 10.0, -6.0, 6.0, n)) == "BR"


def test_a_long_element_past_a_lines_end_is_not_pulled_onto_a_crossing_line(
        monkeypatch):
    """A 100 m wall running on past the bridge's end, square across the
    road: the road is within the cap (its median 80 m against 2 x 50 m),
    but the wall spans 1 m of its stations - it crosses the road, it does
    not lie along it - so it stays on the bridge."""
    assert _on(monkeypatch, BRIDGE, _box(60.0, 160.0, 5.0, 6.0)) == "BR"
