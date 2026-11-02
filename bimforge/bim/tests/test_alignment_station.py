"""bimforge.bim.alignment_station: stationing an IfcAlignment.

The truth is bimforge's own Alignment/Profile: the IFC written from them is
stationed back and must land on the same point, bearing and grade.
"""
from __future__ import annotations

import math

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
import ifcopenshell.api  # noqa: E402
import ifcopenshell.api.alignment as api  # noqa: E402

from bimforge.author.sweep import to_model  # noqa: E402
from bimforge.author.tests.test_emit_alignment import _emit, _model  # noqa: E402
from bimforge.bim.alignment_station import (  # noqa: E402
    AlignmentStationer, alignments, format_offset, format_station,
    station_unit)


@pytest.fixture(scope="module")
def emitted(tmp_path_factory):
    m, al, prof = _model()
    _out, f = _emit(tmp_path_factory.mktemp("al"), m)
    return m, al, prof, f


def test_frames_land_on_the_authored_alignment(emitted):
    m, al, prof, f = emitted
    (ifc_al,) = alignments(f)
    st = AlignmentStationer(f, ifc_al)
    k = m.ctx.ft_to_m
    assert st.length == pytest.approx((al.s_end - al.s_start) * k, abs=1e-6)
    for s in [al.s_start, 1050.0, 1123.4, 1250.0, 1301.0, al.s_end]:
        fr = st.frame((s - al.s_start) * k)
        n, e, az = al.point_az(s)
        want = [c * k for c in to_model(m.ctx, n, e, prof.elev(s))]
        # 0.1 mm: the fixture's curve LENGTHS are rounded to 0.001 ft, so the
        # IFC arc (written from length) and bimforge's (from delta) part by µm
        assert fr.point == pytest.approx(want, abs=1e-4)
        # model +y is grid north here, so the azimuth reads straight across
        assert fr.azimuth == pytest.approx(az, abs=1e-4)
        assert fr.grade == pytest.approx(prof.grade(s), abs=1e-6)
        assert math.hypot(*fr.plan_tangent) == pytest.approx(1.0)
        assert fr.plan_tangent[0] * fr.left[0] + fr.plan_tangent[1] * fr.left[1] \
            == pytest.approx(0.0)


def test_stations_read_in_feet_on_a_metric_ifc_over_a_feet_grid(emitted):
    m, al, _prof, f = emitted
    st = AlignmentStationer(f, alignments(f)[0])
    assert station_unit(f) == "ft"            # SI file, ftUS map conversion
    assert st.convert(st.start_station, "ft") == pytest.approx(al.s_start)
    fr = st.frame((1234.56 - al.s_start) * m.ctx.ft_to_m)
    assert st.format_station(fr.station) == "12+34.56"
    assert st.format_station(fr.station, "m") == "0+376.295"
    back = st.frame_at_station(fr.station)
    assert back.distance == pytest.approx(fr.distance)


def test_ends_clamp(emitted):
    *_, f = emitted
    st = AlignmentStationer(f, alignments(f)[0])
    assert st.frame(-5.0).distance == 0.0
    assert st.frame(st.length + 5.0).distance == st.length
    assert st.frame_at_fraction(1.0).point == st.frame(st.length).point
    pts = st.points(10.0)
    assert pts[0] == st.frame(0.0).point and pts[-1] == st.frame(st.length).point


def _feet_file():
    f = ifcopenshell.file(schema="IFC4X3_ADD2")
    ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcProject")
    ft = ifcopenshell.api.run("unit.add_conversion_based_unit", f, name="foot")
    ifcopenshell.api.run("unit.assign_unit", f, units=[ft])
    ifcopenshell.api.run("context.add_context", f, context_type="Model")
    return f


def test_a_feet_project_with_a_curve(tmp_path):
    f = _feet_file()
    ia = api.create(f, "B", include_vertical=False)
    lay = api.get_horizontal_layout(ia)
    seg = dict(StartRadiusOfCurvature=0.0, EndRadiusOfCurvature=0.0)
    api.create_layout_segment(f, lay, f.create_entity(
        "IfcAlignmentHorizontalSegment", StartPoint=f.create_entity(
            "IfcCartesianPoint", Coordinates=(100.0, 0.0)),
        StartDirection=0.0, SegmentLength=200.0, PredefinedType="LINE", **seg))
    # quarter circle, R = 100 ft, turning left (positive radius)
    api.create_layout_segment(f, lay, f.create_entity(
        "IfcAlignmentHorizontalSegment", StartPoint=f.create_entity(
            "IfcCartesianPoint", Coordinates=(300.0, 0.0)),
        StartDirection=0.0, StartRadiusOfCurvature=100.0,
        EndRadiusOfCurvature=100.0, SegmentLength=math.pi * 50.0,
        PredefinedType="CIRCULARARC"))
    api.add_stationing_referent(f, name="5+00", alignment=ia,
                                distance_along=0.0, station=500.0)
    st = AlignmentStationer(f, ia)
    ft = 0.3048
    assert st.station_unit == "ft"
    assert st.start_station == pytest.approx(500.0)
    assert st.length == pytest.approx((200.0 + math.pi * 50.0) * ft, rel=1e-9)
    assert not st.has_profile
    fr = st.frame_at_station(600.0)                       # on the tangent
    assert fr.point == pytest.approx((200.0 * ft, 0.0, 0.0), abs=1e-9)
    assert fr.azimuth == pytest.approx(90.0)              # heading +x
    end = st.frame(st.length)                             # end of the arc
    assert end.point[:2] == pytest.approx((400.0 * ft, 100.0 * ft), abs=1e-6)
    assert end.azimuth == pytest.approx(0.0, abs=1e-6) or \
        end.azimuth == pytest.approx(360.0, abs=1e-6)     # heading +y
    assert st.format_station(st.end_station) == "8+57.08"


