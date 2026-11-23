"""road-corridor V1.2 part C: the family builds a shared-use path beside
the road (P.6)."""
import contextlib
import copy
import io
import uuid

import pytest

from bimforge.author.project import ProjectContext

N0, E0 = 1943000.0, 6594000.0
SECTION = {
    "components": [{"name": "lane", "kind": "carriageway", "width": 12.0},
                   {"name": "shoulder", "kind": "shoulder", "width": 5.0,
                    "slope": -0.05}],
    "courses": [{"name": "HMA", "type": "PAVEMENT", "thickness": 0.4},
                {"name": "AB", "type": "CORE", "thickness": 1.0}],
    "side_slopes": {"cut": {"ratio": 2.0, "ditch": {"width": 4.0, "depth": 1.5}},
                    "fill": {"ratio": 2.0}, "daylight_limit_ft": 150}}


def grade(elev, pct, s0=1000.0, s1=1600.0):
    return {"curves": [{"bvc_station": s0, "bvc_elev": elev, "g_in_pct": pct,
                        "g_out_pct": pct, "length_ft": s1 - s0, "evc_station": s1,
                        "evc_elev": round(elev + pct / 100.0 * (s1 - s0), 5)}]}


PATH = {"side": "R",
        "separation": [[1000, 10.0], [1200, 10.0], [1300, 1.5], [1350, 1.5],
                       [1450, 10.0]],
        "width": 12.0,
        "courses": [{"name": "PATH-HMA", "type": "PAVEMENT", "thickness": 0.25},
                    {"name": "PATH-AB", "type": "CORE", "thickness": 0.5}],
        # on the deck's line at 13+00 and 13+50 (the module docstring)
        "profile": grade(299.48002, 1.0)}
PARAMS = {
    "alignment": {"name": "ML", "pob": {"station": 1000.0, "northing": N0,
                                        "easting": E0},
                  "run": [{"kind": "tangent", "bearing": "N 0-0-0 E",
                           "length": 600.0}]},
    "profile": grade(300.0, 1.0),
    "ground": {"source": "plane", "elevation": 296.0, "slope_e": -0.02},
    "section": SECTION,
    "gaps": [{"from": 1300, "to": 1350, "kind": "structure"}],
    "stations": {"interval": 25, "band": 100},
    "mass_haul": {"shrink": 0.1, "swell": 0.2},
    "path": PATH,
}
CTX = ProjectContext(name="rcp", epsg=2226, base_e=E0, base_n=N0, base_h=300.0,
                     guid_ns=uuid.UUID(int=11))


def build(params, log=None):
    from bimforge.author.families.road_corridor import build as _build
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        m = _build(copy.deepcopy(params), CTX)
    if log is not None:
        log.append(err.getvalue())
    return m


@pytest.fixture(scope="module")
def built():
    log = []
    return build(PARAMS, log), log[0]


def path_courses(m):
    return [e for e in m.elements if e.ifc_class == "IfcCourse" and " path STA " in e.name]


def test_one_path_course_per_course_and_band(built):
    m, _log = built
    names = sorted(e.name for e in path_courses(m))
    bands = ["10+00.00 to 11+00.00", "11+00.00 to 12+00.00", "12+00.00 to 13+00.00",
             "13+50.00 to 14+00.00", "14+00.00 to 15+00.00", "15+00.00 to 16+00.00"]
    assert names == sorted(f"{c} path STA {b}" for c in ("PATH-HMA", "PATH-AB")
                           for b in bands)
    for el in path_courses(m):
        assert el.spatial_part.predefined_type == "SHAREDUSEPATH"
        assert el.spatial_part.parent.predefined_type == "ROADSEGMENT"
        (lf,) = el.geometry
        assert lf.s1 <= 1300.0 + 1e-6 or lf.s0 >= 1350.0 - 1e-6, el.name


def test_a_constant_band_is_its_path_box(built):
    m, _log = built
    el = m.element("PATH-HMA path STA 10+00.00 to 11+00.00")
    assert el.quantities["volume_cf"] == pytest.approx(
        12.0 * 0.25 * 100.0 * (1.0 + 0.01 ** 2) ** 0.5, rel=1e-9)
    vol = el.standard_qto["Qto_CourseBaseQuantities"]["Volume"]
    assert vol[2] == "PathLength * Width * Thickness"
    assert el.dimensions["Width"] == pytest.approx(12.0)
    # the centre of the paved width: 17 + 10 + 6 ft right
    assert el.dimensions["Offset"] == pytest.approx(-33.0, abs=0.01)


