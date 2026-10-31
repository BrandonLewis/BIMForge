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
    AlignmentStationer, alignments, format_station, station_unit)


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