def test_a_polyline_alignment_interpolates():
    f = _feet_file()
    pts = [f.create_entity("IfcCartesianPoint", Coordinates=c)
           for c in [(0.0, 0.0, 10.0), (100.0, 0.0, 12.0), (100.0, 50.0, 12.0)]]
    ia = api.create_as_polyline(f, "P", pts)
    st = AlignmentStationer(f, ia)
    ft = 0.3048
    assert st.length == pytest.approx(150.0 * ft)
    fr = st.frame(50.0 * ft)
    assert fr.point == pytest.approx((50.0 * ft, 0.0, 11.0 * ft))
    assert fr.grade == pytest.approx(0.02)
    assert st.frame(125.0 * ft).point[:2] == pytest.approx((100 * ft, 25 * ft))


@pytest.mark.parametrize("value,unit,want", [
    (1234.56, "ft", "12+34.56"), (99.996, "ft", "1+00.00"),
    (5.0, "ft", "0+05.00"), (-12.5, "ft", "-0+12.50"),
    (1234.5678, "m", "1+234.568"), (12.0, "m", "0+012.000")])
def test_format_station(value, unit, want):
    assert format_station(value, unit) == want


def test_ifc4_has_no_alignments(tmp_path):
    m, *_ = _model(schema="IFC4")
    _out, f = _emit(tmp_path, m)
    assert alignments(f) == []


def test_elevation_reads_through_the_map_conversion(emitted):
    m, al, prof, f = emitted
    st = AlignmentStationer(f, alignments(f)[0])
    fr = st.frame((1123.4 - al.s_start) * m.ctx.ft_to_m)
    elev_ft = st.elevation_m(fr.point[2]) / m.ctx.ft_to_m
    assert elev_ft == pytest.approx(prof.elev(1123.4), abs=1e-6)


def test_offsets_are_radial_and_round_trip(emitted):
    m, al, prof, f = emitted
    st = AlignmentStationer(f, alignments(f)[0])
    k = m.ctx.ft_to_m
    for s, off_ft, side in [(1050.0, 12.0, "Lt"), (1200.0, 25.0, "Rt"),
                            (1330.0, 40.0, "Lt")]:
        d = (s - al.s_start) * k
        left = off_ft * k * (1 if side == "Lt" else -1)
        p = st.point_at(d, left)
        n, e = al.station_offset(s, off_ft, side)       # bimforge's radial truth
        want = to_model(m.ctx, n, e, prof.elev(s))
        assert p[:2] == pytest.approx([c * k for c in want[:2]], abs=1e-4)
        assert p[2] == pytest.approx(st.frame(d).point[2])   # at grade
        dd, oo = st.locate(p[0], p[1])
        assert dd == pytest.approx(d, abs=1e-6)
        assert oo == pytest.approx(left, abs=1e-6)
        assert format_offset(oo) == f"{off_ft:.2f} {side}"


def test_locate_clamps_past_the_ends(emitted):
    *_, f = emitted
    st = AlignmentStationer(f, alignments(f)[0])
    fr = st.frame(0.0)
    x = fr.point[0] - fr.plan_tangent[0] * 10 + fr.left[0] * 3
    y = fr.point[1] - fr.plan_tangent[1] * 10 + fr.left[1] * 3
    d, off = st.locate(x, y)
    assert d == 0.0 and off == pytest.approx(3.0)
    assert format_offset(0.0) == "CL" and format_offset(-1.0, "m") == "1.00 Rt"


def test_locate_many_matches_locate(emitted):
    import numpy as np
    m, al, prof, f = emitted
    st = AlignmentStationer(f, alignments(f)[0])
    k = m.ctx.ft_to_m
    pts, want = [], []
    for s, off in [(1010.0, 0.0), (1100.0, 12.0), (1200.0, -25.0), (1340.0, 7.5)]:
        d = (s - al.s_start) * k
        pts.append(st.point_at(d, off * k)[:2])
        want.append((d, off * k))
    dd, oo = st.locate_many(np.array(pts))
    for (d, o), gd, go in zip(want, dd, oo):
        assert gd == pytest.approx(d, abs=2e-3)      # chord sag only
        assert go == pytest.approx(o, abs=2e-3)