def test_a_band_with_a_separation_kink_withholds_its_formula_and_says_so(built):
    m, log = built
    el = m.element("PATH-AB path STA 12+00.00 to 13+00.00")
    assert len(el.standard_qto["Qto_CourseBaseQuantities"]["Volume"]) == 2
    assert ("road-corridor: PATH-AB path STA 12+00.00 to 13+00.00: Volume formula "
            "withheld") in log


def test_every_course_meets_its_stated_volume_and_the_earthwork_is_closed(built):
    from bimforge.author.gate import check_stated_quantities
    m, _log = built
    assert check_stated_quantities(m) == []
    from collections import Counter
    for el in m.elements:
        if not el.ifc_class.startswith("IfcEarthworks"):
            continue
        for g in el.geometry:
            (d,) = g.body_solids()
            directed = Counter((a, b) for t in d["tris"] for a, b in zip(t, t[1:] + t[:1]))
            assert all(n == 1 and directed[b, a] == 1
                       for (a, b), n in directed.items()), el.name


def test_the_ground_reaches_past_the_path():
    from bimforge.author.alignment import Alignment, Profile
    from bimforge.author.corridor.params import parse
    from bimforge.author.families.road_corridor import ground_reach
    al_p = PARAMS["alignment"]
    al = Alignment(al_p["pob"], al_p["run"])
    prof = Profile(PARAMS["profile"]["curves"])
    c = parse(copy.deepcopy(PARAMS), al.s_start, al.s_end, alignment=al, profile=prof)
    # 17 ft to the edge, 10 ft out, 12 paved, two 2 ft shoulders, then the
    # 150 ft daylight limit
    assert ground_reach(c) == pytest.approx(17.0 + 10.0 + 12.0 + 4.0 + 150.0)


def test_a_right_side_path_s_courses_build_whichever_way_their_rings_wind(built):
    # course_rings winds a right path's rings counterclockwise and a left
    # one's clockwise; StationLoft winds every loft counterclockwise, so
    # pappus and centroid_path find area on either side
    from bimforge.author.alignment import Alignment, Profile
    from bimforge.author.corridor.params import parse
    from bimforge.author.corridor.path import course_rings, surface
    from bimforge.author.primitives import _signed_area2
    m, _log = built
    al_p = PARAMS["alignment"]
    al = Alignment(al_p["pob"], al_p["run"])
    prof = Profile(PARAMS["profile"]["curves"])
    sides = {}
    for side in ("R", "L"):
        params = copy.deepcopy(PARAMS)
        params["path"]["side"] = side
        c = parse(params, al.s_start, al.s_end, alignment=al, profile=prof)
        sides[side] = _signed_area2(course_rings(c.path, surface(c, 1050.0))[0])
    assert sides["R"] > 0.0 > sides["L"]
    for el in path_courses(m):
        (lf,) = el.geometry
        assert all(_signed_area2(r) > 0.0 for r in lf.rings), el.name
        assert el.quantities["volume_cf"] > 0.0


# -- a curve's ends: the path's courses split at its PC and PT -------------------

#: a 100 ft left curve of radius 500 from 11+25 (its PC) to 12+25 (its PT),
#: stationed at its length (500 x 0.2 rad), inside 50 ft bands; the road at
#: 7 %, the path on the left (inside the curve) at 3 % from 10+75 to 12+75,
#: 15 ft out
CURVE = copy.deepcopy(PARAMS)
CURVE.update({
    "alignment": {"name": "ML", "pob": {"station": 1000.0, "northing": N0,
                                        "easting": E0},
                  "run": [{"kind": "tangent", "bearing": "N 0-0-0 E", "length": 125.0},
                          {"kind": "curve", "delta": "11-27-32.961249419",
                           "radius": 500.0, "turn": "L", "length": 100.0},
                          {"kind": "tangent", "bearing": "N 11-27-32.961249419 W",
                           "length": 125.0}]},
    "profile": grade(300.0, 7.0, 1000.0, 1350.0),
    "ground": {"source": "plane", "elevation": 298.0, "slope_n": 0.07},
    "gaps": [],
    "stations": {"interval": 25, "band": 50},
    "path": {"side": "L", "stations": [1075, 1275], "separation": [[1000, 15.0]],
             "width": 12.0, "courses": PATH["courses"],
             # level with the road's edge of shoulder at 11+75
             "profile": grade(308.76, 3.0, 1075.0, 1275.0)}})


