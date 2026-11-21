"""StationLoft and the corridor frame (P.6)."""
import pytest

from bimforge.author.alignment import Alignment, Profile
from bimforge.author.corridor.frame import densify, survey_point
from bimforge.author.corridor.loft import StationLoft
from bimforge.author.primitives import exact_of
from bimforge.author.sweep import MAX_ARC_STEP_RAD

POB = {"station": 0.0, "northing": 0.0, "easting": 0.0}
RECT = [(5.0, 0.0), (-5.0, 0.0), (-5.0, -1.0), (5.0, -1.0)]


def line(length=100.0):
    return Alignment(POB, [{"kind": "tangent", "bearing": "N 0-0-0 E",
                            "length": length}], name="T")


def curve():
    """10 ft tangent, a 100 ft right curve of radius 500, 10 ft tangent."""
    return Alignment(POB, [
        {"kind": "tangent", "bearing": "N 0-0-0 E", "length": 10.0},
        {"kind": "curve", "delta": "11-27-33", "radius": 500.0, "turn": "R",
         "length": 100.0},
        {"kind": "tangent", "bearing": "N 11-27-33 E", "length": 10.0}], name="C")


def level(elev=100.0, length=120.0, grade_pct=0.0):
    return Profile([{"bvc_station": 0.0, "bvc_elev": elev, "g_in_pct": grade_pct,
                     "g_out_pct": grade_pct, "length_ft": length,
                     "evc_station": length,
                     "evc_elev": elev + grade_pct / 100.0 * length}])


def test_a_section_point_sits_left_and_below_on_a_level_tangent():
    assert survey_point(line(), level(), 50.0, 5.0, -1.0) == pytest.approx(
        (50.0, -5.0, 99.0))


def test_densify_keeps_chords_on_the_curve():
    al = curve()
    got = densify(al, level(), [0.0, 10.0, 110.0, 120.0])
    steps = [b - a for a, b in zip(got, got[1:])]
    assert got[0] == 0.0 and got[-1] == 120.0
    assert max(steps[1:-1]) <= MAX_ARC_STEP_RAD * 500.0 + 1e-9
    assert len(got) > 4


def test_a_straight_loft_is_its_prism():
    lf = StationLoft("slab", line(), level(), None, [0.0, 50.0, 100.0], [RECT] * 3)
    assert lf.volume_cf == pytest.approx(1000.0, rel=1e-9)
    assert lf.average_end_area_cf == pytest.approx(1000.0, rel=1e-9)
    assert lf.mean_width_ft == pytest.approx(10.0)
    assert lf.length_ft == 100.0


def test_a_curved_loft_agrees_with_its_curvature_corrected_end_areas():
    al, prof = curve(), level()
    ring = [(12.0, 0.0), (2.0, 0.0), (2.0, -1.0), (12.0, -1.0)]   # left of the line
    ss = densify(al, prof, [0.0, 10.0, 110.0, 120.0])
    lf = StationLoft("outer", al, prof, None, ss, [ring] * len(ss))
    assert lf.volume_cf > 1210.0            # the outside of a right curve is longer
    assert lf.volume_cf == pytest.approx(lf.average_end_area_cf, rel=1e-3)


def test_grade_lengthens_the_loft():
    lf = StationLoft("slab", line(), level(grade_pct=6.0), None, [0.0, 100.0], [RECT] * 2)
    assert lf.average_end_area_cf == pytest.approx(1000.0 * (1 + 0.06 ** 2) ** 0.5)
    assert lf.volume_cf == pytest.approx(lf.average_end_area_cf, rel=1e-6)


def test_its_exact_form_is_one_section_per_station():
    ss = [0.0, 50.0, 100.0]
    lf = StationLoft("slab", line(), level(), None, ss, [RECT] * 3, ifc="IfcCourse")
    d = lf.body_solids()[0]
    ex = exact_of(d)
    assert ex is not None and ex["kind"] == "sectioned"
    assert [sec["s"] for sec in ex["sections"]] == ss
    d["verts"][0] = (d["verts"][0][0] + 1.0,) + tuple(d["verts"][0][1:])
    assert exact_of(d) is None              # an edited mesh is written as itself


@pytest.mark.parametrize("stations, rings, match", [
    ([0.0], [RECT], "one ring per station"),
    ([0.0, 0.0], [RECT, RECT], "strictly ascending"),
    ([0.0, 10.0], [RECT, RECT[:3]], "same vertex count"),
    ([0.0, 10.0], [RECT, RECT[::-1]], "wind the same way"),
])
def test_bad_lofts_are_refused(stations, rings, match):
    with pytest.raises(ValueError, match=match):
        StationLoft("x", line(), level(), None, stations, rings)


# ---------------------------------------------------- the gate's interface
# gate._ifc_exact_sweep_check holds a drawn IfcSectionedSolidHorizontal to
# the loft it came from: these are the four legs it measures with.