def test_an_international_foot_project_keeps_its_stations():
    """A file in the international foot (0.3048 m): its native 50,000 ft
    station reads 500+00.00, not 499+99.90 through the US survey foot."""
    from bimforge.bim.alignment_station import INTL_FT_M, foot_m
    f = _feet_file()
    ia = api.create(f, "B", include_vertical=False)
    lay = api.get_horizontal_layout(ia)
    api.create_layout_segment(f, lay, f.create_entity(
        "IfcAlignmentHorizontalSegment", StartPoint=f.create_entity(
            "IfcCartesianPoint", Coordinates=(0.0, 0.0)),
        StartDirection=0.0, StartRadiusOfCurvature=0.0, EndRadiusOfCurvature=0.0,
        SegmentLength=200.0, PredefinedType="LINE"))
    api.add_stationing_referent(f, name="500+00", alignment=ia,
                                distance_along=0.0, station=50000.0)
    assert foot_m(f) == INTL_FT_M
    st = AlignmentStationer(f, ia)
    assert st.format_station(st.start_station) == "500+00.00"
    assert st.format_station(st.end_station) == "502+00.00"
    assert st.convert(st.start_station, "ft") == pytest.approx(50000.0, abs=1e-9)
    assert st.to_unit(st.frame(st.length).point[0], "ft") == pytest.approx(200.0)


def test_a_polyline_corner_keeps_each_pieces_own_tangent():
    """(0,0) -> (100,0) -> (100,50) m: a point just before the corner is on
    the INCOMING piece - 99.75 along, on the line - in bulk and singly."""
    import numpy as np
    import ifcopenshell.api
    f = ifcopenshell.file(schema="IFC4X3_ADD2")
    ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcProject")
    m = ifcopenshell.api.run("unit.add_si_unit", f, unit_type="LENGTHUNIT")
    ifcopenshell.api.run("unit.assign_unit", f, units=[m])         # metres
    ifcopenshell.api.run("context.add_context", f, context_type="Model")
    pts = [f.create_entity("IfcCartesianPoint", Coordinates=c)
           for c in [(0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (100.0, 50.0, 0.0)]]
    st = AlignmentStationer(f, api.create_as_polyline(f, "P", pts))
    d, o = st.locate_many(np.array([(99.75, 0.0), (100.0, 10.0), (50.0, 3.0),
                                    (-5.0, 2.0), (101.0, 60.0)]))
    assert d == pytest.approx([99.75, 110.0, 50.0, 0.0, 150.0], abs=1e-9)
    assert o == pytest.approx([0.0, 0.0, 3.0, 2.0, -1.0], abs=1e-9)
    assert st.locate(99.75, 0.0) == pytest.approx((99.75, 0.0), abs=1e-9)


def test_an_indexed_poly_curve_follows_its_segments():
    """The CoordList is a pool: Segments say the path. An arc piece is
    refused, not stationed as a chord."""
    import ifcopenshell.api
    f = ifcopenshell.file(schema="IFC4X3_ADD2")
    ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcProject")
    m = ifcopenshell.api.run("unit.add_si_unit", f, unit_type="LENGTHUNIT")
    ifcopenshell.api.run("unit.assign_unit", f, units=[m])
    ctx = ifcopenshell.api.run("context.add_context", f, context_type="Model")
    axis = ifcopenshell.api.run("context.add_context", f, context_type="Model",
                                context_identifier="Axis", target_view="GRAPH_VIEW",
                                parent=ctx)
    # the pool lists the corner LAST; the path is 1 -> 3 -> 2
    pool = f.create_entity("IfcCartesianPointList3D",
                           CoordList=[(0.0, 0.0, 0.0), (100.0, 50.0, 0.0),
                                      (100.0, 0.0, 0.0)])

    def alignment(segments):
        curve = f.create_entity("IfcIndexedPolyCurve", Points=pool,
                                Segments=segments)
        al = ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcAlignment",
                                  name="I")
        al.Representation = f.create_entity(
            "IfcProductDefinitionShape", Representations=[f.create_entity(
                "IfcShapeRepresentation", ContextOfItems=axis,
                RepresentationIdentifier="Axis", RepresentationType="Curve3D",
                Items=[curve])])
        return al
    lines = [f.create_entity("IfcLineIndex", (1, 3)),
             f.create_entity("IfcLineIndex", (3, 2))]
    st = AlignmentStationer(f, alignment(lines))
    assert st.length == pytest.approx(150.0)
    assert st.frame(100.0).point[:2] == pytest.approx((100.0, 0.0))
    assert st.frame(150.0).point[:2] == pytest.approx((100.0, 50.0))
    arc = [f.create_entity("IfcArcIndex", (1, 3, 2))]
    with pytest.raises(NotImplementedError, match="IfcArcIndex"):
        AlignmentStationer(f, alignment(arc))