@pytest.fixture(scope="module")
def curve_built():
    log = []
    return build(CURVE, log), log[0]


def _box_miss(lofts, thickness):
    """(the Volume entry course_volume writes, |box - volume| / volume)."""
    from bimforge.author.corridor import dimensions as dims
    from bimforge.author.corridor.loft import centroid_path
    got = centroid_path(lofts)
    _shape, volume = dims.course_volume(got.volume_cf, got.path_ft,
                                        lofts[0].widths_ft, thickness)
    width = lofts[0].widths_ft[0]
    return volume, abs(got.path_ft * width * thickness - got.volume_cf) / got.volume_cf


def test_the_curve_s_pc_and_pt_end_the_path_s_bands_and_each_holds_its_formula(
        curve_built):
    from bimforge.author.gate import FORMULA_TOLERANCE, check_stated_quantities
    m, log = curve_built
    bands = ["10+75.00 to 11+00.00", "11+00.00 to 11+25.00", "11+25.00 to 11+50.00",
             "11+50.00 to 12+00.00", "12+00.00 to 12+25.00", "12+25.00 to 12+50.00",
             "12+50.00 to 12+75.00"]
    assert sorted(e.name for e in path_courses(m)) == sorted(
        f"{c} path STA {b}" for c in ("PATH-HMA", "PATH-AB") for b in bands)
    for el in path_courses(m):
        vol = el.standard_qto["Qto_CourseBaseQuantities"]["Volume"]
        assert vol[2] == "PathLength * Width * Thickness", el.name
        box = el.dimensions["PathLength"] * el.dimensions["Width"] * el.dimensions[
            "Thickness"]
        assert abs(box - vol[1]) <= FORMULA_TOLERANCE * vol[1], el.name
    assert "withheld" not in log
    assert check_stated_quantities(m) == []


def test_without_the_split_or_one_sided_rings_the_curve_s_ends_miss(curve_built):
    # the same courses lofted as one band across the PC, its ring at the PC
    # the section's own (a chord across the PC, a step section_v solves on
    # each side): 2.8e-4 off, so the formula would be withheld. Split there
    # but with that ring kept, the curve's side still misses
    from bimforge.author.alignment import Alignment, Profile
    from bimforge.author.corridor.loft import StationLoft
    from bimforge.author.corridor.params import parse
    from bimforge.author.corridor.path import course_rings, surface
    from bimforge.author.gate import FORMULA_TOLERANCE
    from bimforge.author.primitives import _signed_area2
    m, _log = curve_built
    al_p = CURVE["alignment"]
    al = Alignment(al_p["pob"], al_p["run"], name="ML")
    prof = Profile(CURVE["profile"]["curves"])
    c = parse(copy.deepcopy(CURVE), al.s_start, al.s_end, alignment=al, profile=prof)
    for k, name in enumerate(("PATH-HMA", "PATH-AB")):
        thickness = c.path.courses[k].thickness
        (a,) = m.element(f"{name} path STA 11+00.00 to 11+25.00").geometry
        (b,) = m.element(f"{name} path STA 11+25.00 to 11+50.00").geometry
        both = course_rings(c.path, surface(c, 1125.0))[k]
        # wound as the lofts wind theirs (StationLoft: counterclockwise)
        both = both[::-1] if _signed_area2(both) < 0.0 else both
        whole = StationLoft("whole", al, prof, None, a.stations + b.stations[1:],
                            a.rings[:-1] + [both] + b.rings[1:])
        volume, miss = _box_miss([whole], thickness)
        assert len(volume) == 2 and miss > 1e-4
        half = StationLoft("half", al, prof, None, b.stations, [both] + b.rings[1:])
        volume, miss = _box_miss([half], thickness)
        assert len(volume) == 2 and miss > 10 * FORMULA_TOLERANCE
        # and the family's own, one-sided, hold
        for lf in (a, b):
            assert _box_miss([lf], thickness)[1] <= FORMULA_TOLERANCE