def _ring(s, grow=0.0):
    """Left of the line, widening 0.02 ft per foot of station."""
    w = 12.0 + 0.02 * s
    return [(w + grow, 0.0), (2.0 - grow, 0.0), (2.0 - grow, -1.0),
            (w + grow, -1.0)]


def _lofts():
    al, prof = curve(), level()
    ss = densify(al, prof, [0.0, 10.0, 110.0, 120.0])
    return [StationLoft("slab", line(), level(), None, [0.0, 50.0, 100.0],
                        [RECT] * 3),
            StationLoft("outer", al, prof, None, ss, [_ring(s) for s in ss])]


def _ring_points(lf):
    """Every ring vertex at every station: the loft's mesh, less the fan
    centres, which sit a chord's sag inside the surface."""
    return [p for i in range(len(lf.stations)) for p in lf._world(i)]


@pytest.mark.parametrize("i", [0, 1])
def test_its_own_mesh_lies_on_its_surface_and_spans_its_stations(i):
    lf = _lofts()[i]
    res, lo, hi = lf.surface_residual_ft(_ring_points(lf))
    assert res == pytest.approx(0.0, abs=1e-6)
    assert lo == pytest.approx(lf.s0, abs=1e-6)
    assert hi == pytest.approx(lf.s1, abs=1e-6)


@pytest.mark.parametrize("i", [0, 1])
def test_a_mesh_pushed_out_strays_by_the_push(i):
    lf = _lofts()[i]
    grown = [[(u + (0.1 if u > 0 else -0.1), v) for u, v in r] for r in lf.rings]
    if i == 1:
        grown = [_ring(s, grow=0.1) for s in lf.stations]
    big = StationLoft("big", lf.alignment, lf.profile, None, lf.stations, grown)
    res, _lo, _hi = lf.surface_residual_ft(_ring_points(big))
    assert res == pytest.approx(0.1, abs=1e-6)


@pytest.mark.parametrize("i", [0, 1])
def test_its_own_caps_sit_in_their_end_sections(i):
    lf = _lofts()[i]
    d = lf.body_solids()[0]
    assert lf.cap_station_error_ft(d["verts"], d["tris"]) == pytest.approx(
        0.0, abs=1e-6)


def test_a_leaned_end_cap_is_seen():
    lf = _lofts()[0]
    d = lf.body_solids()[0]
    # shear the far cap along travel (+y, north) by 0.04 ft per foot left
    verts = [(x, y + 0.04 * -x, z) if abs(y - lf.s1) < 1e-9 else (x, y, z)
             for x, y, z in d["verts"]]
    assert lf.cap_station_error_ft(verts, d["tris"]) == pytest.approx(0.2,
                                                                      abs=1e-6)


@pytest.mark.parametrize("i", [0, 1])
def test_its_wall_area_is_its_own_and_a_missing_wall_shows(i):
    lf = _lofts()[i]
    d = lf.body_solids()[0]
    want = lf.wall_area_sf(d["verts"], d["tris"])
    assert want > 0.0
    assert lf.wall_area_sf(d["verts"], d["tris"]) == want
    # drop the top surface (v = 0, at elevation 100)
    tris = [t for t in d["tris"]
            if not all(abs(d["verts"][j][2] - 100.0) < 1e-9 for j in t)]
    assert lf.wall_area_sf(d["verts"], tris) < 0.9 * want


def test_a_drawn_loft_passes_the_exact_sweep_check(tmp_path):
    pytest.importorskip("ifcopenshell")
    import uuid

    from bimforge.author import gate
    from bimforge.author.emit_ifc import emit_ifc
    from bimforge.author.model import Element, StructureModel
    from bimforge.author.project import ProjectContext
    ctx = ProjectContext(name="Loft Fixture", schema="IFC4X3_ADD2", epsg=2226,
                         base_e=0.0, base_n=0.0, base_h=0.0,
                         guid_ns=uuid.UUID(int=6004))
    al = curve()
    prof = Profile([{"bvc_station": 20.0, "bvc_elev": 100.0, "g_in_pct": 3.0,
                     "g_out_pct": -2.0, "length_ft": 80.0, "evc_station": 100.0,
                     "evc_elev": 100.0 + 2.4 - 0.05 / 160.0 * 80.0 ** 2}])
    ss = densify(al, prof, [0.0, 10.0, 20.0, 100.0, 110.0, 120.0])
    lf = StationLoft("course", al, prof, ctx, ss, [_ring(s) for s in ss],
                     ifc="IfcCourse")
    m = StructureModel("loft", ctx)
    m.add(Element.from_geometry("course", lf, ifc_class="IfcCourse",
                                quantities={"volume_cf": lf.volume_cf}))
    out = tmp_path / "loft.ifc"
    emit_ifc(m, str(out))
    assert gate._exact_sweep_names(out) == {"course"}
    assert gate._ifc_exact_sweep_check(m, out) == []