def test_path_runs_cut_at_a_segment_end_and_refuse_one_with_no_section():
    from types import SimpleNamespace

    from bimforge.author.families.road_corridor import path_runs

    def secs(*has):
        return [SimpleNamespace(s=1000.0 + 25.0 * i, path=object() if h else None)
                for i, h in enumerate(has)]

    assert path_runs(secs(1, 1, 1, 1, 1)) == [(0, 4)]
    assert path_runs(secs(1, 1, 1, 1, 1), [1050.0]) == [(0, 2), (2, 4)]
    # a break at a stretch's end, or where the path is not, cuts nothing
    assert path_runs(secs(1, 1, 1, 0, 0), [1050.0]) == [(0, 2)]
    assert path_runs(secs(0, 0, 1, 1, 1), [1050.0]) == [(2, 4)]
    assert path_runs(secs(0, 1, 1, 0, 1, 1)) == [(1, 2), (4, 5)]
    with pytest.raises(ValueError, match=r"segment end at 10\+40.00 is no section"):
        path_runs(secs(1, 1, 1), [1040.0])


def test_only_a_step_in_curvature_is_a_break():
    from bimforge.author.alignment import Alignment
    from bimforge.author.families.road_corridor import at_break, curvature_steps
    pob = {"station": 1000.0, "northing": 0.0, "easting": 0.0}
    arc = {"kind": "curve", "delta": "5-43-46.480624710", "radius": 500.0,
           "turn": "L", "length": 50.0}
    al = Alignment(pob, [{"kind": "tangent", "bearing": "N 0-0-0 E", "length": 100.0},
                         {"kind": "tangent", "bearing": "N 0-0-0 E", "length": 100.0},
                         arc, dict(arc),
                         dict(arc, radius=1000.0, delta="2-51-53.240312355")])
    # two tangents meet at 11+00, two like arcs at 12+50: no step there
    assert al.seg_breaks(1000.0, 1350.0) == [1100.0, 1200.0, 1250.0, 1300.0]
    assert curvature_steps(al, 1000.0, 1350.0) == [1200.0, 1300.0]
    assert [at_break(al, s) for s in (1100.0, 1200.0, 1250.0, 1300.0)] == [
        False, True, False, True]


def test_the_one_sided_tangent_refuses_a_stencil_across_a_segment_end():
    from bimforge.author.alignment import Alignment, Profile
    from bimforge.author.corridor.params import parse
    from bimforge.author.corridor.path import cos_theta
    al_p = CURVE["alignment"]
    al = Alignment(al_p["pob"], al_p["run"], name="ML")
    prof = Profile(CURVE["profile"]["curves"])
    c = parse(copy.deepcopy(CURVE), al.s_start, al.s_end, alignment=al, profile=prof)
    cos_theta(c, 1125.0, toward=1.0)
    cos_theta(c, 1124.98, toward=-1.0)
    with pytest.raises(ValueError, match=r"11\+24.99.*reaches past a segment end"):
        cos_theta(c, 1124.99, toward=1.0)


def curves(elev, rows):
    """A profile of 100 ft curves from 10+00, one per (g_in, g_out) row."""
    out, s, z = [], 1000.0, elev
    for g1, g2 in rows:
        z1 = z + g1 / 100.0 * 100.0 + (g2 - g1) / 100.0 * 100.0 / 2.0
        out.append({"bvc_station": s, "bvc_elev": round(z, 5), "g_in_pct": g1,
                    "g_out_pct": g2, "length_ft": 100.0, "evc_station": s + 100.0,
                    "evc_elev": round(z1, 5)})
        s, z = s + 100.0, z1
    return {"curves": out}


#: 7.5 ft above the road from 12+00 to 13+00 (309.48 against 302.0)
UP = curves(299.48002, [(1, 9), (9, 1), (1, 1), (1, -7), (-7, 1), (1, 1)])
#: 8.5 ft below it (293.48 against 302.0)
DIP = curves(299.48002, [(1, -7), (-7, 1), (1, 1), (1, 9), (9, 1), (1, 1)])


def wall_params(profile, **over):
    p = copy.deepcopy(PARAMS)
    p.update(walls="auto", gaps=[], **over)
    p["path"] = dict(copy.deepcopy(PATH), separation=[[1000, 10.0]], profile=profile)
    return p


def test_a_path_above_the_road_takes_a_strip_wall_and_its_rail():
    from bimforge.author.corridor import dimensions as dims
    m = build(wall_params(UP))
    (rail,) = [e for e in m.elements if e.ifc_class == "IfcRailing"
               and e.name.startswith("Path rail ")]
    assert rail.name.startswith("Path rail R STA 10+8")
    assert (rail.predefined_type, rail.type_name, rail.family_class) == (
        "GUARDRAIL", "Path rail", dims.PATH_RAIL)
    assert rail.dimensions["RailHeight"] == pytest.approx(3.5)
    length = rail.dimensions["EndStation"] - rail.dimensions["StartStation"]
    assert rail.standard_qto["Qto_RailingBaseQuantities"]["Length"] == (
        "length", pytest.approx(length), dims.LENGTH)
    assert rail.psets["BIMForge_Guardrail"]["RailHeight"] == ("length", pytest.approx(3.5))
    assert rail.spatial_part.predefined_type == "SHAREDUSEPATH"
    assert 320.0 < length < 345.0                      # about 10+83 to 14+17


def test_the_path_s_road_part_and_rail_pass_the_schema(tmp_path):
    import ifcopenshell
    import yaml

    from bimforge.author.families.registry import build_from_spec
    from bimforge.author.gate import schema_issues
    paycodes = ("rules:\n  - {match: \"(?i)^(HMA|AB) \", group: rc_pave}\n"
                "groups:\n  rc_pave: {measure: GrossVolume}\n"
                "codes:\n  RC-PAVE: {group: rc_pave, measure: GrossVolume, unit: CY,\n"
                "            item_number: \"0001\", description: \"Pavement\"}\n")
    (tmp_path / "rc.paycodes.yaml").write_text(paycodes, "utf-8")
    spec = {"family": "road-corridor", "params": wall_params(UP),
            "paycodes": "./rc.paycodes.yaml", "outputs": {"ifc": "out/rc.ifc"},
            "project": {"name": "Path fixture", "epsg": 2226,
                        "base": [E0, N0, 300.0], "guid_ns": str(uuid.UUID(int=11)),
                        "schema": "IFC4X3_ADD2", "facility": {"kind": "road"}}}
    path = tmp_path / "rc.spec.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False), "utf-8")
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        assert build_from_spec(str(path)) == 0, err.getvalue()[-2000:]
    f = ifcopenshell.open(str(tmp_path / "out" / "rc.ifc"))
    assert not schema_issues(f)
    parts = [p for p in f.by_type("IfcRoadPart") if p.ObjectType == "SHAREDUSEPATH"]
    assert parts and all(p.PredefinedType == "USERDEFINED" for p in parts)
    for part in parts:
        refs = [r.RelatingClassification for r in part.HasAssociations
                if r.is_a("IfcRelAssociatesClassification")]
        assert [r.Identification for r in refs] == ["road-corridor-shared-use-path"]
    (rail,) = [r for r in f.by_type("IfcRailing") if r.Name.startswith("Path rail ")]
    import ifcopenshell.util.element as E
    assert E.get_type(rail).Name == "Path rail"
    assert E.get_predefined_type(rail) == "GUARDRAIL"


def path_rails(m):
    return [e for e in m.elements if e.name.startswith("Path rail ")]


def test_a_path_below_the_road_takes_no_path_rail():
    assert path_rails(build(wall_params(DIP))) == []


def test_a_path_fill_wall_takes_a_rail_at_the_path_s_outer_edge():
    p = wall_params(UP)
    p["section"] = copy.deepcopy(SECTION)
    p["section"]["side_slopes"]["daylight_limit_ft"] = 30
    rails = {e.name: e for e in path_rails(build(p))}
    assert set(rails) == {"Path rail R STA 10+83.00 to 14+17.00",
                          "Path rail R STA 12+44.00 to 13+52.00"}
    strip = rails["Path rail R STA 10+83.00 to 14+17.00"]
    outer = rails["Path rail R STA 12+44.00 to 13+52.00"]
    # the strip wall's rail stands at q; the fill wall's at o, a path's
    # width (12 ft) and its shoulders farther out (u is negative to the right)
    base = lambda e: abs(e.geometry[0].rings[0][0][0])
    assert base(outer) > base(strip) + 12.0
    assert outer.spatial_part.predefined_type == "SHAREDUSEPATH"
